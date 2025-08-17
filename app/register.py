"""Register Prefect deployments"""
import asyncio
from app.utils.logging import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)

async def register_deployments():
    """Register all Prefect deployments"""
    logger.info("Ready for Prefect deployment registration")

if __name__ == "__main__":
    asyncio.run(register_deployments())
