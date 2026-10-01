"""
graph/tools.py
──────────────
Geo-targeting and knowledge tools for the PunkAI agent graph.

Tools:
  geocode_location          - Google Geocoding API + Nominatim fallback
  get_dynamic_place_types   - LLM infers POI search phrases from business context
  get_competitor_types      - LLM infers competitor POI category
  search_pois_by_type       - Google Places Text Search for POI discovery
  search_brand_locations    - Brand-specific Google Places search
  retrieve_marketing_knowledge - Knowledge base retrieval (placeholder)
"""

from __future__ import annotations

import asyncio
import calendar
import html.parser
import json
import logging
import math
import re
import unicodedata
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import httpx
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from app.core.config import settings
from app.graph.grounding import grounded_text as _gemini_grounded_text
from app.graph.usage import record_api_call, tracked_ainvoke

logger = logging.getLogger(__name__)

_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}

# Scope (canonical targeting key) → preferred Google Geocoding result types, most
# specific first. Used to pick the right result rather than blindly taking [0]
# (e.g. "Quebec" as a province must select administrative_area_level_1, not the
# locality "Quebec City" that Google ranks first).
_SCOPE_TYPE_PREFERENCE: dict[str, list[str]] = {
    "country_groups": ["country"],
    "admin_areas": ["administrative_area_level_1", "administrative_area_level_2"],
    "granular_local": [
        # neighborhood/sublocality first so a modifier query ("Montreal downtown")
        # keeps its tight extent instead of collapsing to the locality (Montreal).
        # A bare city returns no neighborhood result, so it falls through to locality.
        "neighborhood", "sublocality",
        "locality", "postal_code",
        "administrative_area_level_3", "administrative_area_level_2",
        "street_address", "premise",
    ],
}


async def _with_retry(coro_fn, *, max_attempts: int = 3, base_delay: float = 1.0):
    """Retry coro_fn on transient HTTP failures with exponential backoff."""
    delay = base_delay
    for attempt in range(max_attempts):
        try:
            return await coro_fn()
        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
            if attempt == max_attempts - 1:
                raise
            logger.warning(
                "HTTP transient error (attempt %d/%d): %s — retrying in %.1fs",
                attempt + 1, max_attempts, exc, delay,
            )
            await asyncio.sleep(delay)
            delay *= 2.0


# ── POI → ZIP resolution ──────────────────────────────────────────────────────
# Meta geo targeting runs on ZIP codes (one unique set for every ad set role),
# not on lat/lng radius pins. Meta's zip key format is "<ISO2>:<code>" — a
# 5-digit ZIP for the US, the 3-character FSA for Canada.
#
# The postal + country are extracted from each POI's Google address components
# at DISCOVERY time (the Places searchText response already carries them — see
# _extract_postal_and_country), stored on the POI dict, and simply read back
# here. No reverse-geocode pass: the data was already fetched and paid for.


def _poi_zip_key(poi: dict) -> str | None:
    """Meta zip key from a POI's stored ``postal_code`` + ``country_code``.
    ``None`` when either is missing (that POI just drops out of the zip set)."""
    postal = str(poi.get("postal_code") or "").strip().upper()
    country = str(poi.get("country_code") or "").strip().upper()
    if not postal or not country:
        return None
    if country == "CA":
        postal = postal.split(" ")[0][:3]     # full postal → FSA
    return f"{country}:{postal}"


def resolve_poi_zips(geo_data: dict) -> list[str]:
    """Unique Meta zip keys for ``geo_data["targetable_pois"]``, read from the
    postal/country each POI carries from discovery. Pure — no network.

    POIs without a stored postal drop out; callers fall back to city targeting
    when the whole list comes back empty. Cached in ``geo_data["target_zips"]``
    so a plan-edit rebuild reuses it.
    """
    cached = geo_data.get("target_zips")
    if cached is not None:
        return list(cached)

    pois = geo_data.get("targetable_pois") or []
    keys: set[str] = set()
    for p in pois:
        k = _poi_zip_key(p)
        if k:
            keys.add(k)

    zips = sorted(keys)
    missing = sum(1 for p in pois if _poi_zip_key(p) is None)
    if missing:
        logger.info("resolve_poi_zips: %d/%d POIs had no postal code", missing, len(pois))
    logger.info("resolve_poi_zips: %d POIs → %d unique zips", len(pois), len(zips))
    geo_data["target_zips"] = zips
    return zips


# ── LLM helper ───────────────────────────────────────────────────────────────


def _make_llm(temperature: float = 0.0, model: str | None = None) -> ChatGoogleGenerativeAI:
    """Lightweight Gemini instance for tool-internal LLM calls. Flash tier."""
    return ChatGoogleGenerativeAI(
        model=model or settings.GEMINI_MODEL,
        **settings.llm_auth,
        temperature=temperature,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────


def _bbox_for_radius_km(
    lat: float, lng: float, radius_km: float
) -> tuple[float, float, float, float]:
    """Approximate bounding box. Returns (lat_min, lat_max, lng_min, lng_max)."""
    delta_lat = radius_km / 111.0
    cos_lat = math.cos(math.radians(lat)) if lat != 0 else 1.0
    delta_lng = radius_km / (111.0 * cos_lat)
    return (lat - delta_lat, lat + delta_lat, lng - delta_lng, lng + delta_lng)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres between two lat/lng points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bbox_diagonal_km(bounds: Dict[str, float]) -> float:
    """Diagonal length (km) of a bounds dict {lat_min,lat_max,lng_min,lng_max}."""
    return _haversine_km(
        bounds["lat_min"], bounds["lng_min"],
        bounds["lat_max"], bounds["lng_max"],
    )


def _normalize_bbox(b: Optional[Dict[str, float]]) -> Optional[Dict[str, float]]:
    """Un-invert a bbox whose longitude span crosses the antimeridian.

    Google's US viewport reaches the Aleutians, so it comes back as
    lng_min=167.0 > lng_max=-66.9. Left as-is that breaks POI search twice over:
    `_tile_bbox` divides a NEGATIVE span into negative-width rectangles (which
    Places rejects as low.longitude > high.longitude), and `_point_in_bounds`
    reduces to `167.0 <= lng <= -66.9` — False for every point on Earth. Net
    effect: zero POIs for any bbox-based angle at US/RU/NZ/FJ scope.

    ponytail: keeps the WIDER half instead of splitting into two boxes — for the
    US that keeps [-180, -66.9] (CONUS + mainland Alaska + Hawaii) and drops only
    the far Aleutian slivers. Split into two boxes if a Pacific-straddling market
    ever matters.
    """
    if b and b["lng_min"] > b["lng_max"]:
        east = 180.0 - b["lng_min"]   # lng_min → +180
        west = b["lng_max"] + 180.0   # -180 → lng_max
        b = {**b, **({"lng_min": -180.0} if west >= east else {"lng_max": 180.0})}
    return b


def _tile_bbox(bounds: Dict[str, float], max_tiles: int) -> List[Dict[str, float]]:
    """
    Split a bounds box into a grid of <= max_tiles sub-rectangles.

    Picks an n×n grid where n = floor(sqrt(max_tiles)) (>=1), giving square-ish
    tiles. Returns a list of {lat_min,lat_max,lng_min,lng_max} sub-boxes.
    """
    n = max(1, int(math.isqrt(max(1, max_tiles))))
    lat_min, lat_max = bounds["lat_min"], bounds["lat_max"]
    lng_min, lng_max = bounds["lng_min"], bounds["lng_max"]
    lat_step = (lat_max - lat_min) / n
    lng_step = (lng_max - lng_min) / n
    tiles: List[Dict[str, float]] = []
    for i in range(n):
        for j in range(n):
            tiles.append({
                "lat_min": lat_min + i * lat_step,
                "lat_max": lat_min + (i + 1) * lat_step,
                "lng_min": lng_min + j * lng_step,
                "lng_max": lng_min + (j + 1) * lng_step,
            })
    return tiles


async def _nominatim_geocode(location_name: str) -> Dict[str, Any]:
    """Free geocoding via OpenStreetMap Nominatim."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        async def _do_request():
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": location_name, "format": "json", "limit": 1, "addressdetails": 1},
                headers={"User-Agent": "punkAI-campaign-builder/2.0"},
            )
            resp.raise_for_status()
            return resp.json()

        try:
            results = await _with_retry(_do_request, max_attempts=3, base_delay=1.0)
            if results:
                hit = results[0]
                logger.info("Nominatim geocode OK: %s", location_name)
                # Nominatim boundingbox = [lat_min, lat_max, lng_min, lng_max] (strings).
                bounds: Optional[Dict[str, float]] = None
                bb = hit.get("boundingbox")
                if isinstance(bb, (list, tuple)) and len(bb) == 4:
                    try:
                        bounds = {
                            "lat_min": float(bb[0]), "lat_max": float(bb[1]),
                            "lng_min": float(bb[2]), "lng_max": float(bb[3]),
                        }
                    except (TypeError, ValueError):
                        bounds = None
                _display = hit.get("display_name", location_name)
                _nom_addr = hit.get("address") or {}
                _nom_locality = (
                    _nom_addr.get("city") or _nom_addr.get("town")
                    or _nom_addr.get("village") or _nom_addr.get("county")
                    or (_display.split(",")[0].strip() if _display else None)
                )
                return {
                    "location_name": location_name,
                    "formatted_address": _display,
                    "locality": _nom_locality or None,
                    "latitude": float(hit["lat"]),
                    "longitude": float(hit["lon"]),
                    "is_city": hit.get("addresstype") in ("city", "town", "county"),
                    "place_type": hit.get("addresstype"),
                    "place_id": f"osm:{hit.get('osm_type', '?')}:{hit.get('osm_id', '?')}",
                    "bounds": bounds,
                    "country_name": _nom_addr.get("country") or None,
                    "admin_area1_name": _nom_addr.get("state") or None,
                    "postal_code": str(_nom_addr.get("postcode") or "").strip().upper(),
                    "country_code": str(_nom_addr.get("country_code") or "").strip().upper(),
                    "_source": "nominatim",
                }
        except Exception as exc:
            logger.error("Nominatim geocoding failed after retries: %s", exc)

    return {
        "location_name": location_name,
        "latitude": None,
        "longitude": None,
        "error": "geocoding_failed",
    }


# addressComponent types that carry a place's locality identity. Used to match a
# POI to a borough/city reliably: Manhattan places read "New York" in their
# formattedAddress but carry a `sublocality` component = "Manhattan", so a
# formatted-string match wrongly drops them. Structured components fix that.
_LOCALITY_COMPONENT_TYPES: frozenset[str] = frozenset({
    "locality", "sublocality", "sublocality_level_1",
    "postal_town", "administrative_area_level_2", "neighborhood",
})

# State/province component type — the level ABOVE locality, used to stop a
# metro-sized city's bbox from bleeding across a state line (NYC → New Jersey).
_STATE_COMPONENT_TYPES: frozenset[str] = frozenset({
    "administrative_area_level_1",
})


def _extract_components_text(
    components: List[Dict[str, Any]], want_types: frozenset
) -> List[str]:
    """Collect the long+short text of the addressComponents whose ``types``
    intersect ``want_types`` (Places API New uses ``longText``/``shortText``).
    Returns raw strings (normalization happens at match time); empty when absent."""
    tokens: List[str] = []
    for comp in components or []:
        if set(comp.get("types", []) or []) & want_types:
            for key in ("longText", "shortText"):
                val = comp.get(key)
                if val:
                    tokens.append(val)
    return tokens


def _extract_locality_tokens(components: List[Dict[str, Any]]) -> List[str]:
    """Locality-ish tokens (locality/sublocality/…) of a Places result."""
    return _extract_components_text(components, _LOCALITY_COMPONENT_TYPES)


def _extract_state_tokens(components: List[Dict[str, Any]]) -> List[str]:
    """State/province tokens (administrative_area_level_1) of a Places result."""
    return _extract_components_text(components, _STATE_COMPONENT_TYPES)


def _extract_postal_and_country(components: List[Dict[str, Any]]) -> tuple[str, str]:
    """(postal_code, country ISO2) from a Places New addressComponents list.

    Meta geo targeting keys are ``<ISO2>:<postal>`` (US ZIP, Canada FSA). Both
    components ship in the same ``searchText`` response the POI search already
    makes — extracting them here is why no second reverse-geocode pass is needed.
    Returns ``("", "")`` when either is absent."""
    postal = country = ""
    for comp in components or []:
        types = set(comp.get("types", []) or [])
        if "postal_code" in types:
            postal = str(comp.get("shortText") or comp.get("longText") or "").strip().upper()
        elif "country" in types:
            country = str(comp.get("shortText") or "").strip().upper()
    return postal, country


async def _google_places_text_search(
    query: str,
    lat: float,
    lng: float,
    radius_meters: Optional[float] = None,
    max_results: int = 20,
    location_restriction: Optional[Dict[str, float]] = None,
    included_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Core Google Places Text Search (New) API call.

    Returns a list of place dicts with name, lat, lng, types.
    Uses google_maps_api_key for authentication.

    Spatial constraint precedence:
      - location_restriction (a {lat_min,lat_max,lng_min,lng_max} box) → hard
        locationRestriction.rectangle (results MUST fall inside the box).
      - else radius_meters → soft locationBias circle around (lat, lng).
      - else neither → text-relevance only.

    ``included_type`` restricts results server-side to one Places type (see
    ``poi_type_rules.primary_type``) — Google never returns the brewery/
    apartment/rest-stop for "dog park" in the first place, instead of us
    discarding it after the fact. Places rejects the WHOLE request (HTTP 400,
    non-retryable) if the value is unrecognized; on that failure (only on the
    FIRST page — a later page's failure is a transient/quota issue, already
    covered by ``_with_retry``, not an enum problem) this retries once with
    ``included_type`` dropped, so a stale/mistyped type value degrades to
    plain text search rather than silently zeroing a real category.

    Paginates via nextPageToken up to GEO_POI_MAX_PAGES so a single query can
    return more than the 20-result per-page cap.
    """
    if not settings.GOOGLE_MAPS_API_KEY:
        logger.warning("google_maps_api_key not set - cannot search Places")
        return []

    results: List[Dict[str, Any]] = []
    headers = {
        "X-Goog-Api-Key": settings.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": (
            "places.displayName,places.location,"
            "places.types,places.formattedAddress,"
            "places.addressComponents,places.rating,places.userRatingCount,"
            "nextPageToken"
        ),
        # rating/userRatingCount move this call from Text Search Pro ($32/1k)
        # to Enterprise ($35/1k) — +9%, no new API surface. Place Details by
        # place_id was priced out instead (~$20/1k POIs vs ~$1.75/1k for this
        # bump, since one call here already bundles up to 20 places) — see
        # poi_selection.py's module docstring for the ranking this buys.
        # Shared by geocode_or_place's _resolve too, so that path pays the
        # same tier — low call volume there, not worth a second fieldmask.
        "Content-Type": "application/json",
    }

    base_payload: Dict[str, Any] = {
        "textQuery": query,
        "maxResultCount": min(max_results, 20),
    }
    if included_type:
        base_payload["includedType"] = included_type
    if location_restriction is not None:
        base_payload["locationRestriction"] = {
            "rectangle": {
                "low": {
                    "latitude": location_restriction["lat_min"],
                    "longitude": location_restriction["lng_min"],
                },
                "high": {
                    "latitude": location_restriction["lat_max"],
                    "longitude": location_restriction["lng_max"],
                },
            }
        }
    elif radius_meters is not None:
        base_payload["locationBias"] = {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": float(radius_meters),
            }
        }

    max_pages = max(1, int(getattr(settings, "GEO_POI_MAX_PAGES", 1)))
    async with httpx.AsyncClient(timeout=15.0) as client:
        page_token: Optional[str] = None

        for _page in range(max_pages):
            payload = dict(base_payload)
            if page_token:
                payload["pageToken"] = page_token

            async def _do_places_request():
                resp = await client.post(
                    "https://places.googleapis.com/v1/places:searchText",
                    headers=headers,
                    json=payload,
                )
                record_api_call("places_text_search")
                if resp.status_code in _RETRYABLE_HTTP_CODES:
                    raise httpx.HTTPStatusError(
                        f"Retryable status {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                if not resp.is_success:
                    logger.error("Google Places error: %d %s", resp.status_code, resp.text[:200])
                    return None
                return resp.json()

            try:
                data = await _with_retry(_do_places_request, max_attempts=3, base_delay=1.0)
            except Exception as exc:
                logger.error("Google Places Text Search failed after retries: %s", exc)
                break

            if data is None:
                if included_type and _page == 0:
                    logger.warning(
                        "Places includedType=%r rejected for %r — retrying as plain text search",
                        included_type, query,
                    )
                    return await _google_places_text_search(
                        query=query, lat=lat, lng=lng,
                        radius_meters=radius_meters, max_results=max_results,
                        location_restriction=location_restriction,
                        included_type=None,
                    )
                break
            for p in data.get("places", []):
                name_text = p.get("displayName", {}).get("text", "Unknown")
                loc = p.get("location", {})
                _components = p.get("addressComponents", [])
                _postal, _country = _extract_postal_and_country(_components)
                results.append({
                    "name": name_text,
                    "lat": loc.get("latitude"),
                    "lng": loc.get("longitude"),
                    "types": p.get("types", []),
                    "address": p.get("formattedAddress", ""),
                    "postal_code": _postal,
                    "country_code": _country,
                    "locality_tokens": _extract_locality_tokens(_components),
                    "state_tokens": _extract_state_tokens(_components),
                    # None (not 0.0) when unrated — "never rated" must stay
                    # distinguishable from "rated zero" for the narrator and
                    # for poi_selection's Bayesian scorer (n=0 collapses the
                    # formula to the pool mean regardless of `rating`).
                    "rating": p.get("rating"),
                    "user_ratings_total": int(p.get("userRatingCount") or 0),
                })
            page_token = data.get("nextPageToken")
            if not page_token or len(results) >= max_results:
                break

    return results[:max_results]


# ── Tool: geocode_location ────────────────────────────────────────────────────


def _select_geocode_result(
    results: List[Dict[str, Any]], scope: Optional[str]
) -> Dict[str, Any]:
    """
    Pick the result whose types best match the requested scope, instead of
    blindly taking results[0]. Falls back to results[0] when scope is None or no
    candidate matches the preference. (e.g. scope="admin_areas" + "Quebec"
    selects the administrative_area_level_1 province over the locality.)
    """
    prefs = _SCOPE_TYPE_PREFERENCE.get(scope or "")
    if prefs:
        for pref_type in prefs:
            for r in results:
                if pref_type in r.get("types", []):
                    return r
    return results[0]


def _extract_bounds_from_geometry(geometry: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Extract a {lat_min,lat_max,lng_min,lng_max} box from a Google geometry.

    Prefers ``bounds`` (true extent), falls back to ``viewport``.
    """
    box = geometry.get("bounds") or geometry.get("viewport")
    if not box:
        return None
    try:
        sw, ne = box["southwest"], box["northeast"]
        return {
            "lat_min": float(sw["lat"]), "lat_max": float(ne["lat"]),
            "lng_min": float(sw["lng"]), "lng_max": float(ne["lng"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _canonical_locality(
    result: Optional[Dict[str, Any]], formatted_address: str
) -> Optional[str]:
    """Resolve the canonical city/locality token for locality_filter matching.

    Prefers Google ``address_components`` (locality → postal_town →
    administrative_area_level_2 → sublocality); falls back to the first
    comma-token of ``formatted_address``. This is the geocoder's RESOLVED name,
    not the raw user input — so a typo'd query ("ney york") still yields the real
    city ("New York") and does not wipe every POI in _address_in_locality.
    """
    _pref = (
        "locality", "postal_town",
        "administrative_area_level_2", "sublocality",
    )
    components = (result or {}).get("address_components", []) or []
    for pref_type in _pref:
        for comp in components:
            if pref_type in (comp.get("types", []) or []):
                name = comp.get("long_name") or comp.get("short_name")
                if name:
                    return name
    token = (formatted_address or "").split(",")[0].strip()
    return token or None


def _country_name(result: Optional[Dict[str, Any]]) -> Optional[str]:
    """Resolve the country ``long_name`` (e.g. "Canada", "United States") from a
    Google Geocoding result's ``address_components``.

    Used to build the country string-filter that stops a large admin-area's
    axis-aligned bounding box from bleeding POIs across an international border
    (e.g. Ontario province's bbox physically contains Chicago/Minneapolis). We
    deliberately keep only the long name — the ISO short (Canada → "CA") collides
    with California's abbreviation and would let US POIs pass a Canada filter.
    """
    for comp in (result or {}).get("address_components", []) or []:
        if "country" in (comp.get("types", []) or []):
            name = comp.get("long_name")
            if name:
                return name
    return None


def _admin_area1_name(result: Optional[Dict[str, Any]]) -> Optional[str]:
    """Resolve the state/province ``long_name`` (e.g. "New York", "New Jersey")
    from a Google Geocoding result's ``address_components``.

    Used to build the state string-filter that stops a metro-sized city's bbox
    from bleeding POIs across a STATE line — New York City's bounding box reaches
    west across the Hudson into New Jersey (Jersey City/Hoboken sit inside the
    rectangle), and the metro-relax that nulls the locality filter would otherwise
    leave those unguarded. One admin level below ``_country_name``."""
    for comp in (result or {}).get("address_components", []) or []:
        if "administrative_area_level_1" in (comp.get("types", []) or []):
            name = comp.get("long_name")
            if name:
                return name
    return None


def _google_result_to_location(location_name: str, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert one Google Geocoding result into the canonical location dict
    shared by ``geocode_location`` and ``probe_location_candidates``.

    Returns ``None`` for a malformed/partial result (missing ``geometry`` /
    ``geometry.location`` / ``formatted_address`` / a numeric lat+lng) instead of
    raising — a Google response arm is not always the well-formed geocode shape, and
    an unguarded subscript here propagates out of the probe fan-out
    (``asyncio.gather`` with no ``return_exceptions``) and crashes the whole act.
    Callers already skip falsy results."""
    geometry = result.get("geometry") or {}
    loc = geometry.get("location") or {}
    formatted_address = result.get("formatted_address")
    if loc.get("lat") is None or loc.get("lng") is None or not formatted_address:
        logger.warning(
            "Skipping malformed geocode result for %s (types=%s, keys=%s)",
            location_name, result.get("types"), sorted(result.keys()),
        )
        return None
    types = result.get("types", [])
    is_city = any(
        t in {"locality", "administrative_area_level_2", "administrative_area_level_3"}
        for t in types
    )
    # place_type = the most relevant admin/locality type for this result.
    _known_types = (
        "country", "administrative_area_level_1", "administrative_area_level_2",
        "administrative_area_level_3", "locality", "postal_code",
        "neighborhood", "sublocality", "street_address", "premise",
    )
    place_type = next((t for t in _known_types if t in types), types[0] if types else None)
    _postal, _country = _geocode_postal_and_country(result.get("address_components") or [])
    return {
        "location_name": location_name,
        "formatted_address": formatted_address,
        "locality": _canonical_locality(result, formatted_address),
        "latitude": loc["lat"],
        "longitude": loc["lng"],
        "is_city": is_city,
        "place_type": place_type,
        "place_id": result.get("place_id"),
        "bounds": _extract_bounds_from_geometry(geometry),
        "country_name": _country_name(result),
        "admin_area1_name": _admin_area1_name(result),
        "postal_code": _postal,
        "country_code": _country,
    }


def _geocode_postal_and_country(components: List[Dict[str, Any]]) -> tuple[str, str]:
    """(postal_code, country ISO2) from a classic Google Geocoding result's
    ``address_components`` (``long_name``/``short_name``/``types``). Distinct from
    the Places New shape read by ``_extract_postal_and_country``."""
    postal = country = ""
    for comp in components or []:
        types = set(comp.get("types", []) or [])
        if "postal_code" in types:
            postal = str(comp.get("short_name") or comp.get("long_name") or "").strip().upper()
        elif "country" in types:
            country = str(comp.get("short_name") or "").strip().upper()
    return postal, country


def _build_geocode_params(
    location_name: str, scope: Optional[str], api_key: str
) -> Dict[str, str]:
    """
    Build Google Geocoding query params.

    For region scopes (admin_areas / country_groups) use the ``components`` filter
    to FORCE region resolution: a bare admin-area name like "Quebec" otherwise
    resolves to the same-named city (Google returns one best result, the locality).
    components is sent WITHOUT ``address`` — putting the same value in both yields
    ZERO_RESULTS. For all other scopes the plain ``address`` query is used.
    """
    if scope == "admin_areas":
        parts = [p.strip() for p in location_name.split(",") if p.strip()]
        comps = [f"administrative_area:{parts[0] if parts else location_name}"]
        if len(parts) > 1:
            comps.append(f"country:{parts[-1]}")
        return {"components": "|".join(comps), "key": api_key}
    if scope == "country_groups":
        return {"components": f"country:{location_name}", "key": api_key}
    return {"address": location_name, "key": api_key}


async def _geocode_core(
    location_name: str, allow_broad: bool = False, scope: Optional[str] = None,
    osm_fallback: bool = True,
) -> Dict[str, Any]:
    """Address-geocoding core shared by ``geocode_location`` and ``geocode_or_place``.

    Google Geocoding API with a Nominatim (OpenStreetMap) fallback. Plain async fn
    (no ``@tool``) so ``geocode_or_place`` can call it without a nested tool
    invocation. See ``geocode_location`` for the argument/return contract.

    ``osm_fallback=False`` makes a Google miss a clean ``geocoding_failed`` result
    instead of an OSM first-hit — for callers (event venues) that pay per point and
    would rather drop an unresolved venue than target a guessed one.
    """
    async def _osm() -> Dict[str, Any]:
        if osm_fallback:
            return await _nominatim_geocode(location_name)
        return {"location_name": location_name, "latitude": None, "longitude": None,
                "error": "geocoding_failed"}

    if not settings.GOOGLE_MAPS_API_KEY:
        logger.warning("google_maps_api_key not set - falling back to Nominatim")
        return await _osm()

    async with httpx.AsyncClient(timeout=10.0) as client:
        async def _do_geocode_request(params: Dict[str, str]):
            resp = await client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params=params,
            )
            record_api_call("geocoding")
            resp.raise_for_status()
            return resp.json()

        try:
            params = _build_geocode_params(location_name, scope, settings.GOOGLE_MAPS_API_KEY)
            data = await _with_retry(
                lambda: _do_geocode_request(params), max_attempts=3, base_delay=1.0
            )
            api_status = data.get("status", "")

            # Region-forcing components query missed → retry as a plain address query
            # so odd inputs still resolve (then Nominatim below if that also fails).
            if "components" in params and (api_status != "OK" or not data.get("results")):
                logger.info(
                    "Components geocode for %s returned %s — falling back to address query",
                    location_name, api_status or "no results",
                )
                params = {"address": location_name, "key": settings.GOOGLE_MAPS_API_KEY}
                data = await _with_retry(
                    lambda: _do_geocode_request(params), max_attempts=3, base_delay=1.0
                )
                api_status = data.get("status", "")

            if api_status not in ("OK", "ZERO_RESULTS"):
                logger.error("Geocoding API error (%s) - falling back to Nominatim", api_status)
                return await _osm()

            if data["results"]:
                result = _select_geocode_result(data["results"], scope)
                types = result.get("types", [])

                broad_types = {"country", "administrative_area_level_1", "continent"}
                if not allow_broad and any(t in broad_types for t in types):
                    logger.warning("Geocoding scope too large for %s: %s", location_name, types)
                    return {
                        "location_name": location_name,
                        "error": "scope_too_large",
                        "message": (
                            "Location scope is too broad (country or state). "
                            "Please provide a more specific location."
                        ),
                    }

                mapped = _google_result_to_location(location_name, result)
                if mapped is not None:
                    return mapped
                logger.warning("Malformed Google result for %s - trying Nominatim", location_name)
                return await _osm()
            else:
                logger.warning("Geocoding zero results for %s - trying Nominatim", location_name)
                return await _osm()

        except Exception as exc:
            logger.error("Geocoding failed after retries — falling back to Nominatim: %s", exc)
            return await _osm()


@tool
async def geocode_location(
    location_name: str, allow_broad: bool = False, scope: Optional[str] = None
) -> Dict[str, Any]:
    """
    Convert a human-readable location to lat/lng coordinates.

    Uses Google Geocoding API with Nominatim (OpenStreetMap) fallback.
    Returns scope_too_large error for country/state-level results unless allow_broad is True.

    Args:
        location_name: Human-readable place name (e.g. "Austin, TX", "21 Baker St, London").
        allow_broad: If True, allow country/state-level results (e.g. "Canada", "Texas").
        scope: Optional canonical targeting key ("admin_areas", "granular_local",
            "country_groups", "radius") used to disambiguate which result to pick
            when Google returns several (e.g. province vs. city of the same name).

    Returns:
        Dict with location_name, formatted_address, latitude, longitude, is_city,
        place_type (matched admin level), and bounds (extent box) when available.
    """
    return await _geocode_core(location_name, allow_broad, scope)


# Google always tags a business/POI reverse-geocode entry with one of these
# two umbrella types (regardless of its specific category — "restaurant",
# "cafe", ...), and tags an address-level entry with one of the rest. A pin
# label wants a PLACE NAME (city/town/neighbourhood), never "Joe's Diner" or
# "123 Main St" — excluding these two umbrella tags is exhaustive; no need to
# enumerate every POI category Google has.
_POI_OR_ADDRESS_TYPES = frozenset({
    "point_of_interest", "establishment", "premise", "subpremise",
    "street_address", "route", "plus_code",
})

# Preferred order for PICKING THE LABEL off the winning result's own
# address_components (a result can carry more than one of these — e.g. a
# "locality" entry is also "political"). Not used to pick WHICH result wins
# (that's the POI/address exclusion above) — Google already orders surviving
# results most-to-least specific, so the first survivor is correct.
_PLACE_LABEL_TYPES = (
    "neighborhood", "sublocality", "locality", "postal_town",
    "administrative_area_level_3", "administrative_area_level_2",
)


def _component_long_name(components: Optional[List[Dict[str, Any]]], wanted_type: str) -> Optional[str]:
    for c in components or []:
        if wanted_type in (c.get("types") or []):
            return c.get("long_name")
    return None


async def reverse_geocode_point(lat: float, lng: float) -> Optional[Dict[str, Any]]:
    """Reverse-geocode a raw map coordinate (a user-dropped or dragged pin)
    into a short place label — a city/town/neighbourhood NAME, never a
    business or street address — for naming a pin+radius location the user
    positioned themselves rather than searched by name.

    Google Geocoding's ``latlng=`` reverse lookup first (same provider the
    forward path uses), Nominatim's ``/reverse`` as a fallback — mirrors
    ``_geocode_core``'s own fallback chain. Returns the canonical location
    dict shape (``_google_result_to_location``) on a Google hit; a minimal
    dict with just the fields a pin label needs on a Nominatim hit. ``None``
    on total failure — callers keep whatever generic label they already had,
    never block pin creation on this.
    """
    if settings.GOOGLE_MAPS_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/geocode/json",
                    params={"latlng": f"{lat},{lng}", "key": settings.GOOGLE_MAPS_API_KEY},
                )
                results = (resp.json() or {}).get("results") or []
        except Exception:
            logger.warning("reverse_geocode_point: Google lookup failed for %s,%s", lat, lng, exc_info=True)
            results = []
        # Google orders reverse-geocode results most-to-least specific
        # (nearest POI/address first, country last). Drop every POI/address
        # entry FIRST, then take whatever real administrative/locality entry
        # is left at the front — filtering before picking, not picking
        # results[0] and hoping it wasn't a business.
        candidates = [r for r in results if not (_POI_OR_ADDRESS_TYPES & set(r.get("types") or []))]
        if candidates:
            preferred = candidates[0]
            loc = _google_result_to_location(f"{lat:.5f},{lng:.5f}", preferred)
            if loc:
                label = None
                for _t in _PLACE_LABEL_TYPES:
                    label = _component_long_name(preferred.get("address_components"), _t)
                    if label:
                        break
                # The reverse-geocoded PLACE is the label here, not the
                # input coordinate string _google_result_to_location stamped
                # as location_name (that's only meaningful for a forward,
                # name-driven geocode).
                loc["location_name"] = label or loc["formatted_address"].split(",")[0]
                return loc
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lng, "format": "jsonv2"},
                headers={"User-Agent": "punk-ai/1.0 (hello@usepunk.ai)"},
            )
            data = resp.json() or {}
    except Exception:
        logger.warning("reverse_geocode_point: Nominatim lookup failed for %s,%s", lat, lng, exc_info=True)
        return None
    addr = data.get("address") or {}
    name = (
        addr.get("neighbourhood") or addr.get("suburb") or addr.get("city")
        or addr.get("town") or addr.get("village") or addr.get("county")
    )
    if not name:
        return None
    return {
        "location_name": name,
        "formatted_address": data.get("display_name") or name,
        "latitude": lat, "longitude": lng,
        "is_city": False, "place_type": None,
    }


def _place_to_location(query: str, place: Dict[str, Any]) -> Dict[str, Any]:
    """Adapt one ``_google_places_text_search`` result into the canonical location
    dict shape (identical keyset to ``_google_result_to_location``), so a Places
    business hit drops into every ``result.get("latitude")`` gate and the anchor
    caches unchanged. A business is a point → ``is_city`` False, no ``bounds``.
    """
    locality_tokens = place.get("locality_tokens") or []
    state_tokens = place.get("state_tokens") or []
    return {
        "location_name": place.get("name") or query,
        "formatted_address": place.get("address") or "",
        "locality": locality_tokens[0] if locality_tokens else None,
        "latitude": place.get("lat"),
        "longitude": place.get("lng"),
        "is_city": False,
        "place_type": "establishment",
        "place_id": None,
        "bounds": None,
        "country_name": None,
        "admin_area1_name": state_tokens[0] if state_tokens else None,
        "postal_code": place.get("postal_code", ""),
        "country_code": place.get("country_code", ""),
    }


@tool
async def geocode_or_place(
    location_name: str, allow_broad: bool = False, scope: Optional[str] = None,
    market_hint: str = "", allow_coarse: bool = False,
) -> Dict[str, Any]:
    """Resolve ONE store/competitor ANCHOR — a business name ("shawarmaz st
    catherine") or a street address ("1055 Canada Pl, Vancouver") — to a pin.
    Same dict shape as ``geocode_location``, plus ``market_mismatch``. NOT for
    city/region scope: a bare "Montreal" must resolve to the city, not a random
    Montreal business, so location-scope callers stay on ``geocode_location``.

    Places Text Search runs FIRST because it returns the place's CANONICAL name;
    the geocoder copies the query straight back into ``location_name``, so a shop
    entered as "its in SKS tower in mohakhali" was mapped under that sentence.
    Address geocode is the fallback, and its echo is overridden with the resolved
    address — the only honest label it can offer.

    ``market_hint`` is the market the user named. It is NOT appended to the query:
    that pinned "..., Montreal" onto a Dhaka address and carried the user's typos
    ("Toronro") into Google. It is used only (a) as a RETRY suffix when the bare
    lookup misses entirely, and (b) to set ``market_mismatch`` — the resolved
    address when it does not sit in the named market, else "". Callers warn on it;
    they never block, since a shop abroad from the stated market is legitimate.

    ``allow_coarse``: permit a last-resort geocode of the hint alone (a city
    centroid) so a vague pin still emits. Owned-store callers leave it False so a
    store miss stays a miss.
    """
    hint = (market_hint or "").strip()
    miss: Dict[str, Any] = {
        "location_name": location_name, "latitude": None, "longitude": None,
        "error": "geocoding_failed",
    }

    async def _resolve(query: str) -> Optional[Dict[str, Any]]:
        nonlocal miss
        places = await _google_places_text_search(query=query, lat=0.0, lng=0.0)
        # ponytail: top text-search hit wins. For a vague BUILDING name the top
        # hit can be a tenant inside it ("SKS Tower" -> "Secret Recipe ... SKS
        # Tower Outlet"), and Places ranking is not stable across calls. The
        # confirm map shows this name beside the resolved address and the address
        # stays editable, so the user catches it. If that proves too loose,
        # re-rank `places` by token overlap with the typed string before taking [0].
        if places and places[0].get("lat") is not None:
            logger.info("geocode_or_place: Places resolved %r", query)
            return _place_to_location(query, places[0])
        base = await _geocode_core(query, allow_broad, scope)
        if isinstance(base, dict) and base.get("latitude"):
            # The geocode arm echoes the query into location_name; the resolved
            # address is the only honest label. Places already returns one.
            base["location_name"] = base.get("formatted_address") or query
            return base
        if isinstance(base, dict):
            miss = base          # keep the richest miss dict (scope_too_large, ...)
        return None

    hit = await _resolve(location_name)
    if hit is None and hint:
        hit = await _resolve(f"{location_name}, {hint}")
    if hit is None and hint and allow_coarse:
        coarse = await _geocode_core(hint, allow_broad, scope)
        if isinstance(coarse, dict) and coarse.get("latitude"):
            logger.info(
                "geocode_or_place: coarse fallback %r for unresolved %r", hint, location_name
            )
            hit = coarse
    if hit is None:
        return miss

    # Containment, warn-only. Reuses the POI-filter matcher: accent-, suffix- and
    # bilingual-tolerant, and lenient on empties so it never raises a false alarm.
    _addr = hit.get("formatted_address") or ""
    hit["market_mismatch"] = (
        _addr if hint and not _address_in_locality(_addr, hint) else ""
    )
    return hit


# ── Location-name disambiguation (geocode-first) ─────────────────────────────
# Ambiguous bare names ("Quebec", "New York", "Georgia") denote several real
# entities (city vs province vs country). Instead of guessing the scope before
# geocoding, probe Google for every entity the name resolves to, then let an
# LLM tiebreak (or the user) pick among ENUMERATED candidates.

_PLACE_TYPE_LABELS: dict[str, str] = {
    "locality": "city",
    "postal_town": "town",
    "administrative_area_level_1": "state/province (entire region)",
    "administrative_area_level_2": "county/region",
    "administrative_area_level_3": "district",
    "country": "country (entire country)",
    "neighborhood": "neighborhood",
    "sublocality": "neighborhood",
    "postal_code": "postal code",
    "street_address": "street address",
    "premise": "building",
}


def _candidate_label(candidate: Dict[str, Any]) -> str:
    """Human-readable option label for the disambiguation widget."""
    type_label = _PLACE_TYPE_LABELS.get(candidate.get("place_type") or "", "place")
    return f"{candidate.get('formatted_address') or candidate.get('location_name')} — {type_label}"


# Arms whose top result is only accepted when it genuinely IS an admin region.
# Google biases a bare name to its most-prominent entity (usually a city), so
# `components=administrative_area:{name}` returns the CITY, not the state — the
# old arm was dead weight that always deduped away. The reliable way to surface
# the region entity with a DISTINCT place_id is the "{name} State"/"{name}
# Province" address query; we gate its result on the admin type so a spurious
# match ("Brooklyn State") cannot inject a fake region candidate.
_ADMIN_REGION_TYPES: frozenset[str] = frozenset({
    "administrative_area_level_1", "administrative_area_level_2",
})
# Same story for the country entity: `components=country:{name}` returns
# ZERO_RESULTS (it filters, it doesn't look up), so a shared name like "Georgia"
# (US state vs country) never surfaced the country. The "{name} country" address
# variant does — gated on the country type so "New York country" (→ New York
# County) or "Paris country" (→ the city) cannot inject a false country.
_COUNTRY_TYPES: frozenset[str] = frozenset({"country"})


async def probe_location_candidates(location_name: str) -> List[Dict[str, Any]]:
    """Enumerate every real place a bare name could mean.

    Runs, in parallel: the plain address query, a locality-forced query, and
    three name-variant queries ("{name} State" / "{name} Province" / "{name}
    country") — then dedupes the top result of each arm by ``place_id``. The
    variant arms are gated on a type (see ``_ADMIN_REGION_TYPES`` /
    ``_COUNTRY_TYPES``): Google resolves a bare "New York" to the city on every
    component arm and `components=country/administrative_area` filters return
    nothing, so a name variant is the only way to surface the state or country
    as a separate candidate — and the type gate stops that variant from
    injecting a false region ("Montreal State") or country ("Paris country").
    A ZERO_RESULTS or gated-out arm contributes nothing (a city name has no
    state/country entity — expected and cheap). No ``allow_broad`` guard:
    candidates are presented as-is; picking the province IS the point.

    Returns candidate dicts in the ``geocode_location`` shape plus ``place_id``
    and a human-readable ``label``. Empty list when the API key is missing or
    every arm misses (caller falls back to ``geocode_location``).
    """
    if not settings.GOOGLE_MAPS_API_KEY:
        return []

    # (params, require_types): require_types=None accepts any top result;
    # a frozenset only accepts a result whose types intersect it.
    arm_specs: List[tuple[Dict[str, str], Optional[frozenset[str]]]] = [
        ({"address": location_name}, None),
        ({"components": f"locality:{location_name}"}, None),
        ({"address": f"{location_name} State"}, _ADMIN_REGION_TYPES),
        ({"address": f"{location_name} Province"}, _ADMIN_REGION_TYPES),
        ({"address": f"{location_name} country"}, _COUNTRY_TYPES),
    ]

    async with httpx.AsyncClient(timeout=10.0) as client:
        async def _probe_arm(
            params: Dict[str, str], require: Optional[frozenset[str]]
        ) -> Optional[Dict[str, Any]]:
            full = {**params, "key": settings.GOOGLE_MAPS_API_KEY}

            async def _do_request():
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/geocode/json", params=full,
                )
                record_api_call("geocoding")
                resp.raise_for_status()
                return resp.json()

            try:
                data = await _with_retry(_do_request, max_attempts=2, base_delay=1.0)
            except Exception as exc:
                logger.warning("Probe geocode arm %s failed: %s", params, exc)
                return None
            if data.get("status") != "OK":
                return None
            results = data.get("results") or []
            if not results:
                return None
            top = results[0]  # one interpretation per arm
            if require is not None and not (require & set(top.get("types", []))):
                return None
            return top

        arm_results = await asyncio.gather(
            *(_probe_arm(ps, req) for ps, req in arm_specs)
        )

    candidates: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for result in arm_results:
        if not result:
            continue
        pid = result.get("place_id") or result.get("formatted_address") or ""
        if pid in seen_ids:
            continue
        seen_ids.add(pid)
        candidate = _google_result_to_location(location_name, result)
        if candidate is None:  # malformed arm result — skip, never crash the probe
            continue
        candidate["label"] = _candidate_label(candidate)
        candidates.append(candidate)
    return candidates


async def disambiguate_location_candidates(
    candidates: List[Dict[str, Any]],
    business_desc: str = "",
    det_type: str = "",
    sibling_locations: Optional[List[str]] = None,
    target_audience: str = "",
    location_scope: str = "",
) -> tuple[int, float]:
    """LLM tiebreak among enumerated geocode candidates.

    Returns ``(chosen_index, confidence)``. Any failure returns ``(0, 0.0)`` so
    the caller falls through to asking the user — never a silent guess.
    """
    if not candidates:
        return (0, 0.0)
    if len(candidates) == 1:
        return (0, 1.0)

    listing = "\n".join(
        f"  {i}. {c.get('label') or c.get('formatted_address')} (type: {c.get('place_type')})"
        for i, c in enumerate(candidates)
    )
    siblings = ", ".join(sibling_locations or []) or "(none)"
    prompt = (
        "You are resolving an ambiguous place name for a Meta Ads geo-targeting "
        "campaign. The user's location name matched SEVERAL real places. Pick the "
        "one the user most likely means.\n\n"
        f"Candidates:\n{listing}\n\n"
        "Context signals:\n"
        f"- Business description: {business_desc or '(unknown)'}\n"
        f"- Target audience: {target_audience or '(unknown)'}\n"
        f"- Targeting approach: {det_type or '(unknown)'} "
        "(store_set / competitor_nearby anchor on a single shop → almost always a city, "
        "not a whole province)\n"
        f"- Other locations in the same request: {siblings} "
        "(a list of cities suggests this is also a city)\n"
        f"- Location scope the user chose or that was inferred (may be a default "
        f"guess, weigh it but do not blindly trust it): {location_scope or '(unknown)'}\n\n"
        "Rules:\n"
        "- A small local business (bakery, salon, gym) targets a city, not a "
        "province or country, unless the user said otherwise.\n"
        "- confidence is YOUR certainty the user meant that candidate: use >= 0.95 "
        "only when the context clearly determines it; otherwise stay below 0.95 "
        "so the user is asked.\n"
        '- Return ONLY strict JSON: {"choice": <candidate index>, "confidence": <0.0-1.0>}\n\n'
        "JSON:"
    )

    for attempt in range(2):
        try:
            llm = _make_llm()
            result, _ = await tracked_ainvoke(
                llm, [HumanMessage(content=prompt)],
                node_name="tool/disambiguate_location", writer=None,
            )
            raw = result.text.strip()
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
            parsed = json.loads(raw)
            idx = int(parsed.get("choice", 0))
            conf = float(parsed.get("confidence", 0.0))
            if not (0 <= idx < len(candidates)):
                return (0, 0.0)
            return (idx, max(0.0, min(conf, 1.0)))
        except Exception as exc:
            logger.warning("disambiguate_location attempt %d failed: %s", attempt + 1, exc)
            if attempt == 0:
                await asyncio.sleep(1.0)

    return (0, 0.0)


# ── Tool: get_dynamic_place_types ─────────────────────────────────────────────


@tool
async def get_dynamic_place_types(business_context: str) -> List[str]:
    """
    Use an LLM to infer the top 5 most relevant POI search phrases
    from a business description, for use in Google Places Text Search.

    Args:
        business_context: Description of the business, its audience, and goals.

    Returns:
        List of up to 5 descriptive search phrases (e.g. ["pet store", "veterinary clinic"]).
    """
    if not business_context:
        return []

    prompt = (
        "You are a geo-targeting analyst for a Meta Ads campaign. From the context "
        "below, list up to 5 types of PHYSICAL PLACES where the TARGET AUDIENCE "
        "naturally gathers because of their occupation, income, lifestyle, "
        "interests, or demographics.\n\n"
        "These phrases go straight into Google Places Text Search - return natural, "
        "descriptive phrases, NOT API slugs (e.g. 'crossfit gym', 'yoga studio', "
        "'specialty coffee shop').\n\n"
        "THE TARGET AUDIENCE IS THE PRIMARY DRIVER:\n"
        "- If a 'Target audience' is given, derive the places from that audience — "
        "NOT from the business's own buyers/customers.\n"
        "- Decompose the audience into its DISTINCT FACETS and return at least one "
        "place type per facet BEFORE adding extras, so the list stays stable across "
        "runs and COVERS every facet (not just one). Facet -> venue mapping:\n"
        "  * occupation / workplace ('works in hospitals', 'lawyers') -> that "
        "workplace itself (hospital, medical clinic; law firm).\n"
        "  * income / wealth ('over 300k', 'high earners', 'affluent', 'luxury') -> "
        "premium venues matching that wealth (luxury car dealership, fine dining "
        "restaurant, private golf club, upscale fitness club, luxury real estate "
        "office).\n"
        "  * interests / hobbies / lifestyle -> venues tied to that interest.\n\n"
        "BUSINESS DESCRIPTION IS SELLER CONTEXT ONLY:\n"
        "- Use it only to EXCLUDE the brand's own sales channel and ANY shop in the "
        "SAME product category (those are competitor / point-of-sale targeting, "
        "handled separately). A supplement brand must NOT return 'supplement shop'; "
        "a coffee roaster must NOT return 'coffee shop'.\n"
        "- Do NOT target the seller's own buyers just because the business "
        "description names them. A B2B 'SaaS for hospitals' must NOT collapse the "
        "list to 'hospital' UNLESS the target audience is hospital staff.\n"
        "- When a facet allows several equally valid venues, prefer the ones where "
        "THIS product's need actually shows up (a sports supplement brand's "
        "'gym-goers' facet should lean gym/training venues over generic fitness "
        "retail) so the list reads as built for this business, not audience alone.\n"
        "- If 'Target audience' is thin or generic, derive the facets from the "
        "business description and its edge instead (a halal meal-prep service with "
        "no stated audience still implies mosque / islamic center / halal "
        "restaurant from the business itself).\n"
        "- Prefer specific venues over generic ones ('crossfit gym', not 'store').\n\n"
        "Examples:\n"
        "- Audience: hospital staff earning $300k+ -> hospital, medical clinic, "
        "luxury car dealership, fine dining restaurant, private golf club "
        "(BOTH the workplace facet AND the high-income facet, every run)\n"
        "- Sports supplement brand (audience: gym-goers, combat-sports fans) -> "
        "crossfit gym, mma gym, boxing gym, weightlifting gym, fitness center\n"
        "- Halal meal-prep service -> mosque, islamic center, halal restaurant, "
        "middle eastern grocery, university campus\n"
        "- Premium dog food brand -> dog park, veterinary clinic, pet grooming "
        "salon, dog training center, pet-friendly cafe\n\n"
        "Rules:\n"
        "- At most 5 phrases, most relevant first\n"
        "- When the audience has multiple facets, cover EACH facet before repeating one\n"
        "- Return ONLY a comma-separated list, no explanation\n\n"
        f"Business Context:\n{business_context}\n\n"
        "Output:"
    )

    for attempt in range(3):
        try:
            llm = _make_llm()
            result, _ = await tracked_ainvoke(llm, [HumanMessage(content=prompt)], node_name="tool/get_dynamic_place_types", writer=None)
            raw = result.text.strip()
            types = [t.strip().strip('"').strip("'") for t in raw.split(",") if t.strip()]
            return types[:5]
        except Exception as exc:
            logger.warning(
                "get_dynamic_place_types attempt %d failed: %s", attempt + 1, exc
            )
            if attempt < 2:
                await asyncio.sleep(2.0 ** attempt)  # 1s, 2s

    logger.error("get_dynamic_place_types failed after 3 attempts")
    return []


# ── Tool: get_competitor_types ────────────────────────────────────────────────


@tool
async def get_competitor_types(business_context: str) -> List[str]:
    """
    Use an LLM to infer the single most specific competitor POI category
    for a business, for use in Google Places Text Search.

    Args:
        business_context: Description of the business and its market.

    Returns:
        List with one competitor type phrase (e.g. ["specialty coffee shop"]).
    """
    if not business_context:
        return []

    prompt = (
        "You are a competitive intelligence analyst. Given a business context, "
        "identify the SINGLE most specific search phrase that describes the "
        "direct competitor category.\n\n"
        "Rules:\n"
        "- Return ONLY ONE phrase\n"
        "- Use natural, specific language (e.g. 'halal restaurant', 'crossfit gym')\n"
        "- Focus on the PRIMARY competitor type\n"
        "- No explanation, no punctuation, just the phrase\n\n"
        f"Business Context:\n{business_context}\n\n"
        "Output:"
    )

    for attempt in range(3):
        try:
            llm = _make_llm()
            result, _ = await tracked_ainvoke(llm, [HumanMessage(content=prompt)], node_name="tool/get_competitor_types", writer=None)
            raw = result.text.strip().strip('"').strip("'")
            competitor_type = raw.split(",")[0].strip()
            return [competitor_type] if competitor_type else []
        except Exception as exc:
            logger.warning(
                "get_competitor_types attempt %d failed: %s", attempt + 1, exc
            )
            if attempt < 2:
                await asyncio.sleep(2.0 ** attempt)  # 1s, 2s

    logger.error("get_competitor_types failed after 3 attempts")
    return []


# ── Area-aware Places collection ──────────────────────────────────────────────


def _point_in_bounds(lat: float, lng: float, bounds: Dict[str, float]) -> bool:
    """True when (lat,lng) falls inside the bounds box."""
    return (
        bounds["lat_min"] <= lat <= bounds["lat_max"]
        and bounds["lng_min"] <= lng <= bounds["lng_max"]
    )


# ── Region polygon containment ────────────────────────────────────────────────
# A large region's axis-aligned bbox over-covers its real shape (Long Island's
# rectangle reaches across the East River and swallows lower Manhattan). The bbox
# is the last POI guard once the metro-relax nulls the locality filter and the
# state/country filters can't separate same-state bleed. Filtering POIs by the
# region's REAL polygon (from OSM/Nominatim) closes that gap. Point-in-polygon is
# pure geometry — no county/postal-name assumptions, so it is safe in every locale.

# Polygon rings are lists of (lng, lat) tuples, matching GeoJSON coordinate order.
Ring = List[tuple]


def _perp_dist(p: tuple, a: tuple, b: tuple) -> float:
    """Perpendicular distance (in coordinate-degree units) from point ``p`` to the
    infinite line through ``a``–``b``. Degenerate segment (a≈b) → point distance."""
    x0, y0 = p
    x1, y1 = a
    x2, y2 = b
    dx, dy = x2 - x1, y2 - y1
    den = math.hypot(dx, dy)
    if den < 1e-12:
        return math.hypot(x0 - x1, y0 - y1)
    return abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / den


def _dp_open(pts: Ring, tol: float) -> Ring:
    """Iterative Douglas–Peucker on an OPEN polyline (explicit stack, so a huge ring
    can't blow the recursion limit). Keeps endpoints + any vertex farther than
    ``tol`` from its enclosing chord."""
    n = len(pts)
    if n < 3:
        return list(pts)
    keep = [False] * n
    keep[0] = keep[n - 1] = True
    stack = [(0, n - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi <= lo + 1:
            continue
        a, b = pts[lo], pts[hi]
        dmax, idx = 0.0, -1
        for i in range(lo + 1, hi):
            d = _perp_dist(pts[i], a, b)
            if d > dmax:
                dmax, idx = d, i
        if dmax > tol and idx != -1:
            keep[idx] = True
            stack.append((lo, idx))
            stack.append((idx, hi))
    return [pts[i] for i in range(n) if keep[i]]


def _douglas_peucker(ring: Ring, tol: float) -> Ring:
    """Simplify a CLOSED ring (first == last vertex). A naïve DP on a closed ring
    degenerates (the endpoints coincide, so the chord is a point and every distance
    reads 0 → collapses to 2 verts). Split the ring at the vertex farthest from
    ring[0] into two open chains, DP each, and rejoin."""
    n = len(ring)
    if n < 4:
        return list(ring)
    o = ring[0]
    far = max(range(n), key=lambda i: (ring[i][0] - o[0]) ** 2 + (ring[i][1] - o[1]) ** 2)
    if far == 0:
        return list(ring)
    return _dp_open(ring[: far + 1], tol)[:-1] + _dp_open(ring[far:], tol)


def _point_in_polygon(lat: float, lng: float, polygon: List[Ring]) -> bool:
    """True when (lat,lng) lies inside ``polygon`` (a list of rings, each a list of
    (lng,lat) tuples).

    Ray-casting with EVEN-ODD parity accumulated across every ring, which models
    both shapes this guards: a MultiPolygon's disjoint parts still OR-combine (a
    point is inside at most one, so one crossing set = inside), and a Polygon's
    INNER rings punch holes (inside outer + inside hole = two crossing sets =
    outside). Holes matter — Montreal's OSM boundary carries three, one per enclave
    municipality cluster (Westmount, Mont-Royal, …), and treating them as solid made
    a Montreal search claim every enclave's POIs."""
    inside = False
    for ring in polygon:
        n = len(ring)
        if n < 3:
            continue
        j = n - 1
        for i in range(n):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if ((yi > lat) != (yj > lat)) and (
                lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
            ):
                inside = not inside
            j = i
    return inside


def _normalize_geojson_rings(geojson: Dict[str, Any]) -> List[Ring]:
    """Rings of a GeoJSON ``Polygon``/``MultiPolygon`` as (lng,lat) tuples.

    INNER rings (holes) are kept alongside the outer ones — ``_point_in_polygon``
    combines them by even-odd parity, so an enclave carved out of a municipality
    (Westmount inside Montreal) reads as outside instead of inside."""
    t = geojson.get("type")
    coords = geojson.get("coordinates") or []
    rings: List[Ring] = []
    if t == "Polygon":
        for ring in coords:
            rings.append([(float(x), float(y)) for x, y in ring])
    elif t == "MultiPolygon":
        for poly in coords:
            for ring in poly or []:
                rings.append([(float(x), float(y)) for x, y in ring])
    return rings


# Google place_type → Nominatim ``featureType`` bias. A bare name whose city
# outranks its same-named state on Nominatim (e.g. "New York, NY, USA" → New York
# City as the #1 OSM hit) needs the featuretype hint to surface the STATE the user
# actually picked. Only the ambiguous admin scopes are biased; city/town queries
# are left unhinted so a small town that isn't a Nominatim "city" still resolves.
_NOMINATIM_FEATURETYPE: dict[str, str] = {
    "administrative_area_level_1": "state",
    "country": "country",
}

# Reject a fetched polygon whose bbox area is below this fraction of the picked
# candidate's Google ``bounds`` area — that means Nominatim returned a much smaller
# entity than the pick (a city polygon under a state candidate). On rejection the
# caller keeps the candidate's bbox + state/name filters. A correct OSM polygon
# fills most of the same entity's Google bounds, so the ratio sits near 1.
_POLYGON_BOUNDS_MIN_AREA_RATIO = 0.3

# Loose floor applied at EVERY scope. The strict ratio above is an IDENTITY test for
# ambiguous admin picks; this one is a SANITY test — it only has to separate a real
# region from a venue that happens to carry the region's name. Nominatim's top hit for
# "Dallas Downtown Historic District, Dallas, TX, USA" is The Westin Dallas Downtown
# (a hotel), which nests wholly inside the district — so the centroid guard cannot see
# it and size is the only discriminating axis. Measured: correct picks land at 1.00–1.08
# (borough, city, island, neighbourhood), the mis-hits at 0.0001–0.016 (that hotel, a
# 16-acre park under a neighbourhood, a wrong-county island). 0.1 sits between with ~6x
# margin either way, and stays clear of the padding on a Google viewport.
_POLYGON_BOUNDS_MIN_AREA_RATIO_ANY = 0.1

# Google place_type → the Nominatim STRUCTURED query field that names the same
# entity. Structured search (``city=``/``state=``/``country=``) beats free text
# because it constrains the entity KIND, not just the ranking: "Mount Royal, QC,
# Canada" as ``q`` returns the mountain peak (OSM ranks it first), while
# ``city=Mount Royal`` cannot match a peak at all. Nominatim forbids mixing
# structured fields with ``q``, so this is an either/or per lookup.
_NOMINATIM_STRUCTURED_FIELD: dict[str, str] = {
    "locality": "city",
    "postal_town": "city",
    "administrative_area_level_3": "city",
    "administrative_area_level_2": "county",
    "administrative_area_level_1": "state",
    "country": "country",
}

# OSM ``class`` values acceptable for an ADMINISTRATIVE pick. A Google locality /
# admin area / country must come back as a boundary or a populated place — never a
# hill (``natural``), a park (``leisure``), a monument (``tourism``) or a venue
# (``amenity``). This is the direct guard against the same-name entity collision:
# "Mount Royal" the town vs Mont-Royal the peak.
_OSM_ADMIN_CLASSES: frozenset = frozenset({"boundary", "place"})

# Fraction of the Google box's span allowed as slack when testing whether the OSM
# result's own point falls inside it. Covers a representative point that sits just
# outside an irregular true-extent box, without admitting a different entity
# kilometres away.
_POLYGON_POINT_PAD_RATIO = 0.10
_POLYGON_POINT_PAD_MIN_DEG = 0.005


def _osm_point_within_bounds(
    lat: float, lng: float, b: Optional[Dict[str, float]]
) -> bool:
    """True when an OSM result's own coordinate falls inside the picked candidate's
    Google box (padded).

    The general wrong-ENTITY guard, and the counterpart to the wrong-SCOPE area
    ratio below. A correct entity's OSM point always lies within Google's box for
    that same entity; a same-named neighbour does not — Mont-Royal the peak sits
    0.031° east of the Town of Mount Royal's ``lng_max``, well past the pad.

    Returns True when bounds are missing/degenerate so a candidate that carries no
    box (pin-drop, some premises) keeps the legacy unverified behaviour.
    """
    if not b:
        return True
    try:
        lat_min, lat_max = float(b["lat_min"]), float(b["lat_max"])
        lng_min, lng_max = float(b["lng_min"]), float(b["lng_max"])
    except (KeyError, TypeError, ValueError):
        return True
    lat_pad = max(abs(lat_max - lat_min) * _POLYGON_POINT_PAD_RATIO, _POLYGON_POINT_PAD_MIN_DEG)
    lng_pad = max(abs(lng_max - lng_min) * _POLYGON_POINT_PAD_RATIO, _POLYGON_POINT_PAD_MIN_DEG)
    return (
        (lat_min - lat_pad) <= lat <= (lat_max + lat_pad)
        and (lng_min - lng_pad) <= lng <= (lng_max + lng_pad)
    )


def _bounds_area_deg2(b: Optional[Dict[str, float]]) -> float:
    """Axis-aligned area (deg²) of a {lat_min,lat_max,lng_min,lng_max} box, or 0.0
    when missing/degenerate."""
    if not b:
        return 0.0
    try:
        return abs(b["lat_max"] - b["lat_min"]) * abs(b["lng_max"] - b["lng_min"])
    except (KeyError, TypeError):
        return 0.0


def _rings_bbox_area_deg2(rings: List[Ring]) -> float:
    """Axis-aligned bbox area (deg²) enclosing all ring vertices ((lng,lat) tuples)."""
    xs = [x for r in rings for x, _ in r]
    ys = [y for r in rings for _, y in r]
    if not xs or not ys:
        return 0.0
    return abs(max(xs) - min(xs)) * abs(max(ys) - min(ys))


async def _fetch_region_polygon(
    query: str,
    place_type: Optional[str] = None,
    expected_bounds: Optional[Dict[str, float]] = None,
    components: Optional[Dict[str, str]] = None,
) -> Optional[List[Ring]]:
    """Fetch and simplify a region's real polygon from Nominatim (OSM).

    Returns a list of outer rings ((lng,lat) tuples), simplified via Douglas–Peucker
    at ``GEO_POLYGON_SIMPLIFY_M`` metres. If the result still exceeds
    ``GEO_POLYGON_MAX_VERTS`` (pathological continent-scale shapes), the tolerance is
    escalated until it fits. Returns ``None`` on any miss/error — callers then keep
    the plain bbox behaviour. Never raises.

    Google is authoritative on WHICH entity was picked but only ever supplies a
    rectangle; OSM supplies the true shape but must be told which entity and then
    checked. Three layers do that, in order:

    1. ASK precisely — ``components`` (Google's resolved ``locality`` /
       ``admin_area1_name`` / ``country_name``) drives a STRUCTURED Nominatim query
       whose fields constrain the entity kind. Falls back to free-text ``q=query``
       with the ``featureType`` bias when components are absent.
    2. VERIFY THE KIND — an administrative pick must return an administrative OSM
       class (see ``_OSM_ADMIN_CLASSES``); a hill or a park is rejected outright.
    3. VERIFY THE PLACE — the result's own point must fall inside
       ``expected_bounds`` (``_osm_point_within_bounds``), which catches a
       same-named neighbour that survived the first two.

    4. VERIFY THE SIZE — the polygon's bbox must be a plausible fraction of the
       Google box: a strict ratio at ambiguous admin scope (a city returned under a
       state pick), a loose sanity floor everywhere else. This is the only layer that
       can see a wrong entity NESTED inside the right one, where the point check
       (layer 3) passes by construction — Nominatim answers "Dallas Downtown Historic
       District" with a hotel standing in it.

    A polygon that survives all four but collapses to a zero-area sliver under
    simplification is rejected too (see the tolerance loop below).

    Every rejection returns ``None``, so the caller degrades to bbox + locality /
    state / country name filters — coarser, never wrong.
    """
    params: Dict[str, Any] = {"format": "json", "limit": 1, "polygon_geojson": 1}
    structured_field = _NOMINATIM_STRUCTURED_FIELD.get(place_type or "")
    structured: Dict[str, str] = {}
    if components and structured_field:
        # Nominatim rejects structured fields mixed with `q`, so this is either/or.
        _primary = components.get(structured_field)
        if _primary:
            structured[structured_field] = _primary
            for _f in ("state", "country"):
                if _f != structured_field and components.get(_f):
                    structured[_f] = components[_f]
    if structured:
        params.update(structured)
    else:
        params["q"] = query
        featuretype = _NOMINATIM_FEATURETYPE.get(place_type or "")
        if featuretype:
            params["featureType"] = featuretype
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            async def _do_request():
                resp = await client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params=params,
                    headers={"User-Agent": "punkAI-campaign-builder/2.0"},
                )
                resp.raise_for_status()
                return resp.json()

            results = await _with_retry(_do_request, max_attempts=2, base_delay=1.0)
    except Exception as exc:
        logger.warning("Region polygon fetch failed for %s: %s", query, exc)
        return None

    if not results:
        return None
    top = results[0]

    # ── Guard: wrong KIND of entity ──────────────────────────────────────────
    # An administrative pick must resolve to an administrative OSM object. The
    # observed failure: Google picked the Town of Mount Royal (locality) and OSM's
    # top hit for the same string was Mont-Royal the summit — class "natural",
    # type "peak". A park ("leisure") is the same collision with a real polygon
    # attached, which would silently replace the name filters with a hillside.
    # A MISSING class is unverifiable, not suspicious — don't reject on this axis
    # (the point guard below still applies). Live Nominatim always sends it.
    _osm_class = str(top.get("class") or "")
    if (
        _osm_class
        and place_type in _NOMINATIM_STRUCTURED_FIELD
        and _osm_class not in _OSM_ADMIN_CLASSES
    ):
        logger.info(
            "Region polygon for %s rejected: OSM class=%r type=%r is not "
            "administrative (picked place_type=%s) — wrong entity, keeping bbox",
            query, _osm_class, top.get("type"), place_type,
        )
        return None

    # ── Guard: wrong PLACE ───────────────────────────────────────────────────
    # Survives the kind check when the neighbour IS administrative (a same-named
    # borough, an adjacent municipality). Google's box is the ground truth for
    # which entity was picked.
    try:
        _res_lat, _res_lng = float(top["lat"]), float(top["lon"])
    except (KeyError, TypeError, ValueError):
        _res_lat = _res_lng = None
    if (
        _res_lat is not None
        and not _osm_point_within_bounds(_res_lat, _res_lng, expected_bounds)
    ):
        logger.info(
            "Region polygon for %s rejected: OSM point (%.6f, %.6f) outside the "
            "picked candidate's bounds %s — wrong entity, keeping bbox",
            query, _res_lat, _res_lng, expected_bounds,
        )
        return None

    geojson = top.get("geojson") or {}
    rings = _normalize_geojson_rings(geojson)
    if not rings:
        logger.info("Region polygon: no usable geojson for %s (type=%s)", query, geojson.get("type"))
        return None

    # Verify against the picked candidate's Google bounds: a polygon whose bbox is a
    # small fraction of the candidate's box is a different (smaller) entity than the
    # pick — e.g. Nominatim returned New York CITY for a New York STATE candidate.
    # Reject so the caller falls back to the correct bbox + state filters.
    #
    # Two tiers. AMBIGUOUS ADMIN scope (a state/country whose name a smaller same-named
    # entity can outrank on Nominatim — exactly the types carrying a
    # `_NOMINATIM_FEATURETYPE` bias) keeps the strict identity ratio. Every other scope
    # gets the loose sanity floor: there is no larger same-named sibling to confuse the
    # pick with, and the candidate's box may be a PADDED Google viewport that a correct
    # (smaller) polygon legitimately underfills — so the strict ratio would reject the
    # very polygon we want, but a VENUE carrying the region's name still misses the loose
    # floor by orders of magnitude.
    _exp_area = _bounds_area_deg2(expected_bounds)
    if _exp_area > 0:
        _min_ratio = (
            _POLYGON_BOUNDS_MIN_AREA_RATIO
            if (place_type or "") in _NOMINATIM_FEATURETYPE
            else _POLYGON_BOUNDS_MIN_AREA_RATIO_ANY
        )
        _poly_area = _rings_bbox_area_deg2(rings)
        if _poly_area < _min_ratio * _exp_area:
            logger.info(
                "Region polygon for %s rejected: bbox area %.6f deg² << candidate "
                "bounds %.6f deg² (ratio %.5f < %.2f) — wrong entity, keeping bbox",
                query, _poly_area, _exp_area, _poly_area / _exp_area, _min_ratio,
            )
            return None

    # ~111 km per degree of latitude → metres-to-degrees tolerance.
    tol = settings.GEO_POLYGON_SIMPLIFY_M / 111_000.0
    for _ in range(6):  # escalate tolerance until under the vertex cap
        simplified = [_douglas_peucker(r, tol) for r in rings]
        if sum(len(r) for r in simplified) <= settings.GEO_POLYGON_MAX_VERTS:
            rings = simplified
            break
        tol *= 2.0
    else:
        rings = simplified  # last attempt; accept whatever it produced
    # A polygon smaller than the simplify tolerance collapses to a zero-area sliver
    # ([A, B, A] — three vertices, so `_point_in_polygon`'s `n < 3` skip misses it) and
    # then rejects EVERY point. Nothing is lost by dropping it: the caller falls back to
    # bbox + name filters, where a degenerate polygon would have filtered out the world.
    if not any(len(set(r)) >= 3 for r in rings) or _rings_bbox_area_deg2(rings) <= 0:
        logger.info(
            "Region polygon for %s rejected: degenerate after simplify (%d ring(s), "
            "%d vert(s)) — keeping bbox", query, len(rings), sum(len(r) for r in rings),
        )
        return None
    logger.info(
        "Region polygon for %s: %d ring(s), %d vert(s)",
        query, len(rings), sum(len(r) for r in rings),
    )
    return rings


# ── Cached, throttled polygon access ─────────────────────────────────────────
# Polygon-primary filtering fetches a polygon for every named city/region search,
# not just giant regions — so we MUST cache (a polygon depends only on the place,
# never on the search) and throttle. Nominatim's public policy is ~1 req/s +
# cache-required. The cache is process-level (shared across sessions/turns, never
# persisted to the checkpointer) and stores a negative sentinel so polygon-less places aren't
# refetched every time.
_REGION_POLYGON_CACHE: "dict[str, Optional[List[Ring]]]" = {}
_REGION_POLYGON_MISS = object()  # sentinel: fetched, no usable polygon
_region_polygon_lock = asyncio.Lock()
_region_polygon_last_call = 0.0


def _polygon_cache_key(
    query: str,
    place_id: Optional[str],
    place_type: Optional[str] = None,
    components: Optional[Dict[str, str]] = None,
) -> str:
    """A polygon depends only on the place → key by the stable Google place_id when
    present, else the normalized query. ``place_type`` is folded in so a city and its
    same-named state (which share a ``formatted_address``) can't collide on the
    query-fallback branch.

    ``components`` are folded in too: they select the STRUCTURED lookup, which can
    resolve a different (correct) entity than the free-text one for the same string.
    Entries written before structured lookups existed therefore key differently and
    are simply never read again — they age out via the existing FIFO trim.
    """
    base = f"pid:{place_id}" if place_id else f"q:{_norm_locality(query)}"
    key = f"{base}:{place_type}" if place_type else base
    if components:
        _c = ",".join(f"{k}={components[k]}" for k in sorted(components) if components[k])
        if _c:
            key = f"{key}:c[{_c}]"
    return key


async def _region_polygon_cached(
    query: str,
    place_id: Optional[str] = None,
    place_type: Optional[str] = None,
    expected_bounds: Optional[Dict[str, float]] = None,
    components: Optional[Dict[str, str]] = None,
) -> Optional[List[Ring]]:
    """Cached + rate-limited wrapper over ``_fetch_region_polygon``.

    Returns the (simplified) polygon rings, or ``None`` when the place has no usable
    OSM polygon (cached as a sentinel so it is not refetched). Serializes Nominatim
    calls with a ``GEO_NOMINATIM_MIN_INTERVAL_S`` floor between them. Never raises.

    ``components`` drives the structured lookup, ``place_type`` selects the
    structured field (or the free-text ``featureType`` bias), and
    ``expected_bounds`` verifies the result — see ``_fetch_region_polygon``. All
    three are folded into the cache key, so a city and its same-named state, or a
    free-text and a structured resolution of the same string, can't collide.
    """
    global _region_polygon_last_call
    key = _polygon_cache_key(query, place_id, place_type, components)
    if key in _REGION_POLYGON_CACHE:
        val = _REGION_POLYGON_CACHE[key]
        return None if val is _REGION_POLYGON_MISS else val  # type: ignore[return-value]

    async with _region_polygon_lock:
        # Re-check inside the lock: a concurrent caller may have filled it.
        if key in _REGION_POLYGON_CACHE:
            val = _REGION_POLYGON_CACHE[key]
            return None if val is _REGION_POLYGON_MISS else val  # type: ignore[return-value]

        wait = settings.GEO_NOMINATIM_MIN_INTERVAL_S - (
            asyncio.get_event_loop().time() - _region_polygon_last_call
        )
        if wait > 0:
            await asyncio.sleep(wait)

        rings = await _fetch_region_polygon(
            query, place_type, expected_bounds, components,
        )
        _region_polygon_last_call = asyncio.get_event_loop().time()

        # Bound the cache (simple FIFO trim — polygons are place-stable, so eviction
        # order barely matters; this only guards unbounded growth).
        if len(_REGION_POLYGON_CACHE) >= settings.GEO_POLYGON_CACHE_SIZE:
            _REGION_POLYGON_CACHE.pop(next(iter(_REGION_POLYGON_CACHE)), None)
        _REGION_POLYGON_CACHE[key] = rings if rings else _REGION_POLYGON_MISS  # type: ignore[assignment]
        return rings


def _norm_locality(s: str) -> str:
    """Accent-strip + lowercase a place token for tolerant containment matching
    ('Montréal' ⇄ 'Montreal')."""
    decomposed = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower().strip()


# Generic place-type suffix words that carry no locality identity — dropped so a
# geocoder "Québec City" still matches a POI whose component reads "Québec", and
# "New York City" ⇄ "New York". Kept minimal to avoid swallowing real name words.
_GENERIC_LOCALITY_SUFFIXES: frozenset[str] = frozenset({
    "city", "ville", "town", "township", "municipality",
})


# Bilingual municipal name words folded to one spelling. Google returns the FRENCH
# form in a Quebec POI's address ("Mont-Royal, QC") while the geocoder resolved the
# ENGLISH one ("Mount Royal") — a word-set match then fails and the locality filter
# drops every POI in the town. Only the pairs that actually name municipalities go
# here; a generic FR/EN dictionary would collapse unrelated places.
_LOCALITY_WORD_ALIASES: dict[str, str] = {
    "mont": "mount",
}


def _significant_locality_words(s: str) -> list[str]:
    """Normalized significant word-tokens of a locality name: accent-stripped,
    lowercased, split on non-alphanumerics, dropping words < 3 chars and generic
    place-type suffixes ('Québec City' → ['quebec']) so the identity token
    survives for tolerant matching. Bilingual name words are folded via
    ``_LOCALITY_WORD_ALIASES`` ('Mont-Royal' ⇄ 'Mount Royal'). Falls back to the raw
    words if stripping the suffix would leave nothing (a locality literally named
    only by a suffix)."""
    words = [
        _LOCALITY_WORD_ALIASES.get(w, w)
        for w in re.split(r"[^a-z0-9]+", _norm_locality(s)) if len(w) >= 3
    ]
    core = [w for w in words if w not in _GENERIC_LOCALITY_SUFFIXES]
    return core or words


def _locality_tokens_match(a: str, b: str) -> bool:
    """True when two locality NAMES denote the same place, tolerant of a generic
    suffix on one side ('Québec City' ⇄ 'Québec'), accents, and case. Bidirectional
    word-subset: matches when either side's significant word-set is contained in the
    other's, so a longer geocoder token still matches a shorter POI token (the old
    one-directional substring never did). An empty side (too-short/suffix-only name)
    is lenient → match (never drop what we cannot positively place elsewhere)."""
    wa, wb = set(_significant_locality_words(a)), set(_significant_locality_words(b))
    if not wa or not wb:
        return True
    return wa <= wb or wb <= wa


def _address_in_locality(address: str, locality: str) -> bool:
    """True when ``address`` looks like it belongs to ``locality``.

    Matches the locality's significant identity words (the part before the first
    comma, e.g. "Montreal" from "Montreal, QC"; "Québec" from "Québec City")
    against the address's own word-set, accent-insensitive. Both sides go through
    :func:`_significant_locality_words` so the bilingual alias folding applies here
    too — a raw substring test over the address would miss "Mount Royal" in
    "…, Mont-Royal, QC…". Empty address or a suffix-only/too-short locality is
    treated as a match so we never drop a POI we cannot positively place elsewhere.
    """
    core = set(_significant_locality_words((locality or "").split(",")[0]))
    if not core:
        return True
    addr_words = set(_significant_locality_words(address))
    if not addr_words:
        return True
    return core <= addr_words


def _locality_match(poi: Dict[str, Any], locality: str) -> bool:
    """True when ``poi`` belongs to ``locality``, matching the target against the
    POI's STRUCTURED addressComponents when present, else its formatted address.

    The formatted address is an unreliable borough signal — a Manhattan place reads
    "…, New York, NY…" (no "Manhattan"), Queens places read neighbourhood names —
    so a string match over-drops. Google's ``addressComponents`` carry the true
    ``sublocality`` ("Manhattan"/"Queens"), which separates adjacent boroughs
    cleanly. When components are present they are authoritative; otherwise we fall
    back to the formatted-address string (component-less/legacy results).

    Matching is suffix-tolerant and bidirectional (:func:`_locality_tokens_match`)
    so a geocoder "Québec City" matches a POI component "Québec"; a genuine
    neighbour ("Manhattan" vs "Brooklyn") still fails and is dropped."""
    loc_head = (locality or "").split(",")[0]
    if not _significant_locality_words(loc_head):
        return True
    tokens = poi.get("locality_tokens") or []
    if tokens:
        return any(_locality_tokens_match(loc_head, t) for t in tokens)
    return _address_in_locality(poi.get("address", ""), locality)


def _state_match(poi: Dict[str, Any], state: str) -> bool:
    """True when ``poi`` belongs to ``state`` (administrative_area_level_1).

    Guards against a metro-sized city's axis-aligned bbox bleeding across a STATE
    line (New York City's box reaches into New Jersey), where the metro-relax has
    nulled the locality filter. Matches the target state against the POI's
    structured state components (long "New York" + short "NY"), which are reliable;
    a POI with no state component is kept (lenient — never drop what we can't
    positively place elsewhere). Short/empty target → keep."""
    token = _norm_locality(state or "")
    if len(token) < 3:
        return True
    tokens = poi.get("state_tokens") or []
    if not tokens:
        return True
    return any(token in _norm_locality(t) for t in tokens)


def _name_tokens(name: str) -> list[str]:
    """Significant tokens of a place/brand name: accent-stripped, lowercased, split
    on non-alphanumerics, tokens < 2 chars dropped (e.g. "H&M" → ["h","m"] would be
    too loose). Shared by ``_brand_name_match`` and ``_name_match_ratio`` so a query
    and a candidate are always tokenized identically."""
    return [t for t in re.split(r"[^a-z0-9]+", _norm_locality(name)) if len(t) >= 2]


def _brand_name_match(place_name: str, brand_name: str) -> bool:
    """True when a Places result actually IS the brand, not a text-relevance
    neighbour.

    Google Places Text Search for "{brand} in {city}" is relevance-fuzzy, not an
    exact-name lookup: searching "Casper" surfaces other mattress/furniture stores
    (Sleep Country, Structube), and a brand with NO local outlet fills the page
    with unrelated shops (an "IKEA" search in a city without an IKEA returns The
    Brick, CB2, …). A category search wants those neighbours; a BRAND search must
    keep only real outlets — so require every significant token of the brand name
    to appear in the place's display name.

    Matching is WORD-BOUNDARY (token-set membership), not substring: a short token
    like "la" is a substring of "p-la-net" and "B-la-isdell", which made
    "LA Fitness" match Planet Fitness and Blaisdell YMCA — a whole result set of
    the wrong brand. Token equality keeps the cases this gate is meant to allow
    ("Casper - West 4th" ⊇ {casper}, "Sleep Country Canada" ⊇ {sleep, country},
    "Ulta Beauty" ⊇ {ulta}) while rejecting the lookalikes.

    A brand that reduces to no usable token keeps the result (can't positively
    exclude)."""
    brand_tokens = _name_tokens(brand_name)
    if not brand_tokens:
        return True
    place_tokens = set(_name_tokens(place_name))
    return all(t in place_tokens for t in brand_tokens)


def _name_match_ratio(place_name: str, query_name: str) -> float:
    """Fraction of a query name's significant tokens that appear in a place's
    display name — the looser cousin of ``_brand_name_match`` for the named_places
    angle.

    A chain search wants the strict all-or-nothing gate (every token of "Tim
    Hortons" must be present). A specific-venue search must tolerate the user's
    descriptive extras that Google's listing omits: "McGrill Bar" → Google's
    "McGrill" should still match (1 of 2 tokens = 0.5), while "Fight Club" →
    "Sleep Country" scores 0 and is rejected.

    Tokens are compared WORD-BOUNDARY (token-set membership), not by substring —
    see ``_brand_name_match``: substring containment let "la" hit "B-la-isdell",
    scoring "Blaisdell YMCA" at the accept threshold for the query "LA Fitness".

    A query that reduces to no usable token returns 1.0 (can't positively
    exclude)."""
    q_tokens = _name_tokens(query_name)
    if not q_tokens:
        return 1.0
    place_tokens = set(_name_tokens(place_name))
    hits = sum(1 for t in q_tokens if t in place_tokens)
    return hits / len(q_tokens)


# Geocode country long_name → the forms that actually appear at the tail of a
# Google Places formattedAddress. Google returns "USA"/"UK", not the geocoder's
# "United States"/"United Kingdom", so a literal long-name match would drop every
# POI. Any country not listed falls back to its own long name (e.g. "Canada").
_COUNTRY_ADDRESS_ALIASES: dict[str, tuple[str, ...]] = {
    "united states": ("usa", "united states"),
    "united kingdom": ("uk", "united kingdom"),
    "united arab emirates": ("uae", "united arab emirates"),
}


def _address_in_country(address: str, country: Optional[str]) -> bool:
    """True when ``address`` looks like it belongs to ``country``.

    Matches the country name ("Canada", "USA") inside the place's formatted
    address, accent-insensitive. Guards against a large admin area's bounding box
    bleeding POIs across an international border. Empty country or a too-short
    token (< 3 chars) is treated as a match so we never drop a POI we cannot
    positively place elsewhere. Uses long name + address aliases only — the ISO
    short ("CA") collides with California and would wrongly admit US POIs.
    """
    norm_country = _norm_locality(country or "")
    if len(norm_country) < 3:
        return True
    norm_addr = _norm_locality(address)
    if not norm_addr:
        return True
    tokens = _COUNTRY_ADDRESS_ALIASES.get(norm_country, (norm_country,))
    return any(t in norm_addr for t in tokens)


# A correct region polygon fills most of its own bbox, so POIs inside the box hit it at
# a healthy rate. Dropping EVERY one of this many candidates means the polygon is a
# different (or broken) entity — fall back to the pre-polygon set rather than reporting
# an empty area. Below the threshold a genuinely POI-free region is the likelier reading,
# so the polygon is trusted.
# ponytail: count heuristic, not a shape test. Raise if false fallbacks show up.
_POLYGON_WIPEOUT_MIN_CANDIDATES = 5


async def _collect_places_in_area(
    query: str,
    latitude: float,
    longitude: float,
    bounds: Optional[Dict[str, float]] = None,
    search_radius_km: Optional[float] = None,
    locality_filter: Optional[str] = None,
    country_filter: Optional[str] = None,
    state_filter: Optional[str] = None,
    region_polygon: Optional[List[Ring]] = None,
    tile: bool = True,
    included_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Collect Places results for a query, constrained to the selected area so POIs
    do not bleed in from neighbouring places (e.g. Laval results for a Montreal
    search). Strategy scales with the area regardless of scope (city → province):

      - bounds + diagonal > GEO_AREA_TILE_THRESHOLD_KM: tile the bbox into
        GEO_MAX_TILES base rectangles, run a HARD locationRestriction search per
        tile, dedup by rounded (lat,lng). The threshold defaults to 0, so EVERY
        bounded area tiles — a small city fans out just like a province, giving
        uniform POI density across scopes (raise the threshold to restore a
        single search for small areas / cut Google API cost). A tile whose search
        comes back with a FULL page is saturated — the true count was truncated,
        not exhausted. When GEO_TILE_SPLIT_DEPTH > 0 (OFF by default — flat grid,
        baseline cost) a saturated tile adaptively subdivides into 4 quadrants, up
        to that many levels deep, so a dense downtown can get more than the same
        20-result quota as an empty suburb; the whole sweep (base tiles + splits)
        is then capped at GEO_MAX_TILE_SEARCHES Places calls, never below the base
        tile count.
      - When ``search_radius_km`` is also given (pin/radius/competitor scopes pass
        a bbox SYNTHESIZED from center+radius), each tiled point is additionally
        trimmed to inside the ring so the result is a circle, not the bbox square.
      - no bounds + search_radius_km: locationBias circle, then filter to points
        within the radius of the center.
      - neither: text-relevance only (legacy behaviour).

    Every bounded result is additionally filtered to inside the box as a guard
    (the Places rectangle is hard, but this protects against API edge cases).

    ``country_filter`` (a country name) drops any POI whose formatted address does
    not belong to that country. A large admin area's axis-aligned bbox physically
    overlaps neighbouring countries (Ontario's box contains Chicago/Minneapolis);
    unlike ``locality_filter`` it is NOT disabled above the metro threshold and
    applies in both the bounded and unbounded branches.

    ``state_filter`` (a state/province name) is the same guard one admin level
    down: a metro-sized city's bbox reaches across a STATE line (New York City's
    box contains Jersey City/Hoboken, New Jersey). Like ``country_filter`` it is
    NOT disabled by the metro-relax — so the boroughs a NYC search wants survive
    (all New York state) while the New Jersey bleed is dropped.

    ``region_polygon`` (a list of outer rings) is the geometric final guard for
    large NON-CONVEX regions whose axis-aligned bbox over-covers their real shape
    (Long Island's box swallows Manhattan across the East River — same state, so
    ``state_filter`` can't drop it). A POI outside every ring is dropped. Absent
    (None) → no geometric guard, plain bbox behaviour (graceful fallback).

    ``tile=False`` keeps the hard bbox restriction but runs ONE search instead of
    a tiled sweep. Tiling is for CATEGORY sweeps ("coffee shops across Dhaka"),
    where uniform density across the area is the point. For a NAMED venue it is
    actively harmful: results come back concatenated in tile order (a
    south→north / west→east geographic sweep), which destroys Google's relevance
    ranking and its own duplicate suppression — so every junk same-named listing
    in the city surfaces as a separate candidate and the "best" match becomes
    whichever tile happened to be scanned first.

    ``included_type`` restricts the underlying Places call server-side to one
    type (see ``poi_type_rules.primary_type`` / ``_google_places_text_search``'s
    own docstring for the fallback-on-rejection behavior).

    Returns raw place dicts ({name, lat, lng, types, address}).
    """
    # Polygon-primary: when a region's real polygon is available it is authoritative
    # — exact geometry already excludes the cross-city/state/border bleed the name
    # filters only approximate, so drop them. The name filters remain the fallback
    # for places OSM has no polygon for (region_polygon is None then).
    if region_polygon:
        locality_filter = country_filter = state_filter = None

    # Antimeridian guard BEFORE anything reads the box: both the tiling below and
    # the `_point_in_bounds` result guard assume lng_min < lng_max.
    bounds = _normalize_bbox(bounds)

    diag = _bbox_diagonal_km(bounds) if bounds else None

    # Multi-borough metros (NYC ~68 km, LA ~86 km diagonal) format their POI
    # addresses by BOROUGH ("Brooklyn", "Venice"), not the resolved city, so the
    # canonical locality string-filter would wrongly drop most of them. Above the
    # metro threshold the hard locationRestriction bbox already constrains
    # geometry, so the string filter is redundant — skip it. Ordinary cities
    # (Montreal ~50 km) stay below the threshold and keep the corner-bleed guard.
    if bounds and diag is not None and diag > settings.GEO_METRO_UNFILTERED_KM:
        locality_filter = None

    if bounds and tile and diag is not None and diag > settings.GEO_AREA_TILE_THRESHOLD_KM:
        tiles = _tile_bbox(bounds, settings.GEO_MAX_TILES)
    elif bounds:
        tiles = [bounds]
    else:
        tiles = []

    if tiles:
        seen: set[tuple] = set()
        collected: List[Dict[str, Any]] = []
        # POIs the polygon rejected, deduped by rounded coord like `seen` — the same
        # place recurs in every tile, and the wipeout threshold below counts DISTINCT
        # candidates.
        outside_polygon: Dict[tuple, Dict[str, Any]] = {}
        _per_tile_cap = max(1, int(getattr(settings, "GEO_POI_MAX_PAGES", 1))) * 20
        # FIFO work queue of (tile_box, depth). Base tiles are enqueued first, so a
        # budget exhausted by splits can never starve the uniform sweep — it only
        # cuts the adaptive depth short. The budget only ever bounds ADAPTIVE growth;
        # a misconfigured GEO_MAX_TILE_SEARCHES below the base tile count must never
        # truncate the base sweep itself (that would silently drop whole tiles).
        queue: List[tuple[Dict[str, float], int]] = [(t, 0) for t in tiles]
        searches = 0
        _budget = max(settings.GEO_MAX_TILE_SEARCHES, len(tiles))
        while queue and searches < _budget:
            tile_box, depth = queue.pop(0)
            places = await _google_places_text_search(
                query=query, lat=latitude, lng=longitude,
                location_restriction=tile_box,
                max_results=_per_tile_cap,
                included_type=included_type,
            )
            searches += 1
            # A FULL page means the API truncated this tile, not that the tile is
            # exhausted — the rest of its POIs are unreachable at this zoom.
            # Subdivide and re-search. The parent's own results come back again in
            # the children; `seen` below collapses them, so only genuinely deeper
            # POIs are net new.
            if len(places) >= _per_tile_cap and depth < settings.GEO_TILE_SPLIT_DEPTH:
                queue.extend((q, depth + 1) for q in _tile_bbox(tile_box, 4))
            for p in places:
                if p.get("lat") is None or p.get("lng") is None:
                    continue
                lat_p, lng_p = float(p["lat"]), float(p["lng"])
                if not _point_in_bounds(lat_p, lng_p, bounds):  # type: ignore[arg-type]
                    continue
                # Keep ring semantics: a pin/competitor search now tiles a bbox
                # SYNTHESIZED from (center, radius), so trim the bbox corners back
                # to the circle. No-op for named scopes (they pass no radius).
                if search_radius_km is not None and _haversine_km(
                    latitude, longitude, lat_p, lng_p
                ) > search_radius_km:
                    continue
                # Drop cross-border bleed: an admin area's axis-aligned bbox can
                # overlap a neighbouring country (Ontario's box catches Chicago).
                if country_filter and not _address_in_country(p.get("address", ""), country_filter):
                    continue
                # Drop cross-state bleed: a metro city's bbox reaches across a state
                # line (NYC's box catches Jersey City, NJ). Not disabled by metro-relax.
                if state_filter and not _state_match(p, state_filter):
                    continue
                # Drop rectangle-corner bleed: a POI inside the bbox but whose
                # locality is a neighbouring city/borough (the box is axis-aligned,
                # a city is not — corners catch Laval on a Montreal search, or
                # Manhattan on a Brooklyn search). Structured-component match.
                if locality_filter and not _locality_match(p, locality_filter):
                    continue
                # Drop bbox-corner bleed a rectangle can't separate: a POI inside
                # the box but OUTSIDE the region's real polygon (Manhattan inside
                # Long Island's bbox). Geometry — safe in any locale.
                if region_polygon and not _point_in_polygon(lat_p, lng_p, region_polygon):
                    outside_polygon[(round(lat_p, 5), round(lng_p, 5))] = p
                    continue
                key = (round(lat_p, 5), round(lng_p, 5))
                if key in seen:
                    continue
                seen.add(key)
                collected.append(p)
        # The polygon dropped EVERY candidate the bbox found. A correct polygon fills
        # most of its own bbox, so that is the polygon being a different (or broken)
        # entity, not the area being empty — the guards in `_fetch_region_polygon` test
        # SIZE and POSITION, so an adjacent region of similar size still slips through.
        # Report the pre-polygon set instead of a dead end.
        if not collected and len(outside_polygon) >= _POLYGON_WIPEOUT_MIN_CANDIDATES:
            logger.warning(
                "Region polygon dropped all %d candidates for %r — treating it as wrong "
                "and falling back to the bbox result", len(outside_polygon), query,
            )
            return list(outside_polygon.values())
        return collected

    # No bounds: radius-based (pin/competitor) or text-relevance only. No result
    # cap here beyond the Places API's own page limit (GEO_POI_MAX_PAGES pages
    # x 20/page) — every POI found ships, not just the first N.
    radius_meters = search_radius_km * 1000 if search_radius_km is not None else None
    _page_cap = max(1, int(getattr(settings, "GEO_POI_MAX_PAGES", 1))) * 20
    places = await _google_places_text_search(
        query=query, lat=latitude, lng=longitude,
        radius_meters=radius_meters, max_results=_page_cap,
        included_type=included_type,
    )
    out: List[Dict[str, Any]] = []
    for p in places:
        if p.get("lat") is None or p.get("lng") is None:
            continue
        if search_radius_km is not None and _haversine_km(
            latitude, longitude, float(p["lat"]), float(p["lng"])
        ) > search_radius_km:
            continue
        if country_filter and not _address_in_country(p.get("address", ""), country_filter):
            continue
        if state_filter and not _state_match(p, state_filter):
            continue
        if locality_filter and not _locality_match(p, locality_filter):
            continue
        if region_polygon and not _point_in_polygon(
            float(p["lat"]), float(p["lng"]), region_polygon
        ):
            continue
        out.append(p)
    return out


# ── Tool: search_pois_by_type ─────────────────────────────────────────────────


@tool
async def search_pois_by_type(
    poi_type: str,
    city_name: str,
    latitude: float,
    longitude: float,
    search_radius_km: Optional[float] = None,
    target_radius_km: Optional[float] = None,
    bounds: Optional[Dict[str, float]] = None,
    locality_filter: Optional[str] = None,
    country_filter: Optional[str] = None,
    state_filter: Optional[str] = None,
    region_polygon: Optional[List[Ring]] = None,
    parent_label: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Search for POIs of a given type in a city/area using Google Places Text Search.

    Constructs a query like "pet store in Montreal". When ``bounds`` describes a
    large admin area the search is tiled across the bbox for full coverage; when
    ``search_radius_km`` is given a locationBias circle is applied; otherwise
    results are text-relevance only.

    Args:
        poi_type: Descriptive POI phrase (e.g. "pet store", "veterinary clinic").
        city_name: City or area name for the text query (e.g. "Montreal", "Brooklyn, NY").
        latitude: Center latitude for location bias.
        longitude: Center longitude for location bias.
        search_radius_km: Optional search radius in km. None = no spatial bias.
        target_radius_km: Per-POI targeting radius to attach to results.
        bounds: Optional {lat_min,lat_max,lng_min,lng_max} extent of the target
            area (from geocode_location) enabling province-wide tiled coverage.
        locality_filter: Optional city/locality token; when set, results whose
            address belongs to a different city are dropped (kills bbox-corner
            bleed for a specific-city search). Pass only for granular_local city
            scope — NOT for admin/province scope.
        country_filter: Optional country name; when set, results whose address is
            not in that country are dropped (kills cross-border bbox bleed for an
            admin/country scope). Pass for admin_areas / country_groups scope.
        state_filter: Optional state/province name; when set, results outside that
            state are dropped (kills cross-state bbox bleed — NYC → New Jersey —
            that survives the metro-relax). Pass for granular_local / admin_areas.
        region_polygon: Optional list of outer rings; when set, results outside the
            region's real polygon are dropped (kills same-state bbox bleed a
            rectangle can't separate — Manhattan inside Long Island's bbox).
        parent_label: Display label written to each POI's ``parent_location``.
            Defaults to ``city_name``. Pass the RESOLVED address ("Montreal, QC,
            Canada") so the map and POI list show what the geocoder actually
            matched rather than the user's typed word — while ``city_name`` keeps
            driving the Places query text, which must stay the short form.

    Returns:
        Dict with total_pois_found and targetable_poi_coordinates list.
    """
    # Store-anchored searches pass no city: they are already pinned by
    # latitude/longitude + bounds + radius, and the anchor's own locality is a
    # borough or sub-district ("Ville-Marie" for Montreal, "Kafrul" for Dhaka),
    # which narrows the text query to the wrong area. "gym in " is not a query.
    query = f"{poi_type} in {city_name}" if (city_name or "").strip() else poi_type

    # Ask Google to restrict server-side to the matching Places type when we
    # have a confident one for this category (poi_type_rules.validate_pois,
    # applied by the caller after this returns, is the backstop either way —
    # this only cuts junk BEFORE it's fetched/geofenced/MAID-queried).
    from app.graph.builder.executors.poi_type_rules import primary_type
    included_type = primary_type(poi_type)

    places = await _collect_places_in_area(
        query=query,
        latitude=latitude,
        longitude=longitude,
        bounds=bounds,
        search_radius_km=search_radius_km,
        locality_filter=locality_filter,
        country_filter=country_filter,
        state_filter=state_filter,
        region_polygon=region_polygon,
        included_type=included_type,
    )

    poi_coordinates = [
        {
            "name": p["name"],
            "lat": p["lat"],
            "lng": p["lng"],
            "radius_km": target_radius_km,
            "parent_location": parent_label or city_name,
            "types": p.get("types", [poi_type]),
            "formatted_address": p.get("formatted_address") or p.get("address"),
            "postal_code": p.get("postal_code", ""),
            "country_code": p.get("country_code", ""),
            "locality_tokens": p.get("locality_tokens") or [],
            "state_tokens": p.get("state_tokens") or [],
            "rating": p.get("rating"),
            "user_ratings_total": p.get("user_ratings_total", 0),
        }
        # This fixed-key rebuild is a silent drop point for any new Places
        # field — 3 siblings do the same rebuild (search_brand_locations,
        # search_named_places, resolve_named_target's _poi()); grep before
        # adding a 5th field.
        for p in places
        if p.get("lat") is not None
    ]

    density_score = min(len(poi_coordinates) * 2, 100)
    foot_traffic = (
        "high" if density_score >= 60 else ("medium" if density_score >= 30 else "low")
    )

    return {
        "poi_type": poi_type,
        "city": city_name,
        "latitude": latitude,
        "longitude": longitude,
        "search_radius_km": search_radius_km,
        "total_pois_found": len(poi_coordinates),
        "poi_density_score": density_score,
        "foot_traffic_proxy": foot_traffic,
        "targetable_poi_coordinates": poi_coordinates,
    }


# ── Tool: search_brand_locations ──────────────────────────────────────────────


@tool
async def search_brand_locations(
    brand_name: str,
    city_name: str,
    latitude: float,
    longitude: float,
    search_radius_km: Optional[float] = None,
    target_radius_km: Optional[float] = None,
    bounds: Optional[Dict[str, float]] = None,
    locality_filter: Optional[str] = None,
    country_filter: Optional[str] = None,
    state_filter: Optional[str] = None,
    region_polygon: Optional[List[Ring]] = None,
    parent_label: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Find all locations of a specific brand/chain in a city/area.

    Uses Google Places Text Search with the brand name (e.g. "Starbucks in Miami").
    When ``bounds`` is given the search is constrained to (and tiled across) that
    area; when ``search_radius_km`` is given a locationBias circle is applied;
    otherwise results are text-relevance only.

    Args:
        brand_name: Brand or chain name (e.g. "Starbucks", "Walmart").
        city_name: City or area to search within.
        latitude: Center latitude for location bias.
        longitude: Center longitude for location bias.
        search_radius_km: Optional search radius in km. None = no spatial bias.
        target_radius_km: Per-POI targeting radius to attach to results.
        bounds: Optional {lat_min,lat_max,lng_min,lng_max} extent of the target area.
        locality_filter: Optional city/locality token dropping other-city results.
        country_filter: Optional country name dropping cross-border bbox bleed
            (admin_areas / country_groups scope).
        state_filter: Optional state/province name dropping cross-state bbox bleed
            (NYC → New Jersey) that survives the metro-relax.
        region_polygon: Optional list of outer rings dropping same-state bbox bleed
            a rectangle can't separate (Manhattan inside Long Island's bbox).
        parent_label: Display label for each POI's ``parent_location``; defaults to
            ``city_name``. See ``search_pois_by_type`` — the query text keeps the
            short name, the label carries the resolved address.

    Returns:
        Dict with total_locations_found and targetable_poi_coordinates list.
    """
    query = f"{brand_name} in {city_name}"

    places = await _collect_places_in_area(
        query=query,
        latitude=latitude,
        longitude=longitude,
        bounds=bounds,
        search_radius_km=search_radius_km,
        locality_filter=locality_filter,
        country_filter=country_filter,
        state_filter=state_filter,
        region_polygon=region_polygon,
    )

    # Brand-identity gate: Text Search is relevance-fuzzy, so drop results whose
    # name is not actually the brand (kills the "Casper" → Sleep Country / "IKEA"
    # → The Brick bleed). A brand with no local outlet correctly yields 0 here.
    poi_coordinates = [
        {
            "name": p["name"],
            "lat": p["lat"],
            "lng": p["lng"],
            "radius_km": target_radius_km,
            "parent_location": parent_label or city_name,
            "types": p.get("types", []),
            "brand": brand_name,
            "formatted_address": p.get("formatted_address") or p.get("address"),
            "postal_code": p.get("postal_code", ""),
            "country_code": p.get("country_code", ""),
            "locality_tokens": p.get("locality_tokens") or [],
            "state_tokens": p.get("state_tokens") or [],
            "rating": p.get("rating"),
            "user_ratings_total": p.get("user_ratings_total", 0),
        }
        for p in places
        if p.get("lat") is not None and _brand_name_match(p.get("name", ""), brand_name)
    ]

    return {
        "brand_name": brand_name,
        "city": city_name,
        "latitude": latitude,
        "longitude": longitude,
        "search_radius_km": search_radius_km,
        "total_locations_found": len(poi_coordinates),
        "targetable_poi_coordinates": poi_coordinates,
    }


# ── Tool: search_named_places ─────────────────────────────────────────────────


@tool
async def search_named_places(
    place_name: str,
    city_name: str,
    latitude: float,
    longitude: float,
    search_radius_km: Optional[float] = None,
    target_radius_km: Optional[float] = None,
    bounds: Optional[Dict[str, float]] = None,
    locality_filter: Optional[str] = None,
    country_filter: Optional[str] = None,
    state_filter: Optional[str] = None,
    region_polygon: Optional[List[Ring]] = None,
    parent_label: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Find a SPECIFIC named venue/place (not a national chain) by name in a city/area.

    Powers the ``named_places`` targeting angle — the user knows the exact spots
    they want ("Fight Club", "McGrill Bar", "Tomahawk"). Uses Google Places Text
    Search (``"{place_name} in {city_name}"``) like ``search_brand_locations`` but
    with a LOOSER name gate (``_name_match_ratio`` ≥ ``NAMED_PLACE_MATCH_MIN``) so a
    descriptive query still matches the shorter official listing ("McGrill Bar" →
    "McGrill"), and a SMALL per-name cap (``NAMED_PLACE_PER_NAME_LIMIT``) because the
    intent is a few real venues, not a category sweep. Survivors are ranked by match
    ratio (best first). Includes ``formatted_address`` on each result so the confirm
    map shows which venue was matched.

    Args mirror ``search_brand_locations`` (including ``parent_label``, the display
    label for ``parent_location``, defaulting to ``city_name``). Returns a dict with
    ``total_locations_found`` and ``targetable_poi_coordinates``.

    NOTE: assumes ``place_name`` is a PROPER venue name, not a generic category
    ("coffee shops"). The live builder path uses ``resolve_named_target`` (which
    guards this via ``_is_category_like_name``); this standalone tool has no live
    caller today, so no gate is applied here — add one if it is wired up.
    """
    query = f"{place_name} in {city_name}"

    places = await _collect_places_in_area(
        query=query,
        latitude=latitude,
        longitude=longitude,
        bounds=bounds,
        search_radius_km=search_radius_km,
        locality_filter=locality_filter,
        country_filter=country_filter,
        state_filter=state_filter,
        region_polygon=region_polygon,
        tile=False,          # named venue → relevance order, not a tiled sweep
    )

    # Loose name gate + rank by match ratio. Keep only places whose name plausibly
    # IS the queried venue, best match first, then cap to the specific-venue count.
    scored = [
        (_name_match_ratio(p.get("name", ""), place_name), p)
        for p in places
        if p.get("lat") is not None
    ]
    scored = [(r, p) for r, p in scored if r >= settings.NAMED_PLACE_MATCH_MIN]
    scored.sort(key=lambda rp: rp[0], reverse=True)
    scored = scored[: settings.NAMED_PLACE_PER_NAME_LIMIT]

    poi_coordinates = [
        {
            "name": p["name"],
            "lat": p["lat"],
            "lng": p["lng"],
            "radius_km": target_radius_km,
            "parent_location": parent_label or city_name,
            "types": p.get("types", []),
            "formatted_address": p.get("formatted_address") or p.get("address"),
            "postal_code": p.get("postal_code", ""),
            "country_code": p.get("country_code", ""),
            "locality_tokens": p.get("locality_tokens") or [],
            "state_tokens": p.get("state_tokens") or [],
            "named_place": place_name,
            "rating": p.get("rating"),
            "user_ratings_total": p.get("user_ratings_total", 0),
        }
        for _r, p in scored
    ]

    return {
        "place_name": place_name,
        "city": city_name,
        "latitude": latitude,
        "longitude": longitude,
        "search_radius_km": search_radius_km,
        "total_locations_found": len(poi_coordinates),
        "targetable_poi_coordinates": poi_coordinates,
    }


# ── Category-vs-name gate ─────────────────────────────────────────────────────
# Generic place-category nouns that signal a TYPE of venue, not a proper name.
# Used to stop a category phrase ("coffee shops", "rooftop bars") that slipped
# into a name-target slot from being silently resolved to ONE specific venue.
_CATEGORY_NOUNS: frozenset = frozenset({
    "bar", "bars", "pub", "pubs", "cafe", "cafes", "café", "cafés",
    "coffee", "shop", "shops", "store", "stores", "restaurant", "restaurants",
    "gym", "gyms", "studio", "studios", "salon", "salons", "spa", "spas",
    "club", "clubs", "nightclub", "nightclubs", "park", "parks", "mall", "malls",
    "market", "markets", "hotel", "hotels", "bakery", "bakeries", "roaster",
    "roasters", "diner", "diners", "eatery", "eateries", "boutique", "boutiques",
    "clinic", "clinics", "school", "schools", "office", "offices", "venue",
    "venues", "place", "places", "spot", "spots",
})

# Generic EVENT-category nouns, the event-arm counterpart of _CATEGORY_NOUNS.
# Passed as `extra_nouns` by the event→place cross-check so a generic query
# ("music festivals") is never searched for as a proper venue name. Kept apart
# from _CATEGORY_NOUNS so the place gate's behaviour is untouched: an event noun
# is not a place-category tell ("game" alone should not flag a venue name).
_EVENT_CATEGORY_NOUNS: frozenset = frozenset({
    "event", "events", "festival", "festivals", "concert", "concerts",
    "conference", "conferences", "game", "games", "match", "matches",
    "show", "shows", "tournament", "tournaments", "expo", "expos",
    "fair", "fairs", "marathon", "marathons", "race", "races", "gig", "gigs",
    "rave", "raves", "meetup", "meetups", "convention", "conventions",
})

# Domain qualifiers that precede an event noun without naming a specific event
# ("music festivals", "tech conferences", "home games"). Separate from
# _CATEGORY_MODIFIERS so the place gate cannot start reading "music shops" or
# "food market" as categories — only the event arm opts into these.
_EVENT_CATEGORY_MODIFIERS: frozenset = frozenset({
    "music", "tech", "technology", "sports", "sport", "food", "art", "arts",
    "car", "auto", "trade", "comedy", "film", "movie", "book", "beer", "wine",
    "home", "away", "live", "upcoming", "annual", "major", "local",
})

# Qualifiers that commonly precede a category noun without making it a proper
# name ("specialty coffee shops", "rooftop bars", "local gyms"). Anything OUTSIDE
# both sets is treated as a proper-noun tell.
_CATEGORY_MODIFIERS: frozenset = frozenset({
    "specialty", "rooftop", "local", "nearby", "cheap", "trendy", "popular",
    "best", "top", "good", "nice", "big", "small", "new", "old", "craft",
    "indie", "the", "a", "an", "some", "any", "all", "my", "other",
})


def _is_category_like_name(
    name: str,
    extra_nouns: frozenset = frozenset(),
    extra_modifiers: frozenset = frozenset(),
) -> bool:
    """True when `name` reads as a generic CATEGORY, not a proper venue name —
    the last-line defense before a category phrase that leaked into a
    name-target slot is silently treated as ONE specific spot. Conservative:
    flags ONLY when every significant token is a known category noun/modifier
    (and at least one is a category noun), so real venue names — including
    lowercase ones ("the rex") — pass through as specific targets.

    `extra_nouns` / `extra_modifiers` widen the sets for one call site without
    changing any other's verdict: the event arm passes the ``_EVENT_CATEGORY_*``
    sets so "music festivals" is flagged, while the place gate's defaults keep
    "Fight Club" resolvable. Because EVERY token must be known, a proper name
    survives even next to a category noun ("Osheaga Festival" — "Osheaga" is a
    proper-noun tell)."""
    nouns = _CATEGORY_NOUNS | extra_nouns
    modifiers = _CATEGORY_MODIFIERS | extra_modifiers
    tokens = [t for t in re.split(r"[\s,]+", name.strip()) if t]
    if not tokens:
        return False
    saw_category_noun = False
    for tok in tokens:
        low = tok.lower().strip(".&'\"")
        if not low:
            continue
        if low in nouns:
            saw_category_noun = True
            continue
        if low in modifiers:
            continue
        # Neither a category noun nor an accepted modifier → proper-noun tell.
        return False
    return saw_category_noun


# ── Grounded named-target resolution ──────────────────────────────────────────
# Decide WHAT a named entity is from LIVE Google Places results, not the LLM's
# (stale) memory: many exact-name outlets ⇒ a brand (keep all); one dominant ⇒ a
# specific spot; several distinct ⇒ ambiguous (caller asks which); nothing ⇒ a
# web-search fallback. This removes the brand-vs-venue guess from the LLM.


# Grounding itself (google-genai client, Search/Maps call, usage billing) lives in
# app.graph.grounding — this module just consumes it as `_gemini_grounded_text`.


async def _web_search_place(
    name: str,
    city_name: str,
    target_radius_km: Optional[float] = None,
    *,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    parent_label: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Web-search fallback for a named place Google Places can't find (novel /
    obscure). Tavily → LLM extracts one street address → geocode → a single POI
    dict, or None. Mirrors ``search_events``' Tavily→extract→geocode pattern.

    ``parent_label`` is the RESOLVED place label ("Newark, NJ, USA"); it is both
    the display value written to ``parent_location`` and the city text every
    query here uses. ``city_name`` is the user's raw token ("Newark") and is only
    the fallback — asking the web about a bare token throws away the
    disambiguation the user already answered, and the web answers for whichever
    same-named place is more prominent ("Sephora Newark" → Newark, DELAWARE).

    ``latitude``/``longitude`` are the caller's search anchor, forwarded to Maps
    grounding so a bare name resolves near the user's area rather than globally."""
    _q_city = parent_label or city_name
    query = f"{name} {_q_city} address location"
    snippets: List[str] = []

    # Grounding-first: Gemini Maps grounding resolves a novel/obscure name to a
    # real place + address (Search grounding fallback). Legacy Tavily runs only
    # when grounding is off/empty. The SAME address-extraction + geocode below
    # turns the text into a single POI, so the {kind:"single"} contract holds.
    if settings.GROUNDING_ENABLED:
        grounded = await _gemini_grounded_text(
            f"What is the full street address of the place named '{name}' in "
            f"{_q_city}? Use up-to-date map/web information. Give the address only.",
            use_maps=True,
            latitude=latitude,
            longitude=longitude,
        )
        if grounded:
            snippets = [grounded]

    if not snippets and settings.TAVILY_API_KEY:
        async with httpx.AsyncClient(timeout=15.0) as client:
            async def _do():
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={"api_key": settings.TAVILY_API_KEY, "query": query,
                          "search_depth": "basic", "max_results": 5, "include_answer": False},
                )
                if resp.status_code in _RETRYABLE_HTTP_CODES:
                    raise httpx.HTTPStatusError("retryable", request=resp.request, response=resp)
                return resp
            try:
                resp = await _with_retry(_do, max_attempts=2, base_delay=1.0)
                if resp.is_success:
                    snippets = [r.get("content", "") for r in resp.json().get("results", []) if r.get("content")]
            except Exception as exc:
                logger.warning("web place fallback Tavily failed: %s", exc)

    if not snippets:
        return None

    llm = ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL, **settings.llm_auth, temperature=0.0,
    )
    prompt = (
        "From these web snippets, extract the single best street address for the "
        f"place named '{name}' in {_q_city}. Return ONLY the address string (no "
        "explanation, no markdown). If none is found, return NONE.\n\n"
        + "\n\n---\n\n".join(snippets)
    )
    address = ""
    try:
        msg, _ = await tracked_ainvoke(llm, [HumanMessage(content=prompt)],
                                       node_name="tool/web_search_place", writer=None)
        address = msg.text.strip().strip("`").strip()
        if address.upper().startswith("NONE"):
            address = ""
    except Exception as exc:
        logger.warning("web place fallback parse failed: %s", exc)

    lookup = address if address else f"{name}, {_q_city}"
    try:
        # allow_coarse stays False: a total miss must stay a miss, NOT degrade to
        # the city centroid (that would pin a bogus point for a nonsense name).
        geo = await geocode_or_place.ainvoke({"location_name": lookup})
    except Exception:
        geo = None
    if isinstance(geo, dict) and geo.get("latitude"):
        return {
            "name": name, "lat": geo["latitude"], "lng": geo["longitude"],
            "radius_km": target_radius_km, "parent_location": parent_label or city_name,
            "types": [], "formatted_address": geo.get("formatted_address"), "named_place": name,
        }
    return None


async def resolve_named_target(
    name: str,
    city_name: str,
    latitude: float,
    longitude: float,
    hint: str = "specific",           # "specific" (prefer one) | "all" (prefer every outlet)
    search_radius_km: Optional[float] = None,
    target_radius_km: Optional[float] = None,
    bounds: Optional[Dict[str, float]] = None,
    locality_filter: Optional[str] = None,
    country_filter: Optional[str] = None,
    state_filter: Optional[str] = None,
    region_polygon: Optional[List[Ring]] = None,
    parent_label: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve ONE named target against live Google Places, classify from the
    result shape, and (on a miss) fall back to web search. No interrupts.

    ``parent_label`` is the display label written to each POI's ``parent_location``
    (defaults to ``city_name``); the Places query text keeps the short city name.

    Returns ``{"kind", "pois", "candidates"}`` where kind is:
      - "brand"     → many exact-name outlets (or hint='all'): pois = all outlets.
      - "single"    → one dominant match: pois = that one spot.
      - "ambiguous" → several distinct strong matches: candidates = options for
                      the caller's disambiguation ask (pois empty).
      - "notfound"  → nothing anywhere (web fallback also missed).
    """
    places = await _collect_places_in_area(
        query=f"{name} in {city_name}",
        latitude=latitude, longitude=longitude, bounds=bounds,
        search_radius_km=search_radius_km, locality_filter=locality_filter,
        country_filter=country_filter, state_filter=state_filter, region_polygon=region_polygon,
        tile=False,          # named venue → relevance order, not a tiled sweep
    )

    def _poi(p: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": p["name"], "lat": p["lat"], "lng": p["lng"],
            "radius_km": target_radius_km, "parent_location": parent_label or city_name,
            "types": p.get("types", []),
            "formatted_address": p.get("formatted_address") or p.get("address"),
            "postal_code": p.get("postal_code", ""),
            "country_code": p.get("country_code", ""),
            "locality_tokens": p.get("locality_tokens") or [],
            "state_tokens": p.get("state_tokens") or [],
            "named_place": name,
            "rating": p.get("rating"),
            "user_ratings_total": p.get("user_ratings_total", 0),
        }

    def _fb_in_area(fb: Dict[str, Any]) -> bool:
        """A web/LLM-derived point never passed through ``_collect_places_in_area``,
        so it has had NO geometric guard — apply the same one here.

        Without it the fallback is a hole straight through every filter: a brand
        with no outlet inside the targeted area finds nothing in Places, asks the
        web instead, and the web answers for the more prominent same-named city
        ("Sephora Newark" → Newark, DELAWARE, ~180 km and one state away from the
        Newark, NJ the user picked). That point then enters the audience as a
        ``single``. Polygon wins over bbox, matching the polygon-primary rule in
        ``_collect_places_in_area``."""
        lat, lng = fb.get("lat"), fb.get("lng")
        if lat is None or lng is None:
            return False
        if region_polygon:
            return _point_in_polygon(float(lat), float(lng), region_polygon)
        if bounds:
            return _point_in_bounds(float(lat), float(lng), bounds)
        return True          # unbounded caller → legacy behaviour

    def _distinct_sites(rows: List[Dict[str, Any]]) -> int:
        """Count genuinely different SITES, not listings.

        Google lists ONE venue several times — a station entrance and its tunnel,
        a mall kiosk, a duplicate user submission — a few metres apart. Counting
        raw rows made a single spot look like a multi-outlet chain ("Pentagon" in
        Arlington: one Metro station listed twice + one unrelated shop = 3
        "outlets"), which fired the brand branch and skipped the disambiguation
        ask entirely. Same rule the geo executor already applies AFTER
        classification (``executors/geo.py`` / ``NAMED_DEDUP_DISTANCE_KM``) —
        rows here all share a normalized name, so distance alone decides."""
        sites: List[tuple[float, float]] = []
        for p in rows:
            lat, lng = float(p["lat"]), float(p["lng"])
            if not any(
                _haversine_km(lat, lng, a, b) < settings.NAMED_DEDUP_DISTANCE_KM
                for a, b in sites
            ):
                sites.append((lat, lng))
        return len(sites)

    _qn = _norm_locality(name)
    scored = []  # (ratio, is_exact, place)
    for p in places:
        if p.get("lat") is None:
            continue
        ratio = _name_match_ratio(p.get("name", ""), name)
        is_exact = _norm_locality(p.get("name", "")) == _qn
        scored.append((ratio, is_exact, p))

    strong = sorted(
        [s for s in scored if s[0] >= settings.NAMED_PLACE_MATCH_MIN],
        key=lambda s: s[0], reverse=True,
    )
    exacts = [s for s in strong if s[1]]
    exact_sites = _distinct_sites([p for _r, _e, p in exacts])

    # BRAND (hint="all"): a brand is defined by its NAME, so select outlets with the
    # strict all-token gate — never the loose ratio's neighbours. Places text search
    # is relevance-fuzzy and a brand with no local outlet fills the page with rivals
    # ("LA Fitness" in a city where it closed → Planet Fitness, Snap Fitness, YMCA);
    # the old `keep = exacts if exacts else strong` shipped exactly those as the
    # brand's outlets. `is_exact` is normalized EQUALITY, so real chains ("Ulta
    # Beauty" ≠ "Ulta") have no exacts and always fell through to that fallback.
    # No brand-grade match → do NOT invent outlets; fall through to the web fallback
    # / notfound below so the caller can honestly report the miss.
    if hint == "all":
        brand_hits = [s for s in scored if _brand_name_match(s[2].get("name", ""), name)]
        if brand_hits:
            brand_hits.sort(key=lambda s: s[0], reverse=True)
            return {"kind": "brand",
                    "pois": [_poi(p) for _r, _e, p in brand_hits[: settings.NAMED_BRAND_MAX]],
                    "candidates": []}
        # No real outlet. Bail out HERE rather than falling through: `strong` is full
        # of relevance neighbours, and the single/ambiguous logic below would happily
        # pin one of them as if it were the brand.
        fb = await _web_search_place(
            name, city_name, target_radius_km, latitude=latitude, longitude=longitude,
            parent_label=parent_label,
        )
        if fb and _fb_in_area(fb):
            return {"kind": "single", "pois": [fb], "candidates": []}
        return {"kind": "notfound", "pois": [], "candidates": []}

    # BRAND (hint="specific"): the query name recurs as an exact outlet name at many
    # DISTINCT sites → the "named place" is really a chain, so keep every outlet.
    # Sites, not listings: repeats of one venue are not outlets (see _distinct_sites).
    elif exact_sites >= settings.NAMED_CHAIN_MIN_OUTLETS:
        return {"kind": "brand",
                "pois": [_poi(p) for _r, _e, p in exacts[: settings.NAMED_BRAND_MAX]],
                "candidates": []}

    # NOTFOUND in Places → web-search fallback (single pin) or truly notfound.
    if not strong:
        fb = await _web_search_place(
            name, city_name, target_radius_km, latitude=latitude, longitude=longitude,
            parent_label=parent_label,
        )
        if fb and _fb_in_area(fb):
            return {"kind": "single", "pois": [fb], "candidates": []}
        return {"kind": "notfound", "pois": [], "candidates": []}

    # SINGLE: only one strong match, exactly one exact SITE, or a clear dominant
    # (a big ratio gap to the runner-up) → that spot only. Sites, not listings:
    # a venue Google lists twice is still one venue, and counting rows made it
    # look like a tie that had to be asked about.
    dominant = len(strong) == 1 or exact_sites == 1 or (
        len(strong) >= 2 and (strong[0][0] - strong[1][0]) >= 0.35
    )
    if dominant:
        if _is_category_like_name(name):
            # A category phrase ("coffee shops") leaked into a name-target slot —
            # never silently pin the one venue that happened to match; surface the
            # top candidates so the caller ASKS (or the user re-routes to category).
            return {"kind": "ambiguous", "pois": [],
                    "candidates": [_poi(p) for _r, _e, p in
                                   strong[: settings.NAMED_PLACE_PER_NAME_LIMIT]]}
        # One exact site wins over `strong[0]`: ratio saturates at 1.0 for a
        # single-token query ("Pentagon" scores 1.0 for "Pentagon City" too), so
        # the top of `strong` can be a neighbour that merely contains the name.
        best = exacts[0][2] if exact_sites == 1 else strong[0][2]
        return {"kind": "single", "pois": [_poi(best)], "candidates": []}

    # AMBIGUOUS: several distinct strong candidates, none dominant → caller asks.
    return {"kind": "ambiguous", "pois": [],
            "candidates": [_poi(p) for _r, _e, p in strong[: settings.NAMED_PLACE_PER_NAME_LIMIT]]}


# ── Tool: search_events ──────────────────────────────────────────────────────
#
# Retrieve → extract → verify. Retrieval (grounded search + Tavily) keeps every
# source separate; ONE structured LLM call extracts candidate events together
# with the sentence that supports each; deterministic code then rejects anything
# that is not in the evidence, not dated inside the window, or not located — by
# Google, never OSM — inside the target area. Nothing is trusted because the
# model said so: each event's dates buy a paid audience query, its venue is the
# geofence.


class _EventItem(BaseModel):
    """One candidate event as the extractor read it from the evidence."""

    event_name: str
    venue_name: str
    address: str = ""
    start_date: Optional[str] = None       # ISO YYYY-MM-DD, null when the evidence gives none
    end_date: Optional[str] = None
    evidence_index: int = -1               # the [n] of the evidence item that names the event
    evidence_quote: str = ""               # verbatim phrase from that item naming the event


class _EventExtraction(BaseModel):
    events: List[_EventItem] = Field(default_factory=list)


_MONTH_WORDS: Dict[int, set] = {
    m: {calendar.month_name[m].casefold(), calendar.month_abbr[m].casefold()}
    for m in range(1, 13)
}
_EVIDENCE_CHARS = 4000     # per-source cap fed to the extractor


def _event_norm(text: str) -> str:
    """Casefold, strip accents/punctuation, drop ordinal suffixes ("25th" → "25")."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", r"\1", t).strip()


def _event_tokens(text: str, min_len: int = 3) -> List[str]:
    return [w for w in _event_norm(text).split() if len(w) >= min_len]


def _parse_iso_date(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return None


def _date_in_evidence(d: date, tokens: List[str]) -> bool:
    """The day number and the month (name, abbreviation or number) appear NEXT TO
    each other in the source. Adjacent, because a bare "1" is also a street number:
    "1 Circuit Gilles Villeneuve … July 26" must not count as evidence for July 1.
    Year-blind on purpose — "July 25-27" backs 2026-07-25 without printing the year."""
    days = {str(d.day), f"{d.day:02d}"}
    months = _MONTH_WORDS[d.month] | {str(d.month), f"{d.month:02d}"}
    day_at = [i for i, t in enumerate(tokens) if t in days]
    month_at = [i for i, t in enumerate(tokens) if t in months]
    return any(abs(i - j) <= 3 for i in day_at for j in month_at)


def verify_event_claim(
    ev: "_EventItem",
    evidence: List[str],
    window: tuple[date, date],
    max_span_days: int,
) -> tuple[Optional[tuple[date, date]], str]:
    """Deterministic check of one extracted event → ``((start, end), "")`` with the
    dates CLIPPED to the window, or ``(None, reason)``.

    Reasons: ``no_evidence`` / ``not_in_evidence`` (the event isn't in the text it
    cites), ``no_date`` / ``bad_dates`` / ``span_too_long`` / ``date_unsupported``
    (the date isn't in that text) / ``outside_window``.
    """
    lo, hi = window
    idx = ev.evidence_index
    if not (0 <= idx < len(evidence)):
        return None, "no_evidence"
    tokens = _event_norm(evidence[idx]).split()
    src_tokens = set(tokens)
    quote = _event_tokens(ev.evidence_quote, 2)
    if not quote:
        return None, "no_evidence"
    if sum(t in src_tokens for t in quote) / len(quote) < 0.8:
        return None, "not_in_evidence"
    name = _event_tokens(ev.event_name)
    if name and sum(t in src_tokens for t in name) / len(name) < 0.6:
        return None, "not_in_evidence"

    start = _parse_iso_date(ev.start_date)
    if start is None:
        return None, "no_date"
    end = _parse_iso_date(ev.end_date) or start
    if end < start:
        return None, "bad_dates"
    if (end - start).days + 1 > max_span_days:
        return None, "span_too_long"
    if not _date_in_evidence(start, tokens):
        return None, "date_unsupported"
    s, e = max(start, lo), min(end, hi)
    if s > e:
        return None, "outside_window"
    return (s, e), ""


def _point_in_target_area(
    lat: float, lng: float,
    bounds: Optional[Dict[str, float]], region_polygon: Optional[List[Ring]],
) -> bool:
    """Polygon wins over bbox (the polygon-primary rule of ``_collect_places_in_area``);
    no area given → unbounded caller, everything passes."""
    if region_polygon:
        return _point_in_polygon(lat, lng, region_polygon)
    if bounds:
        # A country-scope box can cross the antimeridian (Google's US viewport), and
        # an inverted box contains no point on Earth.
        return _point_in_bounds(lat, lng, _normalize_bbox(bounds))
    return True


async def _locate_event_venue(
    ev: "_EventItem",
    city: str,
    *,
    latitude: Optional[float],
    longitude: Optional[float],
    bounds: Optional[Dict[str, float]],
    region_polygon: Optional[List[Ring]],
) -> tuple[Optional[Dict[str, Any]], str]:
    """Locate an event venue with Google only → ``(point, "")`` or ``(None, reason)``.

    Places text search (a named venue is what Places is for) cross-checked against
    Google Geocoding of the stated address. The two disagreeing by more than
    ``EVENT_VENUE_MAX_DRIFT_KM`` means the venue is ambiguous — dropped rather than
    guessed. The chosen point must then sit inside the targeted area.
    Reasons: ``not_geocoded`` / ``venue_ambiguous`` / ``outside_area``.
    """
    venue = (ev.venue_name or "").strip()
    address = (ev.address or "").strip()
    if not venue and not address:
        return None, "not_geocoded"

    place: Optional[Dict[str, Any]] = None
    try:
        anchored = latitude is not None and longitude is not None
        hits = await _google_places_text_search(
            query=", ".join(x for x in (venue, address or city) if x),
            lat=latitude or 0.0, lng=longitude or 0.0,
            radius_meters=50_000.0 if anchored else None,
            max_results=1,
        )
        if hits and hits[0].get("lat") is not None and hits[0].get("lng") is not None:
            place = hits[0]
    except Exception as exc:  # noqa: BLE001 - a Places failure degrades to the geocode arm
        logger.warning("event venue Places lookup failed for %r: %s", venue, exc)

    geo: Optional[Dict[str, Any]] = None
    if address:
        full = address if city.casefold() in address.casefold() else f"{address}, {city}"
        g = await _geocode_core(full, osm_fallback=False)
        if g.get("latitude") is not None and not g.get("error"):
            geo = g

    if place and geo:
        drift = _haversine_km(place["lat"], place["lng"], geo["latitude"], geo["longitude"])
        if drift > settings.EVENT_VENUE_MAX_DRIFT_KM:
            return None, "venue_ambiguous"
    if place:
        lat, lng = float(place["lat"]), float(place["lng"])
        postal, country = place.get("postal_code", ""), place.get("country_code", "")
    elif geo:
        lat, lng = float(geo["latitude"]), float(geo["longitude"])
        postal, country = geo.get("postal_code", ""), geo.get("country_code", "")
    else:
        return None, "not_geocoded"

    if not _point_in_target_area(lat, lng, bounds, region_polygon):
        return None, "outside_area"
    return {"lat": lat, "lng": lng, "postal_code": postal, "country_code": country}, ""


def _event_window(window_start: str, window_end: str, today: date) -> tuple[date, date]:
    """Resolved search window, clamped to what the vendor can serve: ends no later
    than yesterday (today is never served). Missing bounds → the default past year."""
    hi = min(_parse_iso_date(window_end) or today - timedelta(days=1), today - timedelta(days=1))
    lo = _parse_iso_date(window_start) or hi - timedelta(days=365)
    return lo, hi


def event_range_from_days(days: Any, today: Optional[date] = None) -> str:
    """ISO range covering the last ``days`` days ("last 6 months" → 180), ending
    yesterday — or "" when ``days`` isn't a positive number. Lets an event search
    inherit the recency the user already stated (``lookback_days`` /
    ``audience_filter.window_days``) instead of falling back to the default year."""
    try:
        n = int(days)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    today = today or date.today()
    return f"{(today - timedelta(days=n)).isoformat()} to {(today - timedelta(days=1)).isoformat()}"


class _EventWindow(BaseModel):
    start: Optional[str] = None      # ISO YYYY-MM-DD, inclusive
    end: Optional[str] = None


_ISO_RANGE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:to|through|until|-|–|—)\s*(\d{4}-\d{2}-\d{2})", re.I)


async def resolve_event_window(date_range: str, today: Optional[date] = None) -> tuple[date, date]:
    """Turn the user's free-text event date range into a concrete ``(start, end)``.

    ISO ranges parse directly; any other phrase ("Summer 2025", "last month") is
    resolved by ONE structured LLM call given today's date. Empty, unresolvable or
    failed → the default past year. The end is always clamped to yesterday (the
    vendor never serves today), so a window can be empty (``start > end``) when the
    user asked only for the future — callers must check.
    """
    today = today or date.today()
    text = (date_range or "").strip()
    start = end = ""
    if text:
        m = _ISO_RANGE_RE.search(text)
        if m:
            start, end = m.group(1), m.group(2)
        elif _parse_iso_date(text) and len(text) <= 10:
            start = end = text
        else:
            try:
                llm = _make_llm(temperature=0.0).with_structured_output(_EventWindow, include_raw=True)
                win, _ = await tracked_ainvoke(
                    llm,
                    [HumanMessage(content=(
                        f"Today is {today.isoformat()}. Convert this date phrase to an inclusive "
                        "ISO date range (YYYY-MM-DD) covering the whole period it names, e.g. "
                        "'Summer 2025' -> 2025-06-01..2025-08-31, 'June 2026' -> 2026-06-01..2026-06-30. "
                        "Resolve relative phrases against today. Leave both null if it is not a date "
                        f"phrase.\n\nPhrase: {text}"
                    ))],
                    node_name="tool/resolve_event_window", writer=None,
                )
                start, end = win.start or "", win.end or ""
            except Exception as exc:  # noqa: BLE001 - degrade to the default window
                logger.warning("resolve_event_window(%r) failed: %s", text, exc)
    return _event_window(start, end, today)


@tool
async def search_events(
    city: str,
    event_query: str,
    date_range: str = "",
    parent_label: Optional[str] = None,
    window_start: str = "",
    window_end: str = "",
    bounds: Optional[Dict[str, float]] = None,
    region_polygon: Optional[List[Ring]] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Find events that already took place in a city and return verified, targetable
    venue points.

    Accepts either an event type ("music festivals") or a specific event name
    ("Osheaga", "F1 Grand Prix"). Every returned event was found in retrieved web
    text, dated inside the window, and located by Google inside the target area;
    the rest come back in ``rejected`` with a reason.

    Args:
        city: City or area to search in (e.g. "Montreal, QC", "Austin, TX").
        event_query: Event type or specific event name.
        date_range: Human-readable label of the window (display / search text only).
        parent_label: Display label written to each POI's ``parent_location``;
            defaults to ``city``.
        window_start / window_end: ISO bounds of the window. ``window_end`` is
            clamped to yesterday. Empty → the past year.
        bounds / region_polygon: the target area; venues outside are rejected.
        latitude / longitude: the area's centre, to anchor the Places lookup.

    Returns:
        Dict with total_events_found, targetable_poi_coordinates and rejected.
    """
    today = date.today()
    lo, hi = _event_window(window_start, window_end, today)
    result: Dict[str, Any] = {
        "city": city, "event_query": event_query, "date_range": date_range,
        "window": [lo.isoformat(), hi.isoformat()],
        "total_events_found": 0, "targetable_poi_coordinates": [], "rejected": [],
    }
    if lo > hi:
        result["rejected"].append({"event": event_query, "reason": "outside_window"})
        return result

    # Evidence, one entry per source — provenance survives to verification.
    evidence: List[Dict[str, str]] = []
    if settings.GROUNDING_ENABLED:
        grounded, sources = await _gemini_grounded_text(
            f"List real events that TOOK PLACE between {lo.isoformat()} and {hi.isoformat()} "
            f"(today is {today.isoformat()}). Do not list upcoming or cancelled events. "
            "Aim for up to 10 distinct events, not just the headline one. For EACH give: "
            "the event name, the venue name, the venue's full street address, the exact "
            "start and end dates, and the page it comes from.\n"
            f"City: {city}\nEvent search: {event_query}",
            with_sources=True, max_sources=5,
        )
        if grounded:
            evidence.append({"url": ", ".join(sources) or "google-search-grounding", "text": grounded})

    if settings.TAVILY_API_KEY:
        query = f"{event_query} in {city} {date_range or f'{lo.isoformat()} to {hi.isoformat()}'}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            async def _do_tavily_request():
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": settings.TAVILY_API_KEY,
                        "query": query,
                        "search_depth": "advanced",
                        "max_results": 5,
                        "include_answer": False,
                    },
                )
                if resp.status_code in _RETRYABLE_HTTP_CODES:
                    raise httpx.HTTPStatusError(
                        f"Retryable status {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                return resp

            try:
                resp = await _with_retry(_do_tavily_request, max_attempts=3, base_delay=1.0)
                if resp.is_success:
                    for r in resp.json().get("results", []):
                        if r.get("content"):
                            evidence.append({
                                "url": r.get("url") or "tavily",
                                "text": f"{r.get('title') or ''}\n{r['content']}",
                            })
                else:
                    logger.error("Tavily search error: %d %s", resp.status_code, resp.text[:200])
            except Exception as exc:
                logger.error("Tavily search failed after retries: %s", exc)

    if not evidence:
        return result

    evidence_text = [e["text"][:_EVIDENCE_CHARS] for e in evidence]
    numbered = "\n\n".join(f"[{i}] {e['url']}\n{t}" for i, (e, t) in enumerate(zip(evidence, evidence_text)))
    parse_prompt = (
        "You extract real-world events from numbered evidence.\n\n"
        "Rules:\n"
        "- Use ONLY what the evidence states. Never add events or details from memory.\n"
        "- Only events held at a physical venue.\n"
        f"- Only events that took place between {lo.isoformat()} and {hi.isoformat()} "
        f"(today is {today.isoformat()}); skip everything else.\n"
        "- Dates are ISO YYYY-MM-DD. start_date is null when the evidence gives no date; "
        "end_date equals start_date for a single-day event.\n"
        "- evidence_index is the [n] of the item that names the event; evidence_quote is a "
        "verbatim phrase copied from THAT item that names the event.\n"
        "- One entry per distinct event; if nothing qualifies return an empty list.\n\n"
        f"City context: {city}\nEvent search: {event_query}\n\nEvidence:\n{numbered}"
    )
    llm = ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL, **settings.llm_auth, temperature=0.0,
    ).with_structured_output(_EventExtraction, include_raw=True)
    try:
        extraction, _ = await tracked_ainvoke(
            llm, [HumanMessage(content=parse_prompt)], node_name="tool/search_events", writer=None,
        )
        candidates = list(extraction.events)
    except Exception as exc:
        logger.warning("Event LLM extraction failed: %s", exc)
        return result

    seen: set = set()
    for ev in candidates:
        label = f"{ev.event_name} @ {ev.venue_name}"
        dates, reason = verify_event_claim(ev, evidence_text, (lo, hi), settings.EVENT_MAX_SPAN_DAYS)
        point = None
        if dates:
            point, reason = await _locate_event_venue(
                ev, city, latitude=latitude, longitude=longitude,
                bounds=bounds, region_polygon=region_polygon,
            )
        if not (dates and point):
            result["rejected"].append({"event": label, "reason": reason})
            continue
        key = (round(point["lat"], 4), round(point["lng"], 4), dates)
        if key in seen:
            continue
        seen.add(key)
        result["targetable_poi_coordinates"].append({
            "name": f"{ev.event_name or event_query} @ {ev.venue_name}",
            "lat": point["lat"],
            "lng": point["lng"],
            "radius_km": None,
            "parent_location": parent_label or city,
            "types": ["event_venue"],
            "postal_code": point["postal_code"],
            "country_code": point["country_code"],
            "event_start_date": dates[0].isoformat(),
            "event_end_date": dates[1].isoformat(),
        })

    result["total_events_found"] = len(result["targetable_poi_coordinates"])
    if result["rejected"]:
        logger.info("search_events(%r, %r): rejected %s", event_query, city, result["rejected"])
    return result


# ── Website scraper ───────────────────────────────────────────────────────────


_PIXEL_INIT_RE = re.compile(r"fbq\(\s*['\"]init['\"]\s*,\s*['\"](\d{6,20})['\"]")


class _TextExtractor(html.parser.HTMLParser):
    """Strip HTML tags and collect visible text, skipping script/style/head blocks."""

    _SKIP_TAGS = {"script", "style", "head", "noscript", "meta", "link"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth: int = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        raw = " ".join(self._parts)
        return re.sub(r"\s+", " ", raw).strip()


async def fetch_website_text(url: str, max_chars: int = 3000) -> dict[str, Any]:
    """Fetch a webpage and return cleaned visible text for LLM enrichment.

    Never raises — returns an error key instead so callers can skip gracefully.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )
    }

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            html_content = resp.text
    except Exception as exc:
        logger.warning("fetch_website_text: fetch failed for %s — %s", url, exc)
        return {"url": url, "text": "", "error": "fetch_failed"}

    try:
        extractor = _TextExtractor()
        extractor.feed(html_content)
        text = extractor.get_text()[:max_chars]
    except Exception as exc:
        logger.warning("fetch_website_text: parse failed for %s — %s", url, exc)
        return {"url": url, "text": "", "pixel_id": None, "error": "parse_failed"}

    pixel_id: Optional[str] = None
    try:
        m = _PIXEL_INIT_RE.search(html_content)
        if m:
            pixel_id = m.group(1)
    except Exception:
        pixel_id = None

    return {"url": url, "text": text, "pixel_id": pixel_id, "error": None}


# ── Tool: retrieve_marketing_knowledge ────────────────────────────────────────


# Every rule here answers a way this node has actually been wrong. Meta renames
# its products (the objective set churned through ODAX), so undated model memory
# goes stale; and generic marketing queries pull SEO content farms, which is why
# the source preference is explicit — Meta's own docs rank first for these terms,
# which is what makes grounding viable on a topic otherwise full of spam.
#
# The NONE rule exists because this prompt used to answer EVERY question as a
# generic Meta Ads question, including ones about Punk itself ("how do you know
# where people go?", "what's in your database?") — Google has no knowledge of
# Punk to ground against, so those got answered with Meta Pixel/interest-targeting
# facts that are flatly wrong for this product. Punk's own facts live in
# app/graph/knowledge/punk_kb.md, injected into every chatbot turn already — this
# prompt only needs to step aside when a question belongs there instead.
_KNOWLEDGE_PROMPT = (
    "You are a Meta Ads reference. Answer the question using up-to-date "
    "information, preferring Meta's official documentation "
    "(developers.facebook.com, facebook.com/business/help) over blogs, agency "
    "posts, and other SEO content.\n"
    "- Use the product, objective, and metric names Meta uses TODAY.\n"
    "- Give concrete numbers ONLY when a source states them. Never invent a "
    "benchmark, and never present a typical range as a measured figure.\n"
    "- If the answer is uncertain, contested, or varies by account, say so plainly.\n"
    "- Answer for the advertiser's own market and currency below — never default "
    "to the US or USD.\n"
    "- Be concise: at most ~250 words, plain prose, no markdown headers.\n\n"
    "- If this question is about the PUNK PRODUCT ITSELF — its own database, its "
    "data source, how IT knows where people go, its coverage, its pricing — reply "
    "with EXACTLY the single word NONE and nothing else. Those are not public "
    "Meta facts and must not be answered from the web.\n\n"
    "Advertiser context: {context}\n\n"
    "Question: {query}"
)


@tool
async def retrieve_marketing_knowledge(query: str, context: str = "") -> str:
    """
    Retrieve relevant Meta Ads marketing knowledge for a given query.

    Answers from LIVE web sources via Gemini Search grounding, so current product
    names and real figures reach the user instead of the model's undated memory.
    ``knowledge_based_node`` hands the result to ``chatbot_node``, which injects
    it as "knowledge base content to use in your answer" — so what this returns is
    treated as authoritative and must not be invented.

    ``context`` carries the advertiser's business/industry/target market, so the
    grounded answer (currency, applicable rules) fits THEM, not a generic US
    default. It also lets the prompt recognize when a question is really about
    Punk's own product rather than public Meta facts.

    Gated by ``settings.GROUNDING_ENABLED``. Grounding off, failed, or the prompt
    decided this is a Punk-product question (not a public Meta one) ⇒ returns ""
    — the caller must NOT show a canned blurb in its place; an empty string is a
    real "no grounded answer" signal, not a degrade-to-something-else case.

    Args:
        query: Natural-language question about Meta advertising.
        context: Known advertiser context (business, industry, target market).

    Returns:
        String containing relevant guidance, or "" when nothing grounded applies.
    """
    prompt = _KNOWLEDGE_PROMPT.format(context=context or "unknown", query=query)
    grounded, sources, supported = await _gemini_grounded_text(prompt, with_metadata=True)
    grounded = grounded.strip()
    if not grounded or grounded == "NONE":
        return ""
    if supported < settings.GROUNDING_MIN_SUPPORT:
        # Mostly model memory dressed as a web answer — this string is injected as
        # authoritative, so treat it as "no grounded answer" instead.
        logger.info("retrieve_marketing_knowledge: only %.0f%% supported — dropped", supported * 100)
        return ""
    if sources:
        grounded += "\n\nSources: " + ", ".join(sources)
    return grounded
