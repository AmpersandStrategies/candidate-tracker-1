"""FastAPI routes - Complete with Duplicate Checking"""
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
        "version": "2.4.0",
        "timestamp": datetime.utcnow().isoformat(),
        "database": {
            "status": db_status,
            "candidate_count": candidate_count
        }
    }


@router.get("/collect-all-batches")
async def collect_all_batches():
    """Collect 3 pages at a time without timeout"""
    fec_api_key = os.environ.get('FEC_API_KEY')
    if not fec_api_key:
        return {"error": "FEC_API_KEY not configured"}
    
    try:
        result = db.supabase.table('candidates').select("count", count='exact').execute()
        current_count = result.count if hasattr(result, 'count') else 0
    except:
        current_count = 0
    
    start_page = (current_count // 100) + 1
    candidates_stored = 0
    pages_processed = []
    
    try:
        base_url = "https://api.open.fec.gov/v1/candidates/"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for page_offset in range(3):
                page = start_page + page_offset
                
                if page > 15:
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
                    
                    await asyncio.sleep(0.5)
                    
                    response = await client.get(base_url, params=params)
                    
                    if response.status_code != 200:
                        continue
                    
                    data = response.json()
                    candidates = data.get('results', [])
                    
                    if not candidates:
                        break
                    
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
                    
                except:
                    continue
        
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


@router.get("/count-and-check-duplicates")
async def count_and_check_duplicates():
    """Get accurate count and check for duplicate FEC IDs"""
    try:
        # Get ACTUAL count
        count_result = db.supabase.table('candidates').select("count", count='exact').execute()
        total_count = count_result.count if hasattr(count_result, 'count') else 0
        
        # Get all source_candidate_IDs to check for duplicates
        # We need to paginate through ALL records
        all_records = []
        page_size = 1000
        offset = 0
        
        while True:
            result = db.supabase.table('candidates')\
                .select("source_candidate_ID, candidate_id")\
                .range(offset, offset + page_size - 1)\
                .execute()
            
            if not result.data:
                break
                
            all_records.extend(result.data)
            
            if len(result.data) < page_size:
                break
                
            offset += page_size
        
        # Check for duplicates
        fec_ids = {}
        duplicates = []
        
        for record in all_records:
            fec_id = record.get('source_candidate_ID')
            if fec_id:
                if fec_id in fec_ids:
                    duplicates.append({
                        "fec_id": fec_id,
                        "database_ids": [fec_ids[fec_id], record.get('candidate_id')]
                    })
                else:
                    fec_ids[fec_id] = record.get('candidate_id')
        
        return {
            "total_candidates_in_database": total_count,
            "unique_fec_ids": len(fec_ids),
            "duplicates_found": len(duplicates),
            "duplicate_examples": duplicates[:5] if duplicates else None,
            "verdict": "✓ No duplicates" if len(duplicates) == 0 else f"⚠ {len(duplicates)} duplicates need removal"
        }
        
    except Exception as e:
        return {"error": str(e)}


@router.delete("/remove-duplicates")
async def remove_duplicates():
    """Remove duplicate candidates keeping oldest record for each FEC ID"""
    try:
        # Get all candidates in created order
        all_candidates = []
        page_size = 1000
        offset = 0
        
        while True:
            result = db.supabase.table('candidates')\
                .select("*")\
                .order("created_at")\
                .range(offset, offset + page_size - 1)\
                .execute()
            
            if not result.data:
                break
                
            all_candidates.extend(result.data)
            
            if len(result.data) < page_size:
                break
                
            offset += page_size
        
        # Track which FEC IDs we've seen
        seen_fec_ids = set()
        to_delete = []
        
        for candidate in all_candidates:
            fec_id = candidate.get('source_candidate_ID')
            if fec_id:
                if fec_id in seen_fec_ids:
                    # Duplicate - mark for deletion
                    to_delete.append(candidate.get('candidate_id'))
                else:
                    # First occurrence - keep it
                    seen_fec_ids.add(fec_id)
        
        # Delete duplicates
        deleted_count = 0
        for candidate_id in to_delete:
            try:
                db.supabase.table('candidates').delete().eq('candidate_id', candidate_id).execute()
                deleted_count += 1
            except:
                continue
        
        # Get new count
        count_result = db.supabase.table('candidates').select("count", count='exact').execute()
        final_count = count_result.count if hasattr(count_result, 'count') else 0
        
        return {
            "status": "completed",
            "duplicates_removed": deleted_count,
            "final_candidate_count": final_count,
            "message": f"Removed {deleted_count} duplicate records"
        }
        
    except Exception as e:
        return {"error": str(e)}


@router.get("/candidates")
async def get_candidates():
    """Get all candidates with summary stats"""
    try:
        # Get accurate count
        count_result = db.supabase.table('candidates').select("count", count='exact').execute()
        total_count = count_result.count if hasattr(count_result, 'count') else 0
        
        # Get sample records
        result = db.supabase.table('candidates').select("*").limit(5).execute()
        sample = result.data if result.data else []
        
        # Get state distribution
        state_result = db.supabase.table('candidates').select("state").execute()
        states = {}
        for record in state_result.data if state_result.data else []:
            state = record.get('state', 'Unknown')
            states[state] = states.get(state, 0) + 1
        
        return {
            "total_candidates": total_count,
            "by_state": dict(sorted(states.items())),
            "sample_candidates": sample
        }
        
    except Exception as e:
        return {"error": str(e)}


@router.get("/verify-data")
async def verify_data():
    """Verify data quality"""
    try:
        # Get accurate count
        count_result = db.supabase.table('candidates').select("count", count='exact').execute()
        total_count = count_result.count if hasattr(count_result, 'count') else 0
        
        # Get sample to check quality
        result = db.supabase.table('candidates').select("*").limit(100).execute()
        sample = result.data if result.data else []
        
        # Check states
        state_result = db.supabase.table('candidates').select("state").execute()
        states = set(r.get('state') for r in state_result.data if r.get('state'))
        
        checks = {
            "total_candidates": total_count,
            "expected_total": "~1159",
            "progress": f"{total_count}/1159 ({round(total_count/1159*100, 1)}%)",
            "all_2026_cycle": all(c.get('election_cycle') == 2026 for c in sample),
            "all_house": all(c.get('office') == 'House' for c in sample),
            "all_democrats": all(c.get('party') == 'Democratic' for c in sample),
            "unique_states": len(states),
            "states": sorted(list(states)),
            "sample_records": sample[:2]
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
