"""Undo has to FORK the checkpoint, not replay it.

The obvious implementation — stream from the checkpoint the previous assistant
message was stamped with — does not re-ask the question. The resume value the
user already gave is recorded in that checkpoint's pending writes, so on replay
``interrupt()`` RETURNS that value instead of pausing, and the graph runs forward
past the very step the user was trying to redo.

``aupdate_state`` writes a new checkpoint descending from the anchor. The pending
writes belong to the anchor's id, so the fork starts clean and the node
interrupts again.

This pins the LangGraph semantics the undo endpoint depends on. If a future
version changes them, this fails here rather than silently skipping a wizard step
in production.
"""

from __future__ import annotations

import re
from importlib.metadata import version as _installed
from pathlib import Path
from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


def _pinned_langgraph() -> str:
    reqs = Path(__file__).resolve().parents[1] / "requirements.txt"
    m = re.search(r"^langgraph==([^\s#]+)", reqs.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else ""


# Two tests below pin checkpoint-replay semantics of the langgraph release that
# ships (requirements.txt). They pass on it and fail on 1.2.x, where replaying an
# anchor re-asks and forking an inner checkpoint lands on the subgraph's first
# step. A dev venv drifting ahead of the pin must not read as a regression in the
# undo endpoint — but bumping the pin has to re-verify undo first, so the skip
# says exactly that.
_on_pinned_langgraph = pytest.mark.skipif(
    _installed("langgraph") != _pinned_langgraph(),
    reason=(
        f"langgraph {_installed('langgraph')} installed, requirements.txt pins "
        f"{_pinned_langgraph() or '?'} — undo/rewind semantics are verified only on "
        "the pinned release; re-verify them before bumping it"
    ),
)


class _S(TypedDict):
    answers: list


def _build():
    def ask(state: _S):
        a = interrupt({"step_key": "step_A"})
        b = interrupt({"step_key": "step_B"})
        return {"answers": [a, b]}

    return (
        StateGraph(_S)
        .add_node("ask", ask)
        .add_edge(START, "ask")
        .add_edge("ask", END)
        .compile(checkpointer=MemorySaver())
    )


async def _paused_at(app, config) -> list[str]:
    snap = await app.aget_state(config)
    return [
        i.value.get("step_key")
        for t in (snap.tasks or ())
        for i in (t.interrupts or ())
    ]


async def _drain(app, config, inp) -> None:
    async for _ in app.astream(inp, config, stream_mode=["values"], subgraphs=True):
        pass


@_on_pinned_langgraph
@pytest.mark.asyncio
async def test_replaying_the_anchor_checkpoint_does_not_re_ask():
    """The trap. Kept as a test so nobody 'simplifies' the fork back into this."""
    app = _build()
    cfg = {"configurable": {"thread_id": "replay"}}

    await _drain(app, cfg, {"answers": []})
    assert await _paused_at(app, cfg) == ["step_A"]

    anchor = (await app.aget_state(cfg)).config["configurable"]["checkpoint_id"]
    await _drain(app, cfg, Command(resume="ANSWER_A"))
    assert await _paused_at(app, cfg) == ["step_B"]

    await _drain(
        app,
        {"configurable": {"thread_id": "replay", "checkpoint_id": anchor, "checkpoint_ns": ""}},
        None,
    )
    # step_A is NOT re-asked: the recorded answer was consumed again and the run
    # carried on past it. (Exactly where it lands — paused at step_B or run to
    # completion — is incidental; never being asked step_A again is the bug.)
    assert "step_A" not in await _paused_at(app, cfg)


@pytest.mark.asyncio
async def test_forking_the_anchor_checkpoint_re_asks_the_step():
    """What undo_last actually does."""
    app = _build()
    cfg = {"configurable": {"thread_id": "fork"}}

    await _drain(app, cfg, {"answers": []})
    anchor = (await app.aget_state(cfg)).config["configurable"]["checkpoint_id"]

    await _drain(app, cfg, Command(resume="ANSWER_A"))
    assert await _paused_at(app, cfg) == ["step_B"]

    forked = await app.aupdate_state(
        {"configurable": {"thread_id": "fork", "checkpoint_id": anchor, "checkpoint_ns": ""}},
        None,
    )
    await _drain(app, forked, None)

    # Back on step_A, and the thread's own tip moved with it — a later resume
    # answers the re-asked question, not the one after it.
    assert await _paused_at(app, forked) == ["step_A"]
    assert await _paused_at(app, cfg) == ["step_A"]


@pytest.mark.asyncio
async def test_fork_config_requires_checkpoint_ns():
    """Omitting checkpoint_ns raises KeyError deep in the checkpointer."""
    app = _build()
    cfg = {"configurable": {"thread_id": "ns"}}
    await _drain(app, cfg, {"answers": []})
    anchor = (await app.aget_state(cfg)).config["configurable"]["checkpoint_id"]

    with pytest.raises(KeyError):
        await app.aupdate_state(
            {"configurable": {"thread_id": "ns", "checkpoint_id": anchor}}, None
        )

@pytest.mark.asyncio
async def test_fork_then_resume_is_an_edit():
    """The /rewind resubmit path: fork re-arms the step, then a new value answers it.

    This is what makes edit and retry the same operation as undo — the graph must
    end up past the step carrying the NEW value, with the old one gone.
    """
    app = _build()
    cfg = {"configurable": {"thread_id": "edit"}}

    await _drain(app, cfg, {"answers": []})
    anchor = (await app.aget_state(cfg))["config"]["configurable"]["checkpoint_id"]         if isinstance(await app.aget_state(cfg), dict)         else (await app.aget_state(cfg)).config["configurable"]["checkpoint_id"]

    await _drain(app, cfg, Command(resume="TYPO"))
    assert await _paused_at(app, cfg) == ["step_B"]

    forked = await app.aupdate_state(
        {"configurable": {"thread_id": "edit", "checkpoint_id": anchor, "checkpoint_ns": ""}},
        None,
    )
    await _drain(app, forked, None)
    assert await _paused_at(app, forked) == ["step_A"]   # re-armed

    await _drain(app, cfg, Command(resume="CORRECTED"))
    assert await _paused_at(app, cfg) == ["step_B"]      # advanced again

    await _drain(app, cfg, Command(resume="B_ANSWER"))
    answers = (await app.aget_state(cfg)).values["answers"]
    assert answers == ["CORRECTED", "B_ANSWER"], answers  # the typo never landed

# ── the subgraph trap ─────────────────────────────────────────────────────────
#
# campaign_builder is a compiled subgraph. While it is the pending parent task,
# every interrupt() inside it happens in ONE parent superstep, so the parent
# checkpoint_id is identical for every step and cannot identify one. Stamping
# only that id made every rewind fork to the subgraph's FIRST interrupt no matter
# which answer the user picked — and shipped, because the original tests only
# ever rewound a single step, where "first" happened to be right.


class _Nested(TypedDict):
    answers: list


def _build_nested():
    def ask(state: _Nested):
        a = interrupt({"step_key": "A"})
        b = interrupt({"step_key": "B"})
        c = interrupt({"step_key": "C"})
        return {"answers": [a, b, c]}

    inner = (
        StateGraph(_Nested)
        .add_node("ask", ask)
        .add_edge(START, "ask")
        .add_edge("ask", END)
        .compile()
    )
    return (
        StateGraph(_Nested)
        .add_node("builder", inner)
        .add_edge(START, "builder")
        .add_edge("builder", END)
        .compile(checkpointer=MemorySaver())
    )


async def _nested_paused(app, config) -> list[str]:
    snap = await app.aget_state(config, subgraphs=True)
    out: list[str] = []

    def walk(node):
        for t in (node.tasks or ()):
            for i in (t.interrupts or ()):
                out.append(i.value.get("step_key"))
            if t.state is not None and not isinstance(t.state, dict):
                walk(t.state)

    walk(snap)
    return out


async def _inner_ref(app, config) -> tuple[str, str]:
    """What ChatService._current_checkpoint_ref records: the innermost (ns, id)."""
    snap = await app.aget_state(config, subgraphs=True)
    innermost = snap

    def descend(node):
        nonlocal innermost
        for t in (node.tasks or ()):
            nested = getattr(t, "state", None)
            if nested is not None and not isinstance(nested, dict):
                innermost = nested
                descend(nested)

    descend(snap)
    cfg = innermost.config["configurable"]
    return cfg.get("checkpoint_ns") or "", cfg["checkpoint_id"]


@pytest.mark.asyncio
async def test_interrupts_inside_one_node_share_one_inner_stamp():
    """Several interrupt() calls in ONE node run share ONE checkpoint.

    The query / handoff / reject lanes re-ask inside wizard_interrupt's loop, i.e.
    inside a single node run, so every assistant row they produce carries the SAME
    (ns, id) stamp as the question that started the loop. A stamp therefore cannot
    tell those rows apart — see the test below for what a fork of it does instead.
    Pinned so a langgraph bump that changes this fails here.
    """
    app = _build_nested()
    cfg = {"configurable": {"thread_id": "nested-distinct"}}

    await _drain(app, cfg, {"answers": []})
    at_a = await _inner_ref(app, cfg)
    await _drain(app, cfg, Command(resume="ansA"))
    at_b = await _inner_ref(app, cfg)
    await _drain(app, cfg, Command(resume="ansB"))
    at_c = await _inner_ref(app, cfg)

    assert at_a == at_b == at_c, (at_a, at_b, at_c)


@_on_pinned_langgraph
@pytest.mark.asyncio
async def test_forking_a_shared_stamp_always_re_arms_the_second_interrupt():
    """What /rewind's group rule is built on.

    Forking the stamp shared by a group of interrupts does not re-ask the one the
    caller pointed at: it re-arms the group's SECOND interrupt, however many were
    answered. So ChatService.rewind honours a grouped anchor only when it is the
    second row and refuses the rest up front — the alternative was answering the
    wrong question after the transcript had already been cut. If a langgraph bump
    changes this, that rule has to be revisited, not just this test.
    """
    for answered in (1, 2):
        app = _build_nested()
        cfg = {"configurable": {"thread_id": f"shared-{answered}"}}
        await _drain(app, cfg, {"answers": []})
        for i in range(answered):
            await _drain(app, cfg, Command(resume=f"ans{i}"))
        ns, cid = await _inner_ref(app, cfg)

        forked = await app.aupdate_state(
            {"configurable": {"thread_id": f"shared-{answered}",
                              "checkpoint_id": cid, "checkpoint_ns": ns}},
            None,
        )
        await _drain(app, forked, None)
        assert (await _nested_paused(app, cfg))[:1] == ["B"], answered


@pytest.mark.asyncio
async def test_parent_checkpoint_cannot_identify_a_subgraph_step():
    """Why the namespace is not optional: one id covers every builder step."""
    app = _build_nested()
    cfg = {"configurable": {"thread_id": "nested-parent"}}

    await _drain(app, cfg, {"answers": []})
    at_a = (await app.aget_state(cfg)).config["configurable"]["checkpoint_id"]
    await _drain(app, cfg, Command(resume="ansA"))
    at_b = (await app.aget_state(cfg)).config["configurable"]["checkpoint_id"]
    await _drain(app, cfg, Command(resume="ansB"))
    at_c = (await app.aget_state(cfg)).config["configurable"]["checkpoint_id"]

    assert at_a == at_b == at_c


@pytest.mark.asyncio
async def test_forking_the_parent_always_lands_on_the_first_step():
    """The shipped bug. Kept so nobody drops the namespace again."""
    app = _build_nested()
    cfg = {"configurable": {"thread_id": "nested-wrong"}}

    await _drain(app, cfg, {"answers": []})
    await _drain(app, cfg, Command(resume="ansA"))
    parent_at_b = (await app.aget_state(cfg)).config["configurable"]["checkpoint_id"]
    await _drain(app, cfg, Command(resume="ansB"))
    assert await _nested_paused(app, cfg) == ["C", "C"]

    forked = await app.aupdate_state(
        {"configurable": {"thread_id": "nested-wrong",
                          "checkpoint_id": parent_at_b, "checkpoint_ns": ""}},
        None,
    )
    await _drain(app, forked, None)
    # Targeted B, landed on A.
    assert "B" not in await _nested_paused(app, cfg)


@_on_pinned_langgraph
@pytest.mark.asyncio
async def test_forking_the_inner_checkpoint_lands_on_the_targeted_step():
    """The fix: fork the innermost (ns, id) the anchor recorded."""
    app = _build_nested()
    cfg = {"configurable": {"thread_id": "nested-right"}}

    await _drain(app, cfg, {"answers": []})
    await _drain(app, cfg, Command(resume="ansA"))
    ns_at_b, id_at_b = await _inner_ref(app, cfg)   # recorded while paused at B
    assert ns_at_b.startswith("builder:")           # not the parent namespace

    await _drain(app, cfg, Command(resume="ansB"))
    assert await _nested_paused(app, cfg) == ["C", "C"]

    forked = await app.aupdate_state(
        {"configurable": {"thread_id": "nested-right",
                          "checkpoint_id": id_at_b, "checkpoint_ns": ns_at_b}},
        None,
    )
    await _drain(app, forked, None)
    assert await _nested_paused(app, cfg) == ["B", "B"]

    await _drain(app, cfg, Command(resume="ansB2"))
    assert await _nested_paused(app, cfg) == ["C", "C"]


# ── idle anchors ─────────────────────────────────────────────────────────────
#
# A plain chat reply runs to END, so the assistant row for it is stamped with a
# checkpoint that has nothing pending. Rewinding to it must not depend on an
# interrupt re-arming: an edit there is simply a new turn on the forked state.


class _Chat(TypedDict):
    said: list


def _build_chat():
    def reply(state: _Chat):
        return {"said": [*state.get("said", []), "reply"]}

    return (
        StateGraph(_Chat)
        .add_node("reply", reply)
        .add_edge(START, "reply")
        .add_edge("reply", END)
        .compile(checkpointer=MemorySaver())
    )


@pytest.mark.asyncio
async def test_idle_anchor_has_no_pending_interrupt_and_forks_to_a_new_turn():
    from app.services.resume_preflight import pending_interrupt_value

    app = _build_chat()
    cfg = {"configurable": {"thread_id": "idle"}}

    await _drain(app, cfg, {"said": []})
    anchor = await app.aget_state(cfg, subgraphs=True)
    assert pending_interrupt_value(anchor) is None          # what rewind() keys "idle" on
    anchor_id = anchor.config["configurable"]["checkpoint_id"]

    await _drain(app, cfg, {"said": ["turn 2 discarded"]})   # the answer being edited
    assert (await app.aget_state(cfg)).values["said"][-2:] == ["turn 2 discarded", "reply"]

    forked = await app.aupdate_state(
        {"configurable": {"thread_id": "idle", "checkpoint_id": anchor_id, "checkpoint_ns": ""}},
        {"said": ["forked"]},
    )
    assert forked["configurable"]["checkpoint_id"] != anchor_id
    # The tip moved to the fork and the discarded turn is gone from it.
    assert "turn 2 discarded" not in (await app.aget_state(cfg)).values["said"]

    # …and the edit runs as a fresh turn on the tip, like /chat does.
    await _drain(app, cfg, {"said": ["edited"]})
    assert (await app.aget_state(cfg)).values["said"][-2:] == ["edited", "reply"]


# ── narrator memory ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reset_history_forgets_the_discarded_branch():
    from types import SimpleNamespace

    from app.graph.narrator import beats

    state = {"messages": [SimpleNamespace(type="human", id="rewind-reset")]}
    assert beats.record_history(state, "Found 12 spots in Laval.") is True
    assert beats.recent_history(state)

    await beats.reset_history(state)

    assert not beats.recent_history(state)
