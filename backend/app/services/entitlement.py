"""
services/entitlement.py
────────────────────────
Single source of truth for "is this ad account paid for". Punk sells
subscriptions per Meta ad account, not per user — a subscription only
authorizes the one `ad_account_id` it was bought/assigned for.

Centralized for the same reason `oauth.py`'s `selected_account or ad_account_id`
precedence was: letting each caller re-derive "is this account authorized"
is how the previous check (`AdsAccountSubscriptionService.is_ads_account_authorized`)
grew a fail-open branch that treated an unscoped subscription as covering
every account. One query, one place, no branch to get wrong.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import or_, select

from app.db.database import AsyncSessionLocal
from app.modules.subscription.models import UserSubscription
from app.shared.enums import SubscriptionStatus


async def ad_account_is_paid(
    user_id: str | uuid.UUID, ad_account_id: str | None, db=None
) -> bool:
    """True iff `user_id` holds an active/trialing subscription bound to
    exactly `ad_account_id`.

    A subscription with `ad_account_id IS NULL` is unscoped, not universal —
    it authorizes nothing here. It becomes usable only once assigned to an
    account (`POST /payment/subscription/assign-ad-account`).
    """
    if not ad_account_id or not user_id:
        return False
    try:
        uid = uuid.UUID(str(user_id))
    except ValueError:
        return False

    # `current_period_end` is stored naive-UTC (see repository.py's
    # get_active_subscriptions_by_user, which compares the same way).
    now = datetime.utcnow()
    query = select(UserSubscription.id).where(
        UserSubscription.user_id == uid,
        UserSubscription.ad_account_id == ad_account_id,
        UserSubscription.status.in_([SubscriptionStatus.active, SubscriptionStatus.trialing]),
        or_(
            UserSubscription.current_period_end.is_(None),
            UserSubscription.current_period_end > now,
        ),
    ).limit(1)

    if db is not None:
        result = await db.execute(query)
        return result.scalar_one_or_none() is not None

    async with AsyncSessionLocal() as session:
        result = await session.execute(query)
        return result.scalar_one_or_none() is not None
