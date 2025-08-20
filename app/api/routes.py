"""FastAPI routes"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from datetime import datetime
from app.db.client import db
from app.utils.logging import get_logger

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
    """Get candidates with pagination and filtering - debug version"""
    try:
        # Simple test query first
        test_result = await db.execute_query("SELECT 1 as test")
        
        # If that works, try candidates table
        count_query = "SELECT COUNT(*) FROM candidates"
        total_result = await db.execute_query(count_query)
        
        return {
            "status": "success",
            "test_query": str(test_result),
            "total_candidates": str(total_result),
            "candidates": [],
            "total": 0
        }
        
    except Exception as e:
        # Return the error details
        return {
            "error": f"Database error: {str(e)}",
            "error_type": str(type(e).__name__),
            "status": "failed"
        }


@router.get("/filings")
async def get_filings(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=1000),
    candidate_id: Optional[str] = None
):
    """Get filings with pagination and filtering"""
    try:
        # Count total filings
        if candidate_id:
            result = self.supabase.table('filings').select('*', count='exact').eq('candidate_id', candidate_id).execute()
        else:
            result = self.supabase.table('filings').select('*', count='exact').execute()
        
        total_count = result.count or 0
        
        # Get paginated filings
        offset = (page - 1) * size
        if candidate_id:
            filings_result = self.supabase.table('filings').select('*').eq('candidate_id', candidate_id).range(offset, offset + size - 1).execute()
        else:
            filings_result = self.supabase.table('filings').select('*').range(offset, offset + size - 1).execute()
        
        return {
            "filings": filings_result.data,
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
    return {"message": "Signals endpoint - database connection needed"}
