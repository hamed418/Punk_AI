"""
The REAL builder subgraph (builder_plan → builder_ask → builder_plan …) driven
through genuine LangGraph interrupt/resume with an in-memory checkpointer, with
BUILDER_SINGLE_INTERRUPT on. No DB, no network: the LLMs are stubbed.

This is the gate for turning the flag on: it proves that a reply which isn't an
answer is applied AND the step is re-asked, across real node boundaries and
real checkpointed resumes, with the planner LLM skipped on the re-ask tick.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.graph import wizard_helpers as wh
from app.graph.builder import builder_node as bn
from app.graph.resume_router import ResumeIntent
from app.graph.state import AgentState


def _graph():
    g = StateGraph(AgentState)
    g.add_node("builder_plan", bn.builder_plan)
    g.add_node("builder_ask", bn.builder_ask)
    g.add_node("builder_act", bn.builder_act)
    g.add_node("builder_finalize", bn.builder_finalize)
    g.add_edge(START, "builder_plan")
    g.add_conditional_edges("builder_plan", bn._route_after_plan, {
        "builder_ask": "builder_ask", "builder_act": "builder_act",
        "builder_finalize": "builder_finalize", "chatbot_exit": END,
    })
    g.add_conditional_edges("builder_ask", bn._route_after_step, {"builder_plan": "builder_plan", "chatbot_exit": END})
    g.add_conditional_edges("builder_act", bn._route_after_step, {"builder_plan": "builder_plan", "chatbot_exit": END})
    g.add_edge("builder_finalize", END)
    return g.compile(checkpointer=MemorySaver())


async def _run(app, inp, cfg):
    out = None
    async for chunk in app.astream(inp, cfg, stream_mode="values"):
        out = chunk
    return out


async def _pending(app, cfg):
    snap = await app.aget_state(cfg)
    for task in snap.tasks:
        for intr in task.interrupts:
            return intr.value
    return None


@pytest.fixture()
def env():
    planner = AsyncMock(side_effect=RuntimeError("planner LLM unavailable"))   # → deterministic fallback
    with patch.object(bn, "get_writer", return_value=lambda _e: None), \
         patch.object(bn, "tracked_ainvoke", new=planner), \
         patch.object(wh, "wizard_ask", new=AsyncMock(return_value=None)), \
         patch.object(wh, "flush_narration", new=AsyncMock(return_value=("", {}))), \
         patch.object(wh.settings, "BUILDER_SINGLE_INTERRUPT", True), \
         patch.object(bn.settings, "BUILDER_SINGLE_INTERRUPT", True):
        yield planner


def _start(tid: str) -> tuple[dict, dict]:
    state = {
        "messages": [HumanMessage(content="build me a campaign", id=f"e2e-{tid}")],
        "user_info": {"business_description": "coffee roaster", "target_audience": "commuters"},
        "campaign_builder_state": {},
    }
    return state, {"configurable": {"thread_id": tid}}


@pytest.mark.asyncio
async def test_a_non_answer_is_applied_then_the_same_step_is_asked_again(env):
    app = _graph()
    state, cfg = _start("e2e-1")

    await _run(app, state, cfg)
    first = await _pending(app, cfg)
    assert first and first["step_key"] == "geo_collect_location_type"
    planner_calls_before = env.await_count

    edit = ResumeIntent(lane="edit", target_field="budget", new_value="$500", confidence=0.95)
    classify = AsyncMock(return_value=edit)
    with patch.object(wh, "classify_resume_intent_tools", new=classify), \
         patch.object(wh, "classify_resume_intent", new=classify), \
         patch.object(wh, "narrate", new=AsyncMock()):
        out = await _run(app, Command(resume="set my budget to $500"), cfg)

    # 1. the SAME step is on screen again (a fresh task, one interrupt)
    again = await _pending(app, cfg)
    assert again and again["step_key"] == "geo_collect_location_type"
    # 2. the edit was applied by builder_plan in the same request
    assert out["user_info"]["budget"] == "$500"
    bs = out["campaign_builder_state"]
    # 3. nothing typed was written into the slot as its "answer"
    assert not bs["filled"].get("location_scope")
    assert bs["_single_interrupt"] is True and "_pending_edits" not in bs
    # 4. the reply was classified exactly once
    assert classify.await_count == 1
    # 5. the re-ask tick skipped the planner LLM
    assert env.await_count == planner_calls_before


@pytest.mark.asyncio
async def test_the_step_can_still_be_answered_after_a_non_answer(env):
    app = _graph()
    state, cfg = _start("e2e-2")
    await _run(app, state, cfg)

    q = ResumeIntent(lane="query", question_text="what's a pin?", confidence=0.9)
    with patch.object(wh, "classify_resume_intent_tools", new=AsyncMock(return_value=q)), \
         patch.object(wh, "classify_resume_intent", new=AsyncMock(return_value=q)), \
         patch.object(wh, "narrate", new=AsyncMock()):
        await _run(app, Command(resume="what's a pin?"), cfg)
    assert (await _pending(app, cfg))["step_key"] == "geo_collect_location_type"

    out = await _run(app, Command(resume="target a specific city"), cfg)
    bs = out["campaign_builder_state"]
    assert bs["filled"]["location_scope"] == "granular_local"
    nxt = await _pending(app, cfg)
    assert nxt and nxt["step_key"] != "geo_collect_location_type"       # moved on
    assert "location_scope" not in (bs.get("_ask_attempts") or {})        # counters cleared on answer


@pytest.mark.asyncio
async def test_repeated_rejects_reach_the_exit_instead_of_looping_forever(env):
    app = _graph()
    state, cfg = _start("e2e-3")
    await _run(app, state, cfg)

    reject = ResumeIntent(lane="reject", confidence=0.9)
    with patch.object(wh, "classify_resume_intent_tools", new=AsyncMock(return_value=reject)), \
         patch.object(wh, "classify_resume_intent", new=AsyncMock(return_value=reject)), \
         patch.object(wh, "narrate", new=AsyncMock()):
        out = None
        for i in range(wh._MAX_NONANSWER_LOOPS + 2):
            out = await _run(app, Command(resume=f"hmm nope {i}"), cfg)
            if not await _pending(app, cfg):
                break
    assert not await _pending(app, cfg), "the off-path budget never ended the loop"
    assert out["wizard_failure"] == "user_exit"
    # scratch kept: the user can say "continue" and pick up where they were
    assert out["campaign_builder_state"]["_ask_attempts"].get("geo_collect_location_type") is None
