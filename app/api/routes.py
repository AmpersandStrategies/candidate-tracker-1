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
    """Get candidates with pagination and filtering"""
    try:
        # Build WHERE clause
        where_conditions = ["1=1"]
        params = []
        
        if state:
            where_conditions.append("state = %s")
            params.append(state)
        
        where_clause = " AND ".join(where_conditions)
        count_query = f"SELECT COUNT(*) FROM candidates WHERE {where_clause}"
        
        print(f"DEBUG: About to execute query: {count_query}")
        total = await db.execute_query(count_query, *params)
        
        return {"candidates": [], "total": 0}
    except Exception as e:
        print(f"DEBUG: Database error: {str(e)}")
        return {"error": f"Database connection failed: {str(e)}"}
        
        # Get total count
        count_query = f"SELECT COUNT(*) FROM candidates WHERE {where_clause}"
        total = await db.execute_query(count_query, *params)
        total_count = total[0]['count'] if total else 0
        
        # Get paginated results
        offset = (page - 1) * size
        param_count += 1
        params.append(size)
        param_count += 1
        params.append(offset)
        
        query = f"""
            SELECT * FROM candidates 
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_count-1} OFFSET ${param_count}
        """
        
        rows = await db.execute_query(query, *params)
        candidates = [dict(row) for row in rows]
        
        return {
            "candidates": candidates,
            "total": total_count,
            "page": page,
            "size": size
        }
    except Exception as e:
        logger.error("Error fetching candidates", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/filings")
async def get_filings(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=1000),
    candidate_id: Optional[str] = None
):
    """Get filings with pagination and filtering"""
    try:
        where_conditions = ["1=1"]
        params = []
        param_count = 0
        
        if candidate_id:
            param_count += 1
            where_conditions.append(f"candidate_id = ${param_count}")
            params.append(candidate_id)
        
        where_clause = " AND ".join(where_conditions)
        
        count_query = f"SELECT COUNT(*) FROM filings WHERE {where_clause}"
        total = await db.execute_query(count_query, *params)
        total_count = total[0]['count'] if total else 0
        
        offset = (page - 1) * size
        param_count += 1
        params.append(size)
        param_count += 1
        params.append(offset)
        
        query = f"""
            SELECT * FROM filings 
            WHERE {where_clause}
            ORDER BY receipt_date DESC
            LIMIT ${param_count-1} OFFSET ${param_count}
        """
        
        rows = await db.execute_query(query, *params)
        filings = [dict(row) for row in rows]
        
        return {
            "filings": filings,
            "total": total_count,
            "page": page,
            "size": size
        }
    except Exception as e:
        logger.error("Error fetching filings", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/signals")
async def create_signal(url: str, source: str = "manual"):
    """Create a new signal from social media post URL"""
    try:
        query = """
            INSERT INTO signals (source, url, posted_at, status)
            VALUES ($1, $2, $3, 'new')
            RETURNING signal_id
        """
        
        result = await db.execute_query(
            query,
            source,
            url,
            datetime.utcnow()
        )
        
        if result:
            return {"signal_id": str(result[0]['signal_id']), "status": "created"}
        else:
            raise HTTPException(status_code=500, detail="Failed to create signal")
            
    except Exception as e:
        logger.error("Error creating signal", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")
