"""``builder_node._enrich_reach_estimate`` — wires fetch_delivery_estimate
into the plan editor's estimated_reach dict, beside the MAID audience size
already there. Best-effort: the plan screen must render identically without
Meta's numbers as with them.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.graph.builder.builder_node import _enrich_reach_estimate
from app.graph.meta_spec.builder import build_campaign_spec

SEED = {"geo_locations": {"cities": [{"name": "Toronto"}]}}
USER_INFO = {
    "campaign_objective": "TRAFFIC",
    "business_name": "Bean There",
    "business_description": "Specialty coffee roaster",
    "website_url": "https://beanthere.example",
    "budget": "$50/day",
    "budget_type": "daily",
    "campaign_start_date": "August 1, 2026",
}
BRIEF = {
    "campaign_name": "Bean There — Summer",
    "adset_budget_breakdown": [
        {"adset_name": "Visitors", "budget_pct": 70, "audience_type": "primary"},
        {"adset_name": "Prospecting", "budget_pct": 30, "audience_type": "lookalike"},
    ],
    "headline_suggestions": ["Fresh roast, daily"],
    "body_copy_suggestions": ["Come taste the difference."],
    "cta_recommendation": "LEARN_MORE",
}


def _spec():
    return build_campaign_spec(
        user_info=dict(USER_INFO),
        geo_data={"maid_count": 12000},
        brief=dict(BRIEF),
        seed_targeting=dict(SEED),
        broad_targeting=dict(SEED),
        lookalike_targeting=dict(SEED),
        page_id="pg1",
    )


@pytest.mark.asyncio
async def test_adds_metas_estimate_alongside_the_existing_maid_count():
    plan = {"estimated_reach": {"maid_count": 12000, "radius_km": 5}}
    spec = _spec()
    ui = {"meta_ad_account_id": "act_1", "meta_access_token": "tok"}

    with patch(
        "app.services.meta_ads.fetch_delivery_estimate",
        AsyncMock(return_value={
            "estimate_mau_lower_bound": 10_000,
            "estimate_mau_upper_bound": 50_000,
            "estimate_ready": True,
        }),
    ):
        await _enrich_reach_estimate(plan, spec, ui)

    # Existing MAID-side numbers survive — this is additive, not a replace.
    assert plan["estimated_reach"]["maid_count"] == 12000
    assert plan["estimated_reach"]["radius_km"] == 5
    assert plan["estimated_reach"]["estimate_mau_lower_bound"] == 10_000
    assert plan["estimated_reach"]["estimate_mau_upper_bound"] == 50_000
    assert plan["estimated_reach"]["estimate_ready"] is True


@pytest.mark.asyncio
async def test_skips_silently_without_an_ad_account():
    """Plan reviewed before Meta is connected — no crash, no partial write."""
    plan = {"estimated_reach": {"maid_count": 100}}
    with patch("app.services.meta_ads.fetch_delivery_estimate", AsyncMock()) as fetch:
        await _enrich_reach_estimate(plan, _spec(), {})
    fetch.assert_not_called()
    assert plan == {"estimated_reach": {"maid_count": 100}}


@pytest.mark.asyncio
async def test_skips_silently_on_a_draft_with_no_validated_spec():
    """A mid-edit draft render has no CampaignSpec object (see _plan_form_extra)
    — spec is None, and enrichment must not attempt to read .adsets off it."""
    plan = {"estimated_reach": {}}
    ui = {"meta_ad_account_id": "act_1", "meta_access_token": "tok"}
    with patch("app.services.meta_ads.fetch_delivery_estimate", AsyncMock()) as fetch:
        await _enrich_reach_estimate(plan, None, ui)
    fetch.assert_not_called()


@pytest.mark.asyncio
async def test_a_metadata_endpoint_failure_never_breaks_the_plan_screen():
    """fetch_delivery_estimate already degrades to None on any Graph failure
    (test_meta_transport.py) — this must simply skip the merge, not raise."""
    plan = {"estimated_reach": {"maid_count": 100}}
    ui = {"meta_ad_account_id": "act_1", "meta_access_token": "tok"}
    with patch("app.services.meta_ads.fetch_delivery_estimate", AsyncMock(return_value=None)):
        await _enrich_reach_estimate(plan, _spec(), ui)
    assert plan == {"estimated_reach": {"maid_count": 100}}


@pytest.mark.asyncio
async def test_an_unexpected_exception_is_swallowed():
    plan = {"estimated_reach": {}}
    ui = {"meta_ad_account_id": "act_1", "meta_access_token": "tok"}
    with patch(
        "app.services.meta_ads.fetch_delivery_estimate",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        await _enrich_reach_estimate(plan, _spec(), ui)  # must not raise
    assert plan["estimated_reach"] == {}
