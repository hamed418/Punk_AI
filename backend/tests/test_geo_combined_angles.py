"""
tests/test_geo_combined_angles.py
─────────────────────────────────
Combining multiple composable targeting angles in ONE geo run.

Covers:
  - slot_applies set semantics (det_type as a comma-joined set): the right
    collection slots activate for a combo, and lookback is asked for a combo
    but skipped for a pure event run.
  - _execute_deterministic fans a 2-angle set (event_based + named_places) into
    both angle searches and merges their POIs into one all_pois, each tagged
    with its parent_poi_type.
"""
import asyncio

import pytest

from app.graph.builder import slots as _slots
from app.graph.builder.slots import slot_applies, SLOTS
from app.graph.builder.executors import geo
from tests._geo_run_helper import run_det as _run_det


# ── slot_applies: det_type as a set ─────────────────────────────────────────────

def test_combo_activates_both_collection_slots():
    filled = {"det_type": "event_based,named_places"}
    assert slot_applies(SLOTS["event_queries"], filled)
    assert slot_applies(SLOTS["named_places"], filled)
    # non-selected angles' slots stay inactive
    assert not slot_applies(SLOTS["poi_types"], filled)
    assert not slot_applies(SLOTS["brand_names"], filled)


def test_combo_asks_lookback_but_pure_event_skips_it():
    # not_when subset rule: skip lookback only when EVERY active angle is event.
    assert slot_applies(SLOTS["lookback_days"], {"det_type": "event_based,named_places"})
    assert not slot_applies(SLOTS["lookback_days"], {"det_type": "event_based"})


def test_store_set_gates_unchanged():
    filled = {"det_type": "store_set"}
    assert not slot_applies(SLOTS["poi_confirm"], filled)   # store IS the POI
    assert not slot_applies(SLOTS["locations"], filled)     # store address is the location


def test_single_angle_backward_compatible():
    assert slot_applies(SLOTS["named_places"], {"det_type": "named_places"})
    assert not slot_applies(SLOTS["event_queries"], {"det_type": "named_places"})


# ── _execute_deterministic: 2-angle fan-in ──────────────────────────────────────

def _patch_executor(monkeypatch):
    """Stub geocoding, the confirm interrupt, and the angle tools so the executor
    runs its search arms deterministically with no network / graph runtime."""

    async def fake_probe(_name):
        return []  # forces the plain-geocode path

    async def fake_wi(*a, **k):
        return "yes"

    def fake_add_beat(*a, **k):
        return None

    async def fake_call_tool(tool, args, writer=None, node_name=None):
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        if "geocode" in name:
            return ({
                "latitude": 45.5, "longitude": -73.6, "location_name": "Montreal",
                "is_city": True, "place_type": "locality", "bounds": None,
            }, {"status": "ok"})
        if "event" in name:
            return ({"targetable_poi_coordinates": [
                {"name": "Osheaga Grounds", "lat": 45.51, "lng": -73.61,
                 "event_start_date": "2026-08-01", "event_end_date": "2026-08-03"},
            ]}, {"status": "ok"})
        if "pois_by_type" in name:
            # A place close to the anchor so the competitor distance filter keeps it.
            return ({"targetable_poi_coordinates": [
                {"name": "Rival Gym", "lat": 45.505, "lng": -73.605},
            ]}, {"status": "ok"})
        return (None, {"status": "ok"})

    async def fake_resolve(name, city_name, latitude, longitude, hint="specific", **kw):
        # One clean single-spot match per named target. Honors `parent_label` the
        # same way the real tool does — the stub must not silently keep emitting
        # the short city name, or it would hide a regression in the callers.
        return {"kind": "single", "candidates": [], "pois": [
            {"name": name, "lat": 45.50, "lng": -73.60,
             "parent_location": kw.get("parent_label") or city_name},
        ]}

    monkeypatch.setattr(geo, "probe_location_candidates", fake_probe)
    monkeypatch.setattr(geo, "wizard_interrupt", fake_wi)
    monkeypatch.setattr(geo, "add_beat", fake_add_beat)
    monkeypatch.setattr(geo, "call_tool", fake_call_tool)
    monkeypatch.setattr(geo, "resolve_named_target", fake_resolve)


def test_execute_combines_event_and_named_pois(monkeypatch):
    _patch_executor(monkeypatch)
    ws: dict = {}
    extra_inputs = {
        "named_places_list": ["Fight Club"],
        "event_queries_list": ["Osheaga"],
    }
    events = []

    def writer(ev):
        events.append(ev)

    _run_det(
        "granular_local",
        "event_based,named_places",
        ["Montreal"],
        "a combat sports brand",
        writer,
        extra_inputs,
        ws,
        state=None,
    )

    det = ws["_det_result"]
    names = {p["name"] for p in det["targetable_pois"]}
    tags = {p.get("parent_poi_type") for p in det["targetable_pois"]}
    # BOTH angles contributed, each with its own parent_poi_type tag.
    assert names == {"Fight Club", "Osheaga Grounds"}
    assert "Osheaga" in tags and "Fight Club" in tags
    assert det["pois_found"] == 2
    # Result label reflects the combined set (comma-joined subtype).
    assert det["targeting_type"] == "granular_local/event_based,named_places"


def test_execute_single_named_place_still_works(monkeypatch):
    _patch_executor(monkeypatch)
    ws: dict = {}
    events = []
    _run_det(
        "granular_local", "named_places", ["Montreal"], "biz",
        lambda ev: events.append(ev),
        {"named_places_list": ["Fight Club"]}, ws, state=None,
    )
    det = ws["_det_result"]
    assert {p["name"] for p in det["targetable_pois"]} == {"Fight Club"}
    assert det["targeting_type"] == "granular_local/named_places"


# ── Collapse: ANY angles may combine — nothing is dropped ────────────────────────

def test_collapse_keeps_mixed_store_and_market():
    from app.graph.nodes import _collapse_deterministic_subtypes
    # Store-anchored + market now COMBINE (union of audience sources) — the market
    # slots re-activate on their own via slot_applies' not_when subset rule.
    assert _collapse_deterministic_subtypes(
        ["store_set", "event_based"]
    ) == "store_set,event_based"
    assert _collapse_deterministic_subtypes(
        ["named_places", "competitor_nearby"]
    ) == "named_places,competitor_nearby"
    assert _collapse_deterministic_subtypes(
        ["competitor_nearby", "store_set", "category"]
    ) == "competitor_nearby,store_set,category"


def test_collapse_keeps_store_anchored_pair():
    from app.graph.nodes import _collapse_deterministic_subtypes
    # The store_set + competitor_nearby pair — kept whole, order-preserving. Shared
    # store address feeds both arms downstream.
    assert _collapse_deterministic_subtypes(
        ["store_set", "competitor_nearby"]
    ) == "store_set,competitor_nearby"
    assert _collapse_deterministic_subtypes(
        ["competitor_nearby", "store_set"]
    ) == "competitor_nearby,store_set"


def test_mixed_run_reactivates_market_slots():
    # The gating claim the whole feature rests on: a mixed set brings the market
    # questions BACK (not a subset of the store-anchored pair), while a pure
    # store-anchored run still skips them.
    from app.graph.builder.slots import slot_applies, SLOTS
    mixed = {"det_type": "store_set,event_based"}
    assert slot_applies(SLOTS["locations"], mixed)
    assert slot_applies(SLOTS["location_scope"], mixed)
    assert slot_applies(SLOTS["store_addresses"], mixed)   # store address still asked
    assert slot_applies(SLOTS["event_queries"], mixed)     # event input still asked
    for pure in ({"det_type": "store_set"}, {"det_type": "store_set,competitor_nearby"}):
        assert not slot_applies(SLOTS["locations"], pure)
        assert not slot_applies(SLOTS["location_scope"], pure)


def test_pair_slot_gating():
    # For the pair, the competitor-anchor slots are suppressed (the shared
    # store_addresses slot collects the anchor once), but the radius is still asked.
    from app.graph.builder.slots import slot_applies, SLOTS
    pair = {"det_type": "store_set,competitor_nearby"}
    assert not slot_applies(SLOTS["competitor_anchor"], pair)
    assert not slot_applies(SLOTS["competitor_anchor_confirm"], pair)
    assert slot_applies(SLOTS["competitor_radius_km"], pair)
    assert slot_applies(SLOTS["store_addresses"], pair)
    # poi_confirm APPLIES for the pair (competitor POIs need gating).
    assert slot_applies(SLOTS["poi_confirm"], pair)
    # Pure competitor_nearby still asks its own anchor + confirm.
    solo = {"det_type": "competitor_nearby"}
    assert slot_applies(SLOTS["competitor_anchor"], solo)
    assert slot_applies(SLOTS["competitor_anchor_confirm"], solo)
    # Pure store_set: competitor slots inactive, poi_confirm skipped.
    ss = {"det_type": "store_set"}
    assert not slot_applies(SLOTS["competitor_radius_km"], ss)
    assert not slot_applies(SLOTS["poi_confirm"], ss)


def test_pair_is_store_anchored():
    from app.graph.nodes import _store_anchored
    assert _store_anchored({"deterministic_subtype": "store_set,competitor_nearby"}) is True


def test_extraction_schema_accepts_store_anchored_pair():
    # Regression: the extraction surface must be ABLE to emit the store-anchored
    # pair the downstream (slots/builder_act/geo) already consumes. Before wiring
    # the producer, deterministic_subtypes' Literal excluded these two values, so
    # the whole pair path was unreachable end-to-end.
    from app.graph.nodes import ExtractedUserInfo, _collapse_deterministic_subtypes
    m = ExtractedUserInfo(deterministic_subtypes=["store_set", "competitor_nearby"])
    assert m.deterministic_subtypes == ["store_set", "competitor_nearby"]
    # …and the entry merge collapses it to the comma-set det_type slots read.
    assert (
        _collapse_deterministic_subtypes(m.deterministic_subtypes)
        == "store_set,competitor_nearby"
    )
    # A store-anchored angle listed with a market angle validates AND survives the
    # collapse whole — any angles may combine, nothing is dropped.
    mixed = ExtractedUserInfo(deterministic_subtypes=["store_set", "event_based"])
    assert _collapse_deterministic_subtypes(
        mixed.deterministic_subtypes
    ) == "store_set,event_based"


def test_subtypes_is_per_turn_not_durable():
    """`deterministic_subtypes` must not survive the turn that produced it.

    It persisted in user_info, so the entry merge re-collapsed STALE angles every
    later turn: a correction ("actually, just events") was silently overwritten back
    to the old combo, and anything keyed off the collapse re-fired each turn. The
    collapsed `deterministic_subtype` is the durable value; the list is transport.
    """
    from app.graph.nodes import _collapse_deterministic_subtypes

    # Simulate the entry merge for turn 1: user names a combo.
    current: dict = {}
    current["deterministic_subtypes"] = ["store_set", "event_based"]
    _multi = current.get("deterministic_subtypes")
    if isinstance(_multi, list) and _multi:
        current["deterministic_subtype"] = _collapse_deterministic_subtypes(_multi)
    current.pop("deterministic_subtypes", None)
    assert current["deterministic_subtype"] == "store_set,event_based"
    # The transport is gone — nothing stale left to re-collapse next turn.
    assert "deterministic_subtypes" not in current

    # Turn 2: user narrows to a single angle. With the list popped, the correction
    # sticks instead of being overwritten back to the old combo.
    current["deterministic_subtype"] = "event_based"
    _multi = current.get("deterministic_subtypes")
    if isinstance(_multi, list) and _multi:
        current["deterministic_subtype"] = _collapse_deterministic_subtypes(_multi)
    assert current["deterministic_subtype"] == "event_based"


# ── Map center: market wins for a mixed run, anchors for a pure competitor run ────

def test_mixed_competitor_map_centers_on_market(monkeypatch):
    _patch_executor(monkeypatch)
    ws: dict = {}
    _run_det(
        "granular_local", "competitor_nearby,event_based", ["Montreal"], "biz",
        lambda ev: None,
        {"competitor_anchors": [{"latitude": 40.0, "longitude": -75.0}],
         "competitor_radius_km": 5, "event_queries_list": ["Osheaga"]},
        ws, state=None,
    )
    # Market angle active → open on the geocoded market (45.5/-73.6), NOT the far
    # anchor at 40/-75 where the event venues aren't.
    assert ws["_det_center"].get("latitude") == 45.5


def test_pure_competitor_map_centers_on_anchor(monkeypatch):
    _patch_executor(monkeypatch)
    ws: dict = {}
    _run_det(
        "granular_local", "competitor_nearby", ["Montreal"], "biz",
        lambda ev: None,
        {"competitor_anchors": [{"latitude": 45.5, "longitude": -73.6}],
         "competitor_radius_km": 5},
        ws, state=None,
    )
    # No market angle → anchor centroid (unchanged single-angle behavior).
    assert ws["_det_center"] == {"latitude": 45.5, "longitude": -73.6}


def test_collapse_market_only_still_joins():
    from app.graph.nodes import _collapse_deterministic_subtypes
    # Pure market combos keep the comma-joined set (order-preserving, de-duped).
    assert _collapse_deterministic_subtypes(
        ["named_places", "event_based"]
    ) == "named_places,event_based"
    assert _collapse_deterministic_subtypes(
        ["category", "category", "event_based"]
    ) == "category,event_based"
    assert _collapse_deterministic_subtypes([]) is None
    assert _collapse_deterministic_subtypes(["", None]) is None


def test_pair_radius_map_uses_store_address(monkeypatch):
    # Regression: for the store_set+competitor_nearby pair the competitor_anchor
    # slot is suppressed, so the radius picker must source its center from
    # store_addresses. Before the fix this branch returned early → no map_data.
    from app.graph.builder import builder_node as bn
    from app.graph.builder.slots import SLOTS

    async def fake_parse_store_addresses(raw):
        return ["123 Main St, New York"]

    async def fake_call_tool(tool, args, writer=None, node_name=None):
        return ({"latitude": 40.7, "longitude": -74.0, "location_name": "New York"},
                {"status": "ok"})

    monkeypatch.setattr(bn, "parse_store_addresses", fake_parse_store_addresses)
    monkeypatch.setattr(bn, "call_tool", fake_call_tool)

    events: list = []
    bs = {"filled": {"det_type": "store_set,competitor_nearby",
                     "store_addresses": "123 Main St, New York",
                     "competitor_anchor": ""}}
    asyncio.run(bn._emit_radius_slot_map(
        SLOTS["competitor_radius_km"], bs, None, events.append
    ))
    maps = [e for e in events if e.get("type") == "map_data"]
    assert maps, "pair should emit a radius_picker map centered on the store address"
    assert maps[0]["content"]["action_type"] == "radius_picker"
    assert "center" in maps[0]["content"]


def test_pure_competitor_no_anchor_emits_no_map():
    # Contrast: pure competitor_nearby with no anchor yet emits nothing (unchanged).
    from app.graph.builder import builder_node as bn
    from app.graph.builder.slots import SLOTS
    events: list = []
    bs = {"filled": {"det_type": "competitor_nearby", "competitor_anchor": ""}}
    asyncio.run(bn._emit_radius_slot_map(
        SLOTS["competitor_radius_km"], bs, None, events.append
    ))
    assert not [e for e in events if e.get("type") == "map_data"]


def test_store_anchored_downstream_sites_correct():
    # With the guard forcing a bare "store_set", the exact-match downstream sites
    # behave: start-gate sees store-anchored, and the store-address fallback bridges
    # a street-address `location` into the store-anchor slot.
    from app.graph.nodes import _store_anchored
    from app.graph.builder.slots import _store_location_fallback, SLOTS
    ui = {"deterministic_subtype": "store_set",
          "location": ["1340 Sainte-Catherine St W, Montreal"]}
    assert _store_anchored(ui) is True
    bridged = _store_location_fallback(SLOTS["store_addresses"], ui)
    assert bridged == ["1340 Sainte-Catherine St W, Montreal"]


# ── poi_types label is the UNION across arms, not last-arm-wins ───────────────────

def test_combo_poi_types_label_is_union(monkeypatch):
    _patch_executor(monkeypatch)
    ws: dict = {}
    _run_det(
        "granular_local",
        "category,event_based",
        ["Montreal"],
        "biz",
        lambda ev: None,
        {"poi_types_list": ["gym"], "event_queries_list": ["Osheaga"]},
        ws,
        state=None,
    )
    det = ws["_det_result"]
    # BOTH the category type and the event query appear — not just the last arm's.
    assert "gym" in det["poi_types"]
    assert "Osheaga" in det["poi_types"]


# ── store_set + competitor_nearby pair: shared anchor, both POI sets ──────────────

def test_execute_store_set_and_competitor_pair(monkeypatch):
    _patch_executor(monkeypatch)
    ws: dict = {}
    # Pair: the shops are BOTH the store_set target POIs AND the competitor anchors.
    # builder_node sources competitor_anchors from the shared store_addresses; here
    # we pass them pre-resolved (mirrors that wiring).
    extra_inputs = {
        "store_addresses_list": ["123 Main St, Montreal"],
        "competitor_anchors": [
            {"latitude": 45.5, "longitude": -73.6, "location_name": "123 Main St"},
        ],
        "competitor_radius_km": 5,
    }
    _run_det(
        "granular_local",
        "store_set,competitor_nearby",
        [],                      # store-anchored: no named market
        "a gym brand",
        lambda ev: None,
        extra_inputs,
        ws,
        state=None,
    )
    det = ws["_det_result"]
    tags = {p.get("parent_poi_type") for p in det["targetable_pois"]}
    names = {p.get("name") for p in det["targetable_pois"]}
    # store_set contributed the own shop (human-readable label, "my stores" —
    # see test_store_group_label_is_human_readable); competitor_nearby
    # contributed the rival.
    assert "my stores" in tags
    assert "Rival Gym" in names
    assert det["targeting_type"] == "granular_local/store_set,competitor_nearby"


# ── competitor_nearby also serves "the types I named, near my store" ─────────────

def _patch_anchor_arm(monkeypatch):
    """Stub the anchor arm's tools; record whether competitor-type inference ran."""
    calls: dict = {"get_competitor_types": 0}

    async def fake_call_tool(tool, args, writer=None, node_name=None):
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        if "competitor_types" in name:
            calls["get_competitor_types"] += 1
            return (["supplement store"], {"status": "ok"})
        if "pois_by_type" in name:
            return ({"targetable_poi_coordinates": [
                {"name": f"{args['poi_type']} near shop", "lat": 25.762, "lng": -80.192},
            ]}, {"status": "ok"})
        if "geocode" in name:
            return ({"latitude": 25.7617, "longitude": -80.1918, "location_name": "Miami",
                     "is_city": True, "place_type": "locality", "bounds": None}, {"status": "ok"})
        return (None, {"status": "ok"})

    async def fake_probe(_n):
        return []

    async def fake_wi(*a, **k):
        return "yes"

    monkeypatch.setattr(geo, "probe_location_candidates", fake_probe)
    monkeypatch.setattr(geo, "wizard_interrupt", fake_wi)
    monkeypatch.setattr(geo, "add_beat", lambda *a, **k: None)
    monkeypatch.setattr(geo, "call_tool", fake_call_tool)
    return calls


def _run_anchor(extra: dict) -> dict:
    ws: dict = {}
    _run_det(
        "granular_local", "competitor_nearby", ["Miami"], "a supplement store",
        lambda ev: None,
        {"competitor_anchors": [{"latitude": 25.7617, "longitude": -80.1918}],
         "competitor_radius_km": 5, **extra},
        ws, state=None,
    )
    return ws


def test_anchor_arm_uses_the_types_the_user_named(monkeypatch):
    # "gyms within 10 min of my supplement store": the user named the types, so search
    # THOSE around the store — never infer competitors (which would find supplement
    # stores, the opposite of what was asked).
    calls = _patch_anchor_arm(monkeypatch)
    ws = _run_anchor({"anchor_types_list": ["gym"]})
    det = ws["_det_result"]
    assert calls["get_competitor_types"] == 0
    assert {p["parent_poi_type"] for p in det["targetable_pois"]} == {"gym"}
    assert det["poi_types"] == ["gym"]
    assert ws["_det_anchor_types_from_user"] is True


def test_anchor_arm_without_user_types_still_infers_competitors(monkeypatch):
    # Unchanged default: no types named → infer the rival types as before.
    calls = _patch_anchor_arm(monkeypatch)
    ws = _run_anchor({})
    det = ws["_det_result"]
    assert calls["get_competitor_types"] == 1
    assert {p["parent_poi_type"] for p in det["targetable_pois"]} == {"supplement store"}
    assert ws["_det_anchor_types_from_user"] is False


def test_anchor_progress_label_does_not_call_user_types_competitors(monkeypatch):
    _patch_anchor_arm(monkeypatch)
    ws = _run_anchor({"anchor_types_list": ["gym"]})
    ws["deterministic_type"] = "competitor_nearby"
    disc = [i for i in geo._build_geo_progress(ws) if i["label"] == "Discovery"][0]
    assert "competitor" not in disc["value"].lower()
    # …and the plain competitor run keeps its original label.
    ws2 = {"deterministic_type": "competitor_nearby"}
    disc2 = [i for i in geo._build_geo_progress(ws2) if i["label"] == "Discovery"][0]
    assert disc2["value"] == "Target people near my competitors"


# ── Phase 0: anchor_types — near-shop types stay separate from city-wide poi_types ─

def test_extraction_schema_accepts_anchor_types():
    # The dedicated near-shop type field must exist on the extraction surface and
    # coerce to a list like its siblings.
    from app.graph.nodes import ExtractedUserInfo, _validate_extracted_field
    m = ExtractedUserInfo(poi_types=["shawarma", "cinema"], anchor_types=["bar"])
    assert m.anchor_types == ["bar"]
    assert m.poi_types == ["shawarma", "cinema"]
    # array-coercion registered: a non-list is dropped, a list passes through
    assert _validate_extracted_field("anchor_types", "bar") is None
    assert _validate_extracted_field("anchor_types", ["bar"]) == ["bar"]


def test_has_angle_recognizes_anchor_types():
    # "bars near my shop" (anchor_types only, no poi_types) must still count as a
    # concrete angle — before the split these types lived in poi_types.
    from app.graph.nodes import _has_angle
    assert _has_angle({"anchor_types": ["bar"]}) is True
    assert _has_angle({}) is False


def test_category_and_anchor_types_do_not_collide(monkeypatch):
    # The core Phase 0 fix at the executor boundary: when category AND
    # competitor_nearby both run, the city-wide poi_types and the near-shop
    # anchor_types feed DIFFERENT arms and both surface, tagged by angle. (The
    # builder_node bridge that fills anchor_types_list from the anchor_types field
    # is exercised end-to-end; here we assert the executor keeps the two sets apart.)
    # Distinct coords per type so global dedup never collapses two real POIs.
    _coords = {
        "shawarma": (45.60, -73.60), "cinema": (45.61, -73.61),
        "bar": (45.505, -73.605),  # ~0.7 km from the anchor → inside the 1 km ring
    }

    async def fake_call_tool(tool, args, writer=None, node_name=None):
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        if "geocode" in name:
            return ({"latitude": 45.5, "longitude": -73.6, "location_name": "Montreal",
                     "is_city": True, "place_type": "locality", "bounds": None}, {"status": "ok"})
        if "pois_by_type" in name:
            pt = args["poi_type"]
            lat, lng = _coords.get(pt, (45.7, -73.7))
            return ({"targetable_poi_coordinates": [
                {"name": f"{pt} spot", "lat": lat, "lng": lng},
            ]}, {"status": "ok"})
        return (None, {"status": "ok"})

    async def fake_probe(_n):
        return []

    async def fake_wi(*a, **k):
        return "yes"

    monkeypatch.setattr(geo, "probe_location_candidates", fake_probe)
    monkeypatch.setattr(geo, "wizard_interrupt", fake_wi)
    monkeypatch.setattr(geo, "add_beat", lambda *a, **k: None)
    monkeypatch.setattr(geo, "call_tool", fake_call_tool)

    ws: dict = {}
    _run_det(
        "granular_local",
        "category,competitor_nearby",
        ["Montreal"],
        "a shawarma shop",
        lambda ev: None,
        {"poi_types_list": ["shawarma", "cinema"],
         "anchor_types_list": ["bar"],
         "competitor_anchors": [{"latitude": 45.5, "longitude": -73.6}],
         "competitor_radius_km": 1},
        ws, state=None,
    )
    det = ws["_det_result"]
    by_angle: dict = {}
    for p in det["targetable_pois"]:
        by_angle.setdefault(p.get("source_angle"), set()).add(p.get("parent_poi_type"))
    # city-wide types went to the category arm; "bar" went to the near-shop arm and
    # never leaked into category.
    assert by_angle.get("category") == {"shawarma", "cinema"}
    assert by_angle.get("competitor_nearby") == {"bar"}
    assert ws["_det_anchor_types_from_user"] is True


# ── event window: MAID only has data for events that already happened ────────────

def test_default_past_event_window_is_in_the_past():
    from datetime import date
    win = geo._default_past_event_window()
    assert win
    # Ends now, starts earlier — never a future window.
    assert date.today().strftime("%B %Y") in win


def test_event_arm_defaults_to_a_past_window(monkeypatch):
    seen: dict = {}

    async def fake_call_tool(tool, args, writer=None, node_name=None):
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        if "geocode" in name:
            return ({"latitude": 39.09, "longitude": -94.57, "location_name": "Kansas City",
                     "is_city": True, "place_type": "locality", "bounds": None}, {"status": "ok"})
        if "event" in name:
            seen["date_range"] = args.get("date_range")
            seen["window"] = (args.get("window_start"), args.get("window_end"))
            return ({"targetable_poi_coordinates": [
                {"name": "Arrowhead Stadium", "lat": 39.05, "lng": -94.48},
            ]}, {"status": "ok"})
        return (None, {"status": "ok"})

    async def fake_probe(_n):
        return []

    async def fake_wi(*a, **k):
        return "yes"

    monkeypatch.setattr(geo, "probe_location_candidates", fake_probe)
    monkeypatch.setattr(geo, "wizard_interrupt", fake_wi)
    monkeypatch.setattr(geo, "add_beat", lambda *a, **k: None)
    monkeypatch.setattr(geo, "call_tool", fake_call_tool)

    async def fake_resolve(text, today=None):
        from datetime import date
        return date(2026, 6, 1), date(2026, 6, 30)

    monkeypatch.setattr(geo, "resolve_event_window", fake_resolve)

    # "the last three Chiefs home games" carries no resolvable date → the extractor
    # leaves event_date_range null. Without a window the search drifts to UPCOMING
    # events, which have no MAID sightings at all.
    ws: dict = {}
    _run_det(
        "granular_local", "event_based", ["Kansas City"], "a sports bar",
        lambda ev: None, {"event_queries_list": ["Chiefs home games"]}, ws, state=None,
    )
    assert seen["date_range"] == geo._default_past_event_window()
    # A concrete ISO window rides along, ending in the past (never today or later).
    from datetime import date as _d
    assert _d.fromisoformat(seen["window"][1]) < _d.today()

    # An explicit range keeps its label and gets its resolved ISO window.
    ws2: dict = {}
    _run_det(
        "granular_local", "event_based", ["Kansas City"], "a sports bar",
        lambda ev: None,
        {"event_queries_list": ["SHRM conference"], "event_date_range": "June 2026"},
        ws2, state=None,
    )
    assert seen["date_range"] == "June 2026"
    assert seen["window"] == ("2026-06-01", "2026-06-30")


def test_execute_mixed_store_and_market(monkeypatch):
    _patch_executor(monkeypatch)
    ws: dict = {}
    # The combo that used to be forbidden: own shops (own address) + events (named
    # market). Both arms run and merge into one POI set.
    _run_det(
        "granular_local",
        "store_set,event_based",
        ["Montreal"],
        "a gym brand",
        lambda ev: None,
        {"store_addresses_list": ["123 Main St, Montreal"],
         "event_queries_list": ["Osheaga"]},
        ws,
        state=None,
    )
    det = ws["_det_result"]
    tags = {p.get("parent_poi_type") for p in det["targetable_pois"]}
    names = {p.get("name") for p in det["targetable_pois"]}
    assert "my stores" in tags          # the shop itself (human-readable label)
    assert "Osheaga Grounds" in names   # the event venue
    assert det["targeting_type"] == "granular_local/store_set,event_based"


# ── source_angle provenance: every POI is tagged with the angle that produced it ──

def test_combo_pois_carry_source_angle(monkeypatch):
    # A combined run must tag each POI with its originating angle so the reveal can
    # break results down BY STRATEGY. event_based → the event venue; named_places →
    # the resolved place.
    _patch_executor(monkeypatch)
    ws: dict = {}
    _run_det(
        "granular_local",
        "event_based,named_places",
        ["Montreal"],
        "a combat sports brand",
        lambda ev: None,
        {"named_places_list": ["Fight Club"], "event_queries_list": ["Osheaga"]},
        ws, state=None,
    )
    by_name = {p["name"]: p.get("source_angle") for p in ws["_det_result"]["targetable_pois"]}
    assert by_name["Osheaga Grounds"] == "event_based"
    assert by_name["Fight Club"] == "named_places"


def test_single_named_place_carries_source_angle(monkeypatch):
    _patch_executor(monkeypatch)
    ws: dict = {}
    _run_det(
        "granular_local", "named_places", ["Montreal"], "biz",
        lambda ev: None,
        {"named_places_list": ["Fight Club"]}, ws, state=None,
    )
    pois = ws["_det_result"]["targetable_pois"]
    assert all(p.get("source_angle") == "named_places" for p in pois)


def test_store_and_competitor_pair_source_angles(monkeypatch):
    _patch_executor(monkeypatch)
    ws: dict = {}
    _run_det(
        "granular_local", "store_set,competitor_nearby", [], "a gym brand",
        lambda ev: None,
        {"store_addresses_list": ["123 Main St, Montreal"],
         "competitor_anchors": [
             {"latitude": 45.5, "longitude": -73.6, "location_name": "123 Main St"}],
         "competitor_radius_km": 5},
        ws, state=None,
    )
    angles = {p["name"]: p.get("source_angle")
              for p in ws["_det_result"]["targetable_pois"]}
    # The own shop came from store_set; the rival from competitor_nearby.
    assert angles.get("Rival Gym") == "competitor_nearby"
    assert "store_set" in set(angles.values())


def test_store_group_label_is_human_readable(monkeypatch):
    """A category+store_set combo (the "exclude my store" shape) used to skip
    the map for a pure store_set run (builder_node's `_result_subs !=
    {"store_set"}` check) — now that it rides alongside a market angle, its
    map tab must read as something other than the internal "store_set"
    token. `resolve_group_labels_verbose`'s self-reference match keys on
    `source_angle`, not this label, so the rename is display-only."""
    _patch_executor(monkeypatch)
    ws: dict = {}
    _run_det(
        "granular_local", "category,store_set", ["Montreal"], "smoothie shop",
        lambda ev: None,
        {"poi_types_list": ["gym"], "store_addresses_list": ["123 Main St, Montreal"]},
        ws, state=None,
    )
    pois = ws["_det_result"]["targetable_pois"]
    groups = {g["source_angle"]: g for g in geo.group_pois_by_category(pois)}
    assert "store_set" in groups
    assert groups["store_set"]["key"] == "my stores"
    assert groups["store_set"]["id"] == "store_set:my stores"


# ── build_angle_breakdown: per-strategy showcase for the combined reveal ──────────

def test_build_angle_breakdown_combined():
    det = {
        "targeting_type": "granular_local/store_set,event_based",
        "targetable_pois": [
            {"name": "Iron Temple Gym", "source_angle": "store_set"},
            {"name": "Osheaga Grounds", "source_angle": "event_based"},
            {"name": "Parc Jean-Drapeau", "source_angle": "event_based"},
        ],
    }
    angles, combined = geo.build_angle_breakdown(det, {})
    assert combined is True
    # Order preserved from the comma-joined set.
    assert [a["token"] for a in angles] == ["store_set", "event_based"]
    store, event = angles
    # Label copy drifted (DET_ANGLE_LABELS). Assert the token + count, which are
    # the contract, and only that the label names the right angle.
    assert store["count"] == 1 and "my own" in store["label"]
    assert store["sample_places"] == ["Iron Temple Gym"]
    assert event["count"] == 2
    assert event["sample_places"] == ["Osheaga Grounds", "Parc Jean-Drapeau"]


def test_build_angle_breakdown_single_not_combined():
    det = {
        "targeting_type": "granular_local/category",
        "targetable_pois": [
            {"name": "Gym A", "source_angle": "category"},
            {"name": "Gym B", "source_angle": "category"},
        ],
    }
    angles, combined = geo.build_angle_breakdown(det, {})
    assert combined is False
    assert len(angles) == 1 and angles[0]["count"] == 2


def test_build_angle_breakdown_one_arm_empty_is_not_combined():
    # Two angles requested but only one found spots → not a genuine combo, so it
    # narrates on the single-angle path.
    det = {
        "targeting_type": "granular_local/store_set,event_based",
        "targetable_pois": [{"name": "Iron Temple Gym", "source_angle": "store_set"}],
    }
    angles, combined = geo.build_angle_breakdown(det, {})
    assert combined is False
    assert [a["count"] for a in angles] == [1, 0]


def test_build_angle_breakdown_anchor_types_relabel():
    # When the user named the search types near their store, competitor_nearby is
    # relabeled away from "competitors".
    det = {
        "targeting_type": "granular_local/competitor_nearby,event_based",
        "targetable_pois": [
            {"name": "Gym near shop", "source_angle": "competitor_nearby"},
            {"name": "Osheaga Grounds", "source_angle": "event_based"},
        ],
    }
    angles, combined = geo.build_angle_breakdown(det, {"_det_anchor_types_from_user": True})
    labels = {a["token"]: a["label"] for a in angles}
    assert labels["competitor_nearby"] == geo.ANCHOR_TYPES_LABEL


# ── edit-at-confirm re-geocodes + re-emits the map (the reported bug) ──────────────

def test_location_edit_at_confirm_regeocodes_and_reemits_map(monkeypatch):
    """User confirms Columbus, then replies "add whitehall" at the confirm step.
    The executor must re-geocode the merged set and emit a SECOND confirm_locations
    map containing both cities — not silently re-show the old widget with no map."""
    from app.graph.resume_router import ResumeResult

    _geo_by_name = {
        "columbus": {"latitude": 39.96, "longitude": -83.0, "location_name": "Columbus",
                     "is_city": True, "place_type": "locality", "bounds": None,
                     "formatted_address": "Columbus, OH, USA"},
        "whitehall": {"latitude": 39.96, "longitude": -82.88, "location_name": "Whitehall",
                      "is_city": True, "place_type": "locality", "bounds": None,
                      "formatted_address": "Whitehall, OH, USA"},
    }

    async def fake_probe(_n):
        return []

    async def fake_call_tool(tool, args, writer=None, node_name=None):
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        if "geocode" in name:
            loc = str(args.get("location_name", "")).lower()
            for key, val in _geo_by_name.items():
                if key in loc:
                    return (val, {"status": "ok"})
            return (None, {"status": "ok"})
        if "pois_by_type" in name:
            return ({"targetable_poi_coordinates": [
                {"name": "Coin Laundry", "lat": 39.96, "lng": -83.0},
            ]}, {"status": "ok"})
        return (None, {"status": "ok"})

    # First confirm interrupt returns an append edit (merged set); second confirms.
    # The confirm map rides `repeat_events` (wizard_interrupt re-emits it before
    # EVERY render, including its own in-place re-asks), so the executor-level
    # assertion is on what it handed the interrupt, not on a bare writer event.
    _confirm_calls = {"n": 0}
    _repeat: list[list] = []

    async def fake_wi(*a, **k):
        if k.get("step_key") == "geo_location_confirmation":
            _confirm_calls["n"] += 1
            _repeat.append(list(k.get("repeat_events") or []))
            if _confirm_calls["n"] == 1:
                return ResumeResult(
                    "add whitehall",
                    edits={"geo_locations": ["Columbus", "whitehall"]},
                )
        return ResumeResult("yes", edits={})

    monkeypatch.setattr(geo, "probe_location_candidates", fake_probe)
    monkeypatch.setattr(geo, "wizard_interrupt", fake_wi)
    monkeypatch.setattr(geo, "add_beat", lambda *a, **k: None)
    monkeypatch.setattr(geo, "call_tool", fake_call_tool)

    ws: dict = {}
    events: list = []
    _run_det(
        "granular_local", "category", ["Columbus"], "a laundromat",
        events.append, {"poi_types_list": ["laundromat"]}, ws, state=None,
    )

    confirm_maps = [
        ev for events_for_call in _repeat for ev in events_for_call
        if ev.get("type") == "map_data"
        and ev["content"].get("action_type") == "confirm_locations"
    ]
    # TWO confirm maps: initial (Columbus), then the re-emit after the edit.
    assert len(confirm_maps) == 2
    names = {loc.get("location_name") for loc in confirm_maps[-1]["content"]["locations"]}
    assert names == {"Columbus", "Whitehall"}
    # Merged set stashed for builder_node's slot persistence + confirmed only after
    # the plain "yes".
    assert ws["_locations_synced"] == ["Columbus", "whitehall"]
    assert ws["_location_confirmed"] is True


def test_location_confirm_no_edit_emits_single_map(monkeypatch):
    """A plain confirm (no edit) emits exactly one confirm map — the loop does not
    spin or double-emit."""
    from app.graph.resume_router import ResumeResult

    async def fake_probe(_n):
        return []

    async def fake_call_tool(tool, args, writer=None, node_name=None):
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        if "geocode" in name:
            return ({"latitude": 39.96, "longitude": -83.0, "location_name": "Columbus",
                     "is_city": True, "place_type": "locality", "bounds": None,
                     "formatted_address": "Columbus, OH, USA"}, {"status": "ok"})
        if "pois_by_type" in name:
            return ({"targetable_poi_coordinates": [
                {"name": "Coin Laundry", "lat": 39.96, "lng": -83.0}]}, {"status": "ok"})
        return (None, {"status": "ok"})

    _repeat: list[list] = []

    async def fake_wi(*a, **k):
        if k.get("step_key") == "geo_location_confirmation":
            _repeat.append(list(k.get("repeat_events") or []))
        return ResumeResult("yes", edits={})

    monkeypatch.setattr(geo, "probe_location_candidates", fake_probe)
    monkeypatch.setattr(geo, "wizard_interrupt", fake_wi)
    monkeypatch.setattr(geo, "add_beat", lambda *a, **k: None)
    monkeypatch.setattr(geo, "call_tool", fake_call_tool)

    ws: dict = {}
    events: list = []
    _run_det(
        "granular_local", "category", ["Columbus"], "a laundromat",
        events.append, {"poi_types_list": ["laundromat"]}, ws, state=None,
    )
    confirm_maps = [
        ev for events_for_call in _repeat for ev in events_for_call
        if ev.get("type") == "map_data"
        and ev["content"].get("action_type") == "confirm_locations"
    ]
    assert len(confirm_maps) == 1
    assert "_locations_synced" not in ws


# ── Phase 1: per-angle location + types (each angle its own WHERE + WHAT) ──────────

def _patch_multi_city(monkeypatch):
    """Geocode distinct coords per city; POI/event tools echo the searched city so a
    test can prove each arm searched only ITS OWN market."""
    _city_geo = {
        "toronto": {"latitude": 43.65, "longitude": -79.38, "location_name": "Toronto",
                    "formatted_address": "Toronto, ON, Canada",
                    "is_city": True, "place_type": "locality", "bounds": None},
        "montreal": {"latitude": 45.50, "longitude": -73.60, "location_name": "Montreal",
                     "formatted_address": "Montreal, QC, Canada",
                     "is_city": True, "place_type": "locality", "bounds": None},
    }

    # The stubs mirror the real tools' split: the QUERY text uses the short
    # `city_name`/`city`, while `parent_location` takes `parent_label`. Keeping
    # both visible is what lets the assertions below prove the two never merged.
    async def fake_call_tool(tool, args, writer=None, node_name=None):
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        if "geocode" in name:
            loc = str(args.get("location_name", "")).lower()
            for key, val in _city_geo.items():
                if key in loc:
                    return (dict(val), {"status": "ok"})
            return (None, {"status": "ok"})
        if "pois_by_type" in name:
            city = str(args.get("city_name", ""))
            return ({"targetable_poi_coordinates": [
                {"name": f"{args['poi_type']} in {city}", "lat": args.get("latitude"),
                 "lng": args.get("longitude"),
                 "parent_location": args.get("parent_label") or city},
            ]}, {"status": "ok"})
        if "event" in name:
            city = str(args.get("city", ""))
            return ({"targetable_poi_coordinates": [
                {"name": f"{args['event_query']} venue in {city}", "lat": 45.51, "lng": -73.61,
                 "parent_location": args.get("parent_label") or city},
            ]}, {"status": "ok"})
        return (None, {"status": "ok"})

    async def fake_probe(_n):
        return []

    async def fake_wi(*a, **k):
        return "yes"

    monkeypatch.setattr(geo, "probe_location_candidates", fake_probe)
    monkeypatch.setattr(geo, "wizard_interrupt", fake_wi)
    monkeypatch.setattr(geo, "add_beat", lambda *a, **k: None)
    monkeypatch.setattr(geo, "call_tool", fake_call_tool)


def test_per_angle_routes_each_angle_to_its_own_city(monkeypatch):
    # "shawarma in Toronto, film festivals in Montreal": the category arm must
    # search ONLY Toronto and the event arm ONLY Montreal.
    _patch_multi_city(monkeypatch)
    ws: dict = {}
    _run_det(
        "granular_local",
        "category,event_based",
        ["Toronto", "Montreal"],          # union (seeded flat location)
        "a shawarma shop",
        lambda ev: None,
        {"poi_types_list": ["shawarma"], "event_queries_list": ["film festivals"],
         "angle_specs": [
             {"angle": "category", "locations": ["Toronto"], "poi_types": ["shawarma"]},
             {"angle": "event_based", "locations": ["Montreal"],
              "event_queries": ["film festivals"]},
         ]},
        ws, state=None,
    )
    by_angle = {}
    for p in ws["_det_result"]["targetable_pois"]:
        by_angle.setdefault(p["source_angle"], set()).add(p.get("parent_location"))
    # category searched only Toronto; event searched only Montreal — no cross-bleed.
    # parent_location is the RESOLVED address, not the typed name.
    assert by_angle.get("category") == {"Toronto, ON, Canada"}
    assert by_angle.get("event_based") == {"Montreal, QC, Canada"}


def test_per_angle_spec_without_location_inherits_shared(monkeypatch):
    # A spec that omits `locations` inherits the shared union (here Montreal), so it
    # still runs — the override is optional per field.
    _patch_multi_city(monkeypatch)
    ws: dict = {}
    _run_det(
        "granular_local",
        "category,event_based",
        ["Montreal"],
        "a shawarma shop",
        lambda ev: None,
        {"poi_types_list": ["shawarma"], "event_queries_list": ["film festivals"],
         "angle_specs": [
             {"angle": "category", "poi_types": ["shawarma"]},  # no locations → inherit
             {"angle": "event_based", "locations": ["Montreal"],
              "event_queries": ["film festivals"]},
         ]},
        ws, state=None,
    )
    by_angle = {}
    for p in ws["_det_result"]["targetable_pois"]:
        by_angle.setdefault(p["source_angle"], set()).add(p.get("parent_location"))
    assert by_angle.get("category") == {"Montreal, QC, Canada"}   # inherited shared market
    assert by_angle.get("event_based") == {"Montreal, QC, Canada"}


def test_no_specs_is_byte_identical_legacy(monkeypatch):
    # With no angle_specs every arm searches the full shared set (unchanged path).
    _patch_multi_city(monkeypatch)
    ws: dict = {}
    _run_det(
        "granular_local", "category", ["Toronto", "Montreal"], "a shawarma shop",
        lambda ev: None, {"poi_types_list": ["shawarma"]}, ws, state=None,
    )
    cities = {p.get("parent_location") for p in ws["_det_result"]["targetable_pois"]}
    # category searched BOTH cities (shared set), because nothing narrowed it.
    assert cities == {"Toronto, ON, Canada", "Montreal, QC, Canada"}


# ── entry merge: targeting_angles → durable geo_angle_specs ────────────────────────

def _run_entry_merge(current: dict, extracted: dict) -> dict:
    """Exercise the entry-merge spec resolution in isolation (mirrors entry_node)."""
    from app.graph.nodes import _collapse_deterministic_subtypes, _validate_extracted
    extracted = _validate_extracted(extracted)
    for field, value in extracted.items():
        if value is not None:
            current[field] = value
    _angles = current.get("targeting_angles")
    _fresh_flat_subtypes = isinstance(extracted.get("deterministic_subtypes"), list)
    if isinstance(_angles, list) and _angles:
        _specs = [dict(a) for a in _angles if a and a.get("angle")]
        if _specs:
            current["geo_angle_specs"] = _specs
            if not current.get("deterministic_subtypes"):
                current["deterministic_subtypes"] = list(
                    dict.fromkeys(s["angle"] for s in _specs))
            _spec_locs = [str(loc) for s in _specs for loc in (s.get("locations") or [])
                          if str(loc).strip()]
            if _spec_locs:
                _existing = [str(x) for x in (current.get("location") or [])]
                current["location"] = list(dict.fromkeys(_existing + _spec_locs))
            for _fld in ("poi_types", "anchor_types", "event_queries",
                         "named_places", "competitor_brands"):
                _vals = [str(v) for s in _specs for v in (s.get(_fld) or []) if str(v).strip()]
                if _vals:
                    _cur = [str(x) for x in (current.get(_fld) or [])]
                    current[_fld] = list(dict.fromkeys(_cur + _vals))
    elif _fresh_flat_subtypes and current.get("geo_angle_specs"):
        current.pop("geo_angle_specs", None)
    current.pop("targeting_angles", None)
    _multi = current.get("deterministic_subtypes")
    if isinstance(_multi, list) and _multi:
        _c = _collapse_deterministic_subtypes(_multi)
        if _c is not None:
            current["deterministic_subtype"] = _c
    current.pop("deterministic_subtypes", None)
    return current


def test_targeting_angles_resolve_to_durable_specs_and_seed_fields():
    from app.graph.nodes import AngleSpec
    extracted = {
        "targeting_angles": [
            AngleSpec(angle="category", locations=["Toronto"], poi_types=["shawarma"]).model_dump(exclude_none=True),
            AngleSpec(angle="event_based", locations=["Montreal"], event_queries=["film festivals"]).model_dump(exclude_none=True),
        ],
    }
    out = _run_entry_merge({}, extracted)
    # durable specs stored; transport popped
    assert "targeting_angles" not in out
    assert [s["angle"] for s in out["geo_angle_specs"]] == ["category", "event_based"]
    # angle set collapsed for the slot machine
    assert out["deterministic_subtype"] == "category,event_based"
    # flat fields seeded (union) so WHERE gate + slots don't re-ask
    assert out["location"] == ["Toronto", "Montreal"]
    assert out["poi_types"] == ["shawarma"]
    assert out["event_queries"] == ["film festivals"]


def test_flat_angle_correction_clears_stale_specs():
    # Turn 1: a divergent combo. Turn 2: user narrows flatly ("actually just events")
    # → stale per-angle specs must be dropped, not silently re-applied.
    from app.graph.nodes import AngleSpec
    state = _run_entry_merge({}, {
        "targeting_angles": [
            AngleSpec(angle="category", locations=["Toronto"], poi_types=["shawarma"]).model_dump(exclude_none=True),
            AngleSpec(angle="event_based", locations=["Montreal"], event_queries=["film festivals"]).model_dump(exclude_none=True),
        ],
    })
    assert state.get("geo_angle_specs")
    state = _run_entry_merge(state, {"deterministic_subtypes": ["event_based"]})
    assert "geo_angle_specs" not in state
    assert state["deterministic_subtype"] == "event_based"


# ── Phase 2: per-angle scope, map centroid, breakdown locations ───────────────────

def test_per_angle_scope_drives_the_filters(monkeypatch):
    # A category spec scoped to admin_areas must search with NO locality filter (the
    # province spans cities) but WITH a country filter; a granular_local run keeps the
    # locality filter. Proves _scope_for threads into the filter helpers per angle.
    seen: dict = {}

    async def fake_call_tool(tool, args, writer=None, node_name=None):
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        if "geocode" in name:
            return ({"latitude": 45.5, "longitude": -73.6, "location_name": "Quebec",
                     "place_type": "administrative_area_level_1", "is_city": False,
                     "bounds": {"lat_min": 44, "lat_max": 47, "lng_min": -75, "lng_max": -71},
                     "locality": "Quebec City", "admin_area1_name": "Quebec",
                     "country_name": "Canada", "formatted_address": "Quebec, Canada"},
                    {"status": "ok"})
        if "pois_by_type" in name:
            seen[args["poi_type"]] = {
                "locality_filter": args.get("locality_filter"),
                "country_filter": args.get("country_filter"),
                "state_filter": args.get("state_filter"),
            }
            return ({"targetable_poi_coordinates": [
                {"name": f"{args['poi_type']} spot", "lat": 45.5, "lng": -73.6,
                 "parent_location": args.get("city_name")},
            ]}, {"status": "ok"})
        return (None, {"status": "ok"})

    async def fake_probe(_n):
        return []

    async def fake_wi(*a, **k):
        return "yes"

    monkeypatch.setattr(geo, "probe_location_candidates", fake_probe)
    monkeypatch.setattr(geo, "wizard_interrupt", fake_wi)
    monkeypatch.setattr(geo, "add_beat", lambda *a, **k: None)
    monkeypatch.setattr(geo, "call_tool", fake_call_tool)

    ws: dict = {}
    _run_det(
        "granular_local",          # run-wide default
        "category",
        ["Quebec"],
        "a shawarma shop",
        lambda ev: None,
        {"poi_types_list": ["shawarma"],
         "angle_specs": [{"angle": "category", "locations": ["Quebec"],
                          "scope": "admin_areas", "poi_types": ["shawarma"]}]},
        ws, state=None,
    )
    # admin_areas → locality filter dropped, country filter applied.
    assert seen["shawarma"]["locality_filter"] is None
    assert seen["shawarma"]["country_filter"] == "Canada"


def test_divergent_run_map_centers_between_markets(monkeypatch):
    # A per-angle combo spanning two cities opens on the CENTROID, not the first city.
    _patch_multi_city(monkeypatch)
    ws: dict = {}
    _run_det(
        "granular_local", "category,event_based", ["Toronto", "Montreal"],
        "a shawarma shop", lambda ev: None,
        {"poi_types_list": ["shawarma"], "event_queries_list": ["film festivals"],
         "angle_specs": [
             {"angle": "category", "locations": ["Toronto"], "poi_types": ["shawarma"]},
             {"angle": "event_based", "locations": ["Montreal"], "event_queries": ["film festivals"]},
         ]},
        ws, state=None,
    )
    # centroid of Toronto (43.65) and Montreal (45.50) ≈ 44.575
    assert abs(ws["_det_center"]["latitude"] - 44.575) < 0.01


def test_breakdown_names_each_angle_city():
    det = {
        "targeting_type": "granular_local/category,event_based",
        "targetable_pois": [
            {"name": "Shawarma Palace", "source_angle": "category", "parent_location": "Toronto"},
            {"name": "Festival Grounds", "source_angle": "event_based", "parent_location": "Montreal"},
        ],
    }
    angles, combined = geo.build_angle_breakdown(det, {})
    by_token = {a["token"]: a for a in angles}
    assert by_token["category"]["locations"] == ["Toronto"]
    assert by_token["event_based"]["locations"] == ["Montreal"]


# ── parent_label: resolved address on the POI, short name in the query ────────


def test_parent_label_is_resolved_while_query_keeps_short_city(monkeypatch):
    """The whole point of splitting `parent_label` out of `city_name`: the POI
    label carries the resolved address, but the Google Places query text must keep
    the short city name. Sending "coffee shop in Montreal, QC, Canada" to Places
    would change what gets searched, not just what gets shown."""
    seen: list[dict] = []

    async def fake_probe(_n):
        return []

    async def fake_call_tool(tool, args, writer=None, node_name=None):
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        if "geocode" in name:
            return ({"latitude": 45.50, "longitude": -73.60, "location_name": "montreal",
                     "formatted_address": "Montreal, QC, Canada", "is_city": True,
                     "place_type": "locality", "bounds": None}, {"status": "ok"})
        if "pois_by_type" in name:
            seen.append(dict(args))
            return ({"targetable_poi_coordinates": [
                {"name": "Coin Laundry", "lat": 45.51, "lng": -73.61,
                 "parent_location": args.get("parent_label") or args.get("city_name")},
            ]}, {"status": "ok"})
        return (None, {"status": "ok"})

    async def fake_wi(*a, **k):
        return "yes"

    monkeypatch.setattr(geo, "probe_location_candidates", fake_probe)
    monkeypatch.setattr(geo, "wizard_interrupt", fake_wi)
    monkeypatch.setattr(geo, "add_beat", lambda *a, **k: None)
    monkeypatch.setattr(geo, "call_tool", fake_call_tool)

    ws: dict = {}
    _run_det(
        "granular_local", "category", ["montreal"], "a laundromat",
        lambda ev: None, {"poi_types_list": ["laundromat"]}, ws, state=None,
    )

    assert seen, "search_pois_by_type was never called"
    # Query text keeps the user's short form; the label carries the resolved address.
    assert seen[0]["city_name"] == "montreal"
    assert seen[0]["parent_label"] == "Montreal, QC, Canada"

    pois = ws["_det_result"]["targetable_pois"]
    assert {p["parent_location"] for p in pois} == {"Montreal, QC, Canada"}


def test_parent_label_falls_back_when_no_formatted_address(monkeypatch):
    """The dropped-pin fallback location carries no `formatted_address`
    (geo.py `_apply_pin_fallback`). `_confirm_label` degrades to `location_name`
    rather than emitting an empty label."""
    seen: list[dict] = []

    async def fake_probe(_n):
        return []

    async def fake_call_tool(tool, args, writer=None, node_name=None):
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        if "geocode" in name:
            # No formatted_address — mirrors a bare/partial geocode result.
            return ({"latitude": 45.50, "longitude": -73.60, "location_name": "Montreal",
                     "is_city": True, "place_type": "locality", "bounds": None},
                    {"status": "ok"})
        if "pois_by_type" in name:
            seen.append(dict(args))
            return ({"targetable_poi_coordinates": []}, {"status": "ok"})
        return (None, {"status": "ok"})

    async def fake_wi(*a, **k):
        return "yes"

    monkeypatch.setattr(geo, "probe_location_candidates", fake_probe)
    monkeypatch.setattr(geo, "wizard_interrupt", fake_wi)
    monkeypatch.setattr(geo, "add_beat", lambda *a, **k: None)
    monkeypatch.setattr(geo, "call_tool", fake_call_tool)

    _run_det(
        "granular_local", "category", ["Montreal"], "a laundromat",
        lambda ev: None, {"poi_types_list": ["laundromat"]}, {}, state=None,
    )

    assert seen[0]["parent_label"] == "Montreal"


# ── progress chips: the sidebar summary must not be empty ────────────────────


def test_confirm_interrupt_carries_progress_chips(monkeypatch):
    """`_build_geo_progress` reads PLAIN keys off ws, but the builder path only
    stores `_`-prefixed caches there — so every geo interrupt used to ship
    `progress: []` and the sidebar stayed blank."""
    seen_progress: list = []

    async def fake_probe(_n):
        return []

    async def fake_call_tool(tool, args, writer=None, node_name=None):
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        if "geocode" in name:
            return ({"latitude": 45.50, "longitude": -73.60, "location_name": "Montreal",
                     "formatted_address": "Montreal, QC, Canada", "is_city": True,
                     "place_type": "locality", "bounds": None}, {"status": "ok"})
        if "pois_by_type" in name:
            return ({"targetable_poi_coordinates": [
                {"name": "Coin Laundry", "lat": 45.51, "lng": -73.61},
            ]}, {"status": "ok"})
        return (None, {"status": "ok"})

    async def fake_wi(*a, **k):
        if k.get("step_key") == "geo_location_confirmation":
            seen_progress.append(k.get("progress"))
        return "yes"

    monkeypatch.setattr(geo, "probe_location_candidates", fake_probe)
    monkeypatch.setattr(geo, "wizard_interrupt", fake_wi)
    monkeypatch.setattr(geo, "add_beat", lambda *a, **k: None)
    monkeypatch.setattr(geo, "call_tool", fake_call_tool)

    ws: dict = {}
    _run_det(
        "granular_local", "category", ["Montreal"], "a laundromat",
        lambda ev: None, {"poi_types_list": ["laundromat"]}, ws, state=None,
    )

    assert seen_progress, "the location confirm step never ran"
    labels = {item["label"]: item["value"] for item in seen_progress[0]}
    assert labels["Targeting Scope"] == "Target a specific city, Zip or address"
    assert labels["Locations"] == "Montreal"
    assert labels["Discovery"] == "Search for types of places"
    assert labels["Place Types"] == "laundromat"


def test_progress_chips_track_a_confirm_step_location_edit(monkeypatch):
    """Editing the set at the confirm step must move the Locations chip too."""
    from app.graph.resume_router import ResumeResult

    seen_progress: list = []
    _calls = {"n": 0}

    async def fake_probe(_n):
        return []

    async def fake_call_tool(tool, args, writer=None, node_name=None):
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        if "geocode" in name:
            loc = str(args.get("location_name", "")).lower()
            city = "Laval" if "laval" in loc else "Montreal"
            return ({"latitude": 45.50, "longitude": -73.60, "location_name": city,
                     "formatted_address": f"{city}, QC, Canada", "is_city": True,
                     "place_type": "locality", "bounds": None}, {"status": "ok"})
        if "pois_by_type" in name:
            return ({"targetable_poi_coordinates": [
                {"name": "Coin Laundry", "lat": 45.51, "lng": -73.61},
            ]}, {"status": "ok"})
        return (None, {"status": "ok"})

    async def fake_wi(*a, **k):
        if k.get("step_key") == "geo_location_confirmation":
            seen_progress.append(k.get("progress"))
            _calls["n"] += 1
            if _calls["n"] == 1:
                return ResumeResult(
                    "add laval", edits={"geo_locations": ["Montreal", "laval"]},
                )
        return ResumeResult("yes", edits={})

    monkeypatch.setattr(geo, "probe_location_candidates", fake_probe)
    monkeypatch.setattr(geo, "wizard_interrupt", fake_wi)
    monkeypatch.setattr(geo, "add_beat", lambda *a, **k: None)
    monkeypatch.setattr(geo, "call_tool", fake_call_tool)

    _run_det(
        "granular_local", "category", ["Montreal"], "a laundromat",
        lambda ev: None, {"poi_types_list": ["laundromat"]}, {}, state=None,
    )

    assert len(seen_progress) == 2
    first = {i["label"]: i["value"] for i in seen_progress[0]}
    second = {i["label"]: i["value"] for i in seen_progress[1]}
    assert first["Locations"] == "Montreal"
    assert second["Locations"] == "Montreal, laval"
