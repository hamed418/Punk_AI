"""Geo discovery guards: antimeridian bbox, POI identity, default event window.

Pure functions — no API key, no LLM, no network. Each check fails if the
corresponding fix regresses.
"""

from app.graph.builder.executors.geo import (
    _EVENT_PAST_WINDOW_DAYS,
    dedup_key,
)
from app.graph.tools import _normalize_bbox, _point_in_bounds, _tile_bbox

# The real bounds Google returns for "US" — it reaches the Aleutians, so the
# longitude span crosses the antimeridian and comes back inverted.
US_BOUNDS = {
    "lat_min": 18.7763, "lat_max": 74.071038,
    "lng_min": 166.9999999, "lng_max": -66.885417,
}


def test_antimeridian_bbox_is_uninverted():
    b = _normalize_bbox(US_BOUNDS)
    # Wider half kept: [-180, -66.9] (113°) beats [167, 180] (13°).
    assert b["lng_min"] == -180.0
    assert b["lng_max"] == US_BOUNDS["lng_max"]
    assert b["lng_min"] < b["lng_max"]
    # Latitudes untouched.
    assert (b["lat_min"], b["lat_max"]) == (US_BOUNDS["lat_min"], US_BOUNDS["lat_max"])


def test_us_points_survive_the_bounds_guard():
    b = _normalize_bbox(US_BOUNDS)
    assert _point_in_bounds(40.7128, -74.0060, b)    # New York
    assert _point_in_bounds(21.3069, -157.8583, b)   # Honolulu
    assert not _point_in_bounds(45.5017, -73.5673, US_BOUNDS)  # inverted box: nothing passes


def test_tiles_have_positive_width():
    tiles = _tile_bbox(_normalize_bbox(US_BOUNDS), 12)
    assert len(tiles) == 9
    assert all(t["lng_min"] < t["lng_max"] and t["lat_min"] < t["lat_max"] for t in tiles)


def test_ordinary_bbox_passes_through_unchanged():
    montreal = {"lat_min": 45.4, "lat_max": 45.7, "lng_min": -73.9, "lng_max": -73.4}
    assert _normalize_bbox(montreal) == montreal
    assert _normalize_bbox(None) is None


def test_same_coords_different_names_are_distinct_places():
    # Two conferences whose venue is still "TBD" both geocode to the city centroid.
    a = {"name": "AAD (Dermatology) @ TBD", "lat": 39.7392364, "lng": -104.984862}
    b = {"name": "ACC (Cardiology) @ TBD", "lat": 39.7392364, "lng": -104.984862}
    assert dedup_key(a) != dedup_key(b)
    # The same place under two queries still collapses.
    assert dedup_key(a) == dedup_key({**a, "parent_poi_type": "another query"})
    # No usable coords → nothing to dedup on.
    assert dedup_key({"name": "x"}) is None


def test_event_window_is_a_full_year():
    assert _EVENT_PAST_WINDOW_DAYS == 365
