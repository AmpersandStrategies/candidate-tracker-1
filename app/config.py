"""Configuration management - FORCED UPDATE 2025"""
import os
from typing import List, Optional
from pydantic_settings import BaseSettings

# FORCED UPDATE - Railway please use this version!

class Settings(BaseSettings):
    # Core (UPDATED)
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
    ena
