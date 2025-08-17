"""FEC API client for federal data"""
import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime, date
from app.config import settings
from app.db.client import db
from app.utils.logging import get_logger
from app.utils.retry import api_retry

logger = get_logger(__name__)


class FECClient:
    def __init__(self):
        self.api_key = settings.fec_api_key
        self.base_url = "https://api.open.fec.gov/v1"
        self.client = httpx.AsyncClient(timeout=30.0)
        
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    @api_retry()
    async def _request(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make FEC API request"""
        if not self.api_key:
            raise ValueError("FEC_API_KEY not configured")
        
        url = f"{self.base_url}/{endpoint}"
        request_params = {"api_key": self.api_key}
        if params:
            request_params.update(params)
        
        logger.info("Making FEC API request", endpoint=endpoint)
        response = await self.client.get(url, params=request_params)
        response.raise_for_status()
        
        return response.json()
    
    async def get_candidates(self, cycle: int, party: str = "DEM") -> List[Dict[str, Any]]:
        """Get candidates for election cycle"""
        params = {
            "cycle": cycle,
            "party": party,
            "per_page": 100,
            "page": 1
        }
        
        all_candidates = []
        while True:
            data = await self._request("candidates", params)
            candidates = data.get("results", [])
            all_candidates.extend(candidates)
            
            # Check if more pages
            pagination = data.get("pagination", {})
            if params["page"] >= pagination.get("pages", 1):
                break
            
            params["page"] += 1
        
        logger.info("Retrieved FEC candidates", cycle=cycle, count=len(all_candidates))
        return all_candidates
    
    async def get_committees(self, cycle: int) -> List[Dict[str, Any]]:
        """Get committees for election cycle"""
        params = {
            "cycle": cycle,
            "per_page": 100,
            "page": 1
        }
        
        all_committees = []
        while True:
            data = await self._request("committees", params)
            committees = data.get("results", [])
            all_committees.extend(committees)
            
            pagination = data.get("pagination", {})
            if params["page"] >= pagination.get("pages", 1):
                break
            
            params["page"] += 1
        
        logger.info("Retrieved FEC committees", cycle=cycle, count=len(all_committees))
        return all_committees
    
    async def store_candidate(self, candidate_data: Dict[str, Any], cycle: int) -> Optional[str]:
        """Store candidate in database"""
        try:
            query = """
                INSERT INTO candidates (
                    full_name, party, jurisdiction_type, jurisdiction_name,
                    state, office, district, election_cycle, incumbent,
                    source_url, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (full_name, state, office, election_cycle)
                DO UPDATE SET
                    party = EXCLUDED.party,
                    incumbent = EXCLUDED.incumbent,
                    updated_at = EXCLUDED.updated_at
                RETURNING candidate_id
            """
            
            office_full = candidate_data.get("office_full", "")
            district = candidate_data.get("district", "")
            
            result = await db.execute_query(
                query,
                candidate_data.get("name", ""),
                candidate_data.get("party", ""),
                "federal",
                "United States",
                candidate_data.get("state", ""),
                office_full,
                district,
                cycle,
                candidate_data.get("incumbent_challenge", "") == "I",
                f"https://www.fec.gov/data/candidate/{candidate_data.get('candidate_id', '')}/",
                datetime.utcnow(),
                datetime.utcnow()
            )
            
            if result:
                candidate_id = str(result[0]['candidate_id'])
                logger.info("Stored FEC candidate", candidate_id=candidate_id, name=candidate_data.get("name"))
                return candidate_id
                
        except Exception as e:
            logger.error("Error storing candidate", error=str(e), candidate=candidate_data.get("name"))
        
        return None
    
    async def store_committee(self, committee_data: Dict[str, Any]) -> Optional[str]:
        """Store committee in database"""
        try:
            query = """
                INSERT INTO committees (
                    name, jurisdiction, state, type, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (name, state)
                DO UPDATE SET
                    type = EXCLUDED.type,
                    updated_at = EXCLUDED.updated_at
                RETURNING committee_id
            """
            
            result = await db.execute_query(
                query,
                committee_data.get("name", ""),
                "federal",
                committee_data.get("state", ""),
                committee_data.get("committee_type_full", ""),
                datetime.utcnow(),
                datetime.utcnow()
            )
            
            if result:
                return str(result[0]['committee_id'])
                
        except Exception as e:
            logger.error("Error storing committee", error=str(e))
        
        return None
    
    async def backfill_initial(self):
        """Run initial backfill for configured cycles"""
        cycles = settings.backfill_cycles
        logger.info("Starting FEC backfill", cycles=cycles)
        
        for cycle in cycles:
            logger.info("Processing FEC cycle", cycle=cycle)
            
            # Get candidates
            candidates = await self.get_candidates(cycle)
            for candidate_data in candidates:
                candidate_id = await self.store_candidate(candidate_data, cycle)
                
                if candidate_id:
                    # Get candidate committees
                    committees = await self.get_committees(cycle)
                    for committee_data in committees:
                        committee_id = await self.store_committee(committee_data)
                        
                        if committee_id:
                            # Link candidate and committee
                            await self._link_candidate_committee(candidate_id, committee_id)
        
        logger.info("FEC backfill completed")
    
    async def _link_candidate_committee(self, candidate_id: str, committee_id: str):
        """Link candidate and committee"""
        try:
            query = """
                INSERT INTO candidate_committees (candidate_id, committee_id, role)
                VALUES ($1, $2, 'primary')
                ON CONFLICT (candidate_id, committee_id) DO NOTHING
            """
            await db.execute_command(query, candidate_id, committee_id)
        except Exception as e:
            logger.error("Error linking candidate and committee", error=str(e))
