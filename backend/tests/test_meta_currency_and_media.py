"""
tests/test_meta_currency_and_media.py
─────────────────────────────────────
Two classes of publish failure that had no local defence.

**Currency.** Every budget is sent in the AD ACCOUNT's currency, in minor units.
Meta's minimum daily budget is per-currency — BDT 120 where USD is 1.00 — and the
floor used to be a USD constant, so a plan built for a Bangladeshi or Canadian
account was rejected by Meta with subcode 1885272 and no local explanation.

**Video readiness.** ``POST /advideos`` returns an id the moment Meta has the
bytes, not when the video is usable; a creative built against a transcoding video
is rejected or lands an ad stuck in review.
"""
from __future__ import annotations

import pytest

import app.graph.builder.executors.media as media_exec
from app.graph.builder.executors.publish_ledger import PublishLedger
from app.graph.meta_spec.builder import _resolve_placements, _wants_campaign_budget
from app.graph.meta_spec.models import MIN_BUDGET_CENTS, min_budget_cents
from app.services import meta_ads


# ── currency-aware budget floor ───────────────────────────────────────────────


def test_floor_defaults_to_the_static_constant_when_account_unknown():
    assert min_budget_cents({}) == MIN_BUDGET_CENTS


def test_floor_follows_the_ad_accounts_own_minimum():
    # BDT 120.00, the real value Meta returns for a Bangladeshi account.
    assert min_budget_cents({"min_daily_budget": 12000}) == 12000


def test_floor_never_drops_below_the_static_constant():
    """A nonsense or zero minimum must not let a 1-unit budget through."""
    assert min_budget_cents({"min_daily_budget": 1}) == MIN_BUDGET_CENTS
    assert min_budget_cents({"min_daily_budget": "not a number"}) == MIN_BUDGET_CENTS
    assert min_budget_cents({"min_daily_budget": None}) == MIN_BUDGET_CENTS


def test_a_total_too_small_for_two_floors_is_raised_to_two_floors():
    """Every plan runs two ad sets and Meta bills its minimum on each.

    200 (20000 minor units) cannot cover the BDT floor twice, so both ad sets get
    the floor and the daily spend rises above what was asked. ``build_campaign_tree``
    is what tells the user — see the compliance note it appends.
    """
    from app.graph.meta_spec.builder import _adset_budgets

    slices = _adset_budgets(
        {"budget": "200", "min_daily_budget": 12000},
        {"adset_budget_breakdown": [
            {"adset_name": "Seed", "budget_pct": 95},
            {"adset_name": "Prospecting", "budget_pct": 5},
        ]},
    )
    assert [s["budget_cents"] for s in slices] == [12000, 12000]


def test_a_funded_account_splits_by_percentage_and_spends_the_whole_total():
    """Above 2x the floor the percentages are honoured exactly — no inflation."""
    from app.graph.meta_spec.builder import _adset_budgets

    slices = _adset_budgets(
        {"budget": "1000", "min_daily_budget": 12000},
        {"adset_budget_breakdown": [
            {"adset_name": "Seed", "budget_pct": 60},
            {"adset_name": "Prospecting", "budget_pct": 40},
        ]},
    )
    assert [s["budget_cents"] for s in slices] == [60000, 40000]
    assert sum(s["budget_cents"] for s in slices) == 100000


def test_a_one_adset_brief_still_gets_a_broader_audience():
    """The brief's ad set count is a budget heuristic — it drops the prospecting
    ad set exactly when the recommendation came out low. The second one is
    synthesized so no plan ships without reach beyond the seed."""
    from app.graph.meta_spec.builder import _adset_budgets

    slices = _adset_budgets(
        {"budget": "1000", "business_name": "Bay Metro", "min_daily_budget": 12000},
        {"adset_budget_breakdown": [{"adset_name": "Bay Metro | Custom Audience", "budget_pct": 100}]},
    )
    assert len(slices) == 2
    assert [s["budget_cents"] for s in slices] == [60000, 40000]
    assert slices[1]["audience_type"] == "lookalike"


def test_below_floor_labels_are_rewritten_in_the_accounts_currency():
    """A dollar-denominated lowball on a non-USD account must not survive — and
    the replacement carries the account's own code, not '$'."""
    from app.graph.builder.executors.campaign import _clamp_budget_label

    ui = {"min_daily_budget": 12000, "ad_account_currency": "BDT"}
    assert (
        _clamp_budget_label("Recommended: $17/day — reaches ~9,900 people", ui, "daily", 1)
        == "Recommended: BDT 120/day — reaches ~9,900 people"
    )
    # Already above the floor: left exactly as the model wrote it.
    above = "Recommended: BDT 5000/day — reaches ~38,000 people"
    assert _clamp_budget_label(above, ui, "daily", 1) == above


@pytest.mark.asyncio
async def test_fetch_ad_account_currency_degrades_to_empty(monkeypatch):
    async def _boom(*a, **k):
        raise meta_ads.MetaAdsError("nope")

    monkeypatch.setattr(meta_ads, "_request", _boom)
    assert await meta_ads.fetch_ad_account_currency("act_1", "tok") == {}


@pytest.mark.asyncio
async def test_fetch_ad_account_currency_asks_only_for_real_fields(monkeypatch):
    """A field the AdAccount does not have fails the WHOLE read with code 100.

    ``currency_offset`` shipped in this list and is not an AdAccount field in
    v25, so every call 400'd, degraded to {}, and put every account silently back
    on the USD floor — the exact bug this function exists to prevent.
    """
    seen: dict = {}

    async def _capture(method, endpoint, token, **kw):
        seen.update(kw.get("json_data") or {})
        return {"currency": "CAD", "min_daily_budget": 100}

    monkeypatch.setattr(meta_ads, "_request", _capture)
    await meta_ads.fetch_ad_account_currency("act_1", "tok")
    assert set(seen["fields"].split(",")) == {"currency", "min_daily_budget"}


@pytest.mark.asyncio
async def test_fetch_ad_account_currency_coerces_meta_strings(monkeypatch):
    async def _ok(*a, **k):
        # Meta returns these as strings often enough to matter.
        return {"currency": "BDT", "min_daily_budget": "12000"}

    monkeypatch.setattr(meta_ads, "_request", _ok)
    assert await meta_ads.fetch_ad_account_currency("act_1", "tok") == {
        "currency": "BDT", "min_daily_budget": 12000,
    }


# ── video readiness gate ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wait_for_video_ready_polls_until_ready(monkeypatch):
    phases = iter([{"status": {"video_status": "processing"}},
                   {"status": {"video_status": "ready"}}])

    async def _get(*a, **k):
        return next(phases)

    monkeypatch.setattr(meta_ads, "_request", _get)
    monkeypatch.setattr(meta_ads.asyncio, "sleep", lambda *_: _done())
    await meta_ads.wait_for_video_ready("vid_1", "tok")


@pytest.mark.asyncio
async def test_wait_for_video_ready_raises_on_error_status(monkeypatch):
    async def _get(*a, **k):
        return {"status": {"video_status": "error"}}

    monkeypatch.setattr(meta_ads, "_request", _get)
    with pytest.raises(meta_ads.MetaAdsError, match="could not process video"):
        await meta_ads.wait_for_video_ready("vid_1", "tok")


@pytest.mark.asyncio
async def test_wait_for_video_ready_does_not_block_publish_on_a_read_failure(monkeypatch):
    """An unreadable status is not fatal — Meta stays the judge, as before."""
    async def _boom(*a, **k):
        raise meta_ads.MetaAdsError("transient")

    monkeypatch.setattr(meta_ads, "_request", _boom)
    await meta_ads.wait_for_video_ready("vid_1", "tok")   # returns, does not raise


async def _done():
    return None


# ── ledger remembers the media kind ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_cached_video_is_not_read_back_as_an_image():
    """The bug: the kind was re-derived from the spec and defaulted to "image",
    so a resumed publish built a video into the creative as an image_hash."""
    ledger = PublishLedger()
    await ledger.record_media("0:0", "vid_123", "video")

    ref, kind = await media_exec._resolve_media_ref(
        ledger=ledger, ledger_key="0:0",
        media_id=None, image_hash=None, video_id=None,
        media_map={},                     # the lookup that used to miss
        label="Ad 1", ad_account_id="act_1", access_token="tok",
        writer=lambda _: None,
    )
    assert (ref, kind) == ("vid_123", "video")


@pytest.mark.asyncio
async def test_legacy_ledger_without_kinds_still_resolves():
    """A ledger written before media_kinds existed falls back to the spec."""
    ledger = PublishLedger({"media": {"0:0": "vid_123"}})
    ref, kind = await media_exec._resolve_media_ref(
        ledger=ledger, ledger_key="0:0",
        media_id="m1", image_hash=None, video_id=None,
        media_map={"m1": {"media_type": "video", "file_path": "x"}},
        label="Ad 1", ad_account_id="act_1", access_token="tok",
        writer=lambda _: None,
    )
    assert (ref, kind) == ("vid_123", "video")


@pytest.mark.asyncio
async def test_a_video_that_never_processes_gets_its_own_step_and_wording(monkeypatch):
    """``wait_for_video_ready`` raises MetaAdsError, which the surrounding
    upload handler catches — so a transcode failure told the user their *image*
    upload failed and sent them to re-add a file Meta already has."""
    from app.graph.builder.executors.media import MetaPublishError, RECOVERABLE_PUBLISH_STEPS

    async def ok_upload(*_a, **_k):
        return "vid_9"

    async def never_ready(*_a, **_k):
        raise meta_ads.MetaAdsError("video vid_9 was still processing after 180s")

    monkeypatch.setattr(meta_ads, "upload_video", ok_upload)
    monkeypatch.setattr(meta_ads, "wait_for_video_ready", never_ready)

    with pytest.raises(MetaPublishError) as err:
        await media_exec._resolve_media_ref(
            ledger=PublishLedger(), ledger_key="0:0",
            media_id="m1", image_hash=None, video_id=None,
            media_map={"m1": {"media_type": "video", "file_path": "https://x/v.mp4"}},
            label="Ad 1", ad_account_id="act_1", access_token="tok",
            writer=lambda _: None,
        )

    assert err.value.step == "video_processing"
    assert "image" not in str(err.value)
    # Recoverable: the fix is a different file, not abandoning the session.
    assert "video_processing" in RECOVERABLE_PUBLISH_STEPS


# ── brief parsing that used to invert a structural decision ───────────────────


@pytest.mark.parametrize("text,expected", [
    ("CBO — one budget across ad sets", True),
    ("CBO", True),
    ("ABO — CBO would starve the seed ad set", False),
    ("ABO", False),
    ("not CBO", False),
    ("", False),
    (None, False),
])
def test_cbo_is_read_from_the_leading_verdict_not_a_substring(text, expected):
    assert _wants_campaign_budget({"budget_optimization_type": text}) is expected


def test_placement_prose_still_restricts_but_is_now_reportable():
    """Naming a platform is a delivery restriction, so the plan has to say so."""
    assert _resolve_placements({"placement_strategy": "Facebook Feed only"}) == ["facebook"]
    assert _resolve_placements({"placement_strategy": "Advantage+ placements"}) == []
    assert _resolve_placements({}) == []
