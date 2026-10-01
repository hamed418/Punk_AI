"""``CampaignsService.get_review`` — Meta's ad review, on the campaign page.

The route is keyed on PUNK's campaign id and resolves every Meta id server-side:
``ext_campaign_id`` holds only the primary campaign, and an app plan publishes one
per store with the rest in ``publish_state["campaigns"]``. Ownership is checked on
Punk's id; a missing connection or an unreadable status is an empty list, never an
error on the page.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import app.api.router  # noqa: F401 — registers every module's models before mapper configure
from app.modules.ads.models import AdsAccount, OAuthToken
from app.modules.campaigns import service as campaigns_service
from app.modules.campaigns.models import Campaign
from app.modules.campaigns.repository import CampaignsRepository
from app.modules.campaigns.service import CampaignsService
from app.modules.user.models import User
from app.shared.enums import AdPlatform, CampaignStatus


@pytest_asyncio.fixture
async def db():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(User.__table__.create)
        await conn.run_sync(OAuthToken.__table__.create)
        await conn.run_sync(AdsAccount.__table__.create)
        await conn.run_sync(Campaign.__table__.create)
    async with AsyncSession(eng, expire_on_commit=False) as session:
        yield session
    await eng.dispose()


async def _user(db) -> User:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@x.test", password_hash="x")
    db.add(user)
    await db.commit()
    return user


async def _campaign(db, user, *, ext=None, ledger=None) -> Campaign:
    row = Campaign(
        id=uuid.uuid4(), user_id=user.id, name="c", platform=AdPlatform.meta,
        status=CampaignStatus.draft, ext_campaign_id=ext,
        publish_state={"campaigns": ledger} if ledger else None,
    )
    db.add(row)
    await db.commit()
    return row


@pytest.fixture
def graph(monkeypatch):
    """Stub the credential read and the Graph read; record which campaigns were asked."""
    asked: list[str] = []
    ads_by_campaign: dict[str, list[dict]] = {}

    async def _creds(_user_id):
        return {"access_token": "tok"}

    async def _review(campaign_id, token):
        asked.append(campaign_id)
        return ads_by_campaign.get(campaign_id, [])

    monkeypatch.setattr(campaigns_service, "get_meta_credentials", _creds)
    monkeypatch.setattr(campaigns_service, "fetch_ad_review", _review)
    return asked, ads_by_campaign


def _svc() -> CampaignsService:
    return CampaignsService(CampaignsRepository())


@pytest.mark.asyncio
async def test_another_users_campaign_is_a_404(db, graph):
    owner, stranger = await _user(db), await _user(db)
    row = await _campaign(db, owner, ext="c1")

    with pytest.raises(HTTPException) as exc:
        await _svc().get_review(db, row.id, stranger)

    assert exc.value.status_code == 404
    assert graph[0] == []  # never reached Meta


@pytest.mark.asyncio
async def test_every_campaign_the_plan_published_is_read(db, graph):
    """Primary id plus the ledger's — an app plan is one campaign per store."""
    asked, ads = graph
    user = await _user(db)
    row = await _campaign(db, user, ext="c1", ledger={"ios": "c2", "android": "c3"})
    ads["c3"] = [{"id": "9", "name": "Android ad", "effective_status": "DISAPPROVED",
                  "ad_review_feedback": {"global": {"X": "Misleading claim"}}}]

    (card,) = await _svc().get_review(db, row.id, user)

    assert sorted(asked) == ["c1", "c2", "c3"]
    assert card["key"] == "ads_disapproved"
    assert "Android ad: Misleading claim" in card["cause"]


@pytest.mark.asyncio
async def test_a_draft_with_no_meta_id_makes_no_graph_call(db, graph):
    user = await _user(db)
    row = await _campaign(db, user)

    assert await _svc().get_review(db, row.id, user) == []
    assert graph[0] == []


@pytest.mark.asyncio
async def test_not_connected_is_empty_not_an_error(db, graph, monkeypatch):
    async def _none(_user_id):
        return None

    monkeypatch.setattr(campaigns_service, "get_meta_credentials", _none)
    user = await _user(db)
    row = await _campaign(db, user, ext="c1")

    assert await _svc().get_review(db, row.id, user) == []
    assert graph[0] == []


@pytest.mark.asyncio
async def test_ads_still_in_review_say_so(db, graph):
    asked, ads = graph
    user = await _user(db)
    row = await _campaign(db, user, ext="c1")
    ads["c1"] = [{"id": "1", "effective_status": "PENDING_REVIEW"}]

    (card,) = await _svc().get_review(db, row.id, user)

    assert card["key"] == "ads_in_review"
