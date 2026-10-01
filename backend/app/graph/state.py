"""
graph/state.py
──────────────
Central state definitions for the PunkAI LangGraph campaign-builder agent.

All nodes read from and write to AgentState. The graph uses Postgres checkpointing
so every key in this TypedDict is persisted between turns.

The Three-Layer Data Pattern (read this before declaring a field "redundant")
────────────────────────────────────────────────────────────────────────────
The same conceptual datum (e.g. ``targeting_method``, ``poi_types``,
``lookback_days``, ``search_radius_km``) can legitimately appear in up to
three places at once. This is intentional — each layer serves a different
consumer and a different lifecycle stage:

  1. **Prefill** — ``user_info[...]`` (UserInfo)
     Written by ``entry_node`` from the user's natural-language
     prompt before any wizard runs. Drives the ``prefill`` / ``prefill_source``
     / ``prefill_confidence`` fields of PendingAction so the frontend can
     pre-populate inputs. Also feeds the auto-fill skip path
     (``maybe_log_auto_fill`` short-circuits wizard steps with confidence ≥0.95).

  2. **Scratch** — ``geo_wizard_state``, ``maid_wizard_state``,
     ``campaign_wizard_state``, ``media_wizard_state``
     Wizard-private working memory during the interrupt chain. Owned by one
     wizard at a time. **No reducer** — wizards build a fresh dict via
     ``dict(state.get("…") or {})``, mutate, and write back whole, so they
     can drop keys mid-flow. Cleared on the wizard's execute sub-node.

  3. **Final** — ``geo_data``, ``marketing_plan``, ``campaign_brief``,
     ``meta_campaign_ids``
     Authoritative outputs consumed by downstream wizards and the publish step.
     ``geo_data`` and ``user_info`` use the shallow-merge reducer
     (``_dict_merge_or_clear``) because more than one writer touches them
     (geo writes geo fields, maid writes MAID fields).

Why parity across layers is a feature, not duplication:
  • ``field_owner_registry`` keys both the step-level field names (e.g.
    ``geo_locations``) AND the UserInfo natural names (e.g. ``location``) so
    the resume-router's edit-lane classifier can match either surface
    without a synonym layer.
  • Re-extracting intent on resume (``resume_preflight``) repaints prefill
    without stomping the active wizard's scratch, because they live in
    different keys.
  • Hard-locking a completed wizard (``wizards_completed``) refuses edits to
    Final-layer values, while Prefill stays writable for the next wizard.

If you find yourself wanting to "collapse" parity:
  • Don't add a merge reducer to wizard scratch — would prevent key-drops.
  • Don't unify UserInfo prefill with GeoData final — would break auto-fill
    confidence comparison and the resume-router hard-lock.
  • Same-name keys at different layers are correct. Different-unit pairs
    (e.g. ``poi_radius_m`` in UserInfo vs ``poi_radius_km`` in GeoData) are
    intentional — frontend collects metres, Meta targeting wants km.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import NotRequired, TypedDict


# ── Message roles ─────────────────────────────────────────────────────────────
# Every message in AgentState.messages is one of three kinds, distinguished by
# additional_kwargs["role"]. This module is the single home for the vocabulary —
# it imports nothing from app.*, so nodes, the campaign manager and the narrator
# can all depend on it without a cycle.
#
#   (untagged)     — a real conversational turn: the user typed it, or Punk
#                    answered it. Every LLM sees these.
#   INTERNAL_ROLES — context injected for ONE node to read and act on. Never
#                    shown to another LLM as if it were dialogue.
#   LEDGER_ROLES   — the builder's transcript ledger: the step question Punk
#                    asked and the answer the user gave at each interrupt.
#                    Without these the whole build is invisible to the
#                    transcript, because the builder speaks over the stream.
#
# The predicates are role-based, NOT isinstance-based. A ledger answer is a real
# HumanMessage, and an isinstance(msg, AIMessage) test cannot exclude it.

INTERNAL_ROLES = frozenset({
    "knowledge_context",
    "guardrail_reject",
    "campaign_manager_context",
})

LEDGER_ROLES = frozenset({"wizard_step", "wizard_answer"})

# Tail kept by the LLM readers that would otherwise send the whole list every
# call. A 20-step build adds ~40 ledger records on top of the real turns.
# ponytail: fixed message window; swap for trim_messages(token_counter=...) if
# prompts get tight.
MAX_LLM_HISTORY = 40


def message_role(msg: Any) -> Optional[str]:
    """The role tag on a message, or None for a plain conversational turn."""
    return (getattr(msg, "additional_kwargs", None) or {}).get("role")


def is_internal(msg: Any) -> bool:
    """Injected single-node context — hidden from every other LLM."""
    return message_role(msg) in INTERNAL_ROLES


def is_conversational(msg: Any) -> bool:
    """A genuine user/assistant turn: not injected context, not a ledger record."""
    role = message_role(msg)
    return role not in INTERNAL_ROLES and role not in LEDGER_ROLES


def _shallow_dict_merge(
    a: Optional[dict[str, str]],
    b: Optional[dict[str, str]],
) -> dict[str, str]:
    """Reducer for AgentState.wizard_milestone_cache — shallow dict merge.

    b wins on key collision. Named (not a lambda) so the function is
    pickleable / referenceable by name; some checkpoint serialisers reject
    raw lambdas on hot reload.
    """
    return {**(a or {}), **(b or {})}


def _bounded_history_append(
    a: Optional[list[str]],
    b: Optional[list[str]],
) -> list[str]:
    """Reducer for AgentState.narrator_history — append + keep the last N lines.

    Holds the "already told the user" continuity ledger (the composed narration
    lines) so a cross-worker replay can repopulate GroundingPack.history even
    when the process-local ring is cold. Bounded so long sessions don't bloat
    the checkpoint. Named (not a lambda) so the checkpoint serialiser accepts it.
    """
    merged = list(a or []) + list(b or [])
    return merged[-12:]


def _set_union(a: Optional[set], b: Optional[set]) -> set:
    """Reducer for AgentState.wizards_completed — idempotent set union.

    Safe under parallel LangGraph Send dispatch; same write applied twice
    produces the same result.
    """
    return (a or set()) | (b or set())


def _counter_add(a: Optional[dict], b: Optional[dict]) -> dict:
    """Additive dict reducer for AgentState.google_api_calls — sums per key.

    Unlike _shallow_dict_merge (overwrites on collision), a repeated key here
    means more billed requests of that kind, so counts must accumulate.

    Despite the field's name the keys are VENDOR-wide, not Google-only: Places /
    Geocoding / grounding, plus `unacast_calls` / `unacast_requests`. The name is
    kept because this is a live AsyncPostgresSaver channel and renaming it would
    orphan the key in every existing checkpoint for no functional gain. For
    Unacast the authoritative record is the `unacast_call_log` table, not this
    field — see unacast_query.reconcile_call.
    """
    if not b:
        return a or {}
    out = dict(a or {})
    for k, v in b.items():
        out[k] = out.get(k, 0) + int(v or 0)
    return out


def _dict_merge_or_clear(a: Optional[dict], b: Optional[dict]) -> Optional[dict]:
    """Shallow-merge reducer with explicit-clear semantics.

    Used by ``user_info`` and ``geo_data`` so partial writes from one node
    do not stomp keys set by another node. Per-turn re-init from chat.py
    no longer needs to repaint every key on each turn — absent keys are
    preserved by the merge.

    Semantics:
      • b is None        → clear (return None). Lets nodes / chat.py fully
                           reset the field by explicitly writing None.
      • a is None        → take b as the new value (fresh init).
      • both dicts       → shallow merge, b wins on key collision.
      • either non-dict  → take b (forward-compat fallback).

    NOTE: shallow merge cannot delete keys. Nodes that need to remove a
    key from the merged dict must overwrite the whole field (write a fresh
    dict containing only the keys they want to keep). Wizard scratch dicts
    intentionally use overwrite — no reducer is attached to them.
    """
    if b is None:
        return None
    if not isinstance(b, dict):
        return b
    if a is None or not isinstance(a, dict):
        return dict(b)
    return {**a, **b}


# ── Geo-specific types ────────────────────────────────────────────────────────


class GeoLocation(TypedDict, total=False):
    """A single geocoded location."""

    location_name: str
    formatted_address: str
    latitude: float
    longitude: float
    is_city: bool


class POICoordinate(TypedDict, total=False):
    """A single targetable POI with coordinates."""

    name: str
    lat: float
    lng: float
    radius_km: float
    parent_location: str
    types: list[str]
    brand: str
    event_start_date: str   # ISO date e.g. "2026-07-25"; "TBD" when unknown
    event_end_date: str     # ISO date; same as start for single-day events
    # Extracted from the POI's Google address components at discovery. Meta geo
    # targeting keys are built from these (resolve_poi_zips → "<ISO2>:<postal>").
    postal_code: str
    country_code: str
    # Google rating (1.0-5.0) / review count — only on Places-derived POIs.
    # None/0 on event_based, named_places (web-fallback), store_set and
    # map_pick POIs, which never touch the Places API. poi_selection's
    # Bayesian scorer treats an absent rating as "pool average", not "worst" —
    # see that module for why. Not enforced (total=False); the fields below
    # are already behind reality on some angles (source_angle, parent_poi_type,
    # parent_label, formatted_address, named_place all appear on real POIs but
    # aren't declared here either).
    rating: float
    user_ratings_total: int


class GeoData(TypedDict, total=False):
    """
    Complete geo targeting output stored in AgentState.geo_data.

    Populated by geo_agent_node. Contains deterministic POI/geofence targeting
    data (targeting is always deterministic).
    """

    targeting_method: str               # always "deterministic"
    targeting_type: str                 # e.g. "granular_local", "ai_suggested", "brand"
    locations: list[GeoLocation]        # geocoded user locations

    # ── Programmatic fields ───────────────────────────────────────────────
    meta_targeting: dict                # Meta Graph API targeting spec

    # ── Deterministic fields ──────────────────────────────────────────────
    poi_types: list[str]                # POI types used for search
    targetable_pois: list[POICoordinate]  # every discovered POI (no count cap)
    pois_found: int                      # total POIs collected (always set)
    search_radius_km: float             # broader search radius
    poi_radius_km: float                # per-POI targeting radius (default 1.0)
    lookback_days: int                  # MAID lookback window (default 7)
    completed_searches: list[str]       # tracks location+poi_type combos searched

    # ── MAID extraction results ───────────────────────────────────────────
    maid_extraction_id: str             # UUID ref into maid_extractions Postgres table
    maid_count: int                     # unique device count — quick access for prompts
    maid_visit_stats: dict              # sighting-frequency summary (buckets, repeat-visitor totals)
    maid_query_skipped: bool            # True when warehouse not configured / query failed
    maid_count_confidence: int          # confidence score 85-97
    min_budget_usd: int                 # recommended minimum Meta campaign budget

    # ── Audience layering (see maid_store.AudienceFilter) ─────────────────
    audience_filter: dict               # active narrowing spec, or None = full extracted audience
    filtered_maid_count: int            # maid_count AFTER audience_filter — the true headline/publish count


# ── Shared types ──────────────────────────────────────────────────────────────


class UserInfo(TypedDict, total=False):
    """
    Structured business and campaign information collected from the user.

    All fields are optional (total=False) so partial extraction is valid
    at any point in the conversation.
    """

    business_name: Optional[str]
    business_description: Optional[str]
    industry: Optional[str]
    target_audience: Optional[str]
    budget: Optional[str]
    location: Optional[list]             # list of geocodable place names e.g. ["Montreal", "Toronto"]
    campaign_objective: Optional[str]
    website_url: Optional[str]
    budget_type: Optional[str]          # "daily" | "lifetime"
    campaign_start_date: Optional[str]  # ISO date e.g. "2026-05-01"
    campaign_end_date: Optional[str]    # ISO date; empty string = ongoing
    pixel_status: Optional[str]         # "verified" | "unverified" | "not_installed"
    pixel_id: Optional[str]             # numeric Meta Pixel ID (auto-extracted from site or pasted by user)
    wizard_steps_done: Optional[list]   # durable completion markers across subgraph re-entries
    product_offer: Optional[str]        # optional; empty string = user skipped
    meta_access_token: Optional[str]    # user's Meta Ads access token (from OAuth)
    meta_ad_account_id: Optional[str]   # "act_XXXXXXXXX"
    meta_page_id: Optional[str]         # Facebook Page ID for ad creatives

    # ── Geo targeting prefill (from intent extraction → geo wizard) ───────
    targeting_choice: Optional[str]     # "guided" | "self_directed" — inferred lean when user is unsure vs. knows their target
    geo_scope: Optional[str]            # "country_groups" | "admin_areas" | "granular_local" | "radius"
    deterministic_subtype: Optional[str]  # "ai_suggested" | "category" | "store_set" | "competitor_nearby" | "competitor_area" | "competitor_brand" | "event_based" | "named_places"; may be a comma-joined SET of composable angles (e.g. "event_based,named_places")
    geo_angle_specs: Optional[list]     # per-angle overrides [{angle, locations, poi_types, anchor_types, ...}] when angles diverge in where/what; null → all angles share the flat location/types
    competitor_brands: Optional[list]   # brand names user wants to target e.g. ["Starbucks", "Tim Hortons"]
    named_places: Optional[list]        # specific venue names to target by name e.g. ["Fight Club", "McGrill Bar", "Tomahawk"]
    poi_types: Optional[list]           # CITY/MARKET-WIDE place types to target e.g. ["coffee shop", "gym"] (category angle)
    anchor_types: Optional[list]        # NEAR-MY-BUSINESS place types e.g. ["bar", "gym"] (competitor_nearby anchor) — kept separate from poi_types so a category+competitor_nearby combo doesn't mix the two
    event_queries: Optional[list]       # event names/types to target e.g. ["Coachella", "NBA games"]
    event_date_range: Optional[str]     # event date range if mentioned e.g. "June 2026" or "2026-06-01 to 2026-06-30"

    # ── Audience demographic prefill ──────────────────────────────────────
    target_age_min: Optional[int]       # e.g. 25
    target_age_max: Optional[int]       # e.g. 45
    target_gender: Optional[str]        # "all" | "male" | "female"

    # ── MAID wizard prefill ───────────────────────────────────────────────
    poi_radius_m: Optional[int]         # geofence radius in metres e.g. 100, 500
    lookback_days: Optional[int]        # how many days back to query device visits e.g. 7, 30
    audience_filter: Optional[dict]     # layering predicates on the extracted audience — see maid_store.AudienceFilter / nodes.AudienceFilterSpec
    blocked_attributes: Optional[list]  # Meta-banned targeting classes the user named (race, sexual_orientation, ...) — never applied, only narrated

    # ── Deterministic-specific geo prefill ────────────────────────────────
    store_addresses: Optional[list]     # user's own store addresses for store_set subtype
    competitor_address: Optional[str]   # anchor address for competitor_nearby subtype
    search_radius_km: Optional[int]     # POI/competitor search radius in km


class PendingAction(TypedDict):
    """
    Describes the active interrupt waiting for user input.

    Stored in AgentState *before* calling interrupt() so that reconnecting
    clients can read the current interrupt context from the Postgres checkpoint
    without needing the live event stream.
    """

    action_type: str
    """
    One of:
      "text_input"        – free-text field (city names, POI types, addresses, brand names, numbers)
      "option_selection"  – pick from list (buttons/radio)
      "permission"        – yes/no confirmation shown after a map event (confirm/dismiss prompt)
      "map_interaction"   – lat/lng selection from interactive map widget
      "file_upload"       – media file picker; frontend uploads to /media/upload and resumes
                            with the returned file path (or "skip" to skip the ad set)
      "oauth_connect"     – single-button OAuth flow; options[0] is the authorization URL;
                            frontend opens it in a popup/redirect and resumes with "connected"
      "stepper_input"     – numeric stepper with − / + buttons and Confirm/No; config in `stepper`
    """

    options: list[str]
    """Non-empty for option_selection; empty list for other action types."""

    prompt: str
    """Human-readable question displayed in the UI button/input widget."""

    field: str
    """Which state key this interrupt is collecting (e.g. 'geo_targeting_method')."""

    step_key: str
    """The wizard_interrupt step_key that created this interrupt.
    Used on resume to detect node replay — suppresses duplicate pre-interrupt emissions."""

    prefill: Optional[str]
    """Pre-extracted value from intent_extraction. Frontend pre-populates the input;
    user confirms or overrides. None when no prior value exists."""

    prefill_source: Optional[str]
    """Origin of the prefill value.
    One of: 'intent_extraction' | 'website_enrichment' | 'geo_wizard' | 'user_provided'
    None when prefill is None."""

    prefill_confidence: Optional[float]
    """0.0–1.0 confidence in the prefilled value.
    1.0 = definitive (user explicitly stated it), lower = inferred.
    None when prefill is None."""

    stepper: Optional[dict]
    """Only set when action_type == "stepper_input" and a single stepper is shown.
    Shape: {"default": <number>, "min": <number>, "max": <number>, "step": <number>, "unit": <str>}
    Frontend resumes with the chosen value as a plain string (e.g. "500" for 500 m)."""

    steppers: Optional[list]
    """Multiple stepper configs when action_type == "stepper_input" and more than one stepper is needed.
    Each entry: {"key": str, "label": str, "default": num, "min": num, "max": num, "step": num, "unit": str}.
    Frontend renders N individual stepper controls in one widget.
    Resume returns JSON keyed by each "key", e.g. {"poi_radius_m": 500, "lookback_days": 7}.
    When absent, the single `stepper` field is used (backwards-compatible)."""

    progress: Optional[list]
    """Ordered list of confirmed wizard steps rendered as a summary card above the input widget.
    Each item: {"label": str, "value": str}. None when no steps confirmed yet."""

    title: NotRequired[Optional[str]]
    """Dynamic header title for the widget."""

    subtitle: NotRequired[Optional[str]]
    """Dynamic header subtitle for the widget."""

    # ── Resume Router v1 additions (all optional, frontend-additive) ──────────
    suggestions: NotRequired[Optional[list[str]]]
    """0–4 LLM-generated tappable chip strings displayed above the input widget.
    Tapping a chip submits its text as the resume value. Empty list / None = no chips."""

    escape_menu: NotRequired[Optional[list[str]]]
    """Action buttons (e.g. ["skip", "use default", "explain", "exit wizard"]) shown
    next to Confirm after a user has gone off-path 2+ times on the same step."""

    locked_message: NotRequired[Optional[str]]
    """Banner copy rendered above the widget when this pending_action is a locked-wizard
    summary re-emit. Frontend pairs it with a 'Start New Chat' CTA."""

    readonly: NotRequired[Optional[bool]]
    """True when the widget is rendered as a read-only summary (used by locked refusal
    re-emits). All interactive controls are disabled."""

    locations: NotRequired[Optional[list[dict]]]
    """Geocoded locations to draw on a map ABOVE this widget (pins for plan review /
    location confirmation). Each item: {"location_name"/"formatted_address", "latitude",
    "longitude", "is_city"?}. When present, the frontend renders the map inline with the
    widget's options — there is NO separate `confirm_locations` map_data event for these
    flows. The user's response still comes from this pending_action (options/confirm),
    not the map. Checkpointed, so it survives reconnect. None/absent = no map."""


class AgentState(TypedDict):
    """
    Central state shared across every node in the PunkAI agent graph.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    user_id: Optional[str]          # authenticated user UUID (from JWT, set at session start)
    user_info: Annotated[UserInfo, _dict_merge_or_clear]
    marketing_plan: Optional[dict]
    campaign_brief: Optional[dict]
    meta_campaign_ids: Optional[dict]   # IDs returned after publishing to Meta
    geo_data: Annotated[Optional[GeoData], _dict_merge_or_clear]
    next_nodes: list[str]
    """Routing destination(s) for the next conditional edge. Single source
    of truth — formerly paired with a scalar ``next_node`` field; collapsed
    so every router reads the same key.

    Single-destination routes use a 1-element list; multi-destination routes
    (parallel Send dispatch, see ``_supervisor_route``) use N elements."""
    pending_action: Optional[PendingAction]
    thinking: Annotated[list[str], operator.add]
    token_cost_usd: Annotated[float, operator.add]        # running USD total across turns
    total_tokens: Annotated[int, operator.add]            # running total tokens across turns (input+output+thinking)
    google_api_calls: Annotated[dict[str, int], _counter_add]  # running VENDOR request counts across turns, by API name (Google + Unacast; name kept for checkpoint compatibility — see _counter_add)
    pending_usage: Optional[dict]  # unbilled carry {"tokens", "cost_usd", "api_calls"} while interrupted; no reducer, cleared by writing None
    tool_calls_log: Annotated[list[dict], operator.add]   # every tool invocation across session
    current_turn_tool_errors: Optional[list[dict]]        # errors from the current geo_execute turn only; reset by chatbot_node

    # ── Ephemeral wizard scratch state ────────────────────────────────────────
    # Each wizard subgraph owns one of these fields and stashes per-sub-node
    # inputs / intermediate results there until it hands off to the next wizard.
    # Clearing happens when the wizard's execute sub-node runs.
    geo_wizard_state: Optional[dict]
    maid_wizard_state: Optional[dict]
    campaign_wizard_state: Optional[dict]
    media_wizard_state: Optional[dict]

    # ── Campaign manager (post-publish) ───────────────────────────────────────
    active_campaign_id: Optional[str]       # Meta campaign ID currently in focus
    just_published: Optional[bool]          # True for one turn after Meta publish; per-turn, reset by the chat service
    campaign_manager_state: Optional[dict]  # scratch: awaiting_write_tool, etc.

    # ── Campaign-builder agent scratch (PR5; no reducer — whole-dict writes) ──
    # Holds the planner loop state: iteration counter, filled slot values,
    # pending next_action, capped action_log, and the geo executor scratch.
    # Cleared (set to None) by builder_finalize.
    campaign_builder_state: Optional[dict]

    # ── Wizard hard-exit signal ───────────────────────────────────────────────
    # Set by a wizard on unrecoverable exit (rejection escalation, missing
    # prerequisites, brief generation failure). Consumed by chatbot_node which
    # explains the failure and clears the flag. Empty string sentinel acts as
    # "cleared"; None means never set.
    wizard_failure: Optional[str]

    # ── Auto-fill log (drained by chatbot_node each turn) ─────────────────────
    # Populated by wizard sub-nodes when a step auto-advances on high-confidence
    # prefill (≥0.95). chatbot_node lists these in its next user-facing summary
    # then returns [] to clear. No reducer — last write wins.
    auto_filled_log: Optional[list[dict]]

    # ── Clarify reason (set by entry_node, consumed by chatbot) ───────────────
    # Free-text reason set by entry_node when it routes to chatbot because user
    # context is too thin to start a wizard. OPTIONAL supplementary context —
    # names any unique angle the user raised that the clarify reply should
    # acknowledge. The authoritative which-signals-are-missing list lives in
    # ``missing_signals`` below. Reset to None by chatbot_node.
    clarify_reason: Optional[str]

    # ── Missing 5W signals (set by entry_node, consumed by chatbot) ───────────
    # Structured list of signal names still unknown for the geo gate.
    # Allowed values: "what" | "who" | "why" | "where" | "how_tactic".
    # The chatbot LLM writes the clarify questions in its own words from this
    # list (plus telemetry value). Reset to None by chatbot_node after use.
    missing_signals: Optional[list[str]]

    # ── Tailored follow-up questions (set by entry_node, consumed by chatbot) ──
    # 1-3 business-specific clarify questions the entry LLM proposes from what it
    # just extracted — richer than the coarse ``missing_signals`` 5W taxonomy.
    # Each item: {"ask": <what to learn>, "why": <one-line reason>}. The chatbot
    # phrases them conversationally. Set only on chatbot clarify routes; reset to
    # None by chatbot_node after use. Same no-reducer / explicit-clear lifecycle
    # as ``missing_signals``.
    follow_ups: Optional[list[dict]]

    # ── Onboarding discovery mode (set by entry_node, consumed by chatbot) ────
    # True when entry routed into the conversational intent-capture discovery
    # phase (a normal chat turn, NOT a widget/interrupt). Drives the chatbot's
    # DISCOVERY MODE and suppresses the clarify follow-ups for that turn. Reset
    # to None by chatbot_node. Durable completion lives in
    # ``user_info["wizard_steps_done"]`` ("onboarding_started" / "onboarding").
    onboarding_active: Optional[bool]

    # ── Flow-blocked flag (set by entry_node, consumed by chatbot) ────────────
    # True when the user asked for a later pipeline stage (campaign planning,
    # publishing) whose prerequisite wizards are incomplete and entry_node
    # routed to chatbot instead. The chatbot explains the flow order and
    # invites the user to start the next required step. Reset by chatbot_node.
    flow_blocked: Optional[bool]

    # ── User-turn signal (set per turn, read by the narrator composer) ────────
    # A small read of the human's latest turn so the composer can RESPOND to the
    # user (mirror their words, answer an embedded question) and adapt tone +
    # length — not just narrate Punk's own state. Written two ways:
    #   • entry_node (new-message turns): mood + phrase digest from the Pro call.
    #   • builder_ask (resume/build turns): heuristic from the raw answer (no LLM).
    # Shape: {"phrase": str|None, "embedded_ask": str|None,
    #         "mood": "neutral"|"frustrated"|"confused"|"eager",
    #         "engagement": "terse"|"normal"|"engaged"}. Per-turn, NO reducer —
    # fresh each turn, cleared by omission (same lifecycle as ``missing_signals``).
    user_turn: Optional[dict]

    # ── Wizard milestone narrator cache ───────────────────────────────────────
    # Maps "milestone_key:facts_hash" → emitted text. Populated by
    # wizard_milestone_narrate(). Cache hit on replay = deterministic UX, $0.
    # Reducer merges dicts so parallel Send branches don't race-overwrite.
    wizard_milestone_cache: Annotated[dict[str, str], _shallow_dict_merge]

    # ── Narrator continuity ledger ────────────────────────────────────────────
    # The composed user-facing narration lines already emitted this session
    # (bounded to the last ~12). Feeds GroundingPack.history so the composer
    # builds forward instead of re-showcasing the whole campaign every screen.
    # Primary source is the process-local ring in narrator.beats; this state
    # field is the cross-worker durability backstop (callers splat the
    # {"narrator_history": [...]} fragment flush_narration returns).
    narrator_history: Annotated[list[str], _bounded_history_append]

    # ── Resume Router v1: completed wizards (hard-lock source of truth) ───────
    # Each wizard's finalize node writes its name (e.g. {"geo"}) into this set
    # via the set-union reducer. resume_router.is_completed_owner() reads it to
    # decide whether to refuse edits to fields owned by an already-completed
    # wizard. Set-union reducer is idempotent + commutative — safe under Send.
    wizards_completed: Annotated[set[str], _set_union]
