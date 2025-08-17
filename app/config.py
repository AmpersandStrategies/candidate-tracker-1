"""Configuration management - FORCED UPDATE 2025"""
import os
from typing import List, Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Core
    supabase_url: str
    supabase_service_role_key: str
    
    # Orchestration
    prefect_api_url: Optional[str] = None
    prefect_api_key: Optional[str] = None
    
    # Search
    google_api_key: Optional[str] = None
    google_cse_id: Optional[str] = None
    
    # Federal
    fec_api_key: Optional[str] = None
    
    # Optional APIs
    ftm_api_key: Optional[str] = None
    airtable_token: Optional[str] = None
    airtable_base_id: Optional[str] = None
    ap_api_key: Optional[str] = None
    usvote_api_key: Optional[str] = None
    wa_socrata_app_token: Optional[str] = None
    
    # Feature flags
    initial_backfill_cycles: str = "2026,2028"
    enable_states: bool = True
    enable_airtable_sync: bool = True
    enable_media_whitelist: bool = True
    enable_common_names: bool = True
    enable_ap_elections: bool = False
    enable_usvote_calendars: bool = False
    enable_zapier_sync: bool = False
    enable_push_to_crm: bool = False
    
    # Scraper settings
    scrape_max_concurrency: int = 2
    scrape_delay_ms: int = 1500
    scrape_user_agent: str = "AmpersandResearchBot/1.0 (+contact@example.com)"
    
    @property
    def backfill_cycles(self) -> List[int]:
        """Parse backfill cycles from comma-separated string"""
        return [int(x.strip()) for x in self.initial_backfill_cycles.split(",")]
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
