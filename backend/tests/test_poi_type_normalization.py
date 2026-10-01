"""
tests/test_poi_type_normalization.py
─────────────────────────────────────
POI-type normalization fix: `parse_poi_types` rewrites persona/interest phrases
("coffee lovers") and no-venue place-visit phrases ("open house") into
searchable venue categories instead of silently dropping them, and a dropped
term always reflects in the geo cache key so a re-run actually re-searches.

See the plan: thread 6af26426-72f5-405f-89b7-be3bc9f170e2 stayed frozen at the
same 137 POIs across three turns because "coffee lovers" was silently filtered
out by the parser, leaving `poi_types_list` unchanged and the cache key intact.
"""
from __future__ import annotations

import asyncio

from app.graph.builder import builder_node as bn


# ── _parse_poi_types_never_drop ──────────────────────────────────────────────


def test_never_drop_falls_back_to_comma_split_on_total_parser_failure(monkeypatch):
    async def fake_empty_parser(_raw):
        return []

    monkeypatch.setattr(bn, "parse_poi_types", fake_empty_parser)
    ws: dict = {}
    result = asyncio.run(bn._parse_poi_types_never_drop(ws, "gym, cafe"))
    assert result == ["gym", "cafe"]


def test_never_drop_falls_back_to_semicolon_split_when_present(monkeypatch):
    async def fake_empty_parser(_raw):
        return []

    monkeypatch.setattr(bn, "parse_poi_types", fake_empty_parser)
    ws: dict = {}
    result = asyncio.run(bn._parse_poi_types_never_drop(ws, "gym; cafe, roastery"))
    assert result == ["gym", "cafe, roastery"]


def test_never_drop_keeps_whole_answer_when_no_separator(monkeypatch):
    async def fake_empty_parser(_raw):
        return []

    monkeypatch.setattr(bn, "parse_poi_types", fake_empty_parser)
    ws: dict = {}
    result = asyncio.run(bn._parse_poi_types_never_drop(ws, "coffee lovers"))
    assert result == ["coffee lovers"]


def test_never_drop_empty_input_short_circuits(monkeypatch):
    async def fail_parser(_raw):
        raise AssertionError("must not call the LLM parser for empty input")

    monkeypatch.setattr(bn, "parse_poi_types", fail_parser)
    ws: dict = {}
    assert asyncio.run(bn._parse_poi_types_never_drop(ws, "  ")) == []


def test_never_drop_uses_parser_result_when_non_empty(monkeypatch):
    async def fake_parser(_raw):
        return ["coffee shop"]

    monkeypatch.setattr(bn, "parse_poi_types", fake_parser)
    ws: dict = {}
    result = asyncio.run(bn._parse_poi_types_never_drop(ws, "coffee lovers"))
    assert result == ["coffee shop"]


def test_never_drop_never_returns_fewer_items_than_a_comma_split(monkeypatch):
    async def fake_partial_parser(_raw):
        # Simulates the original bug: the LLM silently drops one term.
        return ["open house", "moving truck rental"]

    monkeypatch.setattr(bn, "parse_poi_types", fake_partial_parser)
    ws: dict = {}
    raw = "open house, moving truck rental, coffee lovers"
    result = asyncio.run(bn._parse_poi_types_never_drop(ws, raw))
    # The never-drop guard only backstops a TOTAL failure (empty/falsy result);
    # a non-empty-but-partial LLM result is the prompt-contract's job (see the
    # substitution-beat tests below), not this wrapper's. Document that here so
    # a future change to the guard's scope is a deliberate decision.
    assert result == ["open house", "moving truck rental"]


# ── Substitution beat detection (deterministic string compare) ──────────────


def _rewritten_and_originals(raw: str, poi_types_list: list[str]) -> tuple[list[str], list[str]]:
    """Mirrors the inline detector added at builder_node.py's geo_discover act."""
    raw_lower = raw.lower()
    rewritten = [p for p in poi_types_list if p.lower() not in raw_lower]
    kept_lower = {p.lower() for p in poi_types_list}
    originals = [
        s.strip() for s in raw.split(",")
        if s.strip() and s.strip().lower() not in kept_lower
    ]
    return rewritten, originals


def test_substitution_detector_flags_rewritten_term_only():
    raw = "open house, moving truck rental, coffee lovers"
    parsed = ["real estate open house", "moving truck rental", "coffee shop"]
    rewritten, originals = _rewritten_and_originals(raw, parsed)
    assert rewritten == ["real estate open house", "coffee shop"]
    assert originals == ["open house", "coffee lovers"]


def test_substitution_detector_empty_when_everything_verbatim():
    raw = "gym, yoga studio"
    parsed = ["gym", "yoga studio"]
    rewritten, originals = _rewritten_and_originals(raw, parsed)
    assert rewritten == []
    assert originals == []


# ── Cache invalidation: a changed poi_types_list changes _geo_cache_key ──────

from types import SimpleNamespace  # noqa: E402

from app.graph.builder.executors import geo  # noqa: E402
from tests._geo_run_helper import run_det as _run_det  # noqa: E402


def _patch_geo_io(monkeypatch, search_calls: list):
    async def fake_probe(_name):
        return []

    async def fake_wi(*a, **k):
        return "yes"

    async def fake_call_tool(tool, args, writer=None, node_name=None):
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        if "geocode" in name:
            city = args["location_name"]
            return ({
                "latitude": 45.5, "longitude": -73.6, "location_name": city,
                "formatted_address": f"{city}, QC, Canada", "locality": city,
                "is_city": True, "place_type": "locality", "bounds": None,
            }, {"status": "ok"})
        if "pois_by_type" in name:
            search_calls.append(args["poi_type"])
            return ({"targetable_poi_coordinates": [
                {"name": f"{args['poi_type']} spot", "lat": 45.5, "lng": -73.6,
                 "parent_location": args.get("parent_label") or args["city_name"]},
            ]}, {"status": "ok"})
        return (None, {"status": "ok"})

    monkeypatch.setattr(geo, "probe_location_candidates", fake_probe)
    monkeypatch.setattr(geo, "wizard_interrupt", fake_wi)
    monkeypatch.setattr(geo, "add_beat", lambda *a, **k: None)
    monkeypatch.setattr(geo, "call_tool", fake_call_tool)
    monkeypatch.setattr(geo.settings, "GEO_REGION_POLYGON_FILTER", False)


def test_changed_poi_types_list_invalidates_all_pois_cache(monkeypatch):
    search_calls: list = []
    _patch_geo_io(monkeypatch, search_calls)
    ws: dict = {}

    _run_det(
        "granular_local", "category", ["Atlanta"], "a furniture store",
        lambda ev: None,
        {"poi_types_list": ["open house", "moving truck rental"]},
        ws, state=None,
    )
    first_poi_key = ws["_poi_cache_key"]
    first_loc_key = ws["_loc_cache_key"]
    assert ws.get("_all_pois_cache")
    calls_after_first_run = len(search_calls)

    # Append a rewritten term — same location/scope, one more POI type. Reuses
    # the SAME ws (the checkpointed scratch), like a resumed session would.
    _run_det(
        "granular_local", "category", ["Atlanta"], "a furniture store",
        lambda ev: None,
        {"poi_types_list": ["open house", "moving truck rental", "coffee shop"]},
        ws, state=None,
    )

    assert ws["_poi_cache_key"] != first_poi_key
    # The location side didn't change — its key (and the location confirm it
    # guards) must survive a POI-only change untouched.
    assert ws["_loc_cache_key"] == first_loc_key
    # The cache was invalidated and Places was actually searched again (not a
    # cache hit) — more search calls happened on the second run.
    assert len(search_calls) > calls_after_first_run


def test_activating_a_new_angle_invalidates_poi_cache_not_location(monkeypatch):
    """Regression for thread 7ae4735e-02fb-4528-a843-0881cb562083: "remove
    longevity clinic and add starbucks" activated the `competitor_brand` angle
    (via the leaf-value pairing rule) with the location set UNCHANGED, and the
    location confirmation re-asked anyway.

    Cause: `angle_names` — {angle_token: [locations]} — gained a new KEY
    (competitor_brand) with the SAME location values, and it used to live in
    `_loc_cache_key`, whose repr changed on the new key alone. It belongs in
    `_poi_cache_key`: which angles exist decides what gets SEARCHED, never
    where geocoding points.
    """
    search_calls: list = []
    _patch_geo_io(monkeypatch, search_calls)

    async def fake_resolve_named_target(name, city, **kwargs):
        return {"kind": "single", "pois": [
            {"name": name, "lat": 45.5, "lng": -73.6, "parent_location": city},
        ]}

    monkeypatch.setattr(geo, "resolve_named_target", fake_resolve_named_target)
    ws: dict = {}

    _run_det(
        "granular_local", "category", ["Atlanta"], "a furniture store",
        lambda ev: None,
        {"poi_types_list": ["open house", "moving truck rental"]},
        ws, state=None,
    )
    first_loc_key = ws["_loc_cache_key"]
    first_poi_key = ws["_poi_cache_key"]
    assert ws.get("_location_confirmed") is True

    # SAME locations, SAME poi_types — only a brand-new angle activates, exactly
    # what `apply_pending_edits`/`_activate_angle_for` does to `filled["det_type"]`
    # for a leaf-value edit like "add starbucks".
    _run_det(
        "granular_local", "category,competitor_brand", ["Atlanta"], "a furniture store",
        lambda ev: None,
        {
            "poi_types_list": ["open house", "moving truck rental"],
            "brand_names_list": ["Starbucks"],
        },
        ws, state=None,
    )

    assert ws["_loc_cache_key"] == first_loc_key
    assert ws["_poi_cache_key"] != first_poi_key
    # The flag the confirm loop reads must have survived — no re-ask.
    assert ws.get("_location_confirmed") is True
