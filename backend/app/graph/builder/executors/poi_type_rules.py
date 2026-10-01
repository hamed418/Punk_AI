"""
graph/builder/executors/poi_type_rules.py
──────────────────────────────────────────
POI category validation against Google Places' own ``types`` array.

``search_pois_by_type`` runs a free-text ``textQuery`` ("dog park in Fort
Collins") and geo.py stamps EVERY result with the category that was searched
for, regardless of what Places says the place actually is. Places' full-text
search is loose — "dog park" also surfaces breweries, apartment complexes,
swimming pools, and highway rest stops that merely mention parks nearby.
Every POI already carries a ``types`` list from that same search response (see
``tools.py:_extract_postal_and_country`` for the sibling field extracted from
the identical response) — this module is the first thing that actually reads
it to check the category claim.

An allowlist, not a blocklist: a category with an entry here keeps only POIs
whose ``types`` intersect the accepted set. A category with NO entry is
unknown to this module and passes through unfiltered — silence here must
never silently narrow a category nobody has taught this list about yet.
"""
from __future__ import annotations

import re

# Canonical category (matched loosely against the user's free-text label) ->
# accepted Google Places (New) type strings. Keep short: one over-broad type
# here (e.g. bare "store") reopens the exact hole this module closes.
_CATEGORY_TYPES: dict[str, frozenset[str]] = {
    "dog park": frozenset({
        "dog_park", "park", "city_park", "national_park", "state_park",
    }),
    "park": frozenset({
        "park", "dog_park", "city_park", "national_park", "state_park",
        "hiking_area", "nature_preserve", "garden",
    }),
    "pet store": frozenset({
        "pet_store", "pet_care", "pet_boarding_service",
    }),
    "vet clinic": frozenset({
        "veterinary_care", "pet_care",
    }),
    "veterinarian": frozenset({
        "veterinary_care", "pet_care",
    }),
    "gym": frozenset({
        "gym", "fitness_center", "yoga_studio", "sports_club",
    }),
    "yoga studio": frozenset({"yoga_studio", "gym", "fitness_center"}),
    "coffee shop": frozenset({"coffee_shop", "cafe"}),
    "cafe": frozenset({"cafe", "coffee_shop"}),
    "restaurant": frozenset({"restaurant", "meal_takeaway", "meal_delivery"}),
    "bar": frozenset({"bar", "night_club", "pub", "wine_bar"}),
    "grocery store": frozenset({"grocery_store", "supermarket", "food_store"}),
    "supermarket": frozenset({"supermarket", "grocery_store", "food_store"}),
    "pharmacy": frozenset({"pharmacy", "drugstore"}),
    "hardware store": frozenset({"hardware_store", "home_improvement_store"}),
    "salon": frozenset({"beauty_salon", "hair_salon", "hair_care"}),
    "spa": frozenset({"spa", "beauty_salon"}),
    "hotel": frozenset({"hotel", "lodging", "motel", "resort_hotel"}),
    "movie theater": frozenset({"movie_theater"}),
    "shopping mall": frozenset({"shopping_mall", "shopping_center"}),
}


# One canonical Places (New) type per category, for the QUERY-TIME
# `includedType` restriction (Google filters server-side instead of us
# discarding junk after the fact) — deliberately a SMALLER set than
# `_CATEGORY_TYPES` above. `includedType` takes exactly one type string, and
# Places rejects the whole request (HTTP 400) if it doesn't recognize the
# value — a typo'd or since-renamed type would silently zero out a real
# category search rather than just fail to narrow it. Listed here only for
# categories whose primary type is long-standing/unambiguous in Places'
# published type table; the request layer (tools.py) also retries once
# without it on a hard failure, so a wrong value here degrades to today's
# text-only behavior rather than losing real POIs.
_PRIMARY_TYPE: dict[str, str] = {
    "dog park": "dog_park",
    "park": "park",
    "pet store": "pet_store",
    "vet clinic": "veterinary_care",
    "veterinarian": "veterinary_care",
    "gym": "gym",
    "cafe": "cafe",
    "restaurant": "restaurant",
    "bar": "bar",
    "grocery store": "grocery_store",
    "supermarket": "supermarket",
    "pharmacy": "pharmacy",
    "hardware store": "hardware_store",
    "spa": "spa",
    "hotel": "hotel",
    "movie theater": "movie_theater",
    "shopping mall": "shopping_mall",
}


def primary_type(category: str) -> str | None:
    """The single Places (New) type to pass as `includedType` for this
    category's search, or ``None`` when there's no confident primary type
    (the search stays text-only, exactly like today, backstopped by
    ``validate_pois`` after the fact)."""
    return _PRIMARY_TYPE.get(_normalize(category))


def _normalize(label: str) -> str:
    """Lowercase, singularize a trailing "s", collapse whitespace — the small
    set of transforms that let "Dog Parks"/"dog park " match the same
    dictionary key without a second free-text-parsing pass (that job already
    belongs to ``wizard_helpers.parse_poi_types``, an LLM rewrite; this is a
    plain lookup normalizer, not a rewrite)."""
    s = re.sub(r"\s+", " ", str(label or "").strip().lower())
    if s.endswith("s") and not s.endswith("ss") and s[:-1] in _CATEGORY_TYPES:
        s = s[:-1]
    return s


def accepted_types(category: str) -> frozenset[str] | None:
    """Accepted Google Places types for ``category``, or ``None`` when this
    category has no allowlist entry (unknown categories are never filtered)."""
    return _CATEGORY_TYPES.get(_normalize(category))


def validate_pois(pois: list[dict], category: str) -> tuple[list[dict], list[dict]]:
    """Split ``pois`` (already tagged with this ``category`` search) into
    (kept, dropped). ``dropped`` entries are ``{"name", "types"}`` — enough to
    narrate.

    A POI with no ``types`` at all is kept, not dropped — Places occasionally
    omits the field, and an absent signal is not evidence the venue is wrong,
    just evidence there is nothing to check it against.
    """
    accepted = accepted_types(category)
    if accepted is None:
        return pois, []
    kept: list[dict] = []
    dropped: list[dict] = []
    for poi in pois:
        types = {str(t).strip().lower() for t in (poi.get("types") or [])}
        if not types or (types & accepted):
            kept.append(poi)
        else:
            dropped.append({"name": poi.get("name") or "(unnamed)", "types": sorted(types)})
    return kept, dropped
