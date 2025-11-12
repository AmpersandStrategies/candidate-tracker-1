"""FastAPI routes for Candidate Tracker - 2026 House Democrats"""
from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime
from app.db.client import db
import os
import httpx
import asyncio

router = APIRouter()

@router.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "3.0.0",
        "timestamp": datetime.now().isoformat()
    }

@router.get("/database-stats")
async def get_database_stats():
    """Get overview statistics of the database"""
    try:
        # Total candidates
        candidates_result = db.supabase.table('candidates').select('candidate_id', count='exact').execute()
        total_candidates = candidates_result.count
        
        # Total filings
        filings_result = db.supabase.table('filings').select('filing_id', count='exact').execute()
        total_filings = filings_result.count
        
        # Candidates with committees
        with_committees = db.supabase.table('candidates')\
            .select('candidate_id', count='exact')\
            .not_.is_('committee_id', 'null')\
            .neq('committee_id', 'NONE')\
            .execute()
        candidates_with_committees = with_committees.count
        
        # Candidates needing enrichment
        needing_enrichment = db.supabase.table('candidates')\
            .select('candidate_id', count='exact')\
            .is_('committee_id', 'null')\
            .execute()
        candidates_needing_enrichment = needing_enrichment.count
        
        # Filings with financial data
        with_financials = db.supabase.table('filings')\
            .select('filing_id', count='exact')\
            .not_.is_('total_receipts', 'null')\
            .execute()
        filings_with_financials = with_financials.count
        
        return {
            "total_candidates": total_candidates,
            "total_filings": total_filings,
            "candidates_with_committees": candidates_with_committees,
            "candidates_needing_enrichment": candidates_needing_enrichment,
            "filings_with_financials": filings_with_financials
        }
    except Exception as e:
        return {"error": str(e)}

@router.get("/collect-candidates")
async def collect_candidates():
    """
    Collect 2026 House Democrats ONLY from FEC API.
    No committee/financial data yet - just candidate records.
    """
    api_key = os.environ.get('FEC_API_KEY')
    if not api_key:
        return {"error": "FEC_API_KEY not found"}
    
    cycles = [2026]  # ONLY 2026
    parties = ["DEM"]  # ONLY Democrats
    offices = ["H"]  # ONLY House
    
    total_found = 0
    total_stored = 0
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        for cycle in cycles:
            for office in offices:
                for party in parties:
                    page = 1
                    consecutive_empty_pages = 0
                    
                    while consecutive_empty_pages < 2:
                        try:
                            # Get candidates from FEC
                            fec_url = f"https://api.open.fec.gov/v1/candidates/?api_key={api_key}&election_year={cycle}&office={office}&party={party}&page={page}&per_page=100"
                            response = await client.get(fec_url)
                            
                            if response.status_code != 200:
                                print(f"FEC API error: {response.status_code}")
                                break
                            
                            data = response.json()
                            results = data.get('results', [])
                            
                            if not results:
                                consecutive_empty_pages += 1
                                page += 1
                                continue
                            
                            consecutive_empty_pages = 0
                            total_found += len(results)
                            
                            # Store candidates
                            for candidate in results:
                                try:
                                    # Check if candidate already exists
                                    existing = db.supabase.table('candidates')\
                                        .select('candidate_id')\
                                        .eq('source_candidate_ID', candidate.get('candidate_id'))\
                                        .execute()
                                    
                                    if existing.data:
                                        continue  # Skip duplicates
                                    
                                    # Parse name
                                    full_name = candidate.get('name', '')
                                    name_parts = full_name.split(',', 1)
                                    last_name = name_parts[0].strip() if name_parts else full_name
                                    first_name = name_parts[1].strip() if len(name_parts) > 1 else ''
                                    
                                    # Create candidate record
                                    candidate_data = {
                                        'source_candidate_ID': candidate.get('candidate_id'),
                                        'full_name': full_name,
                                        'first_name': first_name,
                                        'last_name': last_name,
                                        'party': candidate.get('party'),
                                        'office': candidate.get('office_full'),
                                        'state': candidate.get('state'),
                                        'district'
