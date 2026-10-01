"""
graph/narrator
──────────────
Unified, typed response generator for Punk — "one mind per screen" (Narrator v3).

The narrator no longer generates a separate message per conversational moment.
Each call site records a **beat** (a structured intent — what happened + the
real facts it carries) into a turn-scoped buffer (:mod:`beats`); the buffer is
drained and woven into ONE coherent, conversational message by
:func:`composer.flush_narration` right before the graph pauses (every
``interrupt()`` and at ``builder_finalize``). This is what makes a turn read as
one voice that explains what Punk is doing and showcases the work — instead of
three independently-generated lines stacked with blank lines.

Public surface:
  • :func:`narrate` — back-compat shim: maps a legacy :class:`Utterance` to a
    beat ``add_beat`` call. Returns an (empty-text) :class:`NarratorResult`; the
    real text is produced later by the flush.
  • :func:`narrate_batch` — same, for several utterances sharing a turn.
  • :func:`flush_narration` / :func:`compose_message` — produce the composed
    message (emit via writer / return text).
  • :func:`add_beat`, :func:`build_pack` — direct beat + grounding helpers.

The package imports with zero side effects (no LLM, no API key); ``narrate``
and the flush never raise — they fall back to deterministic beat text.
"""

from __future__ import annotations

from typing import Any, Optional

from app.graph.narrator.beats import (
    add_beat,
    clear as clear_beats,
    drain,
    load_history,
    peek,
    recent_history,
)
from app.graph.narrator.composer import compose_message, flush_narration
from app.graph.narrator.grounding import build_pack
from app.graph.narrator.types import NarratorResult, Utterance

# Legacy role → beat kind. The role used to select a prompt template + critic
# gate; now it only tags the beat so the composer knows how to weave it.
_ROLE_TO_KIND: dict[str, str] = {
    "milestone": "reveal",
    "stage_open": "stage",
    "handoff": "handoff",
    "step_frame": "framing",
    "step_reframe": "reframe",
    "edit_ack": "edit",
    "sidebar_answer": "answer",
    "auto_advance": "auto_fill",
    "failure": "failure",
    "chatbot": "answer",
    "locked_refusal": "answer",
}


async def narrate(
    utterance: Utterance,
    state: Any,
    writer: Any,
    *,
    pack: Optional[Any] = None,  # accepted for signature compat; unused
) -> NarratorResult:
    """Record this utterance as a beat. The text is composed later, at flush.

    Kept async + same signature so the many existing call sites need no change.
    Returns an empty-text NarratorResult (no per-call cache_update — caching now
    happens once per turn in the composer).
    """
    kind = _ROLE_TO_KIND.get(utterance.role, "reveal")
    facts = dict(utterance.facts or {})
    add_beat(state, kind, facts, fallback=utterance.fallback)
    return NarratorResult(text="")


async def narrate_batch(
    utterances: list[Utterance],
    state: Any,
    writer: Any,
) -> list[NarratorResult]:
    """Record several utterances as beats in order (shared turn buffer)."""
    return [await narrate(u, state, writer) for u in utterances]


__all__ = [
    "narrate",
    "narrate_batch",
    "flush_narration",
    "compose_message",
    "add_beat",
    "drain",
    "peek",
    "recent_history",
    "load_history",
    "clear_beats",
    "build_pack",
]
