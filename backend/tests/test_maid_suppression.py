"""``maid_store.suppress`` — the seam for a supplier opt-out/deletion feed
that does not exist yet. ``suppressed_maids`` is empty in every deployment
today; these tests pin the contract the real feed will be wired against.
"""
from unittest.mock import patch

import pytest

from app.services import maid_store


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Db:
    def __init__(self, rows=(), raise_on_execute=False):
        self._rows = rows
        self._raise = raise_on_execute

    async def execute(self, _stmt):
        if self._raise:
            raise RuntimeError("db is down")
        return _Result(self._rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_empty_list_is_a_noop_with_no_db_call():
    with patch.object(maid_store, "AsyncSessionLocal") as session:
        assert await maid_store.suppress([]) == []
        session.assert_not_called()


@pytest.mark.asyncio
async def test_nothing_suppressed_returns_the_list_unfiltered():
    with patch.object(maid_store, "AsyncSessionLocal", return_value=_Db(rows=[])):
        out = await maid_store.suppress(["m1", "m2"])
    assert out == ["m1", "m2"]


@pytest.mark.asyncio
async def test_a_suppressed_maid_is_dropped():
    with patch.object(maid_store, "AsyncSessionLocal", return_value=_Db(rows=[("m2",)])):
        out = await maid_store.suppress(["m1", "m2", "m3"])
    assert out == ["m1", "m3"]


@pytest.mark.asyncio
async def test_every_maid_suppressed_returns_empty():
    with patch.object(
        maid_store, "AsyncSessionLocal", return_value=_Db(rows=[("m1",), ("m2",)]),
    ):
        out = await maid_store.suppress(["m1", "m2"])
    assert out == []


@pytest.mark.asyncio
async def test_a_lookup_failure_fails_open_rather_than_blocking_the_publish():
    """The suppression list is not on the critical path — an outage here must
    never turn into an audience upload failure."""
    with patch.object(maid_store, "AsyncSessionLocal", return_value=_Db(raise_on_execute=True)):
        out = await maid_store.suppress(["m1", "m2"])
    assert out == ["m1", "m2"]
