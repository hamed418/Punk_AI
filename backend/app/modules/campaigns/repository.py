import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple, List
from sqlalchemy import select, func, update, insert, exists, or_, and_, cast, String
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
import app.db.model_registry  # noqa: Ensure all models are imported before mappers are configured
from app.modules.campaigns.models import Campaign
from app.modules.user.models import User
from app.services.meta_ads import _HIDDEN_CAMPAIGN_STATES
from app.services.meta_insights import _CONVERSION_ACTIONS
from app.shared.enums import AdPlatform, CampaignStatus

class CampaignsRepository:
    async def list_campaigns(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        page: int,
        page_size: int,
        status: Optional[str] = None,
        platform: Optional[str] = None,
        meta_ads_id: Optional[str] = None
    ) -> Tuple[List[Campaign], int]:
        query = select(Campaign).where(Campaign.user_id == user_id)

        if status:
            status_enum = CampaignStatus(status)
            query = query.where(Campaign.status == status_enum)
        else:
            # A campaign deleted in Meta gets archived by the sync, not
            # removed — so without an explicit status filter it must be the
            # one thing excluded by default, or archiving is invisible.
            query = query.where(Campaign.status != CampaignStatus.archived)

        if platform:
            query = query.where(Campaign.platform == platform)

        if meta_ads_id:
            # Rows imported from an ad account the user is no longer on stay
            # stamped with that account's id forever (nothing deletes them on
            # disconnect) — so a plain equality-or-skip filter is how campaigns
            # from other accounts used to leak through.
            #
            # The only tolerated NULL is a genuine draft that has never touched
            # Meta at all — no `ext_campaign_id`, so there is nothing in Ad
            # Manager to check it against. The moment a row has an
            # `ext_campaign_id` (a publish attempt happened), its visibility
            # is decided ONLY by whether Meta's sync still returns it
            # (`campaign_saved`'s absence-archive below) — never by age or by
            # whether `meta_ads_id` happened to get stamped. A stray publish
            # that landed with `meta_ads_id` still NULL (a real gap this had)
            # must not get a permanent pass just because it's unattributed.
            draft_cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
            query = query.where(or_(
                Campaign.meta_ads_id == meta_ads_id,
                and_(
                    Campaign.meta_ads_id.is_(None),
                    Campaign.conversation_id.is_not(None),
                    Campaign.ext_campaign_id.is_(None),
                    Campaign.created_at >= draft_cutoff,
                ),
            ))

        count_result = await db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar_one()

        offset = (page - 1) * page_size
        query = query.order_by(Campaign.created_at.desc()).offset(offset).limit(page_size)
        
        result = await db.execute(query)
        campaigns = result.scalars().all()
        
        return list(campaigns), total

    async def get_campaign(self, db: AsyncSession, campaign_id: str, user_id: uuid.UUID) -> Optional[Campaign]:
        result = await db.execute(
            select(Campaign).where(
                Campaign.id == campaign_id,
                Campaign.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def archive_campaign(self, db: AsyncSession, campaign_id: str, user_id: uuid.UUID) -> bool:
        campaign = await self.get_campaign(db, campaign_id, user_id)
        if not campaign:
            return False

        await db.execute(
            update(Campaign)
            .where(Campaign.id == campaign_id)
            # CampaignStatus.ARCHIVED does not exist — the member is lowercase
            # `archived` (app/shared/enums.py), so this raised AttributeError on
            # every call. DELETE /campaigns/{id} has never worked.
            .values(status=CampaignStatus.archived)
        )
        await db.commit()
        return True

    # get single campaing 
    async def get_single_campaign(self, db: AsyncSession, campaign_id: str, user_id: uuid.UUID) -> Optional[Campaign]:
        result = await db.execute(
            select(
                exists().where(
                    Campaign.ext_campaign_id == campaign_id,
                    Campaign.user_id == user_id,
                )
            )
        )

        return result.scalar()

    def parse_meta_date(self, date_string: str | None):

        if not date_string:
            return None

        return datetime.strptime(
            date_string,
            "%Y-%m-%dT%H:%M:%S%z"
        )
    def _sum_conversions(self, actions: Optional[list]) -> int:
        total = 0
        for action in actions or []:
            if action.get("action_type") not in _CONVERSION_ACTIONS:
                continue
            try:
                total += int(float(action.get("value") or 0))
            except (TypeError, ValueError):
                continue
        return total

    def _metrics_from_insights(self, row: Optional[dict]) -> dict:
        """Map one Meta Insights row onto our metric columns.

        Empty dict on a miss — the caller merges this into a larger
        ``.values()``, and never overwriting an existing number with 0 is the
        whole point: a dead token or a campaign with genuinely no delivery
        both look like "no row here", and only the second one is real.
        """
        if not row:
            return {}
        values: dict = {}
        if row.get("spend") is not None:
            try:
                values["spend_usd"] = Decimal(str(row["spend"]))
            except InvalidOperation:
                pass
        if row.get("impressions") is not None:
            values["impressions"] = int(float(row["impressions"]))
        if row.get("clicks") is not None:
            values["clicks"] = int(float(row["clicks"]))
        conversions = self._sum_conversions(row.get("actions"))
        values["conversions"] = conversions
        purchase_roas = row.get("purchase_roas") or []
        if purchase_roas:
            try:
                values["roas"] = Decimal(str(purchase_roas[0].get("value")))
            except (TypeError, InvalidOperation):
                pass
        if conversions > 0 and values.get("spend_usd") is not None:
            values["cpa_usd"] = values["spend_usd"] / conversions
        return values

    def _daily_budget_usd(self, campaign: dict) -> Optional[Decimal]:
        # Minor units, like every other Meta budget figure.
        raw = campaign.get("daily_budget")
        if not raw:
            return None
        try:
            return Decimal(str(raw)) / 100
        except InvalidOperation:
            return None

    #direct save campaign from MCP
    async def campaign_saved(
        self,
        db: AsyncSession,
        user_id,
        campaigns: list[dict],
        meta_ads_id: str,
        insights: Optional[dict] = None,
        currency: Optional[str] = None,
        complete: bool = False,
    ) -> bool:

        insights = insights or {}
        campaign_values = []
        seen_ext_ids: set[str] = set()

        for campaign in campaigns:
            ext_id = campaign.get("id")
            if not ext_id:
                continue
            seen_ext_ids.add(ext_id)
            hidden = campaign.get("effective_status") in _HIDDEN_CAMPAIGN_STATES
            campaign["account_currency"] = currency or "USD"
            metrics = self._metrics_from_insights(insights.get(ext_id))

            if await self.get_single_campaign(db, ext_id, user_id):
                # Already known — refresh what Meta owns instead of skipping.
                # Skipping meant a campaign Punk published (and therefore already
                # had a row for) never picked up its live name, status or dates
                # from Meta again, so the list view showed the plan forever.
                values = {
                    "name": campaign.get("name"),
                    "campaign_plan": campaign,
                    "start_date": self.parse_meta_date(campaign.get("start_time")),
                    "meta_ads_id": meta_ads_id,
                    # A row that exists here is a live Meta object, not a Punk
                    # draft awaiting approval — `draft` never left this branch
                    # even for campaigns published months ago.
                    "status": CampaignStatus.archived if hidden else CampaignStatus.published,
                    **metrics,
                }
                daily_budget = self._daily_budget_usd(campaign)
                if daily_budget is not None:
                    values["daily_budget_usd"] = daily_budget
                await db.execute(
                    update(Campaign)
                    .where(
                        Campaign.ext_campaign_id == ext_id,
                        Campaign.user_id == user_id,
                    )
                    .values(**values)
                )
                continue

            if hidden:
                # Deleted/archived on Meta's side and we never had a row for
                # it — never import a corpse.
                continue

            campaign_values.append({
                "user_id": user_id,

                # Meta campaign name
                "name": campaign.get("name"),

                # Your platform enum
                "platform": AdPlatform.meta,

                # A synced row is a live Meta object, not a Punk draft.
                "status": CampaignStatus.published,

                # Meta campaign ID
                "ext_campaign_id": ext_id,

                "meta_ads_id": meta_ads_id,

                # Save complete Meta response
                "campaign_plan": campaign,

                # Meta dates
                "start_date": self.parse_meta_date(
                    campaign.get("start_time")
                ),

                # Meta response does not contain end_time in your example
                "end_date": None,

                "daily_budget_usd": self._daily_budget_usd(campaign),

                # `insert(Campaign)` runs as one bulk executemany — every dict
                # in the list must carry the same keys, so a metrics miss
                # fills these explicitly rather than omitting the key.
                "spend_usd": metrics.get("spend_usd"),
                "impressions": metrics.get("impressions", 0),
                "clicks": metrics.get("clicks", 0),
                "conversions": metrics.get("conversions", 0),
                "roas": metrics.get("roas"),
                "cpa_usd": metrics.get("cpa_usd"),
            })

        if campaign_values:
            await db.execute(
                insert(Campaign),
                campaign_values
            )

        if complete:
            # Only a fully-paged sync is trustworthy enough to say "Meta no
            # longer mentions this campaign" — a sync truncated by the page
            # cap must not archive campaigns it simply never got to.
            #
            # Scoped by account OR unattributed (NULL), never by account alone:
            # a row that was published before `meta_ads_id` got stamped (a
            # crashed sync, a code gap, anything) must not get a permanent
            # pass just because it belongs to no account on paper — if it
            # ever touched Meta and this account's sync no longer sees it,
            # it's gone. A row genuinely on a DIFFERENT connected account
            # (meta_ads_id set to something else) is left alone.
            await db.execute(
                update(Campaign)
                .where(
                    Campaign.user_id == user_id,
                    or_(Campaign.meta_ads_id == meta_ads_id, Campaign.meta_ads_id.is_(None)),
                    Campaign.ext_campaign_id.is_not(None),
                    Campaign.ext_campaign_id.notin_(seen_ext_ids or {""}),
                    Campaign.status != CampaignStatus.archived,
                )
                .values(status=CampaignStatus.archived)
            )

        await db.commit()

        return True
            
            
            
    # ── draft persistence (publish idempotency) ────────────────────────────────
    #
    # Nothing wrote to this table before. The plan lived only in the LangGraph
    # checkpoint, so a publish that died halfway had no record of what it had
    # already created in Meta — and the retry made a duplicate campaign.

    async def upsert_draft(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        conversation_id: Optional[uuid.UUID],
        name: str,
        campaign_plan: dict,
        daily_budget_usd: Optional[float] = None,
        start_date=None,
        end_date=None,
        meta_ads_id: Optional[str] = None,
    ) -> Campaign:
        """Create or refresh the draft row for a conversation.

        Keyed on ``conversation_id`` so re-approving an edited plan in the same
        chat updates the draft in place instead of accumulating rows. A publish
        that already started (``publish_state`` set) keeps its ledger — the plan
        may have been re-validated, but the Meta objects it already made are
        still out there and must not be forgotten.
        """
        existing: Optional[Campaign] = None
        if conversation_id is not None:
            result = await db.execute(
                select(Campaign).where(
                    Campaign.user_id == user_id,
                    Campaign.conversation_id == conversation_id,
                )
            )
            existing = result.scalars().first()

        if existing is None:
            existing = Campaign(
                user_id=user_id,
                conversation_id=conversation_id,
                platform=AdPlatform.meta,
            )
            db.add(existing)

        existing.name = name[:500]
        existing.campaign_plan = campaign_plan
        existing.status = CampaignStatus.approved
        existing.approved_by_user = True
        existing.approved_at = datetime.now(timezone.utc)
        if daily_budget_usd is not None:
            existing.daily_budget_usd = daily_budget_usd
        if start_date is not None:
            existing.start_date = start_date
        if end_date is not None:
            existing.end_date = end_date
        if meta_ads_id:
            existing.meta_ads_id = meta_ads_id

        await db.commit()
        await db.refresh(existing)
        return existing

    async def get_draft_for_conversation(
        self, db: AsyncSession, *, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Optional[Campaign]:
        result = await db.execute(
            select(Campaign).where(
                Campaign.user_id == user_id,
                Campaign.conversation_id == conversation_id,
            )
        )
        return result.scalars().first()

    async def save_publish_state(
        self, db: AsyncSession, campaign_id: uuid.UUID, publish_state: dict
    ) -> None:
        """Persist the publish ledger after each Meta object is created.

        Committed eagerly and individually: the whole point is to survive a crash
        mid-publish, which a deferred write would not.
        """
        values: dict = {"publish_state": publish_state}
        # An App-promotion plan publishes one campaign per app store, so the
        # scalar column takes the primary and the full list is preserved beside
        # it — dropping the second id orphaned that campaign from every reader
        # that does not open publish_state.
        campaigns = publish_state.get("campaigns") or {}
        campaign_ids = [campaigns[k] for k in sorted(campaigns, key=int)]
        if publish_state.get("campaign_id"):
            values["ext_campaign_id"] = str(publish_state["campaign_id"])
        elif campaign_ids:
            values["ext_campaign_id"] = str(campaign_ids[0])
        adsets = publish_state.get("adsets") or {}
        if adsets:
            # Sorted by ad set index, not dict-insertion order: these line up
            # positionally with the plan's ad sets wherever they are read back.
            values["ext_ad_group_ids"] = [adsets[k] for k in sorted(adsets, key=int)]
        # Once objects exist in Meta the row is no longer merely "approved".
        # Driven off the ledger rather than a separate call so the status can
        # never disagree with the ids sitting next to it.
        if campaign_ids or publish_state.get("campaign_id"):
            values["status"] = CampaignStatus.published

        await db.execute(update(Campaign).where(Campaign.id == campaign_id).values(**values))
        await db.commit()

    # ── Admin Panel Dedicated Queries ──────────────────────────────────────────

    async def list_admin_campaigns(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 10,
        search: Optional[str] = None,
        status: Optional[str] = None,
        platform: Optional[str] = None,
    ) -> Tuple[List[Campaign], int]:
        """Admin query: list all campaigns with joined user information, filtering, and pagination."""
        query = select(Campaign).outerjoin(User, Campaign.user_id == User.id)

        if search:
            search_filter = f"%{search.strip()}%"
            query = query.where(
                or_(
                    Campaign.name.ilike(search_filter),
                    User.email.ilike(search_filter),
                    User.full_name.ilike(search_filter),
                    cast(Campaign.id, String).ilike(search_filter),
                    Campaign.ext_campaign_id.ilike(search_filter),
                )
            )

        if status and status.lower() != "all":
            status_val = status.lower().strip()
            # Support common aliases: 'active' -> 'published'
            if status_val == "active":
                status_val = "published"
            try:
                status_enum = CampaignStatus(status_val)
                query = query.where(Campaign.status == status_enum)
            except ValueError:
                pass

        if platform and platform.lower() != "all":
            platform_val = platform.lower().strip()
            try:
                platform_enum = AdPlatform(platform_val)
                query = query.where(Campaign.platform == platform_enum)
            except ValueError:
                pass

        count_result = await db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar_one()

        query = (
            query.options(selectinload(Campaign.user))
            .order_by(Campaign.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(query)
        campaigns = result.scalars().all()
        return list(campaigns), total

    async def get_admin_campaign_stats(self, db: AsyncSession) -> dict:
        """Admin query: calculate aggregate statistics across all campaigns."""
        total_stmt = select(func.count(Campaign.id))
        total_res = await db.execute(total_stmt)
        total_campaigns = total_res.scalar() or 0

        active_stmt = select(func.count(Campaign.id)).where(
            Campaign.status.in_([CampaignStatus.published, CampaignStatus.approved])
        )
        active_res = await db.execute(active_stmt)
        active_campaigns = active_res.scalar() or 0

        spend_stmt = select(
            func.coalesce(func.sum(Campaign.spend_usd), 0),
            func.coalesce(func.sum(Campaign.clicks), 0),
            func.coalesce(func.sum(Campaign.impressions), 0),
            func.avg(Campaign.roas),
        )
        spend_res = await db.execute(spend_stmt)
        spend_row = spend_res.one()
        total_spend = float(spend_row[0] or 0.0)
        total_clicks = int(spend_row[1] or 0)
        total_impressions = int(spend_row[2] or 0)
        avg_roas = float(spend_row[3] or 0.0)
        avg_ctr = round((total_clicks / total_impressions * 100), 2) if total_impressions > 0 else 0.0

        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        new_stmt = select(func.count(Campaign.id)).where(Campaign.created_at >= seven_days_ago)
        new_res = await db.execute(new_stmt)
        new_this_week = new_res.scalar() or 0

        status_stmt = select(Campaign.status, func.count(Campaign.id)).group_by(Campaign.status)
        status_res = await db.execute(status_stmt)
        status_breakdown = {
            (r[0].value if hasattr(r[0], "value") else str(r[0])): r[1] for r in status_res.all()
        }

        platform_stmt = select(Campaign.platform, func.count(Campaign.id)).group_by(Campaign.platform)
        platform_res = await db.execute(platform_stmt)
        platform_breakdown = {
            (r[0].value if hasattr(r[0], "value") else str(r[0])): r[1] for r in platform_res.all()
        }

        return {
            "total_campaigns": total_campaigns,
            "active_campaigns": active_campaigns,
            "avg_ctr": avg_ctr,
            "total_spend": total_spend,
            "avg_roas": avg_roas,
            "new_this_week": new_this_week,
            "status_breakdown": status_breakdown,
            "platform_breakdown": platform_breakdown,
        }

    async def get_admin_campaign_by_id(self, db: AsyncSession, campaign_id: uuid.UUID) -> Optional[Campaign]:
        """Admin query: retrieve single campaign with loaded user relationship."""
        result = await db.execute(
            select(Campaign)
            .options(selectinload(Campaign.user))
            .where(Campaign.id == campaign_id)
        )
        return result.scalar_one_or_none()

