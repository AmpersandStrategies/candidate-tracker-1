# Ampersand Candidate Tracker

A production-ready candidate tracking system that ingests campaign finance data from federal and state sources, discovers social media profiles, tracks media mentions, and syncs to Airtable.

## Features

- **Federal Data**: FEC API integration for candidate, committee, and filing data
- **State Data**: Support for API, bulk download, and scraping across 50+ jurisdictions
- **Social Discovery**: Google Programmable Search Engine integration for social profiles
- **Media Tracking**: Automated media mention discovery with confidence scoring
- **Airtable Sync**: Automated synchronization to Airtable bases
- **RESTful API**: FastAPI endpoints for external integrations

## Quick Start

### Railway Deployment

1. **Connect GitHub to Railway:**
   - Go to [Railway.app](https://railway.app)
   - Click "New Project" → "Deploy from GitHub repo"
   - Select your repository

2. **Set Environment Variables in Railway:**
   Go to Variables tab and add:

   ```bash
   # Core (Required)
   SUPABASE_URL=your_supabase_project_url
   SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_key

   # Federal Data (Recommended)  
   FEC_API_KEY=your_fec_api_key

   # Social Discovery (Optional)
   GOOGLE_API_KEY=your_google_api_key
   GOOGLE_CSE_ID=your_custom_search_engine_id

   # Airtable Sync (Optional)
   AIRTABLE_TOKEN=your_airtable_token
   AIRTABLE_BASE_ID=your_base_id

   # Feature Flags
   ENABLE_STATES=true
   ENABLE_AIRTABLE_SYNC=true
   INITIAL_BACKFILL_CYCLES=2026,2028
