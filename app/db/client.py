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
            # Use individual parameters instead of connection string
            self._pool = await asyncpg.create_pool(
                host="db.cqihxgedvmnqauygtoql.supabase.co",
                port=5432,
                user="postgres",
                password=settings.database_password,
                database="postgres",
                min_size=1,
                max_size=10,
                timeout=60
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
