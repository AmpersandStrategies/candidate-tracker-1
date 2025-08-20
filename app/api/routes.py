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

@router.get("/debug/db")
async def debug_database():
    """Debug database connection"""
    try:
        # Test basic Supabase connection
        result = db.supabase.table('candidates').select('count').execute()
        return {
            "supabase_connection": "working",
            "result": str(result),
            "data": result.data if hasattr(result, 'data') else "no data attr",
            "count": result.count if hasattr(result, 'count') else "no count attr"
        }
    except Exception as e:
        return {
            "error": str(e),
            "error_type": str(type(e).__name__)
        }
