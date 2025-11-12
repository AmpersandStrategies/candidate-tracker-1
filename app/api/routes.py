"""FastAPI routes - Debug Version"""
from fastapi import APIRouter
from datetime import datetime
import httpx
import os
from app.db.client import db

router = APIRouter()

@router.get("/healthz")
async def health_check():
    """Health check endpoint"""
    try:
        result = db.supabase.table('candidates').select("count", count='exact').execute()
        candidate_count = result.count if hasattr(result, 'count') else 0
        db_status = "connected"
    except Exception as e:
        candidate_count = 0
        db_status = f"error: {str(e)}"
    
    return {
        "status": "healthy",
        "version": "2.0.1-debug",
        "timestamp": datetime.utcnow().isoformat(),
        "database": {
            "status": db_status,
            "candidate_count": candidate_count
        }
    }


@router.get("/test-single-insert")
async def test_single_insert():
    """Test inserting a single candidate to see what fails"""
    try:
        # Try to insert one simple record
        test_record = {
            'source_candidate_id': 'H6CA00000',
            'candidate_name': 'TEST CANDIDATE',
            'party': 'Democratic',
            'jurisdiction_type': 'federal',
            'jurisdiction_name': 'United States',
            'state': 'CA',
            'office': 'House',
            'district': '01',
            'election_cycle': 2026,
            'incumbent': False,
            'candidate_status': 'C',
            'source_url': 'https://www.fec.gov/test'
        }
        
        result = db.supabase.table('candidates').insert(test_record).execute()
        
        return {
            "status": "success",
            "result_data": result.data,
            "result_count": len(result.data) if result.data else 0,
            "test_record": test_record
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "test_record": test_record
        }


@router.get("/check-table-schema")
async def check_table_schema():
    """Check what columns exist in the candidates table"""
    try:
        # Try to get one record to see the schema
        result = db.supabase.table('candidates').select("*").limit(1).execute()
        
        if result.data and len(result.data) > 0:
            columns = list(result.data[0].keys())
        else:
            # Table is empty, try to see error message
            columns = "Table empty - cannot determine schema"
        
        return {
            "status": "success",
            "columns_found": columns,
            "record_count": len(result.data) if result.data else 0
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/collect-2026-house-democrats-verbose")
async def collect_2026_house_democrats_verbose():
    """
    Collect 2026 House Democrats with FULL error reporting.
    This will show us exactly what's failing.
    """
    fec_api_key = os.environ.get('FEC_API_KEY')
    if not fec_api_key:
        return {"error": "FEC_API_KEY not configured"}
    
    candidates_collected = 0
    candidates_stored = 0
    errors = []
    sample_candidate = None
    sample_error = None
    
    try:
        base_url = "https://api.open.fec.gov/v1/candidates/"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Just get first page for debugging
            params = {
                "api_key": fec_api_key,
                "election_year": 2026,
                "office": "H",
                "party": "DEM",
                "per_page": 5,  # Just 5 for testing
                "page": 1,
                "sort": "name"
            }
            
            response = await client.get(base_url, params=params)
            
            if response.status_code != 200:
                return {"error": f"FEC API error: {response.status_code}"}
            
            data = response.json()
            candidates = data.get('results', [])
            candidates_collected = len(candidates)
            
            # Save first one as sample
            if candidates:
                sample_candidate = candidates[0]
            
            # Try to store each one
            for candidate in candidates:
                try:
                    candidate_record = {
                        'source_candidate_id': candidate.get('candidate_id'),
                        'candidate_name': candidate.get('name'),
                        'party': 'Democratic',
                        'jurisdiction_type': 'federal',
                        'jurisdiction_name': 'United States',
                        'state': candidate.get('state'),
                        'office': 'House',
                        'district': candidate.get('district'),
                        'election_cycle': 2026,
                        'incumbent': candidate.get('incumbent_challenge') == 'I',
                        'candidate_status': candidate.get('candidate_status'),
                        'source_url': f"https://www.fec.gov/data/candidate/{candidate.get('candidate_id')}/"
                    }
                    
                    result = db.supabase.table('candidates').insert(candidate_record).execute()
                    
                    if result.data:
                        candidates_stored += 1
                    else:
                        errors.append(f"Insert returned no data for {candidate.get('name')}")
                        if not sample_error:
                            sample_error = {
                                "candidate": candidate.get('name'),
                                "record": candidate_record,
                                "result": "No data returned"
                            }
                        
                except Exception as e:
                    error_detail = {
                        "candidate": candidate.get('name'),
                        "error_type": type(e).__name__,
                        "error_message": str(e)
                    }
                    errors.append(error_detail)
                    if not sample_error:
                        sample_error = error_detail
        
        return {
            "status": "completed",
            "candidates_collected_from_fec": candidates_collected,
            "candidates_stored_in_database": candidates_stored,
            "sample_fec_candidate": sample_candidate,
            "sample_error": sample_error,
            "total_errors": len(errors),
            "all_errors": errors[:10]  # Show first 10 errors
        }
        
    except Exception as e:
        return {
            "status": "failed",
            "error": str(e),
            "error_type": type(e).__name__
        }


@router.get("/candidates")
async def get_candidates():
    """Get all candidates in database"""
    try:
        result = db.supabase.table('candidates').select("*").execute()
        candidates = result.data if result.data else []
        
        return {
            "total_candidates": len(candidates),
            "candidates": candidates[:5]
        }
        
    except Exception as e:
        return {"error": str(e)}


@router.delete("/wipe-candidates")
async def wipe_candidates():
    """Delete all candidates"""
    try:
        result = db.supabase.table('candidates').delete().neq('id', '00000000-0000-0000-0000-000000000000').execute()
        return {"status": "wiped"}
    except Exception as e:
        return {"error": str(e)}
