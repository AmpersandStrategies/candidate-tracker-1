@router.get("/sync-to-airtable-improved")
async def sync_to_airtable_improved():
    """Enhanced sync with proper field mapping, cycle filtering, and multi-table support"""
    try:
        airtable_token = os.environ.get('AIRTABLE_TOKEN')
        airtable_base_id = os.environ.get('AIRTABLE_BASE_ID')
        
        if not airtable_token or not airtable_base_id:
            return {"error": "Airtable credentials not configured"}
        
        # Get ONLY 2026 candidates from database
        candidates_result = db.supabase.table('candidates').select('*').eq('election_cycle', 2026).execute()
        candidates = candidates_result.data
        
        if not candidates:
            return {"error": "No 2026 candidates found in database"}
        
        def map_party(party_code):
            if not party_code:
                return "Other"
            party_code = str(party_code).upper()
            if party_code in ["DEM", "DEMOCRATIC"]:
                return "Democrat"
            elif party_code in ["REP", "REPUBLICAN"]:
                return "Republican"
            elif party_code in ["IND", "INDEPENDENT"]:
                return "Independent"
            else:
                return "Other"
        
        # Airtable endpoints
        candidates_url = f"https://api.airtable.com/v0/{airtable_base_id}/Candidates"
        filings_url = f"https://api.airtable.com/v0/{airtable_base_id}/Filings%20%26%20Finance"
        
        headers = {
            "Authorization": f"Bearer {airtable_token}",
            "Content-Type": "application/json"
        }
        
        candidates_synced = 0
        filings_synced = 0
        errors = []
        candidate_records_map = {}  # To store Airtable record IDs for linking
        
        async with httpx.AsyncClient() as client:
            
            # First, get existing candidates from Airtable to prevent duplicates
            existing_candidates = {}
            try:
                existing_response = await client.get(candidates_url, headers=headers)
                if existing_response.status_code == 200:
                    existing_data = existing_response.json()
                    for record in existing_data.get('records', []):
                        source_id = record.get('fields', {}).get('Source Candidate ID')
                        if source_id:
                            existing_candidates[source_id] = record['id']
            except Exception as e:
                print(f"Warning: Could not fetch existing candidates: {e}")
            
            # Sync candidates to Candidates table
            for i in range(0, len(candidates), 10):
                batch = candidates[i:i+10]
                candidate_records = []
                
                for candidate in batch:
                    source_id = candidate.get('source_candidate_ID', '')
                    
                    # Skip if already exists in Airtable
                    if source_id in existing_candidates:
                        candidate_records_map[source_id] = existing_candidates[source_id]
                        continue
                    
                    record = {
                        "fields": {
                            "Candidate ID": source_id,  # Map to your original field name
                            "Source Candidate ID": source_id,  # Add new field for tracking
                            "Full Name": str(candidate.get('full_name', '')),
                            "Preferred Name": str(candidate.get('preferred_name', '') or ''),
                            "Party": map_party(candidate.get('party', '')),
                            "Jurisdiction": str(candidate.get('jurisdiction_name', '')),
                            "Office Sought": str(candidate.get('office', '')),
                            "Incumbent?": bool(candidate.get('incumbent', False)),
                            "Current Position": str(candidate.get('current_position', '') or ''),
                            "Bio Summary": str(candidate.get('bio_summary', '') or ''),
                            "Confidence Flag": "Medium"  # Default value
                        }
                    }
                    candidate_records.append(record)
                
                if candidate_records:
                    # Log progress every 10 batches
                    if (i // 10 + 1) % 10 == 0:
                        print(f"Syncing candidate batch {i // 10 + 1}")
                    
                    try:
                        response = await client.post(candidates_url, headers=headers, json={"records": candidate_records})
                        
                        if response.status_code == 200:
                            response_data = response.json()
                            candidates_synced += len(candidate_records)
                            
                            # Store record IDs for linking to filings
                            for j, record in enumerate(response_data.get('records', [])):
                                original_candidate = batch[j]
                                source_id = original_candidate.get('source_candidate_ID', '')
                                candidate_records_map[source_id] = record['id']
                                
                        else:
                            error_msg = f"Candidate batch {i//10 + 1} failed: {response.status_code}"
                            errors.append(error_msg)
                            
                    except Exception as batch_error:
                        error_msg = f"Candidate batch {i//10 + 1} error: {str(batch_error)}"
                        errors.append(error_msg)
            
            # Now sync filing data to Filings & Finance table
            for i in range(0, len(candidates), 10):
                batch = candidates[i:i+10]
                filing_records = []
                
                for candidate in batch:
                    source_id = candidate.get('source_candidate_ID', '')
                    
                    # Only create filing record if we have the candidate in Airtable
                    if source_id in candidate_records_map:
                        filing_record = {
                            "fields": {
                                "Filing ID": source_id,  # Use source ID as filing ID for now
                                "Candidate": [candidate_records_map[source_id]],  # Link to candidate record
                                "Jurisdiction": str(candidate.get('jurisdiction_name', '')),
                                "Office": str(candidate.get('office', '')),
                                "Committee Name": f"{candidate.get('full_name', '')} for {candidate.get('office', '')}",  # Constructed name
                                "Committee ID": source_id,  # Use candidate ID as committee ID for now
                                "COH $": 0,  # Placeholder - will be populated when we add financial data
                                "Total Raised": 0,  # Placeholder
                                "Total Spent": 0,  # Placeholder
                                "Funding Source Link": str(candidate.get('source_url', '') or '')
                            }
                        }
                        
                        # Add filing date if available
                        filing_date = candidate.get('first_file_date') or candidate.get('created_at')
                        if filing_date:
                            # Convert to proper date format for Airtable
                            try:
                                from datetime import datetime
                                if isinstance(filing_date, str):
                                    # Try to parse various date formats
                                    for fmt in ['%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f']:
                                        try:
                                            parsed_date = datetime.strptime(filing_date[:len(fmt.replace('%f', ''))], fmt)
                                            filing_record["fields"]["Filing Date"] = parsed_date.strftime('%Y-%m-%d')
                                            break
                                        except ValueError:
                                            continue
                            except Exception:
                                pass  # Skip date if parsing fails
                        
                        filing_records.append(filing_record)
                
                if filing_records:
                    try:
                        response = await client.post(filings_url, headers=headers, json={"records": filing_records})
                        
                        if response.status_code == 200:
                            filings_synced += len(filing_records)
                        else:
                            error_msg = f"Filing batch {i//10 + 1} failed: {response.status_code}"
                            errors.append(error_msg)
                            
                    except Exception as batch_error:
                        error_msg = f"Filing batch {i//10 + 1} error: {str(batch_error)}"
                        errors.append(error_msg)
        
        return {
            "status": "completed",
            "election_cycle_filter": "2026 only",
            "candidates_synced": candidates_synced,
            "filings_synced": filings_synced,
            "total_candidates": len(candidates),
            "errors": errors,
            "candidate_success_rate": f"{(candidates_synced/len(candidates)*100):.1f}%" if candidates else "0%",
            "improvements": [
                "Filtered to 2026 candidates only",
                "Added proper field mapping including Candidate ID",
                "Prevented duplicates by checking existing Airtable records",
                "Created linked records in Filings & Finance table",
                "Added filing dates where available"
            ]
        }
        
    except Exception as e:
        return {"error": f"Enhanced sync failed: {str(e)}"}

@router.get("/cleanup-airtable-duplicates")
async def cleanup_airtable_duplicates():
    """Remove duplicate candidates from Airtable based on Source Candidate ID"""
    try:
        airtable_token = os.environ.get('AIRTABLE_TOKEN')
        airtable_base_id = os.environ.get('AIRTABLE_BASE_ID')
        
        if not airtable_token or not airtable_base_id:
            return {"error": "Airtable credentials not configured"}
        
        candidates_url = f"https://api.airtable.com/v0/{airtable_base_id}/Candidates"
        headers = {
            "Authorization": f"Bearer {airtable_token}",
            "Content-Type": "application/json"
        }
        
        duplicates_found = {}
        records_to_delete = []
        
        async with httpx.AsyncClient() as client:
            # Get all candidates from Airtable
            try:
                response = await client.get(candidates_url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    records = data.get('records', [])
                    
                    # Find duplicates based on Source Candidate ID or Candidate ID
                    seen_ids = {}
                    for record in records:
                        fields = record.get('fields', {})
                        source_id = fields.get('Source Candidate ID') or fields.get('Candidate ID')
                        
                        if source_id:
                            if source_id in seen_ids:
                                # This is a duplicate
                                if source_id not in duplicates_found:
                                    duplicates_found[source_id] = []
                                duplicates_found[source_id].append(record['id'])
                                records_to_delete.append(record['id'])
                            else:
                                seen_ids[source_id] = record['id']
                    
                    # Delete duplicates (keep the first occurrence)
                    deleted_count = 0
                    for record_id in records_to_delete:
                        try:
                            delete_url = f"{candidates_url}/{record_id}"
                            delete_response = await client.delete(delete_url, headers=headers)
                            if delete_response.status_code == 200:
                                deleted_count += 1
                        except Exception as e:
                            print(f"Failed to delete record {record_id}: {e}")
                    
                    return {
                        "status": "completed",
                        "duplicates_found": len(duplicates_found),
                        "records_deleted": deleted_count,
                        "duplicate_details": duplicates_found
                    }
                else:
                    return {"error": f"Failed to fetch records: {response.status_code}"}
                    
            except Exception as e:
                return {"error": f"Cleanup failed: {str(e)}"}
                
    except Exception as e:
        return {"error": f"Cleanup process failed: {str(e)}"}

@router.get("/validate-2026-data")
async def validate_2026_data():
    """Check data quality - election cycles, missing fields, etc."""
    try:
        # Check election cycle distribution in database
        all_candidates = db.supabase.table('candidates').select('election_cycle, party, office, source_candidate_ID, full_name').execute()
        candidates = all_candidates.data
        
        if not candidates:
            return {"error": "No candidates found in database"}
        
        # Analyze data quality
        cycle_counts = {}
        missing_source_ids = 0
        missing_names = 0
        party_distribution = {}
        office_distribution = {}
        
        for candidate in candidates:
            # Election cycle analysis
            cycle = candidate.get('election_cycle')
            if cycle in cycle_counts:
                cycle_counts[cycle] += 1
            else:
                cycle_counts[cycle] = 1
            
            # Missing data analysis
            if not candidate.get('source_candidate_ID'):
                missing_source_ids += 1
            if not candidate.get('full_name'):
                missing_names += 1
            
            # Distribution analysis (2026 only)
            if cycle == 2026:
                party = candidate.get('party', 'Unknown')
                office = candidate.get('office', 'Unknown')
                
                party_distribution[party] = party_distribution.get(party, 0) + 1
                office_distribution[office] = office_distribution.get(office, 0) + 1
        
        return {
            "total_candidates": len(candidates),
            "election_cycles": cycle_counts,
            "candidates_2026": cycle_counts.get(2026, 0),
            "data_quality": {
                "missing_source_ids": missing_source_ids,
                "missing_names": missing_names
            },
            "2026_distribution": {
                "by_party": party_distribution,
                "by_office": office_distribution
            },
            "recommendations": [
                f"Focus sync on {cycle_counts.get(2026, 0)} candidates from 2026 cycle",
                "Clean up records with missing source IDs" if missing_source_ids > 0 else "Source ID data looks good",
                "Review candidates from other cycles - may be legitimate early filers"
            ]
        }
        
    except Exception as e:
        return {"error": f"Validation failed: {str(e)}"}
