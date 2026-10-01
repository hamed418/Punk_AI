"""
wizard_interrupt's `_is_resume` used to read state["pending_action"]["step_key"]
— a field the builder path NEVER persists with a live value (every builder_ask/
media.py return either omits it or writes None). So `_is_resume` was permanently
False, `skip_emit` never gated the pre-interrupt narration on replay, and the
stale-beat discard (`_narrator_drain` in the `else` branch) was dead code: a
beat re-added while LangGraph replayed an already-resolved gate survived into
the buffer and got composed into the NEXT gate's message instead.

Real incident (pulled from the DB, thread b8417752-197a-4825-805e-04480178a3b4):
after the user confirmed the POI list (`geo_pois_confirmation`), the NEXT turn's
widget was the radius stepper (`maid_collect_poi_radius`) but its composed text
was a restatement of the POI-confirmation reveal ("confirm they're the right
ones") — the previous gate's beat had leaked forward.

This drives the REAL `wizard_interrupt` through a genuine two-node LangGraph
resume (matching the real architecture: each gate is its own node visit, not
sequential interrupt() calls inside one function — that distinction matters
because the fix reads LangGraph's `__pregel_resuming` task flag, which is
scoped per task, not per `Command(resume=...)` call: a fresh sibling node
running in the SAME resume call must not be misread as replaying). The
narrator's own compose/LLM path is stubbed out (a fast drain-and-join) so the
test never touches a real model; `beats.py`'s buffer, `_is_resume`, and the
discard branch are exercised for real.
"""
from __future__ import annotations

from typing import Any, TypedDict

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.graph import wizard_helpers as wh
from app.graph.narrator import beats as _beats
from app.graph.wizard_helpers import is_resuming_step, wizard_interrupt

# Real, already-registered STEP_PROMPTS keys — the exact two gates from the
# reported incident (geo_pois_confirmation -> maid_collect_poi_radius).
GATE_A = "geo_pois_confirmation"
GATE_B = "maid_collect_poi_radius"


class _S(TypedDict):
    log: list


def setup_function():
    _beats.clear()


async def _fake_flush_narration(state, writer):
    """Stand-in for composer.flush_narration: drains the REAL beat buffer and
    joins fallbacks, with no LLM call. What we're testing is whether a stale
    beat is still IN the buffer at this point, not what a model does with it.
    """
    drained = _beats.drain(state)
    text = " | ".join(b.fallback for b in drained if b.fallback)
    if text:
        writer({"type": "assistant_message", "content": text})
    return text, {}


def _build(monkeypatch, events: list):
    monkeypatch.setattr(wh, "flush_narration", _fake_flush_narration)

    def _writer(ev):
        events.append(ev)

    is_resume_seen: dict[str, list[bool]] = {"a": [], "b": []}
    orig_is_resuming_step = is_resuming_step

    async def node_a(state: Any):
        is_resume_seen["a"].append(orig_is_resuming_step(state, GATE_A))
        _beats.add_beat(
            state, "reveal", {"stage": "poi_confirm"},
            fallback="GATE_A_REVEAL: found the spots, confirm them",
        )
        result = await wizard_interrupt(_writer, GATE_A, "ctx", state=state, skip_ask=True)
        return {"log": [("a", str(result))]}

    async def node_b(state: Any):
        is_resume_seen["b"].append(orig_is_resuming_step(state, GATE_B))
        _beats.add_beat(
            state, "framing", {"stage": "poi_radius"},
            fallback="GATE_B_FRAMING: how close should the ring be",
        )
        result = await wizard_interrupt(_writer, GATE_B, "ctx", state=state, skip_ask=True)
        return {"log": [("b", str(result))]}

    app = (
        StateGraph(_S)
        .add_node("node_a", node_a)
        .add_node("node_b", node_b)
        .add_edge(START, "node_a")
        .add_edge("node_a", "node_b")
        .add_edge("node_b", END)
        .compile(checkpointer=MemorySaver())
    )
    return app, is_resume_seen


async def _drain_stream(app, inp, config):
    async for _ in app.astream(inp, config, stream_mode=["values"]):
        pass


@pytest.mark.asyncio
async def test_stale_beat_from_a_replayed_gate_does_not_leak_into_the_next_gate(monkeypatch):
    events: list = []
    app, is_resume_seen = _build(monkeypatch, events)
    cfg = {"configurable": {"thread_id": "leak-1"}}

    # Forward pass: pauses at gate_a, having composed+emitted its own reveal.
    await _drain_stream(app, {"log": []}, cfg)
    gate_a_messages = [e for e in events if e.get("type") == "assistant_message"]
    assert len(gate_a_messages) == 1
    assert "GATE_A_REVEAL" in gate_a_messages[0]["content"]

    events.clear()

    # Resume gate_a (a sentinel JSON value — bypasses the LLM resume-router
    # classifier entirely, same as a real "confirm" widget click). This
    # replays node_a from the top (re-adding its beat) before advancing to
    # node_b, which pauses fresh at gate_b.
    await _drain_stream(app, Command(resume='{"confirm":true}'), cfg)

    gate_b_messages = [e for e in events if e.get("type") == "assistant_message"]
    assert len(gate_b_messages) == 1, gate_b_messages
    # The bug: GATE_A_REVEAL riding along in gate_b's composed message.
    assert "GATE_A_REVEAL" not in gate_b_messages[0]["content"]
    assert "GATE_B_FRAMING" in gate_b_messages[0]["content"]

    # And the structural resume signal itself: node_a's OWN interrupt was
    # being replayed; node_b's was a genuinely fresh first ask.
    assert is_resume_seen["a"] == [False, True]
    assert is_resume_seen["b"] == [False]


@pytest.mark.asyncio
async def test_gate_a_beat_buffer_is_empty_after_its_own_replay(monkeypatch):
    """Direct check on the mechanism, not just the end-to-end text: once
    gate_a's replay resolves, nothing of its should remain buffered for
    whatever composes next."""
    events: list = []
    app, _ = _build(monkeypatch, events)
    cfg = {"configurable": {"thread_id": "leak-2"}}

    await _drain_stream(app, {"log": []}, cfg)
    events.clear()
    await _drain_stream(app, Command(resume='{"confirm":true}'), cfg)

    # node_a's replay must produce NO assistant_message of its own (skip_emit);
    # the only message from this resume call is node_b's fresh, clean framing.
    msgs = [e for e in events if e.get("type") == "assistant_message"]
    assert len(msgs) == 1, msgs
    assert "GATE_A_REVEAL" not in msgs[0]["content"]
    assert "GATE_B_FRAMING" in msgs[0]["content"]
