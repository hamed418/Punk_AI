"""
graph/narrator/beats.py
───────────────────────
Turn-scoped beat buffer for the "one mind per screen" narrator.

The old narrator fired a separate LLM call for every user-facing line (one per
role: step_frame, stage_open, milestone, …). Within a single user turn the
builder emits several in sequence, and they were glued together with blank
lines — three independent generations, no single mind composing the turn, so
the output read as stacked, incoherent sentences.

This module replaces those immediate emissions with **beats**: each call site
appends a small structured intent (kind + the concrete facts it carries) to a
per-session buffer instead of generating text. The buffer is drained and
composed into ONE coherent message by :func:`composer.flush_narration` right
before the graph pauses (every ``interrupt()`` and at ``builder_finalize``).

Replay safety: the buffer is process-local and rebuilt by re-execution.
LangGraph does not re-run already-checkpointed nodes on resume, so a reveal
emitted last turn does not reappear; and ``wizard_interrupt``'s existing
``skip_emit`` resume guard suppresses the framing beat + flush on a resume
replay. Determinism therefore comes from those two existing mechanisms plus the
in-process composed-text cache, not from persisting the buffer itself.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from app.core import redis as _redis

# Beat kinds, in the rough order they tend to occur within a turn. The composer
# uses the kind to decide how to weave each beat (an action narration vs a
# result reveal vs a widget framing line).
BeatKind = str  # "stage" | "reveal" | "handoff" | "framing" | "edit" | "answer" | "auto_fill" | "reframe" | "failure"


@dataclass
class Beat:
    """One thing that wants to be said this turn.

    ``facts`` carries the concrete, rich grounding for this beat (real place
    names, counts, budget, the drafted plan, …). ``fallback`` is deterministic
    text emitted verbatim if composition is disabled or fails, so a turn never
    goes silent.
    """

    kind: BeatKind
    facts: dict[str, Any] = field(default_factory=dict)
    fallback: str | None = None


# Process-local, per-session buffers. Bounded so a long-lived worker cannot
# leak sessions (mirrors narrator._RECENT sizing).
_MAX_SESSIONS = 512
_BUFFERS: "OrderedDict[str, list[Beat]]" = OrderedDict()


def session_key(state: Any) -> str:
    """Stable per-session bucket, keyed on the first HumanMessage id.

    Invariant across a whole checkpointed thread and across replays of the same
    turn (the messages list is identical). Mirrors narrator._session_key so the
    beat buffer and the continuity history share one notion of "session".
    Falls back to a constant when no message id is available (single shared
    bucket — acceptable for the degenerate cold-start case).
    """
    try:
        msgs = state.get("messages") if (state is not None and hasattr(state, "get")) else None
    except Exception:
        msgs = None
    if msgs:
        for m in msgs:
            if getattr(m, "type", None) == "human":
                mid = getattr(m, "id", None)
                if mid:
                    return f"sess:{mid}"
                break
    return "sess:default"


def add_beat(
    state: Any,
    kind: BeatKind,
    facts: dict[str, Any] | None = None,
    *,
    fallback: str | None = None,
) -> None:
    """Append a beat to this session's turn buffer."""
    skey = session_key(state)
    buf = _BUFFERS.get(skey)
    if buf is None:
        buf = []
        _BUFFERS[skey] = buf
        if len(_BUFFERS) > _MAX_SESSIONS:
            _BUFFERS.popitem(last=False)
    else:
        # Touch for LRU recency.
        _BUFFERS.move_to_end(skey)
    buf.append(
        Beat(
            kind=kind,
            # Drop only genuinely-empty facts. A numeric 0 (poi_count=0,
            # maid_count=0) is a REAL value the reveal must state — `v not in
            # (None, "", [])` used to strip it because `0 == False == []`-ish
            # emptiness, silently hiding zero-result counts from the composer.
            facts={
                k: v
                for k, v in (facts or {}).items()
                if v is not None and v not in ("", [], {}, ())
            },
            fallback=fallback,
        )
    )


# ── Continuity history ring ──────────────────────────────────────────────────
# The "lines I already told the user" ledger that GroundingPack.history was
# always meant to read from (grounding.py left it []). Wizard narrations are
# emitted as stream events, NOT appended to state["messages"], and the
# interrupt flush path discards its state-merge fragment — so neither the
# transcript nor a state field reliably captures prior narration. This
# process-local per-session ring does: composer._compose appends each composed
# message here, build_pack reads the tail back into pack.history so the
# composer can build forward instead of re-showcasing. Bounded per session.
_MAX_HISTORY = 12
_HISTORY: "OrderedDict[str, list[str]]" = OrderedDict()


def record_history(state: Any, line: str) -> bool:
    """Append one composed user-facing line to this session's continuity ring.

    Returns True when the line was actually appended (False for an empty or
    consecutive-duplicate line), so callers mirror only real additions.
    """
    line = (line or "").strip()
    if not line:
        return False
    skey = session_key(state)
    ring = _HISTORY.get(skey)
    if ring is None:
        ring = []
        _HISTORY[skey] = ring
        if len(_HISTORY) > _MAX_SESSIONS:
            _HISTORY.popitem(last=False)
    else:
        _HISTORY.move_to_end(skey)
    # De-dupe an identical consecutive line (a same-worker replay re-composing
    # the same turn must not stack the ring).
    if ring and ring[-1] == line:
        return False
    ring.append(line)
    if len(ring) > _MAX_HISTORY:
        del ring[: len(ring) - _MAX_HISTORY]
    return True


# ── Cross-instance mirror ─────────────────────────────────────────────────────
# The ring above is process-local, but the API runs on Cloud Run with several
# instances and no session affinity, so a resume routinely lands somewhere that
# never composed the earlier screens — and the composer + chatbot then recap
# counts they already delivered. `narrator_history` in state cannot cover it:
# a node that interrupts never commits its return, so the flush fragment is
# dropped at every pause. Redis (best-effort, same rules as
# modules/chat/run_store.py) carries the ring across instances; with no Redis
# configured or reachable both helpers are no-ops and behaviour is unchanged.
_HISTORY_TTL_S = 7 * 24 * 3600


def _history_key(skey: str) -> str:
    return _redis.key("narr", skey, "hist")


async def load_history(state: Any) -> None:
    """Make Redis's copy of this session's ring the local one, when Redis has it."""
    skey = session_key(state)
    # "sess:default" is ONE bucket shared by every message-less state; never key
    # Redis on it or unrelated sessions would read each other's history.
    if skey == "sess:default" or not _redis.redis_enabled():
        return
    try:
        raw = await _redis.get_client().lrange(_history_key(skey), 0, -1)
    except Exception as exc:  # noqa: BLE001 — an optimisation, never a new failure
        _redis.mark_unavailable(exc)
        return
    if raw:
        _HISTORY[skey] = list(raw)[-_MAX_HISTORY:]
        _HISTORY.move_to_end(skey)


async def remember(state: Any, line: str) -> None:
    """record_history + mirror the appended line to Redis."""
    if not record_history(state, line):
        return
    skey = session_key(state)
    if skey == "sess:default" or not _redis.redis_enabled():
        return
    try:
        pipe = _redis.get_client().pipeline()
        pipe.rpush(_history_key(skey), line.strip())
        pipe.ltrim(_history_key(skey), -_MAX_HISTORY, -1)
        pipe.expire(_history_key(skey), _HISTORY_TTL_S)
        await pipe.execute()
    except Exception as exc:  # noqa: BLE001
        _redis.mark_unavailable(exc)


async def reset_history(state: Any) -> None:
    """Forget this session's "already told" ring, locally and in Redis.

    A rewind forks the graph back to an earlier step, but the ring is NOT part of
    the checkpoint — it would keep the lines narrated on the discarded branch, and
    the composer would keep building on facts the user just undid. Cleared here,
    the composer falls back to the forked state's own ``narrator_history``
    (grounding.build_pack). Never raises: memory hygiene must not fail a rewind.
    """
    skey = session_key(state)
    _HISTORY.pop(skey, None)
    if skey == "sess:default" or not _redis.redis_enabled():
        return
    try:
        await _redis.get_client().delete(_history_key(skey))
    except Exception as exc:  # noqa: BLE001
        _redis.mark_unavailable(exc)


# ── Widget-guide ledger ───────────────────────────────────────────────────────
# Which widget guides (narrator/widget_guides.py) this session has already been
# given in full, and on which user turn — so the first showing explains every
# control and later ones only remind. Same shape and reasons as the history ring
# above: process-local dict, Redis hash mirror for cross-instance resumes, both
# no-ops when Redis is absent or failing.
_GUIDED: "OrderedDict[str, dict[str, int]]" = OrderedDict()


def _guided_key(skey: str) -> str:
    return _redis.key("narr", skey, "guided")


async def load_guided(state: Any) -> None:
    """Merge Redis's guided ledger for this session into the local one."""
    skey = session_key(state)
    if skey == "sess:default" or not _redis.redis_enabled():
        return
    try:
        raw = await _redis.get_client().hgetall(_guided_key(skey))
    except Exception as exc:  # noqa: BLE001 — an optimisation, never a new failure
        _redis.mark_unavailable(exc)
        return
    if raw:
        local = _GUIDED.setdefault(skey, {})
        for k, v in raw.items():
            k = k.decode() if isinstance(k, bytes) else k
            try:
                local.setdefault(k, int(v))
            except (TypeError, ValueError):
                continue
        _GUIDED.move_to_end(skey)
        if len(_GUIDED) > _MAX_SESSIONS:
            _GUIDED.popitem(last=False)


def guided_turn(state: Any, key: str) -> int | None:
    """User-turn index at which ``key``'s full guide was first given, else None."""
    return (_GUIDED.get(session_key(state)) or {}).get(key)


async def mark_guided(state: Any, key: str, turn: int) -> None:
    """Record the FIRST turn ``key`` was guided (a later call never moves it)."""
    skey = session_key(state)
    ledger = _GUIDED.get(skey)
    if ledger is None:
        ledger = {}
        _GUIDED[skey] = ledger
        if len(_GUIDED) > _MAX_SESSIONS:
            _GUIDED.popitem(last=False)
    else:
        _GUIDED.move_to_end(skey)
    if key in ledger:
        return
    ledger[key] = turn
    if skey == "sess:default" or not _redis.redis_enabled():
        return
    try:
        pipe = _redis.get_client().pipeline()
        pipe.hsetnx(_guided_key(skey), key, turn)
        pipe.expire(_guided_key(skey), _HISTORY_TTL_S)
        await pipe.execute()
    except Exception as exc:  # noqa: BLE001
        _redis.mark_unavailable(exc)


def recent_history(state: Any, n: int = _MAX_HISTORY) -> list[str]:
    """Return the last ``n`` composed lines for this session (oldest first)."""
    ring = _HISTORY.get(session_key(state)) or []
    return list(ring[-n:])


def peek(state: Any) -> list[Beat]:
    """Return the current buffered beats without clearing (read-only)."""
    return list(_BUFFERS.get(session_key(state)) or [])


def drain(state: Any) -> list[Beat]:
    """Return the buffered beats and clear the buffer for this session."""
    skey = session_key(state)
    buf = _BUFFERS.pop(skey, None)
    return list(buf or [])


def clear(state: Any | None = None) -> None:
    """Drop one session's buffer, or all buffers when ``state`` is None.

    Test hook + safety valve. The composer drains on every flush, so this is
    only needed to reset between unrelated runs.
    """
    if state is None:
        _BUFFERS.clear()
        _HISTORY.clear()
        _CHANGES.clear()
        _GUIDED.clear()
    else:
        skey = session_key(state)
        _BUFFERS.pop(skey, None)
        _HISTORY.pop(skey, None)
        _CHANGES.pop(skey, None)
        _GUIDED.pop(skey, None)


# ── Turn-change ledger ───────────────────────────────────────────────────────
#
# What actually landed in state THIS turn, vs. what the user was merely told
# was heard — the fact base the composer's "don't claim it happened unless it
# happened" rule checks against (see composer.py's CHANGES block), instead of
# a prompt sentence asking the model to behave.
#
# The bug this closes: an edit-lane ack is narrated at CLASSIFICATION time —
# before the write lands, sometimes a whole node earlier (`_dispatch_edit_intent`
# buffers the ack; `builder_plan` -> `apply_pending_edits` does the write later
# in the SAME turn, or not at all when the field turns out unresolvable, e.g. a
# POI-selection instruction the parser can't read). The composer previously had
# no way to tell an ack that came true from one that didn't — only a request not
# to lie about it.
#
# Same per-session/bounded/process-local shape as `_BUFFERS` above, on purpose:
# identical lifecycle (populated during the turn, drained once at flush).
_CHANGES: "OrderedDict[str, dict[str, Any]]" = OrderedDict()


def _empty_ledger() -> dict[str, Any]:
    return {"applied": [], "heard": {}, "deviations": [], "unsupported": []}


def record_change(
    state: Any,
    *,
    applied: dict[str, str] | None = None,
    heard: dict[str, str] | None = None,
    deviation: str | list[str] | None = None,
    unsupported: str | list[str] | None = None,
) -> None:
    """Append to this turn's change ledger.

    ``heard`` and ``applied`` are ``{field: description}`` — keyed by the
    SAME field name the classifier used (``ResumeIntent.target_field``, e.g.
    ``"poi_selection"``, ``"budget"``), so a write can be matched back to the
    ack it fulfills. Record ``heard`` at ACK time (before the write lands);
    record ``applied`` once the write actually lands — doing so POPS the
    matching ``heard`` entry, so whatever remains in ``heard`` at
    :func:`drain_changes` was acked but genuinely never applied.

    ``deviation`` is a plain sentence stating how the outcome differs from
    the literal ask (a named-arm POI kept past a count trim, a group short of
    the requested N). ``unsupported`` names a clause understood but
    expressible by nothing the executor has — both are additive text, not
    field-keyed, since they describe a nuance within one field's edit rather
    than a second field.
    """
    skey = session_key(state)
    entry = _CHANGES.get(skey)
    if entry is None:
        entry = _empty_ledger()
        _CHANGES[skey] = entry
        if len(_CHANGES) > _MAX_SESSIONS:
            _CHANGES.popitem(last=False)
    else:
        _CHANGES.move_to_end(skey)
    if heard:
        entry["heard"].update(heard)
    if applied:
        for field, desc in applied.items():
            entry["applied"].append(desc)
            entry["heard"].pop(field, None)
    if deviation:
        entry["deviations"].extend(deviation if isinstance(deviation, list) else [deviation])
    if unsupported:
        entry["unsupported"].extend(unsupported if isinstance(unsupported, list) else [unsupported])


def drain_changes(state: Any) -> dict[str, list[str]]:
    """Return and clear this turn's change ledger.

    ``heard_not_applied`` is the ``heard`` dict's remaining VALUES — every
    entry whose matching ``applied`` never arrived.
    """
    skey = session_key(state)
    entry = _CHANGES.pop(skey, None) or _empty_ledger()
    return {
        "applied": list(entry["applied"]),
        "heard_not_applied": list(entry["heard"].values()),
        "deviations": list(entry["deviations"]),
        "unsupported": list(entry["unsupported"]),
    }


__all__ = [
    "Beat",
    "BeatKind",
    "session_key",
    "add_beat",
    "peek",
    "drain",
    "clear",
    "record_history",
    "recent_history",
    "load_history",
    "remember",
    "load_guided",
    "guided_turn",
    "mark_guided",
    "record_change",
    "drain_changes",
]
