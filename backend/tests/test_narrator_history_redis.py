"""The narrator's "already told the user" ring must survive a hop to another
Cloud Run instance (process-local ring cold, Redis warm) and must degrade to the
old process-local behaviour when Redis is off or failing."""
from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from app.core import redis as _redis
from app.graph.narrator import beats


class _FakePipe:
    def __init__(self, store):
        self.store, self.ops = store, []

    def rpush(self, k, v):
        self.ops.append(lambda: self.store.setdefault(k, []).append(v))

    def ltrim(self, k, a, b):
        self.ops.append(lambda: self.store.__setitem__(k, self.store[k][a:] if b == -1 else self.store[k]))

    def expire(self, *_):
        pass

    async def execute(self):
        for op in self.ops:
            op()


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, list[str]] = {}

    def pipeline(self):
        return _FakePipe(self.store)

    async def lrange(self, k, a, b):
        return list(self.store.get(k, []))


def _state(mid: str = "m1") -> dict:
    return {"messages": [HumanMessage(content="hi", id=mid)]}


@pytest.fixture
def fake(monkeypatch):
    r = _FakeRedis()
    monkeypatch.setattr(_redis, "redis_enabled", lambda: True)
    monkeypatch.setattr(_redis, "get_client", lambda: r)
    return r


@pytest.mark.asyncio
async def test_history_crosses_instances(fake):
    state = _state()
    await beats.remember(state, "Audience built — 8,400 verified visitors.")
    beats.clear()  # a different instance: cold process ring
    assert beats.recent_history(state) == []
    await beats.load_history(state)
    assert beats.recent_history(state) == ["Audience built — 8,400 verified visitors."]


@pytest.mark.asyncio
async def test_duplicate_line_not_mirrored_twice(fake):
    state = _state()
    await beats.remember(state, "same line")
    await beats.remember(state, "same line")
    assert list(fake.store.values()) == [["same line"]]


@pytest.mark.asyncio
async def test_default_bucket_never_touches_redis(fake):
    state = {"messages": []}  # session_key -> "sess:default", shared by strangers
    await beats.remember(state, "line")
    assert fake.store == {}


@pytest.mark.asyncio
async def test_redis_failure_falls_back_to_process_ring(monkeypatch):
    class _Boom:
        def pipeline(self):
            raise ConnectionError("down")

        async def lrange(self, *_):
            raise ConnectionError("down")

    marked = []
    monkeypatch.setattr(_redis, "redis_enabled", lambda: True)
    monkeypatch.setattr(_redis, "get_client", lambda: _Boom())
    monkeypatch.setattr(_redis, "mark_unavailable", marked.append)
    state = _state("m2")
    await beats.remember(state, "kept locally")
    await beats.load_history(state)
    assert beats.recent_history(state) == ["kept locally"]
    assert marked  # tripped the shared switch instead of raising into the turn
