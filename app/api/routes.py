"""FastAPI routes - Clean Start v2.0"""
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
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "database": {
            "status": db_status,
            "candidate_count": candidate_count
        }
    }


@router.get("/collect-2026-house-democrats")
async def collect_2026_house_democrats():
    """
    Collect ONLY 2026 House Democrats from FEC API.
    This is our foundation - get this right before adding complexity.
    """
    fec_api_key = os.environ.get('FEC_API_KEY')
    if not fec_api_key:
        return {"error": "FEC_API_KEY not configured"}
    
    candidates_collected = 0
    candidates_stored = 0
    errors = []
    
    try:
        # FEC API endpoint for candidates
        # Filters: 2026 cycle, House (H), Democrat (DEM)
        base_url = "https://api.open.fec.gov/v1/candidates/"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            page = 1
            has_more = True
            
            while has_more and page <= 50:  # Safety limit
                params = {
                    "api_key": fec_api_key,
                    "election_year": 2026,
                    "office": "H",  # House only
                    "party": "DEM",  # Democrats only
                    "per_page": 100,
                    "page": page,
                    "sort": "name",
                    "sort_order": "asc"
                }
                
                response = await client.get(base_url, params=params)
                
                if response.status_code != 200:
                    errors.append(f"FEC API error on page {page}: {response.status_code}")
                    break
                
                data = response.json()
                candidates = data.get('results', [])
                
                if not candidates:
                    has_more = False
                    break
                
                candidates_collected += len(candidates)
                
                # Store each candidate
                for candidate in candidates:
                    try:
                        # Build clean candidate record
                        candidate_record = {
                            'source_candidate_id': candidate.get('candidate_id'),
                            'candidate_name': candidate.get('name'),
                            'party': 'Democratic',  # We know this from our filter
                            'jurisdiction_type': 'federal',
                            'jurisdiction_name': 'United States',
                            'state': candidate.get('state'),
                            'office': 'House',  # We know this from our filter
                            'district': candidate.get('district'),
                            'election_cycle': 2026,
                            'incumbent': candidate.get('incumbent_challenge') == 'I',
                            'candidate_status': candidate.get('candidate_status'),
                            'source_url': f"https://www.fec.gov/data/candidate/{candidate.get('candidate_id')}/"
                        }
                        
                        # Insert into database
                        result = db.supabase.table('candidates').insert(candidate_record).execute()
                        
                        if result.data:
                            candidates_stored += 1
                            
                    except Exception as e:
                        # Skip duplicates and other errors silently
                        continue
                
                # Check if there are more pages
                pagination = data.get('pagination', {})
                if pagination.get('page') >= pagination.get('pages', 0):
                    has_more = False
                else:
                    page += 1
        
        return {
            "status": "completed",
            "candidates_collected_from_fec": candidates_collected,
            "candidates_stored_in_database": candidates_stored,
            "pages_processed": page,
            "errors": errors if errors else None
        }
        
    except Exception as e:
        return {
            "status": "failed",
            "error": str(e),
            "candidates_collected": candidates_collected,
            "candidates_stored": candidates_stored
        }


@router.get("/candidates")
async def get_candidates():
    """Get all candidates in database with summary stats"""
    try:
        # Get all candidates
        result = db.supabase.table('candidates').select("*").execute()
        candidates = result.data if result.data else []
        
        # Calculate stats
        states = {}
        for c in candidates:
            state = c.get('state', 'Unknown')
            states[state] = states.get(state, 0) + 1
        
        return {
            "total_candidates": len(candidates),
            "by_state": states,
            "candidates": candidates[:10]  # Show first 10 as sample
        }
        
    except Exception as e:
        return {"error": str(e)}


@router.get("/verify-data")
async def verify_data():
    """Verify the data we collected is correct"""
    try:
        result = db.supabase.table('candidates').select("*").execute()
        candidates = result.data if result.data else []
        
        # Check data quality
        checks = {
            "total_candidates": len(candidates),
            "all_2026_cycle": all(c.get('election_cycle') == 2026 for c in candidates),
            "all_house": all(c.get('office') == 'House' for c in candidates),
            "all_democrats": all(c.get('party') == 'Democratic' for c in candidates),
            "all_have_state": all(c.get('state') for c in candidates),
            "all_have_candidate_id": all(c.get('source_candidate_id') for c in candidates),
            "unique_states": len(set(c.get('state') for c in candidates if c.get('state'))),
            "sample_records": candidates[:3]  # Show 3 examples
        }
        
        return checks
        
    except Exception as e:
        return {"error": str(e)}


@router.delete("/wipe-candidates")
async def wipe_candidates():
    """
    DANGER: Delete all candidates from database.
    Use this to start completely fresh.
    """
    try:
        # Delete all records
        result = db.supabase.table('candidates').delete().neq('id', '00000000-0000-0000-0000-000000000000').execute()
        
        return {
            "status": "wiped",
            "message": "All candidates deleted from database"
        }
        
    except Exception as e:
        return {"error": str(e)}
