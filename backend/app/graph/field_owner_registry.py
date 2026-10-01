"""
graph/field_owner_registry.py
─────────────────────────────
Maps every editable AgentState field to the wizard that owns it.

The resume-router consults this registry whenever the user issues an
``edit`` lane intent. If the field's owner is in ``state["wizards_completed"]``
the edit is refused (hard lock). Otherwise the edit is applied to the active
wizard's scratch state.

``FIELD_OWNER`` keys cover two surfaces:

1. Step-level field names — the ``field`` values from STEP_PROMPTS, e.g.
   ``"geo_locations"`` from the ``geo_collect_locations`` step.
2. UserInfo natural names — the camel-free keys the classifier is most
   likely to surface from natural language, e.g. ``"location"``,
   ``"business_name"``, ``"budget"``.

Both are wired so the classifier is free to return whichever form fits the
user's phrasing without the router needing a synonym layer.

``APPENDABLE_FIELDS`` lists fields that accept union-merge when the user
says "also add X" — typically list-typed (locations, POI types, brand names,
event queries, creative files).

This module is intentionally a pure-data module — no I/O, no LLM, no graph
imports — so it can be loaded by any node or test without side effects.
"""

from __future__ import annotations

from typing import Literal, Optional


WizardName = Literal["geo", "maid", "campaign", "media"]


# Step-level field names sourced from STEP_PROMPTS plus a small set of
# UserInfo-native names that the classifier will most often emit.
FIELD_OWNER: dict[str, WizardName] = {
    # ── Geo wizard ────────────────────────────────────────────────────────
    "geo_location_type": "geo",
    "geo_locations": "geo",
    "geo_radius_pin": "geo",
    "geo_radius_km": "geo",
    "geo_deterministic_type": "geo",
    "geo_poi_types": "geo",
    "geo_store_addresses": "geo",
    "geo_store_address_for_competitors": "geo",
    "geo_competitor_radius": "geo",
    "geo_brand_names": "geo",
    "geo_named_places": "geo",
    "geo_event_type": "geo",
    "geo_event_date_range": "geo",
    # "geo_business_description" and "geo_map_selection" were removed — grep
    # confirmed zero readers anywhere outside this dict and the classifier
    # prompt (the real business-description field the classifier should name
    # is "business_description", campaign-owned, which has a working `redraft`
    # route; "geo_map_selection" was the map widget's own payload shape, never
    # an NL edit target). Listing a name nothing resolves invites exactly the
    # ack-then-silently-drop bug `is_actionable_field` exists to close off.
    "geo_disambiguate_location": "geo",
    "geo_disambiguate_named_place": "geo",
    "geo_location_confirmation": "geo",
    "geo_store_confirmation": "geo",
    "geo_competitor_store_confirmation": "geo",
    "geo_pois_confirmation": "geo",
    "geo_plan_confirm": "geo",
    # UserInfo natural names (geo prefill surface)
    "location": "geo",
    "geo_scope": "geo",
    "deterministic_subtype": "geo",
    "poi_types": "geo",
    "competitor_brands": "geo",
    "named_places": "geo",
    "store_addresses": "geo",
    "competitor_address": "geo",
    "search_radius_km": "geo",
    "event_queries": "geo",
    "event_date_range": "geo",
    # NL curation of the already-discovered POI set ("just the top 10", "drop
    # everything in Laval") — a tier-1 overlay (builder/edits.py's module
    # docstring), not union-merge, so deliberately NOT in APPENDABLE_FIELDS.
    # See builder/executors/poi_selection.py.
    "poi_selection": "geo",
    # One location's circle / centre and the dropped map pins — typed edits that
    # act on the map's per-location decisions (executors/geo.apply_location_ops).
    "location_ring": "geo",
    "location_center": "geo",
    "map_pins": "geo",
    # Areas carved OUT of the targeted ones ("everywhere except downtown").
    "excluded_areas": "geo",

    # ── MAID wizard ───────────────────────────────────────────────────────
    "maid_poi_radius": "maid",
    "maid_lookback": "maid",
    "maid_confirm_results": "maid",
    # UserInfo natural names (maid prefill surface)
    "poi_radius_m": "maid",
    "lookback_days": "maid",
    # Audience layering (day-of-week/hour/dwell/frequency/trend/set-op) on top
    # of an already-extracted audience — see maid_store.AudienceFilter. Routed
    # to its own recompute path (wizard_helpers._dispatch_edit_intent), not
    # the generic slot commit — it has no Slot of its own by design (see
    # slots.py: an absent filter just means "everything", no question forced
    # on the prompts that need no layering).
    "audience_filter": "maid",

    # ── Campaign builder ──────────────────────────────────────────────────
    # The dynamic intake form collects business / objective / duration / budget /
    # destination in one submission; the plan form edits everything else.
    "campaign_intake": "campaign",
    "campaign_plan_confirm": "campaign",
    # How much of the campaign Punk builds (self / guide / express). Owned by the
    # campaign stage because it gates every campaign act (_OP_MODES).
    "campaign_publish_mode": "campaign",
    # UserInfo natural names (campaign surface)
    "business_name": "campaign",
    "business_description": "campaign",
    # The classifier has always advertised this and it was missing here, so an
    # objective edit was post-validated away into the reject lane. It IS a spec
    # field with a real control ("Objective" in the plan editor's general
    # settings), so post-spec it routes there like any other editor box.
    "campaign_objective": "campaign",
    "industry": "campaign",
    "target_audience": "campaign",
    "budget": "campaign",
    "website_url": "campaign",
    "app_store_url": "campaign",
    "play_store_url": "campaign",
    "budget_type": "campaign",
    "campaign_start_date": "campaign",
    "campaign_end_date": "campaign",
    "pixel_status": "campaign",
    "pixel_id": "campaign",
    # Conversion tracking, all collected on the intake form: which event counts,
    # whether it is one of the advertiser's own custom conversions, and how the
    # events reach Meta.
    "pixel_event": "campaign",
    "custom_conversion_id": "campaign",
    "tracking_method": "campaign",
    # Generated creative, an existing post, or the post behind an existing ad.
    "creative_source": "campaign",
    # Single image/video vs carousel — a preference the editor applies once.
    "ad_format": "campaign",
    "product_offer": "campaign",
    "target_age_min": "campaign",
    "target_age_max": "campaign",
    "target_gender": "campaign",
    # Real Meta spec fields (meta_spec/models.py) with a control in the plan
    # editor, previously absent here — an edit naming them ("Instagram only",
    # "run weekdays 9-5", "cap frequency at 2") was dropped as an unknown
    # field before it ever reached edit_block_reason. Post-spec they route
    # through _POST_SPEC_ROUTE's plan_editor default, same as budget/objective.
    "publisher_platforms": "campaign",
    "adset_schedule": "campaign",
    "bid_strategy": "campaign",
    "budget_schedule_specs": "campaign",
    "frequency_control_specs": "campaign",

    # ── Media wizard ──────────────────────────────────────────────────────
    "creative_upload": "media",
    "meta_oauth_connect": "media",
    "meta_ad_account_id": "media",
    "meta_pixel_id": "media",
    "media_buying_confirm": "media",
    # The go-live gate's field (step media_confirm_go_live). Media-owned, so
    # edit_block_reason refuses it — by the time it is on screen the campaign is
    # already built in Meta and only activation is left.
    "meta_go_live_confirm": "media",
    # UserInfo natural names (media surface)
    "meta_access_token": "media",
    "meta_page_id": "media",
}


# Fields that accept union-merge when the user says "also add X".
# These are conceptually list-typed across either UserInfo or wizard scratch.
APPENDABLE_FIELDS: set[str] = {
    "location",
    "geo_locations",
    "poi_types",
    "geo_poi_types",
    "competitor_brands",
    "geo_brand_names",
    "named_places",
    "geo_named_places",
    "event_queries",
    "geo_event_type",
    "store_addresses",
    "geo_store_addresses",
    # Targeting ANGLES compose: det_type is a comma-joined SET and slot_applies is
    # intersection-based, so "also target people near Starbucks" should ADD an
    # angle. Without these two here resume_router force-collapses is_append to
    # False and the edit SWAPS the angle instead — the opposite of the request.
    "deterministic_subtype",
    "geo_deterministic_type",
}


def resolve_field_owner(field: Optional[str]) -> Optional[WizardName]:
    """Return the wizard name owning ``field`` or None when unknown.

    Unknown fields cause the router to treat the edit as a no-op (with a
    "I couldn't tell which field that referred to" message); this is safer
    than guessing.
    """
    if not field:
        return None
    return FIELD_OWNER.get(field)


def is_completed_owner(owner: Optional[str], state: object) -> bool:
    """True when ``owner`` ∈ AgentState["wizards_completed"].

    ``state`` is duck-typed — accepts any object with a ``.get`` method
    (TypedDict, plain dict, StateSnapshot.values). Returns False when the
    set is missing or empty so callers can treat the result as a simple
    boolean without a None check.
    """
    if not owner:
        return False
    try:
        completed = state.get("wizards_completed") if hasattr(state, "get") else None
    except (AttributeError, TypeError):
        completed = None
    if not completed:
        return False
    return owner in completed


# ── Edit admissibility ────────────────────────────────────────────────────────
# Whether a mid-flow edit to a field can still be HONOURED — decided BEFORE the
# resume router acknowledges it.
#
# Without this the router acked every edit ("Updated budget → $500") and the
# builder then dropped the ones it could not apply. That is the worst failure
# mode of the off-happy-path flow: Punk asserts a change it never made, then
# builds with the old value. Every edit now resolves to exactly one of three
# visible outcomes — commit, refuse, or reframe — and never a silent fourth.
#
# Pure data + duck-typed reads only, so this stays importable from anywhere:
# wizard_helpers dispatches on it, builder/edits.py applies the ones it clears.

EDIT_BLOCK_MESSAGES: dict[str, str] = {
    "published": (
        "That campaign is already live in Meta, so I can't rebuild it from here. "
        "From the campaign manager I can adjust budget, pause/resume, or bid on "
        "the live campaign — everything else, including the audience, needs a "
        "fresh campaign."
    ),
    "plan_editor": (
        "That one lives in your campaign plan — I've reopened the editor below so "
        "you can change it there and see the whole plan update with it."
    ),
    "not_in_editor": (
        "I can't change that one at this point — it shaped how the campaign was "
        "built rather than being a setting on it. Everything that IS adjustable is "
        "in the plan below; if this really needs to change, a fresh build is the "
        "clean way to do it."
    ),
    # budget IS adjustable, just not as the single free-text figure the user gave
    # at intake — the plan holds a real amount per ad set. Telling them "I can't
    # change that" would be wrong; telling them "it's in the editor" without
    # saying WHERE sends them hunting for a field named "budget".
    "budget_in_plan": (
        "Budget lives in the plan below now — each ad set has its own amount, so "
        "you can set them together or split them. Change it there and I'll publish "
        "with the new numbers."
    ),
    "mode_locked": (
        "How much of this I build for you was set when we started, and the campaign "
        "is already put together — switching now would mean rebuilding it from "
        "scratch. Start a new chat if you want to go a different route."
    ),
    "meta_account": (
        "Your Meta account, Page and pixel come straight from the connection, so I "
        "can't retype them here. Pick a different one in the plan editor, or "
        "reconnect if you need a different account."
    ),
    "locked": (
        "That build already finished, so there's nothing left for me to redo. "
        "Start a new chat and I'll build it again with that change baked in."
    ),
}

# The op whose output freezes the campaign stage: once the Meta spec exists, a
# typed edit must not re-derive it, or the user's own editor work is discarded.
_SPEC_BUILT_OP = "generate_meta_json"

# What a campaign-owned field can still do once the spec is built. Audited field
# by field against CampaignSpec and the editor UI — this is verified data, not a
# rule that can be derived: the user_info → spec-path mapping is exactly the
# non-obvious part, and the editor only writes back `spec`, two media_ws keys and
# `tracking_method`, so a field with no control is a dead end twice over.
#
# Anything absent from this map defaults to "plan_editor".
#
#   plan_editor   – a real control exists; reopen the editor (the honest default)
#   not_in_editor – no control, and no writeback if there were. Say so plainly
#                   instead of sending the user to look for a field that is not
#                   there. `campaign_publish_mode` is the sharpest case: express
#                   mode HIDES the very panels we would be pointing at.
#   redraft       – a pure prompt input with zero editor surface, which shaped the
#                   ad copy already written. Committed, then the brief is re-run
#                   and its new suggestions merged into the EXISTING spec — never
#                   `invalidate_from("campaign")`, which would delete the whole
#                   editor tree (copy, media, audiences, budgets) for a wording
#                   change.
_POST_SPEC_ROUTE: dict[str, str] = {
    # No control anywhere in the editor.
    "budget": "budget_in_plan",           # editable as cents per adset; user_info["budget"] is free text, never written back
    "play_store_url": "not_in_editor",    # folded into one shared store-link control
    "creative_source": "not_in_editor",   # shipped read-only; picks the ad-card tab
    "pixel_status": "not_in_editor",      # derived by the media executor
    "campaign_publish_mode": "mode_locked",
    "campaign_intake": "not_in_editor",   # a step key, not a field
    "campaign_plan_confirm": "not_in_editor",
    # Prompt-only inputs. `target_audience` never reaches the Meta spec at all —
    # it feeds the brief, geo POI-type inference and location disambiguation.
    "target_audience": "redraft",
    "business_name": "redraft",
    "business_description": "redraft",
    "industry": "redraft",
    "product_offer": "redraft",
}


def _state_values(state: object) -> dict:
    """Duck-typed read of an AgentState / StateSnapshot.values / plain dict."""
    if state is None:
        return {}
    if callable(getattr(state, "get", None)):
        return state  # type: ignore[return-value]
    values = getattr(state, "values", None)
    if callable(getattr(values, "get", None)):
        return values
    return {}


def edit_block_reason(field: Optional[str], state: object) -> Optional[str]:
    """``None`` when an edit to ``field`` can be applied right now, else a key
    into ``EDIT_BLOCK_MESSAGES`` saying why it cannot.

    Ordered most-final first:

      published    – the campaign exists in Meta. Rebuilding is not an edit any
                     more; the campaign manager owns changes to live campaigns.
      meta_account – account / Page / pixel come from the OAuth connection, not
                     from prose.
      plan_editor  – the Meta spec is already built (see ``_SPEC_BUILT_OP``).
      locked       – the build finalized and its scratch is gone, so there is
                     nothing left to re-run.

    An unknown field returns ``None``: the caller's existing "I couldn't tell
    which field that referred to" path is the right answer, not a block message.
    """
    owner = FIELD_OWNER.get(field or "")
    if owner is None:
        return None
    values = _state_values(state)
    bs = values.get("campaign_builder_state") or {}
    # Check the builder scratch as well as AgentState. `publish` writes
    # bs["meta_campaign_ids"] but only builder_finalize copies it up — and the
    # go_live_confirm gate INTERRUPTS in between. At that pause the campaign
    # already exists in Meta (paused) while AgentState still looks unpublished,
    # so an edit there would sail past this guard, `invalidate_from` would drop
    # publish + activate, and the builder would publish a SECOND campaign. The
    # publish ledger is idempotency for retry-after-failure, not for
    # rebuild-after-edit.
    if values.get("meta_campaign_ids") or bs.get("meta_campaign_ids"):
        return "published"
    if owner == "media":
        return "meta_account"
    if owner == "campaign" and _SPEC_BUILT_OP in set(bs.get("ops_done") or []):
        return _POST_SPEC_ROUTE.get(field or "", "plan_editor")
    # No live builder scratch to rewind AND the owner already signed off = the
    # build is over. Checked last so a mid-build edit (scratch present,
    # wizards_completed still empty) always reaches the commit path.
    if not bs and is_completed_owner(owner, values):
        return "locked"
    return None
