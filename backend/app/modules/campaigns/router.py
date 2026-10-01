from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_admin_user, get_db
from app.modules.ads.schemas import ReadinessItem
from app.modules.user.models import User
from app.shared.pagination import PaginatedResponse

from app.modules.campaigns.repository import CampaignsRepository
from app.modules.campaigns.service import CampaignsService
from app.modules.campaigns.schemas import (
    CampaignListResponse,
    CampaignResponse,
    AdminCampaignListItem,
    AdminCampaignStatsResponse,
)

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])

repository = CampaignsRepository()
service = CampaignsService(repository)


# ── Admin Panel Dedicated Endpoints ──────────────────────────────────────────

@router.get(
    "/admin/stats",
    response_model=AdminCampaignStatsResponse,
    tags=["Admin - Campaigns"],
    summary="Campaign Overview Stats",
    description="Returns aggregate campaign statistics for the admin dashboard overview cards.",
)
async def get_admin_campaign_stats(
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> AdminCampaignStatsResponse:
    """Admin only: aggregate campaign statistics."""
    return await service.get_admin_campaign_stats(db)


@router.get(
    "/admin/list",
    response_model=PaginatedResponse[AdminCampaignListItem],
    tags=["Admin - Campaigns"],
    summary="Admin List Campaigns",
    description="Paginated campaign list across all users with enriched metrics and user info.",
)
async def list_admin_campaigns(
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=10, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(default=None, description="Search campaign name, user email, ID"),
    status: Optional[str] = Query(default=None, description="Filter by status (all, published, draft, approved, archived)"),
    platform: Optional[str] = Query(default=None, description="Filter by platform (meta, google, both)"),
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[AdminCampaignListItem]:
    """Admin only: paginated campaign list with user details."""
    skip = (page - 1) * limit
    return await service.list_admin_campaigns(
        db, skip=skip, limit=limit, search=search, status=status, platform=platform
    )


@router.get(
    "/admin/{campaign_id}",
    response_model=AdminCampaignListItem,
    tags=["Admin - Campaigns"],
    summary="Admin Campaign Details",
    description="Get single campaign full details with user info for admin drawer.",
)
async def get_admin_campaign_details(
    campaign_id: str,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> AdminCampaignListItem:
    """Admin only: single campaign details."""
    return await service.get_admin_campaign_by_id(db, campaign_id)


# ── User-Facing Campaign Endpoints ───────────────────────────────────────────

@router.get("", response_model=CampaignListResponse)
async def list_campaigns(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
    platform: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignListResponse:
    """List all campaigns for the authenticated user with pagination."""
    return await service.list_campaigns(
        db, current_user.id, page, page_size, status, platform
    )



@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    """Get a single campaign by ID."""
    return await service.get_campaign(db, campaign_id, current_user.id)


@router.get("/{campaign_id}/review", response_model=list[ReadinessItem])
async def get_campaign_review(
    campaign_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ReadinessItem]:
    """What Meta's ad review has done to a campaign's ads — in review, or rejected and why.

    Empty when nothing needs saying. Cards use the same wire shape as the readiness
    list, so the frontend renders them with the same component.
    """
    return [
        ReadinessItem(**card)
        for card in await service.get_review(db, campaign_id, current_user)
    ]


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Archive (soft-delete) a campaign."""
    await service.delete_campaign(db, campaign_id, current_user.id)

# direct meta ads api connecting api 
@router.get("/meta/list", status_code=status.HTTP_200_OK)
async def get_campaigns_from_meta(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all meta campaigns for the authenticated user."""
    return await service.get_campaigns_from_meta(db, current_user)
    

# direct get adset from meta 
@router.get("/meta/adset", status_code=status.HTTP_200_OK)
async def get_adsets_from_meta(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all meta adsets for the authenticated user."""
    return await service.get_adsets_from_meta(db, current_user)