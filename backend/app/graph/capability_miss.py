"""
graph/capability_miss.py
─────────────────────────
The queue of what real users asked that Punk could not do — logged, not
guessed at.

Every place the resume flow gives up on a piece of what the user said
(an unrecognised edit field, an edit that was acked then had nowhere to
land, a selection clause with no key to express it, a classification too
uncertain to act on) used to end at a bare ``logger.warning`` with no
consistent shape and no way to ask later "what are people actually asking
for that we don't support yet?" — which is exactly the question behind
the "you only build for the cases I give you" complaint this module exists
to answer differently: stop guessing the next case, log the ones that
actually happened, then build from evidence.

No DB table, no dashboard — one structured log line per miss. The existing
log shipping makes it a queryable field (``kind``) the moment anyone needs
it; add storage when someone actually runs that query and asks for a chart,
not before.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal, Optional

logger = logging.getLogger("app.capability_miss")

Kind = Literal[
    "unknown_field", "dropped_edit", "unsupported_selection", "low_confidence",
    # A request the user made that no setting or tool can do — the weekly list
    # of what to build next (the knob registry's growth queue).
    "unsupported_request",
]

_UTTERANCE_MAX = 300


def record(
    kind: Kind,
    *,
    step_key: str,
    field: Optional[str] = None,
    detail: str,
    utterance: str = "",
    writer: Any = None,
) -> None:
    """Log one capability miss. ``writer`` is optional (only some call sites
    have one in scope, same as narrator/telemetry.record) — when given, also
    emits a ``thinking`` event so it shows up in the dev reasoning stream
    without needing to tail logs.
    """
    payload = {
        "kind": kind,
        "step_key": step_key,
        "field": field,
        "detail": detail,
        "utterance": (utterance or "")[:_UTTERANCE_MAX],
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    logger.warning("capability_miss %s", json.dumps(payload, default=str, ensure_ascii=False))
    if writer is not None:
        try:
            writer({"type": "thinking", "content": f"capability_miss/{kind} {payload}"})
        except Exception:
            pass


__all__ = ["Kind", "record"]
