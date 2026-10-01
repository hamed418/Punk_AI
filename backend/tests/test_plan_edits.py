"""
Typed changes to the BUILT plan (budget / dates / placements), validated against
the real CampaignSpec. Money is the sharp edge: refuse over guess, state the
amount actually set, respect the account currency.
"""

from __future__ import annotations

import copy

import pytest
from langchain_core.messages import HumanMessage

from app.graph.builder.plan_edits import apply_plan_edits, money_period
from app.graph.meta_spec.builder import build_campaign_spec
from app.graph.meta_spec.models import MIN_BUDGET_CENTS, CampaignSpec
from app.graph.narrator.beats import drain_changes

SEED = {"geo_locations": {"custom_locations": [{"latitude": 43.6, "longitude": -79.4, "radius": 2}]}}
BROAD = {"geo_locations": {"cities": [{"name": "Toronto"}]}}

USER_INFO = {
    "campaign_objective": "TRAFFIC", "business_name": "Bean There",
    "business_description": "Specialty coffee roaster", "website_url": "https://beanthere.example",
    "budget": "$50/day", "budget_type": "daily", "campaign_start_date": "August 1, 2099",
}
BRIEF = {
    "campaign_name": "Bean There", "cta_recommendation": "LEARN_MORE — invites a click",
    "adset_budget_breakdown": [
        {"adset_name": "Visitors", "budget_pct": 70, "audience_type": "primary"},
        {"adset_name": "Prospecting", "budget_pct": 30, "audience_type": "lookalike"},
    ],
    "headline_suggestions": ["Fresh roast, daily"], "body_copy_suggestions": ["Come taste the difference."],
}


@pytest.fixture()
def plan() -> dict:
    spec = build_campaign_spec(
        user_info=dict(USER_INFO), geo_data={"maid_count": 12000, "poi_radius_km": 1.5},
        brief=dict(BRIEF), seed_targeting=dict(SEED), broad_targeting=dict(BROAD),
        lookalike_targeting=dict(BROAD), page_id="pg1",
    )
    return spec.model_dump(mode="json")


def _apply(plan, **ops):
    return apply_plan_edits(plan, ops, currency="USD", validate=CampaignSpec.model_validate)


def _daily(spec: dict) -> list[int]:
    return [a["daily_budget"] for a in spec["adsets"]]


def test_period_words():
    assert [money_period(t) for t in ("$40 a day", "200/week", "$900 per month", "1500 total", "40")] == \
        ["day", "week", "month", "total", None]


def test_daily_budget_is_scaled_across_ad_sets_keeping_the_split(plan):
    before = _daily(plan)
    out = _apply(plan, budget="$100 a day")

    assert out.results[0]["status"] == "applied"
    after = _daily(out.spec)
    assert sum(after) == pytest.approx(10000, abs=len(after))            # cents, ±rounding
    assert after[0] / after[1] == pytest.approx(before[0] / before[1], rel=0.05)
    assert "now 100.00 USD" in out.results[0]["detail"]
    CampaignSpec.model_validate(out.spec)
    assert _daily(plan) == before                                        # input never mutated


def test_weekly_amount_becomes_a_daily_budget(plan):
    out = _apply(plan, budget="$700/week")
    assert sum(_daily(out.spec)) == pytest.approx(10000, abs=4)


def test_the_same_amount_is_a_no_op(plan):
    total = sum(_daily(plan))
    out = _apply(plan, budget=f"${total / 100:.2f} a day")
    assert out.results[0]["status"] == "no_op" and out.spec is None


def test_below_metas_minimum_is_refused_and_the_plan_is_untouched(plan):
    out = _apply(plan, budget=f"${MIN_BUDGET_CENTS / 100 - 0.5:.2f} a day")
    assert out.results[0]["status"] == "refused" and "minimum" in out.results[0]["detail"]
    assert out.spec is None


def test_a_total_amount_on_a_daily_plan_is_refused_not_guessed(plan):
    out = _apply(plan, budget="$500 total")
    assert out.results[0]["status"] == "refused" and "per day" in out.results[0]["detail"]


def test_a_daily_amount_on_a_lifetime_plan_is_refused_not_guessed(plan):
    life = copy.deepcopy(plan)
    for a in life["adsets"]:
        a["lifetime_budget"], a["daily_budget"] = a["daily_budget"] * 30, None
    out = _apply(life, budget="$40 a day")
    assert out.results[0]["status"] == "refused" and "total" in out.results[0]["detail"]


def test_unreadable_amount_is_refused(plan):
    assert _apply(plan, budget="a bit more").results[0]["status"] == "refused"


def test_zero_decimal_currency_is_not_scaled_by_a_hundred(plan):
    jpy = copy.deepcopy(plan)
    for a in jpy["adsets"]:
        a["daily_budget"] = 5000
    out = apply_plan_edits(jpy, {"budget": "20000 a day"}, currency="JPY", validate=None)
    # 20000 yen, not 2,000,000: whole yen are the minor unit
    assert sum(a["daily_budget"] for a in out.spec["adsets"]) == pytest.approx(20000, abs=2)


def test_end_date_sets_every_ad_set_and_validates(plan):
    out = _apply(plan, campaign_end_date="2099-12-24")
    assert out.results[0]["status"] == "applied"
    assert all(a["end_time"].startswith("2099-12-24") for a in out.spec["adsets"])


def test_end_before_start_is_refused(plan):
    out = _apply(plan, campaign_end_date="2099-07-01")
    assert out.results[0]["status"] == "refused" and "after the start" in out.results[0]["detail"]


def test_a_start_date_in_the_past_is_refused(plan):
    out = _apply(plan, campaign_start_date="2020-01-01")
    assert out.results[0]["status"] == "refused" and "passed" in out.results[0]["detail"]


def test_unreadable_date_is_refused(plan):
    assert _apply(plan, campaign_end_date="whenever").results[0]["status"] == "refused"


def test_placements_are_set_on_every_ad_set(plan):
    out = _apply(plan, publisher_platforms="only instagram and facebook")
    assert out.results[0]["status"] == "applied"
    assert all(set(a["targeting"]["publisher_platforms"]) == {"facebook", "instagram"} for a in out.spec["adsets"])


def test_advantage_placements_removes_the_restriction(plan):
    narrowed = _apply(plan, publisher_platforms="instagram").spec
    out = _apply(narrowed, publisher_platforms="let Meta choose")
    assert all("publisher_platforms" not in a["targeting"] for a in out.spec["adsets"])


def test_unknown_placement_is_refused(plan):
    assert _apply(plan, publisher_platforms="myspace").results[0]["status"] == "refused"


def test_one_bad_field_does_not_block_a_good_one(plan):
    out = _apply(plan, budget="$80 a day", campaign_end_date="whenever")
    by = {r["field"]: r["status"] for r in out.results}
    assert by == {"budget": "applied", "campaign_end_date": "refused"}
    assert out.spec is not None and sum(_daily(out.spec)) == pytest.approx(8000, abs=4)


def test_a_spec_meta_would_reject_is_never_returned(plan):
    def _reject(_):
        raise ValueError("nope")

    out = apply_plan_edits(plan, {"budget": "$80 a day"}, currency="USD", validate=_reject)
    assert out.spec is None and out.results[0]["status"] == "refused"


# ── through builder_plan's step: ledger, editor reopened, undo ────────────────


def _bs(plan: dict) -> dict:
    return {"marketing_plan": plan, "plan_base": copy.deepcopy(plan),
            "ops_done": ["generate_meta_json"], "stages_complete": ["geo", "maid", "campaign"],
            "filled": {"plan_confirm": "yes"}, "media_ws": {"ad_account_currency": "USD"}}


def test_step_applies_reopens_the_editor_and_is_undoable(plan):
    import asyncio

    from app.graph.builder.builder_node import _apply_plan_edits_step
    from app.graph.builder.interject_tools import perform_undo

    state = {"messages": [HumanMessage(content="x", id="pe-step")], "user_info": {}}
    bs = _bs(plan)
    before = copy.deepcopy(plan)

    _apply_plan_edits_step(bs, state, {"budget": "$100 a day"}, lambda _e: None)

    assert sum(_daily(bs["marketing_plan"])) > sum(_daily(before))
    assert "plan_confirm" not in bs["filled"] and "campaign" not in bs["stages_complete"]
    assert any("100.00 USD" in a for a in drain_changes(state)["applied"])
    assert bs["plan_base"] == before                      # base untouched → a later rebuild sees a user edit

    asyncio.run(perform_undo(bs, state))

    assert bs["marketing_plan"] == before


def test_a_refused_step_leaves_the_plan_and_says_why(plan):
    from app.graph.builder.builder_node import _apply_plan_edits_step

    state = {"messages": [HumanMessage(content="x", id="pe-refuse")], "user_info": {}}
    bs = _bs(plan)
    _apply_plan_edits_step(bs, state, {"budget": "$500 total"}, lambda _e: None)

    assert bs["marketing_plan"] == plan and "plan_confirm" in bs["filled"] and not bs.get("_undo_stack")
    assert "per day" in drain_changes(state)["deviations"][0]


@pytest.mark.asyncio
async def test_dispatch_commits_a_plan_field_instead_of_refusing():
    from unittest.mock import AsyncMock, patch

    from app.graph.resume_router import ResumeIntent
    from app.graph.wizard_helpers import _dispatch_edit_intent

    state = {"messages": [HumanMessage(content="x", id="pe-dispatch")], "user_info": {},
             "campaign_builder_state": {"ops_done": ["generate_meta_json"], "filled": {}}}
    edits: dict = {}
    narrate = AsyncMock()
    with patch("app.graph.wizard_helpers.narrate", new=narrate):
        await _dispatch_edit_intent(
            intent=ResumeIntent(lane="edit", target_field="budget", new_value="$100 a day", confidence=0.95),
            state=state, writer=lambda _e: None, pending={}, cfg={"field": "geo_locations"},
            edits=edits, edit_base={},
        )
    assert edits == {"_plan_edits": {"budget": "$100 a day"}}
    assert narrate.await_count == 0                        # no refusal, no premature ack
    assert drain_changes(state)["heard_not_applied"]
