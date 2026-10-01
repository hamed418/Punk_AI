"""Simple async rate limiter: bounded concurrency + minimum interval between
calls, shared by a semaphore + a monotonic-clock gate. Good enough to avoid
hammering production Gemini quota; not a token-bucket, no burst credit."""
from __future__ import annotations

import asyncio
import time


class RateLimiter:
    def __init__(self, max_concurrency: int, min_interval_sec: float):
        self._sem = asyncio.Semaphore(max_concurrency)
        self._min_interval = min_interval_sec
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def __aenter__(self) -> "RateLimiter":
        await self._sem.acquire()
        async with self._lock:
            now = time.monotonic()
            wait = self._last_call + self._min_interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()
        return self

    async def __aexit__(self, *exc) -> None:
        self._sem.release()
