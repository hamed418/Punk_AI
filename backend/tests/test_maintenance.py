"""
tests/test_maintenance.py
─────────────────────────
Scheduled retention: the jobs, the advisory lock, dry-run safety, and the arq
worker that runs them.

Retention that silently does not run is worse than no policy —
`unacast_raw_observations` holds real advertiser IDs. It runs as an arq cron job
on the punk-ai-worker Cloud Run worker pool (app/worker.py), not inside the API
service, which only gets CPU while a request is in flight.
"""
from __future__ import annotations

import asyncio
import importlib
import sys

import pytest
import pytest_asyncio

from app.core import maintenance


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine():
    """Return the SQLAlchemy pool to the test's own event loop.

    The async engine binds its connection pool to whichever loop first used it,
    and pytest-asyncio gives every test a fresh loop — so a connection opened in
    test one is unusable in test two ("Event loop is closed"). Disposed on the
    way IN as well as out: an earlier test file may already have created it.
    """
    from app.db.database import engine

    await engine.dispose()
    yield
    await engine.dispose()


# ── dry run is the safe default for the CLI, and honoured everywhere ─────────

@pytest.mark.asyncio
async def test_a_dry_run_deletes_nothing():
    result = await maintenance.run_all(confirm=False)
    assert result["skipped"] is None
    assert result["confirm"] is False
    for job in result["jobs"]:
        assert job.get("deleted") is False, job


@pytest.mark.asyncio
async def test_every_registered_job_runs():
    result = await maintenance.run_all(confirm=False)
    assert {j["job"] for j in result["jobs"]} == set(maintenance.JOBS)


@pytest.mark.asyncio
async def test_only_runs_a_single_job():
    result = await maintenance.run_all(confirm=False, only="raw_observations")
    assert [j["job"] for j in result["jobs"]] == ["raw_observations"]


@pytest.mark.asyncio
async def test_a_zero_day_window_is_refused():
    """`--days 0` would delete the entire cache."""
    with pytest.raises(ValueError):
        await maintenance.sweep_raw_observations(days=0, confirm=True)


# ── the advisory lock ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_runs_do_not_both_sweep():
    """A redeploy briefly overlapping two workers, or a manual CLI sweep during
    the cron, must not double-sweep. The loser no-ops."""
    a, b = await asyncio.gather(
        maintenance.run_all(confirm=False),
        maintenance.run_all(confirm=False),
    )
    skipped = [r for r in (a, b) if r["skipped"] == "locked"]
    ran = [r for r in (a, b) if r["skipped"] is None]
    assert len(skipped) == 1 and len(ran) == 1, (a["skipped"], b["skipped"])


@pytest.mark.asyncio
async def test_the_lock_is_released_for_the_next_run():
    """A held-forever lock would silently stop retention for good."""
    await maintenance.run_all(confirm=False)
    second = await maintenance.run_all(confirm=False)
    assert second["skipped"] is None


def test_the_lock_key_cannot_collide_with_the_unacast_gate():
    """Both use pg advisory locks on the same database; a shared key would make
    a retention sweep block vendor calls, or worse, silently share a slot."""
    from app.graph.unacast_query import _GATE_LOCK_KEY

    assert maintenance._MAINTENANCE_LOCK_KEY != _GATE_LOCK_KEY


# ── one job failing must not hide the others ────────────────────────────────

@pytest.mark.asyncio
async def test_a_failing_job_is_reported_not_swallowed(monkeypatch):
    async def boom(**_kw):
        raise RuntimeError("db exploded")

    monkeypatch.setitem(
        maintenance.JOBS, "raw_observations", (boom, "UNACAST_RAW_RETENTION_DAYS")
    )
    result = await maintenance.run_all(confirm=False)

    assert "raw_observations" in result["failed"]
    failed = next(j for j in result["jobs"] if j["job"] == "raw_observations")
    assert "db exploded" in failed["error"]
    # The other job still ran — a partial failure must stay visible, not abort.
    assert any(j["job"] == "abandoned_extractions" for j in result["jobs"])


# ── the arq worker ──────────────────────────────────────────────────────────

def _import_worker():
    sys.modules.pop("app.worker", None)
    return importlib.import_module("app.worker")


def test_the_worker_runs_retention_daily_on_a_namespaced_queue(monkeypatch):
    """The worker pool is what actually runs retention. Its queue carries the
    environment prefix because local dev and production share one Redis host,
    and two workers on one queue would dedupe each other's cron runs."""
    from app.core import config

    monkeypatch.setattr(config.settings, "REDIS_HOST", "redis.example", raising=False)
    try:
        worker = _import_worker()
        assert [job.name for job in worker.WorkerSettings.cron_jobs] == ["cron:retention"]
        assert worker.WorkerSettings.queue_name == f"{config.settings.REDIS_KEY_PREFIX}arq:queue"
        assert worker.WorkerSettings.queue_name.startswith("punk:")
        assert worker.WorkerSettings.redis_settings.host == "redis.example"
    finally:
        sys.modules.pop("app.worker", None)


def test_the_worker_refuses_to_start_without_redis(monkeypatch):
    """An arq worker with no Redis has no queue; failing at import names the
    problem instead of a connection error to an empty host."""
    from app.core import config

    monkeypatch.setattr(config.settings, "REDIS_HOST", "", raising=False)
    try:
        with pytest.raises(RuntimeError, match="REDIS_HOST"):
            _import_worker()
    finally:
        sys.modules.pop("app.worker", None)


def test_the_retention_job_confirms_its_deletes(monkeypatch):
    """A cron job that only dry-runs would read as retention while deleting
    nothing."""
    from app.core import config

    monkeypatch.setattr(config.settings, "REDIS_HOST", "redis.example", raising=False)
    captured: dict = {}

    async def _fake_run_all(**kwargs):
        captured.update(kwargs)
        return {"jobs": []}

    try:
        worker = _import_worker()
        monkeypatch.setattr(worker, "run_all", _fake_run_all)
        asyncio.run(worker.retention({}))
        assert captured == {"confirm": True}
    finally:
        sys.modules.pop("app.worker", None)
