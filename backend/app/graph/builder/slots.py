"""
graph/builder/slots.py
──────────────────────
Slot model for the campaign-builder agent (phase 5.1).

A slot is one piece of information the build needs. Each maps to an existing
``prompts_registry`` step config so ``builder_ask`` re-uses the exact widget,
prompt, and pending_action contract the wizard chain ships today — the
frontend cannot tell the difference.

The planner fills slots opportunistically from conversation/user_info and asks
only for what is missing or ambiguous; ``required_for_stage`` is what the
ordering invariant in builder_plan enforces in code (never trust the prompt).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# Pipeline order — builder_plan refuses any act/ask that jumps a stage.
STAGE_ORDER: tuple[str, ...] = ("geo", "maid", "campaign", "media")


@dataclass(frozen=True)
class Slot:
    name: str                       # canonical slot key in builder scratch
    stage: str                      # geo | maid | campaign | media
    step_key: str                   # prompts_registry key for builder_ask
    prefill_key: Optional[str] = None   # user_info key to prefill from
    required: bool = True
    # Slot only applies when this predicate over filled-slots passes.
    # Encoded as (slot_name, expected) to stay picklable/checkpointable.
    # `expected` is a single value, or a tuple of acceptable values (the slot
    # applies when the dep matches ANY of them).
    only_when: Optional[tuple[str, str | tuple[str, ...]]] = None
    # Slot is SKIPPED when the named slot's value is one of the excluded
    # values: (slot_name, excluded_value, ...). Used where only_when's single
    # equality can't express the route (e.g. locations don't apply for the
    # radius scope). Two forms:
    #   flat   (dep, v1, v2, ...)          – skip when dep matches any value.
    #   nested ((dep1, ...), (dep2, ...))  – multiple independent clauses; skip
    #                                         when ANY clause matches. Needed when
    #                                         a slot has >1 skip reason keyed off
    #                                         different deps (e.g. locations: radius
    #                                         scope OR a store-anchored det_type).
    not_when: Optional[tuple[str, ...] | tuple[tuple[str, ...], ...]] = None
    # Slot is SKIPPED when the named dep's value-set INTERSECTS these values:
    # (slot_name, value, ...). Complements `not_when` (which skips only when the
    # dep set is a SUBSET of its excluded values). Needed to skip a slot the moment
    # a given angle is present ALONGSIDE others — e.g. the competitor-anchor slots
    # are redundant when store_set co-exists with competitor_nearby (the shared
    # store address already anchors both), which the subset rule can't express.
    skip_when_any: Optional[tuple[str, ...]] = None
    # True → slot counts satisfied once its KEY is present in `filled` (even
    # empty), so a legitimate skip ("" answer) is not re-asked forever.
    # builder_ask always writes the key after asking, so key-presence reliably
    # distinguishes "asked & skipped" from "never asked".
    skippable: bool = False
    # True → an extracted/inferred value PREFILLS this slot's widget but never
    # counts as an answer on its own — builder_plan's seed loop skips writing
    # it into `filled`, so the ask always fires. For knobs that size a paid
    # audience (a ring radius, a lookback window), a guess the user never saw
    # is worse than one extra confirm click.
    confirm_prefill: bool = False


SLOTS: dict[str, Slot] = {s.name: s for s in [
    # ── geo ────────────────────────────────────────────────────────────────
    # store-anchored angles (store_set / competitor_nearby) anchor the search on
    # the user's OWN business address collected later — a named market is not needed,
    # so skip the scope question for them. competitor_area is deliberately NOT in
    # these skip lists: it is the storefront-less competitor angle (SaaS, e-commerce,
    # service-area) and searches the named market instead of a ring, so it needs
    # scope + locations and none of the anchor/radius slots below.
    Slot("location_scope", "geo", "geo_collect_location_type", prefill_key="geo_scope",
         not_when=("det_type", "store_set", "competitor_nearby")),
    # radius scope: pin + ring replace named locations (wizard parity:
    # geo_collect_location_type → radius_pin → radius_km → det_type).
    Slot("radius_pin", "geo", "geo_collect_radius_pin",
         only_when=("location_scope", "radius")),
    Slot("radius_km", "geo", "geo_collect_radius_km", prefill_key="search_radius_km",
         only_when=("location_scope", "radius"), confirm_prefill=True),
    # Skipped for the radius scope (pin replaces named locations) AND for the
    # store-anchored angles (the store address IS the location). Two independent
    # clauses → nested not_when.
    Slot("locations", "geo", "geo_collect_locations", prefill_key="location",
         not_when=(("location_scope", "radius"), ("det_type", "store_set", "competitor_nearby"))),
    # Spec order: scope → search mode → inputs. business_description is NOT asked
    # in the geo stage as its own slot — the entry gate collects it upstream (WHAT
    # is now a required routing-gate signal, same as target_audience for WHO), so
    # it is already in user_info by the time geo POI inference runs.
    # Targeting is always deterministic (physical-visit / POI), so det_type
    # follows scope/locations directly with no method question.
    Slot("det_type", "geo", "geo_collect_det_type", prefill_key="deterministic_subtype"),
    Slot("poi_types", "geo", "geo_collect_poi_types", prefill_key="poi_types",
         only_when=("det_type", "category")),
    Slot("brand_names", "geo", "geo_collect_brands", prefill_key="competitor_brands",
         only_when=("det_type", "competitor_brand")),
    Slot("named_places", "geo", "geo_collect_named_places", prefill_key="named_places",
         only_when=("det_type", "named_places")),
    Slot("event_queries", "geo", "geo_collect_events", prefill_key="event_queries",
         only_when=("det_type", "event_based")),
    # Optional: Punk finds the events from context (event queries + city) and reads
    # the real dates back from the search results. Never asked — prefilled + used
    # only when the user stated a range. Mirrors the `offer` slot (required=False).
    Slot("event_date_range", "geo", "geo_collect_event_date_range", prefill_key="event_date_range",
         only_when=("det_type", "event_based"), required=False),
    Slot("store_addresses", "geo", "geo_collect_stores", prefill_key="store_addresses",
         only_when=("det_type", "store_set")),
    # competitor_nearby: user's own store anchors the search (wizard parity:
    # geo_collect_store_anchor → geo_confirm_store_anchor → geo_collect_competitor_radius).
    Slot("competitor_anchor", "geo", "geo_collect_store_anchor", prefill_key="competitor_address",
         only_when=("det_type", "competitor_nearby"),
         # Pair store_set+competitor_nearby: the store_addresses slot already
         # collected the shared locations that anchor the competitor search — don't
         # re-ask the anchor address.
         skip_when_any=("det_type", "store_set")),
    # Confirm the geocoded anchor(s) on the map BEFORE asking the search radius —
    # a radius around a mis-geocoded store is meaningless. builder_ask geocodes the
    # anchors + emits the editable confirm map here (see _enrich_slot_ask); the
    # permission answer just resumes (parity with geo_store_confirmation). skippable:
    # a bare confirm/empty payload still marks it asked so it never re-loops.
    Slot("competitor_anchor_confirm", "geo", "geo_confirm_store_anchor",
         only_when=("det_type", "competitor_nearby"), skippable=True,
         # Pair: the shared store_set confirm (geo_store_confirmation) already shows
         # these locations on a map — one confirm, not two.
         skip_when_any=("det_type", "store_set")),
    Slot("competitor_radius_km", "geo", "geo_collect_competitor_radius", prefill_key="search_radius_km",
         only_when=("det_type", "competitor_nearby"), confirm_prefill=True),
    # POI confirmation gate. store_set is excluded: the stores ARE the POIs and
    # were already confirmed (with a map) at geo_store_confirmation, so a second
    # mapless gate here is redundant — wizard parity with geo_confirm_pois's
    # store_set skip.
    Slot("poi_confirm", "geo", "geo_pois_confirmation", required=False,
         not_when=("det_type", "store_set")),
    # ── maid ───────────────────────────────────────────────────────────────
    # (lookback is ignored by the query core for event-based targeting — it
    #  derives the date windows from the event dates instead.)
    # poi_radius_m uses the combined maid_collect_settings step so radius + lookback
    # are asked in ONE interrupt. builder_ask splits the JSON answer into both filled
    # keys; if only poi_radius comes back (single-widget fallback), lookback_days is
    # asked standalone via its own maid_collect_lookback step. Both slots stay in
    # SLOTS so act-readiness + the maid_query executor reads are unchanged.
    Slot("poi_radius_m", "maid", "maid_collect_settings", prefill_key="poi_radius_m",
         confirm_prefill=True),
    # Skipped for event_based: the maid query derives the window from the event
    # dates themselves, so a user-entered lookback is unused there.
    Slot("lookback_days", "maid", "maid_collect_lookback", prefill_key="lookback_days",
         not_when=("det_type", "event_based"), confirm_prefill=True),
    Slot("maid_confirm", "maid", "maid_confirm_results", required=False),
    # ── campaign ───────────────────────────────────────────────────────────
    # How much of the campaign Punk builds. Asked FIRST in the stage (it decides
    # whether the rest of the stage runs at all), but after the connect_meta
    # pre-act — every mode needs a connected ad account, and "export audience to
    # Meta" needs one to export the audience into.
    #   self    → export the audience as a Custom Audience, then stop.
    #   guide   → the full campaign editor (unchanged behaviour).
    #   express → short basics form, then an ads-only editor.
    # Ordering here is load-bearing: missing_required_slots walks SLOTS in
    # declaration order, so publish_mode must precede campaign_intake.
    Slot("publish_mode", "campaign", "campaign_publish_mode"),
    # Express-only intake form now: business name and what-you-sell/USP are
    # collected upstream by the entry gate (WHAT is a required routing-gate signal,
    # same as WHERE/WHO), and objective is inferred by generate_brief when the user
    # never states one — so guide mode has nothing this form is the only place to
    # ask, and goes straight from publish_mode to the plan editor. Express still
    # needs it: its editor locks the campaign/ad-set panes, so budget, flight
    # dates, which Page, and the objective select have no other home. builder_ask
    # parses the JSON submission (intake_form.parse_intake_submission), validates
    # it, and writes the individual filled/user_info keys the downstream brief +
    # spec builders read — so a submission is the source of truth for act-readiness.
    # See builder_node._enrich_slot_ask (campaign_intake branch) and
    # graph/builder/intake_form.py.
    # Skipped for self-publish (no campaign to describe, only an audience to
    # export) and for guide (nothing left for it to ask).
    Slot("campaign_intake", "campaign", "campaign_intake_form",
         not_when=("publish_mode", "self", "guide")),
    # No pixel slot: the Meta Pixel is one field of the campaign, so it is asked
    # in the plan editor (which lists the ad account's actual pixels) and only
    # when the objective/goal needs one — never as its own interrupt.
    Slot("plan_confirm", "campaign", "campaign_plan_confirm", required=False,
         not_when=("publish_mode", "self")),
    # ── media ──────────────────────────────────────────────────────────────
    # No publish gate: the plan editor's own Publish button is the confirmation,
    # and publish only creates PAUSED objects.
    # Gate on the activate op: the campaign is already built in Meta and PAUSED,
    # so this is the last thing standing between it and live spend. Skipped for
    # self-publish, which never publishes a campaign at all.
    Slot("go_live_confirm", "media", "media_confirm_go_live", required=False,
         not_when=("publish_mode", "self")),
]}

# Confirmation gates: required=False keeps them out of missing_required_slots
# (they cannot be asked up front — each only makes sense after its
# prerequisite operation has produced something to confirm). builder_node
# sequences them via _OP_GATE / _STAGE_EXIT_GATE and refuses planner asks for
# them before the prerequisite op is done.
GATE_SLOTS: frozenset[str] = frozenset({
    "poi_confirm", "maid_confirm", "plan_confirm", "go_live_confirm",
})


def _not_when_clauses(not_when: Any) -> list[tuple[str, ...]]:
    """Normalize not_when into a list of (dep_name, *excluded) clauses. Flat
    (dep, v1, ...) → one clause; nested ((dep1, ...), (dep2, ...)) → many (skip if
    ANY matches). Detected by whether the first element is itself a tuple."""
    if not not_when:
        return []
    return list(not_when) if isinstance(not_when[0], tuple) else [not_when]


def _dep_values(filled: dict[str, Any], dep_name: str) -> set[str]:
    """The dep's value as a SET of lowercased tokens. `det_type` may be a
    comma-joined set of composable angles (e.g. "event_based,named_places"); every
    other dep is single-valued → a one-element set. Empty/absent → empty set."""
    raw = str(filled.get(dep_name, "")).strip().lower()
    return {t.strip() for t in raw.split(",") if t.strip()}


def merge_angle_tokens(*groups: Any) -> str:
    """Union targeting-angle tokens into the comma set ``det_type`` reads.

    Order-preserving and de-duped, e.g. ``("category", ["competitor_brand"])`` →
    ``"category,competitor_brand"``. Accepts strings (comma-joined or single) and
    lists, in any mix, so it works on both a stored slot value and a router edit.

    Lives here rather than in nodes.py because this module already owns the set
    semantics (`_dep_values`, the intersection/subset rules in `slot_applies`) and
    imports nothing from `app.*`, so both `nodes.entry_node` and
    `builder/edits.py` can call it with no cycle.

    ANY angles may combine — each contributes its own places to one shared
    audience, and `slot_applies` re-activates each angle's collection slots on its
    own. Nothing is dropped here.
    """
    out: list[str] = []
    for group in groups:
        if group is None:
            continue
        items = group if isinstance(group, (list, tuple, set)) else [group]
        for item in items:
            if not item:            # None / "" — str() would yield "none"
                continue
            for token in str(item).split(","):
                token = token.strip().lower()
                if token and token not in out:
                    out.append(token)
    return ",".join(out)


def slot_applies(slot: Slot, filled: dict[str, Any]) -> bool:
    """True when the slot is relevant given already-filled slot values.

    Set-aware so a multi-angle run activates every composable angle's slots:
    - only_when → active when the dep set INTERSECTS the accepted values (the
      angle is among those selected).
    - not_when  → skip only when the dep set is a SUBSET of the excluded values
      (EVERY active angle is excluded). So `lookback_days`
      (not_when event_based) is skipped for a pure event run but ASKED for a
      combo like "event_based,named_places" whose non-event POIs need a window.
    - skip_when_any → skip as soon as the dep set INTERSECTS the values (the angle
      is present, possibly alongside others). So the competitor-anchor slots are
      skipped for the store_set+competitor_nearby pair (store_set present) but
      ASKED for a pure competitor_nearby run.
    Single-valued deps (one-element set) behave exactly as before."""
    if slot.only_when is not None:
        dep_name, expected = slot.only_when
        actual = _dep_values(filled, dep_name)
        accepted = {expected.lower()} if isinstance(expected, str) else {e.lower() for e in expected}
        if not (actual & accepted):
            return False
    for dep_name, *excluded in _not_when_clauses(slot.not_when):
        actual = _dep_values(filled, dep_name)
        excluded_set = {e.lower() for e in excluded}
        if actual and actual <= excluded_set:
            return False
    if slot.skip_when_any is not None:
        dep_name, *values = slot.skip_when_any
        if _dep_values(filled, dep_name) & {v.lower() for v in values}:
            return False
    return True


def missing_required_slots(stage: str, filled: dict[str, Any]) -> list[Slot]:
    """Required, applicable, still-unfilled slots for one stage, in order."""
    def _unfilled(s: Slot) -> bool:
        if s.skippable:
            return s.name not in filled        # asked-and-skipped writes the key
        return not str(filled.get(s.name, "") or "").strip()
    return [
        s for s in SLOTS.values()
        if s.stage == stage and s.required and slot_applies(s, filled) and _unfilled(s)
    ]


# Store-anchor slots: both store_set and competitor_nearby need only the user's
# OWN store location. The chatbot often captures that address into the generic
# `location` field (not the store key), so these slots get a fallback bridge from
# `location` when it looks like a real street address.
_STORE_ANCHOR_KEYS: frozenset[str] = frozenset({"store_addresses", "competitor_address"})


def _looks_like_street_address(text: str) -> bool:
    """Heuristic for a geocodable store address: has a digit AND more than one
    token (street number + name). Rejects bare cities ("Montreal") and lone
    postal/area codes ("90210", "M5V") that must NOT be dumped into a store slot."""
    t = text.strip()
    return any(ch.isdigit() for ch in t) and len(t.split()) >= 2


def _store_location_fallback(slot: Slot, user_info: dict[str, Any]) -> Optional[list[str]]:
    """Borrow a street-address-shaped generic `location` for a store-anchor slot
    when its dedicated key is empty and the chosen det_type uses the user's own
    store. Returns a list of candidate addresses, or None."""
    if slot.prefill_key not in _STORE_ANCHOR_KEYS:
        return None
    det_subs = {
        s.strip() for s in str(user_info.get("deterministic_subtype") or "").lower().split(",")
        if s.strip()
    }
    if not (det_subs & {"store_set", "competitor_nearby"}):
        return None
    loc = user_info.get("location")
    candidates = loc if isinstance(loc, list) else ([loc] if loc else [])
    picked = [str(c) for c in candidates if c and _looks_like_street_address(str(c))]
    return picked or None


def store_anchor_field_for_location(value: Any, det_type: Any) -> Optional[str]:
    """The store-anchor field a `location` EDIT really means, or None.

    On a run anchored only on the user's own store(s) the `locations` slot is
    skipped and `location` survives only as a soft market hint (`market_hint`),
    so "change my location to 12 Main St" would commit a hint and leave the
    stores where they were. When EVERY item is street-address-shaped (the same
    test the prefill bridge above uses, so a bare "Toronto" or "90210" keeps
    meaning the hint) it is a store-address edit; a market angle running
    alongside means `location` is a real market and this returns None.
    """
    subs = {s.strip() for s in str(det_type or "").lower().split(",") if s.strip()}
    if not subs or not subs <= {"store_set", "competitor_nearby"}:
        return None
    items = [str(i) for i in (value if isinstance(value, list) else [value]) if i]
    if not items or not all(_looks_like_street_address(i) for i in items):
        return None
    return "store_addresses" if "store_set" in subs else "competitor_address"


def prefill_for(slot: Slot, user_info: dict[str, Any]) -> Optional[str]:
    """Prefill value for a slot from user_info, normalized to str, or None."""
    if not slot.prefill_key:
        return None
    val = user_info.get(slot.prefill_key)
    if val is None or val == "" or val == []:
        # Fallback: bridge a store address captured into the generic `location`
        # field into the store-anchor slot (store_set / competitor_nearby).
        val = _store_location_fallback(slot, user_info)
        if not val:
            return None
    if isinstance(val, list):
        return ", ".join(str(v) for v in val)
    return str(val)
