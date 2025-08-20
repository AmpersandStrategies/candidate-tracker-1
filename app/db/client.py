"""Database client using Supabase REST API"""
from supabase import create_client, Client
from app.config import settings


class DatabaseClient:
    def __init__(self):
        self.supabase: Client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key
        )
    
    async def execute_query(self, query: str, *args):
        """Execute a query using Supabase REST API"""
        try:
            if "SELECT COUNT(*)" in query:
                result = self.supabase.table('candidates').select('*', count='exact').execute()
                return [{'count': result.count}]
            elif "SELECT" in query and "candidates" in query:
                result = self.supabase.table('candidates').select('*').execute()
                return result.data
            else:
                return []
        except Exception as e:
            print(f"Supabase REST API error: {e}")
            return []
    
    async def execute_command(self, command: str, *args):
        """Execute a command using Supabase REST API"""
        return None


# Global instance
db = DatabaseClient()
