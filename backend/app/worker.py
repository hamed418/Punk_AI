"""
app/worker.py
─────────────
The arq worker: scheduled jobs that must run whether or not anyone is using the
API.

Runs on the ``punk-ai-worker`` Cloud Run worker pool — one fixed instance, the
same image as the API, started with ``arq app.worker.WorkerSettings``. A worker
pool rather than a service because arq serves no HTTP port; not a loop inside the
API because that service only gets CPU while a request is in flight. See
docs/maid_retention_runbook.md.

Locally::

    cd backend && .venv/Scripts/arq app.worker.WorkerSettings

Do not leave that running: a local ``.env`` points at the shared database, so a
local worker sweeps it at 04:00 UTC exactly like the deployed one.
"""
from __future__ import annotations
from app.workers.signup_worker import process_signup

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.maintenance import run_all

if not settings.REDIS_HOST:
    raise RuntimeError("REDIS_HOST is not set — the arq worker has no queue to run on.")


async def retention(ctx: dict) -> dict:
    """Both retention sweeps, under the maintenance advisory lock."""
    return await run_all(confirm=True)


class WorkerSettings:
    # redis_settings = RedisSettings(
    #     host=settings.REDIS_HOST,
    #     port=settings.REDIS_PORT,
    #     password=settings.REDIS_PASSWORD or None,
    #     database=settings.REDIS_DB,
    # )
    # # Namespaced by environment: local dev and production share one Redis host,
    # # and two workers on one queue would dedupe each other's cron runs.
    print(" ========== STARTING ARQ WORKER ==========" )
    functions = [
        process_signup,
    ]

    redis_settings = RedisSettings.from_dsn(
        settings.REDIS_URL
    )

    max_jobs = 3

    queue_name = f"{settings.REDIS_KEY_PREFIX}arq:queue"
    cron_jobs = [cron(retention, hour=4, minute=0, timeout=1800)]
