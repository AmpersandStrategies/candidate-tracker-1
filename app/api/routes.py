"""FastAPI routes"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from datetime import datetime
from app.db.client import db
from app.utils.logging import get_logger
import os
import httpx

logger = get_logger(__name__)
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


@router.get("/candidates")
async def get_candidates(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=1000),
    state: Optional[str] = None,
    office: Optional[str] = None,
    election_cycle: Optional[int] = None
):
    """Get candidates with pagination and filtering"""
    try:
        # Build Supabase query for data
        query = db.supabase.table('candidates').select('*')
        
        if state:
            query = query.eq('state', state)
        if office:
            query = query.ilike('office', f'%{office}%')
        if election_cycle:
            query = query.eq('election_cycle', election_cycle)
        
        # Get count separately
        count_query = db.supabase.table('candidates').select('*', count='exact')
        if state:
            count_query = count_query.eq('state', state)
        if office:
            count_query = count_query.ilike('office', f'%{office}%')
        if election_cycle:
            count_query = count_query.eq('election_cycle', election_cycle)
        
        count_result = count_query.execute()
        total_count = count_result.count or 0
        
        # Get paginated results
        offset = (page - 1) * size
        data_result = query.range(offset, offset + size - 1).execute()
        
        return {
            "candidates": data_result.data,
            "total": total_count,
            "page": page,
            "size": size
        }
        
    except Exception as e:
        return {
            "error": f"Database error: {str(e)}",
            "candidates": [],
            "total": 0
        }


@router.get("/filings")
async def get_filings(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=1000),
    candidate_id: Optional[str] = None
):
    """Get filings with pagination and filtering"""
    try:
        # Build Supabase query
        query = db.supabase.table('filings').select('*', count='exact')
        
        if candidate_id:
            query = query.eq('candidate_id', candidate_id)
        
        # Get count separately
        count_query = db.supabase.table('filings').select('*', count='exact')
        if candidate_id:
            count_query = count_query.eq('candidate_id', candidate_id)
        
        count_result = count_query.execute()
        total_count = count_result.count or 0
        
        # Get paginated results
        offset = (page - 1) * size
        data_result = query.range(offset, offset + size - 1).execute()
        
        return {
            "filings": data_result.data,
            "total": total_count,
            "page": page,
            "size": size
        }
        
    except Exception as e:
        return {
            "error": f"Database error: {str(e)}",
            "filings": [],
            "total": 0
        }


@router.post("/signals")
async def create_signal(url: str, source: str = "manual"):
    """Create a new signal from social media post URL"""
    try:
        result = db.supabase.table('signals').insert({
            'source': source,
            'url': url,
            'posted_at': datetime.utcnow().isoformat(),
            'status': 'new'
        }).execute()
        
        return {"signal_id": result.data[0]['signal_id'], "status": "created"}
        
    except Exception as e:
        return {"error": f"Database error: {str(e)}"}


@router.get("/collect-fec-data")
async def collect_fec_data():
    """Collect real FEC candidates"""
    try:
        fec_api_key = os.environ.get('FEC_API_KEY')
        
        async with httpx.AsyncClient() as client:
            # Get 2026 Democratic House candidates
            response = await client.get(
                "https://api.open.fec.gov/v1/candidates",
                params={
                    "api_key": fec_api_key,
                    "cycle": 2026,
                    "party": "DEM",
                    "office": "H",
                    "per_page": 50
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
                        
                except Exception as e:
                    continue  # Skip duplicates/errors
            
            return {
                "status": "success",
                "candidates_found": len(candidates),
                "candidates_stored": stored_count
            }
            
    except Exception as e:
        return {"error": f"FEC collection failed: {str(e)}"}


@router.get("/add-test-candidate")
async def add_test_candidate():
    """Add a test candidate to verify database insert works"""
    try:
        result = db.supabase.table('candidates').insert({
            'full_name': 'Jane Test Candidate',
            'party': 'Democratic',
            'jurisdiction_type': 'federal',
            'jurisdiction_name': 'United States',
            'state': 'CA',
            'office': 'House',
            'election_cycle': 2026,
            'incumbent': False,
            'source_url': 'https://test.example.com'
        }).execute()
        
        return {
            "status": "success",
            "candidate_added": result.data[0] if result.data else "No data returned"
        }
        
    except Exception as e:
        return {
            "error": f"Failed to add test candidate: {str(e)}"
        }
