import uuid
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
from decimal import Decimal
from app.shared.enums import AdPlatform, CampaignStatus

class CampaignResponse(BaseModel):
    id: uuid.UUID
    name: str
    platform: AdPlatform
    status: CampaignStatus
    campaign_plan: Optional[Dict[str, Any]] = None
    daily_budget_usd: Optional[Decimal] = None
    monthly_budget_usd: Optional[Decimal] = None
    impressions: int = 0
    clicks: int = 0
    conversions: int = 0
    spend_usd: Optional[Decimal] = None
    roas: Optional[Decimal] = None
    cpa_usd: Optional[Decimal] = None
    approved_by_user: bool
    approved_at: Optional[datetime] = None
    created_at: datetime
    ext_campaign_id: Optional[str] = None

    model_config = {"from_attributes": True}

class CampaignListResponse(BaseModel):
    results: List[CampaignResponse]
    total: int
    page: int
    page_size: int


class AdminCampaignListItem(BaseModel):
    id: uuid.UUID
    name: str
    platform: AdPlatform
    status: CampaignStatus
    user_id: uuid.UUID
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    daily_budget_usd: Optional[Decimal] = None
    monthly_budget_usd: Optional[Decimal] = None
    spend_usd: Decimal = Decimal("0.00")
    impressions: int = 0
    clicks: int = 0
    conversions: int = 0
    ctr: float = 0.0
    roas: Optional[Decimal] = None
    cpa_usd: Optional[Decimal] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    campaign_plan: Optional[Dict[str, Any]] = None
   

    model_config = {"from_attributes": True}


class AdminCampaignStatsResponse(BaseModel):
    total_campaigns: int
    active_campaigns: int
    avg_ctr: float
    total_spend: float
    avg_roas: float
    new_this_week: int
    status_breakdown: Dict[str, int]
    platform_breakdown: Dict[str, int]