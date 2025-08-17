"""Configuration management - completely new file"""
import os
from typing import List, Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    supabase_url: str
    supabase_service_role_key: str
    prefect_api_url: Optional[str] = None
    prefect_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    google_cse_id: Optional[str] = None
    fec_api_key: Optional[str] = None
    ftm_api_key: Optional[str] = None
    airtable_token: Optional[str] = None
    airtable_base_id: Optional[str] = None
    ap_api_key: Optional[str] = None
    usvote_api_key: Optional[str] = None
    wa_socrata_app_token: Optional[str] = None
    initial_backfill_cycles: str = "2026,2028"
    enable_states: bool = True
    enable_airtable_sync: bool = True
    enable_media_whitelist: bool = True
    enable_common_names: bool = True
    enable_ap_elections: bool = False
    enable_usvote_calendars: bool = False
    enable_zapier_sync: bool = False
    enable_push_to_crm: bool = False
    scrape_max_concurrency: int = 2
    scrape_delay_ms: int = 1500
    scrape_user_agent: str = "AmpersandResearchBot/1.0 (+contact@example.com)"
    
    @property
    def backfill_cycles(self) -> List[int]:
        return [int(x.strip()) for x in self.initial_backfill_cycles.split(",")]
    
    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()
