"""FastAPI routes"""
from fastapi import APIRouter
from datetime import datetime

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

@router.get("/test")
async def test():
    """Simple test endpoint"""
    return {"message": "API is working"}
from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime
from app.db.client import db
import os
import httpx

@router.get("/candidates")
async def get_candidates(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=1000),
    state: Optional[str] = None
):
    """Get candidates with pagination and filtering"""
    try:
        query = db.supabase.table('candidates').select('*')
        
        if state:
            query = query.eq('state', state)
        
        count_query = db.supabase.table('candidates').select('*', count='exact')
        if state:
            count_query = count_query.eq('state', state)
        
        count_result = count_query.execute()
        total_count = count_result.count or 0
        
        offset = (page - 1) * size
        data_result = query.range(offset, offset + size - 1).execute()
        
        return {
            "candidates": data_result.data,
            "total": total_count,
            "page": page,
            "size": size
        }
    except Exception as e:
        return {"error": f"Database error: {str(e)}"}
