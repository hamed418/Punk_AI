"""
graph/nodes.py
──────────────
Async node functions for the PunkAI LangGraph campaign-builder agent.

Node responsibilities:
  entry_node           – TWO parallel Flash temp-0 structured calls (routing +
                         business-field extraction into user_info), run
                         concurrently: topic filter + routing + extraction
                         (replaces the old guardrail → intent_extraction →
                         supervisor pipeline of three serial LLM calls, and the
                         later single Pro+thinking call)
  knowledge_based_node – answers Meta Ads questions from the knowledge base
  chatbot_node         – sole producer of all user-visible conversational replies

Wizard subgraphs live in backend/app/graph/wizards/ — they replaced the old
monolithic geo_agent_node, maid_extraction_node, campaign_planner_node, and
media_buying_node, making each interrupt its own checkpoint boundary and
eliminating linear-growth replay cost.

Thinking mode:
  Every node emits structured thinking events via get_stream_writer() so the
  frontend can show real-time reasoning (stream_mode="custom"). The chatbot
  also enables Gemini's native thinking (thinking_level) for chain-of-thought
  reasoning, sized per turn by _chatbot_thinking_level().
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Literal, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.config import get_stream_writer
from pydantic import BaseModel, Field

from app.core.config import settings
from app.graph.knowledge import load_punk_kb
from app.graph.narrator.grounding import build_pack
from app.graph.narrator.post_process import scrub_jargon
from app.graph.prompts import (
    CHATBOT_SYSTEM_PROMPT,
    ENTRY_SYSTEM_PROMPT,
    EXTRACTION_ONLY_SYSTEM_PROMPT,
)
from app.graph.state import (
    MAX_LLM_HISTORY,
    AgentState,
    UserInfo,
    is_conversational,
    is_internal,
)
from app.graph.usage import tracked_ainvoke, tracked_astream
from app.graph.tools import retrieve_marketing_knowledge
from app.graph.wizard_helpers import is_relative_location

logger = logging.getLogger(__name__)

# Real user/assistant turns held back from eviction when the ledger fills the
# MAX_LLM_HISTORY window on a long build. See the trim in chatbot_node.
_MIN_CONVERSATIONAL_TAIL = 6


# ── LLM factories ─────────────────────────────────────────────────────────────
# Called inside nodes (not at import time) so no API key is needed at startup.

def _make_llm(temperature: float | None = None, model: str | None = None) -> ChatGoogleGenerativeAI:
    """Standard Gemini instance — no thinking tokens. Flash tier by default."""
    return ChatGoogleGenerativeAI(
        model=model or settings.GEMINI_MODEL,
        **settings.llm_auth,
        temperature=temperature if temperature is not None else settings.GEMINI_TEMPERATURE,
        timeout=60.0,
        max_retries=5,
    )


def _make_thinking_llm(
    thinking_level: str = "high",
    model: str | None = None,
    temperature: float | None = None,
) -> ChatGoogleGenerativeAI:
    """
    Gemini instance with native thinking enabled. Pro tier by default — used by
    the chatbot.

    ``thinking_level`` is minimal | low | medium | high (Gemini 3's replacement
    for ``thinking_budget``, which is deprecated on these models).

    ``temperature`` defaults to GEMINI_TEMPERATURE; the chatbot passes
    settings.CHATBOT_TEMP.

    Returns thinking blocks in response.content as:
        [{"type": "thinking", "thinking": "<reasoning>"}, {"type": "text", "text": "<answer>"}]
    """
    return ChatGoogleGenerativeAI(
        model=model or settings.GEMINI_MODEL_PRO,
        **settings.llm_auth,
        temperature=temperature if temperature is not None else settings.GEMINI_TEMPERATURE,
        thinking_level=thinking_level,
        include_thoughts=True,
    )


def _chatbot_thinking_level(wizard_failure: str | None) -> str:
    """Thinking level for the chatbot turn.

    A failure post-mortem needs room to reason about recovery. Everything else
    is answering a real person about their campaign — including genuine
    questions where depth of explanation is the whole point — so it gets
    ``medium`` rather than the old routine-turn budget of ~3k tokens.
    """
    return "high" if wizard_failure else "medium"


# ── Entry decision schemas ─────────────────────────────────────────────────────

class AngleSpec(BaseModel):
    """One targeting angle with its OWN location + place-types, for a combo where
    the angles DIVERGE in where/what (e.g. "shawarma in Toronto, film festivals in
    Montreal"). Emit `targeting_angles` (a list of these) ONLY when angles genuinely
    diverge; when every angle shares the same location/types, leave it null and use
    the flat fields (the common path).

    Any field left null INHERITS the shared flat value (the executor falls back to
    the run-wide `location` / type fields). `angle` is required — it says which arm
    this spec drives. `scope` is reserved for a later phase (per-angle area-size).
    """

    angle: Literal[
        "category", "competitor_brand", "named_places",
        "event_based", "store_set", "competitor_nearby", "competitor_area",
    ]
    locations: Optional[list[str]] = None      # override; inherit shared `location` if null
    scope: Optional[Literal[               # per-angle area-size; inherit run-wide geo_scope if null
        "granular_local", "admin_areas", "country_groups", "radius",
    ]] = None
    poi_types: Optional[list[str]] = None      # category types for THIS angle
    anchor_types: Optional[list[str]] = None   # near-business types for THIS angle
    named_places: Optional[list[str]] = None
    competitor_brands: Optional[list[str]] = None
    event_queries: Optional[list[str]] = None
    event_date_range: Optional[str] = None


class AudienceFilterClause(BaseModel):
    """ONE flat narrowing clause — day-of-week, hour, dwell, visit frequency,
    cadence, trend, or boolean logic across POI groups. Every field optional;
    set ONLY what the user actually stated — never invent a predicate.
    Mirrors ``maid_store.AudienceFilter``'s single-clause shape; see
    EXTRACTION_FIELDS_SPEC's ``audience_filter`` entry for full semantics and
    worked examples.

    Deliberately NOT self-referential (no ``any_of`` field here) — this is
    what one entry of ``AudienceFilterSpec.any_of`` is. A model that referenced
    itself would make the generated structured-output schema recursive, which
    Gemini/LangChain structured output does not handle as reliably as a
    concrete, bounded shape like this one.
    """
    groups: Optional[list[str]] = None
    op: Optional[Literal["union", "intersection", "difference"]] = None
    exclude_groups: Optional[list[str]] = None
    window_days: Optional[int] = None
    min_visits: Optional[int] = None
    min_distinct_pois: Optional[int] = None
    # "3 of the 5 place types" — at least N of `groups` (each a different
    # KIND of place, not a different outlet: that is min_distinct_pois).
    min_distinct_groups: Optional[int] = None
    days_of_week: Optional[list[int]] = None   # Mon=0..Sun=6
    hours: Optional[list[int]] = None          # [lo, hi) local hour, e.g. [0, 9]
    min_dwell_min: Optional[int] = None
    min_weekly_hours: Optional[float] = None
    trend: Optional[Literal["started", "lapsed"]] = None
    cadence_days: Optional[int] = None             # target recurring interval, e.g. 14 for "every payday"
    cadence_tolerance_days: Optional[int] = None    # +/- window around cadence_days
    invert: Optional[bool] = None    # flip SELECT into EXCLUDE over the same otherwise-eligible pool
    # Per-group visit floor. `min_visits` is a TOTAL across the clause, so
    # "3+ times at the gym AND 3+ at the coffee shop" was inexpressible.
    min_visits_per_group: Optional[int] = None
    # 0..1 — share of a device's OWN visits that must fall inside this clause's
    # scope. How "ONLY on weekdays" is said; every other field is "at least one".
    min_share_in_scope: Optional[float] = None
    # Drop visits evidenced by a single low-accuracy ping.
    min_confidence: Optional[Literal["confirmed"]] = None
    # Scope for exclude_groups, in days. Absent = inherit the selection's scope;
    # 0 = "ever".
    exclude_window_days: Optional[int] = None
    # Asymmetric trend windows — "started going after NEVER going before" needs
    # a short recent window and a long prior one.
    trend_recent_days: Optional[int] = None
    trend_prior_days: Optional[int] = None
    # PRESENCE-PATTERN role signal (owner/staff, not min_weekly_hours' dwell
    # sum): 0..1 share of the scope's OBSERVED operating days a device was
    # present on. Needs only 1 ping/day — survives the ~47% of visits that are
    # single-ping, unlike a dwell-based test. See maid_store.AudienceFilter's
    # docblock for the full contrast with min_weekly_hours.
    min_open_day_share: Optional[float] = None
    # Minutes between a device's first and last ping on its busiest single
    # local day (max across days) — an arrival-to-departure envelope, immune
    # to visit-gap fragmentation. "spends all day inside" -> this, not
    # min_dwell_min, which reads near-zero on a gap-fragmented stay.
    min_intraday_span_min: Optional[int] = None
    # Absolute floor on distinct presence-days, alongside min_open_day_share —
    # stops "2 of 3 observed days" clearing a share threshold on thin evidence.
    min_days_present: Optional[int] = None
    # A clause the user named but that NONE of the fields above can express
    # ("men in their 30s", "cut it in half") — put it VERBATIM here and still
    # set whatever fields above you CAN, same obligation as poi_selection's
    # `unsupported` key (resume_router.py). Never approximate an inexpressible
    # clause with the nearest field that doesn't actually mean what they said.
    unsupported: Optional[str] = None


class AudienceFilterSpec(AudienceFilterClause):
    """The full extraction surface: everything ``AudienceFilterClause`` has,
    PLUS ``any_of`` — a bounded 2-level OR-of-AND (disjunctive normal form),
    matching the ceiling Meta's own Ads Manager audience combinator exposes
    ("include people who match ANY of the following / ALL of the following").
    Not a general recursive tree — each ``any_of`` entry is a plain
    ``AudienceFilterClause`` with no further nesting.

    Set ``any_of`` ONLY when the user names genuinely SEPARATE qualifying
    groups joined by "or," each with its own internal AND-logic ("gym-and-
    coffee-shop regulars, OR anyone who's hit 3+ open houses"). A plain
    multi-group mention stays the flat ``groups`` list on this object
    (union, the default) — do not use ``any_of`` for an ordinary list of
    interchangeable venues. When ``any_of`` is set, the flat fields on this
    same object are ignored — never set both.
    """
    any_of: Optional[list[AudienceFilterClause]] = None


class ExtractedUserInfo(BaseModel):
    """Extraction surface for the entry node — mirrors the UserInfo prefill
    fields. Every field is optional; None means "not mentioned / unchanged".
    Enum-like fields are Literal so the schema, not the prompt, enforces them.
    Field semantics live in prompts.EXTRACTION_FIELDS_SPEC.
    """

    business_name: Optional[str] = None
    business_description: Optional[str] = None
    industry: Optional[str] = None
    target_audience: Optional[str] = None
    budget: Optional[str] = None
    budget_type: Optional[Literal["daily", "lifetime"]] = None
    location: Optional[list[str]] = None
    website_url: Optional[str] = None
    campaign_objective: Optional[str] = None
    product_offer: Optional[str] = None
    campaign_start_date: Optional[str] = None
    campaign_end_date: Optional[str] = None
    pixel_status: Optional[Literal["verified", "unverified", "not_installed"]] = None
    targeting_choice: Optional[Literal["guided", "self_directed"]] = None
    geo_scope: Optional[
        Literal["granular_local", "admin_areas", "country_groups", "radius"]
    ] = None
    deterministic_subtype: Optional[
        Literal[
            "competitor_nearby", "competitor_area", "competitor_brand", "category",
            "store_set", "event_based", "ai_suggested", "named_places",
        ]
    ] = None
    # Combo vehicle: when the user names MULTIPLE angles at once ("Osheaga AND Fight
    # Club", "my shops AND events in Montreal"), list ALL that apply here. ANY mix is
    # allowed — each angle just contributes its own places to one shared audience:
    #   • MARKET angles (category / competitor_brand / named_places / event_based /
    #     competitor_area) search inside a named external market;
    #   • store-anchored angles (store_set / competitor_nearby) build off the user's
    #     OWN store address;
    #   • mixed is fine ("store_set","event_based") — for a mixed set the market slots
    #     re-activate on their own (slot_applies' not_when SUBSET rule).
    # ai_suggested is "you pick for me" and is never listed here (use
    # deterministic_subtype). Collapsed to a comma-joined deterministic_subtype
    # downstream (see entry_node merge); nothing is dropped.
    deterministic_subtypes: Optional[
        list[Literal[
            "category", "competitor_brand", "named_places", "event_based",
            "store_set", "competitor_nearby", "competitor_area",
        ]]
    ] = None
    # Per-angle override: when the angles DIVERGE in location/types ("shawarma in
    # Toronto, film festivals in Montreal"), list one AngleSpec per angle with its
    # own location + types. Null when angles share the same where/what (the common
    # case — use the flat fields). Resolved into a durable `geo_angle_specs` in the
    # entry merge; the angle tokens also seed `deterministic_subtypes`.
    targeting_angles: Optional[list[AngleSpec]] = None
    competitor_brands: Optional[list[str]] = None
    named_places: Optional[list[str]] = None
    poi_types: Optional[list[str]] = None
    # CITY/MARKET-WIDE types go in poi_types (category angle); types the user wants
    # searched NEAR THEIR OWN BUSINESS go here (competitor_nearby anchor). A dedicated
    # field so a category+competitor_nearby combo keeps the two sets apart — a shared
    # poi_types could not carry which types belong to the near-business search.
    anchor_types: Optional[list[str]] = None
    event_queries: Optional[list[str]] = None
    event_date_range: Optional[str] = None
    target_age_min: Optional[int] = None
    target_age_max: Optional[int] = None
    target_gender: Optional[Literal["male", "female", "all"]] = None
    poi_radius_m: Optional[int] = None
    lookback_days: Optional[int] = None
    search_radius_km: Optional[int] = None
    store_addresses: Optional[list[str]] = None
    competitor_address: Optional[str] = None
    # Layering on top of the audience being built — day-of-week, hour, dwell,
    # frequency, trend, or set logic across POI groups. See AudienceFilterSpec.
    audience_filter: Optional[AudienceFilterSpec] = None
    # Meta-banned targeting classes the user named (race, sexual orientation,
    # religion, health condition, ...) — captured so Punk can say what it
    # refused instead of silently dropping it. NOT applied to targeting.
    blocked_attributes: Optional[
        list[Literal["race", "ethnicity", "sexual_orientation", "religion", "health_condition"]]
    ] = None


class FollowUp(BaseModel):
    """One tailored clarify question proposed by the entry node.

    The entry LLM authors these from what it just extracted; chatbot_node
    phrases them in Punk's voice. Goes BEYOND the coarse 5W taxonomy.
    """

    ask: str
    """The specific thing to learn, in plain terms (chatbot phrases it)."""

    why: str
    """One-line reason this matters, grounded in THIS business."""


class EntryRouting(BaseModel):
    """Routing half of the entry decision: topic filter + route (NO extraction).

    Filled by its own Flash structured call so field extraction can run
    concurrently in a separate call. Splitting the old combined 25-field
    EntryDecision — which needed Pro to fill reliably (Flash returned mostly
    nulls on the combined schema) — into two focused Flash calls lets each stay
    cheap, and asyncio.gather overlaps them so entry latency ≈ one Flash call.
    """

    off_topic: bool
    """True when the latest user message is outside Punk's marketing domain."""

    detected_topic: str
    """Short label of what the user asked about (used for the deflection)."""

    route: Literal[
        "onboarding",
        "geo_agent",
        "campaign_builder",
        "knowledge_based",
        "campaign_manager",
        "chatbot",
        "end",
    ]
    """Routing destination. "onboarding" = build/advertising intent present but the
    goal isn't yet clearly understood — hold a normal discovery conversation. Use
    ONLY when ONBOARDING STATUS is NOT "complete"; entry_node resolves it to the
    chatbot lane in discovery mode.

    "campaign_builder" = RESUME a build already in progress. Use it whenever
    BUILD IN PROGRESS says a build is paused and the user wants to carry on
    ("continue", "keep going", "yes let's finish it", "go on"). "geo_agent"
    starts a build from scratch and is refused once geo is COMPLETE; without
    this value there was no way back into a partially-built campaign, so a
    single builder failure orphaned it permanently."""

    reasoning: str
    """Short explanation of why this route was chosen."""

    missing_signals: list[
        Literal["what", "who", "why", "where", "how_tactic"]
    ] = []
    """When route='chatbot' due to thin business context: exactly which 5W
    signals are still unknown. Empty for wizard routes, normal chatbot turns,
    and pure greetings. Never padded with signals the user already answered."""

    follow_ups: list[FollowUp] = []
    """1-3 tailored clarify questions for 'chatbot' routes, grounded in what
    was just extracted. Goes BEYOND the 5W taxonomy — specific to the business
    (echo business_description / industry). Never re-ask a field already in
    `extracted`. Empty for wizard routes, greetings, and normal chatbot turns."""

    clarify_reason: Optional[str] = None
    """OPTIONAL unique angle the chatbot should echo in its clarify reply
    (e.g. 'User mentioned pop-up event'). Never a list of missing signals —
    that's what missing_signals is for."""

    flow_blocked: bool = False
    """True ONLY when routing to 'chatbot' because the user asked for a later
    stage (campaign plan, publishing, budget setup) whose prerequisite wizards
    are not COMPLETE. The chatbot explains the flow order when set."""

    user_turn_digest: Optional[str] = None
    """One short line capturing the user's latest message in THEIR words —
    their phrasing for what they want, plus any question they slipped in. Used by
    the narrator to reply TO the user (mirror their words, answer their question)
    instead of only narrating Punk's state. Null for pure widget values."""

    mood: Optional[Literal["neutral", "frustrated", "confused", "eager"]] = None
    """The user's affect this turn, so the narrator can adapt tone: frustrated →
    brief + reassure; confused → add guidance; eager → match momentum. Null =
    treat as neutral."""


class EntryDecision(EntryRouting):
    """Full one-pass decision — routing + extraction combined.

    Retained as an EntryRouting subclass so tests (and any single-call fallback)
    can construct the whole decision in one object. Production ``entry_node`` no
    longer fills this schema in one Pro call; it fills ``EntryRouting`` and
    ``ExtractedUserInfo`` via two parallel Flash calls (see ``entry_node``).
    """

    extracted: ExtractedUserInfo = Field(default_factory=ExtractedUserInfo)
    """Business/campaign fields extracted from the latest user message."""


# ── Helpers ────────────────────────────────────────────────────────────────────

def derive_stage(state: AgentState, geo_data: Optional[dict] = None) -> dict[str, Any]:
    """Single source of truth for campaign-pipeline stage derivation.

    Used by _build_wizard_state_context (entry prompt), _detect_handoff
    (narrator short-circuit), and _stage_fact_lines (chatbot context) so the
    three stage readers cannot drift apart.

    ``geo_data`` overrides the state lookup — the entry context builder passes
    results it recovered from the wizard scratchpad.
    """
    if geo_data is None:
        geo_data = state.get("geo_data") or {}
    geo_done = bool(geo_data)
    method = geo_data.get("targeting_method", "deterministic")
    pois = geo_data.get("pois_found", 0)
    _maid_count_raw = geo_data.get("maid_count")
    maid_done = geo_done and (
        _maid_count_raw is not None
        or geo_data.get("maid_query_skipped") is True
    )
    # Every reader of the returned `maid_count` below quotes it back in
    # narration/stage-context prose to the user or the LLM — it must be the
    # audience an active filter actually leaves, not the pre-filter superset
    # (`_maid_count_raw` above stays the presence/done-check signal, which
    # must not change when a filter is edited after the query already ran).
    from app.graph.maid_query import audience_headline_count

    maid_count = audience_headline_count(geo_data)
    marketing_plan = state.get("marketing_plan")
    campaign_done = bool(marketing_plan and "parse_error" not in marketing_plan)
    media_published = (
        "media" in (state.get("wizards_completed") or set())
        or bool((state.get("meta_campaign_ids") or {}).get("campaign_id"))
    )

    if not geo_done:
        next_stage = "geo"
    elif not maid_done:
        next_stage = "maid"
    elif not campaign_done:
        next_stage = "campaign"
    elif not media_published:
        next_stage = "media"
    else:
        next_stage = "done"

    return {
        "geo_done": geo_done,
        "method": method,
        "pois": pois,
        "maid_done": maid_done,
        "maid_count": maid_count,
        "campaign_done": campaign_done,
        "media_published": media_published,
        "next_stage": next_stage,
    }


def _build_wizard_state_context(state: AgentState) -> str:
    """Build a concise wizard progress summary for the entry LLM."""
    geo_data = state.get("geo_data")
    ws = state.get("geo_wizard_state") or {}

    # Deep-scan: geo finished but results not merged to parent state yet —
    # read the scratchpad so the context doesn't claim NOT_STARTED.
    if not geo_data and ws.get("_det_result"):
        geo_data = dict(ws["_det_result"])

    if not geo_data:
        return (
            "geo_wizard: NOT_STARTED\n"
            "maid_wizard: NOT_STARTED\n"
            "campaign_wizard: NOT_STARTED\n"
            "media_wizard: NOT_STARTED"
        )

    st = derive_stage(state, geo_data=geo_data)
    lines = [f"geo_wizard: COMPLETE (method={st['method']}, pois={st['pois']})"]

    if st["maid_done"]:
        maid_count = st["maid_count"] if st["maid_count"] is not None else "n/a"
        lines.append(f"maid_wizard: COMPLETE (maid_count={maid_count})")
    elif st["method"] == "deterministic" and st["pois"] == 0:
        lines.append("maid_wizard: NOT_STARTED (waiting for geo POIs)")
    else:
        lines.append("maid_wizard: PENDING")

    if st["campaign_done"]:
        lines.append("campaign_wizard: COMPLETE (marketing_plan generated)")
    elif st["maid_done"]:
        lines.append("campaign_wizard: PENDING")
    else:
        lines.append("campaign_wizard: NOT_STARTED")

    if st["media_published"]:
        lines.append("media_wizard: COMPLETE (published to Meta)")
    elif st["campaign_done"]:
        lines.append("media_wizard: PENDING")
    else:
        lines.append("media_wizard: NOT_STARTED")

    return "\n".join(lines)


def _extract_last_human_text(state: AgentState) -> str | None:
    """Return the text of the most recent real user turn, or None.

    Skips ledger and injected-context records: a wizard answer is a genuine
    HumanMessage, but it is not "what the user just asked us", and this feeds the
    knowledge-RAG query, the proceed detector and the extraction call.
    """
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage) and isinstance(msg.content, str) and is_conversational(msg):
            return msg.content
    return None


def _extract_last_ai_text(state: AgentState) -> str | None:
    """Return the text of the most recent real assistant turn, or None.

    Used to give the parallel extraction call a little conversational context
    (mirrors the resume-path ``_build_extraction_messages`` signature). Filtered
    like its human counterpart, which also keeps injected context blobs out.
    """
    for msg in reversed(state["messages"]):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str) and is_conversational(msg):
            return msg.content
    return None


_BOTH_INTERSECTION_RE = re.compile(r"\bboth\b|\ball of\b", re.IGNORECASE)


def _infer_intersection_filter(text: str | None, extracted: dict) -> dict | None:
    """Deterministic backstop for "who went to both X and Y" phrasing that
    the one-shot ``ExtractedUserInfo`` call sometimes drops entirely — it's a
    best-effort structured-output call with no schema-level enforcement on
    ``audience_filter`` (``_validate_extracted_field`` below has no case for
    it, so a dropped value passes through silently as ``None``).

    Only fires when THIS turn's text says "both"/"all of" AND the LLM did
    NOT already produce an op/groups of its own — never overrides an
    explicit extraction, never invents group names the LLM didn't itself
    extract this turn (uses only ``named_places``/``event_queries``/
    ``competitor_brands`` already in ``extracted``).
    """
    if not text or not _BOTH_INTERSECTION_RE.search(text):
        return None
    af = extracted.get("audience_filter") or {}
    if af.get("op") or af.get("groups"):
        return None
    labels = [
        *(extracted.get("named_places") or []),
        *(extracted.get("event_queries") or []),
        *(extracted.get("competitor_brands") or []),
    ]
    if len(labels) < 2:
        return None
    return {"groups": labels, "op": "intersection"}


# A real but unquantified frequency claim — "frequent", "regulars", "keeps
# coming back" — names a genuine repeatable behavior, unlike "a while"/"a
# long time" which names no behavior at all.
_VAGUE_FREQUENCY_RE = re.compile(
    r"\bfrequent(?:ly|s)?\b|\bregulars?\b|\bregularly\b|\bkeep(?:s)? coming back\b",
    re.IGNORECASE,
)


def _infer_vague_frequency_filter(text: str | None, extracted: dict) -> dict | None:
    """Deterministic backstop: a real-but-unquantified frequency claim
    ("frequent dog parks", "regulars") must not silently produce NO filter
    just because never-invent correctly refused to guess a number. Sets the
    minimal reading of "more than once" (``min_visits: 2``) ONLY when the
    LLM extracted no frequency/cadence/trend predicate of its own for this
    turn — never overrides a real extracted value, and never fires on text
    with no vague-frequency phrase at all.
    """
    if not text or not _VAGUE_FREQUENCY_RE.search(text):
        return None
    af = extracted.get("audience_filter") or {}
    if any(af.get(k) for k in ("min_visits", "min_visits_per_group", "cadence_days", "trend")):
        return None
    return {**af, "min_visits": 2}


# Sidecar-field triggers: each of these fields only means something when its
# OWN evidence is in the text — unlike groups/op/window_days, an LLM stacking
# one of these onto an otherwise-correct extraction (observed on "at least N
# of A, B, or C" phrasing: min_distinct_groups extracted correctly, then
# min_confidence/role-presence/trend_recent_days piled on with a
# self-admitted "inferring... not explicitly stated" rationale) is not a
# harmless extra — min_confidence silently drops unconfirmed visits and the
# role-presence trio silently narrows a plain "visited 3 of 5 kinds of
# place" audience down to a staff-only one. Never-invent applies to EVERY
# field, not just the primary one a phrase obviously maps to.
_CONFIRMED_VISIT_RE = re.compile(
    r"\bdefinitely\b|\bconfirmed\b|\bnot just passing\b", re.IGNORECASE,
)
_ROLE_LANGUAGE_RE = re.compile(
    r"\bowners?\b|\bown\b|\bstaff\b|\bmanagers?\b|\bemployees?\b|\bbarbers?\b|\bworkers?\b",
    re.IGNORECASE,
)


def _strip_unsupported_sidecar_fields(text: str | None, extracted: dict) -> dict | None:
    """Deterministic backstop: drop a sidecar field whose OWN required
    evidence is absent — a hallucinated extra stacked onto an otherwise
    correct extraction, not a wrong primary read (that's Gaps 1/2/4 above).
    Each check is independent and additive; returns None when nothing needed
    stripping (the extraction was already clean).
    """
    af = extracted.get("audience_filter")
    if not isinstance(af, dict):
        return None
    out = dict(af)
    changed = False
    # trend_recent_days/trend_prior_days are sidecars of `trend` — meaningless
    # (and unused downstream) without it.
    if not out.get("trend") and (out.get("trend_recent_days") or out.get("trend_prior_days")):
        out.pop("trend_recent_days", None)
        out.pop("trend_prior_days", None)
        changed = True
    # min_confidence needs an explicit certainty phrase, not just "at least
    # N of" counting language.
    if out.get("min_confidence") and not (text and _CONFIRMED_VISIT_RE.search(text)):
        out.pop("min_confidence", None)
        changed = True
    # exclude_window_days is a sidecar of exclude_groups.
    if not out.get("exclude_groups") and "exclude_window_days" in out:
        out.pop("exclude_window_days", None)
        changed = True
    # The presence-pattern role trio (AUDIENCE_FILTER_ROLE_GUARD) needs real
    # role language ("owners", "staff", "managers", ...) — a plain counting
    # phrase ("any 3 of these 5 spots") is not that.
    if (
        any(out.get(k) is not None for k in
            ("min_open_day_share", "min_intraday_span_min", "min_days_present"))
        and not (text and _ROLE_LANGUAGE_RE.search(text))
    ):
        for k in ("min_open_day_share", "min_intraday_span_min", "min_days_present"):
            out.pop(k, None)
        changed = True
    return out if changed else None


def _apply_audience_filter_backstops(text: str | None, extracted: dict) -> dict | None:
    """Run every deterministic audience_filter backstop in order and return
    the final spec to merge, or None if none fired. Shared by both
    extraction call sites (entry_node's first-mention path and
    extract_user_info_from_text's resume path) so a "both X and Y"/vague-
    frequency correction lands the same whether it's the user's first
    message or a mid-build edit — see this module's docstring note on the
    two paths previously drifting apart on exactly this.

    Whether an "and" list is an intersection (singular items) or a union
    (all-plural) is the extraction prompt's job, not a backstop's — see the
    ``op`` spec in prompts.py.

    Order matters: intersection-inference can SET groups+op from labels the
    LLM extracted separately; vague-frequency only adds min_visits when
    nothing else claimed the frequency slot; sidecar-stripping runs LAST
    since it only removes fields, never sets one, so it cannot interact with
    anything upstream setting them first.
    """
    spec = dict(extracted.get("audience_filter") or {}) if extracted.get("audience_filter") else {}
    working = dict(extracted)
    if spec:
        working["audience_filter"] = spec

    inferred = _infer_intersection_filter(text, working)
    if inferred:
        working["audience_filter"] = inferred

    vague = _infer_vague_frequency_filter(text, working)
    if vague:
        working["audience_filter"] = vague

    stripped = _strip_unsupported_sidecar_fields(text, working)
    if stripped is not None:
        working["audience_filter"] = stripped

    return working.get("audience_filter")


def _engagement_from_text(text: str | None) -> str:
    """Cheap read of how much the user typed → how much room the narrator gets.

    A clipped answer ("yes", "skip", an option click) means the user wants to
    move fast → terse. A full sentence or two means they're leaning in → engaged.
    Mirrors the build-side heuristic in builder._read_user_turn so both write
    points speak the same vocabulary.
    """
    t = (text or "").strip()
    if not t:
        return "normal"
    words = len(t.split())
    if words <= 3:
        return "terse"
    if words >= 12 or "?" in t:
        return "engaged"
    return "normal"


def _format_known_fields(known: dict) -> str:
    """Compact key: value | key: value format for known user context."""
    if not known:
        return ""
    items = []
    for k, v in known.items():
        items.append(f"{k}: {json.dumps(v) if isinstance(v, (list, dict)) else v}")
    return " | ".join(items)


def _validate_audience_filter_clause(clause: dict) -> Optional[dict]:
    """Sanity-check one extracted ``AudienceFilterClause``/``AudienceFilterSpec``
    dict — the structured-output call already enforces the pydantic SHAPE
    (``ExtractedUserInfo.audience_filter``), this enforces the VALUES: no
    zero/negative counts, no out-of-range day-of-week/hour tokens, no empty
    lists left over after cleaning. Previously there was NO validation case
    for ``audience_filter`` at all, so a malformed extraction (e.g. a
    negative ``cadence_days``, an ``hours`` pair with lo >= hi) passed
    through unchecked into targeting.

    Field set is read off ``AudienceFilterClause.model_fields`` rather than
    hand-duplicated here, so a new field added to that model is
    automatically allowed through (still value-checked by the catch-all
    ``else`` branch) instead of silently stripped.

    Returns ``None`` when nothing meaningful survives — an empty clause is a
    no-op filter (match everyone), not "match nobody"; that distinction
    matters (``maid_store.apply_audience_filter``'s empty-spec case).
    """
    if not isinstance(clause, dict):
        return None
    allowed = set(AudienceFilterClause.model_fields) | {"any_of"}
    out: dict[str, Any] = {}
    for key, val in clause.items():
        if key not in allowed or val is None:
            continue
        if key in ("window_days", "min_visits", "min_distinct_pois", "min_distinct_groups", "min_dwell_min",
                   "cadence_days", "cadence_tolerance_days",
                   "min_visits_per_group", "trend_recent_days", "trend_prior_days",
                   "min_intraday_span_min", "min_days_present"):
            try:
                ival = int(val)
            except (ValueError, TypeError):
                continue
            if ival > 0:
                out[key] = ival
        elif key == "exclude_window_days":
            # 0 is MEANINGFUL here ("has never been"), unlike every other
            # integer field above where 0 is an absent constraint.
            try:
                out[key] = max(0, int(val))
            except (ValueError, TypeError):
                continue
        elif key in ("min_share_in_scope", "min_open_day_share"):
            try:
                fval = float(val)
            except (ValueError, TypeError):
                continue
            if 0.0 < fval <= 1.0:
                out[key] = fval
        elif key == "min_confidence":
            if str(val).strip().lower() == "confirmed":
                out[key] = "confirmed"
        elif key == "min_weekly_hours":
            try:
                fval = float(val)
            except (ValueError, TypeError):
                continue
            if fval > 0:
                out[key] = fval
        elif key == "days_of_week":
            if isinstance(val, list):
                days = sorted({
                    int(d) for d in val
                    if isinstance(d, (int, float)) and not isinstance(d, bool) and 0 <= int(d) <= 6
                })
                if days:
                    out[key] = days
        elif key == "hours":
            if (
                isinstance(val, list) and len(val) == 2
                and all(isinstance(h, (int, float)) and not isinstance(h, bool) for h in val)
                and 0 <= val[0] < val[1] <= 24
            ):
                out[key] = [int(val[0]), int(val[1])]
        elif key in ("groups", "exclude_groups"):
            if isinstance(val, list):
                clean = [g for g in val if isinstance(g, str) and g.strip()]
                if clean:
                    out[key] = clean
        elif key == "op":
            if val in ("union", "intersection", "difference"):
                out[key] = val
        elif key == "trend":
            if val in ("started", "lapsed"):
                out[key] = val
        elif key == "invert":
            out[key] = bool(val)
        elif key == "unsupported":
            if isinstance(val, str) and val.strip():
                out[key] = val.strip()
        elif key == "any_of":
            if isinstance(val, list):
                branches = [b for b in (_validate_audience_filter_clause(c) for c in val) if b]
                if branches:
                    out["any_of"] = branches
        else:
            out[key] = val
    return out or None


def _validate_extracted_field(field: str, value: Any) -> Any:
    """Validate a single extracted field. Returns value if valid, else None."""
    if value is None:
        return None

    # Budget: digits only (no text like "five thousand", no "per day" suffix)
    if field == "budget":
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            if re.match(r"^\d+(\.\d+)?$", value.strip()):
                return value.strip()
        return None

    # Location: concrete geocodable place names. Reject only when the WHOLE value
    # is a bare relative phrase ("downtown", "my area"); a concrete place that
    # merely contains such a word ("downtown Montreal") must survive.
    if field == "location":
        if isinstance(value, list):
            clean = [v for v in value if isinstance(v, str) and not is_relative_location(v)]
            return clean if clean else None
        if isinstance(value, str):
            return None if is_relative_location(value) else [value]
        return None

    # Dates: ISO YYYY-MM-DD
    if field in ("campaign_start_date", "campaign_end_date"):
        if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            return value
        return None

    # Ages: int 0–130
    if field in ("target_age_min", "target_age_max"):
        try:
            age = int(value)
            return age if 0 <= age <= 130 else None
        except (ValueError, TypeError):
            return None

    # Exact gender enum
    if field == "target_gender":
        return value if value in ("male", "female", "all") else None

    # Objective: canonicalize free-text / display labels to a Meta objective token
    # (APP_PROMOTION, TRAFFIC, …) so the builder executor's .upper() lookup and the
    # picker prefill both match. Keep the raw string if it maps to nothing — never
    # silently drop a stated goal.
    if field == "campaign_objective":
        from app.graph.builder.executors.campaign import _normalize_objective
        return _normalize_objective(value) or value

    # Positive integers
    if field in ("poi_radius_m", "lookback_days", "search_radius_km"):
        try:
            val = int(value)
            return val if val > 0 else None
        except (ValueError, TypeError):
            return None

    # Arrays must be lists. Strip whitespace/control chars from each entry and
    # drop anything blank after stripping — a garbled/truncated structured-output
    # item (observed: poi_types "caf\n\n" from a mid-string cut) would otherwise
    # reach the Places query and render as a blank line in user-facing text
    # unfiltered. Doesn't recover truncated content (can't tell "caf" apart from
    # a legitimately short type like "spa"), only strips embedded whitespace/newlines.
    if field in ("competitor_brands", "named_places", "poi_types", "anchor_types", "event_queries", "store_addresses", "deterministic_subtypes"):
        if not isinstance(value, list):
            return None
        cleaned = [s.strip() for s in value if isinstance(s, str)]
        cleaned = [s for s in cleaned if s]
        return cleaned or None

    if field == "audience_filter":
        return _validate_audience_filter_clause(value)

    return value


def _validate_extracted(extracted: dict) -> dict:
    """Validate all extracted fields; return dict of valid entries only."""
    valid = {f: v for f, v in
             ((f, _validate_extracted_field(f, v)) for f, v in extracted.items())
             if v is not None}
    # `audience_filter.window_days` ("within the last 45 days") and
    # `lookback_days` ("how far back to search") are deliberately DIFFERENT
    # knobs (see prompts.py's audience_filter spec) — but when the user only
    # ever stated the former, leaving the latter unset means the maid stage
    # asks a "how far back?" question the user already effectively answered,
    # then narrates a lookback_days ("past 7 day(s)") that doesn't match the
    # window actually being enforced by the filter (45 days). Seed the slot's
    # prefill from the stated window so it stops disagreeing with itself —
    # this is a display/prefill default, not a rewrite of window_days, which
    # keeps controlling the actual filter regardless of what this seeds.
    _af = valid.get("audience_filter")
    if isinstance(_af, dict) and _af.get("window_days") and "lookback_days" not in valid:
        valid["lookback_days"] = int(_af["window_days"])
    return valid


def _build_extraction_messages(
    last_human: str,
    known_fields: dict,
    last_ai: str | None = None,
) -> list:
    """Build LLM message list for standalone field extraction (resume path)."""
    from datetime import date as _date

    messages: list = [
        # .replace, not .format — the spec may legally contain literal braces.
        SystemMessage(content=EXTRACTION_ONLY_SYSTEM_PROMPT.replace("{today}", _date.today().isoformat())),
    ]

    if known_fields:
        messages.append(
            SystemMessage(content=f"Known user context: {_format_known_fields(known_fields)}")
        )

    if last_ai:
        # Reference context, NOT a turn to extract from. As a bare AIMessage the
        # model reads Punk's own paraphrase as if the user had said it: on a
        # "yes, go ahead" turn the assistant's "those specific stores" came back
        # as poi_types=["beauty store"], overwriting a correctly extracted
        # competitor_brand angle with a category the user never typed.
        _clamped = last_ai[:500] + ("..." if len(last_ai) > 500 else "")
        messages.append(SystemMessage(content=(
            "Previous assistant message, provided ONLY so you can resolve references "
            "in the user's message ('those', 'it', 'the second one', 'that city'). "
            "It is NOT user input: never take a field value from it.\n"
            "---\n" + _clamped
        )))

    messages.append(HumanMessage(content=last_human))
    return messages


def _split_gemini_thinking(content: Any) -> tuple[str, str]:
    """
    Separate Gemini thinking blocks from the answer text.

    Handles two content shapes:
      - list[dict]: thinking-enabled response with mixed block types
      - str: standard response (thinking disabled or not triggered)

    Returns:
        (thinking_text, answer_text) — either may be an empty string.
    """
    if isinstance(content, str):
        return "", content

    thinking_parts: list[str] = []
    answer_parts: list[str] = []

    for block in content:
        if not isinstance(block, dict):
            answer_parts.append(str(block))
            continue
        block_type = block.get("type", "")
        if block_type == "thinking":
            thinking_parts.append(block.get("thinking", ""))
        else:
            answer_parts.append(block.get("text", ""))

    return "\n".join(thinking_parts), "\n".join(answer_parts)


# ── Thinking-trace introspection helpers ──────────────────────────────────────
# state["thinking"] is a reducer-merged list of per-turn reasoning entries.
# These helpers let nodes read prior reasoning back without recomputing it.

_SUPERVISOR_FAILURE_PATTERN = re.compile(
    r"(Supervisor error|failed after|blocked|locked_refusal|wizard_failure|recovered geo_data)",
    re.IGNORECASE,
)


def _recent_failures(thinking_log: list[str], lookback: int = 12) -> list[str]:
    """Return recent thinking entries that name a failure/blocked/error condition."""
    if not thinking_log:
        return []
    tail = thinking_log[-lookback:]
    return [line for line in tail if line and _SUPERVISOR_FAILURE_PATTERN.search(line)]


# Domain keyword sets used by _extract_last_meaningful_step to filter thinking
# entries down to the wizard that just failed.
_WIZARD_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "geo_targeting_unresolved": ("geo_wizard", "geocode", "POI", "place search", "targeting_method"),
    "maid_audience_unresolved": ("maid", "audience", "radius", "lookback"),
    "campaign_brief_generation_failed": ("campaign", "brief", "budget", "objective"),
    "campaign_meta_json_generation_failed": ("meta", "campaign", "json"),
}

_FAILURE_TOKENS = ("error", "failed", "blocked", "locked_refusal", "unresolved")


def _extract_last_meaningful_step(
    thinking_log: list[str],
    failure_code: str,
) -> str | None:
    """Last non-error thinking line in the failed wizard's domain.

    Used by chatbot_node's wizard_failure branch to surface the last successful
    step before things derailed — so the chatbot can say "you were close at X"
    instead of asking the user to start over blind.
    """
    if not thinking_log:
        return None
    keywords = _WIZARD_DOMAIN_KEYWORDS.get(failure_code)
    if not keywords:
        return None
    keywords_lower = tuple(k.lower() for k in keywords)
    for line in reversed(thinking_log):
        if not line:
            continue
        lower = line.lower()
        if any(tok in lower for tok in _FAILURE_TOKENS):
            continue
        if any(k in lower for k in keywords_lower):
            return line.strip()
    return None


# ── Durable step markers (mirrors campaign_wizard helpers; local copy avoids a
#    wizard→nodes import cycle). Persist via user_info's merge reducer. ─────────

def _step_done(user_info: dict, step: str) -> bool:
    return step in (user_info.get("wizard_steps_done") or [])


def _mark_step_done(user_info: dict, step: str) -> None:
    arr = list(user_info.get("wizard_steps_done") or [])
    if step not in arr:
        arr.append(step)
    user_info["wizard_steps_done"] = arr


_STORE_ANCHORED_SUBTYPES: frozenset[str] = frozenset({"store_set", "competitor_nearby"})


def _collapse_deterministic_subtypes(multi: list[str]) -> str | None:
    """Collapse a multi-angle extraction into the `deterministic_subtype` string the
    geo slot reads. Thin wrapper over ``slots.merge_angle_tokens`` so entry
    extraction and the mid-flow edit lane share one union implementation.

    Returns the collapsed string, or None when there is nothing usable to set.
    """
    from app.graph.builder.slots import merge_angle_tokens

    return merge_angle_tokens(multi) or None


def _store_anchored(user_info: dict) -> bool:
    """True when the user named an own-store targeting angle. For store_set /
    competitor_nearby the audience is built from the user's OWN store (the store
    itself, or the anchor Punk searches around for competitors), and that address
    is collected later inside the builder — so a separately-named market (WHERE) is
    NOT required to start the build."""
    _subs = {
        s.strip() for s in str(user_info.get("deterministic_subtype") or "").split(",")
        if s.strip()
    }
    return bool(
        _subs & _STORE_ANCHORED_SUBTYPES
        or user_info.get("store_addresses")
        or user_info.get("competitor_address")
    )


def _has_angle(user_info: dict) -> bool:
    """True when a CONCRETE targeting angle exists — the user named (or Punk
    resolved) which real-world places/people to build the audience from. Covers the
    concrete place/brand/event fields only; `deterministic_subtype` is handled by
    each caller because its meaning is context-dependent (a guided delegation is
    not a self-explained angle for the onboarding fork, but still defines WHO for
    the build gate)."""
    return bool(
        user_info.get("poi_types")
        or user_info.get("anchor_types")
        or user_info.get("competitor_brands")
        or user_info.get("named_places")
        or user_info.get("store_addresses")
        or user_info.get("event_queries")
        or user_info.get("competitor_address")
    )


# Follow-ups for the CODE build gate below — the routing LLM's own follow_ups
# are empty whenever it picked a wizard route (prompts.py's "emit [] for all
# others" instruction), so when the gate overrides that route back to chatbot
# for a missing WHERE/WHO/WHAT, nothing else in the turn ever proposes the one
# question that would unblock it. Without this the fallback CLARIFY branch in
# chatbot_node was the only thing left to ask, and its own prose explicitly
# banned asking WHAT — a real deadlock (see the wholesale-coffee thread).
# Wording mirrors the spec the routing LLM is taught at prompts.py:911-922.
_GATE_FOLLOW_UPS: dict[str, dict[str, str]] = {
    "where": {
        "ask": "Which city, region, or market should the ads run in?",
        "why": "Targeting needs a concrete, geocodable place to search.",
    },
    "who": {
        "ask": "Who do you want to reach — an interest, demographic, or occupation?",
        "why": "Defines the audience the campaign is built around.",
    },
    "what": {
        "ask": "What do you sell, and what makes you the best choice?",
        "why": "Feeds the place mapper that picks relatable POI types to build the audience from.",
    },
}


def _gate_signals(current: dict) -> tuple[bool, bool, bool]:
    """The build gate's three hard signals — (has_where, has_who, has_what).

    Pure and side-effect-free so it is unit-testable without the two LLM calls
    `entry_node` otherwise requires. See the call site in `entry_node` for the
    full rationale of each signal; kept here as the single source of truth so
    the build gate, its store-anchored WHERE exemption, and the resume fallback
    can never drift from each other.
    """
    has_where = bool(current.get("location")) or _store_anchored(current)
    has_who = bool(
        current.get("target_audience")
        or _has_angle(current)
        or current.get("deterministic_subtype")   # guided ai_suggested, pre-POI
    )
    # product_offer is NOT a WHAT signal — its extraction spec (prompts.py) is a
    # promotional detail ("50% off launch week", "grand opening this Friday"),
    # not what the business sells. Counting it here let a promo-only message
    # ("50% off this week, reach gym-goers in Austin") satisfy WHAT with
    # business_description still empty: the gate opened, geo ran with nothing
    # to build POI context from (_geo_business_desc in builder_node.py reads
    # ONLY business_description too), and the real "what do you sell" question
    # only ever surfaced later — the exact ordering bug this gate exists to
    # prevent. Keep this the single source of truth for WHAT.
    has_what = bool(str(current.get("business_description") or "").strip())
    return has_where, has_who, has_what


# ── Node: entry (merged guardrail + intent extraction + supervisor) ────────────

async def entry_node(state: AgentState) -> dict[str, Any]:
    """
    Single entry node — first node executed on every user turn.

    Two parallel Flash temp-0 structured calls (routing + extraction, run
    concurrently) do what used to take three serial LLM calls (guardrail →
    intent_extraction → supervisor): topic filtering, routing, and business-field
    extraction. The jobs were split because a single Flash call filling the
    combined ~25-field EntryDecision returned mostly nulls (thin user_info then
    skipped the geo plan review and tripped the soft geo guard, making routing
    erratic); giving extraction its own focused Flash call fixes that while
    dropping the slow Pro+thinking call from the hot path. Behavior contracts
    preserved from the old pipeline:
      • off-topic turns emit the guardrail_reject-tagged message for chatbot
      • extraction merges overwrite-on-non-null into user_info
      • the soft geo guard blocks geo_agent when there is zero business signal
      • missing_signals is forwarded only on chatbot clarify routes
    Never appends user-visible messages — routing and state only.
    """
    writer = get_stream_writer()

    # Bypass LLM when campaign_manager has a pending write awaiting confirmation.
    # The user's last message is a yes/no response — route directly so the
    # campaign_manager_node can execute or cancel the write without LLM misrouting.
    cm_state = state.get("campaign_manager_state") or {}
    if cm_state.get("awaiting_write_tool"):
        writer({"type": "thinking", "content": "Entry: campaign manager write pending — bypassing LLM, routing to campaign_manager"})
        return {"next_nodes": ["campaign_manager"], "pending_action": None}

    writer({"type": "thinking", "content": "Entry: classifying topic, routing, and extracting business details..."})
    logger.info("Entry start: thread=%s", state.get("thread_id", "n/a"))

    from datetime import date as _date

    # Static body kept byte-identical across sessions AND days so Gemini's
    # implicit prefix cache hits maximally — all dynamic content (today, wizard
    # context, known fields, failures) is appended below as a trailing suffix.
    system_prompt = ENTRY_SYSTEM_PROMPT
    system_prompt += f"\n\n── TODAY ──\n{_date.today().isoformat()}"

    wizard_context = _build_wizard_state_context(state)
    logger.info("Entry wizard context: %s", wizard_context)
    system_prompt += f"\n\n── CURRENT WIZARD PROGRESS ──\n{wizard_context}"

    # A paused build is invisible to the wizard-progress block above: that reads
    # geo_data and the legacy geo_wizard_state, neither of which says whether the
    # builder still holds a half-finished campaign. Entry never looked at
    # campaign_builder_state at all, so it could not offer to resume one.
    _bstate = state.get("campaign_builder_state") or {}
    if _bstate.get("filled"):
        _done = ", ".join(_bstate.get("stages_complete") or []) or "none yet"
        system_prompt += (
            "\n\n── BUILD IN PROGRESS ──\n"
            f"A campaign build is PAUSED with {len(_bstate['filled'])} answer(s) saved "
            f"(stages complete: {_done}).\n"
            "If the user wants to carry on with it, route 'campaign_builder' — that "
            "resumes exactly where they left off. Never route 'geo_agent' for a resume; "
            "it restarts from the beginning."
        )
        writer({"type": "thinking", "content": (
            f"Entry: paused build detected — {len(_bstate['filled'])} slot(s), "
            f"stages_complete={_bstate.get('stages_complete') or []}"
        )})

    _ob_steps = (state.get("user_info") or {}).get("wizard_steps_done") or []
    _ob_status = (
        "complete" if "onboarding" in _ob_steps
        else ("in progress" if "onboarding_started" in _ob_steps else "not started")
    )
    system_prompt += f"\n\n── ONBOARDING STATUS ──\n{_ob_status}"

    recent_failures = _recent_failures(state.get("thinking") or [])
    if recent_failures:
        failures_block = "\n".join(f"- {line}" for line in recent_failures)
        system_prompt += (
            "\n\n── RECENT FAILURES (last ~2 turns) ──\n"
            f"{failures_block}\n"
            "Avoid repeating the same dead-end route. Prefer chatbot for "
            "clarification when prior attempts to a wizard already failed."
        )
        writer({
            "type": "thinking",
            "content": f"Entry: {len(recent_failures)} recent failure signal(s) injected into prompt",
        })

    known_fields = {k: v for k, v in (state.get("user_info") or {}).items() if v is not None}
    if known_fields:
        system_prompt += (
            "\n\n── KNOWN USER CONTEXT ──\n"
            f"{_format_known_fields(known_fields)}\n"
            "Do not re-extract unchanged fields — return null for them."
        )

    # Two parallel Flash calls replace the old single Pro+thinking call: a
    # routing-only decision (EntryRouting) and a field-extraction call
    # (ExtractedUserInfo), run concurrently via asyncio.gather. The combined
    # 25-field EntryDecision needed Pro to fill reliably (Flash returned mostly
    # nulls on the combined schema); splitting the jobs keeps each Flash call
    # focused, and overlapping them makes entry latency ≈ one Flash call instead
    # of one slow Pro+thinking call. temp 0 keeps both deterministic.
    #
    # Bounded history slice (3 turns, matches builder_plan) — enough for reference
    # resolution ("yes"/"the second one") and multi-turn extraction. Known fields
    # are re-injected via the KNOWN USER CONTEXT block above, so trimming the raw
    # transcript loses no established context and kills O(n)-per-session growth.
    routing_llm = _make_llm(temperature=0.0).with_structured_output(
        EntryRouting, include_raw=True
    )
    # Filter BEFORE slicing — a build appends ~40 ledger records, which would fill
    # the 6-message window entirely and hide the real conversation from routing.
    routing_messages = [SystemMessage(content=system_prompt)] + [
        m for m in state["messages"] if is_conversational(m)
    ][-6:]

    # Extraction reuses the resume-path surface (proven on Flash): the focused
    # EXTRACTION_ONLY prompt + ExtractedUserInfo schema, seeded with known fields
    # and the last AI turn for reference resolution.
    last_human = _extract_last_human_text(state)
    extraction_llm = _make_llm(temperature=0.0, model=settings.GEMINI_MODEL_PRO).with_structured_output(
        ExtractedUserInfo, include_raw=True
    )
    extraction_messages = (
        _build_extraction_messages(last_human, known_fields, _extract_last_ai_text(state))
        if last_human
        else None
    )

    async def _route() -> Any:
        res, _u = await tracked_ainvoke(
            routing_llm, routing_messages, node_name="entry_routing", writer=writer
        )
        return res

    async def _extract() -> Any:
        if extraction_messages is None:
            return None
        res, _u = await tracked_ainvoke(
            extraction_llm, extraction_messages, node_name="entry_extraction", writer=writer
        )
        return res

    decision, extracted_model = await asyncio.gather(
        _route(), _extract(), return_exceptions=True
    )

    # Routing is load-bearing — a failure there falls back to chatbot. Extraction
    # is best-effort: a failure just means no new fields are merged this turn.
    if isinstance(decision, BaseException):
        logger.error("entry_node routing call failed — routing to chatbot: %s", decision)
        writer({"type": "thinking", "content": f"Entry error: {decision} -> routing to chatbot"})
        return {"next_nodes": ["chatbot"], "pending_action": None}
    if isinstance(extracted_model, BaseException):
        logger.warning(
            "entry_node extraction call failed — retrying once: %s", extracted_model,
        )
        try:
            extracted_model = await _extract()
        except Exception as retry_exc:
            logger.warning(
                "entry_node extraction retry also failed — proceeding with no new fields: %s",
                retry_exc,
            )
            extracted_model = None

    # Off-topic: tag an internal message so chatbot_node declines politely.
    # No extraction merge — off-topic text is not business signal.
    if decision.off_topic:
        writer({"type": "thinking", "content": f"Entry: off-topic ('{decision.detected_topic}') — deflecting via chatbot"})
        return {
            "next_nodes": ["chatbot"],
            "pending_action": None,
            "messages": [
                AIMessage(
                    content=decision.detected_topic,
                    additional_kwargs={"role": "guardrail_reject"},
                )
            ],
        }

    # Extraction merge: overwrite on non-null — allows corrections from user.
    extracted_raw = extracted_model.model_dump(exclude_none=True) if extracted_model else {}
    extracted = _validate_extracted(extracted_raw)
    _before_af = extracted.get("audience_filter")
    _after_af = _apply_audience_filter_backstops(last_human, extracted)
    if _after_af is not None and _after_af != _before_af:
        extracted["audience_filter"] = _after_af
        writer({"type": "thinking", "content": (
            f"Entry: audience_filter backstop(s) applied -> {_before_af!r} -> {_after_af!r}"
        )})
    current: UserInfo = dict(state.get("user_info") or {})
    for field, value in extracted.items():
        if value is not None:
            current[field] = value
    # Per-angle specs (divergent where/what): resolve the transport
    # `targeting_angles` into the durable `geo_angle_specs` (list of dicts the geo
    # executor reads) and seed the angle tokens so the existing collapse + slot
    # gating still run. Mirrors the deterministic_subtypes transport pattern below:
    # the transport is popped so a later correction is not overwritten by stale
    # specs. Emitting targeting_angles this turn REPLACES any prior specs.
    _angles = current.get("targeting_angles")
    # A fresh flat subtypes extraction this turn (present BEFORE we derive it from
    # specs) is a correction — it must clear stale per-angle specs so the old combo
    # isn't silently re-applied (same hazard the deterministic_subtypes transport
    # guards against).
    _fresh_flat_subtypes = isinstance(extracted.get("deterministic_subtypes"), list)
    if isinstance(_angles, list) and _angles:
        _specs = [
            (a.model_dump(exclude_none=True) if hasattr(a, "model_dump") else dict(a))
            for a in _angles if a
        ]
        _specs = [s for s in _specs if s.get("angle")]
        if _specs:
            current["geo_angle_specs"] = _specs
            # Seed the angle set for collapse/slot gating unless the user already
            # named subtypes explicitly this turn.
            if not current.get("deterministic_subtypes"):
                current["deterministic_subtypes"] = list(
                    dict.fromkeys(s["angle"] for s in _specs)
                )
            # Seed the flat `location` with the UNION of every spec's locations so the
            # WHERE gate + the `locations` slot are satisfied (the user DID name cities,
            # just per-angle) and the confirm map shows them all. Merge, preserving any
            # already-present shared location, order-preserving + de-duped.
            _spec_locs = [
                str(loc) for s in _specs for loc in (s.get("locations") or [])
                if str(loc).strip()
            ]
            if _spec_locs:
                _existing = [str(x) for x in (current.get("location") or [])]
                current["location"] = list(dict.fromkeys(_existing + _spec_locs))
            # Seed the flat TYPE fields from the union of spec types, for the same
            # reason: the collection slots gate on these, so leaving them empty would
            # re-ask for types the user already named per-angle. The executor still
            # routes each type to its own angle via the specs; these flats only unblock
            # slot gating and drive the progress display.
            for _fld in ("poi_types", "anchor_types", "event_queries",
                         "named_places", "competitor_brands"):
                _vals = [
                    str(v) for s in _specs for v in (s.get(_fld) or []) if str(v).strip()
                ]
                if _vals:
                    _cur = [str(x) for x in (current.get(_fld) or [])]
                    current[_fld] = list(dict.fromkeys(_cur + _vals))
            _dr = next(
                (s.get("event_date_range") for s in _specs if s.get("event_date_range")),
                None,
            )
            if _dr and not current.get("event_date_range"):
                current["event_date_range"] = _dr
            writer({"type": "thinking", "content": (
                f"Entry: per-angle specs → {[s['angle'] for s in _specs]}"
            )})
    elif _fresh_flat_subtypes and current.get("geo_angle_specs"):
        current.pop("geo_angle_specs", None)
        writer({"type": "thinking", "content": (
            "Entry: flat angle correction — cleared stale per-angle specs"
        )})
    current.pop("targeting_angles", None)

    # Collapse a multi-angle extraction into ONE downstream value: the det_type
    # slot reads `deterministic_subtype`, so a combo becomes a comma-joined set
    # (e.g. "store_set,event_based"). De-dupe, preserve order. A single-entry
    # list is treated as a plain single subtype.
    _multi = current.get("deterministic_subtypes")
    if isinstance(_multi, list) and _multi:
        _collapsed = _collapse_deterministic_subtypes(_multi)
        if _collapsed is not None:
            current["deterministic_subtype"] = _collapsed
            writer({"type": "thinking", "content": f"Entry: angles → {_collapsed}"})
    # `deterministic_subtypes` is a PER-TURN transport, not durable state — the
    # collapsed string is the durable value. Persisting it would re-collapse stale
    # angles on every later turn, silently overriding a correction ("actually, just
    # events" would be overwritten back to the old combo) and re-firing any beat
    # keyed off it. Drop it once consumed.
    current.pop("deterministic_subtypes", None)
    if extracted:
        writer({"type": "thinking", "content": f"Entry extracted (validated): {sorted(extracted)}"})

    route_name = decision.route
    missing_signals = list(decision.missing_signals or [])

    # "campaign_builder" means RESUME, so it needs something to resume. A "yes"
    # with no paused build is a fresh build request: rewrite it to geo_agent HERE,
    # before the onboarding / build gates, so it still passes through them (recovery
    # extraction, clarify follow-ups). Handling it after the gates let a resume
    # with a missing signal fall to a chatbot turn with no brief, which then
    # invented a next step (budget) — thread a90cc17c.
    if route_name == "campaign_builder" and not (state.get("campaign_builder_state") or {}).get("filled"):
        writer({"type": "thinking", "content": (
            "Entry guard: 'campaign_builder' resume requested but no paused build exists "
            "— treating as geo_agent."
        )})
        route_name = "geo_agent"

    # Self-healing: if geo_data is missing but scratchpad has results, surface a thinking hint.
    geo_data = state.get("geo_data") or {}
    ws = state.get("geo_wizard_state") or {}
    if not geo_data.get("pois_found") and ws.get("_det_result"):
        writer({"type": "thinking", "content": "Entry self-healing: recovered geo_data from wizard scratchpad."})

    # Routing gate's three hard signals — WHERE (a named market, or a store-anchored
    # angle whose address the builder collects later), WHO (an explicit
    # target_audience, OR a concrete/derived targeting angle — once an angle is
    # chosen the audience is defined, so poi_types / a delegated deterministic_
    # subtype satisfy WHO even when the extractor never captured an audience noun),
    # AND WHAT (what the business sells / its edge — business_description ONLY).
    # WHAT feeds the dynamic place mapper (get_dynamic_place_types) as well as
    # the brief/persona/copy — a build that starts without it picks POIs from
    # the audience alone and reads generic. This aligns the code guard with the
    # router's own reasoning and unblocks the guided "you suggest" fast-path.
    # The BLOCK itself runs AFTER the onboarding / guidance gate below, so a
    # no-angle user still gets their guidance turn instead of a bare
    # where/who/what clarify; these flags are also read by the store-anchored
    # WHERE exemption just below. See _gate_signals for why product_offer does
    # NOT satisfy WHAT.
    has_where, has_who, has_what = _gate_signals(current)

    # ── Guided lean: user wants Punk to recommend the targeting approach ───────
    # Either unsure who/where, or named who/where but asked HOW ("how should I do
    # this?"). Coerce the deterministic ai_suggested path so the geo flow can run
    # Punk's recommendation once the user gives the go-ahead.
    guided = current.get("targeting_choice") == "guided"
    if guided:
        if not current.get("deterministic_subtype"):
            current["deterministic_subtype"] = "ai_suggested"

    # ── Store-anchored WHERE exemption ─────────────────────────────────────────
    # For store_set / competitor_nearby the user's OWN store is the geo anchor
    # (collected later in the builder), so a named market is not required. If the
    # LLM held the user at chatbot only for a missing WHERE, clear it and let the
    # build proceed — mirrors the "prompt teaches, code catches misfires" guard
    # above. A named angle is required; a bare location alone does NOT trigger this.
    # WHO (target_audience) and WHAT (business description) are still required —
    # only flip back to build when both are present and WHERE was the sole
    # remaining gap.
    if _store_anchored(current) and "where" in missing_signals:
        missing_signals = [s for s in missing_signals if s != "where"]
        if route_name == "chatbot" and not missing_signals and has_who and has_what:
            route_name = "geo_agent"

    # Did the user EXPLAIN a concrete POI/PLACE ANGLE themselves? The two-path
    # fork is about the HOW (which real-world places/people to target), so only a
    # concrete angle skips it. A bare location or a bare audience is NOT an angle —
    # those users still get the guidance fork. A guided "you decide" also does not
    # count (handled separately below). Self-directed explained angles skip to build.
    target_explained = _has_angle(current) or (
        current.get("deterministic_subtype") and not guided
    )

    # ── Onboarding / guidance gate ────────────────────────────────────────────
    # GUIDED → ONE conversational recommendation turn (answer their "how", explain
    #   an approach), then build on the next go-ahead.
    # SELF-DIRECTED + explained target → straight to the geo flow, no guidance.
    # Build intent but nothing explained → one guidance turn.
    # Durable markers: "onboarding_started" → fork/guidance turn given;
    #   "onboarding_recommended" → the concrete angle recommendation was delivered;
    #   "onboarding" → done. The FORK turn is not a recommendation, so a user who
    #   delegates ("help me") AFTER the fork still earns its own recommendation turn
    #   — it names the concrete angle before building, instead of dropping into a
    #   generic geo narration.
    onboarding_active = False
    _ob_done = _step_done(current, "onboarding")
    _ob_started = _step_done(current, "onboarding_started")
    _ob_recommended = _step_done(current, "onboarding_recommended")
    if route_name in ("onboarding", "geo_agent") and not _ob_done:
        if guided and not _ob_recommended:
            # Delegated — give ONE concrete angle recommendation turn (names the
            # actual approach for THIS business), await go-ahead. Works whether the
            # delegation lands on the first turn or right after the two-path fork.
            onboarding_active = True
            route_name = "chatbot"
            _mark_step_done(current, "onboarding_started")
            _mark_step_done(current, "onboarding_recommended")
        elif guided:
            # Recommendation already given; user is responding → build.
            route_name = "geo_agent"
            _mark_step_done(current, "onboarding")
        elif target_explained:
            # Self-directed, explained target — straight to build.
            route_name = "geo_agent"
            _mark_step_done(current, "onboarding")
        elif not _ob_started:
            # Build intent, nothing explained — one guidance turn.
            onboarding_active = True
            route_name = "chatbot"
            _mark_step_done(current, "onboarding_started")
        else:
            # Guidance already happened; brain now judges the goal clear.
            route_name = "geo_agent"
            _mark_step_done(current, "onboarding")
    elif route_name == "onboarding":
        route_name = "geo_agent"              # onboarding already complete
    if onboarding_active:
        writer({"type": "thinking", "content": "Entry: guidance/recommendation turn active before build."})

    # ── Build gate: require WHERE + WHO + WHAT before actually starting the build ──
    # Runs AFTER the onboarding gate so a no-angle user's guidance turn is never
    # preempted (onboarding_active routes to chatbot and is left untouched here).
    # Only a resolved geo_agent route is held: if the market (WHERE), audience
    # (WHO), or what the business sells (WHAT) is still missing, drop back to a
    # chatbot clarify asking exactly those. WHAT is gated because the dynamic
    # place mapper (get_dynamic_place_types) reads business_description to pick
    # relatable POI types — starting the build without it picks POIs from the
    # audience alone. A promo/offer mention (product_offer) does NOT satisfy
    # WHAT — naming a sale without saying what the business is leaves the
    # mapper with nothing either. Catches LLM misfires; the prompt teaches the
    # same gate.
    #
    # Recovery pass: this turn's extraction call only ever reads the LATEST
    # human message, so a field stated once on an earlier turn and then never
    # repeated (e.g. lost to a genuine parse failure — see tracked_ainvoke's
    # raise) stays permanently null and the gate blocks forever. Before
    # blocking, retry extraction over EVERY prior human turn concatenated, and
    # merge only fields still absent from `current` — never overwrites, so a
    # later correction can't be reverted by stale older text. One extra Flash
    # call, only on the turn that would otherwise stall.
    if route_name == "geo_agent" and not (has_where and has_who and has_what):
        _prior_human = " ".join(
            str(m.content) for m in state["messages"]
            if isinstance(m, HumanMessage) and isinstance(m.content, str) and is_conversational(m)
        ).strip()
        if _prior_human and _prior_human != (last_human or ""):
            try:
                _recovery_llm = _make_llm(temperature=0.0, model=settings.GEMINI_MODEL_PRO).with_structured_output(
                    ExtractedUserInfo, include_raw=True
                )
                _recovery_parsed, _ = await tracked_ainvoke(
                    _recovery_llm,
                    _build_extraction_messages(_prior_human, known_fields, None),
                    node_name="entry_extraction_recovery",
                    writer=writer,
                )
                _recovered = _validate_extracted(
                    _recovery_parsed.model_dump(exclude_none=True) if _recovery_parsed else {}
                )
            except Exception as recovery_exc:
                logger.warning("Entry recovery extraction failed: %s", recovery_exc)
                _recovered = {}
            _new_fields = {
                f: v for f, v in _recovered.items()
                if v is not None and current.get(f) is None
            }
            if _new_fields:
                current.update(_new_fields)
                has_where, has_who, has_what = _gate_signals(current)
                writer({"type": "thinking", "content": (
                    f"Entry recovery: recovered field(s) from earlier turns -> {sorted(_new_fields)}"
                )})
                logger.info("Entry recovery: recovered %s", sorted(_new_fields))

    gate_blocked_signals: list[str] = []
    if route_name == "geo_agent" and not (has_where and has_who and has_what):
        writer({"type": "thinking", "content": "Entry guard: build blocked — missing WHERE/WHO/WHAT. Rerouting to chatbot for clarification."})
        logger.info(
            "Entry guard: build blocked (where=%s who=%s what=%s), rerouting to chatbot",
            has_where, has_who, has_what,
        )
        route_name = "chatbot"
        need = [
            s for s, present in (("where", has_where), ("who", has_who), ("what", has_what))
            if not present
        ]
        if need:
            missing_signals = need
        gate_blocked_signals = need

    # Only forward missing_signals when we're actually routing to chatbot for
    # a clarify turn — other destinations should not carry stale signals. While
    # onboarding discovery owns the turn, suppress clarify signals entirely.
    forwarded_signals = (
        missing_signals if route_name == "chatbot" and not onboarding_active else []
    )

    # Tailored follow-ups ride along only on chatbot clarify routes. The greeting
    # soft-guard above leaves decision.follow_ups empty, so a pure no-signal
    # greeting still gets the warm welcome rather than a question pile. Discovery
    # mode suppresses them (it owns the conversation).
    forwarded_follow_ups = (
        [f.model_dump() for f in decision.follow_ups]
        if route_name == "chatbot" and not onboarding_active
        else []
    )
    # The routing LLM authored no follow-ups (it picked a wizard route before the
    # code gate overrode it back to chatbot) — synthesize from the gate's own
    # missing signals so the turn never falls through to the unguided fallback
    # CLARIFY branch, which is the deadlock this closes.
    if not forwarded_follow_ups and gate_blocked_signals and route_name == "chatbot":
        forwarded_follow_ups = [
            dict(_GATE_FOLLOW_UPS[s]) for s in gate_blocked_signals if s in _GATE_FOLLOW_UPS
        ]

    writer({"type": "thinking", "content": f"Entry decision: '{route_name}' (reasoning: {decision.reasoning})"})
    logger.info("Entry route: %s (from LLM: %s)", route_name, decision.route)

    # Per-turn read of the human's latest message for the narrator (mood +
    # their own phrasing + engagement). No reducer — fresh each turn, consumed by
    # the composer this same turn, cleared by omission next turn.
    user_turn = {
        "phrase": decision.user_turn_digest,
        "mood": decision.mood or "neutral",
        "engagement": _engagement_from_text(_extract_last_human_text(state)),
        "embedded_ask": (
            decision.user_turn_digest
            if decision.user_turn_digest and "?" in decision.user_turn_digest
            else None
        ),
    }

    result: dict[str, Any] = {
        "user_info": current,
        "next_nodes": [route_name],
        "onboarding_active": onboarding_active or None,
        "pending_action": None,
        "clarify_reason": decision.clarify_reason,
        "missing_signals": forwarded_signals or None,
        "follow_ups": forwarded_follow_ups or None,
        "flow_blocked": decision.flow_blocked if route_name == "chatbot" else None,
        "user_turn": user_turn,
    }

    # A change typed while a build is paused (no interrupt to catch it) used to
    # reach only `user_info`: builder_plan seeds slots once, so every slot that
    # was already filled kept its old value and the user was told nothing. Send
    # it through the edit bus instead — applied, narrated, undoable.
    if route_name == "campaign_builder" and _bstate.get("filled") and extracted:
        from app.graph.builder.edits import edits_from_extraction
        from app.graph.narrator.beats import record_change

        _typed, _held = edits_from_extraction(extracted, state, _bstate)
        if _typed or _held:
            _new_bs = dict(_bstate)
            _pend = dict(_new_bs.get("_pending_edits") or {})
            _pend.update(_typed)
            if _pend:
                _new_bs["_pending_edits"] = _pend
            result["campaign_builder_state"] = _new_bs
            record_change(state, heard={f: f"change {f}" for f in _typed})
            if _held:
                record_change(state, deviation=(
                    "didn't change " + ", ".join(sorted(set(_held))) + " yet — it would "
                    "re-pull audience data you already have; say it again at the next "
                    "question and I'll do it there"
                ))
            writer({"type": "thinking", "content": (
                f"Entry: typed change to a paused build → edit bus {sorted(_typed)}, held {_held}"
            )})
    return result


# ── Helper: standalone user_info extraction (used by chat.py resume path) ────

async def extract_user_info_from_text(
    text: str,
    current: dict | None = None,
    last_ai_response: str | None = None,
) -> dict:
    """Run field extraction on a raw user message string. Returns merged user_info.

    Used by /chat/{id}/resume to update user_info when the graph entry node
    is skipped on resume. Same extraction surface as entry_node
    (ExtractedUserInfo, Flash temp 0, structured output — no thinking).
    Overwrite-on-non-null merge: extracted non-null values update user_info.
    """
    current = dict(current or {})
    text = (text or "").strip()
    if not text:
        return current

    llm = _make_llm(temperature=0.0, model=settings.GEMINI_MODEL_PRO)
    structured_llm = llm.with_structured_output(ExtractedUserInfo, include_raw=True)
    known_fields = {k: v for k, v in current.items() if v is not None}
    messages = _build_extraction_messages(text, known_fields, last_ai_response)

    try:
        parsed, _usage = await tracked_ainvoke(
            structured_llm, messages, node_name="intent_extraction_resume", writer=None
        )
        extracted: dict[str, Any] = parsed.model_dump(exclude_none=True) if parsed else {}
    except Exception as exc:
        logger.error("extract_user_info_from_text LLM call failed: %s", exc)
        return current

    extracted = _validate_extracted(extracted)
    _after_af = _apply_audience_filter_backstops(text, extracted)
    if _after_af is not None and _after_af != extracted.get("audience_filter"):
        extracted["audience_filter"] = _after_af

    for field, value in extracted.items():
        if value is not None:
            current[field] = value
    return current


# ── Node: knowledge_based ──────────────────────────────────────────────────────

def _knowledge_query_context(state: AgentState) -> str:
    """Advertiser context for the grounded knowledge call: business, industry,
    and target market — without it the grounded prompt has no idea WHOSE Meta
    Ads question this is, and answers generically (wrong currency, wrong market
    assumptions, and no signal to tell a Punk-product question from a Meta one)."""
    info = state.get("user_info") or {}
    parts = [
        info.get("business_name"),
        info.get("industry"),
        info.get("business_description") or info.get("product_offer"),
        info.get("target_audience"),
    ]
    location = info.get("location")
    if location:
        parts.append("targeting " + ", ".join(str(loc) for loc in location))
    return " | ".join(str(p).strip() for p in parts if str(p or "").strip())


async def knowledge_based_node(state: AgentState) -> dict[str, Any]:
    """
    Answer a Meta Ads knowledge question using the knowledge base tool.

    Retrieves relevant documentation, then routes to chatbot_node which
    synthesizes the retrieved content into a conversational response.
    The raw knowledge is stored temporarily in geo_data-style — instead,
    we pass it to chatbot via a special AIMessage tag so chatbot can use it.

    Questions about Punk's own product (not public Meta facts) resolve to ""
    from the tool — see _KNOWLEDGE_PROMPT's NONE rule — and no tagged message is
    emitted at all, so chatbot_node answers purely from CHATBOT_SYSTEM_PROMPT's
    own Punk knowledge base instead of a web-grounded non-answer.
    """
    writer = get_stream_writer()
    query = _extract_last_human_text(state) or "Meta Ads best practices"
    context = _knowledge_query_context(state)

    writer({"type": "thinking", "content": f"Knowledge agent: retrieving docs for query: {query!r}"})
    try:
        knowledge: str = await retrieve_marketing_knowledge.ainvoke(
            {"query": query, "context": context}
        )
    except Exception as exc:
        logger.error("knowledge_based_node retrieval failed: %s", exc)
        knowledge = ""

    if not knowledge:
        writer({"type": "thinking", "content": "Knowledge agent: no grounded Meta-facts answer — leaving it to Punk's own knowledge"})
        return {"next_nodes": ["chatbot"]}

    writer({"type": "thinking", "content": "Knowledge agent: retrieved content, forwarding to chatbot"})

    # Pass retrieved knowledge to chatbot via a tagged system message that
    # chatbot_node will detect and use as grounding context.
    return {
        "next_nodes": ["chatbot"],
        "messages": [
            AIMessage(
                content=knowledge,
                additional_kwargs={"role": "knowledge_context"},
            )
        ],
    }


# ── Between-wizard handoff detection (narrator v2, Phase 6) ──────────────────

# A "proceed" reply is a short affirmative with no question — the only case the
# structured handoff narrator should hijack. Anything else (a question, a new
# detail) falls through to the full chatbot LLM so nothing is lost.
_HANDOFF_PROCEED_WORDS = frozenset({
    "yes", "y", "yeah", "yep", "ok", "okay", "sure", "ready", "proceed",
    "continue", "go", "go ahead", "let's go", "lets go", "next", "sounds good",
    "ready to continue", "ok ready to continue", "lets continue", "let's continue",
})


def _looks_like_proceed(text: str) -> bool:
    t = (text or "").strip().lower().rstrip("!.")
    if not t or "?" in t:
        return False
    return t in _HANDOFF_PROCEED_WORDS


def _detect_handoff(state: AgentState) -> Optional[dict]:
    """Return ``{stage, facts}`` for a clean between-wizard transition, else None.

    Mirrors the stage logic in chatbot_node's context builder but only fires on
    a transition the structured 4-beat narrator can own end-to-end. Returns None
    for the zero-MAID case (the chatbot LLM has bespoke handling) and for any
    state where a wizard hasn't actually completed.
    """
    geo_data = state.get("geo_data")
    if not geo_data:
        return None
    st = derive_stage(state)

    if not st["maid_done"]:
        locs = [l.get("location_name") for l in (geo_data.get("locations") or []) if l.get("location_name")]
        return {
            "stage": "geo_to_maid",
            "facts": {"stage": "geo_to_maid", "poi_count": st["pois"], "locations": locs, "method": st["method"]},
        }
    if not st["campaign_done"]:
        if st["maid_count"] == 0:
            return None  # apologetic zero-result handoff stays with the chatbot LLM
        return {
            "stage": "maid_to_campaign",
            "facts": {
                "stage": "maid_to_campaign",
                "maid_count": st["maid_count"],
                "confidence": geo_data.get("maid_count_confidence"),
                "method": st["method"],
            },
        }
    if not st["media_published"]:
        return {
            "stage": "campaign_to_media",
            "facts": {
                "stage": "campaign_to_media",
                "plan_name": (state.get("marketing_plan") or {}).get("campaign_name"),
                "objective": (state.get("user_info") or {}).get("campaign_objective"),
            },
        }
    return None


def _stage_fact_lines(state: AgentState) -> list[str]:
    """Compact pipeline facts for the chatbot system context.

    Replaces the old per-stage scripted paragraphs: the model gets the real
    numbers plus the product-policy rules and composes the reply itself.
    """
    st = derive_stage(state)
    if not st["geo_done"]:
        return []
    geo_data = state.get("geo_data") or {}

    def _mark(done: bool, stage_key: str) -> str:
        if done:
            return "COMPLETE"
        return "NEXT" if st["next_stage"] == stage_key else "pending"

    audience = _mark(st["maid_done"], "maid")
    if st["maid_count"] is not None:
        audience += f" ({st['maid_count']:,} visitor profiles)"
    lines = [
        "Pipeline status: "
        f"places=COMPLETE ({st['pois']} spots) | "
        f"audience={audience} | "
        f"campaign_plan={_mark(st['campaign_done'], 'campaign')} | "
        f"publish={_mark(st['media_published'], 'media')}",
        "Rules: never re-ask data a completed stage already collected (location, "
        "business, audience inputs); these numbers are reference facts — cite one "
        "ONLY when the user's turn actually needs it, never re-list numbers the "
        "ALREADY TOLD THE USER block shows you've already delivered; close by "
        "inviting the user toward the NEXT stage (not as a yes/no question).",
    ]

    locs = [
        loc.get("location_name")
        for loc in (geo_data.get("locations") or [])
        if loc.get("location_name")
    ]
    if locs:
        lines.append(f"Confirmed locations: {', '.join(locs)}")
    confidence = geo_data.get("maid_count_confidence")
    if st["maid_count"] and confidence:
        lines.append(f"Audience confidence: {confidence}")

    # Product policy — encoded in prose on purpose, do not drop:
    if st["maid_done"] and st["maid_count"] == 0:
        lines.append(
            "Zero-audience policy: the visit-data search found 0 visitor profiles — a "
            "data-coverage issue, NOT a location-targeting failure. Never suggest "
            "restarting location targeting; offer to proceed to campaign "
            "planning with area-based targeting instead (Meta serves ads "
            "to people in those areas)."
        )
    if st["campaign_done"] and not st["media_published"]:
        lines.append(
            "Publish preview: campaigns are created in Meta Ads Manager in "
            "PAUSED status so the user can review before going live."
        )
    if st["media_published"]:
        lines.append("Campaign published to Meta Ads successfully.")
    return lines


def _tagged_context_this_turn(state: AgentState, role: str) -> str:
    """Content of the most recent AIMessage tagged ``role``, scoped to THIS turn.

    A tagged context message (knowledge_context / campaign_manager_context /
    guardrail_reject) is injected by a single upstream node and checkpointed into
    state forever. Scanning the whole reversed history — the old approach — finds
    the same tag from a prior turn too, so a stale "off-topic" verdict or a stale
    knowledge blob silently re-injects on every later chatbot call in the session.
    Stop the scan at the last real HumanMessage: anything before that belongs to
    an earlier turn.
    """
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage) and is_conversational(msg):
            break
        if isinstance(msg, AIMessage) and msg.additional_kwargs.get("role") == role:
            return str(msg.content)
    return ""


# ── Node: chatbot ──────────────────────────────────────────────────────────────

async def chatbot_node(state: AgentState) -> dict[str, Any]:
    """
    Generate all user-visible conversational responses.

    This is the sole producer of messages the user actually reads. It
    receives full context from state — what data was just gathered, which
    fields are still missing, whether the campaign is ready — and crafts
    a warm, helpful reply using Gemini with thinking enabled.

    Always routes back to supervisor so the conversation can continue.
    """
    writer = get_stream_writer()
    writer({"type": "thinking", "content": "Chatbot: reviewing current session state..."})

    # LLM is constructed after the context scans below — the thinking level
    # depends on what kind of turn this is (see _chatbot_thinking_level).

    # ── Build context summary for the system prompt ────────────────────────────
    user_info = state.get("user_info") or {}
    geo_data = state.get("geo_data")
    marketing_plan = state.get("marketing_plan")

    collected_fields = {k: v for k, v in user_info.items() if v}

    context_lines: list[str] = []

    # The same plain-worded grounding view the narrator composes from, not a raw
    # dump of user_info: its internal keys (deterministic_subtype,
    # wizard_steps_done, ...) invited the model to repeat plumbing at the user.
    # `changes` is left to the narrator (read-only here) and `user_turn` gets its
    # own instruction below; the geo method labels are internal jargon.
    pack = build_pack(state, drain_changes=False)
    view = pack.as_prompt_dict()
    view.pop("changes", None)
    view.pop("user_turn", None)
    if view.get("geo"):
        view["geo"] = {
            k: v for k, v in view["geo"].items() if k not in ("method", "targeting_type")
        }
    if view:
        context_lines.append(
            "Session facts — the real values; cite only what this turn needs:\n"
            + json.dumps(view, default=str, ensure_ascii=False, indent=2)
        )
    else:
        context_lines.append("No business info collected yet.")

    if pack.user_turn:
        context_lines.append(
            "The user's latest turn, as read:\n"
            + json.dumps(pack.user_turn, default=str, ensure_ascii=False)
            + "\nIf `embedded_ask` is set, answer it first in plain words. Match `mood` "
            "(frustrated → brief and reassuring, no hype; confused → add one plain "
            "guiding sentence). `engagement` sets your DEFAULT length only — a genuine "
            "question still gets the fuller answer it asked for."
        )

    last_human_text = (_extract_last_human_text(state) or "").lower()

    # Skip-ahead: entry_node routed here because the user asked for a later
    # stage whose prerequisite wizards are incomplete (flow_blocked flag).
    if state.get("flow_blocked"):
        context_lines.append(
            "User asked to jump ahead, but prerequisites are incomplete. "
            "Flow: (1) Location Targeting → (2) Audience Building → "
            "(3) Campaign Planning → (4) Publishing to Meta. Briefly explain "
            "why the next required step comes first and invite them to start it."
        )

    context_lines.extend(_stage_fact_lines(state))

    # What the narrator already said this session (the composer's continuity ring).
    # Without this the chatbot re-recaps counts/facts the narrator just delivered at
    # the last pause, so consecutive messages read as two disjointed voices. Give
    # the chatbot the same "already delivered" ledger the composer uses.
    try:
        from app.graph.narrator import load_history as _load_history
        from app.graph.narrator import recent_history as _recent_history

        await _load_history(state)  # the narrator may have spoken on another instance
        _already = _recent_history(state, n=4)
    except Exception:
        _already = []
    if _already:
        context_lines.append(
            "ALREADY TOLD THE USER (Punk narrated these at earlier screens — do "
            "NOT restate their numbers/facts; acknowledge and build forward, as one "
            "continuous voice):\n" + "\n".join(f"  - {line}" for line in _already)
        )

    meta_ids = state.get("meta_campaign_ids") or {}
    if meta_ids.get("campaign_id"):
        id_lines = [f"Published Meta campaign ID: {meta_ids['campaign_id']}"]
        if meta_ids.get("adset_ids"):
            id_lines.append(f"Ad set IDs: {', '.join(meta_ids['adset_ids'])}")
        if meta_ids.get("ad_ids"):
            id_lines.append(f"Ad IDs: {', '.join(meta_ids['ad_ids'])}")
        context_lines.append(
            "Campaign published to Meta — cite these IDs when confirming success:\n"
            + "\n".join(id_lines)
        )

    if marketing_plan and "parse_error" in marketing_plan:
        context_lines.append("Campaign generation encountered an issue — let the user know gently.")

    # Check if the last message is a knowledge context block from knowledge_based_node
    # — scoped to THIS turn only, see _tagged_context_this_turn.
    knowledge_context: str = _tagged_context_this_turn(state, "knowledge_context")

    if knowledge_context:
        context_lines.append(
            f"\nKnowledge base content to use in your answer:\n{knowledge_context}"
        )

    # Check for campaign manager analysis from campaign_manager_node
    campaign_manager_context: str = _tagged_context_this_turn(state, "campaign_manager_context")

    if campaign_manager_context:
        context_lines.append(
            f"\nCampaign manager analysis (base your response on this data):\n{campaign_manager_context}"
        )

    # Check for guardrail rejection flag
    rejected_topic: str = _tagged_context_this_turn(state, "guardrail_reject")

    if rejected_topic:
        context_lines.append(
            f"\nOFF-TOPIC ALERT: The user asked about '{rejected_topic}', which is unrelated to "
            "Meta advertising. Politely decline and redirect them to Meta Ads topics."
        )

    failed_tools = state.get("current_turn_tool_errors") or []
    if failed_tools:
        failure_summary = "\n".join(f"- {e['tool']}: {e['error_msg']}" for e in failed_tools)
        context_lines.append(
            f"\nTool failures this turn (mention to user only if relevant to their question):\n{failure_summary}"
        )

    # Onboarding discovery owns the turn: a natural, conversational goal capture
    # before the targeting flow. It replaces the build-start clarify (the
    # follow_ups / missing_signals block is suppressed below when active).
    # Suppressed when a knowledge question just came back: a user asking "how
    # does this work?" gets answered, not forced into the two-path targeting
    # fork with "since you've asked me to suggest a strategy" — a strategy they
    # never asked for. See session 0fc30c89 in the plan for the failure this fixes.
    onboarding_active = bool(state.get("onboarding_active")) and not knowledge_context
    if onboarding_active:
        recap = (
            f"Known so far: {_format_known_fields(collected_fields)}\n"
            if collected_fields else ""
        )
        # Two distinct onboarding turns share this mode:
        #  • DELEGATED (targeting_choice="guided", e.g. "help me" / "you decide") →
        #    the RECOMMENDATION turn: name the concrete angle and proceed. Do NOT
        #    re-offer the two-path fork — the user already handed you the wheel.
        #  • otherwise → the FORK turn: present the two paths and let them choose.
        if user_info.get("targeting_choice") == "guided":
            context_lines.append(
                "\nGUIDANCE MODE — RECOMMENDATION TURN\n"
                f"{recap}"
                "The user asked YOU to pick the targeting angle (which real-world "
                "places/people to build the audience from). Do NOT re-offer a choice "
                "or ask which places — you own this call now.\n"
                "1. FIRST, if the user asked anything, answer it directly.\n"
                "2. State the CONCRETE angle you'll use, named and grounded in the "
                "AUDIENCE they named + their location (use their business only if they "
                "already told you what they sell — NEVER ask), plus one line on WHY it "
                "fits — say WHAT you're going to do. E.g. 'beach goers in Miami': 'I'll "
                "build the audience from people who visit the city's beaches, beach bars, "
                "boardwalks, and surf shops.' A supplement shop targeting injured MMA "
                "fighters: 'I'll build the audience from two kinds of spots — top MMA and "
                "combat-sport gyms, and sports-rehab / physio clinics — so we reach both "
                "active fighters and the ones treating pain.' A pet shop: 'I'll target "
                "people who visit other pet shops, dog parks, groomers, and vets nearby.' "
                "Name the actual place types, not a vague 'relevant spots'.\n"
                "   PUNK FINDS THE PLACES ITSELF. For a competitor angle Punk discovers "
                "the competitors from the business — so state it as something YOU'll do "
                "('I'll build the audience from people who visit nearby burger joints'), "
                "then hand off. NEVER ask the user to name, list, or give competitors, "
                "brands, or specific places (or their addresses) — that's Punk's job. The "
                "ONLY address ever needed is the user's OWN business, and then ONLY for a "
                "store-anchored angle; the targeting step collects it later — do NOT ask "
                "for it here. Close by inviting them to "
                "proceed, never by requesting a list.\n"
                "   MARKET-WIDE BY DEFAULT. Recommend an angle built on place types, "
                "chains, named venues or events — something Punk can search across the "
                "market they named. Only recommend a STORE-ANCHORED angle (places around "
                "the user's OWN business) when they have already shown they HAVE a "
                "physical location: they said 'my shop / my store / my locations' or gave "
                "an address. A national, B2B or online-only seller has no anchor to search "
                "around, so an angle phrased as 'near your location' would dead-end on an "
                "address they cannot give — for them the competitor angle is the "
                "MARKET-WIDE one (their competitors across the whole targeting area), "
                "which needs no address at all. Reaching people AT a place type (offices, "
                "hospitals, venues) across their market is market-wide and always fine.\n"
                "3. The recommendation is about the ANGLE (which places) — NEVER the "
                "location. Location (city/region) is the USER's to give; if it's missing, "
                "collect it naturally, never as something YOU decide.\n"
                "Do NOT ask what the business is / sells here unless it is listed as still "
                "unknown — recommend the angle straight from the audience + location you "
                "already have when you can. Do NOT ask about the campaign goal / objective "
                "here — that's collected later. Never ask 'what's the main goal?' or "
                "'visit in person or order online?'.\n"
                "Conversational, in your own voice. No fork, no checklist, no widgets, "
                "no rigid 5W list. Never claim a value the user didn't give. Keep it tight."
            )
        else:
            context_lines.append(
                "\nGUIDANCE MODE\n"
                f"{recap}"
                "The user has advertising intent but hasn't said HOW to target — which "
                "real-world places/people to build the audience from. Your job this turn: "
                "offer TWO clear paths, conversationally, not a script.\n"
                "1. FIRST, if the user asked anything (e.g. 'how should I do this?'), "
                "answer it directly.\n"
                "2. Open with ONE short line, grounded in the AUDIENCE they named (and "
                "their business only if they already told you what they sell — NEVER ask), "
                "on Punk's edge: we reach people by the real-world spots they already "
                "visit. E.g. 'beach goers in Miami': 'we can reach beach goers by the "
                "real-world spots they already show up at.'\n"
                "3. PRESENT THE TWO PATHS neutrally and clearly, both framed for the "
                "AUDIENCE they named — this fork is about the targeting ANGLE only:\n"
                "   - they tell YOU the KIND of angle they have in mind (e.g. 'competitor "
                "customers', 'people who visit gyms'), OR\n"
                "   - they ask YOU to recommend the best angle for their store.\n"
                "Make it an easy either/or; do not bury one path as an afterthought.\n"
                "Naming the ANGLE is all that's needed — the user never has to list "
                "specific competitors, brands, or places; Punk discovers those itself. "
                "NEVER ask them to provide competitor names or addresses.\n"
                "4. Give a concrete, grounded ANGLE recommendation ONLY if they ask for "
                "it or clearly delegate ('you decide', 'recommend something'). When you "
                "do, name the actual approach and WHY it fits — e.g. a venture studio "
                "targeting tech founders in SF: 'I'd reach people who recently visited "
                "startup hubs, coworking spaces, and VC/tech events around SF.' A pet "
                "shop: 'I'd target people who visit other pet shops, dog parks, and vets "
                "nearby.' The recommendation is about the ANGLE (which places) — NEVER "
                "the location or the goal.\n"
                "Location (the city/region to run ads) is the USER's to give — never "
                "offer to pick it. If it's missing, collect it naturally; never present "
                "it as something YOU decide. Do NOT ask what the business is / sells here "
                "unless it is listed as still unknown, and do NOT ask about the campaign "
                "goal / objective here — that's collected later; otherwise work from the "
                "audience + location you already have.\n"
                "Conversational, in your own voice. Do NOT pile on questions, no "
                "checklist, no widgets, no rigid 5W list. Never claim a value the user "
                "didn't give. Keep it tight."
            )

    clarify = state.get("clarify_reason")
    follow_ups = state.get("follow_ups") or []
    missing_signals = state.get("missing_signals") or []
    if (follow_ups or missing_signals) and not onboarding_active:
        known_recap = (
            f"Known so far: {_format_known_fields(collected_fields)}\n"
            if collected_fields else ""
        )
        angle_line = f"Unique angle worth echoing: {clarify}\n" if clarify else ""
        if follow_ups:
            # Extraction-aware path: the entry LLM proposed business-specific
            # questions. Render them as the agenda; the chatbot phrases them
            # conversationally — NOT as a rigid 5W bullet list.
            agenda = "\n".join(
                f"- {fu.get('ask', '')}"
                + (f"  (why: {fu['why']})" if fu.get("why") else "")
                for fu in follow_ups
            )
            context_lines.append(
                "\nCLARIFY REQUEST\n"
                f"{known_recap}"
                f"{angle_line}"
                "Ask these follow-ups in your own conversational voice — build on "
                "what you already know, vary the phrasing, weave in the 'why' "
                "naturally. Do NOT dump a generic checklist; make each question "
                "specific to their business. Never re-ask anything already known.\n"
                f"{agenda}"
            )
        else:
            # Fallback: only the coarse 5W taxonomy is available.
            context_lines.append(
                "\nCLARIFY REQUEST\n"
                f"Still unknown: {', '.join(missing_signals)} "
                "(who=audience, where=geo, what=what the business sells / its edge, "
                "how_tactic=which real-visit tactic). If 'what' is listed, DO ask it — "
                "it feeds the place mapper and nothing else in the flow ever collects "
                "it. Do NOT ask the campaign goal/objective — the builder collects "
                "that later.\n"
                f"{known_recap}"
                f"{angle_line}"
                "Ask for the missing pieces in your own words — one short message, "
                "at most 4 questions, scannable (bullets are fine). Never re-ask "
                "anything already known."
            )

    wizard_failure = state.get("wizard_failure")
    if wizard_failure:
        _failure_msgs = {
            "geo_targeting_unresolved": (
                "Geo targeting couldn't be resolved after multiple attempts. Explain warmly that "
                "we're handing this back; suggest the user clarify their targeting goal (locations, "
                "competitors, brand chains, or events) and offer to restart geo setup."
            ),
            "maid_audience_unresolved": (
                "Audience extraction couldn't settle on parameters after multiple revisions. "
                "Acknowledge the back-and-forth, summarise what we know, and offer to restart MAID "
                "with a clearer radius/lookback or to proceed with geo-fence based targeting."
            ),
            "campaign_brief_generation_failed": (
                "Campaign brief generation hit a hard error after retries. Apologise briefly, "
                "explain it was a transient model failure, and invite the user to retry campaign "
                "planning when they're ready."
            ),
            "campaign_meta_json_generation_failed": (
                "Meta campaign JSON generation failed after retries. The brief is intact; only the "
                "final publish-ready JSON couldn't be produced. Suggest retrying."
            ),
            "campaign_audience_export_failed": (
                "Exporting the Custom Audience into the user's ad account failed. A message "
                "already gave them the exact Meta error — do NOT repeat it, and do NOT restart "
                "geo or audience collection: the extracted audience is intact. Acknowledge "
                "briefly and offer to retry the export."
            ),
            # The three builder exits. All of them KEEP the build scratch, so the
            # one thing every message must do is tell the user their progress is
            # safe and that "continue" resumes it. Without entries here the raw
            # code was handed to the LLM to improvise on, which is how a user who
            # got confused was then told their campaign was gone.
            "user_exit": (
                "The user stepped out of the guided build — they went off-script several "
                "times or asked to stop. Nothing is lost: every answer, the discovered "
                "spots and the audience are all still saved. Do NOT restart anything and "
                "do NOT re-ask earlier questions. Answer whatever they actually wanted, "
                "then tell them they can say 'continue' to pick the build up exactly where "
                "it left off."
            ),
            "builder_iteration_budget": (
                "The build loop hit its safety limit for this turn. This is our ceiling, "
                "not the user's mistake — say so plainly, in one short line, with no jargon "
                "and no error code. Their progress is saved; invite them to say 'continue' "
                "to resume."
            ),
            "builder_planner_failed": (
                "The build planner could not choose a next step. Apologise briefly, treat it "
                "as a transient fault on our side, and note their progress is saved and "
                "'continue' resumes it. Do NOT re-ask anything already answered."
            ),
            "builder_act_failed": (
                "A build step hit an unexpected error on our side. This is our fault, not the "
                "user's input — their answers were fine. Do NOT invent a cause, do NOT suggest "
                "changing any value they already gave (radius, lookback, budget), and do NOT "
                "re-ask anything answered. Say plainly that something broke on our end, their "
                "progress is saved, and 'continue' retries from where it stopped."
            ),
        }
        if str(wizard_failure).startswith("campaign_publish_failed:"):
            _failure_msgs[str(wizard_failure)] = (
                "Meta publish failed after the user confirmed. A milestone message already "
                "explained the error — do NOT restart geo/audience collection or ask for "
                "locations. Acknowledge the publish issue briefly, offer to re-upload the "
                "creative or retry publishing, and stay focused on the media/publish step only."
            )
        if str(wizard_failure).startswith("maid_query_failed:"):
            _failure_msgs[str(wizard_failure)] = (
                "Audience extraction hit an unexpected error on our side right after the "
                "user answered the radius/lookback question. This is our fault, not the "
                "user's input — their radius and lookback values were fine. Do NOT invent "
                "a cause, do NOT ask them to change the radius or lookback, and do NOT "
                "re-ask anything already answered. Say plainly that building the audience "
                "hit a snag on our end, their answers are saved, and 'continue' retries "
                "the extraction."
            )
        context_lines.append(
            "\nWIZARD FAILURE: " + _failure_msgs.get(
                wizard_failure,
                f"Wizard exited with failure code '{wizard_failure}'. Acknowledge gracefully and offer the user a next step.",
            )
        )
        hint = _extract_last_meaningful_step(state.get("thinking") or [], wizard_failure)
        if hint:
            context_lines.append(
                f"\nLast meaningful step before failure: {hint}\n"
                "Use this only to say WHERE the build stopped, so the user can resume "
                "from that point. Do NOT suggest changing the values involved unless "
                "the failure message itself says a value was the problem."
            )

    # ── Narrator v2 handoff short-circuit ─────────────────────────────────────
    # When a wizard stage cleanly completed AND the user simply said "proceed"
    # (no question, no new detail), emit the structured four-beat handoff and
    # skip the full chatbot LLM. Any special context (clarify / failure /
    # knowledge / campaign-manager / guardrail / tool errors) disqualifies the
    # short-circuit so those bespoke paths are never hijacked.
    if (
        not missing_signals
        and not follow_ups
        and not onboarding_active
        and not wizard_failure
        and not knowledge_context
        and not campaign_manager_context
        and not rejected_topic
        and not failed_tools
        and _looks_like_proceed(last_human_text)
    ):
        _handoff = _detect_handoff(state)
        if _handoff:
            try:
                from app.graph.narrator import add_beat as _add_beat
                from app.graph.narrator import compose_message as _compose_message

                # Record the handoff as a beat, then compose it — streamed live
                # via `writer` (so the handoff isn't a blocking blob) AND returned
                # so the text can be appended to `messages` as an AIMessage.
                _add_beat(state, "handoff", _handoff["facts"], fallback="")
                _text = await _compose_message(state, writer)
                if _text:
                    writer({"type": "input_mode", "mode": "chat"})
                    writer({"type": "thinking", "content": f"Chatbot: structured handoff ({_handoff['stage']}) emitted"})
                    return {
                        "messages": [AIMessage(content=_text)],
                        "next_nodes": ["entry"],
                        "thinking": [],
                        "current_turn_tool_errors": None,
                        "auto_filled_log": [],
                        "wizard_failure": None,
                        "clarify_reason": None,
                        "missing_signals": None,
                        "follow_ups": None,
                        "onboarding_active": None,
                        "flow_blocked": None,
                    }
            except Exception as exc:
                logger.warning("narrator v2 handoff short-circuit failed: %s", exc)
                # fall through to full chatbot LLM

    context_block = "\n".join(context_lines)
    writer({"type": "thinking", "content": f"Chatbot context:\n{context_block}"})

    # Injected single-node context never reads as dialogue. Ledger records DO —
    # they are the build conversation, and without them this node has no idea what
    # the user said between the first interrupt and now.
    clean_messages = [msg for msg in state["messages"] if not is_internal(msg)]
    # Bound it: nothing else caps this list, and a long build adds ~40 records that
    # would otherwise ride every call for the rest of the session. Keep the head so
    # the user's original ask survives the window.
    if len(clean_messages) > MAX_LLM_HISTORY:
        tail = clean_messages[-MAX_LLM_HISTORY:]
        # Reserve room for real dialogue. A 20-step build produces ~40 ledger
        # records (state.py), which is the whole window — so on a long build the
        # tail could be 100% widget Q/A and the user's actual words got evicted,
        # leaving this node to answer a follow-up it could no longer see. Ledger
        # records still belong here (they ARE the build conversation); they just
        # must not crowd everything else out.
        recent_talk = [m for m in clean_messages[:-MAX_LLM_HISTORY] if is_conversational(m)]
        if recent_talk and sum(1 for m in tail if is_conversational(m)) < _MIN_CONVERSATIONAL_TAIL:
            tail = recent_talk[-_MIN_CONVERSATIONAL_TAIL:] + tail
        clean_messages = clean_messages[:2] + tail

    chat_messages = [
        SystemMessage(
            content=(
                f"{CHATBOT_SYSTEM_PROMPT}\n\n--- Punk Product Facts ---\n{load_punk_kb()}"
                f"\n\n--- Session Context ---\n{context_block}"
            )
        ),
        *clean_messages,
    ]

    # CHATBOT_TEMP (see config.py): the chatbot quotes real counts, names and
    # dollar amounts, so it is tuned separately from the 0.7 brain default.
    llm = _make_thinking_llm(
        thinking_level=_chatbot_thinking_level(wizard_failure),
        temperature=settings.CHATBOT_TEMP,
    )

    try:
        raw, _usage_cb = await tracked_astream(
            llm,
            chat_messages,
            node_name="chatbot",
            writer=writer,
            emit_assistant=True,
            emit_thinking=True,
            thinking_source="punk",
        )
        thinking_text, answer_text = _split_gemini_thinking(raw.content)
    except Exception as exc:
        logger.error("chatbot_node LLM call failed: %s", exc)
        answer_text = "I'm having trouble responding right now — please try again in a moment."
        thinking_text = ""
        _usage_cb = {"cost_usd": 0.0}
        writer({"type": "assistant_message", "content": answer_text})

    writer({"type": "input_mode", "mode": "chat"})
    if not answer_text:
        writer({"type": "assistant_message", "content": ""})
    writer({"type": "thinking", "content": "Chatbot: response generated"})

    return {
        # The stream above already showed the raw text — the prompt's plain-words
        # rule is the front-line defence there. The PERSISTED copy is what later
        # turns and the DB read back, so it gets the same deterministic scrub the
        # narrator's composer applies.
        "messages": [AIMessage(content=scrub_jargon(answer_text))],
        "next_nodes": ["entry"],
        "thinking": [thinking_text] if thinking_text else [],
        "current_turn_tool_errors": None,
        "auto_filled_log": [],
        "wizard_failure": None,
        "clarify_reason": None,
        "missing_signals": None,
        "follow_ups": None,
        "onboarding_active": None,
        "flow_blocked": None,
    }


