"""
Integration tests for builder_node._apply_geo_poi_selection_edit's maid-side
delegation — a POI-curation edit ("remove the dog parks") that lands AFTER
the audience is already extracted must recompute the persisted MAID
extraction (count, POIs, map-recompute flag), not just the geo-side POI list.

Also covers the sibling fix in poi_selection.apply_specs: `unsupported`
clauses must only be re-narrated for the CURRENT turn, not replayed forever
from the persisted spec history.

DB calls (fetch/update_maid_extraction) are monkeypatched to an in-memory
fake row, same fixture shape as test_audience_filter_edit.py — everything
else (POI folding, geofence attribution) is the REAL code.
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
GYM_A = {
    "name": "GymA", "lat": 45.5, "lng": -73.5, "radius_km": 1.0,
    "source_angle": "category", "parent_poi_type": "gym",
    "parent_label": "Montreal", "types": ["gym"],
}
GYM_B = {
    "name": "GymB", "lat": 45.51, "lng": -73.51, "radius_km": 1.0,
    "source_angle": "category", "parent_poi_type": "gym",
    "parent_label": "Montreal", "types": ["gym"],
}
GYM_C = {
    "name": "GymC", "lat": 45.52, "lng": -73.52, "radius_km": 1.0,
    "source_angle": "category", "parent_poi_type": "gym",
    "parent_label": "Montreal", "types": ["gym"],
}


def _obs(maid: str, poi: dict, count: int = 1) -> dict:
    """A stored row, attributed to its POI by poi_key as the vendor returns it."""
    from app.graph.unacast_query import poi_key

    return {"lat": poi["lat"], "lng": poi["lng"], "maid": maid, "count": count,
            "poi_key": poi_key(poi)}


@pytest.fixture
def fake_extraction_db(monkeypatch):
    row = {
        "maid_count": 3,
        "maids": ["A", "B", "C"],
        "observations": [
            _obs("A", GYM, count=2),
            _obs("B", GYM, count=1),
            _obs("C", COFFEE, count=5),
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


def _bs(pois, **geo_extra):
    return {
        "filled": {}, "ops_done": [],
        "geo_result": {
            "targetable_pois": [dict(p) for p in pois],
            "pois_found": len(pois),
            "maid_extraction_id": "extraction-1",
            **geo_extra,
        },
        # apply_specs always re-folds from the discovery SUPERSET, never from
        # a previous turn's trimmed result (poi_selection.apply_specs's own
        # docstring) — without this cache a widening spec has nothing to
        # widen back INTO, same as it would in the real geo_discover flow.
        "geo_ws": {"_all_pois_cache": [dict(p) for p in pois]},
    }


def test_poi_trim_after_extraction_recomputes_audience_and_flags_recompute(
    fake_extraction_db, monkeypatch,
):
    monkeypatch.setattr(bn, "get_writer", lambda: (lambda _e: None))
    beats = []
    orig_add_beat = bn.add_beat
    bn.add_beat = lambda state, kind, facts, **kw: beats.append(facts)
    try:
        bs = _bs([GYM, COFFEE])
        note = asyncio.run(bn._apply_geo_poi_selection_edit(bs, {}, ["drop the gym"]))
    finally:
        bn.add_beat = orig_add_beat

    # Geo-side result no longer carries the dropped POI.
    assert [p["name"] for p in bs["geo_result"]["targetable_pois"]] == ["Coffee"]
    # Maid-side extraction was refreshed, not left stale — count is DISTINCT
    # maids attributed to surviving POIs (only "C", at Coffee), not the sum
    # of each observation's `count`.
    assert fake_extraction_db["filtered_maid_count"] == 1
    assert [p["name"] for p in fake_extraction_db["pois"]] == ["Coffee"]
    # The narrator grounding pack (state["geo_data"]) mirror-refresh flag was
    # set — round 2's fix: maid.py no longer gates the map re-emit on a flag
    # (maid_confirm now always re-fetches via repeat_events), but grounding
    # STILL needs this flag to know bs["geo_result"] changed.
    assert bs["_geo_recommit"] is True
    # One beat for the whole turn (narrate=False on the delegated maid call).
    assert len(beats) == 1
    assert beats[0]["audience_count"] == 1
    assert "poi selection" in note


def test_a_purged_extraction_is_treated_as_not_found(fake_extraction_db):
    """A published (or swept) extraction has empty observations — recomputing
    a POI edit against it would silently wipe every surviving POI's audience
    rather than the honest "couldn't find the saved audience" message the
    missing-row path already gives."""
    fake_extraction_db["purged_at"] = "2026-01-01T00:00:00+00:00"
    fake_extraction_db["maids"] = []
    fake_extraction_db["observations"] = []

    bs = _bs([GYM, COFFEE])
    note = asyncio.run(bn._apply_maid_poi_edits(bs, {}, {}))

    assert note == "maid edit skipped — extraction not found"
    assert fake_extraction_db["pois"] == [dict(GYM), dict(COFFEE)]  # untouched


def test_with_audience_false_suppresses_this_beats_audience_count(
    fake_extraction_db, monkeypatch,
):
    """When an audience-filter patch is ALSO landing this turn (builder_plan
    runs the POI trim first, then the filter recompute — see builder_plan's
    ordering comment), the POI curation beat must not carry its own
    PRE-filter audience_count: the filter beat right after states the real,
    post-filter number. Two different totals for one combined turn ("drop
    the Laval gyms, only weekend visitors") would read as Punk contradicting
    itself."""
    monkeypatch.setattr(bn, "get_writer", lambda: (lambda _e: None))
    beats = []
    orig_add_beat = bn.add_beat
    bn.add_beat = lambda state, kind, facts, **kw: beats.append(facts)
    try:
        bs = _bs([GYM, COFFEE])
        asyncio.run(bn._apply_geo_poi_selection_edit(
            bs, {}, ["drop the gym"], with_audience=False,
        ))
    finally:
        bn.add_beat = orig_add_beat

    assert len(beats) == 1
    # The mock above records facts verbatim (bypassing add_beat's own
    # None-filtering, which is what actually strips this key in production —
    # see narrator/beats.py) — so the call-site contract this proves is
    # "passes None", which add_beat then drops before the composer ever sees it.
    assert beats[0]["audience_count"] is None
    # The maid-side recompute still ran for real — with_audience only hides
    # the NUMBER from this beat, it must never skip the actual work.
    assert fake_extraction_db["filtered_maid_count"] == 1


def test_poi_trim_without_extraction_is_unchanged(monkeypatch):
    """A geo-stage trim (no maid_extraction_id yet) must not touch maid state
    or crash trying to reach the DB."""
    monkeypatch.setattr(bn, "get_writer", lambda: (lambda _e: None))
    bs = _bs([GYM, COFFEE])
    bs["geo_result"].pop("maid_extraction_id")
    asyncio.run(bn._apply_geo_poi_selection_edit(bs, {}, ["drop the gym"]))
    assert [p["name"] for p in bs["geo_result"]["targetable_pois"]] == ["Coffee"]
    assert "maid_ws" not in bs


def test_widening_spec_restores_poi_into_persisted_extraction(
    fake_extraction_db, monkeypatch,
):
    """"top 1" then "actually make it 2" must bring a second POI back into
    the persisted extraction (the `added` half of the delegated delta), with
    a fresh warehouse pull for the newly-restored spot. Three POIs, not two:
    widening all the way back to the full original superset is a known,
    separate blind spot (report.applied stays empty because nothing is
    dropped RELATIVE TO THE ORIGINAL SET) — orthogonal to this fix, so this
    test widens to a proper subset instead of exercising that edge case."""
    monkeypatch.setattr(bn, "get_writer", lambda: (lambda _e: None))

    async def fake_query_pois_audience(geo, pois, writer=None):
        return [_obs("D", pois[0], count=1)], None

    monkeypatch.setattr(
        "app.graph.builder.executors.maid.query_pois_audience", fake_query_pois_audience,
    )

    fake_extraction_db["pois"] = [dict(GYM_A), dict(GYM_B), dict(GYM_C)]
    fake_extraction_db["observations"] = [
        _obs("A", GYM_A), _obs("B", GYM_B), _obs("C", GYM_C),
    ]
    fake_extraction_db["maid_count"] = 3

    bs = _bs([GYM_A, GYM_B, GYM_C])
    asyncio.run(bn._apply_geo_poi_selection_edit(bs, {}, [{"n": 1, "scope": "all"}]))
    kept_after_1 = {p["name"] for p in fake_extraction_db["pois"]}
    assert len(kept_after_1) == 1

    asyncio.run(bn._apply_geo_poi_selection_edit(bs, {}, [{"n": 2, "scope": "all"}]))
    kept_after_2 = {p["name"] for p in fake_extraction_db["pois"]}
    assert len(kept_after_2) == 2
    assert kept_after_1 < kept_after_2  # the original survivor plus one restored
    assert bs["_geo_recommit"] is True


def test_unsupported_clause_is_only_narrated_the_turn_it_happened(monkeypatch):
    """Turn 1's unsupported clause ("recommend the best places only") must
    not resurface on turn 2's unrelated edit — the bug from thread
    0b3b050c-7873-42f1-8732-79273520fc38."""
    recorded = []
    monkeypatch.setattr(
        "app.graph.capability_miss.record",
        lambda kind, **kw: recorded.append((kind, kw)),
    )
    bs = _bs([GYM, COFFEE])
    bs["geo_result"].pop("maid_extraction_id")  # unrelated to this fix — geo stage only
    asyncio.run(bn._apply_geo_poi_selection_edit(
        bs, {}, [{"unsupported": "recommend me the best places only"}],
    ))
    note2 = asyncio.run(bn._apply_geo_poi_selection_edit(bs, {}, ["drop the gym"]))

    assert len(recorded) == 1  # not re-fired on turn 2
    assert "best places" not in note2
    assert [p["name"] for p in bs["geo_result"]["targetable_pois"]] == ["Coffee"]


def test_added_poi_query_failure_is_named_not_silenced(fake_extraction_db, monkeypatch):
    """A widen/add that reaches the vendor and gets refused (budget exhausted,
    breaker open, ...) must not read the same as a genuinely quiet spot —
    query_pois_audience returning ([], "budget") has to surface as
    add_failure_kind on the beat, not vanish into a bare 0."""
    monkeypatch.setattr(bn, "get_writer", lambda: (lambda _e: None))

    async def fake_query_pois_audience(geo, pois, writer=None):
        return [], "budget"

    monkeypatch.setattr(
        "app.graph.builder.executors.maid.query_pois_audience", fake_query_pois_audience,
    )

    beats = []
    orig_add_beat = bn.add_beat
    bn.add_beat = lambda state, kind, facts, **kw: beats.append(facts)
    try:
        bs = _bs([GYM, COFFEE])
        note = asyncio.run(bn._apply_maid_poi_edits(
            bs, {}, {"removed": [], "added": [dict(COFFEE, name="NewSpot",
                                                     lat=45.7, lng=-73.7)]},
        ))
    finally:
        bn.add_beat = orig_add_beat

    assert len(beats) == 1
    assert beats[0]["add_failure_kind"] == "budget"
    assert isinstance(note, str)  # the call completed without raising


def test_poi_trim_refreshes_whole_audience_visit_stats(fake_extraction_db, monkeypatch):
    """Removing a POI must refresh geo["maid_visit_stats"] to match the
    survivors, not just the headline count. Previously the summary stayed at
    the pre-trim extraction's numbers while maid_count/filtered_maid_count
    moved with the trim — a busy removed spot's repeat-visitor count/max_seen
    could keep showing next to a much smaller new total."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)

    def _visits(n: int) -> list[dict]:
        return [
            {"ts": (now - timedelta(days=d + 1)).isoformat(), "dwell_min": 10,
             "dwell_lower_s": 600, "n_pings": 2}
            for d in range(n)
        ]

    fake_extraction_db["observations"] = [
        {**_obs("A", GYM, count=2), "visits": _visits(2), "days": []},
        {**_obs("B", GYM, count=1), "visits": _visits(1), "days": []},
        # Coffee's own device visited 5 times — the busiest spot, and the one
        # this test removes. Its 5-visit device must not linger in the
        # whole-audience summary afterward.
        {**_obs("C", COFFEE, count=5), "visits": _visits(5), "days": []},
    ]

    monkeypatch.setattr(bn, "get_writer", lambda: (lambda _e: None))
    bs = _bs([GYM, COFFEE])
    asyncio.run(bn._apply_maid_poi_edits(bs, {}, {"removed": [dict(COFFEE)], "added": []}))

    assert bs["geo_result"]["filtered_maid_count"] == 2  # A, B — C's spot is gone
    stats = bs["geo_result"]["maid_visit_stats"]
    assert stats["total_devices"] == 2
    assert stats["repeat_visitor_count"] == 1   # A (2 visits) only; B is 1x
    assert stats["max_seen"] == 2               # not 5 — C left with Coffee

    # The surviving POI's own per-POI visit_stats is refreshed too (not left
    # stale from before the trim) — same "actually shown" set as the total.
    by_name = {p["name"]: p for p in bs["geo_result"]["targetable_pois"]}
    assert by_name["Gym"]["visit_stats"]["total_devices"] == 2


def test_added_poi_gets_a_visit_stats_stamp(fake_extraction_db, monkeypatch):
    """A newly-added POI (never queried before this turn) must get a
    per-POI visit_stats the first time, not just an audience_count — a blank
    stamp reads as "no data" on the hover card and sorts as 0 on every
    frequency sort, indistinguishable from a genuinely quiet spot."""
    monkeypatch.setattr(bn, "get_writer", lambda: (lambda _e: None))

    async def fake_query_pois_audience(geo, pois, writer=None):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        visits = [
            {"ts": (now - timedelta(days=d + 1)).isoformat(), "dwell_min": 10,
             "dwell_lower_s": 600, "n_pings": 2}
            for d in range(2)
        ]
        return [{**_obs("D", pois[0], count=2), "visits": visits, "days": []}], None

    monkeypatch.setattr(
        "app.graph.builder.executors.maid.query_pois_audience", fake_query_pois_audience,
    )

    bs = _bs([GYM, COFFEE])
    new_spot = dict(COFFEE, name="NewSpot", lat=45.7, lng=-73.7)
    asyncio.run(bn._apply_maid_poi_edits(bs, {}, {"removed": [], "added": [new_spot]}))

    by_name = {p["name"]: p for p in bs["geo_result"]["targetable_pois"]}
    assert by_name["NewSpot"]["visit_stats"]["total_devices"] == 1


def test_added_poi_query_success_carries_no_failure_kind(fake_extraction_db, monkeypatch):
    monkeypatch.setattr(bn, "get_writer", lambda: (lambda _e: None))

    async def fake_query_pois_audience(geo, pois, writer=None):
        return [_obs("D", pois[0], count=1)], None

    monkeypatch.setattr(
        "app.graph.builder.executors.maid.query_pois_audience", fake_query_pois_audience,
    )

    beats = []
    orig_add_beat = bn.add_beat
    bn.add_beat = lambda state, kind, facts, **kw: beats.append(facts)
    try:
        bs = _bs([GYM, COFFEE])
        asyncio.run(bn._apply_maid_poi_edits(
            bs, {}, {"removed": [], "added": [dict(COFFEE, name="NewSpot",
                                                     lat=45.7, lng=-73.7)]},
        ))
    finally:
        bn.add_beat = orig_add_beat

    assert beats[0]["add_failure_kind"] is None


def test_unsupported_clause_alongside_actionable_keys_still_applies(monkeypatch):
    """A single spec naming BOTH an unsupported idea and a real key ("just
    the best ones, and drop the gym") must still apply the `match` — the
    normalize_spec contract (poi_selection.py) that the old unconditional
    `continue` violated."""
    recorded = []
    monkeypatch.setattr(
        "app.graph.capability_miss.record",
        lambda kind, **kw: recorded.append(kw["detail"]),
    )
    bs = _bs([GYM, COFFEE])
    bs["geo_result"].pop("maid_extraction_id")  # unrelated to this fix — geo stage only
    asyncio.run(bn._apply_geo_poi_selection_edit(
        bs, {}, [{"unsupported": "the best ones", "op": "drop", "match": "gym"}],
    ))
    # The `match` still ran — this is the fix, not just the unsupported echo.
    assert [p["name"] for p in bs["geo_result"]["targetable_pois"]] == ["Coffee"]
    assert recorded == ["the best ones"]
