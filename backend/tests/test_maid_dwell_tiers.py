"""
tests/test_maid_dwell_tiers.py
──────────────────────────────
Dwell is an INTERVAL with a measurability tier, not a point estimate.

`cluster_visits` used to record `dwell_min = max(1, last - first)`, so a
single-ping visit — where the duration is genuinely unknown — was stored as a
measured 60 seconds. Measured on 287,000 real pings, **46.6% of visits are
single-ping** (docs/maid_signal_quality_baseline.md §4), so that fabrication
covered nearly half the data and fed straight into `min_dwell_min` and
`min_weekly_hours`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.graph.maid_query import cluster_visits, visit_is_timed
from app.services.maid_store import apply_audience_filter


def _iso(minute: int, day: int = 1) -> str:
    return datetime(2026, 9, day, 12, 0, tzinfo=timezone.utc).replace(
        minute=0
    ).__add__(timedelta(minutes=minute)).isoformat()


# ── sessionization ───────────────────────────────────────────────────────────

def test_pings_within_the_gap_are_one_visit():
    visits = cluster_visits([_iso(0), _iso(5), _iso(12)])
    assert len(visits) == 1
    assert visits[0]["n_pings"] == 3
    assert visits[0]["dwell_lower_s"] == 12 * 60


def test_a_gap_beyond_the_threshold_splits_the_visit():
    visits = cluster_visits([_iso(0), _iso(25)])
    assert len(visits) == 2
    assert all(v["n_pings"] == 1 for v in visits)


def test_the_chain_is_transitive():
    """Pings at 0/19/38/57 are ONE 57-minute visit even though the endpoints are
    an hour apart. Correct for a continuous stay, wrong for a device drifting
    through — `n_pings` and `dwell_lower_s` are what let a reader tell them
    apart, so this behaviour is pinned rather than "fixed"."""
    visits = cluster_visits([_iso(0), _iso(19), _iso(38), _iso(57)])
    assert len(visits) == 1
    assert visits[0]["dwell_lower_s"] == 57 * 60


# ── dwell bounds ─────────────────────────────────────────────────────────────

def test_single_ping_dwell_is_zero_not_one_minute():
    """The whole point. An unmeasured visit must not look like a measured
    short one."""
    visits = cluster_visits([_iso(0)])
    assert visits[0]["dwell_lower_s"] == 0
    assert visits[0]["dwell_min"] == 0
    assert visits[0]["n_pings"] == 1
    assert not visit_is_timed(visits[0])


def test_two_pings_make_dwell_measurable():
    visits = cluster_visits([_iso(0), _iso(10)])
    assert visits[0]["dwell_lower_s"] == 600
    assert visit_is_timed(visits[0])


def test_upper_bound_uses_the_devices_pings_at_other_places():
    """The device left before its next ping ANYWHERE. A ping at a different POI
    is exactly as good a bound as one at the same POI, and is often the only
    one available."""
    here = [_iso(0), _iso(10)]
    # Same device seen elsewhere at minute -5 and minute 30.
    timeline = sorted(
        datetime.fromisoformat(t)
        for t in (_iso(-5), _iso(0), _iso(10), _iso(30))
    )
    visits = cluster_visits(here, device_timeline=timeline)

    assert visits[0]["dwell_lower_s"] == 600            # observed 10 min
    assert visits[0]["dwell_upper_s"] == 35 * 60        # -5 min .. +30 min
    assert visits[0]["dwell_upper_s"] > visits[0]["dwell_lower_s"]


def test_upper_bound_falls_back_to_the_gap_without_a_timeline():
    visits = cluster_visits([_iso(0), _iso(10)])
    # No neighbouring pings: bounded by one gap either side.
    assert visits[0]["dwell_upper_s"] == (10 + 20 + 20) * 60


def test_upper_bound_is_never_below_the_lower_bound():
    visits = cluster_visits([_iso(0), _iso(10)], device_timeline=[])
    assert visits[0]["dwell_upper_s"] >= visits[0]["dwell_lower_s"]


# ── legacy data ──────────────────────────────────────────────────────────────

def test_a_visit_without_n_pings_is_not_measurable():
    """Every visit cluster_visits builds carries n_pings. One without it has no
    evidence of how long the device stayed, so it is never treated as measured."""
    assert not visit_is_timed({"ts": _iso(0), "dwell_min": 45})
    assert visit_is_timed({"ts": _iso(0), "dwell_min": 45, "n_pings": 2})


# ── the predicates ───────────────────────────────────────────────────────────

def _obs(visits: list[dict], maid: str = "dev-1") -> dict:
    return {
        "maid": maid, "lat": 40.75, "lng": -73.98, "count": len(visits),
        "poi_ids": ["category:bar"], "poi_uids": ["40.75,-73.98"],
        "visits": visits,
        "days": sorted({v["ts"][:10] for v in visits}),
    }


def test_min_dwell_min_excludes_unmeasurable_visits():
    """A single-ping visit cannot clear a dwell floor — there is no duration to
    compare. Previously it carried a fabricated 1 minute."""
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=2)).isoformat()

    measured = _obs([{"ts": recent, "dwell_lower_s": 4 * 3600, "n_pings": 6}], "measured")
    unmeasured = _obs([{"ts": recent, "dwell_lower_s": 0, "n_pings": 1}], "unmeasured")

    keep = apply_audience_filter(
        [measured, unmeasured], {"min_dwell_min": 180}, pois=[{"lng": -73.98}]
    )
    assert keep == ["measured"]


def test_min_weekly_hours_sums_only_measured_dwell():
    """Summing a fabricated minute for each single-ping visit put invented time
    into a threshold the user stated in real hours."""
    now = datetime.now(timezone.utc)
    visits = [
        {"ts": (now - timedelta(days=d)).isoformat(),
         "dwell_lower_s": 8 * 3600, "n_pings": 20}
        for d in range(1, 6)
    ] + [
        # 200 single-ping visits: 200 fabricated minutes under the old rule.
        {"ts": (now - timedelta(days=1, minutes=m)).isoformat(),
         "dwell_lower_s": 0, "n_pings": 1}
        for m in range(200)
    ]
    staff = _obs(visits, "staff")

    keep = apply_audience_filter(
        [staff], {"min_weekly_hours": 30, "window_days": 7}, pois=[{"lng": -73.98}]
    )
    assert keep == ["staff"], "40 measured hours over 7 days must clear 30/week"

    keep_high = apply_audience_filter(
        [staff], {"min_weekly_hours": 45, "window_days": 7}, pois=[{"lng": -73.98}]
    )
    assert keep_high == [], "the fabricated single-ping minutes must not top it up"


# ── dwell_bound: lower (default) vs upper (opt-in) ──────────────────────────

def test_dwell_bound_upper_admits_a_visit_the_lower_bound_misses():
    """Two pings 10 min apart, but the device's OWN timeline shows it arrived
    much earlier and left much later — the true stay is ~3 hours. The lower
    bound (default) sees only the observed 10 min and fails a 120-min floor;
    dwell_bound='upper' reads the real bound cluster_visits already computed."""
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(hours=2)).isoformat()
    visit = {"ts": ts, "dwell_lower_s": 600, "dwell_upper_s": 10800, "n_pings": 2}
    dev = _obs([visit], "brief-pings-long-stay")

    default = apply_audience_filter(
        [dev], {"min_dwell_min": 120}, pois=[{"lng": -73.98}]
    )
    assert default == [], "lower bound (default, unchanged) must still fail"

    upper = apply_audience_filter(
        [dev], {"min_dwell_min": 120, "dwell_bound": "upper"}, pois=[{"lng": -73.98}]
    )
    assert upper == ["brief-pings-long-stay"]


def test_dwell_bound_defaults_to_lower_when_absent_or_unknown():
    """Absent, and an unrecognized value, both fall back to today's behaviour
    — 'lower' is not conditional on the key being spelled out."""
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(hours=2)).isoformat()
    visit = {"ts": ts, "dwell_lower_s": 600, "dwell_upper_s": 10800, "n_pings": 2}
    dev = _obs([visit], "dev")

    no_key = apply_audience_filter([dev], {"min_dwell_min": 120}, pois=[{"lng": -73.98}])
    explicit_lower = apply_audience_filter(
        [dev], {"min_dwell_min": 120, "dwell_bound": "lower"}, pois=[{"lng": -73.98}]
    )
    assert no_key == explicit_lower == []


def test_dwell_bound_upper_feeds_min_weekly_hours_too():
    """The same opt-in applies to the min_weekly_hours sum, not just
    min_dwell_min — both read _dwell_seconds through the same dwell_bound."""
    now = datetime.now(timezone.utc)
    # 5 visits/week, each observed as a brief 20-min ping-pair but bounded by
    # the device's own timeline at ~6 hours — enough to clear 25 hrs/week only
    # under the upper bound.
    visits = [
        {"ts": (now - timedelta(days=d)).isoformat(),
         "dwell_lower_s": 1200, "dwell_upper_s": 6 * 3600, "n_pings": 2}
        for d in range(1, 6)
    ]
    dev = _obs(visits, "brief-pings")

    lower = apply_audience_filter(
        [dev], {"min_weekly_hours": 25, "window_days": 7}, pois=[{"lng": -73.98}]
    )
    assert lower == [], "5 * 20 observed minutes/week cannot clear 25 hrs/week"

    upper = apply_audience_filter(
        [dev], {"min_weekly_hours": 25, "window_days": 7, "dwell_bound": "upper"},
        pois=[{"lng": -73.98}],
    )
    assert upper == ["brief-pings"], "5 * 6 bounded hours/week clears 25 hrs/week"


def test_min_dwell_min_needs_a_measured_dwell():
    """A visit carrying only a whole-minute dwell_min, with no ping evidence
    (n_pings) or measured span (dwell_lower_s), has no measured duration and
    cannot clear a dwell floor."""
    now = datetime.now(timezone.utc)
    unmeasured = _obs(
        [{"ts": (now - timedelta(hours=3)).isoformat(), "dwell_min": 240}], "unmeasured"
    )
    keep = apply_audience_filter(
        [unmeasured], {"min_dwell_min": 180}, pois=[{"lng": -73.98}]
    )
    assert keep == []
