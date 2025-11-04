"""
FastAPI Routes - Candidate Tracker
Clean, consolidated endpoints for reliable data collection
"""
from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime
from app.db.client import db
import os
import httpx
import asyncio

router = APIRouter()

# ============================================================================
# HEALTH & UTILITY ENDPOINTS
# ============================================================================

@router.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "2.1.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/database-stats")
async def database_stats():
    """Quick overview of database contents"""
    try:
        candidates_result = db.supabase.table('candidates').select('candidate_id', count='exact').execute()
        filings_result = db.supabase.table('filings').select('filing_id', count='exact').execute()
        
        # Get candidates with committees
        with_committees = db.supabase.table('candidates').select('candidate_id').not_.is_('committee_id', 'null').execute()
        
        # Get candidates with occupation data
        with_occupation = db.supabase.table('candidates').select('candidate_id').not_.is_('occupation', 'null').execute()
        
        # Get viability distribution
        high = db.supabase.table('candidates').select('candidate_id').eq('viability_bucket', 'HIGH').execute()
        medium = db.supabase.table('candidates').select('candidate_id').eq('viability_bucket', 'MEDIUM').execute()
        low = db.supabase.table('candidates').select('candidate_id').eq('viability_bucket', 'LOW').execute()
        
        return {
            "total_candidates": candidates_result.count,
            "total_filings": filings_result.count,
            "candidates_with_committees": len(with_committees.data) if with_committees.data else 0,
            "candidates_with_occupation": len(with_occupation.data) if with_occupation.data else 0,
            "viability_distribution": {
                "high": len(high.data) if high.data else 0,
                "medium": len(medium.data) if medium.data else 0,
                "low": len(low.data) if low.data else 0
            }
        }
    except Exception as e:
        return {"error": str(e)}

@router.get("/candidates")
async def get_candidates(
    limit: int = Query(default=10, le=100),
    party: Optional[str] = None,
    office: Optional[str] = None,
    viability_bucket: Optional[str] = None
):
    """Get candidates from database with optional filters"""
    try:
        query = db.supabase.table('candidates').select('*')
        
        if party:
            query = query.eq('party', party)
        if office:
            query = query.eq('office', office)
        if viability_bucket:
            query = query.eq('viability_bucket', viability_bucket)
        
        result = query.limit(limit).execute()
        
        return {
            "candidates": result.data,
            "count": len(result.data)
        }
    except Exception as e:
        return {"error": str(e)}

# ============================================================================
# MAIN COLLECTION ENDPOINT - COMPLETE DATA COLLECTION
# ============================================================================

@router.get("/collect-candidates")
async def collect_candidates(
    cycles: str = "2026,2028",
    parties: str = "DEM"
):
    """
    Comprehensive candidate collection - gets everything in one pass:
    - Candidate basic info from FEC
    - Committee ID and name
    - Statement of Organization (SOO/F1) link
    - Occupation data
    - Most recent quarterly financial report (Q3 2025 as of Oct 2025)
    - Creates filing record with ALL financial data
    
    Focuses on House and Senate only (no Presidential candidates).
    """
    try:
        fec_api_key = os.environ.get('FEC_API_KEY')
        if not fec_api_key:
            return {"error": "FEC_API_KEY not found"}
        
        cycle_list = [int(c.strip()) for c in cycles.split(',')]
        party_list = [p.strip().upper() for p in parties.split(',')]
        offices = ["H", "S"]  # House and Senate only - no Presidential
        
        total_candidates_found = 0
        total_candidates_stored = 0
        total_filings_created = 0
        collection_summary = []
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            for cycle in cycle_list:
                for office in offices:
                    for party in party_list:
                        try:
                            cycle_candidates_found = 0
                            cycle_candidates_stored = 0
                            cycle_filings_created = 0
                            page = 1
                            max_pages = 100  # Safety limit
                            
                            while page <= max_pages:
                                # Get candidates from FEC API
                                params = {
                                    'api_key': fec_api_key,
                                    'cycle': cycle,
                                    'office': office,
                                    'party': party,
                                    'per_page': 100,
                                    'page': page
                                }
                                
                                response = await client.get(
                                    "https://api.open.fec.gov/v1/candidates/",
                                    params=params
                                )
                                
                                if response.status_code != 200:
                                    break
                                
                                data = response.json()
                                candidates = data.get('results', [])
                                
                                if not candidates:
                                    break  # No more candidates
                                
                                cycle_candidates_found += len(candidates)
                                
                                # Process each candidate
                                for candidate in candidates:
                                    try:
                                        source_candidate_id = candidate.get('candidate_id')
                                        
                                        # Skip if already exists
                                        existing = db.supabase.table('candidates').select('candidate_id').eq(
                                            'source_candidate_ID', source_candidate_id
                                        ).execute()
                                        
                                        if existing.data:
                                            continue
                                        
                                        # Parse name
                                        full_name = candidate.get('name', '')
                                        if ',' in full_name:
                                            last_name = full_name.split(',')[0].strip()
                                            first_name = full_name.split(',')[1].strip() if len(full_name.split(',')) > 1 else ''
                                        else:
                                            first_name = ''
                                            last_name = full_name
                                        
                                        # Get committee info
                                        committee_id = None
                                        committee_name = None
                                        soo_link = None
                                        
                                        committees_response = await client.get(
                                            "https://api.open.fec.gov/v1/committees/",
                                            params={
                                                'api_key': fec_api_key,
                                                'candidate_id': source_candidate_id,
                                                'per_page': 10
                                            }
                                        )
                                        
                                        if committees_response.status_code == 200:
                                            committees_data = committees_response.json()
                                            committees = committees_data.get('results', [])
                                            
                                            if committees:
                                                committee = committees[0]
                                                committee_id = committee.get('committee_id')
                                                committee_name = committee.get('name')
                                                
                                                # Get SOO (F1) link
                                                soo_response = await client.get(
                                                    "https://api.open.fec.gov/v1/filings/",
                                                    params={
                                                        'api_key': fec_api_key,
                                                        'committee_id': committee_id,
                                                        'form_type': 'F1',
                                                        'per_page': 1
                                                    }
                                                )
                                                
                                                if soo_response.status_code == 200:
                                                    soo_data = soo_response.json()
                                                    soo_filings = soo_data.get('results', [])
                                                    if soo_filings and soo_filings[0].get('pdf_url'):
                                                        soo_link = soo_filings[0]['pdf_url']
                                        
                                        # Create candidate record
                                        candidate_data = {
                                            'source_candidate_ID': source_candidate_id,
                                            'full_name': f"{first_name} {last_name}".strip(),
                                            'first_name': first_name,
                                            'last_name': last_name,
                                            'party': party,
                                            'office': candidate.get('office_full', office),
                                            'state': candidate.get('state'),
                                            'district': candidate.get('district'),
                                            'election_cycle': cycle,
                                            'incumbent': candidate.get('incumbent_challenger') == 'I',
                                            'status': candidate.get('candidate_status', 'Active'),
                                            'occupation': candidate.get('candidate_occupation'),
                                            'committee_id': committee_id,
                                            'jurisdiction_name': f"{candidate.get('state', 'Unknown')} {office}",
                                            'source_system': 'FEC',
                                            'updated_at': datetime.utcnow().isoformat()
                                        }
                                        
                                        candidate_result = db.supabase.table('candidates').insert(candidate_data).execute()
                                        
                                        if candidate_result.data:
                                            cycle_candidates_stored += 1
                                            candidate_uuid = candidate_result.data[0]['candidate_id']
                                            
                                            # Get most recent quarterly financial report
                                            total_receipts = None
                                            receipts_period = None
                                            total_disbursements = None
                                            disbursements_period = None
                                            cash_on_hand = None
                                            report_url = None
                                            period_end = None
                                            
                                            if committee_id:
                                                reports_response = await client.get(
                                                    "https://api.open.fec.gov/v1/reports/",
                                                    params={
                                                        'api_key': fec_api_key,
                                                        'committee_id': committee_id,
                                                        'per_page': 1,
                                                        'sort': '-coverage_end_date'  # Most recent first
                                                    }
                                                )
                                                
                                                if reports_response.status_code == 200:
                                                    reports_data = reports_response.json()
                                                    reports = reports_data.get('results', [])
                                                    
                                                    if reports:
                                                        report = reports[0]
                                                        total_receipts = report.get('total_receipts')
                                                        receipts_period = report.get('receipts_period')  # Just that quarter
                                                        total_disbursements = report.get('total_disbursements')
                                                        disbursements_period = report.get('disbursements_period')  # Just that quarter
                                                        cash_on_hand = report.get('cash_on_hand_end_period')
                                                        report_url = report.get('pdf_url')
                                                        period_end = report.get('coverage_end_date')
                                            
                                            # Create filing record with all data
                                            filing_data = {
                                                'candidate_id': candidate_uuid,
                                                'committee_id': committee_id,
                                                'filing_type': 'Quarterly Financial Report',
                                                'committee_name': committee_name,
                                                'statement_of_org': soo_link,
                                                'filing_date': datetime.utcnow().strftime('%Y-%m-%d'),
                                                'period_end': period_end,
                                                'total_receipts': total_receipts,
                                                'receipts_period': receipts_period,
                                                'total_disbursements': total_disbursements,
                                                'disbursements_period': disbursements_period,
                                                'cash_on_hand': cash_on_hand,
                                                'source_url': report_url
                                            }
                                            
                                            filing_result = db.supabase.table('filings').insert(filing_data).execute()
                                            if filing_result.data:
                                                cycle_filings_created += 1
                                        
                                        # Rate limiting
                                        await asyncio.sleep(0.3)
                                        
                                    except Exception as e:
                                        continue
                                
                                # Check pagination
                                pagination = data.get('pagination', {})
                                if page >= pagination.get('pages', 1):
                                    break
                                
                                page += 1
                                await asyncio.sleep(0.2)
                            
                            collection_summary.append({
                                "cycle": cycle,
                                "office": office,
                                "party": party,
                                "candidates_found": cycle_candidates_found,
                                "candidates_stored": cycle_candidates_stored,
                                "filings_created": cycle_filings_created
                            })
                            
                            total_candidates_found += cycle_candidates_found
                            total_candidates_stored += cycle_candidates_stored
                            total_filings_created += cycle_filings_created
                            
                        except Exception as e:
                            continue
        
        return {
            "status": "success",
            "cycles_collected": cycle_list,
            "parties": party_list,
            "offices": offices,
            "total_candidates_found": total_candidates_found,
            "total_candidates_stored": total_candidates_stored,
            "total_filings_created": total_filings_created,
            "collection_summary": collection_summary,
            "message": f"Successfully collected {total_candidates_stored} candidates with {total_filings_created} filing records"
        }
        
    except Exception as e:
        return {"error": f"Collection failed: {str(e)}"}

# ============================================================================
# QUARTERLY FINANCIAL REPORTS UPDATE
# ============================================================================

@router.get("/collect-financial-reports")
async def collect_financial_reports(
    batch_size: int = 50,
    start_offset: int = 0
):
    """
    Collect latest quarterly financial reports for candidates who have committees.
    Creates NEW filing records for each quarterly report (doesn't overwrite).
    
    Run this after FEC quarterly deadlines:
    - April 15 (Q1)
    - July 15 (Q2)
    - October 15 (Q3)
    - January 31 (Q4)
    """
    try:
        fec_api_key = os.environ.get('FEC_API_KEY')
        if not fec_api_key:
            return {"error": "FEC_API_KEY not found"}
        
        # Get candidates with committees
        candidates_result = db.supabase.table('candidates').select(
            'candidate_id, source_candidate_ID, full_name, committee_id'
        ).not_.is_('committee_id', 'null').order('candidate_id').range(
            start_offset, start_offset + batch_size - 1
        ).execute()
        
        candidates = candidates_result.data
        
        if not candidates:
            return {"status": "completed", "message": "No more candidates to process"}
        
        reports_created = 0
        no_reports_found = 0
        errors = []
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            for candidate in candidates:
                try:
                    committee_id = candidate.get('committee_id')
                    candidate_uuid = candidate.get('candidate_id')
                    
                    if not committee_id:
                        continue
                    
                    # Get latest financial report
                    reports_response = await client.get(
                        "https://api.open.fec.gov/v1/reports/",
                        params={
                            'api_key': fec_api_key,
                            'committee_id': committee_id,
                            'per_page': 1,
                            'sort': '-coverage_end_date'
                        }
                    )
                    
                    if reports_response.status_code == 200:
                        reports_data = reports_response.json()
                        reports = reports_data.get('results', [])
                        
                        if reports:
                            report = reports[0]
                            period_end = report.get('coverage_end_date')
                            
                            # Check if we already have this report
                            existing_filing = db.supabase.table('filings').select('filing_id').eq(
                                'candidate_id', candidate_uuid
                            ).eq('period_end', period_end).execute()
                            
                            if existing_filing.data:
                                continue  # Already have this report
                            
                            # Create new filing record for this quarterly report
                            filing_data = {
                                'candidate_id': candidate_uuid,
                                'committee_id': committee_id,
                                'filing_type': 'Quarterly Financial Report',
                                'filing_date': report.get('receipt_date', datetime.utcnow().strftime('%Y-%m-%d')),
                                'period_end': period_end,
                                'total_receipts': report.get('total_receipts'),
                                'receipts_period': report.get('receipts_period'),
                                'total_disbursements': report.get('total_disbursements'),
                                'disbursements_period': report.get('disbursements_period'),
                                'cash_on_hand': report.get('cash_on_hand_end_period'),
                                'source_url': report.get('pdf_url', '')
                            }
                            
                            result = db.supabase.table('filings').insert(filing_data).execute()
                            if result.data:
                                reports_created += 1
                        else:
                            no_reports_found += 1
                    
                    # Rate limiting
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    errors.append(f"Error processing {candidate.get('full_name')}: {str(e)}")
                    continue
        
        next_offset = start_offset + batch_size
        
        return {
            "status": "batch_completed",
            "batch_info": {
                "processed": f"Candidates {start_offset + 1} - {start_offset + len(candidates)}",
                "next_offset": next_offset
            },
            "results": {
                "candidates_processed": len(candidates),
                "new_reports_created": reports_created,
                "no_reports_found": no_reports_found
            },
            "errors": errors[:5] if errors else [],
            "next_steps": [
                f"Run again with start_offset={next_offset} to continue" if len(candidates) == batch_size else "All candidates processed"
            ]
        }
        
    except Exception as e:
        return {"error": f"Financial report collection failed: {str(e)}"}

# ============================================================================
# VIABILITY SCORING
# ============================================================================

@router.get("/calculate-viability")
async def calculate_viability():
    """
    Calculate viability scores for all candidates.
    
    Scoring (0-10 points):
    - Occupation: 0-3 points (higher for elected officials, lawyers, business owners)
    - Office plausibility: 0-2 points (House/Senate = 2)
    - Media mentions: 0-5 points (when implemented)
    
    Buckets: HIGH (7+), MEDIUM (4-6), LOW (0-3)
    """
    try:
        # Occupation scoring keywords
        high_value_occupations = ['MAYOR', 'COUNCIL', 'LEGISLATOR', 'SENATOR', 'REPRESENTATIVE', 
                                   'COMMISSIONER', 'JUDGE', 'ATTORNEY', 'LAWYER']
        medium_value_occupations = ['BUSINESS', 'EXECUTIVE', 'DIRECTOR', 'MANAGER', 'CONSULTANT',
                                     'PROFESSOR', 'DOCTOR', 'PHYSICIAN']
        
        # Get all candidates
        all_candidates = []
        offset = 0
        batch_size = 1000
        
        while True:
            candidates_result = db.supabase.table('candidates').select(
                'candidate_id, occupation, office'
            ).range(offset, offset + batch_size - 1).execute()
            
            batch = candidates_result.data
            if not batch:
                break
            
            all_candidates.extend(batch)
            offset += batch_size
            
            if len(batch) < batch_size:
                break
        
        scores_calculated = 0
        high_viability = 0
        medium_viability = 0
        low_viability = 0
        
        for candidate in all_candidates:
            try:
                candidate_id = candidate.get('candidate_id')
                occupation = (candidate.get('occupation') or '').upper()
                office = (candidate.get('office') or '').upper()
                
                # OCCUPATION SCORE (0-3 points)
                occupation_score = 0
                if any(keyword in occupation for keyword in high_value_occupations):
                    occupation_score = 3
                elif any(keyword in occupation for keyword in medium_value_occupations):
                    occupation_score = 2
                elif occupation and occupation != 'NONE':
                    occupation_score = 1
                
                # OFFICE PLAUSIBILITY SCORE (0-2 points)
                office_score = 0
                if 'HOUSE' in office or office == 'H':
                    office_score = 2
                elif 'SENATE' in office or office == 'S':
                    office_score = 2
                else:
                    office_score = 2  # State/local offices
                
                # MEDIA SCORE (0-5 points) - placeholder
                media_score = 0
                
                # Calculate total
                total_score = occupation_score + office_score + media_score
                
                # Determine bucket
                if total_score >= 7:
                    bucket = "HIGH"
                    high_viability += 1
                elif total_score >= 4:
                    bucket = "MEDIUM"
                    medium_viability += 1
                else:
                    bucket = "LOW"
                    low_viability += 1
                
                # Update candidate
                db.supabase.table('candidates').update({
                    'viability_score': total_score,
                    'viability_bucket': bucket
                }).eq('candidate_id', candidate_id).execute()
                
                scores_calculated += 1
                
            except Exception as e:
                continue
        
        return {
            "status": "completed",
            "total_candidates": len(all_candidates),
            "scores_calculated": scores_calculated,
            "distribution": {
                "high_viability": high_viability,
                "medium_viability": medium_viability,
                "low_viability": low_viability
            },
            "scoring_breakdown": {
                "occupation": "0-3 points based on keywords",
                "office": "0-2 points based on office type",
                "media": "0-5 points (not yet implemented)"
            }
        }
        
    except Exception as e:
        return {"error": f"Viability calculation failed: {str(e)}"}

# ============================================================================
# AIRTABLE SYNC
# ============================================================================

@router.get("/sync-to-airtable")
async def sync_to_airtable():
    """
    Sync candidates and filings from Supabase to Airtable.
    Run this after collecting candidates or financial reports.
    
    Creates proper linked records:
    - Candidates table gets candidate info
    - Filings & Finance table gets filing records linked to candidates
    """
    try:
        airtable_token = os.environ.get('AIRTABLE_TOKEN')
        airtable_base_id = os.environ.get('AIRTABLE_BASE_ID')
        
        if not airtable_token or not airtable_base_id:
            return {"error": "Missing Airtable credentials"}
        
        def map_party(party_code):
            """Map FEC party codes to Airtable values"""
            if not party_code:
                return "Other"
            party_upper = str(party_code).upper().strip()
            if party_upper in ["DEM", "DEMOCRATIC"]:
                return "Democratic"
            elif party_upper in ["REP", "REPUBLICAN"]:
                return "Republican"
            elif party_upper in ["IND", "INDEPENDENT"]:
                return "Independent"
            else:
                return "Other"
        
        # Get all candidates from Supabase
        all_candidates = []
        offset = 0
        batch_size = 1000
        
        while True:
            candidates_result = db.supabase.table('candidates').select('*').range(
                offset, offset + batch_size - 1
            ).execute()
            
            batch = candidates_result.data
            if not batch:
                break
            
            all_candidates.extend(batch)
            offset += batch_size
            
            if len(batch) < batch_size:
                break
        
        # Get existing Airtable candidates to avoid duplicates
        candidates_url = f"https://api.airtable.com/v0/{airtable_base_id}/Candidates"
        filings_url = f"https://api.airtable.com/v0/{airtable_base_id}/Filings%20%26%20Finance"
        headers = {
            "Authorization": f"Bearer {airtable_token}",
            "Content-Type": "application/json"
        }
        
        existing_candidates = {}  # source_candidate_ID -> airtable_record_id
        existing_filings = set()  # Set of filing identifiers
        
        async with httpx.AsyncClient() as client:
            # Get existing candidates
            offset = None
            while True:
                params = {"pageSize": 100}
                if offset:
                    params["offset"] = offset
                
                response = await client.get(candidates_url, headers=headers, params=params)
                if response.status_code != 200:
                    break
                
                data = response.json()
                for record in data.get('records', []):
                    source_id = record.get('fields', {}).get('Source Candidate ID')
                    if source_id:
                        existing_candidates[source_id] = record['id']
                
                offset = data.get('offset')
                if not offset:
                    break
            
            # Get existing filings
            offset = None
            while True:
                params = {"pageSize": 100}
                if offset:
                    params["offset"] = offset
                
                response = await client.get(filings_url, headers=headers, params=params)
                if response.status_code != 200:
                    break
                
                data = response.json()
                for record in data.get('records', []):
                    fields = record.get('fields', {})
                    candidate_link = fields.get('Candidate', [])
                    period_end = fields.get('Period End', '')
                    if candidate_link and period_end:
                        existing_filings.add(f"{candidate_link[0]}_{period_end}")
                
                offset = data.get('offset')
                if not offset:
                    break
        
        candidates_synced = 0
        filings_synced = 0
        errors = []
        
        # Sync candidates in batches of 10 (Airtable limit)
        async with httpx.AsyncClient() as client:
            for i in range(0, len(all_candidates), 10):
                candidate_batch = all_candidates[i:i+10]
                candidate_records = []
                
                for candidate in candidate_batch:
                    source_id = candidate.get('source_candidate_ID')
                    
                    # Skip if already exists
                    if source_id in existing_candidates:
                        continue
                    
                    candidate_record = {
                        "fields": {
                            "Source Candidate ID": source_id,
                            "Full Name": str(candidate.get('full_name', '')),
                            "Party": map_party(candidate.get('party')),
                            "Jurisdiction": str(candidate.get('jurisdiction_name', '')),
                            "Office Sought": str(candidate.get('office', '')),
                            "State": str(candidate.get('state', '')),
                            "Incumbent?": bool(candidate.get('incumbent', False)),
                            "Status": str(candidate.get('status', 'Active')),
                            "Occupation": str(candidate.get('occupation', '')),
                            "Viability Score": candidate.get('viability_score', 0),
                            "Viability Bucket": str(candidate.get('viability_bucket', ''))
                        }
                    }
                    candidate_records.append(candidate_record)
                
                # Create candidate records
                if candidate_records:
                    try:
                        response = await client.post(
                            candidates_url,
                            headers=headers,
                            json={"records": candidate_records}
                        )
                        
                        if response.status_code == 200:
                            response_data = response.json()
                            created_records = response_data.get('records', [])
                            candidates_synced += len(created_records)
                            
                            # Update existing_candidates map
                            for record in created_records:
                                source_id = record.get('fields', {}).get('Source Candidate ID')
                                if source_id:
                                    existing_candidates[source_id] = record['id']
                        else:
                            errors.append(f"Candidate batch {i//10 + 1} failed: {response.status_code}")
                    
                    except Exception as e:
                        errors.append(f"Candidate batch {i//10 + 1} error: {str(e)}")
                
                await asyncio.sleep(0.2)
        
        # Now sync filings
        all_filings = []
        offset = 0
        
        while True:
            filings_result = db.supabase.table('filings').select('*').range(
                offset, offset + batch_size - 1
            ).execute()
            
            batch = filings_result.data
            if not batch:
                break
            
            all_filings.extend(batch)
            offset += batch_size
            
            if len(batch) < batch_size:
                break
        
        # Sync filings in batches
        async with httpx.AsyncClient() as client:
            for i in range(0, len(all_filings), 10):
                filing_batch = all_filings[i:i+10]
                filing_records = []
                
                for filing in filing_batch:
                    candidate_uuid = filing.get('candidate_id')
                    
                    # Find the candidate's source_candidate_ID and Airtable record ID
                    candidate_result = db.supabase.table('candidates').select(
                        'source_candidate_ID'
                    ).eq('candidate_id', candidate_uuid).execute()
                    
                    if not candidate_result.data:
                        continue
                    
                    source_id = candidate_result.data[0].get('source_candidate_ID')
                    airtable_candidate_id = existing_candidates.get(source_id)
                    
                    if not airtable_candidate_id:
                        continue  # Candidate not in Airtable yet
                    
                    # Check if filing already exists
                    period_end = filing.get('period_end', '')
                    filing_identifier = f"{airtable_candidate_id}_{period_end}"
                    
                    if filing_identifier in existing_filings:
                        continue
                    
                    filing_record = {
                        "fields": {
                            "Candidate": [airtable_candidate_id],
                            "Filing Type": str(filing.get('filing_type', '')),
                            "Filing Date": str(filing.get('filing_date', '')),
                            "Period End": str(filing.get('period_end', '')),
                            "Committee ID": str(filing.get('committee_id', '')),
                            "Committee Name": str(filing.get('committee_name', '')),
                            "Total Receipts": float(filing.get('total_receipts', 0)) if filing.get('total_receipts') else 0,
                            "Receipts Period": float(filing.get('receipts_period', 0)) if filing.get('receipts_period') else 0,
                            "Total Disbursements": float(filing.get('total_disbursements', 0)) if filing.get('total_disbursements') else 0,
                            "Disbursements Period": float(filing.get('disbursements_period', 0)) if filing.get('disbursements_period') else 0,
                            "Cash on Hand": float(filing.get('cash_on_hand', 0)) if filing.get('cash_on_hand') else 0,
                            "SOO Link": str(filing.get('statement_of_org', '')),
                            "Report Link": str(filing.get('source_url', ''))
                        }
                    }
                    filing_records.append(filing_record)
                
                # Create filing records
                if filing_records:
                    try:
                        response = await client.post(
                            filings_url,
                            headers=headers,
                            json={"records": filing_records}
                        )
                        
                        if response.status_code == 200:
                            response_data = response.json()
                            filings_synced += len(response_data.get('records', []))
                        else:
                            errors.append(f"Filing batch {i//10 + 1} failed: {response.status_code}")
                    
                    except Exception as e:
                        errors.append(f"Filing batch {i//10 + 1} error: {str(e)}")
                
                await asyncio.sleep(0.2)
        
        return {
            "status": "completed",
            "candidates": {
                "total_in_supabase": len(all_candidates),
                "already_in_airtable": len(existing_candidates) - candidates_synced,
                "newly_synced": candidates_synced
            },
            "filings": {
                "total_in_supabase": len(all_filings),
                "newly_synced": filings_synced
            },
            "errors": errors[:10] if errors else []
        }
        
    except Exception as e:
        return {"error": f"Airtable sync failed: {str(e)}"}

# ============================================================================
# DEBUG ENDPOINT
# ============================================================================

@router.get("/debug-candidate")
async def debug_candidate(candidate_id: str):
    """
    Debug a single candidate - test FEC API calls and data retrieval.
    Use either source_candidate_ID (FEC ID) or candidate_id (UUID).
    """
    try:
        fec_api_key = os.environ.get('FEC_API_KEY')
        if not fec_api_key:
            return {"error": "FEC_API_KEY not found"}
        
        # Try to find candidate
        candidate = None
        
        # Try as source_candidate_ID first
        result = db.supabase.table('candidates').select('*').eq(
            'source_candidate_ID', candidate_id
        ).execute()
        
        if result.data:
            candidate = result.data[0]
        else:
            # Try as UUID
            result = db.supabase.table('candidates').select('*').eq(
                'candidate_id', candidate_id
            ).execute()
            if result.data:
                candidate = result.data[0]
        
        if not candidate:
            return {"error": "Candidate not found"}
        
        source_id = candidate.get('source_candidate_ID')
        debug_info = {
            "candidate": candidate,
            "fec_data": {}
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Test committee lookup
            committees_response = await client.get(
                "https://api.open.fec.gov/v1/committees/",
                params={
                    'api_key': fec_api_key,
                    'candidate_id': source_id,
                    'per_page': 5
                }
            )
            
            debug_info["fec_data"]["committees"] = {
                "status_code": committees_response.status_code,
                "data": committees_response.json() if committees_response.status_code == 200 else None
            }
            
            # Test SOO lookup
            if committees_response.status_code == 200:
                committees = committees_response.json().get('results', [])
                if committees:
                    committee_id = committees[0].get('committee_id')
                    
                    soo_response = await client.get(
                        "https://api.open.fec.gov/v1/filings/",
                        params={
                            'api_key': fec_api_key,
                            'committee_id': committee_id,
                            'form_type': 'F1',
                            'per_page': 1
                        }
                    )
                    
                    debug_info["fec_data"]["soo"] = {
                        "status_code": soo_response.status_code,
                        "data": soo_response.json() if soo_response.status_code == 200 else None
                    }
                    
                    # Test financial reports
                    reports_response = await client.get(
                        "https://api.open.fec.gov/v1/reports/",
                        params={
                            'api_key': fec_api_key,
                            'committee_id': committee_id,
                            'per_page': 3,
                            'sort': '-coverage_end_date'
                        }
                    )
                    
                    debug_info["fec_data"]["reports"] = {
                        "status_code": reports_response.status_code,
                        "data": reports_response.json() if reports_response.status_code == 200 else None
                    }
        
        return debug_info
        
    except Exception as e:
        return {"error": f"Debug failed: {str(e)}"}
