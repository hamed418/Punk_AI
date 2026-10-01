"""
scripts/token_meter_admin.py
────────────────────────────
One-off admin tool to inspect / reset the per-user token meter and raise the
plan cap. Needed after switching billing to total-token accounting, which
fills usage_token ~10x faster than the old output-only counting.

Usage (from repo root or backend/):
    python -m scripts.token_meter_admin --email user@example.com            # inspect only
    python -m scripts.token_meter_admin --email user@example.com --apply    # reset meter + raise cap
    python -m scripts.token_meter_admin --email ... --apply --cap-multiplier 10  # custom raise
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.modules.user.models import User
 
from app.modules.subscription.models import UserSubscription, Subscription
from app.shared.enums import SubscriptionStatus


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--apply", action="store_true", help="perform writes (default: dry inspect)")
    ap.add_argument("--cap-multiplier", type=float, default=10.0,
                    help="multiply plan.total_token_can_use by this when --apply")
    args = ap.parse_args()

    async with AsyncSessionLocal() as db:
        user = (await db.execute(
            select(User).where(User.email == args.email)
        )).scalar_one_or_none()
        if not user:
            print(f"No user with email {args.email}")
            return

        sub = (await db.execute(
            select(UserSubscription).where(
                UserSubscription.user_id == user.id,
                UserSubscription.status == SubscriptionStatus.active,
            )
        )).scalar_one_or_none()
        if not sub:
            print(f"No ACTIVE subscription for {args.email}")
            return

        plan = (await db.execute(
            select(Subscription).where(Subscription.id == sub.plan_id)
        )).scalar_one_or_none()

        print("── BEFORE ──")
        print(f"  user            : {args.email} ({user.id})")
        print(f"  usage_token     : {sub.usage_token}")
        print(f"  plan_id         : {sub.plan_id}")
        print(f"  total_can_use   : {plan.total_token_can_use if plan else 'NO PLAN'}")

        if not args.apply:
            print("\n(dry run — pass --apply to reset meter and raise cap)")
            return

        sub.usage_token = 0
        if plan:
            plan.total_token_can_use = int(plan.total_token_can_use * args.cap_multiplier)
        await db.commit()

        print("\n── AFTER ──")
        print(f"  usage_token     : {sub.usage_token}")
        print(f"  total_can_use   : {plan.total_token_can_use if plan else 'NO PLAN'}")
        if plan:
            print(f"\nNOTE: total_token_can_use is plan-level — this raises the cap "
                  f"for EVERY user on plan {sub.plan_id}.")


if __name__ == "__main__":
    asyncio.run(main())
