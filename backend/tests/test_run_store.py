"""
tests/test_run_store.py
───────────────────────
The Redis mirror that lets any Cloud Run instance see — and stop — a chat run
owned by another one (app/modules/chat/run_store.py, runs.py).

An in-memory fake stands in for Redis: just the calls the mirror makes, with
pub/sub fanned out to every subscriber, so two "instances" in one process see
each other's messages exactly as they would through a shared Redis.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict

import pytest

from app.modules.chat import run_store, runs


class _FakePubSub:
    def __init__(self, redis: "_FakeRedis"):
        self.redis = redis
        self.queue: asyncio.Queue = asyncio.Queue()
        self.channels: list[str] = []

    async def subscribe(self, channel: str) -> None:
        self.channels.append(channel)
        self.redis.subscribers[channel].append(self.queue)

    async def listen(self):
        while True:
            yield await self.queue.get()

    async def aclose(self) -> None:
        for channel in self.channels:
            if self.queue in self.redis.subscribers[channel]:
                self.redis.subscribers[channel].remove(self.queue)


class _FakePipeline:
    def __init__(self, redis: "_FakeRedis"):
        self.redis = redis
        self.ops: list = []

    def __getattr__(self, name):
        def _queue(*args, **kwargs):
            self.ops.append((name, args, kwargs))
            return self
        return _queue

    async def execute(self):
        for name, args, kwargs in self.ops:
            await getattr(self.redis, name)(*args, **kwargs)


class _FakeRedis:
    def __init__(self):
        self.kv: dict = {}
        self.hashes: dict = {}
        self.lists: dict = defaultdict(list)
        self.subscribers: dict = defaultdict(list)
        self.expired: list[str] = []

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        return True

    async def get(self, key):
        return self.kv.get(key)

    async def delete(self, key):
        self.kv.pop(key, None)

    async def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update(mapping)

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def expire(self, key, seconds):
        self.expired.append(key)
        return True

    async def publish(self, channel, data):
        for queue in list(self.subscribers[channel]):
            queue.put_nowait({"type": "message", "data": data})
        return len(self.subscribers[channel])

    async def rpush(self, key, value):
        self.lists[key].append(value)

    async def ltrim(self, key, start, end):
        pass

    async def lrange(self, key, start, end):
        return list(self.lists[key])

    def pipeline(self):
        return _FakePipeline(self)

    def pubsub(self):
        return _FakePubSub(self)


@pytest.fixture
def fake_redis(monkeypatch):
    redis = _FakeRedis()

    async def _client():
        return redis

    monkeypatch.setattr(run_store, "enabled", lambda: True)
    monkeypatch.setattr(run_store, "_client", _client)
    monkeypatch.setattr(runs, "_RETAIN_SECONDS", 0)
    return redis


async def _until(predicate, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


async def _sleeper(emit):
    emit({"type": "thinking", "content": "working"})
    await asyncio.sleep(30)


@pytest.mark.asyncio
async def test_a_second_claim_on_a_busy_thread_is_refused(fake_redis):
    """The double-submit guard across instances: two tabs on two instances
    must not race two resume values into one interrupt."""
    assert await run_store.claim("t-claim", "run-a") is True
    assert await run_store.claim("t-claim", "run-b") is False

    await run_store.release("t-claim", "run-b")          # not ours: no effect
    assert await run_store.claim("t-claim", "run-c") is False
    await run_store.release("t-claim", "run-a")
    assert await run_store.claim("t-claim", "run-c") is True


@pytest.mark.asyncio
async def test_a_long_run_keeps_its_status_and_claim_alive(fake_redis, monkeypatch):
    """The mirrored keys carry a TTL. A MAID turn can run longer than it, and
    used to lose its status (a reconnect elsewhere saw "no run") and its busy
    claim (a second submit could start) mid-turn."""
    monkeypatch.setattr(runs, "_TOUCH_EVERY_S", 0.05)
    run = await runs.start_run("t-ttl", _sleeper)
    claim_key = run_store._k("t-ttl", "claim")
    meta_key = run_store._k("t-ttl", "meta")
    try:
        await _until(lambda: claim_key in fake_redis.expired)
        assert fake_redis.expired.count(meta_key) >= 2, "meta re-armed after start"
    finally:
        await runs.cancel("t-ttl")
    assert not run.running


@pytest.mark.asyncio
async def test_a_stop_from_another_instance_stops_the_run(fake_redis):
    """The task lives on one instance and the stop button can be pressed on any.
    The request travels over the control channel, and the requester only hears
    back once the owner's own cancel — and so the partial-turn persist — is done."""
    run = await runs.start_run("t-remote", _sleeper)
    control = run_store._k("t-remote", "control")
    await _until(lambda: fake_redis.subscribers[control])

    acked = await run_store.request_cancel("t-remote", timeout=2.0)

    assert acked is True
    assert run.cancelled and run.remote_cancel
    assert not run.running


@pytest.mark.asyncio
async def test_cancel_reaches_a_run_this_instance_does_not_own(fake_redis):
    """`runs.cancel` is what the stop button, delete-conversation and bulk
    delete call. For a run owned elsewhere it must go through the mirror, not
    report "nothing to stop"."""
    run = await runs.start_run("t-elsewhere", _sleeper)
    control = run_store._k("t-elsewhere", "control")
    await _until(lambda: fake_redis.subscribers[control])

    # Pretend this request landed on a different instance: it has no local run.
    owned_here = runs._runs.pop("t-elsewhere")
    try:
        assert await runs.cancel("t-elsewhere", timeout=2.0) is True
    finally:
        runs._runs.setdefault("t-elsewhere", owned_here)
    assert not run.running


@pytest.mark.asyncio
async def test_an_unanswered_stop_reports_failure(fake_redis):
    """Nobody owns the run (it died with its instance): the caller must hear
    False, not wait forever or claim success."""
    assert await run_store.request_cancel("t-orphan", timeout=0.2) is False


@pytest.mark.asyncio
async def test_without_redis_cancel_is_purely_local(monkeypatch):
    monkeypatch.setattr(run_store, "enabled", lambda: False)
    assert await runs.cancel("t-nothing") is False
    assert await run_store.request_cancel("t-nothing", timeout=0.1) is False
