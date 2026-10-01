"""
graph/narrator/types.py
────────────────────────
Typed contracts for the unified response generator (Narrator v3 — the
"one mind per screen" composer, see :mod:`narrator.composer`).

Every user-visible string Punk emits — wizard step framing, milestone
reveals, handoffs, edit acks, failures, the chatbot's clarify ack — is
described by one :class:`Utterance`. Call sites hand this to ``narrate``,
which files it as a beat (:mod:`narrator.beats`); the beats are woven into
ONE message by :func:`composer.flush_narration` at the next graph pause.

Nothing here performs IO or LLM calls — pure data definitions so the module
imports with zero side effects and no API key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

# ── Roles ─────────────────────────────────────────────────────────────────────
#
# One role per distinct conversational moment. The role tags the beat kind the
# composer weaves it as (see narrator/__init__.py's _ROLE_TO_KIND); it no
# longer selects a prompt template or critic gate — the v3 composer has one
# prompt for the whole turn, not one per role.

Role = Literal[
    "stage_open",      # entering a wizard / stage (narration, no interrupt to follow)
    "step_frame",      # conversational intro BEFORE an interrupt widget (legacy: wizard_ask)
    "step_reframe",    # off-path resume loop, iteration >= 1 (legacy: silent re-widget)
    "milestone",       # result reveal / search done / plan drafted (legacy: wizard_milestone_narrate)
    "sidebar_answer",  # query-lane inline answer mid-wizard (legacy: wizard_sidebar_answer)
    "edit_ack",        # edit-lane confirmation (legacy: wizard_narrate edit echoes)
    "auto_advance",    # high-confidence prefill auto-fill notice
    "handoff",         # between-wizard transition (legacy: chatbot four-beat prose)
    "failure",         # wizard_failure explanation
    "locked_refusal",  # cross-wizard edit refused (completed-wizard lock)
    "chatbot",         # supervisor → chatbot clarify ack
]

Tone = Literal["confident", "apologetic", "celebratory", "neutral"]

CacheScope = Literal["session", "global", "none"]


# ── Grounding ──────────────────────────────────────────────────────────────────


@dataclass
class GroundingPack:
    """Structured snapshot of the live session, fed to the narrator so it can
    cite real values by key instead of being handed a pre-truncated string.

    Built by :func:`narrator.grounding.build_pack`. Unlike the legacy
    ``_session_summary`` (which flattened + truncated lists to 2–3 items), this
    keeps the full data; the composer decides what to surface, and
    counts/names are never silently lost.
    """

    business: dict[str, Any] = field(default_factory=dict)
    audience: dict[str, Any] = field(default_factory=dict)
    geo: dict[str, Any] = field(default_factory=dict)
    maid: dict[str, Any] = field(default_factory=dict)
    campaign: dict[str, Any] = field(default_factory=dict)
    media: dict[str, Any] = field(default_factory=dict)

    # Rich, place-specific signals computed from ``geo_data.targetable_pois`` so
    # the composer can SHOWCASE the work — name which spots/brands the AI is
    # targeting and what's special about them — instead of reciting a bare
    # count. Bounded (top-N / sample) so a 200-POI run stays scannable; the
    # composer is trusted to pick what to surface. Empty when no POIs found yet.
    #   highlights = {
    #     "top_brands":      [["Starbucks", 6], ["Tim Hortons", 5], …],   # name → count
    #     "sample_places":   ["Starbucks Downtown", "Tim Hortons #42", …], # real names
    #     "places_by_region":{"Montreal": ["…", "…"], "Laval": [...]},
    #     "event_names":     ["Osheaga"], "event_dates": ["2026-08-01 → 2026-08-03"],
    #     "top_rated":       [["Gym X", 4.7, 812], …],  # name, stars, review count
    #     "rating_coverage": [41, 47],                   # rated / total — hedge below 1.0
    #   }
    highlights: dict[str, Any] = field(default_factory=dict)

    # The last N user-facing lines already emitted this session, most-recent
    # last. Surfaced in the prompt (NOT in ``as_prompt_dict``, so it never
    # enters the replay cache fingerprint) to suppress repeated openers and let
    # the narrator build a thread instead of restarting cold each turn.
    history: list[str] = field(default_factory=list)

    # The human's latest turn, distilled so the composer can RESPOND to them
    # (mirror their words, answer an embedded question) and adapt tone + length.
    #   user_turn = {"phrase": "...", "embedded_ask": "...|None",
    #                "mood": "neutral|frustrated|confused|eager",
    #                "engagement": "terse|normal|engaged"}
    user_turn: dict[str, Any] = field(default_factory=dict)

    # Soft orientation: where the user is in the build pipeline, for an optional
    # "almost there" cue. {"index": int, "total": int, "phase_label": str}.
    progress: dict[str, Any] = field(default_factory=dict)

    # Explicitly flagged gaps the narrator may acknowledge (e.g. unresolved
    # locations, zero MAID result).
    open_questions: list[str] = field(default_factory=list)

    # What ACTUALLY changed in state this turn (from `beats.drain_changes`) —
    # {"applied": [...], "heard_not_applied": [...], "deviations": [...],
    # "unsupported": [...]}. The composer's ONLY license to say something was
    # added/removed/changed/updated is an entry in `applied`; everything else
    # here is a fact the composer must state as heard-not-done, a deviation,
    # or a plain "can't do that". Replaces a prompt sentence asking the model
    # not to lie with a closed list it can check against.
    changes: dict[str, list[str]] = field(default_factory=dict)

    def is_empty(self) -> bool:
        """True when no business context has been collected yet (cold start)."""
        return not any(
            (self.business, self.audience, self.geo, self.maid, self.campaign)
        )

    def as_prompt_dict(self) -> dict[str, Any]:
        """Serialisable view fed to the prompt builder. Drops empty sections so
        the model is not distracted by `{}` placeholders."""
        out: dict[str, Any] = {}
        for key in ("business", "audience", "geo", "maid", "campaign", "media", "highlights"):
            section = getattr(self, key)
            if section:
                out[key] = section
        if self.user_turn:
            out["user_turn"] = self.user_turn
        if self.progress:
            out["progress"] = self.progress
        if self.open_questions:
            out["open_questions"] = self.open_questions
        if self.changes and any(self.changes.values()):
            out["changes"] = self.changes
        return out


# ── Utterance request ───────────────────────────────────────────────────────────


@dataclass
class Utterance:
    """A request to record one user-visible beat.

    Callers build this and hand it to ``narrator.narrate``. The role tags
    which beat kind it becomes; the remaining fields tune grounding and
    length for this specific emission.
    """

    role: Role

    # Concrete grounding values for THIS emission (e.g. {"poi_count": 12,
    # "poi_brand": "Starbucks"}). Merged with the GroundingPack at prompt time;
    # also forms the cache key.
    facts: dict[str, Any] = field(default_factory=dict)

    # Extra jargon / phrasing this role must avoid, on top of the global ban.
    forbidden_terms: list[str] = field(default_factory=list)

    max_chars: int = 600
    tone: Tone = "neutral"
    why_required: bool = True

    # Cache scope override. ``none`` forces a fresh generation (rare — used for
    # genuinely one-off content). Defaults to per-role policy when None.
    cache_scope: Optional[CacheScope] = None

    # Deterministic fallback text emitted if live composition fails entirely.
    # Never let the wizard stall on a narrator error.
    fallback: Optional[str] = None

    # The interrupt step this utterance precedes (step_frame / step_reframe).
    # Used for cache keying + cross-step continuity, not required for other
    # roles.
    step_key: Optional[str] = None


# ── Narrator result ──────────────────────────────────────────────────────────────


@dataclass
class NarratorResult:
    """What ``narrate`` returns to its caller.

    ``text`` is always present (the emitted string). The remaining fields are
    observability + state-merge hooks:

      • ``cache_update`` — splat into the node's returned state diff so the L1
        entry survives the checkpoint round-trip (mirrors the legacy
        ``wizard_milestone_cache`` return contract).
      • ``repaired`` / ``cache_hit`` / ``fell_back`` — fed to telemetry; also
        let tests assert behaviour without scraping logs.
    """

    text: str
    cache_update: dict[str, str] = field(default_factory=dict)

    cache_hit: bool = False
    repaired: bool = False
    fell_back: bool = False


__all__ = [
    "Role",
    "Tone",
    "CacheScope",
    "GroundingPack",
    "Utterance",
    "NarratorResult",
]
