from sqlalchemy import select, func, cast, Date, or_, and_, distinct
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from .models import User
from app.modules.ads.models import OAuthToken, AdsAccount
from app.modules.subscription.models import UserSubscription, Subscription
from app.modules.campaigns.models import Campaign
from app.modules.chat.models import Conversation
from typing import Optional
from datetime import datetime, timezone

# Valid statuses confirmed in the Postgres enum (no 'complete')
ACTIVE_SUB_STATUSES = ["active", "trialing", "paid"]


class UserRepository:
    async def get_user_by_id(self, db: AsyncSession, user_id: str) -> Optional[User]:
        result = await db.execute(
            select(User)
            .where(User.id == user_id)
            .options(
                selectinload(User.oauth_tokens).selectinload(OAuthToken.ads_accounts).selectinload(AdsAccount.subscription),
                selectinload(User.subscriptions).selectinload(UserSubscription.plan),
                selectinload(User.ads_accounts).selectinload(AdsAccount.subscription)
            )
        )
        return result.scalar_one_or_none()

    async def update_user(self, db: AsyncSession, user: User):
        db.add(user)
        await db.commit()
        return await self.get_user_by_id(db, str(user.id))

    async def get_users(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        search: Optional[str] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        date: Optional[str] = None,
        plan: Optional[str] = None,  # "free" = no active sub; anything else = plan name
    ):
        query = select(User).options(
            selectinload(User.subscriptions).selectinload(UserSubscription.plan),
            selectinload(User.campaigns),
            selectinload(User.conversations),
            selectinload(User.sessions),
        )

        # Search both full_name and email
        if search:
            pattern = f"%{search}%"
            query = query.where(
                or_(
                    User.full_name.ilike(pattern),
                    User.email.ilike(pattern),
                )
            )
        if role:
            query = query.where(User.role == role)
        if is_active is not None:
            query = query.where(User.is_active == is_active)
        if date:
            query = query.where(cast(User.created_at, Date) == date)

        if plan:
            plan_lower = plan.strip().lower()
            if plan_lower == "free":
                # "Free" = users who have NO active/trialing/paid subscription
                paid_user_ids = (
                    select(UserSubscription.user_id)
                    .where(
                        and_(
                            UserSubscription.user_id.isnot(None),
                            UserSubscription.status.in_(ACTIVE_SUB_STATUSES),
                        )
                    )
                    .scalar_subquery()
                )
                query = query.where(User.id.notin_(paid_user_ids))
            else:
                # Named plan (Starter / Standard / Pro …) — find by subscription name
                plan_subq = (
                    select(UserSubscription.user_id)
                    .join(Subscription, UserSubscription.plan_id == Subscription.id)
                    .where(
                        and_(
                            UserSubscription.status.in_(ACTIVE_SUB_STATUSES),
                            func.lower(Subscription.name) == plan_lower,
                        )
                    )
                    .scalar_subquery()
                )
                query = query.where(User.id.in_(plan_subq))

        # Total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar_one()

        # Paginated data
        query = query.order_by(User.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(query)
        users = result.scalars().all()

        return total, users

    async def get_user_details_with_stats(self, db: AsyncSession, user_id: str) -> Optional[User]:
        result = await db.execute(
            select(User)
            .where(User.id == user_id)
            .options(
                selectinload(User.oauth_tokens).selectinload(OAuthToken.ads_accounts).selectinload(AdsAccount.subscription),
                selectinload(User.subscriptions).selectinload(UserSubscription.plan),
                selectinload(User.ads_accounts).selectinload(AdsAccount.subscription),
                selectinload(User.sessions),
                selectinload(User.campaigns),
                selectinload(User.conversations),
            )
        )
        return result.scalar_one_or_none()

    async def get_user_stats(self, db: AsyncSession) -> dict:
        """Aggregate stats for the admin users overview cards."""
        from datetime import timedelta
        from app.modules.user.models import UserSession

        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        thirty_days_ago = now - timedelta(days=30)

        # Total registered users
        total = (await db.execute(select(func.count()).select_from(User))).scalar_one()

        # Active (30d): distinct users who had a session active in the last 30 days
        active_30d = (await db.execute(
            select(func.count(distinct(UserSession.user_id)))
            .where(UserSession.last_active_at >= thirty_days_ago)
        )).scalar_one()

        # Suspended: accounts that have been deactivated (is_active=False)
        suspended = (await db.execute(
            select(func.count()).select_from(User).where(User.is_active == False)
        )).scalar_one()

        # New this month: registered since the 1st of current month
        new_this_month = (await db.execute(
            select(func.count()).select_from(User).where(User.created_at >= month_start)
        )).scalar_one()

        # Plan breakdown — only valid DB statuses (no 'complete')
        subs_result = await db.execute(
            select(UserSubscription)
            .options(selectinload(UserSubscription.plan))
            .where(UserSubscription.status.in_(ACTIVE_SUB_STATUSES))
        )
        plan_counts: dict[str, int] = {}
        for sub in subs_result.scalars().all():
            plan_name = sub.plan.name if sub.plan else "Unknown"
            plan_counts[plan_name] = plan_counts.get(plan_name, 0) + 1

        # Paying users: distinct users with at least one active subscription
        paying_users = (await db.execute(
            select(func.count(distinct(UserSubscription.user_id)))
            .where(
                and_(
                    UserSubscription.user_id.isnot(None),
                    UserSubscription.status.in_(ACTIVE_SUB_STATUSES),
                )
            )
        )).scalar_one()

        return {
            "total_users": total,
            "active_users": active_30d,
            "new_this_month": new_this_month,
            "suspended_users": suspended,
            "paying_users": paying_users,
            "plan_breakdown": plan_counts,
        }
