"""FastAPI routes - Batch Collection (No Timeout)"""
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
        "version": "2.3.0-batch",
        "timestamp": datetime.utcnow().isoformat(),
        "database": {
            "status": db_status,
            "candidate_count": candidate_count
        }
    }


@router.get("/collect-batch")
async def collect_batch(page: int = 1):
    """
    Collect ONE PAGE (100 candidates) at a time.
    Call this multiple times with different page numbers.
    
    Example: /collect-batch?page=1
             /collect-batch?page=2
             etc.
    """
    fec_api_key = os.environ.get('FEC_API_KEY')
    if not fec_api_key:
        return {"error": "FEC_API_KEY not configured"}
    
    if page < 1 or page > 50:
        return {"error": "Page must be between 1 and 50"}
    
    candidates_stored = 0
    errors = []
    
    try:
        base_url = "https://api.open.fec.gov/v1/candidates/"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            params = {
                "api_key": fec_api_key,
                "election_year": 2026,
                "office": "H",
                "party": "DEM",
                "per_page": 100,
                "page": page,
                "sort": "name"
            }
            
            response = await client.get(base_url, params=params)
            
            if response.status_code != 200:
                return {
                    "status": "error",
                    "page": page,
                    "error": f"FEC API returned {response.status_code}"
                }
            
            data = response.json()
            candidates = data.get('results', [])
            pagination = data.get('pagination', {})
            
            # Store each candidate
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
                        candidates_stored += 1
                        
                except Exception as e:
                    # Skip duplicates
                    continue
            
            return {
                "status": "success",
                "page": page,
                "total_pages": pagination.get('pages', 0),
                "candidates_on_this_page": len(candidates),
                "candidates_stored": candidates_stored,
                "next_page": page + 1 if page < pagination.get('pages', 0) else None,
                "message": f"Processed page {page} of {pagination.get('pages', 0)}"
            }
        
    except Exception as e:
        return {
            "status": "error",
            "page": page,
            "error": f"{type(e).__name__}: {str(e)}"
        }


@router.get("/collect-all-batches")
async def collect_all_batches():
    """
    Collect ALL remaining pages automatically.
    Processes 3 pages at a time to avoid timeouts.
    Call this multiple times until complete.
    """
    fec_api_key = os.environ.get('FEC_API_KEY')
    if not fec_api_key:
        return {"error": "FEC_API_KEY not configured"}
    
    # Check current count
    try:
        result = db.supabase.table('candidates').select("count", count='exact').execute()
        current_count = result.count if hasattr(result, 'count') else 0
    except:
        current_count = 0
    
    # Figure out which page to start from (roughly)
    # 500 candidates = page 5 completed, start at page 6
    start_page = (current_count // 100) + 1
    
    candidates_stored = 0
    pages_processed = []
    
    try:
        base_url = "https://api.open.fec.gov/v1/candidates/"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Process 3 pages max per request
            for page_offset in range(3):
                page = start_page + page_offset
                
                if page > 15:  # Safety limit
                    break
                
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
                    
                    await asyncio.sleep(0.5)  # Rate limit protection
                    
                    response = await client.get(base_url, params=params)
                    
                    if response.status_code != 200:
                        continue
                    
                    data = response.json()
                    candidates = data.get('results', [])
                    
                    if not candidates:
                        break
                    
                    # Store candidates
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
                                
                        except:
                            continue
                    
                    candidates_stored += stored_this_page
                    pages_processed.append(page)
                    
                except Exception as e:
                    continue
        
        # Check new count
        try:
            result = db.supabase.table('candidates').select("count", count='exact').execute()
            new_count = result.count if hasattr(result, 'count') else 0
        except:
            new_count = current_count
        
        return {
            "status": "success",
            "pages_processed": pages_processed,
            "candidates_stored_this_run": candidates_stored,
            "database_count_before": current_count,
            "database_count_after": new_count,
            "expected_total": "~1159",
            "message": "Run this endpoint again if count is still below 1159" if new_count < 1159 else "Collection complete!"
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error": f"{type(e).__name__}: {str(e)}",
            "candidates_stored": candidates_stored
        }


@router.get("/candidates")
async def get_candidates():
    """Get all candidates with summary stats"""
    try:
        result = db.supabase.table('candidates').select("*").execute()
        candidates = result.data if result.data else []
        
        states = {}
        for c in candidates:
            state = c.get('state', 'Unknown')
            states[state] = states.get(state, 0) + 1
        
        return {
            "total_candidates": len(candidates),
            "by_state": dict(sorted(states.items())),
            "sample_candidates": candidates[:3]
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
            "expected_total": "~1159",
            "progress": f"{len(candidates)}/1159 ({round(len(candidates)/1159*100, 1)}%)",
            "all_2026_cycle": all(c.get('election_cycle') == 2026 for c in candidates),
            "all_house": all(c.get('office') == 'House' for c in candidates),
            "all_democrats": all(c.get('party') == 'Democratic' for c in candidates),
            "unique_states": len(set(c.get('state') for c in candidates if c.get('state'))),
            "states": sorted(list(set(c.get('state') for c in candidates if c.get('state')))),
            "sample_records": candidates[:2]
        }
        
        if checks["all_2026_cycle"] and checks["all_house"] and checks["all_democrats"]:
            checks["quality"] = "✓ Perfect"
        else:
            checks["quality"] = "⚠ Issues found"
        
        return checks
        
    except Exception as e:
        return {"error": str(e)}


@router.delete("/wipe-candidates")
async def wipe_candidates():
    """DANGER: Delete all candidates"""
    try:
        result = db.supabase.table('candidates').delete().neq('candidate_id', '00000000-0000-0000-0000-000000000000').execute()
        return {"status": "wiped"}
    except Exception as e:
        return {"error": str(e)}
