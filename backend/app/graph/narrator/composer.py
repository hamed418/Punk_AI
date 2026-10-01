"""
graph/narrator/composer.py
──────────────────────────
The "one mind per screen" composer.

:func:`flush_narration` drains the turn's beat buffer (see :mod:`beats`) and, in
ONE LLM call, weaves every beat into a single coherent, conversational message
that explains what Punk is doing and showcases the work (real spots, brands,
counts, the drafted plan). It replaces the old per-role generation stack —
there is no critic, no statements-only question stripping, no per-role
model/temperature matrix. The compose call runs on the Pro tier (thinking depth
scales with the turn), retries once if nothing streamed, and then degrades to the
beats' own fallback text so a turn never goes silent.

Called right before every graph pause (inside ``wizard_interrupt``) and at
``builder_finalize``. ``narrate`` never raises.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings
from app.graph.knowledge import load_punk_kb
from app.graph.narrator import beats as _beats
from app.graph.narrator import cache, telemetry
from app.graph.narrator.grounding import build_pack
from app.graph.narrator.post_process import scrub_jargon
from app.graph.narrator.prompts import base
from app.graph.narrator.prompts import composer as _cprompt
from app.graph.narrator.widget_guides import attach_widget_guides, guide_action_count
from app.graph.state import is_conversational, is_internal
from app.graph.usage import _split_stream_content

logger = logging.getLogger(__name__)

_TRANSCRIPT_TURNS = 6  # recent messages fed in as real continuity context
_HISTORY_CHARS = 240  # per-line cap stored in the continuity ring / state ledger

# Beat kinds that justify deeper thinking (a result reveal, a between-stage
# handoff recap, a failure that needs care). Everything else (framing / edit /
# auto_fill / reframe) is a simple turn on the light thinking level so the first
# streamed token lands fast. `answer` is rich too: the user asked a real question
# mid-step, and depth follows what they ASKED, not how short their message was.
_RICH_KINDS = {"reveal", "handoff", "failure", "budget_framing", "answer"}

# Shown once when both stream attempts produce nothing. NOT canned beat text —
# the deterministic fallback was removed; this is a plain retry nudge.
_ERROR_TEXT = "I hit a snag putting that together — give me a second and try again."


def _temperature() -> float:
    return getattr(settings, "NARRATOR_COMPOSER_TEMP", 1.0)


# How the user's engagement scales the character budget — terse user gets a
# tight line, an engaged user a little more room. Clamped to a sane floor so a
# rich reveal never collapses to nothing.
_ENGAGEMENT_SCALE: dict[str, float] = {"terse": 0.4, "normal": 1.0, "engaged": 1.2}
_MIN_MAX_CHARS = 200
# Room for each failure beat past the first. Connect is where a new advertiser can
# hit several constraints at once (no payment, no Pixel, terms, unpublished Page…);
# at the flat budget the composer chose which survived and nobody could tell which.
_FAILURE_CHARS = 220
_MAX_EXTRA_FAILURES = 4
# Room per action a widget guide lists (see widget_guides.py) — a first-sight
# guide of 8 actions cannot fit the terse 0.4x budget.
_GUIDE_CHARS_PER_ACTION = 45


def _max_chars(state: Any = None, beat_list: list["_beats.Beat"] | None = None) -> int:
    base_chars = getattr(settings, "NARRATOR_REVEAL_MAX_CHARS", 800)
    failures = sum(1 for b in (beat_list or []) if b.kind == "failure")
    base_chars += _FAILURE_CHARS * min(max(failures - 1, 0), _MAX_EXTRA_FAILURES)
    try:
        engagement = ((state or {}).get("user_turn") or {}).get("engagement")
    except AttributeError:
        engagement = None
    scale = _ENGAGEMENT_SCALE.get(engagement or "normal", 1.0)
    # Depth follows the TURN TYPE, not the user's message length. A content-rich
    # turn (a result reveal, a handoff recap, a failure that needs care) must not
    # be squeezed to the terse 0.4x budget just because the user answered "yes" —
    # that's what made rich screens read shallow. Never let a rich beat drop below
    # full budget; the terse penalty applies only to simple framing/ack turns.
    if beat_list and any(b.kind in _RICH_KINDS for b in beat_list):
        scale = max(scale, 1.0)
    guide_actions = guide_action_count(beat_list or [])
    if guide_actions:
        # The guide IS the new content of this screen — never squeeze it.
        scale = max(scale, 1.0)
    return max(_MIN_MAX_CHARS, int(base_chars * scale)) + _GUIDE_CHARS_PER_ACTION * guide_actions


def _make_llm(model: str, thinking_level: str) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=model,
        **settings.llm_auth,
        temperature=_temperature(),
        thinking_level=thinking_level,
        # Per attempt. Without it a hung stream never reaches the retry or the
        # stitched fallback below.
        timeout=settings.WIZARD_NARRATOR_TIMEOUT_S,
    )


def _select_tier(beat_list: list[_beats.Beat]) -> tuple[str, str]:
    """Pick (model, thinking_level) for this turn's beats.

    Every screen runs on the smart tier — the prose IS the product, and the lite
    tier wrote the flattest copy on exactly the simple screens users see most.
    Only the depth of thinking varies, with the turn (see ``_RICH_KINDS``).
    """
    deep = any(b.kind in _RICH_KINDS for b in beat_list)
    level = (
        settings.NARRATOR_COMPOSER_THINKING_LEVEL
        if deep
        else settings.NARRATOR_COMPOSER_THINKING_LEVEL_FAST
    )
    return settings.GEMINI_MODEL_PRO, level


def _recent_transcript(state: Any) -> list[str]:
    """The last few real user/assistant turns, as plain strings, so the composer
    has genuine continuity context (replaces the old process-local _RECENT ring,
    which only held wizard lines and drifted)."""
    try:
        msgs = state.get("messages") if hasattr(state, "get") else None
    except Exception:
        msgs = None
    if not msgs:
        return []
    out: list[str] = []
    for m in msgs[-(_TRANSCRIPT_TURNS * 2):]:
        role = getattr(m, "type", None)
        content = getattr(m, "content", None)
        # Ledger records belong here — they ARE the recent conversation during a
        # build, which is the case this function was written for. Injected context
        # blobs do not; they were never said to anyone.
        if not content or role not in ("human", "ai") or is_internal(m):
            continue
        who = "User" if role == "human" else "Punk"
        text = content if isinstance(content, str) else str(content)
        out.append(f"{who}: {text.strip()[:300]}")
    return out[-_TRANSCRIPT_TURNS:]


def _turn_index(state: Any) -> int:
    """Count of real user turns — part of the compose replay-cache key.

    Ledger records are excluded deliberately: they land mid-build, and counting
    them would move the key on every step, so a replayed screen would miss the
    entry the first pass stored and regenerate at full price.
    """
    try:
        msgs = state.get("messages") if hasattr(state, "get") else None
        if not msgs:
            return 0
        return sum(
            1 for m in msgs
            if getattr(m, "type", None) == "human" and is_conversational(m)
        )
    except Exception:
        return 0


def _build_messages(beat_list: list[_beats.Beat], pack, transcript: list[str], max_chars: int) -> list:
    forbidden = sorted(set(base.GLOBAL_FORBIDDEN_TERMS))
    system = "\n\n".join(
        [
            base.PERSONA,
            base.PLAIN_WORDS_RULE,
            base.CONTINUITY_RULE,  # vary openers across consecutive screens
            _cprompt.COMPOSE_RULE,
            _cprompt.EXEMPLARS,    # worked beats→message examples anchor the flow
            _cprompt.OUTPUT_RULE,
        ]
    )
    # A mid-step question ("does Punk use interests?", "how is the audience built?")
    # is answered from real product facts, not from the model's guess at them —
    # the same file the chatbot already gets.
    if any(b.kind == "answer" for b in beat_list):
        system += (
            "\n\nPUNK PRODUCT FACTS — when the user's question is about Punk itself, "
            "answer from these and nothing else:\n" + load_punk_kb()
        )

    beats_payload = [
        {"kind": b.kind, "facts": b.facts} for b in beat_list
    ]
    # Which reveal clauses apply: the reveal beats' own facts over the pack's
    # `maid` section (where the funnel / role signals live).
    signals = dict(getattr(pack, "maid", None) or {})
    for b in beat_list:
        if b.kind == "reveal":
            signals.update(b.facts)
    hint_block = _cprompt.beat_hint_block([b.kind for b in beat_list], signals)

    transcript_block = ""
    if transcript:
        transcript_block = (
            "\n\nRecent conversation (continue this thread; do not restate what "
            "you already said):\n" + "\n".join(f"  {line}" for line in transcript)
        )

    # The lines Punk already narrated this session. This is the source of truth
    # for what NOT to repeat — facts that appear here have already been shown, so
    # reference them in a clause, never re-list them.
    already_block = ""
    history = getattr(pack, "history", None) or []
    if history:
        already_block = (
            "\n\nALREADY DELIVERED earlier this session — these are screens you "
            "ALREADY showed the user. Do NOT restate their counts, place names, "
            "store/city, goal, or budget; build forward from them:\n"
            + "\n".join(f"  - {line}" for line in history)
        )

    # RESPOND TO THE USER — the human's latest turn, first-class. Placed at the
    # top so the composer replies TO them (mirror their words, answer an embedded
    # question, match their mood/energy) before narrating Punk's own beats.
    user_block = ""
    ut = getattr(pack, "user_turn", None) or {}
    if ut:
        user_block = (
            "RESPOND TO THE USER FIRST — this is the human's latest turn:\n"
            f"{json.dumps(ut, default=str, ensure_ascii=False)}\n"
            "  • If `embedded_ask` is set, answer it in one plain sentence BEFORE "
            "moving on.\n"
            "  • Open by acknowledging what they just said; use THEIR words "
            "(`phrase`) for their goal/answer, not an internal label.\n"
            "  • Match `engagement`: terse → ONE tight line; engaged → a little "
            "more. Match `mood`: frustrated → brief + reassure, zero hype; "
            "confused → add one plain guiding sentence; eager → keep momentum, "
            "stay concise.\n\n"
        )

    # WHAT ACTUALLY CHANGED — a closed list to check claims against, not a
    # request to behave. Replaces a prompt sentence ("never say X unless a
    # beat reports it") that the model could satisfy or ignore with no way for
    # anyone downstream to tell which happened. `applied` is the ONLY source
    # of "this is done"; everything else here is a fact the model must state
    # as heard-not-done / a deviation / a plain "can't do that" instead.
    changes = getattr(pack, "changes", None) or {}
    changes_block = ""
    if any(changes.values()):
        lines = ["WHAT ACTUALLY CHANGED THIS TURN — ground every claim in this list:"]
        if changes.get("applied"):
            lines.append(
                "  DONE — the ONLY changes you may report as added/removed/"
                f"changed/updated: {changes['applied']}"
            )
        if changes.get("deviations"):
            lines.append(
                f"  DEVIATIONS — outcome differs from what was literally asked; "
                f"say this out loud, do not let it pass silently: {changes['deviations']}"
            )
        if changes.get("unsupported"):
            lines.append(
                f"  CAN'T DO — say plainly you can't and what you did instead of "
                f"this part: {changes['unsupported']}"
            )
        if changes.get("heard_not_applied"):
            lines.append(
                "  HEARD, NOT YET DONE — acknowledge hearing these, never say "
                f"they're done: {changes['heard_not_applied']}"
            )
        if not changes.get("applied"):
            lines.append(
                "  Nothing in DONE above -> nothing changed this turn. Do not "
                "use added/removed/changed/updated/trimmed/updated for anything."
            )
        changes_block = "\n".join(lines) + "\n\n"

    # user_turn and changes are rendered explicitly below; keeping them in the
    # reference dict too just states them twice.
    reference = {
        k: v for k, v in pack.as_prompt_dict().items() if k not in ("user_turn", "changes")
    }

    # Order: background first, the task last. Reference + what was already said +
    # the recent conversation set the scene; then who to answer, what really
    # changed, and the beats to weave sit right next to the length and the ban list.
    human = (
        f"REFERENCE context (lookup only — use it to spell a name / get a number "
        f"right for a fact THIS turn's beats introduce; do NOT re-list facts from "
        f"earlier screens). Use `highlights` to name real spots/brands the FIRST "
        f"time they land:\n"
        f"{json.dumps(reference, default=str, ensure_ascii=False)}"
        f"{already_block}"
        f"{transcript_block}\n\n"
        f"{user_block}"
        f"{changes_block}"
        f"Beats this turn (weave ALL of them, in order) — surface ONLY the facts "
        f"these beats newly introduce:\n"
        f"{json.dumps(beats_payload, default=str, ensure_ascii=False)}\n\n"
        f"{hint_block}\n\n"
        f"Forbidden internal jargon: {forbidden}\n"
        f"Length: about {max_chars // 6} words, never more than {max_chars} characters."
    )
    return [SystemMessage(content=system), HumanMessage(content=human)]


async def _stream_once(
    messages: list, model: str, thinking_level: str, writer: Any
) -> tuple[str, bool]:
    """Stream ONE compose attempt token-by-token through ``writer``.

    Returns ``(accumulated_text, emitted_any)``. Answer tokens are emitted as
    incremental ``assistant_message`` events the instant they arrive; thinking
    tokens are split out and discarded (narration only). Whole-turn token usage
    is captured by the chat endpoint's ``get_usage_metadata_callback`` wrapper,
    so no explicit usage plumbing is needed here. Exceptions are swallowed and
    whatever streamed so far is returned, so the caller can decide whether a
    retry is safe (only when nothing was emitted).
    """
    llm = _make_llm(model, thinking_level)
    parts: list[str] = []
    try:
        async for chunk in llm.astream(messages):
            _thinking, answer = _split_stream_content(getattr(chunk, "content", ""))
            if answer:
                parts.append(answer)
                if writer is not None:
                    writer({"type": "assistant_message", "content": answer})
    except Exception as exc:
        logger.warning("narrator compose stream failed model=%s: %r", model, exc)
    return "".join(parts).strip(), bool(parts)


def _stitch_fallbacks(beat_list: list["_beats.Beat"]) -> str:
    """Join the beats' deterministic `fallback` copy into one coherent message.

    Used only when live composition fails entirely — a stitched line of real,
    hand-written fallbacks (with true counts) beats a generic retry nudge. Beats
    that carry no fallback are skipped; de-dupes an identical consecutive line.
    """
    parts: list[str] = []
    for b in beat_list:
        fb = (getattr(b, "fallback", None) or "").strip()
        if fb and (not parts or parts[-1] != fb):
            parts.append(fb)
    return " ".join(parts).strip()


def _ledger_fallback_line(changes: dict[str, list[str]]) -> str:
    """Plain, template-only statement of what did NOT go as asked. Used when no
    LLM composition runs, so honesty never depends on the narrator being on."""
    parts: list[str] = []
    if changes.get("heard_not_applied"):
        parts.append("Not applied yet: " + "; ".join(changes["heard_not_applied"]) + ".")
    if changes.get("deviations"):
        parts.append("Adjusted: " + "; ".join(changes["deviations"]) + ".")
    if changes.get("unsupported"):
        parts.append("I can't do this yet: " + "; ".join(changes["unsupported"]) + ".")
    return " ".join(parts)


def _emit(writer: Any, text: str) -> None:
    if writer is not None and text:
        # Trailing blank line keeps this message visually separate from a widget
        # (or a later message) that chat.py concatenates after it.
        writer({"type": "assistant_message", "content": text + "\n\n"})


async def _compose(state: Any, writer: Any, *, emit: bool) -> tuple[str, dict[str, Any]]:
    """Drain the buffer and compose one message. Returns (text, cache_update).

    When ``emit`` is True the message is STREAMED token-by-token through
    ``writer`` as ``assistant_message`` events as the LLM generates it (the
    wizard / builder pause path and the chatbot handoff). When False the text is
    generated silently and only returned. Returns ("", {}) when nothing
    buffered. There is no deterministic fallback: on a total LLM failure (zero
    tokens across one retry) a single plain retry nudge is emitted instead.
    """
    beat_list = _beats.drain(state)
    if not beat_list:
        return "", {}

    # Kill-switch: no LLM narration at all. The deterministic beat-fallback text
    # was removed, so a disabled narrator simply carries no narrated message —
    # the widget/work below still renders. EXCEPT the change ledger: an edit
    # that was acknowledged but not applied, adjusted, or refused must still be
    # said, or turning the narrator off turns every such edit into a silent lie.
    if not settings.WIZARD_NARRATOR_ENABLED:
        line = _ledger_fallback_line(_beats.drain_changes(state))
        if emit and line:
            _emit(writer, line)
        return line, {}

    # Pull the session's "already told" ring from Redis first — this may be a
    # different instance from the one that composed the earlier screens. The
    # guided ledger rides the same hop, and must be loaded before a widget
    # guide is attached (first sight vs reminder) and before max_chars, the
    # cache fingerprint and the prompt read the beats.
    await _beats.load_history(state)
    await _beats.load_guided(state)
    await attach_widget_guides(state, beat_list, _turn_index(state))
    max_chars = _max_chars(state, beat_list)
    pack = build_pack(state)

    # ── Cache (replay determinism) ────────────────────────────────────────────
    # Key on the beats + grounding + turn index. A LangGraph replay of the same
    # turn reproduces identical beats → same key → identical text at $0. A cache
    # HIT is emitted whole (not re-streamed) — replay determinism over motion.
    fp = cache.stable_fingerprint(
        {
            "beats": [{"k": b.kind, "f": b.facts} for b in beat_list],
            "g": pack.as_prompt_dict(),
            "t": _turn_index(state),
        }
    )
    key = f"compose:{fp}"
    hit = cache.lookup(key, state)
    if hit is not None:
        if emit:
            _emit(writer, hit)
        await _beats.remember(state, hit[:_HISTORY_CHARS])
        telemetry.record(
            writer, role="compose", cache_hit=True, repaired=False,
            fell_back=False, char_len=len(hit),
        )
        return hit, {}

    # ── Generate (streamed live) ───────────────────────────────────────────────
    transcript = _recent_transcript(state)
    messages = _build_messages(beat_list, pack, transcript, max_chars)
    model, level = _select_tier(beat_list)
    stream_writer = writer if emit else None

    text, emitted = await _stream_once(messages, model, level, stream_writer)
    if not text and not emitted:
        # Nothing streamed at all (connection error / timeout before any token) —
        # safe to retry once on the same tier without duplicating partial output.
        text, emitted = await _stream_once(messages, model, level, stream_writer)

    if not text:
        # Total failure across both attempts. Prefer the beats' own hand-written
        # `fallback` copy (real numbers, coherent) over the generic retry nudge —
        # this is the whole point of carrying a fallback per beat. Only when NO
        # beat carried one do we fall back to the plain retry line.
        stitched = _stitch_fallbacks(beat_list)
        out_text = stitched or _ERROR_TEXT
        if emit:
            _emit(writer, out_text)
        if stitched:
            await _beats.remember(state, stitched[:_HISTORY_CHARS])
        telemetry.record(
            writer, role="compose", cache_hit=False, repaired=False,
            fell_back=True, char_len=len(out_text),
        )
        return out_text, {}

    # The live stream emitted raw answer chunks without the trailing blank line
    # that _emit appends; emit one separator so this message stays visually
    # distinct from a widget/message chat.py concatenates after it. The returned
    # text (persisted as an AIMessage / saved to DB) stays clean.
    if emit and writer is not None:
        writer({"type": "assistant_message", "content": "\n\n"})

    # Deterministic jargon guardrail on the PERSISTED copy: if a banned internal
    # term slipped past the prompt's forbidden-terms list, swap it for plain words
    # before it lands in the DB, the compose cache, and the continuity ring (where
    # it would otherwise be fed back into future "ALREADY DELIVERED" context). The
    # live token stream above already showed the raw text — the prompt ban is the
    # front-line defence there; this keeps every stored/echoed copy clean.
    text = scrub_jargon(text)
    cache_update = cache.store(key, text)
    await _beats.remember(state, text[:_HISTORY_CHARS])
    telemetry.record(
        writer, role="compose", cache_hit=False, repaired=False,
        fell_back=False, char_len=len(text),
    )
    update: dict[str, Any] = {"narrator_history": [text[:_HISTORY_CHARS]]}
    if cache_update:
        update["wizard_milestone_cache"] = cache_update
    return text, update


async def flush_narration(state: Any, writer: Any) -> tuple[str, dict[str, Any]]:
    """Compose all beats buffered this turn and EMIT the message via ``writer``.

    Called right before every graph pause (inside ``wizard_interrupt``) and at
    ``builder_finalize``. Returns ``(composed_text, update)``.

    ``update`` is a state-merge fragment ({"wizard_milestone_cache": {...}}) the
    caller MAY splat into its node diff to persist the composed text across a
    cross-worker checkpoint round-trip; callers that cannot (e.g.
    ``wizard_interrupt`` returns a ResumeResult) may ignore it — the process-local
    cache plus the resume ``skip_emit`` guard already make same-worker replay
    deterministic. ``("", {})`` when nothing buffered.

    ``composed_text`` is the full message as emitted. ``builder_finalize`` records
    it in ``state["messages"]`` so later nodes can see what the user was told;
    ``narrator_history`` is no substitute, being truncated to ``_HISTORY_CHARS``.
    """
    return await _compose(state, writer, emit=True)


async def compose_message(state: Any, writer: Any = None) -> str:
    """Compose all buffered beats and RETURN the text.

    For the chatbot handoff short-circuit, which appends the message to
    ``messages`` itself. Pass ``writer`` to ALSO stream it live token-by-token
    (so the handoff is not a blocking blob); omit it to generate silently.
    Returns "" when nothing is buffered.
    """
    text, _update = await _compose(state, writer, emit=writer is not None)
    return text


__all__ = ["flush_narration", "compose_message"]
