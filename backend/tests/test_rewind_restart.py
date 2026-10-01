"""Rewinding a builder step must RESUME FROM THAT POINT, on the real graph shape.

campaign_builder loops ``plan -> ask(interrupt) -> plan -> ask …`` inside a compiled
subgraph under a parent ``entry`` node. On that shape, forking the inner checkpoint a
step was stamped with and replaying does NOT re-ask the step: the first interrupt
swallows the last resume value the thread was ever given and the run walks past it
(the prod trace: ``Resumed geo_pois_confirmation iter=0: '{"confirm":true…}'``).

``rewind_restore.restore_from_anchor`` writes the anchor's state onto the thread head
as the ``entry`` node instead, so the builder starts fresh and re-arms exactly the
targeted step. Both halves are pinned here so a langgraph bump that changes either one
fails loudly, not in production.
"""

from __future__ import annotations

import operator
import re
from importlib.metadata import version as _installed
from pathlib import Path
from typing import Annotated, TypedDict

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt

from app.graph.state import _dict_merge_or_clear
from app.modules.chat.rewind_restore import (
    GROUP_REFUSAL,
    plan_rewind,
    reducer_fields,
    restore_from_anchor,
    restore_updates,
    with_question_text,
)


def _pinned() -> str:
    reqs = Path(__file__).resolve().parents[1] / "requirements.txt"
    m = re.search(r"^langgraph==([^\s#]+)", reqs.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else ""


on_pinned_langgraph = pytest.mark.skipif(
    _installed("langgraph") != _pinned(),
    reason="rewind semantics are verified only on the pinned langgraph — re-verify before bumping",
)

STEPS = ["S0", "S1", "S2", "S3", "S4", "S5"]


class S(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    answers: list
    cursor: int
    spent: Annotated[int, operator.add]                 # billing-style counter
    user_info: Annotated[dict, _dict_merge_or_clear]
    next_nodes: list
    pending_usage: dict


TOY = dict(schema=S, forced={})


def _build():
    def entry(state: S):
        return {}

    def plan(state: S):
        return {}

    def ask(state: S):
        cur = state.get("cursor", 0)
        v = interrupt({"step_key": STEPS[cur]})
        return {
            "answers": [*(state.get("answers") or []), v],
            "cursor": cur + 1,
            "spent": 10,
            "user_info": {f"k{cur}": v},
        }

    def route(state: S):
        return "ask" if state.get("cursor", 0) < len(STEPS) else END

    inner = (
        StateGraph(S)
        .add_node("plan", plan)
        .add_node("ask", ask)
        .add_edge(START, "plan")
        .add_conditional_edges("plan", route, {"ask": "ask", END: END})
        .add_edge("ask", "plan")
        .compile()
    )
    return (
        StateGraph(S)
        .add_node("entry", entry)
        .add_node("campaign_builder", inner)
        .add_edge(START, "entry")
        .add_edge("entry", "campaign_builder")
        .add_edge("campaign_builder", END)
        .compile(checkpointer=MemorySaver())
    )


async def _drain(app, cfg, inp):
    async for _ in app.astream(inp, cfg, stream_mode=["values"], subgraphs=True):
        pass


async def _paused(app, cfg):
    snap = await app.aget_state(cfg, subgraphs=True)
    out: list[str] = []

    def walk(n):
        for t in n.tasks or ():
            for i in t.interrupts or ():
                out.append(i.value["step_key"])
            if t.state is not None and not isinstance(t.state, dict):
                walk(t.state)

    walk(snap)
    return out


async def _innermost(app, cfg):
    snap = await app.aget_state(cfg, subgraphs=True)
    inner = snap

    def desc(n):
        nonlocal inner
        for t in n.tasks or ():
            s = getattr(t, "state", None)
            if s is not None and not isinstance(s, dict):
                inner = s
                desc(s)

    desc(snap)
    return inner


async def _session(tid: str, answered: int):
    """Answer ``answered`` steps; return the app, config and, per step, the innermost
    snapshot recorded while the thread was paused AT that step (what the assistant row
    gets stamped with)."""
    app = _build()
    cfg = {"configurable": {"thread_id": tid}}
    anchors = {}
    await _drain(app, cfg, {"answers": [], "cursor": 0})
    anchors[0] = await _innermost(app, cfg)
    for i in range(answered):
        await _drain(app, cfg, Command(resume=f"a{i}"))
        anchors[i + 1] = await _innermost(app, cfg)
    return app, cfg, anchors


@on_pinned_langgraph
@pytest.mark.asyncio
@pytest.mark.parametrize("answered,target", [(2, 0), (2, 1), (4, 1), (4, 3)])
async def test_forking_the_inner_checkpoint_does_not_re_ask_the_step(answered, target):
    """The trap the old rewind fell into. Kept so nobody 'simplifies' back to it."""
    app, cfg, anchors = await _session(f"fork-{answered}-{target}", answered)
    c = anchors[target].config["configurable"]
    forked = await app.aupdate_state({"configurable": {
        "thread_id": cfg["configurable"]["thread_id"],
        "checkpoint_id": c["checkpoint_id"], "checkpoint_ns": c["checkpoint_ns"]}}, None)
    await _drain(app, forked, None)

    # Walked past the step instead of re-asking it: the replay's first interrupt
    # consumed a recorded resume value.
    assert f"S{target}" not in await _paused(app, cfg)


@on_pinned_langgraph
@pytest.mark.asyncio
@pytest.mark.parametrize("answered,target", [(2, 0), (2, 1), (4, 1), (4, 3), (5, 4)])
async def test_restore_re_arms_exactly_the_targeted_step_and_the_edit_lands(answered, target):
    app, cfg, anchors = await _session(f"restore-{answered}-{target}", answered)

    await restore_from_anchor(app, cfg, anchors[target].values, **TOY)
    await _drain(app, cfg, None)
    assert await _paused(app, cfg) == [f"S{target}"] * 2       # re-armed, nothing consumed

    await _drain(app, cfg, Command(resume="EDITED"))
    assert await _paused(app, cfg) == [f"S{target + 1}"] * 2   # advanced from the edit
    inner = await _innermost(app, cfg)
    assert inner.values["answers"] == [f"a{i}" for i in range(target)] + ["EDITED"]
    assert inner.values["user_info"] == {
        **{f"k{i}": f"a{i}" for i in range(target)}, f"k{target}": "EDITED",
    }


@on_pinned_langgraph
@pytest.mark.asyncio
async def test_restore_drops_state_learned_after_the_anchor_across_runs():
    """A thread whose builder already ran to END has later keys on the head; restoring
    an earlier step must not leak them (a shallow merge can't delete a key)."""
    app, cfg, anchors = await _session("cross-run", len(STEPS))
    head = await app.aget_state(cfg)
    assert set(head.values["user_info"]) == {f"k{i}" for i in range(len(STEPS))}

    await restore_from_anchor(app, cfg, anchors[2].values, **TOY)
    await _drain(app, cfg, None)
    assert await _paused(app, cfg) == ["S2"] * 2
    inner = await _innermost(app, cfg)
    assert inner.values["user_info"] == {"k0": "a0", "k1": "a1"}
    assert inner.values["answers"] == ["a0", "a1"]


@on_pinned_langgraph
@pytest.mark.asyncio
async def test_restore_does_not_rewind_accounting_counters():
    """Tokens already spent stay on the books: the counter is not restored."""
    app, cfg, anchors = await _session("counters", 3)
    before = (await app.aget_state(cfg)).values.get("spent", 0)
    await restore_from_anchor(app, cfg, anchors[1].values, **TOY)
    after = (await app.aget_state(cfg)).values.get("spent", 0)
    assert after == before                                   # not reset to the anchor's value


# ── pure restore_updates on the real AgentState ────────────────────────────────


def test_reducer_fields_are_derived_from_the_real_schema():
    fields = reducer_fields()
    assert {"messages", "user_info", "geo_data", "thinking", "token_cost_usd", "total_tokens",
            "google_api_calls", "tool_calls_log", "wizard_milestone_cache", "narrator_history",
            "wizards_completed"} <= fields
    assert "campaign_builder_state" not in fields and "pending_action" not in fields


def test_restore_updates_shape():
    anchor = {
        "campaign_builder_state": {"filled": {"a": 1}},
        "pending_action": {"step_key": "geo_pois_confirmation"},
        "user_info": {"business_name": "x"},
        "geo_data": None,
        "total_tokens": 999,              # reducer counter — must NOT be restored
        "token_cost_usd": 9.9,
        "not_a_state_key": 1,             # foreign key — dropped
        "messages": [HumanMessage(content="hi", id="m1")],
    }
    head = {
        "messages": [HumanMessage(content="hi", id="m1"), AIMessage(content="later", id="m2")],
        "user_info": {"business_name": "x", "learned_later": 1},
        "geo_data": {"pois": 3},
    }
    clear, restore = restore_updates(anchor, head)

    assert clear == {"user_info": None, "geo_data": None}      # both hold keys the anchor lacks
    assert restore["campaign_builder_state"] == {"filled": {"a": 1}}
    assert restore["pending_action"] == {"step_key": "geo_pois_confirmation"}
    assert restore["user_info"] == {"business_name": "x"}
    assert "geo_data" not in restore                          # anchor had none → stays cleared
    assert restore["next_nodes"] == ["campaign_builder"] and restore["pending_usage"] is None
    for key in ("total_tokens", "token_cost_usd", "not_a_state_key"):
        assert key not in restore
    # head-only message removed, shared message left alone
    assert [type(m).__name__ for m in restore["messages"]] == ["RemoveMessage"]
    assert restore["messages"][0].id == "m2"


def test_restore_updates_re_adds_messages_the_head_lacks():
    anchor = {"messages": [HumanMessage(content="a", id="m1"), HumanMessage(content="b", id="m2")]}
    head = {"messages": [HumanMessage(content="a", id="m1")]}
    (restore,) = restore_updates(anchor, head)
    assert [m.id for m in restore["messages"]] == ["m2"]


def test_no_clear_write_when_nothing_would_leak():
    """The common case is ONE atomic write, not clear + restore."""
    anchor = {"user_info": {"a": 1, "b": 2}, "geo_data": None}
    head = {"user_info": {"a": 0}, "geo_data": None}
    updates = restore_updates(anchor, head)
    assert len(updates) == 1 and updates[0]["user_info"] == {"a": 1, "b": 2}


# ── plan_rewind ───────────────────────────────────────────────────────────────


def test_builder_step_restarts_and_parent_pause_forks():
    assert plan_rewind(anchor_ns="campaign_builder:x", anchor_id="r1", group_ids=["r1"]).mode == "restart"
    assert plan_rewind(anchor_ns="", anchor_id="r1", group_ids=["r1"]).mode == "fork"
    assert plan_rewind(anchor_ns="campaign_builder:x", anchor_id="r1", group_ids=["r1"],
                       restart_enabled=False).mode == "fork"


def test_grouped_stamp_allows_only_the_row_the_mode_re_arms():
    # restart re-arms the FIRST interrupt of the node …
    assert plan_rewind(anchor_ns="b:x", anchor_id="q1", group_ids=["q1", "q2"]).refusal is None
    assert plan_rewind(anchor_ns="b:x", anchor_id="q2", group_ids=["q1", "q2"]).refusal == GROUP_REFUSAL
    # … a fork the SECOND (the rule the old code shipped).
    assert plan_rewind(anchor_ns="", anchor_id="q2", group_ids=["q1", "q2"]).refusal is None
    assert plan_rewind(anchor_ns="", anchor_id="q1", group_ids=["q1", "q2"]).refusal == GROUP_REFUSAL


# ── the re-asked question keeps its words ─────────────────────────────────────


def test_reask_without_narration_gets_the_stored_question_text_before_the_widget():
    replay = [
        {"type": "thinking", "content": "Builder plan #2"},
        {"type": "map_data", "content": {}},
        {"type": "input_mode", "mode": "widget"},
        {"type": "pending_action", "content": {"step_key": "geo_pois_confirmation"}},
        {"type": "done"},
    ]
    out = with_question_text(replay, "Here are your spots — confirm?")
    types = [e["type"] for e in out]
    assert types == ["thinking", "map_data", "assistant_message", "input_mode", "pending_action", "done"]
    assert out[2]["content"] == "Here are your spots — confirm?"


def test_reask_that_narrates_itself_is_left_alone():
    replay = [{"type": "assistant_message", "content": "fresh"}, {"type": "pending_action", "content": {}}]
    assert with_question_text(replay, "old text") == replay


def test_no_stored_text_and_errors_are_handled():
    replay = [{"type": "error", "content": "boom"}, {"type": "pending_action", "content": {}}]
    assert with_question_text(replay, "") == [{"type": "pending_action", "content": {}}]
    assert [e["type"] for e in with_question_text([{"type": "done"}], "q")] == ["done", "assistant_message"]
