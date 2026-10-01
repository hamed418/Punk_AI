"""
Phase 3 of the mid-turn edit redesign: the classifier is generated from the
knob registry and runs on function-calling.

  * the edit tool's field is an enum of real knobs — the model can't invent one
  * relative changes are computed in code from the live value
  * a change scoped to one item of an unscoped number is refused honestly
  * ambiguity asks (clarify) instead of guessing
  * an unsupported ask alongside real edits no longer discards the edits
  * an explicit replace of the angles actually replaces them
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from app.graph.builder.edits import apply_edits, stash_edits
from app.graph.builder.knobs import KNOBS, current_values, knob_catalog, resolve_relative
from app.graph.resume_router import (
    ResumeIntent, ResumeResult, _classifier_context, _edit_field_tool,
    _structural_tools, _translate_tool_calls,
)


def _state(**bs) -> dict:
    return {
        "messages": [HumanMessage(content="x", id=f"rr-{id(bs)}")],
        "user_info": {"budget": "$500"},
        "campaign_builder_state": {"filled": {}, **bs},
    }


def _call(name: str, **args) -> dict:
    return {"name": name, "args": args, "id": "c1"}


# ── schema ────────────────────────────────────────────────────────────────────


def test_edit_field_is_an_enum_of_real_knobs():
    from app.graph.builder.knobs import edit_field_knobs

    schema = _edit_field_tool().args_schema.model_json_schema()
    allowed = set(schema["properties"]["field"]["enum"])
    assert {k.name for k in edit_field_knobs()} <= allowed
    # Owned by their dedicated tools, so one intent can't split across two.
    assert "poi_selection" not in allowed and "audience_filter" not in allowed
    assert "meta_ad_account_id" in allowed          # gets the specific refusal
    assert "geo_radius_pin" not in allowed          # not typeable


def test_catalog_carries_units_choices_and_confusables():
    cat = knob_catalog()
    assert "search_radius_km (unit km" in cat and "NOT poi_radius_m" in cat
    assert "one of country_groups|admin_areas|granular_local|radius" in cat


def test_handoff_tools_are_bound_but_not_the_trim_twin():
    names = {t.name for t in _structural_tools()}
    assert {"undo", "get_build_state", "list_changeable", "clarify"} <= names
    assert "narrow_pois" not in names and "trim_pois" in names


# ── relative + scoped changes ─────────────────────────────────────────────────


@pytest.mark.parametrize("op,value,current,expected", [
    ("scale", "double", "12 km", "24 km"),
    ("scale", "half", "12 km", "6 km"),
    ("scale", "3x", "12 km", "36 km"),
    ("delta", "+2 km", "12 km", "14 km"),
    ("delta", "1 mile", "12 km", "13.6093 km"),
    ("delta", "2 km smaller", "12 km", "10 km"),
    ("delta", "5 more days", "14", "19 days"),
    ("scale", "double", None, None),               # nothing to be relative to
    ("scale", "a lot", "12 km", None),             # no number → ask
])
def test_relative_changes_are_computed_in_code(op, value, current, expected):
    knob = KNOBS["lookback_days"] if "days" in value else KNOBS["search_radius_km"]
    assert resolve_relative(knob, op, value, current) == expected


def test_scale_uses_the_live_value():
    state = _state(geo_ws={"_search_ring_km": 12.0})
    intent = _translate_tool_calls(
        [_call("edit_field", field="search_radius_km", value="double", mode="scale")],
        "double the circle", "geo_location_confirmation", state,
    )
    assert intent.lane == "edit" and intent.new_value == "24 km"


def test_relative_change_with_no_value_to_scale_asks():
    intent = _translate_tool_calls(
        [_call("edit_field", field="search_radius_km", value="double", mode="scale")],
        "double the circle", "geo_location_confirmation", _state(),
    )
    assert intent.lane == "clarify"
    assert intent.clarify_options == ["search_radius_km"]


def test_one_locations_circle_becomes_its_own_scoped_edit():
    intent = _translate_tool_calls(
        [_call("edit_field", field="search_radius_km", value="3 km", target="Laval")],
        "just Laval's circle to 3 km", "geo_location_confirmation", _state(),
    )
    assert intent.lane == "edit"
    assert intent.target_field == "location_ring" and intent.edit_target == "Laval"
    assert intent.new_value == "3 km"


def test_a_visit_ring_for_one_group_is_scoped_not_refused():
    intent = _translate_tool_calls(
        [_call("edit_field", field="poi_radius_m", value="50 m", target="cafes")],
        "50 m for the cafes", "maid_confirm_results", _state(),
    )
    assert intent.lane == "edit" and intent.target_field == "poi_radius_m"
    assert intent.edit_target == "cafes" and intent.new_value == "50 m"


def test_a_number_scoped_to_one_item_that_cant_be_is_still_refused_honestly():
    intent = _translate_tool_calls(
        [_call("edit_field", field="lookback_days", value="14", target="cafes")],
        "14 days for the cafes", "maid_confirm_results", _state(),
    )
    assert intent.lane == "unhandled" and "cafes" in intent.unsupported_what


# ── clarify / unsupported ─────────────────────────────────────────────────────


def test_clarify_call_becomes_the_clarify_lane():
    intent = _translate_tool_calls(
        [_call("clarify", options=["search_radius_km", "poi_radius_m"],
               question="The search circle or the ring around each spot?")],
        "make the radius bigger", "maid_confirm_results",
    )
    assert intent.lane == "clarify"
    assert intent.clarify_options == ["search_radius_km", "poi_radius_m"]


def test_unsupported_part_no_longer_discards_the_real_edit():
    intent = _translate_tool_calls(
        [_call("unhandled", what="only women"),
         _call("edit_field", field="budget", value="$800")],
        "only women, and budget 800", "maid_confirm_results",
    )
    assert intent.lane == "edit" and intent.target_field == "budget"
    assert intent.unsupported_what == "only women"


# ── explicit replace of angles ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_explicit_replace_of_angles_actually_replaces():
    from app.graph.wizard_helpers import _dispatch_edit_intent

    intent = _translate_tool_calls(
        [_call("edit_field", field="deterministic_subtype", value="event_based", mode="replace")],
        "forget the cafes, just do events", "geo_pois_confirmation",
    )
    assert intent.is_replace
    state = _state()
    edits: dict = {}
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
        await _dispatch_edit_intent(
            intent=intent.model_copy(update={"confidence": 0.95}), state=state,
            writer=lambda _e: None, pending={}, cfg={"field": "geo_pois_confirmation"},
            edits=edits, edit_base={"deterministic_subtype": ["category"]},
        )
    bs = {"ops_done": ["geo_discover"], "filled": {"det_type": "category"}}
    stash_edits(bs, ResumeResult("x", edits=edits))
    apply_edits(bs, state)
    assert bs["filled"]["det_type"] == "event_based"


# ── context + lanes in the interrupt ──────────────────────────────────────────


def test_context_carries_current_values_and_a_pending_question():
    state = _state(
        filled={"poi_radius_m": "100", "lookback_days": "14"},
        _clarify={"question": "Search circle or visit ring?", "raw": "make it bigger",
                  "options": ["search_radius_km", "poi_radius_m"]},
    )
    ctx = _classifier_context("maid_confirm_results", state)
    assert "Current values:" in ctx and "poi_radius_m=100 m" in ctx and "budget=$500" in ctx
    assert 'Punk just asked: "Search circle or visit ring?"' in ctx
    assert '"make it bigger"' in ctx


def test_clarify_lane_asks_and_remembers_the_request():
    from app.graph import wizard_helpers as wh
    from app.graph.narrator import beats

    state = _state(_single_interrupt=True)
    state["messages"] = [HumanMessage(content="x", id="rr-clarify-lane")]
    intent = ResumeIntent(lane="clarify", clarify_options=["search_radius_km", "poi_radius_m"],
                          question_text="Search circle or visit ring?", confidence=0.9)
    with patch("app.graph.wizard_helpers.get_stream_writer", return_value=MagicMock()), \
         patch("app.graph.wizard_helpers.narrate", new=AsyncMock()), \
         patch("app.graph.wizard_helpers.flush_narration", new=AsyncMock(return_value=("", {}))), \
         patch("app.graph.wizard_helpers.settings.RESUME_ROUTER_TOOLCALLING", False), \
         patch("app.graph.wizard_helpers.interrupt", side_effect=["make the radius bigger"]), \
         patch("app.graph.wizard_helpers.classify_resume_intent", new=AsyncMock(return_value=intent)):
        result = asyncio.run(wh.wizard_interrupt(MagicMock(), "maid_confirm_results", "ctx", state=state))

    assert result.answered is False and result.edits == {}
    assert state["campaign_builder_state"]["_clarify"]["raw"] == "make the radius bigger"
    kinds = [b.kind for b in beats.drain(state)]
    assert "clarify" in kinds


def test_list_changeable_answers_from_the_registry():
    from app.graph.builder import interject_tools as it

    state = _state(filled={"poi_radius_m": "100"})
    token = it._ho_state.set(state)
    try:
        out = it.list_changeable.invoke({})
    finally:
        it._ho_state.reset(token)
    settings = {c["setting"]: c for c in out["changeable"]}
    assert "search radius km" in settings and settings["poi radius m"]["now"] == "100 m"
    assert current_values(state)["poi_radius_m"] == "100 m"
