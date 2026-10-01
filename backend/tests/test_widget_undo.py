"""
A change made on the confirm map — a dragged / resized circle, a dropped pin, an
added or removed place — is undoable like a typed edit: the executor stashes the
pre-edit decisions, builder_act turns them into ONE v2 snapshot, and "undo" puts
the old map back and re-runs the search. A plain confirm through the same lane
pushes nothing.
"""
from __future__ import annotations

import asyncio
import json

from app.graph.builder.builder_node import _sync_confirm_edits_undoable
from app.graph.builder.executors import geo
from app.graph.builder.interject_tools import perform_undo
from tests.test_geo_pin_radius_confirm import _AUSTIN_BOUNDS, _patch


def _drive_once(ws):
    async def _go():
        await geo._execute_deterministic(
            "granular_local", "category", ["Austin"], "a gym brand",
            lambda ev: None, {"poi_types_list": ["gym"]}, ws, state=None,
        )
    try:
        asyncio.run(_go())
    except geo._GeoStepPaused:
        pass


def _bs(ws):
    return {
        "geo_ws": ws, "ops_done": ["geo_discover"],
        "filled": {"location_scope": "granular_local", "locations": "Austin", "det_type": "category"},
    }


def _settle(ws, bs):
    """What builder_act does when the geo task ends."""
    _sync_confirm_edits_undoable(ws, bs["filled"], bs, {}, {"user_info": {}})
    bs["geo_ws"] = ws


def _drag(radius=25.0):
    return json.dumps({
        "confirm": True, "added": [], "removed": [],
        "updated": [{"name": "Austin", "lat": 30.30, "lng": -97.65, "radius_km": radius}],
    })


def test_a_drag_on_the_map_pushes_one_undo_snapshot_and_undo_restores_it(monkeypatch):
    _patch(monkeypatch, [_drag()], {"Austin": "locality"}, {"Austin": _AUSTIN_BOUNDS})
    ws: dict = {}
    _drive_once(ws)
    bs = _bs(ws)
    moved = ws["_geocoded_locations"][0]
    assert moved["search_radius_km"] == 25.0

    _settle(ws, bs)

    assert "_widget_undo_before" not in bs["geo_ws"]           # scratch, never persisted
    assert len(bs["_undo_stack"]) == 1
    snap = bs["_undo_stack"][0]
    assert snap["v"] == 2 and snap["unit"] == "poi_search"
    before = snap["geo_ws"]["_geocoded_locations"][0]
    assert before["search_radius_km"] != 25.0                   # the ring as it was, deep-copied

    msg, _ = asyncio.run(perform_undo(bs, {"user_info": {}}))

    assert msg == "reverted the last edit"
    restored = bs["geo_ws"]["_geocoded_locations"][0]
    assert restored["search_radius_km"] == before["search_radius_km"]
    assert "_location_confirmed" not in bs["geo_ws"]           # the old map is shown again
    assert "geo_discover" not in bs["ops_done"]                 # the search re-runs


def test_a_plain_confirm_pushes_nothing(monkeypatch):
    _patch(monkeypatch, [json.dumps({"confirm": True, "added": [], "removed": []})],
           {"Austin": "locality"}, {"Austin": _AUSTIN_BOUNDS})
    ws: dict = {}
    _drive_once(ws)
    bs = _bs(ws)

    _settle(ws, bs)

    assert not bs.get("_undo_stack")


def test_a_dropped_pin_is_undone_with_its_pin(monkeypatch):
    add_pin = json.dumps({"confirm": True, "removed": [], "added": [{"lat": 30.35, "lng": -97.70, "radius_km": 8}]})
    _patch(monkeypatch, [add_pin], {"Austin": "locality"}, {"Austin": _AUSTIN_BOUNDS})
    ws: dict = {}
    _drive_once(ws)
    bs = _bs(ws)
    assert ws["_manual_pins"]

    _settle(ws, bs)
    asyncio.run(perform_undo(bs, {"user_info": {}}))

    assert not bs["geo_ws"].get("_manual_pins")
    assert all(loc.get("ui_mode") != "pin_radius" or loc["location_name"] == "Austin"
               for loc in bs["geo_ws"]["_geocoded_locations"])
