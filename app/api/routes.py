"""FastAPI routes - Robust Collection"""
from fastapi import APIRouter
from datetime import datetime
import httpx
import os
from app.db.client import db
import asyncio

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
        "version": "2.2.0",
        "timestamp": datetime.utcnow().isoformat(),
        "database": {
            "status": db_status,
            "candidate_count": candidate_count
        }
    }


@router.get("/collect-2026-house-democrats")
async def collect_2026_house_democrats():
    """
    Collect 2026 House Democrats with robust error handling.
    Continues processing even if some pages fail.
    """
    fec_api_key = os.environ.get('FEC_API_KEY')
    if not fec_api_key:
        return {"error": "FEC_API_KEY not configured"}
    
    candidates_collected = 0
    candidates_stored = 0
    page_errors = []
    
    try:
        base_url = "https://api.open.fec.gov/v1/candidates/"
        
        # Longer timeout for FEC API
        async with httpx.AsyncClient(timeout=60.0) as client:
            page = 1
            has_more = True
            consecutive_failures = 0
            
            while has_more and page <= 50:
                try:
                    params = {
                        "api_key": fec_api_key,
                        "election_year": 2026,
                        "office": "H",
                        "party": "DEM",
                        "per_page": 100,
                        "page": page,
                        "sort": "name"
                    }
                    
                    # Add delay to avoid rate limiting
                    if page > 1:
                        await asyncio.sleep(0.5)
                    
                    response = await client.get(base_url, params=params)
                    
                    if response.status_code != 200:
                        error_msg = f"Page {page}: HTTP {response.status_code}"
                        page_errors.append(error_msg)
                        consecutive_failures += 1
                        
                        # If we get 3 failures in a row, stop
                        if consecutive_failures >= 3:
                            page_errors.append(f"Stopping after {consecutive_failures} consecutive failures")
                            break
                        
                        page += 1
                        continue
                    
                    # Reset failure counter on success
                    consecutive_failures = 0
                    
                    data = response.json()
                    candidates = data.get('results', [])
                    
                    if not candidates:
                        has_more = False
                        break
                    
                    candidates_collected += len(candidates)
                    
                    # Store each candidate
                    stored_this_page = 0
                    for candidate in candidates:
                        try:
                            candidate_record = {
                                'full_name': candidate.get('name'),
                                'party': 'Democratic',
                                'jurisdiction_type': 'federal',
                                'jurisdiction_name': 'United States',
                                'state': candidate.get('state'),
                                'office': 'House',
                                'district': candidate.get('district'),
                                'election_cycle': 2026,
                                'status': candidate.get('candidate_status'),
                                'incumbent': candidate.get('incumbent_challenge') == 'I',
                                'source_url': f"https://www.fec.gov/data/candidate/{candidate.get('candidate_id')}/",
                                'source_candidate_ID': candidate.get('candidate_id'),
                                'source_system': 'fec'
                            }
                            
                            result = db.supabase.table('candidates').insert(candidate_record).execute()
                            
                            if result.data:
                                stored_this_page += 1
                                candidates_stored += 1
                                
                        except Exception as e:
                            # Skip duplicates and other insert errors
                            continue
                    
                    # Check pagination
                    pagination = data.get('pagination', {})
                    total_pages = pagination.get('pages', 0)
                    
                    if page >= total_pages:
                        has_more = False
                    else:
                        page += 1
                    
                except httpx.TimeoutException:
                    page_errors.append(f"Page {page}: Timeout")
                    consecutive_failures += 1
                    if consecutive_failures >= 3:
                        break
                    page += 1
                    continue
                    
                except httpx.RequestError as e:
                    page_errors.append(f"Page {page}: Network error - {type(e).__name__}")
                    consecutive_failures += 1
                    if consecutive_failures >= 3:
                        break
                    page += 1
                    continue
                    
                except Exception as e:
                    page_errors.append(f"Page {page}: Unexpected error - {type(e).__name__}: {str(e)}")
                    consecutive_failures += 1
                    if consecutive_failures >= 3:
                        break
                    page += 1
                    continue
        
        return {
            "status": "completed" if not page_errors else "completed_with_errors",
            "candidates_collected_from_fec": candidates_collected,
            "candidates_stored_in_database": candidates_stored,
            "pages_processed": page - 1,
            "page_errors": page_errors if page_errors else None,
            "note": "If some pages failed, run this endpoint again - duplicates will be skipped automatically"
        }
        
    except Exception as e:
        return {
            "status": "failed",
            "error": f"{type(e).__name__}: {str(e)}",
            "candidates_collected": candidates_collected,
            "candidates_stored": candidates_stored,
            "page_errors": page_errors
        }


@router.get("/candidates")
async def get_candidates():
    """Get all candidates with summary stats"""
    try:
        result = db.supabase.table('candidates').select("*").execute()
        candidates = result.data if result.data else []
        
        # Calculate stats
        states = {}
        for c in candidates:
            state = c.get('state', 'Unknown')
            states[state] = states.get(state, 0) + 1
        
        return {
            "total_candidates": len(candidates),
            "by_state": dict(sorted(states.items())),
            "sample_candidates": candidates[:5]
        }
        
    except Exception as e:
        return {"error": str(e)}


@router.get("/verify-data")
async def verify_data():
    """Verify data quality"""
    try:
        result = db.supabase.table('candidates').select("*").execute()
        candidates = result.data if result.data else []
        
        checks = {
            "total_candidates": len(candidates),
            "all_2026_cycle": all(c.get('election_cycle') == 2026 for c in candidates),
            "all_house": all(c.get('office') == 'House' for c in candidates),
            "all_democrats": all(c.get('party') == 'Democratic' for c in candidates),
            "all_have_state": all(c.get('state') for c in candidates),
            "all_have_fec_id": all(c.get('source_candidate_ID') for c in candidates),
            "unique_states": len(set(c.get('state') for c in candidates if c.get('state'))),
            "states_represented": sorted(list(set(c.get('state') for c in candidates if c.get('state')))),
            "sample_records": candidates[:3]
        }
        
        # Add quality verdict
        if checks["all_2026_cycle"] and checks["all_house"] and checks["all_democrats"]:
            checks["quality_verdict"] = "✓ All records match expected criteria"
        else:
            checks["quality_verdict"] = "⚠ Some records don't match expected criteria"
        
        return checks
        
    except Exception as e:
        return {"error": str(e)}


@router.delete("/wipe-candidates")
async def wipe_candidates():
    """DANGER: Delete all candidates"""
    try:
        result = db.supabase.table('candidates').delete().neq('candidate_id', '00000000-0000-0000-0000-000000000000').execute()
        return {"status": "wiped", "message": "All candidates deleted"}
    except Exception as e:
        return {"error": str(e)}
