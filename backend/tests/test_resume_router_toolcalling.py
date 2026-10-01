"""
Tests for Phase 3's tool-calling classifier backend
(resume_router.classify_resume_intent_tools), gated behind
settings.RESUME_ROUTER_TOOLCALLING.

Same coverage shape as test_resume_router.py's lane-classifier tests — mocked
LLM (tracked_ainvoke), no network — because the whole point of this backend
is that it returns the IDENTICAL ResumeIntent shape the lane classifier does,
so the existing dispatch in wizard_helpers.py needs zero new tests of its
own; only "does this backend translate tool calls into that shape correctly"
needs covering here.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.graph.resume_router import (
    _TOOLCALL_SYSTEM_PROMPT,
    _intent_cache,
    _translate_tool_calls,
    classify_resume_intent_tools,
    is_sentinel_resume,
)


@pytest.fixture(autouse=True)
def _clear_intent_cache():
    """Same reasoning as test_resume_router.py's own autouse fixture: without
    this, two tests using the same (raw, step_key) pair silently share a
    cache entry and the second one never invokes its own mock."""
    _intent_cache.clear()
    yield
    _intent_cache.clear()


def _mock_llm_returning(*calls: dict):
    """Patch context that makes the tool-calling classifier LLM return the
    given tool call dicts on its .tool_calls attribute."""
    msg = SimpleNamespace(tool_calls=list(calls))
    return patch(
        "app.graph.resume_router.tracked_ainvoke",
        new=AsyncMock(return_value=(msg, None)),
    )


def _call(name: str, **args) -> dict:
    return {"name": name, "args": args, "id": f"call_{name}"}


# ── sentinel bypass ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_toolcalling_sentinel_skips_llm():
    with patch("app.graph.resume_router.tracked_ainvoke") as mock_invoke:
        intent = await classify_resume_intent_tools("yes", "geo_collect_locations")
        assert intent.lane == "confirm"
        assert mock_invoke.call_count == 0


# ── single-call translation ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_answer_step_translates_to_confirm():
    with _mock_llm_returning(_call("answer_step", value="Montreal")):
        intent = await classify_resume_intent_tools("Montreal", "geo_collect_locations")
    assert intent.lane == "confirm"
    assert intent.answer_value == "Montreal"


@pytest.mark.asyncio
async def test_reject_step_translates_to_reject():
    # "no" is a sentinel value (bypasses the LLM entirely) — use a non-
    # sentinel rejection so the mock actually gets exercised.
    with _mock_llm_returning(_call("reject_step")):
        intent = await classify_resume_intent_tools("not that one", "geo_collect_locations")
    assert intent.lane == "reject"


@pytest.mark.asyncio
async def test_ask_question_translates_to_query():
    with _mock_llm_returning(_call("ask_question", question="what's a POI?")):
        intent = await classify_resume_intent_tools("what's a POI?", "geo_collect_locations")
    assert intent.lane == "query"
    assert intent.question_text == "what's a POI?"


@pytest.mark.asyncio
async def test_edit_field_append_mode():
    with _mock_llm_returning(_call("edit_field", field="location", value="Toronto", mode="append")):
        intent = await classify_resume_intent_tools("also add Toronto", "geo_location_confirmation")
    assert intent.lane == "edit"
    assert intent.target_field == "location"
    assert intent.new_value == "Toronto"
    assert intent.is_append is True
    assert intent.is_remove is False


@pytest.mark.asyncio
async def test_edit_field_remove_mode():
    with _mock_llm_returning(_call("edit_field", field="location", value="Laval", mode="remove")):
        intent = await classify_resume_intent_tools("remove Laval", "geo_location_confirmation")
    assert intent.lane == "edit"
    assert intent.is_remove is True
    assert intent.is_append is False


@pytest.mark.asyncio
async def test_go_back_translates_to_backtrack():
    with _mock_llm_returning(_call("go_back", step_key="geo_collect_locations")):
        intent = await classify_resume_intent_tools(
            "go back to where I picked locations", "geo_pois_confirmation",
        )
    assert intent.lane == "edit"
    assert intent.target_step_key == "geo_collect_locations"


@pytest.mark.asyncio
async def test_trim_pois_maps_to_poi_selection_field():
    # `trim_pois` takes a `spec` dict (Step 4 — the classifier emits the
    # executable selection spec directly, not a verbatim instruction string)
    # translated straight through as `new_value`, same shape `filter_audience`
    # already used for `audience_filter`.
    spec = {"op": "keep", "n": 10, "scope": "all"}
    with _mock_llm_returning(_call("trim_pois", spec=spec)):
        intent = await classify_resume_intent_tools("just the top 10", "geo_pois_confirmation")
    assert intent.lane == "edit"
    assert intent.target_field == "poi_selection"
    assert intent.new_value == spec


@pytest.mark.asyncio
async def test_filter_audience_maps_to_audience_filter_field():
    with _mock_llm_returning(_call("filter_audience", patch={"days_of_week": [5, 6]})):
        intent = await classify_resume_intent_tools("just weekends", "maid_confirm_results")
    assert intent.lane == "edit"
    assert intent.target_field == "audience_filter"
    assert intent.new_value == {"days_of_week": [5, 6]}


@pytest.mark.asyncio
async def test_unhandled_alone():
    with _mock_llm_returning(_call("unhandled", what="frequency cap")):
        intent = await classify_resume_intent_tools("cap frequency at 2", "geo_collect_locations")
    assert intent.lane == "unhandled"


# ── handoff short-circuit ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handoff_tool_call_short_circuits_to_handoff_lane():
    """A call naming a REAL handoff tool (owned by interject_tools.py) must
    not be interpreted here — this backend only recognises THAT it's a
    handoff, defers actual selection to run_handoff_turn."""
    with _mock_llm_returning(_call("undo")):
        intent = await classify_resume_intent_tools("undo that", "geo_collect_locations")
    assert intent.lane == "handoff"
    assert intent.question_text == "undo that"


@pytest.mark.asyncio
async def test_handoff_short_circuit_ignores_other_calls_in_the_batch():
    with _mock_llm_returning(_call("answer_step", value="Montreal"), _call("get_pois")):
        intent = await classify_resume_intent_tools(
            "Montreal, and which of these are worth it", "geo_collect_locations",
        )
    assert intent.lane == "handoff"


# ── multi-call composite (the "yes 2km, and bump my budget to 500" case) ────

@pytest.mark.asyncio
async def test_multi_call_answer_plus_edit_both_land():
    with _mock_llm_returning(
        _call("answer_step", value="2km"),
        _call("edit_field", field="budget", value="500", mode="replace"),
    ):
        intent = await classify_resume_intent_tools(
            "yes 2km, and bump my budget to 500", "geo_radius_km",
        )
    assert intent.lane == "edit"
    assert intent.answer_value == "2km"
    assert intent.target_field == "budget"
    assert intent.new_value == "500"


@pytest.mark.asyncio
async def test_multi_call_three_things_extra_edits_carries_the_rest():
    with _mock_llm_returning(
        _call("answer_step", value="chicago works"),
        _call("ask_question", question="what is a POI"),
        _call("edit_field", field="budget", value="500", mode="replace"),
        _call("edit_field", field="deterministic_subtype", value="event_based", mode="append"),
    ):
        intent = await classify_resume_intent_tools(
            "chicago works, what's a POI, also bump my budget to 500, and add events too",
            "geo_collect_locations",
        )
    assert intent.answer_value == "chicago works"
    assert intent.question_text == "what is a POI"
    assert intent.target_field == "budget"
    assert len(intent.extra_edits) == 1
    assert intent.extra_edits[0].target_field == "deterministic_subtype"


# ── post-validation reuse (unknown field collapses to unhandled) ────────────

@pytest.mark.asyncio
async def test_hallucinated_field_collapses_to_unhandled():
    """Proves _post_validate_edit_lane is genuinely shared — a bogus field
    from a tool call's `field` arg is exactly as dangerous as one from the
    JSON classifier and must be caught the same way."""
    with _mock_llm_returning(_call("edit_field", field="not_a_real_field", value="x")):
        intent = await classify_resume_intent_tools("x", "geo_collect_locations")
    assert intent.lane == "unhandled"


# ── degenerate cases ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_tool_calls_falls_back_to_reject():
    with _mock_llm_returning():
        intent = await classify_resume_intent_tools("...", "geo_collect_locations")
    assert intent.lane == "reject"


@pytest.mark.asyncio
async def test_unrecognised_tool_name_is_ignored_not_crashed():
    with _mock_llm_returning({"name": "some_hallucinated_tool", "args": {}, "id": "x"}):
        intent = await classify_resume_intent_tools("x", "geo_collect_locations")
    assert intent.lane == "reject"


@pytest.mark.asyncio
async def test_classifier_crash_degrades_to_lane_json_not_reject():
    """A crash (e.g. a tool schema Gemini's converter rejects) must reach the
    lane-JSON backend — it used to become lane="reject", i.e. the user was told
    their sentence was unclear when the router never ran."""
    from app.graph.resume_router import ResumeIntent

    fallback = ResumeIntent(lane="edit", target_field="poi_selection",
                            new_value={"op": "keep", "n": 20}, confidence=0.9)
    with patch("app.graph.resume_router.tracked_ainvoke",
               new=AsyncMock(side_effect=ValueError("schema crash"))), \
         patch("app.graph.resume_router.classify_resume_intent",
               new=AsyncMock(return_value=fallback)) as lane_json:
        intent = await classify_resume_intent_tools("target the best 20 spots", "geo_pois_confirmation")
    assert intent is fallback
    assert lane_json.await_count == 1


# ── cache ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_toolcalling_replay_is_free():
    _intent_cache.clear()
    with _mock_llm_returning(_call("answer_step", value="Montreal")) as mock_invoke:
        first = await classify_resume_intent_tools("hmm", "geo_collect_locations")
        second = await classify_resume_intent_tools("hmm", "geo_collect_locations")
    assert mock_invoke.await_count == 1
    assert first.lane == second.lane == "confirm"


@pytest.mark.asyncio
async def test_toolcalling_and_lane_classifier_never_share_a_cache_entry():
    """Different cache namespace ('TC\\x00' prefix) — a replay must not read
    one backend's decision through the other's key."""
    from app.graph.resume_router import _hash, classify_resume_intent

    _intent_cache.clear()
    with _mock_llm_returning(_call("answer_step", value="Montreal")):
        await classify_resume_intent_tools("hmm", "geo_collect_locations")
    lane_key = ("geo_collect_locations", _hash("hmm" + "\x00"))
    assert lane_key not in _intent_cache


# ── translation helper (pure, no LLM) ───────────────────────────────────────

def test_translate_empty_calls_is_reject():
    intent = _translate_tool_calls([], "raw", "geo_collect_locations")
    assert intent.lane == "reject"
    assert intent.confidence == 0.0


def test_translate_accepts_object_shaped_calls_not_just_dicts():
    """LangChain tool_calls are sometimes plain dicts, sometimes ToolCall
    objects with attribute access — the translator must handle both."""
    call = SimpleNamespace(name="answer_step", args={"value": "Montreal"}, id="1")
    intent = _translate_tool_calls([call], "Montreal", "geo_collect_locations")
    assert intent.lane == "confirm"
    assert intent.answer_value == "Montreal"


# ── prompt content ───────────────────────────────────────────────────────────

def test_toolcall_prompt_has_hypothetical_guard():
    assert "HYPOTHETICAL" in _TOOLCALL_SYSTEM_PROMPT
    assert "ask_question" in _TOOLCALL_SYSTEM_PROMPT


# ── end-to-end: the settings flag actually selects this backend ────────────
# A self-contained twin of test_resume_router.py's _loop_harness (not
# cross-imported — tests/ has no __init__.py, so module-to-module test
# imports are fragile here) proving wizard_interrupt's classifier dispatch
# (wizard_helpers.py: `_classify = classify_resume_intent_tools if
# settings.RESUME_ROUTER_TOOLCALLING else classify_resume_intent`) genuinely
# routes to THIS backend when the flag is on, and that the untouched dispatch
# block resolves its output exactly like it would the lane classifier's.

@contextmanager
def _loop_harness(toolcall_results, interrupt_values):
    import app.graph.wizard_helpers as wh

    with ExitStack() as stack:
        stack.enter_context(patch.object(wh.settings, "RESUME_ROUTER_TOOLCALLING", True))
        stack.enter_context(patch(
            "app.graph.wizard_helpers.interrupt", side_effect=list(interrupt_values),
        ))
        stack.enter_context(patch(
            "app.graph.wizard_helpers.classify_resume_intent_tools",
            new=AsyncMock(side_effect=list(toolcall_results)),
        ))
        # If the flag failed to route here, the lane classifier would be
        # called instead — fail loudly rather than silently classifying via
        # the wrong backend.
        stack.enter_context(patch(
            "app.graph.wizard_helpers.classify_resume_intent",
            new=AsyncMock(side_effect=AssertionError(
                "flag on: classify_resume_intent (lane backend) must not be called"
            )),
        ))
        mock_narrate = stack.enter_context(patch("app.graph.wizard_helpers.narrate", new=AsyncMock()))
        stack.enter_context(patch("app.graph.wizard_helpers.wizard_ask", new=AsyncMock()))
        stack.enter_context(patch("app.graph.wizard_helpers.generate_chips", new=AsyncMock(return_value=[])))
        stack.enter_context(patch("app.graph.wizard_helpers.flush_narration", new=AsyncMock()))
        stack.enter_context(patch("app.graph.wizard_helpers._narrator_peek", return_value=False))
        stack.enter_context(patch("app.graph.wizard_helpers._narrator_drain", return_value=[]))
        yield mock_narrate


@pytest.mark.asyncio
async def test_flag_on_routes_wizard_interrupt_to_the_toolcalling_backend():
    from app.graph.resume_router import ResumeIntent
    from app.graph.wizard_helpers import wizard_interrupt

    resumed_state = {
        "pending_action": {"step_key": "geo_collect_locations"},
        "campaign_builder_state": {},
    }
    with _loop_harness(
        toolcall_results=[ResumeIntent(lane="confirm", answer_value="Montreal", confidence=0.9)],
        interrupt_values=["Montreal"],
    ):
        writer_events = []
        result = await wizard_interrupt(
            writer=writer_events.append,
            step_key="geo_collect_locations",
            context="test",
            state=resumed_state,
        )
    assert str(result) == "Montreal"


def test_toolcall_prompt_covers_multi_call_and_confidence_replacement():
    """Tool names themselves don't need to appear in the system prompt text —
    a bound tool's name/description reaches the model through the
    function-calling schema, not prose duplication (unlike the old lane
    classifier, which had no such channel and had to spell out every lane).
    What the prompt DOES need to say is the stuff the schema can't carry:
    call several tools per turn, and what "unsure" means with no confidence
    field to fall back on."""
    assert "SEVERAL" in _TOOLCALL_SYSTEM_PROMPT.upper()
    assert "ask_question" in _TOOLCALL_SYSTEM_PROMPT
    assert "unhandled" in _TOOLCALL_SYSTEM_PROMPT
    assert "confidence" in _TOOLCALL_SYSTEM_PROMPT.lower()


# ── an empty answer is retried, then handed to the lane-JSON classifier ───────


@pytest.mark.asyncio
async def test_no_tool_call_is_retried_once_and_the_retry_wins():
    empty = (SimpleNamespace(tool_calls=[]), None)
    good = (SimpleNamespace(tool_calls=[_call("edit_field", field="budget", value="500", mode="replace")]), None)
    with patch("app.graph.resume_router.tracked_ainvoke", new=AsyncMock(side_effect=[empty, good])) as llm:
        intent = await classify_resume_intent_tools("make it 500", "geo_collect_locations")
    assert intent.lane == "edit" and intent.target_field == "budget"
    assert llm.await_count == 2


@pytest.mark.asyncio
async def test_two_empty_answers_fall_back_to_the_json_classifier_not_a_reject():
    empty = (SimpleNamespace(tool_calls=[]), None)
    from app.graph.resume_router import ResumeIntent

    json_intent = ResumeIntent(lane="edit", target_field="budget", new_value="500", confidence=0.9)
    with patch("app.graph.resume_router.tracked_ainvoke", new=AsyncMock(side_effect=[empty, empty])) as llm, \
         patch("app.graph.resume_router.classify_resume_intent", new=AsyncMock(return_value=json_intent)) as fallback:
        intent = await classify_resume_intent_tools("make it 500", "geo_collect_locations")
    assert intent is json_intent and llm.await_count == 2 and fallback.await_count == 1


@pytest.mark.asyncio
async def test_two_stalls_fall_back_to_the_json_classifier_not_a_reject():
    from app.graph.resume_router import ResumeIntent

    json_intent = ResumeIntent(lane="edit", target_field="budget", new_value="500", confidence=0.9)
    with patch("app.graph.resume_router.tracked_ainvoke", new=AsyncMock(side_effect=[TimeoutError(), TimeoutError()])) as llm, \
         patch("app.graph.resume_router.classify_resume_intent", new=AsyncMock(return_value=json_intent)) as fallback:
        intent = await classify_resume_intent_tools("make it 500", "geo_collect_locations")
    assert intent is json_intent and llm.await_count == 2 and fallback.await_count == 1


@pytest.mark.asyncio
async def test_one_stall_is_retried_transparently():
    good = (SimpleNamespace(tool_calls=[_call("edit_field", field="budget", value="500", mode="replace")]), None)
    with patch("app.graph.resume_router.tracked_ainvoke", new=AsyncMock(side_effect=[TimeoutError(), good])):
        intent = await classify_resume_intent_tools("make it 500", "geo_collect_locations")
    assert intent.lane == "edit" and intent.target_field == "budget"
