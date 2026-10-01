"""
tests/test_geo_confirm_edit.py
──────────────────────────────
The "edit a location at the geo confirm step" fix:

  - _dispatch_edit_intent merges an append/remove against ``edit_base`` (the
    field's CURRENT value) so "add whitehall" yields ``current + [whitehall]``,
    not just ``[whitehall]``.
"""
from __future__ import annotations

import asyncio

from app.graph import wizard_helpers as wh
from app.graph.resume_router import ResumeIntent


# ── _dispatch_edit_intent edit_base seeding ──────────────────────────────────


def _noop_narrate_patch(monkeypatch):
    async def _fake_narrate(*a, **k):
        return None
    monkeypatch.setattr(wh, "narrate", _fake_narrate)


def test_dispatch_append_merges_against_edit_base(monkeypatch):
    _noop_narrate_patch(monkeypatch)
    intent = ResumeIntent(
        lane="edit", target_field="geo_locations", new_value="whitehall",
        is_append=True, confidence=0.95,
    )
    edits: dict = {}
    asyncio.run(wh._dispatch_edit_intent(
        intent=intent, state={}, writer=lambda e: None,
        pending={}, cfg={"field": "geo_location_confirmation"}, edits=edits,
        edit_base={"geo_locations": ["Columbus"]},
    ))
    assert edits["geo_locations"] == ["Columbus", "whitehall"]


def test_dispatch_remove_against_edit_base(monkeypatch):
    _noop_narrate_patch(monkeypatch)
    intent = ResumeIntent(
        lane="edit", target_field="geo_locations", new_value="Columbus",
        is_remove=True, confidence=0.95,
    )
    edits: dict = {}
    asyncio.run(wh._dispatch_edit_intent(
        intent=intent, state={}, writer=lambda e: None,
        pending={}, cfg={"field": "geo_location_confirmation"}, edits=edits,
        edit_base={"geo_locations": ["Columbus", "Whitehall"]},
    ))
    assert edits["geo_locations"] == ["Whitehall"]


def test_dispatch_append_without_edit_base_is_additions_only(monkeypatch):
    # Back-compat: no edit_base → merges against the empty accumulator (old path).
    _noop_narrate_patch(monkeypatch)
    intent = ResumeIntent(
        lane="edit", target_field="geo_locations", new_value="whitehall",
        is_append=True, confidence=0.95,
    )
    edits: dict = {}
    asyncio.run(wh._dispatch_edit_intent(
        intent=intent, state={}, writer=lambda e: None,
        pending={}, cfg={"field": "geo_location_confirmation"}, edits=edits,
    ))
    assert edits["geo_locations"] == ["whitehall"]


# ── Confirm-step edit rebinds the PER-ANGLE location set ─────────────────────
#
# `angle_names` is frozen from `geo_angle_specs` before the confirm loop, while an
# edit only rebound the flat `location_names`. `_locs_for` then filtered each angle
# to the PRE-EDIT names: a location added at the confirm step was geocoded, drawn
# on the map and counted in the chips — then dropped before the POI search, so
# every POI came back tagged with the original city.

from types import SimpleNamespace

from app.graph.builder.executors import geo
from tests._geo_run_helper import run_det as _run_det


def _patch_for_confirm_edit(monkeypatch, interrupt_results):
    """Stub the executor's I/O. `interrupt_results` is popped one per confirm ask."""

    async def fake_probe(_name):
        return []

    async def fake_wi(*a, **k):
        return interrupt_results.pop(0) if interrupt_results else "yes"

    async def fake_call_tool(tool, args, writer=None, node_name=None):
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        if "geocode" in name:
            city = args["location_name"]
            return ({
                "latitude": 45.5, "longitude": -73.6, "location_name": city,
                "formatted_address": f"{city}, QC, Canada", "locality": city,
                "is_city": True, "place_type": "locality", "bounds": None,
            }, {"status": "ok"})
        if "pois_by_type" in name:
            city = args["city_name"]
            # Distinct coords per city — the shared coord dedupe would otherwise
            # collapse the two stub POIs and hide what this test measures.
            return ({"targetable_poi_coordinates": [
                {"name": f"Gym in {city}", "lat": 45.5 + 0.01 * len(city),
                 "lng": -73.6, "parent_location": args.get("parent_label") or city},
            ]}, {"status": "ok"})
        return (None, {"status": "ok"})

    monkeypatch.setattr(geo, "probe_location_candidates", fake_probe)
    monkeypatch.setattr(geo, "wizard_interrupt", fake_wi)
    monkeypatch.setattr(geo, "add_beat", lambda *a, **k: None)
    monkeypatch.setattr(geo, "call_tool", fake_call_tool)
    monkeypatch.setattr(geo.settings, "GEO_REGION_POLYGON_FILTER", False)


def _run_category_geo(monkeypatch, interrupt_results, location_names):
    _patch_for_confirm_edit(monkeypatch, interrupt_results)
    ws: dict = {}
    _run_det(
        "granular_local", "category", location_names, "a gym brand",
        lambda ev: None,
        {
            "poi_types_list": ["gym"],
            # Per-angle spec pinned to the ORIGINAL market only.
            "angle_specs": [
                {"angle": "category", "locations": ["Montreal"], "poi_types": ["gym"]},
            ],
        },
        ws, state=None,
    )
    return ws["_det_result"]


def test_confirm_edit_adds_location_to_every_angle(monkeypatch):
    det = _run_category_geo(
        monkeypatch,
        [SimpleNamespace(edits={"geo_locations": ["Montreal", "Westmount"]}), "yes"],
        ["Montreal"],
    )
    searched = {p["name"] for p in det["targetable_pois"]}
    assert searched == {"Gym in Montreal", "Gym in Westmount"}


def test_no_edit_still_searches_only_the_spec_locations(monkeypatch):
    # Regression guard: without an edit the per-angle filter must still apply.
    det = _run_category_geo(monkeypatch, ["yes"], ["Montreal", "Laval"])
    assert {p["name"] for p in det["targetable_pois"]} == {"Gym in Montreal"}


# ── Confirm-widget add/remove delta ──────────────────────────────────────────
#
# The widget's search bar submits the POI-confirm payload shape. `is_sentinel_resume`
# short-circuits any JSON to the confirm lane before the classifier runs, so
# `ResumeResult.edits` is always empty for it — the executor has to parse the string
# itself or the user's picks are confirmed away unread.

import json

# The live wire payload. `place_id` is deliberately present and deliberately
# unused — the frontend sends it, and an unknown key must not disturb the fold.
_BASTROP = {
    "name": "Bastrop", "lat": 30.1104947, "lng": -97.3152701,
    "parent_location": "Bastrop, TX 78602, USA", "parent_poi_type": "locality",
    "place_id": "ChIJadvR6FuaRIYRYNmtW2Y8DTQ",
}


def _delta(confirm=True, added=(), removed=()):
    """The exact wire shape, Q:/A: wrapper already stripped by `_unwrap_qa`."""
    return json.dumps({
        "confirm": confirm, "added": list(added), "removed": list(removed),
    })


def test_widget_delta_add_reaches_the_poi_search(monkeypatch):
    det = _run_category_geo(monkeypatch, [_delta(added=[_BASTROP])], ["Montreal"])
    # Both markets searched — the added one survived the per-angle rebind.
    assert {p["name"] for p in det["targetable_pois"]} == {
        "Gym in Montreal", "Gym in Bastrop",
    }


def test_widget_delta_applies_and_advances(monkeypatch):
    # One confirm ask only: a structured pick needs no second confirm round. The
    # scripted list has a single entry, so a second ask would fall through to the
    # "yes" default and go unnoticed — count the calls instead.
    calls: list = []
    _patch_for_confirm_edit(monkeypatch, [_delta(added=[_BASTROP])])
    _real_wi = geo.wizard_interrupt

    async def counting_wi(*a, **k):
        calls.append(k.get("step_key"))
        return await _real_wi(*a, **k)

    monkeypatch.setattr(geo, "wizard_interrupt", counting_wi)
    ws: dict = {}
    _run_det(
        "granular_local", "category", ["Montreal"], "a gym brand",
        lambda ev: None, {"poi_types_list": ["gym"]}, ws, state=None,
    )
    assert calls.count("geo_location_confirmation") == 1
    assert ws["_location_confirmed"] is True
    assert ws["_locations_synced"] == ["Montreal", "Bastrop"]


def test_widget_delta_added_location_is_fully_geocoded(monkeypatch):
    # The "search with filter" guarantee: the added location must go through
    # _do_geocode, not a stub synthesized from the widget's lat/lng — otherwise
    # it reaches search_pois_by_type with no geometry at all. City/town scope
    # now searches a pin+radius ring (no name-based locality_filter — the hard
    # ring already scopes it) rather than a political bbox — see
    # _stamp_location_radius_mode / _search_geometry_for.
    searches: list[dict] = []
    _patch_for_confirm_edit(monkeypatch, [_delta(added=[_BASTROP])])
    _real_call_tool = geo.call_tool

    async def spy_call_tool(tool, args, writer=None, node_name=None):
        if "pois_by_type" in getattr(tool, "name", getattr(tool, "__name__", "")):
            searches.append(args)
        return await _real_call_tool(tool, args, writer=writer, node_name=node_name)

    monkeypatch.setattr(geo, "call_tool", spy_call_tool)
    _run_det(
        "granular_local", "category", ["Montreal"], "a gym brand",
        lambda ev: None, {"poi_types_list": ["gym"]}, {}, state=None,
    )
    added = [s for s in searches if s["city_name"] == "Bastrop"]
    assert added, "the added location was never searched"
    assert added[0]["locality_filter"] is None
    assert added[0]["bounds"] is not None
    assert added[0]["search_radius_km"] == geo.settings.GEO_PIN_RADIUS_FALLBACK_KM


def test_widget_delta_remove_matches_the_resolved_address(monkeypatch):
    # location_names holds the raw token; the widget round-trips the RESOLVED place.
    det = _run_category_geo(
        monkeypatch,
        [_delta(removed=[{
            "name": "Laval", "parent_location": "Laval, QC, Canada",
            "lat": 45.5, "lng": -73.6,
        }])],
        ["Montreal", "Laval"],
    )
    assert {loc["location_name"] for loc in det["locations"]} == {"Montreal"}


def test_widget_delta_removing_everything_re_asks(monkeypatch):
    # Never advance into a POI search with zero markets — re-ask instead.
    det = _run_category_geo(
        monkeypatch,
        [_delta(removed=[{"name": "Montreal"}]), "yes"],
        ["Montreal"],
    )
    assert {loc["location_name"] for loc in det["locations"]} == {"Montreal"}


def test_widget_delta_noop_confirms_without_relooping(monkeypatch):
    det = _run_category_geo(monkeypatch, [_delta()], ["Montreal"])
    assert {p["name"] for p in det["targetable_pois"]} == {"Gym in Montreal"}


def test_widget_delta_reject_re_asks(monkeypatch):
    det = _run_category_geo(monkeypatch, [_delta(confirm=False), "yes"], ["Montreal"])
    assert {p["name"] for p in det["targetable_pois"]} == {"Gym in Montreal"}


# ── Hint-driven disambiguation ───────────────────────────────────────────────


def test_hint_picks_the_place_type_the_user_clicked():
    cands = [
        {"place_type": "administrative_area_level_2", "latitude": 30.10, "longitude": -97.31},
        {"place_type": "locality", "latitude": 30.11, "longitude": -97.32},
    ]
    assert geo._pick_candidate_by_hint(cands, {"place_type": "locality"}) == 1


def test_hint_falls_back_to_nearest_coordinate():
    cands = [
        {"place_type": "locality", "latitude": 40.7, "longitude": -74.0},
        {"place_type": "locality", "latitude": 30.11, "longitude": -97.32},
    ]
    hint = {"place_type": "locality", "lat": 30.1104947, "lng": -97.3152701}
    assert geo._pick_candidate_by_hint(cands, hint) == 1


def test_hint_declines_when_nothing_is_close():
    cands = [{"place_type": "locality", "latitude": 40.7, "longitude": -74.0}]
    hint = {"place_type": "postal_code", "lat": 30.11, "lng": -97.31}
    assert geo._pick_candidate_by_hint(cands, hint) is None
    assert geo._pick_candidate_by_hint(cands, None) is None


# ── Delta parsing / folding, pure ────────────────────────────────────────────


def test_parse_location_delta_ignores_non_delta_answers():
    assert geo._parse_location_delta("yes") is None
    assert geo._parse_location_delta('{"action": "publish"}') is None
    assert geo._parse_location_delta("{not json") is None
    assert geo._parse_location_delta(_delta())["confirm"] is True


def test_loc_delta_to_names_harvests_hints():
    merged, hints = geo._loc_delta_to_names(
        {"added": [_BASTROP], "removed": []}, ["Montreal"], [],
    )
    assert merged == ["Montreal", "Bastrop"]
    assert hints["Bastrop"]["place_type"] == "locality"
    assert hints["Bastrop"]["lat"] == 30.1104947


def test_loc_delta_to_names_skips_an_already_present_location():
    merged, hints = geo._loc_delta_to_names(
        {"added": [{"name": "montréal"}]}, ["Montreal"], [],
    )
    assert merged == ["Montreal"]
    assert hints == {}
