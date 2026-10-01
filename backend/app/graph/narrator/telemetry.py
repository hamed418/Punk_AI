"""
graph/narrator/telemetry.py
───────────────────────────
Lightweight per-emission metrics for the narrator.

Logs structured quality signals so regressions are visible without scraping
prose: repair/fallback/cache-hit flags, role, length. Emitted as a single
``thinking`` event (visible in the dev reasoning stream) plus a debug log
line. No external metrics backend dependency — the existing ``usage.py``
tracker already captures token cost per call.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def record(
    writer: Any,
    *,
    role: str,
    cache_hit: bool,
    repaired: bool,
    fell_back: bool,
    char_len: int,
) -> None:
    payload = {
        "role": role,
        "cache_hit": cache_hit,
        "repaired": repaired,
        "fell_back": fell_back,
        "chars": char_len,
    }
    logger.debug("narrator emit %s", payload)
    if writer is not None:
        try:
            writer({"type": "thinking", "content": f"narrator/{role} {payload}"})
        except Exception:
            pass


__all__ = ["record"]
