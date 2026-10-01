"""The checkpoint is the authority on what widget the UI should be showing.

``wizard_interrupt`` calls ``interrupt(_iv)`` where ``_iv`` IS the pending_action
dict (plus an ``_interrupt_index`` stamp), so ``tasks[].interrupts[].value`` is
the real record — not the copy the client used to scrape out of the last
assistant message's ``langchain_data``.

The case that matters is the nested one: ``campaign_builder`` is a compiled
subgraph, so a builder interrupt never appears in the parent's
``tasks[].interrupts``. It surfaces only in ``tasks[].state.tasks[].interrupts``,
which is the whole reason the walk recurses.

Also covers the ``/chat`` guard: sending a fresh message to a thread that is
paused at an interrupt used to make LangGraph drop the pending task and restart
the interrupted node, silently losing the wizard's place.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.chat.service import ChatService
from app.modules.chat.repository import ChatRepository
from app.services.resume_preflight import (
    _has_pending_interrupt,
    pending_interrupt_value,
)

PENDING = {
    "action_type": "text_input",
    "step_key": "geo_collect_locations",
    "prompt": "Which neighbourhoods?",
}


def _snapshot(*tasks, values: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(tasks=list(tasks), values=values or {}, next=())


def _task(interrupts=(), state=None) -> SimpleNamespace:
    return SimpleNamespace(
        interrupts=[SimpleNamespace(value=v) for v in interrupts],
        state=state,
    )


# ── reading the paused widget out of the checkpoint ──────────────────────────

def test_none_when_nothing_is_paused():
    assert pending_interrupt_value(_snapshot(_task())) is None
    assert pending_interrupt_value(None) is None
    assert _has_pending_interrupt(_snapshot(_task())) is False


def test_parent_level_interrupt():
    snap = _snapshot(_task(interrupts=[PENDING]))
    assert pending_interrupt_value(snap) == PENDING
    assert _has_pending_interrupt(snap) is True


def test_subgraph_interrupt_is_found_through_the_parent():
    """The builder case. The parent task carries no interrupts of its own."""
    inner = _snapshot(_task(interrupts=[{**PENDING, "_interrupt_index": 2}]))
    outer = _snapshot(_task(interrupts=(), state=inner))

    assert outer.tasks[0].interrupts == []  # nothing at the parent level
    assert pending_interrupt_value(outer) == PENDING  # the stamp is stripped
    assert _has_pending_interrupt(outer) is True


def test_non_dict_interrupt_value_yields_no_widget():
    """A bare interrupt("...") is paused but has no pending_action to render."""
    snap = _snapshot(_task(interrupts=["just a string"]))
    assert pending_interrupt_value(snap) is None
    assert _has_pending_interrupt(snap) is True


# ── /chat on a paused thread ─────────────────────────────────────────────────

class _FakeGraph:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    async def aget_state(self, config, subgraphs: bool = False):
        return self._snapshot


def _request(graph):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(graph=graph)))


@pytest.mark.asyncio
async def test_chat_on_an_interrupted_thread_returns_409_with_the_widget():
    inner = _snapshot(_task(interrupts=[{**PENDING, "_interrupt_index": 0}]))
    service = ChatService(ChatRepository())
    payload = SimpleNamespace(session_id="thread-1", message="hello", question=None)

    with pytest.raises(HTTPException) as exc:
        await service.chat_stream(
            payload,
            _request(_FakeGraph(_snapshot(_task(state=inner)))),
            SimpleNamespace(id="user-1"),
        )

    assert exc.value.status_code == 409
    # The client gets the widget it should have been showing, so it can re-render
    # instead of corrupting the thread.
    assert exc.value.detail["pending_action"] == PENDING


@pytest.mark.asyncio
async def test_chat_without_a_graph_is_503_not_a_crash():
    service = ChatService(ChatRepository())
    payload = SimpleNamespace(session_id=None, message="hello", question=None)

    with pytest.raises(HTTPException) as exc:
        await service.chat_stream(payload, _request(None), SimpleNamespace(id="user-1"))
    assert exc.value.status_code == 503


# ── undo eligibility ─────────────────────────────────────────────────────────

def _msg(checkpoint_id, checkpoint_ns=""):
    return SimpleNamespace(
        checkpoint_id=checkpoint_id,
        checkpoint_ns=checkpoint_ns,
        auto_id=1,
        role="assistant",
    )


def test_can_undo_needs_two_stamped_assistant_turns():
    service = ChatService(ChatRepository())
    snap = _snapshot()

    # Third arg is `running`, resolved once per request by the caller (it is a
    # cross-instance lookup now — see runs.describe). Passing it in keeps this a
    # pure predicate instead of one that reaches into a global registry.
    assert service._can_undo(snap, [], False) is False
    assert service._can_undo(snap, [_msg("ck2")], False) is False           # first turn
    assert service._can_undo(snap, [_msg("ck2"), _msg(None)], False) is False  # unstamped row
    assert service._can_undo(snap, [_msg("ck2"), _msg("ck1")], False) is True


def test_can_undo_is_blocked_while_a_turn_is_running():
    """Including a turn running on ANOTHER instance: the caller resolves that
    through runs.describe, so a rewind cannot start underneath one."""
    service = ChatService(ChatRepository())
    snap = _snapshot()

    rewindable = [_msg("ck2"), _msg("ck1")]
    assert service._can_undo(snap, rewindable, False) is True
    assert service._can_undo(snap, rewindable, True) is False


def test_can_undo_refuses_a_row_with_no_namespace():
    """Pre-namespace rows carry the ambiguous parent stamp shared by every builder
    step, so forking one rewinds to the wrong step. Refuse rather than guess."""
    service = ChatService(ChatRepository())
    snap = _snapshot()

    stale = [_msg("ck2", checkpoint_ns=None), _msg("ck1", checkpoint_ns=None)]
    assert service._can_undo(snap, stale, False) is False


def test_can_undo_is_hard_blocked_after_publish():
    """Rewinding past a publish leaves the checkpoint describing live Meta objects."""
    service = ChatService(ChatRepository())
    published = _snapshot(values={"meta_campaign_ids": {"campaign_id": "1203"}})

    assert service._can_undo(published, [_msg("ck2"), _msg("ck1")], False) is False


def test_can_undo_is_blocked_by_ids_held_only_in_the_builder_scratch():
    """`publish` writes meta_campaign_ids into the builder's scratch and only
    builder_finalize copies them up — with the go_live_confirm gate pausing in
    between. At that pause the campaign is live on Meta (paused) while the parent
    values still look unpublished; a rewind there would publish a second one."""
    service = ChatService(ChatRepository())
    inner = _snapshot(values={"campaign_builder_state": {"meta_campaign_ids": {"campaign_id": "1203"}}})
    parent = _snapshot(SimpleNamespace(interrupts=[], state=inner), values={})

    assert service._publish_locked(parent) is True
    assert service._can_undo(parent, [_msg("ck2"), _msg("ck1")], False) is False

    # An empty scratch (build still in progress) is not a lock.
    idle = _snapshot(
        SimpleNamespace(interrupts=[], state=_snapshot(values={"campaign_builder_state": {}})),
        values={},
    )
    assert service._publish_locked(idle) is False


def test_can_undo_is_blocked_by_a_partly_built_publish_ledger():
    """Objects created on Meta but not yet recorded in state (the ledger half of
    the lock, computed by the async caller)."""
    service = ChatService(ChatRepository())
    rewindable = [_msg("ck2"), _msg("ck1")]

    assert service._can_undo(_snapshot(), rewindable, False, ledger_locked=False) is True
    assert service._can_undo(_snapshot(), rewindable, False, ledger_locked=True) is False
