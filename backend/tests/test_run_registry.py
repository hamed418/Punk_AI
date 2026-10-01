"""The agent turn outlives its HTTP connection.

Chat used to drive ``graph.astream()`` from inside the SSE response generator, so
the run's lifetime was the connection's lifetime: a refresh or a thread switch
closed the generator, cancelled the graph mid-superstep, and skipped every line
after the stream loop — the assistant message was never written and the turn
vanished from history.

These cover the guarantees the registry replaces that with: the producer always
reaches its ``finally``, a late subscriber can replay what it missed, one thread
runs one turn, a stop still persists the partial answer, and the replay buffer
does not pin the 24 MB MAID map in memory.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.modules.chat import runs


@pytest.fixture(autouse=True)
def _clean_registry():
    runs._runs.clear()
    runs._persists.clear()
    yield
    runs._runs.clear()
    runs._persists.clear()


async def _drain(thread_id: str, from_seq: int = 0) -> list[dict]:
    return [ev async for _seq, ev in runs.subscribe(thread_id, from_seq)]


# ── the whole point: losing every subscriber does not lose the turn ───────────

@pytest.mark.asyncio
async def test_producer_finishes_after_subscriber_disconnects():
    committed = asyncio.Event()
    released = asyncio.Event()

    async def producer(emit):
        try:
            emit({"type": "assistant_message", "content": "half "})
            await released.wait()
            emit({"type": "assistant_message", "content": "the rest"})
            emit({"type": "done"})
        finally:
            committed.set()

    await runs.start_run("t1", producer)

    # A subscriber attaches, reads one frame, then walks away — the browser tab
    # closing, or Starlette tearing the response down on a refresh.
    agen = runs.subscribe("t1")
    first = await agen.__anext__()
    assert first[1]["content"] == "half "
    await agen.aclose()

    released.set()
    await asyncio.wait_for(committed.wait(), timeout=2)

    run = runs.get_run("t1")
    await asyncio.wait_for(run.done.wait(), timeout=2)
    assert not run.running
    # The work that happened after the disconnect is still on the run.
    texts = [ev.get("content") for _s, ev in run.events if ev["type"] == "assistant_message"]
    assert texts == ["half ", "the rest"]


# ── reattach ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_late_subscriber_replays_backlog_then_goes_live():
    gate = asyncio.Event()

    async def producer(emit):
        emit({"type": "thinking", "content": "a"})
        emit({"type": "assistant_message", "content": "b"})
        await gate.wait()
        emit({"type": "assistant_message", "content": "c"})
        emit({"type": "done"})

    await runs.start_run("t2", producer)
    await asyncio.sleep(0)  # let the producer reach the gate

    collected: list[dict] = []

    async def reader():
        async for _seq, ev in runs.subscribe("t2", 0):
            collected.append(ev)

    task = asyncio.create_task(reader())
    await asyncio.sleep(0)
    gate.set()
    await asyncio.wait_for(task, timeout=2)

    assert [e.get("content") for e in collected] == ["a", "b", "c", None]
    assert collected[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_from_seq_skips_what_the_client_already_saw():
    async def producer(emit):
        for i in range(4):
            emit({"type": "assistant_message", "content": str(i)})

    await runs.start_run("t3", producer)
    await asyncio.wait_for(runs.get_run("t3").done.wait(), timeout=2)

    assert [e["content"] for e in await _drain("t3", from_seq=2)] == ["2", "3"]


# ── one turn per thread ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_second_run_on_a_live_thread_is_refused():
    gate = asyncio.Event()

    async def producer(emit):
        await gate.wait()

    await runs.start_run("t4", producer)
    with pytest.raises(runs.RunBusyError):
        await runs.start_run("t4", producer)

    gate.set()
    await asyncio.wait_for(runs.get_run("t4").done.wait(), timeout=2)

    # Once it has finished the thread accepts a new turn again.
    await runs.start_run("t4", producer)


# ── stop button ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_still_persists_the_partial_turn():
    persisted: list[str] = []
    started = asyncio.Event()

    async def commit(text: str) -> None:
        await asyncio.sleep(0.01)  # a real DB write suspends; cancellation must not eat it
        persisted.append(text)

    async def producer(emit):
        captured = ""
        try:
            emit({"type": "assistant_message", "content": "partial"})
            captured = "partial"
            started.set()
            await asyncio.sleep(30)  # the long LLM call the user gave up on
        except asyncio.CancelledError:
            emit({"type": "cancelled"})
            raise
        finally:
            persist = runs.track_persist(commit(captured), "t5")
            try:
                await asyncio.shield(persist)
            except asyncio.CancelledError:
                pass

    await runs.start_run("t5", producer)
    await asyncio.wait_for(started.wait(), timeout=2)

    assert await runs.cancel("t5") is True
    # cancel() returning means the detached persist has already been drained.
    assert persisted == ["partial"]
    assert runs.get_run("t5").cancelled is True


@pytest.mark.asyncio
async def test_cancel_on_an_idle_thread_is_a_no_op():
    assert await runs.cancel("nobody") is False


# ── replay buffer does not pin the MAID map ──────────────────────────────────

@pytest.mark.asyncio
async def test_replay_buffer_stores_the_slimmed_map():
    big = [{"lat": 40.0 + i * 1e-6, "lng": -74.0, "maid": f"m{i}"} for i in range(20_000)]
    live_seen: list[int] = []

    async def producer(emit):
        emit({"type": "map_data", "content": {"action_type": "maid_split_view",
                                              "maid_observations": big}})

    await runs.start_run("t6", producer)
    run = runs.get_run("t6")
    await asyncio.wait_for(run.done.wait(), timeout=2)

    stored = run.events[0][1]["content"]["maid_observations"]
    assert len(stored) <= runs._MAX_STORED_OBSERVATIONS
    # The source list is never mutated — a live subscriber must still get all of it.
    assert len(big) == 20_000
    del live_seen


@pytest.mark.asyncio
async def test_trim_sacrifices_thinking_frames_not_widgets():
    async def producer(emit):
        emit({"type": "pending_action", "content": {"action_type": "text_input"}})
        for i in range(runs._MAX_BUFFERED_EVENTS + 50):
            emit({"type": "thinking", "content": str(i)})

    await runs.start_run("t7", producer)
    run = runs.get_run("t7")
    await asyncio.wait_for(run.done.wait(), timeout=2)

    kinds = [ev["type"] for _s, ev in run.events]
    assert len(run.events) <= runs._MAX_BUFFERED_EVENTS
    assert "pending_action" in kinds  # the frame the UI needs on reattach survived


# ── a failing turn still terminates its subscribers ──────────────────────────

@pytest.mark.asyncio
async def test_producer_exception_becomes_an_error_frame():
    async def producer(emit):
        emit({"type": "thinking", "content": "working"})
        raise RuntimeError("gemini exploded")

    await runs.start_run("t8", producer)
    await asyncio.wait_for(runs.get_run("t8").done.wait(), timeout=2)

    events = await _drain("t8")
    assert events[-1] == {"type": "error", "content": "gemini exploded"}


# ── deleting a thread must not leave its turn running ─────────────────────────
#
# The run keeps a task writing against a checkpoint and a conversation row that
# are about to disappear; its _commit_turn then inserts an assistant message for
# a cascade-deleted conversation and the failure is only logged.

class _StubSaver:
    """Stands in for AsyncPostgresSaver's `async with ... as checkpointer`."""

    deleted: list[str] = []

    @classmethod
    def from_conn_string(cls, _url):
        return cls()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def adelete_thread(self, thread_id):
        type(self).deleted.append(thread_id)


class _StubRepo:
    def __init__(self):
        self.deleted_conv_ids = []

    async def find_specific_user_chat(self, _db, thread_id, _user_id):
        return SimpleNamespace(id=f"conv-{thread_id}", thread_id=thread_id)

    async def find_specific_user_chats(self, _db, thread_ids, _user_id):
        return [SimpleNamespace(id=f"conv-{t}", thread_id=t) for t in thread_ids]

    async def delete_conversation(self, _db, conv_id):
        self.deleted_conv_ids.append(conv_id)

    async def delete_multiple_conversations(self, _db, conv_ids):
        self.deleted_conv_ids.extend(conv_ids)


@pytest.fixture
def _delete_service(monkeypatch):
    from app.modules.chat import service as service_module

    _StubSaver.deleted = []
    monkeypatch.setattr(service_module, "AsyncPostgresSaver", _StubSaver)
    repo = _StubRepo()
    return service_module.ChatService(repo), repo


async def _park_run(thread_id: str) -> asyncio.Event:
    """A turn that will never finish on its own — only a cancel ends it."""
    started = asyncio.Event()

    async def producer(emit):
        emit({"type": "thinking", "content": "working"})
        started.set()
        await asyncio.sleep(30)

    await runs.start_run(thread_id, producer)
    await asyncio.wait_for(started.wait(), timeout=2)
    return started


@pytest.mark.asyncio
async def test_deleting_a_conversation_cancels_its_live_run(_delete_service):
    svc, repo = _delete_service
    await _park_run("t-del")
    assert runs.is_running("t-del") is True

    result = await svc.delete_conversation(SimpleNamespace(id="u1"), "t-del", db=None)

    # The blanket try/except turns a crash into a message, so assert the happy
    # path was actually reached and not just survived.
    assert result == {"message": "Conversation deleted successfully"}
    assert runs.is_running("t-del") is False
    assert _StubSaver.deleted == ["t-del"]
    assert repo.deleted_conv_ids == ["conv-t-del"]


@pytest.mark.asyncio
async def test_bulk_delete_cancels_every_live_run(_delete_service):
    svc, _repo = _delete_service
    for tid in ("t-a", "t-b"):
        await _park_run(tid)

    result = await svc.delete_multiple_conversations(
        SimpleNamespace(id="u1"), ["t-a", "t-b", "t-idle"], db=None
    )

    assert result == {"message": "3 conversation(s) deleted successfully"}
    assert not any(runs.is_running(t) for t in ("t-a", "t-b"))
