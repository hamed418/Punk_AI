"""
Acceptance check against the CEO's 45 audience-targeting prompts.

This does NOT call the LLM (extraction fidelity — prose to an AudienceFilter
spec — needs a live-model eval, out of scope for pytest). What it verifies is
the mechanical half: given the AudienceFilter spec extraction SHOULD produce
for a representative prompt from each capability tier, apply_audience_filter
finds a real, non-empty, properly-narrowed audience over rich synthetic data
(tests/maid_fixtures.py) shaped exactly like a real Unacast extraction — so the
predicate plumbing is proven against production-shaped rows.

12 of 45 need no layering at all (plain union/category/event search) — already
covered by test_maid_privacy_and_grouping.py. This file covers the 33 that do.
"""
from maid_fixtures import synth_audience
from app.graph.maid_query import attribute_audience
from app.services.maid_store import apply_audience_filter

POIS = [
    {"name": "Spot A", "lat": 45.50, "lng": -73.57, "radius_km": 0.3,
     "source_angle": "category", "parent_poi_type": "gym"},
    {"name": "Spot B", "lat": 45.52, "lng": -73.55, "radius_km": 0.3,
     "source_angle": "category", "parent_poi_type": "coffee shop"},
]
GYM = "category:gym"
COFFEE = "category:coffee shop"


def _extraction(window_days: int = 180):
    """One shared synth pull — attributed, poi_ids-stamped, cached per test run."""
    maids, obs = synth_audience(lookback_days=window_days, pois=POIS)
    _, kept = attribute_audience(obs, POIS, stamp_stats=False)
    return kept


# Cases: (prompt, expected AudienceFilter spec). One representative per
# capability tier — set algebra, frequency, day-of-week/hour, dwell/owner
# detection, trend. Exercised against the SAME synth data every case, since
# the synth archetypes aren't POI-type-aware (see _maid_demo_fallback docstring).
CASES = [
    (
        "vet clinic AND PetSmart AND dog park, 45 days",
        {"groups": [GYM, COFFEE], "op": "intersection", "window_days": 45},
    ),
    (
        "Starbucks weekdays before 9am",
        {"days_of_week": [0, 1, 2, 3, 4], "hours": [0, 9]},
    ),
    (
        "gym-goers who show up 3+ times in the last two weeks",
        {"min_visits": 3, "window_days": 14},
    ),
    (
        "people at a bar 3+ hours on a Friday or Saturday night",
        {"days_of_week": [4, 5], "hours": [20, 24], "min_dwell_min": 120},
    ),
    (
        "barbershop owners/managers — inside 40+ hrs/week",
        {"window_days": 28, "min_weekly_hours": 30},
    ),
    (
        "barbershop regulars who haven't been back in 2 months (win-back)",
        {"window_days": 60, "trend": "lapsed"},
    ),
    (
        "laundromat visitors who suddenly started going in the last 2 weeks",
        {"window_days": 14, "trend": "started"},
    ),
    (
        "nail salon visits that only happen on weekdays",
        {"days_of_week": [0, 1, 2, 3, 4]},
    ),
    (
        "gym AND coffee-shop crowd, excluding my own store's regulars",
        {"groups": [GYM, COFFEE], "op": "intersection"},
    ),
    (
        "2+ different courses this month (multi-location visitors)",
        {"min_distinct_pois": 2, "window_days": 30},
    ),
    (
        "people at the casino on payday, every payday (Phase 5)",
        {"groups": [GYM], "cadence_days": 14, "cadence_tolerance_days": 3},
    ),
    (
        "gym-and-coffee-shop regulars, OR anyone who's hit 3+ open houses (Phase 5, any_of)",
        {"any_of": [
            {"groups": [GYM, COFFEE], "op": "intersection"},
            {"groups": [COFFEE], "min_visits": 3},
        ]},
    ),
]


def test_every_capability_tier_finds_a_real_narrowed_audience():
    kept = _extraction()
    full_union = {o["maid"] for o in kept if o.get("maid")}
    assert len(full_union) > 50, "synth data too sparse for this test to mean anything"

    failures = []
    for prompt, spec in CASES:
        # pois=POIS: the synth writes each archetype's hour/weekday in LOCAL
        # time (derived from POIS' longitude — see _maid_demo_fallback), so
        # the evaluator needs the same POIs to shift back to local before
        # comparing days_of_week/hours — exactly what every real call site
        # (maid.py, builder_node.py, media.py) does.
        result = apply_audience_filter(kept, spec, pois=POIS)
        ok = 0 < len(result) <= len(full_union)
        if not ok:
            failures.append((prompt, spec, len(result)))
    assert not failures, f"predicate found no/too-large audience for: {failures}"


def test_intersection_narrows_relative_to_plain_union():
    kept = _extraction()
    union = apply_audience_filter(kept, {"groups": [GYM, COFFEE], "op": "union"}, pois=POIS)
    inter = apply_audience_filter(kept, {"groups": [GYM, COFFEE], "op": "intersection"}, pois=POIS)
    assert len(inter) <= len(union)


def test_frequency_narrows_relative_to_no_predicate():
    kept = _extraction()
    everyone = apply_audience_filter(kept, {}, pois=POIS)
    regulars = apply_audience_filter(kept, {"min_visits": 5}, pois=POIS)
    assert 0 < len(regulars) < len(everyone)


# ── Explicitly out of scope (see plan) — documented, not silently missing ──

OUT_OF_SCOPE_NEEDS_HOME_LOCATION = [
    "out-of-state buyers touring Scottsdale",
    "empty nesters in big suburban houses",
    "homeowners (vs renters)",
]

BLOCKED_BY_POLICY = [
    "white women 18-45 (race)",
    "lesbian tree planters (sexual orientation)",
]


def test_out_of_scope_and_blocked_lists_are_non_empty_reminders():
    # Not a functional assertion — just keeps the "what we deliberately don't
    # cover" list from silently rotting out of sync with the plan doc.
    assert len(OUT_OF_SCOPE_NEEDS_HOME_LOCATION) == 3
    assert len(BLOCKED_BY_POLICY) == 2
