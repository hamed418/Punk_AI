"""
tests/test_maid_visit_evidence.py
─────────────────────────────────
Per-visit EVIDENCE: confidence, distance, flags, and truncation disclosure.

`min_confidence` shipped as a filter field with no producer — nothing ever set
`confirmed`, so `v.get("confirmed") is False` was never true and the predicate
silently did nothing. A field the extractor can emit and the evaluator ignores is
worse than a missing feature: it looks like it worked.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.graph.maid_query import cluster_visits
from app.graph.maid_signal import FLAG_BITS, accuracy_upper_m
from app.services.maid_store import apply_audience_filter

HIGH = 1 << FLAG_BITS["HIGH_ACCURACY"]          # 0-35 m
MODERATE = 1 << FLAG_BITS["MODERATE_ACCURACY"]  # 50-220 m
DRIVING = 1 << FLAG_BITS["LIKELY_DRIVING"]


def _iso(minute: int) -> str:
    return (datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
            + timedelta(minutes=minute)).isoformat()


# ── accuracy decoding ────────────────────────────────────────────────────────

def test_accuracy_upper_bound():
    assert accuracy_upper_m(HIGH) == 35.0
    assert accuracy_upper_m(MODERATE) == 220.0


def test_no_accuracy_bits_is_unbounded_not_a_big_number():
    """None, so a caller cannot compare "unknown" against a radius and get a
    confident answer."""
    assert accuracy_upper_m(0) is None
    assert accuracy_upper_m(None) is None


# ── the confirmation rule ────────────────────────────────────────────────────

def test_one_precise_ping_well_inside_the_ring_confirms():
    meta = {_iso(0): {"flags": HIGH, "dist_m": 20.0}}
    v = cluster_visits([_iso(0)], ping_meta=meta, radius_m=100.0)[0]
    assert v["confirmed"] is True
    assert v["best_accuracy_m"] == 35.0
    assert v["min_dist_m"] == 20.0


def test_one_precise_ping_on_the_ring_edge_does_not_confirm():
    """The vendor's geo search is fuzzy — observations can be returned from
    just OUTSIDE the drawn area — so an edge ping is not proof of a visit."""
    meta = {_iso(0): {"flags": HIGH, "dist_m": 95.0}}
    assert cluster_visits([_iso(0)], ping_meta=meta, radius_m=100.0)[0]["confirmed"] is False


def test_one_imprecise_ping_does_not_confirm():
    meta = {_iso(0): {"flags": MODERATE, "dist_m": 20.0}}
    assert cluster_visits([_iso(0)], ping_meta=meta, radius_m=100.0)[0]["confirmed"] is False


def test_two_pings_confirm_regardless_of_precision():
    """Repetition is its own evidence: a device seen twice at one place was
    there, whatever each individual fix was worth."""
    meta = {
        _iso(0): {"flags": MODERATE, "dist_m": 90.0},
        _iso(5): {"flags": MODERATE, "dist_m": 88.0},
    }
    v = cluster_visits([_iso(0), _iso(5)], ping_meta=meta, radius_m=100.0)[0]
    assert v["confirmed"] is True


def test_flags_are_ored_across_the_cluster():
    """So a later filter can drop a visit whose evidence includes a driving or
    spoof ping without re-reading the pings."""
    meta = {
        _iso(0): {"flags": HIGH, "dist_m": 10.0},
        _iso(5): {"flags": DRIVING, "dist_m": 12.0},
    }
    v = cluster_visits([_iso(0), _iso(5)], ping_meta=meta, radius_m=100.0)[0]
    assert v["flags_or"] & DRIVING
    assert v["flags_or"] & HIGH


def test_without_ping_meta_the_evidence_fields_are_absent():
    """A backend that supplies no evidence must not have visits reclassified as
    unconfirmed — absent is not the same as False."""
    v = cluster_visits([_iso(0)])[0]
    assert "confirmed" not in v
    assert "flags_or" not in v


# ── min_confidence now has a producer ────────────────────────────────────────

def _obs(maid: str, visits: list[dict]) -> dict:
    return {
        "maid": maid, "lat": 40.75, "lng": -73.98, "count": len(visits),
        "poi_ids": ["category:gym"], "poi_uids": ["a"], "visits": visits,
        "days": sorted({v["ts"][:10] for v in visits}),
    }


def test_min_confidence_actually_filters():
    """Before the producer existed this returned BOTH devices — the field was
    accepted by the extractor and ignored by the evaluator."""
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(hours=2)).isoformat()
    solid = _obs("solid", [{"ts": ts, "n_pings": 4, "dwell_lower_s": 900, "confirmed": True}])
    weak = _obs("weak", [{"ts": ts, "n_pings": 1, "dwell_lower_s": 0, "confirmed": False}])

    both = apply_audience_filter([solid, weak], None, pois=[{"lat": 40.75, "lng": -73.98}])
    assert set(both) == {"solid", "weak"}

    strict = apply_audience_filter(
        [solid, weak], {"min_confidence": "confirmed"}, pois=[{"lat": 40.75, "lng": -73.98}]
    )
    assert strict == ["solid"]


def test_min_confidence_keeps_visits_that_carry_no_evidence():
    """Legacy and demo-synth visits have no `confirmed` key. Treating absent as
    unconfirmed would silently empty every such audience."""
    now = datetime.now(timezone.utc)
    legacy = _obs("legacy", [{"ts": (now - timedelta(hours=2)).isoformat(), "dwell_min": 30}])
    assert apply_audience_filter(
        [legacy], {"min_confidence": "confirmed"}, pois=[{"lat": 40.75, "lng": -73.98}]
    ) == ["legacy"]


def test_exclude_flags_drops_a_visit_by_its_evidence():
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(hours=2)).isoformat()
    clean = _obs("clean", [{"ts": ts, "n_pings": 3, "dwell_lower_s": 600, "flags_or": HIGH}])
    drove = _obs("drove", [{"ts": ts, "n_pings": 3, "dwell_lower_s": 600, "flags_or": DRIVING}])

    keep = apply_audience_filter(
        [clean, drove], {"exclude_flags": DRIVING}, pois=[{"lat": 40.75, "lng": -73.98}]
    )
    assert keep == ["clean"]


# ── truncation disclosure ────────────────────────────────────────────────────

def test_truncation_is_recorded_and_reports_under_sampled_devices():
    """`observationLimitHit` used to be logged and nothing else. A truncated
    POI's frequency counts are FLOORS, and truncation is not random with respect
    to devices, so a min_visits over one systematically under-counts."""
    from app.graph.unacast_query import (
        _reset_truncation,
        parse_response,
        truncation_report,
    )

    _reset_truncation()
    payload = {
        "features": [{
            "id": "keyA",
            "properties": {
                "observationLimitHit": True,
                "observationCount": 100000,
                "totalPossibleObservationCount": 10479989,
                "totalPossibleObservationCountPerDevice": {"dev-1": 900, "dev-2": 1},
                "observationsPerDevice": [
                    {"advertiserID": "dev-1", "observations": [
                        {"timestampEpochMS": 1788665280000,
                         "latitude": 40.75, "longitude": -73.98},
                    ]},
                    {"advertiserID": "dev-2", "observations": [
                        {"timestampEpochMS": 1788665280000,
                         "latitude": 40.75, "longitude": -73.98},
                    ]},
                ],
            },
        }],
    }
    rows, total, truncated = parse_response(payload, {"keyA": {"lat": 40.75, "lng": -73.98}})
    assert total == 2 and len(rows) == 2
    assert truncated == {"keyA"}

    report = truncation_report()
    assert report["truncated_poi_count"] == 1
    # dev-1 truly has 900 observations but only 1 came back; dev-2 is complete.
    assert report["under_sampled_devices"] == ["dev-1"]
    assert report["worst_sampled_fraction"] == pytest.approx(100000 / 10479989)
    _reset_truncation()


def test_an_untruncated_response_records_nothing():
    from app.graph.unacast_query import (
        _reset_truncation,
        parse_response,
        truncation_report,
    )

    _reset_truncation()
    payload = {
        "features": [{
            "id": "keyA",
            "properties": {
                "observationCount": 12,
                "observationsPerDevice": [
                    {"advertiserID": "dev-1", "observations": [
                        {"timestampEpochMS": 1788665280000,
                         "latitude": 40.75, "longitude": -73.98},
                    ]},
                ],
            },
        }],
    }
    parse_response(payload, {"keyA": {"lat": 40.75, "lng": -73.98}})
    assert truncation_report()["truncated_poi_count"] == 0
