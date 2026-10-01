"""Tests for the campaign-builder planner machinery (PR5.1 dark, PR5.2 wiring).

Covers the code-enforced invariants — never the prompt:
  - stage-order coercion (act on a later stage gets replaced)
  - invalid/out-of-stage ask slots get replaced with the next required slot
  - premature done gets coerced back to work
  - act allowed only once required slots are filled
  - slot prefill from user_info
  - iteration budget exhaustion sets wizard_failure
  - flag-off: entry routing still targets geo_wizard
  - 5.2: campaign-stage act sequence with plan_confirm gate, gate slots
    refused before their op, revision/decline/cancel confirm semantics,
    stage-completion refresh, finalize merge
"""

import asyncio
import json
from unittest.mock import patch

import pytest

from app.graph.builder.builder_node import (
    PlannerAction,
    _MAX_PLAN_ITERATIONS,
    _MaidSettingsExtract,
    _apply_confirm_semantics,
    _backfill_location_scope,
    _cached_parse,
    _enrich_slot_ask,
    _looks_like_admin_or_country,
    _next_step,
    _normalize_slot_answer,
    _resolved_pixel_id,
    _refresh_stage_completion,
    _self_referential_exclusion_needs_store,
    builder_act,
    builder_ask,
    builder_finalize,
    builder_plan,
    coerce_action,
    _current_stage,
)
from app.graph.builder.executors.media import MetaPublishError
from app.graph.builder.slots import (
    SLOTS,
    Slot,
    missing_required_slots,
    prefill_for,
    slot_applies,
)
from app.graph.prompts_registry import GO_LIVE_OPTIONS

def _valid_spec() -> dict:
    """A minimal, valid serialized CampaignSpec — the shape the campaign editor
    submits (whole tree, ads nested under ad sets)."""
    return {
        "name": "C",
        "objective": "OUTCOME_TRAFFIC",
        "adsets": [
            {
                "name": "AS1",
                "audience_role": "broad",
                "optimization_goal": "LINK_CLICKS",
                "billing_event": "IMPRESSIONS",
                "destination_type": "WEBSITE",
                "daily_budget": 5000,
                "targeting": {"geo_locations": {"countries": ["US"]}},
                "start_time": "2026-07-01T00:00:00+00:00",
                "ads": [
                    {
                        "name": "AS1 Ad 1",
                        "creative": {
                            "title": "t", "body": "b",
                            "call_to_action": "LEARN_MORE",
                            "link": "https://x.example",
                        },
                    }
                ],
            }
        ],
    }


# The plan gate is satisfied by a campaign_plan_editor publish submission.
_PLAN_APPROVE = json.dumps({"action": "publish", "spec": _valid_spec()})


def _bs(filled=None, stages_complete=None, **kw):
    return {"filled": filled or {}, "stages_complete": stages_complete or [], **kw}


# ── coerce_action invariants ───────────────────────────────────────────────────

def test_act_out_of_stage_is_coerced_to_ask():
    bs = _bs()  # nothing filled — current stage is geo
    action, note = coerce_action(PlannerAction(kind="act", operation="publish"), bs, {})
    assert note and "out of stage" in note
    assert action["kind"] == "ask"
    assert SLOTS[action["slot"]].stage == "geo"


def test_act_before_required_slots_is_coerced():
    bs = _bs(filled={"locations": "Montreal"})  # geo still missing slots
    action, note = coerce_action(PlannerAction(kind="act", operation="geo_discover"), bs, {})
    assert note and "before required slots" in note
    assert action["kind"] == "ask"


def test_act_allowed_when_stage_slots_filled():
    filled = {
        "location_scope": "granular_local", "locations": "Montreal",
        "business_desc": "coffee shop", "targeting_method": "deterministic",
        "det_type": "category", "poi_types": "coffee shop",
    }
    action, note = coerce_action(PlannerAction(kind="act", operation="geo_discover"), _bs(filled=filled), {})
    assert note is None
    assert action == {"kind": "act", "operation": "geo_discover"}


def test_invalid_ask_slot_is_replaced():
    action, note = coerce_action(PlannerAction(kind="ask", slot="nonsense"), _bs(), {})
    assert note and "invalid" in note
    assert action["kind"] == "ask" and action["slot"] in SLOTS


def test_premature_done_is_coerced_back_to_work():
    action, note = coerce_action(PlannerAction(kind="done"), _bs(), {})
    assert note and "incomplete" in note
    assert action["kind"] == "ask"


def test_planner_fail_with_no_errors_is_coerced_to_next_step():
    """A repeated proposal (e.g. `_GeoStepPaused` re-dispatching the same op
    after an internal confirm resolves) is not a real failure — the planner
    misreading it must not surface a false "something broke" apology."""
    bs = _bs(action_log=[
        {"step": "act:geo_discover", "summary": "paused — one confirm answered, re-dispatching"},
        {"step": "act:geo_discover", "summary": "paused — one confirm answered, re-dispatching"},
    ])
    action, note = coerce_action(PlannerAction(kind="fail", reason="stuck"), bs, {})
    assert note and "planner gave up" in note
    assert action["kind"] != "fail"


def test_planner_fail_with_repeated_error_is_honored():
    """The genuine escape hatch: an op that actually errored twice must still
    be able to fail out to the user."""
    bs = _bs(action_log=[
        {"step": "act:geo_discover", "summary": "error: boom"},
        {"step": "act:geo_discover", "summary": "error: boom again"},
    ])
    action, note = coerce_action(PlannerAction(kind="fail", reason="stuck"), bs, {})
    assert action == {"kind": "fail", "reason": "stuck"}
    assert note is None


def test_maid_stage_always_runs():
    # Targeting is always deterministic — the maid stage is never skipped.
    bs = _bs(stages_complete=["geo"])
    assert _current_stage(bs, {}) == "maid"


# ── prefill ───────────────────────────────────────────────────────────────────

def test_prefill_from_user_info_lists_and_scalars():
    ui = {"location": ["Montreal", "Toronto"], "search_radius_km": "12"}
    assert prefill_for(SLOTS["locations"], ui) == "Montreal, Toronto"
    assert prefill_for(SLOTS["radius_km"], ui) == "12"
    # campaign_intake carries no prefill_key — prefill lives in the form schema.
    assert prefill_for(SLOTS["campaign_intake"], ui) is None


def test_store_location_bridge_from_generic_location():
    """A store address captured into the generic `location` field prefills the
    store-anchor slots when the det_type uses the user's own store."""
    # store_set: street-address-shaped location bridges into store_addresses.
    ui = {"deterministic_subtype": "store_set", "location": ["123 Main St, Montreal"]}
    assert prefill_for(SLOTS["store_addresses"], ui) == "123 Main St, Montreal"
    # competitor_nearby: same location bridges into the competitor anchor slot.
    ui2 = {"deterministic_subtype": "competitor_nearby", "location": ["500 Peel St Montreal"]}
    assert prefill_for(SLOTS["competitor_anchor"], ui2) == "500 Peel St Montreal"


def test_store_location_bridge_rejects_bare_city_and_wrong_dettype():
    # Bare city (no digit) must NOT be dumped into a store address.
    ui = {"deterministic_subtype": "store_set", "location": ["Montreal"]}
    assert prefill_for(SLOTS["store_addresses"], ui) is None
    # Lone postal code (single token) is not a geocodable street address.
    ui_pc = {"deterministic_subtype": "store_set", "location": ["90210"]}
    assert prefill_for(SLOTS["store_addresses"], ui_pc) is None
    # Bridge only fires for store_set / competitor_nearby det_types.
    ui_cat = {"deterministic_subtype": "category", "location": ["123 Main St, Montreal"]}
    assert prefill_for(SLOTS["store_addresses"], ui_cat) is None
    # A real store_addresses value always wins over the bridge.
    ui_real = {
        "deterministic_subtype": "store_set",
        "store_addresses": ["9 Oak Ave"],
        "location": ["123 Main St, Montreal"],
    }
    assert prefill_for(SLOTS["store_addresses"], ui_real) == "9 Oak Ave"


# ── confirm_prefill: knobs that size a paid audience must never be silently
# ── seeded from an extraction guess (thread f7ad8978-5e21-4746-b47c-474a3439eb4a:
# ── a guessed poi_radius_m never surfaced as a question at all) ────────────────

def test_confirm_prefill_slots_marked_in_slots_module():
    for name in ("poi_radius_m", "lookback_days", "radius_km", "competitor_radius_km"):
        assert SLOTS[name].confirm_prefill is True
    # An ordinary opportunistic slot is unaffected.
    assert SLOTS["locations"].confirm_prefill is False


def test_confirm_prefill_slots_never_silently_seeded(writer_events):
    async def _boom(*args, **kwargs):
        raise RuntimeError("api down")

    state = {
        "messages": [],
        "user_info": {
            "location": ["Montreal"],
            "poi_radius_m": 250,
            "lookback_days": 30,
            "search_radius_km": 8,
        },
        "campaign_builder_state": None,
    }
    with patch("app.graph.builder.builder_node.tracked_ainvoke", side_effect=_boom):
        result = asyncio.run(builder_plan(state))

    bs = result["campaign_builder_state"]
    assert bs["_prefill_seeded"] is True
    assert "poi_radius_m" not in bs["filled"]
    assert "lookback_days" not in bs["filled"]
    assert "radius_km" not in bs["filled"]
    assert "competitor_radius_km" not in bs["filled"]
    # Ordinary opportunistic slots still seed normally.
    assert bs["filled"]["locations"] == "Montreal"


def test_maid_stage_asks_combined_widget_despite_extraction_guess():
    """With poi_radius_m unfilled (confirm_prefill kept it out of `filled`),
    _next_step must pick it as the ask — never treat an extraction guess as
    an answer that lets it skip straight to the lookback-only ask."""
    bs = _bs(filled={**_GEO_FILLED, "poi_confirm": "yes"}, stages_complete=["geo"])
    assert _next_step(bs, "maid") == {"kind": "ask", "slot": "poi_radius_m"}


def test_reconcile_geo_scope_demotes_radius_for_store_subtype():
    """'radius' scope + own-store subtype is contradictory. The guard demotes
    radius so the un-prefillable radius_pin map interrupt is never asked and the
    store-address path runs instead."""
    from app.graph.builder.builder_node import _reconcile_geo_scope

    # store_set + a named city → radius demoted to granular_local; the map-pin
    # slot no longer applies, next geo ask is the store address.
    filled = {"location_scope": "radius", "det_type": "store_set"}
    _reconcile_geo_scope(filled, {"location": ["Montreal"]})
    assert filled["location_scope"] == "granular_local"
    missing = {s.name for s in missing_required_slots("geo", filled)}
    assert "radius_pin" not in missing
    assert "store_addresses" in missing

    # competitor_nearby with no known location → scope cleared so the location
    # type is asked cleanly (still no radius_pin).
    filled2 = {"location_scope": "radius", "det_type": "competitor_nearby"}
    _reconcile_geo_scope(filled2, {})
    assert "location_scope" not in filled2
    assert "radius_pin" not in {s.name for s in missing_required_slots("geo", filled2)}

    # A genuine radius request (no store subtype) is left untouched.
    filled3 = {"location_scope": "radius", "det_type": "category"}
    _reconcile_geo_scope(filled3, {"location": ["Montreal"]})
    assert filled3["location_scope"] == "radius"
    assert "radius_pin" in {s.name for s in missing_required_slots("geo", filled3)}


# ── list parsing ──────────────────────────────────────────────────────────────

def test_cached_parse_empty_short_circuits_without_llm():
    """Empty/blank slot values must NOT invoke the LLM parser — most det_types
    leave the other types' list slots blank."""
    calls = []

    async def _parser(raw):
        calls.append(raw)
        return ["should not happen"]

    ws: dict = {}
    assert asyncio.run(_cached_parse(ws, "_k", "", _parser)) == []
    assert asyncio.run(_cached_parse(ws, "_k", "   ", _parser)) == []
    assert calls == []


def test_cached_parse_runs_once_and_caches():
    calls = []

    async def _parser(raw):
        calls.append(raw)
        return [raw.upper()]

    ws: dict = {}
    assert asyncio.run(_cached_parse(ws, "_k", "gyms", _parser)) == ["GYMS"]
    assert asyncio.run(_cached_parse(ws, "_k", "gyms", _parser)) == ["GYMS"]
    assert calls == ["gyms"]  # second call served from cache


# ── builder_plan node behavior ────────────────────────────────────────────────

@pytest.fixture()
def writer_events():
    events: list[dict] = []
    with patch("app.graph.builder.builder_node.get_writer", return_value=events.append):
        yield events


def test_iteration_budget_sets_wizard_failure(writer_events):
    state = {
        "messages": [],
        "user_info": {},
        "campaign_builder_state": _bs(iteration=_MAX_PLAN_ITERATIONS, _prefill_seeded=True),
    }
    result = asyncio.run(builder_plan(state))
    assert result["wizard_failure"] == "builder_iteration_budget"
    assert result["campaign_builder_state"]["next_action"]["kind"] == "fail"


def test_plan_seeds_prefill_and_coerces_llm_failure(writer_events):
    async def _boom(*args, **kwargs):
        raise RuntimeError("api down")

    state = {
        "messages": [],
        "user_info": {"location": ["Austin"], "business_description": "coffee shop"},
        "campaign_builder_state": None,
    }
    with patch("app.graph.builder.builder_node.tracked_ainvoke", side_effect=_boom):
        result = asyncio.run(builder_plan(state))

    bs = result["campaign_builder_state"]
    # prefill seeded from user_info (business details now live in the intake form,
    # which carries no seedable slot — only geo slots seed here)
    assert bs["filled"]["locations"] == "Austin"
    # LLM failure coerced to a deterministic ask in the current (geo) stage
    assert bs["next_action"]["kind"] == "ask"
    assert SLOTS[bs["next_action"]["slot"]].stage == "geo"
    assert "wizard_failure" not in result


# ── entry routing ─────────────────────────────────────────────────────────────

def test_geo_agent_alias_routes_to_builder():
    # campaign_builder is the sole build path; the legacy "geo_agent" alias the
    # entry LLM may still emit resolves to it unconditionally (wizard chain gone).
    from app.graph.graph import _entry_route

    assert _entry_route({"next_nodes": ["geo_agent"]}) == "campaign_builder"
    assert _entry_route({"next_nodes": ["campaign_builder"]}) == "campaign_builder"


# ── 5.2: stage sequencing, gates, confirm semantics ──────────────────────────

_GEO_FILLED = {
    "location_scope": "granular_local", "locations": "Montreal",
    "business_desc": "coffee shop", "targeting_method": "deterministic",
    "det_type": "category", "poi_types": "coffee shop",
}
_CAMPAIGN_FILLED = {
    **_GEO_FILLED,
    "poi_confirm": "yes",
    "poi_radius_m": "500", "lookback_days": "30", "maid_confirm": "yes",
    # publish_mode gates campaign_intake (skipped for guide/self — see
    # slots.py) and precedes it in declaration order, so every fixture that
    # expects campaign_intake to already be answered needs a mode too.
    # Express is the mode that still asks the form these other keys came from.
    "publish_mode": "express",
    # The intake form fills these in one submission.
    "campaign_intake": "done",
    "business_name": "Cafe X", "business_desc": "coffee shop",
    "objective": "TRAFFIC", "website_url": "https://cafex.com",
}


def _campaign_bs(**kw):
    base = dict(
        filled=dict(_CAMPAIGN_FILLED),
        stages_complete=["geo", "maid"],
        # connect_meta is the first campaign pre-act (Meta OAuth + ad account),
        # fired right after the audience is confirmed. enrich_website is the
        # second pre-act, running once business_name + objective are filled.
        ops_done=["geo_discover", "maid_query", "connect_meta", "enrich_website"],
    )
    base.update(kw)
    return _bs(**base)


def test_campaign_stage_act_sequence_with_plan_gate():
    """Campaign stage: connect Meta → brief → pixel → spec → approve.

    connect_meta (OAuth + ad account) is the first campaign pre-act, firing
    right after the audience is confirmed so the intake + brief run with the
    user's Meta account resolved. resolve_meta (pixel only now) stays ahead of
    generate_meta_json, because the spec needs the real pixel id to build a
    promoted_object. The spec is built BEFORE plan_confirm so the gate presents a
    real, editable payload instead of a preview of one.
    """
    # connect_meta not yet done → it fires first, before brief/spec.
    bs = _campaign_bs(ops_done=["geo_discover", "maid_query", "enrich_website"])
    assert _next_step(bs, "campaign") == {"kind": "act", "operation": "connect_meta"}
    bs["ops_done"] = bs["ops_done"] + ["connect_meta"]
    # Meta connected, all slots filled, no brief yet → act generate_brief
    assert _next_step(bs, "campaign") == {"kind": "act", "operation": "generate_brief"}
    # Brief generated → resolve the pixel so the spec can reference a real id
    bs["ops_done"] = bs["ops_done"] + ["generate_brief"]
    assert _next_step(bs, "campaign") == {"kind": "act", "operation": "resolve_meta"}
    # Pixel resolved → build the spec, ungated
    bs["ops_done"] = bs["ops_done"] + ["resolve_meta"]
    assert _next_step(bs, "campaign") == {"kind": "act", "operation": "generate_meta_json"}
    # Spec built → now the user approves it (stage exit gate)
    bs["ops_done"] = bs["ops_done"] + ["generate_meta_json"]
    assert _next_step(bs, "campaign") == {"kind": "ask", "slot": "plan_confirm"}
    bs["filled"]["plan_confirm"] = _PLAN_APPROVE
    assert _next_step(bs, "campaign") is None
    # Media stage: no publish gate (the editor's Publish button is the
    # confirmation), so publish fires straight away and creates everything PAUSED.
    # Only then does go_live_confirm gate `activate`.
    assert _next_step(bs, "media") == {"kind": "act", "operation": "publish"}
    bs["ops_done"] = bs["ops_done"] + ["publish"]
    assert _next_step(bs, "media") == {"kind": "ask", "slot": "go_live_confirm"}
    bs["filled"]["go_live_confirm"] = GO_LIVE_OPTIONS[0]
    assert _next_step(bs, "media") == {"kind": "act", "operation": "activate"}


def test_sales_without_an_account_pixel_is_never_asked_as_an_interrupt():
    """The Pixel is a field of the campaign, so it is asked in the plan editor
    (which lists the ad account's actual pixels) — never as its own interrupt,
    and never at the price of silently downgrading SALES to Traffic."""
    filled = {**_CAMPAIGN_FILLED, "objective": "SALES"}
    bs = _campaign_bs(
        filled=filled,
        ops_done=["geo_discover", "maid_query", "connect_meta", "enrich_website",
                  "generate_brief"],
    )
    assert _next_step(bs, "campaign") == {"kind": "act", "operation": "resolve_meta"}

    # media_select_pixel found nothing on the ad account. The stage carries on:
    # the spec is built anyway and the editor opens on the offending field.
    bs["ops_done"] = bs["ops_done"] + ["resolve_meta"]
    assert _resolved_pixel_id(bs, {"pixel_id": "999888777"}) is None
    assert _next_step(bs, "campaign") == {"kind": "act", "operation": "generate_meta_json"}
    bs["ops_done"] = bs["ops_done"] + ["generate_meta_json"]
    assert _next_step(bs, "campaign") == {"kind": "ask", "slot": "plan_confirm"}


def test_a_website_pixel_never_becomes_the_campaign_pixel():
    """A Pixel on the advertiser's SITE is not a Pixel on the ad account we
    publish to. Seeding the plan with it produced an id the editor's account-
    scoped picker cannot display, and a publish Meta rejects."""
    bs = _campaign_bs()
    ui = {"pixel_id": "111222333444"}          # scraped by enrich_website
    assert _resolved_pixel_id(bs, ui) is None
    bs["media_ws"] = {"pixel_id": "555666777"}  # resolved against the ad account
    assert _resolved_pixel_id(bs, ui) == "555666777"


def test_geo_exit_gate_sequencing_deterministic():
    bs = _bs(filled=dict(_GEO_FILLED))
    assert _next_step(bs, "geo") == {"kind": "act", "operation": "geo_discover"}
    bs["ops_done"] = ["geo_discover"]
    assert _next_step(bs, "geo") == {"kind": "ask", "slot": "poi_confirm"}
    bs["filled"]["poi_confirm"] = "yes"
    assert _next_step(bs, "geo") is None


def test_geo_exit_gate_skipped_for_store_set():
    filled = {
        "location_scope": "granular_local", "locations": "Montreal",
        "business_desc": "shawarma shop", "targeting_method": "deterministic",
        "det_type": "store_set", "store_addresses": "1340 Sainte-Catherine St. West",
    }
    bs = _bs(filled=filled, ops_done=["geo_discover"])
    # poi_confirm's not_when excludes store_set — the stores were already
    # confirmed (with a map) at geo_store_confirmation, so the stage exits
    # without a second mapless gate (wizard parity with geo_confirm_pois).
    assert _next_step(bs, "geo") is None


def test_poi_confirm_decline_reasks():
    bs = _bs(filled={**_GEO_FILLED, "poi_confirm": "no, drop the mall"}, ops_done=["geo_discover"])
    note = asyncio.run(_apply_confirm_semantics(bs, {}))
    assert note and "asking again" in note
    assert "poi_confirm" not in bs["filled"]
    assert _next_step(bs, "geo") == {"kind": "ask", "slot": "poi_confirm"}


def test_poi_confirm_json_true_advances_stage():
    # The editable POI map sends a JSON delta, not plain "yes". A {"confirm":true}
    # payload must be read as a confirmation (not a decline) so geo exits.
    bs = _bs(
        filled={**_GEO_FILLED,
                "poi_confirm": '{"confirm":true,"added":[],"removed":[]}'},
        ops_done=["geo_discover"],
        geo_result={"pois_found": 3, "targetable_pois": [
            {"name": "Gym A", "lat": 45.5, "lng": -73.5},
            {"name": "Gym B", "lat": 45.51, "lng": -73.51},
            {"name": "Gym C", "lat": 45.52, "lng": -73.52},
        ]},
    )
    note = asyncio.run(_apply_confirm_semantics(bs, {}))
    assert note is None or "asking again" not in note  # not a decline
    assert "poi_confirm" in bs["filled"]                # gate stays satisfied
    assert _next_step(bs, "geo") is None                # geo stage exits


def test_poi_confirm_json_false_reasks():
    bs = _bs(
        filled={**_GEO_FILLED, "poi_confirm": '{"confirm":false}'},
        ops_done=["geo_discover"],
        geo_result={"pois_found": 3, "targetable_pois": []},
    )
    note = asyncio.run(_apply_confirm_semantics(bs, {}))
    assert note and "asking again" in note
    assert "poi_confirm" not in bs["filled"]
    assert _next_step(bs, "geo") == {"kind": "ask", "slot": "poi_confirm"}


def test_poi_confirm_json_applies_edits_to_geo_result():
    bs = _bs(
        filled={**_GEO_FILLED, "poi_confirm": (
            '{"confirm":true,'
            ' "added":[{"name":"Picked","lat":45.6,"lng":-73.6}],'
            ' "removed":[{"name":"Gym A","lat":45.5,"lng":-73.5}]}'
        )},
        ops_done=["geo_discover"],
        geo_result={"pois_found": 2, "poi_radius_km": 1.5, "targetable_pois": [
            {"name": "Gym A", "lat": 45.5, "lng": -73.5},
            {"name": "Gym B", "lat": 45.51, "lng": -73.51},
        ]},
    )
    note = asyncio.run(_apply_confirm_semantics(bs, {}))
    assert note and "POI edits applied" in note
    names = {p["name"] for p in bs["geo_result"]["targetable_pois"]}
    assert names == {"Gym B", "Picked"}
    assert bs["geo_result"]["pois_found"] == 2
    added = next(p for p in bs["geo_result"]["targetable_pois"] if p["name"] == "Picked")
    assert added["radius_km"] == 1.5  # backfilled from geo_result.poi_radius_km
    assert "poi_confirm" in bs["filled"]
    # A POI edit must flag a geo_data re-commit so the narrator grounding pack
    # refreshes to the new count (the "count never updates" bug).
    assert bs["_geo_recommit"] is True


def test_poi_edit_makes_builder_plan_recommit_geo_data(writer_events):
    """After a POI map edit changes the count, builder_plan must re-emit geo_data
    so the narrator grounding pack sees the new total (not just the scratch)."""
    edited_pois = [
        {"name": "Gym B", "lat": 45.51, "lng": -73.51},
        {"name": "Picked", "lat": 45.6, "lng": -73.6},
    ]
    bs = _bs(
        filled={**_GEO_FILLED, "poi_confirm": (
            '{"confirm":true,'
            ' "added":[{"name":"Picked","lat":45.6,"lng":-73.6}],'
            ' "removed":[{"name":"Gym A","lat":45.5,"lng":-73.5}]}'
        )},
        _prefill_seeded=True,
        ops_done=["geo_discover"],
        geo_result={"pois_found": 2, "poi_radius_km": 1.5, "targetable_pois": [
            {"name": "Gym A", "lat": 45.5, "lng": -73.5},
            {"name": "Gym B", "lat": 45.51, "lng": -73.51},
        ]},
    )
    state = {"messages": [], "user_info": {}, "campaign_builder_state": bs}
    with patch("app.graph.builder.builder_node.tracked_ainvoke",
               side_effect=RuntimeError("skip llm — deterministic path")):
        result = asyncio.run(builder_plan(state))
    # geo_data is re-committed and carries the edited spot set + refreshed count.
    assert "geo_data" in result
    assert result["geo_data"]["pois_found"] == 2
    assert {p["name"] for p in result["geo_data"]["targetable_pois"]} == {"Gym B", "Picked"}
    # the recommit flag is consumed (popped), not left sticky
    assert "_geo_recommit" not in result["campaign_builder_state"]


def test_maid_exit_gate_sequencing():
    bs = _bs(
        filled={**_GEO_FILLED, "poi_radius_m": "500", "lookback_days": "30"},
        stages_complete=["geo"],
        ops_done=["geo_discover"],
    )
    assert _next_step(bs, "maid") == {"kind": "act", "operation": "maid_query"}
    bs["ops_done"] = bs["ops_done"] + ["maid_query"]
    assert _next_step(bs, "maid") == {"kind": "ask", "slot": "maid_confirm"}
    bs["filled"]["maid_confirm"] = "yes"
    assert _next_step(bs, "maid") is None


def test_gate_slot_refused_before_its_operation():
    bs = _campaign_bs()  # generate_brief NOT done yet
    action, note = coerce_action(PlannerAction(kind="ask", slot="plan_confirm"), bs, {})
    assert note and "gate slot" in note
    assert action == {"kind": "act", "operation": "generate_brief"}


def test_act_repeat_is_coerced():
    bs = _campaign_bs(ops_done=[
        "geo_discover", "maid_query", "connect_meta", "enrich_website",
        "generate_brief", "resolve_meta",
    ])
    bs["filled"]["plan_confirm"] = _PLAN_APPROVE
    action, note = coerce_action(PlannerAction(kind="act", operation="generate_brief"), bs, {})
    assert note and "already done" in note
    assert action == {"kind": "act", "operation": "generate_meta_json"}


def test_meta_json_requires_meta_connection_first():
    """generate_meta_json is no longer gated on plan_confirm — the spec has to
    exist before the user can approve it. What it IS ordered behind is
    resolve_meta, whose page/pixel ids the spec's promoted_object needs."""
    bs = _campaign_bs(ops_done=[
        "geo_discover", "maid_query", "connect_meta", "enrich_website", "generate_brief",
    ])
    action, note = coerce_action(PlannerAction(kind="act", operation="generate_meta_json"), bs, {})
    assert note
    assert action == {"kind": "act", "operation": "resolve_meta"}


def test_publish_still_refused_without_plan_confirm():
    """The campaign stage cannot close until the plan is approved, so publish
    stays unreachable — the approval gate just moved later in the stage."""
    bs = _campaign_bs(ops_done=[
        "geo_discover", "maid_query", "connect_meta", "enrich_website",
        "generate_brief", "resolve_meta", "generate_meta_json",
    ])
    assert _next_step(bs, "campaign") == {"kind": "ask", "slot": "plan_confirm"}


def test_plan_form_save_stores_edited_spec_and_reasks():
    """A save submission validates and stores the whole edited spec, keeps the
    brief, and re-asks the gate so the editor re-emits — no brief regeneration."""
    bs = _campaign_bs(ops_done=[
        "geo_discover", "maid_query", "enrich_website",
        "generate_brief", "resolve_meta", "generate_meta_json",
    ])
    bs["brief"] = {"campaign_name": "v1"}
    edited = _valid_spec()
    edited["adsets"][0]["daily_budget"] = 3000
    bs["filled"]["plan_confirm"] = json.dumps({"action": "save", "spec": edited})
    note = asyncio.run(_apply_confirm_semantics(bs, {}))
    assert note and "saved" in note
    assert bs["marketing_plan"]["adsets"][0]["daily_budget"] == 3000
    assert "plan_overrides" not in bs                       # no diff mechanism now
    assert bs["brief"] == {"campaign_name": "v1"}          # brief survives
    assert "plan_confirm" not in bs["filled"]              # gate re-asked


def test_plan_form_prose_reply_reasks_without_revision():
    """A stray typed reply (not a form submission) just drops the gate answer so
    the form re-emits — there is no prose-revision path anymore."""
    bs = _campaign_bs(ops_done=[
        "geo_discover", "maid_query", "enrich_website",
        "generate_brief", "resolve_meta", "generate_meta_json",
    ])
    bs["brief"] = {"campaign_name": "v1"}
    bs["filled"]["plan_confirm"] = "drop the budget to $30/day"
    note = asyncio.run(_apply_confirm_semantics(bs, {}))
    assert note and "re-asking" in note
    assert "revision_note" not in bs
    assert bs["brief"] == {"campaign_name": "v1"}
    assert "plan_confirm" not in bs["filled"]


def test_maid_confirm_decline_reasks():
    bs = _campaign_bs(stages_complete=["geo"], ops_done=["geo_discover", "maid_query"])
    bs["filled"]["maid_confirm"] = "no, that audience looks wrong"
    note = asyncio.run(_apply_confirm_semantics(bs, {}))
    assert note and "asking again" in note
    assert "maid_confirm" not in bs["filled"]
    assert _next_step(bs, "maid") == {"kind": "ask", "slot": "maid_confirm"}


def test_go_live_leave_paused_closes_the_media_stage():
    bs = _campaign_bs(
        ops_done=["geo_discover", "maid_query", "enrich_website", "generate_brief",
                  "generate_meta_json", "resolve_meta", "publish"],
    )
    bs["filled"]["plan_confirm"] = _PLAN_APPROVE
    bs["filled"]["go_live_confirm"] = GO_LIVE_OPTIONS[-1]  # Leave it paused — ...
    note = asyncio.run(_apply_confirm_semantics(bs, {}))
    assert note and "paused" in note
    assert bs["stay_paused"] is True
    assert "activate" in bs["ops_done"]
    assert _next_step(bs, "media") is None


def test_refresh_marks_completed_stages():
    bs = _campaign_bs(
        ops_done=["geo_discover", "maid_query", "connect_meta", "enrich_website",
                  "generate_brief", "generate_meta_json", "resolve_meta", "publish", "activate"],
    )
    bs["filled"]["plan_confirm"] = _PLAN_APPROVE
    bs["filled"]["go_live_confirm"] = GO_LIVE_OPTIONS[0]
    _refresh_stage_completion(bs, {})
    assert set(bs["stages_complete"]) == {"geo", "maid", "campaign", "media"}
    assert _current_stage(bs, {}) == "done"


def test_finalize_flags_a_fresh_publish(writer_events):
    state = {
        "campaign_builder_state": {
            "geo_result": {"pois_found": 3},
            "brief": {"raw": "plan", "creatives": []},
            "marketing_plan": {"campaign": {"name": "X"}},
            "meta_campaign_ids": {"campaign_id": "123", "adset_ids": ["a1"], "ad_ids": []},
            "stages_complete": ["geo", "maid", "campaign", "media"],
        },
    }
    update = asyncio.run(builder_finalize(state))
    # A fresh publish ends the turn (see _route_after_publish_pipeline); the
    # builder no longer hands off to campaign_manager in the same turn.
    assert update["next_nodes"] == ["chatbot"]
    assert update["active_campaign_id"] == "123"
    assert update["just_published"] is True


def test_derive_stage_detects_media_published_via_meta_campaign_ids():
    from app.graph.nodes import derive_stage

    st = derive_stage({
        "geo_data": {"targeting_method": "deterministic", "maid_count": 100},
        "marketing_plan": {"campaign": {"name": "X"}},
        "meta_campaign_ids": {"campaign_id": "120208999"},
        "media_wizard_state": None,
    })
    assert st["media_published"] is True
    assert st["next_stage"] == "done"


def test_derive_stage_detects_media_published_via_wizards_completed():
    from app.graph.nodes import derive_stage

    st = derive_stage({
        "geo_data": {"targeting_method": "deterministic", "maid_count": 100},
        "marketing_plan": {"campaign": {"name": "X"}},
        "wizards_completed": {"geo", "maid", "campaign", "media"},
    })
    assert st["media_published"] is True


def test_route_after_publish_pipeline():
    from langgraph.graph import END

    from app.graph.graph import _route_after_publish_pipeline

    # A fresh publish ends the turn: the narration is already flushed.
    assert _route_after_publish_pipeline({
        "just_published": True,
        "meta_campaign_ids": {"campaign_id": "123"},
    }) == END
    assert _route_after_publish_pipeline({
        "meta_campaign_ids": {"campaign_id": "123"},
    }) == "chatbot"
    assert _route_after_publish_pipeline({}) == "chatbot"


def test_finalize_merges_builder_results(writer_events):
    state = {
        "campaign_builder_state": {
            "geo_result": {"pois_found": 3},
            "brief": {"raw": "plan", "creatives": []},
            "marketing_plan": {"campaign": {"name": "X"}},
            "meta_campaign_ids": {"campaign_id": "123"},
            "stages_complete": ["geo", "maid", "campaign", "media"],
        },
    }
    update = asyncio.run(builder_finalize(state))
    assert update["campaign_builder_state"] is None
    assert update["geo_data"] == {"pois_found": 3}
    assert update["campaign_brief"]["raw"] == "plan"
    assert update["marketing_plan"]["campaign"]["name"] == "X"
    assert update["meta_campaign_ids"]["campaign_id"] == "123"
    assert update["wizards_completed"] == {"geo", "maid", "campaign", "media"}


# ── conditional geo-route slots (wizard parity restore) ───────────────────────
# The wizard branches per searching type: radius scope collects a pin + ring
# instead of named locations; competitor_nearby collects the user's own store
# anchor + search radius; event_based also collects a date range. These tests
# pin the slot model to those routes.

def test_radius_scope_replaces_locations_with_pin_and_ring():
    names = [s.name for s in missing_required_slots("geo", {"location_scope": "radius"})]
    assert "locations" not in names
    assert names[:2] == ["radius_pin", "radius_km"]


def test_named_scopes_still_require_locations():
    for scope in ("granular_local", "admin_areas", "country_groups"):
        names = [s.name for s in missing_required_slots("geo", {"location_scope": scope})]
        assert "locations" in names, scope


def test_competitor_nearby_requires_anchor_confirm_then_radius():
    # The anchor is confirmed on the map BEFORE the radius is asked — a radius
    # around a mis-geocoded store is meaningless.
    filled = {
        "location_scope": "granular_local", "locations": "Montreal",
        "business_desc": "cafe", "targeting_method": "deterministic",
        "det_type": "competitor_nearby",
    }
    names = [s.name for s in missing_required_slots("geo", filled)]
    assert names == ["competitor_anchor", "competitor_anchor_confirm", "competitor_radius_km"]


def test_competitor_anchor_confirm_satisfied_once_answered():
    # skippable: key-presence marks it asked, so a bare/empty confirm payload does
    # not re-loop. Once anchor + confirm are present, only radius remains.
    filled = {
        "location_scope": "granular_local", "locations": "Montreal",
        "business_desc": "cafe", "targeting_method": "deterministic",
        "det_type": "competitor_nearby",
        "competitor_anchor": "500 Peel St, Montreal",
        "competitor_anchor_confirm": "",
    }
    names = [s.name for s in missing_required_slots("geo", filled)]
    assert names == ["competitor_radius_km"]


def test_store_anchored_angles_skip_location_scope_and_locations():
    # store_set / competitor_nearby anchor the search on the user's OWN store
    # address (collected later in the builder), so the generic scope + named-market
    # questions are not asked. det_type is seeded from extraction before the first
    # plan call, so the gate fires without any slot reordering.
    for det, next_slot in (("store_set", "store_addresses"),
                           ("competitor_nearby", "competitor_anchor")):
        names = [s.name for s in missing_required_slots(
            "geo", {"business_desc": "cafe", "det_type": det})]
        assert "location_scope" not in names, det
        assert "locations" not in names, det
        assert next_slot in names, det


def test_non_store_angles_still_require_location_scope_and_locations():
    # Guard against over-skipping: every non-store angle still needs the market.
    for det in ("ai_suggested", "category", "competitor_brand", "event_based"):
        names = [s.name for s in missing_required_slots(
            "geo", {"business_desc": "cafe", "det_type": det})]
        assert "location_scope" in names, det
        assert "locations" in names, det


def test_radius_scope_still_skips_locations():
    names = [s.name for s in missing_required_slots("geo", {"location_scope": "radius"})]
    assert "locations" not in names
    assert names[:2] == ["radius_pin", "radius_km"]


def test_slot_applies_multi_clause_not_when():
    # Nested not_when: skip if ANY clause matches; apply only when NONE match.
    s = Slot("x", "geo", "geo_collect_locations",
             not_when=(("a", "x"), ("b", "y")))
    assert slot_applies(s, {"a": "x"}) is False
    assert slot_applies(s, {"b": "y"}) is False
    assert slot_applies(s, {"a": "z", "b": "z"}) is True
    assert slot_applies(s, {}) is True
    # Flat single-clause form stays backward compatible.
    flat = Slot("x", "geo", "geo_collect_locations", not_when=("a", "x"))
    assert slot_applies(flat, {"a": "x"}) is False
    assert slot_applies(flat, {"a": "z"}) is True


def test_event_based_requires_queries_only():
    # event_queries is required; the date range is optional — Punk finds the events
    # from context and reads the real dates back from the search results.
    filled = {
        "location_scope": "granular_local", "locations": "Montreal",
        "business_desc": "cafe", "targeting_method": "deterministic",
        "det_type": "event_based",
    }
    names = [s.name for s in missing_required_slots("geo", filled)]
    assert names == ["event_queries"]


def test_geo_asks_det_type_after_locations():
    # business_desc moved to the campaign stage — no business ask fires in geo.
    # Spec order: scope → locations → search mode (det_type) → inputs.
    names = [s.name for s in missing_required_slots(
        "geo", {"location_scope": "granular_local", "locations": "Montreal"},
    )]
    assert names[0] == "det_type"
    assert "business_desc" not in names


def test_campaign_intake_is_the_only_required_campaign_slot():
    # publish_mode is the first required campaign slot regardless of mode.
    # Once express is picked, the intake form is the only OTHER required
    # slot — business/objective/budget/destination all come from its
    # submission, so no per-field slots gate before it.
    names = [s.name for s in missing_required_slots("campaign", {})]
    assert names == ["publish_mode", "campaign_intake"]
    names = [s.name for s in missing_required_slots(
        "campaign", {"publish_mode": "express"})]
    assert names == ["campaign_intake"]


def test_guide_skips_the_intake_form_entirely():
    # Guide mode has nothing else required in the campaign stage: business
    # name/what-you-sell come from the entry gate upstream (WHAT), and the
    # objective is inferred by generate_brief — plan_confirm is not required
    # (it is the stage-exit gate, asked only once the acts have run).
    names = [s.name for s in missing_required_slots(
        "campaign", {"publish_mode": "guide"})]
    assert names == []


def test_no_objective_adds_a_pixel_slot():
    # The Pixel is asked in the plan editor, so no objective — conversion or not —
    # puts a pixel interrupt between the intake and the plan.
    for obj in ("SALES", "LEADS", "TRAFFIC", "AWARENESS", "ENGAGEMENT", "APP_PROMOTION"):
        names = [s.name for s in missing_required_slots(
            "campaign", {"publish_mode": "express", "campaign_intake": "done", "objective": obj})]
        assert names == [], obj


def test_out_of_order_required_ask_is_coerced_to_next():
    # Only the scope is set → next required slot is `locations`. The planner
    # tries to jump ahead to det_type (applicable + required, but not first)
    # → coerced back to locations.
    bs = _bs(filled={"location_scope": "granular_local"})
    action, note = coerce_action(PlannerAction(kind="ask", slot="det_type"), bs, {})
    assert note and "out of order" in note
    assert action == {"kind": "ask", "slot": "locations"}


def test_in_order_required_ask_passes_through():
    # scope + locations filled → next required slot is det_type (business_desc
    # moved to the campaign stage); asking it passes through uncoerced.
    bs = _bs(filled={"location_scope": "granular_local", "locations": "Montreal"})
    action, note = coerce_action(PlannerAction(kind="ask", slot="det_type"), bs, {})
    assert note is None
    assert action == {"kind": "ask", "slot": "det_type"}


def test_every_slot_step_key_exists_in_registry():
    # builder_ask re-uses the wizard widget contract via prompts_registry —
    # a slot pointing at a missing step_key would break the frontend.
    from app.graph.prompts_registry import STEP_PROMPTS
    for slot in SLOTS.values():
        assert slot.step_key in STEP_PROMPTS, slot.name


async def _enrich_empty(*args, **kwargs):
    return {}


def _run_maid_ask(answer, extracted=None):
    """Drive builder_ask for the poi_radius_m (combined maid) slot, stubbing the
    interrupt to return ``answer`` and bypassing the radius-map enrichment. The
    free-text LLM fallback is stubbed to return ``extracted`` (None = no extraction)
    so no real model call fires."""
    bs = {"filled": {}, "stages_complete": [],
          "next_action": {"kind": "ask", "slot": "poi_radius_m"}}
    state = {"campaign_builder_state": bs, "user_info": {}, "messages": []}

    async def _fake_interrupt(*args, **kwargs):
        return answer

    async def _fake_extract(*args, **kwargs):
        return extracted

    with patch("app.graph.builder.builder_node.get_writer", return_value=lambda *_: None), \
         patch("app.graph.builder.builder_node._enrich_slot_ask", new=_enrich_empty), \
         patch("app.graph.builder.builder_node._extract_maid_settings", new=_fake_extract), \
         patch("app.graph.builder.builder_node.wizard_interrupt", side_effect=_fake_interrupt):
        update = asyncio.run(builder_ask(state))
    return update


def test_builder_ask_combined_fills_both_maid_slots():
    # New multi-stepper widget returns JSON → one interrupt fills both slots (no
    # LLM fallback needed — extracted stays None to prove the JSON path is used).
    update = _run_maid_ask('{"poi_radius_m": 250, "lookback_days": 14}')
    filled = update["campaign_builder_state"]["filled"]
    assert filled["poi_radius_m"] == "250"
    assert filled["lookback_days"] == "14"


def test_builder_ask_freetext_extracts_both_maid_slots():
    # User typed free text instead of using the widget → JSON parse empty → LLM
    # fallback returns both values → still filled in one go.
    update = _run_maid_ask(
        "make the radius 200 and look back two weeks",
        extracted=_MaidSettingsExtract(poi_radius_m=200, lookback_days=14),
    )
    filled = update["campaign_builder_state"]["filled"]
    assert filled["poi_radius_m"] == "200"
    assert filled["lookback_days"] == "14"


def test_builder_ask_single_answer_fills_only_radius():
    # Non-JSON answer where the LLM extracts only the radius (lookback not stated)
    # → JSON parse empty, fallback yields one value → only poi_radius is filled
    # (as the clean extracted integer); lookback_days stays missing and is asked
    # standalone.
    update = _run_maid_ask(
        "250 m", extracted=_MaidSettingsExtract(poi_radius_m=250, lookback_days=None)
    )
    filled = update["campaign_builder_state"]["filled"]
    assert filled["poi_radius_m"] == "250"
    assert "lookback_days" not in filled


def _run_text_ask(slot_name, answer, extracted="__RAW__"):
    """Drive builder_ask for a plain-text slot, stubbing the interrupt to return
    ``answer``. ``extracted`` stubs the slot-value LLM: "__RAW__" leaves the
    extractor unpatched-but-inert by returning the raw answer; None simulates a
    failed extraction; any str simulates a cleaned value."""
    bs = {"filled": {}, "stages_complete": [],
          "next_action": {"kind": "ask", "slot": slot_name}}
    state = {"campaign_builder_state": bs, "user_info": {}, "messages": []}

    async def _fake_interrupt(*args, **kwargs):
        return answer

    async def _fake_extract(sname, raw, writer):
        return raw if extracted == "__RAW__" else extracted

    with patch("app.graph.builder.builder_node.get_writer", return_value=lambda *_: None), \
         patch("app.graph.builder.builder_node._enrich_slot_ask", new=_enrich_empty), \
         patch("app.graph.builder.builder_node._extract_slot_value", new=_fake_extract), \
         patch("app.graph.builder.builder_node.wizard_interrupt", side_effect=_fake_interrupt):
        update = asyncio.run(builder_ask(state))
    return update


def test_builder_ask_strips_wrapping_from_text_slot():
    # Wrapped sentence → extractor returns the bare value → only that is stored.
    update = _run_text_ask("competitor_anchor", "my store is at 1340 Sainte-Catherine",
                           extracted="1340 Sainte-Catherine")
    assert update["campaign_builder_state"]["filled"]["competitor_anchor"] == "1340 Sainte-Catherine"
    assert update["user_info"]["competitor_address"] == "1340 Sainte-Catherine"


def test_builder_ask_clean_text_slot_roundtrips():
    # Already-clean value: extractor returns it unchanged → stored as-is.
    update = _run_text_ask("competitor_anchor", "1340 Sainte-Catherine",
                           extracted="1340 Sainte-Catherine")
    assert update["campaign_builder_state"]["filled"]["competitor_anchor"] == "1340 Sainte-Catherine"


def test_builder_ask_text_slot_extract_failure_falls_back_to_raw():
    # Extractor returns None (LLM failed/empty) → raw answer is kept.
    update = _run_text_ask("competitor_anchor", "1340 Sainte-Catherine", extracted=None)
    assert update["campaign_builder_state"]["filled"]["competitor_anchor"] == "1340 Sainte-Catherine"


def test_builder_ask_text_slot_skips_json_payload():
    # A widget JSON payload must NOT hit the extractor — a str extracted here would
    # prove it fired, so assert the raw JSON is what lands (extractor bypassed).
    update = _run_text_ask("competitor_anchor", '{"foo": 1}', extracted="LEAKED")
    assert update["campaign_builder_state"]["filled"]["competitor_anchor"] == '{"foo": 1}'


# ── conversational answers at option / value steps (resolve → re-ask) ────────────
# A user may TYPE at a widget instead of clicking. Each step resolves the answer
# (deterministic maps → LLM canonicalize) and RE-ASKS when unresolvable, instead
# of silently mis-picking (the old objective→AWARENESS / det_type→ai_suggested bug).


def _run_enum_ask(slot_name, answer, *, canon="__UNSET__", filled=None, unresolved=None):
    """Drive builder_ask for an option/value slot. ``canon`` stubs the LLM
    canonicalizers: '__UNSET__' leaves them unpatched (deterministic-only path —
    an accidental LLM call fails, surfacing as an unresolved re-ask); None
    simulates 'no match'; any str simulates a canonical resolution."""
    import contextlib

    bs = {"filled": dict(filled or {}), "stages_complete": [],
          "next_action": {"kind": "ask", "slot": slot_name}}
    if unresolved:
        bs["_unresolved"] = dict(unresolved)
    state = {"campaign_builder_state": bs, "user_info": {}, "messages": []}

    async def _fake_interrupt(*a, **k):
        return answer

    async def _fake_enum_canon(sname, raw, writer):
        return canon

    stack = [
        patch("app.graph.builder.builder_node.get_writer", return_value=lambda *_: None),
        patch("app.graph.builder.builder_node._enrich_slot_ask", new=_enrich_empty),
        patch("app.graph.builder.builder_node.wizard_interrupt", side_effect=_fake_interrupt),
    ]
    if canon != "__UNSET__":
        stack.append(patch("app.graph.builder.builder_node._canonicalize_enum_answer", new=_fake_enum_canon))
    with contextlib.ExitStack() as es:
        for p in stack:
            es.enter_context(p)
        return asyncio.run(builder_ask(state))


def test_det_type_conversational_resolves_via_llm():
    update = _run_enum_ask("det_type", "the crowd that hangs around my rivals",
                           canon="competitor_nearby")
    assert update["campaign_builder_state"]["filled"]["det_type"] == "competitor_nearby"


def test_unresolvable_enum_reasks_instead_of_silent_default():
    update = _run_enum_ask("det_type", "make it really good", canon=None)
    bs = update["campaign_builder_state"]
    assert "det_type" not in bs["filled"]           # NOT silently defaulted
    assert bs["_unresolved"]["det_type"] == 1
    assert bs["next_action"] is None                # slot left for the planner to re-ask


def test_unresolvable_enum_escapes_to_default_after_max_tries():
    # Two prior failed attempts already recorded → this third one escapes.
    update = _run_enum_ask("det_type", "meh", canon=None, unresolved={"det_type": 2})
    assert update["campaign_builder_state"]["filled"]["det_type"] == "ai_suggested"


def test_successful_resolve_clears_unresolved_counter():
    update = _run_enum_ask("det_type", "gyms and cafes near me", canon="category",
                           unresolved={"det_type": 1})
    bs = update["campaign_builder_state"]
    assert bs["filled"]["det_type"] == "category"
    assert "det_type" not in (bs.get("_unresolved") or {})


def test_ai_suggested_needs_no_sub_inputs():
    filled = {
        "location_scope": "granular_local", "locations": "Montreal",
        "business_desc": "cafe", "targeting_method": "deterministic",
        "det_type": "ai_suggested",
    }
    assert missing_required_slots("geo", filled) == []


# ── answer normalization (labels/ordinals → canonical keys) ───────────────────

def test_normalize_det_type_answers():
    assert _normalize_slot_answer(
        "det_type", "Target people hanging out near my competitors"
    ) == "competitor_nearby"
    assert _normalize_slot_answer("det_type", "category") == "category"
    assert _normalize_slot_answer("det_type", "gibberish") == "ai_suggested"


def test_normalize_location_scope_answers():
    assert _normalize_slot_answer(
        "location_scope", "Drop a pin and set the targeting area"
    ) == "radius"
    assert _normalize_slot_answer(
        "location_scope", "Target a specific city, Zip or address"
    ) == "granular_local"
    assert _normalize_slot_answer("location_scope", "radius") == "radius"
    # Unrecognized scope answers stay unfilled so the planner re-asks
    # (worldwide is no longer a supported scope).
    assert _normalize_slot_answer("location_scope", "worldwide") == ""
    assert _normalize_slot_answer("location_scope", "blorp") == ""


def test_unmatched_scope_answer_reasks():
    # An empty normalized scope leaves location_scope in the missing set.
    names = [s.name for s in missing_required_slots("geo", {"location_scope": ""})]
    assert "location_scope" in names


def test_normalize_radius_answers():
    assert float(_normalize_slot_answer("radius_km", "12.5")) == 12.5
    # Unit-suffixed answers keep the user's value (km), not the default.
    assert float(_normalize_slot_answer("radius_km", "12 km")) == 12.0
    assert float(_normalize_slot_answer("competitor_radius_km", "3 km")) == 3.0
    # The radius-picker widget payload "Q: ...\nA: <value> <unit>" — the value
    # is read from the answer line, not the (digit-bearing) prompt.
    assert float(_normalize_slot_answer(
        "competitor_radius_km", "Q: How far (1-50)?\nA: 2 km")) == 2.0
    assert float(_normalize_slot_answer(
        "radius_km", "Q: What radius?\nA: 8 km")) == 8.0
    # Truly empty answers still fall back to the wizard defaults (10 km / 5 km).
    assert float(_normalize_slot_answer("radius_km", "")) == 10.0
    assert float(_normalize_slot_answer("competitor_radius_km", "")) == 5.0
    # Non-geo slots pass through untouched.
    assert _normalize_slot_answer("budget", "$50/day") == "$50/day"


# The objective/website/app-URL collection all moved into the intake form; the
# intake_form module owns their parsing and validation (see test_campaign_intake).


# ── builder_act geo_discover wiring for the restored routes ───────────────────

def _act_state(filled):
    return {
        "messages": [],
        "user_info": {},
        "campaign_builder_state": _bs(
            filled=filled,
            next_action={"kind": "act", "operation": "geo_discover"},
        ),
    }


def test_geo_discover_passes_radius_pin_and_ring(writer_events):
    captured = {}

    async def fake_det(targeting_type, det_type, location_names, business_desc,
                       writer, extra_inputs, ws, state=None, target_audience=""):
        captured["targeting_type"] = targeting_type
        captured["extra"] = extra_inputs
        ws["_det_result"] = {
            "pois_found": 1,
            "targeting_type": "radius/ai_suggested",
            "targetable_pois": [{"name": "Spot", "lat": 45.5, "lng": -73.6}],
        }

    filled = {
        "location_scope": "radius", "business_desc": "cafe",
        "det_type": "ai_suggested",
        "radius_pin": '{"lat": 45.5, "lng": -73.6}', "radius_km": "12.0",
    }
    with patch("app.graph.builder.builder_node._execute_deterministic", side_effect=fake_det):
        result = asyncio.run(builder_act(_act_state(filled), {}))

    assert captured["targeting_type"] == "radius"
    assert captured["extra"]["lat"] == 45.5
    assert captured["extra"]["lng"] == -73.6
    assert captured["extra"]["radius_km"] == 12.0
    assert "geo_discover" in result["campaign_builder_state"]["ops_done"]
    # geo_discover commits the result to state["geo_data"] now (not only at
    # builder_finalize) so the narrator grounding pack is populated at the
    # poi_confirm pause that immediately follows.
    assert result["geo_data"]["pois_found"] == 1


def test_geo_discover_geocodes_competitor_anchor(writer_events):
    captured = {}

    async def fake_det(targeting_type, det_type, location_names, business_desc,
                       writer, extra_inputs, ws, state=None, target_audience=""):
        captured["det_type"] = det_type
        captured["extra"] = extra_inputs
        ws["_det_result"] = {
            "pois_found": 2,
            "targeting_type": "granular_local/competitor_nearby",
            "targetable_pois": [{"name": "Rival Cafe", "lat": 45.51, "lng": -73.61}],
        }

    async def fake_geocode(tool, args, writer=None, node_name=None):
        captured["geocode_args"] = args
        return (
            {"latitude": 45.5, "longitude": -73.6, "formatted_address": "123 Main St"},
            {"status": "success", "tool": "geocode_location"},
        )

    filled = {
        "location_scope": "granular_local", "locations": "Montreal",
        "business_desc": "cafe", "targeting_method": "deterministic",
        "det_type": "competitor_nearby",
        "competitor_anchor": "123 Main St", "competitor_radius_km": "3.0",
    }
    with patch("app.graph.builder.builder_node._execute_deterministic", side_effect=fake_det), \
         patch("app.graph.builder.builder_node.call_tool", side_effect=fake_geocode):
        result = asyncio.run(builder_act(_act_state(filled), {}))

    assert captured["det_type"] == "competitor_nearby"
    extra = captured["extra"]
    assert extra["store_address"] == "123 Main St"
    assert extra["competitor_store_lat"] == 45.5
    assert extra["competitor_store_lng"] == -73.6
    assert extra["competitor_radius_km"] == 3.0
    # The market is a soft hint (a retry/warning inside geocode_or_place), never a
    # suffix on the user's own anchor text.
    assert captured["geocode_args"]["location_name"] == "123 Main St"
    assert captured["geocode_args"]["market_hint"] == "Montreal"
    assert "geo_discover" in result["campaign_builder_state"]["ops_done"]


def test_geo_discover_business_name_anchor_populates_anchors(writer_events):
    # A business-name anchor resolves via geocode_or_place (Places fallback lives
    # inside the tool; here call_tool is stubbed to return a Places-shaped hit) →
    # competitor_anchors list is populated, not just the legacy scalars.
    captured = {}

    async def fake_det(targeting_type, det_type, location_names, business_desc,
                       writer, extra_inputs, ws, state=None, target_audience=""):
        captured["extra"] = extra_inputs
        ws["_det_result"] = {
            "pois_found": 1, "targeting_type": "granular_local/competitor_nearby",
            "targetable_pois": [{"name": "Rival", "lat": 45.51, "lng": -73.61}],
        }

    async def fake_geocode(tool, args, writer=None, node_name=None):
        # geocode_or_place-shaped business hit (is_city False, no bounds).
        return (
            {"latitude": 45.5, "longitude": -73.6, "location_name": "Shawarmaz",
             "formatted_address": "St Catherine, Montreal", "is_city": False,
             "bounds": None},
            {"status": "success", "tool": "geocode_or_place"},
        )

    filled = {
        "location_scope": "granular_local", "locations": "Montreal",
        "business_desc": "shawarma", "targeting_method": "deterministic",
        "det_type": "competitor_nearby",
        "competitor_anchor": "shawarmaz st catherine", "competitor_radius_km": "3.0",
    }
    async def fake_parse(raw):
        return [raw.strip()] if raw.strip() else []

    with patch("app.graph.builder.builder_node._execute_deterministic", side_effect=fake_det), \
         patch("app.graph.builder.builder_node.parse_store_addresses", side_effect=fake_parse), \
         patch("app.graph.builder.builder_node.call_tool", side_effect=fake_geocode):
        asyncio.run(builder_act(_act_state(filled), {}))

    anchors = captured["extra"]["competitor_anchors"]
    assert len(anchors) == 1
    assert anchors[0]["latitude"] == 45.5
    assert captured["extra"]["competitor_store_lat"] == 45.5


def test_anchor_confirm_empty_prompts_for_address():
    # When the anchor resolves to nothing (geocode + Places both miss → call_tool
    # returns (None, log)), the confirm step must NOT emit a map and must ask for a
    # full street address instead of the hollow "Are these your store locations?".
    events = []

    async def fake_miss(tool, args, writer=None, node_name=None):
        return (None, {"status": "error", "tool": "geocode_or_place"})

    async def fake_parse(raw):
        return [raw.strip()] if raw.strip() else []

    bs = {
        "filled": {"det_type": "competitor_nearby", "locations": "Montreal",
                   "competitor_anchor": "asdfqwer zzz"},
        "geo_ws": {}, "stages_complete": [],
    }
    state = {"campaign_builder_state": bs, "user_info": {}, "messages": []}
    slot = SLOTS["competitor_anchor_confirm"]
    with patch("app.graph.builder.builder_node.call_tool", side_effect=fake_miss), \
         patch("app.graph.builder.builder_node.parse_store_addresses", side_effect=fake_parse):
        overrides = asyncio.run(_enrich_slot_ask(slot, bs, state, events.append))

    assert not any(e.get("type") == "map_data" for e in events)
    assert "street address" in overrides["prompt_override"].lower()


def test_anchor_confirm_recovers_when_parser_drops_business_name():
    # parse_store_addresses (LLM) returns [] for a business name it doesn't consider
    # a street address, but geocode_or_place resolves it via Places. The confirm
    # step must NOT drop the anchor: it keeps the raw answer, geocodes it, emits the
    # map — no bogus "I couldn't pinpoint that" (the reported confuse-the-user bug).
    events = []

    async def drop_parse(raw):
        return []          # LLM decides "shawarmaz st catherine" isn't an address

    async def montreal(raw):
        return ["Montreal"]

    async def fake_hit(tool, args, writer=None, node_name=None):
        assert args["location_name"] == "shawarmaz st catherine"
        assert args["market_hint"] == "Montreal"   # soft hint, not a suffix
        return (
            {"latitude": 45.497, "longitude": -73.575, "location_name": "Shawarmaz",
             "formatted_address": "1340 Rue Sainte-Catherine Ouest, Montreal",
             "is_city": False, "bounds": None},
            {"status": "success", "tool": "geocode_or_place"},
        )

    bs = {
        "filled": {"det_type": "competitor_nearby", "locations": "Montreal",
                   "competitor_anchor": "shawarmaz st catherine"},
        "geo_ws": {}, "stages_complete": [],
    }
    state = {"campaign_builder_state": bs, "user_info": {}, "messages": []}
    slot = SLOTS["competitor_anchor_confirm"]
    with patch("app.graph.builder.builder_node.call_tool", side_effect=fake_hit), \
         patch("app.graph.builder.builder_node.parse_store_addresses", side_effect=drop_parse), \
         patch("app.graph.builder.builder_node.parse_location_names", side_effect=montreal):
        overrides = asyncio.run(_enrich_slot_ask(slot, bs, state, events.append))

    maps = [e for e in events if e.get("type") == "map_data"]
    assert len(maps) == 1
    assert maps[0]["content"]["locations"][0]["latitude"] == 45.497
    assert overrides["prompt_override"] == "Is this your business location?"


def test_poi_confirm_gets_rerun_on_edit_for_geo_fields():
    # Regression: geo_pois_confirmation's map is emitted once by geo_discover's
    # ACT phase and never re-emitted from inside the confirm loop. Without
    # rerun_on_edit, a location edit here ("just manhattan") just re-loops on
    # the stale map instead of returning so apply_pending_edits ->
    # invalidate_from("geo") can drop geo_discover from ops_done and trigger a
    # fresh run + fresh map. Every OTHER geo confirm gate (competitor_anchor_
    # confirm) already carries this wiring; poi_confirm was the one left out.
    bs = {"ops_done": ["geo_discover"], "filled": {}, "geo_ws": {}}
    state = {"campaign_builder_state": bs, "user_info": {}, "messages": []}
    slot = SLOTS["poi_confirm"]

    overrides = asyncio.run(_enrich_slot_ask(slot, bs, state, lambda ev: None))

    rerun = overrides.get("rerun_on_edit")
    assert rerun, "poi_confirm must set rerun_on_edit or edits here re-loop on a stale map"
    # Every real, classifier-nameable geo field must be covered — not just
    # location. An angle change ("also target Starbucks") mid-confirm must
    # invalidate the stale POI set exactly like a location change does.
    for field in ("location", "deterministic_subtype", "poi_types", "named_places",
                  "event_queries", "competitor_brands", "store_addresses"):
        assert field in rerun, f"{field!r} missing from poi_confirm's rerun_on_edit"


def test_poi_confirm_repeats_the_map_on_every_reask():
    # Regression: a `poi_selection` NL trim ("just the top 15") is a tier-1
    # overlay — it updates bs["geo_result"] WITHOUT rerunning geo_discover, so
    # the original map emit (inside geo_discover's act) never fires again.
    # geo_pois_confirmation was the only confirm gate with no repeat_events at
    # all — a plain reject lost the map exactly the same way. Every re-ask
    # (any reason) must carry the CURRENT geo_result's map, mirroring how
    # geo_location_confirmation/geo_store_confirmation already do this
    # (executors/geo.py) and how maid_confirm's own ad hoc flag does it here.
    det = {
        "targetable_pois": [
            {"name": "Vet A", "lat": 39.7, "lng": -104.9, "source_angle": "category"},
            {"name": "Dog Park B", "lat": 39.8, "lng": -105.0, "source_angle": "category"},
        ],
        "locations": [{"lat": 39.7, "lng": -104.9}],
        "lookback_days": "90",
    }
    bs = {
        "ops_done": ["geo_discover"], "filled": {}, "geo_ws": {},
        "geo_result": det,
    }
    state = {"campaign_builder_state": bs, "user_info": {}, "messages": []}
    slot = SLOTS["poi_confirm"]

    overrides = asyncio.run(_enrich_slot_ask(slot, bs, state, lambda ev: None))

    events = overrides.get("repeat_events")
    assert events, "poi_confirm must repeat its map so a re-ask is never a bare prompt"
    # A zero-arg callable, not a prebuilt dict — evaluated fresh at every
    # pause so a mid-loop mutation (a handoff trim_pois call) is reflected on
    # the NEXT pause instead of replaying a stale map (see wizard_helpers'
    # repeat_events docstring for why this must be lazy).
    assert callable(events[0])
    ev = events[0]()
    assert ev["type"] == "map_data"
    assert [p["name"] for p in ev["content"]["pois"]] == ["Vet A", "Dog Park B"]

    # The lambda closes over the LIVE bs dict — mutate geo_result the way a
    # handoff trim_pois call would (no rerun_on_edit exit involved) and the
    # SAME callable must reflect it on the next evaluation.
    bs["geo_result"]["targetable_pois"] = det["targetable_pois"][:1]
    ev2 = events[0]()
    assert [p["name"] for p in ev2["content"]["pois"]] == ["Vet A"]


def test_poi_confirm_no_repeat_event_before_pois_exist():
    # No geo_result yet (poi_confirm shouldn't normally be asked this early).
    # The lambda is still returned unconditionally (it's evaluated per pause,
    # not per call-setup) but must degrade to None — never an empty/bogus map
    # — when there's nothing to show yet.
    bs = {"ops_done": [], "filled": {}, "geo_ws": {}}
    state = {"campaign_builder_state": bs, "user_info": {}, "messages": []}
    slot = SLOTS["poi_confirm"]

    overrides = asyncio.run(_enrich_slot_ask(slot, bs, state, lambda ev: None))

    events = overrides.get("repeat_events")
    assert events and callable(events[0])
    assert events[0]() is None


def test_maid_confirm_gets_rerun_on_edit_for_geo_and_maid_fields():
    # Regression: maid_confirm_results's map/audience is emitted once by
    # maid_query's ACT phase and never re-emitted from inside the confirm
    # loop — same shape as poi_confirm above. Without rerun_on_edit, an edit
    # here ("also target coffee shops", "make the radius 500m", "now only
    # weekends") is narrated as applied by wizard_interrupt's edit-ack, then
    # silently discarded: the loop just re-interrupts on the stale widget
    # instead of returning to the caller, so stash_edits/apply_pending_edits/
    # invalidate_from never run and the audience never recomputes.
    bs = {"ops_done": ["geo_discover", "maid_query"], "filled": {}, "maid_ws": {}}
    state = {"campaign_builder_state": bs, "user_info": {}, "messages": []}
    slot = SLOTS["maid_confirm"]

    overrides = asyncio.run(_enrich_slot_ask(slot, bs, state, lambda ev: None))

    rerun = overrides.get("rerun_on_edit")
    assert rerun, "maid_confirm must set rerun_on_edit or edits here re-loop on a stale audience"
    # Geo-owned fields (an angle/type/location edit invalidates geo_discover
    # AND maid_query) and maid-owned fields (radius/lookback/audience_filter
    # invalidate maid_query only) must both be covered.
    for field in ("location", "deterministic_subtype", "poi_types", "named_places",
                  "event_queries", "competitor_brands", "store_addresses",
                  "poi_radius_m", "lookback_days", "audience_filter"):
        assert field in rerun, f"{field!r} missing from maid_confirm's rerun_on_edit"


def test_geo_discover_store_set_business_name_not_dropped(writer_events):
    # store_set: a user may type a store NAME, not a postal address. The LLM parser
    # returns [] for it, but the never-drop guard must keep it so it reaches the
    # executor's geocode_or_place (Places resolves the name). Assert the store
    # survives into extra_inputs["store_addresses_list"].
    captured = {}

    async def fake_det(targeting_type, det_type, location_names, business_desc,
                       writer, extra_inputs, ws, state=None, target_audience=""):
        captured["extra"] = extra_inputs
        ws["_det_result"] = {
            "pois_found": 1, "targeting_type": "granular_local/store_set",
            "targetable_pois": [{"name": "Shawarmaz", "lat": 45.5, "lng": -73.6}],
        }

    async def drop_parse(raw):
        return []          # LLM decides "Shawarmaz" isn't a street address

    filled = {
        "location_scope": "granular_local", "locations": "Montreal",
        "business_desc": "shawarma", "targeting_method": "deterministic",
        "det_type": "store_set", "store_addresses": "Shawarmaz",
    }
    with patch("app.graph.builder.builder_node._execute_deterministic", side_effect=fake_det), \
         patch("app.graph.builder.builder_node.parse_store_addresses", side_effect=drop_parse):
        asyncio.run(builder_act(_act_state(filled), {}))

    assert captured["extra"]["store_addresses_list"] == ["Shawarmaz"]


def test_geo_discover_passes_event_dates(writer_events):
    captured = {}

    async def fake_det(targeting_type, det_type, location_names, business_desc,
                       writer, extra_inputs, ws, state=None, target_audience=""):
        captured["extra"] = extra_inputs
        ws["_det_result"] = {
            "pois_found": 1,
            "targeting_type": "granular_local/event_based",
            "targetable_pois": [{"name": "Spot", "lat": 1.0, "lng": 2.0}],
        }

    filled = {
        "location_scope": "granular_local", "locations": "Montreal",
        "business_desc": "cafe", "targeting_method": "deterministic",
        "det_type": "event_based",
        "event_queries": "concerts",
        "event_date_range": "Summer 2026",
    }
    with patch("app.graph.builder.builder_node._execute_deterministic", side_effect=fake_det):
        asyncio.run(builder_act(_act_state(filled), {}))

    assert captured["extra"]["event_date_range"] == "Summer 2026"


def test_geo_discover_propagates_interrupt_not_failure(writer_events):
    # The executor raises GraphInterrupt for the geo_location_confirmation /
    # poi_confirm widgets. builder_act MUST let it bubble to the framework
    # (pausing the graph) — never swallow it into builder_act_failed, or the
    # confirmation widget collapses into a chatbot message.
    from langgraph.errors import GraphInterrupt

    async def fake_det(*a, **kw):
        raise GraphInterrupt(())

    filled = {
        "location_scope": "granular_local", "locations": "Montreal",
        "business_desc": "cafe", "targeting_method": "deterministic",
        "det_type": "ai_suggested",
    }
    with patch("app.graph.builder.builder_node._execute_deterministic", side_effect=fake_det):
        with pytest.raises(GraphInterrupt):
            asyncio.run(builder_act(_act_state(filled), {}))


def test_geo_discover_syncs_confirm_edit_even_when_it_pauses_again(writer_events):
    """A confirm-step location edit ("include aurora") that itself needs a
    disambiguation pause must not lose the edit on the next dispatch.

    ``_execute_deterministic`` stashes the merged set on
    ``ws["_locations_synced"]`` and then raises ``_GeoStepPaused`` (the added
    name still needs its own answer). Before the fix, that sync back into
    ``filled["locations"]`` only ran on the branch that finishes WITHOUT
    pausing again — so the very next geo_discover dispatch re-derived
    `location_names` from the stale pre-edit value, silently dropping the
    added location off the confirm map.
    """
    from app.graph.builder.executors.geo import _GeoStepPaused

    async def fake_det(targeting_type, det_type, location_names, business_desc,
                        writer, extra_inputs, ws, state=None, target_audience=""):
        ws["_locations_synced"] = ["Denver", "aurora"]
        raise _GeoStepPaused()

    filled = {
        "location_scope": "granular_local", "locations": "Denver",
        "business_desc": "dog gear", "targeting_method": "deterministic",
        "det_type": "category",
    }
    with patch("app.graph.builder.builder_node._execute_deterministic", side_effect=fake_det):
        result = asyncio.run(builder_act(_act_state(filled), {}))

    bs = result["campaign_builder_state"]
    assert bs["filled"]["locations"] == "Denver, aurora"
    assert result["user_info"]["location"] == "Denver, aurora"
    assert bs["geo_ws"]["_parsed_locations"]["list"] == ["Denver", "aurora"]
    assert "geo_discover" not in bs.get("ops_done", [])


def test_geo_discover_reads_synced_locations_across_a_raw_interrupt(writer_events):
    """The actual shape behind the "include aurora" bug in production: the
    edit-added name needed its OWN fresh disambiguation `interrupt()` — not
    `_GeoStepPaused` — which raises a real `GraphInterrupt` straight out of
    `_execute_deterministic` (`_apply_location_edit` → `_do_geocode`,
    executors/geo.py). The framework then discards this WHOLE node's return,
    so `filled["locations"]` is never durably updated — only the `ws` dict
    (parked by `builder/scratch.py`'s save_act_scratch/take_act_scratch across
    exactly that pause) still holds the edit, via `_locations_synced`.

    The next geo_discover dispatch must read `ws["_locations_synced"]`
    directly rather than re-deriving `location_names` from the still-stale
    `filled["locations"]` — `test_geo_discover_syncs_confirm_edit_even_when_it
    _pauses_again` above only covers the OTHER pause shape (`_GeoStepPaused`,
    where a return DOES happen and filled gets committed).
    """
    from langgraph.errors import GraphInterrupt

    filled = {
        "location_scope": "granular_local", "locations": "Denver",
        "business_desc": "dog gear", "targeting_method": "deterministic",
        "det_type": "category",
    }

    async def fake_det_pausing(targeting_type, det_type, location_names, business_desc,
                                writer, extra_inputs, ws, state=None, target_audience=""):
        ws["_locations_synced"] = ["Denver", "aurora"]
        raise GraphInterrupt(())

    with patch("app.graph.builder.builder_node._execute_deterministic", side_effect=fake_det_pausing):
        with pytest.raises(GraphInterrupt):
            asyncio.run(builder_act(_act_state(filled), {}))

    captured = {}

    async def fake_det_capture(targeting_type, det_type, location_names, business_desc,
                                writer, extra_inputs, ws, state=None, target_audience=""):
        captured["location_names"] = list(location_names)
        ws["_det_result"] = {
            "pois_found": 1,
            "targeting_type": "granular_local/category",
            "targetable_pois": [{"name": "Spot", "lat": 39.7, "lng": -104.9}],
        }

    # What `take_act_scratch` hands back on the retry: `filled["locations"]`
    # is STILL "Denver" (the framework-discard never let it change) — only
    # `geo_ws` carries the edit, exactly as the pause above left it.
    retry_state = _act_state(filled)
    retry_state["campaign_builder_state"]["geo_ws"] = {"_locations_synced": ["Denver", "aurora"]}
    with patch("app.graph.builder.builder_node._execute_deterministic", side_effect=fake_det_capture):
        asyncio.run(builder_act(retry_state, {}))

    assert captured["location_names"] == ["Denver", "aurora"]


def test_geo_discover_reads_synced_stores_across_a_raw_interrupt(writer_events):
    """Same shape as the location test above, for the store_set confirm's
    `_stores_synced` (executors/geo.py's store confirm loop is the identical
    pattern — rerun_on_edit + its own fresh-interrupt disambiguation path)."""
    from langgraph.errors import GraphInterrupt

    filled = {
        "location_scope": "granular_local", "business_desc": "cafe",
        "targeting_method": "deterministic", "det_type": "store_set",
        "store_addresses": "123 Main St",
    }

    async def fake_det_pausing(targeting_type, det_type, location_names, business_desc,
                                writer, extra_inputs, ws, state=None, target_audience=""):
        ws["_stores_synced"] = ["123 Main St", "456 Oak Ave"]
        raise GraphInterrupt(())

    with patch("app.graph.builder.builder_node._execute_deterministic", side_effect=fake_det_pausing):
        with pytest.raises(GraphInterrupt):
            asyncio.run(builder_act(_act_state(filled), {}))

    captured = {}

    async def fake_det_capture(targeting_type, det_type, location_names, business_desc,
                                writer, extra_inputs, ws, state=None, target_audience=""):
        captured["store_addresses_list"] = list(extra_inputs["store_addresses_list"])
        ws["_det_result"] = {
            "pois_found": 1,
            "targeting_type": "granular_local/store_set",
            "targetable_pois": [{"name": "Store", "lat": 39.7, "lng": -104.9}],
        }

    retry_state = _act_state(filled)
    retry_state["campaign_builder_state"]["geo_ws"] = {
        "_stores_synced": ["123 Main St", "456 Oak Ave"],
    }
    with patch("app.graph.builder.builder_node._execute_deterministic", side_effect=fake_det_capture):
        asyncio.run(builder_act(retry_state, {}))

    assert captured["store_addresses_list"] == ["123 Main St", "456 Oak Ave"]


def test_geo_discover_ignores_synced_locations_mid_replay_of_a_live_pause(writer_events):
    """The `_is_fresh_dispatch` gate on the `_locations_synced` override above
    exists to prevent a regression confirmed live in thread
    844c2185-41aa-43db-814a-69adf0ac4d61: applying that override while THIS
    call is replaying a task that is STILL mid-chain on a live GraphInterrupt
    (``save_act_scratch`` parked scratch for it — ``take_act_scratch`` returns
    a HIT) changes which name ``_do_geocode()``'s per-name loop reaches its
    OWN fresh ``interrupt()`` for FIRST, relative to the ORIGINAL (pre-pause)
    run. LangGraph matches a replayed task's ``Command(resume=...)`` history
    to ``interrupt()`` calls purely by order within the task (see
    ``_GeoStepPaused``'s docstring) — reordering them feeds an EARLIER turn's
    answer (meant for a different interrupt) into the wrong one. Live symptom:
    the disambiguate-location step's classify was fed the PRIOR turn's
    "include Aurora" text instead of the user's actual pick, because the
    override moved aurora's probe ahead of the confirm step's own interrupt.

    A live act-scratch entry (built with the real ``scratch.py``, not a bare
    dict) is exactly the signal that distinguishes this case from the
    fresh-dispatch one the tests above cover — so this uses the real
    ``save_act_scratch``/``act_stamp`` round trip instead of hand-building
    ``geo_ws``.
    """
    from app.graph.builder import scratch as _scratch

    filled = {
        "location_scope": "granular_local", "locations": "Denver",
        "business_desc": "dog gear", "targeting_method": "deterministic",
        "det_type": "category",
    }
    cfg = {"configurable": {"thread_id": "t-mid-replay"}}
    _scratch.clear()
    stamp = _scratch.act_stamp(filled)
    _scratch.save_act_scratch(
        cfg, "geo_discover", {"geo_ws": {"_locations_synced": ["Denver", "aurora"]}}, stamp,
    )

    captured = {}

    async def fake_det_capture(targeting_type, det_type, location_names, business_desc,
                                writer, extra_inputs, ws, state=None, target_audience=""):
        captured["location_names"] = list(location_names)
        ws["_det_result"] = {
            "pois_found": 1,
            "targeting_type": "granular_local/category",
            "targetable_pois": [{"name": "Spot", "lat": 39.7, "lng": -104.9}],
        }

    try:
        with patch("app.graph.builder.builder_node._execute_deterministic", side_effect=fake_det_capture):
            asyncio.run(builder_act(_act_state(filled), cfg))
    finally:
        _scratch.clear()

    # take_act_scratch popped a HIT (the parked entry above) — this call is
    # mid-replay of an active chain, so the override must NOT fire: the
    # original, still-unedited `filled["locations"]` is what the confirm
    # loop's OWN interrupt (reached first, exactly as in the pre-pause run)
    # needs to see for interrupt() ordering to stay identical across replay.
    assert captured["location_names"] == ["Denver"]


# ── campaign intake + enrich pre-act ─────────────────────────────────────────
# There is no Pixel ask anywhere: enrich_website scrapes business context only,
# and a conversion objective with no account Pixel is answered in the plan editor.

def test_intake_is_the_only_campaign_ask():
    names = [s.name for s in missing_required_slots(
        "campaign", {"publish_mode": "express"})]
    assert names == ["campaign_intake"]


def test_enrich_website_no_pixel_leaves_the_objective_alone(writer_events):
    # SALES + a scraped site with NO Pixel → no auto-switch, no ask, no slot.
    async def fake_fetch(url):
        return {"pixel_id": None, "text": "We sell coffee.", "error": None}

    async def fake_enrich(*args, **kwargs):
        class _R:
            content = '{"business_category": "Cafe", "products_services": ["coffee"]}'
        return _R(), {}

    bs = _bs(filled={"publish_mode": "express", "business_name": "Cafe X", "objective": "Sales",
                     "website_url": "https://cafex.com"},
             next_action={"kind": "act", "operation": "enrich_website"})
    state = {"messages": [], "user_info": {}, "campaign_builder_state": bs}
    with patch("app.graph.tools.fetch_website_text", side_effect=fake_fetch), \
         patch("app.graph.builder.builder_node.tracked_ainvoke", side_effect=fake_enrich):
        result = asyncio.run(builder_act(state, {}))
    out_bs = result["campaign_builder_state"]
    assert out_bs["filled"]["objective"] == "Sales"          # unchanged
    assert [s.name for s in missing_required_slots("campaign", out_bs["filled"])] == [
        "campaign_intake"]


def _pre_enrich_bs():
    # website_url is now a prereq of the enrich_website pre-act (it scrapes the
    # collected URL), so the URL must already be filled for enrich to be pending.
    return _bs(
        filled={**_GEO_FILLED, "poi_confirm": "yes", "poi_radius_m": "500",
                "lookback_days": "30", "maid_confirm": "yes",
                "business_name": "Cafe X", "objective": "Sales",
                "website_url": "https://cafex.com"},
        stages_complete=["geo", "maid"],
        # connect_meta already done so enrich_website is the pending pre-act.
        ops_done=["geo_discover", "maid_query", "connect_meta"],
    )


def test_enrich_website_pre_act_runs_before_the_brief():
    from app.graph.builder.builder_node import _next_step, _pre_act_pending
    bs = _pre_enrich_bs()
    assert _pre_act_pending(bs, "campaign", bs["filled"]) == "enrich_website"
    assert _next_step(bs, "campaign") == {"kind": "act", "operation": "enrich_website"}


def test_enrich_website_preempts_planner_ask():
    bs = _pre_enrich_bs()
    action, note = coerce_action(PlannerAction(kind="ask", slot="plan_confirm"), bs, {})
    assert note and "pre-act pending" in note
    assert action == {"kind": "act", "operation": "enrich_website"}


def test_enrich_website_never_adopts_the_sites_pixel(writer_events):
    """A Pixel on the site is not a Pixel on the ad account — it is reported to
    the user, never written as the campaign's pixel."""
    async def fake_fetch(url):
        return {"pixel_id": "998877665544", "text": "We sell coffee.", "error": None}

    async def fake_enrich(*args, **kwargs):
        class _R:
            content = '{"business_category": "Cafe", "products_services": ["coffee"]}'
        return _R(), {}

    bs = _bs(filled={"publish_mode": "express", "business_name": "Cafe X", "objective": "Sales",
                     "website_url": "https://cafex.com"},
             next_action={"kind": "act", "operation": "enrich_website"})
    state = {"messages": [], "user_info": {}, "campaign_builder_state": bs}
    with patch("app.graph.tools.fetch_website_text", side_effect=fake_fetch), \
         patch("app.graph.builder.builder_node.tracked_ainvoke", side_effect=fake_enrich):
        result = asyncio.run(builder_act(state, {}))
    out_bs = result["campaign_builder_state"]
    assert "pixel_id" not in (result.get("user_info") or {})
    assert "pixel_status" not in out_bs["filled"]
    assert "enrich_website" in out_bs["ops_done"]
    assert [s.name for s in missing_required_slots("campaign", out_bs["filled"])] == [
        "campaign_intake"]


def test_enrich_website_empty_url_is_graceful(writer_events):
    bs = _bs(filled={"publish_mode": "express", "business_name": "Cafe X", "objective": "Sales"},
             next_action={"kind": "act", "operation": "enrich_website"})
    state = {"messages": [], "user_info": {}, "campaign_builder_state": bs}
    result = asyncio.run(builder_act(state, {}))
    out_bs = result["campaign_builder_state"]
    assert out_bs["enrichment"] == {}
    assert "enrich_website" in out_bs["ops_done"]
    # empty url → no scrape → objective untouched, and still nothing to ask.
    assert out_bs["filled"]["objective"] == "Sales"
    assert [s.name for s in missing_required_slots("campaign", out_bs["filled"])] == [
        "campaign_intake"]


# ── connect_meta pixel auto-detect (Part 2) ─────────────────────────────────────

def _run_detect_pixel(pixels):
    """Run media_detect_pixel with every account-scoped Graph read stubbed —
    an unstubbed read would hit the real Graph API with the fake token."""
    from app.graph.builder.executors import media as media_exec
    state = {"user_info": {"meta_access_token": "tok", "meta_ad_account_id": "act_1"},
             "media_wizard_state": {}}

    async def _pixels(acct, tok):
        return pixels

    async def _empty_list(*a, **k):
        return []

    async def _none(*a, **k):
        return None

    async def _currency(*a, **k):
        return {}

    async def _tz(*a, **k):
        return ""

    with patch.object(media_exec, "get_writer", return_value=lambda e: None), \
         patch("app.services.meta_ads.fetch_ad_pixels", side_effect=_pixels), \
         patch("app.services.meta_ads.fetch_ad_account_timezone", side_effect=_tz), \
         patch("app.services.meta_ads.fetch_ad_account_currency", side_effect=_currency), \
         patch("app.services.meta_ads.fetch_custom_conversions", side_effect=_empty_list), \
         patch("app.services.meta_ads.list_custom_audiences", side_effect=_empty_list), \
         patch("app.services.meta_ads.fetch_ad_account_business", side_effect=_none):
        return asyncio.run(media_exec.media_detect_pixel(state))


def test_detect_pixel_single_autouses_and_verifies():
    res = _run_detect_pixel([{"id": "111222333", "name": "Main"}])
    assert res["user_info"]["pixel_status"] == "verified"
    assert res["user_info"]["pixel_id"] == "111222333"
    assert res["media_wizard_state"]["pixel_id"] == "111222333"
    # Candidates carry last_fired_time now (it drives has_warm_dataset).
    assert res["media_wizard_state"]["pixel_candidates"] == [
        {"id": "111222333", "name": "Main", "last_fired_time": ""}
    ]


def test_detect_pixel_multi_verifies_but_defers_choice():
    res = _run_detect_pixel([{"id": "111", "name": "A"}, {"id": "222", "name": "B"}])
    assert res["user_info"]["pixel_status"] == "verified"     # question still skipped
    assert "pixel_id" not in res["user_info"]                 # not auto-picked
    assert "pixel_id" not in res["media_wizard_state"]        # media_select_pixel chooses later
    assert len(res["media_wizard_state"]["pixel_candidates"]) == 2


def _run_detect_page_assets(pages, *, stored_page_id="pg_1"):
    """media_detect_page_assets with the Page + form Graph calls stubbed."""
    from app.graph.builder.executors import media as media_exec
    state = {
        "user_info": {
            "meta_access_token": "tok",
            "meta_page_id": stored_page_id,
            "website_url": "https://beanthere.example",   # skips the website read
        },
        "media_wizard_state": {},
    }

    async def _fake_pages(_tok):
        return [dict(p) for p in pages]

    async def _fake_page_tokens(_tok):
        return {p["id"]: f"ptok_{p['id']}" for p in pages}

    async def _fake_forms(page_id, _tok, *, page_token=""):
        return [{"id": f"form_{page_id}", "name": "F", "status": "ACTIVE"}]

    with patch.object(media_exec, "get_writer", return_value=lambda e: None), \
         patch("app.services.meta_ads.list_meta_pages", side_effect=_fake_pages), \
         patch("app.services.meta_ads.list_page_tokens", side_effect=_fake_page_tokens), \
         patch("app.services.meta_ads.list_lead_forms", side_effect=_fake_forms):
        return asyncio.run(media_exec.media_detect_page_assets(state))


_TWO_PAGES = [
    {"id": "pg_1", "name": "Bean There", "instagram": {"id": "ig_77", "username": "bt"}},
    {"id": "pg_2", "name": "Roasters", "instagram": None},
]


def test_detect_page_assets_lists_every_page_with_its_forms():
    ws = _run_detect_page_assets(_TWO_PAGES)["media_wizard_state"]
    assert [p["id"] for p in ws["page_candidates"]] == ["pg_1", "pg_2"]
    # Forms are fetched per Page, so switching Page in the editor does not leave
    # the Instant form dropdown showing another Page's forms.
    assert ws["page_candidates"][1]["lead_forms"] == [
        {"id": "form_pg_2", "name": "F", "status": "ACTIVE"}
    ]
    # The stored Page stays the default, and brings its Instagram identity.
    assert ws["page_id"] == "pg_1"
    assert ws["instagram_user_id"] == "ig_77"
    assert ws["lead_form_candidates"] == [{"id": "form_pg_1", "name": "F", "status": "ACTIVE"}]


def test_detect_page_assets_replaces_a_page_the_token_can_no_longer_see():
    """Publishing against a Page the token lost access to fails at Meta; any Page
    it can still see is a better default."""
    res = _run_detect_page_assets(_TWO_PAGES, stored_page_id="pg_gone")
    assert res["media_wizard_state"]["page_id"] == "pg_1"
    assert res["user_info"]["meta_page_id"] == "pg_1"


def test_detect_pixel_none_leaves_status_unset():
    res = _run_detect_pixel([])
    # No pixel status/id, and an empty candidate list — which is what the plan
    # editor's pixel picker renders as "No pixel found". user_info is still
    # patched: has_warm_dataset=False steers the brief off conversion goals.
    assert "pixel_status" not in res["user_info"]
    assert "pixel_id" not in res["user_info"]
    assert res["user_info"]["has_warm_dataset"] is False
    assert res["media_wizard_state"]["pixel_candidates"] == []


def test_no_account_pixel_still_asks_nothing():
    """SALES with no Pixel signal anywhere: the campaign stage has nothing left
    to ask — the pixel is the plan editor's question."""
    base = {**_GEO_FILLED, "poi_confirm": "yes", "poi_radius_m": "500",
            "lookback_days": "30", "maid_confirm": "yes",
            "publish_mode": "express", "campaign_intake": "done",
            "business_name": "X", "business_desc": "c", "objective": "sales",
            "website_url": "https://x.com"}
    assert missing_required_slots("campaign", base) == []


def test_act_user_exit_routes_to_chatbot(writer_events):
    # A forced wizard exit inside an act's interrupt must route to chatbot
    # (wizard_failure=user_exit), not report a false builder_act_failed.
    from app.graph.wizard_exit import WizardExitRequested

    async def fake_det(*a, **kw):
        raise WizardExitRequested()

    filled = {
        "location_scope": "granular_local", "locations": "Montreal",
        "business_desc": "cafe", "targeting_method": "deterministic",
        "det_type": "ai_suggested",
    }
    with patch("app.graph.builder.builder_node._execute_deterministic", side_effect=fake_det):
        result = asyncio.run(builder_act(_act_state(filled), {}))
    assert result["wizard_failure"] == "user_exit"
    assert result["next_nodes"] == ["chatbot"]
    # CONTRACT CHANGE: this used to assert `is None`. Discarding the scratch on a
    # user exit destroyed every answered slot, the discovered POIs, the audience
    # and the plan — punishing a confused user with total data loss. The exit now
    # keeps the build and only clears next_action, so "continue" resumes it.
    kept = result["campaign_builder_state"]
    assert kept is not None
    assert kept["filled"]["locations"] == "Montreal"
    assert kept["next_action"] is None


def test_publish_failure_is_recoverable_and_retries(writer_events):
    """A recoverable publish error does not fail the wizard — publish never reached
    _mark_op_done, so it re-runs (the ledger resumes what already succeeded)."""

    async def fake_publish(*args, **kwargs):
        raise MetaPublishError("bad creative", step="creative_resolution")

    bs = _campaign_bs(
        ops_done=["geo_discover", "maid_query", "enrich_website", "generate_brief",
                  "generate_meta_json", "resolve_meta"],
    )
    bs["filled"]["plan_confirm"] = _PLAN_APPROVE
    bs["marketing_plan"] = _valid_spec()
    bs["next_action"] = {"kind": "act", "operation": "publish"}
    state = {
        "messages": [],
        "user_info": {"meta_access_token": "tok", "meta_ad_account_id": "act_1"},
        "campaign_builder_state": bs,
    }
    with patch("app.graph.builder.builder_node.publish_campaign_to_meta", side_effect=fake_publish), \
         patch("app.graph.builder.builder_node.ad_account_is_paid", return_value=True), \
         patch("app.graph.builder.builder_node.wizard_milestone_narrate", return_value={}):
        result = asyncio.run(builder_act(state, {}))
    assert "wizard_failure" not in result
    # publish did not complete → not marked done → it will be retried.
    assert "publish" not in result["campaign_builder_state"]["ops_done"]


def test_builder_act_publish_after_confirm(writer_events):
    meta_ids = {
        "campaign_id": "camp_999",
        "adset_ids": ["as_1"],
        "ad_ids": ["ad_1"],
    }

    async def fake_publish(*args, **kwargs):
        return meta_ids

    bs = _campaign_bs(
        ops_done=["geo_discover", "maid_query", "enrich_website", "generate_brief",
                  "generate_meta_json", "resolve_meta"],
    )
    bs["filled"]["plan_confirm"] = _PLAN_APPROVE
    bs["marketing_plan"] = {"campaign": {"name": "Test", "objective": "AWARENESS"}, "adsets": [{"name": "A"}]}
    bs["brief"] = {"creatives": []}
    bs["media_ws"] = {"promoted_object": None}
    bs["next_action"] = {"kind": "act", "operation": "publish"}
    state = {
        "messages": [],
        "user_info": {
            "meta_access_token": "tok",
            "meta_ad_account_id": "act_123",
            "business_name": "Test Biz",
        },
        "campaign_builder_state": bs,
        "user_id": "user-1",
    }
    with patch("app.graph.builder.builder_node.publish_campaign_to_meta", side_effect=fake_publish), \
         patch("app.graph.builder.builder_node.ad_account_is_paid", return_value=True), \
         patch("app.graph.builder.builder_node.wizard_milestone_narrate", return_value={}):
        result = asyncio.run(builder_act(state, {}))
    assert result["campaign_builder_state"]["meta_campaign_ids"] == meta_ids
    assert result["active_campaign_id"] == "camp_999"
    assert result["just_published"] is True
    assert "publish" in result["campaign_builder_state"]["ops_done"]


# ── campaign intake form (ONE dynamic form, JSON-submitted) ───────────────────
# The intake form collects business / objective / duration / budget / destination
# in a single interrupt. builder_ask parses the JSON submission, validates it, and
# writes the individual filled/user_info keys. Detailed intake schema + validation
# coverage lives in test_campaign_intake; here we cover the builder_ask wiring.

from app.graph.builder.builder_node import _extract_budget_amount


def _run_intake_ask(values, filled_extra=None, user_info=None):
    """Drive builder_ask through the intake-form path with a JSON submission."""
    bs = {"filled": {**(filled_extra or {})}, "stages_complete": [],
          "next_action": {"kind": "ask", "slot": "campaign_intake"}}
    state = {"campaign_builder_state": bs, "user_info": user_info or {}, "messages": []}

    async def _fake_interrupt(*args, **kwargs):
        return json.dumps({"values": values})

    async def _fake_budget(*args, **kwargs):
        return (["Recommended: $75/day"], "daily")

    with patch("app.graph.builder.builder_node.get_writer", return_value=lambda *_: None), \
         patch("app.graph.builder.executors.campaign.build_budget_options", new=_fake_budget), \
         patch("app.graph.builder.builder_node.wizard_interrupt", side_effect=_fake_interrupt):
        return asyncio.run(builder_ask(state))


def test_intake_fills_campaign_slots_and_user_info():
    # campaign_intake is express-only now (guide walks straight from
    # publish_mode to the plan editor — see slots.py), so a submission always
    # carries the budget this form is the only chance to set.
    update = _run_intake_ask({
        "business_name": "Brew & Co", "business_context": "best beans in town",
        "objective": "TRAFFIC", "budget_amount": 7500,
    })
    filled = update["campaign_builder_state"]["filled"]
    assert filled["campaign_intake"] == "done"
    assert filled["objective"] == "TRAFFIC"
    assert filled["business_name"] == "Brew & Co"
    # The website came off the connected Page at connect_meta, so intake must not
    # touch the key — writing "" would overwrite it and block enrich_website.
    assert "website_url" not in filled
    ui = update["user_info"]
    assert ui["business_name"] == "Brew & Co"
    assert ui["product_offer"] == "best beans in town"
    assert ui["campaign_objective"] == "TRAFFIC"
    assert ui["budget"] == "$75/day"
    assert "campaign_intake" not in update["campaign_builder_state"]  # advances


def test_intake_app_objective_writes_store_urls():
    update = _run_intake_ask({
        "business_name": "Fit App", "business_context": "workout tracker",
        "objective": "OUTCOME_APP_PROMOTION",
        "app_store_url": "apps.apple.com/app/fit", "budget_amount": 7500,
    })
    filled = update["campaign_builder_state"]["filled"]
    assert filled["objective"] == "APP_PROMOTION"
    assert filled["app_store_url"] == "https://apps.apple.com/app/fit"
    assert update["user_info"]["app_store_url"] == "https://apps.apple.com/app/fit"


def test_intake_validation_error_reasks_with_errors():
    # Missing business name + missing objective → slot stays unfilled and the
    # errors are stashed for the re-emitted form.
    update = _run_intake_ask({"business_context": "coffee"})
    bs = update["campaign_builder_state"]
    assert "campaign_intake" not in bs["filled"]
    assert "business_name" in bs["intake_errors"]
    assert bs["next_action"] is None


def test_intake_non_json_reply_is_a_form_error():
    bs = {"filled": {}, "stages_complete": [],
          "next_action": {"kind": "ask", "slot": "campaign_intake"}}
    state = {"campaign_builder_state": bs, "user_info": {}, "messages": []}

    async def _fake_interrupt(*a, **k):
        return "I want more sales"

    async def _fake_budget(*a, **k):
        return (["Recommended: $75/day"], "daily")

    with patch("app.graph.builder.builder_node.get_writer", return_value=lambda *_: None), \
         patch("app.graph.builder.executors.campaign.build_budget_options", new=_fake_budget), \
         patch("app.graph.builder.builder_node.wizard_interrupt", side_effect=_fake_interrupt):
        update = asyncio.run(builder_ask(state))
    assert "__root__" in update["campaign_builder_state"]["intake_errors"]


# ── the two-phase express editor: the intake ask is now campaign_plan_editor ──
# The intake form used to be its own action_type (campaign_intake_form),
# rendered on a separate screen before the plan editor existed. It now renders
# AS the Campaign pane of that same editor (phase: "intake", no spec yet) —
# see CampaignEditor.tsx and builder_node's campaign_intake ask branch.


def test_intake_ask_envelope_is_the_plan_editor_in_its_intake_phase():
    bs = {"filled": {"publish_mode": "express"}, "media_ws": {}, "stages_complete": []}
    state = {"campaign_builder_state": bs, "user_info": {}, "messages": []}
    slot = SLOTS["campaign_intake"]

    async def _fake_prefill(*a, **k):
        return (None, "")

    with patch("app.graph.builder.builder_node._intake_budget_prefill", side_effect=_fake_prefill):
        overrides = asyncio.run(_enrich_slot_ask(slot, bs, state, lambda ev: None))

    assert overrides["action_type_override"] == "campaign_plan_editor"
    extra = overrides["extra"]
    assert extra["phase"] == "intake"
    assert extra["publish_mode"] == "express"
    assert extra["locks"] == {"geo": True, "audience": True, "campaign": True, "adset": True}
    assert "form_schema" in extra
    # No spec/catalog — this is the whole point: nothing to draw a tree from
    # before the intake answers exist.
    assert "spec" not in extra
    assert "catalog" not in extra


def test_extract_budget_amount_from_verbose_label():
    assert _extract_budget_amount("Recommended: $280/day — reaches ~140,000") == "$280/day"
    assert _extract_budget_amount("Aggressive: $1,050/day") == "$1,050/day"
    assert _extract_budget_amount("$75 per day") == "$75/day"
    assert _extract_budget_amount("$50") == "$50/day"
    assert _extract_budget_amount("no dollar here") == ""


# ── maid ask: don't re-ask a lookback the user gave earlier ──────────────────────
# When lookback_days is prefilled, the poi_radius_m ask must use the radius-only
# stepper (maid_collect_poi_radius) instead of the combined maid_collect_settings
# widget, so the known lookback isn't re-shown.

def _run_maid_radius_ask(filled_extra=None, answer="250", slot="poi_radius_m", extracted=None):
    """Drive builder_ask for a maid tuning slot, capturing the step_key passed to
    wizard_interrupt. The radius-picker map emit is short-circuited via the maid_ws
    guard. ``answer`` is the resume value (a plain number, a JSON payload, or prose);
    ``extracted`` is the _MaidSettingsExtract the natural-language extractor would
    return for a prose answer (None simulates no LLM hit)."""
    from app.graph.builder.builder_node import _MaidSettingsExtract  # noqa: F401
    captured: dict = {}
    bs = {"filled": {**(filled_extra or {})},
          "maid_ws": {"_poi_radius_map_emitted": True},
          "next_action": {"kind": "ask", "slot": slot}}
    state = {"campaign_builder_state": bs, "user_info": {}, "messages": []}

    async def _fake_interrupt(*args, **kwargs):
        captured["step_key"] = kwargs.get("step_key")
        return answer

    async def _fake_maid_extract(text, writer):
        return extracted

    with patch("app.graph.builder.builder_node.get_writer", return_value=lambda *_: None), \
         patch("app.graph.builder.builder_node._extract_maid_settings", new=_fake_maid_extract), \
         patch("app.graph.builder.builder_node.wizard_interrupt", side_effect=_fake_interrupt):
        update = asyncio.run(builder_ask(state))
    return captured, update


def test_maid_radius_only_when_lookback_prefilled():
    captured, update = _run_maid_radius_ask(filled_extra={"lookback_days": "7"})
    # radius-only stepper, not the combined radius+lookback widget
    assert captured["step_key"] == "maid_collect_poi_radius"
    filled = update["campaign_builder_state"]["filled"]
    assert filled["poi_radius_m"] == "250"
    assert filled["lookback_days"] == "7"          # prefilled value preserved


def test_maid_combined_widget_when_lookback_missing():
    # Regression guard: with no prefilled lookback, the combined widget is used.
    captured, _ = _run_maid_radius_ask(filled_extra={})
    assert captured["step_key"] == "maid_collect_settings"


# ── never-silently-seeded values still show as the widget's starting position ──

def _run_maid_ask_capturing_extra(user_info, filled_extra=None, slot="poi_radius_m", answer=None):
    """Like _run_maid_radius_ask but also captures the `extra` kwarg
    wizard_interrupt received, and lets the caller supply user_info (the
    never-silently-filled extraction value confirm_prefill keeps out of
    `filled`)."""
    captured: dict = {}
    bs = {"filled": {**(filled_extra or {})},
          "maid_ws": {"_poi_radius_map_emitted": True},
          "next_action": {"kind": "ask", "slot": slot}}
    state = {"campaign_builder_state": bs, "user_info": user_info, "messages": []}

    async def _fake_interrupt(*args, **kwargs):
        captured["extra"] = kwargs.get("extra")
        captured["step_key"] = kwargs.get("step_key")
        return answer or "250"

    with patch("app.graph.builder.builder_node.get_writer", return_value=lambda *_: None), \
         patch("app.graph.builder.builder_node.wizard_interrupt", side_effect=_fake_interrupt):
        asyncio.run(builder_ask(state))
    return captured


def test_combined_ask_seeds_steppers_from_extraction_guess():
    """A guessed value the seed loop refused to silently pre-answer still
    shows as the widget's starting position — the user sees 250/30, not the
    registry defaults 100/7, and can accept with one click."""
    captured = _run_maid_ask_capturing_extra(
        {"poi_radius_m": 250, "lookback_days": 30},
        answer='{"poi_radius_m": 250, "lookback_days": 30}',
    )
    assert captured["step_key"] == "maid_collect_settings"
    steppers = captured["extra"]["steppers"]
    assert next(s for s in steppers if s["key"] == "poi_radius_m")["default"] == 250
    assert next(s for s in steppers if s["key"] == "lookback_days")["default"] == 30


def test_seeded_stepper_default_clamps_into_widget_range():
    """An extraction guess of 2000 m must not land outside the 1-500 control."""
    captured = _run_maid_ask_capturing_extra({"poi_radius_m": 2000}, answer="500")
    steppers = captured["extra"]["steppers"]
    assert next(s for s in steppers if s["key"] == "poi_radius_m")["default"] == 500


def test_radius_only_ask_seeds_its_stepper_default_too():
    captured = _run_maid_ask_capturing_extra(
        {"poi_radius_m": 250}, filled_extra={"lookback_days": "7"}, answer="250",
    )
    assert captured["step_key"] == "maid_collect_poi_radius"
    assert captured["extra"]["stepper"]["default"] == 250


def test_lookback_only_ask_seeds_its_stepper_default_too():
    captured = _run_maid_ask_capturing_extra(
        {"lookback_days": 30}, filled_extra={"poi_radius_m": "100"},
        slot="lookback_days", answer="30",
    )
    assert captured["extra"]["stepper"]["default"] == 30
    # Registry default (7) must not silently win when a real value is known.
    assert captured["extra"]["stepper"]["default"] != 7


# ── radius-only write must NEVER clobber a known lookback (any answer format) ─────

def test_radius_only_preserves_lookback_json():
    # Widget/client sends JSON that (wrongly) still carries a lookback → radius-only
    # mode writes ONLY the radius; the prefilled lookback survives.
    _, update = _run_maid_radius_ask(
        filled_extra={"lookback_days": "30"},
        answer='{"poi_radius_m": 100, "lookback_days": 7}',
    )
    filled = update["campaign_builder_state"]["filled"]
    assert filled["poi_radius_m"] == "100"
    assert filled["lookback_days"] == "30"          # NOT clobbered to 7


def test_radius_only_preserves_lookback_prose():
    # Human/widget prose "Radius selected 100m and Lookback days: 7" → the NL
    # extractor would return both, but radius-only mode ignores the lookback.
    from app.graph.builder.builder_node import _MaidSettingsExtract
    _, update = _run_maid_radius_ask(
        filled_extra={"lookback_days": "30"},
        answer="Radius selected 100m and Lookback days: 7",
        extracted=_MaidSettingsExtract(poi_radius_m=100, lookback_days=7),
    )
    filled = update["campaign_builder_state"]["filled"]
    assert filled["poi_radius_m"] == "100"
    assert filled["lookback_days"] == "30"          # NOT clobbered


def test_radius_only_preserves_lookback_freetext():
    from app.graph.builder.builder_node import _MaidSettingsExtract
    _, update = _run_maid_radius_ask(
        filled_extra={"lookback_days": "30"},
        answer="keep it tight, 100 m",
        extracted=_MaidSettingsExtract(poi_radius_m=100, lookback_days=None),
    )
    filled = update["campaign_builder_state"]["filled"]
    assert filled["poi_radius_m"] == "100"
    assert filled["lookback_days"] == "30"


# ── reverse case: radius given, lookback missing → ask lookback standalone ────────

def test_lookback_standalone_step_when_radius_prefilled():
    captured, _ = _run_maid_radius_ask(
        filled_extra={"poi_radius_m": "100"}, slot="lookback_days", answer="14",
    )
    assert captured["step_key"] == "maid_collect_lookback"


def test_spec_contract_backend_matches_frontend_messages():
    # Locks the backend against the messages MAID_TUNING_WIDGET_SPEC.md tells the
    # frontend to send: human "Q: … A: …" prose carrying ONLY the collected value(s).
    from app.graph.builder.builder_node import _MaidSettingsExtract

    # Radius-only ask (lookback already known = 7): FE sends only the radius.
    _, up = _run_maid_radius_ask(
        filled_extra={"lookback_days": "7"},
        answer="Q: Set the ring around each spot\nA: Radius selected 100m",
        extracted=_MaidSettingsExtract(poi_radius_m=100, lookback_days=None),
    )
    f = up["campaign_builder_state"]["filled"]
    assert f["poi_radius_m"] == "100" and f["lookback_days"] == "7"

    # Lookback-only ask (radius already known = 100): FE sends only the window.
    _, up = _run_maid_radius_ask(
        filled_extra={"poi_radius_m": "100"}, slot="lookback_days",
        answer="Q: How far back to count visits\nA: Lookback days: 30",
        extracted=_MaidSettingsExtract(poi_radius_m=None, lookback_days=30),
    )
    f = up["campaign_builder_state"]["filled"]
    assert f["lookback_days"] == "30" and f["poi_radius_m"] == "100"

    # Combined ask (neither known): FE sends both.
    _, up = _run_maid_radius_ask(
        filled_extra={},
        answer="Q: …\nA: Radius selected 100m and Lookback days: 30",
        extracted=_MaidSettingsExtract(poi_radius_m=100, lookback_days=30),
    )
    f = up["campaign_builder_state"]["filled"]
    assert f["poi_radius_m"] == "100" and f["lookback_days"] == "30"


def test_lookback_ask_emits_poi_map_with_known_radius():
    # Radius known, lookback missing → the lookback ask emits the POI map so the
    # frontend renders (ring drawn at the known radius, display-only).
    events: list[dict] = []
    bs = {"filled": {"poi_radius_m": "100"},
          "maid_ws": {},
          "next_action": {"kind": "ask", "slot": "lookback_days"}}
    state = {"campaign_builder_state": bs, "user_info": {}, "messages": []}

    def _writer(ev):
        events.append(ev)

    async def _fake_interrupt(*args, **kwargs):
        return "14"

    async def _fake_maid_extract(text, writer):
        return None

    with patch("app.graph.builder.builder_node.get_writer", return_value=_writer), \
         patch("app.graph.builder.builder_node._extract_maid_settings", new=_fake_maid_extract), \
         patch("app.graph.builder.builder_node.wizard_interrupt", side_effect=_fake_interrupt):
        asyncio.run(builder_ask(state))

    maps = [e["content"] for e in events
            if e.get("type") == "map_data"
            and e["content"].get("action_type") == "poi_radius_picker"]
    assert maps, "expected a poi_radius_picker map_data for the lookback ask"
    assert maps[0]["prefill_radius_m"] == 100


def test_lookback_standalone_parses_all_formats():
    from app.graph.builder.builder_node import _MaidSettingsExtract
    # plain number (generic write), JSON, and human text all yield 14; radius kept.
    for answer, extracted in (
        ("14", None),
        ('{"lookback_days": 14}', None),
        ("past two weeks", _MaidSettingsExtract(poi_radius_m=None, lookback_days=14)),
    ):
        _, update = _run_maid_radius_ask(
            filled_extra={"poi_radius_m": "100"}, slot="lookback_days",
            answer=answer, extracted=extracted,
        )
        filled = update["campaign_builder_state"]["filled"]
        assert filled["lookback_days"] == "14", f"answer={answer!r}"
        assert filled["poi_radius_m"] == "100", f"answer={answer!r}"


# ── event_based: dates drive the window; don't ask lookback or event date range ──

def test_lookback_not_asked_for_event_based():
    # event_based derives its window from the event dates → lookback isn't asked.
    ev = {s.name for s in missing_required_slots("maid", {"det_type": "event_based"})}
    assert "lookback_days" not in ev
    # ...but a normal angle still collects it.
    non_ev = {s.name for s in missing_required_slots("maid", {"det_type": "category"})}
    assert "lookback_days" in non_ev


def test_maid_radius_only_for_event_based():
    # event_based → radius-only stepper (lookback excluded), not the combined widget.
    captured, _ = _run_maid_radius_ask(filled_extra={"det_type": "event_based"})
    assert captured["step_key"] == "maid_collect_poi_radius"


def test_event_date_range_never_required():
    # The event date range is optional — Punk searches from context. Never asked.
    ev = {s.name for s in missing_required_slots("geo", {"det_type": "event_based"})}
    assert "event_date_range" not in ev
    assert "event_queries" in ev          # the queries themselves are still required


# ── the pixel is a plan-editor field, not a slot ──────────────────────────────

def test_no_pixel_slot_exists():
    """The pixel ask (and its skip→Traffic degrade) is gone: the pixel is one
    field of the campaign, edited where every other field is."""
    assert "pixel_status" not in SLOTS
    from app.graph.prompts_registry import STEP_PROMPTS
    assert "campaign_collect_pixel_id" not in STEP_PROMPTS


def test_campaign_sequence_intake_first_then_plan_gate():
    # connect_meta (empty-prereq pre-act) fires first — the OAuth step runs
    # before any campaign question.
    assert _next_step(_bs(filled={}), "campaign") == {"kind": "act", "operation": "connect_meta"}
    # Once Meta is connected, publish_mode is the first required campaign ask —
    # it precedes campaign_intake in declaration order and decides whether that
    # form is even asked (skipped for guide/self, see slots.py).
    assert _next_step(_bs(filled={}, ops_done=["connect_meta"]), "campaign") == {
        "kind": "ask", "slot": "publish_mode"}
    # Express picked → the intake form is next.
    assert _next_step(
        _bs(filled={"publish_mode": "express"}, ops_done=["connect_meta"]), "campaign",
    ) == {"kind": "ask", "slot": "campaign_intake"}
    # Guide picked → nothing left to ask; straight to the acts (generate_brief
    # infers the objective, generate_meta_json/plan_confirm don't gate on it).
    assert _next_step(
        _bs(filled={"publish_mode": "guide"}, ops_done=["connect_meta"]), "campaign",
    ) == {"kind": "act", "operation": "generate_brief"}
    # Intake done, no acts yet → generate_brief.
    bs = _bs(filled={"publish_mode": "express", "campaign_intake": "done", "objective": "TRAFFIC",
                     "business_name": "X", "website_url": "https://x.com"},
             ops_done=["geo_discover", "maid_query", "connect_meta", "enrich_website"])
    assert _next_step(bs, "campaign") == {"kind": "act", "operation": "generate_brief"}


# ── geo scope backfill: named location must not re-ask the scope question ────────

def test_looks_like_admin_or_country():
    assert _looks_like_admin_or_country("Texas")
    assert _looks_like_admin_or_country("Quebec")
    assert _looks_like_admin_or_country("USA")
    assert _looks_like_admin_or_country("united states")
    assert _looks_like_admin_or_country("Austin, Texas")   # tail token matches
    assert not _looks_like_admin_or_country("Los Angeles")
    assert not _looks_like_admin_or_country("New York")
    assert not _looks_like_admin_or_country("")


def test_backfill_scope_defaults_granular_for_named_city():
    filled: dict = {}
    _backfill_location_scope(filled, {"location": ["New York"]})
    assert filled["location_scope"] == "granular_local"
    # string (non-list) location also works
    filled2: dict = {}
    _backfill_location_scope(filled2, {"location": "Los Angeles"})
    assert filled2["location_scope"] == "granular_local"


def test_backfill_scope_skips_state_or_country():
    filled: dict = {}
    _backfill_location_scope(filled, {"location": ["Texas"]})
    assert "location_scope" not in filled


def test_backfill_scope_noop_when_scope_present_or_no_location():
    # existing scope is never overwritten
    filled = {"location_scope": "radius"}
    _backfill_location_scope(filled, {"location": ["New York"]})
    assert filled["location_scope"] == "radius"
    # no location → nothing to infer from
    filled2: dict = {}
    _backfill_location_scope(filled2, {})
    assert "location_scope" not in filled2


# ── maid_retry_pending: a failed extraction is never a confirmed one ─────────
# thread a10b211a: a too-large/budget/etc. refusal used to leave maid_query
# looking "done" (zero-count), so the bare permission gate at maid_confirm
# closed the maid stage on a plain "yes" with no audience and no way back.

def test_a_pending_maid_retry_asks_the_gate_instead_of_re_acting():
    """maid_query left OUT of ops_done (builder_act's early return on
    failure) plus maid_retry_pending set must not loop back into re-running
    the act — _next_step routes to the maid_confirm ask instead."""
    bs = _bs(
        filled={"poi_radius_m": "100", "lookback_days": "7"},
        stages_complete=[],
        ops_done=["geo_discover"],
        maid_retry_pending={"kind": "budget"},
        maid_ws={"poi_radius_m": 100, "lookback_days": 7},
    )
    assert _next_step(bs, "maid") == {"kind": "ask", "slot": "maid_confirm"}


def test_maid_confirm_asks_a_retry_question_not_a_bare_permission():
    from app.graph.builder.slots import SLOTS

    bs = _bs(maid_retry_pending={"kind": "budget"})
    overrides = asyncio.run(_enrich_slot_ask(SLOTS["maid_confirm"], bs, {}, lambda _e: None))

    assert overrides["action_type_override"] == "option_selection"
    assert overrides["options_override"] == ["Retry now", "Continue without a visitor audience"]
    assert "budget" in overrides["prompt_override"].lower()


def test_ip_not_allowlisted_offers_no_retry_option():
    """A configuration problem, not a transient one — retrying cannot fix it."""
    from app.graph.builder.slots import SLOTS

    bs = _bs(maid_retry_pending={"kind": "ip_not_allowlisted"})
    overrides = asyncio.run(_enrich_slot_ask(SLOTS["maid_confirm"], bs, {}, lambda _e: None))

    assert overrides["options_override"] == ["Continue without a visitor audience"]


def test_a_bare_yes_resolves_to_retry_not_confirmation():
    """The exact a10b211a fix: with maid_retry_pending set, "yes" must NOT
    satisfy the plain confirmation membership check — it must resolve to the
    first (recommended) retry option, dropping maid_query from ops_done so
    _next_step re-runs it."""
    bs = _bs(
        filled={"maid_confirm": "yes"},
        ops_done=["geo_discover", "maid_query"],
        maid_retry_pending={"kind": "timeout"},
    )
    note = asyncio.run(_apply_confirm_semantics(bs, {}))

    assert note == "retrying the audience query"
    assert bs.get("maid_retry_pending") is None
    assert "maid_query" not in bs["ops_done"]
    assert "maid_confirm" not in bs["filled"]


def test_continue_without_option_opts_out_and_closes_the_gate():
    bs = _bs(
        filled={"maid_confirm": "Continue without a visitor audience"},
        ops_done=["geo_discover"],
        maid_retry_pending={"kind": "budget"},
        geo_result={},
    )
    note = asyncio.run(_apply_confirm_semantics(bs, {}))

    assert "continuing without" in note
    assert bs.get("maid_retry_pending") is None
    assert "maid_query" in bs["ops_done"]
    assert bs["geo_result"]["maid_opted_out"] is True


# ── _self_referential_exclusion_needs_store: the "exclude my store" repair ──
# gate. "target pilates+volleyball, exclude anyone who's been to my store"
# resolves `exclude_groups=["my store"]` to nothing when store_set was never
# activated — this decides whether builder_act's maid_query repair path
# should activate it and ask for the address, instead of reporting a dead
# "not found" and shipping the audience unfiltered.

def test_self_referential_exclusion_without_a_store_address_needs_repair():
    assert _self_referential_exclusion_needs_store(
        det_type="category", store_addresses="",
        unresolved_exclude_groups=["my store"],
    ) is True


def test_no_repair_once_store_set_is_already_active():
    """store_set already active but the label is STILL unresolved means the
    store's query failed or it was removed at the confirm gate — a louder
    failure `_assert_groups_fetched` already raises on, not this repair."""
    assert _self_referential_exclusion_needs_store(
        det_type="category,store_set", store_addresses="",
        unresolved_exclude_groups=["my store"],
    ) is False


def test_no_repair_once_an_address_is_already_on_file():
    assert _self_referential_exclusion_needs_store(
        det_type="category", store_addresses="123 Main St",
        unresolved_exclude_groups=["my store"],
    ) is False


def test_no_repair_for_a_non_self_referential_unresolved_label():
    """A missing THIRD-PARTY exclude group (e.g. "SneakerCon") is a genuinely
    missing label, not a store address gap — no store_set to activate."""
    assert _self_referential_exclusion_needs_store(
        det_type="category", store_addresses="",
        unresolved_exclude_groups=["SneakerCon"],
    ) is False


def test_no_repair_with_nothing_unresolved():
    assert _self_referential_exclusion_needs_store(
        det_type="category", store_addresses="", unresolved_exclude_groups=[],
    ) is False
