"""app/modules/campaigns/repository.py::campaign_saved — reconcile + metrics.

Before this, the Meta sync was upsert-only: it inserted/updated whatever
Meta's response contained and never noticed a row Meta stopped returning
(deleted) or flagged as DELETED/ARCHIVED (Meta returns those by default —
measured on `meta_ads.list_account_campaigns`). It also never wrote a single
performance metric, so spend/impressions/clicks/conversions sat at their
column defaults forever, and it hardcoded the Punk lifecycle status to
`draft`, so the UI's Active/Paused pill never matched anything.

Real in-memory SQLite: the load-bearing behavior is the SQL (the absence
diff, the truncation guard, the bulk-insert homogeneity), which a mocked
repository would let slide silently.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import app.api.router  # noqa: F401 — registers every module's models before mapper configure
from app.modules.campaigns.models import Campaign
from app.modules.campaigns.repository import CampaignsRepository
from app.modules.user.models import User
from app.shared.enums import AdPlatform, CampaignStatus


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(User.__table__.create)
        await conn.run_sync(Campaign.__table__.create)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session


def _row(user_id, ext_id, meta_ads_id="act_1", status=CampaignStatus.published):
    return Campaign(
        id=uuid.uuid4(),
        user_id=user_id,
        name=f"c-{ext_id}",
        platform=AdPlatform.meta,
        status=status,
        ext_campaign_id=ext_id,
        meta_ads_id=meta_ads_id,
    )


async def _get(db, ext_id):
    return (
        await db.execute(select(Campaign).where(Campaign.ext_campaign_id == ext_id))
    ).scalar_one()


@pytest_asyncio.fixture
async def user(db):
    u = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@x.test", password_hash="x")
    db.add(u)
    await db.commit()
    return u


@pytest.mark.asyncio
async def test_deleted_and_absent_campaigns_archived_on_complete_sync(db, user):
    db.add_all([_row(user.id, "101"), _row(user.id, "102"), _row(user.id, "103")])
    await db.commit()

    await CampaignsRepository().campaign_saved(
        db,
        user.id,
        [
            {"id": "101", "name": "Live", "effective_status": "ACTIVE"},
            {"id": "102", "name": "Dead", "effective_status": "DELETED"},
            {"id": "999", "name": "NewlyDead", "effective_status": "ARCHIVED"},
        ],
        "act_1",
        complete=True,
    )

    assert (await _get(db, "101")).status == CampaignStatus.published
    assert (await _get(db, "102")).status == CampaignStatus.archived
    # 103 was never in the response at all — absence, on a fully-paged sync.
    assert (await _get(db, "103")).status == CampaignStatus.archived
    # A campaign already dead on Meta's side, with no prior row, is never imported.
    with pytest.raises(Exception):
        await _get(db, "999")


@pytest.mark.asyncio
async def test_unattributed_published_row_still_gets_archived_when_gone(db, user):
    # The exact shape a publish leaves behind if it ever runs with a stale
    # build that skips the meta_ads_id stamp: a real, published campaign with
    # no account attribution at all. Absence-archiving must not skip it just
    # because meta_ads_id is NULL — "not in Ad Manager" has to be the whole
    # rule, with no unattributed-row loophole.
    db.add_all([_row(user.id, "301", meta_ads_id=None)])
    await db.commit()

    await CampaignsRepository().campaign_saved(db, user.id, [], "act_1", complete=True)

    assert (await _get(db, "301")).status == CampaignStatus.archived


@pytest.mark.asyncio
async def test_other_connected_account_is_never_touched(db, user):
    # A campaign genuinely attributed to a DIFFERENT connected account must
    # survive a sync of this one — cross-account safety is the one thing the
    # unattributed-row fix must not give up.
    db.add_all([_row(user.id, "401", meta_ads_id="act_2")])
    await db.commit()

    await CampaignsRepository().campaign_saved(db, user.id, [], "act_1", complete=True)

    assert (await _get(db, "401")).status == CampaignStatus.published


@pytest.mark.asyncio
async def test_absent_campaign_survives_a_truncated_sync(db, user):
    db.add_all([_row(user.id, "201")])
    await db.commit()

    await CampaignsRepository().campaign_saved(
        db, user.id, [], "act_1", complete=False,
    )

    # complete=False means the page cap was hit, not that the sync finished —
    # a campaign this response happens not to mention must not be archived.
    assert (await _get(db, "201")).status == CampaignStatus.published


@pytest.mark.asyncio
async def test_metrics_written_and_not_zeroed_on_a_later_miss(db, user):
    db.add_all([_row(user.id, "1")])
    await db.commit()

    insights = {
        "1": {
            "spend": "12.50",
            "impressions": "100",
            "clicks": "10",
            "actions": [{"action_type": "purchase", "value": "2"}],
            "purchase_roas": [{"value": "3.5"}],
        }
    }
    await CampaignsRepository().campaign_saved(
        db, user.id, [{"id": "1", "name": "C", "effective_status": "ACTIVE"}],
        "act_1", insights=insights, complete=True,
    )

    row = await _get(db, "1")
    assert row.spend_usd == Decimal("12.50")
    assert row.impressions == 100
    assert row.clicks == 10
    assert row.conversions == 2
    assert row.roas == Decimal("3.5")
    assert row.cpa_usd == Decimal("6.25")

    # A later sync with a dead token/throttled insights call must not wipe
    # the numbers that are already there.
    await CampaignsRepository().campaign_saved(
        db, user.id, [{"id": "1", "name": "C", "effective_status": "ACTIVE"}],
        "act_1", insights={}, complete=True,
    )

    row = await _get(db, "1")
    assert row.spend_usd == Decimal("12.50")
    assert row.conversions == 2


@pytest.mark.asyncio
async def test_new_dead_campaign_is_never_inserted(db, user):
    await CampaignsRepository().campaign_saved(
        db, user.id,
        [{"id": "500", "name": "Dead on arrival", "effective_status": "DELETED"}],
        "act_1", complete=True,
    )

    result = await db.execute(select(Campaign).where(Campaign.ext_campaign_id == "500"))
    assert result.scalar_one_or_none() is None
