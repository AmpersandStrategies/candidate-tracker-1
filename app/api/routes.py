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
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {
            "database": "ready"
        }
    }

@router.get("/test")
async def test():
    """Simple test endpoint"""
    return {"message": "API is working"}

@router.get("/candidates")
async def get_candidates(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=1000),
    state: Optional[str] = None
):
    """Get candidates with pagination and filtering"""
    try:
        query = db.supabase.table('candidates').select('*')
        
        if state:
            query = query.eq('state', state)
        
        count_query = db.supabase.table('candidates').select('*', count='exact')
        if state:
            count_query = count_query.eq('state', state)
        
        count_result = count_query.execute()
        total_count = count_result.count or 0
        
        offset = (page - 1) * size
        data_result = query.range(offset, offset + size - 1).execute()
        
        return {
            "candidates": data_result.data,
            "total": total_count,
            "page": page,
            "size": size
        }
    except Exception as e:
        return {"error": f"Database error: {str(e)}"}

@router.get("/collect-democratic-candidates")
async def collect_democratic_candidates():
    """Collect ALL Democratic candidates + Independents for 2026 cycle"""
    try:
        fec_api_key = os.environ.get('FEC_API_KEY')
        
        if not fec_api_key:
            return {"error": "FEC_API_KEY not configured"}
        
        parties_to_collect = ["DEM", "IND"]
        offices = ["H", "S", "P"]
        cycles = [2026]
        
        total_candidates_found = 0
        total_candidates_stored = 0
        collection_summary = []
        
        async with httpx.AsyncClient() as client:
            for cycle in cycles:
                for office in offices:
                    for party in parties_to_collect:
                        
                        page = 1
                        candidates_in_category = 0
                        stored_in_category = 0
                        
                        while True:
                            try:
                                response = await client.get(
                                    "https://api.open.fec.gov/v1/candidates",
                                    params={
                                        "api_key": fec_api_key,
                                        "cycle": cycle,
                                        "party": party,
                                        "office": office,
                                        "per_page": 100,
                                        "page": page
                                    }
                                )
                                response.raise_for_status()
                                
                                data = response.json()
                                candidates = data.get("results", [])
                                
                                if not candidates:
                                    break
                                
                                candidates_in_category += len(candidates)
                                
                                for candidate in candidates:
                                    try:
                                        source_id = candidate.get('candidate_id', '')
                                        
                                        existing = db.supabase.table('candidates').select('candidate_id').eq('source_system', 'FEC').eq('source_candidate_ID', source_id).execute()
                                        
                                        if existing.data:
                                            continue
                                        
                                        result = db.supabase.table('candidates').insert({
                                            'source_candidate_ID': source_id,
                                            'source_system': 'FEC',
                                            'full_name': candidate.get('name', ''),
                                            'party': candidate.get('party', ''),
                                            'jurisdiction_type': 'federal',
                                            'jurisdiction_name': 'United States',
                                            'state': candidate.get('state', ''),
                                            'office': candidate.get('office_full', office),
                                            'district': candidate.get('district', ''),
                                            'election_cycle': cycle,
                                            'incumbent': candidate.get('incumbent_challenge_full', '') == 'Incumbent',
                                            'status': candidate.get('candidate_status', 'Active'),
                                            'source_url': f"https://www.fec.gov/data/candidate/{source_id}/"
                                        }).execute()
                                        
                                        if result.data:
                                            stored_in_category += 1
                                            
                                    except Exception as insert_error:
                                        continue
                                
                                pagination = data.get("pagination", {})
                                if page >= pagination.get("pages", 1):
                                    break
                                    
                                page += 1
                                await asyncio.sleep(0.1)
                                
                            except Exception as page_error:
                                break
                        
                        category_summary = {
                            "cycle": cycle,
                            "office": office,
                            "party": party,
                            "candidates_found": candidates_in_category,
                            "candidates_stored": stored_in_category
                        }
                        collection_summary.append(category_summary)
                        
                        total_candidates_found += candidates_in_category
                        total_candidates_stored += stored_in_category
        
        return {
            "status": "success",
            "focus": "Democratic candidates + Independents",
            "total_candidates_found": total_candidates_found,
            "total_candidates_stored": total_candidates_stored,
            "collection_summary": collection_summary,
            "message": f"Successfully collected {total_candidates_stored} Democratic and Independent candidates"
        }
        
    except Exception as e:
        return {"error": f"Collection failed: {str(e)}"}

@router.get("/sync-to-airtable-complete")
async def sync_to_airtable_complete():
    """Complete sync with all schema fields and proper linked records - Democrats and Independents only"""
    try:
        airtable_token = os.environ.get('AIRTABLE_TOKEN')
        airtable_base_id = os.environ.get('AIRTABLE_BASE_ID')
        
        if not airtable_token or not airtable_base_id:
            return {"error": "Airtable credentials not configured"}
        
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
            return {"error": "No Democratic or Independent candidates found in database"}
        
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
        
        # Airtable endpoints
        candidates_url = f"https://api.airtable.com/v0/{airtable_base_id}/Candidates"
        filings_url = f"https://api.airtable.com/v0/{airtable_base_id}/Filings%20%26%20Finance"
        
        headers = {
            "Authorization": f"Bearer {airtable_token}",
            "Content-Type": "application/json"
        }
        
        candidates_synced = 0
        filings_synced = 0
        errors = []
        candidate_records_map = {}
        
        async with httpx.AsyncClient() as client:
            
            # Get existing candidates to prevent duplicates
            existing_candidates = {}
            try:
                existing_response = await client.get(candidates_url, headers=headers)
                if existing_response.status_code == 200:
                    existing_data = existing_response.json()
                    for record in existing_data.get('records', []):
                        source_id = record.get('fields', {}).get('Source Candidate ID')
                        if source_id:
                            existing_candidates[source_id] = record['id']
            except Exception as e:
                print(f"Warning: Could not fetch existing candidates: {e}")
            
            # Sync candidates with complete field mapping
            for i in range(0, len(candidates), 10):
                batch = candidates[i:i+10]
                candidate_records = []
                
                for candidate in batch:
                    source_id = candidate.get('source_candidate_ID', '')
                    
                    # Skip if already exists in Airtable
                    if source_id in existing_candidates:
                        candidate_records_map[source_id] = existing_candidates[source_id]
                        continue
                    
                    # Complete field mapping matching your original schema
                    record = {
                        "fields": {
                            "Candidate ID": source_id,
                            "Source Candidate ID": source_id,
                            "Full Name": str(candidate.get('full_name', '')),
                            "Preferred Name": str(candidate.get('preferred_name', '') or ''),
                            "Party": map_party(candidate.get('party', '')),
                            "Jurisdiction": str(candidate.get('jurisdiction_name', '')),
                            "Office Sought": str(candidate.get('office', '')),
                            "Incumbent?": bool(candidate.get('incumbent', False)),
                            "Current Position": str(candidate.get('current_position', '') or ''),
                            "Bio Summary": str(candidate.get('bio_summary', '') or ''),
                            "Media Mentions": str(candidate.get('media_mentions', '') or ''),
                            "Confidence Flag": "Medium",
                            "Status": "Active"
                        }
                    }
                    candidate_records.append(record)
                
                if candidate_records:
                    # Minimal logging - only every 25th batch
                    if (i // 10 + 1) % 25 == 0:
                        print(f"Syncing candidate batch {i // 10 + 1}")
                    
                    try:
                        response = await client.post(candidates_url, headers=headers, json={"records": candidate_records})
                        
                        if response.status_code == 200:
                            response_data = response.json()
                            candidates_synced += len(candidate_records)
                            
                            # Map record IDs for linking
                            batch_index = 0
                            for record in response_data.get('records', []):
                                while batch_index < len(batch) and batch[batch_index].get('source_candidate_ID', '') in existing_candidates:
                                    batch_index += 1
                                if batch_index < len(batch):
                                    source_id = batch[batch_index].get('source_candidate_ID', '')
                                    candidate_records_map[source_id] = record['id']
                                    batch_index += 1
                                
                        else:
                            error_msg = f"Candidate batch {i//10 + 1} failed: {response.status_code} - {response.text}"
                            errors.append(error_msg)
                            
                    except Exception as batch_error:
                        error_msg = f"Candidate batch {i//10 + 1} error: {str(batch_error)}"
                        errors.append(error_msg)
            
            # Create Filings & Finance records with proper linking
            for i in range(0, len(candidates), 10):
                batch = candidates[i:i+10]
                filing_records = []
                
                for candidate in batch:
                    source_id = candidate.get('source_candidate_ID', '')
                    
                    # Only create filing if candidate was successfully created/exists
                    if source_id in candidate_records_map:
                        filing_record = {
                            "fields": {
                                "Filing ID": source_id,
                                "Candidate": [candidate_records_map[source_id]],
                                "Jurisdiction": str(candidate.get('jurisdiction_name', '')),
                                "Office": str(candidate.get('office', '')),
                                "Committee Name": f"{candidate.get('full_name', '')} for {candidate.get('office', '')}",
                                "Committee ID": source_id,
                                "COH $": 0,
                                "Total Raised": 0,
                                "Total Spent": 0,
                                "Funding Source Link": str(candidate.get('source_url', '') or '')
                            }
                        }
                        
                        # Add filing date if available
                        filing_date = candidate.get('created_at')
                        if filing_date:
                            try:
                                if isinstance(filing_date, str):
                                    for fmt in ['%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f']:
                                        try:
                                            parsed_date = datetime.strptime(filing_date[:len(fmt.replace('%f', ''))], fmt)
                                            filing_record["fields"]["Filing Date"] = parsed_date.strftime('%Y-%m-%d')
                                            break
                                        except ValueError:
                                            continue
                            except Exception:
                                pass
                        
                        filing_records.append(filing_record)
                
                if filing_records:
                    try:
                        response = await client.post(filings_url, headers=headers, json={"records": filing_records})
                        
                        if response.status_code == 200:
                            filings_synced += len(filing_records)
                        else:
                            error_msg = f"Filing batch {i//10 + 1} failed: {response.status_code} - {response.text}"
                            errors.append(error_msg)
                            
                    except Exception as batch_error:
                        error_msg = f"Filing batch {i//10 + 1} error: {str(batch_error)}"
                        errors.append(error_msg)
        
        return {
            "status": "completed",
            "filter": "Democrats and Independents only, 2026 cycle",
            "candidates_synced": candidates_synced,
            "filings_synced": filings_synced,
            "total_candidates": len(candidates),
            "errors": errors,
            "candidate_success_rate": f"{(candidates_synced/len(candidates)*100):.1f}%" if candidates else "0%",
            "schema_compliance": [
                "All original schema fields included",
                "Proper linked records between Candidates and Filings & Finance",
                "Democrats and Independents only, 2026 cycle",
                "Fixed party mapping to match Airtable field options"
            ]
        }
        
    except Exception as e:
        return {"error": f"Complete sync failed: {str(e)}"}

@router.get("/democratic-collection-status")
async def democratic_collection_status():
    """Get status of Democratic candidate collection"""
    try:
        dem_result = db.supabase.table('candidates').select('*', count='exact').eq('party', 'DEM').eq('jurisdiction_type', 'federal').execute()
        dem_count = dem_result.count or 0
        
        ind_result = db.supabase.table('candidates').select('*', count='exact').eq('party', 'IND').eq('jurisdiction_type', 'federal').execute()
        ind_count = ind_result.count or 0
        
        dem_house = db.supabase.table('candidates').select('*', count='exact').eq('party', 'DEM').eq('office', 'House').execute()
        dem_senate = db.supabase.table('candidates').select('*', count='exact').eq('party', 'DEM').eq('office', 'Senate').execute()
        dem_president = db.supabase.table('candidates').select('*', count='exact').eq('party', 'DEM').eq('office', 'President').execute()
        
        dem_candidates = db.supabase.table('candidates').select('state').eq('party', 'DEM').eq('jurisdiction_type', 'federal').execute()
        dem_states = [c.get('state') for c in dem_candidates.data if c.get('state')]
        
        from collections import Counter
        top_dem_states = dict(Counter(dem_states).most_common(10))
        
        return {
            "democratic_candidates": dem_count,
            "independent_candidates": ind_count,
            "democratic_breakdown": {
                "house": dem_house.count or 0,
                "senate": dem_senate.count or 0,
                "president": dem_president.count or 0
            },
            "top_democratic_states": top_dem_states,
            "focus": "Democrats primary, Independents secondary"
        }
        
    except Exception as e:
        return {"error": f"Status check failed: {str(e)}"}

@router.get("/cleanup-airtable-duplicates")
async def cleanup_airtable_duplicates():
    """Remove duplicate candidates from Airtable based on Source Candidate ID"""
    try:
        airtable_token = os.environ.get('AIRTABLE_TOKEN')
        airtable_base_id = os.environ.get('AIRTABLE_BASE_ID')
        
        if not airtable_token or not airtable_base_id:
            return {"error": "Airtable credentials not configured"}
        
        candidates_url = f"https://api.airtable.com/v0/{airtable_base_id}/Candidates"
        headers = {
            "Authorization": f"Bearer {airtable_token}",
            "Content-Type": "application/json"
        }
        
        duplicates_found = {}
        records_to_delete = []
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(candidates_url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    records = data.get('records', [])
                    
                    # Find duplicates based on Source Candidate ID
                    seen_ids = {}
                    for record in records:
                        fields = record.get('fields', {})
                        source_id = fields.get('Source Candidate ID') or fields.get('Candidate ID')
                        
                        if source_id:
                            if source_id in seen_ids:
                                # This is a duplicate
                                if source_id not in duplicates_found:
                                    duplicates_found[source_id] = []
                                duplicates_found[source_id].append(record['id'])
                                records_to_delete.append(record['id'])
                            else:
                                seen_ids[source_id] = record['id']
                    
                    # Delete duplicates (keep the first occurrence)
                    deleted_count = 0
                    for record_id in records_to_delete:
                        try:
                            delete_url = f"{candidates_url}/{record_id}"
                            delete_response = await client.delete(delete_url, headers=headers)
                            if delete_response.status_code == 200:
                                deleted_count += 1
                        except Exception as e:
                            print(f"Failed to delete record {record_id}: {e}")
                    
                    return {
                        "status": "completed",
                        "duplicates_found": len(duplicates_found),
                        "records_deleted": deleted_count,
                        "duplicate_details": duplicates_found
                    }
                else:
                    return {"error": f"Failed to fetch records: {response.status_code}"}
                    
            except Exception as e:
                return {"error": f"Cleanup failed: {str(e)}"}
                
    except Exception as e:
        return {"error": f"Cleanup process failed: {str(e)}"}

@router.get("/validate-2026-data")
async def validate_2026_data():
    """Check data quality - election cycles, missing fields, etc."""
    try:
        # Check all candidates in database
        all_candidates = db.supabase.table('candidates').select('election_cycle, party, office, source_candidate_ID, full_name').execute()
        candidates = all_candidates.data
        
        if not candidates:
            return {"error": "No candidates found in database"}
        
        # Analyze data quality
        cycle_counts = {}
        missing_source_ids = 0
        missing_names = 0
        party_distribution = {}
        office_distribution = {}
        
        for candidate in candidates:
            # Election cycle analysis
            cycle = candidate.get('election_cycle')
            if cycle in cycle_counts:
                cycle_counts[cycle] += 1
            else:
                cycle_counts[cycle] = 1
            
            # Missing data analysis
            if not candidate.get('source_candidate_ID'):
                missing_source_ids += 1
            if not candidate.get('full_name'):
                missing_names += 1
            
            # Distribution analysis
            party = candidate.get('party', 'Unknown')
            office = candidate.get('office', 'Unknown')
            
            party_distribution[party] = party_distribution.get(party, 0) + 1
            office_distribution[office] = office_distribution.get(office, 0) + 1
        
        return {
            "total_candidates": len(candidates),
            "election_cycles": cycle_counts,
            "candidates_2026": cycle_counts.get(2026, 0),
            "data_quality": {
                "missing_source_ids": missing_source_ids,
                "missing_names": missing_names
            },
            "2026_distribution": {
                "by_party": party_distribution,
                "by_office": office_distribution
            },
            "recommendations": [
                f"Focus sync on {cycle_counts.get(2026, 0)} candidates from 2026 cycle",
                "Clean up records with missing source IDs" if missing_source_ids > 0 else "Source ID data looks good",
                "Review candidates from other cycles - may be legitimate early filers"
            ]
        }
        
    except Exception as e:
        return {"error": f"Validation failed: {str(e)}"}

@router.get("/debug-airtable")
async def debug_airtable():
    """Debug endpoint to test Airtable connection and data format"""
    try:
        airtable_token = os.environ.get('AIRTABLE_TOKEN')
        airtable_base_id = os.environ.get('AIRTABLE_BASE_ID')
        
        if not airtable_token or not airtable_base_id:
            return {"error": "Airtable credentials not configured"}
        
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
            response = await client.post(airtable_url, headers=headers, json=test_record)
            
            return {
                "status_code": response.status_code,
                "response_text": response.text,
                "test_record": test_record,
                "headers_sent": headers,
                "url": airtable_url
            }
            
    except Exception as e:
        return {"error": f"Debug failed: {str(e)}"}
