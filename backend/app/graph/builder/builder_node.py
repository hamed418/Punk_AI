"""
graph/builder/builder_node.py
─────────────────────────────
Campaign-builder agent subgraph — the sole campaign build+publish path.

Hybrid two-tier design: thinking, asking, and acting are separate sub-nodes so
no node both loops an LLM *and* interrupts — collection interrupts live ONLY
in ``builder_ask``, keeping resume-replay cost flat (one tiny node), while the
planner is free to skip, reorder, and batch collection the wizards hard-wire.

    builder_plan     – ONE Flash temp-0 structured call → next action
                       (ask | act | done | fail). Never interrupts. Hard
                       stage/sequence invariants enforced HERE in code.
    builder_ask      – ONE wizard_interrupt() per visit (full resume-router /
                       narrator / chips / pending_action contract reused
                       unchanged). Writes the answer into the slot scratch
                       and mirrors it into user_info via the slot's
                       prefill_key so the LLM cores see fresh values.
    builder_act      – ONE expensive operation per visit:
                         geo_discover       – POI discovery / targeting spec
                         maid_query         – warehouse audience extraction
                         generate_brief     – Pro+thinking campaign brief
                         generate_meta_json – Pro+thinking Meta campaign JSON
                                              (per-ad creatives are collected in
                                              the campaign editor at plan_confirm)
                         resolve_meta       – Meta OAuth, ad account, pixel
                                              (interrupts BEFORE publish confirm)
                         publish            – Meta API create + activate only
                                              (runs straight off the editor's
                                              Publish; objects land PAUSED and
                                              go_live_confirm gates activation)
    builder_finalize – merges results into AgentState, sets
                       wizards_completed, routes to campaign_manager on publish.

Sequencing model: each stage runs [pre-act slots] → [acts in order, with
confirmation gates between (plan_confirm) or after (poi_confirm,
maid_confirm)] → next stage. ``_next_step`` is the single deterministic source of that order; the
planner LLM proposes, ``coerce_action`` disposes.

Why brief/meta-JSON are separate acts: an interrupt inside the same node
invocation as an expensive LLM call would re-run that call on every resume
replay. Splitting them puts a checkpoint between the Pro call and the
confirmation interrupt — exactly the boundary the campaign wizard draws.

Scratch lives in ``state["campaign_builder_state"]`` (no reducer — rebuilt and
written whole, like the wizard scratch dicts): ``iteration``, ``filled`` slot
values, ``ops_done``, ``next_action``, ``action_log`` (compact, capped), the
per-stage results (``geo_result``, ``brief``, ``marketing_plan``,
``meta_campaign_ids``) and the ``geo_ws``/``maid_ws``/``media_ws`` scratches
the relocated executors cache into.
"""

from __future__ import annotations

import contextlib
import copy
import functools
import logging
import re
from typing import Any, Literal, Optional
from urllib.parse import urlparse

from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field, ValidationError

from app.graph.builder.executors.campaign import (
    CampaignGenerationError,
    generate_campaign_brief,
)
from app.core.config import settings
from app.graph.meta_spec import (
    BudgetParseError,
    CampaignSpec,
    SpecBuildError,
    build_campaign_tree,
    build_editor_catalog,
    errors_to_form_keys,
    parse_budget_to_cents,
)
from app.graph.meta_spec.builder import AUDIENCE_ROLE_LABELS, ad_name
from app.graph.builder.intake_form import (
    INTAKE_FIELD,
    build_intake_schema,
    intake_to_slots,
    parse_intake_submission,
)
from app.graph.builder.executors.geo import (
    DET_TYPE_MAP,
    LOCATION_TYPE_MAP,
    _execute_deterministic,
    _GeoStepPaused,
    build_angle_breakdown,
)
from app.graph.builder.executors.maid import run_maid_query
from app.graph.wizard_exit import StepPaused
from app.graph.builder.executors.media import (
    PLAN_FIXABLE_PUBLISH_STEPS,
    MetaPublishError,
    hydrate_media_urls,
    publish_campaign_to_meta,
)
from app.services.entitlement import ad_account_is_paid
from app.graph.builder.edits import (
    apply_edits,
    collect_pending,
    refresh_copy,
    stash_edits,
)
from app.graph.field_owner_registry import FIELD_OWNER
from app.graph.builder.prompts import BUILDER_PLANNER_SYSTEM_PROMPT
from app.graph.builder.scratch import act_stamp, save_act_scratch, take_act_scratch
from app.graph.builder.slots import (
    GATE_SLOTS,
    SLOTS,
    STAGE_ORDER,
    Slot,
    missing_required_slots,
    prefill_for,
    slot_applies,
)
from app.graph.prompts_registry import (
    GEO_DETERMINISTIC_OPTIONS,
    GEO_LOCATION_TYPE_OPTIONS,
    GO_LIVE_OPTIONS,
    PUBLISH_MODE_OPTIONS,
    STEP_PROMPTS,
)
from app.graph.state import AgentState, is_conversational
from app.graph.tool_runner import call_tool
from app.graph.tools import geocode_or_place
from app.graph.usage import tracked_ainvoke
from app.graph.narrator import add_beat, flush_narration, peek as _narrator_peek
from app.graph.narrator.beats import record_change
from app.graph.wizard_helpers import (
    _is_confirmation,
    confirmation_intent,
    _make_llm,
    drain_ledger,
    get_writer,
    is_resuming_step,
    market_hint,
    parse_brand_names,
    parse_event_queries,
    parse_int_safe,
    parse_location_names,
    parse_poi_types,
    parse_length,
    parse_radius_float,
    parse_store_addresses,
    read_user_turn,
    resolve_option,
    wizard_interrupt,
    wizard_milestone_narrate,
)

logger = logging.getLogger(__name__)

# Full cold-start build ≈ 16 asks + 6 acts + confirmation gates; budget leaves
# headroom for revision loops without letting a planner livelock run away.
_MAX_PLAN_ITERATIONS = 40
_ACTION_LOG_CAP = 40


async def _cached_parse(ws: dict, cache_key: str, raw: str, parser) -> list[str]:
    """Run an LLM-backed list parser once per distinct raw string, caching the
    result in the ``geo_ws`` scratch. ``builder_ask``/``builder_act`` can re-enter
    on resume; without this the parser would re-call the LLM on every replay.
    Mirrors the ``_geocoded_locations`` / ``_anchor_geocoded`` caching pattern.

    Comma is ambiguous in location/address input (it both separates distinct
    items and joins parts of one "City, Country" pair or street address), so the
    builder routes these through the geo wizard's smart parsers instead of a
    naive ``str.split(",")``.
    """
    # Empty input can't yield items — skip the LLM entirely. Most det_types leave
    # the other types' list slots blank, so without this every geo_discover would
    # fire a wasted parse call per unused slot.
    if not raw or not raw.strip():
        return []
    cached = ws.get(cache_key)
    if isinstance(cached, dict) and cached.get("raw") == raw:
        return list(cached.get("list") or [])
    parsed = await parser(raw)
    ws[cache_key] = {"raw": raw, "list": parsed}
    return parsed


async def _parse_addrs_never_drop(ws: dict, raw: str, cache_key: str) -> list[str]:
    """Parse a store / competitor-anchor answer into distinct addresses, NEVER
    dropping a non-empty answer.

    ``parse_store_addresses`` is LLM-backed and returns ``[]`` for a business name
    it doesn't consider a street address (e.g. "shawarmaz st catherine"). But
    ``geocode_or_place`` resolves exactly those via the Places fallback, so a drop
    here silently loses a perfectly resolvable location — which is what made the
    competitor confirm step say "I couldn't pinpoint that" while the radius step
    (reads the raw string) resolved the same anchor fine. The same applies to
    store_set: a user may type a store NAME, not a postal address. When the parser
    yields nothing, split on the documented unambiguous ';' outlet separator, else
    keep the whole answer as one entry — so the value always reaches
    geocode_or_place (which resolves business names via Places).
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    parsed = await _cached_parse(ws, cache_key, raw, parse_store_addresses)
    if parsed:
        return parsed
    semi = [s.strip() for s in raw.split(";") if s.strip()]
    return semi or [raw]


async def _parse_poi_types_never_drop(ws: dict, raw: str) -> list[str]:
    """Parse a POI-types answer into searchable venue phrases, NEVER dropping a
    non-empty answer.

    ``parse_poi_types`` is LLM-backed and normalizes each item (see its
    docstring) — a total parser failure (bad JSON, API error) is caught inside
    ``parse_list_input`` and falls back to a naive comma/semicolon split, which
    is fine. This wrapper is the last-resort guard for the case that fallback
    itself can't handle: an empty/non-list result reaching here at all. Mirrors
    ``_parse_addrs_never_drop`` above.
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    parsed = await _cached_parse(ws, "_parsed_poi_types", raw, parse_poi_types)
    if parsed:
        return parsed
    if ";" in raw:
        semi = [s.strip() for s in raw.split(";") if s.strip()]
        if semi:
            return semi
    comma = [s.strip() for s in raw.split(",") if s.strip()]
    return comma or [raw]


def _sync_confirm_edits(ws: dict, filled: dict, bs: dict, update: dict, state: Any = None) -> None:
    """Write a geo confirm-step location/store edit back to ``filled`` + the
    ``user_info`` prefill mirror, and pre-seed the parse cache with the exact
    synced list.

    ``_apply_location_edit``/its store counterpart (executors/geo.py) stash the
    merged set on ``ws["_locations_synced"]``/``["_stores_synced"]`` — ws-local,
    not ``filled``. Called only on a run that reaches the end of
    ``_execute_deterministic`` without pausing again, this used to leave a run
    that PAUSES again (``_GeoStepPaused``, e.g. an ambiguous added name needing
    its own disambiguation) with ``filled["locations"]`` still the pre-edit
    value. The next geo_discover dispatch re-derives ``location_names`` from
    that stale ``filled`` value (builder_act, this module), which no longer
    matches the ``_loc_cache_key`` ``_apply_location_edit`` computed — the
    mismatch check then pops ``_location_confirmed`` and prunes the just-picked
    disambiguation for the added name right back out of ``ws``, so it silently
    vanishes from the confirm map on the very next turn. Calling this from BOTH
    branches (paused and finished) closes that gap.

    Seeding ``_parsed_locations``/``_parsed_store_addresses`` (the same
    ``{"raw", "list"}`` shape ``_cached_parse`` reads) makes the next parse
    return the synced list verbatim instead of re-splitting the joined string
    through the LLM parser, which could re-merge a multi-word name back apart.
    """
    _locations_synced = ws.get("_locations_synced")
    if _locations_synced:
        _loc_list = [str(x) for x in _locations_synced]
        _loc_str = ", ".join(_loc_list)
        filled["locations"] = _loc_str
        bs["filled"] = filled
        update["user_info"] = {
            **(update.get("user_info") or {}), "location": _loc_str,
        }
        ws["_parsed_locations"] = {"raw": _loc_str, "list": _loc_list}
    # A search pinned to its own cities ("events only in Montreal") keeps its
    # list through a confirm-map edit; write that back to the durable specs, or
    # a later geocode rollback (which drops the sync) resurrects removed names.
    _angle_synced = ws.get("_angle_names_synced")
    _specs = ((state or {}).get("user_info") or {}).get("geo_angle_specs") if isinstance(state, dict) else None
    if _angle_synced and _specs:
        _new_specs = copy.deepcopy(_specs)
        for _s in _new_specs:
            _own, _now = _s.get("locations"), _angle_synced.get(_s.get("angle"))
            if _own and _now is not None and list(_now) != list(_own):
                _s["locations"] = list(_now)
        if _new_specs != _specs:
            update["user_info"] = {**(update.get("user_info") or {}), "geo_angle_specs": _new_specs}
    _stores_synced = ws.get("_stores_synced")
    if _stores_synced:
        _store_list = [str(x) for x in _stores_synced]
        _store_str = ", ".join(_store_list)
        filled["store_addresses"] = _store_str
        bs["filled"] = filled
        update["user_info"] = {
            **(update.get("user_info") or {}), "store_addresses": _store_str,
        }
        ws["_parsed_store_addresses"] = {"raw": _store_str, "list": _store_list}


def _sync_confirm_edits_undoable(ws: dict, filled: dict, bs: dict, update: dict, state: Any) -> None:
    """``_sync_confirm_edits`` plus an undo point for a confirm-step change.

    The executor stashes the decisions it is about to change (``_widget_undo_
    before`` — a map drag / pin / resize, a typed or clicked add/remove of a
    location or store). Here, once the act has settled, that becomes ONE v2
    snapshot — but only if something really changed (a plain "yes" through the
    same lane pushes nothing). Undo puts the old map back and re-runs the search.
    """
    from app.graph.builder.edits import GEO_DECISION_KEYS, push_undo

    before = ws.pop("_widget_undo_before", None)
    filled_before = dict(filled)
    _sync_confirm_edits(ws, filled, bs, update, state)
    if not before:
        return
    compared = (*GEO_DECISION_KEYS, "_geocoded_locations", "_geocoded_stores", "_locations_synced", "_stores_synced")
    if all(ws.get(k) == before.get(k) for k in compared):
        return
    ui_now = state.get("user_info") or {}
    ui_prev = {
        ui_key: ui_now.get(ui_key)
        for ui_key, slot in (("location", "locations"), ("store_addresses", "store_addresses"))
        if filled.get(slot) != filled_before.get(slot)
    }
    if "geo_angle_specs" in (update.get("user_info") or {}):
        ui_prev["geo_angle_specs"] = ui_now.get("geo_angle_specs")
    push_undo(bs, unit="poi_search", filled=filled_before, geo_before=before, user_info=ui_prev)


# Acts per stage, in execution order. _OPERATION_STAGE is derived.
_STAGE_ACTS: dict[str, tuple[str, ...]] = {
    "geo": ("geo_discover",),
    "maid": ("maid_query",),
    # OAuth + ad-account selection now happen up front in the connect_meta
    # PRE-act (see _STAGE_PRE_ACTS) — right after the audience is confirmed and
    # before the intake questions/brief, so both run with Meta creds in hand.
    # resolve_meta is what remains: PIXEL resolution only. It stays BEFORE
    # generate_meta_json (the spec's promoted_object wants the real pixel_id)
    # and AFTER the objective is known (media_select_pixel skips for
    # non-conversion objectives), so it runs after campaign_intake. It never
    # asks: a conversion run with no account pixel is answered in the plan editor.
    # export_audience is the whole of the self-publish route: the audience goes
    # into the user's ad account and nothing else is built.
    "campaign": ("export_audience", "generate_brief", "resolve_meta", "generate_meta_json"),
    # Creatives are collected per-ad inside the campaign editor (plan_confirm),
    # so the media stage only publishes — the old collect_creatives upload step
    # is gone. publish always leaves everything PAUSED; `activate` is what starts
    # delivery, behind the go_live_confirm preview gate.
    "media": ("publish", "activate"),
}
_OPERATION_STAGE: dict[str, str] = {
    op: stage for stage, ops in _STAGE_ACTS.items() for op in ops
}
# Which publish modes each act belongs to. An op missing from this map runs in
# every mode. See the `publish_mode` slot: `self` exports the audience and stops,
# `guide` and `express` differ only in how much of the plan editor they show —
# which is a widget payload difference (_plan_form_extra), not a routing one.
_OP_MODES: dict[str, frozenset[str]] = {
    "export_audience": frozenset({"self"}),
    "generate_brief": frozenset({"guide", "express"}),
    "resolve_meta": frozenset({"guide", "express"}),
    "generate_meta_json": frozenset({"guide", "express"}),
    "publish": frozenset({"guide", "express"}),
    "activate": frozenset({"guide", "express"}),
}


def _publish_mode(filled: dict) -> str:
    """The chosen mode, or "" before the question has been answered."""
    return str(filled.get("publish_mode") or "").strip().lower()


def _stage_acts(stage: str, filled: dict) -> tuple[str, ...]:
    """The stage's acts, minus the ones that don't apply to the chosen mode.

    Before `publish_mode` is answered every act still applies — the question
    itself is a required slot, so _next_step asks it long before it reaches the
    act loop, and an empty mode must not filter the geo/maid stages away.
    """
    mode = _publish_mode(filled)
    if not mode:
        return _STAGE_ACTS[stage]
    return tuple(
        op for op in _STAGE_ACTS[stage] if mode in _OP_MODES.get(op, frozenset({mode}))
    )


def _stage_exit_gate(stage: str, filled: dict) -> Optional[str]:
    """The stage's closing gate. Self-publish has no plan to approve, so the
    campaign stage closes as soon as the audience is exported."""
    if stage == "campaign" and _publish_mode(filled) == "self":
        return None
    return _STAGE_EXIT_GATE.get(stage)
# Acts that run as soon as their prerequisite slots are filled, BEFORE the
# stage's remaining slots.
#   • connect_meta has NO prereqs, so it fires the instant the campaign stage
#     opens — i.e. right after the maid stage (incl. the maid_confirm audience
#     gate) completes and before any intake question. This is what lets the
#     intake + brief run with the user's Meta creds/ad account already resolved.
#   • enrich_website scrapes the site for business context the brief uses (wizard
#     parity: campaign_enrich_website).
# Order matters: connect_meta first (fires immediately), enrich_website only
# once the intake has filled its prereqs. Kept out of _STAGE_ACTS so the
# post-slot act loop never double-runs them, and out of PlannerAction.operation
# so the planner can't propose them — they are deterministic-only, like the
# wizard's non-interrupt enrichment node.
_STAGE_PRE_ACTS: dict[str, tuple[tuple[str, frozenset[str]], ...]] = {
    "campaign": (
        ("connect_meta", frozenset()),
        ("enrich_website", frozenset({"business_name", "objective", "website_url"})),
    ),
}


def _resolved_pixel_id(bs: dict, ui: dict) -> Optional[str]:
    """The pixel to build promoted_object from.

    ONLY the one resolved against the live ad account by ``media_select_pixel`` —
    it exists on the account we publish to. A pixel scraped off the advertiser's
    website can belong to a different account: seeding the plan with it produces
    an id the editor's account-scoped picker cannot even display, and a publish
    Meta rejects. No pixel here means the editor asks for one.
    """
    return (bs.get("media_ws") or {}).get("pixel_id") or None


async def _recommended_budget(ui: dict, geo: dict, bs: dict, writer) -> str:
    """The daily budget a plan opens on when the user was never asked for one.

    ``build_budget_options`` already sizes tiers against the objective, targeting
    method and audience count, and pins temperature to 0 so the number is stable
    across a resume. We take its recommended tier. A failure here must not cost
    the run a plan, so it falls back to the configured floor — visible and wrong
    beats absent and fatal, and the editor is one field away either way.
    """
    from app.graph.builder.executors.campaign import build_budget_options

    try:
        options, _btype = await build_budget_options(
            ui, geo, bs.get("enrichment") or {}, writer, include_custom=False, bs=bs,
        )
        chosen = next(
            (o for o in options if "recommended" in o.lower()),
            options[0] if options else "",
        )
        if chosen:
            return chosen
    except Exception:
        logger.warning("budget recommendation failed — falling back to the floor", exc_info=True)
    # The floor is per ad account and per currency, so the fallback is read off
    # the account too — a dollar constant here spends the wrong amount on every
    # non-USD account, which is the one case this branch exists to survive.
    from app.graph.builder.executors.campaign import _budget_floor

    floor, code = _budget_floor(ui, "daily", 1)
    return f"{code} {int(floor)}/day"


async def _intake_budget_prefill(
    ui: dict, geo: dict, bs: dict, writer
) -> tuple[Optional[int], str]:
    """``(minor units, why)`` for the express intake's budget box.

    Guide mode never asks — ``generate_brief`` opens the plan on
    ``_recommended_budget`` and the editor shows it filled in. Express asks, and
    asks it before the user has seen a plan, so hand them the same recommendation
    as the box's starting value rather than an empty field with a floor.

    Costs nothing extra: ``generate_brief`` only derives one when ``user_info``
    carries no budget, and an answered intake always does. An unparseable label
    leaves the box empty — ``parse_intake_submission`` still requires an amount,
    so the failure mode is the behaviour we have today.
    """
    label = await _recommended_budget(ui, geo, bs, writer)
    try:
        return parse_budget_to_cents(label, ui.get("ad_account_currency")), label
    except BudgetParseError:
        logger.warning("intake budget prefill: no number in %r", label)
        return None, ""


def _pre_act_pending(bs: dict, stage: str, filled: dict) -> Optional[str]:
    """Name of the first pre-slot act whose prereqs are filled but isn't done."""
    done = _ops_done(bs)
    for op, prereqs in _STAGE_PRE_ACTS.get(stage, ()):
        if op not in done and all(str(filled.get(p) or "").strip() for p in prereqs):
            return op
    return None
# Confirmation slot that must be answered (and approved) BEFORE this op runs.
# generate_meta_json is deliberately NOT gated any more: the spec is built first
# so plan_confirm can present a real, editable payload instead of a preview of
# one. plan_confirm is now the campaign stage's exit gate (below).
# publish is deliberately NOT gated: the plan editor's own Publish button is the
# confirmation, and publish only creates PAUSED objects. go_live_confirm below is
# what stands between them and spend.
_OP_GATE: dict[str, str] = {
    # The campaign already exists in Meta, PAUSED, and the user has seen Meta's
    # own previews of it. This gate is the last thing before live spend.
    "activate": "go_live_confirm",
}


class SubscriptionRequired(Exception):
    """Raised by `_require_paid_account` when `publish` or `activate` is
    attempted on a Meta ad account with no active Punk subscription.

    Caught in `builder_act` above the generic `except Exception` — the
    generic handler reports `builder_act_failed`, which would tell the user
    something broke, when nothing did. `pending` is a `PendingAction` dict,
    already shaped for the same no-interrupt() permission-gate pattern
    `campaign_manager_node._write_permission_pending` uses.
    """

    def __init__(self, pending: dict):
        self.pending = pending
        super().__init__("subscription required for this ad account")


def _subscription_required_pending(ad_account_name: str) -> dict:
    name = ad_account_name.strip() if ad_account_name else "this ad account"
    return {
        "action_type": "option_selection",
        "options": ["I've subscribed — try again", "Not now"],
        "prompt": (
            f"**{name}** doesn't have an active Punk subscription yet, so I "
            "can't publish or start a live campaign on it. Subscribe this "
            "account from Billing, then come back and try again."
        ),
        "field": "subscription_required",
        "step_key": "subscription_required",
        "prefill": None,
        "stepper": None,
        "progress": None,
    }


async def _require_paid_account(state: AgentState, writer: Any, ad_account_id: str, ad_account_name: str = "") -> None:
    """Raise `SubscriptionRequired` unless `ad_account_id` has an active
    Punk subscription. Call before any op that creates or activates a live
    Meta object — never before a read."""
    if await ad_account_is_paid(state.get("user_id"), ad_account_id):
        return
    pending = _subscription_required_pending(ad_account_name)
    writer({"type": "assistant_message", "content": pending["prompt"]})
    writer({"type": "pending_action", "content": pending})
    raise SubscriptionRequired(pending)


# Confirmation slot that closes the stage AFTER its last op.
_STAGE_EXIT_GATE: dict[str, str] = {
    "geo": "poi_confirm",
    "maid": "maid_confirm",
    "campaign": "plan_confirm",
}
# Gate slots may only be asked once their prerequisite op is done.
_GATE_PREREQ_OP: dict[str, str] = {
    "poi_confirm": "geo_discover",
    # The campaign spec must exist before we can ask the user to approve it.
    "plan_confirm": "generate_meta_json",
    "maid_confirm": "maid_query",
    # There is nothing to preview until the ads exist in Meta.
    "go_live_confirm": "publish",
}

# Options offered at maid_confirm when the query genuinely failed this turn
# (bs["maid_retry_pending"] set — see builder_act's maid_query branch). The
# first option is always the recommended one: a bare "yes"/"ok" resolves to
# it in _apply_gate_answers, since there is no audience to confirm.
_MAID_RETRY_OPTIONS_DEFAULT = ("Retry now", "Continue without a visitor audience")
_MAID_RETRY_OPTIONS: dict[str, tuple[str, ...]] = {
    # A configuration problem, not a transient one — retrying the same call
    # cannot fix it, so it is not offered.
    "ip_not_allowlisted": ("Continue without a visitor audience",),
}

# Fields the competitor_anchor_confirm branch (below) applies itself via a
# targeted re-geocode. stash_edits excludes exactly these so a co-emitted edit
# to anything ELSE ("also change my budget") still reaches apply_pending_edits
# instead of being acked and dropped. Kept as one constant so the exclude list
# here and the read loop that consumes them cannot drift apart.
_ANCHOR_OWNED_FIELDS = (
    "store_addresses", "geo_store_addresses", "competitor_address", "competitor_anchor",
)


class PlannerAction(BaseModel):
    """One structured next-action from the planner LLM."""

    kind: Literal["ask", "act", "done", "fail"]
    slot: Optional[str] = None
    """Slot name to collect — required when kind='ask'."""
    operation: Optional[
        Literal[
            "geo_discover",
            "maid_query",
            "generate_brief",
            "generate_meta_json",
            "resolve_meta",
            "publish",
        ]
    ] = None
    """Operation to run — required when kind='act'."""
    reason: Optional[str] = None
    """Short rationale; the failure reason when kind='fail'."""


# ── Scratch helpers ────────────────────────────────────────────────────────────

def _wizard_exit_class():
    """Lazy import of WizardExitRequested to avoid a circular import."""
    from app.graph.wizard_exit import WizardExitRequested
    return WizardExitRequested


def _bs(state: AgentState) -> dict:
    return dict(state.get("campaign_builder_state") or {})


def _log(bs: dict, entry: dict) -> None:
    log = list(bs.get("action_log") or [])
    log.append(entry)
    bs["action_log"] = log[-_ACTION_LOG_CAP:]


def _ops_done(bs: dict) -> set[str]:
    return set(bs.get("ops_done") or [])


def _has_repeated_action_error(bs: dict) -> bool:
    """Whether the action log shows the same act step erroring twice.

    The only real signal that a planner `kind="fail"` is warranted rather than
    a misread of a healthy pause-and-retry loop (see `coerce_action`) — actual
    exceptions are logged by `builder_act`'s except-block as
    ``{"step": f"act:{operation}", "summary": f"error: {exc}"}``.
    """
    counts: dict[str, int] = {}
    for entry in bs.get("action_log") or []:
        step = str(entry.get("step") or "")
        summary = str(entry.get("summary") or "")
        if step.startswith("act:") and summary.startswith("error:"):
            counts[step] = counts.get(step, 0) + 1
            if counts[step] >= 2:
                return True
    return False


def _mark_op_done(bs: dict, op: str) -> None:
    bs["ops_done"] = sorted(_ops_done(bs) | {op})


def _reopen_plan_editor(bs: dict, filled: dict) -> None:
    """Send the flow back to the campaign plan editor.

    Dropping the gate answer is not enough: slot selection is stage-scoped.
    ``plan_confirm`` is the campaign stage's EXIT gate, and ``stages_complete`` is
    append-only (``_refresh_stage_completion``) — so with "campaign" still marked
    done, ``_current_stage`` stays on "media" and the user never sees the editor.
    Un-completing the stage is what actually reopens it. "media" goes too,
    otherwise the campaign stage closes again and lands straight back in the media
    stage with it already marked done.
    """
    filled.pop("plan_confirm", None)
    # `publish_fail_counts` deliberately survives: every publish failure reopens
    # this editor, so resetting here would make `_PUBLISH_RETRY_LIMIT` unreachable
    # and the terminal wording would never fire. An *edited* plan is the fresh
    # attempt, so the reset lives in `_apply_plan_form_submission` instead.
    bs["stages_complete"] = sorted(
        set(bs.get("stages_complete") or []) - {"campaign", "media"}
    )


# How many times one publish step may fail before the gate stops re-offering
# itself. Two retries is enough for a flaky upload; beyond that the answer is not
# going to change and the widget is just a loop.
_PUBLISH_RETRY_LIMIT = 3


def _publish_is_terminal(exc, fails: dict) -> tuple[bool, bool]:
    """``(terminal, permission)`` for a publish failure — is another identical
    attempt pointless?

    No longer decides *where* the user lands (every failure reopens the plan
    editor); it decides how the failure is worded. Meta's permission family (app
    capability / missing scope / dead token) and a step that has already failed
    ``_PUBLISH_RETRY_LIMIT`` times will not go differently on an unchanged spec,
    so those get "here is what to fix" instead of "let's retry".

    ``custom_audience`` is exempt: its re-asked gate offers the geo-only publish,
    which is a genuinely different attempt. The plan-fixable steps are exempt
    because they leave the ad account clean and Meta's rejection reaches the field
    it is about — what the user publishes next is a different plan, so counting
    those would spend the whole allowance on three typos.

    Mutates ``fails`` — the per-step counter lives in the builder state so it
    survives the interrupt/resume round trip, and only a plan resubmission clears
    it (``_apply_plan_form_submission``).
    """
    from app.services.meta_ads import is_permission_error

    fails[exc.step] = fails.get(exc.step, 0) + 1
    if exc.step == "custom_audience":
        return False, False
    if exc.step in PLAN_FIXABLE_PUBLISH_STEPS:
        permission = is_permission_error(exc.__cause__)
        return permission, permission
    permission = is_permission_error(exc.__cause__)
    return permission or fails[exc.step] >= _PUBLISH_RETRY_LIMIT, permission


def _apply_publish_failure(bs: dict, filled: dict, exc, message: str) -> None:
    """Where a failed publish leaves the user.

    The default is the plan editor, with the reason attached — the publish gate's
    only control is "publish the same thing again", so re-asking it was a dead end
    that burned the retry cap on an unchanged spec. Reopening the campaign stage is
    the only way back to the editor: the client unmounts it on submit and never
    re-renders it from the transcript.

    A rejection ``meta_remediation`` recognises does not go there, because the plan
    is not what is wrong — the fix is a Meta screen (Terms of Service nobody has
    accepted, an account with no card on it) and no control in the editor can
    touch it. Its ``severity`` decides:

    * ``degrades`` — Punk publishes with less rather than not at all. The audience
      case is the original: ``publish_without_audience`` makes the next attempt
      hand every seed/lookalike ad set to Advantage+ inside the same locations, the
      op is left un-done so ``_next_step`` re-runs publish immediately, and
      ``custom_audience`` cannot fail again because it no longer runs.
    * ``blocks`` — nothing to degrade to. The editor still reopens, because its
      Publish button IS the retry and it is the only screen that has one: leaving
      the publish op un-done with no gate in front of it re-runs the failing Meta
      call every iteration until the plan budget is gone (the hazard the
      ``export_audience`` handler documents). What changes is that no control is
      marked and no "adjust the plan" banner appears — the fix-it card goes up
      instead, because there is nothing on that form to adjust.

    Either way the fix-it card travels on ``publish_remediation`` and is restated
    on the Preview & Publish screen (``_preview_extra``).
    """
    fix = getattr(exc, "remediation", None)
    if fix:
        bs["publish_remediation"] = [
            r for r in (bs.get("publish_remediation") or []) if r.get("key") != fix["key"]
        ] + [fix]

    degrades = (fix or {}).get("severity") == "degrades"
    if degrades or exc.step == "custom_audience":
        bs["publish_audience_blocked"] = True
        bs["publish_without_audience"] = True
    elif fix:
        _reopen_plan_editor(bs, filled)
        # Deliberately no plan_errors: marking a control the user cannot fix from
        # here makes the editor look broken and hides the real instruction.
        bs.pop("plan_errors", None)
    else:
        _reopen_plan_editor(bs, filled)
        # The field Meta named AND the banner. Without the field keys this was a
        # page-level message over a plan with nothing marked on it, so "adjust the
        # plan and try again" had no target.
        bs["plan_errors"] = {**exc.plan_errors, "__root__": message}
    bs["filled"] = filled


def _publish_terminal_message(exc, *, permission: bool) -> str:
    """Wording for a publish that will not succeed on another identical attempt.

    Never says "let's retry" — that is what sent the user round the loop this
    replaces. Anything already created in Meta is PAUSED (every spec defaults to
    PAUSED and activation is a separate final pass), so the user is told their
    money is safe rather than left guessing.
    """
    cause = exc.__cause__
    detail = getattr(cause, "user_msg", None) or exc.user_message
    if permission:
        head = (
            "Meta refused this call for permissions, not for anything wrong with your "
            "campaign — retrying the same way will keep failing. "
            "Reconnect your Meta account, and if that doesn't clear it your ad account "
            "or app is missing Ads Management access for this action."
        )
    else:
        head = (
            f"Publishing failed {_PUBLISH_RETRY_LIMIT} times at the same step. "
            "Publishing the same plan again will fail the same way — something in it "
            "has to change."
        )
    tail = (
        "Anything already created in Meta is PAUSED and not spending, and your campaign "
        "plan is open below — change what you need and hit publish again once it's sorted."
    )
    return f"{head}\n\nMeta said: {detail}\n\n{tail}"


def _stage_complete(bs: dict, stage: str) -> bool:
    return stage in set(bs.get("stages_complete") or [])


def _current_stage(bs: dict, state: AgentState) -> str:
    """First incomplete stage in pipeline order."""
    for stage in STAGE_ORDER:
        if _stage_complete(bs, stage):
            continue
        return stage
    return "done"


def _gate_pending(gate: Optional[str], filled: dict) -> bool:
    """Gate slot still needs an answer — skipped when its only_when predicate
    fails (e.g. poi_confirm is deterministic-only)."""
    if not gate or str(filled.get(gate, "") or "").strip():
        return False
    slot = SLOTS.get(gate)
    return slot is None or slot_applies(slot, filled)


def _next_step(bs: dict, stage: str) -> Optional[dict]:
    """Deterministic next action within one stage, or None when the stage is
    finished: pre-act slots → acts in order (gates between) → exit gate."""
    filled = bs.get("filled") or {}
    # Pre-slot acts run once their prereq slots are filled, before the stage's
    # remaining required slots (e.g. enrich_website scrapes the site so the
    # intake form opens with the business already described).
    pre_op = _pre_act_pending(bs, stage, filled)
    if pre_op:
        return {"kind": "act", "operation": pre_op}
    missing = missing_required_slots(stage, filled)
    if missing:
        return {"kind": "ask", "slot": missing[0].name}
    done = _ops_done(bs)
    for op in _stage_acts(stage, filled):
        gate = _OP_GATE.get(op)
        if _gate_pending(gate, filled):
            return {"kind": "ask", "slot": gate}
        if op not in done:
            # maid_query failed genuinely (budget/breaker/IP/an un-splittable
            # timeout) rather than succeeding with zero — builder_act left it
            # OUT of ops_done on purpose so a bare re-plan does not silently
            # retry it. Ask the maid_confirm gate instead of re-running the
            # act: _enrich_slot_ask's maid_confirm branch sees
            # maid_retry_pending and asks a real retry question (not "does
            # this look right?"), and the answer clears the flag one way or
            # the other. Without this, the op stayed "not done" forever with
            # nothing left to break the loop — every subsequent plan visit
            # re-proposed the same failed act.
            if op == "maid_query" and bs.get("maid_retry_pending"):
                return {"kind": "ask", "slot": "maid_confirm"}
            return {"kind": "act", "operation": op}
    exit_gate = _stage_exit_gate(stage, filled)
    if _gate_pending(exit_gate, filled):
        return {"kind": "ask", "slot": exit_gate}
    return None


def _refresh_stage_completion(bs: dict, state: AgentState) -> None:
    """Mark the current stage complete once _next_step has nothing left.
    Idempotent — called at the top of every plan visit."""
    while True:
        stage = _current_stage(bs, state)
        if stage == "done" or _next_step(bs, stage) is not None:
            return
        bs["stages_complete"] = sorted(set(bs.get("stages_complete") or []) | {stage})


def _restore_locked_targeting(new_spec: dict, prior: dict) -> None:
    """Re-inject the server-owned, editor-locked targeting into a submitted spec.

    Geo ZIPs (from the map step) and the MAID ``audience_role``/``custom_audiences``
    are shown read-only in the editor; they are the product and must not be
    editable there. The editor round-trips them, but a stale or partial submission
    could drop them — so we authoritatively restore them from the previously stored
    spec.

    ``audience_role`` is matched by ad set **name**, not by position. The editor
    can add and delete ad sets, and position-matching meant deleting the seed ad
    set promoted whichever ad set shifted into index 0 to ``seed`` — so publish
    attached the MAID custom audience to an ad set the user never chose, with no
    error and nothing on screen to show it. A name that matches no prior ad set
    is a new or renamed one, and keeps the role the client sent (the editor
    creates them ``broad``).

    Geo stays index-matched: every ad set in a run shares one zip set, so a
    mis-match is a no-op, and the first prior ad set is the right fallback for an
    ad set the user just added.
    """
    prior_adsets = prior.get("adsets") or []
    if not prior_adsets:
        return
    prior_by_name = {
        a.get("name"): a for a in prior_adsets if a.get("name")
    }
    for idx, adset in enumerate(new_spec.get("adsets") or []):
        t = adset.get("targeting")
        if not isinstance(t, dict):
            t = {}
            adset["targeting"] = t

        geo_source = prior_adsets[idx] if idx < len(prior_adsets) else prior_adsets[0]
        prior_geo = (geo_source.get("targeting") or {}).get("geo_locations")
        if prior_geo is not None:
            t["geo_locations"] = prior_geo

        # audience_role decides which real audience id bind_audiences injects at
        # publish; keep the planned role rather than trusting the client.
        prior_role = (prior_by_name.get(adset.get("name")) or {}).get("audience_role")
        if prior_role:
            adset["audience_role"] = prior_role


def _mirror_first_ad(spec: dict) -> None:
    """Express edits one ad card — every ad set publishes that same creative.

    The express editor renders only ad set 0's ads, so the ads on the other ad
    sets keep the brief's copy and never get media — and a media-less ad is
    skipped at publish, quietly shipping an ad set with no ad. Copy ad set 0's
    ads over them instead.
    """
    adsets = spec.get("adsets") or []
    source = (adsets[0].get("ads") or []) if adsets else []
    if not source:
        return
    for adset in adsets[1:]:
        ads = copy.deepcopy(source)
        # An app ad set with its own store URL keeps that link — the same reason
        # build_campaign_tree derives adset_link per ad set.
        store_url = (adset.get("promoted_object") or {}).get("object_store_url")
        for d, ad in enumerate(ads):
            # Same shape build_campaign_tree gives a fresh ad; a second ad on the
            # same ad set (never in express today) gets a number to stay distinct.
            ad["name"] = ad_name(
                str((ad.get("creative") or {}).get("title") or "Ad"),
                str(adset.get("name") or "Ad Set"),
            ) + (f" {d + 1}" if d else "")
            if store_url and isinstance(ad.get("creative"), dict):
                ad["creative"]["link"] = store_url
        adset["ads"] = ads


def _apply_plan_form_submission(bs: dict, submission: dict) -> Optional[str]:
    """Validate a full campaign-editor submission and store it as the plan.

    The editor owns the whole campaign tree (add/remove ad sets and ads, per-ad
    creative), so a submission carries the complete edited spec — ``{action,
    spec}`` — not a diff. We restore the locked geo/audience targeting, validate
    against ``CampaignSpec`` (the authority), and store the result.

    Three outcomes:
      * valid + action=publish → gate satisfied, flow advances
      * valid + action=save    → spec stored, gate re-asked so the user can keep
                                 editing
      * invalid                → field errors + the user's edited tree stashed so
                                 the editor re-renders exactly what they typed.
    """
    filled = bs.get("filled") or {}
    new_spec = submission.get("spec")
    action = str(submission.get("action") or "publish").lower()

    if not isinstance(new_spec, dict):
        filled.pop("plan_confirm", None)
        return "plan editor sent no spec — asking again"

    bs.pop("plan_errors", None)
    # A resubmitted plan is a genuinely fresh attempt, so the per-step failure
    # counters start over. This is the only place they reset: reopening the editor
    # does not, or publishing the same spec forever would never hit the cap.
    bs.pop("publish_fail_counts", None)
    # The draft is the fallback source of the locked geo/audience: a plan that has
    # never validated (a conversion goal still missing its pixel) has no stored
    # marketing_plan, and the locks must survive that round trip too.
    _restore_locked_targeting(
        new_spec, bs.get("marketing_plan") or bs.get("marketing_plan_draft") or {}
    )
    # "Do it for me" shows a single ad card; it stands for every ad set — unless
    # the user hit "Unlock & edit", which means they are now editing ad sets
    # individually and the mirror would just overwrite what they typed into ad
    # set 2+ with ad set 0's ad. Checked against bs, not just this submission:
    # the editor remounts after every save (a fresh mount starts its local
    # "unlocked" state over), so a Save after the one that unlocked it would
    # otherwise re-mirror and silently discard the user's per-ad-set edits.
    #
    # Two-way now: the frontend seeds its local `unlocked` state from
    # express_unlocked (below) and sends the flag back either way, so a
    # RE-lock (unlocked -> submission.unlocked=False) clears it here too — the
    # frontend already restored the campaign/ad-set halves to Punk's plan
    # before this submit (see CampaignEditor's relock()), so the mirror below
    # is exactly what re-propagates the surviving ad onto the rest.
    if "unlocked" in submission:
        bs["express_unlocked"] = bool(submission["unlocked"])
    if not bs.get("express_unlocked") and _publish_mode(filled) == "express":
        _mirror_first_ad(new_spec)

    try:
        spec = CampaignSpec.model_validate(new_spec)
    except (ValidationError, ValueError) as exc:
        # A rejected edit is the editor's normal error path, not a run failure.
        # Keep the user's (invalid) tree so the re-emitted editor shows it, with
        # the errors attached to the offending fields.
        bs["plan_errors"] = errors_to_form_keys(exc)
        bs["marketing_plan_draft"] = new_spec
        filled.pop("plan_confirm", None)
        return "plan has validation errors — re-emitting the editor"

    # Valid: the edited spec is now authoritative. Clear any invalid draft and
    # mark generate_meta_json done so it does not rebuild a brief-derived tree
    # over the user's full edits.
    bs.pop("marketing_plan_draft", None)
    edited = spec.model_dump(mode="json")
    # A previous publish may have left a campaign tree in the resume ledger. It
    # describes the plan as it WAS, so resuming it after a real edit would publish
    # the old plan and silently drop what the user just changed. Only a changed
    # plan sets this — hitting publish again unchanged still resumes, which is the
    # whole point of the ledger.
    if edited != (bs.get("marketing_plan") or {}):
        bs["publish_plan_dirty"] = True
    bs["marketing_plan"] = edited
    bs["ops_done"] = sorted(_ops_done(bs) | {"generate_meta_json"})
    # The Page the user picked in the editor becomes the wizard's Page. Without
    # this, the one path that rebuilds the tree (_plan_form_extra, when a stored
    # spec fails re-validation) would re-read the connect-time default and
    # silently revert them to whichever Page Meta happened to list first.
    if spec.page_id:
        media_ws = dict(bs.get("media_ws") or {})
        media_ws["page_id"] = spec.page_id
        media_ws["instagram_user_id"] = spec.instagram_user_id or ""
        # lead_form_candidates was still the PREVIOUS Page's forms — every Page's
        # forms were already fetched at connect time onto page_candidates
        # (media_detect_page_assets), so this is a lookup, not a Graph call.
        new_page = next(
            (p for p in media_ws.get("page_candidates") or [] if p.get("id") == spec.page_id),
            None,
        )
        if new_page is not None:
            media_ws["lead_form_candidates"] = new_page.get("lead_forms") or []
        bs["media_ws"] = media_ws

    # Campaign-level, and not a Meta field, so it arrives beside the spec rather
    # than inside it. Applied for save and publish alike — the user changed it on
    # the screen either way.
    tracking_method = str(submission.get("tracking_method") or "").strip()
    if tracking_method:
        filled["tracking_method"] = tracking_method

    if action == "save":
        filled.pop("plan_confirm", None)
        return "plan saved — re-emitting the editor for review"

    # action == "publish": gate satisfied (plan_confirm stays set). Return None so
    # _apply_confirm_semantics continues to any later gate this turn.
    return None


async def _apply_template_action(bs: dict, state: AgentState, submission: dict) -> str:
    """Overlay a previous campaign onto the plan currently in the editor.

    The editor sends
    ``{action: "apply_template", campaign_id, adset_ids?, ad_ids?, spec}``. ``spec``
    is what is on screen — applying to that rather than to a rebuilt tree means
    edits already made are kept underneath the template, and picking a second
    template replaces the first rather than compounding it.

    ``adset_ids`` / ``ad_ids`` are the ad sets and ads ticked in the editor's copy
    picker. **Absent** means the whole campaign — what the feature did before the
    picker existed, and what the editor sends when it could not read the campaign's
    structure. An **empty list** means the picker was used and nothing was ticked
    at that level, which is a different answer: unticking every ad under a ticked
    ad set copies its settings and none of its copy.

    An empty ``campaign_id`` is "set up fresh": there is nothing to undo, because
    the overlay never destroyed the built plan — it produced a new tree from it.

    The on-screen spec is validated before it is stored, exactly as the save path
    does. Storing it unchecked meant an invalid tree could land in
    ``marketing_plan``, and the next render of an invalid ``marketing_plan``
    (``_plan_form_extra``) drops ``generate_meta_json`` and rebuilds from the
    brief — silently throwing the user's whole plan away.
    """
    campaign_id = str(submission.get("campaign_id") or "").strip()
    current = submission.get("spec")
    if isinstance(current, dict):
        _restore_locked_targeting(
            current, bs.get("marketing_plan") or bs.get("marketing_plan_draft") or {}
        )
        try:
            CampaignSpec.model_validate(current)
        except (ValidationError, ValueError) as exc:
            bs["plan_errors"] = errors_to_form_keys(exc)
            bs["marketing_plan_draft"] = current
            return "plan has validation errors — re-emitting the editor before applying a template"
        bs["marketing_plan"] = current
    if not campaign_id:
        return "no template selected — leaving the plan as it is"

    def _ids(key: str) -> Optional[list[str]]:
        raw = submission.get(key)
        return [str(i) for i in raw if i] if isinstance(raw, list) else None

    adset_ids, ad_ids = _ids("adset_ids"), _ids("ad_ids")

    plan = bs.get("marketing_plan") or {}
    bs.pop("marketing_plan_draft", None)
    bs.pop("plan_errors", None)
    bs["marketing_plan"] = await _apply_previous_campaign(
        bs, _ui_view(state, bs), dict(plan), campaign_id,
        adset_ids=adset_ids, ad_ids=ad_ids,
    )
    # generate_meta_json must not rebuild over this on the next visit.
    bs["ops_done"] = sorted(_ops_done(bs) | {"generate_meta_json"})
    picked = (
        f" ({len(adset_ids or [])} ad set(s) / {len(ad_ids or [])} ad(s) picked)"
        if adset_ids is not None or ad_ids is not None else ""
    )
    return (
        f"applied the setup from campaign {campaign_id}{picked} — re-emitting the editor"
    )


# Keys that mark a JSON reply at poi_confirm/maid_confirm as the editable
# map's own delta payload, as opposed to some other JSON-shaped text that
# merely parses as an object. Checked BEFORE the value is trusted as a
# confirmation — `_parse_json_value(raw, "{")` succeeding on ANY object used
# to be read as "this is a confirm", so a garbage payload like
# {"poi_radius_m": -99999, "lookback_days": 100000} closed the gate outright.
_DELTA_KEYS = frozenset({"confirm", "added", "removed"})


async def _apply_confirm_semantics(bs: dict, state: AgentState) -> Optional[str]:
    """Interpret answered confirmation gates (code, not prompt). Returns a
    thinking note when an answer changed the plan state.

      plan_confirm    – any non-approve answer = revision request: stash the
                        text for the regeneration prompt, clear the brief, and
                        re-run generate_brief (mirrors the wizard's loop; the
                        wizard's separate patch-extraction LLM call is replaced
                        by feeding the verbatim request to the brief LLM).
      poi_confirm     – decline re-asks the same confirm (wizard re-loops);
                        an editable-map delta removes/adds discovered POIs.
      maid_confirm    – decline re-asks; an editable-map delta removes POIs and
                        drops the audience attributed to them, then re-shows the
                        recomputed map for another confirm.
      go_live_confirm – "Leave it paused" closes the media stage with the
                        campaign built but not delivering.
    """
    filled = bs.get("filled") or {}

    poic_raw = filled.get("poi_confirm")
    poic_str = str(poic_raw or "").strip()
    if poic_str:
        # The editable POI map sends a JSON delta ({"confirm": .., "added": [..],
        # "removed": [..]}); a plain text answer falls through to the membership
        # check. Mirror the geo wizard's geo_confirm_pois interpretation.
        #
        # `edits and not _DELTA_KEYS.isdisjoint(edits)` (not a bare `if edits`)
        # — any JSON object used to be trusted as "this is the delta shape",
        # confirmation gate satisfied, no further check. A garbage payload
        # that merely PARSES as an object ({"poi_radius_m": -99999,
        # "lookback_days": 100000}) walked straight through as a confirm.
        # Shape must be checked before the value is trusted as a confirmation
        # signal; a non-delta object now falls through to the plain yes/no
        # parse below like any other text answer.
        edits = _parse_json_value(poic_raw, "{")
        if edits and not _DELTA_KEYS.isdisjoint(edits):
            if edits.get("confirm") is False:
                filled.pop("poi_confirm", None)
                return "POIs not confirmed — asking again"
            # Confirmed (possibly with edits) — apply the delta to the discovered
            # POIs and leave the gate value set so flow advances past geo.
            # ponytail: this branch never persists to Postgres the way maid_confirm's
            # sibling below (_apply_maid_poi_edits) does — same gap undo() had until
            # its own fix. Left alone because it cannot fire with an extraction
            # already on record: reaching poi_confirm again requires backtracking
            # through geo_pois_confirmation, and invalidate_from("poi_search") drops
            # geo_result (and maid_extraction_id with it) on the way there. If a
            # future path reaches this gate with an extraction still live, delegate
            # to _apply_maid_poi_edits the same way _apply_geo_poi_selection_edit does.
            from app.graph.builder.executors.geo import apply_poi_edits, _poi_key
            det = bs.get("geo_result")
            if isinstance(det, dict):
                _removed_pois = list(edits.get("removed") or [])
                _push_map_delta_undo(bs, "poi_confirm", edits)
                added_applied, removed_names = apply_poi_edits(det, edits)
                bs["geo_result"] = det
                if added_applied:
                    _record_map_additions(bs, list(edits.get("added") or []))
                if removed_names:
                    # A manual map removal must join the SAME replayable spec
                    # list an NL trim writes to (`_poi_selection_specs`) — else
                    # a later re-fold (a fresh search, or another NL trim)
                    # re-derives from the untouched superset and resurrects
                    # exactly what the user just clicked off the map.
                    # Identity-pinned (`ids`), not a `match` — this removal
                    # names no CATEGORY, only the specific POIs clicked.
                    _record_map_removals(bs, _removed_pois)
                if added_applied or removed_names:
                    # The count changed. Two things must happen so the USER sees
                    # it (both were missing — the reported "count never updates"
                    # bug): (1) flag a geo_data re-commit so the narrator grounding
                    # pack refreshes from the edited det, and (2) record an `edit`
                    # beat so the next pause's composed message states the new
                    # total instead of silently carrying the pre-edit `geo_complete`
                    # count. Reuse the beat pipeline — no hand-rolled emit here.
                    bs["_geo_recommit"] = True
                    new_total = int(det.get("pois_found", 0))
                    add_beat(
                        state, "edit",
                        {
                            "stage": "geo_poi_edit",
                            "poi_count": new_total,
                            "added": len(added_applied),
                            "removed": len(removed_names),
                        },
                        fallback=(
                            f"Updated — you're now targeting **{new_total}** "
                            "spot(s). Let's keep building your audience from there."
                        ),
                    )
                    return (
                        f"POI edits applied: +{len(added_applied)} added / "
                        f"-{len(removed_names)} removed / total={det['pois_found']}"
                    )
        elif confirmation_intent(poic_str) != "yes":
            # Covers a plain rejection AND an unclear reply (an unrelated
            # question, "Yes." mis-parsed by the old exact-membership check,
            # a non-delta JSON blob) — none of those are the user cancelling,
            # so this only ever re-asks, never reports a cancellation.
            filled.pop("poi_confirm", None)
            return "POIs not confirmed — asking again"

    pc = str(filled.get("plan_confirm") or "").strip()
    if pc and "generate_brief" in _ops_done(bs):
        # The plan gate is the campaign_plan_editor. A submission is
        # {"action": "publish"|"save", "spec": {...}}: the whole edited campaign
        # tree, validated and stored as the plan. Anything that is not a form
        # submission (a stray typed reply) just drops the gate answer so the editor
        # re-emits — there is no prose-revision path.
        submission = _parse_json_value(pc, "{")
        if isinstance(submission, dict) and submission.get("action") == "apply_template":
            # "Start from a previous campaign", chosen from inside the editor. It
            # needs a Graph read, so it cannot be a local swap like every other
            # field — the editor sends the campaign id and gets the overlaid plan
            # back. Applied to the tree currently on screen, so edits made before
            # picking a template survive underneath it.
            note = await _apply_template_action(bs, state, submission)
            filled.pop("plan_confirm", None)
            return note
        if isinstance(submission, dict) and "spec" in submission:
            note = _apply_plan_form_submission(bs, submission)
            # A publish submission returns None (gate satisfied) — fall through so
            # any other gate answered the same turn is still processed. A save /
            # error returns a note and stops here.
            if note is not None:
                return note
        else:
            filled.pop("plan_confirm", None)
            return "waiting for the plan form — re-asking"

    _maid_retry = bs.get("maid_retry_pending")
    if _maid_retry and str(filled.get("maid_confirm") or "").strip():
        # maid_confirm was asked as a RETRY question (_enrich_slot_ask above),
        # not the usual "does this look right?" — so its answer is resolved
        # against those options, and specifically NOT against the plain
        # confirm gate below: a bare "yes" here used to satisfy the plain
        # permission gate
        # and close the maid stage with a genuinely failed, zero-count
        # extraction and no way back (thread a10b211a). There is no audience
        # to confirm, so a bare "yes"/"ok" resolves to the first (recommended)
        # option instead of ever reading as confirmation.
        _raw_answer = str(filled.get("maid_confirm") or "").strip()
        _options = _MAID_RETRY_OPTIONS.get(_maid_retry.get("kind") or "", _MAID_RETRY_OPTIONS_DEFAULT)
        # Option match FIRST: "Continue without a visitor audience" opens with
        # "continue", which confirmation_intent reads as a yes — checked first it
        # turned that button into a retry.
        _resolved = resolve_option(_raw_answer, list(_options))
        if _resolved not in _options and _is_confirmation(_raw_answer):
            _resolved = _options[0]
        filled.pop("maid_confirm", None)
        if _resolved == "Continue without a visitor audience" or _resolved not in _options:
            bs["maid_retry_pending"] = None
            (bs.get("geo_result") or bs.setdefault("geo_result", {}))["maid_opted_out"] = True
            _mark_op_done(bs, "maid_query")
            return "continuing without a real-visitor audience, at the user's request"
        # Any other resolved option is a retry: clear the flag and drop
        # maid_query so _next_step re-runs it. invalidate_from is not needed
        # here — nothing about the search's INPUTS changed, only the flag
        # that was blocking the re-run.
        bs["maid_retry_pending"] = None
        bs["ops_done"] = sorted(_ops_done(bs) - {"maid_query"})
        return "retrying the audience query"

    maidc_raw = filled.get("maid_confirm")
    maidc_str = str(maidc_raw or "").strip()
    if maidc_str:
        # The editable maid map sends the same JSON delta as poi_confirm
        # ({"confirm":.., "added":[..], "removed":[..]}); a plain text answer
        # falls through to the yes/re-ask parse. Same shape guard as
        # poi_confirm above — a JSON object that isn't actually a delta must
        # not be trusted as a confirmation (see the comment there).
        edits = _parse_json_value(maidc_raw, "{")
        if edits and not _DELTA_KEYS.isdisjoint(edits):
            if edits.get("confirm") is False:
                filled.pop("maid_confirm", None)
                return "audience not confirmed — asking again"
            if (edits.get("removed") or []) or (edits.get("added") or []):
                # Same replayable record the poi_confirm gate keeps — without
                # it a later NL trim re-folds from the untouched superset and
                # resurrects exactly what was just clicked off the map.
                _push_map_delta_undo(bs, "maid_confirm", edits)
                _record_map_removals(bs, list(edits.get("removed") or []))
                _record_map_additions(bs, list(edits.get("added") or []))
                note = await _apply_maid_poi_edits(bs, state, edits)
                # Re-show the recomputed map and re-confirm: drop the gate answer
                # so the maid_confirm ask fires again (the ask re-emits the map).
                filled.pop("maid_confirm", None)
                return note
        elif confirmation_intent(maidc_str) != "yes":
            filled.pop("maid_confirm", None)
            return "audience not confirmed — asking again"

    golive = str(filled.get("go_live_confirm") or "").strip()
    if golive:
        resolved = resolve_option(golive, GO_LIVE_OPTIONS).strip().lower()
        if resolved.startswith("leave it"):
            # The campaign stays exactly as published — built and PAUSED. Marking
            # the op done (rather than leaving the gate unanswered) is what closes
            # the media stage, so the builder finalizes instead of re-asking.
            bs["stay_paused"] = True
            _mark_op_done(bs, "activate")
            return "campaign left paused at the user's request"
    return None


def _merge_regenerated_plan(bs: dict, state: Any, generated: dict) -> dict:
    """The plan to store after ``generate_meta_json``: ``generated``, with the
    user's plan-editor work carried over when this is a REGENERATION after a
    geo / audience edit (``invalidate_from`` parked their plan as
    ``marketing_plan_prev``). ``plan_base`` — what Punk generated last time — is
    what makes "the user changed it" a diff rather than a guess. Locked targeting
    always comes from the fresh build. What was kept, and anything that
    couldn't be, goes to the change ledger so the reply can say so."""
    prev = bs.pop("marketing_plan_prev", None)
    if not (prev and bs.get("plan_base")):
        return generated

    from app.graph.meta_spec.merge import merge_or_fallback
    from app.graph.narrator.beats import record_change

    merged = merge_or_fallback(
        bs["plan_base"], prev, generated, validate=CampaignSpec.model_validate,
    )
    if merged.kept:
        record_change(state, applied={"__plan_merge__": (
            "kept your plan edits: " + "; ".join(merged.kept[:6])
            + (f" (+{len(merged.kept) - 6} more)" if len(merged.kept) > 6 else "")
        )})
    if merged.conflicts:
        record_change(state, deviation=merged.conflicts)
    return merged.spec


def _apply_plan_edits_step(bs: dict, state: Any, ops: dict, writer: Any) -> None:
    """Apply typed changes (budget / dates / placements) to the BUILT plan,
    validated against the real CampaignSpec. A landed change reopens the editor
    so the user sees the plan they just changed; a refused one leaves the plan
    exactly as it was and says why. One ledger line per field either way."""
    from app.graph.builder.plan_edits import apply_plan_edits
    from app.graph.narrator.beats import record_change

    plan = bs.get("marketing_plan")
    if not plan:
        record_change(state, unsupported="there's no built plan to change yet")
        return
    currency = str((bs.get("media_ws") or {}).get("ad_account_currency") or "")
    outcome = apply_plan_edits(plan, ops, currency=currency, validate=CampaignSpec.model_validate)
    for r in outcome.results:
        if r["status"] in ("applied", "no_op"):
            record_change(state, applied={r["field"]: r["detail"]})
        else:
            record_change(state, deviation=f"didn't change {r['field'].replace('_', ' ')} — {r['detail']}")
    if outcome.spec is None:
        return
    from app.graph.builder.edits import push_undo

    push_undo(bs, unit=None, plan=plan)
    bs["marketing_plan"] = outcome.spec
    # Show the changed plan: the editor is the campaign stage's exit gate.
    _reopen_plan_editor(bs, bs.setdefault("filled", {}))
    writer({"type": "thinking", "content": (
        f"Builder plan: plan edits → {[(r['field'], r['status']) for r in outcome.results]}"
    )})


async def _apply_location_ops_edit(bs: dict, state: Any, ops: list[dict], writer: Any) -> None:
    """Run typed per-location changes (circle / centre / pin) against the map
    decisions, invalidate the Places search when any landed, and put ONE truthful
    line per op in the change ledger — including "which one?" when a target was
    ambiguous, so nothing is guessed."""
    from app.graph.builder.edits import GEO_DECISION_KEYS, invalidate_from, push_undo
    from app.graph.builder.executors.geo import apply_location_ops
    from app.graph.narrator.beats import record_change

    ws = dict(bs.get("geo_ws") or {})
    before = {k: copy.deepcopy(ws.get(k)) for k in (*GEO_DECISION_KEYS, "_geocoded_locations")}
    results = await apply_location_ops(ws, ops, writer)
    applied = [r for r in results if r["status"] == "applied"]
    field_of = {"ring": "location_ring", "center": "location_center", "unpin": "map_pins",
                "exclude": "excluded_areas", "unexclude": "excluded_areas"}
    for r in results:
        key = field_of.get(r["kind"], r["kind"])
        if r["status"] in ("applied", "no_op"):
            record_change(state, applied={key: r["detail"]})
        elif r["status"] == "unresolved" and r.get("candidates"):
            # Ask, never guess: the request stays "heard", and the user is told which to pick.
            record_change(state, deviation=f"didn't change anything yet — {r['detail']}")
        else:
            record_change(state, unsupported=r["detail"])
    if applied:
        bs["geo_ws"] = ws
        filled = bs.setdefault("filled", {})
        push_undo(bs, unit="poi_search", filled=filled, geo_before=before)
        invalidate_from(bs, filled, "poi_search")
    writer({"type": "thinking", "content": f"Builder plan: location ops → {[(r['kind'], r['status']) for r in results]}"})


def _record_map_removals(bs: dict, removed: list) -> None:
    """Append the specific POIs a user clicked off the map to the replayable
    selection specs, identity-pinned (`ids`) — a removal names no category, only
    those spots. Shared by the poi_confirm and maid_confirm gates."""
    from app.graph.builder.executors.geo import _norm_poi_name, _poi_key

    ids = []
    for poi in removed or []:
        if not isinstance(poi, dict):
            continue
        key = _poi_key(poi)
        if key is not None:
            ids.append([key[0], key[1], _norm_poi_name(poi.get("name"))])
    if ids:
        bs["_poi_selection_specs"] = [
            *(bs.get("_poi_selection_specs") or []),
            {"op": "drop", "ids": ids},
        ]
        # A removed map pick is gone for good — not merely dropped by a spec.
        gone = {tuple(i) for i in ids}
        bs["_map_added_pois"] = [
            p for p in (bs.get("_map_added_pois") or [])
            if (k := _poi_key(p)) is None or (k[0], k[1], _norm_poi_name(p.get("name"))) not in gone
        ]


def _resolve_visitor_floors(det: dict, instructions: list) -> tuple[list, list[str]]:
    """Turn "keep only the spots that have visitors" (a spec's ``min_visitors``)
    into an identity-pinned drop of the spots that fall short, read from the
    per-spot counts stamped on the audience map. Pinned to those spots, like a
    map click, so later trims and undo replay it exactly. Returns the rewritten
    instructions and any "couldn't apply" notes."""
    from app.graph.builder.executors.geo import _norm_poi_name, _poi_key
    from app.graph.builder.executors.poi_selection import normalize_spec, resolve_drop_predicate

    out: list = []
    notes: list[str] = []
    for raw in instructions:
        spec = normalize_spec(raw)
        floor = spec.get("min_visitors")
        if not floor:
            out.append(raw)
            continue
        if not det.get("maid_extraction_id"):
            notes.append("I can only filter spots by visitors once the audience has been pulled")
            continue
        shown = [p for p in det.get("targetable_pois") or [] if isinstance(p, dict)]
        scope = resolve_drop_predicate(shown, spec["match"]) if spec["match"] else shown
        short = [p for p in scope if (p.get("audience_count") or 0) < floor]
        label = "any visitors" if floor == 1 else f"at least {floor} visitors"
        if not short:
            notes.append(f"every spot already has {label}, so nothing was removed")
        elif len(short) == len(shown):
            notes.append(f"no spot has {label}, so I kept them all")
        else:
            ids = [
                [k[0], k[1], _norm_poi_name(p.get("name"))]
                for p in short if (k := _poi_key(p)) is not None
            ]
            out.append({"op": "drop", "ids": ids})
    return out, notes


def _push_map_delta_undo(bs: dict, gate: str, edits: dict) -> None:
    """Undo point for spots added / removed on the POI or audience map. The
    replayable lists carry the change, so undo restores them and re-folds; the
    gate's own answer is left out of ``filled`` or undo would replay the click."""
    if not (edits.get("added") or edits.get("removed")):
        return
    from app.graph.builder.edits import push_undo

    filled = {k: v for k, v in (bs.get("filled") or {}).items() if k != gate}
    push_undo(bs, unit=None, filled=filled, keys=("_poi_selection_specs", "_map_added_pois"))


def _record_map_additions(bs: dict, added: list) -> None:
    """Remember the spots a user added on the map (``bs["_map_added_pois"]``).

    They were never in the Places search's own results (``_all_pois_cache``), so
    every later fold over that superset (a "top 5 each", an undo) and every
    re-search silently lost them. Re-adding a spot the user earlier removed lifts
    that removal, or the same replayed drop would delete it again."""
    from app.graph.builder.executors.geo import _norm_poi_name, _poi_key

    picks = [
        {**a, "parent_poi_type": a.get("parent_poi_type") or "map_pick"}
        for a in added or [] if isinstance(a, dict) and _poi_key(a) is not None
    ]
    if not picks:
        return
    have = {_poi_key(p) for p in bs.get("_map_added_pois") or []}
    bs["_map_added_pois"] = [
        *(bs.get("_map_added_pois") or []), *(dict(p) for p in picks if _poi_key(p) not in have),
    ]
    idents = {(k[0], k[1], _norm_poi_name(p.get("name"))) for p in picks if (k := _poi_key(p))}
    specs = []
    for spec in bs.get("_poi_selection_specs") or []:
        if isinstance(spec, dict) and spec.get("op") == "drop" and spec.get("ids"):
            ids = [i for i in spec["ids"] if tuple(i) not in idents]
            if not ids:
                continue
            spec = {**spec, "ids": ids}
        specs.append(spec)
    bs["_poi_selection_specs"] = specs


def _poi_superset(bs: dict, det: Optional[dict]) -> list:
    """What a POI trim folds over: everything the Places search found, plus the
    spots the user added by hand."""
    from app.graph.builder.executors.geo import _poi_key

    base = list((bs.get("geo_ws") or {}).get("_all_pois_cache") or (det or {}).get("targetable_pois") or [])
    have = {_poi_key(p) for p in base}
    return base + [dict(p) for p in bs.get("_map_added_pois") or [] if _poi_key(p) not in have]


def _merge_map_added(bs: dict, det: Any) -> None:
    """Put the user's map-added spots into a FRESH search result."""
    if not isinstance(det, dict) or not bs.get("_map_added_pois"):
        return
    merged = _poi_superset({"geo_ws": {}, "_map_added_pois": bs["_map_added_pois"]}, det)
    if len(merged) != len(det.get("targetable_pois") or []):
        det["targetable_pois"] = merged
        det["pois_found"] = len(merged)


def _normalize_publish_mode(raw: str) -> str:
    """One of the three PUBLISH_MODE_OPTIONS → its routing token, or "".

    Matched on the label before the em-dash so the description copy can change
    freely, and via ``resolve_option`` first so a numeric pick ("2") or a client
    that rewrites " — " to " - " still lands on the right branch.
    """
    resolved = resolve_option(str(raw or ""), PUBLISH_MODE_OPTIONS).strip().lower()
    for prefix, mode in (
        ("export audience to meta", "self"),
        ("set up campaign manually", "guide"),
        ("let punk setup", "express"),
        # Pre-rename labels — a session checkpointed in Redis before this
        # deploy is still paused on the old option list and answers with its
        # text, so both generations must keep resolving.
        ("publish it myself", "self"),
        ("guide me", "guide"),
        ("do it for me", "express"),
    ):
        if resolved.startswith(prefix):
            return mode
    return ""


async def _record_go_live_consent(
    *, user_id: Any, campaign_id: Any, campaign_ids: Any, ad_account_id: Any,
    go_live_answer: Any,
) -> None:
    """Durable record of the go_live_confirm answer that just activated a
    campaign. The gate itself is real — this only ever runs after the user
    picked "set it live", never by default — but until now that answer was
    only a checkpoint field, not a durable record. The submission copy's
    claim that a launch "is recorded" was not true until this existed.

    Best-effort: a logging failure must never undo a successful activation
    the user explicitly asked for, so this never raises.
    """
    try:
        from app.db.database import AsyncSessionLocal
        from app.modules.auditLogs.repository import AuditLogRepository
        from app.modules.auditLogs.schemas import AuditLogRequest

        async with AsyncSessionLocal() as db:
            row = await AuditLogRepository().create_audit_logs(
                db,
                AuditLogRequest(
                    user_id=str(user_id or ""),
                    action="meta.go_live_confirmed",
                    resource_type="campaign",
                    resource_id=str(campaign_id or ""),
                    new_data={
                        "go_live_answer": go_live_answer,
                        "campaign_ids": campaign_ids,
                        "ad_account_id": ad_account_id,
                    },
                ),
            )
        if row is None:
            logger.warning(
                "builder_node: go-live consent audit write returned no row "
                "(user=%s, campaign=%s)", user_id, campaign_id,
            )
    except Exception as exc:  # noqa: BLE001 — must never undo a real activation
        logger.warning("builder_node: go-live consent audit write failed — %s", exc)


async def _apply_maid_poi_edits(
    bs: dict, state: AgentState, edits: dict, *, narrate: bool = True,
) -> str:
    """Apply an editable maid-map delta: remove (or add) POIs on the persisted
    extraction, recompute per-POI counts + the deduped total, drop observations
    orphaned by a removal, and flag the maid_confirm ask to re-emit the map.

    Reuses ``apply_poi_edits`` (the geo delta interpreter) and
    ``attribute_audience`` so removal and counting stay consistent with the
    initial extraction.

    ``narrate=False`` (the geo-side POI-trim delegation in
    ``_apply_geo_poi_selection_edit`` below) skips the ``add_beat`` here — that
    caller adds its own single beat for the turn, already carrying the
    refreshed audience count; a second beat from this function would just
    compete with it for the same pause.
    """
    from app.graph.builder.executors.geo import apply_poi_edits, dedup_key, _poi_key
    from app.graph.builder.executors.maid import query_pois_audience
    from app.graph.maid_query import attribute_audience, compute_visit_stats
    from app.services.maid_store import (
        AudienceFilterUnevaluable,
        apply_audience_filter,
        fetch_maid_extraction,
        update_maid_extraction,
    )

    geo = bs.get("geo_result") or {}
    extraction_id = geo.get("maid_extraction_id")
    if not extraction_id:
        # No beat is added here — a caller with narrate=False (see docstring)
        # already owns this turn's single beat and would collide with one
        # added here. record_change still fires: it can only ever pop a
        # `heard` entry that was actually placed (the poi_selection edit-lane
        # ack), so a direct map-delta call with none pending is a no-op push.
        # Without this the edit-lane ack survives to `heard_not_applied` and
        # the composer tells the user Punk is "still working on" a trim that
        # will never land.
        record_change(state, unsupported="I haven't extracted an audience yet — let's finish that step first.")
        return "maid edit skipped — no extraction on record"
    extraction = await fetch_maid_extraction(str(extraction_id))
    # A purged extraction (published, or swept as abandoned) has an empty
    # observations superset — recomputing against it would silently wipe every
    # POI's audience rather than fail loudly. Treated as "not found": the
    # editable superset genuinely isn't there any more.
    if not extraction or extraction.get("purged_at"):
        record_change(state, unsupported="I couldn't find the saved audience for this build — let's re-run that step.")
        return "maid edit skipped — extraction not found"

    # Drop/add POIs by coord key against the persisted POI list. Dedup the loaded
    # list by (coord, name) first: extractions persisted before the geo-discovery
    # dedup fix may hold multiple rows for one place at one lat/lng, which would
    # make a single map removal cascade into N removals (each shares a
    # `_poi_key`). Keep the first occurrence. Name is part of the key for the same
    # reason as the geo-discovery pass — distinct events at a shared "TBD" city
    # centroid are different places, not duplicates.
    _seen_keys: set = set()
    _persisted_pois: list[dict] = []
    for _p in (extraction["pois"] or []):
        _ck = dedup_key(_p)
        if _ck is not None and _ck in _seen_keys:
            continue
        if _ck is not None:
            _seen_keys.add(_ck)
        _persisted_pois.append(_p)
    det = {
        "targetable_pois": _persisted_pois,
        "pois_found": len(_persisted_pois),
        "poi_radius_km": geo.get("poi_radius_km"),
    }
    added_names, removed_names = apply_poi_edits(det, edits)
    # Every POI must carry the ring radius it is bought at: attribute_audience
    # matches rows to POIs by poi_key, and that key includes the radius. A POI
    # added on the map arrives without one.
    _radius_km = geo.get("poi_radius_km")
    remaining_pois = [
        p if p.get("radius_km") or not _radius_km else {**p, "radius_km": _radius_km}
        for p in det["targetable_pois"]
    ]

    observations = list(extraction["observations"] or [])
    # A newly ADDED POI sits where the warehouse was never queried — pull its
    # audience now so it contributes real visitors instead of showing 0. The
    # ones apply_poi_edits appended are those whose coord key is not in the
    # prior POI set.
    prior_keys = {k for k in (_poi_key(p) for p in (extraction["pois"] or [])) if k is not None}
    newly_added = [p for p in remaining_pois if _poi_key(p) not in prior_keys]
    add_failure_kind: str | None = None
    if newly_added:
        add_obs, add_failure_kind = await query_pois_audience(geo, newly_added, writer=get_writer())
        observations.extend(add_obs)

    # Recompute audience against surviving POIs. Observations that now fall in
    # NO POI are dropped — the audience "goes with" the removed spot. Two
    # passes, same shape run_maid_query uses (attribute_audience's own
    # docstring, point 2): an UNSTAMPED pass over the raw superset for the
    # persisted maid list/total, then a STAMPED pass below over whatever's
    # actually shown (the filtered subset when a filter is active, else this
    # same superset) — so a POI's on-screen audience_count AND visit_stats
    # always match the audience actually displayed, never a stale pre-edit or
    # pre-filter one, and a newly added POI (never stamped before) gets both
    # for the first time.
    new_total, kept_obs = attribute_audience(observations, remaining_pois, stamp_stats=False)
    kept_maids = sorted({r["maid"] for r in kept_obs if r.get("maid") is not None})

    # A POI edit changes the superset, not the active audience filter — reapply
    # it (if any) so the headline stays filtered instead of silently reverting
    # to the full audience. `new_total`/`kept_maids` above ARE the superset,
    # unaffected by the filter; `shown_rows` (below) is what's actually shown.
    audience_filter_spec = extraction.get("audience_filter")
    filter_dropped: str | None = None
    shown_rows = kept_obs
    if audience_filter_spec:
        try:
            filtered_maids = set(apply_audience_filter(kept_obs, audience_filter_spec, pois=remaining_pois))
            shown_rows = [o for o in kept_obs if o.get("maid") in filtered_maids]
        except AudienceFilterUnevaluable as exc:
            # The edit left the filter unable to judge the remaining spots. Same
            # rule as run_maid_query: never keep a filter nothing can evaluate —
            # publish re-applies it and would fail — so show everyone at the
            # remaining spots and say why.
            filter_dropped = str(exc)
            audience_filter_spec = None
            shown_rows = kept_obs
    # The stamped pass: `filtered_total` is what's headlined, and every
    # surviving/added POI's audience_count + visit_stats now reflect exactly
    # this set — the same set `maid_visit_stats` below is computed over.
    filtered_total, shown_rows = attribute_audience(shown_rows, remaining_pois, stamp_stats=True)

    await update_maid_extraction(
        str(extraction_id),
        maids=kept_maids,
        observations=kept_obs,
        pois=remaining_pois,
        maid_count=new_total,
        audience_filter=audience_filter_spec,
        filtered_maid_count=filtered_total,
        _clear_filter=filter_dropped is not None,
    )

    # Mirror the recomputed audience forward so the composer grounding + budget
    # framing read the new total (parity with the geo poi-edit re-commit).
    # Same true-superset-vs-filtered split as `_apply_maid_audience_filter_
    # edit` below — `new_total` (above) is the count against the SURVIVING
    # POIs before the audience filter narrows it further; `filtered_total` is
    # what the active filter leaves. Previously both mirrored `filtered_
    # total`, making the two fields structurally identical.
    geo["maid_count"] = new_total
    geo["filtered_maid_count"] = filtered_total
    geo["audience_filter"] = audience_filter_spec
    if filter_dropped:
        geo["maid_filter_unevaluable"] = filter_dropped
    geo["targetable_pois"] = remaining_pois
    # Whole-audience visit_stats recomputed over `shown_rows` — the same set
    # the headline (`filtered_total`) and every per-POI stamp just above are
    # computed over. Previously left at the pre-edit extraction's summary, so
    # a trim that dropped the audience's busiest spot still reported its old
    # repeat-visitor count next to the new, smaller total.
    geo["maid_visit_stats"] = compute_visit_stats(shown_rows)["summary"]
    bs["geo_result"] = geo

    # maid_confirm's repeat_events lambda re-fetches the extraction fresh on
    # every pause (builder_node._maid_confirm_map_event) — no flag needed to
    # ask for a re-emit. What IS needed: the narrator grounding pack mirrors
    # bs["geo_result"] into state["geo_data"] only when this flag is set
    # (builder_plan, "_geo_recommit"), so without it the composer keeps citing
    # the pre-edit audience count on every later turn that doesn't carry its
    # own add_beat fact (a no-op edit, a plain reject) — see grounding.py's
    # _build_maid, which reads state["geo_data"], not bs directly.
    bs["_geo_recommit"] = True

    if narrate:
        add_beat(
            state, "edit",
            {
                "stage": "maid_poi_edit",
                "audience_count": filtered_total,
                "poi_count": len(remaining_pois),
                "removed": len(removed_names),
                "added": len(added_names),
                "filter_dropped": filter_dropped,
                "add_failure_kind": add_failure_kind,
            },
            fallback=(
                f"Updated — your audience is now **{filtered_total:,} verified visitor(s)** "
                f"across **{len(remaining_pois)}** spot(s). Take another look."
                + (f" I had to drop the audience filter: {filter_dropped}." if filter_dropped else "")
                # A newly-added spot that failed to query silently reads as
                # "0 visitors" otherwise — the same false-acknowledgment the
                # heard/applied ledger elsewhere exists to prevent. Say why.
                + (
                    f" I couldn't pull visitors for the newly added spot(s) yet "
                    f"({add_failure_kind.replace('_', ' ')}) — they'll show 0 until "
                    "that succeeds; everything else here is current."
                    if add_failure_kind else ""
                )
            ),
        )
    return (
        f"maid POI edits applied: +{len(added_names)} / -{len(removed_names)} / "
        f"total_audience={filtered_total}"
    )


async def _recompute_audience_filter(
    bs: dict, state: AgentState, specs: list, *, this_turn_unsupported: str | None = None,
    extraction: dict | None = None,
):  # -> Optional[maid_store.AudienceFilterReport] — module imported lazily below,
   # `from __future__ import annotations` (top of file) keeps this unevaluated.
    """Resolve + fold `specs` (RAW, unresolved patches) and apply the result
    against the persisted observation superset, updating `bs`/`geo` in place.
    Returns `None` when there is no extraction to recompute against (no
    `maid_extraction_id`, or the row is missing).

    The compute core shared by `_apply_maid_audience_filter_edit` (appends
    ONE new patch, then calls this with the full history) and `undo()`'s
    restore path (calls this with a POPPED history, no new patch) — same
    split as `_apply_geo_poi_selection_edit` vs `apply_specs`. Does NOT push
    an undo snapshot, add a beat, or touch capability_miss — those are only
    correct for a genuine NEW edit, not a restore, so the two callers each
    add their own on top of this shared recompute.

    `specs` are re-resolved against the CURRENT extraction's POIs every call
    (never cached) — a POI edit between two filter edits must not leave a
    stale resolved group id behind, same reasoning `_apply_geo_poi_selection_
    edit` re-folds from the superset instead of a previous result.
    """
    from app.graph.maid_query import attribute_audience, compute_visit_stats
    from app.services import maid_store
    from app.services.maid_store import (
        apply_audience_filter,
        describe_audience_filter,
        fetch_maid_extraction,
        resolve_audience_filter_specs,
        update_maid_extraction,
    )

    geo = _builder_geo(state, bs)
    extraction_id = geo.get("maid_extraction_id")
    if not extraction_id:
        return None
    # A caller that already loaded the row (the edit path, to reconcile its
    # history against it) passes it in: the row carries the whole observation
    # superset, so a second fetch is not free.
    extraction = extraction or await fetch_maid_extraction(str(extraction_id))
    # Same reasoning as _apply_maid_poi_edits: a purged extraction's
    # observations are empty, so recomputing against it would report "0
    # people match" instead of the caller's honest "not found" message.
    if not extraction or extraction.get("purged_at"):
        return None

    pois = extraction["pois"] or []

    # `total_named` vs `total_matched` is how `deviations` below tells the user
    # a named group didn't exist on screen instead of silently narrowing to
    # nothing.
    merged, total_named, total_matched = resolve_audience_filter_specs(specs, pois)
    # What the extraction actually PURCHASED is stamped on its stored filter by
    # run_maid_query, not on the user's patches, so the fold above drops it —
    # and without it every later trend check falls back to guessing from data.
    _bought = (extraction.get("audience_filter") or {}).get("_history_days_bought")
    if _bought:
        merged["_history_days_bought"] = _bought

    before_count = int(geo.get("filtered_maid_count") or geo.get("maid_count") or 0)
    observations = extraction["observations"] or []
    try:
        filtered_maids = set(apply_audience_filter(observations, merged, pois=pois))
    except maid_store.AudienceFilterUnevaluable as exc:
        # Refuse the edit instead of persisting a filter nothing can evaluate —
        # a stored one would fail again at publish. Nothing is written, so the
        # rejected patch does not enter `_audience_filter_specs` either.
        current = extraction.get("audience_filter") or {}
        return maid_store.AudienceFilterReport(
            filter=current, before_count=before_count, after_count=before_count,
            applied=describe_audience_filter(current) or ["unchanged"],
            deviations=[f"I couldn't apply that: {exc}"],
            unsupported=[this_turn_unsupported] if this_turn_unsupported else [],
        )
    filtered_obs = [o for o in observations if o.get("maid") in filtered_maids]
    filtered_total, filtered_obs = attribute_audience(filtered_obs, pois, stamp_stats=True)

    await update_maid_extraction(
        str(extraction_id),
        maids=extraction["maids"],
        observations=observations,   # superset unchanged — only the filter changed
        pois=pois,
        maid_count=extraction["maid_count"],
        audience_filter=merged,
        filtered_maid_count=filtered_total,
    )

    # `maid_count` stays the TRUE superset (`extraction["maid_count"]`,
    # unaffected by a filter edit — `update_maid_extraction` just above
    # already persists it unchanged); `filtered_maid_count` is what THIS
    # filter leaves. These used to both be set to `filtered_total`, which
    # made the two numbers structurally identical — no read of this state
    # could ever answer "how many did the filter cut".
    geo["maid_count"] = extraction["maid_count"]
    geo["filtered_maid_count"] = filtered_total
    geo["audience_filter"] = merged
    geo["targetable_pois"] = pois
    geo["maid_visit_stats"] = compute_visit_stats(filtered_obs)["summary"]
    bs["geo_result"] = geo
    bs["_audience_filter_specs"] = list(specs)

    # See _apply_maid_poi_edits's identical line for why this is here — the
    # narrator grounding pack (state["geo_data"]) is a mirror of bs["geo_result"]
    # that only builder_plan refreshes, and only when this flag is set.
    # Covers both callers: _apply_maid_audience_filter_edit and
    # interject_tools.undo()'s audience-filter restore.
    bs["_geo_recommit"] = True

    deviations: list[str] = []
    if total_named and total_matched < total_named:
        _miss = total_named - total_matched
        deviations.append(
            f"{_miss} named group{'s' if _miss != 1 else ''} didn't match "
            "any category on screen — left out of that filter"
        )
    if filtered_total == 0 and before_count > 0:
        deviations.append("this filter matches nobody currently on the map")

    return maid_store.AudienceFilterReport(
        filter=merged, before_count=before_count, after_count=filtered_total,
        applied=describe_audience_filter(merged) or ["cleared — showing everyone found"],
        deviations=deviations,
        unsupported=[this_turn_unsupported] if this_turn_unsupported else [],
    )


async def _apply_maid_audience_filter_edit(
    bs: dict, state: AgentState, patch: dict, *, narrate: bool = True,
) -> str:
    """Apply a mid-turn audience-layering edit ("now only weekends", "just
    the ones who go 3+ times") against the ALREADY-PERSISTED observation
    superset — no warehouse re-query, no maid-stage rollback. Same recompute
    shape as ``_apply_maid_poi_edits`` but for a filter change rather than a
    POI delta, and now the SAME safety rails ``_apply_geo_poi_selection_edit``
    has: an ordered, replayable patch history instead of one shallow-merged
    dict, a structured report instead of a bare string, an undo snapshot, and
    an ``unsupported`` clause that reaches capability_miss instead of vanishing.

    Every accepted patch is appended to ``bs["_audience_filter_specs"]`` RAW
    (unresolved) and the WHOLE list is re-resolved + re-folded
    (``maid_store.fold_audience_filter_specs``) against the CURRENT extraction
    every call — never just this call's patch merged onto the previous
    result. Two things this buys, both free: "3+ visits" then "actually just
    1+" replays as the full history from empty and correctly ends at
    ``min_visits: 1`` (undo() can pop the last entry and get the SAME
    correct state back, not a stale merge); and group labels ("gym") always
    resolve against whichever POIs are on screen NOW, so a POI edit between
    two filter edits doesn't leave a stale resolved id behind.

    ``narrate=False`` mirrors ``_apply_geo_poi_selection_edit``'s handoff
    path — no ``add_beat``, the human-facing sentence returned directly.
    """
    from app.services import maid_store

    prior_specs: list = list(bs.get("_audience_filter_specs") or [])
    extraction = None
    _extraction_id = _builder_geo(state, bs).get("maid_extraction_id")
    if _extraction_id:
        extraction = await maid_store.fetch_maid_extraction(str(_extraction_id))
        if extraction and not extraction.get("purged_at"):
            # The history only records EDITS. A filter stated in the user's
            # first message is applied at extraction and never enters it, so
            # folding `[this_patch]` from empty used to erase that original
            # filter on the very first edit (and on every undo back past it).
            # Make sure the history reproduces the audience's real filter
            # BEFORE appending to it — see `reconcile_audience_history`.
            prior_specs = maid_store.reconcile_audience_history(
                prior_specs, extraction.get("audience_filter"), extraction["pois"] or [],
            )
    specs = prior_specs + [dict(patch)]

    report = await _recompute_audience_filter(
        bs, state, specs, this_turn_unsupported=patch.get("unsupported"),
        extraction=extraction,
    )
    if report is None:
        # record_change fires regardless of `narrate` (same reasoning as the
        # `applied` calls below) — without it, the edit-lane ack's `heard`
        # entry (wizard_helpers.py's audience_filter dispatch) survives to
        # `drain_changes` unmatched and the composer tells the user Punk is
        # still narrowing an audience that was never extracted in the first
        # place.
        geo = _builder_geo(state, bs)
        if not geo.get("maid_extraction_id"):
            _msg = "I haven't extracted an audience yet — let's finish that step first."
            record_change(state, unsupported=_msg)
            return _msg if not narrate else "audience filter edit skipped — no extraction on record"
        _msg = "I couldn't find the saved audience for this build — let's re-run that step."
        record_change(state, unsupported=_msg)
        return _msg if not narrate else "audience filter edit skipped — extraction not found"

    # Undo snapshot — pushed HERE too, same reasoning as
    # _apply_geo_poi_selection_edit's own push: a turn that ONLY edits the
    # audience filter never reaches apply_pending_edits's `applied` list (it's
    # a control key, edits.py:apply_pending_edits returns before pushing when
    # `applied` is empty), so without this push undo() could never actually
    # restore an audience-only edit despite its docstring claiming it does.
    from app.graph.builder.edits import push_undo

    push_undo(bs, unit=None, keys=("_audience_filter_specs",), _audience_filter_specs=prior_specs)

    filtered_total = report.after_count
    merged = report.filter
    _fallback = (
        f"Updated — your audience is now **{filtered_total:,} verified visitor(s)** "
        f"matching {', '.join(report.applied)}."
    )
    if report.deviations:
        _fallback += " " + " ".join(report.deviations)
    if report.unsupported:
        _fallback += " Couldn't do this part: " + "; ".join(report.unsupported)

    if narrate:
        add_beat(
            state, "edit",
            {
                "stage": "maid_audience_filter_edit",
                "audience_count": filtered_total,
                "before_count": report.before_count,
                "filter": merged,
                "deviations": report.deviations,
                "unsupported": report.unsupported,
            },
            fallback=_fallback,
        )

    if report.unsupported:
        # Same evidence queue poi_selection feeds — a demographic/shape this
        # data source genuinely doesn't carry, or one the classifier fumbled;
        # either way it's what to look at before guessing the next field.
        from app.graph import capability_miss

        for clause in report.unsupported:
            capability_miss.record(
                "unsupported_selection", step_key="maid_confirm_results",
                field="audience_filter", detail=clause,
            )

    # Truth layer: the `applied` half of the audience_filter ack recorded in
    # wizard_helpers._dispatch_edit_intent — see that site's
    # record_change(heard=...) call for the other half. Fires regardless of
    # `narrate`, same reasoning as the POI path: the handoff route records
    # `applied` with no matching `heard`, and the CHANGES ledger stays
    # accurate either way.
    record_change(
        state,
        applied={"audience_filter": f"audience -> {filtered_total:,} matching {', '.join(report.applied)}"},
        deviation=report.deviations or None,
        unsupported=report.unsupported or None,
    )
    if not narrate:
        return _fallback
    return f"maid audience filter edit applied: filter={merged} total_audience={filtered_total}"


def _reapply_poi_selection_specs(bs: dict, det: dict, writer: Any) -> None:
    """Re-fold ``bs["_poi_selection_specs"]`` over a FRESH geo_discover
    result. Call this right where a new ``det`` lands (the builder's
    geo_discover handler), BEFORE ``pois_found`` is read for the POI-found
    narration — a re-search that silently un-does a curation reads as Punk
    lying about what it just did, the same class of bug
    ``_apply_geo_poi_selection_edit`` exists to avoid on the way in.

    Unlike the old identity-blacklist overlay this REPLACES, a re-fold is not
    purely conservative: a bare-count spec ("top 5 of each category")
    re-evaluated against a fresh, larger superset now picks the top 5 of the
    NEW set, and a `match` drop ("drop everything in Laval") re-suppresses a
    newly-opened Laval gym too. That is the deliberate tradeoff that makes
    widening possible (see poi_selection.apply_specs's docstring) — a
    standing instruction re-applying is more honest than a frozen blacklist.
    The old "only the exact POIs the user saw stay dropped" property is
    preserved exactly where it still belongs: `ids` specs (map-widget clicks)
    are identity-pinned regardless of how large the superset gets.
    """
    specs = bs.get("_poi_selection_specs")
    if not specs or not isinstance(det, dict) or not det.get("targetable_pois"):
        return
    from app.graph.builder.executors.poi_selection import apply_specs

    report = apply_specs(det["targetable_pois"], specs, ref_point=_poi_ref_point(bs))
    if len(report.kept) == len(det["targetable_pois"]):
        return
    det["targetable_pois"] = report.kept
    det["pois_found"] = len(report.kept)
    writer({"type": "thinking", "content": (
        f"geo_discover: re-applied {len(specs)} POI selection spec(s) — "
        f"{len(report.dropped)} suppressed, {len(report.kept)} remain"
    )})


def _poi_preview_map_event(det: Optional[dict], geo_ws: dict, filled: dict) -> Optional[dict]:
    """The ``geo_pois_confirmation`` map, built from whatever ``det``
    (``bs["geo_result"]``) currently holds. Single source of truth for the
    event shape shared by the original emit (``builder_act``'s ``geo_discover``
    branch, right after discovery) and ``_enrich_slot_ask``'s ``poi_confirm``
    branch, which re-emits the SAME shape as a ``repeat_events`` entry so a
    re-ask of this gate never shows a bare prompt with no map underneath it —
    regardless of whether the re-ask was triggered by a plain reject/query, or
    by a ``poi_selection`` NL trim (a tier-1 overlay that never reruns
    geo_discover, so the original emit never fires a second time).

    Every value here is reachable outside ``builder_act``'s closure: ``center``
    / ``event_date_ranges`` are scratch keys already persisted onto
    ``bs["geo_ws"]``; ``search_radius_km`` is just the ``competitor_radius_km``
    slot's raw value, the same source ``extra_inputs`` read it from at act time.

    Returns ``None`` when there is nothing to show yet (no ``det`` / no
    ``targetable_pois``) — the caller skips ``repeat_events`` entirely rather
    than replaying an empty map.
    """
    if not isinstance(det, dict) or not det.get("targetable_pois"):
        return None
    from app.graph.builder.executors.geo import excluded_areas_payload
    from app.graph.maid_query import group_pois_by_category_with_audience

    pois = det.get("targetable_pois") or []
    return {"type": "map_data", "content": {
        "action_type": "maid_split_view",
        "pois": pois,
        "poi_categories": group_pois_by_category_with_audience(pois, []),
        "maid_observations": [],
        "center": geo_ws.get("_det_center") or (det.get("locations") or [{}])[0],
        "maid_count": 0,
        "search_radius_km": filled.get("competitor_radius_km"),
        "lookback_days": det.get("lookback_days"),
        "event_date_ranges": geo_ws.get("_det_event_date_ranges"),
        "editable": True,
        "excluded_areas": excluded_areas_payload(geo_ws),
    }}


async def _maid_confirm_map_event(
    extraction_id: Optional[str], visit_stats: Optional[dict],
    maid_funnel: Optional[dict] = None,
) -> Optional[dict]:
    """The ``maid_confirm_results`` map, re-fetched fresh from the persisted
    extraction. ``maid_confirm``'s sibling to ``_poi_preview_map_event`` above
    — same reason (a ``repeat_events`` entry, so a re-ask of this gate never
    shows a bare prompt with no map underneath it, on ANY re-ask reason: a
    plain reject/query, a no-op edit, a successful POI trim or audience-filter
    narrowing) — but ASYNC: the maid observations blob lives in Postgres, not
    in checkpoint state (see ``executors/maid.py``'s own comment on why), so
    there is no in-memory shortcut the way ``_poi_preview_map_event`` has.

    Returns ``None`` when there's no extraction yet (pre-maid_query — the
    gate won't be showing) or the row can't be found.
    """
    if not extraction_id:
        return None
    from app.services.maid_store import fetch_maid_extraction
    from app.graph.maid_query import build_maid_split_view

    extraction = await fetch_maid_extraction(str(extraction_id))
    # A purged row (publish, or the abandoned-row sweep) still carries a
    # nonzero HISTORICAL maid_count but empty maids/observations — without
    # this guard it looks like a valid re-fetch and renders a map full of
    # zeros/empties under a stale nonzero count. Every sibling
    # fetch_maid_extraction caller already guards this (builder_node.py's
    # own poi-edit paths, maid_store.py, executors/maid.py); this was the
    # one that didn't.
    if not extraction or extraction.get("purged_at"):
        return None
    # `observations`/`maid_count` on the extraction are the UNFILTERED
    # superset — build_maid_split_view applies the active audience_filter (if
    # any) itself, so `maid_count` here is guaranteed to match the initial
    # emit in run_maid_query and the reconnect re-emit in resume_preflight.
    return {"type": "map_data", "content": build_maid_split_view(
        pois=extraction["pois"],
        observations=extraction["observations"] or [],
        audience_filter=extraction.get("audience_filter"),
        center=extraction["center"],
        # Whole-audience summary lives on the checkpoint, not the extraction
        # row; removing a POI does not invalidate it.
        visit_stats=visit_stats,
        search_radius_km=extraction["search_radius_km"],
        lookback_days=extraction["lookback_days"],
        event_date_ranges=extraction["event_date_ranges"],
        # Role-inference disclosure lives on checkpoint state (maid_funnel),
        # not the extraction row — same reason visit_stats above is a param
        # rather than re-derived from `extraction`: it's a whole-audience
        # summary, not a per-POI fact this row alone can answer.
        role_confidence_tier=(maid_funnel or {}).get("role_confidence"),
        role_basis=(maid_funnel or {}).get("role_basis"),
        # `extraction["observations"]` is the full persisted superset (count/
        # visits/poi_ids intact, not the lean {lat,lng,maid} rows a POI-edit
        # recompute works with) — safe and cheap to recompute per-POI
        # visit_stats from here, so every re-ask of this gate shows a
        # per-POI hover stat that matches the currently-active filter instead
        # of whatever was last stamped by a DIFFERENT edit.
        stamp_stats=True,
        editable=True,
    )}


def _poi_ref_point(bs: dict) -> Optional[tuple]:
    """The `(lat, lng)` `apply_specs` measures distance from — the build's own
    market centroid or competitor-anchor centroid, ALREADY computed and
    stored during discovery (`geo._det_center`, the same point the map
    preview centers on). No new geocode, no new state: `_det_center` can be
    `{}` or carry `None` coordinates (e.g. an anchor build with no resolvable
    store address) — those cases return `None` so a distance-dependent spec
    becomes an honest `unsupported` clause instead of measuring from (0, 0).
    """
    center = (bs.get("geo_ws") or {}).get("_det_center") or {}
    lat, lng = center.get("latitude"), center.get("longitude")
    if lat is None or lng is None:
        return None
    return (float(lat), float(lng))


async def _apply_geo_poi_selection_edit(
    bs: dict, state: AgentState, instructions: list[Any], *, narrate: bool = True,
    with_audience: bool = True,
) -> str:
    """Apply one or more POI-curation instructions ("just the top 10", "top 5
    of each category", "drop everything in Laval") against the PERSISTED
    discovery superset — no Places re-search, no invalidate_from (tier-1
    overlay; same shape as _apply_maid_audience_filter_edit above,
    generalized to geo). Each item in `instructions` may be a raw NL string
    (normalized internally) or an already-typed spec dict (the classifier's
    new shape) — `apply_specs` accepts either.

    Every accepted instruction is appended to ``bs["_poi_selection_specs"]``
    and the WHOLE list is re-folded against the superset every call — never
    just this call's new instruction against the previous result. That is
    what makes "top 5" then "actually make it 10" widen instead of only ever
    being able to shrink further (see poi_selection.apply_specs's docstring).

    ``narrate=False`` (the interject_tools.narrow_pois handoff path) skips every
    ``add_beat`` and returns the human-facing sentence directly instead of a
    terse log string — the handoff compose LLM speaks straight from a tool's
    return value, with no later pause to flush a beat into. `record_change`
    still fires either way: a mutation missing from the CHANGES ledger is
    worse than one a beat would have also mentioned. The edit-lane caller
    (below, in `_dispatch_edit_intent`) passes no kwarg and is unaffected.

    ``with_audience=False`` (``builder_plan``, when an audience-filter patch
    is ALSO stashed this turn) drops this beat's own audience number — a
    combined "drop Laval AND only weekends" turn otherwise carries two
    `audience_count`s in the same buffer, the pre-filter total here and the
    filtered total from `_apply_maid_audience_filter_edit` right after, and
    the composer has no way to know which is current.
    """
    from app.graph.builder.executors.poi_selection import apply_specs

    det = bs.get("geo_result")
    if not isinstance(det, dict) or not det.get("targetable_pois"):
        _msg = "I haven't found any spots yet — let's finish the search first."
        if not narrate:
            return _msg
        add_beat(
            state, "reframe",
            {"step": "geo_pois_confirmation", "still_needed": "spots to curate"},
            fallback=_msg,
        )
        return "poi selection edit skipped — no POIs on record"

    superset = _poi_superset(bs, det)
    prior_specs: list = list(bs.get("_poi_selection_specs") or [])
    instructions, _visitor_notes = _resolve_visitor_floors(det, list(instructions))
    specs = prior_specs + instructions

    report = apply_specs(
        superset, specs, ref_point=_poi_ref_point(bs), unsupported_from=len(prior_specs),
    )
    report.deviations.extend(_visitor_notes)

    if not report.applied and not report.deviations and not report.unsupported:
        _msg = "No change — nothing on the map matched that."
        if not narrate:
            return _msg
        add_beat(
            state, "reframe",
            {"step": "geo_pois_confirmation", "form_error": "nothing matched"},
            fallback=_msg,
        )
        return "poi selection: nothing matched"

    if len(report.kept) == len(det.get("targetable_pois") or []) and not report.unsupported:
        # Every instruction resolved to a genuine no-op against what's
        # currently shown (e.g. "top 20" when only 12 exist). Not silence —
        # say so, the same reasoning as the unmatched-instruction branch
        # above: the ack the user already saw promised something would
        # happen.
        _reason = "; ".join(report.deviations) if report.deviations else "already at that count"
        _msg = f"No change — {_reason}."
        if not narrate:
            return _msg
        add_beat(
            state, "reframe",
            {"step": "geo_pois_confirmation", "form_error": _reason},
            fallback=_msg,
        )
        return "poi selection: " + _reason

    # Undo snapshot — pushed HERE too, not only by apply_pending_edits's own
    # push (edits.py): a turn that ONLY trims POIs (no other field edit) never
    # reaches that function's `applied` list, so without this push undo()'s
    # docstring claim ("reverts a POI trim") was false for the common case.
    from app.graph.builder.edits import push_undo

    push_undo(bs, unit=None, keys=("_poi_selection_specs",), _poi_selection_specs=prior_specs)

    bs["_poi_selection_specs"] = specs
    det["targetable_pois"] = report.kept
    det["pois_found"] = len(report.kept)
    bs["geo_result"] = det
    # Same two things _apply_confirm_semantics's poi_confirm branch does after
    # an edit changes the count: flag the narrator grounding pack to refresh,
    # and record a beat so the next pause states the new total instead of
    # silently carrying the pre-edit count.
    bs["_geo_recommit"] = True
    new_total = len(report.kept)

    # A trim/widen AFTER the audience is already extracted leaves the persisted
    # MAID extraction — and the map/count shown at maid_confirm_results — stale
    # otherwise: this is a geo-owned overlay, it never touches maid state. Reuse
    # _apply_maid_poi_edits (the maid-side delta applier) rather than
    # duplicating its extraction-refetch/re-attribute/persist logic: pass BOTH
    # dropped and kept as the "removed"/"added" halves of the delta — dedup in
    # apply_poi_edits (executors/geo.py) makes re-"adding" an already-present
    # POI a no-op, so this is correct whether the spec narrowed, widened, or
    # both across its history. narrate=False: one beat for the whole turn,
    # added below, carrying the refreshed count — not two competing beats.
    _audience_count: Optional[int] = None
    if det.get("maid_extraction_id"):
        await _apply_maid_poi_edits(
            bs, state, {"removed": report.dropped, "added": report.kept}, narrate=False,
        )
        _audience_count = (bs.get("geo_result") or {}).get("filtered_maid_count")

    # `report.applied` (poi_selection.py) already decided whether this trim
    # actually ranked by rating (only true when a surviving POI has reviews)
    # — reuse that same signal here so the LLM-composed and deterministic-
    # fallback messages never disagree about what happened.
    _ranked_by_rating = any("ranked by rating" in a for a in report.applied)
    _fallback = (
        (
            f"Kept the **{new_total}** best-rated spot(s), still on the map above."
            if _ranked_by_rating else
            f"Trimmed it down — you're now targeting **{new_total}** spot(s), "
            "still on the map above."
        )
    )
    _breakdown = {
        gid.split(":", 1)[-1]: n for gid, n in report.after_by_group.items() if n
    }
    if len(_breakdown) > 1:
        _fallback = _fallback.rstrip(".") + " (" + ", ".join(
            f"{n} {label}" for label, n in _breakdown.items()
        ) + ")."
    _named_kept_total = sum(report.protected_kept.values())
    if _named_kept_total:
        # Speak the named-arm bypass out loud — both in `facts` (for the
        # composer) and in the deterministic fallback (so it survives an LLM
        # outage), since this is exactly the number that otherwise reads as
        # an unexplained +N in the final count.
        _fallback += (
            f" I also kept {_named_kept_total} spot(s) you named specifically "
            "— a count only trims the ones I guessed."
        )
    if with_audience and _audience_count is not None:
        # The audience was already extracted before this trim — state the
        # REFRESHED number, not the poi_count. Without this the fallback (and
        # the composer, fed the same fact below) has nothing but the pre-edit
        # count still sitting in narrator grounding to talk about. Suppressed
        # when an audience-filter patch is landing right after this beat (see
        # `with_audience`'s docstring above) — that beat states the number.
        _fallback += f" That's **{_audience_count:,}** real visitor(s) now."
    if report.deviations:
        _fallback += " " + " ".join(report.deviations)
    if report.unsupported:
        _fallback += " Couldn't do this part: " + "; ".join(report.unsupported)
    if narrate:
        add_beat(
            state, "edit",
            {
                "stage": "geo_poi_curation",
                "poi_count": new_total,
                # Per category — `poi_count` is the TOTAL across them, and a
                # narrator handed only that called 18 spots "18 dog parks".
                "breakdown": _breakdown,
                "named_kept": _named_kept_total,
                "audience_count": _audience_count if with_audience else None,
                "deviations": report.deviations,
                "unsupported": report.unsupported,
            },
            fallback=_fallback,
        )
    # Truth layer: this is the `applied` half of the poi_selection ack
    # recorded in wizard_helpers._dispatch_edit_intent — see that site's
    # `record_change(heard=...)` call for the other half. Fires regardless of
    # `narrate`: the handoff path records `applied` with no matching `heard`
    # (there's no _dispatch_edit_intent on that route) — intentional, the
    # CHANGES ledger stays accurate either way.
    record_change(
        state,
        applied={"poi_selection": f"spots -> {new_total} kept ({'; '.join(report.applied)})"},
        deviation=report.deviations or None,
        unsupported=report.unsupported or None,
    )
    if report.unsupported:
        # The queue of selection clauses the grammar genuinely cannot express
        # yet ("at least 2 in each", "cut it in half", "5 per city") — see
        # capability_miss.py's module docstring. This is the emit site that
        # actually pays: it's evidence for what to add next, not a guess.
        from app.graph import capability_miss

        for clause in report.unsupported:
            capability_miss.record(
                "unsupported_selection", step_key="geo_pois_confirmation",
                field="poi_selection", detail=clause,
            )
    if not narrate:
        return _fallback
    return "poi selection: " + "; ".join(report.applied or report.deviations)


def coerce_action(action: PlannerAction, bs: dict, state: AgentState) -> tuple[dict, Optional[str]]:
    """Enforce the stage-order/sequence invariants in code; never trust the
    prompt.

    Returns (action_dict, coercion_note). A planner proposal that jumps a
    stage, asks for an unknown/inapplicable/premature slot, repeats a finished
    op, or declares done early is replaced with the deterministic next step
    from ``_next_step``.
    """
    stage = _current_stage(bs, state)
    filled = bs.get("filled") or {}

    def _fallback(note: str) -> tuple[dict, str]:
        return _next_step(bs, stage) or {"kind": "done"}, note

    if stage == "done":
        return {"kind": "done"}, None if action.kind == "done" else "coerced: pipeline complete"

    if action.kind == "fail":
        # A deterministic next step is ALWAYS available whenever stage != "done"
        # (that's what _next_step guarantees), so kind="fail" from the LLM is
        # never load-bearing — it is only ever the model misreading its own
        # prompt. The concrete case this coerces: a chained interrupt inside
        # geo/store-anchor resolution pauses mid-act (_GeoStepPaused) and
        # re-dispatches the SAME operation next tick — two or three identical
        # "act: geo_discover" proposals in a row with nothing in OPERATIONS
        # DONE reads, to the planner, exactly like an op that failed twice
        # (prompt rule 6), and it bails with a false "something broke"
        # apology on a pipeline that is working as designed. Only honor a
        # fail when the action log actually shows repeated ERRORS on the same
        # step — the genuine escape hatch for a truly stuck build.
        if _has_repeated_action_error(bs):
            return {"kind": "fail", "reason": action.reason or "planner gave up"}, None
        return _fallback("coerced: planner gave up but a deterministic next step exists")

    if action.kind == "done":
        return _fallback("coerced: planner said done but pipeline incomplete")

    # A pending pre-slot act (e.g. website enrichment) preempts every ask/act in
    # the stage — it feeds the conditional slots that follow. The planner cannot
    # name pre-acts (not in its Literal), so any proposal falls back to the
    # deterministic enrich step.
    pre_op = _pre_act_pending(bs, stage, filled)
    if pre_op:
        return _fallback(f"coerced: {pre_op!r} pre-act pending")

    if action.kind == "ask":
        slot = SLOTS.get(action.slot or "")
        if slot is None or slot.stage != stage or not slot_applies(slot, filled):
            return _fallback(f"coerced: ask for invalid/out-of-stage slot {action.slot!r}")
        if slot.name in GATE_SLOTS and _GATE_PREREQ_OP[slot.name] not in _ops_done(bs):
            return _fallback(f"coerced: gate slot {slot.name!r} asked before its operation ran")
        # Non-gate optional slots (only `offer`) are auto-defaulted, never asked —
        # a volunteered value is still captured via extraction/prefill. Coerce any
        # planner attempt to ask one back to the deterministic next step.
        if not slot.required and slot.name not in GATE_SLOTS:
            return _fallback(f"coerced: optional slot {slot.name!r} is auto-defaulted, never asked")
        # Required slots are collected in the canonical SLOTS order — the
        # planner cannot reorder them (the flow the user designed is strict:
        # scope → business desc → mode → mode-inputs). An out-of-order required ask is
        # rewritten to the next required slot.
        missing = missing_required_slots(stage, filled)
        if missing and slot.name != missing[0].name and slot.required:
            return _fallback(
                f"coerced: required slot {slot.name!r} asked out of order — next is {missing[0].name!r}"
            )
        return {"kind": "ask", "slot": slot.name}, None

    # kind == "act"
    operation = action.operation or ""
    op_stage = _OPERATION_STAGE.get(operation)
    if op_stage != stage:
        return _fallback(f"coerced: act {action.operation!r} out of stage order (current={stage})")
    if missing_required_slots(stage, filled):
        return _fallback(f"coerced: act {action.operation!r} before required slots filled")
    done = _ops_done(bs)
    if operation in done:
        return _fallback(f"coerced: act {action.operation!r} already done")
    stage_ops = _stage_acts(stage, filled)
    if operation not in stage_ops:
        return _fallback(f"coerced: act {action.operation!r} does not apply to this publish mode")
    if any(prev not in done for prev in stage_ops[: stage_ops.index(operation)]):
        return _fallback(f"coerced: act {action.operation!r} before earlier {stage} operations")
    gate = _OP_GATE.get(operation)
    if _gate_pending(gate, filled):
        return _fallback(f"coerced: act {action.operation!r} before {gate} confirmation")
    return {"kind": "act", "operation": action.operation}, None


# ── user_info bridging ─────────────────────────────────────────────────────────

def _slot_user_info_patch(slot: Slot, value: str) -> dict:
    """Mirror a freshly-asked slot value into user_info keys so the LLM cores
    (brief / Meta JSON / publish) see what the user just said. List-typed
    user_info values are never stomped with raw strings (shallow-merge
    reducer would lose structure other nodes rely on)."""
    if not slot.prefill_key or slot.prefill_key == "location":
        return {}
    return {slot.prefill_key: value}


def _ui_view(state: AgentState, bs: dict) -> dict:
    """user_info overlaid with current slot values (fresher than extraction)."""
    ui = dict(state.get("user_info") or {})
    filled = bs.get("filled") or {}
    for name, value in filled.items():
        slot = SLOTS.get(name)
        if slot is None or not value:
            continue
        for k, v in _slot_user_info_patch(slot, str(value)).items():
            cur = ui.get(k)
            if cur is None or isinstance(cur, str):
                ui[k] = v
    return ui


def _builder_geo(state: AgentState, bs: dict) -> dict:
    return dict(bs.get("geo_result") or state.get("geo_data") or {})


# Admin-area / country tokens that must NOT default to granular_local. Covers US
# states, CA/AU provinces & territories, and common country names/aliases. Not
# exhaustive internationally — an uncommon name slips through and geocodes as
# scope_too_large (same degradation as typing a country into a city field).
_ADMIN_OR_COUNTRY_TOKENS: frozenset[str] = frozenset({
    # US states
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota", "tennessee",
    "texas", "utah", "vermont", "virginia", "washington", "west virginia",
    "wisconsin", "wyoming",
    # CA provinces / territories
    "alberta", "british columbia", "manitoba", "new brunswick",
    "newfoundland and labrador", "nova scotia", "ontario", "prince edward island",
    "quebec", "saskatchewan", "northwest territories", "nunavut", "yukon",
    # AU states / territories
    "new south wales", "queensland", "victoria", "tasmania",
    "western australia", "south australia", "australian capital territory",
    "northern territory",
    # Countries / aliases
    "usa", "us", "u.s.", "u.s.a.", "united states", "united states of america",
    "america", "canada", "uk", "u.k.", "united kingdom", "england", "scotland",
    "wales", "britain", "great britain", "australia", "india", "germany",
    "france", "spain", "italy", "mexico", "brazil", "japan", "china",
})


def _looks_like_admin_or_country(text: str) -> bool:
    """True when ``text`` names a state / province / territory / country rather
    than a specific city — those must not be defaulted to granular_local scope."""
    t = str(text or "").strip().lower()
    if not t:
        return False
    # Match the full string or its last comma-token ("Austin, Texas" → "texas").
    tail = t.split(",")[-1].strip()
    return t in _ADMIN_OR_COUNTRY_TOKENS or tail in _ADMIN_OR_COUNTRY_TOKENS


def _backfill_location_scope(filled: dict, user_info: dict) -> None:
    """Deterministic bridge for the common case the entry extractor drops: a
    named location present but ``geo_scope`` (→ location_scope slot) missing, so
    the planner asks the scope question the user already answered by naming a
    city. Default granular_local, UNLESS a location token looks like a
    state/country (the extractor is reliable for those broad inputs). Mutates
    ``filled`` in place; idempotent."""
    if str(filled.get("location_scope") or "").strip():
        return
    loc = user_info.get("location")
    candidates = loc if isinstance(loc, list) else ([loc] if loc else [])
    tokens = [str(c) for c in candidates if c and str(c).strip()]
    if not tokens:
        return
    if any(_looks_like_admin_or_country(t) for t in tokens):
        return
    filled["location_scope"] = "granular_local"


def _reconcile_geo_scope(filled: dict, user_info: dict) -> None:
    """Deterministic guard: a 'radius' location scope is contradictory with an
    own-store-anchor subtype (store_set / competitor_nearby). Those subtypes
    geocode a text ADDRESS (geo_collect_stores / geo_collect_store_anchor) and
    never need a manual map pin — but 'radius' forces the required,
    un-prefillable `radius_pin` slot, producing a map-pin interrupt that
    discards the named location. The extractor conflates the two (the word
    'around' is a cue for both), so when both land, demote the radius scope to
    the named-location path. Mutates `filled` in place; idempotent."""
    scope = str(filled.get("location_scope", "")).strip().lower()
    det_subs = {
        s.strip() for s in str(filled.get("det_type", "")).lower().split(",")
        if s.strip()
    }
    if scope != "radius" or not (det_subs & {"store_set", "competitor_nearby"}):
        return
    if user_info.get("location"):
        filled["location_scope"] = "granular_local"
    else:
        filled.pop("location_scope", None)


# ── Sub-nodes ──────────────────────────────────────────────────────────────────

async def builder_plan(state: AgentState) -> dict:
    """ONE Flash temp-0 structured call deciding the next action. No interrupts."""
    writer = get_writer()
    bs = _bs(state)
    bs.setdefault("filled", {})
    bs.setdefault("stages_complete", [])

    # Pin the interrupt contract for this build (see settings.BUILDER_SINGLE_
    # INTERRUPT). Safe here: builder_plan only runs between tasks, never while an
    # interrupt is paused mid-task, so a build can't switch contracts mid-reply.
    if "_single_interrupt" not in bs:
        bs["_single_interrupt"] = settings.BUILDER_SINGLE_INTERRUPT
    # Set by builder_ask / builder_act when the last task ended on a re-ask or a
    # pause; consumed below to skip the planner LLM. Popped here so an early
    # return can't leave it armed for an unrelated later turn.
    _reask_tick = bool(bs.pop("_reask_tick", False))

    # Seed slots from user_info prefill once, before the first plan call.
    if not bs.get("_prefill_seeded"):
        user_info = state.get("user_info") or {}
        for slot in SLOTS.values():
            # confirm_prefill slots (poi_radius_m, lookback_days, radius_km,
            # competitor_radius_km) size a paid audience — an extraction
            # guess must not silently stand in for a user answer. The value
            # stays in user_info and still reaches the widget as its starting
            # position via prefill_for at ask time (_enrich_slot_ask /
            # builder_ask), it just never marks the slot as filled.
            if slot.confirm_prefill:
                continue
            val = prefill_for(slot, user_info)
            if val is not None and not bs["filled"].get(slot.name):
                bs["filled"][slot.name] = val
        bs["_prefill_seeded"] = True

    # Deterministic guard: 'radius' scope + own-store subtype is contradictory —
    # demote radius so the store-address path runs, not the map-pin interrupt.
    # Runs every plan (not just first seed) to also catch det_type set mid-flow.
    _reconcile_geo_scope(bs["filled"], state.get("user_info") or {})

    # Deterministic bridge: named location present but geo_scope dropped by the
    # extractor → default granular_local so we don't re-ask the scope question.
    _backfill_location_scope(bs["filled"], state.get("user_info") or {})

    # Commit any edit the resume router accepted during the last interrupt, and
    # roll back whatever it invalidated. ONE apply point for all 8 interrupt
    # sites: builder_plan runs after every ask and act, so producers only have to
    # stash (see edits.stash_edits) and no return path in builder_act needs to
    # know about edits. Runs BEFORE the gate semantics below so a gate answered
    # in the same turn is interpreted against the post-edit slot values.
    # A refused campaign-field edit ("change my budget") asks for the plan editor
    # instead. _dispatch_edit_intent already told the user; this reopens it.
    # Sweep bs AND every executor `ws` into one bucket first. The 7 executor
    # interrupt sites stash onto a `ws`, so reading bs["_pending_edits"] alone
    # missed a control key raised at any of them — the field loop in
    # apply_pending_edits then skipped it as a _CONTROL_KEY and it vanished,
    # after the user had already been told the editor was reopening.
    _pending = collect_pending(bs)
    # Handoff-lane writes queued in single-interrupt mode (interject_tools._queue).
    # Undo runs FIRST: it reverts the edit made before this turn, not one this
    # same turn is about to apply.
    _undo_ui: dict = {}
    if _pending.pop("_undo", None):
        from app.graph.builder.interject_tools import perform_undo

        _undo_note, _undo_ui = await perform_undo(bs, state)
        writer({"type": "thinking", "content": f"Builder plan: undo — {_undo_note}"})
    if _pending.pop("_delegate_rest", None):
        bs["_auto_default_remaining"] = True
    if _pending.pop("_reopen_plan", None):
        _reopen_plan_editor(bs, bs.setdefault("filled", {}))
        writer({"type": "thinking", "content": (
            "Builder plan: edit targeted a plan field — reopening the campaign editor"
        )})
    # A prompt-only campaign field (audience, business description, …) changed after
    # the spec was built. Commit it to user_info and redraft the copy, keeping the
    # user's plan — see edits.refresh_copy for why this is not invalidate_from.
    #
    # refresh_copy itself is deferred until AFTER apply_pending_edits, below: the
    # SAME turn can carry both a redraft-eligible field and an ordinary geo/maid
    # edit ("rename the business AND add Toronto"), and when it does,
    # apply_pending_edits's own invalidate_from("geo") already drops the campaign
    # stage — brief, marketing_plan, generate_brief from ops_done, all of it — as
    # part of the larger rollback. Running refresh_copy first announced "plan
    # kept" a few lines before the rollback beat below announced the opposite:
    # "gets rebuilt from scratch too". Only the user_info patch has to happen
    # eagerly; it merges into `update["user_info"]` regardless of what the
    # rollback below does.
    _redraft = _pending.pop("_redraft", None)
    _redraft_patch: dict = (
        {k: v for k, v in _redraft.items() if v is not None} if _redraft else {}
    )

    # NL POI curation ("just the top 10", "drop everything in Laval") —
    # recomputed straight from the persisted discovery superset, deliberately
    # NOT routed through apply_pending_edits/invalidate_from, which would
    # re-run Places for a change that only ever narrows what it already
    # found. Popped and applied BEFORE the audience-filter patch below (both
    # can land in one reply — "drop the Laval gyms, only weekend visitors"):
    # _recompute_audience_filter always re-resolves group labels against the
    # CURRENT POI set, so running the POI trim first is what makes the filter
    # beat's count the true final one. `with_audience=False` when a filter
    # patch is ALSO stashed this turn suppresses this beat's own (pre-filter)
    # audience number — the filter beat right after states the real one, and
    # narrating two different totals for one turn reads as Punk contradicting
    # itself.
    _audience_filter_patch = _pending.pop("_audience_filter_patch", None)
    _location_ops = _pending.pop("_location_ops", None)
    if _location_ops:
        await _apply_location_ops_edit(bs, state, _location_ops, writer)
    _plan_ops = _pending.pop("_plan_edits", None)
    if _plan_ops:
        _apply_plan_edits_step(bs, state, _plan_ops, writer)
    _poi_selection_edits = _pending.pop("_poi_selection", None)
    if _poi_selection_edits:
        _ps_note = await _apply_geo_poi_selection_edit(
            bs, state, _poi_selection_edits, with_audience=not bool(_audience_filter_patch),
        )
        writer({"type": "thinking", "content": f"Builder plan: {_ps_note}"})

    # Audience-layering edit ("now only weekends", "just the ones who go 3+
    # times") — recomputed straight from the persisted extraction superset;
    # deliberately NOT routed through apply_pending_edits/invalidate_from
    # (that would roll back the whole maid stage and re-query the warehouse
    # for a change that needs neither). See _apply_maid_audience_filter_edit.
    if _audience_filter_patch:
        _af_note = await _apply_maid_audience_filter_edit(bs, state, _audience_filter_patch)
        writer({"type": "thinking", "content": f"Builder plan: {_af_note}"})

    _had_plan = bool(bs.get("marketing_plan"))
    _report = apply_edits(bs, state)
    _ui_patch, _rolled_back, _edit_note = _report.ui_patch, _report.rolled_back, _report.note
    # What each named change ACTUALLY did — the only claims the narrator may make.
    _outcome_facts = [
        {"field": o.field, "status": o.status, "detail": o.detail} for o in _report.outcomes
    ]
    if _edit_note:
        writer({"type": "thinking", "content": f"Builder plan: {_edit_note}"})

    if _redraft_patch:
        if "campaign" in _rolled_back:
            # The rollback beat below already tells the user their plan is being
            # rebuilt from scratch — that subsumes the brief re-run this would
            # have done, so running it too (and re-announcing "plan kept") would
            # contradict the very next beat.
            writer({"type": "thinking", "content": (
                f"Builder plan: redraft on {list(_redraft_patch)} — "
                "campaign stage already rolled back this turn, skipping (subsumed)"
            )})
        else:
            refresh_copy(bs, bs.setdefault("filled", {}))
            writer({"type": "thinking", "content": (
                f"Builder plan: redraft on {list(_redraft_patch)} — "
                "re-running the brief, plan kept"
            )})
    if _rolled_back:
        # The user was told the edit landed; this is where they find out what it
        # costs. Silent re-running of a stage they already approved is the same
        # class of dishonesty as the dropped-edit bug itself.
        # Say what it COSTS, not just what is happening. A geo/maid edit after the
        # plan exists throws away the campaign tree the user may have spent real
        # time editing — copy, media, budgets. Rebuilding silently is the same
        # class of dishonesty as the dropped-edit bug.
        # A plan with a generated base is MERGED on regeneration (meta_spec/
        # merge.py), so the user's edits carry over; only a plan with no base
        # (older builds) is still rebuilt from scratch.
        _keeps_plan = bool(bs.get("marketing_plan_prev"))
        _lost_plan = "campaign" in _rolled_back and bool(_had_plan) and not _keeps_plan
        add_beat(
            state, "edit",
            {
                "stage": "edit_invalidation",
                "rebuilding": _rolled_back,
                "discards_plan": _lost_plan,
                "keeps_plan_edits": _keeps_plan,
                "outcomes": _outcome_facts,
            },
            fallback=(
                "Got it — that changes things upstream, so I'm redoing "
                f"{', '.join(_rolled_back)} with your update."
                + (
                    " Your campaign plan gets rebuilt from scratch too, so any "
                    "wording or media you set in the editor will need another look."
                    if _lost_plan else ""
                )
                + (
                    " Your plan edits carry over to the rebuilt plan."
                    if _keeps_plan and "campaign" in _rolled_back else ""
                )
            ),
        )

    elif _outcome_facts and bs.get("_single_interrupt"):
        # Single-interrupt mode acks AFTER the write, from what happened —
        # _dispatch_edit_intent no longer says "updated" before it's true. (In
        # the legacy loop the ack still comes first, at dispatch.)
        add_beat(
            state, "edit",
            {"stage": "edit_result", "outcomes": _outcome_facts},
            fallback=" ".join(
                o["detail"].rstrip(".") + "." for o in _outcome_facts if o["detail"]
            ) or "Done.",
        )

    # Interpret answered confirmation gates, then refresh stage completion.
    note = await _apply_confirm_semantics(bs, state)
    if note:
        writer({"type": "thinking", "content": f"Builder plan: {note}"})
    _refresh_stage_completion(bs, state)

    iteration = int(bs.get("iteration", 0))
    if iteration >= _MAX_PLAN_ITERATIONS:
        logger.warning("builder_plan: iteration budget exhausted")
        bs["next_action"] = {"kind": "fail", "reason": "iteration budget exhausted"}
        return {"campaign_builder_state": bs, "wizard_failure": "builder_iteration_budget"}
    bs["iteration"] = iteration + 1

    stage = _current_stage(bs, state)
    writer({"type": "thinking", "content": f"Builder plan #{bs['iteration']}: stage={stage}"})

    if stage == "done":
        bs["next_action"] = {"kind": "done"}
        return {"campaign_builder_state": bs}

    filled_view = "\n".join(f"  {k}: {v}" for k, v in (bs["filled"] or {}).items()) or "  (none)"
    log_view = "\n".join(
        f"  {e.get('step')}: {e.get('summary')}" for e in (bs.get("action_log") or [])[-10:]
    ) or "  (none)"
    missing = missing_required_slots(stage, bs["filled"])
    deterministic = _next_step(bs, stage)
    system = (
        BUILDER_PLANNER_SYSTEM_PROMPT
        + f"\n── CURRENT STAGE ──\n{stage}"
        + f"\n── FILLED SLOTS ──\n{filled_view}"
        + f"\n── MISSING REQUIRED SLOTS (current stage) ──\n"
        + ("  " + ", ".join(s.name for s in missing) if missing else "  (none — ready to act)")
        + f"\n── OPERATIONS DONE ──\n  " + (", ".join(sorted(_ops_done(bs))) or "(none)")
        + f"\n── DEFAULT NEXT STEP (follow unless conversation says otherwise) ──\n  {deterministic}"
        + f"\n── RECENT ACTIONS ──\n{log_view}"
    )
    # State the rollback outright rather than leaving the planner to infer it
    # from ops that silently vanished from OPERATIONS DONE.
    if _rolled_back:
        system += (
            "\n── APPLIED THIS TURN ──\n"
            f"  The user changed something upstream. {', '.join(_rolled_back)} "
            "were rolled back on purpose and must be re-run; treat the DEFAULT "
            "NEXT STEP above as correct even though it repeats earlier work."
        )

    # Real conversation only. `record_qa` writes TWO ledger messages per resolved
    # step, so an unfiltered [-6:] window is entirely wizard_step/wizard_answer
    # records after ~3 steps — while the prompt tells the planner to follow the
    # default "unless conversation says otherwise". It was being instructed to
    # deviate on a conversation it could not see. entry_node already filters this
    # way (`is_conversational`); the planner just never did.
    #
    # Filtered unconditionally, not only on recovery turns: a curated view that
    # exists only for the rare path is the same out-of-band instinct that
    # produced the removed `_try_backtrack`, and the rare branch rots.
    _history = [m for m in state["messages"] if is_conversational(m)][-6:]

    # A re-ask / pause tick (the last task ended on a reply that didn't answer
    # its step, or on one answer of a multi-question act) changes nothing the
    # planner could reason about beyond the edits already applied above — the
    # DEFAULT NEXT STEP it is told to follow IS the answer. Skipping the call
    # keeps an edit turn at the same Vertex call count as before the
    # single-interrupt contract (the ~2-concurrent quota is the constraint).
    if _reask_tick and deterministic:
        action, note = deterministic, "re-ask tick — deterministic next step, planner LLM skipped"
    else:
        llm = _make_llm(temperature=0.0)
        structured_llm = llm.with_structured_output(PlannerAction, include_raw=True)
        try:
            proposal, _usage = await tracked_ainvoke(
                structured_llm,
                [SystemMessage(content=system)] + _history,
                node_name="builder_plan",
                writer=writer,
            )
        except Exception as exc:
            logger.error("builder_plan LLM failed — deterministic fallback: %s", exc)
            proposal = PlannerAction(kind="ask", slot="__invalid__")  # coerced below

        action, note = coerce_action(proposal, bs, state)
    if note:
        writer({"type": "thinking", "content": f"Builder plan: {note}"})
    _log(bs, {"step": f"plan#{bs['iteration']}", "summary": f"{action}"})
    bs["next_action"] = action

    update: dict = {"campaign_builder_state": bs}
    # A POI map-edit this turn changed the discovered-spot count. Re-commit the
    # edited geo_result to the shared `geo_data` (shallow-merge reducer) so the
    # narrator grounding pack + downstream reads see the new total — without this
    # the pack stays at the pre-edit count until the next maid_query commit.
    if bs.pop("_geo_recommit", None) and isinstance(bs.get("geo_result"), dict):
        update["geo_data"] = bs["geo_result"]
    # Mirror committed edits into user_info so the LLM cores (brief / Meta JSON)
    # and the narrator's grounding pack see the new values. `filled` is the
    # string-typed slot layer; user_info keeps the richer shape.
    # The redraft value has to LAND in user_info — that is the only input
    # generate_campaign_brief reads, so without this the re-run would redraft from
    # the old audience and nothing would change.
    _merged_ui = {**_undo_ui, **_ui_patch, **_redraft_patch}
    if _merged_ui:
        update["user_info"] = _merged_ui
    if _redraft_patch:
        # Truth layer: the `applied` half of each redraft field's ack
        # (wizard_helpers._dispatch_edit_intent's `heard={block_field: ...}`
        # at the `block == "redraft"` branch) — this merge above is the actual
        # commit point, not `refresh_copy` (which only invalidates
        # `generate_brief`, it never writes the field itself).
        record_change(state, applied={
            f: f"redraft {f}" for f in _redraft_patch
        })
    # A geo/maid rollback leaves `state["geo_data"]` holding POIs and an audience
    # derived from the OLD inputs, and `_builder_geo` falls back to it — so the
    # narrator's grounding pack would keep citing pre-edit counts until the
    # re-commit. `_dict_merge_or_clear` treats an explicit None as a clear (a
    # shallow merge cannot drop keys). Safe: the builder prefers the surviving
    # `bs["geo_result"]` meanwhile, and geo_discover / maid_query re-commit it.
    if {"geo", "maid"} & set(_rolled_back or ()):
        update["geo_data"] = None
    if action["kind"] == "fail":
        update["wizard_failure"] = "builder_planner_failed"
    return update


def _normalize_slot_answer(name: str, raw: str) -> str:
    """Canonicalize a raw interrupt answer before it lands in ``filled``.

    The wizards normalize option answers inside their collection nodes (full
    labels / ordinals / legacy phrasing → canonical keys); ``slot_applies``,
    ``_current_stage`` and the executors all branch on the canonical values,
    so the builder must apply the same mapping. Prefill-seeded values are
    already canonical (entry extraction schema is Literal-typed) and pass
    through these maps unchanged.
    """
    if name == "det_type":
        # Already-canonical value (from the conversational resolver or a canonical
        # prefill, possibly comma-joined multi-angle) → pass through; the prose→key
        # map below only recognizes labels/ordinals, not the keys themselves.
        parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
        if parts and all(p in DET_TYPE_MAP.values() for p in parts):
            return ",".join(parts)
        resolved = resolve_option(raw, GEO_DETERMINISTIC_OPTIONS).lower()
        for key, val in DET_TYPE_MAP.items():
            if key in resolved:
                return val
        return "ai_suggested"
    if name == "location_scope":
        if raw.strip().lower() in LOCATION_TYPE_MAP.values():   # already canonical
            return raw.strip().lower()
        resolved = resolve_option(raw, GEO_LOCATION_TYPE_OPTIONS).lower()
        for key, val in LOCATION_TYPE_MAP.items():
            if key in resolved:
                return val
        # No recognizable scope — leave the slot unfilled so the planner
        # re-asks instead of silently picking a scope for the user.
        return ""
    if name == "radius_km":
        # Same server-side bounds gap as the MAID steppers had — a request
        # can hand this slot any value, bypassing the widget's own min/max.
        # Clamped silently (no user-facing note) to the registry's own
        # stepper range, same as the MAID fix; this is the one place both
        # the direct ask AND a cross-step "change the radius to X" edit
        # write through (apply_pending_edits calls this too).
        return str(_clamp_to_stepper(
            STEP_PROMPTS["geo_collect_radius_km"]["stepper"],
            parse_length(raw, "km", default=10.0),
        ))
    if name == "competitor_radius_km":
        return str(_clamp_to_stepper(
            STEP_PROMPTS["geo_collect_competitor_radius"]["stepper"],
            parse_length(raw, "km", default=5.0),
        ))
    if name == "poi_radius_m":
        # A cross-step edit ("make it 0.5 km around each spot", "300 feet")
        # reaches here as text; the executor later reads only the number, so an
        # unconverted "0.5 km" became a 0.5 m ring. Bare numbers are metres.
        metres = parse_length(raw, "m", default=None)
        if metres is None:
            return raw
        return str(int(round(_clamp_to_stepper(
            STEP_PROMPTS["maid_collect_settings"]["steppers"][0], metres,
        ))))
    return raw


def _parse_json_value(raw: Any, opener: str) -> Any:
    """Parse a JSON object ('{') or array ('[') answer; {}/[] on failure."""
    import json as _json

    empty: Any = {} if opener == "{" else []
    if not isinstance(raw, str) or not raw.strip().startswith(opener):
        return empty
    try:
        return _json.loads(raw)
    except ValueError:
        return empty


class _MaidSettingsExtract(BaseModel):
    """Two maid tuning values pulled from a free-text answer (any language)."""

    poi_radius_m: Optional[int] = Field(
        None, description="Ring radius in METERS. Convert km→m (2 km = 2000). null if not stated."
    )
    lookback_days: Optional[int] = Field(
        None, description="Lookback window in DAYS. Convert weeks→×7, months→×30. null if not stated."
    )


_MAID_EXTRACT_PROMPT = (
    "Extract two ad-audience settings from the user's message, which may be in any "
    "language or phrasing:\n"
    "  • poi_radius_m — how tight a ring to draw around each spot, in METERS.\n"
    "  • lookback_days — how far back to count visits, in DAYS.\n"
    "Normalize units (km→m, weeks→days×7, months→days×30). Return null for any value "
    "the user did not mention. Do not invent values."
)


async def _extract_maid_settings(text: str, writer: Any) -> Optional[_MaidSettingsExtract]:
    """LLM fallback for the combined maid ask when the answer is not JSON — e.g. the
    user typed free text ('radius 200, look back 2 weeks') instead of using the widget.
    Mirrors ``parse_list_input``'s LLM-with-fallback convention. Returns None on failure
    so the caller degrades to the single-slot path."""
    try:
        llm = _make_llm(temperature=0.0).with_structured_output(_MaidSettingsExtract, include_raw=True)
        res, _usage = await tracked_ainvoke(
            llm,
            [SystemMessage(content=_MAID_EXTRACT_PROMPT), HumanMessage(content=text)],
            node_name="builder_ask_maid_extract",
            writer=writer,
        )
        return res
    except Exception as exc:
        logger.warning("builder_ask maid free-text extract failed: %s", exc)
        return None


# Plain-text slots whose answer is a bare value (not an option / list / number),
# so a user who wraps it in a sentence would otherwise store the whole sentence.
# Each maps to a one-line description of the value to pull out. Slots already
# handled by the list parsers, resolve_option, or the maid extractor are
# deliberately NOT here. (business_name / business_desc / offer moved to the
# intake form, which parses its own JSON submission.)
_SLOT_EXTRACTION: dict[str, str] = {
    "competitor_anchor": "a single street address or place name (the user's business)",
}


class _SlotValueExtract(BaseModel):
    """The bare value pulled from a possibly-wrapped free-text slot answer."""

    value: Optional[str] = Field(
        None,
        description="The requested field only, with any conversational wrapping removed. "
        "null if the message contains no usable value.",
    )


async def _extract_slot_value(slot_name: str, raw: str, writer: Any) -> Optional[str]:
    """Strip conversational wrapping from a plain-text slot answer via ONE Flash
    temp-0 call (mirrors ``_extract_maid_settings``). Returns the cleaned value,
    or None on failure/empty so the caller degrades to the raw answer."""
    field_desc = _SLOT_EXTRACTION[slot_name]
    prompt = (
        f"Extract {field_desc} from the user's message, which may be in any language "
        "or phrasing. If the message is already just the value with no extra wording, "
        "return it unchanged. Do not translate, rephrase, or invent — return null only "
        "if the message carries no usable value."
    )
    try:
        llm = _make_llm(temperature=0.0).with_structured_output(_SlotValueExtract, include_raw=True)
        res, _usage = await tracked_ainvoke(
            llm,
            [SystemMessage(content=prompt), HumanMessage(content=raw)],
            node_name="builder_ask_slot_extract",
            writer=writer,
        )
        value = (res.value or "").strip() if res else ""
        return value or None
    except Exception as exc:
        logger.warning("builder_ask slot extract failed (%s): %s", slot_name, exc)
        return None


# ── Conversational answer resolution for option / value steps ───────────────────
# A widget step (objective, det_type, scope) or a structured-value step (date
# range, budget) must accept a TYPED conversational answer, not just an option
# click. Each slot resolves in three tiers: deterministic maps first (0-cost),
# then a constrained LLM canonicalize, then None → the caller RE-ASKS (bounded,
# with an escape to a sane default) instead of silently mis-picking. This
# generalizes the ``location_scope`` re-ask pattern to every collection step.

_MAX_UNRESOLVED = 3   # re-ask up to this many times, then escape to the fallback


def _det_det_type(raw: str) -> Optional[str]:
    resolved = resolve_option(raw, GEO_DETERMINISTIC_OPTIONS).lower()
    for key, val in DET_TYPE_MAP.items():
        if key in resolved:
            return val
    return None


def _det_location_scope(raw: str) -> Optional[str]:
    resolved = resolve_option(raw, GEO_LOCATION_TYPE_OPTIONS).lower()
    for key, val in LOCATION_TYPE_MAP.items():
        if key in resolved:
            return val
    return None


# slot → {deterministic, valid, hint (per-value meaning for the LLM), fallback
# (escape value after _MAX_UNRESOLVED re-asks)}.
_ENUM_SLOTS: dict[str, dict] = {
    "det_type": {
        "deterministic": _det_det_type,
        "valid": ("ai_suggested", "category", "store_set", "competitor_nearby",
                  "competitor_area", "competitor_brand", "named_places", "event_based"),
        "hint": (
            "ai_suggested = let Punk pick the places; category = search a POI category "
            "(e.g. gyms, cafes); store_set = people near the user's OWN store(s); "
            "competitor_nearby = people near the user's competitors, searched around "
            "their OWN business address; competitor_area = the same competitors but "
            "searched across the WHOLE targeting area (no storefront to anchor on); "
            "competitor_brand = "
            "fans of a big brand; named_places = specific named places the user lists; "
            "event_based = people who attend events"
        ),
        "fallback": "ai_suggested",
    },
    "location_scope": {
        "deterministic": _det_location_scope,
        "valid": ("country_groups", "admin_areas", "granular_local", "radius"),
        "hint": (
            "country_groups = whole countries / country groups; admin_areas = states or "
            "provinces; granular_local = a specific city or neighborhood; radius = a map "
            "pin plus a radius ring"
        ),
        "fallback": "granular_local",
    },
}


class _EnumAnswer(BaseModel):
    """The single canonical option an ambiguous free-text answer maps to."""

    value: Optional[str] = Field(
        None,
        description="Exactly one canonical key from the allowed set, verbatim; "
        "null if the message clearly matches none of them.",
    )


async def _canonicalize_enum_answer(slot_name: str, raw: str, writer: Any) -> Optional[str]:
    """Map a conversational answer to one canonical option via ONE Flash temp-0
    call, constrained to the slot's valid values. Returns the canonical value or
    None (→ re-ask). Mirrors ``_extract_slot_value``."""
    spec = _ENUM_SLOTS[slot_name]
    valid = spec["valid"]
    prompt = (
        "The user is answering a multiple-choice step. Map their message to EXACTLY "
        "ONE of these canonical values (reply with the value string verbatim), or null "
        "if none clearly fits.\n"
        f"Allowed values: {', '.join(valid)}.\n"
        f"Meaning: {spec['hint']}.\n"
        "Do not invent a value; return null when the message is unrelated or unclear."
    )
    try:
        llm = _make_llm(temperature=0.0).with_structured_output(_EnumAnswer, include_raw=True)
        res, _usage = await tracked_ainvoke(
            llm,
            [SystemMessage(content=prompt), HumanMessage(content=raw)],
            node_name=f"builder_ask_enum_{slot_name}",
            writer=writer,
        )
        val = (getattr(res, "value", None) or "").strip() if res else ""
        return val if val in valid else None
    except Exception as exc:
        logger.warning("builder_ask enum canonicalize failed (%s): %s", slot_name, exc)
        return None


async def _resolve_enum_slot(slot_name: str, raw: str, bs: dict, writer: Any) -> Optional[str]:
    """Deterministic maps → cached LLM canonicalize → None. Caches the LLM result
    by raw in ``bs['_slot_extract']`` (shared with ``_extract_slot_value``) so a
    checkpoint replay never re-issues the call."""
    raw_s = (raw or "").strip()
    if not raw_s:
        return None
    det = _ENUM_SLOTS[slot_name]["deterministic"](raw_s)
    if det:
        return det
    if raw_s[:1] in ("{", "["):        # widget JSON payload — never a prose choice
        return None
    cache = dict(bs.get("_slot_extract") or {})
    ckey = f"enum:{slot_name}"
    entry = cache.get(ckey)
    if isinstance(entry, dict) and entry.get("raw") == raw_s:
        return entry.get("value") or None
    val = await _canonicalize_enum_answer(slot_name, raw_s, writer)
    cache[ckey] = {"raw": raw_s, "value": val}
    bs["_slot_extract"] = cache
    return val


# Value-resolver slots (date_range / budget) moved to the intake form, which
# parses its own submission. Kept as an empty map so the resolve branch in
# builder_ask stays a no-op rather than a special case to delete there.
_RESOLVE_VALUE_SLOTS: dict[str, Any] = {}


def _register_unresolved(bs: dict, slot_name: str) -> bool:
    """Bump the unresolved-attempt counter for a slot. Returns True when the
    budget is exhausted (caller should escape to the fallback) instead of
    re-asking again."""
    counts = dict(bs.get("_unresolved") or {})
    counts[slot_name] = counts.get(slot_name, 0) + 1
    bs["_unresolved"] = counts
    return counts[slot_name] >= _MAX_UNRESOLVED


def _clear_unresolved(bs: dict, slot_name: str) -> None:
    counts = dict(bs.get("_unresolved") or {})
    if counts.pop(slot_name, None) is not None:
        bs["_unresolved"] = counts


def _escape_value(slot_name: str, bs: dict, raw: str) -> str:
    """Sane default used once the re-ask budget is exhausted."""
    if slot_name in _ENUM_SLOTS:
        return _ENUM_SLOTS[slot_name]["fallback"]
    return raw


def _reframe_unresolved(state: AgentState, slot_name: str, raw: str, writer: Any) -> None:
    """Emit a narration beat so the re-ask isn't silent (the user sees why the
    same widget re-rendered). Best-effort."""
    try:
        add_beat(
            state, "reframe",
            {"step": slot_name, "asked_for": slot_name, "rejected_reply": str(raw)[:120]},
            fallback=(
                f"I didn't quite catch which option you meant for "
                f"**{slot_name.replace('_', ' ')}** — could you pick one or say it another way?"
            ),
        )
    except Exception as exc:
        logger.debug("reframe_unresolved beat failed (%s): %s", slot_name, exc)


def _reframe_intake_errors(state: AgentState, errors: Any, schema: dict) -> None:
    """Beat explaining why the intake form re-rendered. Best-effort, no-op clean.

    Labels come from the schema we just built, not the raw error keys — the user
    is being asked to fix "Daily budget", not `budget_amount`. ``__root__`` is the
    form-level banner (parse_intake_submission's contract), not a field, so it
    carries its own message instead of a name. No resume guard is needed: an error
    re-render is a fresh ``builder_ask`` execution (the slot stayed unfilled and
    ``next_action`` was cleared), not an interrupt replay.
    """
    if not errors:
        return
    try:
        labels = {
            f["key"]: f.get("label") or f["key"]
            for group in (schema.get("groups") or [])
            for f in (group.get("fields") or [])
            if f.get("key")
        }
        root = str(errors.get("__root__") or "").strip()
        names = [
            labels.get(k, str(k).replace("_", " "))
            for k in errors if k != "__root__"
        ]
        # One flat, quotable string rather than a names list + a problems map.
        # The composer only ever sees `kind` + `facts` (composer.py:167 — `verbatim`
        # is not forwarded), and given three overlapping keys it wrote around all of
        # them and named no field at all. A single concrete fact is what it cites.
        add_beat(
            state, "reframe",
            {"step": "campaign_intake",
             "still_needed": ", ".join(names) or None,
             "form_error": root or None},
            fallback=(
                f"Almost there — **{', '.join(names)}** still needs a look "
                "before I can build the plan."
                if names else (root or "Let's fix a couple of details on the form below.")
            ),
        )
    except Exception as exc:
        logger.debug("reframe_intake_errors beat failed: %s", exc)


def _frame_audience_roles(state: AgentState, bs: dict, adsets: list[dict]) -> None:
    """Beat explaining why the plan runs more than one ad set, said once.

    "Why am I paying for a second audience?" is the first thing a beginner
    asks once the plan editor opens, and neither beat framing that pause today
    answers it — campaign_brief_drafted frames the objective/budget/dates, not
    the audience, and generate_meta_json (which actually builds the ad sets and
    assigns their roles) emits nothing. Fires only when there is something to
    explain: 2+ ad sets carrying 2+ distinct roles (seed / lookalike / broad,
    assigned by meta_spec.builder._audience_role).

    Guarded by bs["audience_role_framed"] rather than a per-item list like
    geo.py's disambiguation guard — this only ever needs to fire once per
    thread, not once per item, and wizard_interrupt already skips the whole
    emit block on a resume replay so no further guard is needed there.

    Best-effort, no-op clean — same contract as _reframe_intake_errors.
    """
    if bs.get("audience_role_framed"):
        return
    try:
        roles: list[str] = []
        seen: set[str] = set()
        role_cents: dict[str, int] = {}
        for a in adsets:
            role = str(a.get("audience_role") or "")
            if role not in AUDIENCE_ROLE_LABELS:
                continue
            if role not in seen:
                seen.add(role)
                roles.append(role)
                role_cents[role] = 0
            cents = a.get("daily_budget") or a.get("lifetime_budget") or 0
            role_cents[role] += int(cents or 0)
        if len(adsets) <= 1 or len(roles) <= 1:
            return

        # Real split off the plan's own ad sets, not the meta_spec.builder
        # 60/40 default — that number is only a fallback for when the brief
        # supplies no adset_budget_breakdown, and can already be wrong for a
        # given plan. A campaign-level (CBO) budget leaves every ad set's own
        # budget unset, so name the roles without a split rather than assert
        # one that isn't true.
        total = sum(role_cents.values())
        parts = [
            f"{AUDIENCE_ROLE_LABELS.get(r, r)} ({round(role_cents[r] / total * 100)}%)"
            if total > 0
            else AUDIENCE_ROLE_LABELS.get(r, r)
            for r in roles
        ]
        why = (
            f"This plan runs {len(adsets)} ad sets — "
            + " and ".join(parts)
            + ". The real-visitor list is highest intent but small; the rest "
            "prospect for people like them so the campaign keeps finding new "
            "customers once that list is used up."
        )
        # One flat, pre-composed string fact — not a role/budget map. Same
        # lesson as _reframe_intake_errors above: several overlapping keys get
        # written around; a single concrete sentence is what gets cited.
        add_beat(
            state, "framing",
            {"step": "campaign_plan_confirm", "why_two_audiences": why},
            fallback=why,
        )
        bs["audience_role_framed"] = True
    except Exception as exc:
        logger.debug("audience_role framing beat failed: %s", exc)


async def _emit_radius_slot_map(
    slot: Slot, bs: dict, state: AgentState, writer: Any,
    prefill_radius_m: int | None = None,
) -> None:
    """Emit the wizard's radius picker map_data before a stepper radius ask
    (builder parity with geo_collect_radius_km / geo_collect_competitor_radius /
    maid_collect_poi_radius). Mutates ``bs`` in place (emit guards + the
    competitor-anchor geocode cache that ``builder_act`` reuses).

    ``prefill_radius_m`` (poi_radius_picker only) draws the ring at an
    already-known radius for display — used by the lookback-only ask, where the
    radius was given earlier and no radius stepper is shown.

    Like the wizards, the guard flags live in scratch and reset across the
    interrupt pause, so a resume re-shows the map — acceptable parity.
    """
    filled = bs.get("filled") or {}
    writer({"type": "thinking", "content": f"builder_ask: emitting radius map for {slot.name}"})

    if slot.name == "radius_km":
        # radius_pin (asked first) holds {"lat":..,"lng":..}. Mirror geo_wizard:549.
        pin = _parse_json_value(filled.get("radius_pin"), "{")
        gw = dict(bs.get("geo_ws") or {})
        if pin.get("lat") and pin.get("lng") and not gw.get("_radius_km_map_emitted"):
            writer({"type": "map_data", "content": {
                "action_type": "radius_picker",
                "center": {"lat": float(pin["lat"]), "lng": float(pin["lng"])},
            }})
            gw["_radius_km_map_emitted"] = True
            bs["geo_ws"] = gw
        return

    if slot.name == "poi_radius_m":
        # Mirror maid_wizard:131-146 — POIs + center from the geo result.
        geo = _builder_geo(state, bs)
        locations = geo.get("locations") or []
        ms = dict(bs.get("maid_ws") or {})
        if not ms.get("_poi_radius_map_emitted"):
            writer({"type": "map_data", "content": {
                "action_type": "poi_radius_picker",
                "pois": [
                    {
                        "lat": p["lat"],
                        "lng": p["lng"],
                        "name": p.get("name", ""),
                        "parent_location": p.get("parent_location", ""),
                    }
                    for p in (geo.get("targetable_pois") or [])
                    if p.get("lat") and p.get("lng")
                ],
                "center": locations[0] if locations else {},
                "prefill_radius_m": prefill_radius_m,
            }})
            ms["_poi_radius_map_emitted"] = True
            bs["maid_ws"] = ms
        return

    if slot.name == "competitor_radius_km":
        # The anchor is only geocoded in builder_act; geocode it here so the
        # radius picker has a center, and cache the result for builder_act to
        # reuse (avoids a second geocode). Mirror geo_wizard:1267.
        gw = dict(bs.get("geo_ws") or {})
        if gw.get("_competitor_radius_map_emitted"):
            return
        anchor = str(filled.get("competitor_anchor") or "").strip()
        # Pair store_set+competitor_nearby: the competitor_anchor slot is suppressed
        # (skip_when_any=store_set), so the anchor address lives in store_addresses.
        # Mirror builder_act's pair anchor sourcing so the picker still gets a center.
        if not anchor:
            _det_subs = {
                s.strip() for s in str(filled.get("det_type", "")).lower().split(",")
                if s.strip()
            }
            if "store_set" in _det_subs:
                _stores = await _parse_addrs_never_drop(
                    gw, str(filled.get("store_addresses", "")), "_parsed_store_addresses"
                )
                anchor = _stores[0] if _stores else ""
        if not anchor:
            return
        cached = gw.get("_anchor_geocoded")
        result = cached.get("result") if isinstance(cached, dict) and cached.get("anchor") == anchor else None
        if result is None:
            hint = market_hint(await _cached_parse(
                gw, "_parsed_locations", str(filled.get("locations", "")), parse_location_names
            ))
            result, _glog = await call_tool(
                geocode_or_place,
                {"location_name": anchor, "market_hint": hint, "allow_coarse": True},
                writer=writer, node_name="builder_ask_competitor_radius",
            )
            if isinstance(result, dict) and result.get("latitude"):
                gw["_anchor_geocoded"] = {"anchor": anchor, "result": result}
        if isinstance(result, dict) and result.get("latitude"):
            writer({"type": "map_data", "content": {
                "action_type": "radius_picker",
                "center": {"lat": float(result["latitude"]), "lng": float(result["longitude"])},
                "locations": [result],
            }})
            gw["_competitor_radius_map_emitted"] = True
        bs["geo_ws"] = gw
        return


# ── Budget label helper ─────────────────────────────────────────────────────────


def _extract_budget_amount(text: str) -> str:
    """Pull a clean ``$N/day`` out of a verbose budget tier label like
    ``"Recommended: $280/day — estimated to reach ~140,000 people…"`` for display /
    narration. Builder budgets are always daily, so the period is normalized to
    ``/day``. Returns "" if no dollar amount is present."""
    import re
    m = re.search(r"\$\s?[\d,]+(?:\.\d+)?", text or "")
    if not m:
        return ""
    return f"{m.group().replace(' ', '')}/day"


def _backfill_copy_suggestions(plan: dict, brief: dict, *, force: bool = False) -> None:
    """Populate each creative's ``title_suggestions`` / ``body_suggestions`` from the
    cached brief when a stored plan lacks them (built before the alternates existed).
    Mirrors ``build_campaign_spec`` (builder.py) — same ``_options`` helper, same brief
    keys — so a session checkpointed before this feature gets the extra headlines and
    bodies without a full rebuild, and publishes them as text variations. The primary
    ``title`` / ``body`` are never touched.

    ``force`` overwrites suggestions that are already present. This is how a
    ``redraft`` edit (the user changed their audience / business description after
    the spec was built) reaches an EXISTING plan: re-run the brief, then push its
    new copy in without rebuilding the tree. It is one-shot on purpose — leaving it
    on would stomp the user's chosen suggestion on every later render.
    """
    from app.graph.meta_spec.builder import _options
    from app.graph.meta_spec.enums import CREATIVE_BODY_MAX, CREATIVE_TITLE_MAX

    for adset in plan.get("adsets") or []:
        for ad in adset.get("ads") or []:
            creative = ad.get("creative")
            if not isinstance(creative, dict):
                continue
            if force or not creative.get("title_suggestions"):
                titles = _options(
                    brief.get("headline_suggestions"),
                    creative.get("title") or "",
                    CREATIVE_TITLE_MAX,
                )
                if len(titles) > 1:
                    creative["title_suggestions"] = titles
            if force or not creative.get("body_suggestions"):
                bodies = _options(
                    brief.get("body_copy_suggestions"),
                    creative.get("body") or "",
                    CREATIVE_BODY_MAX,
                )
                if len(bodies) > 1:
                    creative["body_suggestions"] = bodies


async def _apply_previous_campaign(
    bs: dict,
    ui: dict,
    plan: dict,
    campaign_id: str,
    *,
    adset_ids: list[str] | None = None,
    ad_ids: list[str] | None = None,
) -> dict:
    """Overlay a previous campaign's setup onto the freshly built plan.

    ``adset_ids`` / ``ad_ids`` narrow the campaign to the parts the user ticked in
    the editor's copy picker; empty means all of it.

    Everything here degrades to "plan unchanged": the user asked to reuse a
    campaign as a convenience, and failing to read it must not cost them the run
    they have already answered questions for. What went wrong is said in
    ``compliance_notes``, which the editor renders as a banner.

    An overlay that produces a combination our matrix rejects is NOT swallowed —
    it goes to ``marketing_plan_draft`` + ``plan_errors``, the same route an
    invalid user edit takes, so the editor opens on the offending fields.
    """
    from app.graph.meta_spec.builder import apply_campaign_template
    from app.graph.meta_spec.importer import (
        TemplateImportError,
        campaign_template,
        select_tree_subset,
    )
    from app.services import meta_ads as _meta

    try:
        tree = await _meta.fetch_campaign_tree(campaign_id, ui["meta_access_token"])
        template, notes = campaign_template(
            select_tree_subset(tree, adset_ids, ad_ids)
        )
    except TemplateImportError as exc:
        logger.info("template import refused for %s: %s", campaign_id, exc)
        plan["compliance_notes"] = [*(plan.get("compliance_notes") or []), str(exc)]
        return plan
    except Exception:
        # Say plainly that the plan below is NOT the one they asked to start from —
        # the values in front of them are the only evidence either way, and a fresh
        # plan looks like a working one. exc_info so the cause is recoverable.
        logger.warning("template import failed for %s", campaign_id, exc_info=True)
        plan["compliance_notes"] = [
            *(plan.get("compliance_notes") or []),
            f"We couldn't read campaign {campaign_id}, so none of its settings were "
            "reused — this plan was set up fresh. Everything below is still editable.",
        ]
        return plan

    # This run's ids, so a goal the template introduces (Leads promotes the Page,
    # Sales the pixel) lands on something real instead of validating into an
    # unfixable field error in the editor.
    merged = apply_campaign_template(
        plan, template,
        page_id=ui.get("meta_page_id"),
        pixel_id=_resolved_pixel_id(bs, ui),
    )
    merged["compliance_notes"] = [*(merged.get("compliance_notes") or []), *notes]

    try:
        return CampaignSpec.model_validate(merged).model_dump(mode="json")
    except ValidationError as exc:
        # Meta accepts combinations we do not model. Hand it to the editor with
        # the fields marked rather than dropping the user's choice silently.
        logger.info("template overlay did not validate for %s: %s", campaign_id, exc)
        bs["marketing_plan_draft"] = merged
        bs["plan_errors"] = errors_to_form_keys(exc)
        return merged


async def _enrich_reach_estimate(plan: dict, spec: Optional[CampaignSpec], ui: dict) -> None:
    """Add Meta's own reach estimate to ``plan["estimated_reach"]`` in place,
    beside the MAID audience size it already carries — the ads_read
    justification's "delivery estimates, shown on the plan screen" claim had
    nothing behind it; nowhere in the codebase called delivery_estimate.

    Best-effort and silent on anything short of success: no ad account/token
    yet (plan reviewed before Meta connects), no ad sets, or Meta's own
    (semi-deprecated) endpoint erroring — the plan screen must render exactly
    as well without this as with it.
    """
    ad_account_id = ui.get("meta_ad_account_id")
    access_token = ui.get("meta_access_token")
    if not (spec and spec.adsets and ad_account_id and access_token):
        return
    try:
        from app.services.meta_ads import fetch_delivery_estimate

        adset = spec.adsets[0]
        estimate = await fetch_delivery_estimate(
            ad_account_id, access_token,
            optimization_goal=adset.optimization_goal.value,
            targeting_spec=adset._wire_targeting(),
            promoted_object=adset.promoted_object.to_payload() if adset.promoted_object else None,
        )
        if estimate:
            plan.setdefault("estimated_reach", {}).update(estimate)
    except Exception as exc:  # noqa: BLE001 — must never break the plan screen
        logger.info("plan editor: reach estimate enrichment skipped — %s", exc)


async def _plan_form_extra(bs: dict, state: AgentState) -> Optional[dict]:
    """The ``campaign_plan_editor`` payload: full spec + option catalog + locks.

    The bespoke editor renders the campaign tree directly (Campaign panel · Ad Set
    tabs · Ad cards) from ``spec`` and populates its dropdowns from ``catalog``.
    ``locks`` marks the server-owned targeting (geo ZIPs + MAID audience) the
    editor shows read-only.

    When the user's last submission failed validation, its (invalid) edited tree
    lives in ``marketing_plan_draft`` and is emitted verbatim alongside ``errors``
    so the editor re-renders exactly what the user typed. Otherwise the validated
    ``marketing_plan`` is emitted.

    Returns ``None`` only when no plan exists — the caller drops
    ``generate_meta_json`` from ``ops_done`` so the act (re)builds the initial tree.
    """
    draft = bs.get("marketing_plan_draft")
    plan = draft or bs.get("marketing_plan")
    if not plan:
        return None

    objective: Any = plan.get("objective")
    spec: Optional[CampaignSpec] = None
    if not draft:
        try:
            spec = CampaignSpec.model_validate(plan)
            plan = spec.model_dump(mode="json")
            objective = spec.objective
        except ValidationError as exc:
            # The stored (non-draft) spec should always validate. If it somehow
            # does not, force a rebuild rather than render a broken editor.
            logger.warning("plan editor: stored spec did not validate — forcing rebuild: %s", exc)
            bs["ops_done"] = sorted(_ops_done(bs) - {"generate_meta_json"})
            return None
        # Backfill the copy dropdowns for plans checkpointed before the suggestion
        # pool existed. The pools are display-only (never published) and are simply
        # the brief's AI candidates, so we can add them on render without a rebuild.
        # A draft is skipped — it already holds the user's edited tree verbatim.
        # `_copy_refresh` is the one-shot set by a `redraft` edit: the brief was
        # just re-run against a changed audience / description, so overwrite the
        # stale suggestion pools instead of only filling empty ones. Popped here so
        # the very next render is back to fill-if-empty and never stomps a choice
        # the user has since made.
        _force_copy = bool(bs.pop("_copy_refresh", None))
        _backfill_copy_suggestions(plan, bs.get("brief") or {}, force=_force_copy)

    # Rehydrate the ad images. media_url is a client-only preview the editor
    # strips on submit (the spec is extra="forbid"), so a re-emitted editor has
    # media_id and nothing to render. Hydrate a COPY: the draft branch above
    # aliases bs["marketing_plan_draft"] itself, and planting media_url in stored
    # state would fail extra="forbid" on the next validate, far from here.
    plan = copy.deepcopy(plan)
    await hydrate_media_urls(plan, state.get("user_id"))

    # user_info lives on the GRAPH state, not on bs — bs["user_info"] is never
    # written, so reading it here silently shipped page_id=None and left the
    # Engagement boost-object picker with nothing to query.
    ui = _ui_view(state, bs)
    await _enrich_reach_estimate(plan, spec, ui)
    media_ws = bs.get("media_ws") or {}
    extra: dict[str, Any] = {
        "spec": plan,
        "catalog": build_editor_catalog(
            objective,
            pixel_candidates=media_ws.get("pixel_candidates") or [],
            custom_conversions=media_ws.get("custom_conversions") or [],
            audience_candidates=media_ws.get("audience_candidates") or [],
            lead_form_candidates=media_ws.get("lead_form_candidates") or [],
            # Same precedence as generate_meta_json — a re-rendered editor opens
            # on the Page the user picked, not the connect-time default.
            page_id=media_ws.get("page_id") or ui.get("meta_page_id"),
            page_candidates=media_ws.get("page_candidates") or [],
            user_info=ui,
            previous_campaigns=bs.get("previous_campaigns") or [],
            ad_account_timezone=media_ws.get("ad_account_timezone") or "",
        ),
        "locks": {"geo": True, "audience": True},
        # The two-phase express editor needs to be TOLD the mode, not infer it
        # from lock shape — inference breaks the moment express_unlocked below
        # collapses locks to this same guide shape, which is exactly the case
        # a re-lock button has to tell apart from actual guide mode.
        "phase": "plan",
        "publish_mode": _publish_mode(bs.get("filled") or {}),
        "express_unlocked": bool(bs.get("express_unlocked")),
        # Not part of the spec: it is a Punk setting, and CampaignSpec is
        # extra="forbid" with every field in it published to Meta. It rides
        # beside the spec in both directions — see _apply_plan_form_submission.
        "tracking_method": str((bs.get("filled") or {}).get("tracking_method") or ""),
        # Same deal: the intake form's "what your ad should be" answer, which
        # decides whether the ad card opens on composed copy or on the post
        # picker, and which tab of it. Lives in user_info only (intake_to_slots
        # writes no slot for it), so it is read off the ui view.
        "creative_source": str(ui.get("creative_source") or ""),
    }
    errors = dict(bs.get("plan_errors") or {})

    # Express mode hides the campaign and ad-set halves entirely: those users
    # answered budget/flight/Page on the intake form and everything else is
    # defaulted, so the editor is reduced to the ad copy and creative — the one
    # part nobody else can decide for them.
    #
    # Unless something is wrong behind that curtain. Publish failures key most of
    # what Meta rejects to ad-set paths (preflight_adset blames everything under
    # adsets[i]), and those steps are exempt from the retry cap — so a locked
    # editor showing no control for the failing field is an unfixable loop. Show
    # the whole thing instead, and say why it just appeared.
    # bs["express_unlocked"]: the user hit "Unlock & edit" in the editor on a
    # previous submission. Falls through to the guide locks (geo + audience
    # only) so the campaign/ad-set panes stay open on every re-emit from here
    # on — re-locking after an explicit unlock would just relock the fields
    # they came back to edit.
    if _publish_mode(bs.get("filled") or {}) == "express" and not bs.get(
        "express_unlocked"
    ):
        if _express_can_fix(errors):
            extra["locks"] = {"geo": True, "audience": True, "campaign": True, "adset": True}
        elif errors:
            note = (
                "This one needs a setting outside the ad itself, so I've opened up "
                "the full campaign for you."
            )
            errors["__root__"] = f"{note} {errors['__root__']}" if errors.get("__root__") else note

    if errors:
        extra["errors"] = errors
    # The same fix-it cards the publish gate shows. They belong here too: this is
    # where a blocked publish lands (its Publish button is the retry), and the
    # Instagram/WhatsApp gaps are worth reading BEFORE spending, not after.
    fixes = _remediation_extra(bs, state)
    if fixes:
        extra["remediation"] = fixes
    return extra


# Paths the ads-only editor actually renders a control for. Everything else lives
# in the Campaign panel or the ad-set panel, both hidden in express mode.
_EXPRESS_REACHABLE = re.compile(r"^adsets\[\d+\]\.ads\[\d+\]\.")


def _express_can_fix(errors: dict | None) -> bool:
    """True when every plan error has a control the express editor shows.

    ``__root__`` is skipped: it is a banner, not a field, and every publish
    failure sets one — treating it as unreachable would unlock the editor on
    every failure, including the ad-copy ones express is built to handle.
    """
    for key in errors or {}:
        if key == "__root__":
            continue
        if not _EXPRESS_REACHABLE.match(str(key)):
            return False
        # The one genuinely misleading key: the path is ad-level so the pattern
        # above passes it, but the only control that writes it is the instant-form
        # select in the ad-set panel.
        if str(key).endswith(".creative.lead_gen_form_id"):
            return False
    return True


def _audience_notice(bs: dict, geo: dict) -> Optional[dict]:
    """The visitor audience was built but never attached — or None.

    Publishing without it is automatic (Meta refuses a customer-list audience on an
    ad account outside a Business, and no answer the user could give changes that),
    so it is the one publish decision made FOR them. Said twice on purpose: once in
    the publish beat, once on the Preview & Publish screen before anything spends.

    Gated on ``maid_extraction_id`` — a plan that never had a visitor audience has
    nothing to have lost.
    """
    if not (bs.get("publish_without_audience") and (geo or {}).get("maid_extraction_id")):
        return None
    return {
        "dropped": True,
        "reason": str(
            bs.get("audience_blocked_reason")
            or "Meta would not store your visitor audience on this ad account, "
               "because the account is not attached to a Meta Business."
        ),
        "fix": "Add the ad account to a Business in Business Manager, then republish "
               "to target your visitors directly.",
    }


async def _preview_extra(bs: dict, state: AgentState) -> dict:
    """Widget payload for the Preview & Publish gate.

    Almost everything here is already known once ``publish`` returns — the ids
    Meta gave us plus the parts of the approved spec worth restating (placements,
    budget, flight). The ad previews themselves are deliberately absent: Meta's
    preview iframe URLs are short-lived, so the client fetches them from
    /ads/ad-previews when the user opens the preview rather than us baking a URL
    into a payload that may sit on screen for minutes.

    The one live read is the pixel's ``last_fired_time`` — see ``_tracking_extra``.
    """
    ids = bs.get("meta_campaign_ids") or (state.get("meta_campaign_ids") or {})
    plan = bs.get("marketing_plan") or {}
    adsets = plan.get("adsets") or []

    # One entry per ad, named the way the editor named it, so the preview tab
    # strip can say which ad it is showing.
    #
    # Named by the plan slot publish recorded ("{adset_idx}:{ad_idx}"), not by
    # position: publish skips an ad with no media, and a positional pairing then
    # slides every later id onto the previous ad's name. Sessions published
    # before ad_keys existed have none, and fall back to the positional read.
    ads: list[dict] = []
    ad_ids = list(ids.get("ad_ids") or [])
    ad_keys = list(ids.get("ad_keys") or [])
    flat = [ad for a in adsets for ad in (a.get("ads") or [])]
    for i, ad_id in enumerate(ad_ids):
        spec_ad: dict = {}
        if i < len(ad_keys):
            adset_idx, _, ad_idx = str(ad_keys[i]).partition(":")
            with contextlib.suppress(ValueError, IndexError):
                spec_ad = (adsets[int(adset_idx)].get("ads") or [])[int(ad_idx)]
        elif i < len(flat):
            spec_ad = flat[i]
        ads.append({"ad_id": str(ad_id), "name": spec_ad.get("name") or f"Ad {i + 1}"})

    first = adsets[0] if adsets else {}
    budget_type, budget_amount = _summary_budget(plan, adsets)
    extra: dict[str, Any] = {
        "campaign_id": str(ids.get("campaign_id") or ""),
        "ad_account_id": str(ids.get("ad_account_id") or ""),
        "ads": ads,
        "summary": {
            "campaign_name": plan.get("name") or "",
            "objective": plan.get("objective") or "",
            "placements": _placement_summary(adsets),
            "budget": {
                "type": budget_type,
                "amount": budget_amount,
                "currency": (bs.get("media_ws") or {}).get("ad_account_currency") or "USD",
            },
            "start_date": first.get("start_time") or "",
            "end_date": first.get("end_time") or "",
        },
    }
    access_token = str(_ui_view(state, bs).get("meta_access_token") or "")
    tracking = await _tracking_extra(
        bs, adsets, access_token,
        user_id=str(state.get("user_id") or ""),
    )
    if tracking:
        extra["tracking"] = tracking
    notice = _audience_notice(bs, _builder_geo(state, bs))
    if notice:
        extra["audience_notice"] = notice
    fixes = _remediation_extra(bs, state)
    # The one check that needs a live read, and the last place to make it before
    # money moves: a dataset Meta has never seen an event from means the campaign
    # is about to optimize toward something that never arrives.
    #
    # Unless no browser event was ever going to arrive: instant-form leads happen
    # inside Facebook and CRM uploads happen after the fact, so for those two the
    # warning describes the setup working as chosen. Same rule as
    # TrackingService.health, so the preview and the tracking card agree.
    from app.modules.tracking.service import uses_pixel as _uses_pixel

    if (
        tracking
        and not tracking.get("last_fired_time")
        and _uses_pixel(tracking.get("tracking_method"))
    ):
        from app.services import meta_remediation as _fix

        fixes = fixes + [
            _fix.render(
                _fix.CATALOG["pixel_never_fired"],
                dataset_id=tracking.get("pixel_id") or "",
            )
        ]
    # A pixel the ad account can SEE but does not OWN — shared in from another
    # Meta business. ``tracking_business_id`` is this account's own business
    # (media_detect_pixel resolves it via fetch_ad_account_business); a dataset
    # listed on that business whose own ``owner_business`` disagrees was shared
    # in from elsewhere. fetch_business_datasets already requests the field —
    # this is the only place anything reads it.
    ad_account_business_id = str((bs.get("media_ws") or {}).get("tracking_business_id") or "")
    if tracking and tracking.get("pixel_id") and ad_account_business_id and access_token:
        from app.services import meta_ads as _meta, meta_remediation as _fix

        datasets = await _meta.fetch_business_datasets(ad_account_business_id, access_token)
        owning_business = next(
            (
                str((d.get("owner_business") or {}).get("id") or "")
                for d in datasets
                if str(d.get("id")) == str(tracking.get("pixel_id"))
            ),
            "",
        )
        if owning_business and owning_business != ad_account_business_id:
            fixes = fixes + [
                _fix.render(
                    _fix.CATALOG["pixel_owner_mismatch"],
                    dataset_id=tracking.get("pixel_id") or "",
                )
            ]
    # The other thing Meta never complains about: an unverified domain. The
    # campaign publishes, runs, and quietly attributes a fraction of the web
    # conversions it otherwise would. Nothing raises an exception, so nothing else
    # in Punk would ever surface this card.
    domain = _conversion_domain(adsets)
    business_id = str((bs.get("media_ws") or {}).get("tracking_business_id") or "")
    if tracking and domain and business_id and access_token:
        from app.services import meta_ads as _meta, meta_remediation as _fix

        verified = await _meta.fetch_verified_domains(business_id, access_token)
        # None means the read failed, not that nothing is verified — same rule as
        # everywhere else on this gate: never accuse on an unknown.
        #
        # It is currently None on every account: /{business_id}/owned_domains
        # answers "(#100) Tried accessing nonexisting field" on Graph v25.0 (see
        # scripts/probe_domain_edge.py). So this branch silently checks nothing,
        # and the gate has to SAY that rather than reading as a domain that
        # passed — an unverified domain costs attribution with no error anywhere.
        if verified is None:
            extra["domain_check"] = "unavailable"
        if verified is not None and domain not in verified:
            fixes = fixes + [
                _fix.render(
                    _fix.CATALOG["domain_not_verified"], business_id=business_id,
                )
            ]
    if fixes:
        extra["remediation"] = fixes
    return extra


def _conversion_domain(adsets: list[dict]) -> str:
    """The domain this campaign counts conversions on, bare and lowercased.

    Reads the ad's own ``conversion_domain`` first — AdSpec already derives it
    from the link and Meta validates against that exact value — and falls back to
    the link's host for a plan built before the field existed. One domain: a
    campaign whose ads point at two of them is not a shape the editor can build.
    """
    for adset in adsets:
        for ad in adset.get("ads") or []:
            named = str(ad.get("conversion_domain") or "").strip().lower()
            if named:
                return named.removeprefix("www.")
            link = str(ad.get("link") or "").strip()
            if link:
                host = urlparse(link if "//" in link else f"https://{link}").hostname
                if host:
                    return host.lower().removeprefix("www.")
    return ""


def _remediation_extra(bs: dict, state: AgentState) -> list[dict]:
    """Everything the user has to go do in Meta themselves, for one gate.

    Three sources, one list, because the user does not care which layer noticed:
    the connect-time account read, whatever Meta refused during a publish, and the
    plan-vs-Page check that catches what Meta never complains about at all (ads
    bought on Instagram placements under a Page with no Instagram account linked
    run fine, as a placeholder profile nobody asked for).

    Deduped by key and ordered blocks → degrades → warns, so the thing standing
    between the user and a live campaign is the thing they read first.
    """
    from app.services import meta_remediation as _fix

    ui = _ui_view(state, bs)
    media_ws = bs.get("media_ws") or {}
    plan = bs.get("marketing_plan") or {}
    ids = {
        "ad_account_id": str(ui.get("meta_ad_account_id") or ""),
        "page_id": str(plan.get("page_id") or ui.get("meta_page_id") or ""),
        "business_id": str(media_ws.get("tracking_business_id") or ""),
        "dataset_id": str(media_ws.get("pixel_id") or ""),
    }

    page = next(
        (
            p for p in (media_ws.get("page_candidates") or [])
            if str(p.get("id")) == ids["page_id"]
        ),
        None,
    )
    asset_gaps = _fix.render_all(
        _fix.check_plan_assets(
            plan,
            page=page,
            instagram_user_id=str(media_ws.get("instagram_user_id") or ""),
        ),
        **ids,
    )

    seen: dict[str, dict] = {}
    for entry in (
        list(bs.get("account_remediation") or [])
        + list(bs.get("publish_remediation") or [])
        + asset_gaps
    ):
        seen.setdefault(entry["key"], entry)
    rank = {"blocks": 0, "degrades": 1, "warns": 2}
    return sorted(seen.values(), key=lambda e: rank.get(e.get("severity"), 3))


def _page_blockers(bs: dict) -> list:
    """Cards for what the connected Pages lack, off the flags ``media_detect_page_assets``
    sets: no Page at all, an unpublished default Page, no advertising role on it.

    An unpublished or role-less default Page is only a warning when another Page can
    carry the campaign — the plan editor's Page picker is one click away, and a red
    "blocks" card for someone with three healthy Pages is the wrong noise. Severity is
    display and sort only; nothing gates on it.
    """
    from dataclasses import replace

    from app.services import meta_remediation as _fix

    mws = bs.get("media_ws") or {}
    pages = mws.get("page_candidates") or []
    found = []
    if mws.get("no_facebook_page"):
        found.append(_fix.CATALOG["no_facebook_page"])
    for flag, field, otherwise in (
        ("page_unpublished", "is_published",
         "Pick one of your other published Pages in the plan editor, or publish this one."),
        ("page_role_missing", "can_advertise",
         "Pick a Page you can advertise under in the plan editor."),
    ):
        if not mws.get(flag):
            continue
        card = _fix.CATALOG[flag]
        if any(p.get(field) is True for p in pages):
            card = replace(card, severity="warns", effect=otherwise)
        found.append(card)
    return found


def _connect_extra_beats(
    state: Any, bs: dict, blockers: list, ad_account_id: str, *,
    tos_accepted: bool | None = None,
) -> None:
    """Chat beats at connect for what is not a publish blocker.

    Kept off ``account_remediation`` (and so off the publish gate's cards): the plan
    editor's pixel picker owns tracking there, and unread Custom Audience Terms are a
    guess. Same buffered ``failure`` beats as the blocker loop, so the composer says
    it all in one message.

    ``blockers`` is what ``ad_account_blockers`` found — only read, to avoid saying
    the same thing twice. ``tos_accepted`` is ``fetch_custom_audience_tos``: only
    ``None`` (Meta would not say) earns the "confirm it yourself" beat.
    """
    from dataclasses import replace

    from app.services import meta_remediation as _fix

    mws = bs.get("media_ws") or {}
    pixels = mws.get("pixel_candidates") or []
    if not pixels:
        add_beat(
            state, "failure",
            facts=_fix.beat_facts(_fix.CATALOG["no_pixel"], ad_account_id=ad_account_id),
            fallback=(
                "There is no Pixel on this ad account, so I will steer you toward "
                "goals that do not need one. You can set one up in Events Manager."
            ),
        )
    elif not any(p.get("last_fired_time") for p in pixels):
        # Same test as ``has_warm_dataset`` (media.py): a Pixel that never fired is,
        # for the brief, the same as none — delivery learns from events. The catalog
        # effect describes a campaign that does not exist yet at connect.
        add_beat(
            state, "failure",
            facts=_fix.beat_facts(
                replace(
                    _fix.CATALOG["pixel_never_fired"],
                    effect="I will steer you toward goals that do not need conversion data.",
                ),
                dataset_id=mws.get("pixel_id") or pixels[0].get("id") or "",
            ),
            fallback=(
                "Your Pixel has never received an event, so I will steer you toward goals "
                "that do not need conversion data until it is installed on your site."
            ),
        )
    # An audience already on the account means the terms were accepted there (Meta
    # refuses to create one otherwise) — nothing to confirm. Skipped too when the
    # audience is already off the table.
    if (
        tos_accepted is None
        and not bs.get("publish_without_audience")
        and not mws.get("audience_candidates")
        and not any(r.key == "custom_audience_tos" for r in blockers)
    ):
        add_beat(
            state, "failure",
            facts=_fix.beat_facts(
                _fix.CATALOG["custom_audience_tos"],
                unverified=True, ad_account_id=ad_account_id,
            ),
            fallback=(
                "I cannot check whether Custom Audience Terms are accepted on this "
                "ad account. If not, accept them in Meta before publishing or the "
                "campaign goes out targeted by location only."
            ),
        )


async def _tracking_extra(
    bs: dict, adsets: list[dict], access_token: str, *, user_id: str = ""
) -> Optional[dict]:
    """Conversion-tracking status for the Preview & Publish gate, or None.

    Only for plans that actually promote a pixel — every other objective measures
    on Meta's own surfaces and has nothing to install.

    ``last_fired_time`` is read live rather than carried in state because it is
    the whole point: a Pixel that exists but has never fired publishes cleanly and
    then optimizes toward an event that never arrives. That is the one thing worth
    telling someone before they spend money, and it can become true between the
    publish and the moment they look at this screen.
    """
    promoted = next(
        (
            a.get("promoted_object") or {}
            for a in adsets
            if (a.get("promoted_object") or {}).get("pixel_id")
            or (a.get("promoted_object") or {}).get("custom_conversion_id")
        ),
        {},
    )
    pixel_id = promoted.get("pixel_id")
    if not pixel_id:
        return None

    media_ws = bs.get("media_ws") or {}
    activity: dict = {}
    quality: float | None = None
    if access_token:
        from app.services import meta_ads as _meta

        activity = await _meta.fetch_pixel_activity(str(pixel_id), access_token)
        # Event Match Quality: how well the identifiers reaching this dataset
        # resolve to real accounts. A dataset that fires constantly and matches
        # nobody optimizes almost as badly as one that never fires, and this gate
        # is the last place to notice.
        quality = await _meta.fetch_event_match_quality(str(pixel_id), access_token)

    name = activity.get("name") or next(
        (p.get("name") for p in media_ws.get("pixel_candidates") or []
         if str(p.get("id")) == str(pixel_id)),
        "",
    )
    # What the campaign actually optimizes toward, in the user's own words where
    # they picked one of their custom conversions.
    custom_id = str(promoted.get("custom_conversion_id") or "")
    conversion_label = next(
        (
            c.get("name")
            for c in media_ws.get("custom_conversions") or []
            if str(c.get("id")) == custom_id
        ),
        "",
    ) or str(promoted.get("custom_event_type") or "")

    # How conversions reach Meta. Guide's own answer is a slot; express is never
    # asked and gets one derived from the campaign's shape in media_select_pixel,
    # which persists it on the ad account rather than into ``filled``. Read both,
    # slot first — an empty method reads as the full pixel + server default, and
    # showing a "do it for me" user a server code sample is exactly the parameter
    # they do not have.
    setup = await _tracking_setup(user_id)
    tracking_method = str(
        (bs.get("filled") or {}).get("tracking_method")
        or (setup.get("setup") or {}).get("tracking_method")
        or ""
    )

    return {
        "pixel_id": str(pixel_id),
        "pixel_name": name or "Your Pixel",
        # None when Meta has never seen an event from it — or when the read
        # failed, which the client treats the same way (it only ever adds a
        # warning, never removes one).
        "last_fired_time": activity.get("last_fired_time"),
        "created_by_punk": bool(media_ws.get("pixel_created")),
        # Whose business owns the dataset. "" for one that sits on the ad account
        # itself, which is what a personal account gets.
        "business_id": str(media_ws.get("tracking_business_id") or ""),
        "event_match_quality": quality,
        "conversion_event": conversion_label,
        # How the user said conversions would reach Meta, so the gate can say
        # whether the server half is expected at all.
        "tracking_method": tracking_method,
        "events_manager_url": (
            f"https://business.facebook.com/events_manager2/list/pixel/{pixel_id}/settings"
        ),
        # The install helper itself, not directions to go find it. This gate is
        # where the advertiser is looking when the setup is fresh in their head;
        # sending them to a settings page to hunt for a snippet is where the
        # server half of a "pixel + server" setup went to die.
        **setup,
    }


async def _tracking_setup(user_id: str) -> dict:
    """The snippet / endpoint / key for this account's chosen method, or nothing.

    ``TrackingService.snippet`` reads the method off the account row and returns
    only the halves it uses, so the branching lives in one place rather than being
    re-derived here.

    Best-effort: a failure here costs the preview a copy block, never the publish.
    """
    from app.db.database import AsyncSessionLocal
    from app.modules.ads.repository import AdsRepository
    from app.modules.tracking.service import TrackingService

    if not user_id:
        return {}
    try:
        async with AsyncSessionLocal() as db:
            setup = await TrackingService(AdsRepository()).snippet(db, str(user_id))
    except Exception as exc:  # noqa: BLE001 — a copy block is never worth the gate
        logger.warning("publish gate: could not build the tracking setup — %s", exc)
        return {}
    return {
        "setup": {
            key: setup[key]
            for key in (
                "pixel_snippet", "server_example", "ingest_url", "ingest_key",
                "instructions",
                # Not rendered — read back by _tracking_extra as the fallback for
                # a mode that never answered the question.
                "tracking_method",
            )
            if setup.get(key)
        }
    }


def _placement_summary(adsets: list[dict]) -> list[dict]:
    """Platforms + positions the plan actually buys, deduped across ad sets.

    Meta's targeting names positions per platform (``facebook_positions``,
    ``instagram_positions``, …); an empty list on a platform means Advantage+
    placements chose for us, which reads as "all" to the user.
    """
    seen: dict[str, list[str]] = {}
    for adset in adsets:
        targeting = adset.get("targeting") or {}
        for platform in targeting.get("publisher_platforms") or []:
            positions = targeting.get(f"{platform}_positions") or []
            bucket = seen.setdefault(str(platform), [])
            for pos in positions:
                label = str(pos).replace("_", " ").title()
                if label not in bucket:
                    bucket.append(label)
    return [{"platform": p, "positions": v or ["All placements"]} for p, v in seen.items()]


def _summary_budget(plan: dict, adsets: list[dict]) -> tuple[str, int]:
    """``(type, amount)`` for the Preview & Publish budget row, in minor units.

    A campaign carries a budget only under Advantage+ campaign budget (CBO). The
    ordinary plan sets it per ad set (ABO), where the campaign's own
    daily/lifetime are both null — reading only the campaign level showed those
    users a budget of 0.00 next to a campaign that spends every day.

    Ad set budgets are summed because that is what the account actually spends;
    daily wins a mixed plan, since a daily and a lifetime figure cannot be added
    into one honest number and the daily one is the rate the user is agreeing to.
    """
    for scope in ("lifetime", "daily"):
        amount = plan.get(f"{scope}_budget")
        if amount:
            return scope, int(amount)

    totals = {
        scope: sum(int(a.get(f"{scope}_budget") or 0) for a in adsets)
        for scope in ("daily", "lifetime")
    }
    scope = "daily" if totals["daily"] else "lifetime"
    return scope, totals[scope]


def _clamp_to_stepper(stepper_cfg: dict, val: Any) -> Any:
    """Clamp a numeric value into a registry stepper's own min/max.

    The one place both stepper write paths route through: the frontend
    control already enforces min/max, but that is advisory only — a request
    can hand the resume endpoint any JSON it likes, bypassing the widget
    entirely. Without this, `builder_ask`'s maid-settings write
    (`poi_radius_m` / `lookback_days`) took the JSON value verbatim, so
    `{"poi_radius_m": -99999, "lookback_days": 100000}` landed unchanged: a
    malformed ring (negative radius) and a 274-year lookback window sliced
    into vendor calls against the shared monthly Unacast call budget.
    """
    if val is None:
        return None
    lo, hi = stepper_cfg.get("min"), stepper_cfg.get("max")
    if lo is not None:
        val = max(val, lo)
    if hi is not None:
        val = min(val, hi)
    return val


def _seeded_stepper(stepper_cfg: dict, raw_value: Any, parser: Any) -> Optional[dict]:
    """A copy of a registry stepper config with `default` overridden by an
    extracted-but-unconfirmed user_info value, clamped into the stepper's own
    min/max so an out-of-range extraction (e.g. 2000 m into a 1-500 control)
    can't land outside the widget. None when there's nothing to seed —
    callers then leave the registry default untouched."""
    if raw_value in (None, ""):
        return None
    val = parser(str(raw_value), default=None)
    if val is None:
        return None
    return {**stepper_cfg, "default": _clamp_to_stepper(stepper_cfg, val)}


async def _enrich_slot_ask(slot: Slot, bs: dict, state: AgentState, writer: Any) -> dict:
    """Per-call widget enrichment for ``builder_ask`` — wizard parity for slots
    whose options / prompt / map the wizard computes at call time (the static
    registry config ships empty options for these). Returns ``wizard_interrupt``
    kwargs and emits any pre-interrupt map_data.
    """
    name = slot.name

    # Meta cannot hold a customer-list audience on this ad account — either it
    # already refused one (publish_audience_blocked) or the connect-time
    # capability check saw the account has no Business. Trying anyway stays the
    # first option (it is an account setting, fixable between attempts), plus a
    # geo-only publish so the user is not dead-ended on someone else's Business
    # Manager.
    # Same constraint, one question earlier: "Export audience to Meta" puts the
    # audience in the ad account and nothing else, so on an account Meta won't
    # let hold one it is the single mode that cannot work. Warned, not removed —
    # the option list is index-addressed (the widget answers "1"/"2"/"3", see
    # _normalize_publish_mode), and dropping an entry would remap every numeric
    # pick. A warning also leaves the choice open to someone who fixes their
    # Business Manager between the two screens.
    if name == "publish_mode" and bs.get("audience_blocked_reason"):
        return {
            "prompt_override": (
                "Your audience is ready. One thing first: this ad account isn't "
                "attached to a Meta Business, so Meta won't let us store the "
                "audience inside it — \"Export audience to Meta\" will fail until "
                "the account is added to a Business in Business Manager. "
                "How would you like to take it to Meta?"
            ),
        }

    if name == "plan_confirm":
        form = await _plan_form_extra(bs, state)
        if form:
            _frame_audience_roles(state, bs, (form.get("spec") or {}).get("adsets") or [])
            return {
                "action_type_override": "campaign_plan_editor",
                "field_override": "campaign_plan_confirm",
                "prompt_override": (
                    "Here's your campaign. Everything is editable — add ad sets or "
                    "ads, adjust targeting and creative, then publish."
                ),
                "extra": form,
            }

    # The express-only intake form: business name/what-they-sell prefill from the
    # entry gate, objective, budget, flight, Page. No network calls — everything
    # else is defaulted and shown filled in by the plan editor, which express
    # never opens (its campaign/ad-set panes stay locked), so this form is the
    # only chance to set them. The client renders it from the form_schema;
    # builder_ask parses the JSON submission.
    #
    # No skip_ask: the framing above this widget is narrated the normal way
    # (wizard_ask -> step_frame beat -> the pause's composed message), same as
    # publish_mode and the plan editor. Its predecessor — the free-text batch ask
    # that printed its own question list verbatim — DID pass skip_ask=True, and
    # keeping that flag here after the emit was dropped is what shipped the intake
    # form with no assistant message above it at all.
    if name == "campaign_intake":
        media_ws = bs.get("media_ws") or {}
        ui = _ui_view(state, bs)
        # A re-render after a validation error already carries the user's own
        # number in `values`, which wins over `suggestion` — deriving one again
        # would be an LLM call nothing reads.
        budget_cents, budget_reason = (
            await _intake_budget_prefill(ui, _builder_geo(state, bs), bs, writer)
            if not (bs.get("intake_values") or {}).get("budget_amount")
            else (None, "")
        )
        schema = build_intake_schema(
            user_info=ui,
            enrichment=bs.get("enrichment") or {},
            errors=bs.get("intake_errors"),
            pages=media_ws.get("page_candidates") or [],
            # Ad accounts are not all USD, and Meta's daily minimum is
            # per-currency — both were read off the account at connect time.
            currency=str(media_ws.get("ad_account_currency") or "USD"),
            min_budget_cents=media_ws.get("min_daily_budget") or None,
            # connect_meta already read the Page's website into user_info;
            # a non-empty value here drops the website question.
            page_website=str(ui.get("website_url") or ""),
            # The editor's form picker lives in the ad-set panel express hides,
            # so the choice moves onto this form.
            lead_forms=media_ws.get("lead_form_candidates") or [],
            # Read-only line when the account already has a warm dataset. Read
            # at connect time by media_detect_pixel, so no extra Graph call.
            pixels=media_ws.get("pixel_candidates") or [],
            budget_suggestion=budget_cents,
            budget_reason=budget_reason,
        )
        # Re-render after a failed submission. The form carries its own inline
        # field errors, but the chat said nothing about why the same widget came
        # back — so buffer a reframe beat, which the composer weaves ahead of the
        # step framing into the one message this pause emits.
        _reframe_intake_errors(state, bs.get("intake_errors"), schema)
        next_line = (
            "Punk sets targeting, bidding and placements for you. You'll "
            "still see the ad before anything publishes."
        )
        # Emitted as campaign_plan_editor, same as the plan-review pause below —
        # not the old "campaign_intake_form" action type any more. The intake
        # form now renders AS the Campaign pane of the tree editor (phase:
        # "intake", no spec yet — CampaignEditor.tsx switches on `phase` before
        # touching `spec`/`catalog`), so the same widget the plan re-emits into
        # is on screen from the first question, with a greyed-out Ad set/Ad row
        # showing what's next. The wire submission is byte-identical either
        # way — {"values": {...}} — so parse_intake_submission and the
        # campaign_intake slot handler below need no change.
        #
        # intake_form.INTAKE_ACTION_TYPE ("campaign_intake_form") is unused
        # here now but stays exported: WidgetCampaignIntakeForm.tsx and its
        # ActiveWidgetRenderer case still render it for transcripts persisted
        # before this change.
        return {
            "action_type_override": "campaign_plan_editor",
            "field_override": INTAKE_FIELD,
            "prompt_override": f"Let's set up your campaign — fill in the details below. {next_line}",
            "extra": {
                "phase": "intake",
                "form_schema": schema,
                "values": bs.get("intake_values") or {},
                "errors": bs.get("intake_errors"),
                "locks": {"geo": True, "audience": True, "campaign": True, "adset": True},
                "publish_mode": "express",
            },
        }

    # Preview & Publish. The campaign is already built in Meta and PAUSED; this
    # gate is what lets the user look at Meta's own rendering of the ads before
    # anything spends. The preview iframes are NOT in this payload — their URLs
    # are short-lived, so the client fetches them from /ads/ad-previews when it
    # opens the preview.
    #
    # Emitted as campaign_plan_editor (phase: "preview"), same as intake/plan —
    # not the standalone "campaign_preview" action type any more. This is the
    # third phase of the one persistent editor shell (ActiveWidgetRenderer keys
    # it "campaign-plan-editor", a constant, so intake -> plan -> preview never
    # remounts). CampaignEditor.tsx switches on `phase` before touching `spec`.
    #
    # campaign_preview stays exported/rendered: WidgetCampaignPreview.tsx and
    # its ActiveWidgetRenderer case still draw it for transcripts persisted
    # before this change.
    if name == "go_live_confirm":
        return {
            "action_type_override": "campaign_plan_editor",
            "field_override": "meta_go_live_confirm",
            "extra": {"phase": "preview", **await _preview_extra(bs, state)},
        }

    if name in ("radius_km", "competitor_radius_km", "poi_radius_m"):
        await _emit_radius_slot_map(slot, bs, state, writer)
        user_info = state.get("user_info") or {}
        # poi_radius_m normally uses the combined maid_collect_settings widget
        # (radius + lookback in one interrupt). Use the radius-only stepper whenever
        # the lookback is NOT being collected — it was given earlier (prefilled) OR
        # it's an event_based angle (event dates drive the window, so the lookback
        # slot is not_when-excluded) — so a value we won't use isn't shown. The
        # radius-only reply falls through to the single-slot write below, leaving
        # any prefilled lookback_days untouched.
        if name == "poi_radius_m":
            maid_missing = {s.name for s in missing_required_slots("maid", bs.get("filled") or {})}
            if "lookback_days" not in maid_missing:
                # Single-widget radius-only stepper (no `key` — it's the sole
                # control, not one of a `steppers` list).
                radius_stepper = _seeded_stepper(
                    STEP_PROMPTS["maid_collect_poi_radius"]["stepper"],
                    user_info.get("poi_radius_m"), parse_int_safe,
                )
                overrides: dict = {"_step_key_override": "maid_collect_poi_radius"}
                if radius_stepper is not None:
                    overrides["extra"] = {"stepper": radius_stepper}
                return overrides
            # Both still missing — combined widget. Same confirm_prefill slot
            # (poi_radius_m) drives it, so seed the lookback stepper here too
            # from the never-silently-filled user_info value. Each entry needs
            # its own `key`/`label`/`hint`, so clamp against the COMBINED
            # widget's own steppers list, not the standalone single-widget cfg.
            combined_steppers = STEP_PROMPTS["maid_collect_settings"]["steppers"]
            radius_stepper = _seeded_stepper(
                combined_steppers[0], user_info.get("poi_radius_m"), parse_int_safe,
            )
            lookback_stepper = _seeded_stepper(
                combined_steppers[1], user_info.get("lookback_days"), parse_int_safe,
            )
            if radius_stepper is not None or lookback_stepper is not None:
                steppers = [dict(s) for s in combined_steppers]
                if radius_stepper is not None:
                    steppers[0] = radius_stepper
                if lookback_stepper is not None:
                    steppers[1] = lookback_stepper
                return {"extra": {"steppers": steppers}}
            return {}
        step_key = "geo_collect_radius_km" if name == "radius_km" else "geo_collect_competitor_radius"
        stepper = _seeded_stepper(
            STEP_PROMPTS[step_key]["stepper"], user_info.get("search_radius_km"), parse_radius_float,
        )
        return {"extra": {"stepper": stepper}} if stepper is not None else {}

    if name == "lookback_days":
        # Reverse of the radius-only case: the radius was given earlier and only the
        # lookback is missing. Render the lookback-only stepper on the POI map (map
        # data + the maid_collect_lookback single stepper) with the ring drawn at the
        # known radius — so we show ONLY the missing value. The write branch writes
        # lookback alone and preserves the radius. (When BOTH were missing the ask is
        # the combined maid_collect_settings widget, via the poi_radius_m slot.)
        known_radius = str((bs.get("filled") or {}).get("poi_radius_m", "") or "").strip()
        if known_radius:
            await _emit_radius_slot_map(
                SLOTS["poi_radius_m"], bs, state, writer,
                prefill_radius_m=parse_int_safe(known_radius, default=None),
            )
        user_info = state.get("user_info") or {}
        stepper = _seeded_stepper(
            STEP_PROMPTS["maid_collect_lookback"]["stepper"], user_info.get("lookback_days"), parse_int_safe,
        )
        return {"extra": {"stepper": stepper}} if stepper is not None else {}

    if name == "competitor_anchor_confirm":
        # Geocode the user's OWN store anchor(s) and show them on an editable map
        # for review BEFORE the radius is asked. Caches into _geocoded_anchors so
        # builder_act reuses the geocode (no second lookup). Permission answer just
        # resumes — parity with geo_store_confirmation. Guard resets across the
        # pause (a resume re-shows the map), matching _emit_radius_slot_map.
        gw = dict(bs.get("geo_ws") or {})
        filled = bs.get("filled") or {}
        anchor_addrs = await _parse_addrs_never_drop(
            gw, str(filled.get("competitor_anchor") or ""), "_parsed_competitor_anchors"
        )
        cache = gw.get("_geocoded_anchors")
        anchors: list[dict] = (
            list(cache.get("list") or [])
            if isinstance(cache, dict) and cache.get("addrs") == anchor_addrs
            else []
        )
        if not anchors and anchor_addrs:
            # Cache miss = the anchor set changed (first run, or a confirm-step
            # edit reset the cache). Re-emit the map for the new set, so drop the
            # emitted-guard alongside the stale geocode.
            gw.pop("_anchor_confirm_map_emitted", None)
            hint = market_hint(await _cached_parse(
                gw, "_parsed_locations", str(filled.get("locations", "")), parse_location_names
            ))
            for addr in anchor_addrs:
                result, _glog = await call_tool(
                    geocode_or_place,
                    {"location_name": addr, "market_hint": hint, "allow_coarse": True},
                    writer=writer, node_name="builder_ask_anchor_confirm",
                )
                if isinstance(result, dict) and result.get("latitude"):
                    anchors.append(result)
            gw["_geocoded_anchors"] = {"addrs": anchor_addrs, "list": anchors}
        if anchors and not gw.get("_anchor_confirm_map_emitted"):
            writer({"type": "map_data", "content": {
                "action_type": "confirm_locations",
                "locations": anchors,
                "editable": True,
            }})
            gw["_anchor_confirm_map_emitted"] = True
        bs["geo_ws"] = gw
        # No anchor resolved (even the Places fallback missed) → ask for a full
        # street address instead of a hollow, mapless "Are these your locations?".
        if not anchors:
            prompt = (
                "I couldn't pinpoint that. Please share a full street address "
                "(e.g. \"1340 Sainte-Catherine St W, Montreal\")."
            )
        else:
            # Resolved outside the market the user named → say so and let them
            # decide. Never a rejection: a shop abroad from the stated market is
            # legitimate, and only the user knows which case this is.
            _mismatch = next(
                (a["market_mismatch"] for a in anchors if a.get("market_mismatch")), ""
            )
            prompt = (
                f"I found **{_mismatch}** — that's outside the market you named. "
                "Is that your business, or should I look somewhere else?"
                if _mismatch else
                "Is this your business location?" if len(anchors) == 1
                else "Are these your business locations?"
            )
        # Editing the anchor set at this confirm re-runs geocoding: break the widget
        # loop so builder_ask can reset the geocode scratch + re-ask (which re-geocodes
        # and re-emits a fresh map). edit_base merges an append against the current set.
        return {
            "prompt_override": prompt,
            "rerun_on_edit": {
                "store_addresses", "geo_store_addresses",
                "competitor_address", "competitor_anchor",
            },
            "edit_base": {
                "store_addresses": list(anchor_addrs),
                "geo_store_addresses": list(anchor_addrs),
            },
        }

    if name == "maid_confirm":
        _retry = bs.get("maid_retry_pending")
        if _retry:
            # The query genuinely failed this turn (builder_act's maid_query
            # branch left the op out of ops_done) — ask what to do about THAT,
            # not "does this audience look right?". Options are resolved
            # against `_MAID_CONFIRM_RETRY_OPTIONS` in `_apply_gate_answers`,
            # where a bare "yes" also resolves to the first (recommended) one
            # rather than being read as confirmation — there is no audience to
            # confirm. `ip_not_allowlisted` drops the retry option: it is a
            # configuration problem, and retrying the same call cannot fix it.
            _kind = _retry.get("kind") or "vendor_error"
            _options = _MAID_RETRY_OPTIONS.get(_kind, _MAID_RETRY_OPTIONS_DEFAULT)
            _kind_prompt = {
                "budget": (
                    "This month's shared audience-data budget is used up, so I "
                    "couldn't pull the visitors for these spots. It resets at the "
                    "start of next month."
                ),
                "capacity": (
                    "The audience data service was at capacity for too long, so I "
                    "couldn't pull the visitors for these spots."
                ),
                "circuit_open": (
                    "The audience data provider failed several times in a row, so "
                    "I paused requests to it rather than burn through the shared "
                    "data budget getting nothing back."
                ),
                "ip_not_allowlisted": (
                    "I couldn't reach the audience data provider — this environment "
                    "isn't calling from an approved network address. That's a "
                    "configuration problem on our side, not something a retry fixes."
                ),
                "timeout": (
                    "The audience data provider timed out on some very busy spots, "
                    "even after I split the request down as far as it goes."
                ),
                "rate_limited": (
                    "The audience data provider's daily request limit is used up. "
                    "It resets at midnight UTC."
                ),
                "request_rejected": (
                    "The audience data provider rejected this search — usually a "
                    "spot outside the US/Canada area it covers."
                ),
            }.get(_kind, "The audience query didn't succeed this turn.")
            return {
                "prompt_override": f"{_kind_prompt} What would you like to do?",
                "options_override": list(_options),
                "action_type_override": "option_selection",
            }

        # An edit at THIS gate ("also target coffee shops", "make the radius
        # 500m", "now only weekends") names a geo- or maid-owned field, but this
        # gate does not own re-computation for either — the map on screen comes
        # from geo_discover's/maid_query's ACT phase. Without rerun_on_edit the
        # edit is acked by the narrator, merged into wizard_interrupt's local
        # `edits`, and then silently discarded: the loop just re-interrupts on
        # the same stale widget (`_rerun_target` falsy at
        # wizard_helpers.py:1425), so stash_edits/apply_pending_edits/
        # invalidate_from never run this turn. Same fix as poi_confirm below,
        # widened to maid-owned fields (poi_radius_m, lookback_days,
        # audience_filter) so a maid-only edit reruns maid_query without
        # dragging geo_discover along too. `audience_filter` rides this same
        # return via its own `_audience_filter_patch` side-channel (dispatched
        # in `edits` regardless of which field triggered the return) — see
        # wizard_helpers.py:1670-1690.
        #
        # `repeat_events` — same mechanism `poi_confirm` below uses, and for
        # the identical reason: a plain reject/query/no-op-edit loops in place
        # inside the SAME wizard_interrupt call, never returning here, so a
        # map emitted only above (once) would leave every later re-ask at this
        # gate pointing at nothing. Was previously gated behind a
        # `_maid_recompute` flag ("guarantees a single emit") — that flag is
        # exactly the bug: a genuine no-op edit (nothing matched a drop
        # instruction) never flipped it, so the map went stale the first time
        # this gate re-asked for any reason other than a successful maid-side
        # recompute. An async entry — the maid map needs a Postgres round trip
        # (`_maid_confirm_map_event`), unlike `poi_confirm`'s in-memory one —
        # is why `wizard_helpers.wizard_interrupt`'s `repeat_events` loop now
        # awaits a coroutine result.
        return {
            "rerun_on_edit": {f for f, owner in FIELD_OWNER.items() if owner in ("geo", "maid")},
            "repeat_events": [lambda: _maid_confirm_map_event(
                (bs.get("geo_result") or {}).get("maid_extraction_id"),
                (bs.get("geo_result") or {}).get("maid_visit_stats"),
                (bs.get("geo_result") or {}).get("maid_funnel") or {},
            )],
        }

    # The map on screen here comes from geo_discover's ACT phase, emitted
    # once before this gate is ever asked (builder_act, "geo_discover"
    # operation) — unlike competitor_anchor_confirm, this gate does not own
    # its own re-computation. Any geo-owned field named in an edit means the
    # POI set no longer matches what's on screen, so return immediately
    # (rerun_on_edit) instead of re-showing the stale map + gate. The generic
    # apply_pending_edits -> invalidate_from("geo") path (builder_plan, every
    # slot) then drops geo_discover from ops_done and pops this gate from
    # `filled`, so the planner re-runs geo_discover for the new input and a
    # FRESH map is emitted before this gate is re-asked.
    if name == "poi_confirm":
        # `repeat_events` — same mechanism `geo_location_confirmation` /
        # `geo_store_confirmation` already use (executors/geo.py) — so this
        # gate never re-opens as a bare permission prompt with no map beneath
        # it, on ANY re-ask reason: a plain reject/query loops in place inside
        # the SAME wizard_interrupt call; a `poi_selection` NL trim ("top 15")
        # returns via rerun_on_edit and gets asked again as a FRESH call.
        #
        # Passed as a LAMBDA, not a prebuilt event: the handoff lane's
        # `narrow_pois` tool (interject_tools.py) can mutate bs["geo_result"]
        # from an `unhandled`/query dispatch INSIDE this same loop, with no
        # rerun_on_edit exit to trigger a fresh call — a static event captured
        # here at call-setup time would then replay the pre-trim map on the
        # next pause. The lambda closes over the live `bs` dict and re-reads
        # geo_result at every pause, so it's correct whether nothing, a
        # reject/query, or a handoff trim happened since the last one.
        return {
            "rerun_on_edit": {f for f, owner in FIELD_OWNER.items() if owner == "geo"},
            "repeat_events": [lambda: _poi_preview_map_event(
                bs.get("geo_result"), bs.get("geo_ws") or {}, bs.get("filled") or {}
            )],
        }

    return {}


def _read_user_turn(result: Any, slot: Any, bs: dict) -> dict:
    """Thin wrapper over ``wizard_helpers.read_user_turn`` — kept so this call
    site (and any other future one) can pass the ``Slot`` object it already
    has instead of resolving a field name itself. ``wizard_interrupt`` calls
    the shared function directly (it only has a step_key, resolved via
    ``_step_to_slot``) right after each interrupt resolves, so a mid-turn edit
    that loops back to re-interrupt without returning here still gets a fresh
    ``state["user_turn"]`` for its own flush. This call (after the interrupt
    loop finally returns) re-derives the same value for durable persistence
    onto the node diff — see the call site below.
    """
    return read_user_turn(result, getattr(slot, "name", None), bs)


def _with_ledger(fn):
    """Commit this node's buffered transcript records into ``messages``.

    ``wizard_interrupt`` returns a ResumeResult, not a state diff, so it buffers
    each resolved Q/A pair process-locally and the enclosing graph node commits it
    here. This is the only place the builder's conversation reaches the transcript.

    Drained in ``finally``, not on the happy path: an interrupt raised LATER in the
    same node execution discards the node's writes, and the replay re-derives the
    records from the replayed interrupts. A buffer that survived the exception
    would double them.
    """
    @functools.wraps(fn)
    async def _wrapped(state, *args, **kwargs):
        try:
            update = await fn(state, *args, **kwargs) or {}
        finally:
            records = drain_ledger(state)
        if not records:
            return update
        return {**update, "messages": [*(update.get("messages") or []), *records]}

    return _wrapped


@_with_ledger
async def builder_ask(state: AgentState) -> dict:
    """ONLY collection node that interrupts — one wizard_interrupt() per visit."""
    writer = get_writer()
    bs = _bs(state)
    # Everything below — the handoff lane's undo / delegate_rest / narrow_pois
    # tools included (interject_tools._bs) — must write the copy this node
    # RETURNS. They read state["campaign_builder_state"]; left pointing at the
    # input dict, their key reassignments were overwritten by our return.
    state = {**state, "campaign_builder_state": bs}
    action = bs.get("next_action") or {}
    # Resume safety: an in-flight checkpoint may reference a slot removed in a
    # deploy (the campaign intake rebuild collapsed nine slots into one). Rather
    # than KeyError, clear the stale action and let builder_plan re-route onto
    # the current slot set (already-filled keys survive and prefill the form).
    slot = SLOTS.get(action.get("slot"))
    if slot is None:
        logger.info("builder_ask: stale slot %r — re-planning", action.get("slot"))
        bs["next_action"] = None
        return {"campaign_builder_state": bs}

    # Wizard parity: dynamic options / prompt / radius-picker map the static
    # registry config lacks.
    overrides = await _enrich_slot_ask(slot, bs, state, writer)

    # Plain step_key swap (e.g. radius-only maid stepper when lookback is known).
    step_key_override = overrides.pop("_step_key_override", None)
    # The intake form carries its prefill inside form_schema field suggestions,
    # so it takes no top-level prefill.
    prefill = None if slot.name == "campaign_intake" else prefill_for(slot, state.get("user_info") or {})
    # `wizard_interrupt` itself now defaults `edit_base` to every appendable
    # field's current value (`_resolve_edit_base`), overlaid with whatever
    # `overrides` supplies here — `_enrich_slot_ask` may hand in its own
    # partial base (the store-anchor confirm does; it owns only its field),
    # and that partial base no longer starves every OTHER field the way a
    # local `setdefault` here used to.
    try:
        result = await wizard_interrupt(
            writer,
            step_key=step_key_override or slot.step_key,
            context=f"campaign builder — collecting {slot.name}",
            state=state,
            prefill=prefill,
            prefill_source="intent_extraction" if prefill else None,
            **overrides,
        )
    except _wizard_exit_class():
        # Off-path budget exhausted / escape menu → route to chatbot rather than
        # letting WizardExitRequested escape the subgraph unhandled. (GraphInterrupt
        # is NOT caught here — it is not a WizardExitRequested — so the interrupt
        # still bubbles to the framework and pauses the graph.)
        logger.info("builder_ask %s: user exit requested — routing to chatbot", slot.name)
        # KEEP the scratch. `bs` holds every answered slot, the discovered POIs,
        # the audience, the brief and the plan; `_bs` is a shallow copy, so the
        # only thing that persists it is this diff. Writing None here meant a
        # confused user who went off-path eight times lost the entire build —
        # the single most destructive behaviour on the unhappy path. Clearing
        # `next_action` is enough to stop the loop; builder_plan picks up exactly
        # where this left off when the user says "continue".
        bs["next_action"] = None
        return {
            "campaign_builder_state": bs,
            "next_nodes": ["chatbot"],
            "pending_action": None,
            "wizard_failure": "user_exit",
        }

    # The radius-map emit guards are set on `bs` by _enrich_slot_ask on THIS
    # replay pass and ride out in the returned diff. An edit answer (e.g. "keep
    # top 10") re-asks the same slot next visit, where the stale guard suppressed
    # the map — so the ring picker never showed the edited POI set. The ask is
    # answered; drop the guards so the re-ask re-emits.
    for _ws_key, _flag in (("maid_ws", "_poi_radius_map_emitted"),
                           ("geo_ws", "_radius_km_map_emitted"),
                           ("geo_ws", "_competitor_radius_map_emitted")):
        if isinstance(bs.get(_ws_key), dict) and _flag in bs[_ws_key]:
            bs[_ws_key] = {k: v for k, v in bs[_ws_key].items() if k != _flag}

    filled = dict(bs.get("filled") or {})
    update: dict = {"campaign_builder_state": bs}

    # A resolved interrupt is proof the planner is not livelocking — the user
    # just answered. _MAX_PLAN_ITERATIONS exists to bound a runaway plan→act→plan
    # loop WITHIN a turn, but `iteration` only ever incremented, so a long or
    # much-revised build hit 40 and then re-failed on every future entry with its
    # scratch intact and unreachable. Reset here so the budget means what it says.
    bs["iteration"] = 0

    # Per-turn read of the user's answer for the narrator (mirror their words,
    # answer an embedded question, adapt tone + length). Computed from `bs`
    # BEFORE the slot is written below, so a re-answer of the same slot is still
    # detectable. No reducer — consumed by the next flush, cleared next turn.
    update["user_turn"] = _read_user_turn(result, slot, bs)

    # Park any cross-step edit the resume router accepted during this interrupt.
    # builder_plan commits it and rolls back whatever it invalidates. Before this,
    # `result.edits` was read by exactly ONE slot (competitor_anchor_confirm,
    # below) and silently discarded for the other 22 — the user was told
    # "Updated <field>" and the build carried on with the old value.
    #
    # competitor_anchor_confirm excludes _ANCHOR_OWNED_FIELDS because the branch
    # below owns those: it applies them itself via a targeted re-geocode rather
    # than a full geo-stage rollback, which would throw away the confirmed
    # anchors. Every OTHER field an edit names there ("also change my budget")
    # still needs to reach apply_pending_edits — stashing unconditionally (with
    # only the owned keys excluded) is what used to be a full skip and silently
    # dropped anything that wasn't an anchor.
    stash_edits(bs, result, exclude=(
        _ANCHOR_OWNED_FIELDS if slot.name == "competitor_anchor_confirm" else ()
    ))

    # Anchor confirm edit re-run: the user changed the store-anchor set at the
    # geo_confirm_store_anchor step ("add another store"). wizard_interrupt returned
    # early (rerun_on_edit) with the merged addresses. Apply them to the anchor slot,
    # reset the geocode/map scratch so _enrich_slot_ask re-geocodes + re-emits a fresh
    # map, and leave competitor_anchor_confirm UNfilled so the planner re-asks it.
    if slot.name == "competitor_anchor_confirm":
        _anchor_edit = None
        # Delta lane first. This step's map is emitted `editable: True`, so its
        # search bar submits {"confirm":..,"added":[..],"removed":[..]} — and
        # `is_sentinel_resume` short-circuits any JSON to the confirm lane before
        # the classifier runs, so `.edits` is empty for it. The raw JSON then got
        # written into filled["competitor_anchor_confirm"] and NOTHING ever parsed
        # it (_apply_confirm_semantics only knows poi/plan/maid/go_live), so the
        # user's added or removed anchors were confirmed away unread.
        _anchor_delta = _parse_json_value(str(result), "{")
        if isinstance(_anchor_delta, dict) and (
            {"confirm", "added", "removed"} & set(_anchor_delta)
        ):
            if _anchor_delta.get("confirm") is False:
                bs["next_action"] = None      # re-ask; the map re-emits
                return update
            _cur = [
                a.strip() for a in str(filled.get("competitor_anchor", "")).split(",")
                if a.strip()
            ]
            _added = [str(x.get("name") or x) if isinstance(x, dict) else str(x)
                      for x in (_anchor_delta.get("added") or [])]
            _removed = {
                (str(x.get("name") or x) if isinstance(x, dict) else str(x)).strip().lower()
                for x in (_anchor_delta.get("removed") or [])
            }
            _next = [a for a in _cur if a.strip().lower() not in _removed]
            for _a in _added:
                if _a and _a.strip().lower() not in {c.strip().lower() for c in _next}:
                    _next.append(_a)
            if _next and _next != _cur:
                _anchor_edit = _next
            elif not _next:
                writer({"type": "thinking", "content": (
                    "Anchor delta would empty the anchor set — re-asking"
                )})
                bs["next_action"] = None
                return update
        _anchor_edits = getattr(result, "edits", None) or {}
        for _k in _ANCHOR_OWNED_FIELDS:
            if _anchor_edit:
                break                      # a delta already resolved this turn
            _v = _anchor_edits.get(_k)
            if _v:
                _anchor_edit = _v
                break
        if _anchor_edit:
            _addr_str = (
                ", ".join(str(x) for x in _anchor_edit)
                if isinstance(_anchor_edit, list) else str(_anchor_edit)
            )
            filled["competitor_anchor"] = _addr_str
            gw = dict(bs.get("geo_ws") or {})
            for _gk in ("_geocoded_anchors", "_anchor_confirm_map_emitted",
                        "_parsed_competitor_anchors"):
                gw.pop(_gk, None)
            bs["geo_ws"] = gw
            bs["filled"] = filled          # confirm stays unfilled → planner re-asks
            bs["next_action"] = None
            writer({"type": "thinking", "content": (
                f"Anchor edit at confirm: re-geocoding {_addr_str}"
            )})
            return update

    # Single-interrupt mode: the reply was an edit / question / reject, not an
    # answer to THIS slot. Its edits are stashed above; never write the raw text
    # into `filled` (a budget edit typed at poi_confirm used to land in the gate
    # as its "answer"). builder_plan applies the edits and re-asks this slot.
    if not getattr(result, "answered", True):
        bs["next_action"] = None
        bs["_reask_tick"] = True
        _log(bs, {"step": f"ask:{slot.name}", "summary": "not answered — re-planning"})
        return update

    # Publish mode: the three-way choice that decides how much of the campaign
    # Punk builds. Stored as the short token the routing tables key off, never as
    # the option label — the copy after the em-dash is free to change.
    if slot.name == "publish_mode":
        mode = _normalize_publish_mode(str(result))
        if not mode:
            # Unrecognized answer (someone typed prose instead of clicking) — leave
            # the slot unfilled so the planner re-asks with the three options.
            bs["next_action"] = None
            _log(bs, {"step": "ask:publish_mode", "summary": f"unmatched={str(result)[:40]!r}"})
            return update
        filled["publish_mode"] = mode
        bs["filled"] = filled
        bs["next_action"] = None
        _log(bs, {"step": "ask:publish_mode", "summary": f"mode={mode}"})
        return update

    # Campaign intake form: one JSON submission fills business, objective,
    # duration, budget and the objective-conditional destination. Validation
    # errors are stashed and the same form re-emits with them attached (the slot
    # stays unfilled). A non-JSON reply is treated as a form error, not an LLM
    # extraction — the form is the contract.
    if slot.name == "campaign_intake":
        values, errors = parse_intake_submission(str(result))
        if errors:
            bs["intake_errors"] = errors
            # Echo the submission back so the re-emitted form keeps what the
            # user typed instead of blanking out (see the values passthrough in
            # the campaign_intake ask branch).
            bs["intake_values"] = values
            bs["next_action"] = None
            _log(bs, {"step": "ask:campaign_intake", "summary": f"errors={list(errors)[:4]}"})
            return update
        bs.pop("intake_errors", None)
        bs.pop("intake_values", None)
        f_patch, ui_patch = intake_to_slots(
            values,
            # The express budget arrives in the ad account's minor units — the
            # same currency the ask branch built the widget's prefix and floor
            # from. Getting it from anywhere else is how they drift apart.
            currency=str((bs.get("media_ws") or {}).get("ad_account_currency") or "USD"),
            pixel_candidates=(bs.get("media_ws") or {}).get("pixel_candidates") or [],
        )
        filled.update(f_patch)
        bs["filled"] = filled
        cur_ui = state.get("user_info") or {}
        update["user_info"] = {
            k: v for k, v in ui_patch.items()
            if cur_ui.get(k) is None or isinstance(cur_ui.get(k), str)
        }
        _log(bs, {
            "step": "ask:campaign_intake",
            "summary": (
                f"name={str(filled.get('business_name', ''))[:40]} "
                f"obj={filled.get('objective', '')} budget={ui_patch.get('budget', '')}"
            ),
        })
        bs["next_action"] = None
        return update

    # Maid tuning slots (poi_radius_m + lookback_days). Both formats are accepted in
    # every path: a JSON payload ({"poi_radius_m":N,"lookback_days":M}) via the fast
    # path, OR a free-typed / widget-prose answer via the natural-language extractor
    # (_extract_maid_settings, any language). Which values we WRITE depends on the
    # ask:
    #   • combined maid_collect_settings (slot poi_radius_m, no override) → both.
    #   • radius-only maid_collect_poi_radius (override, lookback already known /
    #     event_based) → radius ONLY; the known lookback is never overwritten.
    #   • standalone maid_collect_lookback (slot lookback_days) → lookback ONLY; a
    #     prefilled radius is never touched.
    if slot.name in ("poi_radius_m", "lookback_days"):
        radius_only = step_key_override == "maid_collect_poi_radius"
        want_radius = slot.name == "poi_radius_m"
        want_lookback = slot.name == "lookback_days" or (want_radius and not radius_only)

        parsed = _parse_json_value(str(result), "{")
        pj = parsed if isinstance(parsed, dict) else {}
        r_val = pj.get("poi_radius_m") if want_radius else None
        l_val = pj.get("lookback_days") if want_lookback else None
        # Natural-language / prose fallback for anything JSON didn't supply.
        if (want_radius and r_val is None) or (want_lookback and l_val is None):
            extracted = await _extract_maid_settings(str(result), writer)
            if extracted:
                if want_radius and r_val is None:
                    r_val = extracted.poi_radius_m
                if want_lookback and l_val is None:
                    l_val = extracted.lookback_days

        # Server-side bounds: the frontend stepper enforces min/max, but that
        # is advisory only — the resume endpoint takes whatever JSON a request
        # sends. Without this, {"poi_radius_m": -99999, "lookback_days":
        # 100000} landed verbatim: a malformed ring and a 274-year lookback
        # window sliced into vendor calls against the shared monthly Unacast
        # call budget. Clamp to the same bounds the combined widget itself
        # ships (STEP_PROMPTS["maid_collect_settings"]["steppers"]).
        _maid_steppers = STEP_PROMPTS["maid_collect_settings"]["steppers"]
        if want_radius and r_val is not None:
            r_val = parse_int_safe(str(r_val), default=None)
        if want_lookback and l_val is not None:
            l_val = parse_int_safe(str(l_val), default=None)
        if r_val is not None:
            _clamped = _clamp_to_stepper(_maid_steppers[0], r_val)
            if _clamped != r_val:
                writer({"type": "thinking", "content": (
                    f"MAID: clamping poi_radius_m {r_val} -> {_clamped}"
                )})
            r_val = _clamped
        if l_val is not None:
            _clamped = _clamp_to_stepper(_maid_steppers[1], l_val)
            if _clamped != l_val:
                writer({"type": "thinking", "content": (
                    f"MAID: clamping lookback_days {l_val} -> {_clamped}"
                )})
            l_val = _clamped

        writes: list[tuple[str, Any]] = []
        if want_radius and r_val is not None:
            writes.append(("poi_radius_m", r_val))
        if want_lookback and l_val is not None:
            writes.append(("lookback_days", l_val))

        if writes:
            ui_patch: dict = {}
            cur_ui = state.get("user_info") or {}
            for sub_name, raw_val in writes:
                val = _normalize_slot_answer(sub_name, str(raw_val))
                filled[sub_name] = val
                patch = _slot_user_info_patch(SLOTS[sub_name], val)
                ui_patch.update({k: v for k, v in patch.items()
                                 if cur_ui.get(k) is None or isinstance(cur_ui.get(k), str)})
            if ui_patch:
                update["user_info"] = ui_patch
            bs["filled"] = filled
            if want_radius and r_val is not None:
                bs["_poi_ring_specs"] = []      # one ring for EVERY spot: no per-group override survives it
            _log(bs, {"step": "ask:maid_settings",
                      "summary": f"radius={filled.get('poi_radius_m', '')} "
                                 f"lookback={filled.get('lookback_days', '')}"})
            bs["next_action"] = None
            return update
        # Nothing resolved (couldn't parse the value) → fall through to the generic
        # single-slot write below, preserving prior behavior for odd input.

    # Plain-text slots: strip conversational wrapping ("my business name is X" → "X")
    # before the write. Skip widget-JSON / empty payloads (same guard as
    # _read_user_turn) so the LLM never fires on a sentinel. Cache by raw string in
    # scratch (mirrors _cached_parse) so a checkpoint replay doesn't re-issue the call.
    raw_answer = str(result)
    if slot.name in _SLOT_EXTRACTION and raw_answer.strip() and raw_answer.strip()[:1] not in ("{", "["):
        cache = dict(bs.get("_slot_extract") or {})
        entry = cache.get(slot.name)
        if isinstance(entry, dict) and entry.get("raw") == raw_answer:
            cleaned = entry.get("value")
        else:
            cleaned = await _extract_slot_value(slot.name, raw_answer, writer)
            cache[slot.name] = {"raw": raw_answer, "value": cleaned}
            bs["_slot_extract"] = cache
        if cleaned:
            result = cleaned

    # Conversational option / value steps: resolve (deterministic maps → LLM),
    # else RE-ASK (bounded) instead of silently mis-picking. Generalizes the
    # location_scope re-ask pattern to every collection step, so a user who TYPES
    # an answer ("i want it to be sales") at a widget gets the right slot value.
    if slot.name in _ENUM_SLOTS or slot.name in _RESOLVE_VALUE_SLOTS:
        if slot.name in _ENUM_SLOTS:
            resolved = await _resolve_enum_slot(slot.name, str(result), bs, writer)
        else:
            resolved = await _RESOLVE_VALUE_SLOTS[slot.name](str(result), bs, writer)
        if resolved is None:
            if _register_unresolved(bs, slot.name):
                resolved = _escape_value(slot.name, bs, str(result))
            else:
                _reframe_unresolved(state, slot.name, str(result), writer)
                bs["filled"] = filled          # slot stays unfilled → planner re-asks
                bs["next_action"] = None
                return update
        else:
            _clear_unresolved(bs, slot.name)
        result = resolved

    filled[slot.name] = _normalize_slot_answer(slot.name, str(result))

    ui_patch = _slot_user_info_patch(slot, filled[slot.name])
    if ui_patch:
        # Don't stomp list-typed extraction values with raw answer strings.
        cur_ui = state.get("user_info") or {}
        ui_patch = {k: v for k, v in ui_patch.items()
                    if cur_ui.get(k) is None or isinstance(cur_ui.get(k), str)}
        if ui_patch:
            update["user_info"] = ui_patch

    bs["filled"] = filled
    _log(bs, {"step": f"ask:{slot.name}", "summary": filled[slot.name][:80]})
    bs["next_action"] = None
    return update


async def _run_media_overlay(
    state: AgentState, bs: dict, update: dict, node_fns: tuple,
    live: Optional[dict] = None,
) -> dict:
    """Run a sequence of media executor nodes over a state overlay, threading
    media_wizard_state / user_info between them. Persists media_ws back onto bs,
    merges any user_info onto ``update``, and returns the accumulated ui_patch.

    Shared by connect_meta (auth + ad account) and resolve_meta (pixel). The
    media nodes read marketing_plan/campaign_brief only for narration context, so
    an empty brief/plan (connect_meta runs before either exists) is fine.

    ``live``, when passed, is ``builder_act``'s ``_live`` registry — this
    registers ``media_ws`` there too (seeded before the loop AND re-bound after
    every node_fn, since a node inside may itself pause or exit without
    returning) so an edit an executor stashed onto the working copy survives a
    WizardExit / error return the same way geo_ws and maid_ws already do; see
    the exit/error handlers below.

    The seed-before-loop half matters because the executors (media.py) now
    stash directly onto ``view["media_wizard_state"]`` — the exact dict object
    handed to them as ``state["media_wizard_state"]`` below — rather than their
    own private ``_ws()`` copy. Registering that SAME object in ``live`` before
    a node runs is what makes a stash visible even if the node never returns to
    the `upd = await node_fn(view)` line at all.
    """
    view = dict(state)
    view["media_wizard_state"] = bs.get("media_ws") or {}
    view["marketing_plan"] = bs.get("marketing_plan") or {}
    view["campaign_brief"] = bs.get("brief") or {}
    view["geo_data"] = _builder_geo(state, bs)
    ui_patch: dict = {}
    for node_fn in node_fns:
        if live is not None:
            live["media_ws"] = view["media_wizard_state"]
        upd = await node_fn(view)
        view["media_wizard_state"] = upd.get("media_wizard_state") or view["media_wizard_state"]
        if live is not None:
            live["media_ws"] = view["media_wizard_state"]
        if upd.get("user_info"):
            ui_patch.update(upd["user_info"])
            view["user_info"] = {**(view.get("user_info") or {}), **upd["user_info"]}
        for k, v in upd.items():
            if k not in ("media_wizard_state", "user_info", "pending_action"):
                update[k] = v
    bs["media_ws"] = dict(view["media_wizard_state"] or {})
    if ui_patch:
        update["user_info"] = {**(update.get("user_info") or {}), **ui_patch}
    return ui_patch


def _self_referential_exclusion_needs_store(
    *, det_type: str, store_addresses: str, unresolved_exclude_groups: list[str],
) -> bool:
    """True when an `audience_filter.exclude_groups` label named the user's
    own business ("my store", "one of my stores"...) but resolved to nothing
    because `store_set` was never activated and no address is on file yet —
    the exact gap `builder_act`'s maid_query repair path exists to close.
    Pulled out as a pure function (no `bs`/`state`) so it's testable without
    the rest of the executor's plumbing.

    False once `store_set` IS active — a still-unresolved self-reference at
    that point means the store's query failed or it was removed at the
    confirm gate, a different (and louder) failure already handled by
    `_assert_groups_fetched` inside `run_maid_query`, not this repair.
    """
    from app.services.maid_store import is_self_reference_label

    det_tokens = {t.strip() for t in det_type.split(",") if t.strip()}
    return (
        "store_set" not in det_tokens
        and not store_addresses.strip()
        and any(is_self_reference_label(g) for g in unresolved_exclude_groups)
    )


@_with_ledger
async def builder_act(state: AgentState, config: RunnableConfig) -> dict:
    """ONE expensive operation per visit (see module docstring for the set)."""
    writer = get_writer()
    bs = _bs(state)
    # Same as builder_ask: everything downstream (executors' wizard_interrupt
    # off-path counters, handoff tools) writes the copy this node RETURNS.
    state = {**state, "campaign_builder_state": bs}
    action = bs.get("next_action") or {}
    operation = action.get("operation")
    filled = dict(bs.get("filled") or {})
    update: dict = {}
    # An act that pauses on interrupt() replays from the top with every write
    # discarded. `take_act_scratch` returns the working scratch this act had
    # already built before that pause so the replay reads it instead of
    # re-fetching; it is popped, so it only ever spans one pause. `_live`
    # registers the copies this run mutates, for the GraphBubbleUp handler.
    _act_stamp = act_stamp(filled)
    _resumed_scratch = take_act_scratch(config, str(operation or ""), _act_stamp)
    bs.update(_resumed_scratch)
    # Empty exactly when this call has NO active interrupt chain to replay —
    # either a genuinely fresh dispatch, or the prior chain ended through an
    # exit that skipped save_act_scratch (`_GeoStepPaused`'s own clean return,
    # a WizardExitRequested, an error). Non-empty means we're mid-replay of a
    # task that is STILL paused on a live GraphInterrupt (save_act_scratch ran
    # in builder_act's own `except GraphBubbleUp`, below) — seen by the
    # `_locations_synced`/`_stores_synced` reads a few lines down.
    _is_fresh_dispatch = not _resumed_scratch
    _live: dict[str, dict] = {}

    try:
        if operation == "geo_discover":
            ws = _live["geo_ws"] = dict(bs.get("geo_ws") or {})
            # Every multi-value slot routes through the LLM list parser: these are
            # free-text interrupt answers, so a fixed separator can't be assumed
            # (comma joins "City, Country" pairs and address parts; users also write
            # "and"/"&"/"plus"). parse_list_input falls back to a comma/semicolon
            # split on any failure, so this is strictly more robust than str.split.
            location_names = await _cached_parse(
                ws, "_parsed_locations", str(filled.get("locations", "")), parse_location_names
            )
            # A confirm-step edit whose added name needed its OWN fresh
            # disambiguation interrupt (`_apply_location_edit` → `_do_geocode`,
            # executors/geo.py) raises a real GraphInterrupt from deep inside
            # this act. Once that chain FINISHES (the edit resolves and
            # `_GeoStepPaused` ends the task cleanly, or an error/exit path
            # returns without ever reaching a durable commit), the next FRESH
            # dispatch must read the merged set from `_locations_synced` — the
            # one place it survives when `filled["locations"]` was never
            # durably written (a `_GeoStepPaused` return, `_sync_confirm_edits`
            # below, is the normal durable path; this is the backstop for
            # every OTHER exit).
            #
            # `_is_fresh_dispatch` gates it to exactly that case. Applying it
            # while `_is_fresh_dispatch` is False — i.e. THIS call is replaying
            # a task still mid-chain on a live GraphInterrupt — is actively
            # WRONG: it changes which names `_do_geocode()`'s per-name loop
            # reaches interrupt() for, and in what order, relative to the
            # ORIGINAL (pre-pause) run. LangGraph matches a replayed task's
            # `Command(resume=...)` history to `interrupt()` calls purely by
            # ORDER WITHIN THE TASK (see `_GeoStepPaused`'s docstring) — an
            # extra name now resolving to an EARLIER interrupt() than it did
            # the first time round shifts every later index and feeds a stale
            # answer meant for one interrupt into a different one. (Confirmed
            # live: thread 844c2185-41aa-43db-814a-69adf0ac4d61 — the
            # disambiguate-location step's classify was fed the PRIOR turn's
            # "include Aurora" text, not the user's actual pick, because this
            # override moved aurora's probe ahead of the confirm step's own
            # interrupt on replay.)
            #
            # Safe against staleness: any edit through another path prunes
            # this key (edits._LOCATION_WS_KEYS) the moment it invalidates the
            # "geocode" unit; safe against an abandoned run because
            # take_act_scratch already refuses scratch whose act_stamp
            # (derived from `filled`) no longer matches.
            _locations_synced = ws.get("_locations_synced")
            if _locations_synced and _is_fresh_dispatch:
                location_names = list(_locations_synced)
            store_addresses_list = await _parse_addrs_never_drop(
                ws, str(filled.get("store_addresses", "")), "_parsed_store_addresses"
            )
            # Same reasoning, same class of pause, for the store_set confirm.
            _stores_synced = ws.get("_stores_synced")
            if _stores_synced and _is_fresh_dispatch:
                store_addresses_list = list(_stores_synced)
            # det_type may be a comma-joined set of composable angles (e.g. the
            # store_set+competitor_nearby pair). Parse once; every branch below
            # tests membership in this set, not the raw string.
            _det_subs = {
                s.strip() for s in str(filled.get("det_type", "")).lower().split(",")
                if s.strip()
            }
            targeting_type = str(filled.get("location_scope") or "granular_local")
            _poi_types_raw = str(filled.get("poi_types", ""))
            _poi_types_list = await _parse_poi_types_never_drop(ws, _poi_types_raw)
            extra_inputs: dict = {
                "poi_types_list": _poi_types_list,
                "brand_names_list": await _cached_parse(
                    ws, "_parsed_brand_names", str(filled.get("brand_names", "")), parse_brand_names
                ),
                "named_places_list": await _cached_parse(
                    ws, "_parsed_named_places", str(filled.get("named_places", "")), parse_brand_names
                ),
                "event_queries_list": await _cached_parse(
                    ws, "_parsed_event_queries", str(filled.get("event_queries", "")), parse_event_queries
                ),
                "store_addresses_list": store_addresses_list,
                # Per-angle overrides (divergent where/what). Absent → the executor
                # uses the shared flat lists above (legacy path). Each spec carries an
                # angle's own locations + types; the executor filters each arm to them.
                "angle_specs": (state.get("user_info") or {}).get("geo_angle_specs") or [],
            }
            # `parse_poi_types` rewrites persona/interest phrases ("coffee lovers")
            # and no-venue place-visit phrases ("open house") into searchable venue
            # categories — tell the user once per distinct raw answer so a rewrite
            # isn't silent. Deterministic string compare, no extra LLM call. Keyed
            # on the raw answer (not a bare bool) so a LATER poi_types edit narrates
            # its own substitution instead of being swallowed by a once-per-build flag.
            if _poi_types_raw.strip() and bs.get("_poi_subst_acked") != _poi_types_raw:
                _raw_lower = _poi_types_raw.lower()
                _rewritten = [p for p in _poi_types_list if p.lower() not in _raw_lower]
                if _rewritten:
                    bs["_poi_subst_acked"] = _poi_types_raw
                    _kept_lower = {p.lower() for p in _poi_types_list}
                    _originals = [
                        s.strip() for s in _poi_types_raw.split(",")
                        if s.strip() and s.strip().lower() not in _kept_lower
                    ]
                    add_beat(
                        state, "answer",
                        {"stage": "poi_type_substitution", "originals": _originals, "rewritten": _rewritten},
                        fallback=(
                            f"Quick note — {', '.join(repr(o) for o in _originals)} "
                            f"{'isn’t' if len(_originals) == 1 else 'aren’t'} places I can search "
                            f"directly, so I targeted {', '.join(_rewritten)} instead."
                        ),
                    )
            # competitor_nearby also serves "the types I named, near my store" ("gyms
            # within 10 min of my supplement store"). The `poi_types` slot is
            # only_when=category — deliberately, since making it active here would make
            # it REQUIRED and add an ask to the plain "competitors near me" flow — so it
            # is never prefilled for this angle. Bridge the extracted near-shop types
            # from user_info under their OWN key (mirrors slots._store_location_fallback).
            #
            # Source is the dedicated `anchor_types` field (NOT poi_types): the extractor
            # routes near-my-shop types to anchor_types and city/market-wide types to
            # poi_types, so a category+competitor_nearby combo no longer collides. No
            # `category not in _det_subs` guard is needed — the two type sets are already
            # separate at extraction. Empty → the arm infers competitor types as before.
            if "competitor_nearby" in _det_subs:
                _ui_types = (state.get("user_info") or {}).get("anchor_types") or []
                if isinstance(_ui_types, str):
                    _ui_types = [_ui_types]
                extra_inputs["anchor_types_list"] = [
                    str(t) for t in _ui_types if str(t).strip()
                ]
            anchor_tool_log: list[dict] = []

            # radius scope: pin coordinates + ring size (slots radius_pin /
            # radius_km). The pin arrives as a {"lat": .., "lng": ..} JSON
            # answer from the map_interaction widget.
            pin = _parse_json_value(filled.get("radius_pin"), "{")
            if pin.get("lat") and pin.get("lng"):
                extra_inputs["lat"] = float(pin["lat"])
                extra_inputs["lng"] = float(pin["lng"])
            if str(filled.get("radius_km", "") or "").strip():
                extra_inputs["radius_km"] = parse_radius_float(
                    str(filled["radius_km"]), default=10.0
                )

            # event_based: date range narrows the venue search windows.
            if str(filled.get("event_date_range", "") or "").strip():
                extra_inputs["event_date_range"] = str(filled["event_date_range"]).strip()
            elif "event_based" in _det_subs:
                # The extractor left the event range empty ("who went to X in the last
                # 6 months" stated a recency, just not under this field). Inherit it —
                # the searched window then matches what the user said, instead of the
                # default year. The event date slot is never asked, so nothing else
                # would supply it.
                from app.graph.tools import event_range_from_days

                _ui = state.get("user_info") or {}
                _derived = event_range_from_days(_ui.get("lookback_days")) or event_range_from_days(
                    (_ui.get("audience_filter") or {}).get("window_days")
                )
                if _derived:
                    extra_inputs["event_date_range"] = _derived

            # competitor_nearby: geocode the user's OWN store(s) as the search
            # anchor(s) (wizard parity: geo_collect_store_anchor did this at
            # collection time; builder_act does it here, before the executor —
            # the executor only consumes the coordinates). Multiple outlets are
            # supported: the free-text answer is parsed like store_set addresses
            # and each outlet becomes one anchor.
            if "competitor_nearby" in _det_subs:
                extra_inputs["competitor_radius_km"] = parse_radius_float(
                    str(filled.get("competitor_radius_km") or ""), default=5.0
                )
                # Pair store_set+competitor_nearby: the shops collected for store_set
                # ARE the competitor search anchors — the competitor_anchor slot was
                # suppressed (skip_when_any), so source the addresses from the shared
                # store_addresses list. Pure competitor_nearby uses its own anchor ask.
                if "store_set" in _det_subs and store_addresses_list:
                    anchor_addrs = store_addresses_list
                else:
                    anchor_addrs = await _parse_addrs_never_drop(
                        ws, str(filled.get("competitor_anchor") or ""), "_parsed_competitor_anchors"
                    )
                hint = market_hint(location_names)
                # Reuse the single-anchor geocode builder_ask cached for the
                # radius-picker map instead of geocoding that outlet twice.
                # Cache the resolved anchor set so the executor's anchor-confirm
                # interrupt (which pauses this act) replays a read, not re-geocode,
                # on resume — mirrors store_set's _geocoded_stores.
                _anchor_cache = ws.get("_geocoded_anchors")
                anchors: list[dict] = (
                    list(_anchor_cache.get("list") or [])
                    if isinstance(_anchor_cache, dict) and _anchor_cache.get("addrs") == anchor_addrs
                    else []
                )
                if not anchors:
                    cached = ws.get("_anchor_geocoded")
                    for addr in anchor_addrs:
                        result = (
                            cached.get("result")
                            if isinstance(cached, dict) and cached.get("anchor") == addr
                            else None
                        )
                        if result is None:
                            result, _glog = await call_tool(
                                geocode_or_place,
                                {"location_name": addr, "market_hint": hint, "allow_coarse": True},
                                writer=writer, node_name="builder_geo_discover",
                            )
                            anchor_tool_log.append(_glog)
                        if isinstance(result, dict) and result.get("latitude"):
                            anchors.append(result)
                    ws["_geocoded_anchors"] = {"addrs": anchor_addrs, "list": anchors}
                if anchors:
                    extra_inputs["competitor_anchors"] = anchors
                    # Backward-compat scalars: the executor prefers competitor_anchors
                    # but falls back to these for old checkpoints. Seed from the first.
                    first = anchors[0]
                    extra_inputs["store_address"] = anchor_addrs[0]
                    extra_inputs["competitor_store_lat"] = float(first["latitude"])
                    extra_inputs["competitor_store_lng"] = float(first["longitude"])
                    extra_inputs["competitor_store_geocoded"] = first
                    # The anchor map + its confirmation interrupt live in the
                    # executor's competitor_nearby arm (replay-safe home, mirrors
                    # store_set) — NOT emitted here, so the anchor is actually
                    # waited on before the competitor search spends the API.

            # The entry gate now requires WHAT (business_description or
            # product_offer) before routing here, so user_info.business_description
            # is guaranteed non-empty. filled["business_desc"] is express intake's
            # later, more specific "what you sell & your edge" answer and still
            # wins when present.
            _geo_business_desc = (
                str(filled.get("business_desc") or "").strip()
                or str((state.get("user_info") or {}).get("business_description") or "").strip()
            )
            try:
                await _execute_deterministic(
                    targeting_type,
                    str(filled.get("det_type") or "ai_suggested"),
                    location_names,
                    _geo_business_desc,
                    writer,
                    extra_inputs,
                    ws,
                    state=state,
                    target_audience=str((state.get("user_info") or {}).get("target_audience") or ""),
                )
            except _GeoStepPaused:
                # One confirm/disambiguation step inside the geo pipeline just
                # resolved (a location was disambiguated, a location/store map
                # was confirmed, ...). More of the pipeline may still need
                # asking. Persist ws and end this act WITHOUT marking
                # geo_discover done — _next_step re-dispatches it as a FRESH
                # task next tick, which is what keeps every interrupt() call
                # the only one in its own task (see _GeoStepPaused's
                # docstring for why that matters: LangGraph matches
                # Command(resume=...) values to interrupt() calls by order
                # WITHIN one task, not by step_key).
                #
                # Log this as forward progress, not a repeat: without an entry
                # here, RECENT ACTIONS shows consecutive identical
                # "act: geo_discover" proposals with nothing in OPERATIONS
                # DONE, which the planner LLM misreads as the op failing twice
                # and answers with kind="fail" — a real user-visible false
                # "something broke" apology for a pipeline that is working
                # exactly as designed.
                _log(bs, {"step": "act:geo_discover", "summary": "paused — one confirm answered, re-dispatching"})
                # A location/store edit may have settled just before THIS pause
                # (e.g. the ambiguous name it added needed its own disambiguation
                # next) — sync it now so the re-dispatch below reads the edited
                # set instead of the stale pre-edit `filled["locations"]`. See
                # `_sync_confirm_edits`'s docstring.
                _sync_confirm_edits_undoable(ws, filled, bs, update, state)
                bs["geo_ws"] = ws
                bs["next_action"] = None
                bs["_reask_tick"] = True
                return {"campaign_builder_state": bs, **update}
            det = ws.get("_det_result") or {}
            # Before ANYTHING reads pois_found (the narration below, the
            # poi_confirm gate) — a fresh search must not silently un-drop
            # what an earlier "just the top 10" / "drop everything in Laval"
            # already removed. See the function docstring.
            _merge_map_added(bs, det)
            _reapply_poi_selection_specs(bs, det, writer)
            bs["geo_result"] = det
            tool_log = anchor_tool_log + (ws.pop("_det_tool_log", []) or [])
            update["tool_calls_log"] = tool_log

            # Geocode-first scope correction: the disambiguation probe resolves
            # what entity a bare name actually is ("Quebec" → the province),
            # which is ground truth over the pre-geocode scope guess. Sync it
            # into the filled slot + user_info mirror so the planner prompt,
            # progress display, and any re-run stay consistent.
            _resolved_scope = str(ws.get("_resolved_scope") or "")
            if _resolved_scope and str(filled.get("location_scope") or "") != _resolved_scope:
                filled["location_scope"] = _resolved_scope
                bs["filled"] = filled
                update["user_info"] = {
                    **(update.get("user_info") or {}), "geo_scope": _resolved_scope,
                }

            # Confirm-step location/store edit sync: when the user edited the set at
            # the geo confirm step ("add whitehall"), the executor re-geocoded inside
            # its confirm loop and stashed the merged list in ws. Write it back to the
            # slot (executor input on any re-run) + the user_info prefill mirror so the
            # progress chips, campaign brief, and later runs match what was confirmed.
            _sync_confirm_edits_undoable(ws, filled, bs, update, state)

            if not det.get("pois_found"):
                _log(bs, {"step": "act:geo_discover", "summary": "no POIs found"})
                bs["geo_ws"] = ws
                bs["next_action"] = None
                return {
                    "campaign_builder_state": bs,
                    "current_turn_tool_errors": [e for e in tool_log if e.get("status") == "error"] or None,
                    "wizard_failure": "geo_targeting_unresolved",
                    **update,
                }

            # Same POI map + insight the wizard's geo_show_pois emits; the
            # poi_confirm exit gate that follows is the wizard's
            # geo_pois_confirmation. Pure store_set skips the map — the stores ARE
            # the POIs and were already confirmed visually inside
            # _execute_deterministic. But the store_set+competitor_nearby pair DOES
            # show the map: the competitor POIs are new and need the confirm gate,
            # so skip only when store_set is the SOLE angle.
            det_subtype = (det.get("targeting_type") or "/").split("/")[-1]
            _result_subs = {s.strip() for s in det_subtype.split(",") if s.strip()}
            if _result_subs != {"store_set"}:
                # `filled` doesn't carry competitor_radius_km's freshly-parsed value
                # until the next turn commits it, so pass extra_inputs' own copy here
                # rather than routing through the shared helper's `filled` param —
                # the RE-emit in _enrich_slot_ask reads it from `filled` instead,
                # once it has settled into a real slot value.
                _poi_map_event = _poi_preview_map_event(
                    det, ws, {**filled, "competitor_radius_km": extra_inputs.get("competitor_radius_km")},
                )
                if _poi_map_event:
                    writer(_poi_map_event)
            # Same POI-found reveal the maid milestone uses below: record a beat
            # (NOT a direct emit) so the next pause's flush_narration weaves it
            # into ONE composed message with the poi_confirm step framing —
            # avoids the stacked "Great news!…Got it." double message + missing
            # separator. The composer's grounding pack names the real spots.
            # `business` is intentionally NOT passed — it's available in the
            # grounding pack for reference, and re-stamping the store name on the
            # spots-found reveal reads robotic. This beat showcases the NEW result:
            # the count + type of spots found.
            # Per-angle breakdown so a COMBINED run (several composable angles fanned
            # into one POI set) narrates each strategy + what it contributed, instead
            # of the composer improvising against a bare count + comma string. Single
            # angle → combined=False → the composer's unchanged single-angle path.
            _angles, _combined = build_angle_breakdown(det, ws)
            _poi_count = int(det.get("pois_found", 0))
            # Angles that yielded NOTHING. build_angle_breakdown deliberately keeps
            # them (count 0) so the caller can see the full requested set — without
            # surfacing them the reveal silently under-delivers on what Punk promised
            # ("hospitals AND trade shows" → only trade shows found, user never told).
            _empty = [a["label"].lower() for a in _angles if a["count"] == 0]
            if _combined:
                _labels = [a["label"].lower() for a in _angles if a["count"] > 0]
                _joined = (
                    ", ".join(_labels[:-1]) + f", and {_labels[-1]}"
                    if len(_labels) > 1 else (_labels[0] if _labels else "")
                )
                _geo_fallback = (
                    f"Combined **{len(_labels)}** targeting approaches — {_joined} — "
                    f"into **{_poi_count}** real-visitor spots, all plotted on the map above."
                )
            else:
                _geo_fallback = (
                    f"Found **{_poi_count}** targeting location(s) "
                    "— all plotted on the map above."
                )
            if _empty:
                _geo_fallback += (
                    f" I couldn't find any spots for: {', '.join(_empty)}."
                )
            update.update(await wizard_milestone_narrate(
                writer, state, "geo_complete",
                facts={
                    "poi_count": _poi_count,
                    "det_type": det_subtype,
                    "angles": _angles,
                    "combined": _combined,
                    "missing_angles": _empty,
                },
                fallback=_geo_fallback,
            ))
            bs["geo_ws"] = ws
            # Term-level misses (a specific named place/event query that found
            # zero venues — e.g. "SneakerCon" — as opposed to `_empty` above,
            # which is angle-level). geo.py stamps these on `ws` but nothing
            # downstream ever read them, so the narrator/grounding pack had no
            # way to tell a not-found search term apart from a real, found POI
            # label and would describe it as one anyway. Persist onto `det`
            # (-> state["geo_data"], durable) so grounding._build_geo can keep
            # it out of the "these are real spots" fields.
            _not_found = ws.get("_det_named_not_found") or []
            if _not_found:
                det["not_found_labels"] = _not_found
            # Commit the geo result to state NOW (shallow-merge reducer), not only
            # at builder_finalize — the narrator grounding pack reads
            # state["geo_data"], so without this the poi_confirm pause composes
            # against empty grounding and the composer invents spots / mislabels
            # counts.
            update["geo_data"] = det
            _log(bs, {"step": "act:geo_discover", "summary": f"pois={int((bs.get('geo_result') or {}).get('pois_found', 0))}"})

        elif operation == "maid_query":
            ws = _live["maid_ws"] = dict(bs.get("maid_ws") or {})
            geo = _builder_geo(state, bs)
            ws["poi_radius_m"] = parse_radius_float(str(filled.get("poi_radius_m", "")), default=None)
            ws["lookback_days"] = parse_int_safe(str(filled.get("lookback_days", "")), default=None)
            ws["poi_ring_specs"] = list(bs.get("_poi_ring_specs") or [])
            # det_type is a comma-joined SET, so a bare == fails for a combo like
            # "event_based,named_places". It only worked because the substring test
            # on targeting_type ("<scope>/<a,b>") happened to catch it — by accident,
            # not design. Split to tokens like every other det_type read.
            _det_tokens = {
                t.strip() for t in str(filled.get("det_type", "")).lower().split(",")
                if t.strip()
            }
            ws["is_event_based"] = (
                "event_based" in str(geo.get("targeting_type") or "")
                or "event_based" in _det_tokens
            )
            # Layering the user stated up front ("gym-goers who go 3+ times a
            # week") — seed it once from extraction; a mid-turn edit
            # (_apply_maid_audience_filter_edit) or a session-cache restore
            # take priority and are handled inside run_maid_query itself.
            _user_info = state.get("user_info") or {}
            if geo.get("audience_filter") is None and _user_info.get("audience_filter"):
                geo["audience_filter"] = dict(_user_info["audience_filter"])
            # Banned-attribute audience request ("white women", "lesbian ...")
            # — narrate the refusal once, never apply it. Flagged on `bs` (not
            # `ws`) so it survives the executor's own resume boundary and
            # still fires exactly once per build.
            _blocked = _user_info.get("blocked_attributes")
            if _blocked and not bs.get("_blocked_attrs_acked"):
                bs["_blocked_attrs_acked"] = True
                add_beat(
                    state, "answer",
                    {"stage": "audience_policy", "blocked": _blocked},
                    fallback=(
                        f"Quick note — Meta no longer allows targeting by "
                        f"{', '.join(a.replace('_', ' ') for a in _blocked)}, so I "
                        "left that out. I'm building the audience from everything "
                        "else you gave me (age, gender, and the places/behavior you "
                        "described) instead."
                    ),
                )
            session_id = (config.get("configurable") or {}).get("thread_id", "unknown")
            try:
                result = await run_maid_query(state, ws, geo, writer, str(session_id))
            except Exception as exc:
                # Tagged separately from the generic outer `except Exception` below
                # (which would report this identically to any other operation's
                # failure, as "builder_act_failed" — indistinguishable in logs from
                # a campaign-brief or publish failure). Mirrors the
                # `campaign_publish_failed:` prefix pattern (nodes.py's
                # _failure_msgs) so the wizard_failure code alone says WHICH op
                # AND which exception type broke, without a log hunt.
                logger.error("builder_act maid_query failed: %s", exc, exc_info=True)
                _log(bs, {"step": "act:maid_query", "summary": f"error: {exc}"})
                bs.update(_live)
                bs["next_action"] = None
                return {
                    "campaign_builder_state": bs,
                    "wizard_failure": f"maid_query_failed:{type(exc).__name__}",
                    **update,
                }
            bs["maid_ws"] = ws
            bs["geo_result"] = geo
            # Commit the maid-enriched geo to state NOW (shallow-merge reducer) so
            # the maid_confirm pause's grounding pack carries the real audience
            # count instead of leaving the composer to mislabel the POI count.
            update["geo_data"] = geo

            # The query genuinely failed (budget/breaker/IP/an un-splittable
            # timeout) — as opposed to running and honestly finding nobody —
            # and there is nothing to show for this turn. Do NOT mark the op
            # done: run_maid_query swallowing the failure into a clean-looking
            # zero used to let `_mark_op_done` below close the maid stage, so
            # the exit gate (`maid_confirm`) asked a bare "does this look
            # right?" and a plain "yes" satisfied it — closing the build with
            # zero audience and no way back (thread a10b211a). Recorded on
            # `bs`, not `geo`, so it survives the shallow-merge into
            # AgentState and `_next_step` can see it next planner visit.
            if result.get("failure_kind") and not result["filtered_maid_count"]:
                bs["maid_retry_pending"] = {
                    "kind": result["failure_kind"],
                    "failed_keys": sorted(
                        {k for _l in result["maid_tool_log"] for k in (_l.get("failed_keys") or ())}
                    ),
                }
                _log(bs, {"step": "act:maid_query", "summary": f"failed: {result['failure_kind']}"})
                update["tool_calls_log"] = result["maid_tool_log"]
                update["current_turn_tool_errors"] = [
                    e for e in result["maid_tool_log"] if e["status"] == "error"
                ] or None
                bs["next_action"] = None
                return {"campaign_builder_state": bs, **update}

            bs["maid_facts"] = {k: result[k] for k in
                                ("maid_count", "filtered_maid_count", "pois_found",
                                 "date_context", "lookback_days", "poi_radius_m")}
            _log(bs, {"step": "act:maid_query", "summary": f"maids={result['filtered_maid_count']}"})
            maid_errors = [e for e in result["maid_tool_log"] if e["status"] == "error"] or None
            update["tool_calls_log"] = result["maid_tool_log"]
            update["current_turn_tool_errors"] = maid_errors
            # REPAIR, not a dead end: "exclude anyone who's been to my store"
            # named a self-reference (see maid_store.is_self_reference_label)
            # that resolved to nothing because the store was never collected
            # in the first place — the user hasn't given an address yet and
            # `store_set` never turned on (prompts.py rule 4c should catch
            # this up front; this is the safety net for the phrasings it
            # misses, or a self-reference surfacing only on a later turn).
            # Rather than report a dead "not found" and ship the audience
            # unfiltered, activate `store_set` (the SAME move an edit makes
            # via `edits._activate_angle_for`) and roll back to the geocode
            # unit — `missing_required_slots` then asks `store_addresses` on
            # its own (Slot.only_when=("det_type","store_set"), slots.py:103)
            # before the geo/maid search re-runs. If the store WAS collected
            # and the exclusion still failed (removed at the confirm gate, or
            # its query errored), this does not fire — that case already
            # raises loudly via `_assert_groups_fetched` inside `run_maid_query`.
            _unresolved_exclude = (geo.get("audience_filter") or {}).get("_unresolved_exclude_groups") or []
            if _self_referential_exclusion_needs_store(
                det_type=str(filled.get("det_type") or ""),
                store_addresses=str(filled.get("store_addresses") or ""),
                unresolved_exclude_groups=_unresolved_exclude,
            ):
                from app.graph.builder.edits import invalidate_from
                from app.graph.builder.slots import merge_angle_tokens

                filled["det_type"] = merge_angle_tokens(filled.get("det_type"), "store_set")
                bs["filled"] = filled
                invalidate_from(bs, filled, "geocode")
                bs["next_action"] = None
                update["user_info"] = {
                    **(update.get("user_info") or {}),
                    "deterministic_subtype": [
                        t for t in filled["det_type"].split(",") if t
                    ],
                }
                _log(bs, {"step": "act:maid_query", "summary": (
                    "exclude-my-store: no address on file — activating store_set"
                )})
                writer({"type": "thinking", "content": (
                    "MAID: audience_filter excludes the user's own store, but no "
                    "store address is known yet — activating store_set so it's "
                    "asked for, then re-running the search with it"
                )})
                return {"campaign_builder_state": bs, **update}
            # Same audience-found milestone the maid wizard narrates.
            _radius = result["poi_radius_m"]
            # A group named in "both X and Y" (etc.) that never resolved to a
            # real POI (maid.py's first-mention resolve) — say so plainly
            # rather than letting the count quietly be a narrower match than
            # what was asked for. See maid.py's `_unresolved_groups` stamp.
            # `_unresolved_exclude` (above) is the SAME situation for
            # exclude_groups, kept separate because it means an exclusion the
            # user asked for was never applied — worse than a missing
            # POSITIVE group, and the narrator needs to say so, not fold it
            # into "this isn't the overlap you asked for".
            _unresolved = (geo.get("audience_filter") or {}).get("_unresolved_groups") or []
            _unresolved_note = (
                f"Heads up — **{', '.join(_unresolved)}** wasn't found in the data, "
                "so this is NOT the overlap you asked for — it's everyone found "
                "at the remaining spot(s). "
            ) if _unresolved else ""
            _unresolved_exclude_note = (
                f"Heads up — I couldn't apply your exclusion for "
                f"**{', '.join(_unresolved_exclude)}**, so those visitors are still "
                "in this audience. "
            ) if _unresolved_exclude else ""
            # The headline is the FILTERED, actually-publishable count — the
            # raw superset (`result["maid_count"]`) rides along only as
            # "before filter" context. Three outcomes, not two: a real
            # audience, a real superset the active filter narrowed to
            # nobody (say so + offer to relax it — never present 0 as if it
            # were the found audience), or genuinely nobody detected at all.
            _shown_count = result["filtered_maid_count"]
            _raw_count = result["maid_count"]
            if _shown_count > 0:
                _fallback = (
                    f"Found **{_shown_count:,} verified visitors** detected at your {result['pois_found']} spots during {result['date_context']}. "
                    + (
                        f"**{result['repeat_visitor_count']:,} of them ({result['repeat_visitor_pct']}%)** "
                        + ("came back on more than one day" if result["visit_basis"] == "visits" else "were detected more than once")
                        + " — your repeat crowd. "
                        if result["repeat_visitor_count"] > 0 else ""
                    )
                    + "Their devices were picked up on-site, so your ads reach those exact people — and Meta expands delivery to a lookalike audience matched on that real visitation behavior."
                )
            elif result["maid_filter_zeroed"]:
                _chips = ", ".join(result["audience_filter_chips"]) or "your narrowing"
                _fallback = (
                    f"Found **{_raw_count:,} people** at your {result['pois_found']} spots during {result['date_context']}, "
                    f"but your narrowing (**{_chips}**) matched none of them. Want me to loosen one of those "
                    "and try again?"
                )
            else:
                _fallback = (
                    f"No real visitors turned up at those {result['pois_found']} spots during {result['date_context']}. "
                    "We can still target the area itself — Meta will show your ads to people nearby."
                )
            _reveal_facts = {
                "audience_count": _shown_count,
                "audience_count_before_filter": _raw_count,
                "active_filter": result["audience_filter_chips"],
                "filter_zeroed": result["maid_filter_zeroed"],
                "poi_count": result["pois_found"],
                "radius_m": round(_radius / 100) * 100 if _radius else None,
                "lookback_days": result["lookback_days"],
                "confidence_pct": 95 if _shown_count > 10000 else 94 if _shown_count > 2000 else 93 if _shown_count > 500 else 92,
                "date_context": result["date_context"],
                # Frequency: `visit_basis` = "visits" (timestamped) or
                # "sightings" (no timestamp). Composer labels accordingly.
                "visit_basis": result["visit_basis"],
                "repeat_visitor_count": result["repeat_visitor_count"],
                "repeat_visitor_pct": result["repeat_visitor_pct"],
                "frequency_buckets": result["visit_buckets"],
                "max_frequency": result["max_seen"],
                "unresolved_audience_groups": _unresolved,
                "unresolved_exclude_groups": _unresolved_exclude,
            }
            # Only present when audience_filter reads as a role predicate
            # (min_weekly_hours or a presence-pattern field) — see
            # maid_query.is_role_spec/role_confidence. NEVER gates the
            # returned audience; role targeting is never refused. This is
            # the SPOKEN half of the disclosure (see BEAT_HINTS["reveal"]
            # for how the composer is told to use it) — gated by presence,
            # not `is None`, so an ordinary non-role turn's facts stay
            # exactly as they were before this feature, with no null noise
            # for the composer's "surface only what's here" reading to trip
            # over.
            if result.get("role_confidence") is not None:
                _reveal_facts["role_confidence"] = result["role_confidence"]
                _reveal_facts["role_basis"] = result.get("role_basis")
                _reveal_facts["dwell_measurable_device_pct"] = result.get("dwell_measurable_device_pct")
            update.update(await wizard_milestone_narrate(
                writer, state, "maid_audience_found",
                facts=_reveal_facts,
                fallback=_unresolved_note + _unresolved_exclude_note + _fallback,
            ))

        elif operation == "enrich_website":
            # Wizard parity (campaign_enrich_website): scrape the site and LLM-
            # extract business context into bs["enrichment"]. Non-interrupting and
            # graceful — an empty/failed scrape yields empty enrichment.
            from app.graph.tools import fetch_website_text
            from app.graph.prompts import WEBSITE_ENRICHMENT_GROUNDED_PROMPT, WEBSITE_ENRICHMENT_PROMPT
            import json as _json

            cur_ui = state.get("user_info") or {}
            url = str(filled.get("website_url") or cur_ui.get("website_url") or "").strip()
            enrichment: dict = {}
            ui_patch: dict = {}
            scraped_pixel_id = None
            if not url:
                # No site to scrape — the brief would otherwise run on the business
                # name alone. A business name IS enough to ground a live search
                # lookup for the same fields; no name means nothing to search for.
                business_name = str(cur_ui.get("business_name") or "").strip()
                if business_name:
                    from app.graph.grounding import grounded_text

                    location = ", ".join(str(loc) for loc in (cur_ui.get("location") or [])) or "unknown"
                    writer({"type": "update", "content": "No website given — looking up your business online..."})
                    try:
                        raw = await grounded_text(
                            WEBSITE_ENRICHMENT_GROUNDED_PROMPT.format(
                                business_name=business_name,
                                location=location,
                                extra_context=(
                                    f"What they sell: {cur_ui['product_offer']}"
                                    if cur_ui.get("product_offer") else ""
                                ),
                            )
                        )
                        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
                        enrichment = _json.loads(cleaned) if cleaned else {}
                    except Exception as exc:
                        logger.info("builder_act enrich_website: grounded lookup skipped/failed — %s", exc)
                        enrichment = {}
                    if enrichment.get("business_category") and not cur_ui.get("industry"):
                        ui_patch["industry"] = enrichment["business_category"]
                    if enrichment.get("products_services") and not cur_ui.get("business_description"):
                        ui_patch["business_description"] = ", ".join(enrichment["products_services"][:3])
                    summary_parts = []
                    if enrichment.get("business_category"):
                        summary_parts.append(f"Business type: {enrichment['business_category']}")
                    for offer in (enrichment.get("active_offers") or [])[:2]:
                        summary_parts.append(f"Offer: {offer}")
                    if summary_parts:
                        add_beat(state, "reveal", {"enrichment_summary": summary_parts},
                            fallback=(
                                "Here's what I found about your business online:\n"
                                + "\n".join(f"  • {p}" for p in summary_parts)
                                + "\n\nWe'll use this to tailor the ads to your brand."
                            ))
                bs["enrichment"] = enrichment
            else:
                writer({"type": "update", "content": "Fetching your website to learn about your business..."})
                page = await fetch_website_text(url)
                # Reported, never used as the campaign's pixel: a pixel on the
                # advertiser's SITE is not one on the ad account we publish to.
                # media_detect_pixel owns that, and the plan editor asks for it.
                scraped_pixel_id = page.get("pixel_id") if isinstance(page, dict) else None
                if not page.get("error") and page.get("text"):
                    try:
                        raw_enrich, _u = await tracked_ainvoke(
                            _make_llm(),
                            [SystemMessage(content=WEBSITE_ENRICHMENT_PROMPT), HumanMessage(content=page["text"])],
                            node_name="builder_act/enrich_website",
                            writer=writer,
                        )
                        enrichment = _json.loads(raw_enrich.text.strip())
                    except Exception as exc:
                        logger.warning("builder_act enrich_website: extraction failed — %s", exc)
                        enrichment = {}
                    summary_parts: list[str] = []
                    if enrichment.get("business_category"):
                        summary_parts.append(f"Business type: {enrichment['business_category']}")
                    for offer in (enrichment.get("active_offers") or [])[:2]:
                        summary_parts.append(f"Offer: {offer}")
                    if enrichment.get("primary_cta"):
                        summary_parts.append(f"CTA: {enrichment['primary_cta']}")
                    if scraped_pixel_id:
                        summary_parts.append(f"Meta Pixel detected: {scraped_pixel_id}")
                    if summary_parts:
                        # Beat (not direct emit): woven into the next pause's
                        # single composed message instead of stacking ahead of it.
                        add_beat(state, "reveal", {"enrichment_summary": summary_parts},
                            fallback=(
                                "Great — here's what I pulled from your site:\n"
                                + "\n".join(f"  • {p}" for p in summary_parts)
                                + "\n\nWe'll use this to tailor the ads to your brand."
                            ))
                        if not cur_ui.get("business_description") and enrichment.get("products_services"):
                            ui_patch["business_description"] = ", ".join(enrichment["products_services"][:3])
                        if not cur_ui.get("industry") and enrichment.get("business_category"):
                            ui_patch["industry"] = enrichment["business_category"]
                bs["enrichment"] = enrichment
            # No objective auto-switch here, and no pixel ask anywhere: a conversion
            # objective with no account pixel opens the plan editor on the pixel
            # field instead (see generate_meta_json).
            bs["filled"] = filled
            if ui_patch:
                update["user_info"] = ui_patch
            _log(bs, {"step": "act:enrich_website",
                      "summary": f"site_pixel={'yes' if scraped_pixel_id else 'no'} "
                                 f"cat={enrichment.get('business_category', '-')}"})

        elif operation == "generate_brief":
            ui = _ui_view(state, bs)
            geo = _builder_geo(state, bs)
            # The intake form no longer asks for a budget — a number means nothing
            # before you have seen a plan. Start from the recommendation we already
            # derive from the objective, geo and audience size; the plan editor
            # shows it filled in and changes it at campaign or ad-set level.
            if not str(ui.get("budget") or "").strip():
                budget = await _recommended_budget(ui, geo, bs, writer)
                ui["budget"] = budget
                update["user_info"] = {**(update.get("user_info") or {}), "budget": budget}
            # Guide mode never asks for a business name (the entry gate only
            # requires what the business sells, not its name — see nodes.py's
            # WHAT signal), so the brief's own grounding rule ("MUST be exactly
            # user_info.business_name, or 'Your Business' if empty") would fall
            # back to a generic placeholder even when a real name is sitting in
            # enrichment or the connected Page. Backfill before the brief runs.
            if not str(ui.get("business_name") or "").strip():
                page_id = str(ui.get("meta_page_id") or "")
                page_name = next(
                    (
                        str(p.get("name") or "") for p in (bs.get("media_ws") or {}).get("page_candidates") or []
                        if str(p.get("id")) == page_id
                    ),
                    "",
                )
                derived_name = str((bs.get("enrichment") or {}).get("business_name") or "") or page_name
                if derived_name:
                    ui["business_name"] = derived_name
                    update["user_info"] = {**(update.get("user_info") or {}), "business_name": derived_name}
            writer({"type": "update", "content": "Building your campaign plan..."})
            try:
                brief = await generate_campaign_brief(
                    ui, geo, bs.get("enrichment") or {}, writer,
                    node="builder_act/generate_brief",
                )
            except CampaignGenerationError as exc:
                _log(bs, {"step": "act:generate_brief", "summary": f"error: {exc}"})
                bs["next_action"] = None
                return {
                    "campaign_builder_state": bs,
                    "tool_calls_log": [exc.log_entry],
                    "current_turn_tool_errors": [exc.log_entry],
                    "wizard_failure": "campaign_brief_generation_failed",
                }
            from app.graph.builder.executors.campaign import (
                reconcile_brief_budget,
                reconcile_brief_reach,
            )
            brief = reconcile_brief_reach(brief, ui)
            # Force the brief's DISPLAYED budget to the chosen budget so the plan
            # card + drafted-plan narration match the recommendation the user
            # accepted (the brief LLM otherwise invents its own number).
            brief = reconcile_brief_budget(brief, ui)
            bs["brief"] = brief
            # Guide mode never asks for the objective up front any more (see
            # generate_campaign_brief's OBJECTIVE-less meta_options branch) — the
            # brief picks one itself and reports it in brief["objective"]. Only
            # write it back when nothing already had an answer: an explicit
            # user-stated objective (chat extraction or express intake) always
            # wins, and build_campaign_spec hard-fails with no objective at all,
            # so a brief that returned nothing usable still gets a safe default.
            from app.graph.builder.executors.campaign import _normalize_objective
            if not str(ui.get("campaign_objective") or "").strip():
                inferred_objective = _normalize_objective(brief.get("objective")) or "AWARENESS"
                ui["campaign_objective"] = inferred_objective
                update["user_info"] = {
                    **(update.get("user_info") or {}), "campaign_objective": inferred_objective,
                }
                filled["objective"] = inferred_objective
                bs["filled"] = filled
            _log(bs, {"step": "act:generate_brief", "summary": "brief drafted"})
            # The drafted-plan milestone. It is now the ONLY thing framing the plan
            # before the editor opens.
            # NOTE: audience_count / reach_model are intentionally NOT passed here.
            # The real-visitor audience was already showcased on the maid screen
            # (it's in the narrator's ALREADY DELIVERED ledger) — re-headlining
            # "149,580 people who visited Provigo…" on the plan-confirm screen is
            # the repetition we're killing. This beat frames the DRAFTED PLAN
            # (objective + budget + dates), not the audience.
            # Pass CLEAN, reconciled figures so the narration can't restate the
            # brief LLM's invented budget/reach: a bare "$N/day" budget (the stored
            # value carries reach copy) and the reconciled reach from the brief.
            _clean_budget = _extract_budget_amount(ui.get("budget") or "") or (ui.get("budget") or "")
            _reach = str((brief.get("kpi_targets") or {}).get("reach") or "")
            update.update(await wizard_milestone_narrate(
                writer, state, "campaign_brief_drafted",
                facts={
                    "objective": ui.get("campaign_objective") or "",
                    "budget": _clean_budget,
                    "budget_type": ui.get("budget_type") or "",
                    "reach": _reach,
                    "start_date": ui.get("campaign_start_date") or "",
                    "end_date": ui.get("campaign_end_date") or "ongoing",
                },
                fallback="Draft plan ready. Review the details below before we move to publish.",
            ))
            # No plan card here: the plan_confirm editor immediately below shows
            # every field it would restate.

        elif operation == "generate_meta_json":
            # Deterministic assembly — no LLM. The brief (Gemini) supplies strategy,
            # naming and copy; every structural field Meta validates comes from
            # meta_spec's objective matrix. The previous second Pro call invented a
            # JSON document that publish then largely ignored.
            ui = _ui_view(state, bs)
            geo = _builder_geo(state, bs)
            brief = bs.get("brief") or {}
            writer({"type": "update", "content": "Building your Meta campaign..."})

            from app.services import meta_ads as _meta
            from app.graph.tools import resolve_poi_zips

            # Meta geo targeting is by ZIP code: read the unique postal codes the
            # POIs already carry from discovery and cache them on geo_data. Runs
            # here — after poi_confirm edits and maid trimming — so an edit-driven
            # rebuild reuses the cache. Pure (no network).
            resolve_poi_zips(geo)

            # Targeting variants. build_targeting is pure (its access_token
            # parameter is unused), so this is safe before any Graph API call.
            seed_targeting = await _meta.build_targeting(geo)
            broad_targeting = await _meta.build_targeting(geo, broad=True)

            try:
                tree = build_campaign_tree(
                    user_info=ui,
                    geo_data=geo,
                    brief=brief,
                    seed_targeting=seed_targeting,
                    broad_targeting=broad_targeting,
                    # A prospecting ad set is planned regardless; whether it gets a
                    # real lookalike id is decided at publish (bind_audiences
                    # degrades it to broad if the lookalike could not be built).
                    lookalike_targeting=broad_targeting,
                    # media_ws first: it carries the Page the user picked in the
                    # editor (mirrored by _apply_plan_form_submission), where
                    # user_info still holds Meta's arbitrary first Page.
                    page_id=(bs.get("media_ws") or {}).get("page_id") or ui.get("meta_page_id"),
                    instagram_user_id=(bs.get("media_ws") or {}).get("instagram_user_id"),
                    pixel_id=_resolved_pixel_id(bs, ui),
                )
            except SpecBuildError as exc:
                # A prerequisite no edit can supply (unknown objective, no Page, no
                # app). A conversion goal with no pixel is NOT this — it builds a
                # tree and is handed to the editor below.
                log_entry = {
                    "tool": "build_campaign_tree", "status": "error", "error_msg": str(exc),
                    "attempts": 1, "duration_ms": 0.0, "args": {},
                    "node": "builder_act/generate_meta_json",
                }
                _log(bs, {"step": "act:generate_meta_json", "summary": f"error: {exc}"})
                bs["next_action"] = None
                return {
                    "campaign_builder_state": bs,
                    "tool_calls_log": [log_entry],
                    "current_turn_tool_errors": [log_entry],
                    "wizard_failure": "campaign_meta_json_generation_failed",
                }

            # "Start from a previous campaign" is applied from inside the plan
            # editor now (_apply_template_action), not chosen up front — picking a
            # template is a judgement about a plan, and there is no plan yet here.
            try:
                spec = CampaignSpec.model_validate(tree)
            except ValidationError as exc:
                # A conversion goal whose pixel the ad account does not have. The
                # plan editor is the only place the pixel is asked, so hand it the
                # tree with the error attached — the same route an invalid user edit
                # takes (_apply_plan_form_submission). The objective the user chose
                # is left alone; they pick a pixel or change the goal in the editor.
                # jsonable_encoder because the raw tree carries datetimes and this
                # goes out over SSE — a validated spec is model_dump(mode="json").
                from fastapi.encoders import jsonable_encoder

                bs["marketing_plan_draft"] = jsonable_encoder(tree)
                bs["plan_errors"] = errors_to_form_keys(exc)
                _log(bs, {"step": "act:generate_meta_json",
                          "summary": f"invalid → editor: {list(bs['plan_errors'])[:3]}"})
            else:
                bs.pop("marketing_plan_draft", None)
                bs.pop("plan_errors", None)
                generated = spec.model_dump(mode="json")
                final = _merge_regenerated_plan(bs, state, generated)
                bs["plan_base"] = generated
                bs["marketing_plan"] = final
                _log(bs, {"step": "act:generate_meta_json",
                          "summary": f"adsets={len(final.get('adsets') or [])} objective={spec.objective.value}"})

        elif operation == "connect_meta":
            # OAuth + ad-account selection + pixel detection, up front (pre-act).
            # Runs right after the audience is confirmed so the intake questions +
            # brief have the user's Meta creds/ad account. media_detect_pixel reads
            # the account's Pixels here (objective-independent) so the plan editor's
            # pixel picker has real options; the objective-specific promoted_object
            # is still built in resolve_meta.
            from app.graph.builder.executors.media import (
                media_check_meta_auth,
                media_select_ad_account,
                media_detect_pixel,
                media_detect_page_assets,
            )
            ui_patch = await _run_media_overlay(
                state, bs, update,
                (media_check_meta_auth, media_select_ad_account, media_detect_pixel,
                 media_detect_page_assets),
                live=_live,
            )
            ui = {**_ui_view(state, bs), **ui_patch}
            if not ui.get("meta_access_token"):
                raise RuntimeError("Meta credentials unavailable after auth flow")
            if not ui.get("meta_ad_account_id"):
                # Connected, but Meta shared no ad account — media_check_meta_auth has
                # already asked twice for the user to create one and connect again.
                raise RuntimeError(
                    "Meta shared no ad account with Punk. Create one in Business settings "
                    "→ Accounts → Ad accounts, then connect Meta again and tick it on "
                    "Meta's consent screen."
                )
            # The Page's website, mirrored into the SLOT store: enrich_website's
            # prereqs are read from `filled`, and nobody asks for a URL any more,
            # so this is the only thing that lets the site scrape run at all.
            if ui_patch.get("website_url") and not filled.get("website_url"):
                filled["website_url"] = ui_patch["website_url"]
                bs["filled"] = filled
            # The account's own campaigns, offered in the plan editor as "start
            # from a previous campaign". Cached here rather than fetched at render
            # time: the editor re-renders on every save, and this is one Graph call
            # whose answer does not change mid-run.
            try:
                from app.services import meta_ads as _meta

                bs["previous_campaigns"] = await _meta.list_account_campaigns(
                    ui["meta_ad_account_id"], ui["meta_access_token"],
                )
                logger.info(
                    "connect_meta: %d previous campaigns available from %s",
                    len(bs["previous_campaigns"]), ui["meta_ad_account_id"],
                )
            except Exception:
                # An empty list and a failed lookup both render as "no campaigns to
                # start from", so log the difference.
                bs["previous_campaigns"] = []
                logger.warning(
                    "connect_meta: previous campaigns lookup failed for %s",
                    ui["meta_ad_account_id"], exc_info=True,
                )
            # What about this account will stop a publish? Meta only says no to
            # most of it at write time — a customer-list audience on an account
            # outside a Business fails with subcode 1870050 at publish, which used
            # to be the first the user heard of it, after building the whole
            # campaign. One read answers all of it now.
            try:
                from app.services import meta_ads as _meta

                _blockers = await _meta.ad_account_blockers(
                    ui["meta_ad_account_id"], ui["meta_access_token"],
                )
            except Exception:
                logger.warning(
                    "connect_meta: account capability check failed for %s",
                    ui["meta_ad_account_id"], exc_info=True,
                )
                _blockers = []
            # Not Meta errors and not probe results — facts about what the connection
            # contains, found while listing Pages. Said now, on the same card list, so
            # they are also on the publish gate.
            _blockers = list(_blockers) + _page_blockers(bs)
            # Whether the Custom Audience Terms are accepted: True stops the
            # "confirm it yourself" beat, False is a plain card, None keeps asking.
            # Moot when there is no audience to build.
            _tos = None
            if not any(r.key == "audience_needs_business" for r in _blockers):
                try:
                    from app.services import meta_ads as _meta_tos

                    _tos = await _meta_tos.fetch_custom_audience_tos(
                        ui["meta_ad_account_id"], ui["meta_access_token"],
                    )
                except Exception:
                    logger.warning(
                        "connect_meta: terms check failed for %s",
                        ui["meta_ad_account_id"], exc_info=True,
                    )
                if _tos is False:
                    from app.services import meta_remediation as _fix_tos

                    _blockers.append(_fix_tos.CATALOG["custom_audience_tos"])
            if _blockers:
                from app.services import meta_remediation as _fix

                bs["account_remediation"] = _fix.render_all(
                    _blockers, ad_account_id=ui["meta_ad_account_id"],
                )
                for _rem in _blockers:
                    if _rem.key == "audience_needs_business":
                        # Decided here rather than at publish: the answer is the
                        # same on every attempt (it is an account setting, not a
                        # plan choice), and deciding it now is what lets publish
                        # run without a gate.
                        bs["audience_blocked_reason"] = _rem.cause
                        bs["publish_without_audience"] = True
                    # Beat, not a direct emit: the connect handoff beat sits in the
                    # same buffer, so a raw emit here put an "we can't build your
                    # visitor audience" paragraph next to the "audience locked in"
                    # one, written by two different minds. Buffered, the composer
                    # states both in one message.
                    add_beat(
                        state, "failure",
                        facts=_fix.beat_facts(
                            _rem, ad_account_id=ui["meta_ad_account_id"],
                        ),
                        fallback=f"{_rem.cause} {_rem.effect}".strip(),
                    )
            _connect_extra_beats(
                state, bs, _blockers, ui["meta_ad_account_id"], tos_accepted=_tos,
            )
            _log(bs, {"step": "act:connect_meta",
                      "summary": f"account={ui.get('meta_ad_account_id', '')[:20]} "
                                 f"pixels={len((bs.get('media_ws') or {}).get('pixel_candidates') or [])}"})

        elif operation == "resolve_meta":
            # Pixel resolution only — OAuth/account already done in connect_meta.
            # Reads the objective (via user_info) so it must run after
            # campaign_intake; stays before generate_meta_json so the spec's
            # promoted_object is built against the real pixel id.
            # No pixel on the account is NOT a failure and NOT a question here:
            # generate_meta_json builds the tree anyway and the plan editor asks
            # for the pixel on the one screen that can show the account's options.
            from app.graph.builder.executors.media import media_select_pixel
            await _run_media_overlay(state, bs, update, (media_select_pixel,), live=_live)
            _log(bs, {"step": "act:resolve_meta", "summary": f"pixel={(bs.get('media_ws') or {}).get('pixel_id') or 'n/a'}"})

        elif operation == "export_audience":
            # "Publish it myself": the audience goes into the user's ad account and
            # the build stops there. No brief, no spec, no campaign — the campaign
            # stage's remaining acts are filtered out for this mode (_OP_MODES).
            ui = _ui_view(state, bs)
            if not ui.get("meta_access_token") or not ui.get("meta_ad_account_id"):
                raise RuntimeError("Meta credentials unavailable — connect_meta must run first")

            from app.graph.builder.executors.media import export_audience_only
            from app.services.meta_ads import acting_user

            try:
                with acting_user(state.get("user_id")):
                    exported = await export_audience_only(
                        ui, _builder_geo(state, bs), writer,
                        export_state=bs.setdefault("audience_export_state", {}),
                    )
            except MetaPublishError as exc:
                _log(bs, {"step": "act:export_audience", "summary": f"FAILED at {exc.step}"})
                bs["next_action"] = None
                writer({"type": "assistant_message", "content": exc.user_message})
                # Exit the builder rather than fall back into builder_plan. The op
                # stays undone and _next_step would hand it straight back — with no
                # gate in front of it (this route has none) that re-ran the failing
                # Meta call every iteration until the plan budget was gone. The
                # builder state survives on AgentState, so a user-driven retry
                # resumes here, and audience_export_state means it reuses any
                # audience Meta already created instead of making a second one.
                return {
                    "campaign_builder_state": bs,
                    "wizard_failure": "campaign_audience_export_failed",
                    **update,
                }

            bs["audience_export"] = exported
            _log(bs, {
                "step": "act:export_audience",
                "summary": f"audience={exported['audience_id']} uploaded={exported['uploaded']}",
            })
            _manager_url = (
                "https://adsmanager.facebook.com/adsmanager/audiences"
                f"?act={str(exported['ad_account_id']).replace('act_', '')}"
            )
            add_beat(
                state, "reveal",
                {
                    "stage": "audience_exported",
                    "audience_name": exported["audience_name"],
                    "audience_id": exported["audience_id"],
                    "uploaded": exported["uploaded"],
                    "ads_manager_url": _manager_url,
                },
                fallback=(
                    f"**{exported['audience_name']}** is in your ad account with "
                    f"**{exported['uploaded']:,} profiles** uploaded. Meta takes a little "
                    "while to finish matching them to real accounts. Build your campaign "
                    f"against it here: {_manager_url}"
                ),
            )

        elif operation == "activate":
            # The campaign already exists in Meta, PAUSED, and the user has just
            # approved it at the go_live_confirm preview gate. This is the only
            # thing that starts spend.
            ui = _ui_view(state, bs)
            from app.graph.builder.executors.media import activate_published_tree
            from app.services.meta_ads import acting_user

            # Re-checked here even though `publish` already checked it: a
            # subscription can lapse between the two, and activate is the
            # last point before money moves.
            await _require_paid_account(state, writer, ui.get("meta_ad_account_id") or "")

            _ids = bs.get("meta_campaign_ids") or {}
            try:
                with acting_user(state.get("user_id")):
                    # NOT `_live` — that name is builder_act's scratch registry
                    # (see its declaration above the try block). Reusing it here
                    # shadowed the dict with activate_published_tree's return
                    # value, so a later exception in this same act flushed a
                    # single activation record instead of the pending-edit
                    # scratch — `bs.update(_live)` in the except branches below
                    # would crash outright once :4273 rebinds it to a bool.
                    _activated = await activate_published_tree(
                        _ids,
                        ui,
                        bs.get("marketing_plan") or {},
                        writer,
                        user_id=state.get("user_id"),
                        thread_id=(config.get("configurable") or {}).get("thread_id"),
                    )
            except MetaPublishError as exc:
                # Deliberately NOT _apply_publish_failure: the campaign is built and
                # correct, so reopening the plan editor would ask the user to fix
                # something that isn't broken. Drop the gate answer instead, so the
                # preview screen comes back with a working retry.
                _log(bs, {"step": "act:activate", "summary": f"FAILED at {exc.step}"})
                filled.pop("go_live_confirm", None)
                bs["filled"] = filled
                bs["next_action"] = None
                writer({"type": "assistant_message", "content": exc.user_message})
                return {"campaign_builder_state": bs, **update}

            _ids["activated"] = _activated
            bs["meta_campaign_ids"] = _ids
            _log(bs, {"step": "act:activate", "summary": f"activated={_activated}"})

            if _activated:
                await _record_go_live_consent(
                    user_id=state.get("user_id"),
                    campaign_id=_ids.get("campaign_id"),
                    campaign_ids=_ids.get("campaign_ids"),
                    ad_account_id=_ids.get("ad_account_id"),
                    go_live_answer=filled.get("go_live_confirm"),
                )
            add_beat(
                state, "reveal",
                {
                    "stage": "campaign_live" if _activated else "campaign_still_paused",
                    "campaign_id": _ids.get("campaign_id") or "",
                    "ad_count": len(_ids.get("ad_ids") or []),
                },
                fallback=(
                    "Your campaign is live — new ads go through Meta's review first "
                    "(usually within a day), then delivery starts."
                    if _activated else
                    "Your campaign is built and still PAUSED. Nothing is spending; "
                    "switch it on in Ads Manager whenever you're ready."
                ),
            )

        elif operation == "publish":
            ui = _ui_view(state, bs)
            if not ui.get("meta_access_token") or not ui.get("meta_ad_account_id"):
                raise RuntimeError("Meta credentials unavailable — resolve_meta must run first")
            await _require_paid_account(state, writer, ui["meta_ad_account_id"])

            view = dict(state)
            view["geo_data"] = _builder_geo(state, bs)
            view["marketing_plan"] = bs.get("marketing_plan") or {}
            view["campaign_brief"] = bs.get("brief") or {}

            from app.services.meta_ads import acting_user

            try:
                # Binds whose token is on the wire, so the transport can mark a
                # revoked connection invalid instead of failing on 190 forever.
                with acting_user(state.get("user_id")):
                    meta_ids = await publish_campaign_to_meta(
                        ui,
                        view["geo_data"],
                        view["marketing_plan"],
                        view["campaign_brief"],
                        writer,
                        user_id=state.get("user_id"),
                        # Keys the draft row, which carries the publish ledger
                        # that makes a retry resume rather than duplicate.
                        thread_id=(config.get("configurable") or {}).get("thread_id"),
                        allow_without_audience=bool(
                            bs.get("publish_without_audience")
                        ),
                        # Consumed here: the ledger's campaign tree is dropped on
                        # this attempt, so the next one has nothing stale to fear.
                        plan_dirty=bool(bs.pop("publish_plan_dirty", False)),
                    )
            except MetaPublishError as exc:
                _log(bs, {"step": "act:publish", "summary": f"FAILED at {exc.step}"})
                bs["next_action"] = None
                _terminal, _perm = _publish_is_terminal(
                    exc, bs.setdefault("publish_fail_counts", {})
                )
                # `_terminal` no longer exits to chatbot — it only picks the
                # wording. A permission failure or a repeated one still has to say
                # WHAT is wrong and HOW to clear it, and the editor is where the
                # user needs to be either way.
                if _terminal:
                    _log(bs, {
                        "step": "act:publish",
                        "summary": f"terminal at {exc.step} ({'permission' if _perm else 'retry limit'})",
                    })
                # Deliver the reason directly, not only through the narrator: the
                # milestone can cache-hit or be switched off entirely
                # (WIZARD_NARRATOR_ENABLED), and a publish that failed silently is
                # what made this look like the conversation had reset. A terminal
                # message skips the narrator's paraphrase on purpose — "do not
                # retry, fix the access first" must reach the user unsoftened.
                message = (
                    _publish_terminal_message(exc, permission=_perm)
                    if _terminal else exc.user_message
                )
                writer({"type": "assistant_message", "content": message})
                if not _terminal:
                    update.update(await wizard_milestone_narrate(
                        writer, state, "media_failed",
                        facts={"failure_reason": message},
                        fallback=message,
                    ))
                _apply_publish_failure(bs, filled, exc, message)
                return {"campaign_builder_state": bs, **update}
            if meta_ids is None:
                _log(bs, {"step": "act:publish", "summary": "no adsets — nothing to publish"})
                bs["next_action"] = None
                return {
                    "campaign_builder_state": bs,
                    "wizard_failure": "campaign_publish_no_adsets",
                    **update,
                }
            # Not an id: a fix-it card publish could only discover after the
            # campaign existed. Moved onto the same list every other publish
            # remediation travels on, so the Preview & Publish gate restates it.
            _lead_fix = meta_ids.pop("lead_webhook_remediation", None)
            if _lead_fix:
                bs["publish_remediation"] = [
                    r for r in (bs.get("publish_remediation") or [])
                    if r.get("key") != _lead_fix["key"]
                ] + [_lead_fix]
            bs["meta_campaign_ids"] = meta_ids
            bs.pop("publish_fail_counts", None)
            # Usually one. An App-promotion plan with both store links publishes
            # one campaign per store, because Meta puts the promoted app on the
            # campaign and iOS installs need their own SKAdNetwork campaign.
            _campaign_ids = meta_ids.get("campaign_ids") or [meta_ids["campaign_id"]]
            _log(bs, {"step": "act:publish", "summary": f"campaigns={','.join(_campaign_ids)}"})
            writer({"type": "campaign_published", "content": meta_ids})
            # Published ads are PAUSED until the activation pass flips them, and
            # that pass can be skipped (no ads, or activation switched off), so
            # the publisher reports what actually happened.
            # NOT `_live` — see the note at the activate branch above; that name
            # is builder_act's pending-edit scratch registry, not a local flag.
            _is_active = bool(meta_ids.get("activated"))
            _status = "ACTIVE" if _is_active else "PAUSED"
            # "Live" on Meta means submitted: a new ad is reviewed before it delivers,
            # and a new ad account is reviewed more slowly. Without this the first
            # thing a new advertiser learns about review is that nothing is delivering.
            _review_note = (
                "New ads go through Meta's review before they deliver — usually within a "
                "day, and there is nothing to do meanwhile."
                if _is_active else ""
            )
            _campaign_label = (
                ("Campaign live in Meta" if _is_active else "Campaign created in Meta (paused)")
                if len(_campaign_ids) == 1
                else f"**{len(_campaign_ids)} campaigns** "
                     f"{'live' if _is_active else 'created (paused)'} in Meta (one per app store)"
            )
            # The audience was built and then not used — nobody chose that, so the
            # publish message is where they find out, with the reason and the fix.
            _notice = _audience_notice(bs, view["geo_data"])
            _notice_line = (
                f" Your visitor audience wasn't attached: {_notice['reason']} "
                f"The ads are running on Meta's Advantage+ audience inside the same "
                f"locations. {_notice['fix']}"
                if _notice else ""
            )
            update.update(await wizard_milestone_narrate(
                writer, state, "media_published",
                facts={
                    "campaign_id": meta_ids["campaign_id"],
                    "campaign_count": len(_campaign_ids),
                    "adset_count": len(meta_ids["adset_ids"]),
                    "ad_count": len(meta_ids["ad_ids"]),
                    "status": _status,
                    **({"ads_in_review": _review_note} if _review_note else {}),
                    "business_name": ui.get("business_name") or "",
                    # Without this the composer carries the earlier audience beat
                    # forward and claims the ads target the real visitors even on a
                    # publish that deliberately dropped them for Advantage+.
                    "audience_mode": (
                        "custom_audience"
                        if (meta_ids.get("custom_audience_id") or meta_ids.get("lookalike_audience_id"))
                        else "advantage_plus"
                    ),
                    **(
                        {
                            "audience_dropped_reason": _notice["reason"],
                            "audience_fix": _notice["fix"],
                        }
                        if _notice else {}
                    ),
                },
                fallback=(
                    f"{_campaign_label} — **{len(meta_ids['adset_ids'])} ad group(s)**, "
                    f"**{len(meta_ids['ad_ids'])} ad(s)**, status **{_status}**. "
                    f"You can review in Meta Ads Manager.{_notice_line}"
                    f"{' ' + _review_note if _review_note else ''}"
                ),
            ))
            update["active_campaign_id"] = meta_ids["campaign_id"]
            update["just_published"] = True

        else:
            _log(bs, {"step": f"act:{operation}", "summary": "unknown operation"})
            bs["next_action"] = None
            return {"campaign_builder_state": bs, "wizard_failure": "builder_unknown_operation"}

    except GraphBubbleUp:
        # interrupt() (geo location/POI confirm, creative upload, OAuth) raises
        # GraphInterrupt — a GraphBubbleUp — to PAUSE the graph. It must reach
        # the framework, never be caught here, or the interrupt is silently
        # turned into a builder_act_failed and the widget never holds.
        #
        # The framework discards this node's writes, so park the scratch the act
        # had already built (geocodes, disambiguation picks, resolved places) for
        # the replay that resumes it. Cache only — losing it costs a re-fetch.
        save_act_scratch(config, str(operation or ""), _live, _act_stamp)
        raise
    except StepPaused:
        # An executor's interrupt just resolved (see StepPaused) — typically a
        # reply that didn't answer it, whose edits are stashed on its ws. Persist
        # the scratch and leave the op NOT done so _next_step re-dispatches it as
        # a fresh task after builder_plan has applied those edits. Logged as
        # progress, not a repeat (same reasoning as the geo pause above).
        _log(bs, {"step": f"act:{operation}", "summary": "paused — one reply handled, re-dispatching"})
        bs.update(_live)
        bs["next_action"] = None
        bs["_reask_tick"] = True
        return {"campaign_builder_state": bs, **update}
    except _wizard_exit_class():
        # User bailed mid-wizard (escape menu / off-path budget exhausted).
        # Route back to chatbot like the resume-router wrapper does, instead of
        # reporting a false failure.
        logger.info("builder_act %s: user exit requested — routing to chatbot", operation)
        # Keep the scratch AND this act's accumulated `update`, exactly as the
        # generic error path below does. Discarding them threw away every slot,
        # POI and plan the user had built, plus whatever this act had already
        # produced before they bailed.
        #
        # Also write back `_live`: unlike GraphBubbleUp, there is no replay behind
        # this exit, so a `stash_edits` an executor parked on its `ws` copy
        # (never yet merged onto `bs`) would otherwise vanish for good — acked to
        # the user, then silently dropped on exit.
        bs.update(_live)
        bs["next_action"] = None
        return {
            "campaign_builder_state": bs,
            "next_nodes": ["chatbot"],
            "pending_action": None,
            "wizard_failure": "user_exit",
            **update,
        }
    except SubscriptionRequired as exc:
        # Nothing was lost — publish never ran, or activate ran but the
        # campaign it already created stays PAUSED. `_mark_op_done` below is
        # never reached, so `operation` stays out of `ops_done` and
        # `_next_step` re-proposes it unchanged once the account is paid.
        logger.info("builder_act %s: subscription required — routing to chatbot", operation)
        bs.update(_live)
        bs["next_action"] = None
        return {
            "campaign_builder_state": bs,
            "next_nodes": ["chatbot"],
            "pending_action": exc.pending,
            "wizard_failure": "subscription_required",
            **update,
        }
    except Exception as exc:
        logger.error("builder_act %s failed: %s", operation, exc, exc_info=True)
        _log(bs, {"step": f"act:{operation}", "summary": f"error: {exc}"})
        # Same reasoning as the exit branch above: no replay follows an error, so
        # flush `_live` before the scratch is returned or the stashed edit is lost.
        bs.update(_live)
        bs["next_action"] = None
        return {"campaign_builder_state": bs, "wizard_failure": "builder_act_failed", **update}

    _mark_op_done(bs, operation)
    bs["next_action"] = None
    return {"campaign_builder_state": bs, **update}


async def builder_finalize(state: AgentState) -> dict:
    """Merge results into AgentState and exit.

    Exits to chatbot, except on a fresh publish — there
    ``_route_after_publish_pipeline`` ends the turn on ``just_published``, because
    the narration flushed here is already the complete message.
    """
    writer = get_writer()
    bs = _bs(state)
    writer({"type": "thinking", "content": "Builder: finalizing — merging results into session state"})

    update: dict = {"campaign_builder_state": None, "next_nodes": ["chatbot"]}
    if bs.get("geo_result"):
        update["geo_data"] = bs["geo_result"]
    if bs.get("brief"):
        update["campaign_brief"] = bs["brief"]
    if bs.get("marketing_plan"):
        update["marketing_plan"] = bs["marketing_plan"]
    _published = bool(bs.get("meta_campaign_ids"))
    if _published:
        update["meta_campaign_ids"] = bs["meta_campaign_ids"]
        update["active_campaign_id"] = bs["meta_campaign_ids"].get("campaign_id")
        # next_nodes stays ["chatbot"]; the conditional edge reads this flag and
        # ends the turn instead. Nothing runs after the flush below.
        update["just_published"] = True

    # Compose + emit any beats buffered this turn that no interrupt flushed
    # (e.g. a publish reveal on a turn that ends in `done` with no further ask).
    # Persist the composed-text cache fragment so a cross-worker resume replay
    # re-emits identical text at $0.
    # Fill the brief pre-first-token gap (LLM thinking window) with motion, but
    # only when there are actually beats to compose. source != "punk" → not
    # persisted.
    if _narrator_peek(state):
        writer({"type": "thinking", "source": "system", "content": "Pulling it together..."})
    _text, _narr = await flush_narration(state, writer)
    if _narr.get("wizard_milestone_cache"):
        update["wizard_milestone_cache"] = _narr["wizard_milestone_cache"]
    if _narr.get("narrator_history"):
        update["narrator_history"] = _narr["narrator_history"]

    # A publish turn ends here — no chatbot runs after it — so this flush is the
    # turn's only assistant text. If the compose produced nothing, say it plainly
    # rather than shipping a silent turn the chat service would persist as blank.
    if _published and not _text:
        _ids = bs["meta_campaign_ids"]
        _status = "ACTIVE" if _ids.get("activated") else "PAUSED"
        _text = (
            f"{'Campaign live in Meta' if _ids.get('activated') else 'Campaign created in Meta (paused)'} — "
            f"**{len(_ids.get('adset_ids') or [])} ad group(s)**, "
            f"**{len(_ids.get('ad_ids') or [])} ad(s)**, status **{_status}**. "
            "You can review it in Meta Ads Manager."
        )
        writer({"type": "assistant_message", "content": _text})

    # The builder talks to the user through the stream, not the transcript, so
    # `messages` would otherwise still end at the pre-build user turn — leaving the
    # next turn's entry/chatbot/campaign_manager blind to everything that just
    # happened. Record what was actually said.
    if _text:
        update["messages"] = [AIMessage(content=_text)]

    completed = set(bs.get("stages_complete") or [])
    if completed:
        update["wizards_completed"] = completed
    return update


# ── Routing ────────────────────────────────────────────────────────────────────

def _route_after_plan(state: AgentState) -> str:
    action = (_bs(state).get("next_action")) or {}
    kind = action.get("kind")
    if kind == "ask":
        return "builder_ask"
    if kind == "act":
        return "builder_act"
    if kind == "done":
        return "builder_finalize"
    return "chatbot_exit"  # fail → parent routes to chatbot via wizard_failure


def _route_after_step(state: AgentState) -> str:
    if state.get("wizard_failure"):
        return "chatbot_exit"
    return "builder_plan"


def build_campaign_builder() -> CompiledStateGraph:
    """Compile the campaign-builder subgraph (registered as one parent node)."""
    g = StateGraph(AgentState)
    g.add_node("builder_plan", builder_plan)
    g.add_node("builder_ask", builder_ask)
    g.add_node("builder_act", builder_act)
    g.add_node("builder_finalize", builder_finalize)

    g.add_edge(START, "builder_plan")
    g.add_conditional_edges("builder_plan", _route_after_plan, {
        "builder_ask": "builder_ask",
        "builder_act": "builder_act",
        "builder_finalize": "builder_finalize",
        "chatbot_exit": END,
    })
    g.add_conditional_edges("builder_ask", _route_after_step, {
        "builder_plan": "builder_plan",
        "chatbot_exit": END,
    })
    g.add_conditional_edges("builder_act", _route_after_step, {
        "builder_plan": "builder_plan",
        "chatbot_exit": END,
    })
    g.add_edge("builder_finalize", END)
    return g.compile()
