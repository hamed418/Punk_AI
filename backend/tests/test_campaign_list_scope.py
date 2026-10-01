"""app/modules/campaigns/service.py::list_campaigns — scoped to the connected account.

Before this, the filter read `users.select_meta_id` (a mirror the account
switcher never wrote — NULL on a fresh connect, NULLed on disconnect) instead
of `oauth_tokens.selected_account` (what the Meta sync stamps rows from). A
NULL mirror skipped the filter entirely, so every campaign ever synced from
every account — including disconnected ones — came back.

Real in-memory SQLite: the load-bearing behavior is the SQL filter itself
(the OR/AND escape for Punk's own drafts), which a mocked repository would
let slide silently.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import app.api.router  # noqa: F401 — registers every module's models before mapper configure
from app.modules.ads.models import AdsAccount, OAuthToken
from app.modules.campaigns.models import Campaign
from app.modules.campaigns.repository import CampaignsRepository
from app.modules.campaigns.service import CampaignsService
from app.modules.user.models import User
from app.shared.enums import AdPlatform, CampaignStatus


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(User.__table__.create)
        await conn.run_sync(OAuthToken.__table__.create)
        await conn.run_sync(AdsAccount.__table__.create)
        await conn.run_sync(Campaign.__table__.create)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session


def _campaign(user_id, meta_ads_id, conversation_id=None, created_at=None, ext_campaign_id=None):
    return Campaign(
        id=uuid.uuid4(),
        user_id=user_id,
        conversation_id=conversation_id,
        name="c",
        platform=AdPlatform.meta,
        status=CampaignStatus.draft,
        meta_ads_id=meta_ads_id,
        ext_campaign_id=ext_campaign_id,
        **({"created_at": created_at} if created_at else {}),
    )


@pytest_asyncio.fixture
async def seeded_user(db):
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@x.test", password_hash="x")
    account_a = _campaign(user.id, "act_A")
    punk_draft = _campaign(user.id, None, conversation_id=uuid.uuid4())  # Punk-created draft
    # Started a publish, then abandoned it — never picked up a meta_ads_id
    # or got explicitly archived. Old enough that it's dead weight, not
    # work in progress.
    old_abandoned_draft = _campaign(
        user.id, None, conversation_id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc) - timedelta(hours=72),
    )
    # A row that already reached Meta (has an ext_campaign_id) but never got
    # its meta_ads_id stamped — the exact shape a stray publish leaves. It is
    # not "still being built": Ad Manager is the only thing that gets to say
    # whether it's still around, so the drafts pass must not apply here even
    # though it's recent and has a conversation_id.
    unattributed_published = _campaign(
        user.id, None, conversation_id=uuid.uuid4(), ext_campaign_id="ext_1",
    )
    db.add(user)
    db.add_all([
        account_a,
        _campaign(user.id, "act_B"),
        _campaign(user.id, None, conversation_id=None),  # legacy import, no owner
        punk_draft,
        old_abandoned_draft,
        unattributed_published,
    ])
    await db.commit()
    user.expected_visible_ids = {account_a.id, punk_draft.id}
    return user


@pytest.mark.asyncio
async def test_list_excludes_other_accounts_keeps_punk_drafts(db, seeded_user, monkeypatch):
    monkeypatch.setattr(
        "app.modules.campaigns.service.get_meta_credentials",
        AsyncMock(return_value={"ad_account_id": "act_A"}),
    )
    service = CampaignsService(CampaignsRepository())

    result = await service.list_campaigns(db, seeded_user.id, 1, 20, None, None)

    assert result.total == 2
    assert {c.id for c in result.results} == seeded_user.expected_visible_ids


@pytest.mark.asyncio
async def test_list_empty_when_no_account_connected(db, seeded_user, monkeypatch):
    monkeypatch.setattr(
        "app.modules.campaigns.service.get_meta_credentials",
        AsyncMock(return_value=None),
    )
    service = CampaignsService(CampaignsRepository())

    result = await service.list_campaigns(db, seeded_user.id, 1, 20, None, None)

    assert result.total == 0
    assert result.results == []
