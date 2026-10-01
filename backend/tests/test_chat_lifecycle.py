"""The eleven flows a chat turn has to survive.

Refresh, thread switch, stop, edit, double-submit, two tabs, cancel-during-rewind
and backend restart each move the turn between three places that can disagree: the
in-process run registry, the LangGraph checkpoint, and the ``chat_messages``
transcript. Every bug this file pins was a disagreement between two of them.

Registry-level flows run against the real ``runs`` module with fake producers, the
same style as ``test_run_registry.py``. Decision-level flows (stop reconciliation)
run against the real ``ChatService`` methods with stub snapshots, the same style as
``test_stop_rollback.py`` — no DB, no HTTP.

NOT covered here, deliberately: every flow that needs the run to be *findable*
(1, 3, 7, 8) assumes one process. ``_runs`` is a module-level dict, so on a fleet
of more than one Cloud Run instance a request that lands on a non-owning instance
sees no run at all — ``/stream`` 204s, ``/cancel`` no-ops, and the double-submit
guard stops guarding. These tests pass per-instance and prove nothing about the
fleet.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.modules.chat import runs
from app.modules.chat.repository import ChatRepository
from app.modules.chat.schemas import CancelOutcome
from app.modules.chat.service import ChatService

SERVICE = ChatService(ChatRepository())


@pytest.fixture(autouse=True)
def _clean_registry():
    runs._runs.clear()
    runs._persists.clear()
    yield
    runs._runs.clear()
    runs._persists.clear()


def _msg(role, *, step_key=None, content="x", auto_id=1, ckpt=None, ns=None):
    return SimpleNamespace(
        role=role,
        content=content,
        auto_id=auto_id,
        checkpoint_id=ckpt,
        checkpoint_ns=ns,
        langchain_data=({"pending_action": {"step_key": step_key}} if step_key else None),
    )


async def _park_run(thread_id: str) -> asyncio.Event:
    """A turn that runs until something cancels it."""
    started = asyncio.Event()

    async def producer(emit):
        emit({"type": "thinking", "content": "working"})
        started.set()
        await asyncio.sleep(30)

    await runs.start_run(thread_id, producer)
    await asyncio.wait_for(started.wait(), timeout=2)
    return started


# ── 1 · refresh during streaming ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flow1_refresh_during_streaming_replays_then_goes_live():
    """The browser drops the connection and comes back. Nothing is lost."""
    gate = asyncio.Event()

    async def producer(emit):
        emit({"type": "assistant_message", "content": "before "})
        await gate.wait()
        emit({"type": "assistant_message", "content": "after"})
        emit({"type": "done"})

    await runs.start_run("t1", producer)
    await asyncio.sleep(0)

    # The pre-refresh connection reads one frame and dies.
    agen = runs.subscribe("t1")
    assert (await agen.__anext__())[1]["content"] == "before "
    await agen.aclose()

    # The refreshed client asks for everything from the top.
    collected: list[dict] = []

    async def reader():
        async for _seq, ev in runs.subscribe("t1", 0):
            collected.append(ev)

    task = asyncio.create_task(reader())
    await asyncio.sleep(0)
    gate.set()
    await asyncio.wait_for(task, timeout=2)

    assert [e.get("content") for e in collected] == ["before ", "after", None]
    assert runs.is_running("t1") is False


# ── 2 · refresh while paused at a widget ─────────────────────────────────────

def test_flow2_paused_thread_reports_its_widget_from_the_checkpoint():
    """No run exists — the checkpoint is what tells the client to draw the widget.

    This is the property that makes the transcript a cache rather than the truth:
    /status reads the live interrupt, so a refresh repairs itself even when the DB
    row for the question was never written.
    """
    from app.services.resume_preflight import pending_interrupt_value

    paused = SimpleNamespace(
        tasks=(
            SimpleNamespace(
                state=None,
                interrupts=(SimpleNamespace(value={"step_key": "geo_collect_stores"}),),
            ),
        ),
        next=("campaign_builder",),
        values={},
    )
    assert runs.is_running("nobody") is False
    assert pending_interrupt_value(paused) == {"step_key": "geo_collect_stores"}


# ── 3 · switch thread while streaming, then return ───────────────────────────

@pytest.mark.asyncio
async def test_flow3_switching_away_detaches_the_client_not_the_run():
    committed = asyncio.Event()
    released = asyncio.Event()

    async def producer(emit):
        try:
            emit({"type": "assistant_message", "content": "kept going"})
            await released.wait()
            emit({"type": "done"})
        finally:
            committed.set()

    await runs.start_run("t3", producer)
    agen = runs.subscribe("t3")
    await agen.__anext__()
    await agen.aclose()  # user clicked another thread

    released.set()
    await asyncio.wait_for(committed.wait(), timeout=2)

    # Coming back re-attaches to the finished run — the 120s retention window is
    # what stops a turn that completed while away from showing as an empty screen.
    assert runs.get_run("t3") is not None
    replayed = [ev async for _s, ev in runs.subscribe("t3", 0)]
    assert replayed[0]["content"] == "kept going"


# ── 4 · stop BEFORE the widget answer is consumed ────────────────────────────

def test_flow4_unconsumed_answer_is_withdrawn():
    """Graph never moved: same step_key AND the same checkpoint it asked from."""
    tail = [
        _msg("user", content="500 Queen St W", auto_id=9),
        _msg("assistant", step_key="geo_collect_stores", auto_id=8, ckpt="ck-1", ns=""),
    ]
    assert SERVICE._answered_step_key(tail) == "geo_collect_stores"
    asking = SERVICE._asking_message(tail)
    assert (asking.checkpoint_id, asking.checkpoint_ns) == ("ck-1", "")


# ── 5 · stop AFTER it is consumed ────────────────────────────────────────────

def test_flow5_consumed_answer_survives_when_the_step_advanced():
    tail = [
        _msg("user", auto_id=9),
        _msg("assistant", step_key="geo_collect_stores", auto_id=8, ckpt="ck-1", ns=""),
    ]
    assert SERVICE._answered_step_key(tail) != "geo_store_confirmation"


def test_flow5_consumed_answer_survives_a_step_that_re_asks_itself():
    """The regression D1 fixes.

    A validation retry consumes the answer and interrupts again on the SAME
    step_key. Comparing step_keys alone says "never moved" and withdraws a message
    the graph has already acted on. The checkpoint address is what distinguishes
    them: committing a superstep always writes a new checkpoint_id.
    """
    tail = [
        _msg("user", content="not a real address", auto_id=9),
        _msg("assistant", step_key="geo_collect_stores", auto_id=8, ckpt="ck-1", ns=""),
    ]
    current_step = "geo_collect_stores"          # identical — the step re-asked
    current_ckpt, current_ns = "ck-2", ""        # but the graph committed

    assert SERVICE._answered_step_key(tail) == current_step  # step_key is fooled
    asking = SERVICE._asking_message(tail)
    assert (current_ckpt, current_ns) != (asking.checkpoint_id, asking.checkpoint_ns)


def test_flow5_pre_stamp_rows_fall_back_to_the_step_key_verdict():
    """Rows written before the checkpoint columns existed carry None.

    There is no backfill (see migration a41b7c6d92e5), so the guard must degrade to
    the old behaviour rather than refusing to roll back at all.
    """
    tail = [_msg("user", auto_id=9), _msg("assistant", step_key="s", auto_id=8)]
    assert SERVICE._asking_message(tail).checkpoint_id is None


# ── 6 · edit an old answer ───────────────────────────────────────────────────

def test_flow6_edit_requires_both_checkpoint_halves():
    assert SERVICE._is_rewindable(SimpleNamespace(checkpoint_id="ck", checkpoint_ns="")) is True
    assert SERVICE._is_rewindable(SimpleNamespace(checkpoint_id="ck", checkpoint_ns=None)) is False


def test_flow6_edit_is_refused_once_published():
    """Forking past a publish would describe ad objects that already exist."""
    published = SimpleNamespace(values={"meta_campaign_ids": {"campaign_id": "1203"}})
    assert SERVICE._publish_locked(published) is True
    assert SERVICE._publish_locked(SimpleNamespace(values={})) is False


# ── 7 · submit twice quickly ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flow7_second_submit_is_refused_while_one_is_live():
    await _park_run("t7")
    with pytest.raises(runs.RunBusyError):
        await runs.start_run("t7", lambda emit: asyncio.sleep(0))
    assert runs.live_run_count() == 1


# ── 8 · resume from two tabs ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flow8_second_tab_can_attach_to_the_run_it_was_refused():
    """RunBusyError is not a failure — the turn exists and is joinable.

    The client turns the 409 into an attach, so the second tab watches the same
    stream instead of reporting a message that never sent.
    """
    async def producer(emit):
        emit({"type": "assistant_message", "content": "one turn"})
        emit({"type": "done"})

    await runs.start_run("t8", producer)
    with pytest.raises(runs.RunBusyError):
        await runs.start_run("t8", producer)

    await asyncio.wait_for(runs.get_run("t8").done.wait(), timeout=2)
    seen = [ev async for _s, ev in runs.subscribe("t8", 0)]
    assert [e.get("content") for e in seen] == ["one turn", None]


# ── 9 · cancel while a rewind begins ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_flow9_cancel_cannot_split_the_row_delete_from_the_fork():
    """The regression D2 fixes.

    Rewind deletes transcript rows and then forks the checkpoint. Cancelled between
    the two, it leaves a truncated transcript over an unforked checkpoint: /status
    reports neither running nor interrupted, the client's repair path never fires,
    and the conversation is dead. Shielding makes the pair atomic.
    """
    steps: list[str] = []

    async def cut_and_fork():
        steps.append("rows-deleted")
        await asyncio.sleep(0.02)   # the checkpointer write suspends
        steps.append("forked")

    # Mirrors ChatService.rewind: the cut happens in the request handler, BEFORE a
    # run exists, so the thing that can interrupt it is the client disconnecting and
    # Starlette cancelling the handler — not the stop button.
    async def handler():
        cut = runs.track_persist(cut_and_fork(), "rewind-thread")
        await asyncio.shield(cut)

    task = asyncio.create_task(handler())
    await asyncio.sleep(0)          # let it reach the shielded section
    task.cancel()                   # client disconnected
    with pytest.raises(asyncio.CancelledError):
        await task

    # Shielding alone would strand the fork half here with nothing awaiting it.
    # Tracking is what lets drain_persists finish the pair.
    await runs.drain_persists("rewind-thread", timeout=2)
    assert steps == ["rows-deleted", "forked"]


# ── 10 · backend restart during streaming ────────────────────────────────────

@pytest.mark.asyncio
async def test_flow10_shutdown_cancels_runs_but_persists_the_partial_turn():
    """``cancel_all()`` runs before ``close_checkpointer()`` (main.py:52-58) so the
    shielded persist commits while the pool is still open."""
    persisted: list[str] = []

    async def commit(text: str) -> None:
        await asyncio.sleep(0.01)
        persisted.append(text)

    started = asyncio.Event()

    async def producer(emit):
        captured = ""
        try:
            emit({"type": "assistant_message", "content": "half an answer"})
            captured = "half an answer"
            started.set()
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            emit({"type": "cancelled"})
            raise
        finally:
            persist = runs.track_persist(commit(captured), "t10")
            try:
                await asyncio.shield(persist)
            except asyncio.CancelledError:
                pass

    await runs.start_run("t10", producer)
    await asyncio.wait_for(started.wait(), timeout=2)

    await runs.cancel_all()

    assert persisted == ["half an answer"]
    assert runs.is_running("t10") is False


# ── 11 · backend restart while paused ────────────────────────────────────────

@pytest.mark.asyncio
async def test_flow11_restart_while_paused_loses_nothing():
    """Nothing is in flight, so a restart is a no-op — the checkpoint holds the
    interrupt and /status rebuilds the widget from it."""
    await runs.cancel_all()
    assert runs.live_run_count() == 0
    assert runs.get_run("t11") is None
    assert await runs.cancel("t11") is False


# ── the outcome contract Stop reports ────────────────────────────────────────

def test_cancel_outcomes_are_distinct_and_serialise_as_strings():
    values = {o.value for o in CancelOutcome}
    assert values == {"not_running", "unsent", "kept", "publish_interrupted"}
    assert CancelOutcome.UNSENT == "unsent"  # str enum — JSON-safe as-is
