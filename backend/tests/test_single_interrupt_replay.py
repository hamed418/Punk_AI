"""
Replay determinism under the one-interrupt-per-task contract, through a REAL
LangGraph resume (MemorySaver).

Legacy mode loops in place: an edit reply is classified, the SAME task then
re-interrupts, and when the user finally answers, LangGraph replays the task
from the top — so the edit reply is classified AGAIN (a second LLM call that
can decide differently, on a different worker). In single-interrupt mode each
reply ends its own task, so it is classified exactly once, ever.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.graph import wizard_helpers as wh
from app.graph.resume_router import ResumeIntent

STEP = "geo_wizard_plan_review"


class _S(TypedDict):
    messages: list
    campaign_builder_state: dict
    log: Annotated[list, operator.add]


def _build():
    async def ask(state: Any):
        bs = dict(state["campaign_builder_state"])
        view = {**state, "campaign_builder_state": bs}
        result = await wh.wizard_interrupt(MagicMock(), STEP, "ctx", state=view, skip_ask=True)
        return {
            "campaign_builder_state": {**bs, "last_answered": result.answered},
            "log": [(str(result), result.answered, dict(result.edits))],
        }

    def route(state: Any):
        # Stand-in for builder_plan re-dispatching an unanswered step.
        return END if state["campaign_builder_state"].get("last_answered") else "ask"

    return (
        StateGraph(_S)
        .add_node("ask", ask)
        .add_edge(START, "ask")
        .add_conditional_edges("ask", route, ["ask", END])
        .compile(checkpointer=MemorySaver())
    )


async def _run(single: bool, thread: str) -> tuple[list, int]:
    edit = ResumeIntent(lane="edit", target_field="business_name", new_value="Gym Co", confidence=0.95)
    classify = AsyncMock(return_value=edit)
    app = _build()
    cfg = {"configurable": {"thread_id": thread}}
    start = {
        "messages": [HumanMessage(content="hi", id=f"replay-{thread}")],
        "campaign_builder_state": {"filled": {}, "_single_interrupt": single},
        "log": [],
    }
    with patch.object(wh, "classify_resume_intent", new=classify), \
         patch.object(wh, "narrate", new=AsyncMock(return_value=None)), \
         patch.object(wh, "flush_narration", new=AsyncMock(return_value=("", {}))), \
         patch.object(wh.settings, "RESUME_ROUTER_TOOLCALLING", False):
        async for _ in app.astream(start, cfg):
            pass
        async for _ in app.astream(Command(resume="rename it Gym Co"), cfg):
            pass
        async for _ in app.astream(Command(resume='{"confirm":true}'), cfg):
            pass
        final = await app.aget_state(cfg)
    return final.values["log"], classify.await_count


@pytest.mark.asyncio
async def test_single_interrupt_classifies_each_reply_exactly_once():
    log, n_classified = await _run(single=True, thread="single")
    assert n_classified == 1
    # Checkpoint serialization turns the logged tuples into lists.
    assert [tuple(entry) for entry in log] == [
        ("rename it Gym Co", False, {"business_name": "Gym Co"}),
        ('{"confirm":true}', True, {}),
    ]


@pytest.mark.asyncio
async def test_legacy_loop_reclassifies_on_replay():
    """Pins the defect the contract removes (legacy threads keep it)."""
    _log, n_classified = await _run(single=False, thread="legacy")
    assert n_classified == 2
