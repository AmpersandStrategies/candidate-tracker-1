"""FastAPI routes for Candidate Tracker"""
from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime
from app.db.client import db
import os
import httpx
import asyncio

router = APIRouter()

@router.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "2.1.0",
        "timestamp": datetime.now().isoformat()
    }

@router.get("/database-stats")
async def get_database_stats():
    """Get overview statistics of the database"""
    try:
        # Total candidates
        candidates_result = db.supabase.table('candidates').select('candidate_id', count='exact').execute()
        total_candidates = candidates_result.count
        
        # Total filings
        filings_result = db.supabase.table('filings').select('filing_id', count='exact').execute()
        total_filings = filings_result.count
        
        # Candidates with committees
        with_committees = db.supabase.table('candidates')\
            .select('candidate_id', count='exact')\
            .not_.is_('committee_id', 'null')\
            .execute()
        candidates_with_committees = with_committees.count
        
        # Candidates needing enrichment (no committee_id)
        needing_enrichment = db.supabase.table('candidates')\
            .select('candidate_id', count='exact')\
            .is_('committee_id', 'null')\
            .execute()
        candidates_needing_enrichment = needing_enrichment.count
        
        # Candidates with occupation
        with_occupation = db.supabase.table('candidates')\
            .select('candidate_id', count='exact')\
            .not_.is_('occupation', 'null')\
            .execute()
        candidates_with_occupation = with_occupation.count
        
        # Viability distribution
        viability_dist = {
            "high": 0,
            "medium": 0,
            "low": 0
        }
        
        viability_result = db.supabase.table('candidates')\
            .select('viability_bucket')\
            .not_.is_('viability_bucket', 'null')\
            .execute()
        
        for candidate in viability_result.data:
            bucket = candidate.get('viability_bucket', '').upper()
            if bucket in viability_dist:
                viability_dist[bucket] += 1
        
        return {
            "total_candidates": total_candidates,
            "total_filings": total_filings,
            "candidates_with_committees": candidates_with_committees,
            "candidates_needing_enrichment": candidates_needing_enrichment,
            "candidates_with_occupation": candidates_with_occupation,
            "viability_distribution": viability_dist
        }
    except Exception as e:
        return {"error": str(e)}

@router.get("/collect-candidates")
async def collect_candidates():
    """
    Collect basic candidate information from FEC API.
    Fast collection - no committee/financial data (no rate limits).
    """
    api_key = os.environ.get('FEC_API_KEY')
    if not api_key:
        return {"error": "FEC_API_KEY not found"}
    
    cycles = [2026, 2028]
    parties = ["DEM"]
    offices = ["H", "S"]  # House and Senate only (no Presidential)
    
    total_found = 0
    total_stored = 0
    collection_summary = []
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        for cycle in cycles:
            for office in offices:
                for party in parties:
                    page = 1
                    cycle_found = 0
                    cycle_stored = 0
                    consecutive_empty_pages = 0
                    
                    while consecutive_empty_pages < 2:  # Stop after 2 empty pages
                        try:
                            # Get candidates from FEC
                            fec_url = f"https://api.open.fec.gov/v1/candidates/?api_key={api_key}&election_year={cycle}&office={office}&party={party}&page={page}&per_page=100"
                            response = await client.get(fec_url)
                            
                            if response.status_code != 200:
                                print(f"FEC API error: {response.status_code}")
                                break
                            
                            data = response.json()
                            results = data.get('results', [])
                            
                            if not results:
                                consecutive_empty_pages += 1
                                page += 1
                                continue
                            
                            consecutive_empty_pages = 0
                            cycle_found += len(results)
                            
                            # Store candidates
                            for candidate in results:
                                try:
                                    # Check if candidate already exists
                                    existing = db.supabase.table('candidates')\
                                        .select('candidate_id')\
                                        .eq('source_candidate_ID', candidate.get('candidate_id'))\
                                        .execute()
                                    
                                    if existing.data:
                                        continue  # Skip duplicates
                                    
                                    # Parse name
                                    full_name = candidate.get('name', '')
                                    name_parts = full_name.split(',', 1)
                                    last_name = name_parts[0].strip() if name_parts else full_name
                                    first_name = name_parts[1].strip() if len(name_parts) > 1 else ''
                                    
                                    # Create candidate record
                                    candidate_data = {
                                        'source_candidate_ID': candidate.get('candidate_id'),
                                        'full_name': full_name,
                                        'first_name': first_name,
                                        'last_name': last_name,
                                        'party': candidate.get('party'),
                                        'office': candidate.get('office_full'),
                                        'state': candidate.get('state'),
                                        'district': candidate.get('district'),
                                        'election_cycle': cycle,
                                        'incumbent': candidate.get('incumbent_challenge') == 'I',
                                        'status': candidate.get('candidate_status'),
                                        'jurisdiction_name': f"{candidate.get('state')} {candidate.get('office')}",
                                        'source_system': 'FEC'
                                    }
                                    
                                    db.supabase.table('candidates').insert(candidate_data).execute()
                                    cycle_stored += 1
                                    
                                except Exception as e:
                                    print(f"Error storing candidate: {e}")
                                    continue
                            
                            page += 1
                            await asyncio.sleep(0.5)  # Small delay between pages
                            
                        except Exception as e:
                            print(f"Error fetching page {page}: {e}")
                            break
                    
                    total_found += cycle_found
                    total_stored += cycle_stored
                    
                    collection_summary.append({
                        "cycle": cycle,
                        "office": office,
                        "party": party,
                        "candidates_found": cycle_found,
                        "candidates_stored": cycle_stored
                    })
    
    return {
        "status": "success",
        "cycles_collected": cycles,
        "parties": parties,
        "offices": offices,
        "total_candidates_found": total_found,
        "total_candidates_stored": total_stored,
        "collection_summary": collection_summary,
        "message": f"Successfully collected {total_stored} candidates"
    }

@router.get("/enrich-financial-data")
async def enrich_financial_data(
    batch_size: int = Query(25, ge=1, le=100),
    start_offset: int = Query(0, ge=0)
):
    """
    Enrich candidates with committee and financial data.
    FIXED: Uses fixed UUID list instead of offset pagination.
    """
    api_key = os.environ.get('FEC_API_KEY')
    if not api_key:
        return {"error": "FEC_API_KEY not found"}
    
    # Get ALL candidate UUIDs that need enrichment (ONCE, at the start)
    try:
        candidates_result = db.supabase.table('candidates')\
            .select('candidate_id, source_candidate_ID')\
            .is_('committee_id', 'null')\
            .execute()
        
        all_candidates = candidates_result.data
        
        if not all_candidates:
            return {
                "status": "completed",
                "message": "All candidates already enriched",
                "total_candidates": 0,
                "enriched_with_committee": 0,
                "filings_created": 0
            }
        
        # Process only the batch requested from the FIXED list
        batch = all_candidates[start_offset:start_offset + batch_size]
        
        if not batch:
            return {
                "status": "completed",
                "message": "Batch offset beyond available candidates",
                "total_candidates": len(all_candidates),
                "enriched_with_committee": 0,
                "filings_created": 0,
                "estimated_remaining": 0
            }
        
    except Exception as e:
        return {"error": f"Failed to get candidates: {str(e)}"}
    
    enriched_count = 0
    filings_count = 0
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        for candidate in batch:
            candidate_uuid = candidate['candidate_id']
            fec_candidate_id = candidate['source_candidate_ID']
            
            try:
                # Get committee data
                committee_url = f"https://api.open.fec.gov/v1/candidates/{fec_candidate_id}/committees/?api_key={api_key}"
                
                # Handle 429 rate limits with retry
                max_retries = 3
                for attempt in range(max_retries):
                    committee_response = await client.get(committee_url)
                    
                    if committee_response.status_code == 429:
                        if attempt < max_retries - 1:
                            await asyncio.sleep(60)  # Wait 60 seconds
                            continue
                        else:
                            print(f"Rate limited after {max_retries} attempts for {fec_candidate_id}")
                            break
                    
                    if committee_response.status_code == 200:
                        break
                
                if committee_response.status_code != 200:
                    # Mark as "NONE" so we stop trying
                    db.supabase.table('candidates')\
                        .update({'committee_id': 'NONE'})\
                        .eq('candidate_id', candidate_uuid)\
                        .execute()
                    await asyncio.sleep(3)
                    continue
                
                committee_data = committee_response.json()
                committees = committee_data.get('results', [])
                
                if not committees:
                    # Mark as "NONE" so we stop trying
                    db.supabase.table('candidates')\
                        .update({'committee_id': 'NONE'})\
                        .eq('candidate_id', candidate_uuid)\
                        .execute()
                    await asyncio.sleep(3)
                    continue
                
                # Get principal committee
                principal = next((c for c in committees if c.get('designation') == 'P'), committees[0])
                committee_id = principal.get('committee_id')
                committee_name = principal.get('name')
                
                # SAVE committee_id IMMEDIATELY
                update_result = db.supabase.table('candidates')\
                    .update({
                        'committee_id': committee_id
                    })\
                    .eq('candidate_id', candidate_uuid)\
                    .execute()
                
                if not update_result.data:
                    print(f"Failed to update committee_id for {fec_candidate_id}")
                    await asyncio.sleep(3)
                    continue
                
                enriched_count += 1
                
                # Get financial reports
                reports_url = f"https://api.open.fec.gov/v1/reports/{committee_id}/?api_key={api_key}&sort=-coverage_end_date&per_page=1"
                
                # Handle 429 rate limits
                for attempt in range(max_retries):
                    reports_response = await client.get(reports_url)
                    
                    if reports_response.status_code == 429:
                        if attempt < max_retries - 1:
                            await asyncio.sleep(60)
                            continue
                    
                    if reports_response.status_code == 200:
                        break
                
                if reports_response.status_code == 200:
                    reports_data = reports_response.json()
                    reports = reports_data.get('results', [])
                    
                    if reports:
                        latest_report = reports[0]
                        
                        # Get SOO link
                        soo_url = f"https://docquery.fec.gov/cgi-bin/forms/{committee_id}/"
                        
                        # Create filing record
                        filing_data = {
                            'candidate_id': candidate_uuid,
                            'committee_id': committee_id,
                            'committee_name': committee_name,
                            'filing_type': latest_report.get('report_type'),
                            'filing_date': latest_report.get('receipt_date'),
                            'period_end': latest_report.get('coverage_end_date'),
                            'period_start': latest_report.get('coverage_start_date'),
                            'total_receipts': latest_report.get('total_receipts'),
                            'receipts_period': latest_report.get('receipts', latest_report.get('total_receipts')),
                            'total_disbursements': latest_report.get('total_disbursements'),
                            'disbursements_period': latest_report.get('disbursements', latest_report.get('total_disbursements')),
                            'cash_on_hand': latest_report.get('cash_on_hand_end_period'),
                            'debts_owed': latest_report.get('debts_owed'),
                            'statement_of_org': soo_url,
                            'source_url': f"https://docquery.fec.gov/cgi-bin/forms/{committee_id}/{latest_report.get('report_year')}/"
                        }
                        
                        db.supabase.table('filings').insert(filing_data).execute()
                        filings_count += 1
                
                await asyncio.sleep(3)  # Rate limiting delay
                
            except Exception as e:
                print(f"Error enriching candidate {fec_candidate_id}: {e}")
                continue
    
    remaining = len(all_candidates) - start_offset - len(batch)
    
    return {
        "status": "success" if remaining <= 0 else "in_progress",
        "batch_processed": len(batch),
        "enriched_with_committee": enriched_count,
        "filings_created": filings_count,
        "estimated_remaining": max(0, remaining),
        "next_offset": start_offset + batch_size if remaining > 0 else None
    }

@router.get("/calculate-viability")
async def calculate_viability():
    """Calculate viability scores for all candidates"""
    try:
        # Get all candidates
        candidates_result = db.supabase.table('candidates')\
            .select('candidate_id, office, occupation, incumbent')\
            .execute()
        
        updated_count = 0
        
        for candidate in candidates_result.data:
            score = 0
            
            # Office plausibility (0-4 points)
            office = candidate.get('office', '')
            if office == 'House':
                score += 3
            elif office == 'Senate':
                score += 4
            
            # Occupation quality (0-3 points)
            occupation = candidate.get('occupation', '').upper()
            high_quality = ['ATTORNEY', 'LAWYER', 'DOCTOR', 'PHYSICIAN', 'PROFESSOR', 'TEACHER', 'BUSINESS OWNER', 'CEO', 'EXECUTIVE']
            medium_quality = ['CONSULTANT', 'MANAGER', 'DIRECTOR', 'ENGINEER', 'ANALYST']
            
            if any(term in occupation for term in high_quality):
                score += 3
            elif any(term in occupation for term in medium_quality):
                score += 2
            elif occupation and occupation != 'NONE':
                score += 1
            
            # Incumbency (0-3 points)
            if candidate.get('incumbent'):
                score += 3
            
            # Determine bucket
            if score >= 7:
                bucket = 'HIGH'
            elif score >= 4:
                bucket = 'MEDIUM'
            else:
                bucket = 'LOW'
            
            # Update candidate
            db.supabase.table('candidates')\
                .update({
                    'viability_score': score,
                    'viability_bucket': bucket
                })\
                .eq('candidate_id', candidate['candidate_id'])\
                .execute()
            
            updated_count += 1
        
        return {
            "status": "success",
            "candidates_scored": updated_count,
            "message": f"Successfully scored {updated_count} candidates"
        }
        
    except Exception as e:
        return {"error": str(e)}

@router.get("/sync-to-airtable")
async def sync_to_airtable():
    """Sync candidates and filings from Supabase to Airtable"""
    
    airtable_token = os.environ.get('AIRTABLE_TOKEN')
    base_id = os.environ.get('AIRTABLE_BASE_ID')
    
    if not airtable_token or not base_id:
        return {"error": "Airtable credentials not found"}
    
    candidates_table = "Candidates"
    filings_table = "Filings & Finance"
    
    headers = {
        "Authorization": f"Bearer {airtable_token}",
        "Content-Type": "application/json"
    }
    
    candidates_synced = 0
    filings_synced = 0
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Sync candidates
        candidates_result = db.supabase.table('candidates').select('*').execute()
        
        for candidate in candidates_result.data:
            try:
                # Check if exists in Airtable
                search_url = f"https://api.airtable.com/v0/{base_id}/{candidates_table}"
                search_params = {
                    "filterByFormula": f"{{Source Candidate ID}}='{candidate.get('source_candidate_ID')}'"
                }
                
                search_response = await client.get(search_url, headers=headers, params=search_params)
                
                if search_response.status_code == 200:
                    existing_records = search_response.json().get('records', [])
                    
                    airtable_data = {
                        "Source Candidate ID": candidate.get('source_candidate_ID'),
                        "Full Name": candidate.get('full_name'),
                        "Party": candidate.get('party'),
                        "Jurisdiction": candidate.get('jurisdiction_name'),
                        "Office Sought": candidate.get('office'),
                        "State": candidate.get('state'),
                        "Incumbent?": candidate.get('incumbent', False),
                        "Status": candidate.get('status'),
                        "Occupation": candidate.get('occupation'),
                        "Viability Score": candidate.get('viability_score'),
                        "Viability Bucket": candidate.get('viability_bucket')
                    }
                    
                    if existing_records:
                        # Update existing
                        record_id = existing_records[0]['id']
                        update_url = f"https://api.airtable.com/v0/{base_id}/{candidates_table}/{record_id}"
                        await client.patch(update_url, headers=headers, json={"fields": airtable_data})
                    else:
                        # Create new
                        create_url = f"https://api.airtable.com/v0/{base_id}/{candidates_table}"
                        await client.post(create_url, headers=headers, json={"fields": airtable_data})
                    
                    candidates_synced += 1
                
                await asyncio.sleep(0.2)  # Airtable rate limiting
                
            except Exception as e:
                print(f"Error syncing candidate: {e}")
                continue
        
        # Sync filings
        filings_result = db.supabase.table('filings').select('*').execute()
        
        for filing in filings_result.data:
            try:
                # Get candidate's Airtable record ID
                candidate_result = db.supabase.table('candidates')\
                    .select('source_candidate_ID')\
                    .eq('candidate_id', filing.get('candidate_id'))\
                    .execute()
                
                if not candidate_result.data:
                    continue
                
                source_id = candidate_result.data[0].get('source_candidate_ID')
                
                # Find Airtable candidate record
                search_url = f"https://api.airtable.com/v0/{base_id}/{candidates_table}"
                search_params = {
                    "filterByFormula": f"{{Source Candidate ID}}='{source_id}'"
                }
                
                search_response = await client.get(search_url, headers=headers, params=search_params)
                
                if search_response.status_code != 200 or not search_response.json().get('records'):
                    continue
                
                candidate_record_id = search_response.json()['records'][0]['id']
                
                airtable_filing_data = {
                    "Candidate": [candidate_record_id],
                    "Filing Type": filing.get('filing_type'),
                    "Filing Date": filing.get('filing_date'),
                    "Period End": filing.get('period_end'),
                    "Committee ID": filing.get('committee_id'),
                    "Total Receipts": float(filing.get('total_receipts', 0) or 0),
                    "Total Disbursements": float(filing.get('total_disbursements', 0) or 0),
                    "Cash on Hand": float(filing.get('cash_on_hand', 0) or 0),
                    "Debts Owed": float(filing.get('debts_owed', 0) or 0),
                    "SOO Link": filing.get('statement_of_org'),
                    "Report Link": filing.get('source_url')
                }
                
                create_url = f"https://api.airtable.com/v0/{base_id}/{filings_table}"
                await client.post(create_url, headers=headers, json={"fields": airtable_filing_data})
                
                filings_synced += 1
                await asyncio.sleep(0.2)
                
            except Exception as e:
                print(f"Error syncing filing: {e}")
                continue
    
    return {
        "status": "success",
        "candidates_synced": candidates_synced,
        "filings_synced": filings_synced,
        "message": f"Synced {candidates_synced} candidates and {filings_synced} filings to Airtable"
    }

@router.get("/debug-candidate")
async def debug_candidate(candidate_id: str):
    """Debug endpoint to test single candidate enrichment"""
    
    api_key = os.environ.get('FEC_API_KEY')
    if not api_key:
        return {"error": "FEC_API_KEY not found"}
    
    try:
        # Get candidate
        candidate_result = db.supabase.table('candidates')\
            .select('*')\
            .eq('source_candidate_ID', candidate_id)\
            .execute()
        
        if not candidate_result.data:
            return {"error": "Candidate not found"}
        
        candidate = candidate_result.data[0]
        
        # Get FEC committee data
        async with httpx.AsyncClient(timeout=30.0) as client:
            committee_url = f"https://api.open.fec.gov/v1/candidates/{candidate_id}/committees/?api_key={api_key}"
            committee_response = await client.get(committee_url)
            committee_data = committee_response.json() if committee_response.status_code == 200 else None
        
        return {
            "candidate": candidate,
            "fec_data": {
                "committees": {
                    "status_code": committee_response.status_code,
                    "data": committee_data
                }
            }
        }
        
    except Exception as e:
        return {"error": str(e)}

@router.get("/candidates")
async def get_candidates(
    limit: int = Query(100, ge=1, le=1000),
    skip: int = Query(0, ge=0),
    party: Optional[str] = None,
    office: Optional[str] = None,
    state: Optional[str] = None,
    viability_bucket: Optional[str] = None
):
    """Get candidates with optional filters"""
    
    try:
        query = db.supabase.table('candidates').select('*')
        
        if party:
            query = query.eq('party', party)
        if office:
            query = query.eq('office', office)
        if state:
            query = query.eq('state', state)
        if viability_bucket:
            query = query.eq('viability_bucket', viability_bucket.upper())
        
        result = query.order('full_name').range(skip, skip + limit - 1).execute()
        
        return {
            "candidates": result.data,
            "count": len(result.data)
        }
        
    except Exception as e:
        return {"error": str(e)}
