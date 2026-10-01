"""
graph/builder/executors/geo.py
──────────────────────────────
Geo execution cores, relocated verbatim from wizards/geo_wizard.py (PR5.0).

Both executors are replay-safe by design: every expensive step (geocoding,
POI search) caches into the ``geo_wizard_state`` scratch dict (``ws``) before
any embedded confirmation interrupt fires, so a resume replays reads, not
API calls. ``_execute_deterministic`` stores its output in ``ws["_det_result"]``
for the caller's show/confirm steps to consume.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import unicodedata
from datetime import date, timedelta
from typing import Any, Callable, Optional

from app.core.config import settings
from app.graph.builder.angle_locations import dedupe as _al_dedupe, norm as _al_norm
from app.graph.builder.edits import stash_edits
from app.graph.wizard_exit import StepPaused
from app.graph.builder.slots import _looks_like_street_address
from app.graph.narrator import add_beat
from app.graph.tool_runner import call_tool
from app.graph.tools import (
    _bbox_diagonal_km,
    _EVENT_CATEGORY_MODIFIERS,
    _EVENT_CATEGORY_NOUNS,
    _is_category_like_name,
    _point_in_polygon,
    _region_polygon_cached,
    disambiguate_location_candidates,
    geocode_location,
    geocode_or_place,
    get_competitor_types,
    get_dynamic_place_types,
    probe_location_candidates,
    resolve_event_window,
    resolve_named_target,
    reverse_geocode_point,
    search_brand_locations,
    search_events,
    search_named_places,
    search_pois_by_type,
)
from app.graph.wizard_helpers import (
    market_hint,
    parse_int_safe,
    parse_radius_float,
    resolve_option,
    wizard_interrupt,
)
from app.graph.builder.executors.poi_type_rules import validate_pois

logger = logging.getLogger(__name__)


class _GeoStepPaused(StepPaused):
    """Raised the instant ANY interrupt() inside ``_execute_deterministic``
    resolves with a real answer — ends this task NOW, before a second
    interrupt() call can be reached in the same task.

    ``_execute_deterministic`` chains up to four confirm/disambiguation
    interrupts (geo_disambiguate_location, geo_location_confirmation,
    geo_disambiguate_named_place, geo_store_confirmation) in one synchronous
    run. LangGraph matches a ``Command(resume=...)`` value to an
    ``interrupt()`` call by ITS ORDER WITHIN ONE TASK, not by ``step_key``
    (see ``langgraph.types.interrupt`` / ``PregelScratchpad.resume`` —
    ``scratchpad.resume[idx]`` where ``idx`` is a per-task call counter). Once
    an EARLIER site in this chain becomes skippable on a later replay (its
    ws flag already answered), every interrupt() reached after it that
    replay has its index shifted down by one and silently reads the WRONG
    historical resume value — a real, confirmed bug (traced live against two
    production threads where the POI-confirm screen never appeared).

    The only fix that doesn't depend on that undocumented internal is to
    guarantee at most one interrupt() ever resolves per task — exactly what
    ``poi_confirm``/``maid_confirm``/etc. already do as separate
    ``builder_ask`` node-cycles. Raising this the moment an answer is
    persisted to ``ws`` propagates out of any nesting depth (loops, the
    ``_resolve_and_collect`` closure) to ``builder_act``'s
    ``geo_discover`` dispatch, which catches it and simply re-dispatches
    geo_discover as a FRESH task next tick — cheap, invisible to the user
    (same questions, same order, one extra silent graph tick), and the
    answer this call just got is already in ``ws`` before this raises.
    """


# LLM tiebreak confidence at/above which an ambiguous location name is
# auto-picked without asking the user (mirrors wizard_interrupt's
# _AUTO_ADVANCE_THRESHOLD for high-confidence prefills).
_DISAMBIG_AUTO_CONFIDENCE = 0.95

# Geocode-result place_type → canonical targeting scope. Ground truth for the
# geocode-first scope correction: whatever entity actually won the probe
# determines the scope, not the pre-geocode guess.
_SCOPE_FROM_PLACE_TYPE: dict[str, str] = {
    "locality": "granular_local",
    "postal_town": "granular_local",
    "neighborhood": "granular_local",
    "sublocality": "granular_local",
    "postal_code": "granular_local",
    "street_address": "granular_local",
    "premise": "granular_local",
    "administrative_area_level_3": "granular_local",
    "administrative_area_level_1": "admin_areas",
    "administrative_area_level_2": "admin_areas",
    "country": "country_groups",
}

# det_types anchored on a single physical shop: an ambiguous bare name ("New
# York", "Quebec") almost always means the city, not the whole state/province,
# so keep the LLM auto-pick for these instead of forcing a disambiguation ask.
_SINGLE_SHOP_DET_TYPES: frozenset[str] = frozenset({"store_set", "competitor_nearby"})

# Angles that search inside a NAMED MARKET (vs the store-anchored ones, which bring
# their own address). When one of these is active the market identity matters: the
# region drives the search, so an ambiguous market name must be resolved properly and
# the map should open on the market rather than on a store anchor.
_MARKET_ANGLES: frozenset[str] = frozenset({
    "ai_suggested", "category", "competitor_brand", "named_places", "event_based",
    "competitor_area",
})

# Plain-English name per targeting angle (deterministic_subtype token). Single
# source of truth for angle labeling — read by the progress-chip "Discovery" line
# (_build_geo_progress) AND the combined-angle reveal breakdown
# (build_angle_breakdown), so the sidebar and the narrated message name each angle
# the same way. When the user named the search TYPES near their store (rather than
# asking for rivals), callers override competitor_nearby's label — see
# ANCHOR_TYPES_LABEL and the `_det_anchor_types_from_user` flag.
DET_ANGLE_LABELS: dict[str, str] = {
    "ai_suggested": "Let Punk find the best spots for me",
    "category": "Search for types of places",
    "store_set": "Target people near my own businesses",
    "competitor_nearby": "Target people near my competitors",
    "competitor_area": "Target people near my competitors across my area",
    "competitor_brand": "Search for big brand names",
    "named_places": "Target specific places by name",
    "event_based": "Target people at events",
}
ANCHOR_TYPES_LABEL = "Target people at these places near my business"

# How far back a past-events search reaches when the user implied past attendance but
# named no resolvable date ("the last three Chiefs home games"). A year covers one full
# cycle of an annual conference / seasonal event; 90 days missed most of them and the
# web-search extractor then filled the gap with multi-year-old editions.
_EVENT_PAST_WINDOW_DAYS = 365

# Wording for the "Skipped unverified events: …" line, keyed by the reason codes
# `search_events` returns in `rejected`.
_EVENT_REJECT_LABELS = {
    "no_evidence": "with no source",
    "not_in_evidence": "not found in their source",
    "no_date": "with no confirmed date",
    "date_unsupported": "whose date the source doesn't support",
    "bad_dates": "with inconsistent dates",
    "span_too_long": "that run too long to be one event",
    "outside_window": "outside your date range",
    "not_geocoded": "whose venue couldn't be located",
    "venue_ambiguous": "with an ambiguous venue",
    "outside_area": "outside your target area",
}


def _angle_label(token: str, anchor_types_from_user: bool = False) -> str:
    """Plain-English label for one angle token, with the competitor_nearby override
    applied when the user named the search types (not rivals)."""
    if token == "competitor_nearby" and anchor_types_from_user:
        return ANCHOR_TYPES_LABEL
    return DET_ANGLE_LABELS.get(token, token)


def build_angle_breakdown(det: dict, ws: dict | None = None) -> tuple[list[dict], bool]:
    """Per-angle showcase breakdown for the combined-targeting reveal.

    A geo run may fan several composable angles into one merged POI set; the raw
    ``det["targeting_type"]`` (``"<scope>/<a,b,c>"``) and each POI's ``source_angle``
    tag carry the provenance the narrator needs to tell the user WHICH strategies it
    combined and what each contributed. Returns ``(angles, combined)`` where:

      • ``angles`` — one entry per active subtype, IN the order the set lists them:
        ``{"token", "label", "count", "sample_places": [name, …][:3]}``. Angles that
        contributed no surviving POI are still listed (count 0) so the caller can see
        the full requested set; ``sample_places`` names real spots for the composer.
      • ``combined`` — True when 2+ angles actually contributed POIs (a genuine combo;
        a single-angle run — or a combo where only one arm found anything — is False,
        so it narrates on the unchanged single-angle path).

    Pure read; never raises on a partial/empty ``det``.
    """
    subtype = str((det or {}).get("targeting_type") or "").split("/")[-1]
    tokens = [t.strip() for t in subtype.split(",") if t.strip()]
    anchor_from_user = bool((ws or {}).get("_det_anchor_types_from_user"))

    grouped: dict[str, list[dict]] = {}
    for p in (det or {}).get("targetable_pois") or []:
        grouped.setdefault(p.get("source_angle") or "", []).append(p)

    angles: list[dict] = []
    for token in tokens:
        plist = grouped.get(token, [])
        samples = [str(p.get("name")).strip() for p in plist if p.get("name")]
        # Cities THIS angle contributed from (per-angle divergent combos search
        # different markets per angle) — lets the reveal say "festivals in Montreal,
        # shawarma in Toronto" instead of one flat market. From each POI's
        # parent_location; order-preserving, de-duped.
        _locs = list(dict.fromkeys(
            str(p.get("parent_location")).strip()
            for p in plist if str(p.get("parent_location") or "").strip()
        ))
        angles.append({
            "token": token,
            "label": _angle_label(token, anchor_from_user),
            "count": len(plist),
            "sample_places": samples[:3],
            "locations": _locs,
        })
    combined = sum(1 for a in angles if a["count"] > 0) > 1
    return angles, combined


def poi_group_id(poi: dict) -> str:
    """The category/brand group a POI belongs to: ``"<source_angle>:<label>"``.

    Shared by ``group_pois_by_category`` (groups POIs for the frontend) and
    MAID attribution (stamps this same id onto each observation row it
    matches) so the two line up — a group's member set and an observation's
    ``poi_ids`` prefix are built from the identical label logic.
    """
    angle = str(poi.get("source_angle") or "")
    label = str(poi.get("parent_poi_type") or poi.get("brand") or poi.get("name") or "").strip()
    return f"{angle}:{label}"


def _poi_quality_rank(poi: dict) -> tuple:
    """Sort key for "which of these places does a real customer actually go to".

    Rating alone is a trap: a 5.0 from three reviews outranks a 4.3 from 1,800.
    Anything at or above GEO_POI_RATING_MIN_SAMPLE reviews therefore sorts ahead
    of every thin-sample place, and review count breaks ties within each band.
    """
    n = int(poi.get("user_ratings_total") or 0)
    return (n >= int(settings.GEO_POI_RATING_MIN_SAMPLE), float(poi.get("rating") or 0.0), n)


def _cap_pois_per_category(pois: list[dict], *, cap: int | None = None, writer=None) -> list[dict]:
    """Keep the ``cap`` best-rated POIs in each group. A no-op unless capped.

    OFF in production (GEO_MAX_POIS_PER_CATEGORY defaults to 0): a real campaign
    is entitled to every location in its category, and silently keeping the
    best-rated few would hand the advertiser a smaller audience than they asked
    for with no way to tell. This exists to keep a manual test run small.

    Groups are ``poi_group_id`` — the same (source_angle, parent_poi_type) sets
    the frontend renders as tabs and the MAID executor queries as separate
    requests — so a brand angle caps per brand, an event angle per event, a
    category angle per search term.

    Input order (the round-robin interleave) is preserved for whatever survives:
    this only removes, it never reorders.
    """
    if cap is None:
        cap = int(getattr(settings, "GEO_MAX_POIS_PER_CATEGORY", 0) or 0)
    cap = int(cap or 0)
    if cap <= 0 or not pois:
        return pois

    by_group: dict[str, list[tuple[int, dict]]] = {}
    for idx, poi in enumerate(pois):
        by_group.setdefault(poi_group_id(poi), []).append((idx, poi))

    keep_idx: set[int] = set()
    dropped_per_group: list[tuple[str, int]] = []
    for gid, members in by_group.items():
        if len(members) <= cap:
            keep_idx.update(i for i, _ in members)
            continue
        ranked = sorted(members, key=lambda ip: _poi_quality_rank(ip[1]), reverse=True)
        keep_idx.update(i for i, _ in ranked[:cap])
        dropped_per_group.append((gid.split(":", 1)[-1] or gid, len(members) - cap))

    if not dropped_per_group:
        return pois

    total_dropped = sum(n for _, n in dropped_per_group)
    if writer:
        detail = ", ".join(f"{label} (-{n})" for label, n in dropped_per_group)
        writer({"type": "update", "content": (
            f"Keeping the {cap} best-rated place(s) per category and setting aside "
            f"{total_dropped} lower-rated one(s): {detail}. Say the word if you want "
            f"any of them back."
        )})
    return [p for i, p in enumerate(pois) if i in keep_idx]


def group_pois_by_category(pois: list[dict]) -> list[dict]:
    """Group POIs into category/brand sets for the frontend (one tab per set).

    Every POI already carries ``source_angle`` (which search strategy found it —
    ``category``, ``competitor_brand``, ``event_based``, …) and ``parent_poi_type``
    (the literal search term: ``"coffee shop"``, ``"Starbucks"``, an event name) —
    stamped uniformly across every angle already (see ``build_angle_breakdown``).
    Grouping on that pair is enough to separate "all coffee shops" from "all
    Starbucks" from "all KFC" with no new POI field.

    Returns one entry per distinct ``(source_angle, parent_poi_type)``, in
    first-seen order: ``{"id", "key", "kind", "source_angle", "count", "pois"}``.
    ``id`` is a stable ``"<source_angle>:<parent_poi_type>"`` token other code
    (MAID provenance, set ops) can key off of; ``key`` is the display label
    (just ``parent_poi_type``); ``kind`` is the raw angle token (machine-readable
    — same value as ``source_angle``, kept as a separate key so a future group
    shape that splits one angle into several kinds doesn't need a rename).
    """
    groups: dict[str, dict] = {}
    for p in pois or []:
        gid = poi_group_id(p)
        angle = str(p.get("source_angle") or "")
        g = groups.get(gid)
        if g is None:
            g = groups[gid] = {
                "id": gid, "key": gid.split(":", 1)[1], "kind": angle,
                "source_angle": angle, "count": 0, "pois": [],
            }
        g["count"] += 1
        g["pois"].append(p)
    return list(groups.values())


def _candidate_scopes(cands: list[dict]) -> set[str]:
    """Distinct targeting scopes the probe candidates map to (via place_type).

    Ground truth for "genuinely ambiguous across scopes": if a bare name
    resolved to both a locality and an administrative_area_level_1, the set has
    >1 element and the user should pick rather than let the LLM guess."""
    return {
        _SCOPE_FROM_PLACE_TYPE[c["place_type"]]
        for c in cands
        if c.get("place_type") in _SCOPE_FROM_PLACE_TYPE
    }

# Granular place_types whose OWN name (not the parent city) is the right locality
# filter token. A borough resolves with locality="New York" (parent) but its POIs
# read "…, Brooklyn, NY…" — filtering on the parent would keep the neighbours and
# drop the target. For these, use the formatted-address head ("Brooklyn"). Both
# Google (sublocality) and Nominatim (suburb/city_district) vocab are listed so the
# fallback geocode path is covered too.
_SUBLOCALITY_PLACE_TYPES: frozenset[str] = frozenset({
    "sublocality", "suburb", "city_district",
})

# Granular place_types whose parent-city locality token IS the right filter (a POI
# in the city carries the city name). Google + Nominatim vocab.
_CITY_PLACE_TYPES: frozenset[str] = frozenset({
    "locality", "postal_town", "administrative_area_level_3", "postal_code",
    "city", "town", "county",
})


def _derive_resolved_scope(
    ws: dict, geocoded_locations: list[dict], targeting_type: str, writer: Any
) -> None:
    """Write ``ws["_resolved_scope"]`` when every resolved location's place_type
    maps unanimously to a scope that differs from the passed ``targeting_type``.
    Mixed or unknown types leave the passed scope untouched."""
    scopes = {
        _SCOPE_FROM_PLACE_TYPE[loc["place_type"]]
        for loc in geocoded_locations
        if loc.get("place_type") in _SCOPE_FROM_PLACE_TYPE
    }
    if len(scopes) == 1:
        derived = next(iter(scopes))
        if derived != targeting_type:
            ws["_resolved_scope"] = derived
            writer({"type": "thinking", "content": (
                f"Geocode-first scope correction: '{targeting_type}' → '{derived}' "
                "(from resolved place types)"
            )})
    elif len(scopes) > 1:
        writer({"type": "thinking", "content": (
            f"Mixed resolved scopes {sorted(scopes)} — keeping '{targeting_type}'"
        )})


def _confirm_label(loc: dict) -> str:
    """The RESOLVED place description to show at the location-confirm step.

    Prefer ``formatted_address`` ("Québec City, QC, Canada") over the raw
    ``location_name`` — the latter is the user's typed word ("Quebec"), which
    reads as ambiguous (city vs province) and makes the confirm message re-ask the
    disambiguation the user already answered. Falls back to location_name."""
    return (loc.get("formatted_address") or loc.get("location_name") or "?").strip()

# ── Canonical answer→key maps ──────────────────────────────────────────────────
# Shared by the wizard collection nodes and builder_ask normalization: raw
# option answers (full labels, ordinals, legacy phrasing) resolve to the
# canonical keys the executors branch on. Matching is substring-on-lowercase.

LOCATION_TYPE_MAP: dict[str, str] = {
    "target country group": "country_groups",
    "target state/province": "admin_areas",
    "target a specific city": "granular_local",
    "drop a pin": "radius",
    # Backward compatibility
    "country groups": "country_groups",
    "admin areas": "admin_areas",
    "granular local": "granular_local",
    "radius": "radius",
}

# Scanned as SUBSTRINGS in insertion order — the first key found in the resolved
# option label wins, so the two competitor lines (which share a prefix) must be
# keyed on their distinguishing tail and listed before any shorter alias.
DET_TYPE_MAP: dict[str, str] = {
    "let punk find": "ai_suggested",
    "search for types": "category",
    "target people near my own": "store_set",
    "across my whole targeting area": "competitor_area",
    "around my business address": "competitor_nearby",
    "target people hanging out near my competitors": "competitor_nearby",
    "search for big brand": "competitor_brand",
    "i already know the exact places": "named_places",
    "exact places": "named_places",
    "target people at events": "event_based",
    # Backward compatibility
    "ai suggested": "ai_suggested",
    "category": "category",
    "store set": "store_set",
    "competitor area": "competitor_area",
    "competitor nearby": "competitor_nearby",
    "competitor brand": "competitor_brand",
    "named places": "named_places",
    "event": "event_based",
}


def _build_geo_progress(ws: dict) -> list[dict]:
    """Build confirmed-steps list from current geo_wizard_state scratch dict."""
    items: list[dict] = []
    _TYPE_LABELS = {
        "country_groups": "Target country group",
        "admin_areas": "Target State/Province or District", "granular_local": "Target a specific city, Zip or address", "radius": "Drop a pin and set targeting area",
    }
    _DET_LABELS = DET_ANGLE_LABELS
    if ws.get("targeting_type"):
        items.append({"label": "Targeting Scope", "value": _TYPE_LABELS.get(ws["targeting_type"], ws["targeting_type"])})
    if ws.get("location_names"):
        locs = ws["location_names"]
        val = ", ".join(locs[:2]) + (f" +{len(locs) - 2} more" if len(locs) > 2 else "")
        items.append({"label": "Locations", "value": val})
    # Pin+radius rings (city/town/metro confirm, or a manual/demoted pin) —
    # one value per location when they differ, else a single shared value.
    _pin_radii = [
        loc["search_radius_km"] for loc in (ws.get("_geocoded_locations") or [])
        if loc.get("ui_mode") == "pin_radius" and loc.get("search_radius_km")
    ]
    if _pin_radii:
        _uniq = sorted(set(_pin_radii))
        _val = f"{_uniq[0]:g} km" if len(_uniq) == 1 else ", ".join(f"{r:g} km" for r in _uniq[:3])
        items.append({"label": "Search Radius", "value": _val})
    if ws.get("business_desc"):
        desc = ws["business_desc"]
        items.append({"label": "Business", "value": desc[:60] + ("…" if len(desc) > 60 else "")})
    if ws.get("targeting_method"):
        items.append({"label": "Method", "value": ws["targeting_method"].title()})
    if ws.get("deterministic_type"):
        # det_type may be a comma-joined set of composable angles — label each.
        _subs = [s.strip() for s in str(ws["deterministic_type"]).split(",") if s.strip()]
        # competitor_nearby also serves "the types I named, near my store" — say that
        # instead of calling the user's own chosen places their "competitors".
        _labels = dict(_DET_LABELS)
        if ws.get("_det_anchor_types_from_user"):
            _labels["competitor_nearby"] = ANCHOR_TYPES_LABEL
        items.append({"label": "Discovery", "value": " + ".join(
            _labels.get(s, s) for s in _subs
        ) or ws["deterministic_type"]})

    extra = ws.get("extra_inputs") or {}
    if extra.get("poi_types_list"):
        items.append({"label": "Place Types", "value": ", ".join(extra["poi_types_list"][:3])})

    if ws.get("deterministic_type") == "store_set":
        if extra.get("store_addresses_list"):
            items.append({"label": "Business Locations", "value": f"{len(extra['store_addresses_list'])} address(es)"})
    else:
        if extra.get("store_addresses_list"):
            items.append({"label": "Business Locations", "value": f"{len(extra['store_addresses_list'])} address(es)"})

    _anchors = extra.get("competitor_anchors") or []
    if len(_anchors) > 1:
        items.append({"label": "Your Business", "value": f"{len(_anchors)} address(es)"})
    elif extra.get("store_address"):
        # The RESOLVED name when we have it. `store_address` is the raw string the
        # user typed ("its in SKS tower in mohakhali") — never their shop's name.
        _anchor_geo = extra.get("competitor_store_geocoded") or {}
        items.append({"label": "Your Business", "value": (
            _anchor_geo.get("location_name") or extra["store_address"]
        )})

    if len(_anchors) > 1:
        items.append({"label": "Locations Confirmed", "value": f"{len(_anchors)} location(s)"})
    elif extra.get("competitor_store_geocoded"):
        addr = extra["competitor_store_geocoded"].get("formatted_address", extra.get("store_address", ""))
        items.append({"label": "Location Confirmed", "value": addr})

    if extra.get("competitor_radius_km"):
        items.append({"label": "Search Radius", "value": f"{extra['competitor_radius_km']} km"})

    if extra.get("brand_names_list"):
        items.append({"label": "Brands", "value": ", ".join(extra["brand_names_list"][:3])})

    if extra.get("named_places_list"):
        items.append({"label": "Places", "value": ", ".join(extra["named_places_list"][:3])})

    if extra.get("event_queries_list"):
        items.append({"label": "Events", "value": ", ".join(extra["event_queries_list"][:2])})

    if extra.get("event_date_range"):
        items.append({"label": "Date Range", "value": extra["event_date_range"]})

    if extra.get("radius_km"):
        items.append({"label": "Target Radius", "value": f"{extra['radius_km']} km"})

    return items


# Bounded concurrency for the POI/geocode search fan-out. Google Places calls
# are independent per (location × type) so they run concurrently instead of
# serially; the semaphore caps in-flight requests to stay under rate limits.
# call_tool never raises (returns (None, err)), so plain gather is safe and the
# result order matches input order — output is identical to the old serial loop.
_POI_SEARCH_CONCURRENCY = 6


async def _gather_bounded(coros: list, limit: int = _POI_SEARCH_CONCURRENCY) -> list:
    """Await coroutines with bounded concurrency, preserving input order."""
    if not coros:
        return []
    sem = asyncio.Semaphore(limit)

    async def _run(coro):
        async with sem:
            return await coro

    return await asyncio.gather(*(_run(c) for c in coros))


def _locality_filter_for(loc: dict, targeting_type: str) -> str | None:
    """Locality token used to drop neighbour-area bleed, for a specific-city search
    only. Returns None for admin/province/radius scopes (cross-area coverage is
    intended) and for pinpoint addresses (street_address/premise, and the synthetic
    pin dict that carries no place_type), where a locality filter would wrongly
    discard valid nearby POIs — radius/bbox already contains those.

    The token source depends on the resolved ``place_type``:

    - Sublocality/borough (``sublocality``, OSM ``suburb``/``city_district``): the
      geocoder's ``locality`` is the PARENT city (Brooklyn resolves with
      locality="New York"), which would keep the neighbours and drop the target.
      Use the formatted-address head ("Brooklyn") instead.
    - City-like (``locality`` etc., or legacy ``is_city``): the resolved
      ``locality`` is correct — a POI in the city carries the city name. Preferred
      over the raw ``location_name`` so a typo'd query ("ney york") still yields a
      real city token instead of wiping every POI.

    ``neighborhood`` is treated as pinpoint (None): Google POI addresses rarely
    carry sub-borough neighbourhood names, so a neighbourhood token over-drops.

    ``pin_radius`` mode (city/town/metro confirm, or a manual/demoted pin)
    always returns None regardless of ``targeting_type``: a hard ring already
    scopes the search geometrically, so a name-based bleed guard is redundant
    at best and wrongly restrictive at worst (the user may have deliberately
    drawn the ring wider than the political place)."""
    if loc.get("ui_mode") == "pin_radius":
        return None
    if targeting_type != "granular_local":
        return None

    place_type = loc.get("place_type")
    _addr_head = (loc.get("formatted_address") or "").split(",")[0].strip()

    if place_type in _SUBLOCALITY_PLACE_TYPES:
        return _addr_head or loc.get("location_name") or None

    if place_type in _CITY_PLACE_TYPES or loc.get("is_city"):
        return (
            loc.get("locality")
            or _addr_head
            or loc.get("location_name")
            or None
        )

    # Pinpoint (street_address/premise), neighborhood, unknown, or synthetic pin
    # (no place_type, is_city False): bbox/radius handles containment.
    return None


def _country_filter_for(loc: dict, targeting_type: str) -> str | None:
    """Country name used to drop cross-border POI bleed, for an admin-area or
    country-group search only. A large region's axis-aligned bounding box
    physically overlaps neighbouring countries (Ontario province's bbox contains
    Chicago/Minneapolis), and the hard rectangle restriction can't tell them
    apart. Returns None for granular_local/radius scopes, where the bbox is a
    single city/ring and no cross-border filter is needed. ``pin_radius``
    mode always returns None — see ``_locality_filter_for``'s docstring."""
    if loc.get("ui_mode") == "pin_radius":
        return None
    if targeting_type in ("admin_areas", "country_groups"):
        return loc.get("country_name") or None
    return None


def _state_filter_for(loc: dict, targeting_type: str) -> str | None:
    """State/province name used to drop cross-STATE POI bleed. A metro-sized city's
    axis-aligned bbox reaches across a state line (New York City's box contains
    Jersey City/Hoboken in New Jersey), and the metro-relax that nulls the locality
    filter for big metros would otherwise leave that bleed unguarded. One admin
    level below ``_country_filter_for``.

    Returns the resolved state for granular_local (city) and admin_areas
    (state/province) scopes; None for country_groups (spans states by design) and
    radius (a single ring, no bbox). ``pin_radius`` mode always returns None —
    see ``_locality_filter_for``'s docstring."""
    if loc.get("ui_mode") == "pin_radius":
        return None
    if targeting_type in ("granular_local", "admin_areas"):
        return loc.get("admin_area1_name") or None
    return None


def _round_robin_by(pois: list[dict], key: str | Callable[[dict], Any]) -> list[dict]:
    """Interleave POIs across groups (by ``key``) so a hard cap applied AFTER this
    keeps some POIs from EVERY group instead of dropping the trailing groups
    entirely.

    ``key`` is either a POI field name (``str``) or a callable mapping a POI to its
    group key. Pass a callable to interleave across a COMPOSITE dimension — e.g.
    ``lambda p: (p["parent_location"], p["parent_poi_type"])`` so the post-cap keeps
    POIs from every (location × type) group. Grouping by ``parent_location`` alone
    is fair across cities but NOT across POI types: ``all_pois`` is built
    type-by-type within each location, so a single-city multi-type run collapses to
    one bucket and the trailing types (e.g. luxury venues after hospitals) get wiped
    by the ``[:200]`` cap. The composite key guards that case.

    Preserves each group's internal order; groups appear in first-seen order. POIs
    whose key is missing/None fall into one bucket and are still interleaved fairly."""
    key_fn = key if callable(key) else (lambda p, _k=key: p.get(_k))
    groups: dict[Any, list[dict]] = {}
    for p in pois:
        groups.setdefault(key_fn(p), []).append(p)
    buckets = list(groups.values())
    out: list[dict] = []
    i = 0
    while any(i < len(b) for b in buckets):
        for b in buckets:
            if i < len(b):
                out.append(b[i])
        i += 1
    return out


def _bbox_from_center(lat: float, lng: float, radius_km: float) -> dict | None:
    """Synthesize a {lat_min,lat_max,lng_min,lng_max} box enclosing the circle of
    ``radius_km`` around (lat, lng). Lets the no-bounds scopes (dropped pin, radius,
    competitor) enter ``_collect_places_in_area``'s TILED path so they fill toward the
    same POI ceiling as named regions instead of capping at one Google page (~20).

    The box over-covers the circle; the tool trims corners back to the ring via its
    ``search_radius_km`` filter. Returns None for a missing/zero radius (caller then
    leaves bounds unset and keeps the legacy single-circle search)."""
    if not radius_km or radius_km <= 0:
        return None
    lat_delta = radius_km / 111.0
    lng_delta = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    return {
        "lat_min": lat - lat_delta, "lat_max": lat + lat_delta,
        "lng_min": lng - lng_delta, "lng_max": lng + lng_delta,
    }


# ── Pin+radius confirm (city/town/metro scope) ──────────────────────────────
# Country/state keep the political boundary at the confirm step (real
# administrative shapes, no natural "radius" reading). Everything smaller —
# city, town, metro, neighbourhood, a street address, or a location the user
# drew/dragged themselves — becomes a pin + adjustable ring instead, searched
# exactly like the standalone "drop a pin" scope already searches
# (_bbox_from_center + a hard-radius filter, no name-based bleed guard).


def _clamp_pin_radius_km(value: Any) -> float:
    """A pin+radius ring, clamped to the same bounds Meta's own
    ``custom_locations.radius`` accepts at publish time
    (``settings.GEO_PIN_RADIUS_MIN_KM``/``MAX_KM`` — shared with
    ``meta_ads.py`` so the search-time ring and the publish-time fallback
    ring can never drift apart). A missing/zero/unparseable value falls back
    to the flat default rather than clamping to the floor — a 0 km ring is
    never what was meant."""
    try:
        km = float(value)
    except (TypeError, ValueError):
        km = 0.0
    if km <= 0:
        km = settings.GEO_PIN_RADIUS_FALLBACK_KM
    return round(min(max(km, settings.GEO_PIN_RADIUS_MIN_KM), settings.GEO_PIN_RADIUS_MAX_KM), 1)


def _default_radius_km_from_bounds(bounds: dict | None) -> float:
    """Default search ring for a pin+radius confirm, sized from the
    geocoder's own viewport (``bounds`` — already fetched at geocode time, no
    extra API call): roughly half the bounds diagonal, so a village and a
    metro don't start at the same ring. No bounds (street address / manual
    pin) → the flat fallback."""
    if not bounds:
        return settings.GEO_PIN_RADIUS_FALLBACK_KM
    try:
        diag = _bbox_diagonal_km(bounds)
    except (KeyError, TypeError, ValueError):
        return settings.GEO_PIN_RADIUS_FALLBACK_KM
    return _clamp_pin_radius_km(diag / 2.0)


def _stamp_location_radius_mode(loc: dict, ws: dict) -> None:
    """Mark one geocoded location ``"boundary"`` or ``"pin_radius"`` and, for
    the latter, size its default search ring.

    Reuses ``_SCOPE_FROM_PLACE_TYPE`` — the same ground truth the
    geocode-first scope correction already trusts — instead of inventing a
    second place-type classification: a result that maps to ``admin_areas``/
    ``country_groups`` is a real administrative shape (boundary); everything
    else (city, town, neighbourhood, street address, or no ``place_type`` at
    all — a synthetic/manual pin) is pin+radius.

    Re-applies any override the user already dialed in at an earlier
    confirm-widget edit (``ws["_loc_radius_overrides"]``, keyed by the
    location's own source name) so a re-geocode forced by editing a SIBLING
    location doesn't silently revert this one's radius or dragged center
    back to the default.
    """
    place_type = loc.get("place_type")
    admin_scope = _SCOPE_FROM_PLACE_TYPE.get(place_type) if place_type else None
    is_boundary = admin_scope in ("admin_areas", "country_groups")
    loc["ui_mode"] = "boundary" if is_boundary else "pin_radius"
    if is_boundary:
        loc.pop("search_radius_km", None)
        loc.pop("default_radius_km", None)
        return
    default_km = _default_radius_km_from_bounds(loc.get("bounds"))
    loc["default_radius_km"] = default_km
    # A ring the user TYPED ("make the circle 5 km", see ``set_search_ring``)
    # replaces the bounds-derived default for every location, including ones
    # geocoded after it. A per-location drag override below still wins.
    loc["search_radius_km"] = ws.get("_search_ring_km") or default_km
    key = _norm_poi_name(loc.get("_source_name") or loc.get("location_name"))
    override = (ws.get("_loc_radius_overrides") or {}).get(key) if key else None
    if not override:
        return
    if override.get("demoted"):
        loc.pop("place_id", None)
        loc.pop("place_type", None)
        loc.pop("bounds", None)
        loc["is_city"] = False
        if override.get("lat") is not None and override.get("lng") is not None:
            loc["latitude"], loc["longitude"] = override["lat"], override["lng"]
        if override.get("label"):
            loc["location_name"] = override["label"]
            loc["formatted_address"] = override.get("formatted_address") or override["label"]
    if override.get("radius_km"):
        loc["search_radius_km"] = override["radius_km"]


def set_search_ring(ws: dict, km: Any) -> list[str] | None:
    """Apply a TYPED search-circle radius ("make the circle 5 km") to every
    pin+radius location. This is the circle Places searches inside — NOT the
    per-POI visit ring (``poi_radius_m``).

    The map widget's ``updated`` delta (``_apply_location_updates``) is the
    only other writer of ``search_radius_km``; without this a typed radius
    resolved to the ``radius_km`` slot, which only a radius-scope run reads,
    and was acked then lost on the re-geocode.

    Returns the labels of the locations whose circle changed; ``[]`` when
    nothing is geocoded yet (the ring is stored and stamped at geocode time);
    ``None`` when locations exist but none has a circle (state/country
    boundaries) — nothing is stored, so the caller can refuse honestly.
    """
    ring = _clamp_pin_radius_km(km)
    locs = list(ws.get("_geocoded_locations") or [])
    # Manual pins are separate dicts in `_manual_pins`; `_with_manual_pins`
    # dedupes by equality, so both copies must change or the pin duplicates.
    pins = list(ws.get("_manual_pins") or [])
    circled = [loc for loc in locs + pins if loc.get("ui_mode") == "pin_radius"]
    if (locs or pins) and not circled:
        return None
    ws["_search_ring_km"] = ring
    # A typed ring replaces earlier per-location drags; dragged centres and
    # demotions in the same override entry stay.
    for ov in (ws.get("_loc_radius_overrides") or {}).values():
        ov.pop("radius_km", None)
    changed: list[str] = []
    for loc in circled:
        loc["search_radius_km"] = ring
        label = _confirm_label(loc)
        if label not in changed:
            changed.append(label)
    return changed


def restamp_search_rings(ws: dict) -> None:
    """Recompute every pin+radius circle from the ring DECISIONS (per-location
    override → typed ring → the location's own default) after those decisions
    were restored — an undo. Without it the cached `_geocoded_locations` keep
    the undone radius and the re-run search uses it."""
    ring = ws.get("_search_ring_km")
    overrides = ws.get("_loc_radius_overrides") or {}
    for loc in list(ws.get("_geocoded_locations") or []) + list(ws.get("_manual_pins") or []):
        if loc.get("ui_mode") != "pin_radius":
            continue
        key = _norm_poi_name(loc.get("_source_name") or loc.get("location_name"))
        radius = (overrides.get(key) or {}).get("radius_km") if key else None
        loc["search_radius_km"] = radius or ring or loc.get("default_radius_km") or loc.get("search_radius_km")


def _search_geometry_for(
    loc: dict, pin_search_radius_km: float | None
) -> tuple[dict | None, float | None]:
    """``(bounds, search_radius_km)`` for one location's Places search.

    A ``pin_radius`` location (city/town/metro confirm, a manual pin, or a
    drag-demoted one) searches a ring around its OWN coordinates sized by its
    OWN ``search_radius_km`` — falling back to the run's flat
    ``pin_search_radius_km`` only if that location somehow carries none (e.g.
    an old checkpoint). A ``boundary`` location (country/state) keeps
    whatever political bbox it geocoded with, unchanged — tiling, name
    filters and the OSM polygon guard all still apply to it.
    """
    if loc.get("ui_mode") == "pin_radius":
        radius = loc.get("search_radius_km") or pin_search_radius_km or settings.GEO_PIN_RADIUS_FALLBACK_KM
        return _bbox_from_center(loc.get("latitude"), loc.get("longitude"), radius), radius
    bounds = loc.get("bounds") or _bbox_from_center(
        loc.get("latitude"), loc.get("longitude"), pin_search_radius_km
    )
    return bounds, pin_search_radius_km


def _default_past_event_window(days: int = _EVENT_PAST_WINDOW_DAYS) -> str:
    """Human-readable "Month YYYY - Month YYYY" window covering roughly the last
    ``days`` days, ending today.

    ``search_events`` interpolates the range straight into the search text, so this
    matches the shape the extractor already produces ("June 2026") rather than an
    ISO range. Used when the user's phrasing implies past attendance but carries no
    resolvable date ("the last three Chiefs home games")."""
    today = date.today()
    start = today - timedelta(days=days)
    if (start.year, start.month) == (today.year, today.month):
        return start.strftime("%B %Y")
    return f"{start.strftime('%B %Y')} - {today.strftime('%B %Y')}"


def _distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine distance in kilometres between two lat/lng points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# How far a probe candidate may sit from the widget's supplied coordinate and still
# count as "the place the user picked". A city centroid from Google's geocoder and the
# autocomplete coordinate for the same city land within a few km; this ceiling only
# rejects a candidate that is plainly a different place.
_HINT_MAX_DISTANCE_KM = 50.0


def _pick_candidate_by_hint(cands: list[dict], hint: dict | None) -> int | None:
    """Index of the probe candidate a location-picker hint identifies, or None.

    The confirm widget's search bar sends the place it resolved (``place_type`` +
    ``lat``/``lng``) alongside the bare name. Re-geocoding that name re-probes and can
    surface several entities ("Bastrop" → the city AND the county), which would fire a
    disambiguation ask one beat after the user already picked from a list. The hint
    settles it: prefer an exact ``place_type`` match, break a tie (or a miss) by
    proximity to the supplied coordinate.

    Returns None when the hint cannot decide — the caller then falls through to the
    LLM tiebreak / user ask unchanged.
    """
    if not hint:
        return None

    pt = str(hint.get("place_type") or "").strip().lower()
    pool = [
        i for i, c in enumerate(cands)
        if pt and str(c.get("place_type") or "").strip().lower() == pt
    ]
    if len(pool) == 1:
        return pool[0]
    if not pool:
        pool = list(range(len(cands)))

    lat, lng = hint.get("lat"), hint.get("lng")
    if lat is None or lng is None:
        return None

    scored: list[tuple[float, int]] = []
    for i in pool:
        c = cands[i]
        try:
            d = _distance_km(
                float(lat), float(lng),
                float(c["latitude"]), float(c["longitude"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if d <= _HINT_MAX_DISTANCE_KM:
            scored.append((d, i))
    return min(scored)[1] if scored else None


async def _execute_deterministic(
    targeting_type: str,
    deterministic_type: str,
    location_names: list[str],
    business_desc: str,
    writer: Any,
    extra_inputs: dict,
    ws: dict,
    state: Any = None,
    target_audience: str = "",
) -> None:
    """Execute deterministic POI discovery. Stores results in ws['_det_result']. No interrupts."""
    tool_log: list[dict] = []
    # POI lookups infer WHERE the audience physically goes — give them the stated
    # audience too when the user named one. business_desc stays untouched for the
    # campaign brief and progress display; only the place-type context is enriched.
    # Both halves are labelled so the LLM can tell "who to reach" apart from
    # "what we sell" (the entry gate now guarantees business_desc is non-empty —
    # see builder_node's WHAT fallback just above this call).
    poi_context = (
        (f"Business: {business_desc}" if business_desc else "")
        + (f"\nTarget audience: {target_audience}" if target_audience else "")
    )
    poi_radius_km = parse_radius_float(str(extra_inputs.get("poi_radius_km") or ""), default=None)
    lookback_days = parse_int_safe(str(extra_inputs.get("lookback_days") or ""), default=None)
    # Radius scope ("drop a pin + ring"): the drawn ring is the POI SEARCH area.
    # The synthetic pin location carries no bbox, so without this the search would
    # fall through to text-relevance only and ignore the ring. Effective only when
    # there is no bbox (named-location scopes pass bounds and ignore this).
    _pin_search_radius_km = (
        parse_radius_float(str(extra_inputs.get("radius_km") or ""), default=None)
        if targeting_type == "radius" else None
    )
    poi_types: list[str] = list(extra_inputs.get("poi_types_list", []))
    all_pois: list[dict] = []
    geocoded_locations: list[dict] = []
    # Label accumulator: each executor arm records the place types IT searched
    # here instead of clobbering the shared `poi_types` var. For a combo the saved
    # "Place Types" label is the UNION of every arm's types, not the last arm's
    # leftover; for a single angle it equals exactly what that arm used to save.
    collected_types: list[str] = []

    # A run may target MULTIPLE composable angles at once — det_type is a
    # comma-joined set (e.g. "event_based,named_places"). Parse it into an
    # ordered, de-duped list of active subtypes; each composable executor arm
    # below runs when its subtype is in the set, so combos fan several searches
    # into the shared `all_pois`. Store-anchored (store_set/competitor_nearby)
    # and ai_suggested are always single (one-element set) — unchanged behavior.
    subtypes: list[str] = [s.strip() for s in str(deterministic_type).split(",") if s.strip()]
    if not subtypes:
        subtypes = ["ai_suggested"]
    subtype_set: set[str] = set(subtypes)

    # ── Progress-chip scratch ────────────────────────────────────────────────────
    # `_build_geo_progress` reads these PLAIN keys off ``ws``, but the builder path
    # only ever stores its own ``_``-prefixed caches there (the plain shape is the
    # retired wizard's). Without this seeding every interrupt below shipped
    # ``progress: []`` and the sidebar summary stayed blank the whole geo stage.
    # Every value is already a parameter here, so seed from the source of truth.
    ws["targeting_type"] = targeting_type
    ws["location_names"] = list(location_names)
    ws["deterministic_type"] = deterministic_type
    ws["extra_inputs"] = extra_inputs
    if business_desc:
        ws["business_desc"] = business_desc

    # ── Per-angle location/type overrides ────────────────────────────────────────
    # `angle_specs` (in extra_inputs) lets a DIVERGENT combo give each angle its OWN
    # location(s) + types ("shawarma in Toronto, film festivals in Montreal"). When
    # absent, every angle inherits the shared flat `location_names` + type lists —
    # byte-identical legacy behavior. Each token maps to at most one spec.
    _angle_specs = extra_inputs.get("angle_specs") or []
    _spec_by_angle: dict[str, dict] = {}
    for _s in _angle_specs:
        if isinstance(_s, dict) and _s.get("angle"):
            _spec_by_angle.setdefault(_s["angle"], _s)
    _shared_names: list[str] = list(location_names)
    # A location-confirm edit earlier in this same geo_discover session (a
    # PRIOR call, before a _GeoStepPaused round trip — see that class) already
    # rebound every angle to its own post-edit set and stashed it here; use it
    # verbatim for any token it covers so the edit doesn't silently revert
    # back to a per-angle spec's original pinned locations on this re-entry.
    # A token the sync doesn't cover (a newly-activated angle) still falls
    # back to the normal spec/shared-set derivation below.
    _angle_names_synced = ws.get("_angle_names_synced") or {}
    # Per-token location names: a spec's own locations, else the shared set (inherit).
    angle_names: dict[str, list[str]] = {}
    for _tok in subtypes:
        if _tok in _angle_names_synced:
            angle_names[_tok] = list(_angle_names_synced[_tok])
            continue
        _sp_locs = (_spec_by_angle.get(_tok) or {}).get("locations")
        angle_names[_tok] = (
            [str(x) for x in _sp_locs if str(x).strip()] if _sp_locs else _shared_names
        )
    # Geocode the UNION of every angle's names (dedup, order-preserving) so a single
    # geocode/confirm pass covers all markets; each arm later filters to its own.
    if _spec_by_angle:
        _union: list[str] = []
        _seen_nm: set[str] = set()
        for _nm in [n for _names in angle_names.values() for n in _names] + _shared_names:
            _key = _nm.strip().lower()
            if _nm.strip() and _key not in _seen_nm:
                _seen_nm.add(_key)
                _union.append(_nm)
        if _union:
            location_names = _union

    def _types_for(token: str, field: str, default: list) -> list:
        """Per-angle type list: a spec's own field, else the shared flat default."""
        _v = (_spec_by_angle.get(token) or {}).get(field)
        return [str(x) for x in _v if str(x).strip()] if _v else default

    def _scope_for(token: str) -> str:
        """Per-angle targeting scope (area-size): a spec's own ``scope``, else the
        run-wide ``targeting_type``. Drives the locality/state/country filters so a
        province-scoped angle drops the locality filter while a city-scoped sibling
        keeps it. Reads ``targeting_type`` lazily so the geocode-first scope
        correction (which rebinds it) is honored as the default."""
        return (_spec_by_angle.get(token) or {}).get("scope") or targeting_type

    # Invalidate the checkpointed geocode/POI scratch when the inputs that define
    # the result change (e.g. the user added/changed a location). Without this the
    # sticky `_geocoded_locations` / `_all_pois_cache` are reused on a re-run and
    # the count the user sees stays frozen at the previous location set.
    #
    # Split in two — WHERE the search happens vs WHAT it looks for — so an
    # edit to one side (`edits.invalidate_from`'s "poi_search" unit: det_type,
    # poi_types, brands, named places, events, competitor radius) does not
    # reset `_location_confirmed` and re-ask a location confirmation the user
    # never touched. `edits._LOCATION_WS_KEYS` / `_POI_WS_KEYS` must agree with
    # this split — both encode the same geocode/poi_search line.
    #
    # `angle_names` is deliberately NOT here despite naming locations: it is
    # {angle_token: [names]}, keyed by which ANGLES are active, not by which
    # locations exist. Activating a new angle (e.g. "add starbucks" turning on
    # `competitor_brand`) adds a key to this dict with the SAME location
    # values — geocoding output is untouched — but the dict's repr still
    # changes, which used to bust this key and re-ask a location the user
    # never touched. `geocoded_locations`/the confirm are pure functions of
    # `location_names` (the flat union, already folded in below); which
    # angles later read from that union (`_want = angle_names.get(token, ...)`
    # at the POI-search loop) is a `_poi_cache_key` concern instead.
    def _compute_loc_cache_key() -> str:
        """Reads the enclosing (possibly just-edited) `location_names` /
        `targeting_type` — called again inside `_apply_location_edit` (via
        `nonlocal`-updated values) so the key seen by the retry below already
        matches, instead of the mismatch check re-popping the confirmation an
        edit that ends via _GeoStepPaused just settled."""
        return repr((
            sorted(n.strip().lower() for n in location_names if n and n.strip()),
            targeting_type,
            extra_inputs.get("lat"),
            extra_inputs.get("lng"),
            extra_inputs.get("radius_km"),
            # Competitor anchor set: changing the confirmed anchor moves the
            # search CENTER, which is a location-side change.
            sorted(
                (round(float(a["latitude"]), 5), round(float(a["longitude"]), 5))
                for a in (extra_inputs.get("competitor_anchors") or [])
                if a.get("latitude") and a.get("longitude")
            ),
        ))

    _loc_cache_key = _compute_loc_cache_key()
    _poi_cache_key = repr((
        tuple(sorted(subtype_set)),
        # Per-angle location assignment: two runs with the same union of names
        # but a different angle→location mapping (including a newly-activated
        # angle) must not share a cached POI result — each angle searches its
        # own location subset.
        sorted(
            (k, tuple(sorted(n.strip().lower() for n in v if n and n.strip())))
            for k, v in angle_names.items()
        ),
        # Per-angle TYPE assignment: two runs with the same angle→location
        # mapping but different searched types must not share a cached result.
        repr(sorted(
            (s.get("angle"), s.get("scope") or "", tuple(sorted(str(t).strip().lower()
                for f in ("poi_types", "anchor_types", "event_queries",
                          "named_places", "competitor_brands")
                for t in (s.get(f) or []))))
            for s in _angle_specs if isinstance(s, dict) and s.get("angle")
        )),
        sorted(poi_types),
        sorted(str(s).strip().lower() for s in extra_inputs.get("brand_names_list", []) if str(s).strip()),
        sorted(str(s).strip().lower() for s in extra_inputs.get("named_places_list", []) if str(s).strip()),
        # Event inputs belong in the key like every other angle's: without them a
        # changed event query or date range hits the sticky POI cache below and
        # returns the previous run's venues (and its cross-check verdicts).
        sorted(str(s).strip().lower() for s in extra_inputs.get("event_queries_list", []) if str(s).strip()),
        str(extra_inputs.get("event_date_range") or "").strip().lower(),
        # Search radius around the (already-settled) anchor/location — changes
        # WHAT gets found, not where the center is.
        extra_inputs.get("competitor_radius_km"),
        # Per-location pin+radius signature (city/town/metro confirm, or a
        # manual/demoted pin) — a radius nudge or a dragged center on the
        # confirm map changes neither `location_names` nor `extra_inputs`,
        # so without this the POI cache below would go stale and silently
        # keep serving the pre-edit search. Read off the LAST run's
        # persisted `_geocoded_locations` (this key is computed before
        # `_do_geocode` runs on this call) — a genuinely new location set
        # is already covered by the `angle_names` signature above.
        sorted(
            (round(float(loc["latitude"]), 5), round(float(loc["longitude"]), 5), loc.get("search_radius_km"))
            for loc in (ws.get("_geocoded_locations") or [])
            if loc.get("ui_mode") == "pin_radius" and loc.get("latitude") is not None and loc.get("longitude") is not None
        ),
        # Areas the user carved OUT: a changed set must not serve a cached POI
        # list that was filtered (or not) for a different one.
        sorted(str(a.get("label") or "").strip().lower() for a in (ws.get("_excluded_areas") or [])),
    ))
    def _prune_loc_scratch(names: list) -> None:
        """Drop the whole-set geocode scratch but KEEP the per-name entries for
        names that survived the change.

        The per-name scratch (candidates / tiebreak / pick / asked-beat) is a
        settled answer about ONE name — probing "NYC" again yields the same two
        candidates. Wiping it wholesale when the SET changes re-asks the
        disambiguation the user already answered for every name that stayed
        (add "Newark" at the confirm step → "which NYC did you mean?" again)."""
        _keep = {str(n) for n in (names or [])}
        for _k in ("_loc_candidates", "_loc_tiebreak", "_loc_picks"):
            _d = ws.get(_k)
            if isinstance(_d, dict):
                ws[_k] = {k: v for k, v in _d.items() if k in _keep}
        _asked = ws.get("_disambig_asked")
        if isinstance(_asked, list):
            ws["_disambig_asked"] = [n for n in _asked if n in _keep]
        ws.pop("_geocoded_locations", None)
        ws.pop("_resolved_scope", None)

    if ws.get("_poi_cache_key") != _poi_cache_key:
        for _k in ("_all_pois_cache", "_poi_types_cache", "_arm_pois"):
            ws.pop(_k, None)
        ws["_poi_cache_key"] = _poi_cache_key

    if ws.get("_loc_cache_key") != _loc_cache_key:
        ws.pop("_location_confirmed", None)
        _prune_loc_scratch(location_names)
        ws["_loc_cache_key"] = _loc_cache_key

    # Geocode the current ``location_names`` into ``geocoded_locations``. Honors the
    # ``_geocoded_locations`` cache (replay-safe); a re-geocode after a confirm-step
    # edit pops that cache first (see the confirm loop below) so this re-runs the
    # probe/disambiguate/geocode for the NEW set. Reads/rebinds the enclosing
    # ``location_names`` + ``targeting_type``; appends to ``tool_log`` in place.
    async def _do_geocode() -> list[dict]:
        nonlocal targeting_type, location_names
        if ws.get("_geocoded_locations"):
            targeting_type = ws.get("_resolved_scope") or targeting_type
            return ws["_geocoded_locations"]

        _geo: list[dict] = []
        loc_preview = ", ".join(location_names[:2]) if location_names else "your selected locations"
        if len(location_names) > 2:
            loc_preview += f" +{len(location_names) - 2} more"
        writer({"type": "update", "content": f"Locating {loc_preview} before finding matching audience places..."})
        writer({"type": "thinking", "content": f"Deterministic: geocoding {len(location_names)} locations..."})
        # DETERMINE allow_broad based on targeting_type
        is_broad_targeting = targeting_type in ("country_groups", "admin_areas")

        # ── Geocode-first disambiguation ─────────────────────────────────────
        # A bare name ("Quebec", "New York") can denote several real entities
        # (city vs province vs country). Instead of steering Google with the
        # pre-geocode scope guess, PROBE for every entity the name resolves to,
        # then tiebreak with the LLM (auto-pick at high confidence) or ask the
        # user among ENUMERATED candidates. Street-address-shaped names are not
        # ambiguous in this sense and keep the plain geocode path.
        cand_map: dict = ws.setdefault("_loc_candidates", {})
        _to_probe = [
            n for n in location_names
            if not _looks_like_street_address(n) and n not in cand_map
        ]
        if _to_probe:
            for name, cands in zip(_to_probe, await _gather_bounded(
                [probe_location_candidates(n) for n in _to_probe]
            )):
                cand_map[name] = cands
                writer({"type": "thinking", "content": (
                    f"Location probe: '{name}' → {len(cands)} candidate(s)"
                )})

        picks: dict = ws.setdefault("_loc_picks", {})
        tiebreaks: dict = ws.setdefault("_loc_tiebreak", {})

        for name in location_names:
            cands = cand_map.get(name) or []
            if _looks_like_street_address(name) or not cands:
                # Plain geocode (keeps the Nominatim fallback chain inside the tool).
                result, _log = await call_tool(
                    geocode_location,
                    {"location_name": name, "allow_broad": is_broad_targeting, "scope": targeting_type},
                    writer=writer, node_name="geo_execute_deterministic",
                )
                tool_log.append(_log)
                if result and isinstance(result, dict) and result.get("latitude"):
                    result["_source_name"] = name
                    _geo.append(result)
                continue

            if len(cands) == 1:
                cands[0]["_source_name"] = name
                _geo.append(cands[0])
                continue

            labels = [c.get("label") or c.get("formatted_address") or name for c in cands]
            if name in picks:
                idx = int(picks[name])
            elif (_hint_idx := _pick_candidate_by_hint(
                cands, (ws.get("_loc_hints") or {}).get(name)
            )) is not None:
                # The user picked this place from the confirm widget's search bar, so
                # the entity is already settled — don't re-ask which one they meant.
                idx = _hint_idx
                picks[name] = idx
                writer({"type": "thinking", "content": (
                    f"Disambiguation: '{name}' → {labels[idx]} "
                    "(matched the location you picked, auto-selected)"
                )})
            else:
                tb = tiebreaks.get(name)
                if not isinstance(tb, dict):
                    _idx, _conf = await disambiguate_location_candidates(
                        cands,
                        business_desc=business_desc,
                        det_type=deterministic_type,
                        sibling_locations=[n for n in location_names if n != name],
                        target_audience=target_audience,
                        location_scope=targeting_type,
                    )
                    tb = {"index": _idx, "confidence": _conf}
                    tiebreaks[name] = tb
                # Force the user picker when the name is genuinely ambiguous
                # across scopes (city vs state/province vs country), regardless
                # of LLM confidence — EXCEPT for a purely single-shop run, where a
                # lone physical shop almost always means the city. That exemption
                # dies the moment a MARKET angle is also active: the market name
                # then drives a region search (events/categories in "Quebec"), so
                # guessing city-vs-province would silently search the wrong place.
                _single_shop_only = bool(
                    (subtype_set & _SINGLE_SHOP_DET_TYPES)
                    and not (subtype_set & _MARKET_ANGLES)
                )
                _force_ask = (
                    len(_candidate_scopes(cands)) > 1
                    and not _single_shop_only
                )
                if not _force_ask and float(tb.get("confidence") or 0.0) >= _DISAMBIG_AUTO_CONFIDENCE:
                    idx = int(tb.get("index") or 0)
                    writer({"type": "thinking", "content": (
                        f"Disambiguation: '{name}' → {labels[idx]} "
                        f"(confidence {float(tb['confidence']):.2f}, auto-picked)"
                    )})
                else:
                    # Add the framing beat once per name. On resume the whole act
                    # replays (picks[name] wasn't persisted — interrupt() raised
                    # before L517), so without this guard the beat is re-added and
                    # leaks into the next pause's (geo_location_confirmation) flush.
                    _asked = ws.setdefault("_disambig_asked", [])
                    if name not in _asked:
                        add_beat(state, "framing", {
                            "stage": "geo_disambiguate_location",
                            "name": name,
                            "candidates": labels,
                        }, fallback=f"**{name}** matches more than one place.")
                        _asked.append(name)
                    answer = await wizard_interrupt(
                        writer,
                        step_key="geo_disambiguate_location",
                        context=f"'{name}' matched {len(cands)} distinct places",
                        state=state,
                        prompt_override=(
                            f"“{name}” matches more than one place — which one do you mean?"
                        ),
                        options_override=labels,
                        skip_ask=True,
                        progress=_build_geo_progress(ws),
                    )
                    # Any OTHER field the user changed in the same breath. Parked for
                    # builder_plan; before this, an edit typed at this step was acked and
                    # then dropped — the exact false-acknowledgment bug, at a site that was
                    # never wired.
                    stash_edits(ws, answer)
                    if not getattr(answer, "answered", True):
                        # Not a pick (an edit / question) — never default to
                        # candidate 0; re-ask after builder_plan applies edits.
                        raise _GeoStepPaused()
                    resolved = resolve_option(str(answer).strip(), labels)
                    idx = labels.index(resolved) if resolved in labels else 0
                    # This resolved from a genuine wizard_interrupt() call
                    # (the auto-picked/hint/cache-hit branches above never
                    # reach here) — persist it and stop NOW, before any later
                    # name in this loop (or geo_location_confirmation right
                    # after it) can reach a SECOND interrupt() in this same
                    # task. See _GeoStepPaused's docstring.
                    picks[name] = idx
                    raise _GeoStepPaused()
                picks[name] = idx
            if 0 <= idx < len(cands):
                cands[idx]["_source_name"] = name
                _geo.append(cands[idx])

        # Geocode-first scope correction: the winners' place types are ground
        # truth. A province winner under a granular_local guess flips the scope
        # (drops the locality filter, labels the run correctly); builder_act
        # syncs ws["_resolved_scope"] back into the filled slots + user_info.
        _derive_resolved_scope(ws, _geo, targeting_type, writer)
        targeting_type = ws.get("_resolved_scope") or targeting_type
        # Boundary vs pin+radius per location (country/state keep the
        # political shape; city/town/metro become a search ring) — see
        # _stamp_location_radius_mode's docstring.
        for _loc in _geo:
            _stamp_location_radius_mode(_loc, ws)
        ws["_geocoded_locations"] = _geo
        return _geo

    def _apply_pin_fallback(geo: list[dict]) -> list[dict]:
        """When geocoding yields nothing but a dropped pin exists, synthesize a
        single pin location so downstream POI search still has a center."""
        if not geo and extra_inputs.get("lat") and extra_inputs.get("lng"):
            geo = [{
                "latitude": extra_inputs["lat"],
                "longitude": extra_inputs["lng"],
                "location_name": "Selected location",
                "is_city": False,
            }]
            _stamp_location_radius_mode(geo[0], ws)
            # The standalone "drop a pin" flow's own radius answer is the
            # authoritative ring here (the user picked it directly via
            # geo_collect_radius_km) — prefer it over the generic
            # bounds-derived default, which has no bounds to derive from
            # for a raw pin anyway (falls back to the flat default).
            if _pin_search_radius_km:
                geo[0]["search_radius_km"] = _pin_search_radius_km
            ws["_geocoded_locations"] = geo
        return geo

    def _norm_locs(xs: list) -> list[str]:
        return sorted(str(x).strip().lower() for x in (xs or []) if str(x).strip())

    def _with_manual_pins(geo: list[dict]) -> list[dict]:
        """Re-append persisted manual pins (see ``_new_manual_pin``) after a
        (re-)geocode. Manual pins live outside ``location_names`` entirely —
        `_do_geocode` never sees them — so a fresh geocode call would
        otherwise silently drop whatever the user dropped on the map."""
        pins = ws.get("_manual_pins") or []
        return geo + [p for p in pins if p not in geo]

    geocoded_locations = _with_manual_pins(_apply_pin_fallback(await _do_geocode()))
    # Geocoding may have corrected the scope (a province winner under a city
    # guess); the chips should show what was actually resolved.
    ws["targeting_type"] = targeting_type

    def _locs_for(token: str) -> list[dict]:
        """Geocoded locations THIS angle should search. With no per-angle specs every
        angle gets the full set (legacy). With specs, filter to the angle's own names
        (tagged ``_source_name`` at geocode time); fall back to the full set if the
        tag match yields nothing (robustness — never search an empty market)."""
        if not _spec_by_angle:
            return geocoded_locations
        _want = {n.strip().lower() for n in angle_names.get(token, _shared_names) if n and n.strip()}
        if not _want:
            return geocoded_locations
        _subset = [
            loc for loc in geocoded_locations
            if str(loc.get("_source_name", "")).strip().lower() in _want
        ]
        return _subset or geocoded_locations

    async def _apply_location_edit(new_names: list) -> None:
        """Adopt an edited location set at the confirm step and re-geocode it.

        Shared by the two ways a user can change the set at that step — a typed
        edit (routed here via ``rerun_on_edit`` → ``_result.edits``) and the confirm
        widget's own search bar (a JSON add/remove delta) — so both land on
        identical state. Rebinds the enclosing ``location_names`` / ``angle_names``
        / ``geocoded_locations``.
        """
        nonlocal location_names, angle_names, geocoded_locations
        _stash_widget_undo(ws, _LOC_UNDO_KEYS)
        _was = {_al_norm(n) for n in location_names}
        location_names = [str(x) for x in new_names]
        # Rebind EVERY angle to the edited set. `angle_names` was frozen
        # from `geo_angle_specs` before the confirm loop, so without this the
        # per-angle filter in `_locs_for` still holds the pre-edit names:
        # locations added at the confirm step get geocoded, mapped, and
        # counted — then dropped before the POI search. The confirm UI
        # edits ONE flat location list, so a removed place leaves every angle
        # and an added one joins every angle — but an angle pinned to its own
        # cities ("events only in Montreal") keeps the rest of its list.
        _now = {_al_norm(n) for n in location_names}
        _added = [n for n in location_names if _al_norm(n) not in _was]

        def _rebind(names: list) -> list:
            kept = [n for n in names if _al_norm(n) in _now]
            return _al_dedupe(kept + _added) or list(location_names)

        angle_names = {_tok: _rebind(_names) for _tok, _names in angle_names.items()}
        # Persist the rebind so it survives a _GeoStepPaused round trip: this
        # confirm loop no longer necessarily reaches the POI search in the
        # SAME call (see _GeoStepPaused) — a fresh re-entry rebuilds
        # angle_names from extra_inputs["angle_specs"] alone (below) and
        # would silently drop this edit's added/removed names back to
        # whatever a per-angle spec originally pinned. Read by that same
        # build site, once, before any spec is consulted.
        ws["_angle_names_synced"] = dict(angle_names)
        ws["_locations_synced"] = list(location_names)
        # Refresh the mismatch-detection key to match what a fresh re-entry
        # will compute from these same synced values — otherwise the
        # "inputs changed since last time" check just below (this function's
        # OWN caller, at the top of the next call) sees the edit as a NEW,
        # unconfirmed change and pops _location_confirmed / re-asks, even
        # though this exact edit is the one just confirmed.
        ws["_loc_cache_key"] = _compute_loc_cache_key()
        # Keep the progress chips in step with the edited set.
        ws["location_names"] = list(location_names)
        # Invalidate the set-wide geocode scratch so the new set is probed +
        # geocoded and a fresh confirm map emits. Per-name scratch for names
        # that survived the edit is kept (see `_prune_loc_scratch`) — adding a
        # location must not re-ask a disambiguation already answered.
        # `_loc_hints` is deliberately NOT cleared — it is the widget's
        # place identity for the names about to be re-probed.
        _prune_loc_scratch(location_names)
        writer({"type": "thinking", "content": (
            f"Geo location edit at confirm: re-geocoding {location_names}"
        )})
        geocoded_locations = _with_manual_pins(_apply_pin_fallback(await _do_geocode()))

    if geocoded_locations:
        if subtype_set & {"ai_suggested", "category", "competitor_brand", "named_places", "event_based"}:
            # Re-geocode loop: an edit at the confirm step (add/remove/replace a
            # location) breaks wizard_interrupt via ``rerun_on_edit``, returning
            # the merged set. We re-geocode it, re-emit a FRESH confirm_locations
            # map, and re-interrupt — so the widget and map never drift apart.
            while not ws.get("_location_confirmed"):
                loc_preview = ", ".join(
                    _confirm_label(loc) for loc in geocoded_locations[:3]
                )
                if len(geocoded_locations) > 3:
                    loc_preview += f" +{len(geocoded_locations) - 3} more"
                # The confirm map rides `repeat_events` (below) instead of being
                # written once here: wizard_interrupt re-asks IN PLACE on the
                # off-path lanes (reject / query / an edit to some other field)
                # without returning, so a once-only emission left those re-asks
                # showing the confirm widget with no map to confirm.
                _confirm_map_event = {"type": "map_data", "content": {
                    "action_type": "confirm_locations",
                    "locations": geocoded_locations,
                    "editable": True,
                    "excluded_areas": excluded_areas_payload(ws),
                }}
                _narrative = (
                    f"Targeting **{_confirm_label(geocoded_locations[0])}**."
                    if len(geocoded_locations) == 1 else
                    f"Targeting **{loc_preview}**."
                )
                _confirm_prompt = (
                    "Is this the right location?" if len(geocoded_locations) == 1 else "Are these the right locations?"
                )
                add_beat(state, "framing", {
                    "stage": "geo_location_confirm",
                    "locations": [_confirm_label(g) for g in geocoded_locations],
                    "location_count": len(geocoded_locations),
                    "targeting_type": deterministic_type,
                }, fallback=_narrative)
                _result = await wizard_interrupt(
                    writer,
                    step_key="geo_location_confirmation",
                    context=f"{deterministic_type} targeting, {len(geocoded_locations)} location(s) geocoded",
                    state=state,
                    prompt_override=_confirm_prompt,
                    skip_ask=True,
                    progress=_build_geo_progress(ws),
                    # A typed search-circle radius returns here too — the map on
                    # screen is what it changes. It is stashed (not excluded
                    # below) and applied by builder_plan → set_search_ring.
                    rerun_on_edit={"geo_locations", "location", "search_radius_km", "geo_radius_km"},
                    edit_base={
                        "geo_locations": list(location_names),
                        "location": list(location_names),
                    },
                    repeat_events=[_confirm_map_event],
                )
                # ── Confirm-widget delta lane ────────────────────────────────
                # The widget's own search bar submits the POI-confirm payload shape
                # ({"confirm":.., "added":[..], "removed":[..]}) rather than prose.
                # That string reaches us as a plain answer — `is_sentinel_resume`
                # short-circuits any JSON to the confirm lane before the classifier
                # runs, so `_result.edits` is always empty for it and the delta would
                # otherwise be confirmed away unread. Parse it here, the same way the
                # poi_confirm gate parses its own gate string.
                # Any OTHER field the user changed in the same breath. Parked for
                # builder_plan; before this it was acked and dropped.
                stash_edits(ws, _result, exclude=("geo_locations", "location"))
                _delta = _parse_location_delta(_result)
                if _delta is not None:
                    if _delta.get("confirm") is False:
                        # Rejected — a genuine wizard_interrupt() call just
                        # resolved (with "no"). Stop this task now rather than
                        # loop back into a SECOND interrupt() call for the
                        # re-ask; a fresh geo_discover dispatch re-enters this
                        # same while loop and asks it again as the first
                        # interrupt of its own task. See _GeoStepPaused.
                        raise _GeoStepPaused()
                    # Split "added" into named picks (re-geocoded below, as
                    # before) vs. a raw map-dropped pin (the "drop pin"
                    # toggle) — carries lat/lng but no name, so it skips
                    # geocoding entirely and becomes a manual pin instead.
                    _stash_widget_undo(ws, _LOC_UNDO_KEYS)
                    _raw_added = _delta.get("added") or []
                    _manual_items = [
                        a for a in _raw_added
                        if isinstance(a, dict) and not str(a.get("name") or "").strip()
                        and (a.get("lat") is not None or a.get("latitude") is not None)
                    ]
                    _named_delta = {**_delta, "added": [a for a in _raw_added if a not in _manual_items]}
                    _pins_changed = _remove_manual_pins(geocoded_locations, ws, _delta.get("removed"))
                    for _mi in _manual_items:
                        _pin = await _new_manual_pin(_mi, ws)
                        if _pin:
                            ws.setdefault("_manual_pins", []).append(_pin)
                            geocoded_locations.append(_pin)
                            _pins_changed = True
                    # Pin+radius drag/resize on an EXISTING location — no
                    # name-list change, just a coordinate/radius patch (or a
                    # demotion when the center moved). See
                    # _apply_location_updates's docstring.
                    if await _apply_location_updates(geocoded_locations, _delta.get("updated"), ws):
                        _pins_changed = True
                    _merged, _hints = _loc_delta_to_names(
                        _named_delta, location_names, geocoded_locations
                    )
                    if not _merged and not ws.get("_manual_pins"):
                        # Empty NAMED set and no manual pin left to carry the
                        # search — a truly empty target, re-ask. (A manual pin
                        # is never in `_merged` — it lives outside
                        # `location_names` entirely — so its mere presence,
                        # not `geocoded_locations`'s still-stale pre-edit
                        # contents, is what decides "empty" here.)
                        writer({"type": "thinking", "content": (
                            "Location delta would empty the target set — re-asking"
                        )})
                        raise _GeoStepPaused()
                    if _norm_locs(_merged) != _norm_locs(location_names):
                        # Carry the picked place's identity into the re-probe so an
                        # ambiguous bare name ("Bastrop" = city AND county) resolves
                        # to what the user actually clicked instead of re-asking.
                        ws.setdefault("_loc_hints", {}).update(_hints)
                        await _apply_location_edit(_merged)
                        if not geocoded_locations:
                            break  # nothing resolved — same exit the typed lane takes
                        writer({"type": "update", "content": (
                            "Updated targeting: " + ", ".join(
                                _confirm_label(loc) for loc in geocoded_locations
                            )
                        )})
                    elif _pins_changed:
                        # A manual-pin add/remove or a radius/center edit with
                        # no name-list change — _apply_location_edit (which
                        # persists geocoded_locations itself) never ran, so
                        # persist here instead.
                        ws["_geocoded_locations"] = list(geocoded_locations)
                        writer({"type": "update", "content": (
                            "Updated targeting: " + ", ".join(
                                _confirm_label(loc) for loc in geocoded_locations
                            )
                        )})
                    # Apply and advance: the pick was explicit and structured, so it
                    # needs no second confirm round (unlike a typed edit below).
                    ws["_location_confirmed"] = True
                    # Just resolved from a genuine wizard_interrupt() call —
                    # stop NOW, before the next phase's own interrupt() can
                    # land in this same task. See _GeoStepPaused's docstring.
                    raise _GeoStepPaused()

                _edited = None
                _result_edits = getattr(_result, "edits", None) or {}
                for _key in ("geo_locations", "location"):
                    _v = _result_edits.get(_key)
                    # Defensive: `_apply_location_edit` and `_norm_locs` both
                    # iterate this as a collection of location names. A
                    # cross-step REPLACE edit is normally already list-wrapped
                    # (wizard_helpers._dispatch_edit_intent), but a bare
                    # string reaching here unwrapped would otherwise explode
                    # into its CHARACTERS, each geocoded as its own bogus
                    # location — guard the actual consumer, not just the one
                    # place that populates it.
                    if _v is not None and not isinstance(_v, list):
                        _v = [_v]
                    if _v is not None and _norm_locs(_v) != _norm_locs(location_names):
                        _edited = _v
                        break
                if _edited:
                    await _apply_location_edit(_edited)
                    if not geocoded_locations:
                        break
                    # Same reasoning as the reject lane above — the edit came
                    # from a resolved wizard_interrupt() call; re-showing the
                    # fresh confirm map happens on a NEW task, not in this one.
                    raise _GeoStepPaused()
                if _result_edits.get("search_radius_km") is not None or _result_edits.get("geo_radius_km") is not None:
                    # Typed circle radius: NOT a confirmation. Leave
                    # `_location_confirmed` unset so the re-dispatch re-shows
                    # the map with the resized circle for the user to confirm.
                    raise _GeoStepPaused()
                if not getattr(_result, "answered", True):
                    # Any other non-answer (a budget edit, a question, a reject)
                    # is NOT a confirmation of these locations. Its edits are
                    # stashed above; re-ask after builder_plan applies them.
                    raise _GeoStepPaused()
                ws["_location_confirmed"] = True
                # Same reasoning as the structured-delta branch above.
                raise _GeoStepPaused()

    if ws.get("_all_pois_cache"):
        all_pois = ws["_all_pois_cache"]
        poi_types = ws.get("_poi_types_cache", poi_types)
        writer({"type": "thinking", "content": "Deterministic: POI cache hit, skipping API calls"})
    else:
        # Polygon-PRIMARY filtering: fetch each named city/region's TRUE polygon and,
        # when present, let it supersede the locality/state/country name filters
        # (exact geometry excludes cross-city/state/border bleed the names only
        # approximate — Montreal's shape drops Laval, NYC's drops NJ). Cached +
        # throttled (Nominatim ~1 req/s). A miss (no OSM polygon / pinpoint / disabled)
        # leaves the entry empty → the name filters still apply (no regression).
        loc_polygons: dict[int, list] = {}
        if settings.GEO_REGION_POLYGON_FILTER and (subtype_set & {
            "ai_suggested", "category", "competitor_brand", "named_places", "event_based"
        }) and targeting_type in ("granular_local", "admin_areas"):
            for loc in geocoded_locations:
                if not loc.get("bounds"):
                    continue
                # pin_radius mode (city/town/metro confirm, or a manual/demoted
                # pin) searches a hard ring the user explicitly sized — often
                # wider than the political place. Imposing the real polygon on
                # top of that would silently re-narrow back to the boundary
                # the user asked to move away from.
                if loc.get("ui_mode") == "pin_radius":
                    continue
                # Attempt an OSM polygon for EVERY place type. True pinpoints
                # (street_address/premise) simply miss on Nominatim and fall back to
                # the bbox/name filters; a neighbourhood/city/region that HAS a polygon
                # gets its real shape (the padded Google viewport a neighbourhood
                # resolves to otherwise leaks adjacent-area POIs).
                _poly = await _region_polygon_cached(
                    loc.get("formatted_address") or loc.get("location_name") or "",
                    place_id=loc.get("place_id"),
                    place_type=loc.get("place_type"),
                    expected_bounds=loc.get("bounds"),
                    # Google's resolved administrative components drive a STRUCTURED
                    # OSM lookup, which constrains the entity KIND rather than just
                    # the ranking — free text asks OSM to re-guess which "Mount
                    # Royal" we meant, and it answers with the mountain.
                    components={
                        "city": loc.get("locality") or "",
                        "state": loc.get("admin_area1_name") or "",
                        "country": loc.get("country_name") or "",
                    },
                )
                if _poly:
                    loc_polygons[id(loc)] = _poly
                    writer({"type": "thinking", "content": (
                        f"Region polygon (primary) for '{_confirm_label(loc)}' "
                        f"({sum(len(r) for r in _poly)} verts) — name filters bypassed"
                    )})

        # ── Event search plumbing ─────────────────────────────────────────────
        # One resolved window per date phrase (cached in ws — a resume never
        # re-asks the LLM) and one args builder, so the event arm and the
        # named-place→event cross-check search under identical, verified rules:
        # concrete ISO window, and the target area the venue must sit inside.
        _event_windows: dict = ws.setdefault("_event_windows", {})

        async def _event_window_for(date_range: str) -> tuple[str, str]:
            if date_range not in _event_windows:
                # Our own default label is already a known window — no LLM call.
                lo, hi = await resolve_event_window(
                    "" if date_range == _default_past_event_window() else date_range
                )
                _event_windows[date_range] = [lo.isoformat(), hi.isoformat()]
            start, end = _event_windows[date_range]
            return start, end

        def _event_args(loc: dict, query: str, date_range: str, window: tuple[str, str]) -> dict:
            _bnd, _ = _search_geometry_for(loc, _pin_search_radius_km)
            return {
                "city": loc.get("location_name", ""), "event_query": query,
                "date_range": date_range, "parent_label": _confirm_label(loc),
                "window_start": window[0], "window_end": window[1],
                "bounds": _bnd, "region_polygon": loc_polygons.get(id(loc)),
                "latitude": loc.get("latitude"), "longitude": loc.get("longitude"),
            }

        def _report_event_rejections(results: list) -> None:
            """One honest line for what verification dropped — never silent."""
            reasons: dict[str, int] = {}
            for r in results:
                for rej in (r or {}).get("rejected", []) if isinstance(r, dict) else []:
                    reasons[rej["reason"]] = reasons.get(rej["reason"], 0) + 1
            if reasons:
                parts = ", ".join(
                    f"{n} {_EVENT_REJECT_LABELS.get(k, k)}" for k, n in sorted(reasons.items())
                )
                writer({"type": "update", "content": f"Skipped unverified events: {parts}."})

        # ── Event↔place cross-check ───────────────────────────────────────────
        # The angle is chosen by the extractor from linguistic cues alone, and it
        # never sees live data. brand-vs-POI survives a wrong guess because
        # `resolve_named_target` re-decides from the Places result shape; events
        # had no such partner, so "Fight Club" read as an event searched for a
        # festival, found none, and (on a pure event run) aborted the whole
        # builder with `geo_targeting_unresolved` — a generic message that never
        # named the target. These two helpers close that loop: on a MISS only,
        # retry the target as the OTHER kind before calling it not-found. No
        # extra cost on the happy path, and `deterministic_subtype` is never
        # mutated — event dates ride per-POI, so adopted POIs route themselves
        # (see the non-event lookback merge in executors/maid.py).

        async def _crosscheck_as_place(query: str, source_angle: str = "event_based") -> bool:
            """An event query that found no venues → maybe it was never an event.
            Retry it as a named place. True when POIs were adopted.

            A GENERIC event query ("music festivals") must not reach Places as a
            venue name — it would pin whatever dominant match came back. Only a
            proper-noun-looking query crosses over. `ambiguous` is treated as a
            miss rather than an ask: the user said "event", so offering a list of
            venues to pick from would be incoherent."""
            if _is_category_like_name(
                query, _EVENT_CATEGORY_NOUNS, _EVENT_CATEGORY_MODIFIERS
            ):
                return False
            _cache: dict = ws.setdefault("_event_crosscheck", {})
            _adopted = False
            for loc in geocoded_locations:
                city = loc.get("location_name", "")
                key = f"{query}@@{city}"
                res = _cache.get(key)
                if res is None:
                    _bnd, _srk = _search_geometry_for(loc, _pin_search_radius_km)
                    res = await resolve_named_target(
                        query, city,
                        latitude=loc.get("latitude"), longitude=loc.get("longitude"),
                        hint="specific",
                        search_radius_km=_srk,
                        target_radius_km=poi_radius_km,
                        bounds=_bnd,
                        locality_filter=_locality_filter_for(loc, targeting_type),
                        country_filter=_country_filter_for(loc, targeting_type),
                        state_filter=_state_filter_for(loc, targeting_type),
                        region_polygon=loc_polygons.get(id(loc)),
                        parent_label=_confirm_label(loc),
                    )
                    _cache[key] = res
                    tool_log.append({
                        "tool": "resolve_named_target", "status": "ok",
                        "args": {"name": query, "city": city, "hint": "specific",
                                 "via": "event_crosscheck"},
                        "result_summary": f"{res['kind']} ({len(res['pois'])} pois)",
                    })
                if res.get("kind") in ("brand", "single"):
                    all_pois.extend(
                        {**p, "parent_poi_type": query, "source_angle": source_angle}
                        for p in res["pois"]
                    )
                    _adopted = True
                    writer({"type": "thinking", "content": (
                        f"'{query}' found no events in {city} but resolved as a "
                        f"place ({res['kind']}) — targeting it as a venue"
                    )})
            return _adopted

        async def _crosscheck_as_event(name: str, source_angle: str = "named_places") -> bool:
            """A named place that resolved to nothing → maybe it was an event all
            along ("Osheaga"). Retry it as an event search. True when POIs were
            adopted; those carry their event dates, which drive the MAID window.

            Callers gate on hint="specific": a `competitor_brand` miss ("all
            Starbucks") must never become an event search."""
            _cache: dict = ws.setdefault("_place_crosscheck", {})
            _window = _default_past_event_window()
            _win = await _event_window_for(_window)
            _adopted = False
            for loc in geocoded_locations:
                city = loc.get("location_name", "")
                key = f"{name}@@{city}"
                res = _cache.get(key)
                if res is None:
                    res, _log = await call_tool(
                        search_events, _event_args(loc, name, _window, _win),
                        writer=writer, node_name="geo_execute_deterministic",
                    )
                    res = res if isinstance(res, dict) else {}
                    _cache[key] = res
                    tool_log.append(_log)
                _pois = res.get("targetable_poi_coordinates") or []
                if _pois:
                    all_pois.extend(
                        {**p, "parent_poi_type": name, "source_angle": source_angle}
                        for p in _pois
                    )
                    _adopted = True
                    writer({"type": "thinking", "content": (
                        f"'{name}' matched no place in {city} but resolved as an "
                        f"event ({len(_pois)} venue(s)) — targeting the event"
                    )})
            return _adopted

        async def _resolve_and_collect(
            names: list[str], hint: str, source_angle: str,
            locs: list[dict] | None = None, scope: str | None = None,
        ) -> None:
            """Grounded resolution for a list of named targets. For each name ×
            location, ``resolve_named_target`` classifies from LIVE Places results
            (brand → all outlets, single → that spot, ambiguous → ask, notfound →
            web fallback). Results cache in ws (replay-safe: no re-search / no
            re-ask on resume). Appends resolved POIs into the shared ``all_pois``
            tagged ``parent_poi_type = name``. ``locs`` restricts the search to this
            angle's own markets (per-angle specs); None → every geocoded location."""
            _resolved: dict = ws.setdefault("_named_resolved", {})
            _picks: dict = ws.setdefault("_named_picks", {})
            _asked: list = ws.setdefault("_named_disambig_asked", [])
            _missing: list[str] = []
            _locs = locs if locs is not None else geocoded_locations
            _scope = scope or targeting_type
            for name in names:
                _found = False
                for loc in _locs:
                    city = loc.get("location_name", "")
                    key = f"{name}@@{city}"
                    res = _resolved.get(key)
                    if res is None:
                        _bnd, _srk = _search_geometry_for(loc, _pin_search_radius_km)
                        res = await resolve_named_target(
                            name, city,
                            latitude=loc.get("latitude"), longitude=loc.get("longitude"),
                            hint=hint,
                            search_radius_km=_srk,
                            target_radius_km=poi_radius_km,
                            bounds=_bnd,
                            locality_filter=_locality_filter_for(loc, _scope),
                            country_filter=_country_filter_for(loc, _scope),
                            state_filter=_state_filter_for(loc, _scope),
                            region_polygon=loc_polygons.get(id(loc)),
                            parent_label=_confirm_label(loc),
                        )
                        _resolved[key] = res
                        tool_log.append({
                            "tool": "resolve_named_target", "status": "ok",
                            "args": {"name": name, "city": city, "hint": hint},
                            "result_summary": f"{res['kind']} ({len(res['pois'])} pois)",
                        })
                        writer({"type": "thinking", "content": (
                            f"Resolved '{name}' in {city} → {res['kind']}"
                        )})
                    kind = res.get("kind")
                    if kind in ("brand", "single"):
                        all_pois.extend(
                            {**p, "parent_poi_type": name, "source_angle": source_angle}
                            for p in res["pois"]
                        )
                        _found = True
                    elif kind == "ambiguous":
                        cands = res.get("candidates") or []
                        labels = [
                            (f"{c['name']} — {c.get('formatted_address')}"
                             if c.get("formatted_address") else c["name"])
                            for c in cands
                        ]
                        if key in _picks:
                            idx = int(_picks[key])
                        else:
                            if key not in _asked:
                                add_beat(state, "framing", {
                                    "stage": "geo_disambiguate_named_place",
                                    "name": name, "candidates": labels,
                                }, fallback=f"**{name}** matches more than one place.")
                                _asked.append(key)
                            answer = await wizard_interrupt(
                                writer,
                                step_key="geo_disambiguate_named_place",
                                context=f"'{name}' matched {len(cands)} distinct places",
                                state=state,
                                prompt_override=(
                                    f"“{name}” matches more than one place — which one do you mean?"
                                ),
                                options_override=labels,
                                skip_ask=True,
                                progress=_build_geo_progress(ws),
                            )
                            # Any OTHER field the user changed in the same breath. Parked for
                            # builder_plan; before this it was acked and dropped.
                            stash_edits(ws, answer)
                            if not getattr(answer, "answered", True):
                                # Not a pick — never default to candidate 0.
                                raise _GeoStepPaused()
                            _resolved_lbl = resolve_option(str(answer).strip(), labels)
                            idx = labels.index(_resolved_lbl) if _resolved_lbl in labels else 0
                            _picks[key] = idx
                            # Just resolved from a genuine wizard_interrupt()
                            # call — stop this task now, same reasoning as
                            # geo_disambiguate_location. See _GeoStepPaused.
                            raise _GeoStepPaused()
                        if 0 <= idx < len(cands):
                            all_pois.append({**cands[idx], "parent_poi_type": name, "source_angle": source_angle})
                            _found = True
                if not _found:
                    # Nothing matched as a place. Before calling it missing, retry
                    # as an EVENT — the extractor may have read a festival name as
                    # a venue. Only for hint="specific" (a `competitor_brand` miss
                    # must not become an event search) and only for a proper name.
                    if hint == "specific" and not _is_category_like_name(name):
                        _found = await _crosscheck_as_event(name, source_angle)
                if not _found:
                    _missing.append(name)
            if _missing:
                ws["_det_named_not_found"] = sorted(set(
                    (ws.get("_det_named_not_found") or []) + _missing
                ))
                writer({"type": "update", "content": (
                    f"Couldn't find: {', '.join(_missing)} — check the spelling or add a city/area."
                )})

        if "ai_suggested" in subtype_set:
            writer({"type": "update", "content": "Choosing place categories that match your business and audience intent..."})
            writer({"type": "thinking", "content": "Deterministic: getting AI-suggested POI types..."})
            result, _log = await call_tool(
                get_dynamic_place_types, {"business_context": poi_context},
                writer=writer, node_name="geo_execute_deterministic",
            )
            tool_log.append(_log)
            # Local to this arm — do NOT overwrite the shared `poi_types` (that
            # forced a following `category` arm to re-search these AI types).
            ai_types = result if result else ["retail store", "shopping mall"]
            collected_types.extend(ai_types)
            writer({"type": "thinking", "content": f"AI suggested POI types: {ai_types}"})
            _ai_locs = _locs_for("ai_suggested")
            _ai_scope = _scope_for("ai_suggested")
            writer({"type": "update", "content": f"Finding {len(ai_types)} place type(s) across {len(_ai_locs)} area(s)..."})
            _pt_order: list[str] = []
            _coros = []
            for loc in _ai_locs:
                city = loc.get("location_name", "")
                _loc_filter = _locality_filter_for(loc, _ai_scope)
                _country_filter = _country_filter_for(loc, _ai_scope)
                _state_filter = _state_filter_for(loc, _ai_scope)
                _bnd, _srk = _search_geometry_for(loc, _pin_search_radius_km)
                for pt in ai_types:
                    _pt_order.append(pt)
                    _coros.append(call_tool(
                        search_pois_by_type, {
                            "poi_type": pt, "city_name": city,
                            "latitude": loc.get("latitude"), "longitude": loc.get("longitude"),
                            "bounds": _bnd,
                            "search_radius_km": _srk,
                            "locality_filter": _loc_filter,
                            "country_filter": _country_filter,
                            "state_filter": _state_filter,
                            "region_polygon": loc_polygons.get(id(loc)),
                            "parent_label": _confirm_label(loc),
                        },
                        writer=writer, node_name="geo_execute_deterministic",
                    ))
            for pt, (result, _log) in zip(_pt_order, await _gather_bounded(_coros)):
                tool_log.append(_log)
                if result and isinstance(result, dict):
                    all_pois.extend(
                        {**p, "parent_poi_type": pt, "source_angle": "ai_suggested"}
                        for p in result.get("targetable_poi_coordinates", [])
                    )

        async def _search_types_across(types: list[str], angle: str) -> None:
            """Search each place type across every location `angle` targets — the
            market-wide counterpart to the anchor-ring search in the
            competitor_nearby arm. Appends to the shared `all_pois`, tagging each POI
            with `angle` so the reveal breakdown keeps combined angles apart."""
            _locs = _locs_for(angle)
            _scope = _scope_for(angle)
            # Per-arm replay cache. The named-place disambiguation further down
            # pauses the act mid-fan-out, and the shared `_all_pois_cache` is only
            # written once EVERY arm has run — so on a combo (category +
            # named_places) each pause re-searched Places for the arms that had
            # already finished. Keyed by what the search depends on, so it
            # self-invalidates when the angle's types or markets change.
            _arm_cache: dict = ws.setdefault("_arm_pois", {})
            _arm_key = repr((
                angle, sorted(types), _scope, _pin_search_radius_km,
                # Per-location search radius (pin_radius mode) is part of
                # WHAT gets searched — a radius nudge on the confirm map must
                # bust this arm's cache same as a location/type change would.
                [(l.get("latitude"), l.get("longitude"), l.get("search_radius_km")) for l in _locs],
            ))
            if _arm_key in _arm_cache:
                all_pois.extend(_arm_cache[_arm_key])
                writer({"type": "thinking", "content": (
                    f"Deterministic: {angle} POI cache hit, skipping API calls"
                )})
                return
            _arm_start = len(all_pois)
            _pt_order = []
            _coros = []
            for loc in _locs:
                city = loc.get("location_name", "")
                _loc_filter = _locality_filter_for(loc, _scope)
                _country_filter = _country_filter_for(loc, _scope)
                _state_filter = _state_filter_for(loc, _scope)
                _bnd, _srk = _search_geometry_for(loc, _pin_search_radius_km)
                for pt in types:
                    _pt_order.append(pt)
                    _coros.append(call_tool(
                        search_pois_by_type, {
                            "poi_type": pt, "city_name": city,
                            "latitude": loc.get("latitude"), "longitude": loc.get("longitude"),
                            "bounds": _bnd,
                            "search_radius_km": _srk,
                            "locality_filter": _loc_filter,
                            "country_filter": _country_filter,
                            "state_filter": _state_filter,
                            "region_polygon": loc_polygons.get(id(loc)),
                            "parent_label": _confirm_label(loc),
                        },
                        writer=writer, node_name="geo_execute_deterministic",
                    ))
            for pt, (result, _log) in zip(_pt_order, await _gather_bounded(_coros)):
                tool_log.append(_log)
                if result and isinstance(result, dict):
                    all_pois.extend(
                        {**p, "parent_poi_type": pt, "source_angle": angle}
                        for p in result.get("targetable_poi_coordinates", [])
                    )
            _arm_cache[_arm_key] = all_pois[_arm_start:]

        if "category" in subtype_set:
            _cat_types = _types_for("category", "poi_types", poi_types)
            collected_types.extend(_cat_types)
            writer({"type": "update", "content": f"Finding {len(_cat_types)} place type(s) across {len(_locs_for('category'))} area(s)..."})
            await _search_types_across(_cat_types, "category")

        if "store_set" in subtype_set:
            _store_addrs = list(extra_inputs.get("store_addresses_list", []))

            # Hoisted out of _do_geocode_stores: the confirm prompt below names
            # this market when an address resolves outside it.
            _store_location_hint = market_hint(location_names)

            async def _do_geocode_stores(addrs: list[str]) -> list[dict]:
                """Geocode store addresses into map-ready dicts. Honors the
                ``_geocoded_stores`` cache (replay-safe); a confirm-step edit pops
                it first so the new address set re-geocodes."""
                if ws.get("_geocoded_stores"):
                    return ws["_geocoded_stores"]
                writer({"type": "update", "content": f"Geocoding {len(addrs)} business address(es) so we can map your own locations..."})
                _stores: list[dict] = []
                _store_coros = [
                    call_tool(
                        geocode_or_place,
                        {"location_name": addr, "market_hint": _store_location_hint},
                        writer=writer, node_name="geo_execute_deterministic",
                    )
                    for addr in addrs
                ]
                for addr, (result, _log) in zip(addrs, await _gather_bounded(_store_coros)):
                    tool_log.append(_log)
                    if isinstance(result, dict) and result.get("latitude"):
                        _stores.append({
                            # The RESOLVED name, not the typed string — Places
                            # answers first now, so this is Google's own label
                            # ("SKS Tower"), not "its in SKS tower in mohakhali".
                            "name": result.get("location_name") or addr,
                            "market_mismatch": result.get("market_mismatch", ""),
                            "lat": result.get("latitude"),
                            "lng": result.get("longitude"),
                            "is_city": result.get("is_city", False),
                            "radius_km": poi_radius_km,
                            # Resolved address, not the raw typed one — same rule as
                            # every other arm (see _confirm_label). Falls back to the
                            # typed string when the geocoder returned no formatted form.
                            "parent_location": result.get("formatted_address") or addr,
                            "postal_code": result.get("postal_code", ""),
                            "country_code": result.get("country_code", ""),
                        })
                ws["_geocoded_stores"] = _stores
                return _stores

            geocoded_stores = await _do_geocode_stores(_store_addrs)
            # Re-geocode loop mirrors the location confirm: an edit to the store
            # address set at the confirm step re-geocodes + re-emits a fresh map.
            while not ws.get("_store_confirmed"):
                # No address resolved (even Places missed) → skip the map and ask for
                # a full street address rather than emitting a hollow, mapless confirm.
                # Rides `repeat_events` so an off-path re-ask (reject / query /
                # unrelated edit) re-renders the widget WITH its map — see the
                # location confirm above.
                _store_map_events = [{"type": "map_data", "content": {
                    "action_type": "confirm_locations",
                    "locations": geocoded_stores,
                    "editable": True,
                }}] if geocoded_stores else []
                _store_narrative = (
                    "I couldn't pinpoint that location."
                    if not geocoded_stores else
                    f"Targeting your business at **{geocoded_stores[0].get('name', 'this location')}**."
                    if len(geocoded_stores) == 1 else
                    f"Targeting **{len(geocoded_stores)} business locations**."
                )
                # An address that resolved OUTSIDE the market the user named is
                # surfaced here, never rejected — a shop abroad from the stated
                # market is legitimate, and only the user can say which it is.
                _mismatch = next(
                    (s["market_mismatch"] for s in geocoded_stores if s.get("market_mismatch")),
                    "",
                )
                _store_prompt = (
                    "I couldn't pinpoint that. Please share a full street address "
                    "(e.g. \"1340 Sainte-Catherine St W, Montreal\")."
                    if not geocoded_stores else
                    f"I found **{_mismatch}** — that's outside {_store_location_hint}. "
                    "Is that right, or did you mean somewhere else?"
                    if _mismatch else
                    "Is this the right location?" if len(geocoded_stores) == 1 else "Are these the right business locations?"
                )
                add_beat(state, "framing", {
                    "stage": "geo_store_confirm",
                    "store_names": [s.get("name") for s in geocoded_stores if s.get("name")],
                    "store_count": len(geocoded_stores),
                    "market_mismatch": _mismatch,          # "" -> dropped by add_beat
                    "stated_market": _store_location_hint if _mismatch else "",
                }, fallback=_store_narrative)
                _store_result = await wizard_interrupt(
                    writer,
                    step_key="geo_store_confirmation",
                    context=f"Store set targeting, {len(geocoded_stores)} address(es) geocoded",
                    state=state,
                    prompt_override=_store_prompt,
                    skip_ask=True,
                    progress=_build_geo_progress(ws),
                    rerun_on_edit={"store_addresses", "geo_store_addresses"},
                    edit_base={
                        "store_addresses": list(_store_addrs),
                        "geo_store_addresses": list(_store_addrs),
                    },
                    repeat_events=_store_map_events,
                )
                # Any OTHER field the user changed in the same breath. Parked for
                # builder_plan; before this it was acked and dropped.
                stash_edits(ws, _store_result, exclude=("store_addresses", "geo_store_addresses"))

                # ── Confirm-widget delta lane ────────────────────────────────
                # This map ships `editable: True` (above), so its search bar
                # submits {"confirm":..,"added":[..],"removed":[..]} rather than
                # prose. `is_sentinel_resume` short-circuits ANY JSON straight to
                # the confirm lane before the classifier runs, so `.edits` is
                # always empty for it — the user's added/removed stores were
                # confirmed away unread. Same fix the location confirm already
                # carries (see _parse_location_delta above).
                _store_delta = _parse_location_delta(_store_result)
                if _store_delta is not None:
                    if _store_delta.get("confirm") is False:
                        # Rejected — same reasoning as the location-confirm
                        # reject lane: stop this task now rather than loop
                        # into a second interrupt() call. See _GeoStepPaused.
                        raise _GeoStepPaused()
                    _stash_widget_undo(ws, _STORE_UNDO_KEYS)
                    _merged_stores, _ = _loc_delta_to_names(
                        _store_delta, _store_addrs, geocoded_stores
                    )
                    if not _merged_stores:
                        writer({"type": "thinking", "content": (
                            "Store delta would empty the anchor set — re-asking"
                        )})
                        raise _GeoStepPaused()
                    if _norm_locs(_merged_stores) != _norm_locs(_store_addrs):
                        _store_addrs = [str(x) for x in _merged_stores]
                        extra_inputs["store_addresses_list"] = list(_store_addrs)
                        ws["_stores_synced"] = list(_store_addrs)
                        ws.pop("_geocoded_stores", None)
                        writer({"type": "thinking", "content": (
                            f"Store delta at confirm: re-geocoding {_store_addrs}"
                        )})
                        geocoded_stores = await _do_geocode_stores(_store_addrs)
                        if not geocoded_stores:
                            break
                    # An explicit, structured pick needs no second confirm round.
                    ws["_store_confirmed"] = True
                    # Just resolved from a genuine wizard_interrupt() call —
                    # stop NOW. See _GeoStepPaused's docstring.
                    raise _GeoStepPaused()

                _store_edited = None
                _store_edits = getattr(_store_result, "edits", None) or {}
                for _key in ("store_addresses", "geo_store_addresses"):
                    _v = _store_edits.get(_key)
                    # Same guard as the location-confirm read loop above — see
                    # that comment.
                    if _v is not None and not isinstance(_v, list):
                        _v = [_v]
                    if _v is not None and _norm_locs(_v) != _norm_locs(_store_addrs):
                        _store_edited = _v
                        break
                if _store_edited:
                    _stash_widget_undo(ws, _STORE_UNDO_KEYS)
                    _store_addrs = [str(x) for x in _store_edited]
                    extra_inputs["store_addresses_list"] = list(_store_addrs)
                    ws["_stores_synced"] = list(_store_addrs)
                    for _k in ("_geocoded_stores",):
                        ws.pop(_k, None)
                    writer({"type": "thinking", "content": (
                        f"Geo store edit at confirm: re-geocoding {_store_addrs}"
                    )})
                    geocoded_stores = await _do_geocode_stores(_store_addrs)
                    # Same reasoning as the reject lane above.
                    raise _GeoStepPaused()
                if not getattr(_store_result, "answered", True):
                    # A non-answer (other-field edit, question, reject) never
                    # confirms the stores; re-ask after its edits are applied.
                    raise _GeoStepPaused()
                ws["_store_confirmed"] = True
                # Same reasoning as the structured-delta branch above.
                raise _GeoStepPaused()
            all_pois.extend(
                # `parent_poi_type` is the human-facing group label ("my
                # stores" — group_pois_by_category's `key`); `source_angle`
                # stays the literal "store_set" token everything else
                # (resolve_group_labels_verbose's self-reference match,
                # _is_discovered, poi_type_rules) keys off of. Now that a
                # store_set POI can ride alongside a market angle (e.g. a
                # category run excluding "my store"), the map tab for it is
                # no longer skipped, so the label needs to read as one.
                {**s, "parent_poi_type": "my stores", "source_angle": "store_set"}
                for s in geocoded_stores
            )

        if "competitor_nearby" in subtype_set:
            my_store = extra_inputs.get("store_address", "")
            # competitor_anchors is the source of truth (one entry per outlet);
            # fall back to the legacy single-anchor scalars for old checkpoints.
            anchors = extra_inputs.get("competitor_anchors") or []
            if not anchors:
                lat = extra_inputs.get("competitor_store_lat")
                lng = extra_inputs.get("competitor_store_lng")
                if lat and lng:
                    anchors = [{"latitude": lat, "longitude": lng, "location_name": my_store}]
            # NOTE: the user confirms these anchor(s) on the map at COLLECTION time —
            # the geo_confirm_store_anchor ask fires right after the anchor address
            # and BEFORE the competitor radius, so by here the anchor is trusted.
            # Type source. This arm is the only store-anchored radius search, so it
            # serves two intents: "competitors near my store" (Punk infers the rival
            # types) and "the places I NAMED near my store" ("gyms within 10 min of my
            # supplement store" — gyms are adjacent traffic, not rivals, and inferring
            # competitor types would search supplement stores instead). When the user
            # named the types, honour them; otherwise infer, exactly as before.
            _user_types = [
                str(t) for t in _types_for(
                    "competitor_nearby", "anchor_types",
                    extra_inputs.get("anchor_types_list") or [],
                )
                if str(t).strip()
            ]
            if _user_types:
                comp_types = list(_user_types)
                writer({"type": "thinking", "content": (
                    f"Store-anchored search using the place types you named: {comp_types}"
                )})
            else:
                result, _log = await call_tool(
                    get_competitor_types, {"business_context": poi_context},
                    writer=writer, node_name="geo_execute_deterministic",
                )
                tool_log.append(_log)
                comp_types = result if result else ["competitor store"]
                writer({"type": "thinking", "content": f"Competitor types: {comp_types}"})
            collected_types.extend(comp_types)
            ws["_det_anchor_types_from_user"] = bool(_user_types)
            comp_radius = float(extra_inputs.get("competitor_radius_km", 5))
            seen_coords: set[tuple] = set()
            _what = "places" if _user_types else "competitor locations"
            writer({"type": "update", "content": f"Finding nearby {_what} within {comp_radius:g} km of your business..."})
            # Build one search per (anchor × competitor type); keep the anchor
            # coords alongside each task so the post-gather distance filter and
            # dedup run in the same order as the old serial loop → identical output.
            _meta: list[tuple] = []  # (ct, a_lat, a_lng)
            _coros = []
            for anchor in anchors:
                a_lat = anchor.get("latitude")
                a_lng = anchor.get("longitude")
                if not (a_lat and a_lng):
                    continue
                # Places QUERY TEXT, not a label. Only a market the user actually
                # named belongs here: the anchor's own `locality` is a borough or
                # sub-district ("Ville-Marie" for Montreal, "Kafrul" for Dhaka) and
                # its `location_name` is now the shop's canonical name ("SKS
                # Tower") — either one searches the wrong area. With no named
                # market, send none: this search is already pinned by the anchor's
                # lat/lng + bounds + radius.
                city = location_names[0] if location_names else ""
                # This arm anchors on store coords, not a geocoded market dict, so
                # there is no `loc` to label from. Prefer the resolved form of the
                # named market; otherwise name the anchor itself, never "".
                _comp_label = (
                    _confirm_label(geocoded_locations[0])
                    if location_names and geocoded_locations
                    else anchor.get("formatted_address")
                    or anchor.get("location_name")
                    or my_store
                )
                for ct in comp_types:
                    _meta.append((ct, a_lat, a_lng))
                    _coros.append(call_tool(
                        search_pois_by_type, {
                            "poi_type": ct, "city_name": city,
                            "latitude": a_lat, "longitude": a_lng,
                            "search_radius_km": comp_radius,
                            "bounds": _bbox_from_center(a_lat, a_lng, comp_radius),
                            "parent_label": _comp_label,
                        },
                        writer=writer, node_name="geo_execute_deterministic",
                    ))
            for (ct, a_lat, a_lng), (result, _log) in zip(_meta, await _gather_bounded(_coros)):
                tool_log.append(_log)
                if result and isinstance(result, dict):
                    for p in result.get("targetable_poi_coordinates", []):
                        if not (p.get("lat") and p.get("lng")):
                            continue
                        if _distance_km(
                            float(a_lat), float(a_lng), float(p["lat"]), float(p["lng"]),
                        ) > comp_radius:
                            continue
                        coord_key = (round(float(p["lat"]), 5), round(float(p["lng"]), 5))
                        if coord_key in seen_coords:
                            continue
                        seen_coords.add(coord_key)
                        all_pois.append({**p, "parent_poi_type": ct, "source_angle": "competitor_nearby"})

        if "competitor_area" in subtype_set:
            # Same rival-type inference as competitor_nearby, searched across the
            # named market instead of a ring around an address. This is the angle for
            # advertisers with no storefront to anchor on (SaaS, e-commerce,
            # service-area), who want their competitors across the WHOLE targeting
            # area. `locations` is a real slot for this angle (it is not in the
            # store-anchored skip lists), so `_locs_for` has markets to work with.
            _area_types = [
                str(t) for t in _types_for("competitor_area", "poi_types", [])
                if str(t).strip()
            ]
            if not _area_types:
                result, _log = await call_tool(
                    get_competitor_types, {"business_context": poi_context},
                    writer=writer, node_name="geo_execute_deterministic",
                )
                tool_log.append(_log)
                _area_types = result if result else ["competitor store"]
                writer({"type": "thinking", "content": f"Competitor types: {_area_types}"})
            collected_types.extend(_area_types)
            writer({"type": "update", "content": (
                f"Finding competitor locations across {len(_locs_for('competitor_area'))} area(s)..."
            )})
            await _search_types_across(_area_types, "competitor_area")

        elif extra_inputs.get("brand_names_list"):
            # det_type dropped "competitor_brand" while filled["brand_names"] is
            # still non-empty — the exact silent-amputation bug this log line
            # exists to catch (see edits.py's det_type union fix). Named brands
            # sit unread until someone notices the tab/spots are gone.
            logger.warning(
                "geo discover: brand_names_list=%r present but 'competitor_brand' "
                "missing from det_type=%r — brand arm skipped",
                extra_inputs["brand_names_list"], sorted(subtype_set),
            )

        if "competitor_brand" in subtype_set:
            # Grounded resolution, hint="all": the user named brand(s) and wants
            # every outlet. resolve_named_target keeps all exact-name outlets from
            # live Places; a name that turns out to be a single venue collapses to
            # one (no false chain).
            _brand_list = _types_for("competitor_brand", "competitor_brands", extra_inputs.get("brand_names_list", []))
            _brand_locs = _locs_for("competitor_brand")
            writer({"type": "update", "content": f"Finding {len(_brand_list)} brand(s) across {len(_brand_locs)} area(s)..."})
            await _resolve_and_collect(_brand_list, "all", "competitor_brand", locs=_brand_locs, scope=_scope_for("competitor_brand"))

        if "named_places" in subtype_set:
            # Grounded resolution, hint="specific": the user named exact spots.
            # resolve_named_target returns THAT spot when one dominates, ASKS which
            # when several distinct venues tie, upgrades to all outlets when live
            # Places shows a chain, and web-search falls back for novel names.
            _named_list = _types_for("named_places", "named_places", extra_inputs.get("named_places_list", []))
            _named_locs = _locs_for("named_places")
            writer({"type": "update", "content": f"Finding {len(_named_list)} place(s) across {len(_named_locs)} area(s)..."})
            await _resolve_and_collect(_named_list, "specific", "named_places", locs=_named_locs, scope=_scope_for("named_places"))

        if "event_based" in subtype_set:
            event_queries = _types_for("event_based", "event_queries", extra_inputs.get("event_queries_list", [])) or [extra_inputs.get("event_type", "")]
            _event_locs = _locs_for("event_based")
            # Per-angle event date range overrides the shared flat one.
            date_range = str(
                (_spec_by_angle.get("event_based") or {}).get("event_date_range")
                or extra_inputs.get("event_date_range", "") or ""
            ).strip()
            if not date_range:
                # `search_events` appends date_range to the query text, so an empty one
                # gives the search nothing to anchor on and it surfaces UPCOMING events.
                # Event targeting is inherently retrospective — the audience is built
                # from MAID sightings, which only exist for events that already
                # happened — so a future venue yields an empty audience by
                # construction. Default to a bounded PAST window ("the last three
                # Chiefs home games" carries no date phrase for the extractor to
                # resolve). Same human-readable shape the extractor emits.
                date_range = _default_past_event_window()
                writer({"type": "thinking", "content": (
                    f"No event date range given — defaulting to the recent past "
                    f"({date_range}); MAID only has data for events already held"
                )})
            _ev_window = await _event_window_for(date_range)
            if date.fromisoformat(_ev_window[0]) > date.fromisoformat(_ev_window[1]):
                # Asked only for the future: the audience is built from MAID sightings,
                # which cannot exist yet. Say so instead of searching.
                writer({"type": "update", "content": (
                    f"'{date_range}' hasn't happened yet, so there are no visitors to "
                    f"target from it — try a past date range."
                )})
                ws["_det_named_not_found"] = sorted(set(
                    (ws.get("_det_named_not_found") or []) + list(event_queries)
                ))
                event_queries = []
            # Record event queries in the label union (a combo may also carry
            # category poi_types, already recorded by that arm).
            collected_types.extend(event_queries)
            writer({"type": "update", "content": f"Finding event venues for {len(event_queries)} quer(ies) across {len(_event_locs)} area(s)..."})
            _meta = []  # (eq, city)
            _coros = []
            for loc in _event_locs:
                city = loc.get("location_name", "")
                for eq in event_queries:
                    _meta.append((eq, city))
                    _coros.append(call_tool(
                        search_events, _event_args(loc, eq, date_range, _ev_window),
                        writer=writer, node_name="geo_execute_deterministic",
                    ))
            # Track hits PER QUERY (not per query×city): an event query is only a
            # miss when no location turned up a venue for it.
            _ev_found: dict[str, bool] = {eq: False for eq in event_queries}
            _ev_results = await _gather_bounded(_coros)
            _report_event_rejections([r for r, _l in _ev_results])
            for (eq, city), (result, _log) in zip(_meta, _ev_results):
                tool_log.append(_log)
                if result and isinstance(result, dict):
                    result_pois = result.get("targetable_poi_coordinates", [])
                    all_pois.extend(
                        {**p, "parent_poi_type": eq, "source_angle": "event_based"}
                        for p in result_pois
                    )
                    if result_pois:
                        _ev_found[eq] = True
                    writer({"type": "thinking", "content": f"Found {len(result_pois)} venue(s) for '{eq}' in {city}"})
            # Zero venues anywhere → the target may never have been an event.
            # Cross-check it as a place before reporting the miss (mirrors
            # `_resolve_and_collect`'s honest-miss tail, which the event arm never
            # had — a miss used to surface only as a debug `thinking` line).
            _ev_missing: list[str] = []
            for eq in event_queries:
                if _ev_found.get(eq):
                    continue
                if not await _crosscheck_as_place(eq):
                    _ev_missing.append(eq)
            if _ev_missing:
                ws["_det_named_not_found"] = sorted(set(
                    (ws.get("_det_named_not_found") or []) + _ev_missing
                ))
                writer({"type": "update", "content": (
                    f"Couldn't find events for: {', '.join(_ev_missing)} — "
                    f"check the spelling or try a different date range."
                )})

        # "Place Types" label = order-preserving union of every arm's searched
        # types (was last-arm-wins when arms clobbered the shared `poi_types`).
        poi_types = list(dict.fromkeys(collected_types))
        ws["_poi_types_cache"] = poi_types

    # No stale-event drop here any more: `search_events` verifies every event's
    # dates against the resolved window (user-supplied or default) before it
    # returns, so an event POI that reaches this point is already dated inside it.

    # Dedup BEFORE round-robin/cap — see dedup_pois's own docstring for both
    # passes and why named arms are sorted to win survivorship over guessed ones.
    all_pois = dedup_pois(all_pois)

    # "Everywhere except downtown": drop what falls inside an area the user
    # carved out. After dedup so a POI counted once is filtered once.
    all_pois = await drop_excluded_pois(ws, all_pois, writer)

    # Category validation: Places' textQuery ("dog park in Fort Collins") is a
    # loose full-text match, not a type filter — geo.py tags every hit with the
    # category that was SEARCHED, regardless of what Places says the place
    # actually IS. A brewery, an apartment complex, or a highway rest stop can
    # come back for "dog park" just as easily as a real one. Each POI already
    # carries Places' own `types` array from that same search response; this
    # checks the claim against it before the POI ever reaches audience
    # targeting. Grouped by parent_poi_type since that's the category each POI
    # was tagged under — cross-angle groups (competitor_brand, named_places,
    # event_based, ai_suggested) have no allowlist entry and pass through
    # unfiltered (see poi_type_rules.validate_pois).
    _by_cat: dict[str, list[dict]] = {}
    for _p in all_pois:
        _by_cat.setdefault(str(_p.get("parent_poi_type") or ""), []).append(_p)
    _validated: list[dict] = []
    _all_dropped: list[dict] = []
    for _cat, _cat_pois in _by_cat.items():
        _kept, _dropped = validate_pois(_cat_pois, _cat)
        _validated.extend(_kept)
        _all_dropped.extend(_dropped)
    if _all_dropped:
        all_pois = _validated
        _sample = ", ".join(d["name"] for d in _all_dropped[:5])
        _more = f" (+{len(_all_dropped) - 5} more)" if len(_all_dropped) > 5 else ""
        writer({"type": "thinking", "content": (
            f"POI type check: dropped {len(_all_dropped)} place(s) whose Google "
            f"Places type didn't match the requested category — {_sample}{_more}"
        )})

    # Round-robin by (location × poi type) BEFORE the hard cap so neither a dense
    # multi-city search drops the trailing cities NOR a dense multi-type search in
    # one city drops the trailing types (all_pois is built type-by-type per city).
    # `parent_location` is the RESOLVED address, so two typed spellings of one
    # market ("montreal" / "Montréal, QC") now share a bucket instead of getting
    # two — which is the correct share, not a regression: they are one market.
    # Interleaved (not truncated) — every POI found ships; the ceiling is now
    # GEO_MAX_TILE_SEARCHES x 20 (API-cost bound), not a POI-count cap.
    all_pois = _round_robin_by(
        all_pois, lambda p: (p.get("parent_location"), p.get("parent_poi_type"))
    )

    # Per-category quality cap. Discovery is unbounded on purpose, but every POI
    # that survives to the confirm gate becomes a geofence in a paid MAID request,
    # so an untrimmed 23-store brand search spends the audience budget on the
    # long tail of the least-visited locations. Capped PER GROUP (the same
    # source_angle/parent_poi_type sets the map shows as tabs) rather than
    # overall, so a search returning 20 Sephora and 3 Ulta keeps both brands
    # instead of silently answering a different question. The user still sees the
    # trim and can add any dropped place back at the confirm gate.
    all_pois = _cap_pois_per_category(all_pois, writer=writer)
    # Cache the POST-dedup, post-round-robin list — this is what the map shows
    # and what `pois_found` counts. Was cached PRE-dedup (right after the search
    # arms ran, above): a trim's "superset" read (builder_node._all_pois_cache)
    # then disagreed with det["targetable_pois"], so a "top N" could report a
    # different count than what was actually on screen. Written unconditionally
    # (cache-hit re-read included) so the cache always reflects the current,
    # settled list — both passes are idempotent on an already-deduped/interleaved
    # input, so re-running them on a cache hit is a no-op, not a second trim.
    ws["_all_pois_cache"] = all_pois
    pois_found = len(all_pois)
    writer({"type": "update", "content": f"Found {pois_found} targetable place(s); preparing the map preview..."})
    writer({"type": "thinking", "content": f"Deterministic: {pois_found} POIs collected"})

    # Map center: anchor centroid for a competitor run, since its POIs ring the
    # user's own store(s). But when a MARKET angle also runs, its POIs sit across the
    # named market instead — centering on the store anchor would open the map away
    # from most of them, so the market center wins for mixed runs. Pure
    # competitor_nearby (and the store pair) keep the anchor centroid.
    if "competitor_nearby" in subtype_set and not (subtype_set & _MARKET_ANGLES):
        _anchors = extra_inputs.get("competitor_anchors") or []
        if _anchors:
            center = {
                "latitude": sum(a["latitude"] for a in _anchors) / len(_anchors),
                "longitude": sum(a["longitude"] for a in _anchors) / len(_anchors),
            }
        else:
            center = {"latitude": extra_inputs.get("competitor_store_lat"), "longitude": extra_inputs.get("competitor_store_lng")}
    else:
        # Market run: with several markets (a divergent per-angle combo spans
        # multiple cities), open on the CENTROID of all of them so the map frames
        # every market instead of the first. A single market keeps its full loc dict
        # (unchanged — the map may read more than lat/lng from it).
        _mkt = [
            loc for loc in geocoded_locations
            if loc.get("latitude") is not None and loc.get("longitude") is not None
        ]
        if len(_mkt) > 1:
            center = {
                "latitude": sum(loc["latitude"] for loc in _mkt) / len(_mkt),
                "longitude": sum(loc["longitude"] for loc in _mkt) / len(_mkt),
            }
        else:
            center = geocoded_locations[0] if geocoded_locations else {}
    event_date_ranges = list({
        f"{p.get('event_start_date', 'TBD')} – {p.get('event_end_date', 'TBD')}"
        for p in all_pois
        if p.get("event_start_date") or p.get("event_end_date")
    })

    # Store all results for geo_show_pois + geo_confirm_pois to consume
    ws["_det_result"] = {
        "targeting_method": "deterministic",
        "targeting_type": f"{targeting_type}/{deterministic_type}",
        "locations": geocoded_locations,
        "poi_types": poi_types,
        "targetable_pois": all_pois,
        "pois_found": pois_found,
        "poi_radius_km": poi_radius_km,
        "lookback_days": lookback_days,
    }
    ws["_det_center"] = center
    ws["_det_event_date_ranges"] = event_date_ranges or None
    ws["_det_extra_inputs"] = extra_inputs
    ws["_det_tool_log"] = tool_log


# ── POI edit helpers ─────────────────────────────────────────────────────────
# Relocated from wizards/geo_wizard.py (builder-only consolidation). Shared by the
# campaign builder's geo_discover act / poi_confirm gate. The POI-found reveal is
# now a `geo_complete` milestone beat in builder_node (woven into the pause's
# single composed message), not a standalone LLM emit here.


def _poi_key(p: dict):
    """Coord identity key for POI dedupe/match, rounded to ~1 m. None when the
    POI carries no usable lat/lng."""
    try:
        return (round(float(p["lat"]), 5), round(float(p["lng"]), 5))
    except (KeyError, TypeError, ValueError):
        return None


def dedup_key(p: dict):
    """Identity key for "is this the SAME place": coordinates AND name.

    Coordinates alone are not enough — an event whose venue is still "TBD"
    geocodes to the city centroid, so several distinct conferences in one city
    land on identical coords and a coord-only key silently ate all but the first.
    The same physical place returned under two queries still collapses (same
    coords AND same name).

    `_poi_key` stays coord-only on purpose: the map-removal lanes in
    ``apply_poi_edits`` pair it with the name themselves and rely on that shape.

    None when the POI carries no usable lat/lng (nothing to dedup on)."""
    k = _poi_key(p)
    return None if k is None else (k, _norm_poi_name(p.get("name")))


def dedup_pois(pois: list[dict]) -> list[dict]:
    """Collapse duplicate POIs across search arms to one survivor each. Two
    passes:
      1. Exact coord dedup (~1 m) — one physical place matched under several
         brands/queries/locations enters as multiple rows at the same lat/lng;
         left unchecked they inflate pois_found and make one map removal count
         as N removals at maid_confirm (shared `_poi_key`).
      2. Name-aware dedup — the SAME venue returned at micro-different coords
         (two place_ids) or by two angles carries the same name a few metres
         apart, slipping past the exact-coord pass. Drop a POI that shares a
         normalized name with a kept POI AND sits within NAMED_DEDUP_DISTANCE_KM.
         Genuinely different same-name outlets (Starbucks x5, distinct Fight
         Clubs) are far apart and survive.

    Sorted stable, named arms first (`not _is_discovered`), before either
    pass: survivorship is "first occurrence wins", so without this a generic
    type arm dispatched earlier in discovery order (e.g. "pet store") silently
    absorbs a brand the user explicitly named (e.g. "PetSmart") — same
    physical store, but the survivor loses `source_angle`/`parent_poi_type`,
    which is simultaneously the map's category-tab id (`poi_group_id`) and the
    bare-count trim's protection marker. A named arm must never lose identity
    to a guessed one.
    """
    from app.graph.builder.executors.poi_selection import _is_discovered

    pois = sorted(pois, key=lambda p: _is_discovered(p))
    _seen_keys: set = set()
    _deduped: list[dict] = []
    for _p in pois:
        _nm = _norm_poi_name(_p.get("name"))
        _ck = dedup_key(_p)
        if _ck is not None and _ck in _seen_keys:
            continue
        _dup = False
        if _nm and _p.get("lat") is not None and _p.get("lng") is not None:
            for _q in _deduped:
                if _nm == _norm_poi_name(_q.get("name")) \
                        and _q.get("lat") is not None and _q.get("lng") is not None \
                        and _distance_km(
                            float(_p["lat"]), float(_p["lng"]),
                            float(_q["lat"]), float(_q["lng"]),
                        ) < settings.NAMED_DEDUP_DISTANCE_KM:
                    _dup = True
                    break
        if _dup:
            continue
        if _ck is not None:
            _seen_keys.add(_ck)
        _deduped.append(_p)
    return _deduped


def _norm_poi_name(name: Any) -> str:
    """Fold a POI name for equality: strip, casefold, drop accents. Makes the
    widget payload's name (e.g. "Jiu Jitsu Île Des Soeurs") match the stored name
    regardless of accent/unicode form. Empty string when no usable name."""
    s = str(name or "").strip()
    if not s:
        return ""
    return (
        unicodedata.normalize("NFKD", s)
        .encode("ascii", "ignore")
        .decode("ascii")
        .casefold()
    )


# What a confirm-step edit (a typed add/remove, a map drag / pin / resize) can
# change, captured BEFORE it lands so "undo" can put it back. builder_act reads
# and pops the stash after the act (`_sync_confirm_edits_undoable`).
_LOC_UNDO_KEYS = (
    "_geocoded_locations", "_locations_synced", "_angle_names_synced", "_loc_cache_key",
    "_parsed_locations", "_location_confirmed", "location_names",
)
_STORE_UNDO_KEYS = ("_geocoded_stores", "_stores_synced", "_store_confirmed", "_parsed_store_addresses")


def _stash_widget_undo(ws: dict, extra: tuple[str, ...]) -> None:
    """Deep-copy the decisions a confirm-step edit is about to change — once per
    act (the first edit wins: it holds the truly pre-edit state)."""
    if "_widget_undo_before" in ws:
        return
    from app.graph.builder.edits import GEO_DECISION_KEYS

    ws["_widget_undo_before"] = {k: copy.deepcopy(ws.get(k)) for k in (*GEO_DECISION_KEYS, *extra)}


def _parse_location_delta(raw: Any) -> dict | None:
    """A confirm-widget add/remove/update delta parsed off a resume answer, or
    None.

    Mirrors ``builder_node._parse_json_value`` (which cannot be imported here —
    that module imports this one). None means "not a delta"; every other answer
    shape (a plain "yes", an option label, a ``ResumeResult`` carrying router
    edits) falls through to the caller's existing lanes untouched.

    ``updated`` (pin+radius drag/resize on an existing location — see
    ``_apply_location_updates``) is a third delta kind alongside the
    original ``added``/``removed``.
    """
    text = str(raw or "").strip()
    if not text.startswith("{"):
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed if {"confirm", "added", "removed", "updated"} & parsed.keys() else None


def _loc_name_tokens(loc: dict) -> set[str]:
    """Every NAME that can identify one location in a confirm payload.

    The name list holds the user's raw word ("laval") while the widget round-trips
    the RESOLVED place ("Laval, QC, Canada"), so a removal has to match on either.
    All accent/case folded via the shared ``_norm_poi_name``.
    """
    return {
        t for t in (
            _norm_poi_name(loc.get("_source_name")),
            _norm_poi_name(loc.get("location_name")),
            _norm_poi_name(loc.get("name")),
            _norm_poi_name(str(loc.get("formatted_address") or "").split(",")[0]),
            _norm_poi_name(str(loc.get("parent_location") or "").split(",")[0]),
        ) if t
    }


def _loc_delta_to_names(
    edits: dict, current_names: list[str], geocoded: list[dict],
) -> tuple[list[str], dict[str, dict]]:
    """Fold a confirm-widget delta into ``(merged_location_names, hints)``.

    Locations are NAMES, not coordinates: an added place must be re-geocoded to earn
    the ``bounds`` / ``locality`` / ``admin_area1_name`` / ``country_name`` /
    ``place_type`` the POI search filters read (see ``_locality_filter_for`` and the
    search arms). So the delta is reduced to name tokens here and the real work is
    left to ``_do_geocode`` — the widget's own ``lat``/``lng`` and ``parent_poi_type``
    ride along as ``hints`` (consumed by ``_pick_candidate_by_hint``) so the re-probe
    resolves to the entity the user clicked without an extra disambiguation ask.

    Pure. Unlike ``apply_poi_edits`` it takes no ``ws``/loop state, so the store
    confirm loop can reuse it as-is.
    """
    merged = [str(n) for n in current_names]

    # Remove: match on NAME only. Unlike a POI, a location has no precise coordinate
    # identity — two markets can legitimately round to the same key, and a city
    # centroid is not a fixed point — so a coord match would drop the wrong one.
    # `_loc_name_tokens` reads five different name fields, so any item carrying any
    # name at all is covered; one carrying none is an empty payload, and skipping it
    # is the only safe reading.
    drop: set[str] = set()
    for item in edits.get("removed") or []:
        if not isinstance(item, dict):
            item = {"name": item}
        item_names = _loc_name_tokens(item)
        if not item_names:
            continue
        for loc in geocoded:
            if item_names & _loc_name_tokens(loc):
                drop.add(_norm_poi_name(
                    loc.get("_source_name") or loc.get("location_name")
                ))
        # Also match the raw name list directly, for a location that never geocoded.
        drop.update(n for n in (_norm_poi_name(x) for x in merged) if n in item_names)
    drop.discard("")
    if drop:
        merged = [n for n in merged if _norm_poi_name(n) not in drop]

    # Append: order-preserving union against what survived the removals.
    hints: dict[str, dict] = {}
    seen = {_norm_poi_name(n) for n in merged}
    for item in edits.get("added") or []:
        if not isinstance(item, dict):
            item = {"name": item}
        name = str(
            item.get("name")
            or str(item.get("parent_location") or "").split(",")[0]
        ).strip()
        if not name or _norm_poi_name(name) in seen:
            continue
        merged.append(name)
        seen.add(_norm_poi_name(name))
        # Any other key the picker sends (e.g. `place_id`) is ignored — the name is
        # what gets re-geocoded, and place_type + coords are enough to settle which
        # entity it resolved to.
        hints[name] = {
            "place_type": item.get("parent_poi_type") or item.get("place_type"),
            "lat": item.get("lat", item.get("latitude")),
            "lng": item.get("lng", item.get("longitude")),
            "formatted_address": item.get("parent_location") or item.get("formatted_address"),
        }

    return merged, hints


async def _new_manual_pin(item: dict, ws: dict) -> dict | None:
    """A confirm-widget ``added`` entry with no resolvable name — a raw pin
    dropped via the map's "drop pin" toggle. Skips geocoding entirely
    (mirrors ``_apply_pin_fallback``'s synthetic-pin shape) and reverse-
    geocodes the coordinate for a real place label ("Griffintown") instead
    of a bare "Custom area N", so a manually dropped pin reads the same as
    a searched one. Falls back to the generic label only when the reverse
    lookup itself fails. Returns None when the item carries no usable
    coordinates."""
    lat = item.get("lat", item.get("latitude"))
    lng = item.get("lng", item.get("longitude"))
    if lat is None or lng is None:
        return None
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    radius = _clamp_pin_radius_km(item.get("radius_km"))
    ws["_manual_pin_seq"] = int(ws.get("_manual_pin_seq") or 0) + 1
    label = str(item.get("name") or "").strip()
    formatted = label
    if not label:
        _rev = await reverse_geocode_point(lat, lng)
        if _rev and _rev.get("location_name"):
            label = str(_rev["location_name"])
            formatted = str(_rev.get("formatted_address") or label)
    if not label:
        label = formatted = f"Custom area {ws['_manual_pin_seq']}"
    return {
        "latitude": lat, "longitude": lng,
        "location_name": label, "formatted_address": formatted,
        # Unique internal id (never shown) so a removal targeting this exact
        # pin can't collide with a sibling pin that reverse-geocoded to the
        # same neighbourhood label.
        "_source_name": f"__manual_pin_{ws['_manual_pin_seq']}__",
        "is_city": False, "place_type": None, "place_id": None, "bounds": None,
        "ui_mode": "pin_radius",
        "search_radius_km": radius, "default_radius_km": radius,
    }


def _remove_manual_pins(geocoded: list[dict], ws: dict, removed: Any) -> bool:
    """Drop a manual (nameless-add) pin the confirm widget's delta named for
    removal.

    Manual pins live outside ``location_names`` (they were never geocoded
    from a name), so ``_loc_delta_to_names`` — which only edits the name
    list — can't remove them; this handles that side directly, matching
    against ``ws["_manual_pins"]`` via the same name-token set removal
    already uses (each manual pin's ``_source_name`` is a unique internal
    id, so this can't cross-match a different pin).
    """
    if not removed:
        return False
    drop_tokens: set[str] = set()
    for item in removed:
        if not isinstance(item, dict):
            item = {"name": item}
        drop_tokens |= _loc_name_tokens(item)
    if not drop_tokens:
        return False
    manual_pins = ws.get("_manual_pins") or []
    to_drop = [p for p in manual_pins if _loc_name_tokens(p) & drop_tokens]
    if not to_drop:
        return False
    ws["_manual_pins"] = [p for p in manual_pins if p not in to_drop]
    geocoded[:] = [loc for loc in geocoded if loc not in to_drop]
    return True


async def _apply_location_updates(geocoded: list[dict], updates: Any, ws: dict) -> bool:
    """Apply confirm-widget radius/center edits to already-geocoded locations
    in place. Returns True if anything changed.

    Each update matches an existing location by ``place_id`` when the widget
    sends one, else by the same name-token match ``_loc_delta_to_names``
    uses for removal (``_loc_name_tokens``). A center move (lat/lng differs
    from the location's current coordinates) DEMOTES the entry — strips its
    political identity (``place_id``/``place_type``/``bounds``) so it
    becomes a plain pin positioned exactly where the user dragged it, and
    reverse-geocodes the NEW coordinate for a fresh label (the old resolved
    city name would otherwise stay attached to a spot the user deliberately
    moved away from). A radius-only edit (same center) just updates
    ``search_radius_km`` in place, no demotion, no relabel.

    Both persist into ``ws["_loc_radius_overrides"]`` (keyed by the
    location's original source-name) so a later re-geocode — forced by
    editing a SIBLING location — re-applies the same override instead of
    reverting this one back to its geocoded default (see
    ``_stamp_location_radius_mode``).
    """
    if not updates:
        return False
    overrides: dict = ws.setdefault("_loc_radius_overrides", {})
    changed = False
    for item in updates:
        if not isinstance(item, dict):
            continue
        item_pid = str(item.get("place_id") or item.get("id") or "").strip()
        item_names = _loc_name_tokens(item)
        match = next(
            (loc for loc in geocoded if item_pid and str(loc.get("place_id") or "") == item_pid),
            None,
        )
        if match is None and item_names:
            match = next((loc for loc in geocoded if item_names & _loc_name_tokens(loc)), None)
        if match is None:
            continue

        new_lat, new_lng, moved = item.get("lat", item.get("latitude")), item.get("lng", item.get("longitude")), False
        if new_lat is not None and new_lng is not None:
            try:
                new_lat, new_lng = float(new_lat), float(new_lng)
                moved = (
                    round(new_lat, 5) != round(float(match.get("latitude") or 0.0), 5)
                    or round(new_lng, 5) != round(float(match.get("longitude") or 0.0), 5)
                )
            except (TypeError, ValueError):
                new_lat = new_lng = None

        key = _norm_poi_name(match.get("_source_name") or match.get("location_name"))
        label = ""
        if moved:
            match["latitude"], match["longitude"] = new_lat, new_lng
            match.pop("place_id", None)
            match.pop("place_type", None)
            match.pop("bounds", None)
            match["is_city"] = False
            match["ui_mode"] = "pin_radius"
            # `item.get("name")` identifies WHICH location this update targets
            # (the match above already consumed it) — it is never a rename,
            # so the new spot is always named from where it actually is now,
            # not the pre-move address it's leaving.
            _rev = await reverse_geocode_point(new_lat, new_lng)
            if _rev and _rev.get("location_name"):
                label = str(_rev["location_name"])
                match["location_name"] = label
                match["formatted_address"] = str(_rev.get("formatted_address") or label)

        new_radius = None
        if item.get("radius_km") is not None:
            new_radius = _clamp_pin_radius_km(item.get("radius_km"))
            match["search_radius_km"] = new_radius

        if key and (moved or new_radius):
            ov = overrides.setdefault(key, {})
            if moved:
                ov.update(lat=new_lat, lng=new_lng, demoted=True)
                if label:
                    ov["label"] = label
                    ov["formatted_address"] = match.get("formatted_address")
            if new_radius:
                ov["radius_km"] = new_radius
        changed = changed or moved or bool(new_radius)
    return changed


def _resolve_map_target(ws: dict, target: str | None, *, pins_only: bool = False) -> tuple[dict | None, list[str]]:
    """The ONE circle-bearing location (or dropped pin) a typed change names.

    Returns ``(loc, candidates)``: ``loc`` is None when nothing / more than one
    matches, and ``candidates`` are the labels to ask about. No target + exactly
    one candidate is unambiguous; with several, the caller must ask.
    """
    pool = list(ws.get("_manual_pins") or []) if pins_only else (
        list(ws.get("_geocoded_locations") or []) + list(ws.get("_manual_pins") or [])
    )
    pool = [loc for loc in pool if loc.get("ui_mode") == "pin_radius"]
    labels = [_confirm_label(loc) for loc in pool]
    if not pool:
        return None, []
    if not target or not str(target).strip():
        return (pool[-1] if pins_only else pool[0]) if (pins_only or len(pool) == 1) else None, labels
    want = _loc_name_tokens({"name": target})
    hits = [loc for loc in pool if want & _loc_name_tokens(loc)]
    return (hits[0] if len(hits) == 1 else None), (labels if len(hits) != 1 else [])


_EXCLUDE_FALLBACK_RADIUS_KM = 1.0


def _inside_targets(ws: dict, lat: float, lng: float) -> bool:
    """True when the point lies inside any area being targeted: a search
    circle, or a boundary location's bounds."""
    for loc in list(ws.get("_geocoded_locations") or []) + list(ws.get("_manual_pins") or []):
        try:
            if loc.get("ui_mode") == "pin_radius":
                if _distance_km(lat, lng, float(loc["latitude"]), float(loc["longitude"])) <= float(
                    loc.get("search_radius_km") or 0
                ):
                    return True
            b = loc.get("bounds")
            if b and b["lat_min"] <= lat <= b["lat_max"] and b["lng_min"] <= lng <= b["lng_max"]:
                return True
        except (KeyError, TypeError, ValueError):
            continue
    return False


def _area_contains(area: dict, polygon: Any, lat: float, lng: float) -> bool:
    """Is (lat, lng) inside an excluded area: its real OSM polygon when there is
    one, else the geocoder's bounds box, else a small circle round its centre."""
    if polygon:
        return _point_in_polygon(lat, lng, polygon)
    b = area.get("bounds")
    if b:
        return b["lat_min"] <= lat <= b["lat_max"] and b["lng_min"] <= lng <= b["lng_max"]
    return _distance_km(lat, lng, area["lat"], area["lng"]) <= _EXCLUDE_FALLBACK_RADIUS_KM


def excluded_areas_payload(ws: dict) -> list[dict]:
    """The areas the user left out, as the maps draw them (grey): a label, a
    centre and — when the geocoder gave one — the bounding box."""
    return [
        {"label": a["label"], "lat": a["lat"], "lng": a["lng"], "bounds": a.get("bounds")}
        for a in ws.get("_excluded_areas") or [] if a.get("label") and a.get("lat") is not None
    ]


async def drop_excluded_pois(ws: dict, pois: list[dict], writer: Any = None) -> list[dict]:
    """Remove POIs that fall inside any area in ``ws["_excluded_areas"]``. The
    user's OWN stores are never dropped (``store_set``): excluding downtown must
    not delete their shop there. Reports what it dropped."""
    areas = ws.get("_excluded_areas") or []
    if not areas or not pois:
        return pois
    keep = list(pois)
    for area in areas:
        polygon = None
        try:
            polygon = await _region_polygon_cached(
                area.get("query") or area["label"], place_id=area.get("place_id"),
                place_type=area.get("place_type"), expected_bounds=area.get("bounds"),
                components=area.get("components"),
            )
        except Exception:                                  # noqa: BLE001 - the bounds fallback still applies
            polygon = None
        gone = [
            p for p in keep
            if p.get("source_angle") != "store_set"
            and p.get("lat") is not None and p.get("lng") is not None
            and _area_contains(area, polygon, float(p["lat"]), float(p["lng"]))
        ]
        if gone:
            drop = {id(p) for p in gone}
            keep = [p for p in keep if id(p) not in drop]
            if writer:
                writer({"type": "update", "content": (
                    f"Left out {len(gone)} spot(s) in {area['label']}, as you asked."
                )})
    return keep


async def _resolve_exclusion(ws: dict, name: str, writer: Any) -> tuple[Optional[dict], str]:
    """Geocode ``name`` (in the context of the first targeted location, so
    "downtown" means downtown of THAT city) into an exclusion descriptor, or
    ``(None, reason)``."""
    anchor = next(
        (str(l.get("location_name") or "") for l in (ws.get("_geocoded_locations") or []) if l.get("location_name")),
        "",
    )
    query = f"{name}, {anchor}" if anchor and anchor.lower() not in name.lower() else name
    found, _log = await call_tool(
        geocode_location, {"location_name": query, "allow_broad": False, "scope": "granular_local"},
        writer=writer or (lambda _e: None), node_name="geo_exclude_area",
    )
    if not (isinstance(found, dict) and found.get("latitude") is not None):
        return None, f"couldn't find {name!r} on the map"
    lat, lng = float(found["latitude"]), float(found["longitude"])
    if not _inside_targets(ws, lat, lng):
        return None, f"{found.get('location_name') or name} isn't inside the areas you're targeting"
    return {
        "label": str(found.get("location_name") or name), "query": query,
        "lat": lat, "lng": lng, "bounds": found.get("bounds"),
        "place_id": found.get("place_id"), "place_type": found.get("place_type"),
        "components": {
            "city": found.get("locality") or "", "state": found.get("admin_area1_name") or "",
            "country": found.get("country_name") or "",
        },
    }, ""


async def apply_location_ops(ws: dict, ops: list[dict], writer: Any = None) -> list[dict]:
    """Apply typed per-location changes to the map's decisions, one result each.

    Uses the SAME functions the map widget's drag / drop-pin use
    (``_apply_location_updates`` / ``_remove_manual_pins``), so a typed change
    and a drag can never disagree. Returns, per op::

        {"kind", "status": applied|no_op|unresolved|failed, "detail", "candidates"?}

    ``unresolved`` means the target matched nothing or several — the caller
    asks instead of guessing. Mutates ``ws`` in place; the caller invalidates the
    Places search when anything was ``applied``.
    """
    results: list[dict] = []
    for op in ops or []:
        kind, target, value = op.get("kind"), op.get("target"), str(op.get("value") or "").strip()
        if kind in ("exclude", "unexclude"):
            areas = list(ws.get("_excluded_areas") or [])
            if kind == "exclude":
                if any(a["label"].lower() == value.lower() for a in areas):
                    results.append({"kind": kind, "status": "no_op", "detail": f"{value} was already left out"})
                    continue
                area, why = await _resolve_exclusion(ws, value, writer)
                if area is None:
                    results.append({"kind": kind, "status": "failed", "detail": why})
                    continue
                if any(a["label"].lower() == area["label"].lower() for a in areas):
                    results.append({"kind": kind, "status": "no_op", "detail": f"{area['label']} was already left out"})
                    continue
                ws["_excluded_areas"] = areas + [area]
                results.append({"kind": kind, "status": "applied", "detail": f"leaving {area['label']} out of the search"})
            else:
                gone = [a for a in areas if value.lower() in a["label"].lower() or a["label"].lower() in value.lower()]
                if not gone:
                    shown = f" (I'm leaving out {', '.join(a['label'] for a in areas)})" if areas else ""
                    results.append({"kind": kind, "status": "unresolved", "candidates": [a["label"] for a in areas],
                                    "detail": f"{value!r} isn't one of the areas left out{shown}"})
                    continue
                ws["_excluded_areas"] = [a for a in areas if a not in gone]
                results.append({"kind": kind, "status": "applied", "detail": f"including {gone[0]['label']} again"})
            continue
        loc, candidates = _resolve_map_target(ws, target, pins_only=(kind == "unpin"))
        if loc is None:
            if candidates:
                results.append({"kind": kind, "status": "unresolved", "candidates": candidates,
                                "detail": f"which one? I have {', '.join(candidates)}"})
            elif kind == "unpin":
                results.append({"kind": kind, "status": "unresolved", "candidates": [],
                                "detail": "there's no dropped pin on the map to remove"})
            else:
                results.append({"kind": kind, "status": "unresolved", "candidates": [],
                                "detail": "these locations have no circle to change "
                                          "(whole states / regions don't get one)"})
            continue
        label = _confirm_label(loc)
        # The appliers below match on the location's OWN name tokens, not the long
        # formatted label ("Griffintown, Montreal, QC") shown to the user.
        ident = loc.get("_source_name") or loc.get("location_name") or label
        geocoded = ws.setdefault("_geocoded_locations", [])
        if kind == "ring":
            from app.graph.wizard_helpers import parse_length

            km = parse_length(value, "km", default=None)
            if not km or km <= 0:
                results.append({"kind": kind, "status": "failed", "detail": f"{value!r} isn't a distance"})
                continue
            ring = _clamp_pin_radius_km(km)
            if float(loc.get("search_radius_km") or 0) == ring:
                results.append({"kind": kind, "status": "no_op", "detail": f"{label}'s circle was already {ring:g} km"})
                continue
            await _apply_location_updates(
                geocoded + [p for p in (ws.get("_manual_pins") or []) if p not in geocoded],
                [{"name": ident, "radius_km": ring}], ws,
            )
            note = f"{label}'s circle is now {ring:g} km"
            if abs(ring - km) > 0.06:      # the ring is stored to 0.1 km; rounding is not a limit
                note += f" (asked for {km:g} — {ring:g} is the allowed limit)"
            results.append({"kind": kind, "status": "applied", "detail": note})
        elif kind == "center":
            if not value:
                results.append({"kind": kind, "status": "failed", "detail": "no address to move it to"})
                continue
            found, _log = await call_tool(
                geocode_location, {"location_name": value, "allow_broad": False, "scope": "granular_local"},
                writer=writer or (lambda _e: None), node_name="geo_move_center",
            )
            if not (isinstance(found, dict) and found.get("latitude") is not None):
                results.append({"kind": kind, "status": "failed", "detail": f"couldn't find {value!r} on the map"})
                continue
            await _apply_location_updates(
                geocoded + [p for p in (ws.get("_manual_pins") or []) if p not in geocoded],
                [{"name": ident, "lat": found["latitude"], "lng": found["longitude"]}], ws,
            )
            results.append({"kind": kind, "status": "applied",
                            "detail": f"moved {label}'s circle to {found.get('location_name') or value}"})
        elif kind == "unpin":
            removed = _remove_manual_pins(geocoded, ws, [{"name": ident}])
            results.append({"kind": kind, "status": "applied" if removed else "failed",
                            "detail": f"removed the pin {label}" if removed else f"couldn't remove {label}"})
        else:
            results.append({"kind": kind, "status": "failed", "detail": "unknown map change"})
    return results


def apply_poi_edits(det: dict, edits: dict) -> tuple[list[str], list[str]]:
    """Apply an editable-map confirm payload ({"added": [...], "removed": [...]})
    to ``det["targetable_pois"]``/``det["pois_found"]`` in place. Returns
    ``(added_names, removed_names)``.

    Shared by the geo wizard's ``geo_confirm_pois`` and the campaign builder's
    poi_confirm gate so both interpret the widget delta identically.
    """
    merged = list(det.get("targetable_pois") or [])
    removed = edits.get("removed") or []
    added = edits.get("added") or []

    # Remove: match on BOTH coord key AND name when the removed item carries
    # both, so a removal only drops the exact POI the user deselected — never a
    # different-named place that happens to share the same coordinate. Fall back
    # to coord-only (item has coords but no name) or name-only (item has a name
    # but no usable coords) so partial payloads still work. Names are accent/case
    # folded via `_norm_poi_name`.
    rm_pairs = {
        (_poi_key(r), _norm_poi_name(r.get("name")))
        for r in removed
        if _poi_key(r) is not None and _norm_poi_name(r.get("name"))
    }
    rm_keys_only = {
        _poi_key(r)
        for r in removed
        if _poi_key(r) is not None and not _norm_poi_name(r.get("name"))
    }
    rm_names_only = {
        _norm_poi_name(r.get("name"))
        for r in removed
        if _poi_key(r) is None and _norm_poi_name(r.get("name"))
    }

    def _is_removed(p: dict) -> bool:
        k = _poi_key(p)
        n = _norm_poi_name(p.get("name"))
        return (
            (k is not None and (k, n) in rm_pairs)
            or (k is not None and k in rm_keys_only)
            or (n != "" and n in rm_names_only)
        )

    removed_names = [p.get("name") or "(unnamed)" for p in merged if _is_removed(p)]
    merged = [p for p in merged if not _is_removed(p)]

    # Append: require usable lat+lng, dedupe by coord key (against both
    # existing and just-added). Backfill radius/type only when absent.
    seen = {k for k in (_poi_key(p) for p in merged) if k is not None}
    default_radius = det.get("poi_radius_km")
    added_applied: list[str] = []
    for a in added:
        k = _poi_key(a)
        if k is None or k in seen:
            continue
        poi = dict(a)
        poi.setdefault("radius_km", default_radius)
        poi.setdefault("parent_poi_type", "map_pick")
        merged.append(poi)
        seen.add(k)
        added_applied.append(poi.get("name") or "(unnamed)")

    det["targetable_pois"] = merged
    det["pois_found"] = len(merged)
    return added_applied, removed_names
