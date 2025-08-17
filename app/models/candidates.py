"""Candidate-related models"""
from typing import Optional
from uuid import UUID
from pydantic import BaseModel
from app.models.common import BaseEntity


class Candidate(BaseEntity):
    candidate_id: Optional[UUID] = None
    full_name: str
    preferred_name: Optional[str] = None
    party: Optional[str] = None
    jurisdiction_type: Optional[str] = None
    jurisdiction_name: Optional[str] = None
    state: Optional[str] = None
    office: Optional[str] = None
    district: Optional[str] = None
    election_cycle: Optional[int] = None
    status: Optional[str] = None
    incumbent: bool = False
    current_position: Optional[str] = None
    bio_summary: Optional[str] = None
    source_url: Optional[str] = None


class Committee(BaseEntity):
    committee_id: Optional[UUID] = None
    name: str
    jurisdiction: Optional[str] = None
    state: Optional[str] = None
    type: Optional[str] = None


class CandidateCommittee(BaseModel):
    candidate_id: UUID
    committee_id: UUID
    role: Optional[str] = None
