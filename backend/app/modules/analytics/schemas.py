from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal

class AnalyticsOverviewResponse(BaseModel):
    total_users: int
    users_change: str
    users_is_positive: bool
    active_campaigns: int
    campaigns_change: str
    campaigns_is_positive: bool
    ai_chats_today: int
    chats_change: str
    chats_is_positive: bool
    mrr: float
    mrr_change: str
    mrr_is_positive: bool


class VelocityDataPoint(BaseModel):
    name: str
    campaigns: int
    reach: int
    conv: int
    benchmark: int


class VelocityResponse(BaseModel):
    timeframe: str
    data: List[VelocityDataPoint]


class ActivityFeedItem(BaseModel):
    id: str
    accent: str
    title: str
    desc: str
    time: str
    badge: str


class ActivityFeedResponse(BaseModel):
    items: List[ActivityFeedItem]


class RecentCampaignItem(BaseModel):
    id: str
    name: str
    platform: str
    dateRange: str
    manager: str
    userEmail: str
    userAvatar: str
    ctr: str
    spend: str
    roas: str
    status: str
    daily_budget: Optional[str] = None
    impressions: int = 0
    clicks: int = 0
    conversions: int = 0


class RecentCampaignsResponse(BaseModel):
    campaigns: List[RecentCampaignItem]