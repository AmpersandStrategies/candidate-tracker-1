"""FastAPI routes - Final with Fill Gaps Endpoint"""
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
        "version": "3.0.0-final",
        "timestamp": datetime.utcnow().isoformat(),
        "database": {
            "status": db_status,
            "candidate_count": candidate_count
        }
    }


@router.get("/collect-all-pages-fill-gaps")
async def collect_all_pages_fill_gaps():
    """
    Collect ALL pages 1-12 from FEC. 
    Skips duplicates automatically.
    Fills any gaps in our collection.
    """
    fec_api_key = os.environ.get('FEC_API_KEY')
    if not fec_api_key:
        return {"error": "FEC_API_KEY not configured"}
    
    candidates_found = 0
    candidates_stored = 0
    pages_with_new_data = []
    
    try:
        base_url = "https://api.open.fec.gov/v1/candidates/"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Go through ALL 12 pages
            for page in range(1, 13):  # Pages 1-12
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
                    candidates_found += len(candidates)
                    
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
                            # Skip duplicates
                            continue
                    
                    if stored_this_page > 0:
                        pages_with_new_data.append(f"Page {page}: +{stored_this_page}")
                    
                    candidates_stored += stored_this_page
                    
                except Exception as e:
                    continue
        
        # Get final count
        count_result = db.supabase.table('candidates').select("count", count='exact').execute()
        final_count = count_result.count if hasattr(count_result, 'count') else 0
        
        return {
            "status": "completed",
            "fec_candidates_checked": candidates_found,
            "new_candidates_added": candidates_stored,
            "pages_with_new_data": pages_with_new_data,
            "database_count_after": final_count,
            "target": 1159,
            "remaining_gap": 1159 - final_count if final_count < 1159 else 0
        }
        
    except Exception as e:
        return {"error": str(e)}


@router.get("/count-and-check-duplicates")
async def count_and_check_duplicates():
    """Get accurate count and check for duplicate FEC IDs"""
    try:
        count_result = db.supabase.table('candidates').select("count", count='exact').execute()
        total_count = count_result.count if hasattr(count_result, 'count') else 0
        
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
        
        seen_fec_ids = set()
        to_delete = []
        
        for candidate in all_candidates:
            fec_id = candidate.get('source_candidate_ID')
            if fec_id:
                if fec_id in seen_fec_ids:
                    to_delete.append(candidate.get('candidate_id'))
                else:
                    seen_fec_ids.add(fec_id)
        
        deleted_count = 0
        for candidate_id in to_delete:
            try:
                db.supabase.table('candidates').delete().eq('candidate_id', candidate_id).execute()
                deleted_count += 1
            except:
                continue
        
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


@router.get("/verify-data")
async def verify_data():
    """Verify data quality"""
    try:
        count_result = db.supabase.table('candidates').select("count", count='exact').execute()
        total_count = count_result.count if hasattr(count_result, 'count') else 0
        
        result = db.supabase.table('candidates').select("*").limit(100).execute()
        sample = result.data if result.data else []
        
        all_records = []
        page_size = 1000
        offset = 0
        
        while True:
            result = db.supabase.table('candidates')\
                .select("state")\
                .range(offset, offset + page_size - 1)\
                .execute()
            
            if not result.data:
                break
                
            all_records.extend(result.data)
            
            if len(result.data) < page_size:
                break
                
            offset += page_size
        
        states = set(r.get('state') for r in all_records if r.get('state'))
        
        checks = {
            "total_candidates": total_count,
            "expected_total": 1159,
            "match": "✓ PERFECT!" if total_count == 1159 else f"⚠ Off by {abs(total_count - 1159)}",
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


@router.get("/candidates")
async def get_candidates():
    """Get all candidates with summary stats"""
    try:
        count_result = db.supabase.table('candidates').select("count", count='exact').execute()
        total_count = count_result.count if hasattr(count_result, 'count') else 0
        
        result = db.supabase.table('candidates').select("*").limit(5).execute()
        sample = result.data if result.data else []
        
        state_result = db.supabase.table('candidates').select("state").limit(2000).execute()
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


@router.delete("/wipe-candidates")
async def wipe_candidates():
    """DANGER: Delete all candidates"""
    try:
        result = db.supabase.table('candidates').delete().neq('candidate_id', '00000000-0000-0000-0000-000000000000').execute()
        return {"status": "wiped"}
    except Exception as e:
        return {"error": str(e)}
"""Add these endpoints to your routes.py for updates and enrichment"""

@router.get("/check-for-new-filings")
async def check_for_new_filings():
    """Check FEC for candidates we don't have yet"""
    fec_api_key = os.environ.get('FEC_API_KEY')
    if not fec_api_key:
        return {"error": "FEC_API_KEY not configured"}
    
    try:
        # Get our current FEC IDs
        all_records = []
        page_size = 1000
        offset = 0
        
        while True:
            result = db.supabase.table('candidates')\
                .select("source_candidate_ID")\
                .range(offset, offset + page_size - 1)\
                .execute()
            
            if not result.data:
                break
            all_records.extend(result.data)
            if len(result.data) < page_size:
                break
            offset += page_size
        
        our_fec_ids = set(r.get('source_candidate_ID') for r in all_records if r.get('source_candidate_ID'))
        
        # Check FEC for total count
        base_url = "https://api.open.fec.gov/v1/candidates/"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            params = {
                "api_key": fec_api_key,
                "election_year": 2026,
                "office": "H",
                "party": "DEM",
                "per_page": 100,
                "page": 1
            }
            
            response = await client.get(base_url, params=params)
            data = response.json()
            fec_total = data.get('pagination', {}).get('count', 0)
            fec_pages = data.get('pagination', {}).get('pages', 0)
            
            # Quick scan for new candidates
            new_candidates = []
            for page in range(1, min(fec_pages + 1, 15)):
                params['page'] = page
                await asyncio.sleep(0.3)
                
                response = await client.get(base_url, params=params)
                candidates = response.json().get('results', [])
                
                for candidate in candidates:
                    fec_id = candidate.get('candidate_id')
                    if fec_id and fec_id not in our_fec_ids:
                        new_candidates.append({
                            'fec_id': fec_id,
                            'name': candidate.get('name'),
                            'state': candidate.get('state'),
                            'district': candidate.get('district')
                        })
        
        return {
            "we_have": len(our_fec_ids),
            "fec_has": fec_total,
            "new_filings_found": len(new_candidates),
            "new_candidates": new_candidates[:20],  # Show first 20
            "action": "Run /collect-new-filings to add them" if new_candidates else "Database is current"
        }
        
    except Exception as e:
        return {"error": str(e)}


@router.get("/collect-new-filings")
async def collect_new_filings():
    """Collect ONLY new candidates we don't have yet"""
    fec_api_key = os.environ.get('FEC_API_KEY')
    if not fec_api_key:
        return {"error": "FEC_API_KEY not configured"}
    
    try:
        # Get our current FEC IDs
        all_records = []
        page_size = 1000
        offset = 0
        
        while True:
            result = db.supabase.table('candidates')\
                .select("source_candidate_ID")\
                .range(offset, offset + page_size - 1)\
                .execute()
            
            if not result.data:
                break
            all_records.extend(result.data)
            if len(result.data) < page_size:
                break
            offset += page_size
        
        our_fec_ids = set(r.get('source_candidate_ID') for r in all_records if r.get('source_candidate_ID'))
        
        # Collect new candidates
        base_url = "https://api.open.fec.gov/v1/candidates/"
        new_stored = 0
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for page in range(1, 15):
                params = {
                    "api_key": fec_api_key,
                    "election_year": 2026,
                    "office": "H",
                    "party": "DEM",
                    "per_page": 100,
                    "page": page
                }
                
                await asyncio.sleep(0.3)
                response = await client.get(base_url, params=params)
                candidates = response.json().get('results', [])
                
                if not candidates:
                    break
                
                for candidate in candidates:
                    fec_id = candidate.get('candidate_id')
                    if not fec_id or fec_id in our_fec_ids:
                        continue
                    
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
                            'source_url': f"https://www.fec.gov/data/candidate/{fec_id}/",
                            'source_candidate_ID': fec_id,
                            'source_system': 'fec'
                        }
                        
                        result = db.supabase.table('candidates').insert(candidate_record).execute()
                        
                        if result.data:
                            new_stored += 1
                            our_fec_ids.add(fec_id)  # Track to avoid duplicates in same run
                            
                    except:
                        continue
        
        # Get final count
        count_result = db.supabase.table('candidates').select("count", count='exact').execute()
        final_count = count_result.count if hasattr(count_result, 'count') else 0
        
        return {
            "status": "completed",
            "new_candidates_added": new_stored,
            "total_candidates_now": final_count,
            "message": f"Added {new_stored} new filings. Database now has {final_count} candidates."
        }
        
    except Exception as e:
        return {"error": str(e)}


@router.get("/enrich-committee-ids")
async def enrich_committee_ids():
    """
    Enrich candidates with their committee IDs from FEC.
    Can run in background - takes 5-10 minutes for 1000+ candidates.
    """
    fec_api_key = os.environ.get('FEC_API_KEY')
    if not fec_api_key:
        return {"error": "FEC_API_KEY not configured"}
    
    try:
        # Get candidates without committee IDs
        result = db.supabase.table('candidates')\
            .select("candidate_id, source_candidate_ID, full_name")\
            .is_('committee_id', 'null')\
            .limit(200)\
            .execute()
        
        candidates_to_enrich = result.data if result.data else []
        
        if not candidates_to_enrich:
            return {
                "status": "complete",
                "message": "All candidates already have committee IDs"
            }
        
        enriched = 0
        base_url = "https://api.open.fec.gov/v1/candidate/{candidate_id}/committees/"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for candidate in candidates_to_enrich[:100]:  # Process 100 at a time
                fec_id = candidate.get('source_candidate_ID')
                if not fec_id:
                    continue
                
                try:
                    url = base_url.format(candidate_id=fec_id)
                    params = {"api_key": fec_api_key}
                    
                    await asyncio.sleep(0.2)  # Rate limit
                    
                    response = await client.get(url, params=params)
                    if response.status_code != 200:
                        continue
                    
                    data = response.json()
                    committees = data.get('results', [])
                    
                    # Get the most recent committee
                    if committees:
                        committee_id = committees[0].get('committee_id')
                        
                        if committee_id:
                            db.supabase.table('candidates')\
                                .update({'committee_id': committee_id})\
                                .eq('candidate_id', candidate.get('candidate_id'))\
                                .execute()
                            enriched += 1
                            
                except:
                    continue
        
        # Check remaining
        remaining_result = db.supabase.table('candidates')\
            .select("count", count='exact')\
            .is_('committee_id', 'null')\
            .execute()
        remaining = remaining_result.count if hasattr(remaining_result, 'count') else 0
        
        return {
            "status": "partial" if remaining > 0 else "complete",
            "enriched_this_run": enriched,
            "remaining_without_committees": remaining,
            "message": f"Enriched {enriched} candidates. Run again to continue." if remaining > 0 else "All candidates enriched!"
        }
        
    except Exception as e:
        return {"error": str(e)}


@router.get("/enrichment-status")
async def enrichment_status():
    """Check enrichment progress"""
    try:
        count_result = db.supabase.table('candidates').select("count", count='exact').execute()
        total = count_result.count if hasattr(count_result, 'count') else 0
        
        # Check committee IDs
        committee_result = db.supabase.table('candidates')\
            .select("count", count='exact')\
            .not_.is_('committee_id', 'null')\
            .execute()
        with_committees = committee_result.count if hasattr(committee_result, 'count') else 0
        
        # Check occupations
        occupation_result = db.supabase.table('candidates')\
            .select("count", count='exact')\
            .not_.is_('occupation', 'null')\
            .execute()
        with_occupations = occupation_result.count if hasattr(occupation_result, 'count') else 0
        
        return {
            "total_candidates": total,
            "enrichment_progress": {
                "committee_ids": {
                    "enriched": with_committees,
                    "remaining": total - with_committees,
                    "percent": round(with_committees / total * 100, 1) if total > 0 else 0
                },
                "occupations": {
                    "enriched": with_occupations,
                    "remaining": total - with_occupations,
                    "percent": round(with_occupations / total * 100, 1) if total > 0 else 0
                }
            },
            "next_action": "Run /enrich-committee-ids to start enrichment"
        }
        
    except Exception as e:
        return {"error": str(e)}

@router.get("/explore-occupation-data")
async def explore_occupation_data():
    """Check what occupation data FEC provides for our candidates"""
    fec_api_key = os.environ.get('FEC_API_KEY')
    if not fec_api_key:
        return {"error": "FEC_API_KEY not configured"}
    
    try:
        # Get 5 candidates WITH committee IDs to test
        result = db.supabase.table('candidates')\
            .select("candidate_id, full_name, source_candidate_ID, committee_id")\
            .not_.is_('committee_id', 'null')\
            .limit(5)\
            .execute()
        
        test_candidates = result.data if result.data else []
        
        if not test_candidates:
            return {"error": "No candidates with committee IDs yet. Run committee enrichment first."}
        
        findings = []
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for candidate in test_candidates:
                fec_id = candidate.get('source_candidate_ID')
                committee_id = candidate.get('committee_id')
                
                candidate_data = {}
                committee_data = {}
                filing_data = {}
                
                # Check 1: Candidate endpoint
                try:
                    url = f"https://api.open.fec.gov/v1/candidate/{fec_id}/"
                    response = await client.get(url, params={"api_key": fec_api_key})
                    if response.status_code == 200:
                        data = response.json().get('results', [{}])[0]
                        candidate_data = {
                            "has_occupation": 'occupation' in data,
                            "occupation": data.get('occupation'),
                            "other_fields": list(data.keys())[:10]
                        }
                except:
                    candidate_data = {"error": "Failed to fetch"}
                
                await asyncio.sleep(0.3)
                
                # Check 2: Committee endpoint
                try:
                    url = f"https://api.open.fec.gov/v1/committee/{committee_id}/"
                    response = await client.get(url, params={"api_key": fec_api_key})
                    if response.status_code == 200:
                        data = response.json().get('results', [{}])[0]
                        committee_data = {
                            "has_candidate_info": 'candidate_ids' in data,
                            "treasurer_name": data.get('treasurer_name'),
                            "other_fields": list(data.keys())[:10]
                        }
                except:
                    committee_data = {"error": "Failed to fetch"}
                
                await asyncio.sleep(0.3)
                
                # Check 3: Form 1 filings
                try:
                    url = "https://api.open.fec.gov/v1/filings/"
                    params = {
                        "api_key": fec_api_key,
                        "committee_id": committee_id,
                        "form_type": "F1"
                    }
                    response = await client.get(url, params=params)
                    if response.status_code == 200:
                        filings = response.json().get('results', [])
                        if filings:
                            latest = filings[0]
                            filing_data = {
                                "has_f1_filing": True,
                                "filing_fields": list(latest.keys())[:15],
                                "sample_data": {k: latest.get(k) for k in ['candidate_name', 'office', 'state'] if k in latest}
                            }
                        else:
                            filing_data = {"has_f1_filing": False}
                except:
                    filing_data = {"error": "Failed to fetch"}
                
                findings.append({
                    "name": candidate.get('full_name'),
                    "fec_id": fec_id,
                    "committee_id": committee_id,
                    "candidate_endpoint": candidate_data,
                    "committee_endpoint": committee_data,
                    "form1_filings": filing_data
                })
        
        return {
            "summary": "Exploring FEC data sources for occupation",
            "candidates_checked": len(findings),
            "findings": findings
        }
        
    except Exception as e:
        return {"error": str(e)}
