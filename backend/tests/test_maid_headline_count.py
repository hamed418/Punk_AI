"""
tests/test_maid_headline_count.py
─────────────────────────────────
Issue J from the live test: one conversation quoted two different audiences.

The reveal said the "2+ visits" filter narrowed 3,506 visitors to 1,277. The very
next turn — the Meta-connect step — said "You've confirmed the audience of
3,506", because its narration context (wizard_helpers._session_summary) read the
raw superset. Every user-facing count now goes through
maid_query.audience_headline_count.
"""
from app.graph.maid_query import audience_headline_count
from app.graph.wizard_helpers import _session_summary, build_context_facts

_FILTERED = {
    "targeting_method": "deterministic",
    "maid_count": 3506,
    "filtered_maid_count": 1277,
    "audience_filter": {"min_visits": 2, "window_days": 7},
}


def test_the_filtered_count_is_the_headline():
    assert audience_headline_count(_FILTERED) == 1277


def test_without_a_filtered_count_the_superset_is_the_headline():
    assert audience_headline_count({"maid_count": 3506}) == 3506
    assert audience_headline_count({}) is None
    assert audience_headline_count(None) is None


def test_a_filter_that_matched_nobody_is_zero_not_the_superset():
    assert audience_headline_count({"maid_count": 3506, "filtered_maid_count": 0}) == 0


def test_the_meta_connect_summary_quotes_the_filtered_audience():
    summary = _session_summary({"geo_data": _FILTERED})
    assert "1,277 visitors" in summary
    assert "narrowed from 3,506" in summary
    assert "3,506 visitors" not in summary


def test_milestone_facts_carry_the_filtered_audience():
    assert build_context_facts({"geo_data": _FILTERED})["audience_count"] == 1277


# ── repeat-visitor %: per-POI, not summed across POIs ────────────────────────
# The "always ~20%" symptom: compute_visit_stats used to sum a device's visits
# across every POI it appeared at, so a device seen once at each of two
# DIFFERENT places counted as a 2-visit repeat — though it never returned to
# either one. With enough POIs in one search this produced a roughly constant,
# meaningless slice of any audience.

def test_one_visit_at_each_of_two_different_pois_is_not_a_repeat():
    from app.graph.maid_query import compute_visit_stats

    obs = [
        {"maid": "dev-1", "poi_key": "gym", "visits": [{"ts": "t1"}], "days": ["2026-09-01"]},
        {"maid": "dev-1", "poi_key": "cafe", "visits": [{"ts": "t2"}], "days": ["2026-09-05"]},
    ]
    summary = compute_visit_stats(obs)["summary"]
    assert summary["repeat_visitor_count"] == 0
    assert summary["repeat_visitor_pct"] == 0


def test_two_visits_at_the_same_poi_is_a_repeat():
    from app.graph.maid_query import compute_visit_stats

    obs = [
        {"maid": "dev-1", "poi_key": "gym",
         "visits": [{"ts": "t1"}, {"ts": "t2"}], "days": ["2026-09-01", "2026-09-05"]},
    ]
    summary = compute_visit_stats(obs)["summary"]
    assert summary["repeat_visitor_count"] == 1
    assert summary["repeat_visitor_pct"] == 100


def test_a_single_pois_own_stats_are_unaffected_by_the_fix():
    """attribute_audience's per-POI stamp_stats pass calls compute_visit_stats
    over just ONE POI's rows — each device appears at most once there, so sum
    and max are identical and this call's numbers do not change."""
    from app.graph.maid_query import compute_visit_stats

    obs = [
        {"maid": "dev-1", "poi_key": "gym",
         "visits": [{"ts": "t1"}, {"ts": "t2"}, {"ts": "t3"}], "days": ["2026-09-01", "2026-09-05", "2026-09-10"]},
        {"maid": "dev-2", "poi_key": "gym", "visits": [{"ts": "t1"}], "days": ["2026-09-01"]},
    ]
    summary = compute_visit_stats(obs)["summary"]
    assert summary["repeat_visitor_count"] == 1          # dev-1 only
    assert summary["max_seen"] == 3
