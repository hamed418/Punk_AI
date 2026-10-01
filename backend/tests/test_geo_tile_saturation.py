"""Adaptive tile saturation: a dense area CAN split for more coverage when enabled,
a sparse area must not pay for it, and the whole sweep must respect a hard call
budget without ever starving the uniform base sweep.

Splitting ships OFF by default (GEO_TILE_SPLIT_DEPTH = 0, flat grid, baseline cost)
— tests that exercise it explicitly enable it via monkeypatch.

No network — `_google_places_text_search` is monkeypatched directly, so these
exercise the real tiling/queue/dedup logic in `_collect_places_in_area` without
hitting Google.
"""

import pytest

from app.core.config import settings
from app.graph import tools
from app.graph.tools import _collect_places_in_area

# A modest bbox — big enough to diagonal past GEO_AREA_TILE_THRESHOLD_KM (0, so
# any bbox tiles) and small enough that _tile_bbox's n x n grid is easy to reason
# about at GEO_MAX_TILES=9 -> n=3 -> 9 base tiles.
DALLAS_BOUNDS = {
    "lat_min": 32.7688185, "lat_max": 32.794811,
    "lng_min": -96.8118291, "lng_max": -96.78199219999999,
}


def _place(i, lat, lng):
    return {
        "name": f"Place {i}", "lat": lat, "lng": lng,
        "types": ["establishment"], "address": f"{i} Main St, Dallas, TX, USA",
        "postal_code": "75201", "country_code": "US",
        "locality_tokens": ["Dallas"], "state_tokens": ["Texas", "TX"],
    }


@pytest.fixture
def recording_search(monkeypatch):
    """Patch `_google_places_text_search` with a fake that records every call's
    kwargs and returns `count_per_call(call_index)` places, each at a distinct
    coordinate derived from the call index (so cross-tile dedup never masks a
    call-count assertion)."""
    calls: list[dict] = []

    def _install(count_per_call):
        async def _fake(**kwargs):
            idx = len(calls)
            calls.append(kwargs)
            n = count_per_call(idx)
            return [
                _place(f"{idx}-{i}", 32.77 + idx * 0.0005 + i * 0.00001, -96.80)
                for i in range(n)
            ]
        monkeypatch.setattr(tools, "_google_places_text_search", _fake)
        return calls

    return _install


@pytest.mark.asyncio
async def test_unsaturated_tiles_never_split(recording_search):
    calls = recording_search(lambda _i: 3)  # well under the 20-per-page cap
    await _collect_places_in_area(
        "coffee shops in Dallas", 32.78, -96.80, bounds=DALLAS_BOUNDS,
    )
    assert len(calls) == settings.GEO_MAX_TILES


@pytest.mark.asyncio
async def test_splitting_is_off_by_default(recording_search):
    # Shipped default: GEO_TILE_SPLIT_DEPTH = 0. Even a fully saturated sweep must
    # stay flat at the base tile count — no config override in this test.
    calls = recording_search(lambda _i: 20)  # every call returns a full page
    await _collect_places_in_area(
        "coffee shops in Dallas", 32.78, -96.80, bounds=DALLAS_BOUNDS,
    )
    assert len(calls) == settings.GEO_MAX_TILES


@pytest.mark.asyncio
async def test_saturated_tiles_split_up_to_the_budget_when_enabled(recording_search, monkeypatch):
    monkeypatch.setattr(settings, "GEO_TILE_SPLIT_DEPTH", 1)
    monkeypatch.setattr(settings, "GEO_MAX_TILE_SEARCHES", 24)
    calls = recording_search(lambda _i: 20)  # every call returns a full page
    await _collect_places_in_area(
        "coffee shops in Dallas", 32.78, -96.80, bounds=DALLAS_BOUNDS,
    )
    assert len(calls) == 24


@pytest.mark.asyncio
async def test_budget_never_starves_the_base_sweep(recording_search, monkeypatch):
    # A misconfigured budget below the base tile count must not truncate the base
    # sweep — that would silently drop whole tiles, the exact bug class this file
    # exists to guard against.
    monkeypatch.setattr(settings, "GEO_MAX_TILE_SEARCHES", 1)
    calls = recording_search(lambda _i: 3)
    await _collect_places_in_area(
        "coffee shops in Dallas", 32.78, -96.80, bounds=DALLAS_BOUNDS,
    )
    assert len(calls) == settings.GEO_MAX_TILES


@pytest.mark.asyncio
async def test_max_results_is_wired_to_geo_poi_max_pages(recording_search):
    calls = recording_search(lambda _i: 3)
    await _collect_places_in_area(
        "coffee shops in Dallas", 32.78, -96.80, bounds=DALLAS_BOUNDS,
    )
    expected = max(1, settings.GEO_POI_MAX_PAGES) * 20
    assert calls
    assert all(c.get("max_results") == expected for c in calls)


@pytest.mark.asyncio
async def test_parent_child_overlap_dedups_when_splitting_enabled(monkeypatch):
    monkeypatch.setattr(settings, "GEO_TILE_SPLIT_DEPTH", 1)
    # Every call — parent AND every child it spawns — returns the SAME coordinate,
    # as if the whole area were one dense hotspot. Output must still collapse to
    # one place, not one per call.
    async def _fake(**kwargs):
        return [_place("dup", 32.78, -96.80) for _ in range(20)]  # saturated, forces splits
    monkeypatch.setattr(tools, "_google_places_text_search", _fake)

    out = await _collect_places_in_area(
        "coffee shops in Dallas", 32.78, -96.80, bounds=DALLAS_BOUNDS,
    )
    assert len(out) == 1
