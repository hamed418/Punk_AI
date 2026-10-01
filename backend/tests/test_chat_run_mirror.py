"""
tests/test_chat_run_mirror.py
─────────────────────────────
A turn started on one instance must be followable from another.

`runs.py` decouples a turn from the HTTP connection so a refresh cannot lose it —
but the registry was a process-local dict, and the service runs at maxScale=5
with sessionAffinity=false. A reconnect lands on a random instance, so four
times out of five the subscriber model found nothing and the user got exactly
the blank screen the module exists to prevent.

These tests simulate the two instances by clearing the local registry between
the write and the read: the only thing left to serve the reconnect is the Redis
mirror. Skipped entirely when Redis is not configured, because the in-process
path is unchanged and already covered elsewhere.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from app.modules.chat import run_store, runs

pytestmark = pytest.mark.skipif(
    not run_store.enabled(), reason="Redis not configured (REDIS_HOST unset)"
)


@pytest.fixture(autouse=True)
def _fresh_redis_client():
    """Rebuild the shared Redis client for each test's event loop.

    `redis.asyncio` binds its connection pool to the loop that first uses it,
    and pytest-asyncio gives every test a new loop — so a client built in test
    one is unusable in test two. Production has a single long-lived loop per
    process and never hits this, which is why the reset lives here rather than
    in app/core/redis.py.
    """
    from app.core import redis as _core_redis

    _core_redis._client = None
    _core_redis._unavailable = False
    yield
    _core_redis._client = None


@pytest.fixture(autouse=True)
def _no_dangling_evictions():
    """`_evict_later` sleeps _RETAIN_SECONDS; a test ending sooner leaves it
    pending and asyncio logs a scary teardown error. Cancel them."""
    yield
    import asyncio

    try:
        loop = asyncio.get_event_loop_policy().get_event_loop()
    except RuntimeError:
        return
    for task in list(asyncio.all_tasks(loop)) if not loop.is_closed() else []:
        if "_evict_later" in repr(task.get_coro()):
            task.cancel()


async def _noop():
    return None


async def _until(produce, predicate, timeout: float = 10.0, step: float = 0.05):
    """Poll ``produce()`` until ``predicate`` holds, instead of guessing a sleep."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        value = await produce()
        if predicate(value):
            return value
        await asyncio.sleep(step)
    raise AssertionError(f"condition not met within {timeout}s")


def _thread() -> str:
    return f"test-mirror-{uuid.uuid4().hex[:12]}"


async def _drain(thread_id: str, from_seq: int = 0) -> list[tuple[int, dict]]:
    return [item async for item in runs.subscribe(thread_id, from_seq)]


@pytest.mark.asyncio
async def test_a_finished_run_replays_on_another_instance():
    """The core failure: instance A ran the turn, the client reconnects to B."""
    tid = _thread()

    async def producer(emit):
        emit({"type": "thinking", "content": "working"})
        emit({"type": "assistant_message", "content": "here is your answer"})

    run = await runs.start_run(tid, producer)
    await run.task

    # Instance B: same Redis, no local knowledge of the run at all.
    runs._runs.pop(tid, None)
    assert runs.get_run(tid) is None, "local registry must be empty for this to mean anything"

    replayed = await _drain(tid)
    kinds = [e["type"] for _seq, e in replayed]
    assert kinds == ["thinking", "assistant_message"]
    assert replayed[-1][1]["content"] == "here is your answer"


@pytest.mark.asyncio
async def test_from_seq_is_honoured_across_instances():
    """A reconnect resumes where it left off rather than replaying everything."""
    tid = _thread()

    async def producer(emit):
        for i in range(5):
            emit({"type": "thinking", "content": f"step {i}"})

    run = await runs.start_run(tid, producer)
    await run.task
    runs._runs.pop(tid, None)

    replayed = await _drain(tid, from_seq=3)
    assert [seq for seq, _e in replayed] == [3, 4]


@pytest.mark.asyncio
async def test_a_live_run_is_followed_from_another_instance():
    """Not just replay — a subscriber elsewhere receives events as they happen."""
    tid = _thread()
    gate = asyncio.Event()

    async def producer(emit):
        emit({"type": "thinking", "content": "first"})
        await gate.wait()
        emit({"type": "assistant_message", "content": "last"})

    run = await runs.start_run(tid, producer)
    # Wait for the first event to REACH the mirror rather than sleeping a fixed
    # interval — under a loaded suite a fixed sleep is a coin flip.
    await _until(lambda: run_store.backlog(tid, 0), lambda b: len(b) >= 1)

    local = runs._runs.pop(tid)          # instance B knows nothing
    collected: list = []

    async def follower():
        async for seq, event in runs.subscribe(tid, 0):
            collected.append(event["type"])

    task = asyncio.create_task(follower())
    # The follower must be subscribed before the second event is emitted, or it
    # is testing replay rather than live delivery.
    await _until(lambda: _noop(), lambda _x: len(collected) >= 1)
    gate.set()
    await local.task
    await asyncio.wait_for(task, timeout=15)

    assert collected == ["thinking", "assistant_message"], collected


@pytest.mark.asyncio
async def test_status_sees_a_run_owned_elsewhere():
    """`is_running` answering "no" for a turn on another instance would let a
    rewind start underneath a live run."""
    tid = _thread()
    started = asyncio.Event()
    release = asyncio.Event()

    async def producer(emit):
        emit({"type": "thinking", "content": "x"})
        started.set()
        await release.wait()

    run = await runs.start_run(tid, producer)
    await started.wait()
    await asyncio.sleep(0.2)

    local = runs._runs.pop(tid)
    info = await runs.describe(tid)
    assert info is not None and info["running"]
    assert info["run_id"] == run.run_id, "the mirror reports the owner's run id"
    assert await runs.is_running_anywhere(tid) is True

    release.set()
    await local.task


@pytest.mark.asyncio
async def test_the_busy_guard_holds_across_instances():
    """Two tabs on two instances both passing the local check would race two
    Command(resume=...) values into one interrupt."""
    tid = _thread()
    release = asyncio.Event()

    async def producer(emit):
        emit({"type": "thinking", "content": "x"})
        await release.wait()

    run = await runs.start_run(tid, producer)
    await asyncio.sleep(0.2)

    local = runs._runs.pop(tid)          # instance B: local check would pass
    with pytest.raises(runs.RunBusyError):
        await runs.start_run(tid, producer)

    release.set()
    await local.task
    # Once finished the claim is released, so the thread is usable again.
    await asyncio.sleep(0.3)
    assert await run_store.claim(tid, "someone-else") is True


@pytest.mark.asyncio
async def test_a_map_payload_is_slimmed_before_it_reaches_redis(monkeypatch):
    """A map_data event can carry ~229k observation points / 24 MB. The local
    buffer already slims it; pushing the raw list to Redis would be far worse.

    Asserted at the boundary — what `append` is HANDED — rather than by writing
    and reading it back. The invariant is "slimmed before it leaves the
    process", and checking it here keeps the test off the network: a real
    round trip of even the slimmed payload can exceed the deliberately tight
    2s socket timeout when Redis is a WAN hop away, which is a property of the
    developer's link, not of the code.
    """
    tid = _thread()
    huge = [{"lat": 1.0 + i, "lng": 2.0} for i in range(20000)]
    seen: list = []

    async def spy(thread_id, seq, event):
        seen.append(event)

    monkeypatch.setattr(run_store, "append", spy)

    async def producer(emit):
        emit({"type": "map_data", "content": {"maid_observations": huge}})

    run = await runs.start_run(tid, producer)
    await run.task

    assert len(seen) == 1, "the event must reach the mirror exactly once"
    stored = seen[0]["content"]["maid_observations"]
    assert len(stored) < len(huge), "raw payload reached the mirror unslimmed"
    assert len(stored) <= 5000
