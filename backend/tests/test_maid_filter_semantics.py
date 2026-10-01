"""
tests/test_maid_filter_semantics.py
───────────────────────────────────
Phase 2 of the MAID redesign: history sizing, the evaluability guard, real
local time, overnight hour ranges, the temporal intersection witness, and the
four new filter fields.

Each group pins a behaviour that was previously wrong in a way no caller could
detect — the failure modes here all returned a confident answer, not an error.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.graph.maid_history import MAX_HISTORY_DAYS, required_history_days
from app.services.maid_store import (
    AudienceFilterUnevaluable,
    _hour_in_range,
    _local_shift,
    _zone_for,
    apply_audience_filter,
    describe_audience_filter,
    intersection_witness_stats,
)

NOW = datetime.now(timezone.utc)
DENVER = [{"lat": 39.7392, "lng": -104.9903}]


def _ago(days: float = 0, hours: float = 0) -> str:
    return (NOW - timedelta(days=days, hours=hours)).isoformat()


def _obs(maid: str, visits: list[dict], groups=("category:gym",), uids=("a",)) -> dict:
    return {
        "maid": maid, "lat": 39.7392, "lng": -104.9903,
        "count": len(visits) or 1,
        "poi_ids": list(groups), "poi_uids": list(uids),
        "visits": visits,
        "days": sorted({v["ts"][:10] for v in visits}),
    }


def _v(ts: str, dwell_s: int = 600, n: int = 3) -> dict:
    return {"ts": ts, "dwell_lower_s": dwell_s, "dwell_min": dwell_s // 60, "n_pings": n}


# ── history sizing ───────────────────────────────────────────────────────────

def test_plain_lookback_needs_no_extra_history():
    assert required_history_days(7, None) == 7
    assert required_history_days(7, {"min_visits": 2}) == 7


def test_window_days_larger_than_lookback_widens_the_purchase():
    """"in the last 45 days" over a 7-day purchase filtered a 7-day audience
    and reported it as 45."""
    assert required_history_days(7, {"window_days": 45}) == 45


def test_trend_doubles_its_window():
    """trend compares [now-W, now] against [now-2W, now-W). Buying only W left
    the older window empty BY CONSTRUCTION, so `started` matched everyone."""
    assert required_history_days(7, {"trend": "started", "window_days": 14}) == 28


def test_asymmetric_trend_windows_are_summed():
    """"started after NEVER going before" wants a short recent window and a long
    prior one — a symmetric 2x cannot express it."""
    assert required_history_days(
        7, {"trend": "started", "trend_recent_days": 14, "trend_prior_days": 46}
    ) == 60


def test_cadence_needs_room_for_repeated_gaps():
    # 2 on-cadence gaps => at least 3 visit days spanning 2 x cadence.
    assert required_history_days(7, {"cadence_days": 14}) == 42
    assert required_history_days(7, {"cadence_days": 7}) == 21


def test_any_of_takes_the_widest_branch():
    """Every branch must be evaluable or the OR silently drops one."""
    need = required_history_days(7, {"any_of": [
        {"min_visits": 2},
        {"trend": "lapsed", "window_days": 30},
    ]})
    assert need == 60


def test_history_is_clamped():
    assert required_history_days(7, {"cadence_days": 90}) == MAX_HISTORY_DAYS


# ── the evaluability guard ───────────────────────────────────────────────────

def test_trend_raises_when_the_prior_window_was_never_bought():
    """The whole point. `started` would otherwise match EVERY device with a
    recent visit, and `lapsed` NOBODY — both indistinguishable from real
    answers at the call site."""
    obs = [_obs("dev-1", [_v(_ago(days=1)), _v(_ago(days=3))])]
    with pytest.raises(AudienceFilterUnevaluable):
        apply_audience_filter(obs, {"trend": "started", "window_days": 30}, pois=DENVER)


def test_trend_is_evaluable_when_the_history_reaches_back():
    obs = [
        _obs("started", [_v(_ago(days=2))]),
        _obs("old-timer", [_v(_ago(days=50)), _v(_ago(days=55))]),
    ]
    keep = apply_audience_filter(
        obs, {"trend": "started", "window_days": 14}, pois=DENVER
    )
    assert keep == ["started"]


def test_lapsed_needs_two_older_visits_and_none_recent():
    """With window_days=14 the prior window is [now-28, now-14) — so the
    "used to come" visits have to land in THAT band, not merely be old."""
    obs = [
        _obs("lapsed", [_v(_ago(days=20)), _v(_ago(days=25))]),
        _obs("once-only", [_v(_ago(days=20))]),
        _obs("still-active", [_v(_ago(days=20)), _v(_ago(days=25)), _v(_ago(days=2))]),
    ]
    keep = apply_audience_filter(obs, {"trend": "lapsed", "window_days": 14}, pois=DENVER)
    assert keep == ["lapsed"]


def test_the_lapsed_prior_window_is_bounded_not_open_ended():
    """A device that stopped coming 40 days ago is NOT "lapsed" under a 14-day
    window — the prior window only reaches back 28 days. Widening the reach is
    what trend_prior_days is for, and this pins that it is a real choice rather
    than an accident."""
    obs = [_obs("long-gone", [_v(_ago(days=40)), _v(_ago(days=45))])]
    assert apply_audience_filter(
        obs, {"trend": "lapsed", "window_days": 14}, pois=DENVER
    ) == []
    assert apply_audience_filter(
        obs,
        {"trend": "lapsed", "trend_recent_days": 14, "trend_prior_days": 60},
        pois=DENVER,
    ) == ["long-gone"]


def test_the_stamped_purchase_size_is_authoritative():
    """A stored extraction says what it bought; that beats guessing from data."""
    obs = [_obs("dev-1", [_v(_ago(days=1)), _v(_ago(days=40))])]
    with pytest.raises(AudienceFilterUnevaluable) as exc:
        apply_audience_filter(
            obs,
            {"trend": "started", "window_days": 30, "_history_days_bought": 7},
            pois=DENVER,
        )
    assert exc.value.have_days == 7


def test_a_legacy_extraction_without_the_stamp_still_evaluates():
    """Refusing every pre-existing extraction would be worse than the
    imprecision it guards against."""
    obs = [_obs("dev-1", [_v(_ago(days=2)), _v(_ago(days=50))])]
    apply_audience_filter(obs, {"trend": "started", "window_days": 14}, pois=DENVER)


# ── local time ───────────────────────────────────────────────────────────────

def test_denver_resolves_to_a_real_zone():
    assert str(_zone_for(DENVER)) == "America/Denver"


def test_dst_is_handled():
    """`lng/15` gave -7 year-round, so "before 9am" read as "before 8am" for
    the eight months MDT is in effect."""
    summer = datetime(2026, 7, 1, 14, 30, tzinfo=timezone.utc)
    winter = datetime(2026, 1, 1, 14, 30, tzinfo=timezone.utc)
    assert _local_shift(summer, DENVER).hour == 8
    assert _local_shift(winter, DENVER).hour == 7


def test_zone_lookup_tries_every_poi_not_just_the_first(monkeypatch):
    """timezonefinder's timezone_at() returns None for a coordinate outside
    any land timezone polygon — a real, not hypothetical, case for a
    waterfront business or a slightly-off geocode. The FIRST poi in the list
    resolving to no zone must not sink the whole lookup when a later one
    would resolve cleanly — that used to silently drop hours/days_of_week
    evaluation back to the DST-ignorant longitude estimate for every device
    in the audience."""
    import app.services.maid_store as ms

    unresolvable_first = [{"lat": 0.0, "lng": -30.0}, *DENVER]  # mid-Atlantic, then Denver
    real_zone_at = ms._zone_at

    def _fake_zone_at(lat_r, lng_r):
        if (lat_r, lng_r) == (0.0, -30.0):
            return None  # ocean coordinate — the library's real behavior
        return real_zone_at(lat_r, lng_r)

    monkeypatch.setattr(ms, "_zone_at", _fake_zone_at)
    assert str(_zone_for(unresolvable_first)) == "America/Denver"


def test_hours_filter_uses_local_time():
    """14:30 UTC in July is 08:30 in Denver — inside "before 9am"."""
    obs = [_obs("early", [_v(datetime(2026, 7, 1, 14, 30, tzinfo=timezone.utc).isoformat())])]
    keep = apply_audience_filter(
        obs, {"hours": [0, 9], "window_days": 100000}, pois=DENVER
    )
    assert keep == ["early"]


# ── overnight hour ranges ────────────────────────────────────────────────────

@pytest.mark.parametrize("hour,expected", [
    (23, True), (0, True), (1, True), (22, True),
    (21, False), (2, False), (12, False),
])
def test_overnight_range_wraps_midnight(hour, expected):
    """"Friday night" is [22, 2], which is NOT `22 <= h < 2` — that is empty
    for every hour, so an overnight filter silently matched nobody."""
    assert _hour_in_range(hour, [22, 2]) is expected


def test_normal_range_still_works():
    assert _hour_in_range(8, [6, 9]) is True
    assert _hour_in_range(9, [6, 9]) is False


# ── intersection: the temporal witness ───────────────────────────────────────

def test_intersection_rejects_one_presence_seen_by_two_geofences():
    """Overlapping rings return ONE physical presence under both features. The
    old guard counted distinct places and passed, because the two POIs really
    are distinct — but the device was only ever in one spot at one time."""
    same_moment = _ago(days=1)
    obs = [
        _obs("co-located", [_v(same_moment)], groups=("category:gym",), uids=("gymA",)),
        _obs("co-located", [_v(same_moment)], groups=("category:cafe",), uids=("cafeB",)),
    ]
    keep = apply_audience_filter(
        obs, {"groups": ["category:gym", "category:cafe"], "op": "intersection"},
        pois=DENVER,
    )
    assert keep == []
    # Q3: the rejection must be visible to a caller (the funnel), not just
    # silent — intersection_raw counted the co-located device in, the witness
    # test then dropped it.
    stats = intersection_witness_stats()
    assert stats == {"intersection_raw": 1, "intersection_after_witness_test": 0}


def test_intersection_accepts_genuinely_separate_visits():
    obs = [
        _obs("real", [_v(_ago(days=3))], groups=("category:gym",), uids=("gymA",)),
        _obs("real", [_v(_ago(days=1))], groups=("category:cafe",), uids=("cafeB",)),
    ]
    keep = apply_audience_filter(
        obs, {"groups": ["category:gym", "category:cafe"], "op": "intersection"},
        pois=DENVER,
    )
    assert keep == ["real"]
    assert intersection_witness_stats() == {
        "intersection_raw": 1, "intersection_after_witness_test": 1,
    }


def test_intersection_witness_stats_resets_on_the_next_unrelated_call():
    """A plain union (the vast majority of prompts) must never carry stale
    numbers from a PREVIOUS call's intersection — apply_audience_filter
    resets the side-channel at the top of every call."""
    same_moment = _ago(days=1)
    obs_intersection = [
        _obs("co-located", [_v(same_moment)], groups=("category:gym",), uids=("gymA",)),
        _obs("co-located", [_v(same_moment)], groups=("category:cafe",), uids=("cafeB",)),
    ]
    apply_audience_filter(
        obs_intersection, {"groups": ["category:gym", "category:cafe"], "op": "intersection"},
        pois=DENVER,
    )
    assert intersection_witness_stats()["intersection_raw"] == 1  # nonzero, sanity check

    apply_audience_filter([_obs("A", [_v(_ago(days=1))])], {"min_visits": 1}, pois=DENVER)
    assert intersection_witness_stats() == {
        "intersection_raw": 0, "intersection_after_witness_test": 0,
    }


def test_single_ping_visits_at_the_same_instant_are_one_presence():
    """A single-ping visit is a zero-length interval. Two of them at the SAME
    instant (one ping returned under two overlapping geofences) were called
    disjoint by an "ends before the other starts" test, so the intersection
    credited one presence to two groups."""
    t = _ago(days=1)
    obs = [
        _obs("ghost", [_v(t, dwell_s=0, n=1)], groups=("category:gym",), uids=("gymA",)),
        _obs("ghost", [_v(t, dwell_s=0, n=1)], groups=("category:cafe",), uids=("cafeB",)),
    ]
    spec = {"groups": ["category:gym", "category:cafe"], "op": "intersection"}
    assert apply_audience_filter(obs, spec, pois=DENVER) == []


# ── min_distinct_groups: "3 of the 5 place types" ────────────────────────────

_KINDS = ["category:gym", "category:cafe", "category:salon", "category:bar", "category:spa"]


def _kinds(maid: str, kinds: list[str], *, start_days: float = 10, uid_prefix: str = "p") -> list[dict]:
    """One separate single-visit row per kind, a day apart — genuinely different
    places at genuinely different times."""
    return [
        _obs(maid, [_v(_ago(days=start_days - i))], groups=(k,), uids=(f"{uid_prefix}{i}",))
        for i, k in enumerate(kinds)
    ]


def test_min_distinct_groups_needs_n_of_the_named_kinds():
    obs = _kinds("three", _KINDS[:3]) + _kinds("two", _KINDS[:2])
    spec = {"groups": _KINDS, "min_distinct_groups": 3}
    assert apply_audience_filter(obs, spec, pois=DENVER) == ["three"]


def test_min_distinct_groups_is_not_min_distinct_pois():
    """Five Starbucks satisfy min_distinct_pois: 5 — that counts PLACES. It is
    still one KIND of place."""
    obs = [
        _obs("regular", [_v(_ago(days=10 - i))], groups=("category:cafe",), uids=(f"cafe{i}",))
        for i in range(5)
    ]
    assert apply_audience_filter(obs, {"min_distinct_pois": 5}, pois=DENVER) == ["regular"]
    assert apply_audience_filter(
        obs, {"groups": ["category:cafe", "category:gym"], "min_distinct_groups": 2}, pois=DENVER,
    ) == []


def test_min_distinct_groups_ignores_groups_the_clause_did_not_name():
    """A row carries EVERY group sharing its poi_key. A device that hit 2 of the
    3 named kinds plus 2 unnamed ones has 4 kinds in total, but only 2 count."""
    obs = _kinds("mixed", ["category:gym", "category:cafe", "category:bar", "category:spa"])
    spec = {"groups": ["category:gym", "category:cafe", "category:salon"], "min_distinct_groups": 3}
    assert apply_audience_filter(obs, spec, pois=DENVER) == []
    spec_ok = {**spec, "min_distinct_groups": 2}
    assert apply_audience_filter(obs, spec_ok, pois=DENVER) == ["mixed"]


def test_min_distinct_groups_rejects_one_presence_under_colocated_geofences():
    """Standing in one strip mall must not read as visiting three kinds of place."""
    t = _ago(days=1)
    obs = [
        _obs("mall", [_v(t)], groups=(k,), uids=(f"u{i}",)) for i, k in enumerate(_KINDS[:3])
    ]
    spec = {"groups": _KINDS, "min_distinct_groups": 2}
    assert apply_audience_filter(obs, spec, pois=DENVER) == []


def test_min_distinct_groups_at_n_equals_m_agrees_with_intersection():
    """intersection IS the N = len(groups) case — same rows, same answer, for a
    device that passes and for the two failure shapes."""
    groups = _KINDS[:3]
    same_moment = _ago(days=1)
    obs = (
        _kinds("real", groups)
        + [_obs("mall", [_v(same_moment)], groups=(k,), uids=(f"m{i}",)) for i, k in enumerate(groups)]
        + _kinds("short", groups[:2])
    )
    inter = apply_audience_filter(obs, {"groups": groups, "op": "intersection"}, pois=DENVER)
    n_of_m = apply_audience_filter(obs, {"groups": groups, "min_distinct_groups": 3}, pois=DENVER)
    assert inter == n_of_m == ["real"]


def test_min_distinct_groups_is_scoped_to_the_stated_window():
    """A 170-day-old visit to the third kind must not complete a "last 30 days"."""
    obs = _kinds("stale", _KINDS[:2], start_days=5) + [
        _obs("stale", [_v(_ago(days=170))], groups=(_KINDS[2],), uids=("old",)),
    ]
    spec = {"groups": _KINDS, "min_distinct_groups": 3}
    assert apply_audience_filter(obs, spec, pois=DENVER) == ["stale"]
    assert apply_audience_filter(obs, {**spec, "window_days": 30}, pois=DENVER) == []


def test_min_distinct_groups_without_named_groups_counts_every_group_in_the_build():
    obs = _kinds("wide", _KINDS[:3]) + _kinds("narrow", _KINDS[:1])
    assert apply_audience_filter(obs, {"min_distinct_groups": 3}, pois=DENVER) == ["wide"]


def test_min_distinct_groups_is_a_known_key_with_a_chip():
    from app.services.maid_store import unknown_filter_keys

    assert unknown_filter_keys({"min_distinct_groups": 2}) == []
    assert describe_audience_filter({"min_distinct_groups": 2}) == ["any 2+ of these groups"]


def test_min_distinct_groups_refuses_a_named_group_whose_query_failed():
    obs = _kinds("x", _KINDS[:3])
    spec = {"groups": _KINDS[:3], "min_distinct_groups": 2}
    with pytest.raises(AudienceFilterUnevaluable):
        apply_audience_filter(
            obs, spec, pois=DENVER, group_status={_KINDS[0]: {"status": "failed"}},
        )


# ── new fields ───────────────────────────────────────────────────────────────

def test_min_visits_per_group_is_not_a_total():
    """5 gym visits + 1 coffee visit satisfies min_visits: 6 but is not
    "3+ times at each"."""
    lopsided = [
        _obs("lopsided", [_v(_ago(days=d)) for d in (1, 2, 3, 4, 5)],
             groups=("category:gym",), uids=("gymA",)),
        _obs("lopsided", [_v(_ago(days=6))], groups=("category:cafe",), uids=("cafeB",)),
    ]
    spec = {"groups": ["category:gym", "category:cafe"], "op": "intersection"}
    assert apply_audience_filter(lopsided, {**spec, "min_visits": 6}, pois=DENVER) == ["lopsided"]
    assert apply_audience_filter(
        lopsided, {**spec, "min_visits_per_group": 3}, pois=DENVER
    ) == []


def test_min_visits_per_group_only_counts_visits_inside_the_stated_window():
    """A row's `_row_time_ok` only requires ONE qualifying visit to keep the
    ROW — it must not license counting the row's entire visit list as if
    every one of them qualified. A device with 10 gym visits total, only 1
    of them in the last 7 days, is not "3+ times at the gym this week"."""
    mostly_old = _obs(
        "mostly-old",
        [_v(_ago(days=1))] + [_v(_ago(days=d)) for d in range(30, 39)],  # 1 recent + 9 old
        groups=("category:gym",), uids=("gymA",),
    )
    spec = {"groups": ["category:gym"], "window_days": 7, "min_visits_per_group": 3}
    assert apply_audience_filter([mostly_old], spec, pois=DENVER) == []
    # Sanity: the SAME device clears a floor its one recent visit can meet.
    assert apply_audience_filter(
        [mostly_old], {**spec, "min_visits_per_group": 1}, pois=DENVER
    ) == ["mostly-old"]


def test_cadence_days_buckets_by_local_day_not_utc():
    """Every other day-bucketing predicate in this function (open_days, the
    presence-pattern envelopes) shifts to local time before taking .date();
    cadence used raw UTC. Denver local 18:00 (6pm) sits right on UTC's OWN
    midnight (MDT is UTC-6, so local 18:00 == UTC 00:00) while being nowhere
    near LOCAL midnight — a real device with a rock-steady weekly 6pm-local
    habit and a few minutes of natural ping jitter around it must read as
    perfectly on-cadence: the jitter never crosses anything meaningful in
    local time, only UTC's unrelated day boundary."""
    base = datetime(2026, 7, 2, 0, 0, tzinfo=timezone.utc)  # = Jul 1, 18:00 MDT
    jitters_min = [0, -3, 4]  # a few minutes either side of the habitual 6pm
    visits = [
        _v((base + timedelta(days=7 * i, minutes=jm)).isoformat())
        for i, jm in enumerate(jitters_min)
    ]
    obs = [_obs("six-pm-regular", visits)]
    # Zero tolerance: only an exact 7-local-day gap counts as on-cadence, so
    # this only passes if the calendar-day bucketing is genuinely local.
    assert apply_audience_filter(
        obs, {"cadence_days": 7, "cadence_tolerance_days": 0}, pois=DENVER,
    ) == ["six-pm-regular"]


def test_min_share_in_scope_expresses_exclusivity():
    """days_of_week alone means "at least one weekday visit", which includes
    every weekend regular."""
    # Build visits on known weekdays/weekends.
    monday = datetime(2026, 9, 7, 15, 0, tzinfo=timezone.utc)      # Mon
    saturday = datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc)    # Sat
    weekday_only = _obs("weekday-only", [_v(monday.isoformat()), _v((monday - timedelta(days=7)).isoformat())])
    mixed = _obs("mixed", [_v(monday.isoformat())] + [_v((saturday - timedelta(days=7 * i)).isoformat()) for i in range(4)])

    spec = {"days_of_week": [0, 1, 2, 3, 4], "window_days": 100000}
    both = apply_audience_filter([weekday_only, mixed], spec, pois=DENVER)
    assert set(both) == {"weekday-only", "mixed"}

    exclusive = apply_audience_filter(
        [weekday_only, mixed], {**spec, "min_share_in_scope": 0.8}, pois=DENVER
    )
    assert exclusive == ["weekday-only"]


def test_exclude_window_days_zero_means_ever():
    obs = [
        _obs("clean", [_v(_ago(days=1))], groups=("category:gym",), uids=("gymA",)),
        _obs("tainted", [_v(_ago(days=1))], groups=("category:gym",), uids=("gymA",)),
        _obs("tainted", [_v(_ago(days=300))], groups=("category:store",), uids=("storeX",)),
    ]
    spec = {"groups": ["category:gym"], "exclude_groups": ["category:store"], "window_days": 7}
    # Default: the exclusion inherits the 7-day scope, so a 300-day-old store
    # visit does not disqualify anyone.
    assert set(apply_audience_filter(obs, spec, pois=DENVER)) == {"clean", "tainted"}
    # "has NEVER been" looks at all history.
    assert apply_audience_filter(
        obs, {**spec, "exclude_window_days": 0}, pois=DENVER
    ) == ["clean"]


def test_new_fields_have_chips():
    chips = describe_audience_filter({
        "min_visits_per_group": 3,
        "min_share_in_scope": 0.8,
        "min_confidence": "confirmed",
    })
    assert "3+ visits each" in chips
    assert "80%+ of visits" in chips
    assert "high-confidence visits" in chips


# ── min_confidence/exclude_flags must scope the visit COUNT, not just the ────
# ── final catch-all guard ─────────────────────────────────────────────────────

def test_min_confidence_scopes_the_min_visits_count():
    """A device with 3 unconfirmed single-ping visits and 0 confirmed ones must
    not satisfy `min_visits: 3` just because `min_confidence` was never applied
    to the COUNT — only to the catch-all guard four other predicates share."""
    ghost = _obs("ghost", [
        {"ts": _ago(2), "dwell_lower_s": 0, "n_pings": 1, "confirmed": False},
        {"ts": _ago(4), "dwell_lower_s": 0, "n_pings": 1, "confirmed": False},
        {"ts": _ago(6), "dwell_lower_s": 0, "n_pings": 1, "confirmed": False},
    ])
    assert apply_audience_filter(
        [ghost], {"min_visits": 3, "min_confidence": "confirmed"}, pois=DENVER,
    ) == []


def test_min_confidence_with_min_visits_keeps_a_real_regular():
    """Same shape, all visits confirmed — must still be counted. Guards against
    over-correcting the fix above into "confidence excludes everyone"."""
    real = _obs("real", [
        {"ts": _ago(2), "dwell_lower_s": 600, "n_pings": 3, "confirmed": True},
        {"ts": _ago(4), "dwell_lower_s": 600, "n_pings": 3, "confirmed": True},
        {"ts": _ago(6), "dwell_lower_s": 600, "n_pings": 3, "confirmed": True},
    ])
    assert apply_audience_filter(
        [real], {"min_visits": 3, "min_confidence": "confirmed"}, pois=DENVER,
    ) == ["real"]


def test_unknown_filter_key_is_ignored_not_fatal(caplog):
    """An LLM-hallucinated key (typo'd `min_dwell_minutes`) must not crash and
    must not silently do nothing with no signal at all — it's logged."""
    obs = [_obs("A", [{"ts": _ago(2), "dwell_lower_s": 600, "n_pings": 3}])]
    result = apply_audience_filter(obs, {"min_dwell_minutes": 999}, pois=DENVER)
    assert result == ["A"]  # the unknown key had no filtering effect
    assert "min_dwell_minutes" in caplog.text


def test_known_filter_keys_never_warn(caplog):
    """Every field in the AudienceFilter comment block above must be in the
    whitelist, or a legitimate spec would warn on every single run."""
    obs = [_obs("A", [{"ts": _ago(2), "dwell_lower_s": 600, "n_pings": 3}])]
    apply_audience_filter(
        obs,
        {
            "groups": ["category:gym"], "op": "union", "exclude_groups": [],
            "window_days": 30, "min_visits": 1, "min_distinct_pois": 1,
            "days_of_week": [0, 1], "hours": [6, 9], "min_dwell_min": 5,
            "min_weekly_hours": 1.0, "cadence_days": 7,
            "cadence_tolerance_days": 1, "invert": False,
            "min_visits_per_group": 1, "min_share_in_scope": 0.5,
            "min_confidence": "confirmed", "exclude_window_days": 7,
        },
        pois=DENVER,
    )
    assert "unrecognized key" not in caplog.text


def test_exclude_flags_scopes_the_min_visits_count():
    """Same class of bug via exclude_flags instead of min_confidence."""
    from app.graph.maid_signal import FLAG_BITS

    driving = 1 << FLAG_BITS["LIKELY_DRIVING"]
    tainted = _obs("tainted", [
        {"ts": _ago(2), "dwell_lower_s": 600, "n_pings": 3, "flags_or": driving},
        {"ts": _ago(4), "dwell_lower_s": 600, "n_pings": 3, "flags_or": driving},
        {"ts": _ago(6), "dwell_lower_s": 600, "n_pings": 3, "flags_or": driving},
    ])
    assert apply_audience_filter(
        [tainted], {"min_visits": 3, "exclude_flags": driving}, pois=DENVER,
    ) == []


# ── min_visits: per-place by default, summed only within a named group ─────
#
# maid_query.compute_visit_stats (the map's repeat-visitor stat) takes a
# device's BEST count at any ONE place, never the sum across every POI in
# the build. Without a named `groups`, min_visits now matches it — the
# common case has no groups, and summing across every POI used to let a
# device seen once at a gym, once at a coffee shop and once at a barber
# satisfy "3+ visits" and be called a regular on screen next to a map that
# correctly called the same device a one-timer.

def test_min_visits_default_is_per_place_not_summed_across_pois():
    """One visit each at three unrelated POIs is not a "2+ visits" regular —
    it's three strangers' worth of noise, not evidence this device comes
    back anywhere."""
    device = [
        _obs("A", [_v(_ago(1))], groups=("category:gym",), uids=("gym",)),
        _obs("A", [_v(_ago(2))], groups=("category:coffee",), uids=("coffee",)),
        _obs("A", [_v(_ago(3))], groups=("category:barber",), uids=("barber",)),
    ]
    assert apply_audience_filter(device, {"min_visits": 2}, pois=DENVER) == []


def test_min_visits_default_counts_returns_to_the_same_place():
    """Two visits at the SAME place clears an ungrouped min_visits: 2 — the
    per-place max is still >= 2 here, unlike the three-different-places case
    above."""
    device = [
        _obs("A", [_v(_ago(1)), _v(_ago(8))], groups=("category:gym",), uids=("gym",)),
    ]
    assert apply_audience_filter(device, {"min_visits": 2}, pois=DENVER) == ["A"]


def test_min_visits_sums_within_a_named_group():
    """A NAMED group is a real single scope ("3+ times at Sephora") — three
    different Sephora locations really is brand loyalty, so min_visits still
    sums across the group's own places when `groups` is set, unlike the
    ungrouped default above."""
    device = [
        _obs("A", [_v(_ago(1))], groups=("brand:sephora",), uids=("sephora-1",)),
        _obs("A", [_v(_ago(2))], groups=("brand:sephora",), uids=("sephora-2",)),
    ]
    assert apply_audience_filter(
        device, {"groups": ["brand:sephora"], "min_visits": 2}, pois=DENVER,
    ) == ["A"]


def test_min_open_day_share_denominator_matches_the_windows_numerator():
    """The "operating days" denominator (open_days) used to be computed over
    the WHOLE bought history regardless of window_days/cutoff, while the
    numerator (_days_present) was correctly capped to the window — a spec
    combining the two ("present most days over the last week") could inflate
    the denominator with weeks-old activity from an unrelated device, making
    the share mathematically unsatisfiable for a device that was genuinely
    present every single day of the window itself."""
    old_timer = _obs(
        "old-timer",
        [_v(_ago(days=d)) for d in range(30, 40)],  # 10 distinct days, all outside any 7-day window
    )
    regular = _obs(
        "regular",
        [_v(_ago(days=d)) for d in range(1, 6)],  # 5 distinct days, all inside a 7-day window
    )
    kept = apply_audience_filter(
        [old_timer, regular], {"window_days": 7, "min_open_day_share": 0.6}, pois=DENVER,
    )
    # regular was present on 5 of the 5 open days the window actually
    # contains (100% >= 60%) — must pass regardless of old-timer's unrelated,
    # off-window history being in the same observation set.
    assert kept == ["regular"]


def test_min_visits_per_place_falls_back_to_poi_key_when_uids_missing():
    """A row persisted before poi_uids/poi_ids existed still groups by
    place, via its poi_key (the request-feature id — one purchase, one
    physical place, present on every row regardless of attribution)."""
    device = [
        {**_obs("A", [_v(_ago(1))], groups=(), uids=()), "poi_key": "place-1"},
        {**_obs("A", [_v(_ago(2))], groups=(), uids=()), "poi_key": "place-1"},
        {**_obs("A", [_v(_ago(3))], groups=(), uids=()), "poi_key": "place-2"},
    ]
    for row in device:
        row["poi_ids"] = []
        row["poi_uids"] = []
    assert apply_audience_filter(device, {"min_visits": 2}, pois=DENVER) == ["A"]
