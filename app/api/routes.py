"""FastAPI routes"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from datetime import datetime
from app.db.client import db
from app.config import settings  # Add this line
from app.utils.logging import get_logger


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
        # Build Supabase query
        query = db.supabase.table('candidates').select('*', count='exact')
        
        if state:
            query = query.eq('state', state)
        if office:
            query = query.ilike('office', f'%{office}%')
        if election_cycle:
            query = query.eq('election_cycle', election_cycle)
        
        # Get total count
        count_result = query.execute()
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
        
        # Get total count
        count_result = query.execute()
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

@router.get("/test/fec-sample")
async def test_fec_sample():
    """Test endpoint to pull 10 FEC candidates"""
    try:
        from app.integrations.fec_client import FECClient
        
        # Check if FEC API key is configured
        fec_api_key = getattr(settings, 'fec_api_key', None)
        if not fec_api_key:
            return {"error": "FEC_API_KEY not configured", "status": "failed"}
        
        # Initialize FEC client
        fec_client = FECClient()
        
        # Get candidates from 2026 cycle
        candidates = await fec_client.get_candidates(2026, "DEM")
        
        return {
            "status": "debug",
            "fec_api_key_configured": bool(fec_api_key),
            "candidates_retrieved": len(candidates),
            "first_candidate": candidates[0] if candidates else None,
            "raw_candidates": candidates[:3]  # Show first 3 for debugging
        }
        
    except Exception as e:
        return {
            "error": f"FEC test failed: {str(e)}",
            "error_type": str(type(e).__name__),
            "status": "failed"
        }
