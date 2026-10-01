"""
scripts/backfill_subscription_tokens.py
────────────────────────────────────────
One-off repair for the billing bugs fixed alongside this script. Run once, AFTER
the fix is deployed. Safe to re-run.

1. Unfunded subscriptions. ``allocate_subscription_tokens`` used to stage the
   first period's tokens and never commit (its caller had already committed, and
   ``get_db`` never does), so every subscription created before the fix is paid,
   ``active`` — and holds ``remaining_tokens = 0``, no ``subscription_token_
   allocations`` row, and ``users.isSubscriptionActive`` false. Those customers
   have been running on the free wallet. Renewals were never affected
   (``process_invoice_paid`` commits itself), which is why this targets only rows
   that were never funded at all: ``remaining_tokens = 0 AND used_tokens = 0``.
   A subscription a renewal already topped up is left alone.

2. Drifted selection. Paying for ad account B used to leave
   ``oauth_tokens.selected_account`` (what publish reads) on A. Where a user has
   EXACTLY ONE paid account and it is not the selected one, both selection columns
   are moved to it. A user with several paid accounts is left alone — guessing
   which one they meant is worse than making them click once.

Dry run by default — prints what it would do and touches nothing::

    .venv/Scripts/python.exe scripts/backfill_subscription_tokens.py

Add ``--confirm`` to write::

    .venv/Scripts/python.exe scripts/backfill_subscription_tokens.py --confirm

NOTE: the local ``.env`` points at the PRODUCTION database. Run this from the
deploy environment on purpose, not from a dev machine by accident.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

# Registers every ORM model before any query runs (see
# sweep_abandoned_maid_extractions.py for why a standalone script needs this).
import app.api.router  # noqa: F401,E402

from app.db.database import AsyncSessionLocal  # noqa: E402
from app.modules.ads.models import OAuthToken  # noqa: E402
from app.modules.ads.repository import AdsRepository  # noqa: E402
from app.modules.subscription.models import (  # noqa: E402
    SubscriptionTokenAllocation,
    UserSubscription,
)
from app.modules.subscription.service import SubscriptionLinkingService  # noqa: E402
from app.modules.user.models import User  # noqa: E402
from app.shared.enums import AdPlatform, SubscriptionPaymentStatus, SubscriptionStatus  # noqa: E402


async def backfill_unfunded(db, confirm: bool) -> int:
    never_allocated = ~(
        select(SubscriptionTokenAllocation.id)
        .where(SubscriptionTokenAllocation.subscription_id == UserSubscription.id)
        .exists()
    )
    subs = (await db.execute(
        select(UserSubscription).where(
            UserSubscription.user_id.is_not(None),
            UserSubscription.status == SubscriptionStatus.active,
            UserSubscription.payment_status == SubscriptionPaymentStatus.paid,
            UserSubscription.total_tokens > 0,
            UserSubscription.remaining_tokens == 0,
            UserSubscription.used_tokens == 0,
            never_allocated,
        )
    )).scalars().all()

    for sub in subs:
        print(f"  fund   sub={sub.id} user={sub.user_id} account={sub.ad_account_id} "
              f"+{sub.total_tokens} tokens")
        if confirm:
            user = await db.get(User, sub.user_id)
            # Commits internally, and is idempotent via SubscriptionTokenAllocation.
            await SubscriptionLinkingService.allocate_subscription_tokens(db, sub, user)
    return len(subs)


async def reconcile_selection(db, confirm: bool) -> int:
    paid = (await db.execute(
        select(UserSubscription).where(
            UserSubscription.user_id.is_not(None),
            UserSubscription.ad_account_id.is_not(None),
            UserSubscription.status.in_([SubscriptionStatus.active, SubscriptionStatus.trialing]),
        )
    )).scalars().all()

    by_user: dict = defaultdict(set)
    for sub in paid:
        by_user[sub.user_id].add(sub.ad_account_id)

    moved = 0
    for user_id, accounts in by_user.items():
        if len(accounts) != 1:
            continue  # several paid accounts: not ours to guess
        (account,) = accounts
        token = (await db.execute(
            select(OAuthToken).where(
                OAuthToken.user_id == user_id, OAuthToken.platform == AdPlatform.meta
            )
        )).scalar_one_or_none()
        if token is None or token.selected_account == account:
            continue
        print(f"  select user={user_id} {token.selected_account} -> {account}")
        moved += 1
        if confirm:
            # Same helper every live selection write goes through: it refuses an
            # account the connection doesn't grant, and moves both columns.
            if not await AdsRepository().update_selected_account(db, user_id, account):
                print(f"         skipped — {account} is not granted by that connection")
    return moved


async def main(confirm: bool) -> None:
    print("DRY RUN — nothing will be written (pass --confirm to apply)\n" if not confirm else "APPLYING\n")
    async with AsyncSessionLocal() as db:
        print("Unfunded subscriptions:")
        funded = await backfill_unfunded(db, confirm)
        print(f"  -> {funded}\n")
        print("Drifted account selection:")
        moved = await reconcile_selection(db, confirm)
        print(f"  -> {moved}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--confirm", action="store_true", help="write changes (default is a dry run)")
    asyncio.run(main(parser.parse_args().confirm))
