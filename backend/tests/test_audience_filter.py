"""
Unit tests for maid_store.apply_audience_filter / resolve_group_labels — the
audience-layering evaluator (day-of-week, hour, dwell, frequency, trend,
boolean set logic across POI groups). No LLM, no DB — pure functions over
hand-built observation rows shaped like the real attribute_audience output:
{maid, poi_ids, count, visits}.
"""
from datetime import datetime, timedelta, timezone

from app.services.maid_store import (
    apply_audience_filter,
    describe_audience_filter,
    fold_audience_filter_specs,
    resolve_group_labels,
    resolve_group_labels_verbose,
    scope_exclusion_to_named_groups,
)

NOW = datetime.now(timezone.utc)


def _v(days_ago: float, dwell_min: int = 10) -> dict:
    """One visit shaped like cluster_visits' output — measured (2+ pings)."""
    return {
        "ts": (NOW - timedelta(days=days_ago)).isoformat(),
        "dwell_min": dwell_min,
        "dwell_lower_s": dwell_min * 60,
        "n_pings": 2,
    }


def _row(
    maid: str, poi_ids: list[str], visits: list[dict] | None = None, count: int | None = None,
    poi_uids: list[str] | None = None,
) -> dict:
    row = {"lat": 45.5, "lng": -73.5, "maid": maid, "poi_ids": poi_ids}
    if poi_uids is not None:
        row["poi_uids"] = poi_uids
    if visits is not None:
        row["visits"] = visits
        row["count"] = count if count is not None else len(visits)
    elif count is not None:
        row["count"] = count
    return row


GYM = "category:gym"
COFFEE = "category:coffee shop"
# Matches what executors/geo.py actually stamps a store_set POI with
# (parent_poi_type="my stores") — see poi_group_id / group_pois_by_category.
STORE = "store_set:my stores"


def test_empty_spec_returns_full_union():
    rows = [_row("A", [GYM]), _row("B", [COFFEE])]
    assert apply_audience_filter(rows, None) == ["A", "B"]
    assert apply_audience_filter(rows, {}) == ["A", "B"]


def test_groups_default_union():
    rows = [_row("A", [GYM]), _row("B", [COFFEE]), _row("C", [STORE])]
    result = apply_audience_filter(rows, {"groups": [GYM, COFFEE]})
    assert result == ["A", "B"]


def test_groups_intersection():
    # An intersection needs one visit per group, not overlapping in time — a
    # device cannot be in two places at once.
    rows = [
        _row("A", [GYM], visits=[_v(1)]),                                       # gym only
        _row("B", [GYM], visits=[_v(1)]), _row("B", [COFFEE], visits=[_v(2)]),  # both
        _row("C", [COFFEE], visits=[_v(2)]),                                    # coffee only
    ]
    result = apply_audience_filter(rows, {"groups": [GYM, COFFEE], "op": "intersection"})
    assert result == ["B"]


def test_groups_difference():
    rows = [
        _row("A", [GYM]),
        _row("B", [GYM]), _row("B", [COFFEE]),
        _row("C", [COFFEE]),
    ]
    result = apply_audience_filter(rows, {"groups": [GYM, COFFEE], "op": "difference"})
    assert result == ["A"]  # gym, not coffee


def test_exclude_groups_drops_devices_seen_there():
    rows = [_row("A", [GYM]), _row("B", [GYM]), _row("B", [STORE])]
    result = apply_audience_filter(rows, {"groups": [GYM], "exclude_groups": [STORE]})
    assert result == ["A"]


# ── scope_exclusion_to_named_groups: don't let an exclusion POI widen the
# positive audience ──────────────────────────────────────────────────────────
#
# `_apply_clause` treats an unset `groups` as "match every device in the
# pool" — a POI collected ONLY to be excluded (the user's own store, pulled
# in solely so "my store" resolves) would otherwise ALSO count as a positive
# targeting source before being subtracted back out. `scope_exclusion_to_
# named_groups` is the deterministic guard: it runs regardless of whether the
# LLM remembered to emit an explicit `groups` list.

_ALL_POIS = [
    {"lat": 1.0, "lng": 1.0, "source_angle": "category", "parent_poi_type": "gym"},
    {"lat": 1.0, "lng": 1.0, "source_angle": "category", "parent_poi_type": "coffee shop"},
    {"lat": 1.0, "lng": 1.0, "source_angle": "store_set", "parent_poi_type": "my stores"},
]


def test_exclusion_clause_gets_explicit_positive_groups():
    clause = {"exclude_groups": [STORE]}
    scoped = scope_exclusion_to_named_groups(clause, _ALL_POIS)
    assert set(scoped["groups"]) == {GYM, COFFEE}
    assert scoped["exclude_groups"] == [STORE]


def test_min_visits_not_inflated_by_excluded_pois():
    """Without the guard, an unset `groups` means a store-only visitor (C)
    would count toward `min_visits`'s TOTAL-across-the-clause pool before
    `exclude_groups` removes them — the guard prevents them entering the
    pool in the first place, not just the final device set."""
    rows = [
        _row("A", [GYM], visits=[_v(1), _v(2)]),          # 2 gym visits — qualifies alone
        _row("B", [GYM], visits=[_v(1)]),                  # 1 gym visit — short of 2 alone
        _row("B", [STORE], visits=[_v(1)]),                # ...but also a store visit
    ]
    clause = scope_exclusion_to_named_groups(
        {"exclude_groups": [STORE], "min_visits": 2}, [
            {"lat": 1.0, "lng": 1.0, "source_angle": "category", "parent_poi_type": "gym"},
            {"lat": 1.0, "lng": 1.0, "source_angle": "store_set", "parent_poi_type": "my stores"},
        ],
    )
    result = apply_audience_filter(rows, clause)
    assert result == ["A"]  # B's store visit must not count toward its min_visits total


def test_guard_leaves_intersection_and_difference_alone():
    """A malformed `{"op": "intersection", "exclude_groups": [...]}` with no
    `groups` already degrades to union in `_apply_clause` — filling `groups`
    in here would turn that into a REAL intersection across every group in
    the pool, almost certainly matching nobody. The guard must not
    re-interpret a spec the LLM got wrong."""
    for op in ("intersection", "difference"):
        clause = {"exclude_groups": [STORE], "op": op}
        scoped = scope_exclusion_to_named_groups(clause, _ALL_POIS)
        assert scoped == clause


def test_guard_is_a_noop_when_groups_already_set():
    clause = {"groups": [GYM], "exclude_groups": [STORE]}
    assert scope_exclusion_to_named_groups(clause, _ALL_POIS) == clause


def test_guard_is_a_noop_without_exclude_groups():
    clause = {"groups": [GYM]}
    assert scope_exclusion_to_named_groups(clause, _ALL_POIS) == clause


def test_guard_also_scopes_a_non_store_exclusion():
    """The widening bug (and its fix) is not store-specific — ANY POI
    collected only to be excluded has the same problem: "target gym-goers,
    exclude people who also go to Starbucks" needs `groups` pinned to gym
    just as much as the store case does. `exclude_groups` need not be a
    self-reference for this guard to matter."""
    pois = [
        {"lat": 1.0, "lng": 1.0, "source_angle": "category", "parent_poi_type": "gym"},
        {"lat": 1.0, "lng": 1.0, "source_angle": "competitor_brand", "parent_poi_type": "Starbucks"},
    ]
    clause = scope_exclusion_to_named_groups(
        {"exclude_groups": ["competitor_brand:Starbucks"]}, pois,
    )
    assert clause["groups"] == ["category:gym"]

    rows = [
        {"maid": "A", "poi_ids": ["category:gym"]},
        {"maid": "B", "poi_ids": ["category:gym", "competitor_brand:Starbucks"]},
        {"maid": "C", "poi_ids": ["competitor_brand:Starbucks"]},  # Starbucks only
    ]
    result = apply_audience_filter(rows, clause)
    assert result == ["A"]  # B excluded (also went to Starbucks); C never a gym visitor anyway


def test_unknown_op_raises():
    import pytest
    with pytest.raises(ValueError):
        apply_audience_filter([_row("A", [GYM])], {"groups": [GYM], "op": "xor"})


def test_window_days_recency():
    rows = [
        _row("recent", [GYM], visits=[_v(2)]),
        _row("stale", [GYM], visits=[_v(90)]),
    ]
    result = apply_audience_filter(rows, {"window_days": 30})
    assert result == ["recent"]


def test_days_of_week_weekends():
    # Anchor a known Saturday and Tuesday relative to "now" isn't reliable
    # across run dates, so walk backward from NOW to find one of each.
    def _last(weekday: int) -> float:
        d = 0
        while (NOW - timedelta(days=d)).weekday() != weekday:
            d += 1
        return d

    sat_ago = _last(5)
    tue_ago = _last(1)
    rows = [
        _row("weekender", [GYM], visits=[_v(sat_ago)]),
        _row("weekdayer", [GYM], visits=[_v(tue_ago)]),
    ]
    result = apply_audience_filter(rows, {"days_of_week": [5, 6]})
    assert result == ["weekender"]


def test_hours_before_9am():
    early = NOW.replace(hour=7, minute=30)
    late = NOW.replace(hour=14, minute=0)
    rows = [
        _row("commuter", [GYM], visits=[{"ts": early.isoformat(), "dwell_min": 10}]),
        _row("afternoon", [GYM], visits=[{"ts": late.isoformat(), "dwell_min": 10}]),
    ]
    result = apply_audience_filter(rows, {"hours": [0, 9]})
    assert result == ["commuter"]


def test_min_dwell_min():
    rows = [
        _row("long", [GYM], visits=[_v(1, dwell_min=200)]),
        _row("short", [GYM], visits=[_v(1, dwell_min=10)]),
    ]
    result = apply_audience_filter(rows, {"min_dwell_min": 180})
    assert result == ["long"]


def test_min_visits_with_timestamps():
    rows = [
        _row("frequent", [GYM], visits=[_v(1), _v(3), _v(5)]),
        _row("rare", [GYM], visits=[_v(1)]),
    ]
    result = apply_audience_filter(rows, {"min_visits": 3})
    assert result == ["frequent"]


def test_a_row_without_visits_never_counts_as_visited():
    # A raw ping count is not a visit count. Every real row carries clustered
    # visits; one without them has no evidence of a visit at all.
    rows = [_row("A", [GYM], count=5), _row("B", [GYM], count=1)]
    assert apply_audience_filter(rows, {"min_visits": 3}) == []


def test_min_distinct_pois():
    # Rows without poi_uids count distinct GROUPS.
    rows = [
        _row("multi", [GYM]), _row("multi", [COFFEE]),
        _row("single", [GYM]),
    ]
    result = apply_audience_filter(rows, {"min_distinct_pois": 2})
    assert result == ["multi"]


def test_min_distinct_pois_same_chain_different_outlets():
    # Real franchise case: SAME brand group, DIFFERENT physical outlets —
    # must count by poi_uids (place), not poi_ids (group), or "2 locations of
    # the same chain" can never match (every outlet shares one group id).
    CHAIN = "competitor_brand:Tim Hortons"
    rows = [
        _row("manager", [CHAIN], poi_uids=["45.50,-73.57"]),
        _row("manager", [CHAIN], poi_uids=["45.51,-73.58"]),
        _row("regular", [CHAIN], poi_uids=["45.50,-73.57"]),
    ]
    result = apply_audience_filter(rows, {"min_distinct_pois": 2})
    assert result == ["manager"]


def test_min_weekly_hours_owner_signal():
    # ~9h/day, 5 days/week for 4 weeks -> way over 40 hrs/week.
    owner_visits = [_v(d, dwell_min=540) for d in range(0, 28, 1) if (NOW - timedelta(days=d)).weekday() < 5]
    rows = [
        _row("owner", [STORE], visits=owner_visits),
        _row("customer", [STORE], visits=[_v(1, dwell_min=20)]),
    ]
    result = apply_audience_filter(rows, {"window_days": 28, "min_weekly_hours": 40})
    assert result == ["owner"]


def test_trend_lapsed():
    rows = [
        _row("lapsed", [GYM], visits=[_v(45), _v(50)]),   # only in the older window
        _row("active", [GYM], visits=[_v(2), _v(5)]),      # recent
    ]
    result = apply_audience_filter(rows, {"window_days": 30, "trend": "lapsed"})
    assert result == ["lapsed"]


def test_trend_started():
    rows = [
        _row("new", [GYM], visits=[_v(2)]),                 # only recent
        _row("longtime", [GYM], visits=[_v(2), _v(50)]),     # recent AND old
    ]
    result = apply_audience_filter(rows, {"window_days": 30, "trend": "started"})
    assert result == ["new"]


def test_time_predicate_excludes_rows_with_no_timestamp():
    rows = [_row("A", [GYM], count=3)]  # no `visits` at all
    assert apply_audience_filter(rows, {"days_of_week": [0, 1]}) == []
    # A visit count cannot come from pings either.
    assert apply_audience_filter(rows, {"min_visits": 1}) == []


def test_intersection_is_subset_of_union():
    rows = [
        _row("A", [GYM], visits=[_v(1)]),
        _row("B", [GYM], visits=[_v(1)]), _row("B", [COFFEE], visits=[_v(2)]),
        _row("C", [COFFEE], visits=[_v(2)]),
    ]
    union = set(apply_audience_filter(rows, {"groups": [GYM, COFFEE], "op": "union"}))
    inter = set(apply_audience_filter(rows, {"groups": [GYM, COFFEE], "op": "intersection"}))
    assert inter == {"B"}
    assert inter <= union


def test_cadence_matches_regular_interval():
    # Visits roughly every 14 days over ~2 months -> 4 gaps, all ~14d.
    rows = [_row("payday", [GYM], visits=[_v(d) for d in (2, 16, 30, 44, 58)])]
    result = apply_audience_filter(rows, {"cadence_days": 14, "cadence_tolerance_days": 3})
    assert result == ["payday"]


def test_cadence_rejects_irregular_visits():
    rows = [_row("random", [GYM], visits=[_v(d) for d in (1, 3, 20, 21, 55)])]
    result = apply_audience_filter(rows, {"cadence_days": 14, "cadence_tolerance_days": 3})
    assert result == []


def test_cadence_default_tolerance_is_lenient_but_bounded():
    # No explicit tolerance -> ~20% of 30 = 6 days. 28-day gaps qualify (within 6).
    rows = [_row("monthlyish", [GYM], visits=[_v(d) for d in (2, 30, 58, 86)])]
    result = apply_audience_filter(rows, {"cadence_days": 30})
    assert result == ["monthlyish"]


def test_any_of_unions_independent_clauses():
    rows = [
        _row("A", [GYM], visits=[_v(1), _v(3), _v(5)]),   # 3+ gym visits
        _row("B", [COFFEE], count=1),                       # single coffee visit — qualifies clause 2? no, needs union
        _row("C", [STORE], count=1),                        # matches neither
    ]
    spec = {"any_of": [
        {"groups": [GYM], "min_visits": 3},
        {"groups": [COFFEE]},
    ]}
    result = apply_audience_filter(rows, spec)
    assert result == ["A", "B"]


def test_any_of_with_one_clause_matches_flat_call():
    rows = [_row("A", [GYM]), _row("B", [COFFEE])]
    flat = apply_audience_filter(rows, {"groups": [GYM]})
    wrapped = apply_audience_filter(rows, {"any_of": [{"groups": [GYM]}]})
    assert flat == wrapped == ["A"]


def test_resolve_group_labels_exact_and_substring():
    pois = [
        {"lat": 1, "lng": 1, "source_angle": "category", "parent_poi_type": "gym"},
        {"lat": 2, "lng": 2, "source_angle": "competitor_brand", "brand": "Starbucks"},
    ]
    assert resolve_group_labels(["gym"], pois) == [GYM]
    assert resolve_group_labels(["starbucks"], pois) == ["competitor_brand:Starbucks"]
    assert resolve_group_labels(["nonexistent place"], pois) == []


def test_resolve_group_labels_verbose_reports_misses():
    # Regression for the "both SneakerCon and Flight Club" bug: SneakerCon
    # never resolved to a POI and was silently dropped, collapsing an
    # intersection of two groups into a plain match on the one that did.
    pois = [
        {"lat": 1, "lng": 1, "source_angle": "named_places", "parent_poi_type": "Flight Club"},
    ]
    resolved, missing = resolve_group_labels_verbose(["Flight Club", "SneakerCon"], pois)
    assert resolved == ["named_places:Flight Club"]
    assert missing == ["SneakerCon"]
    # A label that DOES match is never reported as missing.
    resolved, missing = resolve_group_labels_verbose(["Flight Club"], pois)
    assert resolved == ["named_places:Flight Club"]
    assert missing == []
    # resolve_group_labels (thin wrapper) still returns just the resolved ids.
    assert resolve_group_labels(["Flight Club", "SneakerCon"], pois) == ["named_places:Flight Club"]


def test_describe_audience_filter_unresolved_group_chip():
    spec = {"op": "intersection", "_unresolved_groups": ["SneakerCon"]}
    assert "SneakerCon: not found" in describe_audience_filter(spec)


# ── Local time (the POIs' real IANA zone) ───────────────────────────────────

def test_hours_uses_local_time_when_pois_given():
    # (45.5, -75.0) resolves to America/Toronto — UTC-5 in winter, UTC-4 in summer.
    pois = [{"lat": 45.5, "lng": -75.0}]
    utc_evening = NOW.replace(hour=23, minute=0, second=0, microsecond=0)
    rows = [_row("evening", [GYM], visits=[{"ts": utc_evening.isoformat(), "dwell_min": 10}])]

    # 23:00 UTC is NOT in [17,22) when read raw (no pois -> no shift)
    assert apply_audience_filter(rows, {"hours": [17, 22]}) == []
    # 23:00 UTC is 18:00 or 19:00 in Toronto, which IS in [17,22)
    assert apply_audience_filter(rows, {"hours": [17, 22]}, pois=pois) == ["evening"]


def test_days_of_week_uses_local_time_when_pois_given():
    pois = [{"lat": 45.5, "lng": -75.0}]
    days_ahead = (5 - NOW.weekday()) % 7  # next Saturday
    sat_early_utc = (NOW + timedelta(days=days_ahead)).replace(hour=1, minute=0, second=0, microsecond=0)
    rows = [_row("fri_night", [GYM], visits=[{"ts": sat_early_utc.isoformat(), "dwell_min": 10}])]

    # Raw UTC weekday is Saturday(5) -> matches [5,6] with no shift
    assert apply_audience_filter(rows, {"days_of_week": [5, 6]}) == ["fri_night"]
    # In Toronto it is still Friday evening -> weekday 4, NOT in [5,6]
    assert apply_audience_filter(rows, {"days_of_week": [5, 6]}, pois=pois) == []
    # ...but IS in [4] once shifted to local
    assert apply_audience_filter(rows, {"days_of_week": [4]}, pois=pois) == ["fri_night"]


def test_invert_flips_the_matching_set():
    owner_visits = [_v(d, dwell_min=540) for d in range(0, 28, 1) if (NOW - timedelta(days=d)).weekday() < 5]
    rows = [
        _row("owner", [STORE], visits=owner_visits),
        _row("customer", [STORE], visits=[_v(1, dwell_min=20)]),
    ]
    spec = {"window_days": 28, "min_weekly_hours": 40}
    selected = apply_audience_filter(rows, spec)
    dropped = apply_audience_filter(rows, {**spec, "invert": True})
    assert selected == ["owner"]
    assert dropped == ["customer"]
    # partition, no overlap, nothing lost
    assert set(selected) | set(dropped) == {"owner", "customer"}
    assert not (set(selected) & set(dropped))


def test_rows_without_visits_never_satisfy_a_time_predicate():
    # A time predicate needs visit timestamps; a row without them is excluded,
    # never guessed at.
    rows = [_row("A", [GYM], count=5), _row("B", [GYM], count=1)]
    assert apply_audience_filter(rows, {"hours": [17, 20]}) == []


def test_synth_audience_local_archetypes_match_their_own_declared_hours():
    """Load-bearing: the test fixture and the evaluator must agree on what
    'local' means, or every hour/day-of-week test silently mismatches."""
    import random as _random

    from maid_fixtures import synth_audience

    _random.seed(1234)
    pois = [{"lat": 45.5, "lng": -73.5, "radius_km": 0.5}]  # Montreal
    _maids, obs = synth_audience(lookback_days=30, pois=pois)

    commuters = apply_audience_filter(
        obs, {"hours": [6, 9], "days_of_week": [0, 1, 2, 3, 4]}, pois=pois,
    )
    weekenders = apply_audience_filter(
        obs, {"hours": [20, 24], "days_of_week": [4, 5]}, pois=pois,
    )
    assert commuters, "no device matched the commuter archetype's own declared local hours"
    assert weekenders, "no device matched the weekender archetype's own declared local hours"


# ── describe_audience_filter (UI chips) ──────────────────────────────────────

def test_describe_audience_filter_empty_spec_is_no_chips():
    assert describe_audience_filter(None) == []
    assert describe_audience_filter({}) == []


def test_describe_audience_filter_readable_chips():
    chips = describe_audience_filter({"min_visits": 3, "window_days": 14, "days_of_week": [5, 6]})
    assert "3+ visits" in chips
    assert "last 14d" in chips
    assert "weekends" in chips


def test_describe_audience_filter_invert_prefixes_excluding():
    chips = describe_audience_filter({"min_weekly_hours": 30, "invert": True})
    assert chips[0] == "excluding:"
    assert "30+ hrs/week" in chips


def test_describe_audience_filter_exclusion_chip_states_the_real_window():
    """exclude_window_days never widens the history purchase (see
    maid_history._clause_history_days) — the chip must say what was actually
    checked, never imply "never" when only N days were bought."""
    assert "excluding past visitors (within data bought)" in describe_audience_filter(
        {"exclude_groups": [STORE], "exclude_window_days": 0}
    )
    assert "excluding visitors from the last 30d" in describe_audience_filter(
        {"exclude_groups": [STORE], "exclude_window_days": 30}
    )
    assert "excluding visitors from the last 14d" in describe_audience_filter(
        {"exclude_groups": [STORE], "window_days": 14}
    )
    assert "excluding past visitors" in describe_audience_filter({"exclude_groups": [STORE]})


def test_describe_audience_filter_unresolved_exclude_chip_is_distinct():
    chips = describe_audience_filter({"_unresolved_exclude_groups": ["my store"]})
    assert "my store: exclusion not applied" in chips


# ── fold_audience_filter_specs — the merge algebra, previously untested ────────
# This is the ordered-patch-history fold builder_node._apply_maid_audience_
# filter_edit / undo() replay against. Pulled out here so the shallow-merge /
# None-clears / any_of-wholesale-replace rules are directly testable — before
# this it lived inline and none of these edge cases had a test at all.

def test_fold_empty_specs_is_empty_filter():
    assert fold_audience_filter_specs([]) == {}


def test_fold_single_patch_is_itself_plus_resolved_marker():
    out = fold_audience_filter_specs([{"min_visits": 2}])
    assert out == {"min_visits": 2, "_resolved": True}


def test_fold_later_patch_overwrites_same_key():
    # "3+ visits" then "actually just 1+" — the SECOND value wins, not a merge
    # of both, and the fold does this by replaying the whole history, not by
    # patching a stale stored dict.
    out = fold_audience_filter_specs([{"min_visits": 3}, {"min_visits": 1}])
    assert out["min_visits"] == 1


def test_fold_none_clears_a_previously_set_key():
    out = fold_audience_filter_specs([{"min_visits": 3}, {"min_visits": None}])
    assert "min_visits" not in out


def test_fold_accumulates_different_keys_across_patches():
    out = fold_audience_filter_specs([{"min_visits": 2}, {"days_of_week": [5, 6]}])
    assert out["min_visits"] == 2
    assert out["days_of_week"] == [5, 6]


def test_fold_any_of_replaces_the_whole_filter_not_merges():
    """The sharpest edge: introducing `any_of` after flat keys were already
    set discards those flat keys entirely — any_of can't coexist with them on
    the same filter object (AudienceFilterSpec's own contract)."""
    specs = [
        {"min_visits": 5, "window_days": 30},
        {"any_of": [{"min_visits": 2}, {"days_of_week": [5, 6]}]},
    ]
    out = fold_audience_filter_specs(specs)
    assert "min_visits" not in out
    assert "window_days" not in out
    assert out["any_of"] == [{"min_visits": 2}, {"days_of_week": [5, 6]}]


def test_fold_flat_patch_onto_stored_any_of_starts_fresh_not_merged():
    """Once the filter IS an any_of, a later flat patch ("also 3+ visits")
    has no single OR-branch to land on — it starts a FRESH flat filter,
    discarding the any_of, rather than guessing which branch to patch."""
    specs = [
        {"any_of": [{"min_visits": 2}, {"days_of_week": [5, 6]}]},
        {"min_dwell_min": 15},
    ]
    out = fold_audience_filter_specs(specs)
    assert "any_of" not in out
    assert out["min_dwell_min"] == 15


def test_fold_any_of_none_clears_it_back_to_flat():
    specs = [{"any_of": [{"min_visits": 2}]}, {"any_of": None}]
    out = fold_audience_filter_specs(specs)
    assert out == {"_resolved": True}


def test_fold_widens_correctly_when_the_narrowing_patch_is_dropped():
    """The whole point of keeping history instead of one merged dict: replay
    WITHOUT the popped last patch (what undo() does) correctly restores the
    prior state, not some stuck-narrow hybrid."""
    full_history = [{"min_visits": 2}, {"min_visits": 5}]
    after_undo = full_history[:-1]  # undo pops the last patch
    assert fold_audience_filter_specs(full_history)["min_visits"] == 5
    assert fold_audience_filter_specs(after_undo)["min_visits"] == 2


def test_fold_strips_the_unsupported_key_it_is_not_a_filter_field():
    out = fold_audience_filter_specs([{"min_visits": 2, "unsupported": "women in their 30s"}])
    assert "unsupported" not in out
    assert out["min_visits"] == 2
