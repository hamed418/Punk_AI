"""A store/competitor ANCHOR resolves to the place, labelled by the place.

Two independent defects, one confirmed in session
6688a65e-d5df-420d-8824-be53a71deb37: the geocoder copies the query back as
``location_name``, so a shop entered as "its in SKS tower in mohakhali" was
mapped under that whole sentence; and separately, the market the user named was
concatenated onto the address before the lookup, appending "Montreal" to a Dhaka
address and carrying the user's typos ("Toronro") straight into Google.

Places now answers first (it returns the canonical name), and the market is a
retry + a warning, never a suffix.
"""
import pytest

from app.graph import tools

SKS = {
    "name": "SKS Tower", "lat": 23.7807, "lng": 90.4074,
    "types": ["point_of_interest"],
    "address": "7 Mohakhali C/A, Dhaka 1212, Bangladesh",
    "postal_code": "1212", "country_code": "BD",
    "locality_tokens": ["Dhaka"], "state_tokens": ["Dhaka Division"],
}

TYPED = "its in SKS tower in mohakhali"


@pytest.fixture
def google(monkeypatch):
    """Pin both Google arms. `seen` records every outgoing query verbatim."""
    seen = {"places": [], "geocode": []}
    box = {"places": [], "geocode": None}

    async def _places(query, lat=0.0, lng=0.0, **kw):
        seen["places"].append(query)
        return box["places"]

    async def _geocode(name, allow_broad=False, scope=None):
        seen["geocode"].append(name)
        return box["geocode"] or {
            "location_name": name, "latitude": None, "longitude": None,
            "error": "geocoding_failed",
        }

    monkeypatch.setattr(tools, "_google_places_text_search", _places)
    monkeypatch.setattr(tools, "_geocode_core", _geocode)
    return seen, box


async def _resolve(**kw):
    return await tools.geocode_or_place.ainvoke({"location_name": TYPED, **kw})


@pytest.mark.asyncio
async def test_the_name_is_googles_not_the_sentence_the_user_typed(google):
    seen, box = google
    box["places"] = [SKS]
    out = await _resolve()
    assert out["location_name"] == "SKS Tower"
    assert seen["geocode"] == []            # Places-first: the geocoder never ran


@pytest.mark.asyncio
async def test_the_geocode_arm_labels_with_the_resolved_address_not_the_query(google):
    _, box = google
    box["geocode"] = {
        "location_name": TYPED, "formatted_address": "Mohakhali, Dhaka, Bangladesh",
        "latitude": 23.7807, "longitude": 90.4074,
    }
    out = await _resolve()                  # Places misses, geocode answers
    assert out["location_name"] == "Mohakhali, Dhaka, Bangladesh"


@pytest.mark.asyncio
async def test_the_named_market_is_never_concatenated_onto_the_address(google):
    seen, box = google
    box["places"] = [SKS]
    await _resolve(market_hint="Montreal")
    assert seen["places"] == [TYPED]        # no ", Montreal" glued on


@pytest.mark.asyncio
async def test_an_address_outside_the_named_market_is_flagged_not_dropped(google):
    _, box = google
    box["places"] = [SKS]
    out = await _resolve(market_hint="Montreal")
    assert out["latitude"] == 23.7807                    # still resolved
    assert "Dhaka" in out["market_mismatch"]


@pytest.mark.asyncio
async def test_an_address_inside_the_named_market_is_not_flagged(google):
    _, box = google
    box["places"] = [
        {**SKS, "address": "1340 Sainte-Catherine St W, Montreal, QC, Canada"}
    ]
    out = await _resolve(market_hint="Montreal")
    assert out["market_mismatch"] == ""


@pytest.mark.asyncio
async def test_the_market_is_a_retry_suffix_only_after_a_bare_miss(google):
    seen, _ = google                                     # both arms miss
    out = await _resolve(market_hint="Montreal")
    assert seen["places"] == [TYPED, f"{TYPED}, Montreal"]
    # allow_coarse defaults False: an owned-store miss must stay a miss rather
    # than degrade to the market's city centroid.
    assert out["latitude"] is None


# ── the store-anchored search's query text ───────────────────────────────────


@pytest.mark.asyncio
async def test_a_store_anchored_search_sends_no_city_when_none_was_named(monkeypatch):
    """The anchor search is pinned by lat/lng + bounds + radius, so the city is
    only ever flavour text. Feeding it the anchor's own `locality` searched a
    borough ("Ville-Marie" for Montreal, "Kafrul" for Dhaka), and feeding it
    `location_name` now searches inside the building ("gym in SKS Tower")."""
    seen = {}

    async def _collect(query, **kw):
        seen["query"] = query
        return []

    monkeypatch.setattr(tools, "_collect_places_in_area", _collect)
    await tools.search_pois_by_type.ainvoke({
        "poi_type": "gym", "city_name": "",
        "latitude": 23.778, "longitude": 90.397, "search_radius_km": 5.0,
    })
    assert seen["query"] == "gym"          # not "gym in "


@pytest.mark.asyncio
async def test_a_named_market_still_reaches_the_query(monkeypatch):
    seen = {}

    async def _collect(query, **kw):
        seen["query"] = query
        return []

    monkeypatch.setattr(tools, "_collect_places_in_area", _collect)
    await tools.search_pois_by_type.ainvoke({
        "poi_type": "gym", "city_name": "Montreal",
        "latitude": 45.5, "longitude": -73.57, "search_radius_km": 5.0,
    })
    assert seen["query"] == "gym in Montreal"
