"""
app/core/limiter.py
───────────────────
The shared slowapi rate limiter.

Backed by Redis when it is configured, and by an in-process counter otherwise.

That distinction is not cosmetic. The default in-memory storage keeps its counter
**per process**, and this service runs on Cloud Run with ``maxScale=5``, so a
``@limiter.limit("60/minute")`` decorator was really allowing up to 300/minute —
the limit did not limit. slowapi supports a shared store natively via
``storage_uri``; wiring the existing Redis in is the whole fix.

Falling back rather than requiring Redis keeps local dev and the test suite
working unchanged, and keeps a Redis outage from taking rate limiting (and so
every decorated route) down with it.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request  # noqa: F401 — re-exported; routers import it from here

from app.core.config import settings

# `storage_uri=None` is slowapi's own default and selects in-memory storage, so
# the unconfigured path is byte-identical to the previous behaviour.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL or None,
    # slowapi RAISES when its storage errors unless this is on, so a Redis
    # outage turned every @limiter.limit route into a 500. With it, limits fall
    # back to per-process counting until Redis answers again.
    in_memory_fallback_enabled=True,
    # Namespaced like every other key this app writes: one Redis host is shared,
    # and a developer's .env points at it too. See core/redis.py.
    key_prefix=f"{settings.REDIS_KEY_PREFIX}ratelimit",
)
