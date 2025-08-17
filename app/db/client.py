"""Database client"""
import asyncio
import asyncpg
from supabase import create_client, Client
from app.config import settings


class DatabaseClient:
    def __init__(self):
        self.supabase: Client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key
        )
        self._pool = None
    
    async def get_pool(self):
        """Get asyncpg connection pool"""
        if not self._pool:
            # Extract connection details from Supabase URL
            url = settings.supabase_url.replace("https://", "postgresql://")
            url = url.replace(".supabase.co", ".supabase.co:5432")
            
            self._pool = await asyncpg.create_pool(
                f"{url}/postgres",
                user="postgres",
                password=settings.supabase_service_role_key,
                min_size=1,
                max_size=10
            )
        return self._pool
    
    async def execute_query(self, query: str, *args):
        """Execute a query with parameters"""
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(query, *args)
    
    async def execute_command(self, command: str, *args):
        """Execute a command (INSERT/UPDATE/DELETE)"""
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            return await conn.execute(command, *args)


# Global instance
db = DatabaseClient()
