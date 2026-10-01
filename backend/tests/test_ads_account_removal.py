"""app/modules/ads/repository.py::remove_ads_account — per-ad-account removal.

Before this, the only delete paths dropped the WHOLE Meta connection
(disconnect_account / disconnect_connection_by_id). A Business system-user
token granting one ad account but reaching two (see
test_meta_granted_accounts.py) left the unwanted second account permanently
stuck — there was no way to shed just one account.

Real in-memory SQLite, not a mocked session — the load-bearing behavior here
(selected_account repointing, accessible_accounts pruning, the paid-account
block) is exactly the kind of thing a mock would let slide silently.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy import select

import app.api.router  # noqa: F401 — registers every module's models before mapper configure
from app.modules.ads.models import AdsAccount, OAuthToken
from app.modules.ads.repository import AdsRepository
from app.modules.subscription.models import UserSubscription
from app.modules.user.models import User
from app.shared.enums import AdPlatform, SubscriptionPaymentStatus, SubscriptionStatus


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(User.__table__.create)
        await conn.run_sync(OAuthToken.__table__.create)
        await conn.run_sync(AdsAccount.__table__.create)
        await conn.run_sync(UserSubscription.__table__.create)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    # expire_on_commit=False: tests keep using the same ORM objects across
    # commits, and an expired attribute reload outside an active greenlet
    # raises MissingGreenlet under the aiosqlite driver.
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session


async def _seed_user_with_accounts(db: AsyncSession, account_ids: list[str], selected: str | None = None):
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@x.test", password_hash="x")
    accounts = [{"id": aid, "name": aid} for aid in account_ids]
    token = OAuthToken(
        id=uuid.uuid4(),
        user_id=user.id,
        platform=AdPlatform.meta,
        access_token="tok",
        token_type="system_user",
        accessible_accounts=accounts,
        selected_account=selected or (account_ids[0] if account_ids else None),
        ad_account_id=selected or (account_ids[0] if account_ids else None),
    )
    user.select_meta_id = token.selected_account
    db.add(user)
    db.add(token)
    await db.flush()
    for aid in account_ids:
        db.add(AdsAccount(user_id=user.id, oauth_token_id=token.id, ad_account_id=aid, ad_account_name=aid))
    await db.commit()
    return user, token


async def _get_token(db, token_id):
    return (await db.execute(select(OAuthToken).where(OAuthToken.id == token_id))).scalar_one_or_none()


async def _get_ads_account(db, token_id, ad_account_id):
    return (
        await db.execute(
            select(AdsAccount).where(
                AdsAccount.oauth_token_id == token_id, AdsAccount.ad_account_id == ad_account_id
            )
        )
    ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_blocked_when_account_is_paid(db):
    user, token = await _seed_user_with_accounts(db, ["act_A", "act_B"])
    db.add(UserSubscription(
        id=uuid.uuid4(), user_id=user.id, ad_account_id="act_A",
        status=SubscriptionStatus.active, payment_status=SubscriptionPaymentStatus.paid,
    ))
    await db.commit()

    outcome = await AdsRepository().remove_ads_account(db, user.id, "act_A")

    assert outcome == "paid"
    assert await _get_ads_account(db, token.id, "act_A") is not None


@pytest.mark.asyncio
async def test_removes_unpaid_account_and_prunes_json(db):
    user, token = await _seed_user_with_accounts(db, ["act_A", "act_B"])

    outcome = await AdsRepository().remove_ads_account(db, user.id, "act_A")

    assert outcome == "removed"
    assert await _get_ads_account(db, token.id, "act_A") is None
    refreshed = await _get_token(db, token.id)
    assert {a["id"] for a in refreshed.accessible_accounts} == {"act_B"}


@pytest.mark.asyncio
async def test_removing_selected_account_repoints_selection(db):
    user, token = await _seed_user_with_accounts(db, ["act_A", "act_B"], selected="act_A")

    await AdsRepository().remove_ads_account(db, user.id, "act_A")

    refreshed = await _get_token(db, token.id)
    assert refreshed.selected_account == "act_B"
    assert refreshed.ad_account_id == "act_B"
    refreshed_user = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
    assert refreshed_user.select_meta_id == "act_B"


@pytest.mark.asyncio
async def test_removing_last_account_disconnects_whole_connection(db):
    user, token = await _seed_user_with_accounts(db, ["act_A"])

    outcome = await AdsRepository().remove_ads_account(db, user.id, "act_A")

    assert outcome == "removed"
    assert await _get_token(db, token.id) is None
    assert await _get_ads_account(db, token.id, "act_A") is None


@pytest.mark.asyncio
async def test_unknown_account_is_not_found(db):
    user, _token = await _seed_user_with_accounts(db, ["act_A"])

    outcome = await AdsRepository().remove_ads_account(db, user.id, "act_does_not_exist")

    assert outcome == "not_found"


@pytest.mark.asyncio
async def test_no_connection_is_not_found(db):
    outcome = await AdsRepository().remove_ads_account(db, uuid.uuid4(), "act_A")

    assert outcome == "not_found"


# ── lead webhook teardown ────────────────────────────────────────────────────
# Removing an ad account deletes the only row that can route a lead back to it, so
# Meta kept pushing the Page's leads at /tracking/webhook forever, to be read and
# dropped. The DELETE goes out with the app token, so it works after the
# connection row is gone.


@pytest.fixture
def unsubscribed(monkeypatch):
    from app.services import meta_ads

    called: list[str] = []

    async def _unsub(page_id):
        called.append(page_id)
        return True

    monkeypatch.setattr(meta_ads, "unsubscribe_page_leadgen", _unsub)
    return called


async def _subscribe(db, token, ad_account_id, page_id):
    acc = await _get_ads_account(db, token.id, ad_account_id)
    acc.tracking_lead_page_id = page_id
    await db.commit()


@pytest.mark.asyncio
async def test_disconnecting_unsubscribes_the_page(db, unsubscribed):
    user, token = await _seed_user_with_accounts(db, ["act_A"])
    await _subscribe(db, token, "act_A", "pg_1")

    assert await AdsRepository().disconnect_account(db, user.id, AdPlatform.meta)

    assert unsubscribed == ["pg_1"]


@pytest.mark.asyncio
async def test_disconnecting_a_connection_by_id_unsubscribes_the_page(db, unsubscribed):
    user, token = await _seed_user_with_accounts(db, ["act_A"])
    await _subscribe(db, token, "act_A", "pg_1")

    assert await AdsRepository().disconnect_connection_by_id(db, user.id, token.id)

    assert unsubscribed == ["pg_1"]


@pytest.mark.asyncio
async def test_removing_one_account_unsubscribes_only_its_page(db, unsubscribed):
    user, token = await _seed_user_with_accounts(db, ["act_A", "act_B"])
    await _subscribe(db, token, "act_A", "pg_A")
    await _subscribe(db, token, "act_B", "pg_B")

    assert await AdsRepository().remove_ads_account(db, user.id, "act_A") == "removed"

    assert unsubscribed == ["pg_A"]


@pytest.mark.asyncio
async def test_removing_the_last_account_unsubscribes_once(db, unsubscribed):
    user, token = await _seed_user_with_accounts(db, ["act_A"])
    await _subscribe(db, token, "act_A", "pg_1")

    assert await AdsRepository().remove_ads_account(db, user.id, "act_A") == "removed"

    assert unsubscribed == ["pg_1"]


@pytest.mark.asyncio
async def test_a_page_another_account_still_uses_stays_subscribed(db, unsubscribed):
    """The DELETE is Page-wide: an agency's second client on the same Page must
    keep receiving its leads."""
    user, token = await _seed_user_with_accounts(db, ["act_A", "act_B"])
    await _subscribe(db, token, "act_A", "pg_shared")
    await _subscribe(db, token, "act_B", "pg_shared")

    await AdsRepository().remove_ads_account(db, user.id, "act_A")

    assert unsubscribed == []


@pytest.mark.asyncio
async def test_a_meta_failure_never_blocks_the_disconnect(db, monkeypatch):
    from app.services import meta_ads

    async def _boom(page_id):
        raise RuntimeError("meta down")

    monkeypatch.setattr(meta_ads, "unsubscribe_page_leadgen", _boom)
    user, token = await _seed_user_with_accounts(db, ["act_A"])
    await _subscribe(db, token, "act_A", "pg_1")

    assert await AdsRepository().disconnect_account(db, user.id, AdPlatform.meta)
    assert await _get_token(db, token.id) is None


@pytest.mark.asyncio
async def test_an_account_with_no_subscribed_page_calls_nothing(db, unsubscribed):
    user, _ = await _seed_user_with_accounts(db, ["act_A"])

    await AdsRepository().disconnect_account(db, user.id, AdPlatform.meta)

    assert unsubscribed == []


# ── update_selected_account: the ONE selection writer ───────────────────────
#
# oauth_tokens.selected_account is what publish reads; users.select_meta_id is
# what the profile UI reads. Several callers used to write only one of them, so a
# user could pay for account B while Punk kept publishing into A.


@pytest.mark.asyncio
async def test_selecting_an_account_moves_both_columns(db):
    user, token = await _seed_user_with_accounts(db, ["act_A", "act_B"], selected="act_A")

    assert await AdsRepository().update_selected_account(db, user.id, "act_B") is True

    await db.refresh(token)
    await db.refresh(user)
    assert token.selected_account == "act_B"
    assert user.select_meta_id == "act_B"


@pytest.mark.asyncio
async def test_selecting_an_unconnected_account_moves_neither(db):
    user, token = await _seed_user_with_accounts(db, ["act_A", "act_B"], selected="act_A")

    assert await AdsRepository().update_selected_account(db, user.id, "act_NOT_MINE") is False

    await db.refresh(token)
    await db.refresh(user)
    assert token.selected_account == "act_A"
    assert user.select_meta_id == "act_A"
