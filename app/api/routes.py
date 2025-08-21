"""FastAPI routes"""
from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime
from app.db.client import db
import os
import httpx
import json

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

@router.get("/collect-fec-data")
async def collect_fec_data():
    """Collect FEC candidates"""
    try:
        fec_api_key = os.environ.get('FEC_API_KEY')
        
        if not fec_api_key:
            return {"error": "FEC_API_KEY not configured"}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.open.fec.gov/v1/candidates",
                params={
                    "api_key": fec_api_key,
                    "cycle": 2026,
                    "party": "DEM",
                    "office": "H",
                    "per_page": 20
                }
            )
            response.raise_for_status()
            
            data = response.json()
            candidates = data.get("results", [])
            
            stored_count = 0
            for candidate in candidates:
                try:
                    result = db.supabase.table('candidates').insert({
                        'full_name': candidate.get('name', ''),
                        'party': candidate.get('party', ''),
                        'jurisdiction_type': 'federal',
                        'jurisdiction_name': 'United States',
                        'state': candidate.get('state', ''),
                        'office': candidate.get('office_full', 'House'),
                        'district': candidate.get('district', ''),
                        'election_cycle': 2026,
                        'incumbent': candidate.get('incumbent_challenge', '') == 'I',
                        'source_url': f"https://www.fec.gov/data/candidate/{candidate.get('candidate_id', '')}/"
                    }).execute()
                    
                    if result.data:
                        stored_count += 1
                except Exception as insert_error:
                    print(f"Failed to insert candidate: {insert_error}")
                    continue
            
            return {
                "status": "success",
                "candidates_found": len(candidates),
                "candidates_stored": stored_count
            }
    except Exception as e:
        return {"error": f"Collection failed: {str(e)}"}

@router.get("/sync-to-airtable")
async def sync_to_airtable():
    """Sync candidates to Airtable with detailed debugging"""
    try:
        airtable_token = os.environ.get('AIRTABLE_TOKEN')
        airtable_base_id = os.environ.get('AIRTABLE_BASE_ID')
        
        if not airtable_token or not airtable_base_id:
            return {"error": "Airtable credentials not configured"}
        
        # Get candidates from database
        candidates_result = db.supabase.table('candidates').select('*').execute()
        candidates = candidates_result.data
        
        if not candidates:
            return {"error": "No candidates found in database"}
        
        print(f"Found {len(candidates)} candidates to sync")
        
        # Map party codes to Airtable values
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
        
        airtable_url = f"https://api.airtable.com/v0/{airtable_base_id}/Candidates"
        headers = {
            "Authorization": f"Bearer {airtable_token}",
            "Content-Type": "application/json"
        }
        
        synced_count = 0
        errors = []
        
        # Process in batches of 10 (Airtable limit)
        async with httpx.AsyncClient() as client:
            for i in range(0, len(candidates), 10):
                batch = candidates[i:i+10]
                records = []
                
                for candidate in batch:
                    # Debug: Print candidate data
                    print(f"Processing candidate: {candidate.get('full_name', 'Unknown')}")
                    
                    record = {
                        "fields": {
                            "Full Name": str(candidate.get('full_name', '')),
                            "Party": map_party(candidate.get('party', '')),
                            "Jurisdiction": str(candidate.get('jurisdiction_name', '')),
                            "Office Sought": str(candidate.get('office', '')),
                            "Incumbent?": bool(candidate.get('incumbent', False)),
                            "Status": "Active"
                        }
                    }
                    records.append(record)
                
                # Debug: Print what we're sending
                print(f"Sending batch {i//10 + 1} with {len(records)} records")
                payload = {"records": records}
                print(f"Payload preview: {json.dumps(payload, indent=2)[:500]}...")
                
                try:
                    response = await client.post(airtable_url, headers=headers, json=payload)
                    
                    if response.status_code == 200:
                        synced_count += len(records)
                        print(f"Successfully synced batch {i//10 + 1}")
                    else:
                        error_msg = f"Batch {i//10 + 1} failed: {response.status_code} - {response.text}"
                        print(error_msg)
                        errors.append(error_msg)
                        
                except Exception as batch_error:
                    error_msg = f"Batch {i//10 + 1} error: {str(batch_error)}"
                    print(error_msg)
                    errors.append(error_msg)
        
        return {
            "status": "completed",
            "candidates_synced": synced_count,
            "total_candidates": len(candidates),
            "errors": errors,
            "success_rate": f"{(synced_count/len(candidates)*100):.1f}%" if candidates else "0%"
        }
        
    except Exception as e:
        return {"error": f"Sync failed: {str(e)}"}

@router.get("/check-party-values")
async def check_party_values():
    """Check what party values exist in the data"""
    try:
        candidates_result = db.supabase.table('candidates').select('party').execute()
        parties = [c.get('party') for c in candidates_result.data if c.get('party')]
        unique_parties = list(set(parties))
        return {
            "unique_parties": unique_parties, 
            "count": len(parties),
            "sample_parties": parties[:10]
        }
    except Exception as e:
        return {"error": f"Failed to check parties: {str(e)}"}

@router.get("/debug-airtable")
async def debug_airtable():
    """Debug endpoint to test Airtable connection and data format"""
    try:
        airtable_token = os.environ.get('AIRTABLE_TOKEN')
        airtable_base_id = os.environ.get('AIRTABLE_BASE_ID')
        
        if not airtable_token or not airtable_base_id:
            return {"error": "Airtable credentials not configured"}
        
        # Test with just one simple record
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
