"""A bare ``aupdate_state`` (no ``as_node``) while a nested subgraph interrupt
is pending resets that subgraph's task to a NEW checkpoint_ns and drops its
pending interrupt — LangGraph treats the write as if the task had completed.
For ``campaign_builder`` (a compiled subgraph, exactly like ``builder`` below)
that meant every resume silently restarted the builder from START: the user's
reply landed on whichever interrupt the replay reached FIRST
(``geo_location_confirmation``) instead of the one actually on screen
(``geo_pois_confirmation``).

One call site still does this: ``ChatService._bill_usage`` (writing the
``pending_usage`` carry), which checks for a pending interrupt first and skips
the graph write entirely when one is active.

``map.service._count_api_call`` used to be the second call site — it wrote
``google_api_calls`` onto AgentState via ``aupdate_state``, and had to skip
counting entirely while a subgraph interrupt was pending (exactly when the
editable confirm-location widget maps this counts fire), silently
undercounting them. It now writes a plain ``usage_events`` row instead and
never touches the graph at all, so the interrupt hazard doesn't apply and
nothing is skipped.

This module pins the underlying LangGraph semantics (so nobody "fixes" the
guard away without noticing what breaks) and regression-tests that widget
counting no longer goes near the graph.
"""

from __future__ import annotations

from typing import TypedDict
from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

import app.db.model_registry  # noqa: F401 — see test_usage_events.py
from app.db.models import UsageEvent


class _Inner(TypedDict):
    filled: dict


def _inner_ask(state: _Inner):
    filled = dict(state.get("filled") or {})
    if "a" not in filled:
        filled["a"] = interrupt({"step_key": "step_A"})
        return {"filled": filled}
    filled["b"] = interrupt({"step_key": "step_B"})
    return {"filled": filled}


def _inner_route(state: _Inner):
    return END if "b" in (state.get("filled") or {}) else "ask"


def _build_outer():
    """Mirrors the real shape: a subgraph node ("builder" / campaign_builder)
    nested inside a parent graph, both checkpointed."""
    inner = (
        StateGraph(_Inner)
        .add_node("ask", _inner_ask)
        .add_edge(START, "ask")
        .add_conditional_edges("ask", _inner_route, ["ask", END])
        .compile()
    )
    return (
        StateGraph(_Inner)
        .add_node("builder", inner)
        .add_edge(START, "builder")
        .add_edge("builder", END)
        .compile(checkpointer=MemorySaver())
    )


async def _drain(app, cfg, inp) -> None:
    async for _ in app.astream(inp, cfg, stream_mode=["values"], subgraphs=True):
        pass


def _builder_ns(snap) -> list[str]:
    out = []
    for t in (snap.tasks or ()):
        st = getattr(t, "state", None)
        if st is not None and not isinstance(st, dict):
            out.append(st.config["configurable"].get("checkpoint_ns"))
    return out


def _pending_steps(snap) -> list[str]:
    out = []

    def walk(s):
        for t in (s.tasks or ()):
            for i in (t.interrupts or ()):
                out.append(i.value.get("step_key"))
            st = getattr(t, "state", None)
            if st is not None and not isinstance(st, dict):
                walk(st)

    walk(snap)
    return out


@pytest.mark.asyncio
async def test_bare_aupdate_state_resets_pending_subgraph_interrupt():
    """The trap. Kept as a test so a future 'just write the state, it's
    harmless' change doesn't reintroduce the builder-restart bug silently."""
    app = _build_outer()
    cfg = {"configurable": {"thread_id": "trap"}}

    await _drain(app, cfg, {"filled": {}})
    await _drain(app, cfg, Command(resume="ANSWER_A"))
    snap = await app.aget_state(cfg, subgraphs=True)
    assert set(_pending_steps(snap)) == {"step_B"}
    ns_before = _builder_ns(snap)

    # The bug: a bare aupdate_state while step_B is still pending.
    await app.aupdate_state(cfg, {"filled": {"noise": 1}})

    snap_after = await app.aget_state(cfg, subgraphs=True)
    assert _pending_steps(snap_after) == []          # the interrupt vanished
    assert _builder_ns(snap_after) != ns_before       # new task, not a resume


@pytest.mark.asyncio
async def test_skipping_the_write_preserves_the_pending_interrupt():
    """The fix, same shape: check-then-skip leaves the paused task intact."""
    app = _build_outer()
    cfg = {"configurable": {"thread_id": "safe"}}

    await _drain(app, cfg, {"filled": {}})
    await _drain(app, cfg, Command(resume="ANSWER_A"))
    snap = await app.aget_state(cfg, subgraphs=True)
    assert set(_pending_steps(snap)) == {"step_B"}
    ns_before = _builder_ns(snap)

    # The guard every fixed call site now applies: read-only when interrupted.
    if _pending_steps(snap):
        pass  # no aupdate_state call
    else:
        await app.aupdate_state(cfg, {"filled": {"noise": 1}})

    snap_after = await app.aget_state(cfg, subgraphs=True)
    assert set(_pending_steps(snap_after)) == {"step_B"}
    assert _builder_ns(snap_after) == ns_before

    # And the paused step still resolves normally afterward.
    await _drain(app, cfg, Command(resume="ANSWER_B"))
    final = await app.aget_state(cfg, subgraphs=True)
    assert final.values.get("filled") == {"a": "ANSWER_A", "b": "ANSWER_B"}


def _fake_db():
    """AsyncSessionLocal stand-in: captures db.add(), no real database."""
    added: list = []

    class _DB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        def add(self, obj):
            added.append(obj)

        async def commit(self):
            pass

    return (lambda: _DB()), added


@pytest.mark.asyncio
async def test_count_api_call_never_touches_the_graph_even_while_interrupted(monkeypatch):
    """Regression test for the fix in app.modules.map.service: widget
    counting no longer reads or writes AgentState at all, so it can no longer
    be the thing that resets a pending subgraph interrupt — and it no longer
    needs to skip counting to avoid that, unlike the old aupdate_state path."""
    from app.modules.map.service import _count_api_call

    app = _build_outer()
    cfg = {"configurable": {"thread_id": "map-widget"}}
    await _drain(app, cfg, {"filled": {}})  # paused at step_A

    spy = AsyncMock(wraps=app.aupdate_state)
    monkeypatch.setattr(app, "aupdate_state", spy)
    get_spy = AsyncMock(wraps=app.aget_state)
    monkeypatch.setattr(app, "aget_state", get_spy)

    session, added = _fake_db()
    monkeypatch.setattr("app.db.database.AsyncSessionLocal", session)

    await _count_api_call("map-widget", "places_search_text")

    spy.assert_not_called()
    get_spy.assert_not_called()
    assert len(added) == 1
    row = added[0]
    assert isinstance(row, UsageEvent)
    assert row.thread_id == "map-widget"
    assert row.user_id is None
    assert row.api == "places_search_text"
