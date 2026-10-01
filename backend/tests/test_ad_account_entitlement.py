"""app/services/entitlement.py — the per-ad-account subscription gate.

Punk sells subscriptions per Meta ad account, not per user. The check that
was supposed to enforce this (AdsAccountSubscriptionService.is_ads_account_authorized)
had zero callers anywhere, AND a fail-open branch: a subscription with no
ad_account_id (the common case — guest/early-access rows) authorized every
account for that user. ad_account_is_paid replaces it with one query and no
branch to get wrong.

This runs against a REAL in-memory SQLite DB (not a mocked session) — the
regression this file exists for is in the WHERE clause itself (does NULL
actually fail to match?), which a mocked `db.execute` can't prove either way.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import app.api.router  # noqa: F401 — registers every module's models before mapper configure
from app.modules.subscription.models import UserSubscription
from app.services.entitlement import ad_account_is_paid
from app.shared.enums import SubscriptionPaymentStatus, SubscriptionStatus


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(UserSubscription.__table__.create)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    async with AsyncSession(engine) as session:
        yield session


def _sub(**overrides) -> UserSubscription:
    defaults = dict(
        id=uuid.uuid4(),
        total_tokens=100,
        used_tokens=0,
        remaining_tokens=100,
        status=SubscriptionStatus.active,
        payment_status=SubscriptionPaymentStatus.paid,
    )
    defaults.update(overrides)
    return UserSubscription(**defaults)


async def _seed(db: AsyncSession, *subs: UserSubscription) -> None:
    db.add_all(subs)
    await db.commit()


@pytest.mark.asyncio
async def test_matching_account_is_paid(db):
    uid = uuid.uuid4()
    await _seed(db, _sub(user_id=uid, ad_account_id="act_paid"))

    assert await ad_account_is_paid(uid, "act_paid", db) is True


@pytest.mark.asyncio
async def test_unscoped_subscription_does_not_authorize_any_account(db):
    """THE fail-open regression. An active subscription with no
    ad_account_id used to authorize every account for the user — this is
    the one bug this whole module exists to close."""
    uid = uuid.uuid4()
    await _seed(db, _sub(user_id=uid, ad_account_id=None))

    assert await ad_account_is_paid(uid, "act_anything", db) is False


@pytest.mark.asyncio
async def test_subscription_for_a_different_account_does_not_authorize_this_one(db):
    uid = uuid.uuid4()
    await _seed(db, _sub(user_id=uid, ad_account_id="act_B"))

    assert await ad_account_is_paid(uid, "act_A", db) is False


@pytest.mark.asyncio
async def test_canceled_subscription_does_not_authorize(db):
    uid = uuid.uuid4()
    await _seed(db, _sub(user_id=uid, ad_account_id="act_paid", status=SubscriptionStatus.canceled))

    assert await ad_account_is_paid(uid, "act_paid", db) is False


@pytest.mark.asyncio
async def test_expired_period_end_does_not_authorize(db):
    uid = uuid.uuid4()
    await _seed(db, _sub(
        user_id=uid, ad_account_id="act_paid",
        current_period_end=datetime.utcnow() - timedelta(days=1),
    ))

    assert await ad_account_is_paid(uid, "act_paid", db) is False


@pytest.mark.asyncio
async def test_active_with_no_period_end_never_expires(db):
    uid = uuid.uuid4()
    await _seed(db, _sub(user_id=uid, ad_account_id="act_paid", current_period_end=None))

    assert await ad_account_is_paid(uid, "act_paid", db) is True


@pytest.mark.asyncio
async def test_falsy_inputs_never_authorize(db):
    uid = uuid.uuid4()
    await _seed(db, _sub(user_id=uid, ad_account_id="act_paid"))

    assert await ad_account_is_paid(uid, "", db) is False
    assert await ad_account_is_paid(uid, None, db) is False
    assert await ad_account_is_paid("", "act_paid", db) is False
    assert await ad_account_is_paid(None, "act_paid", db) is False
    assert await ad_account_is_paid("not-a-uuid", "act_paid", db) is False
