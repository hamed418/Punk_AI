"""
app/core/maintenance.py
───────────────────────
The scheduled cleanup jobs, as importable coroutines.

``unacast_raw_observations`` holds real advertiser IDs and is cross-campaign, and
``maid_extractions`` keeps raw device IDs for audiences nobody published —
retention that silently does not run is worse than no policy.

**Who runs them.** ``app/worker.py``: an arq cron job on the ``punk-ai-worker``
Cloud Run worker pool. Not an ``asyncio`` loop inside the API service — that runs
with ``cpu-throttling=true`` and ``minScale=0``, so a background task there is
throttled to nothing between requests and then torn down.
``scripts/sweep_unacast_raw_observations.py`` calls these same functions, so
there is exactly one implementation of what a sweep does.

**Why an advisory lock.** A redeploy can briefly run an old and a new worker side
by side, and a manual CLI sweep can overlap the cron. The lock is the same
mechanism ``unacast_query.acquire_concurrency_slot`` uses for the vendor
concurrency gate, on a different key — a losing caller no-ops rather than
double-sweeping.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Awaitable

from sqlalchemy import func, select, text

from app.core.config import settings
from app.db.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# Advisory-lock key for the maintenance sweep. Distinct from
# unacast_query._GATE_LOCK_KEY (8_417_233_901) — they must never collide, so
# both live in comments that name the other.
_MAINTENANCE_LOCK_KEY = 5_512_884_017


async def sweep_raw_observations(*, days: int, confirm: bool) -> dict:
    """Delete cached Unacast pings older than ``days``.

    Coverage rows go in the SAME transaction as the observations they cover: a
    surviving watermark row would mark a POI-day as paid for with no pings behind
    it, and a covered day is never re-bought — so a later extraction would return
    an empty audience for a POI that genuinely has visitors, silently and
    permanently.

    The window is a privacy bound on raw advertiser IDs. It is shorter than the
    history a trend or cadence filter may buy (``maid_history.MAX_HISTORY_DAYS``),
    on purpose: those older days serve the extraction that bought them and are
    re-bought by a later one, rather than kept here for months.
    """
    if days < 1:
        raise ValueError("retention window must be at least 1 day")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_day = cutoff.date()

    async with AsyncSessionLocal() as db:
        counts = (await db.execute(text(
            "SELECT count(*), count(distinct maid) "
            "FROM unacast_raw_observations WHERE observed_at < :cutoff"
        ), {"cutoff": cutoff})).one()
        coverage = (await db.execute(text(
            "SELECT count(*) FROM unacast_fetch_coverage WHERE date < :cutoff_day"
        ), {"cutoff_day": cutoff_day})).scalar_one()

        result = {
            "job": "raw_observations",
            "days": days,
            "cutoff": cutoff_day.isoformat(),
            "observations_matched": counts[0],
            "devices_matched": counts[1],
            "coverage_matched": coverage,
            "deleted": False,
        }
        if not confirm or (not counts[0] and not coverage):
            return result

        async with db.begin():
            obs = (await db.execute(text(
                "DELETE FROM unacast_raw_observations WHERE observed_at < :cutoff"
            ), {"cutoff": cutoff})).rowcount
            cov = (await db.execute(text(
                "DELETE FROM unacast_fetch_coverage WHERE date < :cutoff_day"
            ), {"cutoff_day": cutoff_day})).rowcount

        result.update({"deleted": True, "observations_deleted": obs, "coverage_deleted": cov})
        logger.info(
            "maintenance: swept %d observation(s) and %d coverage row(s) older than %s",
            obs, cov, cutoff_day,
        )
        return result


async def sweep_abandoned_extractions(*, days: int, confirm: bool) -> dict:
    """Clear raw device IDs from extractions nobody came back to.

    The publish path already purges on success; this covers the rows nobody
    returned to. ``updated_at`` is the signal — a live editing session keeps
    re-touching its row.
    """
    from app.services.maid_store import purge_maid_extraction

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT id, maid_count FROM maid_extractions "
            "WHERE purged_at IS NULL AND updated_at < :cutoff"
        ), {"cutoff": cutoff})).fetchall()

    result = {
        "job": "abandoned_extractions",
        "days": days,
        "cutoff": cutoff.isoformat(),
        "matched": len(rows),
        "deleted": False,
    }
    if not confirm or not rows:
        return result

    cleared = 0
    for row in rows:
        if await purge_maid_extraction(str(row[0]), reason="abandoned-row sweep"):
            cleared += 1
    result.update({"deleted": True, "purged": cleared})
    logger.info("maintenance: purged raw MAIDs from %d/%d extraction(s)", cleared, len(rows))
    return result


# name -> (coroutine, default retention days). Adding a job here is all it takes
# to put it on the schedule.
JOBS: dict[str, tuple[Callable[..., Awaitable[dict]], str]] = {
    "raw_observations": (sweep_raw_observations, "UNACAST_RAW_RETENTION_DAYS"),
    "abandoned_extractions": (sweep_abandoned_extractions, "MAID_EXTRACTION_RETENTION_DAYS"),
}


async def run_all(*, confirm: bool = True, only: str | None = None) -> dict:
    """Run every job under one advisory lock.

    A caller that loses the lock returns ``{"skipped": "locked"}`` rather than
    waiting or double-sweeping: the next scheduled run will do the work, and
    these jobs are idempotent anyway.

    One job failing does not stop the others — each reports its own outcome so a
    partial failure is visible in the response rather than hidden by an
    exception.
    """
    started = time.monotonic()
    async with AsyncSessionLocal() as db:
        # Session-scoped, not transaction-scoped: the jobs below open their own
        # transactions, so a pg_advisory_xact_lock here would release at the end
        # of the first one and stop guarding the rest.
        got = (await db.execute(
            select(func.pg_try_advisory_lock(_MAINTENANCE_LOCK_KEY))
        )).scalar_one()
        if not got:
            logger.info("maintenance: another instance holds the lock — skipping")
            return {"skipped": "locked", "jobs": []}

        results: list[dict] = []
        try:
            for name, (job, days_setting) in JOBS.items():
                if only and name != only:
                    continue
                days = int(getattr(settings, days_setting))
                try:
                    results.append(await job(days=days, confirm=confirm))
                except Exception as exc:  # noqa: BLE001 — one job must not stop the rest
                    logger.exception("maintenance job %s failed", name)
                    results.append({"job": name, "error": f"{type(exc).__name__}: {exc}"})
        finally:
            await db.execute(select(func.pg_advisory_unlock(_MAINTENANCE_LOCK_KEY)))

    return {
        "skipped": None,
        "confirm": confirm,
        "duration_s": round(time.monotonic() - started, 2),
        "jobs": results,
        "failed": [r["job"] for r in results if "error" in r],
    }
