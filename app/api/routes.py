"""FastAPI routes"""
from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime
from app.db.client import db
import os
import httpx
import json
import asyncio

router = APIRouter()

@router.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/test")
async def test_endpoint():
    """Test endpoint to verify API is working"""
    return {"message": "API is working"}

@router.get("/candidates")
async def get_candidates(limit: int = Query(default=10, le=100)):
    """Get candidates from database"""
    try:
        result = db.supabase.table('candidates').select('*').limit(limit).execute()
        return {
            "candidates": result.data,
            "count": len(result.data)
        }
    except Exception as e:
        return {"error": str(e)}

@router.get("/collect-democratic-candidates")
async def collect_democratic_candidates():
    """Collect Democratic and Independent candidates from FEC API for multiple cycles"""
    try:
        base_url = "https://api.open.fec.gov/v1/candidates/"
        api_key = os.environ.get('FEC_API_KEY')
        
        if not api_key:
            return {"error": "FEC_API_KEY not found in environment variables"}
        
        total_candidates_found = 0
        total_candidates_stored = 0
        collection_summary = []
        
        # Process multiple cycles and offices
        cycles = [2025, 2026, 2027, 2028]
        offices = ["H", "S", "P"]  # House, Senate, President
        parties = ["DEM", "IND"]  # Democratic and Independent only
        
        for cycle in cycles:
            for office in offices:
                for party in parties:
                    try:
                        page = 1
                        cycle_candidates_found = 0
                        cycle_candidates_stored = 0
                        
                        while True:
                            params = {
                                'api_key': api_key,
                                'election_year': cycle,
                                'office': office,
                                'party': party,
                                'per_page': 100,
                                'page': page
                            }
                            
                            async with httpx.AsyncClient() as client:
                                response = await client.get(base_url, params=params)
                                
                                if response.status_code != 200:
                                    break
                                
                                data = response.json()
                                candidates = data.get('results', [])
                                
                                if not candidates:
                                    break
                                
                                for candidate in candidates:
                                    cycle_candidates_found += 1
                                    
                                    # Store candidate in database
                                    candidate_data = {
                                        'source_candidate_id': candidate.get('candidate_id'),
                                        'candidate_name': candidate.get('name'),
                                        'party': candidate.get('party'),
                                        'office': candidate.get('office_full', office),
                                        'election_cycle': cycle,
                                        'state': candidate.get('state'),
                                        'district': candidate.get('district'),
                                        'incumbent_challenger': candidate.get('incumbent_challenger'),
                                        'candidate_status': candidate.get('candidate_status'),
                                        'active_through': candidate.get('active_through'),
                                        'jurisdiction_name': f"{candidate.get('state', 'Unknown')} {office}",
                                        'last_updated': datetime.utcnow().isoformat()
                                    }
                                    
                                    try:
                                        result = db.supabase.table('candidates').insert(candidate_data).execute()
                                        cycle_candidates_stored += 1
                                    except Exception as e:
                                        # Continue on individual insert errors
                                        continue
                                
                                page += 1
                                
                                # Pagination limit check
                                if page > 50:
                                    break
                        
                        collection_summary.append({
                            "cycle": cycle,
                            "office": office,
                            "party": party,
                            "candidates_found": cycle_candidates_found,
                            "candidates_stored": cycle_candidates_stored
                        })
                        
                        total_candidates_found += cycle_candidates_found
                        total_candidates_stored += cycle_candidates_stored
                        
                    except Exception as e:
                        continue
        
        return {
            "status": "success",
            "focus": "Democratic candidates + Independents only",
            "cycles_collected": cycles,
            "total_candidates_found": total_candidates_found,
            "total_candidates_stored": total_candidates_stored,
            "collection_summary": collection_summary,
            "message": f"Successfully collected {total_candidates_stored} Democratic and Independent candidates"
        }
        
    except Exception as e:
        return {"error": f"Collection failed: {str(e)}"}

@router.get("/democratic-collection-status")
async def democratic_collection_status():
    """Check status of Democratic candidate collection"""
    try:
        # Get Democratic candidates
        dem_result = db.supabase.table('candidates').select('*').eq('party', 'DEM').execute()
        democratic_candidates = dem_result.data
        
        # Get Independent candidates
        ind_result = db.supabase.table('candidates').select('*').eq('party', 'IND').execute()
        independent_candidates = ind_result.data
        
        # Analyze Democratic breakdown
        dem_breakdown = {"house": 0, "senate": 0, "president": 0}
        for candidate in democratic_candidates:
            office = candidate.get('office', '').lower()
            if 'house' in office or office == 'h':
                dem_breakdown["house"] += 1
            elif 'senate' in office or office == 's':
                dem_breakdown["senate"] += 1
            elif 'president' in office or office == 'p':
                dem_breakdown["president"] += 1
        
        # Top states analysis
        state_counts = {}
        for candidate in democratic_candidates:
            state = candidate.get('state', 'Unknown')
            state_counts[state] = state_counts.get(state, 0) + 1
        
        top_states = dict(sorted(state_counts.items(), key=lambda x: x[1], reverse=True)[:10])
        
        return {
            "democratic_candidates": len(democratic_candidates),
            "independent_candidates": len(independent_candidates),
            "democratic_breakdown": dem_breakdown,
            "top_democratic_states": top_states,
            "focus": "Democrats primary, Independents secondary",
            "next_steps": [
                "Run /collect-democratic-candidates for full collection",
                "Check /democratic-collection-status to monitor progress"
            ]
        }
        
    except Exception as e:
        return {"error": str(e)}

@router.get("/validate-2026-data")
async def validate_2026_data():
    """Validate data specifically for 2026 cycle"""
    try:
        # Get all candidates
        all_result = db.supabase.table('candidates').select('*').limit(1000).execute()
        all_candidates = all_result.data
        
        # Filter for 2026
        candidates_2026 = [c for c in all_candidates if c.get('election_cycle') == 2026]
        
        # Get election cycles
        cycles = {}
        for candidate in all_candidates:
            cycle = candidate.get('election_cycle')
            if cycle:
                cycles[cycle] = cycles.get(cycle, 0) + 1
        
        # Party distribution for 2026
        party_dist = {}
        office_dist = {}
        for candidate in candidates_2026:
            party = candidate.get('party', 'Unknown')
            office = candidate.get('office', 'Unknown')
            party_dist[party] = party_dist.get(party, 0) + 1
            office_dist[office] = office_dist.get(office, 0) + 1
        
        # Data quality checks
        missing_source_ids = len([c for c in all_candidates if not c.get('source_candidate_id')])
        missing_names = len([c for c in all_candidates if not c.get('candidate_name')])
        
        return {
            "total_candidates": len(all_candidates),
            "election_cycles": cycles,
            "candidates_2026": len(candidates_2026),
            "data_quality": {
                "missing_source_ids": missing_source_ids,
                "missing_names": missing_names
            },
            "2026_distribution": {
                "by_party": party_dist,
                "by_office": office_dist
            },
            "recommendations": [
                f"Focus sync on {len(candidates_2026)} candidates from 2026 cycle",
                "Source ID data looks good" if missing_source_ids == 0 else f"Fix {missing_source_ids} missing source IDs",
                "Review candidates from other cycles - may be legitimate early filers"
            ]
        }
        
    except Exception as e:
        return {"error": str(e)}

@router.get("/check-party-values")
async def check_party_values():
    """Check unique party values in database"""
    try:
        result = db.supabase.table('candidates').select('party').execute()
        parties = [c.get('party') for c in result.data if c.get('party')]
        unique_parties = list(set(parties))
        
        return {
            "unique_parties": unique_parties,
            "count": len(result.data),
            "sample_parties": parties[:10]
        }
    except Exception as e:
        return {"error": str(e)}

@router.get("/debug-airtable")
async def debug_airtable():
    """Debug endpoint to test Airtable connection and data format"""
    try:
        airtable_token = os.environ.get('AIRTABLE_TOKEN')
        airtable_base_id = os.environ.get('AIRTABLE_BASE_ID')
        
        if not airtable_token:
            return {"error": "AIRTABLE_TOKEN not found in environment"}
        if not airtable_base_id:
            return {"error": "AIRTABLE_BASE_ID not found in environment"}
        
        test_record = {
            "records": [{
                "fields": {
                    "Full Name": "Test Candidate",
                    "Party": "Democratic",
                    "Jurisdiction": "Test State",
                    "Office Sought": "House",
                    "Incumbent?": False,
                    "Status": "Active"
                }
            }]
        }
        
        airtable_url = f"https://api.airtable.com/v0/{airtable_base_id}/Candidates"
        headers = {
            "Authorization": f"Bearer {airtable_token}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(airtable_url, headers=headers, json=test_record)
                
                return {
                    "status_code": response.status_code,
                    "response_text": response.text,
                    "test_record": test_record,
                    "url": airtable_url,
                    "token_present": bool(airtable_token),
                    "base_id_present": bool(airtable_base_id)
                }
            except httpx.RequestError as e:
                return {"error": f"HTTP request failed: {str(e)}", "error_type": "request_error"}
            except Exception as e:
                return {"error": f"Unexpected error: {str(e)}", "error_type": "unexpected", "exception_class": str(type(e))}
            
    except Exception as e:
        return {"error": f"Outer exception: {str(e)}", "error_type": "outer", "exception_class": str(type(e))}

@router.get("/cleanup-airtable-duplicates")
async def cleanup_airtable_duplicates():
    """Clean up duplicate records in Airtable based on Source Candidate ID"""
    try:
        airtable_token = os.environ.get('AIRTABLE_TOKEN')
        airtable_base_id = os.environ.get('AIRTABLE_BASE_ID')
        
        if not airtable_token or not airtable_base_id:
            return {"error": "Missing Airtable credentials"}
        
        airtable_url = f"https://api.airtable.com/v0/{airtable_base_id}/Candidates"
        headers = {
            "Authorization": f"Bearer {airtable_token}",
            "Content-Type": "application/json"
        }
        
        # Get all records
        all_records = []
        async with httpx.AsyncClient() as client:
            offset = None
            while True:
                params = {"pageSize": 100}
                if offset:
                    params["offset"] = offset
                
                response = await client.get(airtable_url, headers=headers, params=params)
                if response.status_code != 200:
                    break
                
                data = response.json()
                all_records.extend(data.get('records', []))
                
                offset = data.get('offset')
                if not offset:
                    break
        
        # Find duplicates by Source Candidate ID
        seen_ids = {}
        duplicates = []
        
        for record in all_records:
            source_id = record.get('fields', {}).get('Source Candidate ID')
            if source_id:
                if source_id in seen_ids:
                    duplicates.append(record['id'])
                else:
                    seen_ids[source_id] = record['id']
        
        # Delete duplicates
        deleted_count = 0
        if duplicates:
            # Delete in batches of 10 (Airtable limit)
            for i in range(0, len(duplicates), 10):
                batch = duplicates[i:i+10]
                
                # Use query parameters for delete
                record_ids = "&".join([f"records[]={record_id}" for record_id in batch])
                delete_url = f"{airtable_url}?{record_ids}"
                
                async with httpx.AsyncClient() as client:
                    response = await client.delete(delete_url, headers=headers)
                    if response.status_code == 200:
                        deleted_count += len(batch)
        
        return {
            "status": "completed",
            "total_records_checked": len(all_records),
            "duplicates_found": len(duplicates),
            "duplicates_deleted": deleted_count,
            "unique_candidates_remaining": len(seen_ids)
        }
        
    except Exception as e:
        return {"error": f"Cleanup failed: {str(e)}"}

@router.get("/debug-filings")
async def debug_filings():
    """Debug endpoint to check Filings & Finance table access"""
    try:
        airtable_token = os.environ.get('AIRTABLE_TOKEN')
        airtable_base_id = os.environ.get('AIRTABLE_BASE_ID')
        
        filings_url = f"https://api.airtable.com/v0/{airtable_base_id}/Filings%20%26%20Finance"
        headers = {"Authorization": f"Bearer {airtable_token}"}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(filings_url, headers=headers, params={"pageSize": 1})
            
            return {
                "status_code": response.status_code,
                "response_text": response.text,
                "url": filings_url,
                "headers_sent": list(headers.keys())
            }
            
    except Exception as e:
        return {"error": f"Debug failed: {str(e)}"}

@router.get("/collect-financial-data")
async def collect_financial_data():
    """Collect financial data from FEC reports API for existing candidates"""
    try:
        api_key = os.environ.get('FEC_API_KEY')
        if not api_key:
            return {"error": "FEC_API_KEY not found"}
        
        # Get candidates that need financial data
        candidates_result = db.supabase.table('candidates').select('source_candidate_ID, candidate_name, party').eq('election_cycle', 2026).in_('party', ['DEM', 'IND']).execute()
        candidates = candidates_result.data
        
        if not candidates:
            return {"error": "No candidates found"}
        
        financial_data_collected = 0
        candidates_with_committees = 0
        errors = []
        
        # Process candidates to find their committees and financial data
        for i, candidate in enumerate(candidates):
            try:
                source_candidate_id = candidate.get('source_candidate_ID')
                if not source_candidate_id:
                    continue
                
                # Get committees for this candidate
                committees_url = "https://api.open.fec.gov/v1/committees/"
                committee_params = {
                    'api_key': api_key,
                    'candidate_id': source_candidate_id,
                    'per_page': 100
                }
                
                async with httpx.AsyncClient() as client:
                    committee_response = await client.get(committees_url, params=committee_params)
                    
                    if committee_response.status_code != 200:
                        continue
                    
                    committee_data = committee_response.json()
                    committees = committee_data.get('results', [])
                    
                    if not committees:
                        continue
                    
                    candidates_with_committees += 1
                    
                    # Get financial reports for the primary committee
                    primary_committee = committees[0]
                    committee_id = primary_committee.get('committee_id')
                    
                    if committee_id:
                        # Get latest financial reports
                        reports_url = "https://api.open.fec.gov/v1/reports/"
                        reports_params = {
                            'api_key': api_key,
                            'committee_id': committee_id,
                            'per_page': 10,
                            'sort': '-coverage_end_date'  # Most recent first
                        }
                        
                        reports_response = await client.get(reports_url, params=reports_params)
                        
                        if reports_response.status_code == 200:
                            reports_data = reports_response.json()
                            reports = reports_data.get('results', [])
                            
                            if reports:
                                latest_report = reports[0]
                                
                                # Extract financial data
                                financial_update = {
                                    'cash_on_hand': latest_report.get('cash_on_hand_end_period', 0),
                                    'total_receipts': latest_report.get('total_receipts', 0),
                                    'total_disbursements': latest_report.get('total_disbursements', 0),
                                    'debts_owed': latest_report.get('debts_owed', 0),
                                    'report_date': latest_report.get('coverage_end_date'),
                                    'committee_id': committee_id,
                                    'committee_name': primary_committee.get('name', ''),
                                    'last_financial_update': datetime.utcnow().isoformat()
                                }
                                
                                # Update candidate record with financial data
                                db.supabase.table('candidates').update(financial_update).eq('source_candidate_ID', source_candidate_id).execute()
                                financial_data_collected += 1
                
                # Progress logging every 100 candidates
                if (i + 1) % 100 == 0:
                    print(f"Processed {i + 1} candidates, found financial data for {financial_data_collected}")
                
                # Rate limiting - respect FEC API limits
                await asyncio.sleep(0.2)
                
            except Exception as e:
                errors.append(f"Error processing candidate {source_candidate_id}: {str(e)}")
                continue
        
        return {
            "status": "completed",
            "total_candidates_processed": len(candidates),
            "candidates_with_committees": candidates_with_committees,
            "financial_data_collected": financial_data_collected,
            "errors": errors[:10],
            "next_steps": [
                "Add financial fields back to Airtable as Currency type",
                "Update sync function to include real financial data",
                "Set up quarterly automation for financial updates"
            ]
        }
        
    except Exception as e:
        return {"error": f"Financial collection failed: {str(e)}"}

@router.get("/setup-automated-updates")
async def setup_automated_updates():
    """Information endpoint for setting up automated daily/quarterly updates"""
    return {
        "automation_plan": {
            "daily_updates": {
                "schedule": "Every night at 2 AM EST",
                "functions": [
                    "/collect-democratic-candidates - New candidate registrations",
                    "/collect-filings-urls - New FEC filings and PDF links"
                ],
                "purpose": "Catch new candidates and recent filings"
            },
            "quarterly_updates": {
                "schedule": "Day after FEC reporting deadlines",
                "dates": ["February 1", "April 16", "July 16", "October 16"],
                "functions": [
                    "/collect-financial-data - Updated financial reports",
                    "/sync-to-airtable-complete - Refresh Airtable with new financial data"
                ],
                "purpose": "Update financial totals when new quarterly reports are filed"
            }
        },
        "implementation_options": {
            "railway_cron": "Use Railway's built-in cron job scheduling",
            "external_service": "Use GitHub Actions or external scheduler to ping endpoints",
            "webhook_triggers": "Set up webhooks for FEC filing notifications (advanced)"
        },
        "monitoring": {
            "success_metrics": "Track collection counts and sync success rates",
            "failure_alerts": "Email notifications for API failures or data anomalies",
            "data_quality": "Automated checks for missing financial data or broken links"
        }
    }

@router.get("/sync-filings-only")
async def sync_filings_only():
    """Create filing records without financial fields - bypass deployment cache"""
    try:
        airtable_token = os.environ.get('AIRTABLE_TOKEN')
        airtable_base_id = os.environ.get('AIRTABLE_BASE_ID')
        
        if not airtable_token or not airtable_base_id:
            return {"error": "Missing Airtable credentials"}
        
        # Get candidates from database
        candidates = []
        page_size = 1000
        offset = 0

        while True:
            batch_result = db.supabase.table('candidates').select('*').eq('election_cycle', 2026).in_('party', ['DEM', 'IND']).range(offset, offset + page_size - 1).execute()
            
            if not batch_result.data:
                break
                
            candidates.extend(batch_result.data)
            
            if len(batch_result.data) < page_size:
                break
                
            offset += page_size
        
        if not candidates:
            return {"error": "No candidates found"}
        
        # Get existing Airtable candidate records
        airtable_url = f"https://api.airtable.com/v0/{airtable_base_id}/Candidates"
        headers = {"Authorization": f"Bearer {airtable_token}", "Content-Type": "application/json"}
        
        existing_candidates = {}
        async with httpx.AsyncClient() as client:
            offset = None
            while True:
                params = {"pageSize": 100}
                if offset:
                    params["offset"] = offset
                
                response = await client.get(airtable_url, headers=headers, params=params)
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
        
        # Create filing records
        filings_url = f"https://api.airtable.com/v0/{airtable_base_id}/Filings%20%26%20Finance"
        filings_synced = 0
        errors = []
        
        for i in range(0, len(candidates), 10):
            candidate_batch = candidates[i:i+10]
            filing_records = []
            
            for candidate in candidate_batch:
                source_candidate_id = candidate.get('source_candidate_ID')
                
                if not source_candidate_id:
                    continue
                
                # Get candidate record ID for linking
                candidate_record_id = existing_candidates.get(source_candidate_id)
                if not candidate_record_id:
                    continue
                
                # Create filing record with minimal fields
                filing_record = {
                    "fields": {
                        "Filing ID": source_candidate_id,
                        "Candidate": [candidate_record_id],
                        "Filing Date": datetime.now().strftime('%Y-%m-%d'),
                        "Committee Name": str(candidate.get('candidate_name', '')),
                        "CommitteeID": source_candidate_id,
                        "Last Report Date": datetime.now().strftime('%Y-%m-%d'),
                        "Funding Source Link": ""
                    }
                }
                filing_records.append(filing_record)
            
            # Sync filing batch
            if filing_records:
                try:
                    if (i // 10 + 1) % 25 == 0:
                        print(f"Syncing filing batch {i // 10 + 1}")
                    
                    async with httpx.AsyncClient() as client:
                        response = await client.post(
                            filings_url,
                            headers=headers,
                            json={"records": filing_records}
                        )
                        
                        if response.status_code == 200:
                            response_data = response.json()
                            filings_synced += len(response_data.get('records', []))
                        else:
                            errors.append(f"Filing batch {i // 10 + 1} failed: {response.status_code} - {response.text}")
                            
                except Exception as e:
                    errors.append(f"Filing batch {i // 10 + 1} error: {str(e)}")
            
            await asyncio.sleep(0.1)
        
        return {
            "status": "completed",
            "filings_synced": filings_synced,
            "total_candidates": len(candidates),
            "errors": errors[:5]
        }
        
    except Exception as e:
        return {"error": f"Sync failed: {str(e)}"}

@router.get("/sync-to-airtable-complete")
async def sync_to_airtable_complete():
    """Complete sync with all schema fields and proper linked records - Democrats and Independents only"""
    try:
        airtable_token = os.environ.get('AIRTABLE_TOKEN')
        airtable_base_id = os.environ.get('AIRTABLE_BASE_ID')
        
        if not airtable_token or not airtable_base_id:
            return {"error": "Missing Airtable credentials"}
        
        def map_party(party_code):
            if not party_code:
                return "Other"
            party_code = str(party_code).upper()
            if party_code in ["DEM", "DEMOCRATIC"]:
                return "Democratic"
            elif party_code in ["REP", "REPUBLICAN"]:
                return "Republican"
            elif party_code in ["IND", "INDEPENDENT"]:
                return "Independent"
            else:
                return "Other"
        
        # Paginated fetching to handle large datasets
        candidates = []
        page_size = 1000
        offset = 0

        while True:
            batch_result = db.supabase.table('candidates').select('*').eq('election_cycle', 2026).in_('party', ['DEM', 'IND']).range(offset, offset + page_size - 1).execute()
            
            if not batch_result.data:
                break
                
            candidates.extend(batch_result.data)
            
            if len(batch_result.data) < page_size:
                break
                
            offset += page_size
        
        if not candidates:
            return {"error": "No Democratic or Independent candidates found for 2026"}
        
        # Get existing Airtable records with pagination
        airtable_url = f"https://api.airtable.com/v0/{airtable_base_id}/Candidates"
        headers = {"Authorization": f"Bearer {airtable_token}", "Content-Type": "application/json"}
        
        existing_candidates = {}
        async with httpx.AsyncClient() as client:
            offset = None
            while True:
                params = {"pageSize": 100}
                if offset:
                    params["offset"] = offset
                
                response = await client.get(airtable_url, headers=headers, params=params)
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
        
        # Track what we process in this sync run
        processed_in_this_sync = set()
        candidates_synced = 0
        filings_synced = 0
        errors = []
        
        # Process candidates in batches of 10
        for i in range(0, len(candidates), 10):
            candidate_batch = candidates[i:i+10]
            candidate_records = []
            
            for candidate in candidate_batch:
                source_candidate_id = candidate.get('source_candidate_ID')  # Capital ID
                
                # Skip if already processed or exists
                if not source_candidate_id or source_candidate_id in processed_in_this_sync or source_candidate_id in existing_candidates:
                    continue
                
                # Create candidate record
                candidate_record = {
                    "fields": {
                        "Source Candidate ID": source_candidate_id,
                        "Full Name": str(candidate.get('candidate_name', '')),
                        "Party": map_party(candidate.get('party')),
                        "Jurisdiction": str(candidate.get('jurisdiction_name', '')),
                        "Office Sought": str(candidate.get('office', '')),
                        "Incumbent?": candidate.get('incumbent_challenger') == 'I',
                        "Current Position": str(candidate.get('incumbent_challenger', '')),
                        "Bio Summary": f"Candidate for {candidate.get('office', 'Unknown')} in {candidate.get('state', 'Unknown')}",
                        "Confidence Flag": "Medium",
                        "Status": candidate.get('candidate_status', 'Active')
                    }
                }
                candidate_records.append(candidate_record)
                processed_in_this_sync.add(source_candidate_id)
            
            # Sync candidate batch if we have records to create
            if candidate_records:
                try:
                    # Minimal logging - only every 25th batch
                    if (i // 10 + 1) % 25 == 0:
                        print(f"Syncing candidate batch {i // 10 + 1}")
                    
                    async with httpx.AsyncClient() as client:
                        response = await client.post(
                            airtable_url,
                            headers=headers,
                            json={"records": candidate_records}
                        )
                        
                        if response.status_code == 200:
                            response_data = response.json()
                            candidates_synced += len(response_data.get('records', []))
                            
                            # Update existing candidates map with new records
                            for record in response_data.get('records', []):
                                source_id = record.get('fields', {}).get('Source Candidate ID')
                                if source_id:
                                    existing_candidates[source_id] = record['id']
                        else:
                            errors.append(f"Candidate batch {i // 10 + 1} failed: {response.status_code} - {response.text}")
                            
                except Exception as e:
                    errors.append(f"Candidate batch {i // 10 + 1} error: {str(e)}")
            
            # Small delay to respect rate limits
            await asyncio.sleep(0.1)
        
        # Create filing records for all candidates (existing + new)
        filings_url = f"https://api.airtable.com/v0/{airtable_base_id}/Filings%20%26%20Finance"
        
        # Get existing filing records to avoid duplicates
        existing_filings = set()
        async with httpx.AsyncClient() as client:
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
                    filing_id = record.get('fields', {}).get('Filing ID')
                    if filing_id:
                        existing_filings.add(filing_id)
                
                offset = data.get('offset')
                if not offset:
                    break
        
        # Create filing records in batches
        for i in range(0, len(candidates), 10):
            candidate_batch = candidates[i:i+10]
            filing_records = []
            
            for candidate in candidate_batch:
                source_candidate_id = candidate.get('source_candidate_ID')  # Capital ID
                
                # Skip if filing already exists
                if not source_candidate_id or source_candidate_id in existing_filings:
                    continue
                
                # Get candidate record ID for linking
                candidate_record_id = existing_candidates.get(source_candidate_id)
                if not candidate_record_id:
                    continue
                
                # Create filing record with only writable fields
                filing_record = {
                    "fields": {
                        "Filing ID": source_candidate_id,
                        "Candidate": [candidate_record_id],
                        "Filing Date": datetime.now().strftime('%Y-%m-%d'),
                        "Committee Name": str(candidate.get('candidate_name', '')),
                        "CommitteeID": source_candidate_id,  # Fixed: no space
                        "COH $": 0,
                        "Total Raised": 0,
                        "Total Spent": 0,
                        "Last Report Date": datetime.now().strftime('%Y-%m-%d'),
                        "Funding Source Link": ""
                    }
                }
                filing_records.append(filing_record)
            
            # Sync filing batch
            if filing_records:
                try:
                    # Minimal logging - only every 25th batch
                    if (i // 10 + 1) % 25 == 0:
                        print(f"Syncing filing batch {i // 10 + 1}")
                    
                    async with httpx.AsyncClient() as client:
                        response = await client.post(
                            filings_url,
                            headers=headers,
                            json={"records": filing_records}
                        )
                        
                        if response.status_code == 200:
                            response_data = response.json()
                            filings_synced += len(response_data.get('records', []))
                        else:
                            errors.append(f"Filing batch {i // 10 + 1} failed: {response.status_code} - {response.text}")
                            
                except Exception as e:
                    errors.append(f"Filing batch {i // 10 + 1} error: {str(e)}")
            
            await asyncio.sleep(0.1)
        
        return {
            "status": "completed",
            "filter": "Democrats and Independents only, 2026 cycle",
            "candidates_synced": candidates_synced,
            "filings_synced": filings_synced,
            "total_candidates": len(candidates),
            "total_existing_in_airtable": len(existing_candidates) - candidates_synced,
            "errors": errors[:10]  # Limit error output
        }
        
    except Exception as e:
        return {"error": f"Sync failed: {str(e)}"}
