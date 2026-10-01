"""
Integration tests for builder_node._apply_maid_audience_filter_edit /
_recompute_audience_filter — the ordered-patch-history rewrite that brings
audience-filter edits up to the same safety rails POI selection already has:
a replayable spec list, a structured report, an undo snapshot, and an
`unsupported` clause that reaches capability_miss instead of vanishing.

DB calls (fetch/update_maid_extraction) are monkeypatched to an in-memory
fake row — everything else (geofence attribution, filter evaluation, the
fold) is the REAL code.
"""
import asyncio

import pytest

from app.graph.builder import builder_node as bn

GYM = {
    "name": "Gym", "lat": 45.5, "lng": -73.5, "radius_km": 1.0,
    "source_angle": "category", "parent_poi_type": "gym",
    "parent_label": "Montreal", "types": ["gym"],
}
COFFEE = {
    "name": "Coffee", "lat": 45.6, "lng": -73.6, "radius_km": 1.0,
    "source_angle": "category", "parent_poi_type": "coffee shop",
    "parent_label": "Montreal", "types": ["coffee shop"],
}


def _obs(maid: str, poi: dict, count: int) -> dict:
    """A folded row as run_maid_query stores it: attributed to its POI by
    poi_key, with one measured visit per day for `count` days."""
    from datetime import datetime, timedelta, timezone

    from app.graph.unacast_query import poi_key

    now = datetime.now(timezone.utc)
    return {
        "lat": poi["lat"], "lng": poi["lng"], "maid": maid, "count": count,
        "poi_key": poi_key(poi),
        "visits": [
            {"ts": (now - timedelta(days=d + 1)).isoformat(), "dwell_min": 10,
             "dwell_lower_s": 600, "n_pings": 2, "gap_s": 1200}
            for d in range(count)
        ],
    }


@pytest.fixture
def fake_extraction_db(monkeypatch):
    """A single mutable in-memory row standing in for the Postgres table —
    fetch/update_maid_extraction read/write it directly, same contract as
    the real functions (see maid_store.py's own docstrings)."""
    row = {
        "maid_count": 5,
        "maids": ["A", "B", "C"],
        "observations": [
            _obs("A", GYM, count=5),      # 5 visits — clears "3+"
            _obs("B", GYM, count=1),      # 1 visit — fails "3+"
            _obs("C", COFFEE, count=10),  # different POI entirely
        ],
        "pois": [dict(GYM), dict(COFFEE)],
        "audience_filter": None,
        "filtered_maid_count": None,
    }

    row.setdefault("purged_at", None)

    async def fake_fetch(extraction_id):
        return dict(row)

    async def fake_update(extraction_id, **kwargs):
        row.update({k: v for k, v in kwargs.items() if k != "extraction_id"})
        return True

    monkeypatch.setattr("app.services.maid_store.fetch_maid_extraction", fake_fetch)
    monkeypatch.setattr("app.services.maid_store.update_maid_extraction", fake_update)
    return row


def _bs(**geo_extra):
    return {
        "filled": {}, "ops_done": [],
        "geo_result": {"maid_extraction_id": "extraction-1", **geo_extra},
    }


def test_first_filter_edit_narrows_and_reports(fake_extraction_db):
    bs = _bs()
    note = asyncio.run(bn._apply_maid_audience_filter_edit(bs, {}, {"min_visits": 3}))
    assert "filter=" in note
    # A (5 visits) survives, B (1 visit) does not, C (different POI, no
    # min_visits predicate applied to it since it's outside `groups`) — the
    # filter is global here, so only min_visits matters: A survives, B and C
    # (1 visit... wait C has 10) — recompute honestly: A(5)>=3 survives,
    # B(1)<3 excluded, C(10)>=3 survives. total = 2.
    assert bs["geo_result"]["filtered_maid_count"] == 2
    assert bs["geo_result"]["maid_count"] == 5  # true superset, untouched
    assert bs["_audience_filter_specs"] == [{"min_visits": 3}]
    assert bs["_undo_stack"], "must push an undo snapshot, same as the POI edit path"
    # Without this, state["geo_data"] (what the narrator grounding pack reads)
    # never mirrors the fresh filtered_maid_count — round 2's bug: a LATER
    # turn with no beat of its own (a no-op edit, a plain reject) would keep
    # citing the pre-filter count forever.
    assert bs["_geo_recommit"] is True


def test_second_edit_widens_correctly_not_just_narrows_further(fake_extraction_db):
    """"3+ visits" then "actually just 1+" — the SECOND patch must WIN
    (widen back to everyone), proving the fold replays the whole history
    from empty rather than narrowing the previous result further."""
    bs = _bs()
    asyncio.run(bn._apply_maid_audience_filter_edit(bs, {}, {"min_visits": 3}))
    asyncio.run(bn._apply_maid_audience_filter_edit(bs, {}, {"min_visits": 1}))
    assert bs["_audience_filter_specs"] == [{"min_visits": 3}, {"min_visits": 1}]
    assert bs["geo_result"]["filtered_maid_count"] == 3  # A, B, C all clear 1+
    assert bs["geo_result"]["audience_filter"]["min_visits"] == 1


def test_a_purged_extraction_is_treated_as_not_found(fake_extraction_db):
    """A published (or swept) extraction has empty observations — recomputing
    against it would silently report "0 people match" instead of the honest
    "couldn't find the saved audience" the missing-row path already gives."""
    fake_extraction_db["purged_at"] = "2026-01-01T00:00:00+00:00"
    fake_extraction_db["maids"] = []
    fake_extraction_db["observations"] = []

    bs = _bs()
    note = asyncio.run(bn._apply_maid_audience_filter_edit(bs, {}, {"min_visits": 3}))

    assert note == "audience filter edit skipped — extraction not found"
    assert "_audience_filter_specs" not in bs
    assert "filtered_maid_count" not in bs["geo_result"]


def test_unresolved_group_label_becomes_a_deviation(fake_extraction_db):
    """A group label that matches no category on screen must be SPOKEN, not
    silently dropped into a filter that quietly narrows to nothing — same
    "any deviation from the literal request must be spoken" rule the POI
    side already follows (builder_node's named-arm-bypass fix)."""
    beats: list[dict] = []
    orig_add_beat = bn.add_beat
    bn.add_beat = lambda state, kind, facts, **kw: beats.append(facts)
    try:
        bs = _bs()
        asyncio.run(bn._apply_maid_audience_filter_edit(
            bs, {}, {"groups": ["gym", "not-a-real-category"]},
        ))
    finally:
        bn.add_beat = orig_add_beat
    assert beats, "add_beat must fire with a deviation about the unmatched label"
    assert any("didn't match" in d for d in beats[0]["deviations"])


def test_unsupported_clause_reaches_capability_miss(fake_extraction_db, monkeypatch):
    recorded = []
    monkeypatch.setattr(
        "app.graph.capability_miss.record",
        lambda kind, **kw: recorded.append((kind, kw)),
    )
    bs = _bs()
    asyncio.run(bn._apply_maid_audience_filter_edit(
        bs, {}, {"min_visits": 2, "unsupported": "women in their 30s"},
    ))
    assert len(recorded) == 1
    kind, kw = recorded[0]
    assert kind == "unsupported_selection"
    assert kw["field"] == "audience_filter"
    assert kw["detail"] == "women in their 30s"


def test_no_extraction_on_record_is_honest_not_a_crash():
    from app.graph.narrator.beats import drain_changes, record_change

    state = {}
    bs = {"filled": {}, "ops_done": [], "geo_result": {}}
    # Simulate the real turn shape: wizard_helpers._dispatch_edit_intent
    # records `heard` at ACK time, before this function ever runs.
    record_change(state, heard={"audience_filter": "narrow audience: {'min_visits': 2}"})
    note = asyncio.run(bn._apply_maid_audience_filter_edit(bs, state, {"min_visits": 2}))
    assert "no extraction" in note
    assert "_audience_filter_specs" not in bs
    # `unsupported` (not `applied`) is the only thing a permanent failure can
    # record — `applied` would falsely claim the edit landed. The composer's
    # CAN'T DO branch fires on `unsupported` regardless of what `heard`
    # still holds, so the ledger no longer implies "still working on it"
    # with no explanation.
    changes = drain_changes(state)
    assert changes["unsupported"], "a permanent failure must reach the CAN'T DO ledger"


def test_narrate_false_returns_the_human_sentence_directly(fake_extraction_db):
    """The handoff-lane shape (mirrors _apply_geo_poi_selection_edit's
    narrate=False path) — no add_beat, the return value IS the message."""
    beats = []
    orig_add_beat = bn.add_beat
    bn.add_beat = lambda *a, **k: beats.append(a)
    try:
        bs = _bs()
        result = asyncio.run(bn._apply_maid_audience_filter_edit(
            bs, {}, {"min_visits": 3}, narrate=False,
        ))
    finally:
        bn.add_beat = orig_add_beat
    assert not beats
    assert "verified visitor" in result


def test_an_unevaluable_filter_edit_is_refused_not_persisted(fake_extraction_db):
    """A lapsed-trend edit over an extraction that bought 7 days cannot be
    judged. It used to be persisted anyway — and publish re-applies the stored
    filter, where it raised. The edit is refused: nothing written, reason said."""
    stored = {"window_days": 7, "_history_days_bought": 7, "_resolved": True}
    fake_extraction_db["audience_filter"] = dict(stored)
    beats: list[dict] = []
    orig_add_beat = bn.add_beat
    bn.add_beat = lambda state, kind, facts, **kw: beats.append(facts)
    try:
        bs = _bs()
        asyncio.run(bn._apply_maid_audience_filter_edit(
            bs, {}, {"trend": "lapsed", "window_days": 30},
        ))
    finally:
        bn.add_beat = orig_add_beat

    assert fake_extraction_db["audience_filter"] == stored
    assert "_audience_filter_specs" not in bs
    assert any("couldn't apply" in d for d in beats[0]["deviations"])


def test_the_purchase_stamp_survives_a_filter_edit(fake_extraction_db):
    """What was BOUGHT is stamped on the stored filter, not on the user's
    patches — so the fold dropped it, and every later trend check fell back to
    guessing from the data."""
    fake_extraction_db["audience_filter"] = {"window_days": 7, "_history_days_bought": 60}
    bs = _bs()
    asyncio.run(bn._apply_maid_audience_filter_edit(bs, {}, {"min_visits": 3}))

    assert fake_extraction_db["audience_filter"]["_history_days_bought"] == 60
    assert bs["geo_result"]["audience_filter"]["_history_days_bought"] == 60


# ── the stored filter is the base an edit builds on ─────────────────────────
#
# A filter stated in the user's FIRST message is applied at extraction and never
# enters the edit history, so an edit folded from that history erased it. These
# pin the fix: every edit — typed in chat or committed from the layer builder —
# is an overlay on the filter the audience actually carries.


def _stamp(rows: list[dict], pois: list[dict]) -> list[dict]:
    """Rows as run_maid_query persists them: attributed (poi_ids/poi_uids)."""
    from app.graph.maid_query import attribute_audience

    return attribute_audience([dict(r) for r in rows], [dict(p) for p in pois], stamp_stats=False)[1]


def _public(spec: dict | None) -> dict:
    return {k: v for k, v in (spec or {}).items() if not k.startswith("_")}


@pytest.fixture
def stated_up_front(fake_extraction_db):
    """An audience whose first-message filter is 'gym regulars (3+ visits)'."""
    fake_extraction_db["observations"] = _stamp(
        [_obs("A", GYM, 5), _obs("B", GYM, 1), _obs("C", COFFEE, 10)], [GYM, COFFEE]
    )
    fake_extraction_db["audience_filter"] = {
        "groups": ["category:gym"], "min_visits": 3, "_resolved": True,
    }
    return fake_extraction_db


def test_the_first_edit_keeps_the_filter_stated_in_the_first_message(stated_up_front):
    bs = _bs()
    asyncio.run(bn._apply_maid_audience_filter_edit(bs, {}, {"window_days": 30}))
    assert _public(stated_up_front["audience_filter"]) == {
        "groups": ["category:gym"], "min_visits": 3, "window_days": 30,
    }
    assert stated_up_front["filtered_maid_count"] == 1  # still only A


def test_the_history_is_seeded_so_undo_returns_to_the_original_filter(stated_up_front):
    bs = _bs()
    asyncio.run(bn._apply_maid_audience_filter_edit(bs, {}, {"window_days": 30}))
    snapshot = bs["_undo_stack"][-1]["_audience_filter_specs"]
    assert snapshot == [{"groups": ["category:gym"], "min_visits": 3}]

    # undo() restores that snapshot and recomputes — the original filter is back
    asyncio.run(bn._recompute_audience_filter(bs, {}, snapshot))
    assert _public(stated_up_front["audience_filter"]) == {"groups": ["category:gym"], "min_visits": 3}
    assert stated_up_front["filtered_maid_count"] == 1


def test_a_system_default_window_is_not_treated_as_something_the_user_chose(fake_extraction_db):
    fake_extraction_db["audience_filter"] = {"window_days": 7, "_derived": True}
    bs = _bs()
    asyncio.run(bn._apply_maid_audience_filter_edit(bs, {}, {"min_visits": 3}))
    assert bs["_audience_filter_specs"] == [{"min_visits": 3}]


def test_a_history_that_already_matches_is_left_alone(stated_up_front):
    """Normal chat edits must keep their granularity: no rebase when the history
    already reproduces the stored filter."""
    bs = _bs()
    asyncio.run(bn._apply_maid_audience_filter_edit(bs, {}, {"window_days": 30}))
    asyncio.run(bn._apply_maid_audience_filter_edit(bs, {}, {"min_visits": 1}))
    assert bs["_audience_filter_specs"] == [
        {"groups": ["category:gym"], "min_visits": 3},
        {"window_days": 30},
        {"min_visits": 1},
    ]


def test_a_history_that_drifted_from_the_stored_filter_is_rebased_not_trusted(stated_up_front):
    bs = _bs()
    bs["_audience_filter_specs"] = [{"days_of_week": [5, 6]}]  # nothing to do with the stored filter
    asyncio.run(bn._apply_maid_audience_filter_edit(bs, {}, {"window_days": 30}))
    assert bs["_audience_filter_specs"][0] == {"groups": ["category:gym"], "min_visits": 3}
    assert _public(stated_up_front["audience_filter"])["groups"] == ["category:gym"]


def test_preview_and_commit_agree_even_when_the_filter_carries_keys_the_panel_cannot_edit(fake_extraction_db):
    """THE guarantee. The stored filter carries `min_distinct_pois` (not a panel
    key). A panel patch that only touches the window must preview AND commit to
    the same audience, and neither may drop the carried key."""
    from app.services.maid_store import preview_audience_layers

    fake_extraction_db["observations"] = _stamp(
        [_obs("A", GYM, 3), _obs("B", COFFEE, 3), _obs("D", GYM, 3), _obs("D", COFFEE, 3)],
        [GYM, COFFEE],
    )
    fake_extraction_db["audience_filter"] = {"min_distinct_pois": 2, "_resolved": True}
    patch = {"window_days": 30}

    [layer] = preview_audience_layers(
        fake_extraction_db["observations"], fake_extraction_db["pois"],
        [{"label": "x", "patches": [patch]}], base=fake_extraction_db["audience_filter"],
    )
    assert layer["count"] == 1  # only D visited 2 distinct places

    bs = _bs()
    asyncio.run(bn._apply_maid_audience_filter_edit(bs, {}, patch))
    assert fake_extraction_db["filtered_maid_count"] == layer["count"] == 1
    assert _public(fake_extraction_db["audience_filter"]) == layer["filter"] == {
        "min_distinct_pois": 2, "window_days": 30,
    }


def test_removing_a_carried_setting_from_the_panel_removes_exactly_that_key(fake_extraction_db):
    """The ✕ on a carried chip: preview and commit agree, only the named key goes,
    and the removal survives later edits (it is in the replayed history)."""
    from app.graph.resume_router import sanitize_panel_patch
    from app.services.maid_store import preview_audience_layers

    fake_extraction_db["observations"] = _stamp(
        [_obs("A", GYM, 3), _obs("B", COFFEE, 3), _obs("D", GYM, 3), _obs("D", COFFEE, 3)],
        [GYM, COFFEE],
    )
    fake_extraction_db["audience_filter"] = {"min_distinct_pois": 2, "hours": [0, 24], "_resolved": True}
    patch = sanitize_panel_patch({"min_distinct_pois": None, "window_days": 30})

    [layer] = preview_audience_layers(
        fake_extraction_db["observations"], fake_extraction_db["pois"],
        [{"label": "x", "patches": [patch]}], base=fake_extraction_db["audience_filter"],
    )
    bs = _bs()
    asyncio.run(bn._apply_maid_audience_filter_edit(bs, {}, patch))
    assert fake_extraction_db["filtered_maid_count"] == layer["count"] == 3
    assert _public(fake_extraction_db["audience_filter"]) == layer["filter"] == {
        "hours": [0, 24], "window_days": 30,
    }

    asyncio.run(bn._apply_maid_audience_filter_edit(bs, {}, {"min_visits": 1}))
    assert "min_distinct_pois" not in _public(fake_extraction_db["audience_filter"])
    assert _public(fake_extraction_db["audience_filter"])["hours"] == [0, 24]


def test_the_old_preview_would_have_been_wrong_without_the_base(fake_extraction_db):
    """Regression guard for the bug itself: previewing the same patch with NO
    base ignores the carried key and reports a much larger audience."""
    from app.services.maid_store import preview_audience_layers

    obs = _stamp(
        [_obs("A", GYM, 3), _obs("B", COFFEE, 3), _obs("D", GYM, 3), _obs("D", COFFEE, 3)],
        [GYM, COFFEE],
    )
    [no_base] = preview_audience_layers(obs, [dict(GYM), dict(COFFEE)], [{"label": "x", "patches": [{"window_days": 30}]}])
    [with_base] = preview_audience_layers(
        obs, [dict(GYM), dict(COFFEE)], [{"label": "x", "patches": [{"window_days": 30}]}],
        base={"min_distinct_pois": 2},
    )
    assert (no_base["count"], with_base["count"]) == (3, 1)
