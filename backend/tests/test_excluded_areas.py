"""
"Everywhere except downtown": carving a place out of an area that stays targeted.

Refused when the place isn't inside the targeted area, never deletes the user's
own stores, uses the real OSM polygon when there is one (bounds / a small circle
otherwise), and a changed exclusion set never serves a stale cached POI list.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage

from app.graph.builder import builder_node
from app.graph.builder.executors import geo
from app.graph.narrator.beats import drain_changes
from tests.test_geo_pin_radius_confirm import _AUSTIN_BOUNDS, _patch
from tests.test_geo_confirm_single_interrupt import _drive_once

# A ~1 km box round (30.27, -97.74), as (lng, lat) rings like the OSM helper returns.
_SQUARE = [[(-97.745, 30.265), (-97.735, 30.265), (-97.735, 30.275), (-97.745, 30.275), (-97.745, 30.265)]]


def _austin() -> dict:
    return {"location_name": "Austin", "formatted_address": "Austin, TX, USA", "_source_name": "Austin",
            "ui_mode": "pin_radius", "search_radius_km": 15.0, "latitude": 30.27, "longitude": -97.74}


def _found(name="Downtown", lat=30.27, lng=-97.74):
    return {"latitude": lat, "longitude": lng, "location_name": name, "place_id": "p1",
            "place_type": "neighborhood",
            "bounds": {"lat_min": lat - 0.005, "lat_max": lat + 0.005, "lng_min": lng - 0.005, "lng_max": lng + 0.005}}


def _run(ws, ops, found):
    with patch.object(geo, "call_tool", new=AsyncMock(return_value=(found, {}))):
        return asyncio.run(geo.apply_location_ops(ws, ops))


def test_an_area_inside_the_target_is_left_out():
    ws = {"_geocoded_locations": [_austin()]}
    (res,) = _run(ws, [{"kind": "exclude", "target": None, "value": "downtown"}], _found())
    assert res["status"] == "applied" and "Downtown" in res["detail"]
    assert ws["_excluded_areas"][0]["label"] == "Downtown"


def test_the_place_is_geocoded_in_the_context_of_the_targeted_city():
    ws = {"_geocoded_locations": [_austin()]}
    seen = {}

    async def _spy(tool, args, **_kw):
        seen["q"] = args["location_name"]
        return _found(), {}

    with patch.object(geo, "call_tool", new=_spy):
        asyncio.run(geo.apply_location_ops(ws, [{"kind": "exclude", "target": None, "value": "downtown"}]))
    assert seen["q"] == "downtown, Austin"


def test_an_area_outside_the_target_is_refused():
    ws = {"_geocoded_locations": [_austin()]}
    (res,) = _run(ws, [{"kind": "exclude", "target": None, "value": "Dallas"}], _found("Dallas", 32.78, -96.8))
    assert res["status"] == "failed" and "isn't inside" in res["detail"]
    assert "_excluded_areas" not in ws


def test_an_unfindable_place_fails_without_changing_anything():
    ws = {"_geocoded_locations": [_austin()]}
    (res,) = _run(ws, [{"kind": "exclude", "target": None, "value": "nowhere"}], None)
    assert res["status"] == "failed" and "couldn't find" in res["detail"]


def test_excluding_twice_is_a_no_op_and_it_can_be_undone_by_name():
    ws = {"_geocoded_locations": [_austin()]}
    _run(ws, [{"kind": "exclude", "target": None, "value": "downtown"}], _found())
    (again,) = _run(ws, [{"kind": "exclude", "target": None, "value": "Downtown"}], _found())
    assert again["status"] == "no_op" and len(ws["_excluded_areas"]) == 1

    (gone,) = _run(ws, [{"kind": "unexclude", "target": None, "value": "downtown"}], None)
    assert gone["status"] == "applied" and ws["_excluded_areas"] == []
    (nope,) = _run(ws, [{"kind": "unexclude", "target": None, "value": "airport"}], None)
    assert nope["status"] == "unresolved"


# ── the filter ────────────────────────────────────────────────────────────────


def _poi(name, lat, lng, angle="category"):
    return {"name": name, "lat": lat, "lng": lng, "source_angle": angle}


def _area(bounds=True):
    a = {"label": "Downtown", "lat": 30.27, "lng": -97.74}
    if bounds:
        a["bounds"] = {"lat_min": 30.265, "lat_max": 30.275, "lng_min": -97.745, "lng_max": -97.735}
    return a


def _filter(areas, pois, polygon=None):
    events: list = []
    with patch.object(geo, "_region_polygon_cached", new=AsyncMock(return_value=polygon)):
        out = asyncio.run(geo.drop_excluded_pois({"_excluded_areas": areas}, pois, events.append))
    return out, events


def test_polygon_is_used_when_there_is_one():
    inside, outside = _poi("in", 30.27, -97.74), _poi("out", 30.40, -97.74)
    kept, events = _filter([_area()], [inside, outside], polygon=_SQUARE)
    assert [p["name"] for p in kept] == ["out"]
    assert "Left out 1 spot(s) in Downtown" in events[0]["content"]


def test_bounds_box_is_the_fallback_without_a_polygon():
    kept, _ = _filter([_area()], [_poi("in", 30.27, -97.74), _poi("out", 30.30, -97.74)])
    assert [p["name"] for p in kept] == ["out"]


def test_a_small_circle_is_the_last_fallback():
    kept, _ = _filter([_area(bounds=False)], [_poi("in", 30.271, -97.74), _poi("out", 30.30, -97.74)])
    assert [p["name"] for p in kept] == ["out"]


def test_the_users_own_stores_are_never_dropped():
    store = _poi("My cafe", 30.27, -97.74, angle="store_set")
    kept, _ = _filter([_area()], [store, _poi("rival", 30.27, -97.74)])
    assert [p["name"] for p in kept] == ["My cafe"]


def test_a_polygon_lookup_failure_falls_back_instead_of_failing_the_search():
    with patch.object(geo, "_region_polygon_cached", new=AsyncMock(side_effect=RuntimeError("osm down"))):
        kept = asyncio.run(geo.drop_excluded_pois({"_excluded_areas": [_area()]}, [_poi("in", 30.27, -97.74)]))
    assert kept == []


def test_no_areas_returns_the_same_list():
    pois = [_poi("a", 1, 1)]
    assert asyncio.run(geo.drop_excluded_pois({}, pois)) is pois


# ── through the real executor ─────────────────────────────────────────────────


def _patch_and_run(monkeypatch, excluded):
    searches = _patch(monkeypatch, ["yes"], {"Austin": "locality"}, {"Austin": _AUSTIN_BOUNDS})
    monkeypatch.setattr(geo, "_region_polygon_cached", AsyncMock(return_value=None))
    ws: dict = {"_excluded_areas": excluded} if excluded else {}
    while _drive_once(ws):
        pass
    return ws, searches


def test_the_search_result_drops_pois_inside_an_excluded_area(monkeypatch):
    # _patch's fake Places returns "Gym in Austin" at (30.27, -97.74).
    ws, _ = _patch_and_run(monkeypatch, [_area()])
    assert ws["_det_result"]["targetable_pois"] == []


def test_without_an_exclusion_the_same_poi_is_kept(monkeypatch):
    ws, _ = _patch_and_run(monkeypatch, None)
    assert [p["name"] for p in ws["_det_result"]["targetable_pois"]] == ["Gym in Austin"]


def test_a_changed_exclusion_set_never_serves_a_stale_cache(monkeypatch):
    ws, _ = _patch_and_run(monkeypatch, None)
    assert ws["_det_result"]["targetable_pois"]
    ws["_excluded_areas"] = [_area()]                     # what the typed edit writes
    monkeypatch.setattr(geo, "wizard_interrupt", AsyncMock(return_value="yes"))
    while _drive_once(ws):
        pass
    assert ws["_det_result"]["targetable_pois"] == []


# ── through builder_plan's applier: rerun, ledger, undo ───────────────────────


def test_applied_exclusion_reruns_the_search_reports_and_is_undoable():
    from app.graph.builder.interject_tools import perform_undo

    state = {"messages": [HumanMessage(content="x", id="ex-plan")], "user_info": {}}
    bs = {"ops_done": ["geo_discover", "maid_query"], "stages_complete": ["geo", "maid"],
          "filled": {"locations": "Austin"}, "geo_ws": {"_geocoded_locations": [_austin()]}}
    with patch.object(geo, "call_tool", new=AsyncMock(return_value=(_found(), {}))):
        asyncio.run(builder_node._apply_location_ops_edit(
            bs, state, [{"kind": "exclude", "target": None, "value": "downtown"}], lambda _e: None,
        ))

    assert "geo_discover" not in bs["ops_done"] and bs["geo_ws"]["_excluded_areas"]
    assert any("leaving Downtown out" in a for a in drain_changes(state)["applied"])

    asyncio.run(perform_undo(bs, state))
    assert not bs["geo_ws"].get("_excluded_areas")


def test_a_refused_exclusion_changes_nothing_and_says_why():
    state = {"messages": [HumanMessage(content="x", id="ex-refuse")], "user_info": {}}
    bs = {"ops_done": ["geo_discover"], "filled": {}, "geo_ws": {"_geocoded_locations": [_austin()]}}
    with patch.object(geo, "call_tool", new=AsyncMock(return_value=(_found("Dallas", 32.78, -96.8), {}))):
        asyncio.run(builder_node._apply_location_ops_edit(
            bs, state, [{"kind": "exclude", "target": None, "value": "Dallas"}], lambda _e: None,
        ))
    assert "geo_discover" in bs["ops_done"] and not bs.get("_undo_stack")
    assert "isn't inside" in drain_changes(state)["unsupported"][0]


# ── drawn on the maps ────────────────────────────────────────────────────────

_AREA = {"label": "Downtown Montreal", "query": "Downtown, Montreal", "lat": 45.5, "lng": -73.57,
         "bounds": {"lat_min": 45.49, "lat_max": 45.51, "lng_min": -73.58, "lng_max": -73.55},
         "place_id": "p1", "place_type": "neighborhood", "components": {}}


def test_excluded_areas_payload_carries_what_the_map_draws():
    from app.graph.builder.executors.geo import excluded_areas_payload

    assert excluded_areas_payload({"_excluded_areas": [_AREA]}) == [
        {"label": "Downtown Montreal", "lat": 45.5, "lng": -73.57, "bounds": _AREA["bounds"]},
    ]
    assert excluded_areas_payload({}) == []


def test_the_poi_map_event_lists_the_areas_left_out():
    from app.graph.builder.builder_node import _poi_preview_map_event

    det = {"targetable_pois": [{"name": "A", "lat": 45.6, "lng": -73.6}], "locations": [{}]}

    ev = _poi_preview_map_event(det, {"_excluded_areas": [_AREA]}, {})

    assert ev["content"]["excluded_areas"][0]["label"] == "Downtown Montreal"
    assert _poi_preview_map_event(det, {}, {})["content"]["excluded_areas"] == []


def test_the_location_confirm_map_lists_the_areas_left_out(monkeypatch):
    import asyncio

    from app.graph.builder.executors import geo
    from tests.test_geo_pin_radius_confirm import _AUSTIN_BOUNDS, _patch

    seen: list = []

    async def _fake_interrupt(writer, **kw):
        seen.extend(kw.get("repeat_events") or [])
        return "yes"

    _patch(monkeypatch, [], {"Austin": "locality"}, {"Austin": _AUSTIN_BOUNDS})
    monkeypatch.setattr(geo, "wizard_interrupt", _fake_interrupt)
    ws: dict = {"_excluded_areas": [_AREA]}

    async def _go():
        await geo._execute_deterministic(
            "granular_local", "category", ["Austin"], "a gym brand",
            lambda ev: None, {"poi_types_list": ["gym"]}, ws, state=None,
        )
    try:
        asyncio.run(_go())
    except geo._GeoStepPaused:
        pass

    confirm = next(e for e in seen if e["content"]["action_type"] == "confirm_locations")
    assert confirm["content"]["excluded_areas"][0]["label"] == "Downtown Montreal"
