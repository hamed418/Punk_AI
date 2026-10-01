"""
tests/test_maid_signal_gate.py
──────────────────────────────
The signal-quality gate (app/graph/maid_signal.py) and key-based POI
attribution (maid_query.attribute_audience).

Both use facts the vendor response already states instead of re-deriving them
from coordinates: which POI a ping belongs to, and whether the ping is accurate
enough to mean anything for a ring that size. Numbers quoted in the docstrings
are measured, not assumed — docs/maid_signal_quality_baseline.md.
"""
from __future__ import annotations

import pytest

from app.graph.maid_signal import (
    FLAG_BITS,
    PLACE_VISIT_EXCLUDE_MASK,
    accuracy_bounds,
    apply_gate,
    describe_gate,
    mask_for,
    ping_admitted,
)


def _flags(*names: str) -> int:
    return mask_for(*names)


# ── accuracy decoding ────────────────────────────────────────────────────────

@pytest.mark.parametrize("names,expected", [
    (("HIGH_ACCURACY",), (0.0, 35.0)),
    (("MODERATE_ACCURACY", "HIGH_ACCURACY"), (35.0, 50.0)),
    (("MODERATE_ACCURACY",), (50.0, 220.0)),
    (("LOW_ACCURACY", "MODERATE_ACCURACY"), (220.0, 250.0)),
    (("LOW_ACCURACY",), (250.0, 10000.0)),
])
def test_accuracy_bounds_match_the_vendor_table(names, expected):
    assert accuracy_bounds(_flags(*names)) == expected


def test_no_accuracy_bits_is_the_worst_band_not_the_best():
    """16.1% of real pings carry no accuracy bits at all. Treating those as
    precise would repeat the exact mistake the gate exists to fix — an unknown
    accuracy is not evidence of a good fix."""
    lower, upper = accuracy_bounds(0)
    assert lower == 10000.0 and upper is None
    assert accuracy_bounds(None) == (10000.0, None)


# ── the admission rule ───────────────────────────────────────────────────────

def test_permissive_admits_a_band_that_could_be_inside():
    """50-220m: the device COULD have been inside a 100m ring."""
    flags = _flags("MODERATE_ACCURACY")
    assert ping_admitted(flags, 100.0, exclude_mask=0, accuracy_mode="permissive")
    assert not ping_admitted(flags, 100.0, exclude_mask=0, accuracy_mode="strict")


def test_strict_requires_the_whole_band_inside():
    flags = _flags("HIGH_ACCURACY")           # 0-35m
    assert ping_admitted(flags, 100.0, exclude_mask=0, accuracy_mode="strict")


def test_a_wide_band_is_rejected_by_both_modes():
    """250-10,000m cannot place a device in a 100m ring under any reading."""
    flags = _flags("LOW_ACCURACY")
    assert not ping_admitted(flags, 100.0, exclude_mask=0, accuracy_mode="permissive")
    assert not ping_admitted(flags, 100.0, exclude_mask=0, accuracy_mode="strict")


def test_accuracy_is_relative_to_the_ring_not_absolute():
    """The same ping is usable evidence for a 500m ring and useless for a 60m
    one. This is why the gate runs per POI rather than once over all rows."""
    flags = _flags("MODERATE_ACCURACY")       # 50-220m
    assert ping_admitted(flags, 500.0, exclude_mask=0, accuracy_mode="permissive")
    assert not ping_admitted(flags, 40.0, exclude_mask=0, accuracy_mode="permissive")


def test_off_mode_admits_everything():
    assert ping_admitted(0, 100.0, exclude_mask=0, accuracy_mode="off")


def test_exclude_mask_rejects_regardless_of_accuracy():
    """A high-accuracy ping from a device the vendor says was DRIVING is a
    precise measurement of a non-visit."""
    flags = _flags("HIGH_ACCURACY", "LIKELY_DRIVING")
    assert not ping_admitted(
        flags, 100.0, exclude_mask=PLACE_VISIT_EXCLUDE_MASK, accuracy_mode="off"
    )


def test_place_visit_preset_covers_the_documented_bits():
    for name in ("SPOOF_LOCATION", "OVER_CAPACITY_DEVICE",
                 "LAT_GRID_LOCATION", "LIKELY_DRIVING"):
        assert PLACE_VISIT_EXCLUDE_MASK & (1 << FLAG_BITS[name])
    # Not an accuracy filter — those are a separate, radius-relative decision.
    assert not PLACE_VISIT_EXCLUDE_MASK & (1 << FLAG_BITS["HIGH_ACCURACY"])


def test_mask_for_rejects_an_unknown_flag_name():
    """Silently building a mask of 0 would disable the gate without a word."""
    with pytest.raises(KeyError):
        mask_for("NOT_A_REAL_FLAG")


# ── apply_gate ───────────────────────────────────────────────────────────────

def test_apply_gate_drops_driving_and_low_accuracy(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "MAID_ACCURACY_MODE", "permissive", raising=False)
    monkeypatch.setattr(config.settings, "MAID_EXCLUDE_FLAGS", "", raising=False)

    rows = [
        {"maid": "a", "forensic_flags": _flags("HIGH_ACCURACY")},
        {"maid": "b", "forensic_flags": _flags("HIGH_ACCURACY", "LIKELY_DRIVING")},
        {"maid": "c", "forensic_flags": _flags("LOW_ACCURACY")},
        {"maid": "d", "forensic_flags": _flags("MODERATE_ACCURACY")},
    ]
    kept, stats = apply_gate(rows, 100.0)

    assert [r["maid"] for r in kept] == ["a", "d"]
    assert stats["dropped_flags"] == 1        # b, driving
    assert stats["dropped_accuracy"] == 1     # c, 250-10000m
    assert stats["pings_in"] == 4 and stats["pings_kept"] == 2


def test_a_ping_with_no_flags_is_judged_as_unknown_accuracy(monkeypatch):
    """No flags means no accuracy evidence — the worst band, not a free pass.
    Only accuracy_mode="off" keeps such a ping."""
    from app.core import config

    monkeypatch.setattr(config.settings, "MAID_EXCLUDE_FLAGS", "", raising=False)
    rows = [{"maid": "unflagged", "lat": 1.0, "lng": 2.0}]

    monkeypatch.setattr(config.settings, "MAID_ACCURACY_MODE", "permissive", raising=False)
    kept, stats = apply_gate(rows, 100.0)
    assert kept == []
    assert stats["pings_without_flags"] == 1 and stats["dropped_accuracy"] == 1

    monkeypatch.setattr(config.settings, "MAID_ACCURACY_MODE", "off", raising=False)
    kept, _stats = apply_gate(rows, 100.0)
    assert kept == rows


def test_exclude_mask_override_keeps_driving_pings(monkeypatch):
    """A drive-by audience (a billboard) wants exactly the pings the default
    preset drops. The override is per-call, settings untouched — B3."""
    from app.core import config
    from app.graph.maid_signal import DRIVE_BY_EXCLUDE_MASK

    monkeypatch.setattr(config.settings, "MAID_ACCURACY_MODE", "off", raising=False)
    monkeypatch.setattr(config.settings, "MAID_EXCLUDE_FLAGS", "", raising=False)

    rows = [
        {"maid": "driver", "forensic_flags": _flags("LIKELY_DRIVING")},
        {"maid": "spoofed", "forensic_flags": _flags("SPOOF_LOCATION")},
    ]
    kept, _stats = apply_gate(rows, 100.0, exclude_mask=DRIVE_BY_EXCLUDE_MASK)

    # LIKELY_DRIVING kept (the whole point); SPOOF_LOCATION still dropped —
    # the override removes only the driving bit from the default preset.
    assert [r["maid"] for r in kept] == ["driver"]


def test_exclude_mask_none_keeps_default_behaviour(monkeypatch):
    """exclude_mask=None (the default call shape) must be identical to not
    passing the parameter at all — no regression for every existing caller."""
    from app.core import config

    monkeypatch.setattr(config.settings, "MAID_ACCURACY_MODE", "off", raising=False)
    monkeypatch.setattr(config.settings, "MAID_EXCLUDE_FLAGS", "", raising=False)
    rows = [{"maid": "driver", "forensic_flags": _flags("LIKELY_DRIVING")}]

    kept_default, _ = apply_gate(rows, 100.0)
    kept_explicit_none, _ = apply_gate(rows, 100.0, exclude_mask=None)
    assert kept_default == kept_explicit_none == []


def test_gate_is_configurable_by_flag_name(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "MAID_ACCURACY_MODE", "off", raising=False)
    monkeypatch.setattr(config.settings, "MAID_EXCLUDE_FLAGS", "TIMESHIFT", raising=False)

    rows = [
        {"maid": "a", "forensic_flags": _flags("LIKELY_DRIVING")},
        {"maid": "b", "forensic_flags": _flags("TIMESHIFT")},
    ]
    kept, _stats = apply_gate(rows, 100.0)

    # Driving is no longer excluded; TIMESHIFT now is.
    assert [r["maid"] for r in kept] == ["a"]
    assert "TIMESHIFT" in describe_gate()["excluded_flags"]


def test_an_unknown_accuracy_mode_falls_back_loudly(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "MAID_ACCURACY_MODE", "nonsense", raising=False)
    monkeypatch.setattr(config.settings, "MAID_EXCLUDE_FLAGS", "", raising=False)
    assert describe_gate()["accuracy_mode"] == "permissive"


# ── positional mode ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("names,dist_m,kept", [
    (("HIGH_ACCURACY",), 99.0, True),                          # 0-35 m: anywhere inside
    (("MODERATE_ACCURACY", "HIGH_ACCURACY"), 65.0, True),      # 35-50 m: 65 + 35 = 100
    (("MODERATE_ACCURACY", "HIGH_ACCURACY"), 66.0, False),
    (("MODERATE_ACCURACY",), 50.0, True),                      # 50-220 m: 50 + 50 = 100
    (("MODERATE_ACCURACY",), 51.0, False),
    (("LOW_ACCURACY", "MODERATE_ACCURACY"), 0.0, False),       # 220 m+ never fits 100 m
])
def test_positional_uses_where_in_the_ring_the_ping_sits(names, dist_m, kept):
    """Permissive keeps a 50-220 m ping at the ring's edge exactly like a precise
    fix at the door. Positional asks whether even the smallest reported error,
    added to the ping's distance from the centre, still lands inside."""
    assert ping_admitted(
        _flags(*names), 100.0, exclude_mask=0, accuracy_mode="positional", dist_m=dist_m,
    ) is kept


def test_positional_without_a_distance_falls_back_to_permissive():
    flags = _flags("MODERATE_ACCURACY")
    assert ping_admitted(flags, 100.0, exclude_mask=0, accuracy_mode="positional")


def test_apply_gate_reads_each_rows_distance(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "MAID_ACCURACY_MODE", "positional", raising=False)
    monkeypatch.setattr(config.settings, "MAID_EXCLUDE_FLAGS", "", raising=False)
    rows = [
        {"maid": "door", "forensic_flags": _flags("MODERATE_ACCURACY"), "dist_m": 10.0},
        {"maid": "edge", "forensic_flags": _flags("MODERATE_ACCURACY"), "dist_m": 95.0},
    ]
    kept, stats = apply_gate(rows, 100.0)

    assert [r["maid"] for r in kept] == ["door"]
    assert stats["dropped_accuracy"] == 1


# ── key-based attribution ────────────────────────────────────────────────────

def _poi(lat, lng, name, radius_km=0.1, angle="category", ptype="gym"):
    return {
        "lat": lat, "lng": lng, "name": name, "radius_km": radius_km,
        "source_angle": angle, "parent_poi_type": ptype,
    }


def test_attribute_audience_resolves_by_poi_key():
    """The vendor nests each observation under the feature it matched, so the
    POI is a dict lookup, never a geometric scan."""
    from app.graph.maid_query import attribute_audience
    from app.graph.unacast_query import poi_key

    gym = _poi(40.7500, -73.9893, "Gym A", ptype="gym")
    cafe = _poi(40.7359, -73.9911, "Cafe B", ptype="coffee shop")
    pois = [gym, cafe]

    rows = [
        {"maid": "dev-1", "lat": 40.7500, "lng": -73.9893, "count": 1,
         "poi_key": poi_key(gym)},
        {"maid": "dev-1", "lat": 40.7359, "lng": -73.9911, "count": 1,
         "poi_key": poi_key(cafe)},
    ]
    total, kept = attribute_audience(rows, pois, stamp_stats=False)

    assert total == 1, "one device, two places"
    assert kept[0]["poi_ids"] == ["category:gym"]
    assert kept[1]["poi_ids"] == ["category:coffee shop"]
    assert gym["audience_count"] == 1 and cafe["audience_count"] == 1


def test_the_querier_key_resolves_against_the_full_poi():
    """The querier keys features from stripped {lat, lng, radius_km} payloads;
    attribution keys the full POI dict. They used to disagree (the key mixed in
    the place name), so no row ever resolved by key."""
    from app.graph.maid_query import attribute_audience
    from app.graph.unacast_query import poi_key

    gym = _poi(40.7500, -73.9893, "Gym A", radius_km=0.25)
    stripped = {"lat": gym["lat"], "lng": gym["lng"], "radius_km": gym["radius_km"]}
    rows = [{"maid": "dev-1", "lat": 40.75, "lng": -73.9893, "count": 1,
             "poi_key": poi_key(stripped)}]

    total, kept = attribute_audience(rows, [gym], stamp_stats=False)
    assert total == 1 and kept[0]["poi_ids"] == ["category:gym"]


def test_attribute_audience_drops_a_row_whose_poi_was_removed():
    """A POI removed at the confirm gate leaves rows whose key resolves to
    nothing. They are not evidence for this audience any more."""
    from app.graph.maid_query import attribute_audience

    kept_poi = _poi(40.7500, -73.9893, "Gym A")
    rows = [{"maid": "dev-1", "lat": 40.75, "lng": -73.9893, "count": 1,
             "poi_key": "a-key-for-a-poi-that-is-gone"}]
    total, kept = attribute_audience(rows, [kept_poi], stamp_stats=False)

    assert total == 0 and kept == []


def test_a_row_without_attribution_is_never_placed_geometrically():
    """There is no geometric fallback: a ping sitting inside the ring but not
    returned under one of our features is not evidence for the POI."""
    from app.graph.maid_query import attribute_audience

    gym = _poi(40.7500, -73.9893, "Gym A")
    rows = [{"maid": "dev-1", "lat": 40.75001, "lng": -73.98931, "count": 1}]
    total, kept = attribute_audience(rows, [gym], stamp_stats=False)

    assert total == 0 and kept == []


def test_co_located_pois_share_one_purchase():
    """Two POIs at the same coordinates and radius are the same feature, so the
    vendor returns their pings once — and each POI still gets the audience."""
    from app.graph.maid_query import attribute_audience
    from app.graph.unacast_query import poi_key

    gym = _poi(40.7500, -73.9893, "Gym A", ptype="gym")
    spa = _poi(40.7500, -73.9893, "Gym A Spa", ptype="spa")
    rows = [{"maid": "dev-1", "lat": 40.75, "lng": -73.9893, "count": 1,
             "poi_key": poi_key(gym)}]

    total, kept = attribute_audience(rows, [gym, spa], stamp_stats=False)
    assert total == 1
    assert kept[0]["poi_ids"] == ["category:gym", "category:spa"]
    assert gym["audience_count"] == 1 and spa["audience_count"] == 1
