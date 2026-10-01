"""
Unit tests for executors/maid.py's _maid_cache_still_valid — the guard that
decides whether run_maid_query trusts the session-keyed extraction cache or
re-queries the warehouse.

Regression for: "change the radius to 100 meters" invalidated the maid_query
unit correctly, but the cache was keyed on session_id alone — it restored
the 60m-radius extraction instead of re-querying at 100m (a ponytail-flagged
debt that surfaced in practice). Pure function, no DB.
"""
from app.graph.builder.executors.maid import _maid_cache_still_valid

POI_A = {"name": "A", "lat": 45.5, "lng": -73.5}
POI_B = {"name": "B", "lat": 45.6, "lng": -73.6}


def _existing(**overrides):
    base = {
        "maid_count": 100,
        "search_radius_km": 0.06,
        "lookback_days": 30,
        "event_date_ranges": [],
        "pois": [dict(POI_A), dict(POI_B)],
    }
    base.update(overrides)
    return base


def test_identical_params_are_a_cache_hit():
    assert _maid_cache_still_valid(
        _existing(), 0.06, 30, [], [dict(POI_A), dict(POI_B)],
    ) is True


def test_changed_radius_is_a_cache_miss():
    """The exact bug report: radius edited from 60m to 100m."""
    assert _maid_cache_still_valid(
        _existing(), 0.1, 30, [], [dict(POI_A), dict(POI_B)],
    ) is False


def test_changed_lookback_is_a_cache_miss():
    assert _maid_cache_still_valid(
        _existing(), 0.06, 7, [], [dict(POI_A), dict(POI_B)],
    ) is False


def test_changed_poi_set_is_a_cache_miss():
    poi_c = {"name": "C", "lat": 45.7, "lng": -73.7}
    assert _maid_cache_still_valid(
        _existing(), 0.06, 30, [], [dict(POI_A), dict(POI_B), poi_c],
    ) is False


def test_no_existing_extraction_is_a_cache_miss():
    assert _maid_cache_still_valid(None, 0.06, 30, [], [dict(POI_A)]) is False


def test_empty_extraction_is_a_cache_miss():
    assert _maid_cache_still_valid(
        _existing(maid_count=0), 0.06, 30, [], [dict(POI_A), dict(POI_B)],
    ) is False


def test_a_purged_extraction_is_a_cache_miss_even_with_a_real_maid_count():
    """maid_count is the HISTORICAL count and survives a purge — only the
    row's raw maids/observations are cleared. Without this check a purged row
    (published, or swept as abandoned) reads as a valid restore and hands the
    caller an empty maid list under a nonzero maid_count — a phantom cache hit
    that silently publishes zero people while claiming otherwise."""
    from datetime import datetime, timezone

    assert _maid_cache_still_valid(
        _existing(purged_at=datetime.now(timezone.utc)),
        0.06, 30, [], [dict(POI_A), dict(POI_B)],
    ) is False
