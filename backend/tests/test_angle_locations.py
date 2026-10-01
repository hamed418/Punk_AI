"""
"Events only in Montreal": where each search looks. Covers the pure resolver, the
typed edit through the real ``apply_edits`` (specs written, flat list kept as the
union, unit chosen, undo), the flat-edit bug (a removed city surviving in a
search's own list) and the confirm map keeping a search's pinned cities.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.graph.builder import angle_locations as al
from app.graph.builder.builder_node import _sync_confirm_edits_undoable
from app.graph.builder.edits import apply_edits
from app.graph.builder.executors import geo
from app.graph.builder.interject_tools import perform_undo
from tests.test_geo_pin_radius_confirm import _AUSTIN_BOUNDS, _patch

_FILLED = {
    "location_scope": "granular_local", "locations": "Montreal, Toronto",
    "det_type": "category,event_based", "poi_types": "gym", "event_queries": "food festival",
}


def _state(specs=None, location=("Montreal", "Toronto")):
    ui = {"location": list(location)}
    if specs is not None:
        ui["geo_angle_specs"] = specs
    return {"user_info": ui}


def _bs(**kw):
    return {"filled": dict(_FILLED), "ops_done": ["geo_discover"], "geo_ws": {}, **kw}


# ── resolve_angle ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("target,expected", [
    ("events", "event_based"), ("the festivals", "event_based"), ("event_based", "event_based"),
    ("gyms", "category"), ("gym", "category"), ("the category search", "category"),
])
def test_resolve_angle(target, expected):
    assert al.resolve_angle(target, _FILLED, []) == (expected, [])


def test_resolve_angle_by_the_specs_own_items():
    specs = [{"angle": "category", "poi_types": ["pilates studio"]}]
    assert al.resolve_angle("pilates", _FILLED, specs) == ("category", [])


def test_resolve_angle_ambiguous_and_unknown():
    both = {**_FILLED, "poi_types": "food court"}                  # "food" is in both searches
    tok, cands = al.resolve_angle("food", both, [])
    assert tok is None and set(cands) == {"category", "event_based"}
    assert al.resolve_angle("zoos", _FILLED, []) == (None, [])
    assert al.resolve_angle("events", {**_FILLED, "det_type": "category"}, []) == (None, [])   # not running


# ── apply_op ─────────────────────────────────────────────────────────────────

def _op(op, names, target="events"):
    return al.apply_op({"target": target, "op": op, "names": names},
                       filled=_FILLED, specs=[], flat=["Montreal", "Toronto"])


def test_set_pins_one_search_and_keeps_the_flat_union():
    r = _op("set", ["Montreal"])
    assert r["status"] == "applied"
    assert r["specs"] == [{"angle": "event_based", "locations": ["Montreal"]}]
    assert r["flat"] == ["Montreal", "Toronto"]                    # the gyms still search both


def test_set_to_the_shared_list_inherits_again():
    r = al.apply_op({"target": "events", "op": "set", "names": ["Montreal", "Toronto"]},
                    filled=_FILLED, specs=[{"angle": "event_based", "locations": ["Montreal"]}],
                    flat=["Montreal", "Toronto"])
    assert r["status"] == "applied" and r["specs"] == []


def test_add_a_new_city_to_one_search_widens_the_flat_list():
    r = _op("add", ["Laval"])
    assert r["specs"][0]["locations"] == ["Montreal", "Toronto", "Laval"]
    assert r["flat"] == ["Montreal", "Toronto", "Laval"]


def test_remove_from_one_search():
    r = _op("remove", ["Toronto"], target="gyms")
    assert r["specs"] == [{"angle": "category", "locations": ["Montreal"]}]
    assert r["flat"] == ["Montreal", "Toronto"]


def test_a_city_only_one_search_used_leaves_the_flat_list_with_it():
    r = al.apply_op({"target": "events", "op": "set", "names": ["Montreal"]},
                    filled=_FILLED, specs=[{"angle": "event_based", "locations": ["Laval"]}],
                    flat=["Laval", "Montreal", "Toronto"])
    assert "Laval" not in r["flat"] and "Montreal" in r["flat"]


@pytest.mark.parametrize("op,names,target,why", [
    ("remove", ["Paris"], "events", "isn't one of the places"),
    ("remove", ["Montreal", "Toronto"], "events", "no place to look in"),
    ("set", ["Montreal"], "zoos", "couldn't tell which search"),
    ("set", [], "events", "no place was named"),
])
def test_refusals_say_why(op, names, target, why):
    r = _op(op, names, target)
    assert r["status"] == "refused" and why in r["detail"]


def test_a_store_search_has_no_city_list():
    filled = {**_FILLED, "det_type": "category,store_set"}
    r = al.apply_op({"target": "my shop", "op": "set", "names": ["Laval"]}, filled=filled, specs=[], flat=["Montreal"])
    assert r["status"] == "refused" and "store address" in r["detail"]


def test_already_that_is_a_no_op():
    r = al.apply_op({"target": "events", "op": "add", "names": ["Montreal"]},
                    filled=_FILLED, specs=[], flat=["Montreal", "Toronto"])
    assert r["status"] == "no_op"


# ── through the real bus ─────────────────────────────────────────────────────

def test_typed_edit_writes_the_specs_and_only_re_searches():
    bs = _bs(geo_ws={"_angle_names_synced": {"event_based": ["Montreal", "Toronto"]}})
    bs["_pending_edits"] = {"_angle_locations": [{"target": "events", "op": "set", "names": ["Montreal"]}]}

    report = apply_edits(bs, _state())

    assert [(o.field, o.status) for o in report.outcomes] == [("angle_locations", "applied")]
    assert report.ui_patch["geo_angle_specs"] == [{"angle": "event_based", "locations": ["Montreal"]}]
    assert "location" not in report.ui_patch                          # same places: no re-geocode
    assert bs["filled"]["locations"] == "Montreal, Toronto"
    assert "_angle_names_synced" not in bs["geo_ws"]                  # would override the new specs
    assert "geo_discover" not in bs["ops_done"]


def test_a_new_city_for_one_search_re_geocodes_and_undo_restores_the_specs():
    bs = _bs()
    state = _state(specs=[{"angle": "category", "locations": ["Toronto"]}])
    bs["_pending_edits"] = {"_angle_locations": [{"target": "events", "op": "add", "names": ["Laval"]}]}

    report = apply_edits(bs, state)

    assert report.ui_patch["location"] == ["Montreal", "Toronto", "Laval"]
    assert bs["filled"]["locations"] == "Montreal, Toronto, Laval"
    _, restore = asyncio.run(perform_undo(bs, state))
    assert restore["geo_angle_specs"] == [{"angle": "category", "locations": ["Toronto"]}]
    assert restore["location"] == ["Montreal", "Toronto"]
    assert bs["filled"]["locations"] == "Montreal, Toronto"


def test_an_unclear_target_changes_nothing_and_says_so():
    bs = _bs()
    bs["_pending_edits"] = {"_angle_locations": [{"target": "zoos", "op": "set", "names": ["Montreal"]}]}
    state = {"user_info": {"location": ["Montreal", "Toronto"]}}

    report = apply_edits(bs, state)

    assert [o.status for o in report.outcomes] == ["refused"]
    assert report.ui_patch == {} and bs["filled"] == _FILLED
    assert not bs.get("_undo_stack")


def test_a_flat_removal_also_leaves_the_searches_own_list():
    specs = [{"angle": "event_based", "locations": ["Montreal", "Laval"]}]
    bs = _bs()
    bs["_pending_edits"] = {"location": ["Toronto", "Laval"]}         # "remove Montreal"

    report = apply_edits(bs, _state(specs=specs, location=("Montreal", "Toronto", "Laval")))

    assert report.ui_patch["geo_angle_specs"] == [{"angle": "event_based", "locations": ["Laval"]}]


def test_a_flat_addition_joins_a_pinned_search():
    specs = [{"angle": "event_based", "locations": ["Montreal"]}]
    bs = _bs()
    bs["_pending_edits"] = {"location": ["Montreal", "Toronto", "Laval"]}

    report = apply_edits(bs, _state(specs=specs))

    assert report.ui_patch["geo_angle_specs"] == [{"angle": "event_based", "locations": ["Montreal", "Laval"]}]


def test_a_flat_removal_of_a_searchs_only_city_makes_it_inherit():
    specs = [{"angle": "event_based", "locations": ["Montreal"]}]
    bs = _bs()
    bs["_pending_edits"] = {"location": ["Toronto"]}

    report = apply_edits(bs, _state(specs=specs))

    assert report.ui_patch["geo_angle_specs"] == [{"angle": "event_based"}]


# ── the confirm map ──────────────────────────────────────────────────────────

def _drive_once(ws, specs, names=("Austin", "Montreal")):
    async def _go():
        await geo._execute_deterministic(
            "granular_local", "category,event_based", list(names), "a brand",
            lambda ev: None,
            {"poi_types_list": ["gym"], "event_queries_list": ["fest"], "angle_specs": specs},
            ws, state=None,
        )
    try:
        asyncio.run(_go())
    except geo._GeoStepPaused:
        pass


def _remove(name):
    return json.dumps({"confirm": True, "added": [], "removed": [{"name": name}]})


def test_the_confirm_map_keeps_a_searchs_pinned_cities(monkeypatch):
    _patch(monkeypatch, [_remove("Austin")], {"Austin": "locality", "Montreal": "locality"},
           {"Austin": _AUSTIN_BOUNDS, "Montreal": _AUSTIN_BOUNDS})
    ws: dict = {}
    specs = [{"angle": "event_based", "locations": ["Austin", "Montreal"]},
             {"angle": "category", "locations": ["Montreal"]}]

    _drive_once(ws, specs)

    synced = ws["_angle_names_synced"]
    assert synced["event_based"] == ["Montreal"]                      # Austin left every search
    assert synced["category"] == ["Montreal"]


def test_the_confirm_map_does_not_widen_a_pinned_search_on_removal(monkeypatch):
    cities = {"Austin": "locality", "Montreal": "locality", "Laval": "locality"}
    _patch(monkeypatch, [_remove("Austin")], cities, {c: _AUSTIN_BOUNDS for c in cities})
    ws: dict = {}
    specs = [{"angle": "event_based", "locations": ["Montreal"]}]     # the gyms inherit all three

    _drive_once(ws, specs, names=("Austin", "Montreal", "Laval"))

    assert ws["_angle_names_synced"] == {
        "event_based": ["Montreal"],                                   # still only Montreal
        "category": ["Montreal", "Laval"],
    }


def test_a_confirm_map_edit_is_written_back_to_the_durable_specs(monkeypatch):
    _patch(monkeypatch, [_remove("Austin")], {"Austin": "locality", "Montreal": "locality"},
           {"Austin": _AUSTIN_BOUNDS, "Montreal": _AUSTIN_BOUNDS})
    ws: dict = {}
    specs = [{"angle": "event_based", "locations": ["Austin", "Montreal"]}]
    _drive_once(ws, specs)
    bs = {"geo_ws": ws, "ops_done": ["geo_discover"], "filled": {
        "location_scope": "granular_local", "locations": "Austin, Montreal", "det_type": "category,event_based"}}
    update: dict = {}
    state = {"user_info": {"location": ["Austin", "Montreal"], "geo_angle_specs": specs}}

    _sync_confirm_edits_undoable(ws, bs["filled"], bs, update, state)

    assert update["user_info"]["geo_angle_specs"] == [{"angle": "event_based", "locations": ["Montreal"]}]
    assert bs["filled"]["locations"] == "Montreal"
    _, restore = asyncio.run(perform_undo(bs, state))
    assert restore["geo_angle_specs"] == specs and restore["location"] == ["Austin", "Montreal"]


# ── dispatch ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("flags,kind", [
    ({"is_replace": True}, "set"), ({"is_append": True}, "add"), ({"is_remove": True}, "remove"),
])
async def test_a_place_tied_to_one_search_is_stashed_as_an_angle_op(flags, kind):
    from unittest.mock import AsyncMock, patch

    from langchain_core.messages import HumanMessage

    from app.graph.narrator.beats import drain_changes
    from app.graph.resume_router import ResumeIntent
    from app.graph.wizard_helpers import _dispatch_edit_intent

    state = {"messages": [HumanMessage(content="x", id=f"al-{kind}")], "user_info": {},
             "campaign_builder_state": {"filled": dict(_FILLED)}}
    edits: dict = {}
    intent = ResumeIntent(lane="edit", target_field="location", new_value=["Montreal"],
                          edit_target="events", confidence=0.95, **flags)
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
        reframe = await _dispatch_edit_intent(
            intent=intent, state=state, writer=lambda _e: None, pending={},
            cfg={"field": "geo_locations"}, edits=edits, edit_base={},
        )
    assert reframe is False
    assert edits == {"_angle_locations": [{"target": "events", "op": kind, "names": ["Montreal"]}]}
    assert drain_changes(state)["heard_not_applied"]                  # heard, not yet claimed
