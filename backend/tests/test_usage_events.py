"""
tests/test_usage_events.py
───────────────────────────
`usage_events` is the SQL-queryable record `_bill_usage` cannot provide:

  * it skips its AgentState write entirely while a subgraph interrupt is
    pending, and a MAID extraction almost always ends at one — so Google Maps /
    grounding calls made on that turn used to vanish from every store;
  * `token_transactions` is only written when the user HAD balance — a 402
    from `TokenService.deduct_tokens` used to leave real Gemini spend with no
    complete record.

`flush_usage_events` writes unconditionally, on its own session, and never
raises — these pin exactly that.
"""
from __future__ import annotations

import uuid

import pytest

# Instantiating ANY model configures every mapper — same guard the analytics/
# campaigns repositories, alembic/env.py, and test_unacast_usage_attribution.py
# all use.
import app.db.model_registry  # noqa: F401
from app.db.models import UsageEvent
from app.graph import usage as usage_mod
from app.graph.usage import compute_cost, flush_usage_events


class _UsageCb:
    """Stand-in for LangChain's get_usage_metadata_callback() context object."""
    def __init__(self, usage_metadata: dict):
        self.usage_metadata = usage_metadata


def _fake_db(raise_on_commit: bool = False):
    """AsyncSessionLocal stand-in: captures add_all(), no real database."""
    added: list = []

    class _DB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        def add_all(self, objs):
            added.extend(objs)

        async def commit(self):
            if raise_on_commit:
                raise RuntimeError("boom")

    return (lambda: _DB()), added


@pytest.mark.asyncio
async def test_api_calls_are_written_even_when_no_tokens_were_spent(monkeypatch):
    """The interrupted-turn hole: a turn that made Places/geocoding calls but
    spent zero LLM tokens (common — a tool node ran with no chat turn behind
    it) must still land a durable row."""
    session, added = _fake_db()
    monkeypatch.setattr("app.db.database.AsyncSessionLocal", session)

    await flush_usage_events(
        user_id=str(uuid.uuid4()), thread_id="sess-1",
        usage_cb=_UsageCb({}), api_acc={"places_text_search": 7},
    )

    assert len(added) == 1
    row = added[0]
    assert isinstance(row, UsageEvent)
    assert row.kind == "google_maps"
    assert row.api == "places_text_search"
    assert row.quantity == 7
    assert row.cost_usd is None


@pytest.mark.asyncio
async def test_unacast_keys_are_skipped_unacast_call_log_owns_them(monkeypatch):
    """unacast_call_log already records these transactionally with the budget
    ledger (unacast_query.reconcile_call) — writing them here too would be a
    second writer with no reconciling reader."""
    session, added = _fake_db()
    monkeypatch.setattr("app.db.database.AsyncSessionLocal", session)

    await flush_usage_events(
        user_id=str(uuid.uuid4()), thread_id="sess-1",
        api_acc={"unacast_calls": 1, "unacast_requests": 3, "geocoding": 2},
    )

    assert len(added) == 1
    assert added[0].api == "geocoding"


@pytest.mark.asyncio
async def test_grounding_prefixed_keys_get_their_own_kind(monkeypatch):
    session, added = _fake_db()
    monkeypatch.setattr("app.db.database.AsyncSessionLocal", session)

    await flush_usage_events(
        user_id=str(uuid.uuid4()), thread_id="sess-1",
        api_acc={"grounding_search": 2, "grounding_maps": 1, "geocoding": 1},
    )

    by_api = {r.api: r.kind for r in added}
    assert by_api["grounding_search"] == "grounding"
    assert by_api["grounding_maps"] == "grounding"
    assert by_api["geocoding"] == "google_maps"


@pytest.mark.asyncio
async def test_token_rows_carry_cost_and_the_input_output_thinking_split(monkeypatch):
    session, added = _fake_db()
    monkeypatch.setattr("app.db.database.AsyncSessionLocal", session)

    await flush_usage_events(
        user_id=str(uuid.uuid4()), thread_id="sess-1",
        usage_cb=_UsageCb({
            "gemini-2.5-flash": {
                "input_tokens": 100, "output_tokens": 50, "total_tokens": 150,
                "output_token_details": {"reasoning": 20},
            },
        }),
    )

    assert len(added) == 1
    row = added[0]
    assert row.kind == "llm_tokens"
    assert row.api == "gemini-2.5-flash"
    assert row.quantity == 150
    assert row.detail == {"in": 100, "out": 50, "think": 20}
    # Must not drift from _bill_usage's own arithmetic — same helper, same inputs.
    assert row.cost_usd == round(compute_cost(100, 50, 20, "gemini-2.5-flash"), 8)


@pytest.mark.asyncio
async def test_grounding_tokens_merge_into_the_same_models_token_row(monkeypatch):
    session, added = _fake_db()
    monkeypatch.setattr("app.db.database.AsyncSessionLocal", session)

    await flush_usage_events(
        user_id=str(uuid.uuid4()), thread_id="sess-1",
        usage_cb=_UsageCb({
            "gemini-2.5-flash": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        }),
        grounding_acc=[
            {"model": "gemini-2.5-flash", "input_tokens": 10, "output_tokens": 5,
             "thinking_tokens": 0, "total_tokens": 15},
        ],
    )

    token_rows = [r for r in added if r.kind == "llm_tokens"]
    assert len(token_rows) == 1
    assert token_rows[0].quantity == 100 + 50 + 10 + 5


@pytest.mark.asyncio
async def test_a_db_failure_is_swallowed_telemetry_must_not_fail_a_turn(monkeypatch):
    session, _added = _fake_db(raise_on_commit=True)
    monkeypatch.setattr("app.db.database.AsyncSessionLocal", session)

    # Must not raise.
    await flush_usage_events(
        user_id=str(uuid.uuid4()), thread_id="sess-1",
        api_acc={"geocoding": 1},
    )


@pytest.mark.asyncio
async def test_no_usage_opens_no_session(monkeypatch):
    calls = []
    monkeypatch.setattr("app.db.database.AsyncSessionLocal", lambda: calls.append(1))

    await flush_usage_events(user_id=str(uuid.uuid4()), thread_id="sess-1")

    assert calls == []
