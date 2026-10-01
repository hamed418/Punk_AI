"""
Phase 6a: typed per-location circle, move-centre-by-text, remove-a-pin.

Reuses the map widget's own appliers, so a typed change and a drag agree.
Ambiguity is asked about, never guessed; every result is one ledger line.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage

from app.graph.builder import builder_node
from app.graph.builder.executors import geo
from app.graph.narrator.beats import drain_changes


def _loc(name: str, lat: float, km: float = 12.0) -> dict:
    return {
        "location_name": name, "formatted_address": f"{name}, QC, Canada", "_source_name": name,
        "ui_mode": "pin_radius", "search_radius_km": km, "default_radius_km": km,
        "latitude": lat, "longitude": -73.6,
    }


def _ws(*locs, pins=()) -> dict:
    return {"_geocoded_locations": list(locs), "_manual_pins": list(pins)}


def _run(ws, ops):
    return asyncio.run(geo.apply_location_ops(ws, ops))


def test_named_circle_changes_only_that_location():
    ws = _ws(_loc("Montreal", 45.5), _loc("Laval", 45.6))
    (res,) = _run(ws, [{"kind": "ring", "target": "Laval", "value": "3 km"}])
    assert res["status"] == "applied" and "3 km" in res["detail"]
    radii = {l["location_name"]: l["search_radius_km"] for l in ws["_geocoded_locations"]}
    assert radii == {"Montreal": 12.0, "Laval": 3.0}
    assert ws["_loc_radius_overrides"]["laval"]["radius_km"] == 3.0     # survives a re-geocode


def test_miles_are_converted_and_a_clamp_is_said():
    ws = _ws(_loc("Laval", 45.6))
    (res,) = _run(ws, [{"kind": "ring", "target": "Laval", "value": "100 miles"}])
    assert res["status"] == "applied" and "allowed limit" in res["detail"]
    assert ws["_geocoded_locations"][0]["search_radius_km"] == 80.0


def test_same_value_is_a_no_op():
    ws = _ws(_loc("Laval", 45.6, km=3.0))
    (res,) = _run(ws, [{"kind": "ring", "target": "Laval", "value": "3 km"}])
    assert res["status"] == "no_op"


def test_ambiguous_or_missing_target_asks_instead_of_guessing():
    ws = _ws(_loc("Montreal", 45.5), _loc("Laval", 45.6))
    (none,) = _run(ws, [{"kind": "ring", "target": None, "value": "3 km"}])
    assert none["status"] == "unresolved" and len(none["candidates"]) == 2
    (nomatch,) = _run(ws, [{"kind": "ring", "target": "Brossard", "value": "3 km"}])
    assert nomatch["status"] == "unresolved" and len(nomatch["candidates"]) == 2
    assert [l["search_radius_km"] for l in ws["_geocoded_locations"]] == [12.0, 12.0]


def test_a_single_location_needs_no_target():
    ws = _ws(_loc("Montreal", 45.5))
    (res,) = _run(ws, [{"kind": "ring", "target": None, "value": "5 km"}])
    assert res["status"] == "applied"


def test_boundary_only_locations_have_no_circle_to_resize():
    ws = _ws({"location_name": "Quebec", "ui_mode": "boundary"})
    (res,) = _run(ws, [{"kind": "ring", "target": None, "value": "5 km"}])
    assert res["status"] == "unresolved" and res["candidates"] == []


def test_center_moves_by_text_and_demotes_like_a_drag():
    ws = _ws(_loc("Montreal", 45.5))
    found = {"latitude": 45.52, "longitude": -73.58, "location_name": "123 Main St"}
    with patch.object(geo, "call_tool", new=AsyncMock(return_value=(found, {}))), \
         patch.object(geo, "reverse_geocode_point", new=AsyncMock(return_value={"location_name": "Main St"})):
        (res,) = _run(ws, [{"kind": "center", "target": "Montreal", "value": "123 Main St"}])
    assert res["status"] == "applied"
    loc = ws["_geocoded_locations"][0]
    assert (loc["latitude"], loc["longitude"]) == (45.52, -73.58)
    assert "place_id" not in loc and loc["ui_mode"] == "pin_radius"
    assert ws["_loc_radius_overrides"]["montreal"]["demoted"] is True


def test_center_that_cannot_be_found_fails_without_moving_anything():
    ws = _ws(_loc("Montreal", 45.5))
    with patch.object(geo, "call_tool", new=AsyncMock(return_value=(None, {}))):
        (res,) = _run(ws, [{"kind": "center", "target": "Montreal", "value": "nowhere at all"}])
    assert res["status"] == "failed"
    assert ws["_geocoded_locations"][0]["latitude"] == 45.5


def test_dropped_pin_can_be_removed_by_text():
    pin = {**_loc("Griffintown", 45.49), "_source_name": "__manual_pin_1__"}
    ws = _ws(_loc("Montreal", 45.5), pins=[pin])
    (res,) = _run(ws, [{"kind": "unpin", "target": None, "value": ""}])
    assert res["status"] == "applied"
    assert ws["_manual_pins"] == []


def test_no_pin_to_remove_says_so():
    ws = _ws(_loc("Montreal", 45.5))
    (res,) = _run(ws, [{"kind": "unpin", "target": None, "value": ""}])
    assert res["status"] == "unresolved" and "no dropped pin" in res["detail"]


# ── through builder_plan's applier: invalidation, ledger, undo ────────────────


def _bs() -> dict:
    return {
        "ops_done": ["geo_discover", "maid_query"], "stages_complete": ["geo", "maid"],
        "filled": {"location_scope": "granular_local", "locations": "Montreal, Laval", "det_type": "category"},
        "geo_ws": {**_ws(_loc("Montreal", 45.5), _loc("Laval", 45.6)), "_location_confirmed": True},
        "geo_result": {"pois_found": 5},
    }


def test_applied_op_reruns_the_search_keeps_the_confirm_and_is_undoable():
    from app.graph.builder.interject_tools import perform_undo

    state = {"messages": [HumanMessage(content="x", id="lo-plan")], "user_info": {}}
    bs = _bs()
    asyncio.run(builder_node._apply_location_ops_edit(
        bs, state, [{"kind": "ring", "target": "Laval", "value": "3 km"}], lambda _e: None,
    ))

    assert "geo_discover" not in bs["ops_done"]
    assert bs["geo_ws"]["_location_confirmed"] is True
    assert {l["location_name"]: l["search_radius_km"] for l in bs["geo_ws"]["_geocoded_locations"]}["Laval"] == 3.0
    assert any("3 km" in a for a in drain_changes(state)["applied"])

    asyncio.run(perform_undo(bs, state))

    laval = next(l for l in bs["geo_ws"]["_geocoded_locations"] if l["location_name"] == "Laval")
    assert laval["search_radius_km"] == 12.0
    assert "_loc_radius_overrides" not in bs["geo_ws"] or "laval" not in bs["geo_ws"]["_loc_radius_overrides"]


def test_an_ambiguous_op_changes_nothing_and_reports_the_question():
    state = {"messages": [HumanMessage(content="x", id="lo-ambig")], "user_info": {}}
    bs = _bs()
    asyncio.run(builder_node._apply_location_ops_edit(
        bs, state, [{"kind": "ring", "target": None, "value": "3 km"}], lambda _e: None,
    ))
    assert "geo_discover" in bs["ops_done"] and not bs.get("_undo_stack")
    changes = drain_changes(state)
    assert changes["deviations"] and "which one" in changes["deviations"][0]


@pytest.mark.asyncio
async def test_dispatch_stashes_the_op_with_its_target():
    from app.graph.resume_router import ResumeIntent
    from app.graph.wizard_helpers import _dispatch_edit_intent

    state = {"messages": [HumanMessage(content="x", id="lo-dispatch")], "user_info": {},
             "campaign_builder_state": {}}
    edits: dict = {}
    intent = ResumeIntent(lane="edit", target_field="location_ring", new_value="3 km",
                          edit_target="Laval", confidence=0.95)
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
        await _dispatch_edit_intent(
            intent=intent, state=state, writer=lambda _e: None, pending={},
            cfg={"field": "geo_locations"}, edits=edits, edit_base={},
        )
    assert edits == {"_location_ops": [{"kind": "ring", "target": "Laval", "value": "3 km"}]}
    assert drain_changes(state)["heard_not_applied"]


def test_five_miles_is_not_reported_as_a_limit_it_only_rounds():
    """Live thread: "make the fort collins radius to 5 miles" (8.047 km) was stored
    as 8.0 and reported as 'the allowed limit'. Rounding to 0.1 km is not a limit."""
    ws = _ws(_loc("Fort Collins", 40.58), _loc("Denver", 39.74))
    (res,) = _run(ws, [{"kind": "ring", "target": "Fort Collins", "value": "5 miles"}])
    assert res["status"] == "applied" and "limit" not in res["detail"]
    assert {loc["location_name"]: loc["search_radius_km"] for loc in ws["_geocoded_locations"]}["Denver"] != 8.0


def test_the_search_ring_edit_does_not_claim_a_limit_for_rounding():
    from app.graph.builder.edits import _clamp_deviation

    assert _clamp_deviation("search circle", "5 miles", "km", 8.0) is None
    assert "allowed limit" in _clamp_deviation("search circle", "200 km", "km", 80.0)
