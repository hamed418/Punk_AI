from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_admin_user, get_db
from app.modules.user.models import User
from app.modules.analytics.repository import AnalyticsRepository
from app.modules.analytics.service import AnalyticsService
from app.modules.analytics.schemas import (
    AnalyticsOverviewResponse,
    VelocityResponse,
    ActivityFeedResponse,
    RecentCampaignsResponse,
)

router = APIRouter(prefix="/analytics", tags=["Admin - Analytics"])

repository = AnalyticsRepository()
service = AnalyticsService(repository)

service = AnalyticsService(repository) 
@router.get("")
async def get_dashboard_data(
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsOverviewResponse:
    """Admin only: high-level overview metrics."""
    return await service.get_overview(db)


@router.get(
    "/velocity",
    response_model=VelocityResponse,
    summary="Campaigns Launched & Performance Velocity Chart",
    description="Returns time-series data for daily, weekly, or monthly velocity charts.",
)
async def get_velocity(
    timeframe: str = Query(default="daily", description="Timeframe: daily, weekly, monthly"),
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> VelocityResponse:
    """Admin only: time-series velocity chart data."""
    return await service.get_velocity(db, timeframe=timeframe)


@router.get(
    "/activity-feed",
    response_model=ActivityFeedResponse,
    summary="Real-time Activity & Event Feed",
    description="Returns recent system activities, audit logs, and campaign events.",
)
async def get_activity_feed(
    limit: int = Query(default=10, ge=1, le=50, description="Max feed events to return"),
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ActivityFeedResponse:
    """Admin only: live event and audit feed."""
    return await service.get_activity_feed(db, limit=limit)


@router.get(
    "/recent-campaigns",
    response_model=RecentCampaignsResponse,
    summary="Recent Campaigns Across Users",
    description="Returns recent campaigns with performance metrics and user info for the analytics table.",
)
async def get_recent_campaigns(
    limit: int = Query(default=10, ge=1, le=50, description="Max campaigns to return"),
    search: Optional[str] = Query(default=None, description="Search query for name, user email, platform"),
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> RecentCampaignsResponse:
    """Admin only: recent campaigns across all users."""
    return await service.get_recent_campaigns(db, limit=limit, search=search)


@router.get("", summary="Legacy Analytics Endpoint")
async def get_dashboard_data(
    db: AsyncSession = Depends(get_db),
):
    return await service.get_analytics(db)