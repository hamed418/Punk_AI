"""
tests/test_role_confidence.py
──────────────────────────────
role_confidence() never gates the returned audience — role targeting is
never refused (see AUDIENCE_FILTER_ROLE_GUARD's product decision). It only
decides what the narrator/UI SAY about a role-inferred audience: "low"/
"medium"/"high". This pins that invariant directly, not just in prose: a
role predicate matching 100 devices on THIN operating-day evidence must
still return all 100 — labelled low-confidence, never dropped.

Also covers the presence-pattern predicates themselves (min_open_day_share)
end to end, since role_confidence's inputs come straight out of the same
apply_audience_filter call.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.graph.maid_query import (
    attribute_audience,
    compute_visit_stats,
    is_dwell_only_role_spec,
    is_role_spec,
    role_confidence,
)
from app.services.maid_store import apply_audience_filter, role_signal_stats
from app.graph.unacast_query import poi_key as _poi_key_fn

POI = {
    "name": "Barbershop", "lat": 45.5, "lng": -73.6, "radius_km": 0.1,
    "source_angle": "category", "parent_poi_type": "barbershop",
}
PKEY = _poi_key_fn(POI)


def _visit(day: int, hour: int = 9) -> dict:
    ts = datetime(2026, 9, day, hour, 0, tzinfo=timezone.utc)
    return {
        "ts": ts.isoformat(), "dwell_min": 300, "dwell_lower_s": 300 * 60,
        "n_pings": 2, "gap_s": 20 * 60,
    }


def _row(maid: str, days_present: list[int]) -> dict:
    return {
        "lat": POI["lat"], "lng": POI["lng"], "maid": maid,
        "count": len(days_present), "poi_key": PKEY,
        "visits": [_visit(d) for d in days_present],
        "days": [f"2026-09-{d:02d}" for d in days_present],
    }


# 5 operating days total (1-5) — THIN evidence, < 7, so role_confidence's
# open_days branch must read "low" regardless of yield.
_OPERATING_DAYS = [1, 2, 3, 4, 5]


def _build_rows(n_pass: int, n_fail: int) -> list[dict]:
    """`n_pass` devices present on 3+ of the 5 operating days (clears
    min_open_day_share: 0.5 -> 3/5 = 0.6); `n_fail` present on just 1 day
    each (fails it, ~0.2), cycled across every operating day so the UNION
    of all rows' days — the actual "operating days" denominator — covers
    the full 5-day range regardless of who individually passes."""
    rows = []
    for i in range(n_pass):
        rows.append(_row(f"pass-{i}", _OPERATING_DAYS[:3]))
    for i in range(n_fail):
        rows.append(_row(f"fail-{i}", [_OPERATING_DAYS[i % len(_OPERATING_DAYS)]]))
    return rows


def test_thin_evidence_role_match_is_low_confidence_but_never_dropped():
    rows = _build_rows(n_pass=100, n_fail=100)
    _, attributed = attribute_audience(rows, [POI], stamp_stats=False)

    spec = {"min_open_day_share": 0.5}
    kept = apply_audience_filter(attributed, spec, pois=[POI])

    # The never-refuse invariant: every device that clears the predicate is
    # returned, full stop — role_confidence has not been consulted at all yet.
    assert len(kept) == 100
    assert all(m.startswith("pass-") for m in kept)

    open_days = role_signal_stats()["open_days_observed"]
    assert open_days == 5  # thin: all 5 operating days, still under the 7-day floor

    kept_rows = [r for r in attributed if r["maid"] in set(kept)]
    device_pct = compute_visit_stats(kept_rows)["summary"]["dwell_measurable_device_pct"]
    yield_pct = len(kept) / len(attributed) * 100  # 50% — well over the 15% ceiling too

    conf = role_confidence(open_days, yield_pct, device_pct, spec)
    assert conf == "low"

    # And the invariant this whole test exists to pin: a "low" read changes
    # nothing about what was returned.
    assert len(kept) == 100


def test_solid_evidence_role_match_is_high_confidence():
    """Same shape, but 14+ operating days and a yield inside the ceiling —
    should read as high, proving the ladder isn't just always "low"."""
    days = list(range(1, 21))  # 20 operating days
    rows = []
    # 10 of 200 devices pass (5% yield, under the 15% ceiling) — the
    # fixture's own "owner" archetype weight (maid_fixtures.py) is the same 5%.
    for i in range(10):
        rows.append(_row(f"pass-{i}", days[:15]))  # 15/20 = 0.75 share
    # Fail devices cycled one-day-each across the full range so the UNION of
    # all rows' days covers all 20 operating days, not just day 1.
    for i in range(190):
        rows.append(_row(f"fail-{i}", [days[i % len(days)]]))
    _, attributed = attribute_audience(rows, [POI], stamp_stats=False)

    spec = {"min_open_day_share": 0.5}
    kept = apply_audience_filter(attributed, spec, pois=[POI])
    assert len(kept) == 10

    open_days = role_signal_stats()["open_days_observed"]
    assert open_days == 20

    kept_rows = [r for r in attributed if r["maid"] in set(kept)]
    device_pct = compute_visit_stats(kept_rows)["summary"]["dwell_measurable_device_pct"]
    yield_pct = len(kept) / len(attributed) * 100

    assert role_confidence(open_days, yield_pct, device_pct, spec) == "high"


def test_high_yield_forces_low_confidence_even_with_solid_evidence():
    """A role predicate that keeps MOST of a POI's visitors (a 3-chair
    barbershop cannot have hundreds of "staff") reads low regardless of how
    many operating days back it up — the yield ceiling is a separate trap
    door, not just a tiebreaker."""
    days = list(range(1, 21))
    rows = [_row(f"m-{i}", days[:15]) for i in range(50)]  # everyone clears it
    _, attributed = attribute_audience(rows, [POI], stamp_stats=False)

    spec = {"min_open_day_share": 0.5}
    kept = apply_audience_filter(attributed, spec, pois=[POI])
    assert len(kept) == 50  # never refused, even though this is about to read "low"

    open_days = role_signal_stats()["open_days_observed"]
    yield_pct = len(kept) / len(attributed) * 100
    assert yield_pct == 100.0

    kept_rows = [r for r in attributed if r["maid"] in set(kept)]
    device_pct = compute_visit_stats(kept_rows)["summary"]["dwell_measurable_device_pct"]
    assert role_confidence(open_days, yield_pct, device_pct, spec) == "low"


def test_dwell_only_spec_with_low_device_measurability_is_medium_not_high():
    """A dwell-only (min_weekly_hours) spec whose kept devices are mostly
    single-ping (device_dwell_measurable_pct < 50) gets capped at medium even
    with 14+ operating days — the sparsity this whole feature exists to work
    around should never silently read as a confident dwell measurement."""
    spec = {"min_weekly_hours": 10}
    assert role_confidence(20, 5.0, 30.0, spec) == "medium"
    assert role_confidence(20, 5.0, 70.0, spec) == "high"


def test_is_role_spec_and_is_dwell_only_role_spec():
    assert is_role_spec({"min_weekly_hours": 30})
    assert is_role_spec({"min_open_day_share": 0.5})
    assert is_role_spec({"min_intraday_span_min": 240})
    assert is_role_spec({"min_days_present": 4})
    assert not is_role_spec({"min_visits": 3})
    assert not is_role_spec(None)
    assert is_role_spec({"any_of": [{"min_visits": 3}, {"min_weekly_hours": 30}]})

    assert is_dwell_only_role_spec({"min_weekly_hours": 30})
    assert not is_dwell_only_role_spec({"min_weekly_hours": 30, "min_open_day_share": 0.5})
    assert not is_dwell_only_role_spec({"min_open_day_share": 0.5})
    # any_of: dwell-only only when EVERY branch is.
    assert is_dwell_only_role_spec(
        {"any_of": [{"min_weekly_hours": 30}, {"min_weekly_hours": 20}]}
    )
    assert not is_dwell_only_role_spec(
        {"any_of": [{"min_weekly_hours": 30}, {"min_open_day_share": 0.5}]}
    )
