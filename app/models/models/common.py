"""Common models and types"""
from enum import Enum
from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class PlatformType(str, Enum):
    LINKEDIN = "linkedin"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    TWITTER = "twitter"
    BLUESKY = "bluesky"
    WEBSITE = "website"


class JurisdictionLevel(str, Enum):
    STATE = "state"
    CITY = "city"
    COUNTY = "county"


class SignalStatus(str, Enum):
    NEW = "new"
    TRIAGED = "triaged"
    DISMISSED = "dismissed"


class CalendarSource(str, Enum):
    USVOTE = "usvote"
    AP = "ap"
    MANUAL = "manual"


class LimitType(str, Enum):
    FIXED = "fixed"
    NO_LIMIT = "no_limit"
    AGGREGATE = "aggregate"


class BaseEntity(BaseModel):
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
