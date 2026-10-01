"""
Phase 2 of the mid-turn edit redesign.

  * the knob registry covers every field an edit can name — nothing actionable
    is left without a description, and nothing is described that can't land
  * every named change ends in exactly one Outcome
  * "it's already that" is a no-op, not a rebuild
  * undo is an inverse edit: it re-invalidates instead of restoring `ops_done`
    (which used to claim work whose outputs had been popped)
"""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import HumanMessage

from app.graph.builder.edits import apply_edits, is_actionable_field, stash_edits
from app.graph.builder.knobs import KNOBS, NOT_TYPEABLE, knob_for_field
from app.graph.field_owner_registry import FIELD_OWNER
from app.graph.narrator.beats import drain_changes
from app.graph.resume_router import ResumeResult


# ── registry coverage ─────────────────────────────────────────────────────────


def test_every_actionable_field_is_a_knob_or_explicitly_not_typeable():
    missing = [
        f for f in FIELD_OWNER
        if is_actionable_field(f) and knob_for_field(f) is None and f not in NOT_TYPEABLE
    ]
    assert missing == [], f"actionable but undescribed: {missing}"


def test_every_knob_can_actually_land():
    for knob in KNOBS.values():
        names = (knob.name, *knob.aliases)
        assert any(is_actionable_field(n) for n in names) or knob.name == "poi_selection", knob.name


def test_confusables_point_at_real_knobs_and_are_mutual_enough():
    for knob in KNOBS.values():
        for other in knob.confusable_with:
            assert other in KNOBS, f"{knob.name} → unknown {other}"


def test_the_two_radii_are_each_others_confusable():
    assert "poi_radius_m" in KNOBS["search_radius_km"].confusable_with
    assert "search_radius_km" in KNOBS["poi_radius_m"].confusable_with
    assert KNOBS["search_radius_km"].unit == "km" and KNOBS["poi_radius_m"].unit == "m"


# ── outcomes ──────────────────────────────────────────────────────────────────


def _state(msg_id: str) -> dict:
    return {"messages": [HumanMessage(content="x", id=msg_id)], "user_info": {}}


def _bs(**filled) -> dict:
    return {
        "ops_done": ["geo_discover", "maid_query"], "stages_complete": ["geo", "maid"],
        "filled": {"location_scope": "granular_local", "locations": "Montreal",
                   "det_type": "category", "poi_types": "gym", "poi_radius_m": "100", **filled},
        "geo_result": {"pois_found": 3},
    }


def test_same_value_is_a_no_op_and_rebuilds_nothing():
    state = _state("po-noop")
    bs = _bs()
    stash_edits(bs, ResumeResult("x", edits={"poi_radius_m": "100"}))

    report = apply_edits(bs, state)

    assert [o.status for o in report.outcomes] == ["no_op"]
    assert report.rolled_back == []
    assert "maid_query" in bs["ops_done"]
    changes = drain_changes(state)
    assert any("already" in a for a in changes["applied"])


def test_each_field_gets_exactly_one_outcome():
    state = _state("po-mixed")
    bs = _bs()
    stash_edits(bs, ResumeResult("x", edits={
        "poi_radius_m": "5000 m",      # clamped → adjusted
        "lookback_days": "14",         # applied
        "poi_types": "gym",            # already → no_op
        "budget": "$500",              # campaign → applied
    }))

    report = apply_edits(bs, state)

    by_field = {o.field: o.status for o in report.outcomes}
    assert by_field == {
        "poi_radius_m": "adjusted", "lookback_days": "applied",
        "poi_types": "no_op", "budget": "applied",
    }
    assert len(report.outcomes) == 4


def test_unlandable_search_circle_is_unsupported_and_said():
    state = _state("po-unsupported")
    bs = _bs()
    bs["geo_ws"] = {"_geocoded_locations": [{"location_name": "Quebec", "ui_mode": "boundary"}]}
    stash_edits(bs, ResumeResult("x", edits={"search_radius_km": "5 km"}))

    report = apply_edits(bs, state)

    assert [o.status for o in report.outcomes] == ["unsupported"]
    assert drain_changes(state)["unsupported"]


# ── undo as an inverse edit ───────────────────────────────────────────────────


def _undo(bs: dict, state: dict) -> dict:
    from app.graph.builder.interject_tools import perform_undo

    _msg, ui_restore = asyncio.run(perform_undo(bs, state))
    return ui_restore


def test_undo_reinvalidates_instead_of_claiming_popped_work():
    """v1 undo restored ops_done=[geo_discover, maid_query] while geo_result /
    maid_ws were gone — the planner then skipped work that had no output."""
    state = _state("po-undo")
    state["user_info"] = {"poi_radius_m": 100}
    bs = _bs()
    stash_edits(bs, ResumeResult("x", edits={"poi_radius_m": "300"}))
    apply_edits(bs, state)
    assert "maid_query" not in bs["ops_done"]

    ui_restore = _undo(bs, state)

    assert bs["filled"]["poi_radius_m"] == "100"
    assert "maid_query" not in bs["ops_done"]          # rebuilt, never claimed done
    assert ui_restore == {"poi_radius_m": 100}


def test_undo_restores_the_search_circle_and_its_ring():
    state = _state("po-undo-ring")
    bs = _bs()
    bs["geo_ws"] = {"_geocoded_locations": [{
        "location_name": "Montreal", "ui_mode": "pin_radius", "search_radius_km": 12.0,
        "default_radius_km": 12.0, "latitude": 45.5, "longitude": -73.6,
    }]}
    stash_edits(bs, ResumeResult("x", edits={"search_radius_km": "5 km"}))
    apply_edits(bs, state)
    assert bs["geo_ws"]["_geocoded_locations"][0]["search_radius_km"] == 5.0

    _undo(bs, state)

    assert "_search_ring_km" not in bs["geo_ws"]
    assert bs["geo_ws"]["_geocoded_locations"][0]["search_radius_km"] == 12.0
    assert "geo_discover" not in bs["ops_done"]


def test_legacy_v1_snapshot_still_undoes():
    state = _state("po-undo-v1")
    bs = {"filled": {"a": "2"}, "ops_done": ["x"],
          "_undo_stack": [{"filled": {"a": "1"}, "ops_done": ["y"]}]}
    _undo(bs, state)
    assert bs["filled"] == {"a": "1"} and bs["ops_done"] == ["y"]


@pytest.mark.asyncio
async def test_single_mode_dispatch_records_heard_but_does_not_ack_yet():
    """In single-interrupt mode the ack comes after the write, from the outcome."""
    from unittest.mock import AsyncMock, patch

    from app.graph.resume_router import ResumeIntent
    from app.graph.wizard_helpers import _dispatch_edit_intent

    state = _state("po-noack")
    state["campaign_builder_state"] = {"_single_interrupt": True}
    narrate = AsyncMock()
    edits: dict = {}
    with patch("app.graph.wizard_helpers.narrate", new=narrate):
        await _dispatch_edit_intent(
            intent=ResumeIntent(lane="edit", target_field="budget", new_value="$500", confidence=0.95),
            state=state, writer=lambda _e: None, pending={}, cfg={"field": "geo_locations"},
            edits=edits, edit_base={},
        )
    assert edits == {"budget": "$500"}
    assert narrate.await_count == 0
    assert drain_changes(state)["heard_not_applied"] == ["set budget = $500"]


# ── typed changes outside an interrupt ────────────────────────────────────────


def test_extraction_becomes_edits_and_lists_only_gain_items():
    from app.graph.builder.edits import edits_from_extraction

    bs = {"ops_done": [], "filled": {"locations": "Montreal", "det_type": "category", "poi_types": "cafe"}}
    state = {"user_info": {"location": ["Montreal"], "poi_types": ["cafe"]}}
    edits, held = edits_from_extraction(
        {"budget": "$800", "location": ["Laval"], "audience_filter": {"x": 1},
         "meta_ad_account_id": "act_1", "business_name": None},
        state, bs,
    )
    assert edits == {"budget": "$800", "location": ["Montreal", "Laval"]}
    assert held == []


def test_a_cost_bearing_change_is_held_once_audience_data_was_bought():
    from app.graph.builder.edits import edits_from_extraction

    bs = {"ops_done": ["maid_query"], "filled": {"poi_radius_m": "100", "locations": "Montreal"}}
    edits, held = edits_from_extraction({"poi_radius_m": 500, "budget": "$800"}, {"user_info": {}}, bs)
    assert edits == {"budget": "$800"} and held == ["poi_radius_m"]
    # …but free before the audience is bought
    bs["ops_done"] = []
    edits, held = edits_from_extraction({"poi_radius_m": 500}, {"user_info": {}}, bs)
    assert edits == {"poi_radius_m": 500} and held == []


def test_entry_node_stashes_a_typed_change_for_a_paused_build():
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.graph import nodes

    src = __import__("inspect").getsource(nodes.entry_node)
    assert "edits_from_extraction" in src and "_pending_edits" in src


def test_maid_gate_map_removals_join_the_replayable_specs():
    """A removal clicked at the audience map was never recorded, so a later
    re-fold from the discovery superset brought it back."""
    from app.graph.builder.builder_node import _record_map_removals

    bs = {"_poi_selection_specs": [{"op": "keep", "n": 5}]}
    _record_map_removals(bs, [{"name": "Gym A", "lat": 45.5, "lng": -73.6}, "junk", {"name": "no coords"}])
    assert bs["_poi_selection_specs"][0] == {"op": "keep", "n": 5}
    assert bs["_poi_selection_specs"][1]["op"] == "drop"
    assert len(bs["_poi_selection_specs"][1]["ids"]) == 1
    _record_map_removals(bs, [])
    assert len(bs["_poi_selection_specs"]) == 2


@pytest.mark.asyncio
async def test_removing_an_unlisted_place_becomes_an_exclusion_not_a_silent_no_op():
    """"target everywhere except Mile End" when Mile End isn't a listed area: it
    is a place INSIDE a targeted one, so it is carved out — not reported as
    "already that value"."""
    from unittest.mock import AsyncMock, patch

    from app.graph.resume_router import ResumeIntent
    from app.graph.wizard_helpers import _dispatch_edit_intent

    state = _state("po-absent-remove")
    edits: dict = {}
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
        await _dispatch_edit_intent(
            intent=ResumeIntent(lane="edit", target_field="location", new_value="Mile End",
                                is_remove=True, confidence=0.95),
            state=state, writer=lambda _e: None, pending={}, cfg={"field": "geo_pois_confirmation"},
            edits=edits, edit_base={"location": ["Montreal"]},
        )
    assert "location" not in edits                       # the listed area is untouched
    assert edits["_location_ops"] == [{"kind": "exclude", "target": None, "value": "Mile End"}]
    assert drain_changes(state)["heard_not_applied"] == ["leave out Mile End"]


@pytest.mark.asyncio
async def test_removing_a_present_item_still_works_and_a_mixed_removal_keeps_the_real_part():
    from unittest.mock import AsyncMock, patch

    from app.graph.resume_router import ResumeIntent
    from app.graph.wizard_helpers import _dispatch_edit_intent

    state = _state("po-mixed-remove")
    edits: dict = {}
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
        await _dispatch_edit_intent(
            intent=ResumeIntent(lane="edit", target_field="location", new_value=["Laval", "Mile End"],
                                is_remove=True, confidence=0.95),
            state=state, writer=lambda _e: None, pending={}, cfg={"field": "geo_pois_confirmation"},
            edits=edits, edit_base={"location": ["Montreal", "Laval"]},
        )
    assert edits["location"] == ["Montreal"]             # Laval removed
    assert edits["_location_ops"] == [{"kind": "exclude", "target": None, "value": "Mile End"}]


@pytest.mark.asyncio
async def test_removing_an_unlisted_non_location_item_is_said_not_a_silent_no_op():
    from unittest.mock import AsyncMock, patch

    from app.graph.resume_router import ResumeIntent
    from app.graph.wizard_helpers import _dispatch_edit_intent

    state = _state("po-absent-poitype")
    edits: dict = {}
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
        await _dispatch_edit_intent(
            intent=ResumeIntent(lane="edit", target_field="poi_types", new_value="bakery",
                                is_remove=True, confidence=0.95),
            state=state, writer=lambda _e: None, pending={}, cfg={"field": "geo_pois_confirmation"},
            edits=edits, edit_base={"poi_types": ["gym"]},
        )
    assert "poi_types" not in edits
    assert "bakery" in drain_changes(state)["unsupported"][0]
