"""
tests/test_midturn_phase0.py
────────────────────────────
Phase 0 of the mid-turn edit redesign: live bugs where Punk said an edit
landed (or said nothing) while the build did something else.

  * units — "5 miles" / "300 feet" / "0.5 km" land in the knob's own unit
  * clamps are reported, never silent
  * removing a targeting angle actually removes it
  * a geocode rollback clears the confirm-map edits that used to override it
  * the intent cache is scoped per thread
  * handoff-lane writes survive builder_ask's return
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.graph.builder.edits import apply_pending_edits, invalidate_from, stash_edits
from app.graph.narrator.beats import drain_changes, record_change
from app.graph.resume_router import ResumeIntent, ResumeResult, _intent_cache, classify_resume_intent
from app.graph.wizard_helpers import _dispatch_edit_intent, parse_length


def _state(msg_id: str) -> dict:
    return {"messages": [HumanMessage(content="x", id=msg_id)], "campaign_builder_state": {}}


# ── units ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,unit,expected", [
    ("5", "km", 5.0),                     # bare number = already in the target unit
    ("5 km", "km", 5.0),
    ("5km", "km", 5.0),
    ("5k", "km", 5.0),
    ("5 miles", "km", 8.04672),
    ("1 mile", "km", 1.609344),
    ("500 m", "km", 0.5),
    ("500 meters", "km", 0.5),
    ("0.5 km", "m", 500.0),
    ("300 feet", "m", 91.44),
    ("300ft", "m", 91.44),
    ("100", "m", 100.0),
    ("Q: How wide? (1-50)\nA: 12 km", "km", 12.0),   # widget payload: answer half only
    ("no number here", "km", None),
])
def test_parse_length_converts_to_the_target_unit(raw, unit, expected):
    got = parse_length(raw, unit)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


def _ring_bs() -> dict:
    return {
        "ops_done": ["geo_discover"], "stages_complete": ["geo"],
        "filled": {"location_scope": "granular_local", "locations": "Montreal", "det_type": "category"},
        "geo_ws": {"_geocoded_locations": [{
            "location_name": "Montreal", "ui_mode": "pin_radius", "search_radius_km": 12.0,
            "latitude": 45.5, "longitude": -73.6,
        }]},
    }


def test_search_circle_in_miles_is_converted_not_read_as_km():
    bs = _ring_bs()
    stash_edits(bs, ResumeResult("x", edits={"search_radius_km": "5 miles"}))
    apply_pending_edits(bs)
    assert bs["geo_ws"]["_search_ring_km"] == pytest.approx(8.0, abs=0.1)


def test_search_circle_in_metres_is_not_read_as_500_km():
    """The earlier radius fix read "500 m" as 500 km (then silently clamped)."""
    bs = _ring_bs()
    stash_edits(bs, ResumeResult("x", edits={"search_radius_km": "500 m"}))
    apply_pending_edits(bs)
    # 0.5 km is below the minimum ring, so it clamps UP — and says so (below).
    assert bs["geo_ws"]["_search_ring_km"] < 5


def test_clamped_search_circle_is_reported():
    state = _state("p0-clamp-ring")
    bs = _ring_bs()
    stash_edits(bs, ResumeResult("x", edits={"search_radius_km": "200 km"}))
    _ui, _rb, note = apply_pending_edits(bs, state)

    ring = bs["geo_ws"]["_search_ring_km"]
    assert ring < 200
    assert "adjusted" in note
    changes = drain_changes(state)
    assert any("200" in d and f"{ring:g}" in d for d in changes["deviations"])


def test_visit_ring_edit_in_km_lands_in_metres():
    bs = {"ops_done": ["maid_query"], "filled": {"poi_radius_m": "100"}}
    stash_edits(bs, ResumeResult("x", edits={"poi_radius_m": "0.2 km"}))
    apply_pending_edits(bs)
    assert bs["filled"]["poi_radius_m"] == "200"


def test_visit_ring_edit_in_feet_lands_in_metres():
    bs = {"ops_done": ["maid_query"], "filled": {"poi_radius_m": "100"}}
    stash_edits(bs, ResumeResult("x", edits={"poi_radius_m": "300 feet"}))
    apply_pending_edits(bs)
    assert bs["filled"]["poi_radius_m"] == "91"


# ── angle removal ─────────────────────────────────────────────────────────────


async def _dispatch(intent: ResumeIntent, state: dict, edits: dict, edit_base: dict) -> None:
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
        await _dispatch_edit_intent(
            intent=intent, state=state, writer=lambda _e: None, pending={},
            cfg={"field": "maid_poi_radius"}, edits=edits, edit_base=edit_base,
        )


@pytest.mark.asyncio
async def test_removing_an_angle_actually_removes_it():
    """apply_pending_edits unions angle edits with the running set — which used
    to put a removed angle straight back ("forget the cafes" kept the cafes)."""
    state = _state("p0-angle-remove")
    edits: dict = {}
    await _dispatch(
        ResumeIntent(lane="edit", target_field="deterministic_subtype",
                     new_value="category", is_remove=True, confidence=0.95),
        state, edits, {"deterministic_subtype": ["category", "event_based"]},
    )
    bs = {"ops_done": ["geo_discover"], "filled": {"det_type": "category,event_based"}}
    stash_edits(bs, ResumeResult("x", edits=edits))

    ui_patch, rolled_back, _note = apply_pending_edits(bs, state)

    assert bs["filled"]["det_type"] == "event_based"
    assert ui_patch["deterministic_subtype"] == ["event_based"]
    assert rolled_back and rolled_back[0] == "geo"
    assert drain_changes(state)["heard_not_applied"] == []


@pytest.mark.asyncio
async def test_removing_the_last_angle_is_refused_and_said():
    state = _state("p0-angle-last")
    edits: dict = {}
    await _dispatch(
        ResumeIntent(lane="edit", target_field="deterministic_subtype",
                     new_value="category", is_remove=True, confidence=0.95),
        state, edits, {"deterministic_subtype": ["category"]},
    )
    bs = {"ops_done": ["geo_discover"], "filled": {"det_type": "category"}}
    stash_edits(bs, ResumeResult("x", edits=edits))

    _ui, rolled_back, note = apply_pending_edits(bs, state)

    assert bs["filled"]["det_type"] == "category"
    assert rolled_back == []
    assert note is None                      # nothing committed
    changes = drain_changes(state)
    assert changes["deviations"] and changes["heard_not_applied"]


def test_adding_an_angle_still_unions():
    bs = {"ops_done": [], "filled": {"det_type": "category"}}
    stash_edits(bs, ResumeResult("x", edits={"deterministic_subtype": ["event_based"]}))
    apply_pending_edits(bs)
    assert bs["filled"]["det_type"] == "category,event_based"


# ── stale confirm-map edits ───────────────────────────────────────────────────


def test_geocode_rollback_clears_synced_confirm_edits():
    """Left behind, builder_act re-applied these OVER the freshly edited slot."""
    bs = {
        "ops_done": ["geo_discover"], "filled": {},
        "geo_ws": {"_stores_synced": ["old st"], "_angle_names_synced": {"category": ["Laval"]},
                   "_manual_pins": [{"x": 1}]},
    }
    invalidate_from(bs, bs["filled"], "geocode")
    assert "_stores_synced" not in bs["geo_ws"]
    assert "_angle_names_synced" not in bs["geo_ws"]
    assert bs["geo_ws"]["_manual_pins"] == [{"x": 1}]     # a user decision, kept (Phase 4 moves it)


# ── intent cache scope ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_intent_cache_is_not_shared_across_threads(monkeypatch):
    import langgraph.config as lg_config

    _intent_cache.clear()
    payload = {"lane": "edit", "target_field": "budget", "new_value": "500", "confidence": 0.9}
    llm = AsyncMock(return_value=(AIMessage(content=json.dumps(payload)), None))
    thread = {"id": "thread-a"}
    monkeypatch.setattr(
        lg_config, "get_config", lambda: {"configurable": {"thread_id": thread["id"]}},
    )
    with patch("app.graph.resume_router.tracked_ainvoke", new=llm):
        await classify_resume_intent("make it 500", "geo_collect_locations")
        await classify_resume_intent("make it 500", "geo_collect_locations")   # same thread: cached
        thread["id"] = "thread-b"
        await classify_resume_intent("make it 500", "geo_collect_locations")   # other thread: fresh
    assert llm.await_count == 2
    _intent_cache.clear()


# ── handoff writes ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handoff_write_during_ask_survives_the_node_return():
    """builder_ask returns its own copy of the builder state; a handoff tool
    (undo) writing to state["campaign_builder_state"] used to write the INPUT
    dict, so the revert vanished on return."""
    from app.graph.builder import builder_node

    restored = {"location_scope": "granular_local", "locations": "Montreal"}

    async def _fake_interrupt(writer, *, state, **_kw):
        # What interject_tools.undo() does through its contextvar: reassign keys
        # on state["campaign_builder_state"].
        state["campaign_builder_state"]["filled"] = dict(restored)
        state["campaign_builder_state"]["_undo_stack"] = []
        return ResumeResult("Montreal")

    state = {
        "messages": [HumanMessage(content="x", id="p0-handoff")],
        "user_info": {},
        "campaign_builder_state": {
            "filled": {"location_scope": "granular_local", "locations": "Toronto"},
            "_undo_stack": [{"filled": restored}],
            "next_action": {"kind": "ask", "slot": "locations"},
        },
    }
    with patch.object(builder_node, "wizard_interrupt", new=_fake_interrupt), \
         patch.object(builder_node, "get_writer", return_value=lambda _e: None):
        out = await builder_node.builder_ask(state)

    bs = out["campaign_builder_state"]
    assert bs["_undo_stack"] == []
    assert bs["filled"]["location_scope"] == "granular_local"


def test_undo_is_recorded_in_the_change_ledger():
    import asyncio

    from app.graph.builder import interject_tools as it

    state = _state("p0-undo-ledger")
    state["campaign_builder_state"] = {
        "filled": {"a": "2"}, "ops_done": [], "_undo_stack": [{"filled": {"a": "1"}, "ops_done": []}],
    }
    token = it._ho_state.set(state)
    try:
        asyncio.run(it.undo.ainvoke({}))
    finally:
        it._ho_state.reset(token)
    assert state["campaign_builder_state"]["filled"] == {"a": "1"}
    assert "reverted the last edit" in drain_changes(state)["applied"]


def test_ledger_is_said_even_with_the_narrator_disabled(monkeypatch):
    import asyncio

    from app.core.config import settings
    from app.graph.narrator import beats, composer

    state = _state("p0-narrator-off")
    record_change(state, heard={"budget": "set budget = 500"})
    beats.add_beat(state, "framing", {"stage": "x"}, fallback="x")
    monkeypatch.setattr(settings, "WIZARD_NARRATOR_ENABLED", False)
    events: list = []

    text, _ = asyncio.run(composer._compose(state, events.append, emit=True))

    assert "Not applied yet: set budget = 500" in text
    assert any("set budget = 500" in e.get("content", "") for e in events)


def test_a_removed_angle_is_not_reactivated_by_an_emptied_list():
    """"forget the cafes, just do events": the model also empties poi_types. The
    poi_types edit used to switch `category` back ON after the replace."""
    bs = {"ops_done": ["geo_discover"], "filled": {"det_type": "category", "poi_types": "cafe"}}
    stash_edits(bs, ResumeResult("x", edits={
        "deterministic_subtype": ["event_based"], "_angle_removals": ["category"], "poi_types": [],
    }))
    apply_pending_edits(bs)
    assert bs["filled"]["det_type"] == "event_based"
