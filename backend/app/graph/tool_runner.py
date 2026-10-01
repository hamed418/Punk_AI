"""
graph/tool_runner.py
────────────────────
Thin wrapper around LangChain @tool .ainvoke() that adds timing, structured
logging, and graceful failure handling.

Usage::

    result, log_entry = await call_tool(
        geocode_location,
        {"location_name": "Montreal"},
        writer=writer,
        node_name="geo_execute",
    )
    tool_log.append(log_entry)
    if result:
        ...  # happy path

Returns (None, error_entry) instead of raising on failure, so callers never
need individual try/except blocks around tool calls.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


async def call_tool(
    tool: Any,
    args: dict,
    *,
    writer: Any,
    node_name: str,
    max_attempts: int = 1,
) -> tuple[Any | None, dict]:
    """Invoke a LangChain @tool with timing, retry, and structured error logging.

    HTTP-level retry is already handled inside each tool via _with_retry.
    Pass max_attempts=1 (default) for tools that self-retry; increase only for
    tools without internal retry (LLM-based tools).

    Returns:
        (result, log_entry) — result is None on total failure.
    """
    tool_name = getattr(tool, "name", repr(tool))
    start = time.monotonic()
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            result = await tool.ainvoke(args)
            duration_ms = (time.monotonic() - start) * 1000
            return result, {
                "tool": tool_name,
                "args": args,
                "status": "ok",
                "error_msg": None,
                "attempts": attempt,
                "duration_ms": round(duration_ms, 1),
                "node": node_name,
            }
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "call_tool %s attempt %d/%d failed: %s",
                tool_name, attempt, max_attempts, exc,
            )
            if attempt < max_attempts:
                await asyncio.sleep(2.0 ** (attempt - 1))  # 1s, 2s, 4s …

    duration_ms = (time.monotonic() - start) * 1000
    error_msg = str(last_exc)
    entry = {
        "tool": tool_name,
        "args": args,
        "status": "error",
        "error_msg": error_msg,
        "attempts": max_attempts,
        "duration_ms": round(duration_ms, 1),
        "node": node_name,
    }
    if writer:
        writer({"type": "thinking", "content": f"[{tool_name}] failed after {max_attempts} attempt(s): {error_msg}"})
    logger.error("call_tool %s failed after %d attempt(s): %s", tool_name, max_attempts, last_exc)
    return None, entry
