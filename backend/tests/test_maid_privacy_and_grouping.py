"""
Covers the POI/MAID changes: no raw device id over SSE, POI category/brand
grouping (with a per-group audience slice for frontend tabs), and the
union/intersection/difference set-op with frequency layering.
"""
import pytest

from app.graph.maid_query import (
    attribute_audience,
    compute_visit_stats,
    group_pois_by_category_with_audience,
    public_observations,
)
from app.graph.unacast_query import poi_key
from app.services import maid_store

GYM = {"name": "Gold's Gym", "lat": 45.51, "lng": -73.58, "radius_km": 0.5,
       "source_angle": "category", "parent_poi_type": "gym"}
COFFEE = {"name": "Tim Hortons", "lat": 45.52, "lng": -73.59, "radius_km": 0.5,
          "source_angle": "category", "parent_poi_type": "coffee shop"}
POIS = [GYM, COFFEE]


def _visits(*days: str) -> list[dict]:
    return [
        {"ts": f"{d}T12:00:00+00:00", "dwell_min": 10, "dwell_lower_s": 600, "n_pings": 2}
        for d in days
    ]


# A: gym only, 2 visits. B: both venues, 1 visit each. C: coffee only, 5 visits.
RAW_OBS = [
    {"lat": GYM["lat"], "lng": GYM["lng"], "maid": "A", "count": 2, "poi_key": poi_key(GYM),
     "days": ["2026-08-01", "2026-08-02"], "visits": _visits("2026-08-01", "2026-08-02")},
    {"lat": GYM["lat"], "lng": GYM["lng"], "maid": "B", "count": 1, "poi_key": poi_key(GYM),
     "days": ["2026-08-03"], "visits": _visits("2026-08-03")},
    {"lat": COFFEE["lat"], "lng": COFFEE["lng"], "maid": "B", "count": 1, "poi_key": poi_key(COFFEE),
     "days": ["2026-08-03"], "visits": _visits("2026-08-03")},
    {"lat": COFFEE["lat"], "lng": COFFEE["lng"], "maid": "C", "count": 5, "poi_key": poi_key(COFFEE),
     "days": ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04", "2026-08-05"],
     "visits": _visits("2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04", "2026-08-05")},
]


def test_attribute_audience_stamps_poi_ids_and_keeps_frequency():
    total, kept = attribute_audience([dict(r) for r in RAW_OBS], [dict(GYM), dict(COFFEE)])
    assert total == 3  # A, B, C — deduped union
    by_maid = {(r["maid"], r["lat"]): r for r in kept}
    gym_row_a = by_maid[("A", GYM["lat"])]
    assert gym_row_a["poi_ids"] == ["category:gym"]
    assert gym_row_a["count"] == 2 and gym_row_a["days"] == ["2026-08-01", "2026-08-02"]  # not stripped
    coffee_row_c = by_maid[("C", COFFEE["lat"])]
    assert coffee_row_c["poi_ids"] == ["category:coffee shop"]


def test_public_observations_strips_everything_but_coordinates():
    total, kept = attribute_audience([dict(r) for r in RAW_OBS], [dict(GYM), dict(COFFEE)])
    public = public_observations(kept)
    assert len(public) == len(kept)
    for row in public:
        assert set(row.keys()) == {"lat", "lng"}


def test_group_pois_by_category_with_audience_builds_per_tab_slices():
    _, kept = attribute_audience([dict(r) for r in RAW_OBS], [dict(GYM), dict(COFFEE)])
    groups = {g["id"]: g for g in group_pois_by_category_with_audience(POIS, kept)}

    assert set(groups) == {"category:gym", "category:coffee shop"}
    gym_group = groups["category:gym"]
    assert gym_group["key"] == "gym" and gym_group["kind"] == "category" and gym_group["count"] == 1
    assert gym_group["maid_count"] == 2  # A, B
    assert all(set(o.keys()) == {"lat", "lng"} for o in gym_group["maid_observations"])  # redacted

    coffee_group = groups["category:coffee shop"]
    assert coffee_group["maid_count"] == 2  # B, C

    # A device at both venues counts in both groups — group counts don't have
    # to sum to the combined (deduped) total of 3.
    assert gym_group["maid_count"] + coffee_group["maid_count"] > 3


@pytest.mark.asyncio
async def test_compute_audience_set_op_union_and_intersection(monkeypatch):
    _, kept = attribute_audience([dict(r) for r in RAW_OBS], [dict(GYM), dict(COFFEE)])

    async def _fake_fetch(extraction_id):
        return {"pois": POIS, "observations": kept, "lookback_days": 7}

    monkeypatch.setattr(maid_store, "fetch_maid_extraction", _fake_fetch)

    union = await maid_store.compute_audience_set_op(
        "fake-id", ["category:gym", "category:coffee shop"], "union"
    )
    assert union["maid_count"] == 3 and set(union["maids"]) == {"A", "B", "C"}

    intersection = await maid_store.compute_audience_set_op(
        "fake-id", ["category:gym", "category:coffee shop"], "intersection"
    )
    assert intersection["maids"] == ["B"]  # only device seen at both
    assert set(intersection["maids"]) <= set(union["maids"])


@pytest.mark.asyncio
async def test_compute_audience_set_op_frequency_layering(monkeypatch):
    _, kept = attribute_audience([dict(r) for r in RAW_OBS], [dict(GYM), dict(COFFEE)])

    async def _fake_fetch(extraction_id):
        return {"pois": POIS, "observations": kept, "lookback_days": 7}  # 1 week window

    monkeypatch.setattr(maid_store, "fetch_maid_extraction", _fake_fetch)

    # threshold = 2 visits/week * 1 week = 2 visits. B (1 visit at each venue)
    # drops out everywhere; A (2 at gym) and C (5 at coffee) survive their own
    # group but never intersect — so a min-frequency intersection is empty.
    result = await maid_store.compute_audience_set_op(
        "fake-id", ["category:gym", "category:coffee shop"], "intersection",
        min_visits_per_week=2,
    )
    assert result["maids"] == []

    union = await maid_store.compute_audience_set_op(
        "fake-id", ["category:gym", "category:coffee shop"], "union",
        min_visits_per_week=2,
    )
    assert set(union["maids"]) == {"A", "C"}  # higher-frequency devices stay, B does not
    assert union["visit_basis"] == "visits"


def test_compute_visit_stats_basis_matches_expectation():
    # Sanity check the fixture actually produces "visits" (distinct-day) basis,
    # not "sightings" — the frequency-layering test above depends on it.
    stats = compute_visit_stats(RAW_OBS)
    assert stats["summary"]["basis"] == "visits"


def test_apply_poi_edits_preserves_uncapped_pois():
    from app.graph.builder.executors.geo import apply_poi_edits

    # 277 distinct POIs
    pois_277 = [
        {"name": f"Spot {i}", "lat": 45.50 + (i * 0.001), "lng": -73.57 + (i * 0.001), "radius_km": 0.5}
        for i in range(277)
    ]
    det = {"targetable_pois": pois_277, "pois_found": 277, "poi_radius_km": 0.5}

    # Confirm with no removals/additions
    added, removed = apply_poi_edits(det, {"confirm": True})
    assert len(det["targetable_pois"]) == 277
    assert det["pois_found"] == 277
    assert added == [] and removed == []


def test_resolve_poi_zips_uncapped():
    from app.graph.tools import resolve_poi_zips

    pois_250 = [
        {"name": f"Spot {i}", "lat": 40.70 + (i * 0.001), "lng": -74.00 + (i * 0.001),
         "postal_code": f"{10000 + i}", "country_code": "US"}
        for i in range(250)
    ]
    geo_data = {"targetable_pois": pois_250}
    zips = resolve_poi_zips(geo_data)
    assert len(zips) == 250
    assert geo_data["target_zips"] == zips


# ── shared poi_key across categories: the tighter gap wins, neither loses ────
# poi_key is coordinates + radius only, so the SAME physical place found under
# two search labels (e.g. "PetSmart" the brand and "pet store" the category)
# shares one key. A plain overwrite let whichever group was built last decide
# the visit-gap threshold, and — in run_maid_query's per-group row counter —
# silently dropped the other group's row entirely, which an
# op: intersection filter then read as "nobody qualified" even though the
# vendor answered for that spot (thread 237aca1b).

def test_category_by_key_keeps_the_tighter_gap_for_a_shared_poi(monkeypatch):
    from app.core import config
    from app.graph.builder.executors.maid import _category_by_key

    monkeypatch.setattr(
        config.settings, "MAID_VISIT_GAP_BY_CATEGORY",
        "pet store:45,petsmart:10", raising=False,
    )
    shared = {"name": "PetSmart", "lat": 45.51, "lng": -73.58, "radius_km": 0.5,
              "source_angle": "category", "parent_poi_type": "pet store"}
    shared_brand = {**shared, "source_angle": "competitor_brand", "parent_poi_type": "petsmart"}

    out = _category_by_key([shared, shared_brand])

    # One physical place, one key — and it resolved to the TIGHTER (smaller
    # gap-minutes) of the two categories that share it, not whichever was
    # grouped last.
    assert len(out) == 1
    assert list(out.values())[0] == "petsmart"
