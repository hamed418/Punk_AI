"""
Unit tests for executors/geo.py's dedup_pois — survivorship must favor a
NAMED arm (a brand/venue the user asked for by name) over a generic guessed
arm (category/ai_suggested) when both return the same physical place.

Regression for thread b1e1fd10-24c7-439b-92ea-ee3a68bce94f: "vet clinic,
PetSmart, dog park" then "also target pet stores" caused the PetSmart brand
copies to be absorbed into the generic "pet store" category group, silently
losing the tab and the bare-count trim protection. Pure function, no DB, no
network.
"""
from app.graph.builder.executors.geo import dedup_pois


def _poi(name, angle, ptype, lat=39.70, lng=-104.96):
    return {"name": name, "source_angle": angle, "parent_poi_type": ptype, "lat": lat, "lng": lng}


def test_named_arm_survives_dedup_over_a_later_generic_type_arm():
    # Same physical store, found by both arms — category dispatched first in
    # discovery order (as it is in run_geo_discover), brand second.
    category_copy = _poi("PetSmart", "category", "pet store")
    brand_copy = _poi("PetSmart", "competitor_brand", "PetSmart")
    out = dedup_pois([category_copy, brand_copy])
    assert len(out) == 1
    assert out[0]["source_angle"] == "competitor_brand"
    assert out[0]["parent_poi_type"] == "PetSmart"


def test_named_arm_wins_regardless_of_which_order_it_arrives_in():
    brand_copy = _poi("PetSmart", "competitor_brand", "PetSmart")
    category_copy = _poi("PetSmart", "category", "pet store")
    out = dedup_pois([brand_copy, category_copy])
    assert len(out) == 1
    assert out[0]["source_angle"] == "competitor_brand"


def test_two_generic_copies_still_collapse_to_one():
    a = _poi("Denver Animal Hospital", "category", "vet clinic")
    b = _poi("Denver Animal Hospital", "ai_suggested", "animal hospital")
    out = dedup_pois([a, b])
    assert len(out) == 1


def test_same_name_far_apart_are_distinct_places_not_deduped():
    a = _poi("Starbucks", "category", "cafe", lat=39.70, lng=-104.96)
    b = _poi("Starbucks", "category", "cafe", lat=39.90, lng=-105.20)  # >150m away
    out = dedup_pois([a, b])
    assert len(out) == 2
