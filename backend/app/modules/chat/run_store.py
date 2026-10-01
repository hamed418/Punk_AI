"""
app/modules/chat/run_store.py
─────────────────────────────
The cross-instance mirror behind ``runs.py``.

``runs.py`` keeps a live turn as an ``asyncio.Task`` and treats HTTP requests as
subscribers that attach, replay what they missed, and follow along — so a
refresh or a dropped connection cannot lose the turn. That works perfectly
inside one process.

The service runs on Cloud Run with ``maxScale=5`` and ``sessionAffinity=false``,
so a reconnect is load-balanced to a random instance and four times out of five
lands somewhere that has never heard of the run. The subscriber model silently
does nothing, and the user gets the blank screen the module exists to prevent.

**The task cannot move** — it stays on the instance that started it. What moves
is everything a *subscriber* (or a stop button) needs:

    <p>:runs:<thread>:meta     hash    run_id, running, last_seq
    <p>:runs:<thread>:events   list    JSON "[seq, event]", trimmed + TTL'd
    <p>:runs:<thread>:live     pubsub  each event as it is emitted
    <p>:runs:<thread>:claim    string  SET NX — the cross-instance busy guard
    <p>:runs:<thread>:control  pubsub  stop requests and their acknowledgement

Every function here is **best-effort**. Redis unavailable, unconfigured, or
erroring means fall back to the in-process behaviour: a subscriber on the owning
instance still works, and one elsewhere gets what it would have got without this
module. Nothing here may raise into a request. That is the same discipline
``maid_store.suppress`` follows for its own non-critical lookup.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator, Awaitable, Callable, Optional

from app.core import redis as _redis
from app.core.logging import logger

# Mirrored entries outlive the local ones by a margin: a client reconnecting to
# another instance may arrive slightly after the owning instance has evicted its
# copy, and an expired key there is indistinguishable from "no such run". A live
# run re-arms this through `touch`, so it bounds how long a DEAD run's keys
# linger, never how long a live one can take.
_TTL_SECONDS = 600

# Matches runs._MAX_BUFFERED_EVENTS. Kept as its own constant rather than
# imported to avoid a cycle (runs.py imports this module).
_MAX_EVENTS = 2000


def _k(thread_id: str, suffix: str) -> str:
    return _redis.key("runs", thread_id, suffix)


def enabled() -> bool:
    return _redis.redis_enabled()


async def _client() -> Any:
    return _redis.get_client()


async def claim(thread_id: str, run_id: str) -> bool:
    """Take the cross-instance busy lock for this thread.

    ``RunBusyError`` is the double-submit guard — two tabs, a double-clicked
    widget button — that stops two ``Command(resume=...)`` values racing into one
    interrupt. Checked only against a local dict, it does not hold when the two
    submits land on different instances.

    Returns True when the claim is ours, or when Redis is unavailable: refusing
    to start a turn because the mirror is down would be a worse failure than the
    race it prevents.
    """
    if not enabled():
        return True
    try:
        client = await _client()
        got = await client.set(_k(thread_id, "claim"), run_id, nx=True, ex=_TTL_SECONDS)
        return bool(got)
    except Exception as exc:  # noqa: BLE001
        _redis.mark_unavailable(exc)
        return True


async def release(thread_id: str, run_id: str) -> None:
    """Drop the busy lock, but only if it is still ours.

    A stale release would hand the thread to nobody while a newer run is live.
    """
    if not enabled():
        return
    try:
        client = await _client()
        current = await client.get(_k(thread_id, "claim"))
        if current == run_id:
            await client.delete(_k(thread_id, "claim"))
    except Exception as exc:  # noqa: BLE001
        _redis.mark_unavailable(exc)


async def touch(thread_id: str, run_id: str) -> None:
    """Re-arm a LIVE run's mirrored keys so they cannot expire mid-turn.

    They are set with ``_TTL_SECONDS`` when the run starts, and a turn can
    outlast that — a MAID extraction's vendor calls alone run for minutes. Once
    ``meta`` expired, a reconnect to another instance saw "no run" and got an
    empty screen; once ``claim`` expired, a second submit could start a
    competing run on the same thread. The claim is only re-armed while it is
    still ours.
    """
    if not enabled():
        return
    try:
        client = await _client()
        pipe = client.pipeline()
        pipe.expire(_k(thread_id, "meta"), _TTL_SECONDS)
        pipe.expire(_k(thread_id, "events"), _TTL_SECONDS)
        await pipe.execute()
        if await client.get(_k(thread_id, "claim")) == run_id:
            await client.expire(_k(thread_id, "claim"), _TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        _redis.mark_unavailable(exc)


async def mark(thread_id: str, run_id: str, *, running: bool, last_seq: int = -1) -> None:
    """Publish run status so any instance can answer "is this thread busy"."""
    if not enabled():
        return
    try:
        client = await _client()
        await client.hset(_k(thread_id, "meta"), mapping={
            "run_id": run_id,
            "running": "1" if running else "0",
            "last_seq": str(last_seq),
        })
        await client.expire(_k(thread_id, "meta"), _TTL_SECONDS)
        if not running:
            # Wake every remote follower so it stops waiting on a finished run.
            await client.publish(_k(thread_id, "live"), json.dumps({"__end__": True}))
    except Exception as exc:  # noqa: BLE001
        _redis.mark_unavailable(exc)


async def status(thread_id: str) -> Optional[dict]:
    """``{"run_id", "running", "last_seq"}`` for a run on ANY instance, or None."""
    if not enabled():
        return None
    try:
        client = await _client()
        meta = await client.hgetall(_k(thread_id, "meta"))
        if not meta:
            return None
        return {
            "run_id": meta.get("run_id"),
            "running": meta.get("running") == "1",
            "last_seq": int(meta.get("last_seq") or -1),
        }
    except Exception as exc:  # noqa: BLE001
        _redis.mark_unavailable(exc)
        return None


async def append(thread_id: str, seq: int, event: dict) -> None:
    """Mirror one already-slimmed event, then publish it.

    Called in order from a single pump task (``runs._mirror_pump``) — never
    concurrently for one thread — because the replay buffer's ordering is the
    whole point and concurrent writers would interleave.
    """
    if not enabled():
        return
    try:
        client = await _client()
        payload = json.dumps([seq, event], default=str)
        pipe = client.pipeline()
        pipe.rpush(_k(thread_id, "events"), payload)
        pipe.ltrim(_k(thread_id, "events"), -_MAX_EVENTS, -1)
        pipe.expire(_k(thread_id, "events"), _TTL_SECONDS)
        pipe.publish(_k(thread_id, "live"), payload)
        await pipe.execute()
    except Exception as exc:  # noqa: BLE001
        _redis.mark_unavailable(exc)


async def backlog(thread_id: str, from_seq: int = 0) -> list[tuple[int, dict]]:
    """Mirrored events at or after ``from_seq``."""
    if not enabled():
        return []
    try:
        client = await _client()
        raw = await client.lrange(_k(thread_id, "events"), 0, -1)
    except Exception as exc:  # noqa: BLE001
        _redis.mark_unavailable(exc)
        return []

    out: list[tuple[int, dict]] = []
    for item in raw or []:
        try:
            seq, event = json.loads(item)
        except (ValueError, TypeError):
            continue
        if int(seq) >= from_seq:
            out.append((int(seq), event))
    return out


async def open_channel(thread_id: str, suffix: str = "live"):
    """Subscribe to one of a run's channels and return the pubsub, or None.

    Subscription is deliberately SEPARATE from iteration. ``follow_channel``
    below is an async generator, and a generator does not execute until its
    first ``__anext__`` — so building it and only then reading the backlog would
    subscribe AFTER the replay, losing any event published in between. The local
    path in ``runs.subscribe`` registers its queue before replaying for exactly
    this reason; this is the same ordering, made explicit.
    """
    if not enabled():
        return None
    try:
        client = await _client()
        if client is None:
            return None
        pubsub = client.pubsub()
        await pubsub.subscribe(_k(thread_id, suffix))
        return pubsub
    except Exception as exc:  # noqa: BLE001
        _redis.mark_unavailable(exc)
        return None


async def follow_channel(pubsub, from_seq: int) -> AsyncGenerator[tuple[int, dict], None]:
    """Yield events from an ALREADY-SUBSCRIBED channel, from ``from_seq`` on.

    Ends when the owning instance marks the run finished.
    """
    if pubsub is None:
        return
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                data = json.loads(message["data"])
            except (ValueError, TypeError, KeyError):
                continue
            if isinstance(data, dict) and data.get("__end__"):
                return
            try:
                seq, event = data
            except (ValueError, TypeError):
                continue
            if int(seq) >= from_seq:
                yield int(seq), event
    except Exception as exc:  # noqa: BLE001
        _redis.mark_unavailable(exc)
        logger.warning("run mirror follow ended", error=str(exc))


async def close_channel(pubsub) -> None:
    if pubsub is None:
        return
    try:
        await pubsub.aclose()
    except Exception:  # noqa: BLE001 — teardown must not raise
        pass


async def _control_messages(pubsub) -> AsyncGenerator[dict, None]:
    async for message in pubsub.listen():
        if message.get("type") != "message":
            continue
        try:
            data = json.loads(message["data"])
        except (ValueError, TypeError, KeyError):
            continue
        if isinstance(data, dict):
            yield data


async def request_cancel(thread_id: str, *, timeout: float) -> bool:
    """Ask whichever instance owns this run to stop it, and wait until it has.

    Cancellation has to travel: the ``asyncio.Task`` lives on one instance and
    the stop button can be pressed against any of them. Subscribes BEFORE
    publishing, so the owner's acknowledgement cannot arrive in the gap.

    Returns True only once the owner acknowledges — which it does after its own
    local cancel, and so the partial-turn persist, has finished. False when
    Redis is off or nobody answered within ``timeout``.
    """
    pubsub = await open_channel(thread_id, "control")
    if pubsub is None:
        return False
    try:
        client = await _client()
        await client.publish(_k(thread_id, "control"), json.dumps({"action": "cancel"}))

        async def _acked() -> bool:
            async for data in _control_messages(pubsub):
                if data.get("action") == "cancelled":
                    return True
            return False

        return await asyncio.wait_for(_acked(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("remote run cancel was not acknowledged", thread_id=thread_id)
        return False
    except Exception as exc:  # noqa: BLE001
        _redis.mark_unavailable(exc)
        return False
    finally:
        await close_channel(pubsub)


async def listen_for_cancel(
    thread_id: str, on_cancel: Callable[[], Awaitable[None]]
) -> None:
    """Run on the OWNING instance for the life of a run: when another instance
    asks this run to stop, call ``on_cancel`` and then acknowledge.

    The acknowledgement is published only after ``on_cancel`` returns, so the
    requester learns the partial turn is already persisted — exactly what a
    local ``runs.cancel`` promises. ``runs._drive`` cancels this listener when
    the run ends without a remote stop.
    """
    pubsub = await open_channel(thread_id, "control")
    if pubsub is None:
        return
    try:
        async for data in _control_messages(pubsub):
            if data.get("action") != "cancel":
                continue
            await on_cancel()
            client = await _client()
            await client.publish(_k(thread_id, "control"), json.dumps({"action": "cancelled"}))
            return
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        _redis.mark_unavailable(exc)
        logger.warning("run cancel listener ended", thread_id=thread_id, error=str(exc))
    finally:
        await close_channel(pubsub)
