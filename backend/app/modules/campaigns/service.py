import asyncio
import uuid
from decimal import Decimal
import httpx
from typing import Optional
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.oauth import get_meta_credentials
from app.services.meta_ads import fetch_ad_account_currency, fetch_ad_review
from app.services.meta_insights import get_account_campaign_insights
from app.shared.enums import CampaignStatus
from app.shared.pagination import paginate
from app.modules.user.models import User
from app.modules.campaigns.repository import CampaignsRepository
from app.modules.campaigns.schemas import (
    CampaignListResponse,
    CampaignResponse,
    AdminCampaignListItem,
    AdminCampaignStatsResponse,
)

META_GRAPH_URL=settings.META_GRAPH_URL

# Meta caps paging at a few thousand rows, but `paging.next` is server-driven and
# a loop with no ceiling is a hang waiting for a bad cursor. 100 rows per page.
_MAX_PAGES = 50


async def _meta_creds(user: User) -> tuple[str, str]:
    """Return (access_token, ad_account) for this user's Meta connection.

    Replaces ``user.oauth_tokens[0]``, which assumed the first stored token was
    the Meta one: a user who connected Google first sent their Google token to
    graph.facebook.com, and a user with no tokens at all got an IndexError 500.
    ``get_meta_credentials`` filters on platform, is_valid and expiry, and renews
    a token that is close to lapsing.
    """
    creds = await get_meta_credentials(str(user.id))
    if not creds:
        raise HTTPException(status_code=400, detail="Meta account not connected")

    account = creds.get("selected_account") or creds.get("ad_account_id")
    if not account:
        raise HTTPException(
            status_code=400, detail="No Meta ad account selected"
        )
    return creds["access_token"], account


class CampaignsService:
    def __init__(self, repository: CampaignsRepository):
        self.repository = repository

    async def list_campaigns(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        page: int,
        page_size: int,
        status: Optional[str],
        platform: Optional[str]
    ) -> CampaignListResponse:
        
        if status:
            try:
                CampaignStatus(status)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

        # Scoped off the same source `campaign_saved` stamps rows from
        # (oauth_tokens.selected_account), not `users.select_meta_id` — that
        # column is a mirror the account switcher never wrote, so it was
        # either NULL (filter silently skipped) or stale (wrong account).
        creds = await get_meta_credentials(str(user_id))
        account = (creds or {}).get("ad_account_id")
        if not account:
            return CampaignListResponse(results=[], total=0, page=page, page_size=page_size)

        campaigns, total = await self.repository.list_campaigns(
            db, user_id, page, page_size, status, platform, account
        )

        return CampaignListResponse(
            results=[CampaignResponse.model_validate(c) for c in campaigns],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_campaign(self, db: AsyncSession, campaign_id: str, user_id: uuid.UUID) -> CampaignResponse:
        campaign = await self.repository.get_campaign(db, campaign_id, user_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        return CampaignResponse.model_validate(campaign)

    async def get_review(self, db: AsyncSession, campaign_id: str, user: User) -> list[dict]:
        """What Meta's ad review has done to this campaign's ads, as fix-it cards.

        Keyed on Punk's campaign id and resolved to Meta's here: ``ext_campaign_id``
        holds only the PRIMARY campaign, and an app plan publishes one per store with
        the rest in the publish ledger — same union as ``list_user_campaigns``. The
        ownership check is on Punk's id; Meta enforces access to its own.

        ``[]`` for a draft, an unconnected user, or an unreadable status: a review
        card is optional garnish on the page, never worth an error on it.
        """
        campaign = await self.repository.get_campaign(db, campaign_id, user.id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="Campaign not found")

        ids = {campaign.ext_campaign_id} | set(
            ((campaign.publish_state or {}).get("campaigns") or {}).values()
        )
        ids = {str(i) for i in ids if i}
        if not ids:
            return []
        creds = await get_meta_credentials(str(user.id))
        if not creds:
            return []

        from app.services import meta_remediation

        per_campaign = await asyncio.gather(
            *(fetch_ad_review(i, creds["access_token"]) for i in sorted(ids))
        )
        return meta_remediation.review_cards(ad for ads in per_campaign for ad in ads)

    async def delete_campaign(self, db: AsyncSession, campaign_id: str, user_id: uuid.UUID) -> None:
        success = await self.repository.archive_campaign(db, campaign_id, user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Campaign not found")

    # direct meta connection api logic srvice here 

    async def get_campaigns_from_meta(
        self,
        db: AsyncSession,
        user: User
    ):
        meta_access_token, meta_ads_account = await _meta_creds(user)
        campaign_url = (
            f"{META_GRAPH_URL}{meta_ads_account}/campaigns"
        )

        params = {
            "fields": (
                "id,name,status,effective_status,"
                "objective, buying_type,"
                "daily_budget,lifetime_budget,"
                "start_time,stop_time,"
                "created_time,updated_time"
            ),
            "access_token": meta_access_token,
            "limit": 100,
        }

        campaigns = []
        # Hitting the page cap and running out of pages both exit this loop the
        # same way — `complete` tells campaign_saved which one happened, since
        # only a fully-paged sync is trustworthy enough to archive campaigns
        # that this response no longer mentions.
        complete = False

        async with httpx.AsyncClient() as client:

            for _ in range(_MAX_PAGES):

                if not campaign_url:
                    complete = True
                    break

                response = await client.get(
                    campaign_url,
                    params=params
                )

                response.raise_for_status()

                data = response.json()

                campaigns.extend(data.get("data", []))


                # After first request, the next URL already contains
                # the access_token and parameters
                campaign_url = (
                    data.get("paging", {})
                    .get("next")
                )

                params = None

        # Best-effort — a dead token or throttle must not block the campaign
        # list itself from syncing, so both degrade to falsy and campaign_saved
        # simply leaves whatever metrics/currency a row already had.
        insights = await get_account_campaign_insights(meta_ads_account, meta_access_token)
        currency = (await fetch_ad_account_currency(meta_ads_account, meta_access_token)).get("currency")

        await self.repository.campaign_saved(
            db,
            user.id,
            campaigns,
            meta_ads_account,
            insights=insights,
            currency=currency,
            complete=complete,
        )
        return {
            "total_campaigns": len(campaigns),
            "campaigns": campaigns
        }

# get adset form meta 

    async def get_adsets_from_meta(
        self,
        db: AsyncSession,
        user: User
        ):
        meta_access_token, meta_ads_account = await _meta_creds(user)
        adset_url = (
            f"{META_GRAPH_URL}{meta_ads_account}/adsets"
        )

        params = {
            "fields": (
                "id,name,status,effective_status,"
                "objective, buying_type,campaign_id,"
                "daily_budget,lifetime_budget,"
                "start_time,stop_time,"
                "created_time,updated_time"
            ),
                "access_token": meta_access_token,
                "limit": 100,
            }

        adsets = []

        async with httpx.AsyncClient() as client:

            for _ in range(_MAX_PAGES):

                if not adset_url:
                    break

                response = await client.get(
                    adset_url,
                        params=params
                    )
                response.raise_for_status()
                data = response.json()
                adsets.extend(data.get("data", []))
                # After first request, the next URL already contains
                # the access_token and parameters
                adset_url = (
                    data.get("paging", {})
                    .get("next")
                )

                params = None
        return {
                "total_adsets": len(adsets),
                "adsets": adsets
            }

    # ── Admin Panel Dedicated Service Methods ──────────────────────────────────

    async def list_admin_campaigns(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 10,
        search: Optional[str] = None,
        status: Optional[str] = None,
        platform: Optional[str] = None,
    ):
        campaigns, total = await self.repository.list_admin_campaigns(
            db, skip=skip, limit=limit, search=search, status=status, platform=platform
        )

        data = []
        for c in campaigns:
            daily_budget = c.daily_budget_usd
            if daily_budget is None and c.campaign_plan and isinstance(c.campaign_plan, dict):
                adsets = c.campaign_plan.get("adsets")
                if isinstance(adsets, list) and len(adsets) > 0 and isinstance(adsets[0], dict):
                    raw_b = adsets[0].get("daily_budget")
                    if raw_b:
                        daily_budget = Decimal(str(raw_b / 100.0 if raw_b > 100 else raw_b))
                if daily_budget is None:
                    raw_b = c.campaign_plan.get("daily_budget")
                    if raw_b:
                        daily_budget = Decimal(str(raw_b / 100.0 if raw_b > 100 else raw_b))

            impressions = c.impressions or 0
            clicks = c.clicks or 0
            ctr = (float(clicks) / float(impressions) * 100.0) if impressions > 0 else 0.0

            item = AdminCampaignListItem(
                id=c.id,
                name=c.name,
                platform=c.platform,
                status=c.status,
                user_id=c.user_id,
                user_email=c.user.email if c.user else None,
                user_name=c.user.full_name if c.user else None,
                daily_budget_usd=daily_budget,
                monthly_budget_usd=c.monthly_budget_usd,
                spend_usd=c.spend_usd or Decimal("0.00"),
                impressions=impressions,
                clicks=clicks,
                conversions=c.conversions or 0,
                ctr=round(ctr, 2),
                roas=c.roas,
                cpa_usd=c.cpa_usd,
                start_date=c.start_date,
                end_date=c.end_date,
                created_at=c.created_at,
                updated_at=c.updated_at,
                campaign_plan=c.campaign_plan,
            )
            data.append(item)

        page = (skip // limit) + 1
        return paginate(data=data, total=total, page=page, limit=limit)

    async def get_admin_campaign_stats(self, db: AsyncSession) -> AdminCampaignStatsResponse:
        stats = await self.repository.get_admin_campaign_stats(db)
        return AdminCampaignStatsResponse(**stats)

    async def get_admin_campaign_by_id(self, db: AsyncSession, campaign_id: str) -> AdminCampaignListItem:
        try:
            cid = uuid.UUID(campaign_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid campaign ID format")

        c = await self.repository.get_admin_campaign_by_id(db, cid)
        if not c:
            raise HTTPException(status_code=404, detail="Campaign not found")

        daily_budget = c.daily_budget_usd
        if daily_budget is None and c.campaign_plan and isinstance(c.campaign_plan, dict):
            adsets = c.campaign_plan.get("adsets")
            if isinstance(adsets, list) and len(adsets) > 0 and isinstance(adsets[0], dict):
                raw_b = adsets[0].get("daily_budget")
                if raw_b:
                    daily_budget = Decimal(str(raw_b / 100.0 if raw_b > 100 else raw_b))

        impressions = c.impressions or 0
        clicks = c.clicks or 0
        ctr = (float(clicks) / float(impressions) * 100.0) if impressions > 0 else 0.0

        return AdminCampaignListItem(
            id=c.id,
            name=c.name,
            platform=c.platform,
            status=c.status,
            user_id=c.user_id,
            user_email=c.user.email if c.user else None,
            user_name=c.user.full_name if c.user else None,
            daily_budget_usd=daily_budget,
            monthly_budget_usd=c.monthly_budget_usd,
            spend_usd=c.spend_usd or Decimal("0.00"),
            impressions=impressions,
            clicks=clicks,
            conversions=c.conversions or 0,
            ctr=round(ctr, 2),
            roas=c.roas,
            cpa_usd=c.cpa_usd,
            start_date=c.start_date,
            end_date=c.end_date,
            created_at=c.created_at,
            updated_at=c.updated_at,
            campaign_plan=c.campaign_plan,
        )

