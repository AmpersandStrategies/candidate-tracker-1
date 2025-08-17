"""Sample script to ingest 10 FEC candidates"""
import asyncio
from app.integrations.fec_client import FECClient
from app.utils.logging import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)


async def run_fec_sample():
    """Run FEC sample ingestion for 10 candidates"""
    logger.info("Starting FEC sample - 10 candidates")
    
    async with FECClient() as fec_client:
        # Get 2026 Democratic candidates (limited to 10)
        candidates = await fec_client.get_candidates(2026, "DEM")
        sample_candidates = candidates[:10]
        
        logger.info("Processing sample candidates", count=len(sample_candidates))
        
        for candidate_data in sample_candidates:
            candidate_id = await fec_client.store_candidate(candidate_data, 2026)
            
            if candidate_id:
                # Get committees for this candidate
                committees = await fec_client.get_committees(2026)
                for committee_data in committees[:2]:  # Limit to 2 committees per candidate
                    committee_id = await fec_client.store_committee(committee_data)
                    
                    if committee_id:
                        await fec_client._link_candidate_committee(candidate_id, committee_id)
    
    logger.info("FEC sample completed - check Supabase")


if __name__ == "__main__":
    asyncio.run(run_fec_sample())
