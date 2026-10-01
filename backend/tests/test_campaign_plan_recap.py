"""
tests/test_campaign_plan_recap.py
─────────────────────────────────
The structured ``campaign_plan`` payload (v2).

The condensed post-confirm recap card that used to be emitted at the
publish_confirm gate is gone — the plan editor already shows what it restated,
and that gate no longer interrupts the user. What remains is the full payload
builder, whose section order is the client contract.
"""
from __future__ import annotations

from app.graph.builder.executors.campaign import brief_to_plan_payload

GEO_DATA = {"maid_count": 12345}

USER_INFO = {
    "budget": "$50/day",
    "budget_type": "daily",
    "campaign_start_date": "2026-08-01",
    "campaign_end_date": "2026-08-11",
}

BRIEF = {
    "campaign_name": "Bean There — Summer",
    "campaign_type_label": "Traffic",
    "strategic_insight": "Repeat visitors convert cheapest.",
    "objective_label": "Traffic",
    "flight_window": "Aug 1 – Aug 11",
    "budget_breakdown": "$50/day",
    "bid_strategy": "Lowest cost",
    "cta_recommendation": "Shop Now",
    "headline_suggestions": ["One", "Two"],
    "body_copy_suggestions": ["Body one"],
    "audience_summary": "People who visited your shop.",
    "audience_persona": "Urban commuters.",
    "adset_structure": "Two ad sets.",
    "full_funnel_recommendation": "Retarget next.",
    "adset_budget_breakdown": [
        {"adset_name": "Visitors", "budget_pct": 70, "budget_amount": "$35/day"},
    ],
    "kpi_targets": {"reach": "40,000", "cpm_target": "$8.50"},
    "campaign_timeline": [{"phase": "Learning", "dates": "Aug 1–7", "focus": "Delivery"}],
}


def test_unfiltered_payload_is_unchanged():
    keys = [s["key"] for s in brief_to_plan_payload(BRIEF, USER_INFO, GEO_DATA)["sections"]]
    assert keys == [
        "metrics", "strategy", "setup", "creative", "audience_summary",
        "audience_persona", "adset_structure", "full_funnel_recommendation",
        "adsets", "kpis", "timeline",
    ]
