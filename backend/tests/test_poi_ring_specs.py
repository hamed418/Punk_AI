"""
"100 m for the gyms": the visit ring for some spots only. A typed change is stored
as a decision (`bs["_poi_ring_specs"]`), refused when nothing on the map matches,
reset by an "every spot" ring, undoable, and — the part that costs money — sent to
the audience query as each spot's OWN radius, with the session cache invalidated
when one group's ring changes.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.graph.builder.edits import apply_edits
from app.graph.builder.executors import maid
from app.graph.builder.interject_tools import perform_undo

_GYM = {"name": "Iron Gym", "lat": 45.50, "lng": -73.50, "source_angle": "category", "parent_poi_type": "gym"}
_GYM2 = {"name": "Fit Club", "lat": 45.51, "lng": -73.51, "source_angle": "category", "parent_poi_type": "gym"}
_CAFE = {"name": "Bean Bar", "lat": 45.52, "lng": -73.52, "source_angle": "category", "parent_poi_type": "cafe"}


def _bs(**kw):
    return {
        "filled": {"location_scope": "granular_local", "locations": "Montreal", "det_type": "category",
                   "poi_radius_m": "500"},
        "ops_done": ["geo_discover", "maid_query"],
        "geo_result": {"targetable_pois": [dict(_GYM), dict(_GYM2), dict(_CAFE)]}, **kw,
    }


def _edit(bs, value="100 m", match="the gyms"):
    bs["_pending_edits"] = {"_poi_ring": [{"match": match, "value": value}]}
    return apply_edits(bs, {"user_info": {}})


# ── the typed edit ───────────────────────────────────────────────────────────

def test_stores_the_group_ring_and_rebuys_only_the_audience():
    bs = _bs()
    report = _edit(bs)

    assert [(o.field, o.status) for o in report.outcomes] == [("poi_ring", "applied")]
    assert bs["_poi_ring_specs"] == [{"match": "gyms", "radius_m": 100}]
    assert "2 spot(s)" in report.outcomes[0].detail and "100 m" in report.outcomes[0].detail
    assert "maid_query" not in bs["ops_done"] and "geo_discover" in bs["ops_done"]   # no new Places search
    assert bs["filled"]["poi_radius_m"] == "500"                                     # the default is untouched


@pytest.mark.parametrize("raw,metres", [("300 feet", 91), ("0.2 km", 200)])
def test_units_are_converted(raw, metres):
    bs = _bs()
    _edit(bs, raw)
    assert bs["_poi_ring_specs"][0]["radius_m"] == metres


def test_a_group_that_matches_nothing_is_refused_and_writes_nothing():
    bs = _bs()
    report = _edit(bs, match="the zoos")

    assert [o.status for o in report.outcomes] == ["refused"]
    assert "zoos" in report.outcomes[0].detail
    assert not bs.get("_poi_ring_specs") and not bs.get("_undo_stack")
    assert "maid_query" in bs["ops_done"]


def test_a_size_that_isnt_a_distance_is_refused():
    bs = _bs()
    assert _edit(bs, "tight").outcomes[0].status == "refused"
    assert not bs.get("_poi_ring_specs")


def test_an_oversize_ring_is_clamped_and_says_so():
    bs = _bs()
    report = _edit(bs, "20 km")

    assert report.outcomes[0].status == "adjusted"
    assert bs["_poi_ring_specs"][0]["radius_m"] == 500              # the widget's own maximum
    assert "asked for 20000 m, set to 500 m" in report.outcomes[0].detail   # the real value is reported


def test_the_same_ring_again_is_already_that():
    bs = _bs()
    _edit(bs)
    bs["ops_done"] = ["geo_discover", "maid_query"]
    report = _edit(bs)

    assert [o.status for o in report.outcomes] == ["no_op"]
    assert "maid_query" in bs["ops_done"]                              # nothing to re-buy


def test_a_later_ring_for_the_same_group_replaces_the_earlier_one():
    bs = _bs()
    _edit(bs, "100 m")
    _edit(bs, "250 m", match="The Gyms")
    assert bs["_poi_ring_specs"] == [{"match": "Gyms", "radius_m": 250}]


def test_before_the_spots_exist_it_is_stored_for_when_they_are_found():
    bs = _bs()
    bs["geo_result"] = None
    report = _edit(bs)
    assert report.outcomes[0].status == "applied" and bs["_poi_ring_specs"]


def test_an_every_spot_ring_resets_the_group_rings_and_says_so():
    bs = _bs()
    _edit(bs)
    bs["_pending_edits"] = {"poi_radius_m": "300"}
    report = apply_edits(bs, {"user_info": {}})

    assert bs["_poi_ring_specs"] == []
    assert report.outcomes[0].status == "adjusted" and "gyms" in report.outcomes[0].detail
    assert bs["filled"]["poi_radius_m"] == "300"


def test_undo_restores_the_previous_group_rings():
    bs = _bs()
    _edit(bs, "100 m")
    _edit(bs, "250 m")
    asyncio.run(perform_undo(bs, {"user_info": {}}))
    assert bs["_poi_ring_specs"] == [{"match": "gyms", "radius_m": 100}]
    asyncio.run(perform_undo(bs, {"user_info": {}}))
    assert bs["_poi_ring_specs"] == []
    assert "maid_query" not in bs["ops_done"]                          # rebuilt from the restored rings


# ── what the audience query is sent ──────────────────────────────────────────

def test_apply_ring_specs_stamps_only_the_matching_spots():
    pois = [{**p, "radius_km": 0.5} for p in (_GYM, _GYM2, _CAFE)]
    out = maid._apply_ring_specs(pois, [{"match": "gym", "radius_m": 100}, {"match": "zoo", "radius_m": 50}])

    assert [p["radius_km"] for p in pois] == [0.1, 0.1, 0.5]
    assert out == [{"match": "gym", "radius_m": 100, "count": 2}]      # the empty group isn't claimed


def test_a_later_spec_wins_and_the_ring_is_capped():
    pois = [{**_GYM, "radius_km": 0.5}]
    maid._apply_ring_specs(pois, [{"match": "gym", "radius_m": 100}, {"match": "iron", "radius_m": 99999}])
    assert pois[0]["radius_km"] == maid._MAX_MAID_RADIUS_M / 1000.0


class _Stop(Exception):
    pass


def test_the_query_payload_carries_each_spots_own_radius(monkeypatch):
    seen: dict = {}

    async def _fake_query(querier, *, dates, pois, writer, on_row=None):
        seen["pois"] = pois
        raise _Stop

    monkeypatch.setattr(maid, "narrate", AsyncMock())
    monkeypatch.setattr(maid, "fetch_maid_extraction_by_session", AsyncMock(return_value=None))
    monkeypatch.setattr(maid, "get_maid_querier", lambda: object())
    monkeypatch.setattr(maid, "_query_maids_with_retry", _fake_query)
    monkeypatch.setattr("app.graph.unacast_query.estimate_cost",
                        AsyncMock(return_value={"calls": 0, "features": 0, "pois": 3, "cached_pois": 3, "eta_s": 0}))
    geo = {"targetable_pois": [dict(_GYM), dict(_GYM2), dict(_CAFE)]}
    ws = {"poi_radius_m": 500, "lookback_days": 7, "poi_ring_specs": [{"match": "gym", "radius_m": 100}]}

    with pytest.raises(_Stop):
        asyncio.run(maid.run_maid_query({}, ws, geo, lambda ev: None, "sess"))

    assert sorted(p["radius_km"] for p in seen["pois"]) == [0.1, 0.1, 0.5]
    assert geo["poi_ring_overrides"] == [{"match": "gym", "radius_m": 100, "count": 2}]
    assert geo["poi_radius_km"] == 0.5                                 # the default is still the scalar


# ── the session cache ────────────────────────────────────────────────────────

def _cached(pois, **kw):
    return {"maid_count": 5, "search_radius_km": 0.5, "lookback_days": 7, "event_date_ranges": [],
            "pois": pois, "purged_at": None, **kw}


def test_the_cache_is_invalid_when_only_one_groups_ring_changed():
    stored = [{**_GYM, "radius_km": 0.5}, {**_CAFE, "radius_km": 0.5}]
    fresh = [{**_GYM, "radius_km": 0.1}, {**_CAFE, "radius_km": 0.5}]
    assert maid._maid_cache_still_valid(_cached(stored), 0.5, 7, [], fresh) is False


def test_the_cache_holds_when_every_ring_is_unchanged():
    stored = [{**_GYM, "radius_km": 0.1}, {**_CAFE, "radius_km": 0.5}]
    assert maid._maid_cache_still_valid(_cached(stored), 0.5, 7, [], [dict(p) for p in stored]) is True


# ── classifier + dispatch ────────────────────────────────────────────────────

def test_a_targeted_visit_ring_reaches_the_dispatcher_instead_of_being_refused():
    from app.graph.resume_router import _resolve_edit_call

    out = _resolve_edit_call({"field": "poi_radius_m", "value": "100 m", "target": "gyms"}, {})
    assert out["target_field"] == "poi_radius_m" and out["edit_target"] == "gyms"


def test_a_relative_group_ring_asks_for_the_size():
    from app.graph.resume_router import _resolve_edit_call

    out = _resolve_edit_call({"field": "poi_radius_m", "value": "double", "mode": "scale", "target": "gyms"}, {})
    assert out["_clarify"] == ["poi_radius_m"] and "gyms" in out["_question"]


def test_an_untargeted_visit_ring_is_still_the_plain_slot_edit():
    from app.graph.resume_router import _resolve_edit_call

    out = _resolve_edit_call({"field": "poi_radius_m", "value": "300 m"}, {})
    assert out["target_field"] == "poi_radius_m" and out["edit_target"] is None


@pytest.mark.asyncio
async def test_dispatch_stashes_the_group_ring_op():
    from unittest.mock import patch

    from langchain_core.messages import HumanMessage

    from app.graph.narrator.beats import drain_changes
    from app.graph.resume_router import ResumeIntent
    from app.graph.wizard_helpers import _dispatch_edit_intent

    state = {"messages": [HumanMessage(content="x", id="ring-dispatch")], "user_info": {},
             "campaign_builder_state": {}}
    edits: dict = {}
    intent = ResumeIntent(lane="edit", target_field="poi_radius_m", new_value="100 m",
                          edit_target="gyms", confidence=0.95)
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
        reframe = await _dispatch_edit_intent(
            intent=intent, state=state, writer=lambda _e: None, pending={},
            cfg={"field": "geo_locations"}, edits=edits, edit_base={},
        )
    assert reframe is False
    assert edits == {"_poi_ring": [{"match": "gyms", "value": "100 m"}]}
    assert drain_changes(state)["heard_not_applied"]
