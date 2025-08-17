"""Database migration runner"""
import asyncio
import os
from app.db.client import db
from app.utils.logging import get_logger

logger = get_logger(__name__)


async def run_migrations():
    """Run database migrations"""
    schema_path = os.path.join(os.path.dirname(__file__), "../..", "schema.sql")
    
    if not os.path.exists(schema_path):
        logger.error(f"Schema file not found: {schema_path}")
        return
    
    with open(schema_path, 'r') as f:
        schema_sql = f.read()
    
    try:
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(schema_sql)
        logger.info("Database migration completed successfully")
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(run_migrations())
