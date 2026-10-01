"""
app/core/redis.py
─────────────────
One shared async Redis client, and the single switch that says whether Redis is
in play at all.

**Why this exists.** The backend deliberately had no Redis dependency: the
LangGraph checkpointer is ``AsyncPostgresSaver``, and the Unacast budget and
concurrency gates are Postgres for exactly that reason. That held while the
service was one container.

It is now Cloud Run with ``maxScale=5`` and ``sessionAffinity=false``, so a
process-local dict is invisible to the other four instances. Two things depend on
that visibility and are wrong without it:

  * ``modules/chat/runs.py`` — the registry that lets a refreshed browser
    reattach to a running turn. A reconnect is load-balanced to a random
    instance, so four times out of five it finds nothing and the turn appears to
    vanish. That is the exact failure the module was written to prevent.
  * ``core/limiter.py`` — an in-memory counter per instance means the effective
    rate limit is five times the configured one.

**The rule for every consumer.** Redis here is an *optimisation of visibility*,
never a new way to fail. If it is unconfigured or unreachable, callers must fall
back to their existing in-process behaviour and serve the request. That is the
same discipline ``maid_store.suppress`` already follows for its own non-critical
lookup, and it is what keeps local dev and the test suite working with no Redis
at all.

Keys are namespaced by environment (``settings.REDIS_KEY_PREFIX``) because one
Redis host is shared and a developer's ``.env`` points at it too — without the
prefix, a local run and a deployment would read each other's replay buffers.
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Any = None
_unavailable = False


def redis_enabled() -> bool:
    """Whether Redis is configured AND has not been marked unavailable.

    The single switch every caller checks, so "no Redis" is one branch rather
    than a scatter of try/excepts at each use site.
    """
    return bool(settings.REDIS_URL) and not _unavailable


def key(*parts: str) -> str:
    """Build an environment-namespaced key."""
    return settings.REDIS_KEY_PREFIX + ":".join(str(p) for p in parts)


def get_client() -> Any:
    """The shared client, or None when Redis is not in play.

    Built lazily so importing this module never requires Redis to exist —
    matching how ``UnacastClient`` is constructed only when its token is set.
    """
    global _client
    if not redis_enabled():
        return None
    if _client is None:
        import redis.asyncio as _redis

        _client = _redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            # A request must never hang on Redis. These are deliberately short:
            # falling back to in-process behaviour is always better than making
            # the user wait on a store that is only an optimisation.
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
            health_check_interval=30,
        )
        logger.info(
            "Redis enabled: %s:%s db=%s prefix=%r",
            settings.REDIS_HOST, settings.REDIS_PORT, settings.REDIS_DB,
            settings.REDIS_KEY_PREFIX,
        )
    return _client


def mark_unavailable(exc: BaseException) -> None:
    """Trip the switch after a connection failure.

    Once tripped, callers stop trying and use their in-process path, so a Redis
    outage degrades the service instead of slowing every request down by the
    socket timeout. Reset on the next successful ``ping`` at startup.
    """
    global _unavailable
    if not _unavailable:
        _unavailable = True
        logger.error(
            "Redis marked unavailable (%s: %s) — falling back to in-process "
            "state. Chat replay will not survive a reconnect to another instance.",
            type(exc).__name__, exc,
        )


async def ping() -> bool:
    """Liveness check for startup and /health. Never raises."""
    global _unavailable
    if not settings.REDIS_URL:
        return False
    try:
        client = _client or get_client()
        if client is None:
            return False
        await client.ping()
        if _unavailable:
            _unavailable = False
            logger.info("Redis reachable again — shared state re-enabled")
        return True
    except Exception as exc:  # noqa: BLE001 — a health probe must not raise
        mark_unavailable(exc)
        return False


async def aclose() -> None:
    """Release the pool on shutdown."""
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception as exc:  # noqa: BLE001 — shutdown must not raise
            logger.warning("Redis close failed: %s", exc)
        _client = None


async def get_arq_pool():
    """
    Create an ARQ Redis pool for background jobs.

    Returns None when Redis is disabled/unavailable.
    """
    if not redis_enabled():
        return None

    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        return await create_pool(
            RedisSettings.from_dsn(
                settings.REDIS_URL
            )
        )

    except Exception as exc:
        mark_unavailable(exc)
        return None