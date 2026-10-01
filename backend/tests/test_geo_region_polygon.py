"""Region-polygon guards: a wrong OSM entity must never become the POI filter.

The regression: Nominatim's top hit for "Dallas Downtown Historic District, Dallas,
TX, USA" is The Westin Dallas Downtown — a hotel standing INSIDE the district, so the
centroid guard passes by construction. Its ~95 m footprint then collapsed under the
100 m simplify tolerance into a zero-area ring that rejected all 40 POIs Google found.

No network: `_with_retry` wraps the single Nominatim request, so stubbing it is enough.
"""

import pytest

from app.graph import tools
from app.graph.tools import _collect_places_in_area, _fetch_region_polygon

# Google's bounds for the pick, from the failing session's checkpoint.
DALLAS_BOUNDS = {
    "lat_min": 32.7688185, "lat_max": 32.794811,
    "lng_min": -96.8118291, "lng_max": -96.78199219999999,
}


def _rect(lat_min, lat_max, lng_min, lng_max):
    """A closed GeoJSON ring for an axis-aligned box, with enough vertices along the
    edges to survive Douglas-Peucker when the box is large."""
    steps = 8
    pts = []
    for i in range(steps):  # south edge W→E
        pts.append((lng_min + (lng_max - lng_min) * i / steps, lat_min))
    for i in range(steps):  # east edge S→N
        pts.append((lng_max, lat_min + (lat_max - lat_min) * i / steps))
    for i in range(steps):  # north edge E→W
        pts.append((lng_max - (lng_max - lng_min) * i / steps, lat_max))
    for i in range(steps):  # west edge N→S
        pts.append((lng_min, lat_max - (lat_max - lat_min) * i / steps))
    pts.append(pts[0])
    return [[list(p) for p in pts]]


def _nominatim(osm_class, osm_type, lat, lon, ring_coords):
    return [{
        "class": osm_class, "type": osm_type, "lat": str(lat), "lon": str(lon),
        "display_name": f"{osm_type} under test",
        "geojson": {"type": "Polygon", "coordinates": ring_coords},
    }]


@pytest.fixture
def nominatim(monkeypatch):
    """Return a setter that pins Nominatim's response for the next fetch."""
    def _set(payload):
        async def _fake_with_retry(coro_fn, **kwargs):
            return payload
        monkeypatch.setattr(tools, "_with_retry", _fake_with_retry)
    return _set


# The real mis-hit: a hotel inside the district, ratio ≈ 0.00066 of the Google box.
WESTIN = _nominatim(
    "tourism", "hotel", 32.7804465, -96.8018475,
    _rect(32.78018, 32.78072, -96.80232, -96.80138),
)


@pytest.mark.asyncio
async def test_a_venue_nested_in_the_region_is_rejected(nominatim):
    nominatim(WESTIN)
    assert await _fetch_region_polygon(
        "Dallas Downtown Historic District, Dallas, TX, USA",
        place_type="neighborhood", expected_bounds=DALLAS_BOUNDS,
    ) is None


@pytest.mark.asyncio
async def test_a_real_neighbourhood_polygon_still_comes_through(nominatim):
    # Le Plateau-Mont-Royal's shape: same place_type as Dallas, ratio ≈ 1.0.
    nominatim(_nominatim(
        "boundary", "administrative", 32.779, -96.80,
        _rect(32.7695, 32.7940, -96.8110, -96.7830),
    ))
    rings = await _fetch_region_polygon(
        "somewhere, TX, USA", place_type="neighborhood", expected_bounds=DALLAS_BOUNDS,
    )
    assert rings and sum(len(r) for r in rings) >= 3


@pytest.mark.asyncio
async def test_the_strict_admin_ratio_is_unchanged(nominatim):
    # ~0.2 of the box: under the admin tier (0.3), over the loose tier (0.1).
    small = _nominatim(
        "boundary", "administrative", 32.779, -96.80,
        _rect(32.7735, 32.7851, -96.8051, -96.7918),
    )
    nominatim(small)
    assert await _fetch_region_polygon(
        "a state", place_type="administrative_area_level_1",
        expected_bounds=DALLAS_BOUNDS,
    ) is None
    nominatim(small)   # same polygon, non-admin pick → loose tier keeps it
    assert await _fetch_region_polygon(
        "a neighbourhood", place_type="neighborhood", expected_bounds=DALLAS_BOUNDS,
    ) is not None


@pytest.mark.asyncio
async def test_a_polygon_below_the_simplify_tolerance_is_rejected(nominatim):
    # Right kind, right place, passes the ratio against its OWN tiny bounds — but
    # ~60 m across, so Douglas-Peucker at 100 m flattens it to a zero-area sliver.
    tiny_ring = _rect(32.77990, 32.78045, -96.80235, -96.80170)
    nominatim(_nominatim("place", "neighbourhood", 32.7802, -96.8020, tiny_ring))
    assert await _fetch_region_polygon(
        "a very small place", place_type="neighborhood",
        expected_bounds={
            "lat_min": 32.77990, "lat_max": 32.78045,
            "lng_min": -96.80235, "lng_max": -96.80170,
        },
    ) is None


# ── The wipeout fallback ─────────────────────────────────────────────────────


def _places(n):
    """n distinct POIs spread across the Dallas box."""
    return [
        {
            "name": f"Tower {i}", "lat": 32.771 + i * 0.0009, "lng": -96.805,
            "types": ["establishment"], "address": f"{i} Main St, Dallas, TX, USA",
            "postal_code": "75201", "country_code": "US",
            "locality_tokens": ["Dallas"], "state_tokens": ["Texas", "TX"],
        }
        for i in range(n)
    ]


@pytest.fixture
def places(monkeypatch):
    """Pin the Places response; every tile returns the same set."""
    def _set(items):
        async def _fake_search(**kwargs):
            return items
        monkeypatch.setattr(tools, "_google_places_text_search", _fake_search)
    return _set


# A ring far from Dallas — nothing can be inside it.
ELSEWHERE = [[(-70.0, 40.0), (-70.0, 40.1), (-69.9, 40.1), (-69.9, 40.0), (-70.0, 40.0)]]


@pytest.mark.asyncio
async def test_a_polygon_that_drops_everything_falls_back_to_the_bbox(places):
    places(_places(20))
    out = await _collect_places_in_area(
        "office towers in downtown Dallas", 32.779, -96.80,
        bounds=DALLAS_BOUNDS, region_polygon=ELSEWHERE,
    )
    assert len(out) == 20


@pytest.mark.asyncio
async def test_too_few_candidates_keeps_trusting_the_polygon(places):
    # Below the threshold an empty region is the likelier reading than a bad polygon.
    places(_places(3))
    out = await _collect_places_in_area(
        "office towers in downtown Dallas", 32.779, -96.80,
        bounds=DALLAS_BOUNDS, region_polygon=ELSEWHERE,
    )
    assert out == []


@pytest.mark.asyncio
async def test_a_polygon_that_keeps_some_pois_is_left_alone(places):
    places(_places(20))
    # Covers the southern half of the box: some POIs in, some out, no fallback.
    half = _rect(32.7688185, 32.7818, -96.8118291, -96.78199219999999)
    out = await _collect_places_in_area(
        "office towers in downtown Dallas", 32.779, -96.80,
        bounds=DALLAS_BOUNDS,
        region_polygon=[[tuple(p) for p in half[0]]],
    )
    assert 0 < len(out) < 20
