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
    """Get candidates with pagination and fi
