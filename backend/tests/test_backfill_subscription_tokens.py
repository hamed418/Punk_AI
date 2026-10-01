"""scripts/backfill_subscription_tokens.py — the one-off billing repair.

It writes production billing data, so what it selects matters more than usual:
funding a subscription that a renewal already topped up, or one that was canceled,
or moving a user who pays for several accounts, would each be a fresh bug.

Real in-memory SQLite. The script's functions take a session, so nothing here
touches AsyncSessionLocal.
"""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import app.api.router  # noqa: F401 — registers every module's models before mapper configure

# TokenTransaction.tx_metadata is Postgres JSONB; render it as JSON on SQLite.
SQLiteTypeCompiler.visit_JSONB = SQLiteTypeCompiler.visit_JSON

from app.modules.ads.models import AdsAccount, OAuthToken
from app.modules.subscription.models import (
    Subscription,
    SubscriptionTokenAllocation,
    TokenTransaction,
    UserSubscription,
)
from app.modules.user.models import User
from app.shared.enums import AdPlatform, SubscriptionPaymentStatus, SubscriptionStatus

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backfill_subscription_tokens.py"
_spec = importlib.util.spec_from_file_location("backfill_subscription_tokens", _SCRIPT)
backfill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill)


@pytest_asyncio.fixture
async def db():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        for model in (User, OAuthToken, AdsAccount, Subscription, UserSubscription,
                      SubscriptionTokenAllocation, TokenTransaction):
            await conn.run_sync(model.__table__.create)
    async with AsyncSession(eng, expire_on_commit=False) as session:
        yield session
    await eng.dispose()


async def _user(db) -> User:
    u = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@x.test", password_hash="x")
    db.add(u)
    await db.commit()
    return u


def _sub(user, account, **overrides) -> UserSubscription:
    defaults = dict(
        id=uuid.uuid4(), user_id=user.id, ad_account_id=account, total_tokens=500,
        used_tokens=0, remaining_tokens=0,
        status=SubscriptionStatus.active, payment_status=SubscriptionPaymentStatus.paid,
    )
    defaults.update(overrides)
    return UserSubscription(**defaults)


@pytest.mark.asyncio
async def test_funds_only_subscriptions_that_were_never_funded(db):
    u = await _user(db)
    never_funded = _sub(u, "act_1")
    renewal_topped_up = _sub(u, "act_2", remaining_tokens=500)  # month 2+ already worked
    canceled = _sub(u, "act_3", status=SubscriptionStatus.canceled)
    already_allocated = _sub(u, "act_4")
    db.add_all([never_funded, renewal_topped_up, canceled, already_allocated])
    await db.commit()
    db.add(SubscriptionTokenAllocation(subscription_id=already_allocated.id, user_id=u.id))
    await db.commit()

    # Dry run: reports it, writes nothing.
    assert await backfill.backfill_unfunded(db, confirm=False) == 1
    await db.refresh(never_funded)
    assert never_funded.remaining_tokens == 0

    assert await backfill.backfill_unfunded(db, confirm=True) == 1
    for s in (never_funded, renewal_topped_up, canceled, already_allocated):
        await db.refresh(s)
    assert never_funded.remaining_tokens == 500
    assert renewal_topped_up.remaining_tokens == 500
    assert canceled.remaining_tokens == 0
    assert already_allocated.remaining_tokens == 0  # had a row: not ours to redo

    # Re-run is a no-op (it now has an allocation row).
    assert await backfill.backfill_unfunded(db, confirm=True) == 0


async def _connect(db, user, accounts, selected):
    token = OAuthToken(
        id=uuid.uuid4(), user_id=user.id, platform=AdPlatform.meta, access_token="tok",
        accessible_accounts=[{"id": a, "name": a} for a in accounts],
        selected_account=selected, ad_account_id=selected,
    )
    user.select_meta_id = selected
    db.add(token)
    await db.commit()
    return token


@pytest.mark.asyncio
async def test_selection_moves_only_a_user_with_exactly_one_paid_account(db):
    drifted = await _user(db)
    t_drifted = await _connect(db, drifted, ["act_A", "act_B"], selected="act_A")
    db.add(_sub(drifted, "act_B"))  # paid for B, still pointed at A

    several = await _user(db)
    t_several = await _connect(db, several, ["act_A", "act_B"], selected="act_A")
    db.add_all([_sub(several, "act_A"), _sub(several, "act_B")])  # ambiguous: leave alone

    in_step = await _user(db)
    await _connect(db, in_step, ["act_A"], selected="act_A")
    db.add(_sub(in_step, "act_A"))  # already right
    await db.commit()

    assert await backfill.reconcile_selection(db, confirm=False) == 1
    await db.refresh(t_drifted)
    assert t_drifted.selected_account == "act_A"  # dry run wrote nothing

    assert await backfill.reconcile_selection(db, confirm=True) == 1
    await db.refresh(t_drifted)
    await db.refresh(drifted)
    await db.refresh(t_several)
    assert t_drifted.selected_account == "act_B"
    assert drifted.select_meta_id == "act_B"
    assert t_several.selected_account == "act_A"
