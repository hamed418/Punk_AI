"""The `handoff` lane of wizard_interrupt (wizard_helpers.py) — a mid-build
question or process action ("what's a POI?", "undo that", "stop") answered in
place, then the SAME widget re-shown.

`run_handoff_turn` itself is covered in test_interject_tools.py; these drive the
real interrupt loop around it, which had no test at all.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from app.graph import wizard_helpers as wh
from app.graph.builder.interject_tools import HandoffResult

STEP = "geo_wizard_plan_review"


def _state():
    # Distinct message id: narrator buffers are keyed by it process-wide (see
    # test_wizard_interrupt_user_turn.py for the collision this avoids).
    return {
        "messages": [HumanMessage(content="hi", id="wizard-interrupt-handoff-m1")],
        "campaign_builder_state": {"filled": {}},
    }


def _handoff(confidence: float) -> MagicMock:
    return MagicMock(
        lane="handoff", target_field=None, is_append=False, confidence=confidence,
        question_text=None, answer_value=None, extra_edits=None,
    )


@pytest.fixture()
def env():
    narrate = AsyncMock(return_value=None)
    with patch("app.graph.wizard_helpers.get_stream_writer", return_value=MagicMock()), \
         patch("app.graph.wizard_helpers.wizard_ask", new=AsyncMock(return_value=None)), \
         patch("app.graph.wizard_helpers.generate_chips", new=AsyncMock(return_value=[])), \
         patch("app.graph.wizard_helpers.flush_narration", new=AsyncMock(return_value=("", {}))), \
         patch("app.graph.wizard_helpers.narrate", new=narrate), \
         patch("app.graph.wizard_helpers.settings.RESUME_ROUTER_TOOLCALLING", False):
        yield narrate


def _run(replies, intent, handoff_result):
    """Drive the loop: each reply in `replies` is one interrupt() resume."""
    run = AsyncMock(return_value=handoff_result)
    with patch("app.graph.wizard_helpers.interrupt", side_effect=replies) as interrupt_mock, \
         patch("app.graph.wizard_helpers.classify_resume_intent", new=AsyncMock(return_value=intent)), \
         patch("app.graph.builder.interject_tools.run_handoff_turn", new=run):
        result = asyncio.run(wh.wizard_interrupt(MagicMock(), STEP, "ctx", state=_state()))
    return result, run, interrupt_mock


def test_handoff_abort_raises_wizard_exit_without_narrating(env):
    with patch("app.graph.wizard_helpers.interrupt", side_effect=["stop the build"]), \
         patch("app.graph.wizard_helpers.classify_resume_intent", new=AsyncMock(return_value=_handoff(0.9))), \
         patch("app.graph.builder.interject_tools.run_handoff_turn",
               new=AsyncMock(return_value=HandoffResult(None, abort=True))):
        with pytest.raises(wh.WizardExitRequested):
            asyncio.run(wh.wizard_interrupt(MagicMock(), STEP, "ctx", state=_state()))
    env.assert_not_awaited()  # the catching wizard decides what to say about the exit


def test_handoff_below_confidence_floor_never_runs_a_tool(env):
    # A handoff can undo or abort, so a low-confidence guess must re-ask instead.
    result, run, _ = _run(["undo maybe?", "yes"], _handoff(0.5), HandoffResult("should not run", False))
    run.assert_not_awaited()
    assert result == "yes"


def test_handoff_answer_is_narrated_and_the_same_widget_is_reshown(env):
    result, run, interrupt_mock = _run(
        ["what's a POI?", "yes"], _handoff(0.9), HandoffResult("A POI is a place worth targeting.", False),
    )
    run.assert_awaited_once()
    assert interrupt_mock.call_count == 2  # answered in place, then the widget again
    utterance = env.await_args.args[0]
    assert utterance.role == "sidebar_answer"
    assert utterance.facts["answer"] == "A POI is a place worth targeting."
    assert utterance.fallback == "A POI is a place worth targeting."  # tool-grounded text ships if composition mangles it
    assert result == "yes"


def test_handoff_with_nothing_to_say_stays_quiet_but_still_reshows(env):
    result, _, interrupt_mock = _run(["hmm", "yes"], _handoff(0.9), HandoffResult(None, False))
    env.assert_not_awaited()
    assert interrupt_mock.call_count == 2
    assert result == "yes"
