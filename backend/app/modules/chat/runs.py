"""
modules/chat/runs.py
────────────────────
In-process registry of live agent runs.

Why this exists: the chat endpoints used to drive ``graph.astream()`` from
*inside* the SSE response generator, which tied the run's lifetime to the HTTP
connection's lifetime. A refresh, a thread switch, or a dropped connection
closed the generator → ``GeneratorExit`` at the ``yield`` → the graph run was
cancelled mid-superstep and every line after the stream loop (assistant-message
persist, token billing) never ran. The turn simply vanished.

Here the run is an ``asyncio.Task`` that owns the whole turn end to end. HTTP
requests are *subscribers*: they attach, replay whatever they missed, and follow
along. Losing every subscriber changes nothing about the run.

The registry was in-process only, on the assumption of a single uvicorn worker
(backend/Dockerfile CMD has no ``--workers``). That assumption covered THREADS
inside one container and expired when the deployment grew horizontally: Cloud Run
runs this service at ``maxScale=5`` with ``sessionAffinity=false``, so a
reconnect lands on a random instance and four times out of five finds nothing —
the subscriber model silently absent, exactly the blank screen described above.

``run_store.py`` mirrors what a subscriber needs (status, replay buffer, live
events, the busy claim) and what a stop button needs (a control channel) into
Redis, so any instance can serve a reconnect or stop a run. The owning
``asyncio.Task`` still cannot move; only the *visibility* and the stop request
do.

Everything local stays the fast path and works unchanged when Redis is
unconfigured — local dev and the test suite need no Redis, and a Redis outage
degrades to exactly the single-instance behaviour.

An in-flight turn is still lost on deploy; the LangGraph checkpoint survives, so
the thread itself is always recoverable.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Awaitable, Callable, Optional

from app.core.config import settings
from app.core.logging import logger
from app.modules.chat import run_store

# How long a finished run stays in the registry. A client that refreshes just as
# the turn completes still gets the full replay instead of an empty screen.
_RETAIN_SECONDS = 120

# Replay-buffer cap. Overflow drops the oldest `thinking` frames only — they are
# the flood, and replay correctness depends on assistant_message / pending_action
# / map_data / campaign_plan surviving.
_MAX_BUFFERED_EVENTS = 2000

_MAX_CONCURRENT_RUNS = getattr(settings, "MAX_CONCURRENT_CHAT_STREAMS", 300)

# How often a live run re-arms its mirrored keys (run_store._TTL_SECONDS). Well
# inside that TTL, so a long MAID turn never outlives its own status, replay
# buffer or busy claim.
_TOUCH_EVERY_S = 60.0

# The MAID split-view map ships every observed device point — up to ~229k
# {lat,lng,maid} entries, 24 MB on one payload. The map can never draw more than
# 1500 of them (WidgetMaidSplitView caps at `filtered.slice(0, 1500)`, after
# filtering to the current viewport and only above zoom 14). Keeping the rest
# bloats every chat row, every history response, every stringify-diff on the
# client — and, since this module buffers events for replay, would pin tens of
# MB per live run in memory.
#
# Live subscribers still get every point. Only the copy kept for replay and for
# `langchain_data` is sampled. 5000 leaves headroom over the 1500 render cap
# because that cap is per VIEWPORT, so a zoomed-in view still needs points.
_MAX_STORED_OBSERVATIONS = 5000

Emit = Callable[[dict], None]
Producer = Callable[[Emit], Awaitable[None]]


def _slim_for_storage(event_type: str | None, content: Any) -> Any:
    """Shrink a map_data payload before it is buffered or persisted.

    Returns ``content`` untouched for every other event type, and never mutates
    its argument — the live stream must keep full fidelity.
    """
    if event_type != "map_data" or not isinstance(content, dict):
        return content
    obs = content.get("maid_observations")
    if not isinstance(obs, list) or len(obs) <= _MAX_STORED_OBSERVATIONS:
        return content

    # Stride, never obs[:N]. The list is grouped by POI, so a head slice would
    # keep one venue's cluster and leave the rest of the map empty. Round the
    # stride UP so the sample is already within the cap — rounding down overshoots
    # and the trailing truncation would strip dots off the last POIs.
    # ponytail: uniform stride; switch to per-POI quotas if zoomed-in density matters.
    stride = -(-len(obs) // _MAX_STORED_OBSERVATIONS)
    return {**content, "maid_observations": obs[::stride]}


class RunBusyError(RuntimeError):
    """A live run already exists for this thread (double-submit, second tab)."""


class TooManyRunsError(RuntimeError):
    """Global concurrency cap reached."""


@dataclass
class Run:
    run_id: str
    thread_id: str
    # (seq, event) pairs. Seq is carried explicitly rather than implied by list
    # index so trimming the middle of the buffer cannot shift anyone's cursor.
    events: list[tuple[int, dict]] = field(default_factory=list)
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    task: Optional[asyncio.Task] = None
    cancelled: bool = False
    # Set when the stop came from ANOTHER instance, so teardown leaves the
    # control listener running long enough to acknowledge it.
    remote_cancel: bool = False
    _next_seq: int = 0
    # Events waiting to be mirrored to Redis. A queue drained by ONE pump task
    # (_mirror_pump) rather than a task per event: the replay buffer's ordering
    # is the entire point, and concurrent writers would interleave. `emit` stays
    # synchronous and non-blocking — the producer must never wait on Redis.
    mirror_q: Optional[asyncio.Queue] = None

    @property
    def running(self) -> bool:
        return not self.done.is_set()

    @property
    def last_seq(self) -> int:
        """Seq of the most recent event, or -1 when nothing has been emitted."""
        return self._next_seq - 1

    def emit(self, event: dict) -> None:
        """Buffer an event for replay and fan it out to live subscribers."""
        seq = self._next_seq
        self._next_seq += 1

        stored = event
        if event.get("type") == "map_data":
            stored = {**event, "content": _slim_for_storage("map_data", event.get("content"))}
        self.events.append((seq, stored))
        self._trim()

        for q in list(self.subscribers):
            q.put_nowait((seq, event))  # live subscribers get full fidelity

        if self.mirror_q is not None:
            # The SLIMMED copy, same as the local buffer: a map_data payload can
            # be ~24 MB of observation points, which must not be replayed and
            # certainly must not be pushed to Redis whole.
            self.mirror_q.put_nowait((seq, stored))

    def _trim(self) -> None:
        while len(self.events) > _MAX_BUFFERED_EVENTS:
            for i, (_seq, ev) in enumerate(self.events):
                if ev.get("type") == "thinking":
                    del self.events[i]
                    break
            else:
                # No thinking frames left to sacrifice — drop the oldest frame.
                del self.events[0]


_runs: dict[str, Run] = {}

# Persist coroutines spawned out of a producer's ``finally``. They are deliberately
# detached so a stop request (which cancels the producer task) cannot cancel the
# write that saves the partial turn. Tracked so ``cancel`` can wait for them.
#
# Keyed by thread_id (not one flat set) so stopping thread A never waits on
# thread B's unrelated persist — a flat set meant a busy platform could make
# every Stop press pay for every in-flight write, not just its own.
_persists: dict[str, set[asyncio.Task]] = {}


def track_persist(coro: Awaitable[None], thread_id: str) -> asyncio.Task:
    task = asyncio.create_task(coro)
    bucket = _persists.setdefault(thread_id, set())
    bucket.add(task)

    def _done(t: asyncio.Task) -> None:
        bucket.discard(t)
        if not bucket:
            _persists.pop(thread_id, None)

    task.add_done_callback(_done)
    return task


async def drain_persists(thread_id: str, timeout: float = 15.0) -> None:
    pending = set(_persists.get(thread_id, ()))
    if pending:
        await asyncio.wait(pending, timeout=timeout)


def get_run(thread_id: str) -> Optional[Run]:
    return _runs.get(thread_id)


def is_running(thread_id: str) -> bool:
    run = _runs.get(thread_id)
    return run is not None and run.running


def live_run_count() -> int:
    return sum(1 for r in _runs.values() if r.running)


async def start_run(thread_id: str, producer: Producer) -> Run:
    """Spawn ``producer`` as the background owner of this thread's turn.

    Raises ``RunBusyError`` when a run is already live for the thread — that is
    the double-submit guard (two tabs, a double-clicked widget button) that used
    to let two ``Command(resume=...)`` values race into one interrupt.
    """
    existing = _runs.get(thread_id)
    if existing is not None and existing.running:
        raise RunBusyError(thread_id)
    if live_run_count() >= _MAX_CONCURRENT_RUNS:
        raise TooManyRunsError()

    run = Run(run_id=str(uuid.uuid4()), thread_id=thread_id)

    # The double-submit guard has to hold ACROSS instances, not just within one:
    # two tabs (or a double-clicked widget button) can land on different Cloud
    # Run instances and both pass the local check, racing two
    # `Command(resume=...)` values into one interrupt.
    if not await run_store.claim(thread_id, run.run_id):
        raise RunBusyError(thread_id)

    if run_store.enabled():
        run.mirror_q = asyncio.Queue()
    _runs[thread_id] = run
    await run_store.mark(thread_id, run.run_id, running=True, last_seq=-1)
    run.task = asyncio.create_task(_drive(run, producer), name=f"chat-run:{thread_id}")
    return run


async def _mirror_pump(run: Run) -> None:
    """Drain ``run.mirror_q`` to Redis, in order, until the run is done.

    One pump per run so events reach the mirror in the same sequence a local
    subscriber sees them. It also keeps the run's mirrored keys alive: they carry
    a TTL, and a turn longer than it used to lose its status and its busy claim
    mid-run — a reconnect to another instance then saw "no run", and the
    double-submit guard lapsed. Never raises: a mirror failure must not touch
    the turn it is mirroring — ``run_store`` already swallows and degrades.
    """
    assert run.mirror_q is not None
    last_touch = time.monotonic()
    while True:
        try:
            item = await asyncio.wait_for(run.mirror_q.get(), timeout=_TOUCH_EVERY_S)
        except asyncio.TimeoutError:
            item = False  # a quiet stretch — nothing to append, still re-arm
        if item is None:
            return
        if time.monotonic() - last_touch >= _TOUCH_EVERY_S:
            await run_store.touch(run.thread_id, run.run_id)
            last_touch = time.monotonic()
        if item is False:
            continue
        seq, event = item
        await run_store.append(run.thread_id, seq, event)


async def _cancel_from_remote(run: Run) -> None:
    """The control listener's callback: stop this run for another instance."""
    run.remote_cancel = True
    await _cancel_local(run, timeout=15.0)


async def _drive(run: Run, producer: Producer) -> None:
    mirrored = run.mirror_q is not None
    pump = (
        asyncio.create_task(_mirror_pump(run), name=f"chat-mirror:{run.thread_id}")
        if mirrored else None
    )
    # A stop pressed against another instance arrives on the control channel;
    # the task lives here, so this is where it has to be heard.
    listener = (
        asyncio.create_task(
            run_store.listen_for_cancel(run.thread_id, lambda: _cancel_from_remote(run)),
            name=f"chat-cancel-listener:{run.thread_id}",
        )
        if mirrored else None
    )
    try:
        await producer(run.emit)
    except asyncio.CancelledError:
        run.cancelled = True
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("chat run failed", thread_id=run.thread_id, error=str(exc))
        run.emit({"type": "error", "content": str(exc)})
    finally:
        run.done.set()
        for q in list(run.subscribers):
            q.put_nowait(None)  # release every attached subscriber

        if listener is not None and not run.remote_cancel:
            # A remote stop is still acknowledging from inside the listener;
            # cancelling it then would swallow the ack its requester waits for.
            listener.cancel()

        if pump is not None and run.mirror_q is not None:
            # Let the pump finish what is already queued before telling remote
            # followers the run is over, or a reconnect could miss the last
            # events — which are the ones that matter most (the final
            # assistant_message, a pending_action).
            run.mirror_q.put_nowait(None)
            try:
                await asyncio.wait_for(pump, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
                pump.cancel()
        try:
            await run_store.mark(
                run.thread_id, run.run_id, running=False, last_seq=run.last_seq
            )
            await run_store.release(run.thread_id, run.run_id)
        except Exception as mirror_err:  # noqa: BLE001 — mirroring must not fail a turn
            logger.warning(
                "run mirror teardown failed", thread_id=run.thread_id, error=str(mirror_err)
            )

        try:
            asyncio.create_task(_evict_later(run))
        except RuntimeError:
            # Loop already closing (shutdown drained us) — nothing left to evict from.
            _runs.pop(run.thread_id, None)


async def _evict_later(run: Run) -> None:
    await asyncio.sleep(_RETAIN_SECONDS)
    if _runs.get(run.thread_id) is run:
        del _runs[run.thread_id]


async def subscribe(
    thread_id: str, from_seq: int = 0
) -> AsyncGenerator[tuple[int, dict], None]:
    """Yield ``(seq, event)`` from ``from_seq`` onward: backlog first, then live.

    The queue is registered *before* the backlog is replayed, so an event landing
    mid-replay is buffered rather than missed; the ``seq <= replayed`` filter
    then drops the duplicate.
    """
    run = _runs.get(thread_id)
    if run is None:
        # Not ours. The run may be live on another instance — follow the mirror
        # instead of returning nothing, which is what made a reconnect look like
        # an empty screen at maxScale>1.
        async for item in _subscribe_remote(thread_id, from_seq):
            yield item
        return

    q: asyncio.Queue = asyncio.Queue()
    run.subscribers.add(q)
    try:
        replayed = from_seq - 1
        for seq, event in list(run.events):
            if seq >= from_seq:
                replayed = seq
                yield seq, event

        if not run.running:
            return

        while True:
            item = await q.get()
            if item is None:
                return
            seq, event = item
            if seq <= replayed:
                continue
            replayed = seq
            yield seq, event
    finally:
        run.subscribers.discard(q)


async def _subscribe_remote(
    thread_id: str, from_seq: int
) -> AsyncGenerator[tuple[int, dict], None]:
    """Follow a run owned by a different instance: backlog, then live.

    Subscribe BEFORE replaying, same ordering rule as the local path, so an
    event published mid-replay is buffered rather than missed; the
    ``seq <= replayed`` filter then drops the duplicate.
    """
    meta = await run_store.status(thread_id)
    if meta is None:
        return

    if not meta["running"]:
        # Finished elsewhere — the backlog is the whole story.
        for seq, event in await run_store.backlog(thread_id, from_seq):
            yield seq, event
        return

    # Subscribe BEFORE replaying. `follow_channel` is a generator and would not
    # actually subscribe until its first iteration, so building it and reading
    # the backlog first leaves a window where a published event reaches nobody —
    # which is precisely the "reconnect missed the final message" bug this whole
    # mirror exists to prevent. `open_channel` does the subscribe eagerly.
    pubsub = await run_store.open_channel(thread_id)
    replayed = from_seq - 1
    try:
        for seq, event in await run_store.backlog(thread_id, from_seq):
            if seq > replayed:
                replayed = seq
                yield seq, event
        async for seq, event in run_store.follow_channel(pubsub, from_seq):
            # The backlog and the channel overlap by design; drop the duplicate.
            if seq <= replayed:
                continue
            replayed = seq
            yield seq, event
    finally:
        await run_store.close_channel(pubsub)


async def describe(thread_id: str) -> Optional[dict]:
    """``{"run_id", "running", "last_seq"}`` for a run on THIS instance or any
    other, or None when no run exists anywhere.

    The cross-instance replacement for ``get_run``. The local dict is still the
    fast path and the source of truth for a run we own; the mirror answers for
    one owned elsewhere, which the local-only lookup reported as "no run at all".
    """
    run = _runs.get(thread_id)
    if run is not None:
        return {
            "run_id": run.run_id,
            "running": run.running,
            "last_seq": run.last_seq,
        }
    return await run_store.status(thread_id)


async def is_running_anywhere(thread_id: str) -> bool:
    """Cross-instance form of ``is_running``.

    The local-only version answers "no" for a turn running on another instance,
    which would let a rewind start underneath a live run.
    """
    info = await describe(thread_id)
    return bool(info and info["running"])


async def cancel(thread_id: str, timeout: float = 15.0) -> bool:
    """Stop a live run. Returns False when there was nothing to stop.

    Waits for ``done`` so the caller knows the producer's ``finally`` — which
    persists whatever assistant text was captured before the stop — has already
    committed.

    A run owned by ANOTHER instance is stopped through the mirror: the request
    goes out on that run's control channel and this waits for the owner's
    acknowledgement, which it sends only after its own local cancel (and so the
    persist) has finished — the same promise, kept across instances. The stop
    button, delete-conversation and bulk delete all get this, since all three
    call here.
    """
    run = _runs.get(thread_id)
    if run is None:
        remote = await run_store.status(thread_id)
        if remote and remote["running"]:
            if await run_store.request_cancel(thread_id, timeout=timeout):
                return True
            # The ack didn't arrive in time, but the owning instance may have
            # stopped the run anyway — a slow/lost pubsub message is not the
            # same as "nothing happened". Re-check before reporting NOT_RUNNING,
            # or the caller (cancel_run) skips the un-submit rollback for a stop
            # that actually landed.
            remote_after = await run_store.status(thread_id)
            if remote_after is None:
                return True  # the run entry is gone — it ended
            return not remote_after["running"]
        return False
    return await _cancel_local(run, timeout)


async def _cancel_local(run: Run, timeout: float) -> bool:
    """Stop a run owned by THIS instance and wait until its partial turn is saved.

    Takes the Run itself, not a thread id: the remote-stop callback must stop the
    task it was started for, even if the registry entry has since been evicted —
    looking it up again would miss it and bounce the request back out to Redis.

    Returns False on a timed-out wait — the caller must not promise a commit that
    may not have happened.
    """
    if not run.running or run.task is None:
        return False

    run.cancelled = True
    run.task.cancel()
    try:
        await asyncio.wait_for(run.done.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("chat run cancel timed out", thread_id=run.thread_id)
        return False
    # The producer detaches its persist so cancellation can't kill it; wait for it
    # here so a caller that got a 200 back knows the partial turn is committed.
    await drain_persists(run.thread_id, timeout=timeout)
    return True


async def cancel_all(timeout: float = 10.0) -> None:
    """Shutdown hook — stop every live run so their persists get a chance to run."""
    for thread_id in list(_runs):
        try:
            await cancel(thread_id, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cancel_all failed", thread_id=thread_id, error=str(exc))


__all__ = [
    "Emit",
    "Producer",
    "Run",
    "RunBusyError",
    "TooManyRunsError",
    "_slim_for_storage",
    "cancel",
    "cancel_all",
    "drain_persists",
    "get_run",
    "is_running",
    "live_run_count",
    "start_run",
    "subscribe",
    "track_persist",
]
