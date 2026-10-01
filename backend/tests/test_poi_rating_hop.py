"""
tests/test_poi_rating_hop.py
─────────────────────────────
Guards the hop a new Places field has to survive: `_collect_places_in_area`
passes dicts through untouched, but `search_pois_by_type` (the main
category-sweep arm) and its 3 siblings (search_brand_locations,
search_named_places, resolve_named_target's _poi()) each REBUILD a
fixed-key dict — that fixed-key rebuild is the actual silent drop point for
any new Places field. This pins the highest-traffic one; see tools.py's
comment at the rebuild site for the sibling list.
"""
import asyncio

from app.graph import tools


def test_rating_survives_search_pois_by_type(monkeypatch):
    async def _fake_collect(**kw):
        return [{
            "name": "Gym A", "lat": 45.5, "lng": -73.6, "types": ["gym"],
            "address": "", "postal_code": "H2X", "country_code": "CA",
            "rating": 4.7, "user_ratings_total": 812,
        }]

    monkeypatch.setattr(tools, "_collect_places_in_area", _fake_collect)

    out = asyncio.run(tools.search_pois_by_type.ainvoke({
        "poi_type": "gym", "city_name": "Montreal",
        "latitude": 45.5, "longitude": -73.6,
    }))
    poi = out["targetable_poi_coordinates"][0]
    assert poi["rating"] == 4.7
    assert poi["user_ratings_total"] == 812


def test_missing_rating_defaults_to_none_not_zero(monkeypatch):
    # "never rated" must stay distinguishable from "rated zero" — a POI with
    # no rating key at all (e.g. an older cached Places response) must NOT
    # come out as rating=0.0, which the Bayesian scorer would treat as a
    # genuine 0-star place instead of "unrated" (pool average).
    async def _fake_collect(**kw):
        return [{"name": "No Rating Yet", "lat": 45.5, "lng": -73.6, "types": ["gym"]}]

    monkeypatch.setattr(tools, "_collect_places_in_area", _fake_collect)

    out = asyncio.run(tools.search_pois_by_type.ainvoke({
        "poi_type": "gym", "city_name": "Montreal",
        "latitude": 45.5, "longitude": -73.6,
    }))
    poi = out["targetable_poi_coordinates"][0]
    assert poi["rating"] is None
    assert poi["user_ratings_total"] == 0
