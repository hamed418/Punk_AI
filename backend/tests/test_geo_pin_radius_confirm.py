"""
tests/test_geo_pin_radius_confirm.py
─────────────────────────────────────
Boundary → pin+radius confirm (city/town/metro scope):

  - country/state locations stay ui_mode="boundary" (political shape kept).
  - city/town locations become ui_mode="pin_radius" with a sane default
    search_radius_km derived from the geocoder's own viewport.
  - a confirm-widget "updated" delta (drag/resize) demotes a named city to a
    plain pin, re-labels it from the NEW coordinate, and the next POI search
    rings the new center at the new radius — no locality_filter, no bbox
    tiling.
  - an "added" delta entry with no name (the "drop pin" toggle) skips
    geocoding entirely and becomes a manual pin, reverse-geocoded for a
    real label.

Mirrors the fixture shape in test_geo_confirm_edit.py.
"""
from __future__ import annotations

import json

from app.graph.builder.executors import geo
from tests._geo_run_helper import run_det as _run_det

# Distinct bounds per fixture "city" so the default-radius derivation has
# something real to divide: ~11km diagonal for Austin, ~1500km for Texas
# (irrelevant for Texas — it's boundary mode, radius is never computed).
_AUSTIN_BOUNDS = {"lat_min": 30.20, "lat_max": 30.30, "lng_min": -97.80, "lng_max": -97.70}


def _fake_call_tool(place_types: dict[str, str], bounds: dict[str, dict | None]):
    """A `call_tool`/`search_pois_by_type` stub keyed by the fixture's fake
    city names, parameterized per test so each can control place_type/bounds
    per name without duplicating the whole fixture."""
    searches: list[dict] = []

    async def _fake(tool, args, writer=None, node_name=None):
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        if "geocode" in name:
            city = args["location_name"]
            return ({
                "latitude": 30.2672, "longitude": -97.7431, "location_name": city,
                "formatted_address": f"{city}, USA", "locality": city,
                "is_city": True, "place_type": place_types.get(city, "locality"),
                "bounds": bounds.get(city),
            }, {"status": "ok"})
        if "pois_by_type" in name:
            searches.append(args)
            return ({"targetable_poi_coordinates": [
                {"name": f"Gym in {args['city_name']}", "lat": 30.27, "lng": -97.74,
                 "parent_location": args.get("parent_label") or args["city_name"]},
            ]}, {"status": "ok"})
        return (None, {"status": "ok"})

    return _fake, searches


def _patch(monkeypatch, interrupt_results, place_types, bounds, reverse_label="Rainey Street"):
    fake_call_tool, searches = _fake_call_tool(place_types, bounds)

    async def fake_probe(_name):
        return []

    async def fake_wi(*a, **k):
        return interrupt_results.pop(0) if interrupt_results else "yes"

    async def fake_reverse(lat, lng):
        return {"location_name": reverse_label, "formatted_address": f"{reverse_label}, Austin, TX"}

    monkeypatch.setattr(geo, "probe_location_candidates", fake_probe)
    monkeypatch.setattr(geo, "wizard_interrupt", fake_wi)
    monkeypatch.setattr(geo, "add_beat", lambda *a, **k: None)
    monkeypatch.setattr(geo, "call_tool", fake_call_tool)
    monkeypatch.setattr(geo, "reverse_geocode_point", fake_reverse)
    monkeypatch.setattr(geo.settings, "GEO_REGION_POLYGON_FILTER", False)
    return searches


def test_city_gets_pin_radius_mode_with_bounds_derived_default(monkeypatch):
    _patch(monkeypatch, ["yes"], {"Austin": "locality"}, {"Austin": _AUSTIN_BOUNDS})
    ws: dict = {}
    _run_det(
        "granular_local", "category", ["Austin"], "a gym brand",
        lambda ev: None, {"poi_types_list": ["gym"]}, ws, state=None,
    )
    loc = ws["_det_result"]["locations"][0]
    assert loc["ui_mode"] == "pin_radius"
    expected = geo._default_radius_km_from_bounds(_AUSTIN_BOUNDS)
    assert loc["search_radius_km"] == expected
    assert loc["default_radius_km"] == expected
    assert 0 < expected < geo.settings.GEO_PIN_RADIUS_MAX_KM


def test_country_scope_keeps_boundary_mode(monkeypatch):
    _patch(
        monkeypatch, ["yes"], {"Texas": "administrative_area_level_1"},
        {"Texas": {"lat_min": 25.8, "lat_max": 36.5, "lng_min": -106.6, "lng_max": -93.5}},
    )
    ws: dict = {}
    _run_det(
        "admin_areas", "category", ["Texas"], "a gym brand",
        lambda ev: None, {"poi_types_list": ["gym"]}, ws, state=None,
    )
    loc = ws["_det_result"]["locations"][0]
    assert loc["ui_mode"] == "boundary"
    assert "search_radius_km" not in loc


def test_updated_delta_demotes_and_resizes_ring(monkeypatch):
    _moved_lat, _moved_lng, _new_radius = 30.30, -97.65, 25.0
    update_delta = json.dumps({
        "confirm": True, "added": [], "removed": [],
        "updated": [{"name": "Austin", "lat": _moved_lat, "lng": _moved_lng, "radius_km": _new_radius}],
    })
    searches = _patch(
        monkeypatch, [update_delta, "yes"],
        {"Austin": "locality"}, {"Austin": _AUSTIN_BOUNDS}, reverse_label="Rainey Street",
    )
    ws: dict = {}
    _run_det(
        "granular_local", "category", ["Austin"], "a gym brand",
        lambda ev: None, {"poi_types_list": ["gym"]}, ws, state=None,
    )
    det = ws["_det_result"]
    loc = det["locations"][0]
    assert loc["ui_mode"] == "pin_radius"
    assert loc["latitude"] == _moved_lat and loc["longitude"] == _moved_lng
    assert loc["search_radius_km"] == _new_radius
    assert loc["location_name"] == "Rainey Street"  # reverse-geocoded, not the stale "Austin"
    assert "place_id" not in loc or loc.get("place_id") is None

    # The POI search that ran AFTER the demotion used the new ring, not the
    # political bbox/locality filter.
    final_search = searches[-1]
    assert final_search["locality_filter"] is None
    assert final_search["search_radius_km"] == _new_radius
    assert final_search["bounds"] is not None


def test_added_delta_with_no_name_becomes_manual_pin(monkeypatch):
    manual_add = json.dumps({
        "confirm": True, "removed": [],
        "added": [{"lat": 30.35, "lng": -97.70, "radius_km": 8}],
    })
    searches = _patch(
        monkeypatch, [manual_add, "yes"],
        {"Austin": "locality"}, {"Austin": _AUSTIN_BOUNDS}, reverse_label="Domain NORTHSIDE",
    )
    ws: dict = {}
    _run_det(
        "granular_local", "category", ["Austin"], "a gym brand",
        lambda ev: None, {"poi_types_list": ["gym"]}, ws, state=None,
    )
    det = ws["_det_result"]
    names = {loc["location_name"] for loc in det["locations"]}
    assert "Austin" in names
    assert "Domain NORTHSIDE" in names
    manual = next(loc for loc in det["locations"] if loc["location_name"] == "Domain NORTHSIDE")
    assert manual["ui_mode"] == "pin_radius"
    assert manual["search_radius_km"] == 8.0
    assert manual.get("place_id") is None
    assert any(s["city_name"] == "Domain NORTHSIDE" for s in searches)
