"""
tests/test_single_interrupt.py
──────────────────────────────
Phase 1 of the mid-turn edit redesign: ONE interrupt() per task.

A reply that doesn't answer the step on screen (an edit, a question, a reject,
a handoff) returns `answered=False` instead of looping in place. The caller
ends its task; builder_plan applies the stashed edits and re-dispatches, so:
  * an edit is applied in the same request that acknowledged it,
  * a non-answer is never written into the slot as its "answer",
  * a replay can never re-classify an earlier reply.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from app.graph import wizard_helpers as wh
from app.graph.resume_router import ResumeIntent, ResumeResult
from app.graph.wizard_exit import StepPaused, WizardExitRequested

STEP = "geo_wizard_plan_review"


def _state(msg_id: str, single: bool = True, **bs) -> dict:
    return {
        "messages": [HumanMessage(content="hi", id=msg_id)],
        "campaign_builder_state": {"filled": {}, "_single_interrupt": single, **bs},
    }


@pytest.fixture()
def _env():
    with patch("app.graph.wizard_helpers.get_stream_writer", return_value=MagicMock()), \
         patch("app.graph.wizard_helpers.wizard_ask", new=AsyncMock(return_value=None)), \
         patch("app.graph.wizard_helpers.narrate", new=AsyncMock(return_value=None)), \
         patch("app.graph.wizard_helpers.flush_narration", new=AsyncMock(return_value=("", {}))), \
         patch("app.graph.wizard_helpers.settings.RESUME_ROUTER_TOOLCALLING", False):
        yield


def _run(state, replies, intents, step=STEP):
    with patch("app.graph.wizard_helpers.interrupt", side_effect=list(replies)) as intr, \
         patch("app.graph.wizard_helpers.classify_resume_intent",
               new=AsyncMock(side_effect=list(intents))):
        result = asyncio.run(wh.wizard_interrupt(MagicMock(), step, "ctx", state=state))
    return result, intr.call_count


# ── the contract ──────────────────────────────────────────────────────────────


def test_edit_returns_unanswered_after_one_interrupt(_env):
    st = _state("si-edit")
    edit = ResumeIntent(lane="edit", target_field="business_name", new_value="Gym Co", confidence=0.95)

    result, n_interrupts = _run(st, ["rename it Gym Co"], [edit])

    assert n_interrupts == 1
    assert result.answered is False
    assert result.edits == {"business_name": "Gym Co"}
    att = st["campaign_builder_state"]["_ask_attempts"][STEP]
    assert (att["total"], att["reject"]) == (1, 0)


@pytest.mark.parametrize("intent", [
    ResumeIntent(lane="reject", confidence=0.9),
    ResumeIntent(lane="query", question_text="what's a POI", confidence=0.9),
    ResumeIntent(lane="unhandled", target_field="age", confidence=0.9),
])
def test_every_non_answer_lane_returns_after_one_interrupt(_env, intent):
    st = _state(f"si-lane-{intent.lane}")
    result, n_interrupts = _run(st, ["something"], [intent])
    assert n_interrupts == 1
    assert result.answered is False


def test_answer_returns_answered_and_clears_the_counters(_env):
    st = _state("si-answer", _ask_attempts={STEP: {"total": 2, "reject": 1}})
    result, _ = _run(st, ["Montreal"], [ResumeIntent(lane="confirm", confidence=0.95)])
    assert result.answered is True
    assert str(result) == "Montreal"
    assert STEP not in st["campaign_builder_state"]["_ask_attempts"]


def test_composite_answer_plus_edit_is_answered_and_carries_the_edit(_env):
    st = _state("si-composite")
    intent = ResumeIntent(
        lane="edit", target_field="business_name", new_value="Gym Co",
        answer_value="Montreal", confidence=0.95,
    )
    result, _ = _run(st, ["Montreal, and rename it Gym Co"], [intent])
    assert result.answered is True
    assert str(result) == "Montreal"
    assert result.edits == {"business_name": "Gym Co"}


def test_reject_budget_persists_across_tasks_and_exits(_env):
    """The off-path budget used to live in the loop's locals; with one interrupt
    per task it must persist, or the escape hatch could never be reached."""
    st = _state("si-budget", _ask_attempts={STEP: {"total": 3, "reject": wh._MAX_NONANSWER_LOOPS - 1}})
    result, _ = _run(st, ["hmm not that one"], [ResumeIntent(lane="reject", confidence=0.9)])
    assert result.answered is False
    with pytest.raises(WizardExitRequested):
        _run(st, [], [])
    # Reset on exit, so "continue" later doesn't exit again before asking.
    assert STEP not in st["campaign_builder_state"]["_ask_attempts"]


def test_legacy_mode_still_loops_in_place(_env):
    st = _state("si-legacy", single=False)
    edit = ResumeIntent(lane="edit", target_field="business_name", new_value="Gym Co", confidence=0.95)
    result, n_interrupts = _run(
        st, ["rename it", "yes"], [edit, ResumeIntent(lane="confirm", confidence=0.95)],
    )
    assert n_interrupts == 2
    assert result.answered is True
    assert result.edits == {"business_name": "Gym Co"}


def test_handoff_write_is_queued_not_executed(_env):
    """Handoff write tools queue a control op on `edits` in single mode, so the
    write runs once in builder_plan rather than in (and on every replay of)
    the interrupt task."""
    st = _state("si-handoff", _undo_stack=[{"filled": {"a": "1"}, "ops_done": []}])
    captured = {}

    async def _fake_handoff(raw, step_key, state, edits=None):
        captured["edits"] = edits
        from app.graph.builder import interject_tools as it

        token = it._ho_edits.set(edits)
        state_token = it._ho_state.set(state)
        try:
            await it.undo.ainvoke({})
        finally:
            it._ho_edits.reset(token)
            it._ho_state.reset(state_token)
        return it.HandoffResult("reverting", abort=False)

    with patch("app.graph.builder.interject_tools.run_handoff_turn", new=_fake_handoff):
        result, _ = _run(st, ["undo that"], [ResumeIntent(lane="handoff", question_text="undo that", confidence=0.9)])

    assert result.answered is False
    assert result.edits == {"_undo": True}
    assert st["campaign_builder_state"]["_undo_stack"]            # not popped yet
    assert "filled" in st["campaign_builder_state"] and st["campaign_builder_state"]["filled"] == {}


# ── call sites ────────────────────────────────────────────────────────────────


def test_builder_ask_never_writes_a_non_answer_into_the_slot():
    """A budget edit typed at poi_confirm used to be written into the gate as
    its answer."""
    from app.graph.builder import builder_node

    async def _fake_interrupt(writer, **_kw):
        return ResumeResult("bump budget to 500", edits={"budget": "500"}, answered=False)

    state = {
        "messages": [HumanMessage(content="x", id="si-ask")],
        "user_info": {},
        "campaign_builder_state": {
            "filled": {"location_scope": "granular_local", "locations": "Montreal"},
            "next_action": {"kind": "ask", "slot": "locations"},
            "_single_interrupt": True,
        },
    }
    state["campaign_builder_state"]["filled"].pop("locations")
    with patch.object(builder_node, "wizard_interrupt", new=_fake_interrupt), \
         patch.object(builder_node, "get_writer", return_value=lambda _e: None):
        out = asyncio.run(builder_node.builder_ask(state))

    bs = out["campaign_builder_state"]
    assert "locations" not in bs["filled"]
    assert bs["_pending_edits"] == {"budget": "500"}
    assert bs["next_action"] is None
    assert bs["_reask_tick"] is True


def test_builder_plan_runs_a_queued_undo():
    from app.graph.builder import builder_node

    bs = {
        "filled": {"location_scope": "granular_local", "locations": "Toronto"},
        "ops_done": [], "_single_interrupt": True, "_prefill_seeded": True,
        "_undo_stack": [{"filled": {"location_scope": "granular_local", "locations": "Montreal"},
                         "ops_done": []}],
        "_pending_edits": {"_undo": True},
    }
    state = {"messages": [HumanMessage(content="x", id="si-plan-undo")], "user_info": {},
             "campaign_builder_state": bs}
    with patch.object(builder_node, "get_writer", return_value=lambda _e: None), \
         patch.object(builder_node, "tracked_ainvoke", new=AsyncMock(side_effect=RuntimeError("no llm"))):
        out = asyncio.run(builder_node.builder_plan(state))

    assert out["campaign_builder_state"]["filled"]["locations"] == "Montreal"
    assert out["campaign_builder_state"]["_undo_stack"] == []


def test_builder_plan_skips_the_planner_llm_on_a_reask_tick():
    from app.graph.builder import builder_node

    bs = {"filled": {}, "ops_done": [], "_single_interrupt": True, "_prefill_seeded": True,
          "_reask_tick": True}
    state = {"messages": [HumanMessage(content="x", id="si-plan-skip")], "user_info": {},
             "campaign_builder_state": bs}
    llm = AsyncMock(side_effect=AssertionError("planner LLM must not run on a re-ask tick"))
    with patch.object(builder_node, "get_writer", return_value=lambda _e: None), \
         patch.object(builder_node, "tracked_ainvoke", new=llm):
        out = asyncio.run(builder_node.builder_plan(state))

    assert llm.await_count == 0
    assert out["campaign_builder_state"]["next_action"]["kind"] in ("ask", "act")
    assert "_reask_tick" not in out["campaign_builder_state"]


def test_step_paused_is_a_geo_pause_too():
    from app.graph.builder.executors.geo import _GeoStepPaused

    assert issubclass(_GeoStepPaused, StepPaused)


def test_account_select_pauses_on_a_non_answer():
    """An edit typed at the ad-account picker used to fall through to "I didn't
    catch which account that was" right after the edit was acknowledged."""
    from app.graph.builder.executors import media

    async def _fake_interrupt(writer, **_kw):
        return ResumeResult("also add Toronto", edits={"location": ["Toronto"]}, answered=False)

    shared = {
        "needs_account_selection": True, "access_token": "t",
        "accessible_accounts": [{"id": "act_1", "name": "A"}, {"id": "act_2", "name": "B"}],
    }
    state = {
        "messages": [HumanMessage(content="x", id="si-acct")],
        "user_info": {},
        "media_wizard_state": shared,
        "campaign_builder_state": {"_single_interrupt": True},
    }
    with patch.object(media, "wizard_interrupt", new=_fake_interrupt), \
         patch.object(media, "get_writer", return_value=lambda _e: None), \
         pytest.raises(StepPaused):
        asyncio.run(media.media_select_ad_account(state))

    assert shared["_pending_edits"] == {"location": ["Toronto"]}
    assert shared["needs_account_selection"] is True


def test_an_edit_to_the_active_field_survives_into_the_reask(_env):
    """"actually make it 500" at a step that owns the field only updates the
    suggested value; with one interrupt per task the re-ask is a NEW task, which
    used to re-derive the original suggestion and lose the correction."""
    st = _state("si-prefill")
    field = wh.STEP_PROMPTS[STEP]["field"]
    edit = ResumeIntent(lane="edit", target_field=field, new_value="500", confidence=0.95)

    first, _ = _run(st, ["actually make it 500"], [edit])
    assert first.answered is False
    saved = st["campaign_builder_state"]["_ask_attempts"][STEP]
    assert saved["prefill"] == "500" and saved["prefill_source"] == "user_edit"

    # The next task for the same step (fresh call, original suggestion passed in)
    captured = {}

    async def _spy_flush(state, writer):
        return "", {}

    with patch("app.graph.wizard_helpers.interrupt", side_effect=lambda v: captured.setdefault("iv", v) and "yes"),          patch("app.graph.wizard_helpers.classify_resume_intent", new=AsyncMock()):
        asyncio.run(wh.wizard_interrupt(MagicMock(), STEP, "ctx", state=st, prefill="100"))
    assert captured["iv"]["prefill"] == "500"


def test_a_reject_clears_the_suggestion_for_the_reask(_env):
    st = _state("si-reject-prefill")
    _run(st, ["hmm not that one"], [ResumeIntent(lane="reject", confidence=0.9)])
    assert st["campaign_builder_state"]["_ask_attempts"][STEP]["prefill"] is None
