"""app/modules/subscription/service.py — token quota lives on the ad account.

Before this, every allocation path (checkout, signup linking, renewal) credited
tokens into `users.free_message_limit` — a single wallet shared across every
ad account a user pays for. Under a per-ad-account subscription model that
means a second paid account gets no extra quota at all. Allocation must
credit `UserSubscription.remaining_tokens` instead, and spend on one account
must not be payable out of another account's balance.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import app.api.router  # noqa: F401 — registers every module's models before mapper configure
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

# TokenTransaction.tx_metadata is Postgres JSONB, which the SQLite DDL
# compiler has no visit_JSONB for at all (unlike JSON) — render it the same
# as plain JSON for this in-memory test DB.
SQLiteTypeCompiler.visit_JSONB = SQLiteTypeCompiler.visit_JSON

from app.modules.ads.models import AdsAccount, OAuthToken
from app.modules.subscription.models import (
    Subscription,
    SubscriptionTokenAllocation,
    TokenTransaction,
    UserSubscription,
)
from app.modules.subscription.service import SubscriptionLinkingService, TokenService
from app.modules.user.models import User
from app.shared.enums import SubscriptionPaymentStatus, SubscriptionStatus


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(User.__table__.create)
        # User.oauth_tokens / .ads_accounts are lazy="selectin" — any query or
        # refresh() of a User fires them, so these tables must exist even
        # though this file never populates them.
        await conn.run_sync(OAuthToken.__table__.create)
        await conn.run_sync(AdsAccount.__table__.create)
        await conn.run_sync(Subscription.__table__.create)
        await conn.run_sync(UserSubscription.__table__.create)
        await conn.run_sync(SubscriptionTokenAllocation.__table__.create)
        await conn.run_sync(TokenTransaction.__table__.create)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    # expire_on_commit=False: tests keep using the same ORM objects across
    # commits, and an expired attribute reload outside an active greenlet
    # raises MissingGreenlet under the aiosqlite driver.
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session


@pytest_asyncio.fixture
async def user(db):
    u = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@x.test", password_hash="x", free_message_limit=0)
    db.add(u)
    await db.commit()
    return u


def _sub(user_id, ad_account_id, total_tokens=1000, **overrides):
    defaults = dict(
        id=uuid.uuid4(), user_id=user_id, ad_account_id=ad_account_id,
        total_tokens=total_tokens, used_tokens=0, remaining_tokens=0,
        status=SubscriptionStatus.active, payment_status=SubscriptionPaymentStatus.paid,
    )
    defaults.update(overrides)
    return UserSubscription(**defaults)


@pytest.mark.asyncio
async def test_allocation_credits_the_subscription_not_the_user_wallet(db, user):
    sub = _sub(user.id, "act_A", total_tokens=500)
    db.add(sub)
    await db.commit()

    await SubscriptionLinkingService.allocate_subscription_tokens(db, sub, user)
    await db.commit()

    await db.refresh(sub)
    await db.refresh(user)
    assert sub.remaining_tokens == 500
    assert user.free_message_limit == 0


@pytest.mark.asyncio
async def test_allocation_is_idempotent(db, user):
    sub = _sub(user.id, "act_A", total_tokens=500)
    db.add(sub)
    await db.commit()

    await SubscriptionLinkingService.allocate_subscription_tokens(db, sub, user)
    await db.commit()
    sub.remaining_tokens = 1  # simulate spend since first allocation
    await db.commit()

    await SubscriptionLinkingService.allocate_subscription_tokens(db, sub, user)
    await db.commit()

    await db.refresh(sub)
    assert sub.remaining_tokens == 1  # second call was a no-op


@pytest.mark.asyncio
async def test_spend_on_one_account_does_not_drain_another(db, user):
    sub_a = _sub(user.id, "act_A", total_tokens=100, remaining_tokens=100)
    sub_b = _sub(user.id, "act_B", total_tokens=100, remaining_tokens=100)
    db.add_all([sub_a, sub_b])
    await db.commit()

    await TokenService.deduct_tokens(db, user.id, amount=40, ad_account_id="act_A")

    await db.refresh(sub_a)
    await db.refresh(sub_b)
    assert sub_a.remaining_tokens == 60
    assert sub_b.remaining_tokens == 100


@pytest.mark.asyncio
async def test_balance_scoped_to_ad_account_excludes_other_accounts(db, user):
    sub_a = _sub(user.id, "act_A", total_tokens=100, remaining_tokens=100)
    sub_b = _sub(user.id, "act_B", total_tokens=250, remaining_tokens=250)
    db.add_all([sub_a, sub_b])
    await db.commit()

    balance_a = await TokenService.get_user_token_balance_internal(db, user.id, "act_A")
    balance_all = await TokenService.get_user_token_balance_internal(db, user.id)

    assert balance_a["subscription_remaining"] == 100
    assert balance_all["subscription_remaining"] == 350


@pytest.mark.asyncio
async def test_spend_falls_back_to_free_wallet_after_account_balance_exhausted(db, user):
    user.free_message_limit = 30
    sub_a = _sub(user.id, "act_A", total_tokens=100, remaining_tokens=20)
    db.add(sub_a)
    await db.commit()

    await TokenService.deduct_tokens(db, user.id, amount=35, ad_account_id="act_A")

    await db.refresh(sub_a)
    await db.refresh(user)
    assert sub_a.remaining_tokens == 0
    assert user.free_token_usage == 15  # 35 - 20 drawn from the free wallet


@pytest.mark.asyncio
async def test_billing_resolves_the_ad_account_the_way_production_does(db, user):
    """THE bug every test above missed. They all hand deduct_tokens an explicit
    ad_account_id; production handed it None, because _bill_usage read
    `active_ads_account_id` / `ad_account_id` off the AgentState root — keys
    nothing in the repo ever wrote. No paid subscription ever matched, the free
    wallet paid for everything, and paid balances never moved.

    So this exercises the RESOLUTION (ChatService._billing_ad_account) and feeds
    its answer to deduct_tokens, instead of assuming the id arrives."""
    from app.modules.chat.service import ChatService

    svc = ChatService.__new__(ChatService)  # the method needs no injected repo

    # Mid-thread: the builder has resolved Meta. No DB lookup needed.
    with patch("app.modules.chat.service.get_meta_credentials", new=AsyncMock()) as creds:
        resolved = await svc._billing_ad_account(
            {"user_info": {"meta_ad_account_id": "act_A"}}, user.id
        )
        assert resolved == "act_A"
        creds.assert_not_awaited()

    # First turns of a thread: user_info is empty, fall back to the selected account.
    with patch(
        "app.modules.chat.service.get_meta_credentials",
        new=AsyncMock(return_value={"ad_account_id": "act_A"}),
    ):
        assert await svc._billing_ad_account({}, user.id) == "act_A"

    # No Meta connection at all: unscoped, not an exception.
    with patch("app.modules.chat.service.get_meta_credentials", new=AsyncMock(return_value=None)):
        assert await svc._billing_ad_account({}, user.id) is None

    # And the resolved id moves the PAID balance, not the free wallet. Under the old
    # code the id was None, ad_account_subs came out empty, and free_token_usage
    # took the whole 40.
    user.free_message_limit = 1000
    sub = _sub(user.id, "act_A", total_tokens=100, remaining_tokens=100)
    db.add(sub)
    await db.commit()

    await TokenService.deduct_tokens(
        db, user.id, amount=40,
        ad_account_id=await svc._billing_ad_account(
            {"user_info": {"meta_ad_account_id": "act_A"}}, user.id
        ),
    )

    await db.refresh(sub)
    await db.refresh(user)
    assert sub.remaining_tokens == 60
    assert user.free_token_usage == 0


@pytest.mark.asyncio
async def test_allocate_commits_without_a_caller_commit(tmp_path):
    """allocate_subscription_tokens used to stage everything and commit nothing:
    its one production caller had ALREADY committed, and get_db() never commits,
    so the allocation died with the session — remaining_tokens stuck at 0 for the
    whole first billing period.

    Needs a real file DB and a SECOND session: on a shared :memory: connection an
    uncommitted write is visible to every session, which would let the bug pass."""
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'alloc.db'}")
    try:
        async with eng.begin() as conn:
            for model in (User, OAuthToken, AdsAccount, Subscription, UserSubscription,
                          SubscriptionTokenAllocation, TokenTransaction):
                await conn.run_sync(model.__table__.create)

        async with AsyncSession(eng, expire_on_commit=False) as writer:
            u = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@x.test", password_hash="x")
            writer.add(u)
            sub = _sub(u.id, "act_A", total_tokens=500)
            writer.add(sub)
            await writer.commit()

            await SubscriptionLinkingService.allocate_subscription_tokens(writer, sub, u)
            # deliberately NO writer.commit() — that is the production shape.

        async with AsyncSession(eng, expire_on_commit=False) as reader:
            reloaded = await reader.get(UserSubscription, sub.id)
            assert reloaded.remaining_tokens == 500
            allocation = (await reader.execute(
                select(SubscriptionTokenAllocation).where(
                    SubscriptionTokenAllocation.subscription_id == sub.id
                )
            )).scalar_one_or_none()
            assert allocation is not None
            assert (await reader.get(User, u.id)).isSubscriptionActive is True
    finally:
        await eng.dispose()
