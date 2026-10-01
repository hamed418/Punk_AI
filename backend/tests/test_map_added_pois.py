"""
A spot the user adds on the POI map is theirs: it must survive a later trim
("top 3 each"), a fresh Places search, and an undo — none of which used to know
about it, because it was never part of the search's own results.
"""
from __future__ import annotations

import asyncio
import json

from app.graph.builder.builder_node import (
    _apply_confirm_semantics,
    _apply_geo_poi_selection_edit,
    _merge_map_added,
    _reapply_poi_selection_specs,
)
from app.graph.builder.edits import apply_edits, push_undo
from app.graph.builder.interject_tools import perform_undo

_FILLED = {
    "location_scope": "granular_local", "locations": "Montreal", "business_desc": "coffee shop",
    "targeting_method": "deterministic", "det_type": "category", "poi_types": "coffee shop",
}
_GYM_A = {"name": "Gym A", "lat": 45.50, "lng": -73.50, "source_angle": "category", "parent_poi_type": "gym"}
_GYM_B = {"name": "Gym B", "lat": 45.51, "lng": -73.51, "source_angle": "category", "parent_poi_type": "gym"}
_CAFE = {"name": "Cafe C", "lat": 45.52, "lng": -73.52, "source_angle": "category", "parent_poi_type": "cafe"}
_PICK = {"name": "Picked", "lat": 45.60, "lng": -73.60}


def _bs(gate: dict) -> dict:
    found = [dict(_GYM_A), dict(_GYM_B), dict(_CAFE)]
    return {
        "filled": {**_FILLED, "poi_confirm": json.dumps({"confirm": True, "removed": [], **gate})},
        "ops_done": ["geo_discover"], "stages_complete": [],
        "geo_result": {"pois_found": 3, "poi_radius_km": 1.0, "targetable_pois": list(found)},
        "geo_ws": {"_all_pois_cache": [dict(p) for p in found]},
    }


def _add_pick() -> dict:
    bs = _bs({"added": [dict(_PICK)]})
    asyncio.run(_apply_confirm_semantics(bs, {}))
    return bs


def _names(bs: dict) -> set:
    return {p["name"] for p in bs["geo_result"]["targetable_pois"]}


def _trim(bs: dict, spec: dict) -> None:
    asyncio.run(_apply_geo_poi_selection_edit(bs, {}, [spec], narrate=False))


def test_an_added_spot_is_remembered():
    bs = _add_pick()
    assert [p["name"] for p in bs["_map_added_pois"]] == ["Picked"]
    assert bs["_map_added_pois"][0]["parent_poi_type"] == "map_pick"


def test_an_added_spot_survives_a_trim_of_something_else():
    bs = _add_pick()
    _trim(bs, {"op": "drop", "match": "gym"})
    assert _names(bs) == {"Cafe C", "Picked"}          # the gyms went; the pick did not


def test_an_added_spot_survives_top_n_each():
    bs = _add_pick()
    _trim(bs, {"op": "keep", "n": 1, "scope": "each"})
    assert "Picked" in _names(bs)


def test_an_added_spot_survives_a_fresh_search():
    bs = _add_pick()
    bs["_poi_selection_specs"] = [{"op": "drop", "match": "cafe"}]
    fresh = {"pois_found": 3, "targetable_pois": [dict(_GYM_A), dict(_GYM_B), dict(_CAFE)]}

    _merge_map_added(bs, fresh)
    _reapply_poi_selection_specs(bs, fresh, lambda ev: None)

    assert {p["name"] for p in fresh["targetable_pois"]} == {"Gym A", "Gym B", "Picked"}


def test_removing_an_added_spot_removes_it_for_good():
    bs = _add_pick()
    bs["filled"]["poi_confirm"] = json.dumps({"confirm": True, "added": [], "removed": [dict(_PICK)]})
    asyncio.run(_apply_confirm_semantics(bs, {}))

    assert "Picked" not in _names(bs)
    assert not bs["_map_added_pois"]
    _trim(bs, {"op": "keep", "n": 5, "scope": "each"})
    assert "Picked" not in _names(bs)                   # not resurrected by the next fold


def test_adding_back_a_removed_spot_lifts_the_removal():
    bs = _add_pick()
    bs["filled"]["poi_confirm"] = json.dumps({"confirm": True, "added": [], "removed": [dict(_PICK)]})
    asyncio.run(_apply_confirm_semantics(bs, {}))
    bs["filled"]["poi_confirm"] = json.dumps({"confirm": True, "removed": [], "added": [dict(_PICK)]})
    asyncio.run(_apply_confirm_semantics(bs, {}))

    _trim(bs, {"op": "keep", "n": 5, "scope": "each"})
    assert "Picked" in _names(bs)


def test_a_new_location_set_starts_without_the_old_picks():
    bs = _add_pick()
    bs["filled"].pop("poi_confirm")
    bs["_pending_edits"] = {"location": ["Toronto"]}

    apply_edits(bs)

    assert not bs.get("_map_added_pois")


def test_undo_takes_the_added_spot_back_out():
    bs = _add_pick()
    assert "Picked" in _names(bs)
    assert bs["_undo_stack"] and "poi_confirm" not in bs["_undo_stack"][-1]["filled"]

    asyncio.run(perform_undo(bs, {}))

    assert "Picked" not in _names(bs)
    assert not bs["_map_added_pois"]
    assert "poi_confirm" not in bs["filled"]            # the gate asks again, the click isn't replayed


def test_undo_of_a_location_change_brings_the_picks_back():
    bs = _add_pick()
    bs["filled"].pop("poi_confirm")
    bs["_pending_edits"] = {"location": ["Toronto"]}
    apply_edits(bs)
    assert not bs.get("_map_added_pois")

    asyncio.run(perform_undo(bs, {}))

    assert [p["name"] for p in bs["_map_added_pois"]] == ["Picked"]


def test_push_undo_is_the_only_snapshot_shape():
    bs = {"filled": {"a": "1"}, "_poi_ring_specs": [{"match": "gym", "radius_m": 100}]}
    push_undo(bs, unit="maid_query")
    snap = bs["_undo_stack"][-1]
    assert snap["v"] == 2 and snap["unit"] == "maid_query" and snap["filled"] == {"a": "1"}
    assert snap["_poi_ring_specs"] == [{"match": "gym", "radius_m": 100}]
    assert snap["_map_added_pois"] == []
