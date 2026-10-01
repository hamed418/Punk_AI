"""
tests/test_unacast_usage_attribution.py
────────────────────────────────────────
Per-thread / per-user / global attribution for Unacast spend.

`unacast_usage_ledger` answers "how much of this month's quota is gone" but has
no user and no thread on it. The obvious fix — tucking the count into the
token_transactions row the billing path already writes — cannot work:

  * that row is only written when the turn spent LLM tokens (`deduct_tokens`
    early-returns on amount <= 0);
  * `_bill_usage` skips its state write entirely while a subgraph interrupt is
    pending, and a MAID extraction almost always ends at the maid_confirm
    interrupt — i.e. it would be wrong for exactly the turns that spend budget;
  * calls made outside a chat turn have no user at all, so SUM(per-user) could
    never equal the month's real total.

So attribution is captured where the CALL happens (`reconcile_call`), in the
same transaction as the ledger increment. These pin that.
"""
from __future__ import annotations

import uuid

import pytest

# Instantiating ANY model configures every mapper, and CreativeGenerationJob's
# relationship to MediaFile only resolves once every module is imported. Same
# guard the analytics/campaigns repositories and alembic/env.py use.
import app.db.model_registry  # noqa: F401
from app.db.models import UnacastCallLog
from app.graph import unacast_query as uq
from app.graph.usage import api_call_callback, current_turn_identity, turn_identity


class _Ledger:
    """Stand-in for the month's ledger row."""

    def __init__(self):
        self.provisional_reserved = 1
        self.calls_made = 0
        self.requests_made = 0
        self.observations_used = 0


def _fake_db(ledger: _Ledger | None):
    """AsyncSessionLocal stand-in: hands back `ledger` and captures db.add()."""
    added: list = []

    class _Rows:
        def scalar_one_or_none(self):
            return ledger

    class _Tx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *_a):
            return False

    class _DB:
        async def execute(self, *_a, **_k):
            return _Rows()

        def begin(self):
            return _Tx()

        def add(self, obj):
            added.append(obj)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

    return (lambda: _DB()), added


# ── the log row ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_fired_call_is_attributed_to_its_user_and_thread(monkeypatch):
    ledger = _Ledger()
    session, added = _fake_db(ledger)
    monkeypatch.setattr(uq, "AsyncSessionLocal", session)

    user_id = str(uuid.uuid4())
    with turn_identity(user_id, "sess-abc"):
        await uq.reconcile_call(fired=True, observations=500, requests=3, period="2026-09")

    assert len(added) == 1
    row = added[0]
    assert isinstance(row, UnacastCallLog)
    assert row.period == "2026-09"
    assert str(row.user_id) == user_id
    assert row.thread_id == "sess-abc"
    assert row.calls == 1
    assert row.requests == 3
    assert row.observations == 500

    # Same transaction, same `fired` — the two halves must agree.
    assert ledger.calls_made == 1
    assert ledger.requests_made == 3
    assert ledger.observations_used == 500


@pytest.mark.asyncio
async def test_a_released_reservation_logs_nothing(monkeypatch):
    """`fired=False` means the request never reached the vendor (a refused
    concurrency slot). It cost nothing and must not appear anywhere."""
    ledger = _Ledger()
    session, added = _fake_db(ledger)
    monkeypatch.setattr(uq, "AsyncSessionLocal", session)

    with turn_identity(str(uuid.uuid4()), "sess-abc"):
        await uq.reconcile_call(fired=False, period="2026-09")

    assert added == []
    assert ledger.calls_made == 0
    assert ledger.provisional_reserved == 0   # the reservation IS released


@pytest.mark.asyncio
async def test_requests_mirrors_the_ledgers_own_arithmetic(monkeypatch):
    """The ledger floors `requests` at 1; the log must use the identical
    expression or the two counters drift apart over time."""
    ledger = _Ledger()
    session, added = _fake_db(ledger)
    monkeypatch.setattr(uq, "AsyncSessionLocal", session)

    await uq.reconcile_call(fired=True, requests=0, period="2026-09")

    assert added[0].requests == 1
    assert ledger.requests_made == 1


@pytest.mark.asyncio
async def test_a_call_with_no_turn_behind_it_is_still_logged(monkeypatch):
    """A script / the autopilot / a manual run spends real budget. Logging it
    with NULL user is what makes SUM(per-user) + SUM(unattributed) == the
    month's total; dropping the row would make the numbers never reconcile."""
    ledger = _Ledger()
    session, added = _fake_db(ledger)
    monkeypatch.setattr(uq, "AsyncSessionLocal", session)

    assert current_turn_identity() == (None, None)   # no turn open
    await uq.reconcile_call(fired=True, requests=2, period="2026-09")

    assert len(added) == 1
    assert added[0].user_id is None
    assert added[0].thread_id is None
    assert added[0].calls == 1
    assert ledger.calls_made == 1


@pytest.mark.asyncio
async def test_two_calls_in_one_turn_log_two_rows_on_the_same_thread(monkeypatch):
    ledger = _Ledger()
    session, added = _fake_db(ledger)
    monkeypatch.setattr(uq, "AsyncSessionLocal", session)

    with turn_identity(str(uuid.uuid4()), "sess-xyz"):
        await uq.reconcile_call(fired=True, requests=1, period="2026-09")
        await uq.reconcile_call(fired=True, requests=1, period="2026-09")

    assert len(added) == 2
    assert {r.thread_id for r in added} == {"sess-xyz"}
    assert ledger.calls_made == 2


@pytest.mark.asyncio
async def test_src_splits_spend_by_path(monkeypatch):
    ledger = _Ledger()
    session, added = _fake_db(ledger)
    monkeypatch.setattr(uq, "AsyncSessionLocal", session)

    await uq.reconcile_call(fired=True, requests=1, period="2026-09")
    await uq.reconcile_call(fired=True, requests=1, period="2026-09", src="devices")

    assert [r.src for r in added] == [None, "devices"]


@pytest.mark.asyncio
async def test_a_malformed_user_id_does_not_fail_a_paid_call(monkeypatch):
    """The call already happened and already cost budget. Accounting must never
    be able to raise over it — the row lands unattributed instead."""
    ledger = _Ledger()
    session, added = _fake_db(ledger)
    monkeypatch.setattr(uq, "AsyncSessionLocal", session)

    with turn_identity("not-a-uuid", "sess-abc"):
        await uq.reconcile_call(fired=True, requests=1, period="2026-09")

    assert len(added) == 1
    assert added[0].user_id is None
    assert added[0].thread_id == "sess-abc"


@pytest.mark.asyncio
async def test_a_db_error_does_not_propagate_and_leak_the_concurrency_lease(monkeypatch):
    """Both callers (unacast_query.py, unacast_devices.py) run this from a bare
    `finally:` ahead of `release_concurrency_slot(lease)`. An unguarded raise
    here used to skip that release call too — leaking a slot from the shared
    FCFS concurrency pool on top of losing the reservation. Pinned once here
    at the function, so the guarantee holds for both call sites."""
    class _BoomDB:
        async def __aenter__(self):
            raise RuntimeError("db unavailable")

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(uq, "AsyncSessionLocal", lambda: _BoomDB())

    await uq.reconcile_call(fired=True, requests=1, period="2026-09")   # no raise


# ── the convenience view (beside the turn's token cost) ──────────────────────

@pytest.mark.asyncio
async def test_the_turn_accumulator_also_sees_the_call(monkeypatch):
    """Co-location with token usage: the same counts land on the turn's
    token_transactions row. Source of truth is the log table above; this is the
    at-a-glance view."""
    session, _added = _fake_db(_Ledger())
    monkeypatch.setattr(uq, "AsyncSessionLocal", session)

    with api_call_callback() as acc:
        await uq.reconcile_call(fired=True, requests=3, period="2026-09")

    assert acc == {"unacast_calls": 1, "unacast_requests": 3}


@pytest.mark.asyncio
async def test_a_released_reservation_does_not_touch_the_accumulator(monkeypatch):
    session, _added = _fake_db(_Ledger())
    monkeypatch.setattr(uq, "AsyncSessionLocal", session)

    with api_call_callback() as acc:
        await uq.reconcile_call(fired=False, period="2026-09")

    assert acc == {}


@pytest.mark.asyncio
async def test_recording_outside_a_turn_never_raises(monkeypatch):
    """Scripts and the arq worker call this with no accumulator open."""
    session, added = _fake_db(_Ledger())
    monkeypatch.setattr(uq, "AsyncSessionLocal", session)

    await uq.reconcile_call(fired=True, requests=1, period="2026-09")   # no raise
    assert len(added) == 1


# ── the devices path must stay attributed ────────────────────────────────────

def test_the_devices_path_still_reports_through_reconcile_call():
    """Both vendor paths route through reconcile_call — that single choke point
    is what makes one edit cover both. A path that stopped calling it would
    spend budget invisibly (same precedent as
    test_unacast_cost_safety.test_the_ledger_counts_real_requests_not_batches)."""
    import inspect

    from app.graph import unacast_devices

    src = inspect.getsource(unacast_devices)
    assert "reconcile_call(" in src, "the devices path must still reconcile"
    assert 'src="devices"' in src, "and must tag its spend as the devices path"
