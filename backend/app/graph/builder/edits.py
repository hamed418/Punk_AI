"""
graph/builder/edits.py
──────────────────────
The commit path for mid-build user edits.

**The build pipeline is a build system, not a transcript.** Slots are sources,
operations are targets, stages are ordered. When the user changes a slot they
have changed a source, and the correct response is to invalidate the targets
downstream of it and let the planner rebuild them — ``make``, not
``git checkout``.

Why that distinction matters here: the 2026-06 resume-router did try
``git checkout``. Its ``_try_backtrack`` called
``aupdate_state(historical_snapshot.config, {})`` to fork the thread back to an
earlier checkpoint. On the old graph each wizard step was its own node, so the
fork landed on a node boundary. On the builder **all collection happens inside
one re-entered ``builder_ask``** (see builder_node's module docstring), so the
fork discarded every slot filled after the target and the single node re-asked
all of them. That user-visible loop-back is why the lane was removed.

``bs["filled"]`` is the source-of-truth layer that design lacked. Rewriting a
key there and dropping the ops downstream of it re-drives the planner naturally:
no checkpoint fork, no lost slots, no replay surprises. Nothing in this module
touches a checkpoint.

Everything here is pure and synchronous. The two ``builder_node`` symbols it
needs are imported lazily inside the functions — ``builder_node`` imports this
module, so a module-level import would be circular. (Same pattern as
``resume_router.generate_chips`` and ``builder_node._wizard_exit_class``.)
"""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal, Optional

from app.graph.builder.slots import (
    GATE_SLOTS,
    SLOTS,
    STAGE_ORDER,
    merge_angle_tokens,
    slot_applies,
)
from app.graph.field_owner_registry import APPENDABLE_FIELDS, FIELD_OWNER
from app.graph.prompts_registry import STEP_PROMPTS

logger = logging.getLogger(__name__)


# ── field name → slot ─────────────────────────────────────────────────────────
# The classifier names fields on three different surfaces and the registry
# accepts all of them (see field_owner_registry's module docstring): the slot's
# own name, the UserInfo natural name (``Slot.prefill_key``), and the step-level
# field from STEP_PROMPTS. Build one index over all three rather than adding a
# synonym layer.

def _build_edit_aliases() -> dict[str, tuple[str, ...]]:
    """Map every name a slot can be referred to → the slot name(s) it may mean.

    Values are tuples because one alias can legitimately reach two slots:
    ``search_radius_km`` is the ``prefill_key`` of BOTH ``radius_km`` and
    ``competitor_radius_km``. Those are resolved per-call against the filled
    slots, since only one of the two is ever applicable in a given run.
    """
    out: dict[str, list[str]] = {}
    for slot in SLOTS.values():
        step_field = (STEP_PROMPTS.get(slot.step_key) or {}).get("field")
        for alias in (slot.name, slot.prefill_key, step_field):
            if alias:
                bucket = out.setdefault(alias, [])
                if slot.name not in bucket:
                    bucket.append(slot.name)
    return {k: tuple(v) for k, v in out.items()}


EDIT_ALIASES: dict[str, tuple[str, ...]] = _build_edit_aliases()


def resolve_edit_target(field: str, filled: dict[str, Any]) -> Optional[str]:
    """The slot an edit to ``field`` should write, or None when it maps to none.

    When an alias is ambiguous, the applicable slot wins — ``slot_applies``
    already encodes which route the run is on, so a ``search_radius_km`` edit
    lands on ``competitor_radius_km`` for a competitor_nearby run and on
    ``radius_km`` for a radius-scope run. Falls back to the first candidate so a
    not-yet-determinable route still resolves to something deterministic.
    """
    candidates = EDIT_ALIASES.get(field or "")
    if not candidates:
        return None
    for name in candidates:
        slot = SLOTS.get(name)
        if slot is not None and slot_applies(slot, filled):
            return name
    return candidates[0]


# Field names the CLASSIFIER may put in ``ResumeIntent.target_field`` that
# resolve to no slot and no campaign key — each has its own bespoke dispatch
# in ``wizard_helpers._dispatch_edit_intent`` (translated there into the
# underscore-prefixed ``_CONTROL_KEYS`` below: "poi_selection" ->
# ``edits["_poi_selection"]``, etc). A different set from ``_CONTROL_KEYS``
# on purpose — that one is internal stash keys, this one is classifier-facing
# field names; the two layers happen to share two names.
_CONTROL_FIELDS: frozenset[str] = frozenset({
    "poi_selection", "audience_filter", "location_ring", "location_center", "map_pins",
    "excluded_areas",
})


def is_actionable_field(field: str) -> bool:
    """True when an edit naming ``field`` can actually reach a write.

    The single predicate BOTH gates an edit must pass must agree on: the ACK
    gate (``resume_router._validate_edit_target``, which decides whether the
    user is told "got it") and the APPLY gate (this module's field loop in
    ``apply_pending_edits``, below, which decides whether anything is
    actually written).

    Before this function existed the two gates were different predicates.
    The ack gate accepted any name in ``FIELD_OWNER`` (79 keys); the apply
    gate accepted only ``EDIT_ALIASES``, a campaign bare-key, or a control
    field. Seven geo-owned fields (``geo_business_description``,
    ``geo_map_selection``, ``geo_plan_confirm``, ``geo_location_confirmation``,
    ``geo_store_confirmation``, ``geo_disambiguate_location``,
    ``geo_disambiguate_named_place``) were in ``FIELD_OWNER`` but neither in
    ``EDIT_ALIASES`` nor campaign-owned — an edit naming one got acked
    ("Updated **field** -> ..."), then fell through to the
    ``logger.warning(... "no slot or campaign field ... — dropped")`` below,
    silently, after the user had already been told it landed.
    ``_validate_edit_target``'s own docstring names this exact failure mode;
    this function is what makes it unreachable rather than merely documented.
    """
    return (
        field in EDIT_ALIASES
        or FIELD_OWNER.get(field) == "campaign"
        or field in _CONTROL_FIELDS
    )


def canonical_field(field: str) -> str:
    """Alias -> the FIELD_OWNER-registered name downstream consumers key on.

    ``is_actionable_field`` accepts every ``EDIT_ALIASES`` entry, which
    includes slot NAMES (e.g. "locations" for the ``locations`` slot) — but
    every downstream consumer (rerun_on_edit sets, stash_edits ``exclude``,
    ``APPENDABLE_FIELDS``, ``edit_base`` keys) is keyed on the registry names
    instead ("location", "geo_locations"). A slot-name alias that slips past
    ``is_actionable_field`` unchanged reaches none of those guards, gets
    stashed anyway, and invalidates the stage it names mid-execution — see
    ``builder/executors/geo.py``'s confirm loop, which hardcodes only the two
    registry names. Collapse the alias here, once, so the two layers cannot
    disagree.
    """
    if not field or field in FIELD_OWNER:
        return field
    slot = SLOTS.get(resolve_edit_target(field, {}) or "")
    if slot is None:
        return field
    step_field = (STEP_PROMPTS.get(slot.step_key) or {}).get("field")
    for alias in (slot.prefill_key, step_field, slot.name):
        if alias and alias in FIELD_OWNER:
            return alias
    return field


# ── invalidation ──────────────────────────────────────────────────────────────
#
# Units are finer than STAGE_ORDER because the "geo" stage's one act
# (``geo_discover``) does two independent jobs behind one op name: geocoding
# (produces ``geo_location_confirmation`` / ``geo_store_confirmation``) and the
# Places search (produces ``poi_confirm``). Rolling back the whole "geo" stage
# for a POI-only edit ("also target gyms") used to re-ask a location confirm
# the user never touched — because the two confirmations' only memory,
# ``ws["_location_confirmed"]`` / ``ws["_store_confirmed"]``, lived in
# ``geo_ws``, which a stage-level rollback deleted wholesale.
#
# ``_UNIT_ORDER`` is a suffix chain exactly like ``STAGE_ORDER`` was: dooming
# one unit dooms everything after it, so "downstream always rebuilds" still
# holds — a unit is just a smaller grain than a stage.
_UNIT_ORDER: tuple[str, ...] = ("geocode", "poi_search", "maid_query", "campaign", "media")

# slot name → the earliest unit that slot feeds. Not every geo/maid slot needs
# an entry — an unlisted slot falls back to its stage's first unit (below),
# which is always the SAFE (more-invalidating) choice.
_SLOT_UNIT: dict[str, str] = {
    "location_scope": "geocode", "radius_pin": "geocode", "radius_km": "geocode",
    "locations": "geocode", "store_addresses": "geocode", "competitor_anchor": "geocode",
    "det_type": "poi_search", "poi_types": "poi_search", "brand_names": "poi_search",
    "named_places": "poi_search", "event_queries": "poi_search",
    "event_date_range": "poi_search", "competitor_radius_km": "poi_search",
    "poi_radius_m": "maid_query", "lookback_days": "maid_query",
}
_STAGE_DEFAULT_UNIT: dict[str, str] = {
    "geo": "geocode", "maid": "maid_query", "campaign": "campaign", "media": "media",
}

# Canonical (FIELD_OWNER-registered) field names whose edit re-buys live
# Unacast vendor data rather than re-running something free (a brief, a
# Places search against an already-geocoded area). A misread classifier call
# on one of these does not just cost a re-ask — post-Unacast it can spend real,
# shared monthly call budget on a mistaken "just kidding" edit. Raised via
# ``edit_confidence_floor`` below rather than a new gate/interrupt: the money
# boundary (interject_tools.py's module docstring) is deliberate that this
# lane adds no new interrupt boundary, so the floor is the only lever that
# doesn't contradict it.
_COST_BEARING_FIELDS: frozenset[str] = frozenset({
    "poi_radius_m", "lookback_days", "location", "geo_locations",
    "store_addresses", "geo_store_addresses",
})

# How much higher than the global floor a cost-bearing field's edit must clear.
# Additive, not a replacement value: RESUME_EDIT_MIN_CONFIDENCE stays the one
# knob that sets the baseline; this only raises the bar for the fields that can
# spend money, so tuning the global floor still moves both.
_COST_BEARING_CONFIDENCE_MARGIN: float = 0.1


def edit_confidence_floor(field: Optional[str], base_floor: float) -> float:
    """The confidence floor an edit to ``field`` must clear, given the
    process-wide ``base_floor`` (``settings.RESUME_EDIT_MIN_CONFIDENCE``).

    Cost-bearing fields (see ``_COST_BEARING_FIELDS``) get a margin added on
    top — a re-buy of live vendor data is not the same risk as a free re-ask,
    so the same bare-pass confidence should not be enough for both.
    """
    if field in _COST_BEARING_FIELDS:
        return min(1.0, base_floor + _COST_BEARING_CONFIDENCE_MARGIN)
    return base_floor


def _unit_for_slot(slot_name: str) -> str:
    """The unit an edit to this slot invalidates. Falls back to the slot's
    stage's first (most conservative) unit when the slot has no explicit entry,
    so an unmapped field still rolls back at least as much as it used to."""
    if slot_name in _SLOT_UNIT:
        return _SLOT_UNIT[slot_name]
    slot = SLOTS.get(slot_name)
    return _STAGE_DEFAULT_UNIT.get(slot.stage if slot else "geo", "geocode")


# geo_ws keys pruned when the "geocode" unit is doomed — settled answers about
# WHERE the search happens. Kept as a constant (not inline in invalidate_from)
# because executors/geo.py's cache-key split must agree with this set or the two
# layers drift: one preserving a flag the other still re-derives from scratch.
_LOCATION_WS_KEYS: tuple[str, ...] = (
    "_geocoded_locations", "_resolved_scope", "_location_confirmed",
    "_loc_candidates", "_loc_tiebreak", "_loc_picks", "_disambig_asked",
    "_loc_cache_key", "_store_confirmed", "_geocoded_stores",
    "_locations_synced", "_loc_hints",
    # Confirm-map edits persisted for the next dispatch. Left behind by a
    # rollback, builder_act re-applies them OVER the freshly edited slot
    # (`_stores_synced` beat a later typed store edit; `_angle_names_synced`
    # resurrected removed locations for every angle it covered).
    "_stores_synced", "_angle_names_synced",
)
# geo_ws keys pruned when "poi_search" is doomed — settled answers about WHAT
# was found there. Dropped alongside the location keys when "geocode" is doomed
# too (a new location set invalidates any POIs found in the old one).
_POI_WS_KEYS: tuple[str, ...] = (
    "_all_pois_cache", "_poi_types_cache", "_arm_pois", "_poi_cache_key",
    "_named_resolved", "_named_picks", "_named_disambig_asked",
)

# bs-level scratch dropped per doomed unit. "media" is deliberately EMPTY —
# ``media_ws`` holds the OAuth access token, the resolved ad account and the
# pixel candidates from the ``connect_meta`` pre-act; dropping it would force
# the user to reconnect Meta because they renamed their business. The media
# stage's only ops are publish/activate, and once `publish` has run
# `edit_block_reason` returns "published" and no edit reaches this code.
_UNIT_BS_SCRATCH: dict[str, tuple[str, ...]] = {
    # A spot picked on the old map belongs to the old locations; a new location
    # set starts clean (undo restores it — it is in every snapshot).
    "geocode": ("geo_result", "_geo_recommit", "_map_added_pois"),
    "poi_search": ("geo_result", "_geo_recommit"),
    "maid_query": ("maid_ws",),
    "campaign": (
        "brief", "marketing_plan", "marketing_plan_draft", "plan_errors",
        "intake_errors", "intake_values",
    ),
    "media": (),
}
# unit → the ops it produces, for the ops_done sweep. geo_discover appears
# under both geocode and poi_search: either one being doomed re-runs the act
# (the executor's own per-unit cache-key check — see executors/geo.py — decides
# how much of that re-run is actually new work).
_UNIT_OPS: dict[str, tuple[str, ...]] = {
    "geocode": ("geo_discover",),
    "poi_search": ("geo_discover",),
    "maid_query": ("maid_query",),
    "campaign": ("export_audience", "generate_brief", "resolve_meta", "generate_meta_json"),
    "media": ("publish", "activate"),
}


def invalidate_from(bs: dict, filled: dict, unit: str) -> list[str]:
    """Undo ``unit`` and every later unit so the planner rebuilds them.

    Returns the STAGE names touched (in pipeline order), for the caller to
    narrate — a rebuild the user was not told about is indistinguishable from a
    bug. (Stages, not units: the user-facing note talks about "geo"/"maid", not
    internal op grains.)

    Drops, for each doomed unit: its operations from ``ops_done``, the
    confirmation gates whose ``_GATE_PREREQ_OP`` is being dropped, its cached
    artifacts from ``bs``, and (for geocode/poi_search) the matching slice of
    ``geo_ws`` — never the whole thing, so a settled confirmation the edit did
    not touch survives. Recomputes ``stages_complete`` (otherwise append-only —
    see ``_refresh_stage_completion``). Generalizes ``_reopen_plan_editor``,
    which remains the publish-failure-specific wrapper.

    Deliberately does NOT drop pre-acts (``connect_meta``, ``enrich_website``).
    They are keyed off ``_STAGE_PRE_ACTS``, not ``_STAGE_ACTS``/``_UNIT_OPS``,
    and re-running ``connect_meta`` would re-prompt for Meta OAuth.

    Resets ``iteration``: the budget exists to stop a planner livelock, and a
    livelock cannot occur across an edit because each one costs a real user turn.
    Without the reset a user who changes their mind a few times exhausts
    ``_MAX_PLAN_ITERATIONS`` and the build dies permanently.
    """
    from app.graph.builder.builder_node import _GATE_PREREQ_OP, _OPERATION_STAGE

    if unit not in _UNIT_ORDER:
        return []
    doomed_units = set(_UNIT_ORDER[_UNIT_ORDER.index(unit):])

    doomed_ops: set[str] = set()
    for u in doomed_units:
        doomed_ops.update(_UNIT_OPS.get(u, ()))

    ops = set(bs.get("ops_done") or [])
    bs["ops_done"] = sorted(op for op in ops if op not in doomed_ops)

    for gate in GATE_SLOTS:
        prereq_op = _GATE_PREREQ_OP.get(gate)
        if prereq_op in doomed_ops:
            filled.pop(gate, None)

    # The user's plan-editor work is not scratch. Keep it aside (only when a
    # generated base exists to diff against) so the regeneration can merge it
    # back — see meta_spec/merge.py. Without a base the plan is dropped as before.
    if "campaign" in doomed_units and bs.get("marketing_plan") and bs.get("plan_base"):
        bs["marketing_plan_prev"] = bs["marketing_plan"]

    for u in doomed_units:
        for key in _UNIT_BS_SCRATCH.get(u, ()):
            bs.pop(key, None)

    if "geocode" in doomed_units or "poi_search" in doomed_units:
        ws = dict(bs.get("geo_ws") or {})
        if "geocode" in doomed_units:
            for key in _LOCATION_WS_KEYS:
                ws.pop(key, None)
        if "poi_search" in doomed_units:
            for key in _POI_WS_KEYS:
                ws.pop(key, None)
        bs["geo_ws"] = ws

    doomed_stages = {_OPERATION_STAGE[op] for op in doomed_ops if op in _OPERATION_STAGE}
    bs["stages_complete"] = sorted(set(bs.get("stages_complete") or []) - doomed_stages)
    bs["iteration"] = 0

    rolled_back = [s for s in STAGE_ORDER if s in doomed_stages]
    logger.info(
        "builder edits: invalidated units=%s ops_remaining=%s",
        sorted(doomed_units), bs["ops_done"],
    )
    return rolled_back


def refresh_copy(bs: dict, filled: dict) -> None:
    """Re-run the brief and refresh the ad copy WITHOUT rebuilding the campaign.

    For the prompt-only campaign fields (``target_audience``, business description,
    industry, product offer, business name). They shaped the ad copy that already
    exists but have no control in the plan editor, so the honest options are to
    refuse or to redraft — and redraft is the one that respects what the user asked
    for.

    Deliberately NOT ``invalidate_from(bs, filled, "campaign")``: that pops ``brief``
    AND ``marketing_plan`` (see ``_UNIT_BS_SCRATCH``), deleting the user's entire
    editor tree — copy, media, audiences, budgets, dayparting — over a wording
    change. Here only ``generate_brief`` is undone. ``generate_meta_json``,
    ``marketing_plan`` and the stage completion all stay, so ``_next_step`` re-runs
    the brief, leaves the spec alone, and re-opens the editor with fresh
    suggestions beside the user's untouched work.
    """
    bs["ops_done"] = sorted(set(bs.get("ops_done") or []) - {"generate_brief"})
    filled.pop("plan_confirm", None)
    # Consumed once by _plan_form_extra's next render (see _backfill_copy_suggestions).
    bs["_copy_refresh"] = True
    # The editor is the campaign stage's exit gate, so un-complete the stages that
    # closed behind it — mirrors _reopen_plan_editor.
    bs["stages_complete"] = sorted(
        set(bs.get("stages_complete") or []) - {"campaign", "media"}
    )
    logger.info("builder edits: copy redraft — brief re-runs, spec preserved")


# ── apply ─────────────────────────────────────────────────────────────────────

# Edit keys that are directives to the builder rather than field values.
_CONTROL_KEYS: frozenset[str] = frozenset({
    "_reopen_plan", "_restart_step", "_redraft", "_audience_filter_patch",
    "_poi_selection", "_angle_removals", "_undo", "_delegate_rest", "_location_ops", "_plan_edits",
    "_angle_locations", "_poi_ring",
})

# Undo-stack depth (bs["_undo_stack"]) — see the snapshot push in
# apply_pending_edits and interject_tools.undo() (Phase 2's handoff lane).
_UNDO_STACK_MAX = 10

# The user's own decisions — never scratch, never dropped by ``invalidate_from``,
# always captured by an undo snapshot. ``geo_ws`` keys are the map's decisions;
# ``bs`` keys are replayable lists (folded over a fresh search).
GEO_DECISION_KEYS: tuple[str, ...] = (
    "_search_ring_km", "_loc_radius_overrides", "_manual_pins", "_excluded_areas",
)
BS_DECISION_KEYS: tuple[str, ...] = (
    "_poi_selection_specs", "_audience_filter_specs", "_map_added_pois", "_poi_ring_specs",
)


def push_undo(
    bs: dict, *, unit: Optional[str], filled: Optional[dict] = None,
    geo_before: Optional[dict] = None, user_info: Optional[dict] = None,
    plan: Any = None, keys: tuple[str, ...] = BS_DECISION_KEYS, **prior: Any,
) -> None:
    """Push one v2 (inverse-edit) undo snapshot — the ONE place it is built.

    ``filled`` / ``geo_before`` / ``user_info`` are the values from BEFORE the
    change (default: ``bs`` as it is now, i.e. call before writing). ``keys``
    picks which replayable ``bs`` lists to carry; ``prior`` overrides a key's
    value when the caller has already touched it. ``unit`` is what undo
    invalidates so the derived outputs are rebuilt, not restored.
    """
    snap: dict = {
        "v": 2,
        "filled": dict((bs.get("filled") if filled is None else filled) or {}),
        "unit": unit,
        "user_info": dict(user_info or {}),
        "geo_ws": geo_before if geo_before is not None else {},
    }
    if plan is not None:
        snap["plan"] = copy.deepcopy(plan)
    for k in keys:
        snap[k] = copy.deepcopy(list(prior[k] if k in prior else bs.get(k) or []))
    stack = list(bs.get("_undo_stack") or [])
    stack.append(snap)
    bs["_undo_stack"] = stack[-_UNDO_STACK_MAX:]

# Builder scratch buckets an executor's ``ws`` is persisted into. ``builder_ask``
# stashes onto ``bs`` directly; the executors inside ``builder_act`` only hold a
# ``ws``, which rides out to ``bs`` under one of these keys on a normal return.
# Sweeping them here means no return path in builder_act needs to know about edits.
_WS_KEYS: tuple[str, ...] = ("geo_ws", "maid_ws", "media_ws")

_STASH_KEY = "_pending_edits"

# "Take me back to X" as a first-class transition rather than a separate mode.
# ``ResumeIntent.target_step_key`` has always existed and nothing consumed it;
# with invalidate_from in place, a backtrack is just an invalidation whose slot
# is also cleared, so it reuses the same deterministic path as an edit.
_RESTART_KEY = "_restart_step"


def _step_to_slot(step_key: str) -> Optional[str]:
    """The slot a STEP_PROMPTS step collects, or None."""
    for slot in SLOTS.values():
        if slot.step_key == step_key:
            return slot.name
    return None


# Confirmation steps with no Slot of their own — the executor holds the answer
# as a bare ``ws`` boolean (``geo.py``'s ``_location_confirmed`` /
# ``_store_confirmed``), durable only because ``invalidate_from``'s "geocode"
# unit prunes ``geo_ws`` by KEY, not wholesale (see ``_LOCATION_WS_KEYS``). A
# backtrack here is "clear that flag" — expressed as dooming the unit that
# owns it, which prunes it the same way a field edit would.
_STEP_UNIT: dict[str, str] = {
    "geo_location_confirmation": "geocode",
    "geo_store_confirmation": "geocode",
}


def resolve_backtrack_target(step_key: str) -> tuple[str, Optional[str]]:
    """What a "take me back to X" backtrack at ``step_key`` should act on.

    Returns ``("slot", slot_name)``, ``("unit", unit_name)``, or
    ``("none", None)`` when the step resolves to nothing actionable — most of
    ``STEP_PROMPTS`` is either a Slot or one of the two ``_STEP_UNIT`` flags,
    but disambiguation steps (per-name, mid-loop) and a handful of
    read-only/no-op steps map to neither. Callers MUST refuse ``"none"``
    rather than ack it: acking a backtrack that then does nothing is the exact
    false-acknowledgment this module exists to prevent (see the module
    docstring).
    """
    slot_name = _step_to_slot(step_key)
    if slot_name is not None:
        return "slot", slot_name
    if step_key in _STEP_UNIT:
        return "unit", _STEP_UNIT[step_key]
    return "none", None


def current_edit_base(state: Any, bs: dict) -> dict[str, list]:
    """Current value of every appendable field, as a list, for the router's merge.

    ``_dispatch_edit_intent`` merges an ``is_append`` against ``edit_base[field]``.
    Only the two geo confirm sites ever supplied one, so at a ``builder_ask``
    interrupt — the path for 22 of 23 slots — ``existing`` fell back to ``[]`` and
    "also add Toronto" produced ``["Toronto"]``. Montreal was dropped: the user
    asked to ADD and got a REPLACE.

    Read from ``user_info``, NOT from ``bs["filled"]``. ``filled`` stores
    ``", ".join(...)``, so ``"New York, NY, Boston"`` is already ambiguous there,
    while ``user_info["location"]`` stays a genuine list — ``_slot_user_info_patch``
    deliberately never stomps it with the joined string. Comma-splitting the filled
    value is the fallback, and it is only safe for token fields (``det_type``),
    whose values cannot contain a comma.
    """
    user_info = {}
    try:
        user_info = (state or {}).get("user_info") or {}
    except (AttributeError, TypeError):
        user_info = {}
    filled = bs.get("filled") or {}

    base: dict[str, list] = {}
    for field in APPENDABLE_FIELDS:
        slot_name = resolve_edit_target(field, filled)
        slot = SLOTS.get(slot_name) if slot_name else None

        value = user_info.get(slot.prefill_key) if (slot and slot.prefill_key) else None
        if value is None:
            value = user_info.get(field)

        if isinstance(value, list):
            current = [v for v in value if v not in (None, "")]
        elif isinstance(value, str) and value.strip():
            current = [t.strip() for t in value.split(",") if t.strip()]
        elif slot is not None and str(filled.get(slot.name, "") or "").strip():
            # Last resort — see the docstring on why this is token-fields-only safe.
            current = [t.strip() for t in str(filled[slot.name]).split(",") if t.strip()]
        else:
            current = []

        if current:
            base[field] = current
    return base


def stash_edits(scratch: dict, result: Any, *, exclude: Any = ()) -> None:
    """Park a ``ResumeResult``'s cross-step edits for ``apply_pending_edits``.

    ``scratch`` is ``bs`` in ``builder_ask`` or an executor's ``ws`` inside
    ``builder_act``; both reach ``apply_pending_edits`` via the drain below.
    Control keys (``_reopen_plan``, ``_restart_step``, ``_redraft``) ride along
    and are handled by the caller.

    ``exclude`` names fields the CALLER already consumed itself — the geo
    location/store confirms apply their own field via ``rerun_on_edit`` and
    re-geocode in place, so stashing it too would apply it twice and invalidate
    the very stage that is mid-execution.

    No-op when nothing is left to stash, which is the overwhelmingly common case
    — the happy path never allocates.
    """
    edits = getattr(result, "edits", None)
    if not edits:
        return
    skip = set(exclude or ())
    keep = {k: v for k, v in edits.items() if k not in skip}
    if not keep:
        return
    bucket = dict(scratch.get(_STASH_KEY) or {})
    bucket.update(keep)
    scratch[_STASH_KEY] = bucket


def _drain(bs: dict) -> tuple[dict, Optional[str]]:
    """Collect and clear every stashed bucket — ``bs`` plus each ``ws``.

    Returns ``(edits, restart_step_key)``.
    """
    pending: dict = dict(bs.pop(_STASH_KEY, None) or {})
    for ws_key in _WS_KEYS:
        ws = bs.get(ws_key)
        if isinstance(ws, dict) and ws.get(_STASH_KEY):
            ws = dict(ws)
            incoming = ws.pop(_STASH_KEY) or {}
            if _RESTART_KEY in pending and _RESTART_KEY in incoming:
                # Only one restart survives one turn (last write wins, below) —
                # this fires only if two DIFFERENT stash sites both raised one
                # in the same undrained window, which should not happen in
                # practice (one wizard_interrupt resolves per turn).
                logger.warning(
                    "builder edits: two pending backtracks (%r, %r) — keeping %r",
                    pending[_RESTART_KEY], incoming[_RESTART_KEY], incoming[_RESTART_KEY],
                )
            pending.update(incoming)
            bs[ws_key] = ws
    # A backtrack rides in as a control key on the edits bucket, since that is
    # the channel _dispatch_edit_intent already writes to.
    restart: Optional[str] = pending.pop(_RESTART_KEY, None)
    return pending, restart


def collect_pending(bs: dict) -> dict:
    """Sweep every stashed bucket — ``bs`` plus each ``ws`` — into ONE bs-level
    bucket, and return it.

    ``builder_plan`` handles the control keys (``_reopen_plan``, ``_redraft``)
    itself before calling ``apply_pending_edits``, and it read them off
    ``bs["_pending_edits"]`` only. The 7 executor interrupt sites stash onto a
    ``ws``, so a control key raised there — a refused campaign edit typed at the
    pixel picker, say — never reached that read and was then skipped by the field
    loop as a ``_CONTROL_KEY``: dropped silently, after the user had been told
    "I've reopened the editor below". That is the same false-acknowledgment this
    module exists to prevent, surviving in the control channel.

    Consolidating first makes the control keys reachable from one place. The
    bucket is written back to ``bs`` so the later ``apply_pending_edits`` drain
    still sees whatever the caller did not consume; mutating the returned dict
    (``pop``) mutates that bucket, which is exactly how the caller removes a
    control key it has handled.
    """
    pending, restart = _drain(bs)
    if restart:
        pending[_RESTART_KEY] = restart
    if pending:
        bs[_STASH_KEY] = pending
    return pending


@dataclass(frozen=True)
class Outcome:
    """What ONE requested change actually did — the only thing narration may
    claim. Every field an edit named ends in exactly one of these.

      applied      written as asked
      adjusted     written, but not as asked (clamped / converted) — `detail` says how
      no_op        already that value; nothing rebuilt
      refused      understood, deliberately not done — `detail` says why
      unsupported  nothing in the build can take it — `detail` says what
    """

    field: str
    status: Literal["applied", "adjusted", "no_op", "refused", "unsupported"]
    detail: str = ""


def _as_text(value: Any) -> str:
    """Slot values are stored as strings; a multi-item edit joins on ", "."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v is not None)
    return str(value)


# The circle Places searches inside, as the classifier names it (UserInfo name /
# STEP_PROMPTS field). NOT ``poi_radius_m`` — that is the per-POI visit ring.
_SEARCH_RING_FIELDS: frozenset[str] = frozenset({"search_radius_km", "geo_radius_km"})
# The two slots that already hold a search radius for their own route.
_SEARCH_RING_SLOTS: tuple[str, ...] = ("radius_km", "competitor_radius_km")


# Slots holding a length, and the unit their value is stored in.
_LENGTH_SLOT_UNIT: dict[str, str] = {
    "radius_km": "km", "competitor_radius_km": "km", "poi_radius_m": "m",
}


def _clamp_deviation(label: str, text: str, unit: str, stored: Any) -> Optional[str]:
    """A plain sentence when the value written differs from the value asked
    (clamped to a bound), else None — so "set it to 200 km" is never reported
    as done at 200 when 80 was written."""
    from app.graph.wizard_helpers import parse_length

    asked = parse_length(text, unit, default=None)
    try:
        got = float(stored)
    except (TypeError, ValueError):
        return None
    # Stored values are rounded (a circle to 0.1 km, a ring to whole metres):
    # 5 miles = 8.05 km stored as 8.0 is not "the allowed limit".
    if asked is None or abs(asked - got) <= (0.06 if unit == "km" else 1.0):
        return None
    return f"{label}: asked for {asked:g} {unit}, set to {got:g} {unit} (the allowed limit)"


def _apply_search_ring(bs: dict, text: str) -> Optional[list[str]]:
    """Write a typed search-circle radius onto the geocoded locations.

    For a run whose radius lives on the LOCATIONS (a city/address/pin the
    confirm map draws a circle around) rather than in a radius slot — the
    ``radius_km`` slot is only read by a radius-scope run, so a typed radius
    resolved there was acked and then lost. Returns what
    ``executors.geo.set_search_ring`` returns (changed labels / ``[]`` pending /
    ``None`` nothing to write), or ``None`` for an unparseable value.
    """
    from app.graph.builder.executors.geo import set_search_ring
    from app.graph.wizard_helpers import parse_length

    km = parse_length(text, "km", default=None)
    if not km or km <= 0:
        return None
    ws = dict(bs.get("geo_ws") or {})
    labels = set_search_ring(ws, km)
    if labels is not None:
        bs["geo_ws"] = ws
    return labels


def _apply_poi_ring(bs: dict, op: dict) -> dict:
    """One typed visit-ring change for a GROUP of spots → ``{"status", "detail",
    "deviation"?}``. Stored in ``bs["_poi_ring_specs"]`` (a decision, replayed by
    the maid query onto whichever spots match) — matched against the spots on the
    map now so "the gyms" that match nothing is refused, not silently stored."""
    from app.graph.builder.builder_node import _normalize_slot_answer
    from app.graph.builder.executors.poi_selection import resolve_drop_predicate

    match = re.sub(
        r"^(?:(?:all|the|my|these|those|every)\s+)+|(?:\s+(?:spots?|places?|ones|locations?|venues?))+$",
        "", str(op.get("match") or "").strip(), flags=re.IGNORECASE,
    ).strip()
    raw = str(op.get("value") or "")
    stored = _normalize_slot_answer("poi_radius_m", raw)
    if not match or not str(stored).strip().isdigit():
        return {"status": "refused", "detail": f"{raw[:30]!r} isn't a distance, or no group of spots was named"}
    metres = int(stored)
    pois = (bs.get("geo_result") or {}).get("targetable_pois") or []
    count = None
    if pois:
        count = len(resolve_drop_predicate(pois, match))
        if not count:
            return {"status": "refused", "detail": f"nothing on the map matches {match!r}"}
    key = " ".join(match.lower().split())
    specs = list(bs.get("_poi_ring_specs") or [])
    if any(" ".join(str(s.get("match")).lower().split()) == key and s.get("radius_m") == metres for s in specs):
        return {"status": "no_op", "detail": f"the visit ring for {match} was already {metres} m"}
    bs["_poi_ring_specs"] = [
        s for s in specs if " ".join(str(s.get("match")).lower().split()) != key
    ] + [{"match": match, "radius_m": metres}]
    where = f"{count} spot(s)" if count is not None else "the spots found"
    detail = f"visit ring for {match} ({where}) = {metres} m"
    deviation = _clamp_deviation("visit ring", raw, "m", metres)
    return {"status": "adjusted" if deviation else "applied", "detail": detail, "deviation": deviation}


def _activate_angle_for(slot: Any, field: str, filled: dict, ui_patch: dict) -> Optional[str]:
    """When ``slot`` is gated ``only_when=("det_type", angle)`` and that angle
    isn't active, union it into ``det_type`` so the write below isn't silently
    unread.

    ``resolve_edit_target`` falls back to a slot even when ``slot_applies`` is
    False (its docstring: "a not-yet-determinable route still resolves to
    something deterministic"). That is correct for a route the build hasn't
    reached yet, but wrong for an edit: "target Starbucks, Tim Hortons" at the
    POI-confirm gate resolves to ``brand_names`` while ``det_type`` is still
    ``ai_suggested`` — the executor's ``competitor_brand`` arm never reads it
    (``executors/geo.py``, every subtype-gated field is read inside its own
    ``if "<angle>" in subtype_set:``), so geo re-runs on unchanged inputs and
    the brands sit in ``filled`` forever, since ``missing_required_slots`` also
    skips an inapplicable slot. The angle is exactly what activates both reads.

    Only fires for an alias that resolves to ONE slot — ``search_radius_km``
    aliases to both ``radius_km`` and ``competitor_radius_km``, and inferring
    ``competitor_nearby`` from a bare radius change would be a guess this
    function has no business making.

    Returns the activated angle token for the caller's thinking line, or None.
    """
    if slot.only_when is None or slot.only_when[0] != "det_type":
        return None
    if slot_applies(slot, filled):
        return None
    if len(EDIT_ALIASES.get(field, ())) != 1:
        return None
    angle = merge_angle_tokens(filled.get("det_type", ""), slot.only_when[1])
    filled["det_type"] = angle
    ui_patch["deterministic_subtype"] = [
        t.strip() for t in angle.split(",") if t.strip()
    ]
    return angle


# Extraction keys that are transport / owned by their own appliers, never a
# plain typed change.
_EXTRACTION_SKIP = frozenset({
    "audience_filter", "poi_selection", "deterministic_subtype", "deterministic_subtypes",
    "targeting_angles", "geo_angle_specs",
})


def edits_from_extraction(
    extracted: dict, state: Any, bs: dict,
) -> tuple[dict, list[str]]:
    """Turn what entry extraction read from a free-text message sent OUTSIDE an
    interrupt ("actually make it 500 a week") into pending edits, so it goes
    through the same bus — applied, narrated and undoable — instead of only
    landing in ``user_info``, where every already-filled slot ignored it.

    Returns ``(edits, held)``. Rules, each chosen to fail safe:
      * only knobs a typed edit can reach (``is_actionable_field``, not media,
        not the specs that have their own appliers);
      * a list only ever GAINS items (extraction can't tell "also add Laval"
        from "actually Laval"; an add never drops anything, and undo reverts it);
      * a cost-bearing change is HELD once audience data was already bought —
        a stray extraction must not re-buy vendor data; ``held`` names those so
        the caller can say so instead of dropping them silently.
    """
    from app.graph.builder.knobs import knob_for_field

    ops_done = set(bs.get("ops_done") or [])
    bought = "maid_query" in ops_done
    base = current_edit_base(state, bs)
    edits: dict = {}
    held: list[str] = []
    for field, value in (extracted or {}).items():
        if value in (None, "", []) or field in _EXTRACTION_SKIP:
            continue
        if not is_actionable_field(field) or FIELD_OWNER.get(field) == "media":
            continue
        knob = knob_for_field(field)
        if knob is None or knob.tool:
            continue
        if bought and canonical_field(field) in _COST_BEARING_FIELDS:
            held.append(field)
            continue
        if isinstance(value, (list, tuple)) or field in APPENDABLE_FIELDS:
            new_items = list(value) if isinstance(value, (list, tuple)) else [value]
            have = [str(x) for x in (base.get(field) or [])]
            merged = have + [x for x in new_items if str(x).strip().lower() not in {h.lower() for h in have}]
            if merged != have:
                edits[field] = merged
        else:
            edits[field] = value
    return edits, held


@dataclass
class EditReport:
    """Everything one drain of the pending edits did. ``outcomes`` has one
    entry per field the user named (see ``Outcome``)."""

    ui_patch: dict
    rolled_back: list[str]
    note: Optional[str]
    outcomes: list[Outcome]


def apply_pending_edits(bs: dict, state: Any = None) -> tuple[dict, list[str], Optional[str]]:
    """``apply_edits`` as the historic ``(user_info_patch, rolled_back, note)``
    triple — kept for the callers and tests that unpack three values."""
    report = apply_edits(bs, state)
    return report.ui_patch, report.rolled_back, report.note


def apply_edits(bs: dict, state: Any = None) -> EditReport:
    """Drain every stashed edit into the build and invalidate what it breaks.

    Every edit reaching here has already cleared ``edit_block_reason`` and the
    confidence floor in ``_dispatch_edit_intent``; this function's job is to
    make each one TRUE or say exactly how it isn't, as one ``Outcome`` per field.

    ``state`` is optional so unit tests can drive a bare ``bs``; when a real
    ``state`` is passed (``builder_plan`` always does), every outcome lands in
    the narrator's change ledger (``record_change``): applied / no_op as
    ``applied`` (popping the matching ``heard``), adjusted as ``applied`` +
    ``deviation``, refused as ``deviation``, unsupported as ``unsupported``. A
    ``heard`` with no outcome at all stays in ``heard_not_applied``.
    """
    from app.graph.builder.builder_node import _normalize_slot_answer
    from app.graph.narrator.beats import record_change

    pending, restart_step = _drain(bs)
    if not pending and not restart_step:
        return EditReport({}, [], None, [])

    filled = dict(bs.get("filled") or {})
    # Pre-edit copies for the undo snapshot — the search-ring writer mutates
    # geo_ws in place, so capture before the loop, not at push time.
    _geo_before = {
        k: copy.deepcopy((bs.get("geo_ws") or {}).get(k)) for k in GEO_DECISION_KEYS
    }
    _ring_before = list(bs.get("_poi_ring_specs") or [])
    ui_patch: dict = {}
    removals: set[str] = {
        str(t).strip().lower() for t in (pending.get("_angle_removals") or []) if str(t).strip()
    }
    applied: list[str] = []
    applied_by_field: dict[str, str] = {}
    deviations: list[str] = []
    unsupported: list[str] = []
    outcomes: list[Outcome] = []
    earliest_unit: Optional[str] = None

    def _note_unit(unit: str) -> None:
        nonlocal earliest_unit
        if unit not in _UNIT_ORDER:
            return
        if earliest_unit is None or _UNIT_ORDER.index(unit) < _UNIT_ORDER.index(earliest_unit):
            earliest_unit = unit

    def _done(field: str, summary: str, deviation: Optional[str] = None) -> None:
        applied_by_field[field] = summary
        if deviation:
            deviations.append(deviation)
            outcomes.append(Outcome(field, "adjusted", deviation))
        else:
            outcomes.append(Outcome(field, "applied", summary))

    def _no_op(field: str, summary: str) -> None:
        # Resolves the `heard` truthfully (nothing to rebuild) — never counted
        # as a change, never invalidates.
        applied_by_field[field] = summary
        outcomes.append(Outcome(field, "no_op", summary))

    def _unsupported(field: str, why: str) -> None:
        from app.graph import capability_miss

        logger.warning("builder edits: %r has nowhere to land (%s) — dropped", field, why)
        capability_miss.record("dropped_edit", step_key="", field=field, detail=why)
        unsupported.append(why)
        outcomes.append(Outcome(field, "unsupported", why))

    _ui_state = ((state or {}).get("user_info") or {}) if isinstance(state, dict) else {}

    def _angle_specs_now() -> list:
        return copy.deepcopy(ui_patch.get("geo_angle_specs", _ui_state.get("geo_angle_specs")) or [])

    # "Events only in Montreal": where ONE search looks. Written as per-angle
    # specs; the flat location list stays the union of every name any angle uses.
    from app.graph.builder import angle_locations as _al

    for _op in pending.get("_angle_locations") or []:
        _res = _al.apply_op(
            _op, filled=filled, specs=_angle_specs_now(),
            flat=ui_patch.get("location") or _al.flat_names(filled, _ui_state),
        )
        if _res["status"] == "refused":
            deviations.append(f"didn't change where to search — {_res['detail']}")
            outcomes.append(Outcome("angle_locations", "refused", _res["detail"]))
        elif _res["status"] == "no_op":
            _no_op("angle_locations", _res["detail"])
        else:
            _old_flat = ui_patch.get("location") or _al.flat_names(filled, _ui_state)
            ui_patch["geo_angle_specs"] = _res["specs"]
            applied.append(f"angle_locations→{_res['detail'][:60]}")
            _done("angle_locations", _res["detail"])
            if {_al.norm(n) for n in _res["flat"]} != {_al.norm(n) for n in _old_flat}:
                ui_patch["location"] = _res["flat"]
                filled["locations"] = ", ".join(_res["flat"])
                _note_unit("geocode")
            else:
                # Same places to geocode; only WHICH search uses which changed. The
                # confirm map's per-angle sync would override the new specs.
                (bs.get("geo_ws") or {}).pop("_angle_names_synced", None)
                _note_unit("poi_search")

    # "100 m for the gyms": the visit ring for some spots only.
    for _rop in pending.get("_poi_ring") or []:
        _res = _apply_poi_ring(bs, _rop)
        outcomes.append(Outcome(
            "poi_ring", _res["status"], _res["deviation"] if _res["status"] == "adjusted" else _res["detail"],
        ))
        if _res["status"] in ("applied", "adjusted"):
            applied.append(f"poi_ring→{_res['detail'][:60]}")
            applied_by_field["poi_ring"] = _res["detail"]
            if _res["status"] == "adjusted":
                deviations.append(_res["deviation"])
            _note_unit("maid_query")
        elif _res["status"] == "no_op":
            applied_by_field["poi_ring"] = _res["detail"]
        else:
            deviations.append(f"didn't change the visit ring — {_res['detail']}")

    for field, value in pending.items():
        if field in _CONTROL_KEYS:
            continue
        text = _as_text(value)

        # A search-circle radius on a run that draws it per location. Radius-scope
        # and competitor_nearby runs keep the slot path below — their executors
        # read `radius_km` / `competitor_radius_km`.
        if field in _SEARCH_RING_FIELDS and not any(
            slot_applies(SLOTS[n], filled) for n in _SEARCH_RING_SLOTS
        ):
            _prev_ring = (bs.get("geo_ws") or {}).get("_search_ring_km")
            _had_drags = any(
                (ov or {}).get("radius_km") for ov in (_geo_before.get("_loc_radius_overrides") or {}).values()
            )
            labels = _apply_search_ring(bs, text)
            if labels is None:
                _unsupported(
                    field,
                    "search circle: that size isn't a distance, or these locations "
                    "are whole states/regions with no circle to resize",
                )
                continue
            ring = (bs.get("geo_ws") or {}).get("_search_ring_km")
            if ring == _prev_ring and not _had_drags:
                _no_op(field, f"search circle was already {ring:g} km")
                continue
            applied.append(f"{field}→search_ring={ring}")
            _done(field, f"search circle = {ring:g} km", _clamp_deviation("search circle", text, "km", ring))
            if labels:
                # Re-run the Places search inside the resized circle. The
                # location confirm survives (geocode is not doomed).
                _note_unit("poi_search")
            continue

        slot_name = resolve_edit_target(field, filled)

        if slot_name is not None:
            slot = SLOTS[slot_name]
            _activated = None
            if slot_name == "det_type":
                # Angles COMPOSE. Union against what's CURRENTLY running, not just
                # `value` — the router's own append-merge (wizard_helpers.py) only
                # unions correctly when it can see the stored set via `edit_base`;
                # when that lookup comes up empty (or an LLM's is_append flag was
                # wrong), a bare `merge_angle_tokens(value)` here silently replaced
                # the whole angle set — losing a running arm (e.g. a named brand)
                # with no error, anywhere. This is the one place every angle edit
                # commits through, so the guard belongs here, not upstream.
                text = merge_angle_tokens(filled.get("det_type"), value)
                if removals:
                    kept = [t for t in text.split(",") if t and t not in removals]
                    if not kept:
                        # Nothing left to search for — refuse rather than run an
                        # empty build; the user is told why.
                        why = (
                            "kept the targeting angles as they were: removing "
                            f"{', '.join(sorted(removals))} would leave nothing to target"
                        )
                        deviations.append(why)
                        outcomes.append(Outcome(field, "refused", why))
                        continue
                    text = ",".join(kept)
            elif (
                # Never re-activate an angle the same reply removed, and never
                # activate one for an emptying edit ("stop searching cafes" sets
                # poi_types to []) — either put `category` straight back after
                # "forget the cafes, just do events".
                (slot.only_when or ("", ""))[1] not in removals
                and str(text).strip()
            ):
                _activated = _activate_angle_for(slot, field, filled, ui_patch)
                if _activated:
                    applied.append(f"det_type+={_activated}")
                    _note_unit("poi_search")
            new_value = _normalize_slot_answer(slot_name, text)
            if text.strip() and not str(new_value).strip():
                # The normalizer couldn't read it (an unrecognised scope, say).
                # Writing "" would silently blank the slot; say so instead.
                _unsupported(field, f"couldn't read {text[:40]!r} as a {slot_name.replace('_', ' ')}")
                continue
            if (
                not _activated
                and slot_name not in GATE_SLOTS
                and str(filled.get(slot_name) or "") == str(new_value)
            ):
                _no_op(field, f"{slot_name.replace('_', ' ')} was already {str(new_value)[:40]}")
                continue
            if slot_name == "locations":
                # A flat location edit means EVERY search, including one that
                # pinned its own cities: "remove Montreal" must leave that
                # search's list too, or the geocode union puts Montreal back.
                _old_flat = ui_patch.get("location") or _al.flat_names(filled, _ui_state)
                _new_flat = _al.dedupe(list(value) if isinstance(value, (list, tuple)) else text.split(","))
                _respec = _al.rewrite_specs_for_flat_edit(_angle_specs_now(), _old_flat, _new_flat)
                if _respec is not None:
                    ui_patch["geo_angle_specs"] = _respec
            filled[slot_name] = new_value
            _dev = None
            if slot_name in _LENGTH_SLOT_UNIT:
                _dev = _clamp_deviation(
                    slot_name.replace("_", " "), text, _LENGTH_SLOT_UNIT[slot_name], filled[slot_name],
                )
            if slot_name == "poi_radius_m" and bs.get("_poi_ring_specs"):
                # "Every spot" means every spot: a per-group ring left standing
                # would silently override it for those groups.
                _groups = ", ".join(str(r.get("match")) for r in bs["_poi_ring_specs"])
                bs["_poi_ring_specs"] = []
                _reset = f"the separate visit ring you set for {_groups} was reset to match"
                _dev = f"{_dev}; {_reset}" if _dev else _reset
            if slot_name == "det_type":
                # The committed set (union, minus removals), not the raw edit
                # value — which may be a partial list the union just corrected.
                ui_patch["deterministic_subtype"] = [
                    t for t in str(filled[slot_name]).split(",") if t
                ]
            elif slot.prefill_key:
                # Keep the richer structure (a list stays a list) for user_info;
                # `filled` is the string-typed layer, user_info is not.
                ui_patch[slot.prefill_key] = value
            applied.append(f"{field}→{slot_name}={text[:40]}")
            _done(field, f"{field} = {text[:40]}", _dev)
            # A gate is a confirm screen for work that already exists, so a
            # reply naming one is an ANSWER, not a change to anything upstream.
            # It has no _SLOT_UNIT entry, so `_unit_for_slot` would fall back to
            # its stage's first unit ("geocode" for poi_confirm) and roll the
            # whole build back — re-running the Places search and re-buying
            # Unacast data. The backtrack branch below already special-cases
            # gates for exactly this reason; the edit path did not.
            if slot_name not in GATE_SLOTS:
                _note_unit(_unit_for_slot(slot_name))
            continue

        # No slot owns it. The campaign intake writes several bare keys straight
        # into `filled` (business_name, objective, ...) and other campaign fields
        # live only in user_info; both are read by the brief + spec builders.
        owner = FIELD_OWNER.get(field)
        if owner == "campaign":
            if field in filled:
                filled[field] = text
            ui_patch[field] = value
            applied.append(f"{field}={text[:40]} (campaign)")
            _done(field, f"{field} = {text[:40]}")
            _note_unit("campaign")
            continue

        # Unreachable after `is_actionable_field` became the ack gate
        # (resume_router._validate_edit_target) — this predicate IS that
        # gate's apply-side half, so the two can no longer disagree. Kept as
        # the canary for the gates re-diverging: if this ever fires again,
        # something was acked that has nowhere to land, same bug class as
        # before.
        _unsupported(field, "acked (is_actionable_field) but apply found no slot/owner")

    # "Go back to where I picked locations." Three shapes, by what the step
    # resolves to (``resolve_backtrack_target`` — validated already, at
    # classification time in ``wizard_helpers._dispatch_edit_intent``, so a
    # "none" here would mean that guard has a gap, not a legitimate case):
    #   slot, NOT a gate  — clear the slot (planner re-asks it) and invalidate
    #                       the unit it feeds, same as an edit to that field.
    #   slot, IS a gate   — clear the gate answer ONLY. A gate is a confirm
    #                       screen for work that already exists; invalidating
    #                       anything would re-run a POI search / warehouse
    #                       query the user only asked to look at again.
    #   unit (no slot)    — the executor's own ws-flag confirmations
    #                       (geo_location_confirmation / geo_store_confirmation
    #                       have no Slot). Dooming the unit is "clear that flag"
    #                       — invalidate_from's geo_ws prune does the clearing.
    # No checkpoint is touched either way, so every OTHER answer the user
    # already gave survives — the property the 2026-06 rewind lacked.
    if restart_step:
        kind, target = resolve_backtrack_target(restart_step)
        if kind == "slot":
            if target in GATE_SLOTS:
                filled.pop(target, None)
                applied.append(f"restart@{restart_step}(gate)")
            else:
                slot = SLOTS[target]
                filled.pop(target, None)
                _activated = _activate_angle_for(slot, target, filled, ui_patch)
                if _activated:
                    applied.append(f"det_type+={_activated}")
                applied.append(f"restart@{restart_step}")
                _note_unit(_unit_for_slot(target))
        elif kind == "unit":
            applied.append(f"restart@{restart_step}")
            _note_unit(target)
        else:
            logger.warning(
                "builder edits: restart step %r maps to no target — dropped", restart_step
            )
        if kind != "none":
            # Synthetic key — matches the `heard={f"__backtrack__:{step}": ...}`
            # _dispatch_edit_intent records at ack time (a backtrack carries no
            # target_field to key on).
            _key = f"__backtrack__:{restart_step}"
            applied_by_field[_key] = f"went back to {restart_step}"
            outcomes.append(Outcome(_key, "applied", f"went back to {restart_step}"))

    def _ledger() -> None:
        if state is not None and (applied_by_field or deviations or unsupported):
            record_change(
                state, applied=applied_by_field or None,
                deviation=deviations or None, unsupported=unsupported or None,
            )

    if not applied:
        # Nothing changed — but a refusal, an already-that-value, or an
        # unsupported ask still has to reach the user: through the ledger and
        # the outcomes. `note` stays None — it means "something committed"
        # (test_edit_ack_invariant keys on exactly that).
        _ledger()
        return EditReport({}, [], None, outcomes)

    # Undo snapshot — pushed HERE, not earlier: everything above this point
    # can still no-op, and an undo point for a commit that never happened is a
    # lie the same shape as the rest of this module exists to prevent.
    # Format v2 is an INVERSE EDIT, not a state restore: the previous `filled`,
    # the previous values of every user_info key and geo decision this commit
    # touched, and the unit it invalidated. `undo` writes those back and
    # invalidates the same unit, so the build is rebuilt consistently —
    # restoring `ops_done` (v1) claimed work whose outputs invalidate_from had
    # already popped. Bounded so a long, much-revised build doesn't grow it.
    _ui_now = ((state or {}).get("user_info") or {}) if isinstance(state, dict) else {}
    # A combined turn ("bump the radius AND top 5 each category") restores BOTH
    # halves on one undo, not just whichever function ran last.
    push_undo(
        bs, unit=earliest_unit, geo_before=_geo_before, _poi_ring_specs=_ring_before,
        user_info={k: copy.deepcopy(_ui_now.get(k)) for k in ui_patch},
    )

    bs["filled"] = filled
    rolled_back = invalidate_from(bs, filled, earliest_unit) if earliest_unit else []
    bs["filled"] = filled          # invalidate_from popped gate answers in place

    note = f"applied {len(applied)} edit(s): {'; '.join(applied)}"
    if rolled_back:
        note += f" — rebuilding {', '.join(rolled_back)}"
    if deviations:
        note += " — adjusted: " + "; ".join(deviations)
    _ledger()
    return EditReport(ui_patch, rolled_back, note, outcomes)


__all__ = [
    "EDIT_ALIASES",
    "is_actionable_field",
    "canonical_field",
    "collect_pending",
    "resolve_edit_target",
    "resolve_backtrack_target",
    "invalidate_from",
    "refresh_copy",
    "current_edit_base",
    "stash_edits",
    "apply_pending_edits",
    "apply_edits",
    "edits_from_extraction",
    "EditReport",
    "Outcome",
    "edit_confidence_floor",
]


assert _RESTART_KEY in _CONTROL_KEYS, "restart key must be skipped by the field loop"
