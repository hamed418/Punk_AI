"""
Regression coverage for the maid_count/filter mismatch report: a map_data
event claimed 6,939 visitors while every dot/tab/per-POI count on the SAME
payload read 0, because the active audience_filter narrowed the real superset
to nobody and the headline number never applied it.

Three things covered here:
  1. build_maid_split_view — the single payload builder shared by
     executors/maid.py, builder_node._maid_confirm_map_event, and
     resume_preflight.maid_map_reemit_event — always reports the FILTERED
     count as maid_count, with the raw superset alongside it.
  2. Production-shaped synthetic data (tests/maid_fixtures.py) can satisfy a
     cadence_days / min_distinct_pois filter, and every synthesized device is
     attributed to its own POI by poi_key.
"""
from maid_fixtures import synth_audience

from app.graph.maid_query import attribute_audience, build_maid_split_view
from app.graph.unacast_query import poi_key
from app.services.maid_store import apply_audience_filter

GYM = {"name": "Gold's Gym", "lat": 45.51, "lng": -73.58, "radius_km": 0.5,
       "source_angle": "category", "parent_poi_type": "gym"}
COFFEE = {"name": "Tim Hortons", "lat": 45.52, "lng": -73.59, "radius_km": 0.5,
          "source_angle": "category", "parent_poi_type": "coffee shop"}
POIS = [GYM, COFFEE]


def _visits(*days: str) -> list[dict]:
    return [
        {"ts": f"{d}T12:00:00+00:00", "dwell_min": 10, "dwell_lower_s": 600,
         "n_pings": 2, "gap_s": 1200}
        for d in days
    ]


# A: gym, 2 visits. B: both venues, 1 visit each. C: coffee, 5 visits.
RAW_OBS = [
    {"lat": GYM["lat"], "lng": GYM["lng"], "maid": "A", "count": 2, "poi_key": poi_key(GYM),
     "days": ["2026-08-01", "2026-08-02"], "visits": _visits("2026-08-01", "2026-08-02")},
    {"lat": GYM["lat"], "lng": GYM["lng"], "maid": "B", "count": 1, "poi_key": poi_key(GYM),
     "days": ["2026-08-03"], "visits": _visits("2026-08-03")},
    {"lat": COFFEE["lat"], "lng": COFFEE["lng"], "maid": "B", "count": 1, "poi_key": poi_key(COFFEE),
     "days": ["2026-08-03"], "visits": _visits("2026-08-03")},
    {"lat": COFFEE["lat"], "lng": COFFEE["lng"], "maid": "C", "count": 5, "poi_key": poi_key(COFFEE),
     "days": ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04", "2026-08-05"],
     "visits": _visits("2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04", "2026-08-05")},
]


def test_an_unevaluable_filter_does_not_crash_the_map():
    """The map payload is rebuilt on every re-emit and reconnect. A stored trend
    filter whose history was never bought used to raise straight through it; it
    now shows the unfiltered audience, the same fallback the extraction takes."""
    view = build_maid_split_view(
        pois=[dict(GYM), dict(COFFEE)],
        observations=[dict(r) for r in RAW_OBS],
        audience_filter={"trend": "lapsed", "window_days": 30, "_history_days_bought": 7},
        center={}, visit_stats=None, search_radius_km=None,
        lookback_days=7, event_date_ranges=[],
    )
    assert view["maid_count"] == view["unfiltered_maid_count"] == 3


def _split_view(**kw):
    return build_maid_split_view(
        pois=[dict(GYM), dict(COFFEE)],
        observations=[dict(r) for r in RAW_OBS],
        center={},
        visit_stats=None,
        search_radius_km=None,
        lookback_days=30,
        event_date_ranges=[],
        **kw,
    )


def test_no_filter_reports_the_full_superset():
    content = _split_view(audience_filter=None)
    assert content["maid_count"] == 3          # A, B, C
    assert content["unfiltered_maid_count"] == 3
    assert content["audience_filter_chips"] == []


def test_narrowing_filter_reports_filtered_count_with_raw_alongside():
    # min_visits=3 keeps only C (5 visits) — A and B each have 2.
    content = _split_view(audience_filter={"min_visits": 3})
    assert content["unfiltered_maid_count"] == 3   # raw superset unaffected
    assert content["maid_count"] == 1              # C only
    assert content["audience_filter_chips"] == ["3+ visits"]


def test_group_filter_narrows_the_map_the_same_way_it_narrows_the_count():
    """Filtering against the RAW (unstamped) observations would silently no-op
    any groups/min_distinct_pois predicate, because those need the `poi_ids`
    attribute_audience stamps. Scoping to the gym group must drop C (coffee
    only) from both the headline count AND every per-POI/tab count."""
    content = _split_view(audience_filter={"groups": ["category:gym"]})
    assert content["unfiltered_maid_count"] == 3
    assert content["maid_count"] == 2   # A, B — both were seen at the gym
    by_name = {p["name"]: p for p in content["pois"]}
    assert by_name["Gold's Gym"]["audience_count"] == 2       # A, B
    assert by_name["Tim Hortons"]["audience_count"] == 1      # B only (C dropped)
    cats = {g["key"]: g for g in content["poi_categories"]}
    assert cats["gym"]["maid_count"] == 2
    assert cats["coffee shop"]["maid_count"] == 1


def test_filter_matching_nobody_reports_zero_not_the_raw_total():
    content = _split_view(audience_filter={"cadence_days": 999})
    assert content["maid_count"] == 0
    assert content["unfiltered_maid_count"] == 3
    for p in content["pois"]:
        assert p["audience_count"] == 0


def test_two_callers_with_the_same_inputs_agree():
    """The whole point of consolidating into one function: the executor's
    initial emit and the maid_confirm re-emit must never disagree again."""
    a = _split_view(audience_filter={"groups": ["category:gym"]})
    b = _split_view(audience_filter={"groups": ["category:gym"]})
    assert a["maid_count"] == b["maid_count"] == 2
    assert a["unfiltered_maid_count"] == b["unfiltered_maid_count"] == 3


# ── Synthetic data: predicates that need real signal ─────────────────────────

_SYNTH_POIS = [
    {"name": f"Spot {i}", "lat": 40.75 + i * 0.01, "lng": -73.98 - i * 0.01,
     "radius_km": 0.045, "source_angle": "competitor_brand", "parent_poi_type": "Sephora"}
    for i in range(20)
]


def test_synth_audience_satisfies_a_monthly_cadence_filter():
    maids, obs = synth_audience(lookback_days=180, pois=_SYNTH_POIS)
    assert maids
    matched = apply_audience_filter(obs, {"cadence_days": 30}, pois=_SYNTH_POIS)
    assert matched, "no synthesized device has a ~30-day visit cadence"


def test_synth_audience_satisfies_a_multi_location_filter():
    # min_distinct_pois reads poi_uids, which only attribute_audience stamps
    # (production runs this pass before ever calling apply_audience_filter —
    # see build_maid_split_view / executors/maid.py's pass-1 attribution).
    maids, obs = synth_audience(lookback_days=180, pois=_SYNTH_POIS)
    _, attributed = attribute_audience([dict(o) for o in obs], [dict(p) for p in _SYNTH_POIS])
    matched = apply_audience_filter(attributed, {"min_distinct_pois": 2}, pois=_SYNTH_POIS)
    assert matched, "no synthesized device visited 2+ distinct POIs"
    assert len(matched) >= 20


def test_every_synthesized_device_is_attributed_to_its_own_poi():
    """Attribution is by poi_key, so every row a POI produced resolves back to
    that POI and no device is lost."""
    maids, obs = synth_audience(lookback_days=30, pois=_SYNTH_POIS)
    total, kept = attribute_audience([dict(o) for o in obs], [dict(p) for p in _SYNTH_POIS])
    assert total == len(set(maids))
    assert len(kept) == len(obs)
