"""app/modules/payment/service.py — checkout and assignment are per ad account.

Two bugs this closes:
  - create_subscription_checkout used to fall back to an unscoped subscription
    when no ads_account_id was given, which ad_account_is_paid treats as
    authorizing nothing — money paid for a subscription that could never gate
    anything.
  - assign_ad_account used to hand out get_latest_user_subscription, which
    could steal a subscription already bound to a DIFFERENT ad account.

Real in-memory SQLite; Stripe itself is stubbed since this is about our own
DB invariants, not the Stripe integration.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import app.api.router  # noqa: F401 — registers every module's models before mapper configure
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

# TokenTransaction.tx_metadata is Postgres JSONB, which the SQLite DDL compiler has
# no visit_JSONB for (unlike JSON) — render it as plain JSON for this in-memory DB.
SQLiteTypeCompiler.visit_JSONB = SQLiteTypeCompiler.visit_JSON

from app.modules.ads.models import AdsAccount, OAuthToken
from app.modules.subscription.models import (
    Subscription,
    SubscriptionTokenAllocation,
    TokenTransaction,
    UserSubscription,
)
from app.modules.subscription.repository import SubscriptionRepository
from app.modules.payment.service import PaymentService
from app.modules.user.models import User
from app.shared.enums import AdPlatform, SubscriptionPaymentStatus, SubscriptionStatus


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
        # The checkout webhook allocates tokens on the way out.
        await conn.run_sync(SubscriptionTokenAllocation.__table__.create)
        await conn.run_sync(TokenTransaction.__table__.create)
    yield eng
    await eng.dispose()


async def _connect_meta(db, user, account_ids, selected=None) -> OAuthToken:
    """A live Meta connection granting `account_ids`. assign_ad_account and the
    checkout webhook select the account through update_selected_account, which
    only accepts an account this connection actually grants."""
    first = selected or account_ids[0]
    token = OAuthToken(
        id=uuid.uuid4(), user_id=user.id, platform=AdPlatform.meta, access_token="tok",
        token_type="system_user",
        accessible_accounts=[{"id": a, "name": a} for a in account_ids],
        selected_account=first, ad_account_id=first,
    )
    user.select_meta_id = first
    db.add(token)
    await db.commit()
    return token


@pytest_asyncio.fixture
async def db(engine):
    # expire_on_commit=False: tests keep using the same ORM objects across
    # commits, and an expired attribute reload outside an active greenlet
    # raises MissingGreenlet under the aiosqlite driver.
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session


@pytest_asyncio.fixture
async def user(db):
    u = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@x.test", password_hash="x")
    db.add(u)
    await db.commit()
    return u


@pytest_asyncio.fixture
async def plan(db):
    p = Subscription(id=uuid.uuid4(), price_id="price_1", name="Pro", amount=79.99, total_token_can_use=1000)
    db.add(p)
    await db.commit()
    return p


@pytest.fixture
def service():
    return PaymentService(SubscriptionRepository())


@pytest.mark.asyncio
async def test_checkout_requires_ads_account_id(service, db, user, plan):
    payload = SimpleNamespace(subscription_id=plan.id, ads_account_id=None)

    with pytest.raises(HTTPException) as exc:
        await service.create_subscription_checkout(db, payload, user)

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_checkout_conflicts_when_account_already_has_active_sub(service, db, user, plan):
    db.add(UserSubscription(
        id=uuid.uuid4(), user_id=user.id, ad_account_id="act_A", plan_id=plan.id,
        status=SubscriptionStatus.active, payment_status=SubscriptionPaymentStatus.paid,
    ))
    await db.commit()
    payload = SimpleNamespace(subscription_id=plan.id, ads_account_id="act_A")

    with pytest.raises(HTTPException) as exc:
        await service.create_subscription_checkout(db, payload, user)

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_checkout_reuses_a_canceled_sub_for_the_same_account(service, db, user, plan):
    # uq_user_ad_account_sub means this row IS the only slot this ad account
    # will ever get for this user — canceling it must not permanently lock
    # the user out of resubscribing the same account (this exact bug shipped
    # once: the canceled branch fell into the generic 409).
    canceled_sub = UserSubscription(
        id=uuid.uuid4(), user_id=user.id, ad_account_id="act_A", plan_id=plan.id,
        status=SubscriptionStatus.canceled, payment_status=SubscriptionPaymentStatus.canceled,
        stripe_subscription_id="sub_old",
    )
    db.add(canceled_sub)
    await db.commit()
    payload = SimpleNamespace(subscription_id=plan.id, ads_account_id="act_A")

    with patch(
        "app.services.stripe_logic.StripeService.create_checkout_session",
        new=AsyncMock(return_value="https://stripe.test/checkout"),
    ):
        await service.create_subscription_checkout(db, payload, user)

    await db.refresh(canceled_sub)
    assert canceled_sub.status == SubscriptionStatus.incomplete
    assert canceled_sub.payment_status == SubscriptionPaymentStatus.unpaid
    # Same row reused, not a second one (which the unique constraint would reject anyway)
    all_subs = (await db.execute(
        select(UserSubscription).where(UserSubscription.ad_account_id == "act_A")
    )).scalars().all()
    assert len(all_subs) == 1


@pytest.mark.asyncio
async def test_checkout_creates_new_incomplete_sub_for_the_account(service, db, user, plan):
    payload = SimpleNamespace(subscription_id=plan.id, ads_account_id="act_A")

    with patch(
        "app.services.stripe_logic.StripeService.create_checkout_session",
        new=AsyncMock(return_value="https://stripe.test/checkout"),
    ) as mocked:
        url = await service.create_subscription_checkout(db, payload, user)

    assert url == "https://stripe.test/checkout"
    mocked.assert_awaited_once()
    sub = await SubscriptionRepository().get_user_subscription_by_ad_account(db, user.id, "act_A")
    assert sub is not None
    assert sub.status == SubscriptionStatus.incomplete


@pytest.mark.asyncio
async def test_assign_ad_account_stamps_only_the_unscoped_sub(service, db, user, plan):
    await _connect_meta(db, user, ["act_A", "act_OTHER"])
    other_account_sub = UserSubscription(
        id=uuid.uuid4(), user_id=user.id, ad_account_id="act_OTHER", plan_id=plan.id,
        status=SubscriptionStatus.active, payment_status=SubscriptionPaymentStatus.paid,
    )
    unscoped_sub = UserSubscription(
        id=uuid.uuid4(), user_id=user.id, ad_account_id=None, plan_id=plan.id,
        status=SubscriptionStatus.active, payment_status=SubscriptionPaymentStatus.paid,
    )
    db.add_all([other_account_sub, unscoped_sub])
    await db.commit()

    payload = SimpleNamespace(ads_account_id="act_A")
    await service.assign_ad_account(db, payload, user)

    await db.refresh(other_account_sub)
    await db.refresh(unscoped_sub)
    assert unscoped_sub.ad_account_id == "act_A"
    assert other_account_sub.ad_account_id == "act_OTHER"  # untouched


@pytest.mark.asyncio
async def test_assign_ad_account_noop_when_already_paid(service, db, user, plan):
    token = await _connect_meta(db, user, ["act_A"])
    db.add(UserSubscription(
        id=uuid.uuid4(), user_id=user.id, ad_account_id="act_A", plan_id=plan.id,
        status=SubscriptionStatus.active, payment_status=SubscriptionPaymentStatus.paid,
    ))
    await db.commit()

    payload = SimpleNamespace(ads_account_id="act_A")
    result = await service.assign_ad_account(db, payload, user)

    assert result["status"] == "success"
    await db.refresh(user)
    await db.refresh(token)
    assert user.select_meta_id == "act_A"
    assert token.selected_account == "act_A"


@pytest.mark.asyncio
async def test_assign_ad_account_selects_it_for_publishing(service, db, user, plan):
    """The B3 bug: assign wrote users.select_meta_id alone, so the user paid for B
    while oauth_tokens.selected_account — the column publish reads — stayed on A."""
    token = await _connect_meta(db, user, ["act_A", "act_B"], selected="act_A")
    db.add(UserSubscription(
        id=uuid.uuid4(), user_id=user.id, ad_account_id=None, plan_id=plan.id,
        status=SubscriptionStatus.active, payment_status=SubscriptionPaymentStatus.paid,
    ))
    await db.commit()

    await service.assign_ad_account(db, SimpleNamespace(ads_account_id="act_B"), user)

    await db.refresh(user)
    await db.refresh(token)
    assert token.selected_account == "act_B"
    assert user.select_meta_id == "act_B"


@pytest.mark.asyncio
async def test_assign_ad_account_rejects_an_account_the_connection_does_not_grant(service, db, user, plan):
    """It used to accept any string. A paid slot must not be spent on an account
    Meta never granted — nobody could publish into it."""
    await _connect_meta(db, user, ["act_A"])
    unscoped = UserSubscription(
        id=uuid.uuid4(), user_id=user.id, ad_account_id=None, plan_id=plan.id,
        status=SubscriptionStatus.active, payment_status=SubscriptionPaymentStatus.paid,
    )
    db.add(unscoped)
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await service.assign_ad_account(db, SimpleNamespace(ads_account_id="act_NOT_MINE"), user)

    assert exc.value.status_code == 400
    await db.refresh(unscoped)
    assert unscoped.ad_account_id is None  # the slot was not spent


@pytest.mark.asyncio
async def test_assign_ad_account_fails_with_no_subscription_at_all(service, db, user):
    payload = SimpleNamespace(ads_account_id="act_A")

    with pytest.raises(HTTPException) as exc:
        await service.assign_ad_account(db, payload, user)

    assert exc.value.status_code == 400


# ── checkout.session.completed (registered-user branch) ─────────────────────
#
# Stripe's Subscription.retrieve is stubbed (a network call); everything else is
# real. Metadata carries the sub id as a UUID object rather than the string Stripe
# sends: the repo's `UserSubscription.id == <str>` works on Postgres but SQLite's
# Uuid bind wants a UUID, and the string round-trip is not what this file tests.


def _stripe_session():
    return SimpleNamespace(id="cs_test_1", subscription="sub_stripe_1", customer_details=None)


async def _complete_checkout(service, db, user, metadata):
    with patch(
        "app.modules.payment.service.stripe.Subscription.retrieve",
        return_value=SimpleNamespace(status="active"),
    ):
        await service._handle_subscription_checkout(
            db, _stripe_session(), metadata, str(user.id)
        )


@pytest.mark.asyncio
async def test_paid_checkout_selects_the_paid_account_and_funds_it(service, db, user, plan):
    """Paying for B must make B the account Punk publishes into (else the user hits
    _require_paid_account on A right after paying), and must leave B funded."""
    token = await _connect_meta(db, user, ["act_A", "act_B"], selected="act_A")
    sub = UserSubscription(
        id=uuid.uuid4(), user_id=user.id, ad_account_id="act_B", plan_id=plan.id,
        status=SubscriptionStatus.incomplete, payment_status=SubscriptionPaymentStatus.unpaid,
    )
    db.add(sub)
    await db.commit()

    await _complete_checkout(service, db, user, {"subscription_id": sub.id, "ad_account_id": "act_B"})

    await db.refresh(sub)
    await db.refresh(user)
    await db.refresh(token)
    assert sub.status == SubscriptionStatus.active
    assert sub.remaining_tokens == 1000  # plan.total_token_can_use — the month-1 allocation landed
    assert token.selected_account == "act_B"
    assert user.select_meta_id == "act_B"


@pytest.mark.asyncio
async def test_paid_checkout_without_a_meta_connection_still_activates(service, db, user, plan):
    """Selecting is best-effort: a user with no live Meta connection must not make
    the webhook raise (Stripe would retry it forever over a selection nicety)."""
    sub = UserSubscription(
        id=uuid.uuid4(), user_id=user.id, ad_account_id="act_B", plan_id=plan.id,
        status=SubscriptionStatus.incomplete, payment_status=SubscriptionPaymentStatus.unpaid,
    )
    db.add(sub)
    await db.commit()

    await _complete_checkout(service, db, user, {"subscription_id": sub.id, "ad_account_id": "act_B"})

    await db.refresh(sub)
    assert sub.status == SubscriptionStatus.active


@pytest.mark.asyncio
async def test_checkout_fallback_keeps_the_ad_account_from_metadata(service, db, user, plan):
    """No pre-created row (the "should rarely happen" fallback). It used to mint
    ad_account_id=NULL — which ad_account_is_paid rejects forever — with no metadata
    left to recover the account from. Money changed hands; the sub must be scoped."""
    await _connect_meta(db, user, ["act_A", "act_B"])

    await _complete_checkout(service, db, user, {"ad_account_id": "act_B"})  # no subscription_id

    subs = (await db.execute(select(UserSubscription).where(UserSubscription.user_id == user.id))).scalars().all()
    assert len(subs) == 1
    assert subs[0].ad_account_id == "act_B"
    from app.services.entitlement import ad_account_is_paid
    assert await ad_account_is_paid(user.id, "act_B", db) is True


@pytest.mark.asyncio
async def test_checkout_puts_the_ad_account_in_stripe_metadata(service, db, user, plan):
    """The account id has to reach Stripe or the fallback above has nothing to read."""
    payload = SimpleNamespace(subscription_id=plan.id, ads_account_id="act_A")

    with patch(
        "app.services.stripe_logic.StripeService.create_checkout_session",
        new=AsyncMock(return_value="https://stripe.test/checkout"),
    ) as mocked:
        await service.create_subscription_checkout(db, payload, user)

    assert mocked.await_args.kwargs["ad_account_id"] == "act_A"


# ── GET /subscription/success — ownership ───────────────────────────────────
#
# It runs the same activation the webhook runs and used to be unauthenticated:
# anyone holding a session id (it sits in the browser URL) could drive another
# account's activation.


def _paid_session_for(owner_id, payment_status="paid"):
    return SimpleNamespace(id="cs_test_1", payment_status=payment_status, metadata={"user_id": str(owner_id)})


@pytest.mark.asyncio
async def test_success_callback_rejects_a_session_owned_by_someone_else(db, user):
    from app.modules.payment import router as payment_router

    stranger = uuid.uuid4()
    with patch("stripe.checkout.Session.retrieve", return_value=_paid_session_for(stranger)), \
         patch.object(payment_router.service, "process_checkout_session_completed", new=AsyncMock()) as activate:
        with pytest.raises(HTTPException) as exc:
            await payment_router.subscription_success("cs_test_1", current_user=user, db=db)

    assert exc.value.status_code == 403
    activate.assert_not_awaited()  # nothing was activated on the stranger's say-so


@pytest.mark.asyncio
async def test_success_callback_activates_the_owners_paid_session(db, user):
    from app.modules.payment import router as payment_router

    with patch("stripe.checkout.Session.retrieve", return_value=_paid_session_for(user.id)), \
         patch.object(payment_router.service, "process_checkout_session_completed", new=AsyncMock()) as activate:
        result = await payment_router.subscription_success("cs_test_1", current_user=user, db=db)

    assert result["success"] is True
    activate.assert_awaited_once()


@pytest.mark.asyncio
async def test_success_callback_refuses_an_unpaid_session(db, user):
    from app.modules.payment import router as payment_router

    with patch("stripe.checkout.Session.retrieve", return_value=_paid_session_for(user.id, "unpaid")):
        with pytest.raises(HTTPException) as exc:
            await payment_router.subscription_success("cs_test_1", current_user=user, db=db)

    assert exc.value.status_code == 400


# ── cancel / resume — at period END ─────────────────────────────────────────
#
# Cancel is cancel-AT-PERIOD-END: the user has paid through current_period_end, so
# the row stays `active` (ad_account_is_paid keys off status) with the flag set,
# and Stripe's webhooks move status when the period actually ends.

_PERIOD_END = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _stripe_sub(period_end=_PERIOD_END):
    """The shape stripe.Subscription.modify returns (period end on the item)."""
    return {"items": {"data": [{"current_period_end": int(period_end.timestamp())}]}}


async def _live_sub(db, user, plan, **overrides) -> UserSubscription:
    defaults = dict(
        id=uuid.uuid4(), user_id=user.id, ad_account_id="act_A", plan_id=plan.id,
        status=SubscriptionStatus.active, payment_status=SubscriptionPaymentStatus.paid,
        stripe_subscription_id="sub_stripe_1",
    )
    defaults.update(overrides)
    sub = UserSubscription(**defaults)
    db.add(sub)
    await db.commit()
    return sub


@pytest.mark.asyncio
async def test_cancel_keeps_the_account_paid_and_returns_the_period_end(service, db, user, plan):
    """It used to flip status to canceled at once, and ad_account_is_paid keys off
    status — so cancelling cut access immediately instead of at period end. It also
    never said WHEN access ends: checkout does not write current_period_end, so the
    date has to come from Stripe's reply."""
    from app.services.entitlement import ad_account_is_paid

    sub = await _live_sub(db, user, plan)  # no current_period_end yet, like a fresh checkout

    with patch("app.services.stripe_logic.stripe.Subscription.modify", return_value=_stripe_sub()) as modify:
        result = await service.cancel_subscription(db, str(sub.id), user)

    modify.assert_called_once_with("sub_stripe_1", cancel_at_period_end=True)
    assert result["status"] == "success"
    assert result["cancel_at_period_end"] is True
    assert result["current_period_end"].replace(tzinfo=None) == _PERIOD_END.replace(tzinfo=None)
    await db.refresh(sub)
    assert sub.cancel_at_period_end is True
    assert sub.status == SubscriptionStatus.active
    assert sub.current_period_end.replace(tzinfo=None) == _PERIOD_END.replace(tzinfo=None)
    assert await ad_account_is_paid(user.id, "act_A", db) is True


@pytest.mark.asyncio
async def test_cancel_refuses_a_subscription_that_already_ended(service, db, user, plan):
    sub = await _live_sub(db, user, plan, status=SubscriptionStatus.canceled)

    with patch("app.services.stripe_logic.stripe.Subscription.modify") as modify:
        with pytest.raises(HTTPException) as exc:
            await service.cancel_subscription(db, str(sub.id), user)

    assert exc.value.status_code == 409
    modify.assert_not_called()  # not a raw Stripe error on a dead subscription


@pytest.mark.asyncio
async def test_cancel_when_already_scheduled_does_not_call_stripe_again(service, db, user, plan):
    sub = await _live_sub(db, user, plan, cancel_at_period_end=True, current_period_end=_PERIOD_END)

    with patch("app.services.stripe_logic.stripe.Subscription.modify") as modify:
        result = await service.cancel_subscription(db, str(sub.id), user)

    modify.assert_not_called()  # a double-click or a second tab is harmless
    assert result["cancel_at_period_end"] is True


@pytest.mark.asyncio
async def test_cancel_and_resume_only_reach_the_callers_own_subscription(service, db, user, plan):
    sub = await _live_sub(db, user, plan)
    stranger = SimpleNamespace(id=uuid.uuid4())

    with patch("app.services.stripe_logic.stripe.Subscription.modify") as modify:
        for call in (service.cancel_subscription, service.resume_subscription):
            with pytest.raises(HTTPException) as exc:
                await call(db, str(sub.id), stranger)
            assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:  # not a UUID: 404, not a Postgres DataError
            await service.cancel_subscription(db, "sub_stripe_1", user)
        assert exc.value.status_code == 404

    modify.assert_not_called()


@pytest.mark.asyncio
async def test_resume_clears_a_scheduled_cancel(service, db, user, plan):
    sub = await _live_sub(db, user, plan, cancel_at_period_end=True)

    with patch("app.services.stripe_logic.stripe.Subscription.modify", return_value=_stripe_sub()) as modify:
        result = await service.resume_subscription(db, str(sub.id), user)

    modify.assert_called_once_with("sub_stripe_1", cancel_at_period_end=False)
    assert result["cancel_at_period_end"] is False
    await db.refresh(sub)
    assert sub.cancel_at_period_end is False
    assert sub.status == SubscriptionStatus.active


@pytest.mark.asyncio
async def test_resume_refuses_when_nothing_is_scheduled_or_it_already_ended(service, db, user, plan):
    running = await _live_sub(db, user, plan, ad_account_id="act_A", stripe_subscription_id="sub_a")
    ended = await _live_sub(
        db, user, plan, ad_account_id="act_B", stripe_subscription_id="sub_b",
        status=SubscriptionStatus.canceled, cancel_at_period_end=True,
    )

    with patch("app.services.stripe_logic.stripe.Subscription.modify") as modify:
        for sub in (running, ended):
            with pytest.raises(HTTPException) as exc:
                await service.resume_subscription(db, str(sub.id), user)
            assert exc.value.status_code == 409

    modify.assert_not_called()


def test_period_end_reads_the_item_then_the_top_level_and_never_guesses():
    from app.services.stripe_logic import _period_end

    ts = int(_PERIOD_END.timestamp())
    assert _period_end({"items": {"data": [{"current_period_end": ts}]}}) == _PERIOD_END
    assert _period_end({"current_period_end": ts}) == _PERIOD_END
    # Missing is None — NOT start_date/created (a PAST date would make
    # ad_account_is_paid reject a paid account).
    assert _period_end({"start_date": ts, "created": ts, "items": {"data": []}}) is None
    assert _period_end({}) is None


@pytest.mark.asyncio
async def test_checkout_names_the_stripe_product_by_plan_and_account(service, db, user, plan):
    """plan.description is a serialized JSON blob for admin-created plans, and every
    account's Stripe line used to read the same."""
    plan.name = "Pro"
    plan.description = '{"shortDescription": "x", "features": [], "name": "Pro"}'
    await db.commit()
    payload = SimpleNamespace(subscription_id=plan.id, ads_account_id="act_A")

    with patch(
        "app.services.stripe_logic.StripeService.create_checkout_session",
        new=AsyncMock(return_value="https://stripe.test/checkout"),
    ) as mocked:
        await service.create_subscription_checkout(db, payload, user)

    assert mocked.await_args.kwargs["plan_name"] == "Pro — act_A"
