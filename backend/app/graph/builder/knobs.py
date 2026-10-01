"""
graph/builder/knobs.py
──────────────────────
Everything a user can change mid-build, declared once: what it means in plain
words, its unit, which operations make sense on it, and which OTHER knob a user
could mean by the same words. The classifier's field catalog, the
disambiguation cues and the "here's what I can change" answer are generated
from this table (Phase 3), so a new changeable value is one entry here plus a
write path — not prose copied into a prompt.

Deliberately NOT a second copy of the write/invalidation tables. Where a value
lands (slot, unit to rebuild, cost floor) stays in ``builder/edits.py`` /
``slots.py`` / ``field_owner_registry.py``; a knob only names the canonical
field those already route. ``test_knobs.py`` keeps the two in step: every
actionable field (except confirm gates, which are answers, not changes)
resolves to exactly one knob.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

_LIST = frozenset({"set", "add", "remove"})
_NUMBER = frozenset({"set", "scale", "delta"})
_SET = frozenset({"set"})


@dataclass(frozen=True)
class Knob:
    name: str                         # canonical, classifier-facing field name
    owner: str                        # geo | maid | campaign
    describe: str                     # one plain line: what changing it does
    aliases: tuple[str, ...] = ()     # other registry names that mean this knob
    unit: Optional[str] = None        # "km" | "m" | "days" | "money" | "years"
    ops: frozenset = _SET
    confusable_with: tuple[str, ...] = ()
    cue: str = ""                     # how to tell THIS knob from its confusables
    choices: tuple[str, ...] = ()     # canonical values, for enumerated knobs
    tool: Optional[str] = None        # set when a DEDICATED router tool owns it (not edit_field)


KNOBS: dict[str, Knob] = {k.name: k for k in (
    # ── geo: where, and what kind of place ────────────────────────────────────
    Knob("location", "geo",
         "the cities / areas / addresses the campaign targets and searches in. When the place belongs to "
         "ONE search only (\"events only in Montreal\", \"the gyms in Toronto\"), set `target` to that search "
         "(events, gyms, Starbucks); no target = every search",
         aliases=("geo_locations",), ops=_LIST,
         confusable_with=("store_addresses", "geo_scope", "excluded_areas"),
         cue="a PLACE NAME to target (Toronto, Mile End); the user's own shop is store_addresses; "
             "\"everywhere except X\" is excluded_areas"),
    Knob("geo_scope", "geo",
         "how wide the targeting area is: whole country, state/province, city/zip/address, or a dropped pin",
         aliases=("geo_location_type",),
         # The slot normalizer only reads these tokens — "whole state" used to
         # land as a blank slot.
         choices=("country_groups", "admin_areas", "granular_local", "radius"),
         confusable_with=("location", "poi_types"),
         cue="a SCOPE word (whole state, just the city, drop a pin) — a kind of venue is poi_types"),
    Knob("search_radius_km", "geo",
         "the SEARCH CIRCLE drawn around a city / address / pin / the user's own store; spots are searched inside it. "
         "This sets EVERY location's circle at once — when the user names ONE place, use location_ring",
         aliases=("geo_radius_km", "geo_competitor_radius"), unit="km", ops=_NUMBER,
         confusable_with=("poi_radius_m",),
         cue="a ring around a PLACE or AREA, usually km or miles"),
    Knob("location_ring", "geo",
         "the search circle of ONE named location — whenever the user names a specific city / address / pin with a size "
         "(\"make the Fort Collins radius 5 miles\", \"just Laval's circle to 3 km\", \"Denver 20 km\"): set `target` to "
         "that place's name. Never use search_radius_km for it, or every other location's circle changes too",
         unit="km", ops=_NUMBER, confusable_with=("search_radius_km",),
         cue="ONE location's circle, named; all of them at once is search_radius_km"),
    Knob("location_center", "geo",
         "move one location's circle to a different address or place (\"centre it on 123 Main St\") — `value` is the new address",
         confusable_with=("location",),
         cue="MOVING a location's centre; adding another place to target is location"),
    Knob("map_pins", "geo",
         "the pins the user dropped on the map — remove one (\"remove the pin I dropped\"); `target` names it, or empty for the latest",
         ops=frozenset({"remove"}), confusable_with=("location",)),
    Knob("excluded_areas", "geo",
         "parts of the targeted area to LEAVE OUT (\"everywhere except downtown\", \"not the airport\") — `value` names the place",
         ops=frozenset({"add", "remove"}), confusable_with=("location",),
         cue="carving a place OUT of an area that stays targeted; removing a whole targeted city is location"),
    Knob("deterministic_subtype", "geo",
         "which targeting angles run: kinds of place, named brands, specific venues, events, the user's stores, competitors near them",
         aliases=("geo_deterministic_type",), ops=_LIST,
         choices=("ai_suggested", "category", "competitor_brand", "named_places", "event_based",
                  "store_set", "competitor_nearby", "competitor_area"),
         cue="turning a whole search approach on or off (\"also do events\" = add event_based; "
             "\"forget the cafes, just do events\" = set event_based)"),
    Knob("poi_types", "geo",
         "the KINDS of place SEARCHED for (gyms, coffee shops, pet stores) — changing it re-runs the search",
         aliases=("geo_poi_types",), ops=_LIST,
         confusable_with=("competitor_brands", "named_places", "poi_selection"),
         cue="a category of venue to search for; a chain name is competitor_brands; REMOVING a "
             "category/spot already shown on the map is the trim_pois tool (no re-search), not this"),
    Knob("competitor_brands", "geo",
         "named chains / brands whose locations are searched (Starbucks, Tim Hortons)",
         aliases=("geo_brand_names",), ops=_LIST,
         confusable_with=("poi_types", "named_places"), cue="a brand or chain name"),
    Knob("named_places", "geo",
         "specific individual venues searched by name (Central Park, the Bell Centre)",
         aliases=("geo_named_places",), ops=_LIST,
         confusable_with=("poi_types", "competitor_brands"), cue="one particular venue"),
    Knob("event_queries", "geo",
         "events whose venues are targeted (festivals, concerts, trade shows)",
         aliases=("geo_event_type",), ops=_LIST, confusable_with=("location",),
         cue="WHICH events to look for; WHERE those events are searched (\"the festivals only in Montreal\") "
             "is location with target=events"),
    Knob("event_date_range", "geo",
         "the dates of the targeted events",
         aliases=("geo_event_date_range",),
         confusable_with=("lookback_days", "campaign_start_date", "campaign_end_date"),
         cue="WHEN the events happen — not how far back visits count, not when ads run"),
    Knob("store_addresses", "geo",
         "the user's OWN store addresses",
         aliases=("geo_store_addresses",), ops=_LIST,
         confusable_with=("location", "competitor_address"), cue="the user's own shop(s)"),
    Knob("competitor_address", "geo",
         "the user's store address that anchors the competitors-near-me search",
         aliases=("geo_store_address_for_competitors",), ops=_LIST,
         confusable_with=("store_addresses",)),
    Knob("poi_selection", "geo",
         "curating the spots ALREADY found and on the map (top 10, drop the ones in Laval, keep only the "
         "spots that have visitors) — no new search",
         confusable_with=("poi_types", "audience_filter"),
         cue="narrowing what's already found; a new kind of place to search is poi_types; removing spots "
             "that had no visitors is here (min_visitors)",
         tool="trim_pois"),
    # ── maid: who counts as a visitor ─────────────────────────────────────────
    Knob("poi_radius_m", "maid",
         "the VISIT RING around EACH found spot: how close someone must be to count as a visitor. When it is for "
         "some spots only (\"100 m for the gyms\", \"tighter around Starbucks\"), set `target` to that group; "
         "no target = every spot",
         aliases=("maid_poi_radius",), unit="m", ops=_NUMBER,
         confusable_with=("search_radius_km",),
         cue="a small ring around EACH spot, usually metres or feet"),
    Knob("lookback_days", "maid",
         "how many past days of visits count toward the audience",
         aliases=("maid_lookback",), unit="days", ops=_NUMBER,
         confusable_with=("event_date_range", "campaign_end_date"),
         cue="how far BACK visit history goes — not when ads run"),
    Knob("audience_filter", "maid",
         "narrowing the extracted audience by visit behaviour (weekends, 3+ visits, staff vs customers, both X and Y)",
         confusable_with=("adset_schedule", "poi_selection", "target_audience"),
         cue="WHICH VISITORS count, from their visit data — not when ads show; \"keep only the locations that "
             "have visits\" judges SPOTS, so it is poi_selection, not this; naming a GROUP of spots to give "
             "a ring size to (\"100 m for the gyms\") is poi_radius_m with a target, never a filter",
         tool="filter_audience"),
    # ── campaign: the ads themselves ──────────────────────────────────────────
    Knob("business_name", "campaign", "the business name used in the ads"),
    Knob("business_description", "campaign", "what the business does, used to write the ads"),
    Knob("industry", "campaign", "the business's industry"),
    Knob("product_offer", "campaign", "the product or offer the ads promote"),
    Knob("target_audience", "campaign",
         "who the ads are written for, in words (young parents, gym-goers) — shapes the copy",
         confusable_with=("audience_filter",),
         cue="describing people for the copy — filtering the visit data is audience_filter"),
    Knob("campaign_objective", "campaign", "the campaign goal (awareness, traffic, leads, sales)"),
    Knob("campaign_publish_mode", "campaign",
         "how much of the campaign Punk builds (express, guided, or publish it yourself)"),
    Knob("budget", "campaign", "how much to spend", unit="money", ops=_NUMBER,
         confusable_with=("budget_schedule_specs",)),
    Knob("budget_type", "campaign", "daily vs lifetime budget"),
    Knob("budget_schedule_specs", "campaign", "scheduled budget increases for specific periods",
         confusable_with=("budget",)),
    Knob("campaign_start_date", "campaign", "when the ads start running",
         confusable_with=("event_date_range", "lookback_days")),
    Knob("campaign_end_date", "campaign", "when the ads stop running",
         confusable_with=("event_date_range", "lookback_days"),
         cue="WHEN ADS RUN — not how far back visits count"),
    Knob("adset_schedule", "campaign",
         "which days / hours the ads are SHOWN (weekdays 9-5)",
         confusable_with=("audience_filter",),
         cue="WHEN ADS SHOW — not which visitors count"),
    Knob("frequency_control_specs", "campaign", "cap on how often one person sees the ad"),
    Knob("publisher_platforms", "campaign", "where ads appear (Facebook, Instagram, Messenger)", ops=_LIST),
    Knob("bid_strategy", "campaign", "how Meta bids (lowest cost, cost cap, bid cap)"),
    Knob("target_age_min", "campaign", "youngest age shown the ads", unit="years", ops=_NUMBER),
    Knob("target_age_max", "campaign", "oldest age shown the ads", unit="years", ops=_NUMBER),
    Knob("target_gender", "campaign", "gender shown the ads"),
    Knob("website_url", "campaign", "the website the ads link to"),
    Knob("app_store_url", "campaign", "the App Store link for app campaigns"),
    Knob("play_store_url", "campaign", "the Google Play link for app campaigns"),
    Knob("ad_format", "campaign", "ad format (single image, video, carousel)"),
    Knob("creative_source", "campaign", "where the ad images/video come from"),
    Knob("tracking_method", "campaign", "how conversions are tracked"),
    Knob("pixel_status", "campaign", "whether a Meta Pixel is installed"),
    Knob("pixel_id", "campaign", "which Meta Pixel tracks conversions"),
    Knob("pixel_event", "campaign", "which Pixel event counts as a conversion"),
    Knob("custom_conversion_id", "campaign", "which custom conversion counts"),
)}

# Registry fields that route to a slot but are NOT offered as typed changes,
# each with the reason. Confirmation gates are answers to a screen, not values
# to change; the pin is a map coordinate that text can't set yet.
NOT_TYPEABLE: dict[str, str] = {
    "geo_radius_pin": "a map coordinate — set by dropping the pin on the map",
    "geo_pois_confirmation": "confirmation gate (an answer, not a setting)",
    "geo_competitor_store_confirmation": "confirmation gate (an answer, not a setting)",
    "maid_confirm_results": "confirmation gate (an answer, not a setting)",
    "campaign_plan_confirm": "confirmation gate (an answer, not a setting)",
    "meta_go_live_confirm": "confirmation gate (an answer, not a setting)",
    "campaign_intake": "the intake form itself — its fields are knobs of their own",
}

_BY_ALIAS: dict[str, str] = {
    alias: knob.name for knob in KNOBS.values() for alias in (knob.name, *knob.aliases)
}


def knob_for_field(field: Optional[str]) -> Optional[Knob]:
    """The knob a registry field name (canonical or alias) belongs to."""
    return KNOBS.get(_BY_ALIAS.get(field or "", ""))


def edit_field_knobs() -> list[Knob]:
    """Knobs changed through the generic edit tool — the ones with a dedicated
    tool (trim_pois, filter_audience) are left to it, or one intent splits
    across two tools."""
    return [k for k in KNOBS.values() if not k.tool]


def knob_catalog() -> str:
    """One line per edit_field knob for the classifier: name, unit/values, ops,
    meaning, and how it differs from what a user could mean by the same words
    (a confusable owned by a dedicated tool is named by that tool)."""
    lines: list[str] = []
    for k in edit_field_knobs():
        others = [KNOBS[o].tool or o for o in k.confusable_with]
        meta = [f"unit {k.unit}"] if k.unit else []
        if k.choices:
            meta.append("one of " + "|".join(k.choices))
        if k.ops != _SET:
            meta.append("ops " + "/".join(sorted(k.ops)))
        line = f"- {k.name}" + (f" ({'; '.join(meta)})" if meta else "") + f": {k.describe}"
        if others:
            line += f". NOT {', '.join(others)}" + (f" — {k.cue}" if k.cue else "")
        lines.append(line)
    return "\n".join(lines)


# ── live values — what each knob is set to RIGHT NOW ─────────────────────────


def _search_ring_now(bs: dict) -> Optional[str]:
    filled = bs.get("filled") or {}
    for slot in ("radius_km", "competitor_radius_km"):
        if str(filled.get(slot) or "").strip():
            return f"{filled[slot]} km"
    ws = bs.get("geo_ws") or {}
    if ws.get("_search_ring_km"):
        return f"{ws['_search_ring_km']:g} km"
    radii = sorted({
        loc["search_radius_km"] for loc in (ws.get("_geocoded_locations") or [])
        if loc.get("ui_mode") == "pin_radius" and loc.get("search_radius_km")
    })
    if radii:
        return " / ".join(f"{r:g} km" for r in radii)
    return None


def current_values(state: Any) -> dict[str, str]:
    """Readable current value of every knob that has one — the context a
    classifier needs for "make it bigger", "double it", "already that"."""
    try:
        bs = (state or {}).get("campaign_builder_state") or {}
        ui = (state or {}).get("user_info") or {}
    except (AttributeError, TypeError):
        return {}
    filled = bs.get("filled") or {}
    from_slots = {
        "location": "locations", "geo_scope": "location_scope",
        "deterministic_subtype": "det_type", "poi_types": "poi_types",
        "competitor_brands": "brand_names", "named_places": "named_places",
        "event_queries": "event_queries", "event_date_range": "event_date_range",
        "store_addresses": "store_addresses", "competitor_address": "competitor_anchor",
        "lookback_days": "lookback_days",
    }
    out: dict[str, str] = {}
    for knob, slot in from_slots.items():
        if str(filled.get(slot) or "").strip():
            out[knob] = str(filled[slot])
    ring = _search_ring_now(bs)
    if ring:
        out["search_radius_km"] = ring
    if str(filled.get("poi_radius_m") or "").strip():
        out["poi_radius_m"] = f"{filled['poi_radius_m']} m"
    for knob in ("budget", "campaign_objective", "business_name", "campaign_end_date"):
        if ui.get(knob) not in (None, "", []):
            out[knob] = str(ui[knob])
    return out


# ── relative edits, computed in code ─────────────────────────────────────────

_FACTOR_WORDS: dict[str, float] = {
    "double": 2.0, "twice": 2.0, "triple": 3.0, "half": 0.5, "halve": 0.5,
    "quadruple": 4.0,
}


def resolve_relative(knob: Knob, op: str, value: str, current: Optional[str]) -> Optional[str]:
    """``op`` scale/delta → an absolute value string in the knob's unit, from
    the CURRENT value — the model names the change ("double", "+2 km"), code
    does the arithmetic. None when either side isn't a number (the caller then
    asks instead of guessing)."""
    from app.graph.wizard_helpers import parse_length, parse_radius_float

    if current is None:
        return None
    base = (
        parse_length(current, knob.unit) if knob.unit in ("km", "m")
        else parse_radius_float(current, default=None)
    )
    if base is None:
        return None
    text = (value or "").strip().lower()
    if op == "scale":
        factor = next((f for w, f in _FACTOR_WORDS.items() if w in text), None)
        if factor is None:
            factor = parse_radius_float(text.replace("x", " "), default=None)
        if not factor or factor <= 0:
            return None
        result = base * factor
    else:
        amount = (
            parse_length(text, knob.unit) if knob.unit in ("km", "m")
            else parse_radius_float(text, default=None)
        )
        if amount is None:
            return None
        negative = text.startswith("-") or any(w in text for w in ("less", "smaller", "fewer", "lower", "minus"))
        result = base - abs(amount) if negative else base + abs(amount)
    if result <= 0:
        return None
    number = f"{result:g}"
    return f"{number} {knob.unit}" if knob.unit in ("km", "m", "days") else number


__all__ = [
    "Knob", "KNOBS", "NOT_TYPEABLE", "knob_for_field", "knob_catalog", "edit_field_knobs",
    "current_values", "resolve_relative",
]
