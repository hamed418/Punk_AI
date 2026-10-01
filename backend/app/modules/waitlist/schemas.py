
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr
# waiting list 
class WaitListCreateRequest(BaseModel):
    email: str 

class WaitListUpdateRequest(BaseModel): 
    name: Optional[str] = None
    company_name: Optional[str] = None
    linkedin_url: Optional[str] = None
    job_title: Optional[str] = None
    description: Optional[str] = None

class WaitListResponse(BaseModel):
    id: uuid.UUID
    # user info 
    email: str
    name: Optional[str] = None
    company_name: Optional[str] = None
    linkedin_url: Optional[str] = None
    job_title: Optional[str] = None
    description: Optional[str] = None
    # Network & Geolocation
    ip_address: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    timezone: Optional[str] = None
    isp: Optional[str] = None

    # Device Information
    user_agent: Optional[str] = None
    browser: Optional[str] = None
    browser_version: Optional[str] = None
    operating_system: Optional[str] = None
    os_version: Optional[str] = None
    device_type: Optional[str] = None
    device_brand: Optional[str] = None
    device_model: Optional[str] = None

    # Marketing Attribution
    referrer_url: Optional[str] = None
    landing_page: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_term: Optional[str] = None
    utm_content: Optional[str] = None

    # Other
    language: Optional[str] = None
    is_completed: bool

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}