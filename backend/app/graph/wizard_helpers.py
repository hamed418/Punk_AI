"""
graph/wizard_helpers.py
───────────────────────
Shared utilities for the four wizard subgraphs (geo / maid / campaign / media).

Each wizard sub-node is its own checkpoint boundary, so the helper functions
here replace ``_geo_interrupt`` and ``_geo_ack`` from the old monolithic nodes.
Because every sub-node runs at most once per user turn, the smart-ack LLM call
is no longer subject to replay accumulation.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
from collections import OrderedDict
from typing import Any, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.config import get_stream_writer
from langgraph.types import interrupt
from pydantic import BaseModel

from app.core.config import settings
from app.graph.field_owner_registry import (
    APPENDABLE_FIELDS,
    EDIT_BLOCK_MESSAGES,
    edit_block_reason,
)
from app.graph.prompts_registry import STEP_PROMPTS
from app.graph.resume_router import (
    ResumeResult,
    audience_panel_intent,
    classify_resume_intent,
    classify_resume_intent_tools,
    # Not called from here any more (see the comment at its call site) — kept
    # imported because tests patch it as `wizard_helpers.generate_chips`.
    generate_chips,
    is_sentinel_resume,
)
from app.graph import capability_miss
from app.graph.narrator import add_beat as _narrator_add_beat
from app.graph.narrator import cache as narrator_cache, drain as _narrator_drain, flush_narration, narrate, peek as _narrator_peek
from app.graph.narrator.beats import record_change, session_key as _session_key
from app.graph.narrator.types import Utterance
from app.graph.state import PendingAction
from app.graph.usage import tracked_ainvoke, tracked_astream
from app.graph.wizard_exit import WizardExitRequested


# Resume-router bounded-loop knobs. ``_ESCAPE_MENU_THRESHOLD`` is the number
# of off-path replies (reject / query / edit) before the escape menu is
# attached to the pending payload. ``_MAX_NONANSWER_LOOPS`` caps the REJECT
# budget — turns where the reply changed nothing and the widget re-shows with
# no other explanation (tracked via ``reframe_needed``, not lane: an
# out-of-scope `edit` with a self-narrated refusal is not silence, so it does
# not spend this budget). A curious user asking several questions, or naming
# several fields Punk can't yet touch, gets its own answer every time and
# never burns toward eviction. ``_MAX_TOTAL_LOOPS`` is the absolute safety
# valve across EVERY off-path lane combined, so a genuinely stuck exchange
# still terminates.
_ESCAPE_MENU_THRESHOLD = 2
_MAX_NONANSWER_LOOPS = 8
_MAX_TOTAL_LOOPS = _MAX_NONANSWER_LOOPS * 3

logger = logging.getLogger(__name__)


# ── Transcript ledger ─────────────────────────────────────────────────────────
# The builder talks to the user through the stream and collects answers through
# interrupt(), so a whole build used to leave NOTHING in state["messages"] — every
# downstream LLM saw a conversation frozen at the pre-build turn.
#
# wizard_interrupt cannot fix that itself: it returns a ResumeResult (a str
# subclass), not a state diff. So each resolved interrupt buffers its Q/A pair
# here and the enclosing graph node commits it (see `_with_ledger` in
# builder_node). Process-local and session-keyed, mirroring narrator.beats — the
# buffer lives for ONE node execution and never crosses a resume boundary, so
# locality costs nothing.
_LEDGER_MAX_SESSIONS = 512
_LEDGER_CHARS = 400
_LEDGER: "OrderedDict[str, list[BaseMessage]]" = OrderedDict()


def record_qa(state: Any, step_key: str, question: str, answer: str) -> None:
    """Buffer one resolved interrupt as a question/answer pair.

    ``question`` is the step's deterministic prompt, not the composed narration:
    the narration is unrecoverable on a resume (the replay skips the flush), while
    the prompt recomputes identically, so a replayed node re-derives the same pair.
    """
    skey = _session_key(state)
    buf = _LEDGER.get(skey)
    if buf is None:
        buf = []
        _LEDGER[skey] = buf
        if len(_LEDGER) > _LEDGER_MAX_SESSIONS:
            _LEDGER.popitem(last=False)
    else:
        _LEDGER.move_to_end(skey)

    if question:
        buf.append(AIMessage(
            content=str(question)[:_LEDGER_CHARS],
            additional_kwargs={"role": "wizard_step", "step_key": step_key},
        ))
    if answer:
        buf.append(HumanMessage(
            content=str(answer)[:_LEDGER_CHARS],
            additional_kwargs={"role": "wizard_answer", "step_key": step_key},
        ))


def drain_ledger(state: Any) -> list[BaseMessage]:
    """Take this session's buffered records, emptying the buffer."""
    return _LEDGER.pop(_session_key(state), None) or []


def _as_payload(raw: Any) -> Any:
    """The widget's answer as a parsed object, or None if it was plain text."""
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if text[:1] not in "{[":
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _ledger_answer(raw: Any, value: Any) -> str:
    """What to record as the user's answer.

    Several widgets answer with a JSON payload rather than prose — ``plan_confirm``
    sends the whole edited campaign tree, ``poi_confirm`` sends add/remove deltas.
    Recorded verbatim those become truncated machine JSON sitting in the transcript
    as if the user had typed it, dragging ids and media URLs into every later
    prompt. Record what they DID instead.

    Prefers the RESOLVED value over the raw reply, so confirming a suggested
    ``50`` records "50" rather than "yes" — the number is what later turns need.
    """
    text = str(value if value is not None else raw).strip()
    if text and text[:1] not in "{[":
        return text

    payload = _as_payload(value) if isinstance(value, (dict, list)) else _as_payload(raw)
    if isinstance(payload, list):
        items = [str(i).strip() for i in payload if isinstance(i, (str, int, float))]
        return ", ".join(i for i in items if i) or "(made a selection)"
    if isinstance(payload, dict):
        if payload.get("confirm") is False:
            return "(declined)"
        action = payload.get("action")
        if isinstance(action, str) and action.strip():
            return f"(submitted the form — {action.strip()})"
        return "(confirmed)"
    return "(submitted the form)"


# ── Location validity guard ───────────────────────────────────────────────────

# Matches relative / self-referential phrases that are NOT real geocodable places.
# Examples: "my city", "our town", "local area", "downtown", "nearby", "here",
# "my city, downtown", "around here", "this area", "the local district".
_RELATIVE_LOCATION_PATTERNS = re.compile(
    r"^\s*(?:my|our|the|this|that|your|their|its|nearby|local|here|close|around|near"
    r"|city|town|area|shop|store|location|place|neighborhood|hood|downtown"
    r"|district|region|neighbourhood|centre|center|vicinity|zone|in|at|of|by|next|to"
    r"|business|company|office|branch"
    r"|[\s,])+\s*$",
    re.IGNORECASE,
)


def is_relative_location(name: str) -> bool:
    """Return True if the string looks like a relative/self-referential location phrase.

    Strips possessives (business's → business) before matching so phrases like
    'downtown in the business's city' are correctly caught.
    """
    stripped = (name or "").strip()
    if not stripped:
        return True
    normalized = re.sub(r"'s?\b", "", stripped, flags=re.IGNORECASE)
    return bool(_RELATIVE_LOCATION_PATTERNS.match(normalized))


def market_hint(location_names: list[str]) -> str:
    """First named market usable as a geocode hint, or "" when there is none or it
    is relative ("my city").

    The store-anchor angles skip the `locations` slot (slots.py) but still get it
    prefilled, so this is a SOFT hint about the market the user named — never a
    fact about where their shop is. Callers pass it to `geocode_or_place` as
    `market_hint`, which uses it as a retry and a warning, never as a suffix.
    """
    return (
        location_names[0]
        if location_names and not is_relative_location(location_names[0])
        else ""
    )


# ── LLM factory (mirrors nodes._make_llm — duplicated to avoid import cycle) ──

def _make_llm(temperature: float | None = None, model: str | None = None) -> ChatGoogleGenerativeAI:
    """Standard Gemini instance — no thinking tokens. Flash tier by default."""
    return ChatGoogleGenerativeAI(
        model=model or settings.GEMINI_MODEL,
        **settings.llm_auth,
        temperature=temperature if temperature is not None else settings.GEMINI_TEMPERATURE,
    )


# ── Parsing helpers (migrated from nodes.py) ───────────────────────────────────

# Matches the first (optionally signed/decimal) number in a string.
_NUMERIC_RE = re.compile(r"[-+]?\d*\.?\d+")


def parse_radius_float(raw: str, default: float | None = None) -> float | None:
    """Extract a numeric radius from a slot answer.

    Handles three answer shapes seen on the radius/stepper slots:
      - bare numbers ("2", "2.5") — typed answers, prefills, tests;
      - unit-suffixed values ("2 km", "500 m") — typed natural answers;
      - the radius-picker widget payload "Q: <prompt>\\nA: <value> <unit>"
        (WidgetRadiusPickerV2). The prompt half can itself contain digits
        (e.g. a "(1–50)" range), so the value is read from the answer line only.

    The magnitude is returned as displayed — this is unit-agnostic on purpose:
    each slot's picker already uses the unit its caller expects (km for
    radius_km / competitor_radius_km, m for poi_radius_m), so no conversion is
    applied here. Returns ``default`` when no number is present.
    """
    if raw is None:
        return default
    text = str(raw)
    # Widget format "Q: ...\nA: ..." — parse the value from the answer half so a
    # numeric range inside the prompt is never mistaken for the answer.
    if "A:" in text:
        text = text.rsplit("A:", 1)[1]
    match = _NUMERIC_RE.search(text)
    if not match:
        return default
    try:
        return float(match.group(0))
    except (ValueError, AttributeError):
        return default


# A number and an optional length unit. `k` is "5k" (km). Bare "m" is metres,
# never miles — "mi"/"mile" is required for miles.
_LENGTH_RE = re.compile(
    r"([-+]?\d*\.?\d+)\s*"
    r"(kilomet(?:er|re)s?|kms?|k|miles?|mi|met(?:er|re)s?|m|feet|foot|ft|yards?|yds?)?(?![a-z])",
    re.IGNORECASE,
)
_METRES_PER: dict[str, float] = {
    "k": 1000.0, "mi": 1609.344, "m": 1.0, "ft": 0.3048, "yd": 0.9144,
}


def _length_unit_key(token: str) -> str:
    t = token.lower()
    if t.startswith("kilomet") or t in ("km", "kms", "k"):
        return "k"
    if t.startswith("mi"):
        return "mi"
    if t.startswith("met") or t == "m":
        return "m"
    if t in ("ft", "feet", "foot"):
        return "ft"
    return "yd"


def parse_length(raw: Any, unit: str, default: float | None = None) -> float | None:
    """A length from a slot answer, converted to ``unit`` ("km" or "m").

    Unlike ``parse_radius_float`` this honours the unit the user typed —
    "5 miles", "500 m", "300 feet", "2km" — so a circle radius in km and a visit
    ring in metres both land in their own unit. A bare number is taken as
    already in ``unit`` (what the steppers send). Same widget "Q:/A:" handling.
    Returns ``default`` when no number is present.
    """
    if raw is None:
        return default
    text = str(raw)
    if "A:" in text:
        text = text.rsplit("A:", 1)[1]
    match = _LENGTH_RE.search(text)
    if not match:
        return default
    try:
        value = float(match.group(1))
    except ValueError:
        return default
    if not match.group(2):
        return value
    metres = value * _METRES_PER[_length_unit_key(match.group(2))]
    return metres / 1000.0 if unit == "km" else metres


def parse_int_safe(raw: str, default: int | None = None) -> int | None:
    """Extract an integer from a slot answer.

    Shares ``parse_radius_float``'s extraction so the stepper-widget payload
    "Q: ...\\nA: 30 days" and unit-suffixed answers ("30 days") parse instead of
    silently falling back to the default (the widget never sends a bare number).
    """
    val = parse_radius_float(raw, default=None)
    return default if val is None else int(val)


async def parse_list_input(raw: str, item_type: str, examples: str) -> list[str]:
    """
    Use a zero-temperature LLM call to extract a clean list of items from free-form input.

    Handles natural language separators like "and", "&", "plus", "as well as", and
    also plain commas/semicolons. Falls back to a simple comma/semicolon split on
    any failure so the flow is never blocked.
    """
    try:
        llm = _make_llm(temperature=0.0)
        msg, _ = await tracked_ainvoke(
            llm,
            [
                SystemMessage(content=(
                    f"Extract all distinct {item_type} from the user's input. "
                    "Return ONLY a JSON array of strings — no explanation, no markdown fences. "
                    "IMPORTANT: Do NOT split items that belong together, such as 'City, State', "
                    "'City, Country' pairs, or full street addresses. Keep modifiers like "
                    "'downtown', 'north', 'old port' attached to the place name. "
                    "Street addresses (e.g. '123 Main St, Montreal') must remain as a single string. "
                    f"{examples}"
                )),
                HumanMessage(content=raw),
            ],
            node_name="wizard/parse",
            writer=None,
        )
        text = msg.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text)
        if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
            return [x.strip() for x in parsed if x.strip()]
    except Exception:
        pass

    # Fallback: Split by semicolon/comma but avoid splitting "City, State" pairs
    # if it's just one such pair in the input.
    raw_str = (raw or "").strip()
    if ";" in raw_str:
        return [x.strip() for x in raw_str.split(";") if x.strip()]
    
    # If there's only one comma, it's likely a "City, State" pair — don't split.
    if raw_str.count(",") == 1:
        return [raw_str]

    return [x.strip() for x in raw_str.split(",") if x.strip()]


async def parse_location_names(raw: str) -> list[str]:
    return await parse_list_input(
        raw,
        item_type=(
            "location names — which may be cities, neighbourhoods, districts, city areas, "
            "postal codes, or full street addresses. "
            "IMPORTANT rules: "
            "(1) Keep neighbourhood/district modifiers attached to their city: 'Montreal downtown' stays as one item. "
            "(2) Keep full street addresses intact: '123 Rue Sainte-Catherine, Montreal' is ONE item. "
            "(3) 'City, State/Province/Country' pairs are ONE item. "
            "(4) Only split on clear list separators (and/&/plus/,/;) between truly separate locations."
        ),
        examples=(
            "Example: 'Montreal and Toronto' -> [\"Montreal\", \"Toronto\"]\n"
            "Example: 'NYC, Boston and Chicago' -> [\"NYC\", \"Boston\", \"Chicago\"]\n"
            "Example: 'Trinidad and Tobago' -> [\"Trinidad and Tobago\"]\n"
            "Example: 'Mirpur, Dhaka' -> [\"Mirpur, Dhaka\"]\n"
            "Example: 'Montreal downtown' -> [\"Montreal downtown\"]\n"
            "Example: 'Old Port Montreal and Plateau Mont-Royal' -> [\"Old Port Montreal\", \"Plateau Mont-Royal\"]\n"
            "Example: '123 Rue Sainte-Catherine, Montreal' -> [\"123 Rue Sainte-Catherine, Montreal\"]\n"
            "Example: '15 King St West Toronto and 200 Bay St Toronto' -> [\"15 King St West Toronto\", \"200 Bay St Toronto\"]\n"
            "Example: 'downtown Vancouver and North Shore' -> [\"downtown Vancouver\", \"North Shore\"]\n"
            "Example: 'H3B 4G7' -> [\"H3B 4G7\"]"
        ),
    )


async def parse_poi_types(raw: str) -> list[str]:
    """Split + NORMALIZE free-text POI input into Google-Places-searchable venue
    phrases. Never drop an item the user named — every comma/and-separated entry
    in ``raw`` must produce exactly one output entry:
      - already a searchable venue category ("gym", "yoga studio") -> return it
        VERBATIM (rewriting is the exception, not the default).
      - a PERSONA/INTEREST/lifestyle group, not a place ("coffee lovers", "gym
        goers", "foodies") -> rewrite to the physical venue that group visits
        ("coffee shop", "gym", "restaurant").
      - a real place-visit intent with no matching Places venue ("open house",
        "garage sale") -> rewrite to the closest phrase Places can actually match
        ("real estate open house", "garage sale" -> "yard sale" if still none,
        else the nearest concrete venue).
    Output feeds straight into a Places text query ("<phrase> in <city>"), so
    phrases must stay natural search text, not API slugs.
    """
    return await parse_list_input(
        raw,
        item_type=(
            "Google-Places-searchable venue phrases, one per item the user named. "
            "NEVER drop an item — every distinct thing the user mentioned must "
            "produce exactly one output entry. If an item already names a "
            "searchable place category, return it VERBATIM. If an item names a "
            "PERSONA or INTEREST group rather than a place (e.g. 'coffee lovers', "
            "'gym goers', 'foodies'), rewrite it to the physical venue that group "
            "visits (e.g. 'coffee shop', 'gym', 'restaurant'). If an item names a "
            "real place-visit intent that has no matching Google Places venue "
            "(e.g. 'open house', 'garage sale'), rewrite it to the closest phrase "
            "Places can actually match (e.g. 'real estate open house', 'yard sale')"
        ),
        examples=(
            "Example: 'gym and fitness center' -> [\"gym\", \"fitness center\"]\n"
            "Example: 'pet store, vet clinic and dog park' -> [\"pet store\", \"vet clinic\", \"dog park\"]\n"
            "Example: 'yoga studio' -> [\"yoga studio\"]\n"
            "Example: 'coffee lovers' -> [\"coffee shop\"]\n"
            "Example: 'open house, moving truck rental, coffee lovers' -> "
            "[\"real estate open house\", \"moving truck rental\", \"coffee shop\"]\n"
            "Example: 'gym goers and foodies' -> [\"gym\", \"restaurant\"]"
        ),
    )


async def parse_event_queries(raw: str) -> list[str]:
    return await parse_list_input(
        raw,
        item_type="event types or specific event names",
        examples=(
            "Example: 'music festivals and tech conferences' -> [\"music festivals\", \"tech conferences\"]\n"
            "Example: 'Osheaga, Just For Laughs & F1 Grand Prix' -> [\"Osheaga\", \"Just For Laughs\", \"F1 Grand Prix\"]\n"
            "Example: 'Coachella' -> [\"Coachella\"]"
        ),
    )


async def parse_brand_names(raw: str) -> list[str]:
    return await parse_list_input(
        raw,
        item_type="brand or chain names",
        examples=(
            "Example: 'Starbucks and Tim Hortons' -> [\"Starbucks\", \"Tim Hortons\"]\n"
            "Example: 'McDonald\\'s, Burger King & Wendy\\'s' -> [\"McDonald\\'s\", \"Burger King\", \"Wendy\\'s\"]\n"
            "Example: 'Walmart' -> [\"Walmart\"]"
        ),
    )


async def parse_store_addresses(raw: str) -> list[str]:
    """Split free-form input into distinct store/outlet addresses.

    Each item is a full street address that may itself contain commas
    ('123 Rue X, Montreal'). The LLM must keep each address intact while
    separating truly distinct outlets. Semicolons are the unambiguous
    separator; callers should fast-path ';' before calling this.
    """
    return await parse_list_input(
        raw,
        item_type="distinct store / outlet street addresses",
        examples=(
            "Example: '123 Main St; 45 King St W' -> [\"123 Main St\", \"45 King St W\"]\n"
            "Example: '4978A Ch. Queen Mary, 2115 Rue Crescent, 3650 Boul. Saint-Laurent' "
            "-> [\"4978A Ch. Queen Mary\", \"2115 Rue Crescent\", \"3650 Boul. Saint-Laurent\"]\n"
            "Example: '123 Rue Sainte-Catherine, Montreal' -> [\"123 Rue Sainte-Catherine, Montreal\"]\n"
            "Example: '200 Bay St, Toronto and 15 King St W, Toronto' "
            "-> [\"200 Bay St, Toronto\", \"15 King St W, Toronto\"]"
        ),
    )


def resolve_option(raw: str, options: list[str]) -> str:
    """Resolve a numeric choice ('1','2',...) or match text to nearest option.

    Options may have the format "Label — description"; matching uses the full
    string but the label portion (before " — ") is checked first for speed.

    An EXACT match on the whole option wins before any fuzzy matching. Options
    can share a label and differ only in the description (a disambiguation ask
    lists the same venue name at several addresses); the fuzzy loop returns the
    FIRST label hit, so without this an exact answer for option 2 or 3 silently
    resolved to option 1 — and the caller mapped that back to the wrong index.
    """
    raw = (raw or "").strip()
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return options[idx]
    if raw in options:
        return raw
    low = raw.lower()
    for opt in options:
        if opt.lower() == low:
            return opt
    for opt in options:
        label = opt.split(" — ")[0].lower()
        if label.startswith(low) or low in label or low in opt.lower():
            return opt
    return raw


# ── Confirmation detection ────────────────────────────────────────────────────

_CONFIRMATION_WORDS = frozenset({
    "", "yes", "y", "confirm", "ok", "okay", "sure", "correct",
    "right", "yep", "yeah", "sounds good", "go ahead", "continue",
    "proceed", "that's right", "thats right", "looks good", "perfect",
})

# Lead tokens that read as affirmative even with trailing punctuation or a
# tail ("Yes.", "yes please", "yes, do it", "approved") — the exact-membership
# test above misses all of these and reads them as a REJECTION, not a "didn't
# understand". Checked as a leading word/phrase, not substring, so "yesterday"
# or "I don't approve of that" don't match.
_AFFIRMATIVE_LEAD = (
    "yes", "yeah", "yep", "yup", "y", "ok", "okay", "sure", "confirm",
    "confirmed", "approve", "approved", "go ahead", "do it", "proceed",
    "continue", "looks good", "sounds good", "perfect", "correct", "right",
    "that's right", "thats right",
)

# A trailing qualifier after an affirmative lead means the reply isn't a
# clean yes ("yes but make it $500", "sure, except the radius") — this is
# what keeps such a reply from firing a money write or a gate-close while
# still surfacing as "unclear" (re-ask) rather than a silent no.
_AFFIRMATIVE_QUALIFIER_RE = re.compile(
    r"\b(but|except|however|instead|actually|wait|change|unless)\b|\?"
)

_REJECTION_WORDS = frozenset({
    "no", "n", "nope", "nah", "cancel", "stop", "don't", "dont",
    "not yet", "no thanks", "no thank you", "negative",
})


def confirmation_intent(raw: str) -> str:
    """Classify a reply at a yes/no gate as ``"yes"``, ``"no"``, or
    ``"unclear"`` — the shared parser behind every confirmation gate.

    Exact-membership testing (the old ``_is_confirmation``) reads "Yes."
    (trailing punctuation), "yes please" / "yes, do it" (a tail), and
    "approved" (a synonym never listed) as NOT a confirmation — which every
    caller then treated as a REJECTION, not as "ambiguous, ask again". That
    is the single root cause behind three reported symptoms: a builder gate
    silently cancelling an approved change, the same question looping
    forever, and a money-write gate reporting "cancelled by user" for an
    input the user never rejected.

    ``"unclear"`` exists so a caller can re-ask instead of guessing either
    way — an unrelated question or a genuinely ambiguous reply must never be
    read as either yes or no.
    """
    norm = raw.strip().lower()
    # Strip trailing sentence punctuation only ("Yes." -> "yes"); an embedded
    # comma before a tail ("yes, do it") is handled by the lead-token check
    # below, not by stripping punctuation out of the middle of the string.
    norm_stripped = norm.rstrip(".!,;: ")

    if norm_stripped in _CONFIRMATION_WORDS or norm in _CONFIRMATION_WORDS:
        return "yes"
    if norm_stripped in _REJECTION_WORDS or norm in _REJECTION_WORDS:
        return "no"

    for lead in _AFFIRMATIVE_LEAD:
        if norm_stripped == lead or norm_stripped.startswith(lead + " ") or norm_stripped.startswith(lead + ","):
            tail = norm_stripped[len(lead):].lstrip(", ")
            if tail and _AFFIRMATIVE_QUALIFIER_RE.search(tail):
                return "unclear"
            return "yes"

    for word in _REJECTION_WORDS:
        if word and (
            norm_stripped == word
            or norm_stripped.startswith(word + " ")
            or norm_stripped.startswith(word + ",")
        ):
            return "no"

    return "unclear"


def _is_confirmation(raw: str) -> bool:
    return confirmation_intent(raw) == "yes"


# ── Resume / replay detection ─────────────────────────────────────────────────

def is_resuming_step(state: Any, step_key: str) -> bool:
    """True when the graph is replaying an interrupted node from its start.

    On LangGraph resume the interrupted sub-node re-executes from its START, so
    any narration emitted BEFORE that node's ``wizard_interrupt`` call fires a
    SECOND time. ``chat.py`` concatenates every ``assistant_message`` of a turn
    into one saved blob, so the re-fire shows up as the next message opening with
    a verbatim repeat of the previous message's tail (the "robotic repeat" bug).

    Pre-interrupt narration MUST gate on this so it emits only on the first
    (forward) pass.

    ``step_key`` is kept for API compatibility with existing callers but is no
    longer checked against anything — mirrors ``wizard_interrupt``'s own
    ``_is_resume`` fix: comparing against ``state["pending_action"]["step_key"]``
    was permanently False, because the builder path never persists that field
    with a live value. Sourced instead from LangGraph's own ``__pregel_resuming``
    config flag (verified empirically to be per-TASK, not per-call — see
    ``wizard_interrupt``'s identical fix and
    ``tests/test_wizard_interrupt_resume_beat_leak.py``), which only says "this
    node is replaying an answered interrupt", not which step_key. In practice
    that's the granularity every caller actually needs: each caller lives
    inside the one node whose own replay it's asking about, so "some step is
    resuming" and "THIS step is resuming" coincide.
    """
    try:
        from langgraph.config import get_config

        return bool(get_config()["configurable"].get("__pregel_resuming"))
    except Exception:
        return False


# ── Resume payload unwrap ─────────────────────────────────────────────────────
# The frontend echoes the question with the answer: "Q: <prompt>\nA: <answer>".
# Strip the wrapper so the router, option matcher, and node parsers all see the
# bare answer. Non-wrapped values pass through untouched.
_QA_RE = re.compile(r"^Q:\s.*?\nA:\s(.*)$", re.DOTALL)


def _unwrap_qa(raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    m = _QA_RE.match(raw)
    return m.group(1).strip() if m else raw


# ── Per-turn read of the user's raw reply, for the narrator ──────────────────
# Plain-text markers for the build-side mood heuristic. Build answers are mostly
# short confirmations, so we only flag affect on explicit signals + re-answers —
# conservative on purpose, to avoid false "reassurance" on a normal "skip".
_FRUSTRATION_MARKERS = (
    "again", "already said", "already told", "i told you", "told you already",
    "come on", "ugh", "!!", "?!", "for the last time",
)
_CONFUSION_MARKERS = (
    "what do you mean", "what does that mean", "confused", "don't understand",
    "dont understand", "not sure what", "huh?",
)
_EAGER_MARKERS = ("let's go", "lets go", "can't wait", "cant wait", "excited", "love this")


def read_user_turn(result: Any, field_name: Optional[str], bs: dict) -> dict:
    """Heuristic read of the user's raw reply (no LLM) — mirrors the entry-side
    ``user_turn`` so the composer can respond + adapt on build screens too.
    Build turns bypass entry_node and have no spare LLM, so this stays cheap.

    ``phrase`` is the verbatim answer (mirrored back); ``embedded_ask`` is set
    when they slipped a question in; ``mood`` flags affect only on explicit
    signals or a re-answer of the same field; ``engagement`` scales narrator
    length. Widget JSON / sentinel payloads carry no conversational text.

    Shared by ``wizard_interrupt`` (called per-iteration, right after the
    interrupt resolves, so a mid-turn edit reply is fresh for the SAME turn's
    flush) and ``builder_ask`` (called once more after the interrupt returns,
    for durable persistence onto the node diff — see that call site).
    """
    raw = str(result or "").strip()
    is_payload = (not raw) or raw[:1] in ("{", "[")
    low = raw.lower()

    words = len(raw.split())
    if is_payload or words <= 3:
        engagement = "terse"
    elif words >= 12 or "?" in raw:
        engagement = "engaged"
    else:
        engagement = "normal"

    re_answer = field_name is not None and field_name in (bs.get("filled") or {})
    if any(m in low for m in _CONFUSION_MARKERS):
        mood = "confused"
    elif re_answer or any(m in low for m in _FRUSTRATION_MARKERS):
        mood = "frustrated"
    elif any(m in low for m in _EAGER_MARKERS):
        mood = "eager"
    else:
        mood = "neutral"

    return {
        "phrase": None if is_payload else raw[:160],
        "embedded_ask": raw[:160] if (not is_payload and "?" in raw) else None,
        "mood": mood,
        "engagement": engagement,
    }


def _optional_str(value: Any) -> Optional[str]:
    """``value`` if it's a real, non-blank string, else ``None``.

    ``ResumeIntent.question_text`` / ``.answer_value`` are ``Optional[str]``,
    so a real intent is always one or the other. A hand-built test double
    (``MagicMock(lane=..., confidence=...)``) that leaves either field unset
    auto-vends a truthy ``Mock`` for it instead of the ``None`` a real model
    would default to — bare ``if intent.question_text:`` would then treat
    every such double as if the user had asked a question. Strict-typing the
    check is the fix that works for both without touching every test double.
    """
    return value if isinstance(value, str) and value.strip() else None


# ── Scale-aware grounding facts ──────────────────────────────────────────────


def summarize_locations(names: list[str], *, max_named: int = 3) -> str:
    """Render a bounded, human-readable location summary that scales.

    Lists up to ``max_named`` names (Oxford-free, '&' before the last); beyond
    that, switches to a bare count ("5 cities") instead of a long list. Empty
    input → "". This is what keeps the context sentences correct whether there
    is 1 city or 50 — callers and the narrator add bolding, not this helper.

        []                          -> ""
        ["Quebec"]                  -> "Quebec"
        ["Quebec", "Montreal"]      -> "Quebec & Montreal"
        ["A", "B", "C"]             -> "A, B & C"
        ["A", "B", "C", "D", "E"]   -> "5 cities"
    """
    clean = [str(n).strip() for n in (names or []) if str(n or "").strip()]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    if len(clean) <= max_named:
        return f"{', '.join(clean[:-1])} & {clean[-1]}"
    return f"{len(clean)} cities"


def _pluralize(label: str, count: int | None) -> str:
    """Naive count-aware pluralization for a POI/type label used in fallbacks.

    Best-effort only — the narrator handles real phrasing; this just keeps the
    deterministic fallback readable ("142 casino" → "142 casinos"). Leaves
    multi-word or already-plural labels alone when a trailing 's' is present.
    """
    base = (label or "").strip()
    if not base or count == 1:
        return base
    if base.endswith(("s", "x", "z", "ch", "sh")):
        return base
    return base + "s"


def build_context_facts(state: Any) -> dict[str, Any]:
    """Assemble scale-aware, concrete grounding facts from AgentState.

    Pure state read (mirrors the field reads in :func:`_session_summary` and
    ``narrator.grounding``). Returns AGGREGATES only — a POI ``poi_count`` +
    ``poi_type`` and a bounded ``location_summary`` — never individual POI
    names, so the narrated sentence reads correctly whether there is 1 POI or
    several hundred across many cities. Keys whose value is unknown are omitted
    so the composer only ever sees facts that are actually present.
    """
    try:
        user_info = (state or {}).get("user_info") or {}
        geo_data = (state or {}).get("geo_data") or {}
    except AttributeError:
        return {}

    facts: dict[str, Any] = {}

    biz = (user_info.get("business_name") or "").strip()
    if biz:
        facts["business_name"] = biz

    loc_names = [
        (l.get("location_name") or l.get("formatted_address") or "")
        for l in (geo_data.get("locations") or [])
    ]
    loc_names = [n for n in loc_names if n]
    if loc_names:
        facts["location_summary"] = summarize_locations(loc_names)
        facts["location_count"] = len(loc_names)

    poi_count = geo_data.get("pois_found")
    if poi_count is None:
        targetable = geo_data.get("targetable_pois") or []
        poi_count = len(targetable) or None
    if poi_count:
        facts["poi_count"] = poi_count
        poi_types = geo_data.get("poi_types") or []
        facts["poi_type"] = _pluralize(str(poi_types[0]) if poi_types else "spot", poi_count)

    # The filtered headline, never the raw superset — see audience_headline_count.
    from app.graph.maid_query import audience_headline_count

    audience_count = audience_headline_count(geo_data)
    if audience_count is not None:
        facts["audience_count"] = audience_count

    objective = user_info.get("campaign_objective")
    if objective:
        facts["objective"] = objective
    budget = user_info.get("budget")
    if budget:
        facts["budget"] = budget
    method = geo_data.get("targeting_method")
    if method:
        facts["method"] = method

    return facts


# ── Session summary helper ───────────────────────────────────────────────────


def _session_summary(state: Any) -> str:
    """Build a structured one-liner describing the current session state.

    Used as the ``context`` argument to ``wizard_interrupt`` so that
    ``wizard_ask`` (the LLM that generates each wizard step's user-facing
    message) can ground every reply in real business / audience / geo /
    audience-extraction details — not say generic things like "around each
    spot" when the user runs a shawarma shop.

    Degrades gracefully — only includes fields actually present in state.
    """
    try:
        user_info = (state or {}).get("user_info") or {}
        geo_data = (state or {}).get("geo_data") or {}
        ws_geo = (state or {}).get("geo_wizard_state") or {}
        ws_maid = (state or {}).get("maid_wizard_state") or {}
        ws_camp = (state or {}).get("campaign_wizard_state") or {}
    except AttributeError:
        return "Starting new session"

    parts: list[str] = []

    biz = user_info.get("business_name")
    industry = user_info.get("industry") or user_info.get("business_description")
    if biz and industry:
        parts.append(f"Business: {biz} ({industry})")
    elif biz:
        parts.append(f"Business: {biz}")
    elif industry:
        parts.append(f"Business: {industry}")

    audience_bits: list[str] = []
    if user_info.get("target_audience"):
        audience_bits.append(str(user_info["target_audience"]))
    age_min = user_info.get("target_age_min")
    age_max = user_info.get("target_age_max")
    if age_min and age_max:
        audience_bits.append(f"{age_min}-{age_max}")
    gender = user_info.get("target_gender")
    if gender and gender != "all":
        audience_bits.append(str(gender))
    if user_info.get("location"):
        loc = user_info["location"]
        loc_str = ", ".join(loc) if isinstance(loc, list) else loc
        audience_bits.append(f"in {loc_str}")
    if audience_bits:
        parts.append("Audience: " + ", ".join(audience_bits))

    method = geo_data.get("targeting_method") or ws_geo.get("targeting_method")
    if method:
        geo_bits = [method]
        det_type = geo_data.get("targeting_type") or ws_geo.get("deterministic_type")
        if det_type:
            geo_bits.append(str(det_type))
        pois = geo_data.get("pois_found")
        if pois:
            geo_bits.append(f"{pois} POI(s)")
        poi_types = geo_data.get("poi_types") or (ws_geo.get("extra_inputs") or {}).get("poi_types_list")
        if poi_types:
            sample = ", ".join(str(p) for p in poi_types[:3])
            geo_bits.append(f"types: {sample}")
        locs = geo_data.get("locations") or []
        if locs:
            loc_names = [l.get("location_name") or l.get("formatted_address", "") for l in locs[:2]]
            loc_names = [n for n in loc_names if n]
            if loc_names:
                geo_bits.append(f"loc: {', '.join(loc_names)}")
        radius_km = geo_data.get("poi_radius_km")
        if radius_km:
            geo_bits.append(f"radius {radius_km} km")
        parts.append("Geo: " + " — ".join(geo_bits))

    from app.graph.maid_query import audience_headline_count

    # The filtered headline, never the raw superset. This summary is the
    # narration context for the Meta-connect turns (executors/media.py), which
    # used to say "the audience of 3,506" one turn after the reveal said the
    # filter had narrowed it to 1,277.
    maid_count = audience_headline_count(geo_data)
    if maid_count:
        maid_bits = [f"{maid_count:,} visitors"]
        _raw_count = geo_data.get("maid_count")
        if _raw_count and _raw_count != maid_count:
            from app.services.maid_store import describe_audience_filter

            _chips = ", ".join(describe_audience_filter(geo_data.get("audience_filter")))
            maid_bits.append(
                f"narrowed from {_raw_count:,}" + (f" by {_chips}" if _chips else "")
            )
        conf = geo_data.get("maid_count_confidence")
        if conf:
            maid_bits.append(f"{conf}% confidence")
        if ws_maid.get("lookback_days"):
            maid_bits.append(f"last {ws_maid['lookback_days']}d")
        if ws_maid.get("poi_radius_m"):
            maid_bits.append(f"{ws_maid['poi_radius_m']} m around each POI")
        parts.append("MAID: " + ", ".join(maid_bits))

    obj = user_info.get("campaign_objective")
    if obj:
        parts.append(f"Objective: {obj}")
    budget = user_info.get("budget")
    if budget:
        parts.append(f"Budget: {budget}")
    pixel = user_info.get("pixel_status")
    if pixel:
        parts.append(f"Pixel: {pixel}")
    url = user_info.get("website_url")
    if url:
        parts.append(f"Site: {url}")

    return "; ".join(parts) or "New session — no business details yet"


# ── Auto-fill log helper ─────────────────────────────────────────────────────

_AUTO_FILL_CONFIDENCE_THRESHOLD = 0.95


def maybe_log_auto_fill(
    state: Any,
    *,
    prefill: Any,
    prefill_confidence: float | None,
    prefill_source: str | None,
    field_label: str,
) -> list[dict]:
    """Return an updated `auto_filled_log` list.

    Append a new entry when the step is about to silently auto-advance
    (prefill present, confidence ≥ 0.95).  Otherwise return the existing log
    unchanged.  Caller merges the return into its state diff:
    ``return {..., "auto_filled_log": maybe_log_auto_fill(...)}``.

    The chatbot reads this log on its next turn, surfaces the entries to the
    user, then drains it by returning ``"auto_filled_log": []``.
    """
    try:
        log = list((state or {}).get("auto_filled_log") or [])
    except AttributeError:
        log = []
    if (
        prefill is not None
        and (prefill_confidence or 0) >= _AUTO_FILL_CONFIDENCE_THRESHOLD
    ):
        log.append({
            "field": field_label,
            "value": str(prefill),
            "source": prefill_source or "intent_extraction",
        })
    return log


# ── Pre-interrupt LLM message + interrupt ─────────────────────────────────────

async def wizard_ask(
    writer: Any,
    context: str,
    question_hint: str,
    options: list[str] | None = None,
    prefill: str | None = None,
    prefill_source: str | None = None,
    state: Any = None,
    step_key: str | None = None,
    next_up: str | None = None,
    action_type: str | None = None,
) -> None:
    """Single LLM call per interrupt — emits a conversational assistant_message
    before the input widget appears.

    Runs BEFORE interrupt(), so the user sees a warm AI message above the widget.
    When options are provided (option_selection steps), the LLM explains the key
    choices in natural language rather than listing them verbatim.
    """
    # Thin wrapper over the narrator's ``step_frame`` role. Grounding comes from
    # the live state via the GroundingPack, so the legacy ``context`` string is
    # unused here (retained in the signature for caller compatibility). Output is
    # cached by (step_frame, facts, session_fp) and jargon-scrubbed by the
    # narrator. ``narrate`` never raises — it has its own deterministic fallback.
    #
    # Fallback = the widget's own question. Empty fallback historically caused
    # naked input widgets with NO assistant text above them when LLM gen failed
    # (e.g. campaign_collect_business_name #8478 in repro thread).
    # Scale-aware grounding aggregates (business / bounded location summary /
    # poi_count+type / audience_count) merged in so EVERY step_frame line can be
    # concrete without per-step wiring. Returns {} on cold state (early steps),
    # and uses the BOUNDED location_summary ("Quebec & Montreal" / "5 cities")
    # rather than the raw pack's full list — so the narrator never enumerates 50
    # locations. Step keys (step/question/options/next_up) win on key collisions.
    _ctx_facts = build_context_facts(state)
    await narrate(
        Utterance(
            role="step_frame",
            facts={
                **_ctx_facts,
                "step": step_key,
                "question": question_hint,
                "options": list(options or [])[:6],
                # The step's widget type. For "text_input" the widget is hidden
                # (answered in the chat box), so the composer must END on the
                # literal question; other types keep the widget below the framing.
                "action_type": action_type,
                "prefill": prefill,
                "prefill_source": prefill_source,
                # Forward-preview of the step AFTER this one (from the registry's
                # ``preview_hint``). Lets step_frame close with a short "…then X"
                # so the user always knows where the flow is heading. None ⇒ omit.
                "next_up": next_up,
            },
            max_chars=600,
            step_key=step_key,
            fallback=(question_hint or "").strip(),
        ),
        state,
        writer,
    )


async def wizard_milestone_narrate(
    writer: Any,
    state: Any,
    milestone: str,
    facts: dict[str, Any],
    *,
    fallback: str | None = None,
    skip_on_resume_of: str | None = None,
) -> dict[str, Any]:
    """Emit an LLM-narrated milestone message at a wizard stage boundary.

    ``skip_on_resume_of`` is the step_key of the ``interrupt`` that immediately
    follows this milestone in the SAME sub-node. When the node is being replayed
    to resume that interrupt (see :func:`is_resuming_step`), the milestone is a
    duplicate of what already shipped last turn, so it is suppressed entirely
    (no LLM call, no emit, empty merge fragment). Omit it for milestones that do
    NOT precede an interrupt in their node (stage_open / post_result / handoff
    entry nodes) — those run once per turn and must always emit.

    Thin wrapper over the narrator's ``milestone`` role — the narrator owns
    grounding, caching (by ``milestone:facts_fp:session_fp``), jargon scrub, and
    emit. ``WIZARD_NARRATOR_ENABLED`` stays a hard kill-switch that emits the
    plain fallback with no LLM call.

    Returns a state-merge fragment the caller MUST splat into its node return
    dict so the cache entry survives the checkpoint round-trip:

        update = await wizard_milestone_narrate(writer, state, "geo_pois_found",
                                                facts={...}, fallback="...")
        return {**existing_update, **update}
    """
    if skip_on_resume_of and is_resuming_step(state, skip_on_resume_of):
        return {}

    facts = facts or {}

    # No caller-written fallback means none: the composer's own retry line beats
    # a machine string like "geo_pois_found: poi_count=12" reaching the user.
    if not settings.WIZARD_NARRATOR_ENABLED:
        if writer is not None and fallback:
            writer({"type": "assistant_message", "content": fallback})
        return {}

    result = await narrate(
        Utterance(
            role="milestone",
            facts={**facts, "milestone_kind": milestone},
            max_chars=settings.NARRATOR_REVEAL_MAX_CHARS,
            fallback=fallback,
        ),
        state,
        writer,
    )
    return {"wizard_milestone_cache": result.cache_update} if result.cache_update else {}


async def wizard_handoff_narrate(
    writer: Any,
    state: Any,
    stage: str,
    facts: dict[str, Any],
    *,
    fallback: str | None = None,
    skip_on_resume_of: str | None = None,
) -> dict[str, Any]:
    """Emit an LLM-narrated between-wizard handoff at a stage boundary.

    ``skip_on_resume_of`` — same contract as :func:`wizard_milestone_narrate`:
    pass the step_key of the interrupt that follows this handoff in the SAME
    sub-node so it is not re-emitted when that interrupt is resumed.

    Thin wrapper over the narrator's ``handoff`` role. Unlike ``milestone`` (a
    pure result reveal), the handoff role emits FOUR beats — recap, why-next,
    a PREVIEW of what the next wizard will ask, and an invite — so the user
    always knows where the flow is going. ``stage`` is the boundary id
    (``geo_to_maid`` / ``maid_to_campaign`` / ``campaign_to_media``) the role's
    exemplars key off.

    Same return contract as :func:`wizard_milestone_narrate`: the caller MUST
    splat the returned ``{"wizard_milestone_cache": ...}`` fragment into its node
    return so the cache entry survives the checkpoint round-trip.
    """
    if skip_on_resume_of and is_resuming_step(state, skip_on_resume_of):
        return {}

    facts = facts or {}

    # Same rule as wizard_milestone_narrate: no caller fallback, no machine text.
    if not settings.WIZARD_NARRATOR_ENABLED:
        if writer is not None and fallback:
            writer({"type": "assistant_message", "content": fallback})
        return {}

    result = await narrate(
        Utterance(
            role="handoff",
            facts={**facts, "stage": stage},
            max_chars=settings.NARRATOR_REVEAL_MAX_CHARS,
            fallback=fallback,
        ),
        state,
        writer,
    )
    return {"wizard_milestone_cache": result.cache_update} if result.cache_update else {}


def _resolve_edit_base(state: Any, bs: dict, supplied: dict | None) -> dict:
    """``current_edit_base``'s result, with ``supplied`` overlaid on top.

    Caller-supplied keys win — they can be fresher than the checkpoint mid-
    geocode (e.g. a confirm step re-showing a just-edited location list
    before it's persisted to ``bs``). Fields the caller didn't think to pass
    still get a base to merge against instead of silently defaulting to
    "nothing exists yet".

    Lazily imported (mirrors the ``_step_to_slot`` import a few call sites
    below) to avoid a wizard_helpers <-> builder import cycle; swallows any
    failure back to whatever the caller supplied, since a missing base is a
    smaller problem than a crashed interrupt.
    """
    try:
        from app.graph.builder.edits import current_edit_base

        computed = current_edit_base(state, bs)
    except Exception:
        computed = {}
    if not computed:
        return supplied or {}
    return {**computed, **(supplied or {})}


async def wizard_interrupt(
    writer: Any,
    step_key: str,
    context: str,
    state: Any = None,
    next_step_key: str | None = None,
    prompt_override: str | None = None,
    options_override: list[str] | None = None,
    action_type_override: str | None = None,
    field_override: str | None = None,
    skip_ask: bool = False,
    prefill: str | None = None,
    prefill_source: str | None = None,
    prefill_confidence: float | None = None,
    progress: list | None = None,
    locations: list | None = None,
    extra: dict | None = None,
    rerun_on_edit: set[str] | None = None,
    edit_base: dict | None = None,
    repeat_events: list[dict] | None = None,
) -> ResumeResult:
    """Look up step config from STEP_PROMPTS, emit an AI message, then interrupt().

    One LLM call (wizard_ask) fires BEFORE interrupt() to generate a conversational
    message. Pass skip_ask=True when the caller has already emitted its own
    assistant_message (e.g. recommendation nodes that format structured output).

    Pass prefill=<value> when a prior value was extracted by entry_node.
    The interrupt will show a confirmation prompt; if the user confirms (or sends
    a blank/affirmative reply), the prefill value is returned unchanged.

    Pass state=state to enable resume detection. On LangGraph resume, the node
    re-executes from START before interrupt() returns the value. Passing state
    allows wizard_interrupt to detect this replay and skip duplicate emissions.

    Pass ``rerun_on_edit={field, ...}`` when the CALLER owns re-execution for an
    edit to those fields (e.g. a confirm step whose map is produced by re-geocoding
    upstream). An edit-lane reply targeting one of those fields is dispatched
    normally (the merged value lands in ``ResumeResult.edits[target_field]``) and
    then RETURNS immediately instead of looping to re-show the same widget — so the
    caller can apply the edit, re-run, and re-interrupt with fresh output. Edits to
    other fields, and the reject/query lanes, keep looping in place as before.
    Pair it with ``edit_base`` so an append/remove merges against the field's
    current value.

    Pass ``repeat_events=[{...}, ...]`` for side-channel events the widget needs
    ALONGSIDE it every time it renders — e.g. the geo confirm step's
    ``map_data``. They are re-emitted immediately before each ``pending_action``,
    including on the off-path re-ask iterations (reject / query / non-rerun
    edit), so the widget is never shown without the visual it refers to. Emit
    them via this parameter rather than once before the call: an in-loop re-ask
    does not return to the caller, so a caller-side emission fires only once and
    later iterations render a widget pointing at a map that isn't there.

    An entry may also be a zero-arg callable instead of a prebuilt dict — it is
    invoked fresh at EVERY pause rather than captured once at call time. Needed
    when something INSIDE this same loop iteration can mutate the state the
    event is built from (e.g. a handoff-lane tool call reached via `unhandled`/
    query dispatch, which — unlike an edit — never exits via ``rerun_on_edit``
    to rebuild a fresh event): a plain dict would silently replay stale data on
    the next pause. Return ``None`` from the callable to skip that entry for
    one pause (e.g. nothing to show yet); it is simply not written.
    """
    cfg = STEP_PROMPTS[step_key]

    # ── Resume detection ──────────────────────────────────────────────────────
    # When LangGraph resumes from interrupt(), the entire node re-executes.
    # Skip all pre-interrupt emissions if resuming to avoid duplicate UI events.
    #
    # NOT sourced from state["pending_action"]["step_key"] (the old check) —
    # the builder path never persists that field with a live value (every
    # builder_ask/media.py return either omits it or writes None; see
    # service.py's own comment on this), so that comparison was permanently
    # False. The stale-beat discard below (`_narrator_drain` in the `else`
    # branch) and every `skip_on_resume_of` caller were dead code as a result:
    # a beat re-added while THIS node replays a resolved interrupt survived
    # into the NEXT gate's `flush_narration` and got woven into its message
    # (the reported bug — a radius-picker turn narrated as a POI-confirmation
    # reveal instead).
    #
    # Sourced instead from LangGraph's own `__pregel_resuming` config flag —
    # True exactly while THIS task is re-executing to replay an already-
    # answered `interrupt()`, and (verified empirically — see
    # tests/test_wizard_interrupt_resume_beat_leak.py) absent/falsy for a
    # sibling node running for the first time during the SAME `Command(
    # resume=...)` call. Per-task, not per-call, which is exactly the
    # granularity "is this a resume" needs: a `Command(resume=...)` call
    # that replays gate A and then runs gate B fresh must not also mark
    # gate B as resuming.
    _is_resume = False
    try:
        from langgraph.config import get_config

        _is_resume = bool(get_config()["configurable"].get("__pregel_resuming"))
    except Exception:
        _is_resume = False

    _existing_pending = {}
    if state is not None:
        try:
            _existing_pending = state.get("pending_action") or {}
        except AttributeError:
            _existing_pending = {}

    # ── Auto-advance on high-confidence prefills ──────────────────────────────
    # When confidence >= 0.95 AND NOT A RESUME, skip the interrupt entirely
    # and return the prefill immediately. Emits only a "thinking" event so this
    # path is replay-safe and idempotent.
    _AUTO_ADVANCE_THRESHOLD = 0.95
    if (
        prefill is not None
        and prefill_confidence is not None
        and prefill_confidence >= _AUTO_ADVANCE_THRESHOLD
        and not _is_resume
    ):
        writer({"type": "thinking", "content": (
            f"Auto-advance {step_key}: confidence={prefill_confidence} "
            f"value={prefill!r} source={prefill_source}"
        )})
        _field_label = (cfg.get("field") or step_key).replace("_", " ")
        _src_label = {
            "intent_extraction": "your earlier message",
            "website_enrichment": "your website",
            "geo_wizard": "the geo step",
            "user_provided": "an earlier answer",
        }.get(prefill_source or "", "earlier context")
        _auto_fallback = (
            f"Auto-filled **{_field_label}** = `{prefill}` — inferred from "
            f"{_src_label}. Reply with anything to override before the next step."
        )
        await narrate(
            Utterance(
                role="auto_advance",
                facts={"field": _field_label, "value": str(prefill), "source": _src_label},
                max_chars=settings.WIZARD_NARRATOR_MAX_CHARS,
                fallback=_auto_fallback,
            ),
            state,
            writer,
        )
        return ResumeResult(prefill)

    # ── Auto-advance while "do the rest for me" is active ─────────────────────
    # bs["_auto_default_remaining"], set by interject_tools.delegate_rest()
    # (Phase 2's handoff lane). Same skip-the-interrupt shape as the
    # high-confidence-prefill block above — but NEVER for a GATE step. Gates
    # are confirm screens for real, sometimes irreversible work (the plan
    # editor, publish/go-live) — "do the rest for me" must not silently wave
    # one through; the tool's own docstring promises this. A gate step still
    # interrupts normally; only ordinary asks fast-forward. Reuses the exact
    # same fallback-value expression the escape menu's "use default" action
    # already ships with (`_match_escape` below) — not a new risk class, the
    # same one, just reached without two off-path turns first.
    _bs = ((state or {}).get("campaign_builder_state") or {}) if state is not None else {}

    # Default edit_base to the CURRENT value of every appendable field, filled
    # in under whatever the caller already supplied. Only 3 of 8
    # wizard_interrupt() call sites ever passed one (2 of those only for the
    # single field their own confirm owns), so an "also add X" typed at any
    # other interrupt — the OAuth step, a disambiguation loop, a media ask —
    # merged against an empty base and REPLACED the list instead of
    # appending to it. This is the one seam every caller routes through, so
    # the default belongs here, not at each of the five bare call sites.
    edit_base = _resolve_edit_base(state, _bs, edit_base)

    if _bs.get("_auto_default_remaining") and not _is_resume and prefill is None:
        from app.graph.builder.edits import _step_to_slot
        from app.graph.builder.slots import GATE_SLOTS

        _slot_name = _step_to_slot(step_key)
        _default_value = (cfg.get("options") or [""])[0]
        if _slot_name not in GATE_SLOTS and _default_value:
            writer({"type": "thinking", "content": (
                f"Auto-default {step_key} (delegate_rest active): {_default_value!r}"
            )})
            return ResumeResult(_default_value)

    if _is_resume:
        writer({"type": "thinking", "content": f"Resume detected: {step_key} — skipping pre-interrupt emissions"})
        # Restore prefill from the previous pending_action when the caller lost it on re-execution.
        # This handles nodes that compute prefill dynamically (not from state/preextracted).
        if prefill is None and _existing_pending.get("prefill"):
            prefill = _existing_pending.get("prefill")
            prefill_source = prefill_source or _existing_pending.get("prefill_source")
            prefill_confidence = prefill_confidence or _existing_pending.get("prefill_confidence")

    # Single-interrupt mode: what an earlier reply on THIS step did to the
    # suggested value — an edit to the active field ("actually 500") sets it, a
    # reject clears it — lived in the old loop's locals. Restore it, or the
    # re-ask (a fresh task) re-derives the original suggestion and the user's
    # correction silently vanishes.
    _single = bool(_bs.get("_single_interrupt"))
    _attempts = dict((_bs.get("_ask_attempts") or {}).get(step_key) or {}) if _single else {}
    if "prefill" in _attempts:
        prefill = _attempts["prefill"]
        prefill_source = _attempts.get("prefill_source")
        prefill_confidence = _attempts.get("prefill_confidence")

    base_prompt = prompt_override or cfg["prompt"]
    if prefill is not None:
        effective_prompt = f"{base_prompt}\n\n_Suggested: **{prefill}** — or enter your own value._"
        effective_context = f"{context}; pre-filled: {prefill!r}"
    else:
        effective_prompt = base_prompt
        effective_context = context

    pending: PendingAction = {
        "action_type": action_type_override or cfg["action_type"],
        "options": options_override if options_override is not None else cfg.get("options", []),
        "prompt": effective_prompt,
        "field": field_override or cfg["field"],
        "step_key": step_key,
        "prefill": prefill,
        "prefill_source": prefill_source,
        "prefill_confidence": prefill_confidence,
        "stepper": cfg.get("stepper"),
        "steppers": cfg.get("steppers"),
        "progress": progress,
        "title": cfg.get("title"),
        "subtitle": cfg.get("subtitle"),
    }
    if locations:
        pending["locations"] = locations
    if extra:
        # Widget-specific payload merged onto the pending action (e.g. the
        # campaign_content surface's ad_copy variants). Frontend-only fields;
        # they ride the checkpointed pending_action so they survive reconnect.
        pending.update(extra)

    # ── Bounded resume-router loop ────────────────────────────────────────────
    # Iteration 0 reproduces the historic single-shot interrupt: pre-interrupt
    # wizard_ask + pending emission (skipped on replay). Iterations 1+ run only
    # when the resume-router classifies the user's reply as an off-path lane
    # (reject / query / edit). Each iteration re-emits pending_action — that is
    # safe because the frontend dedupes by step_key.
    edits: dict[str, Any] = {}

    # Single-interrupt mode (settings.BUILDER_SINGLE_INTERRUPT, pinned per build
    # by builder_plan): ONE interrupt() per call. A reply that doesn't answer the
    # step returns `answered=False` and the caller ends its task; the planner
    # applies any stashed edit and re-dispatches, so the step is re-asked as a
    # fresh task. The off-path counters that used to live in this loop's locals
    # therefore persist across tasks in bs["_ask_attempts"][step_key].
    iteration = int(_attempts.get("total") or 0)
    _reject_budget = int(_attempts.get("reject") or 0)
    _first_pass = True

    def _save_attempts(*, clear: bool) -> None:
        live_bs = (state or {}).get("campaign_builder_state") if isinstance(state, dict) else None
        if not _single or not isinstance(live_bs, dict):
            return
        att = dict(live_bs.get("_ask_attempts") or {})
        if clear:
            att.pop(step_key, None)
        else:
            att[step_key] = {
                "total": iteration, "reject": _reject_budget,
                # The (possibly edited / cleared) suggestion, restored on entry.
                "prefill": pending.get("prefill"),
                "prefill_source": pending.get("prefill_source"),
                "prefill_confidence": pending.get("prefill_confidence"),
            }
        live_bs["_ask_attempts"] = att

    def _resolved(value: Any) -> ResumeResult:
        """Return the answer, recording the exchange in the transcript ledger.

        Called only once the step is actually resolved, so an interrupt that took
        several off-path re-asks still yields exactly one pair. ``raw`` is the
        loop's local, assigned by the interrupt() below before any call lands here.
        """
        record_qa(state, step_key, base_prompt, _ledger_answer(raw, value))
        _save_attempts(clear=True)
        return ResumeResult(value, edits=edits)

    def _unanswered() -> ResumeResult:
        """Single-interrupt mode: the reply didn't answer this step. Hand it
        back (with any edits) so the caller ends its task; see ``_single``."""
        _save_attempts(clear=False)
        return ResumeResult(raw, edits=edits, answered=False)

    while True:
        if _reject_budget >= _MAX_NONANSWER_LOOPS or iteration >= _MAX_TOTAL_LOOPS:
            writer({"type": "thinking", "content": (
                f"wizard_interrupt {step_key}: budget exhausted "
                f"(reject={_reject_budget} total={iteration}) — raising WizardExitRequested"
            )})
            # Reset, or the next visit to this step (after the user says
            # "continue") would exit again before asking anything.
            _save_attempts(clear=True)
            raise WizardExitRequested()

        # The first pass honours the existing _is_resume skip. Later in-loop
        # iterations (legacy mode) always emit fresh.
        skip_emit = _is_resume and _first_pass
        _first_pass = False

        if not skip_emit:
            if iteration == 0 and not skip_ask:
                resolved_options = options_override if options_override is not None else cfg.get("options", [])
                await wizard_ask(
                    writer, effective_context, effective_prompt,
                    options=resolved_options,
                    prefill=pending.get("prefill"),
                    prefill_source=pending.get("prefill_source"),
                    state=state,
                    step_key=step_key,
                    next_up=cfg.get("preview_hint"),
                    action_type=action_type_override or cfg["action_type"],
                )

            # Frustration jumps the queue — a user who is already annoyed
            # should not have to survive _ESCAPE_MENU_THRESHOLD more turns to
            # find the way out. mood is a per-turn read (state["user_turn"]),
            # not a counter, so this fires the very turn it's detected.
            _frustrated = False
            try:
                _frustrated = ((state or {}).get("user_turn") or {}).get("mood") == "frustrated"
            except (AttributeError, TypeError):
                _frustrated = False
            if iteration >= _ESCAPE_MENU_THRESHOLD or _frustrated:
                pending["escape_menu"] = [
                    "use default", "explain", "exit wizard",
                ]

            # generate_chips (suggestion chips for the active step) is NOT called
            # here: it is a Gemini call on every pause, but pending["suggestions"]
            # has no reader — ChatContext.tsx stores it and types.ts types it, but
            # no widget renders it (WidgetAssistRow only renders escape_menu,
            # above). Re-enable this call when a chips row ships on the frontend;
            # generate_chips itself is untouched and ready.

            # Compose + emit ONE message from every beat buffered this turn
            # (prior milestone/stage reveals + this step's framing) right before
            # the widget renders, so the user sees a single coherent message
            # above the input — not a stack of independently-generated lines.
            # Skipped on a resume replay via the surrounding `if not skip_emit`.
            # Fill the brief pre-first-token gap (the LLM's thinking window on a
            # rich/Pro turn) with motion, but only when beats are actually
            # buffered. source != "punk" → not persisted.
            if _narrator_peek(state):
                writer({"type": "thinking", "source": "system", "content": "Pulling it together..."})
            await flush_narration(state, writer)

            # Side-channel visuals the widget refers to (geo confirm map, …) —
            # re-emitted on every render, including off-path re-asks, so the
            # widget and its map never drift apart.
            for _entry in (repeat_events or []):
                # A callable is evaluated at EVERY pause, not once at call
                # time — see this parameter's docstring for why (a handoff-
                # lane mutation inside this same loop, with no rerun_on_edit
                # exit to rebuild a fresh event). Plain dicts pass through.
                _ev = _entry() if callable(_entry) else _entry
                # Some events (the maid map) can only be rebuilt with a DB
                # round trip — the entry is an async function, so calling it
                # above returns a coroutine rather than the event itself.
                if inspect.isawaitable(_ev):
                    _ev = await _ev
                if _ev:
                    writer(_ev)

            writer({"type": "input_mode", "mode": "widget"})
            writer({"type": "pending_action", "content": pending})
            writer({"type": "thinking", "content": (
                f"Interrupting: {step_key} (iter={iteration})"
            )})
        else:
            # Resume replay: the flush above is skipped, but the node re-ran its
            # pre-interrupt code and may have RE-ADDED framing beats (e.g. the geo
            # disambiguation beat, whose per-name guard lives in un-persisted ws)
            # to this turn's buffer. Those beats were already shown on the pausing
            # turn — discard them here so they don't leak forward and get woven
            # into a LATER pause's flush (the duplicated "clarify city or province"
            # on the confirm screen). Genuinely-new beats added AFTER this resumed
            # interrupt are still buffered and reach the next pause normally.
            _drained = _narrator_drain(state)
            if _drained:
                writer({"type": "thinking", "content": (
                    f"Resume replay {step_key}: discarded {len(_drained)} "
                    "stale pre-interrupt beat(s) already shown last turn"
                )})

        # Stamp this interrupt's position in the task so the /resume stream can
        # compute how many replayed `resume_boundary` events to skip (= index + 1)
        # and forward only the genuinely-new events. Read `len(scratchpad.resume)`
        # (a pure read; do NOT call interrupt_counter() — it mutates). Stamp onto a
        # COPY so the already-emitted SSE pending_action stays clean; only the
        # persisted interrupt value carries `_interrupt_index`. Best-effort: a
        # missing stamp makes the stream gate a no-op (see resume_preflight /
        # chat.py). Re-stamped each loop iteration so a re-ask gets the right index.
        _iv = pending
        try:
            from langgraph.config import get_config

            _sp = get_config()["configurable"].get("__pregel_scratchpad")
            if _sp is not None:
                _iv = {**pending, "_interrupt_index": len(getattr(_sp, "resume", None) or [])}
        except Exception:
            pass
        raw = _unwrap_qa(interrupt(_iv))
        # Resume boundary. interrupt() returning here IS the resume point: on
        # replay the node re-emits its pre-interrupt narration (a duplicate)
        # BEFORE this line, then the genuinely-new work runs AFTER it. The
        # persist layer (chat.py) resets its capture buckets on this typed
        # event so only post-last-resume events are saved — a structural signal,
        # not a string match on the thinking line below.
        writer({"type": "resume_boundary", "step_key": step_key, "iteration": iteration})

        # Refresh state["user_turn"] for THIS reply before any further work —
        # a mid-turn edit (_dispatch_edit_intent returns False below) loops
        # back to re-interrupt without ever returning to builder_ask, so
        # without this the NEXT flush_narration (top of the next iteration)
        # would compose against last turn's phrase/mood/embedded_ask.
        # builder_ask's own _read_user_turn call (after this function returns)
        # re-derives the same value from the final `result` — this is the
        # in-loop copy that keeps every intermediate iteration fresh too.
        if state is not None:
            try:
                from app.graph.builder.edits import _step_to_slot

                state["user_turn"] = read_user_turn(raw, _step_to_slot(step_key), _bs)
            except Exception:
                pass
        writer({"type": "thinking", "content": (
            f"Resumed {step_key} iter={iteration}: {raw!r}"
        )})

        # The audience layer-builder's commit is an exact structured edit: it
        # must skip the sentinel check below (which reads any JSON as "confirm")
        # and the classifier, and lands in the same edit-lane dispatch.
        _panel_intent = audience_panel_intent(raw)

        # Sentinel widget payloads short-circuit straight to the confirm lane.
        if _panel_intent is None and is_sentinel_resume(raw):
            if prefill is not None and _is_confirmation(raw):
                return _resolved(prefill)
            return _resolved(raw)

        # Escape-menu short-circuit — FIRST, ahead of the fuzzy option match below:
        # `resolve_option` could fuzzy-match "exit wizard" onto a real option
        # and swallow it. These are exact matches, so they are unambiguous.
        # The menu is attached to `pending` above at
        # iteration >= _ESCAPE_MENU_THRESHOLD, but nothing ever read it back: the
        # check above matches `pending["options"]` only, so pressing "exit wizard"
        # fell through to the classifier and merely burned another iteration
        # toward the budget it was supposed to escape. These are the deterministic
        # ways out of the loop, so they run before any LLM.
        _escape = _match_escape(raw, pending.get("escape_menu"))
        if _escape:
            writer({"type": "thinking", "content": (
                f"resume_router/{step_key} escape={_escape!r} (iter={iteration})"
            )})
            if _escape == "exit wizard":
                # Progress is preserved — the builder's exit handlers keep the
                # scratch and only clear next_action.
                raise WizardExitRequested()
            if _escape == "use default":
                _fallback = pending.get("prefill")
                if _fallback in (None, ""):
                    _fallback = (cfg.get("options") or [""])[0]
                return _resolved(_fallback)
            # "explain" — answer in place, then re-show the same widget.
            await narrate(
                Utterance(
                    role="sidebar_answer",
                    facts={"question": f"what does '{base_prompt}' mean and what should I pick?",
                           "step": step_key, "active_prompt": base_prompt},
                    max_chars=400,
                    step_key=step_key,
                    fallback=f"This step decides **{(cfg.get('field') or step_key).replace('_', ' ')}**.",
                ),
                state,
                writer,
            )
            iteration += 1
            if _single:
                return _unanswered()
            continue

        # Option-click short-circuit: when the reply selects one of the widget's own
        # options it is ALWAYS an answer — never an off-path lane — even if the option
        # text contains words like "No" (e.g. "No, I'll set it manually"). Skips the
        # classifier (which would mis-read such phrasing as a reject) and costs $0.
        _opts = pending.get("options") or []
        if _panel_intent is None and _opts and resolve_option(raw, _opts) in _opts:
            writer({"type": "thinking", "content": (
                f"resume_router/{step_key} lane=confirm (matched widget option)"
            )})
            return _resolved(raw)

        # Phase 3 rollout flag — routes to the tool-calling classifier
        # backend instead of the lane-JSON one. Both return the identical
        # ResumeIntent shape, so nothing below this line needs to know or
        # care which one ran (see resume_router.py's Phase 3 section
        # docstring for why the dispatch block itself never changes).
        _classify = (
            classify_resume_intent_tools if settings.RESUME_ROUTER_TOOLCALLING
            else classify_resume_intent
        )
        intent = _panel_intent or await _classify(raw, step_key, state)
        # A pending clarifying question has now been read against (the
        # classifier saw it in its context) — don't carry it past this reply.
        if isinstance(_bs, dict) and intent.lane != "clarify":
            _bs.pop("_clarify", None)
        # Builder-turn `thinking` is dropped before persistence (0 bytes on every
        # builder message in practice), so the writer() line below is invisible
        # outside a live SSE stream. Mirror it to the app log — this is the one
        # fact that told us why a resume was silently dropped.
        logger.info(
            "resume_router/%s lane=%s target_field=%s is_append=%s confidence=%s",
            step_key, intent.lane, intent.target_field, intent.is_append, intent.confidence,
        )
        writer({"type": "thinking", "content": (
            f"resume_router/{step_key} lane={intent.lane} "
            f"target_field={intent.target_field} is_append={intent.is_append} "
            f"confidence={intent.confidence}"
        )})

        # ── Composite-reply carriers ───────────────────────────────────────────
        # Any lane may set these alongside its own payload. Handled once, here,
        # ahead of the lane branches below — answer their question, then apply
        # their edits (the lane branches), then resolve their answer at the
        # tail. Question first: an edit or reject branch can `_resolved()` /
        # narrate its own thing further down, and this is the only spot
        # guaranteed to run before all of them.
        _question = _optional_str(getattr(intent, "question_text", None))
        # The handoff lane carries the raw reply as question_text and answers it
        # itself from real tool results (below); answering here too sent two
        # replies to one message, the first ungrounded.
        # A below-floor handoff never runs (it reframes), so it keeps this answer.
        _handoff_answers = (
            intent.lane == "handoff"
            and intent.confidence >= settings.RESUME_EDIT_MIN_CONFIDENCE
        )
        if _question and not _handoff_answers:
            _active_prompt = (STEP_PROMPTS.get(step_key) or {}).get("prompt") or step_key
            await narrate(
                Utterance(
                    role="sidebar_answer",
                    facts={
                        "question": _question,
                        "step": step_key,
                        "active_prompt": _active_prompt,
                    },
                    max_chars=400,
                    step_key=step_key,
                    fallback=(
                        "I want to make sure I answer that properly — could you "
                        "rephrase the question? Or if you'd rather, answer the "
                        "step above and we'll come right back to it."
                    ),
                ),
                state,
                writer,
            )

        # The part of the reply that answers the ACTIVE step, when the reply
        # also does something else ("yes 2km, and bump my budget to 500").
        # Gated by the same confidence floor as an edit — a hallucinated
        # answer commits the slot and the wizard moves on with it.
        _answer = _optional_str(getattr(intent, "answer_value", None))
        if _answer is not None and intent.confidence < settings.RESUME_EDIT_MIN_CONFIDENCE:
            _answer = None

        # Conflict: answer wins. An edit naming the field the user just
        # answered is redundant — applying both double-writes the slot and
        # invalidates the stage the user is standing in for no reason.
        if _answer and intent.target_field and intent.target_field == cfg.get("field"):
            intent = intent.model_copy(update={"target_field": None, "new_value": None})

        if intent.lane == "confirm":
            _use = _answer if _answer is not None else raw
            if prefill is not None and _is_confirmation(_use):
                return _resolved(prefill)
            return _resolved(_use)

        # When the reply went off-path (reject / unclassifiable), the loop
        # re-shows the SAME widget. Emit a step_reframe line above it so the
        # re-ask isn't silent (leak A). query/edit lanes own their own message.
        reframe_needed = False
        if intent.lane == "reject":
            pending["prefill"] = None
            pending["prefill_source"] = None
            pending["prefill_confidence"] = None
            reframe_needed = True
        elif intent.lane == "query":
            # Answered above — question_text is always set for this lane.
            # Keep pending unchanged so the same widget re-renders with the
            # user's question answered in line.
            pass
        elif intent.lane == "edit" and intent.target_field in _step_stepper_keys(cfg):
            # target_field is one of THIS step's stepper sub-keys (e.g.
            # poi_radius_m / lookback_days on the combined maid_collect_settings
            # step). The user is ANSWERING this multi-stepper step in free text,
            # not editing a prior step — cfg["field"] is the step id
            # ("maid_poi_radius"), never the sub-keys, so the classifier's
            # per-field label looks "cross-step" and _dispatch_edit_intent would
            # stash one value and re-ask forever. Return raw so the caller's
            # parser consumes every stepper value (the maid combined ask
            # LLM-extracts BOTH radius + lookback from the full reply).
            writer({"type": "thinking", "content": (
                f"resume_router/{step_key} lane=confirm "
                f"(edit target={intent.target_field} is a stepper key of this step)"
            )})
            return _resolved(raw)
        elif intent.lane == "edit":
            # True ⇒ nothing was applied and nothing was said (the confidence
            # floor rejected it), so the re-ask must not be silent.
            reframe_needed = await _dispatch_edit_intent(
                intent=intent,
                state=state,
                writer=writer,
                pending=pending,
                cfg=cfg,
                edits=edits,
                edit_base=edit_base,
            )
            if intent.unsupported_what:
                # The same reply also asked for something nothing can do — the
                # edits above still land; this part is said, not dropped.
                record_change(state, unsupported=intent.unsupported_what)
                capability_miss.record(
                    "unsupported_request", step_key=step_key, field=intent.unsupported_what,
                    detail=f"alongside an edit; nearest={intent.nearest_field}",
                )
            # Caller-owned re-execution: the edit targets a field whose fresh
            # output (map / geocode) the CALLER regenerates, not this loop. The
            # dispatch above already merged the value into `edits[target_field]`;
            # return it so the caller can apply, re-run, and re-interrupt. Without
            # this the loop would re-show the SAME widget with stale output (the
            # geo confirm "no map after add location" bug).
            #
            # `not reframe_needed` is the guard: a refused or below-confidence
            # edit put NOTHING in `edits`, so handing control back would make the
            # caller re-run its geocode against an unchanged set and re-interrupt
            # — a silent loop. Those cases stay in this loop and re-ask instead.
            #
            # Checked against the PRIMARY target and every `extra_edits` target —
            # not just the primary. `_dispatch_edit_intent` dispatches extras into
            # the same `edits` dict (recursively, one level), so "just manhattan"
            # riding in as an extra alongside an unrelated primary field used to
            # merge into `edits` and then sit there — this loop kept re-asking the
            # SAME (stale) widget instead of returning to the caller, so the geo
            # edit only applied on the NEXT turn, rolling back all four stages at
            # once and bouncing the user back to a confirm they'd already answered.
            _edit_fields = {intent.target_field} | {
                e.target_field for e in (intent.extra_edits or [])
            }
            _rerun_target = rerun_on_edit and (_edit_fields & rerun_on_edit)
            # Single-interrupt mode returns on EVERY non-answer (loop tail), so
            # the per-site allowlist is moot there.
            if not reframe_needed and _rerun_target and not _single:
                writer({"type": "thinking", "content": (
                    f"resume_router/{step_key} rerun-on-edit "
                    f"target={sorted(_rerun_target)} — returning to caller for re-run"
                )})
                return _resolved(raw)

            # A control-key edit (audience_filter, poi_selection, location_ops,
            # poi_ring, angle_locations, redraft, ...) is stashed in `edits` for
            # `builder_plan` to apply — it is NEVER a slot in `rerun_on_edit`
            # (FIELD_OWNER only knows real slot fields), so `_rerun_target` above
            # is always empty for one of these and the branch above never fires.
            # In LEGACY loop mode that used to mean the code falls through to the
            # loop tail's `continue`, which calls `interrupt()` a SECOND time
            # within this SAME node execution — in real LangGraph that pauses the
            # graph again before this function ever returns, discarding the
            # accumulated `edits` entirely (a second `interrupt()` with no
            # intervening return loses anything a real HTTP resume round-trip
            # didn't already resolve). The Layer Builder panel's "Apply" — and
            # the equivalent chat-text audience/POI edit — silently did nothing
            # on screen until whatever reply finally answered the gate, by which
            # point the build had already moved on. Returned as UNANSWERED, like
            # single-interrupt mode's loop tail — this is not the step's real
            # answer, just a stashed edit for the caller to apply before re-asking.
            from app.graph.builder.edits import _CONTROL_KEYS

            _has_control_edit = any(k in edits for k in _CONTROL_KEYS)
            if not reframe_needed and _has_control_edit and not _single:
                writer({"type": "thinking", "content": (
                    f"resume_router/{step_key} control-key edit "
                    f"({sorted(k for k in _CONTROL_KEYS if k in edits)}) — "
                    "returning to caller for re-run"
                )})
                return _unanswered()
        elif intent.lane == "clarify":
            # The reply fits more than one setting and nothing on screen
            # settles it — ask, never guess. Remember what was asked and about
            # which request, so the next reply ("the search one") is read
            # against it (resume_router._classifier_context).
            from app.graph.builder.knobs import KNOBS

            _opts = [o for o in (intent.clarify_options or []) if o]
            _question = intent.question_text or "Which one did you mean?"
            if isinstance(_bs, dict):
                _bs["_clarify"] = {"question": _question, "raw": str(raw), "options": _opts}
            _narrator_add_beat(
                state, "clarify",
                {"question": _question,
                 "options": [KNOBS[o].describe if o in KNOBS else o for o in _opts]},
                fallback=_question,
            )
            writer({"type": "thinking", "content": (
                f"resume_router/{step_key} lane=clarify options={_opts}"
            )})
        elif intent.lane == "unhandled":
            # The user named a real thing ("cap frequency at 2") that has no
            # field yet, or a target the classifier could not resolve at all —
            # NOT the same as staying silent. Say what it can't do plainly and
            # re-show the same widget; no step_reframe stutter on top (same
            # reasoning as an edit refusal — two messages for one reply reads
            # as a stutter), and this does NOT spend the reject budget: a user
            # naming several unsupported things in a row is not the same
            # failure as one who keeps not answering.
            writer({"type": "thinking", "content": (
                f"resume_router/{step_key} lane=unhandled "
                f"target_field={intent.target_field!r} — not acting, explaining instead"
            )})
            from app.graph.builder.knobs import KNOBS

            _named = (
                intent.unsupported_what or (intent.target_field or "").replace("_", " ")
            ).strip()
            _nearest = KNOBS.get(intent.nearest_field or "")
            record_change(state, unsupported=_named or str(raw))
            capability_miss.record(
                "unsupported_request", step_key=step_key, field=_named or None,
                detail=f"nearest={_nearest.name if _nearest else None}",
            )
            await narrate(
                Utterance(
                    role="locked_refusal",
                    facts={"field": _named or "that", "step": step_key,
                           "active_prompt": base_prompt,
                           **({"closest_i_can_do": _nearest.describe} if _nearest else {})},
                    max_chars=320,
                    fallback=(
                        f"I can't do {('**' + _named + '**') if _named else 'that'} yet"
                        + (f" — the closest I can change is {_nearest.describe}." if _nearest
                           else " — ask me what I can change and I'll list it.")
                    ),
                ),
                state,
                writer,
            )
        elif intent.lane == "handoff" and intent.confidence < settings.RESUME_EDIT_MIN_CONFIDENCE:
            # Same floor the edit lane applies — a handoff can trigger undo /
            # abort, which are as consequential as an edit's invalidate_from.
            # A low-confidence guess re-asks instead of risking one of those.
            writer({"type": "thinking", "content": (
                f"resume_router handoff below confidence floor "
                f"({intent.confidence} < {settings.RESUME_EDIT_MIN_CONFIDENCE}) — reframing"
            )})
            pending["prefill"] = None
            reframe_needed = True
        elif intent.lane == "handoff":
            # Anything not answer/reject/query/edit — status, advice grounded
            # in what's actually been found, undo, "do the rest for me",
            # "stop". Runs ONE bounded tool-calling turn in place (Phase 2 —
            # see interject_tools.py's module docstring for why this is
            # deliberately NOT campaign_manager_node's heavier multi-turn
            # ReAct shape) and re-shows the SAME widget afterward — no
            # checkpoint fork, no new interrupt boundary.
            from app.graph.builder.interject_tools import run_handoff_turn

            _ho = await run_handoff_turn(raw, step_key, state, edits=edits if _single else None)
            if _ho.abort:
                # Same precedent as the escape menu's "exit wizard": raise
                # with no narration of its own — the catching wizard (builder_ask)
                # decides what to say about the exit, not this loop.
                raise WizardExitRequested()
            if _ho.text:
                await narrate(
                    Utterance(
                        role="sidebar_answer",
                        facts={"question": raw, "step": step_key, "answer": _ho.text},
                        max_chars=700,
                        step_key=step_key,
                        # `fallback=_ho.text`: if composition mangles this, the
                        # tool-grounded text itself (unstyled but correct) is
                        # what ships, not a re-derived answer that could drop a
                        # real number a tool returned.
                        fallback=_ho.text,
                    ),
                    state,
                    writer,
                )
            else:
                # No tool fired and nothing to say — same "no reframe on top"
                # reasoning as query: re-showing the widget IS the answer when
                # the reply genuinely needed no tool.
                writer({"type": "thinking", "content": (
                    f"resume_router/{step_key} handoff: no tool call, nothing to say"
                )})
        else:
            # Unknown lane — defensive fallback to reject.
            pending["prefill"] = None
            reframe_needed = True

        # Resolve the answer half now that the reject/edit branch above has
        # run — an edit stashed alongside it is already in `edits` on
        # `_resolved`'s ResumeResult.
        if _answer:
            return _resolved(_answer)

        # A question already gave the user a real response; piling "let's
        # try that again" on top of it reads as a stutter (same reasoning as
        # the block-refusal "no reframe on top" comment above).
        if _question:
            reframe_needed = False

        if reframe_needed:
            _field_label = (cfg.get("field") or step_key).replace("_", " ")
            await narrate(
                Utterance(
                    role="step_reframe",
                    facts={
                        "step": step_key,
                        "asked_for": cfg.get("field") or step_key,
                        "rejected_reply": str(raw),
                        "iteration": iteration,
                        "escape_available": (iteration + 1) >= _ESCAPE_MENU_THRESHOLD,
                    },
                    max_chars=320,
                    step_key=step_key,
                    fallback=f"Let's try **{_field_label}** again — {base_prompt}",
                ),
                state,
                writer,
            )
            # Only a genuinely-silent turn spends the reject budget — one
            # where the widget is about to re-show with no other explanation
            # already given (see the const block above _dispatch_edit_intent's
            # own confidence-floor / audience-filter / backtrack-refused paths
            # all funnel here too, which is correct: those are "the model
            # tried and got nothing usable", the same failure class as reject).
            _reject_budget += 1

        iteration += 1
        if _single:
            return _unanswered()


def _match_escape(raw: Any, escape_menu: Any) -> str | None:
    """The escape-menu action this reply selects, or None.

    Exact (case/space-insensitive) match only. A loose match would hijack real
    answers — "explain" is a plausible thing to type at a free-text step, and
    stealing it would be worse than missing the shortcut, since the query lane
    already handles that phrasing conversationally.
    """
    if not escape_menu:
        return None
    needle = " ".join(str(raw or "").strip().lower().split())
    for action in escape_menu:
        if needle == " ".join(str(action).strip().lower().split()):
            return str(action)
    return None


def _step_stepper_keys(cfg: dict) -> set[str]:
    """Return the sub-answer keys of a multi-stepper step (``steppers[].key``).

    Empty for single-field / single-stepper steps. Used to tell a free-text
    answer to a combined stepper step ("radius 100m, lookback 7") apart from a
    genuine cross-step edit: the step's ``field`` is the step id, never the
    sub-keys, so the resume-router must consult these to avoid mis-routing the
    answer to the edit lane.
    """
    keys: set[str] = set()
    for st in (cfg.get("steppers") or []):
        key = st.get("key") if isinstance(st, dict) else None
        if key:
            keys.add(key)
    return keys


def _union_merge_preserve_order(existing: list, additions: list) -> list:
    """Append items from ``additions`` to ``existing`` while preserving order
    and skipping duplicates (case-insensitive for strings)."""
    out = list(existing or [])
    seen_lower = {str(x).strip().lower() for x in out if x is not None}
    for item in additions or []:
        if item is None:
            continue
        key = str(item).strip().lower()
        if key and key not in seen_lower:
            out.append(item)
            seen_lower.add(key)
    return out


def _list_remove_preserve_order(existing: list, removals: list) -> list:
    """Return ``existing`` minus any member matching an entry in ``removals``
    (case-insensitive for strings), preserving the order of the survivors."""
    drop = {str(x).strip().lower() for x in (removals or []) if x is not None}
    out = []
    for item in existing or []:
        if item is None:
            continue
        if str(item).strip().lower() in drop:
            continue
        out.append(item)
    return out


# Appending one of these mid-flow adds a NEW category/brand/place to the POI
# search — it does not, on its own, touch what the audience_filter requires.
# See _widen_live_intersection_filter.
_CATEGORY_APPEND_FIELDS: frozenset[str] = frozenset({
    "poi_types", "geo_poi_types",
    "competitor_brands", "geo_brand_names",
    "named_places", "geo_named_places",
})


async def _widen_live_intersection_filter(
    target_field: str, additions: list, state: Any, edits: dict, writer: Any,
) -> None:
    """"also target pet stores" while "vet clinic AND PetSmart AND dog park"
    is the live audience_filter used to leave the filter frozen at its
    turn-1 groups — the new category got discovered (POIs, the map, the
    count) but visitors were never required to have been there too, so the
    headline audience silently stopped reflecting what the user just asked
    for. When the live filter is an ``intersection``/``difference`` over
    named groups, AND the newly-appended label(s) into it — the same
    (stricter, not looser) direction an explicit "and also only people who
    hit the pet store" audience_filter edit would take.

    Stashes into ``edits["_audience_filter_patch"]`` — the SAME control key
    an explicit audience_filter edit uses (see the ``target_field ==
    "audience_filter"`` branch above) — so ``builder_node._apply_maid_
    audience_filter_edit`` recomputes it exactly like any other filter edit,
    no separate code path. A no-op when there is no live filter, it isn't an
    intersection/difference, or every appended label is already in it.
    """
    if target_field not in _CATEGORY_APPEND_FIELDS:
        return
    live_af = (state.get("geo_data") or {}).get("audience_filter") or {}
    if live_af.get("op") not in ("intersection", "difference") or not live_af.get("groups"):
        return
    # `groups` on the live filter are already-resolved poi_group_id tokens
    # ("category:vet clinic"); the patch machinery (resolve_group_labels,
    # called fresh against the CURRENT POI set every recompute) wants the
    # raw label half ("vet clinic") back, same as any other audience_filter
    # patch — see maid_store.resolve_group_labels_verbose's `key` match.
    existing_raw = [g.split(":", 1)[-1] for g in live_af["groups"]]
    existing_lower = {g.lower() for g in existing_raw}
    new_labels = [
        str(a).strip() for a in (additions or [])
        if str(a).strip() and str(a).strip().lower() not in existing_lower
    ]
    if not new_labels:
        return
    patch = {k: v for k, v in live_af.items() if not str(k).startswith("_")}
    patch["groups"] = existing_raw + new_labels
    # A patch already stashed this same turn (e.g. from a co-emitted explicit
    # audience_filter edit) wins over the auto-widen for any key it sets —
    # this only fills in `groups`/base fields, never overwrites a same-turn
    # user-requested change.
    prior_patch = edits.get("_audience_filter_patch") or {}
    edits["_audience_filter_patch"] = {**patch, **prior_patch}
    writer({"type": "thinking", "content": (
        f"resume_router: {target_field} append while an "
        f"{live_af['op']} audience_filter is live — widening its groups "
        f"to also require {new_labels!r}"
    )})
    await narrate(
        Utterance(
            role="edit_ack",
            facts={"field": "audience filter", "value": new_labels, "action": "widen_requirement"},
            fallback=(
                "Since your audience needs to match every category, "
                "I've added this to that requirement too — visitors now "
                "need to have been here as well."
            ),
        ),
        state,
        writer,
    )


async def _ack_commit(state: Any, writer: Any, utterance: "Utterance") -> None:
    """Narrate a field-commit ack — legacy loop only. In single-interrupt
    mode the ack is composed AFTER the write, from what actually happened
    (builder_plan's `edit_result` / `edit_invalidation` beat over the edit
    Outcomes), so Punk never says \"updated\" before it is true."""
    if ((state or {}).get("campaign_builder_state") or {}).get("_single_interrupt"):
        return
    await narrate(utterance, state, writer)


# Fields whose edits each carry their own instruction and stack in `edits`.
_ACCUMULATING_EDITS = frozenset({
    "poi_selection", "location_ring", "location_center", "map_pins", "excluded_areas",
})


async def _dispatch_edit_intent(
    intent: Any,
    state: Any,
    writer: Any,
    pending: dict,
    cfg: dict,
    edits: dict,
    edit_base: dict | None = None,
) -> bool:
    """Resolve an ``edit`` lane intent against the active step.

    Returns **True when the caller should emit a ``step_reframe``** — i.e. the
    reply changed nothing and the widget is about to re-render with no other
    explanation. False when this function already said its piece (a refusal, or
    an ``edit_ack`` for an edit that landed).

    Mutates ``pending`` (for current-step edits / append-merges) and/or
    ``edits`` (for cross-step in-wizard patches) in place.

    Every path that reaches the ack narrations below has already cleared
    ``edit_block_reason`` and the confidence floor, so an ack is only ever
    emitted for an edit that will actually be applied by
    ``builder/edits.apply_pending_edits``.

    ``edit_base`` — the CURRENT value of each cross-step list field, keyed by
    field name. A cross-step append/remove merges against ``edit_base[field]``
    the first time the field is touched (before that the ``edits`` accumulator is
    empty), so "add whitehall" yields ``current + [whitehall]`` rather than just
    ``[whitehall]``. Later edits accumulate against ``edits`` as before. Only used
    by callers that own re-execution (see ``rerun_on_edit``); omit otherwise.
    """
    target_field = intent.target_field
    new_value = intent.new_value

    # On a store-anchored-only run `location` is just a market hint, so an
    # ADDRESS edit to it would commit a hint and leave the stores untouched.
    # Retargeted here — before the floor, the block check, the append-merge and
    # the ack — so every later step sees (and tells the user about) the field
    # that really changes.
    if target_field in ("location", "geo_locations") and isinstance(state, dict):
        from app.graph.builder.slots import store_anchor_field_for_location

        _bs = state.get("campaign_builder_state") or {}
        _det = (_bs.get("filled") or {}).get("det_type") or (state.get("user_info") or {}).get(
            "deterministic_subtype"
        )
        _anchor = store_anchor_field_for_location(new_value, _det)
        if _anchor:
            writer({"type": "thinking", "content": (
                f"resume_router: {target_field!r} edit names street addresses on a "
                f"store-anchored run — retargeting to {_anchor!r}"
            )})
            target_field = _anchor
            intent = intent.model_copy(update={
                "target_field": _anchor,
                "is_append": intent.is_append and _anchor in APPENDABLE_FIELDS,
                "is_remove": intent.is_remove and _anchor in APPENDABLE_FIELDS,
            })

    # ── Admissibility, decided BEFORE anything is acknowledged ────────────────
    # Every branch below this point ends in an `edit_ack` narration that tells
    # the user their value was applied. That promise is only safe once we know
    # the edit CAN be applied, so the refusals come first. Previously the only
    # check was is_completed_owner, which reads `wizards_completed` — written
    # solely by builder_finalize — so mid-build it was always empty and the
    # refusal was unreachable. The result was an ack for edits that were then
    # silently dropped.
    #
    # A BACKTRACK carries `target_step_key` and no `target_field`, and
    # `edit_block_reason` returns None for an empty field — so "take me back to
    # where I picked locations" walked straight past the `published` guard at the
    # go_live gate, `invalidate_from` dropped publish + activate, and the builder
    # published a SECOND campaign into Meta. Resolve the step to the field it
    # collects (every slot's STEP_PROMPTS field is in FIELD_OWNER) so both shapes
    # of edit are judged by the same gate.
    block_field = target_field or (
        (STEP_PROMPTS.get(getattr(intent, "target_step_key", None) or "") or {}).get("field")
    )

    # Low confidence never commits — checked before admissibility so `redraft`
    # (a commit wearing a block's clothes: see below) can't skip the floor by
    # routing through the block branch first. An edit COMMIT invalidates
    # downstream work and re-runs it (a POI search, a warehouse query), so a
    # mis-read reply is expensive. Falling through to the reject/reframe path
    # costs a genuine edit nothing — the user simply says it again. The 2026-06
    # router had no such floor and auto-rewound on any `is_append`, which is
    # what got it removed.
    #
    # The floor itself is field-aware (edit_confidence_floor), not just the bare
    # global — a re-buy of live Unacast vendor data (poi_radius_m, locations, …)
    # is not the same risk as a free re-ask, so it needs a higher bar to commit.
    from app.graph.builder.edits import edit_confidence_floor

    _floor = edit_confidence_floor(target_field, settings.RESUME_EDIT_MIN_CONFIDENCE)
    if intent.confidence < _floor:
        writer({"type": "thinking", "content": (
            f"resume_router edit below confidence floor "
            f"({intent.confidence} < {_floor}) "
            f"field={target_field!r} — reframing instead of committing"
        )})
        capability_miss.record(
            "low_confidence", step_key=str(pending.get("step_key") or ""),
            field=target_field,
            detail=f"confidence {intent.confidence} < {_floor}",
        )
        pending["prefill"] = None
        return True

    async def _dispatch_extras() -> None:
        """Each `extra_edits` entry as its own edit. Shared by the redraft branch
        (which returns early) and the normal path below, so a redraft primary
        cannot drop the second field of a two-field reply."""
        for _extra in (getattr(intent, "extra_edits", None) or []):
            if not _extra.target_field:
                continue
            if _extra.target_field == intent.target_field and not (
                # Same field twice is normally a repeat of the primary — but some
                # edits ACCUMULATE, each one its own instruction: "top 20 dog
                # parks and 15 each of pet stores and vet clinics" is three
                # poi_selection specs, "events in Montreal, gyms in Toronto" two
                # scoped location edits. Skipping those dropped all but the first.
                (_extra.target_field in _ACCUMULATING_EDITS or _extra.edit_target)
                and (_extra.new_value, _extra.edit_target) != (intent.new_value, intent.edit_target)
            ):
                if (_extra.new_value, _extra.edit_target) != (intent.new_value, intent.edit_target):
                    # Understood but not executed. Never silent: the reply says so
                    # and the miss is logged (an exact repeat of the primary is not
                    # a drop, so it stays quiet).
                    record_change(state, unsupported=(
                        f"I could only apply one change to {str(_extra.target_field).replace('_', ' ')} "
                        f"per message, so I skipped: {_extra.new_value}"
                    ))
                    capability_miss.record(
                        "dropped_extra", step_key=str(pending.get("step_key") or ""),
                        field=_extra.target_field, detail=f"same-field extra not executed: {_extra.new_value}",
                    )
                continue
            _extra_reframe = await _dispatch_edit_intent(
                intent=intent.model_copy(update={
                    "target_field": _extra.target_field,
                    "edit_target": _extra.edit_target,
                    "new_value": _extra.new_value,
                    "is_append": _extra.is_append,
                    "is_remove": _extra.is_remove,
                    "is_replace": _extra.is_replace,
                    "unsupported_what": None,
                    "target_step_key": None,
                    "extra_edits": [],
                }),
                state=state, writer=writer, pending=pending, cfg=cfg,
                edits=edits, edit_base=edit_base,
            )
            # Every reachable path for an extra now narrates or acks itself
            # (apply, block-refusal, backtrack) — True here means the recursive
            # call fell through to a branch that says nothing, which should not
            # happen once ExtraEdit is validated upstream. Logged, not swallowed,
            # so a future gap shows up instead of vanishing.
            if _extra_reframe:
                writer({"type": "thinking", "content": (
                    f"resume_router extra_edit for {_extra.target_field!r} "
                    "resolved to no-op — check edit_block_reason / confidence"
                )})

    block = edit_block_reason(block_field, state)

    # A campaign field named after the plan exists. It used to only reopen the
    # editor and the typed value was never written. The plain fields the plan
    # holds directly (budget, dates, placements) are now applied to the plan
    # itself in builder_plan — validated, reported, undoable — so this is a
    # commit, not a refusal. Everything else keeps the specific refusal below.
    from app.graph.builder.plan_edits import PLAN_TYPED_FIELDS

    if (
        block in ("plan_editor", "budget_in_plan")
        and block_field in PLAN_TYPED_FIELDS
        and new_value not in (None, "", [])
    ):
        edits["_plan_edits"] = {**(edits.get("_plan_edits") or {}), block_field: new_value}
        record_change(state, heard={block_field: f"set {block_field.replace('_', ' ')} to {new_value}"})
        writer({"type": "thinking", "content": (
            f"resume_router edit/plan: {block_field} = {new_value!r} → applied to the built plan"
        )})
        await _dispatch_extras()
        return False

    if block:
        writer({"type": "thinking", "content": (
            f"resume_router edit REFUSED ({block}): field={block_field!r}"
        )})
        # `redraft` is NOT a refusal — the value IS applied, it just cannot go
        # through the plan editor (no control exists for it) and must not go
        # through invalidate_from (that would delete the user's plan). Acknowledge
        # it as the edit it is and leave before the refusal copy below.
        if block == "redraft":
            # Merge, not assign — a second prompt-only field edited later in the
            # same build must not clobber the first (`extra_edits` makes two
            # land in one reply too: "rename the business and tweak the offer").
            edits["_redraft"] = {**(edits.get("_redraft") or {}), block_field: new_value}
            # `edits["_redraft"]` is only STASHED here — the value lands in
            # user_info (and the brief re-runs) later, in builder_plan (see
            # its `_merged_ui` construction). Record `heard` now, `applied`
            # there, same as every other control field.
            record_change(state, heard={block_field: f"redraft {block_field}"})
            await narrate(
                Utterance(
                    role="edit_ack",
                    facts={"field": (block_field or "").replace("_", " "),
                           "value": new_value, "action": "update"},
                    fallback=(
                        f"Updated **{(block_field or '').replace('_', ' ')}** — "
                        "I'm rewriting the ad copy to match, and the new versions "
                        "will be in the headline and text pickers on each ad. Your "
                        "plan, media and budgets stay exactly as they are."
                    ),
                ),
                state,
                writer,
            )
            await _dispatch_extras()
            return False

        # A real refusal. plan_editor additionally reopens the editor; the rest
        # carry no action, the message is the whole response.
        if block == "plan_editor":
            edits["_reopen_plan"] = True
        # role=locked_refusal maps to the "answer" beat kind. Do NOT invent a new
        # role here: Role is a Literal and _ROLE_TO_KIND falls back to "reveal",
        # whose composer hint is "a result that ALREADY landed — showcase it as
        # DONE". A refusal narrated as a reveal is the exact lie this gate exists
        # to prevent.
        await narrate(
            Utterance(
                role="locked_refusal",
                facts={"field": (block_field or "").replace("_", " "),
                       "value": new_value, "reason": block},
                max_chars=320,
                fallback=EDIT_BLOCK_MESSAGES[block],
            ),
            state,
            writer,
        )
        # No reframe on top: the refusal copy steers back to the widget itself,
        # and two messages for one reply reads as a stutter.
        return False

    # Several fields changed in one reply ("change my budget AND add Toronto").
    # Each is dispatched as its own edit — same admissibility check (via the
    # recursive call), same ack. Deliberately placed AFTER the primary's own
    # confidence floor + edit_block_reason above, not before: extras share
    # `intent.confidence` (ExtraEdit carries no confidence of its own), so a
    # reply below the floor now gates the WHOLE reply — extras never dispatch
    # for a primary that was refused or below-floor, rather than sneaking
    # through ungated ahead of the check that was supposed to stop them.
    # Recursion depth is one: the copies carry no extra_edits of their own.
    await _dispatch_extras()

    # Audience-layering edit ("now only weekends", "just the ones who go 3+
    # times a week", "only gym AND coffee-shop regulars"). `new_value` is the
    # AudienceFilter patch dict the classifier extracted (see resume_router's
    # KNOWN EDITABLE FIELDS). Stashed under its own control key — NOT the
    # generic cross-step commit below — because it must recompute from the
    # persisted extraction superset, not go through
    # apply_pending_edits/invalidate_from (that would roll back the whole
    # maid stage and re-query the warehouse for a change that needs neither).
    #
    # Placed AFTER the extras loop above, not before: this used to `return
    # False` ahead of it, so a co-emitted extra ("only weekends AND bump the
    # radius") was acked to nobody — the primary returned before the loop that
    # dispatches extras ever ran, and the second field silently vanished after
    # the user was told the whole reply landed.
    if target_field == "audience_filter":
        if isinstance(new_value, dict) and new_value:
            # Same value checks the extraction and panel paths run — a patch
            # from the classifier used to be merged in raw, so a hallucinated
            # key or a negative count was persisted into
            # `_audience_filter_specs` and evaluated as a silent no-op. A key
            # set to None is kept: that is how a patch CLEARS a filter part.
            from app.graph.nodes import _validate_audience_filter_clause
            from app.services import maid_store

            # `unsupported` is consumed before folding, so it is deliberately not a
            # known evaluator key — not a hallucination.
            _unknown = [k for k in maid_store.unknown_filter_keys(new_value) if k != "unsupported"]
            if _unknown:
                logger.warning("audience_filter edit carried unknown keys %s — dropped", _unknown)
            new_value = {
                **{k: None for k, v in new_value.items()
                   if v is None and k in maid_store._KNOWN_FILTER_KEYS},
                **(_validate_audience_filter_clause(new_value) or {}),
            }
        if not isinstance(new_value, dict) or not new_value:
            writer({"type": "thinking", "content": (
                "resume_router audience_filter edit had no usable patch — reframing"
            )})
            pending["prefill"] = None
            return True
        edits["_audience_filter_patch"] = {
            **(edits.get("_audience_filter_patch") or {}), **new_value,
        }
        writer({"type": "thinking", "content": f"resume_router edit/audience_filter: {new_value!r}"})
        # `heard`, not `applied` — the patch is only STASHED here;
        # `_apply_maid_audience_filter_edit` (builder_plan) does the actual
        # recompute and records `applied` when it lands.
        record_change(state, heard={"audience_filter": f"narrow audience: {new_value}"})
        await narrate(
            Utterance(
                role="edit_ack",
                facts={"field": "audience", "requested": new_value, "action": "requested"},
                fallback="Got it — narrowing your audience to that now.",
            ),
            state,
            writer,
        )
        return False

    # Curation of the already-discovered POI set ("just the top 10", "top 5 of
    # each category", "drop everything in Laval"). Same shape as
    # audience_filter above — a tier-1 OVERLAY recomputed against the
    # persisted `_all_pois_cache` superset, not a slot commit — so it is
    # stashed under its own control key rather than going through the generic
    # cross-step commit below, which would resolve to no slot (poi_selection
    # owns none) and silently drop it. `new_value` is a selection SPEC (a
    # dict — see resume_router's POI_SELECTION prompt block / builder/
    # executors/poi_selection.normalize_spec) — or, from a stale cache entry
    # / Backend B's pre-migration schema, a bare instruction string;
    # normalize_spec accepts either. The actual resolution against the live
    # POI list happens in builder_node._apply_geo_poi_selection_edit, which is
    # the only place that HAS that list — this dispatcher cannot judge
    # whether the spec will match anything, only pass it through.
    #
    # A list (not a single overwrite): two curation instructions in the same
    # build ("drop Laval" now, "also drop the gym ones" later) must both land,
    # same reasoning as audience_filter's dict-merge just above.
    # Typed edits to the map's per-location decisions: one location's circle, its
    # centre, a dropped pin. Stashed as ops for builder_plan, which applies them
    # with the SAME functions the map widget's drag / drop-pin use — so a typed
    # change and a drag can never disagree — and reports each result.
    if target_field in ("location_ring", "location_center", "map_pins", "excluded_areas"):
        if target_field == "excluded_areas":
            _names = new_value if isinstance(new_value, list) else [new_value]
            _new_ops = [
                {"kind": "unexclude" if intent.is_remove else "exclude", "target": None, "value": str(n).strip()}
                for n in _names if str(n or "").strip()
            ]
            _said = ("include " if intent.is_remove else "leave out ") + ", ".join(o["value"] for o in _new_ops)
        else:
            _kind = {"location_ring": "ring", "location_center": "center", "map_pins": "unpin"}[target_field]
            _op = {
                "kind": _kind,
                "target": getattr(intent, "edit_target", None),
                "value": new_value if isinstance(new_value, str) else str(new_value or ""),
            }
            _new_ops = [_op]
            _label = {"ring": "resize the circle", "center": "move the circle", "unpin": "remove the pin"}[_kind]
            _said = f"{_label}{f' of {_op['target']}' if _op['target'] else ''}{f' to {_op['value']}' if _op['value'] else ''}"
        if not _new_ops:
            pending["prefill"] = None
            return True
        edits["_location_ops"] = [*(edits.get("_location_ops") or []), *_new_ops]
        record_change(state, heard={target_field: _said})
        writer({"type": "thinking", "content": f"resume_router edit/{target_field}: {_new_ops!r}"})
        return False

    # "100 m for the gyms": the visit ring for some spots only. An op on the
    # per-group ring decisions (`_poi_ring_specs`), resolved against the spots on
    # the map when applied.
    if target_field == "poi_radius_m" and getattr(intent, "edit_target", None):
        _size = new_value if isinstance(new_value, str) else str(new_value or "")
        if not _size.strip():
            pending["prefill"] = None
            return True
        edits["_poi_ring"] = [
            *(edits.get("_poi_ring") or []), {"match": intent.edit_target, "value": _size},
        ]
        record_change(state, heard={"poi_ring": f"visit ring for {intent.edit_target} = {_size}"})
        writer({"type": "thinking", "content": (
            f"resume_router edit/poi_radius_m scoped to {intent.edit_target!r}: {_size!r}"
        )})
        return False

    # "Events only in Montreal": a place tied to ONE search (target names it).
    # Stashed as an op; builder/angle_locations resolves which search it means and
    # says so when it can't tell.
    if target_field in ("location", "geo_locations") and getattr(intent, "edit_target", None):
        _names = (
            [str(n).strip() for n in new_value if str(n).strip()] if isinstance(new_value, list)
            else [n.strip() for n in str(new_value or "").split(",") if n.strip()]
        )
        if not _names:
            pending["prefill"] = None
            return True
        _kind = "remove" if intent.is_remove else "add" if intent.is_append else "set"
        edits["_angle_locations"] = [
            *(edits.get("_angle_locations") or []),
            {"target": intent.edit_target, "op": _kind, "names": _names},
        ]
        record_change(state, heard={
            "angle_locations": f"{_kind} {', '.join(_names)} for the {intent.edit_target} search",
        })
        writer({"type": "thinking", "content": (
            f"resume_router edit/location scoped to {intent.edit_target!r}: {_kind} {_names}"
        )})
        return False

    if target_field == "poi_selection":
        _spec_or_str = new_value if isinstance(new_value, dict) else str(new_value or "").strip()
        if not _spec_or_str:
            writer({"type": "thinking", "content": (
                "resume_router poi_selection edit had no usable instruction — reframing"
            )})
            pending["prefill"] = None
            return True
        edits["_poi_selection"] = [*(edits.get("_poi_selection") or []), _spec_or_str]
        _instruction = _spec_or_str if isinstance(_spec_or_str, str) else json.dumps(_spec_or_str)
        writer({"type": "thinking", "content": f"resume_router edit/poi_selection: {_instruction!r}"})
        # Was `facts={"value": _instruction, "action": "update"}` + `verbatim=
        # [_instruction]` — handing the composer the user's RAW phrase labelled
        # "update" is why "top 5 of each category" got echoed back verbatim as
        # a done deal while the trim (parsed separately, downstream, and
        # sometimes wrong) hadn't run yet. `action: "requested"` plus the
        # `heard`/`applied` ledger below is what actually gates the claim now;
        # the wording here is no longer load-bearing.
        record_change(state, heard={"poi_selection": f"trim spots: {_instruction}"})
        await narrate(
            Utterance(
                role="edit_ack",
                facts={"field": "spots", "requested": _instruction, "action": "requested"},
                fallback="Got it — applying that to your spots now.",
            ),
            state,
            writer,
        )
        return False

    # "Go back to where I picked locations." The classifier has always produced
    # target_step_key and nothing has ever consumed it, so an explicit backtrack
    # request was silently treated as an ordinary edit (or nothing at all).
    # Recorded as a control key; builder/edits clears that step's slot and
    # invalidates from its stage, which makes the planner re-ask it.
    #
    # Gated on `not new_value`: a backtrack per the classifier prompt carries
    # target_field + target_step_key and NO new_value ("take me back to
    # locations"). An ordinary edit that merely NAMES a step while also giving a
    # value ("go back to locations, use Toronto") is not a backtrack — it must
    # fall through to the target_field commit below, or the co-emitted value
    # was acked here and then silently dropped.
    #
    # Resolved before acking anything: `classify_resume_intent` already drops
    # an unresolvable `target_step_key` for the real classifier path, but this
    # function is also called directly (tests, and any future caller), so its
    # own contract must not depend on the caller having done that. Refusing
    # beats acking a backtrack that then does nothing — the exact
    # false-acknowledgment this module exists to prevent.
    if getattr(intent, "target_step_key", None) and not new_value:
        from app.graph.builder.edits import resolve_backtrack_target

        _kind, _ = resolve_backtrack_target(intent.target_step_key)
        if _kind == "none":
            writer({"type": "thinking", "content": (
                f"resume_router edit/backtrack REFUSED: step={intent.target_step_key!r} "
                "has no resolvable target"
            )})
            pending["prefill"] = None
            return True
        edits["_restart_step"] = intent.target_step_key
        writer({"type": "thinking", "content": (
            f"resume_router edit/backtrack: restart at {intent.target_step_key!r}"
        )})
        # Synthetic key (backtrack carries no target_field) — apply_pending_edits
        # records `applied` under the same key when it actually rewinds.
        record_change(state, heard={
            f"__backtrack__:{intent.target_step_key}": f"go back to {intent.target_step_key}",
        })
        await narrate(
            Utterance(
                role="edit_ack",
                facts={"field": "step", "value": intent.target_step_key,
                       "action": "go back"},
                fallback="Sure — taking you back to that step.",
            ),
            state,
            writer,
        )
        return False

    # Unknown target — defensive: behave like a reject so the user can retype.
    # Returns True so the caller narrates a reframe: returning False here re-showed
    # the widget with no message at all, as if the reply had never arrived.
    if not target_field:
        writer({
            "type": "thinking",
            "content": "edit intent missing target_field — falling back to reject",
        })
        pending["prefill"] = None
        return True

    active_field = cfg.get("field") if cfg else None

    # Cache-bust: a field is about to change, so any cached step framing / handoff
    # that cited the old value is now stale. Coarse prefix eviction forces fresh
    # generation on the next emit. Best-effort.
    try:
        narrator_cache.evict_prefix("step_frame:")
        narrator_cache.evict_prefix("handoff:")
    except Exception as exc:
        logger.debug("narrator cache evict on edit failed: %s", exc)

    # Remove from a list-typed field. Active-step removals shrink the pending
    # prefill in place so the user sees the list drop the item. Cross-step
    # removals merge against `edits`, else `edit_base` (the current value via
    # `current_edit_base`), and ride out to `apply_pending_edits`.
    if intent.is_remove and target_field in APPENDABLE_FIELDS:
        removals = new_value if isinstance(new_value, list) else [new_value]
        if target_field == active_field:
            current = pending.get("prefill") or []
            if not isinstance(current, list):
                current = [current] if current else []
            pending["prefill"] = _list_remove_preserve_order(current, removals)
            writer({"type": "thinking", "content": (
                f"resume_router edit/remove on active step: "
                f"{target_field} -= {removals}"
            )})
        else:
            existing = edits.get(target_field)
            if existing is None and edit_base is not None:
                existing = edit_base.get(target_field)
            existing = existing or []
            if not isinstance(existing, list):
                existing = [existing] if existing else []
            remaining = _list_remove_preserve_order(existing, removals)
            # A removal of something that isn't in the list can't be a removal.
            # For locations it is usually "everywhere except Mile End" — carving
            # part out of an area — which nothing here can do; saying "already
            # that value" (what the bus would report) would be a lie by omission.
            _handled_as_exclusion = False
            _have = {str(x).strip().lower() for x in existing}
            _absent = [r for r in removals if str(r).strip().lower() not in _have]
            _n_absent = len(_absent)
            if existing and _absent and target_field in ("location", "geo_locations"):
                # "everywhere except Mile End" where Mile End isn't a listed
                # location: it is a place INSIDE a targeted one. Carve it out.
                edits["_location_ops"] = [
                    *(edits.get("_location_ops") or []),
                    *({"kind": "exclude", "target": None, "value": str(a).strip()} for a in _absent),
                ]
                record_change(state, heard={"excluded_areas": "leave out " + ", ".join(str(a) for a in _absent)})
                writer({"type": "thinking", "content": (
                    f"resume_router edit/remove of unlisted place(s) {_absent} → excluded_areas"
                )})
                _absent = []
                _handled_as_exclusion = True
            if existing and _absent:
                _what = ", ".join(str(a) for a in _absent)
                _shown = ", ".join(str(e) for e in existing[:4])
                record_change(state, unsupported=(
                    f"{_what} isn't in your {target_field.replace('_', ' ')} ({_shown}), so there's nothing to remove"
                ))
                capability_miss.record(
                    "unsupported_request", step_key=str(pending.get("step_key") or ""),
                    field=target_field, detail=f"remove of absent item(s): {_what}",
                )
            _present_any = _n_absent < len(removals)
            if _present_any or not existing:
                edits[target_field] = remaining
            elif _handled_as_exclusion:
                # Everything was carved out as an exclusion; nothing to remove.
                return False
            elif existing:
                # Every requested removal was absent: nothing to stash, nothing
                # to rebuild. The ledger line above is the whole answer.
                return False
            else:
                edits[target_field] = remaining
            if target_field in ("deterministic_subtype", "geo_deterministic_type"):
                # apply_pending_edits UNIONS an angle edit with the running set
                # (the guard against a replace that forgot a live arm), which
                # silently undid this removal. Name the removal explicitly.
                edits["_angle_removals"] = _union_merge_preserve_order(
                    edits.get("_angle_removals") or [], removals,
                )
            writer({"type": "thinking", "content": (
                f"resume_router edit/remove cross-step: "
                f"{target_field} -= {removals}"
            )})
            record_change(state, heard={target_field: f"remove {removals} from {target_field}"})
            await _ack_commit(
                state, writer,
                Utterance(
                    role="edit_ack",
                    facts={"field": target_field.replace("_", " "), "value": new_value, "action": "remove"},
                    fallback=f"Removed from **{target_field.replace('_', ' ')}**",
                ),
            )
        return False

    # Append onto a list-typed field. When the active step owns the field we
    # mutate the pending prefill so the user sees their list grow. Cross-step
    # appends stash into ``edits``, which rides out on the ResumeResult and is
    # committed by ``builder/edits.apply_pending_edits``.
    if intent.is_append and target_field in APPENDABLE_FIELDS:
        if target_field == active_field:
            current = pending.get("prefill") or []
            if not isinstance(current, list):
                current = [current] if current else []
            additions = new_value if isinstance(new_value, list) else [new_value]
            pending["prefill"] = _union_merge_preserve_order(current, additions)
            writer({"type": "thinking", "content": (
                f"resume_router edit/append on active step: "
                f"{target_field} += {additions}"
            )})
        else:
            existing = edits.get(target_field)
            if existing is None and edit_base is not None:
                existing = edit_base.get(target_field)
            existing = existing or []
            if not isinstance(existing, list):
                existing = [existing] if existing else []
            additions = new_value if isinstance(new_value, list) else [new_value]
            merged = _union_merge_preserve_order(existing, additions)
            edits[target_field] = merged
            writer({"type": "thinking", "content": (
                f"resume_router edit/append cross-step: "
                f"{target_field} += {additions}"
            )})
            record_change(state, heard={target_field: f"add {additions} to {target_field}"})
            await _ack_commit(
                state, writer,
                Utterance(
                    role="edit_ack",
                    facts={"field": target_field.replace("_", " "), "value": new_value, "action": "add"},
                    fallback=f"Added to **{target_field.replace('_', ' ')}**",
                ),
            )
            await _widen_live_intersection_filter(target_field, additions, state, edits, writer)
        return False

    # Replace: current-step field → update prefill so the widget re-renders
    # with the new value pre-filled and the user just confirms.
    if target_field == active_field:
        pending["prefill"] = new_value
        pending["prefill_source"] = "user_edit"
        pending["prefill_confidence"] = 0.95
        writer({"type": "thinking", "content": (
            f"resume_router edit/replace on active step: "
            f"{target_field} = {new_value!r}"
        )})
        return False

    # Replace: cross-step in-wizard field → stash the patch into ``edits``, which
    # builder/edits commits and invalidates against. The active step's widget
    # re-renders unchanged so the user keeps progressing.
    if target_field in APPENDABLE_FIELDS and not isinstance(new_value, list):
        # A pure replace on a list-typed field ("just NYC") still needs list
        # shape downstream — every consumer of `edits[target_field]` for a
        # list field (geo.py's `_apply_location_edit`, the store-confirm
        # equivalent, `_norm_locs`) iterates it as a collection. A bare
        # scalar iterated directly explodes into its CHARACTERS
        # ("New York, NY, USA" -> "N","e","w",...), each geocoded as its own
        # bogus location — see the append/remove guards two blocks above,
        # which the pure-replace lane never had.
        new_value = [new_value]
    edits[target_field] = new_value
    if (
        getattr(intent, "is_replace", False)
        and target_field in ("deterministic_subtype", "geo_deterministic_type")
    ):
        # An EXPLICIT replace ("forget the cafes, just do events"): the angles
        # running now that aren't in the new set are removals. Without naming
        # them, apply_edits' union guard would keep every old angle running.
        _now = list((edit_base or {}).get(target_field) or [])
        _new = {str(v).strip().lower() for v in new_value}
        _drop = [t for t in _now if str(t).strip().lower() not in _new]
        if _drop:
            edits["_angle_removals"] = _union_merge_preserve_order(
                edits.get("_angle_removals") or [], _drop,
            )
    writer({"type": "thinking", "content": (
        f"resume_router edit/replace cross-step: "
        f"{target_field} = {new_value!r}"
    )})
    record_change(state, heard={target_field: f"set {target_field} = {new_value}"})
    # A list-typed field's value (just wrapped above, or already a list from
    # the classifier) has no natural `` `repr` `` — "-> `['NYC']`" leaks Python
    # syntax into the fallback shown when narration is off/fails. Same
    # sidestep the append branch above already takes ("Added to **field**",
    # no value shown) rather than trying to prose-format an arbitrary list.
    _fallback_value = (
        ", ".join(str(v) for v in new_value) if isinstance(new_value, list) else new_value
    )
    await _ack_commit(
        state, writer,
        Utterance(
            role="edit_ack",
            facts={"field": target_field.replace("_", " "), "value": new_value, "action": "update"},
            fallback=f"Updated **{target_field.replace('_', ' ')}** → `{_fallback_value}`",
        ),
    )
    return False


# ── Small convenience ─────────────────────────────────────────────────────────

def get_writer() -> Any:
    """Return the current LangGraph stream writer."""
    return get_stream_writer()
