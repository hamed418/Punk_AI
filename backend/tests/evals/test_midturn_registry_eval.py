"""
tests/evals/test_midturn_registry_eval.py
─────────────────────────────────────────
Live-model eval for the registry-driven router (Phase 3): units, relative
changes, confusable settings, clarify, unsupported asks, capability listing.
Asserts BUILD STATE or lane, never prose — same contract as
test_midturn_parity_eval.py, which stays the parity gate for the rows both
backends share. Rows only the function-calling backend can express (relative
arithmetic, clarify, explicit replace, scoped refusal) run on "tools" only.

    POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=9 PYTHONIOENCODING=utf-8 \\
        pytest -m eval tests/evals/test_midturn_registry_eval.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage

from app.graph.builder import edits as E
from app.graph.prompts_registry import STEP_PROMPTS
from app.graph.resume_router import _intent_cache, classify_resume_intent, classify_resume_intent_tools
from app.graph.wizard_helpers import _dispatch_edit_intent

pytestmark = pytest.mark.eval

BACKENDS = {"json": classify_resume_intent, "tools": classify_resume_intent_tools}
LOC_STEP = "geo_location_confirmation"
MAID_STEP = "maid_confirm_results"


@pytest.fixture(autouse=True)
def _fresh():
    _intent_cache.clear()
    yield
    _intent_cache.clear()


def _bs() -> dict:
    """Montreal category build, audience extracted — both rings exist."""
    return {
        "filled": {
            "location_scope": "granular_local", "locations": "Montreal", "det_type": "category",
            "poi_types": "cafe", "poi_confirm": "yes", "poi_radius_m": "200", "lookback_days": "30",
        },
        "ops_done": ["geo_discover", "maid_query"],
        "stages_complete": ["geo", "maid"],
        "geo_result": {"targetable_pois": [], "pois_found": 40},
        "geo_ws": {
            "_location_confirmed": True, "_search_ring_km": 12.0,
            "_geocoded_locations": [{
                "location_name": "Montreal", "formatted_address": "Montreal, QC, Canada",
                "ui_mode": "pin_radius", "search_radius_km": 12.0, "default_radius_km": 12.0,
                "latitude": 45.5, "longitude": -73.57, "_source_name": "Montreal",
            }],
        },
    }


def _state(bs: dict) -> dict:
    return {
        "messages": [HumanMessage(content="hi", id="midturn-registry-eval")],
        "user_info": {"location": ["Montreal"], "deterministic_subtype": ["category"],
                      "poi_types": ["cafe"], "poi_radius_m": 200, "lookback_days": 30,
                      "budget": "$500"},
        "campaign_builder_state": bs,
    }


async def _drive(backend: str, step: str, raw: str) -> SimpleNamespace:
    bs = _bs()
    state = _state(bs)
    intent = await BACKENDS[backend](raw, step, state)
    edits: dict = {}
    if intent.lane == "edit":
        with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
            await _dispatch_edit_intent(
                intent=intent, state=state, writer=lambda _e: None,
                pending={"step_key": step, "prefill": None},
                cfg={"field": (STEP_PROMPTS.get(step) or {}).get("field")}, edits=edits,
                edit_base=E.current_edit_base(state, bs),
            )
    # Apply everything the builder would, control ops included (the removals
    # an explicit replace names ride as `_angle_removals`).
    keep = {k: v for k, v in edits.items() if not k.startswith("_") or k == "_angle_removals"}
    E.stash_edits(bs, SimpleNamespace(edits=keep))
    report = E.apply_edits(bs, state)
    return SimpleNamespace(intent=intent, edits=edits, bs=bs, report=report)


def _ring(run) -> float:
    return run.bs["geo_ws"]["_search_ring_km"]


# ── units ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_circle_in_miles(backend):
    run = await _drive(backend, LOC_STEP, "make the circle 5 miles")
    assert _ring(run) == pytest.approx(8.0, abs=0.1)
    assert run.bs["filled"]["poi_radius_m"] == "200"


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_visit_ring_in_feet(backend):
    run = await _drive(backend, MAID_STEP, "make it 300 feet around each spot")
    assert run.bs["filled"]["poi_radius_m"] == "91"
    assert _ring(run) == 12.0


# ── confusable settings ───────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_when_ads_show_is_the_schedule_not_the_audience(backend):
    run = await _drive(backend, MAID_STEP, "only show my ads on weekends")
    fields = {run.intent.target_field} | {e.target_field for e in run.intent.extra_edits}
    assert "adset_schedule" in fields and "audience_filter" not in fields


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_who_visited_on_weekends_is_the_audience(backend):
    run = await _drive(backend, MAID_STEP, "only keep people who visited on weekends")
    assert run.intent.target_field == "audience_filter"


# ── function-calling only ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_relative_change_is_computed_from_the_live_value():
    run = await _drive("tools", LOC_STEP, "double the search circle")
    assert _ring(run) == 24.0


@pytest.mark.asyncio
async def test_ambiguous_radius_asks_instead_of_guessing():
    run = await _drive("tools", MAID_STEP, "make the radius bigger")
    assert run.intent.lane == "clarify"
    assert set(run.intent.clarify_options) >= {"search_radius_km", "poi_radius_m"}
    assert run.report.outcomes == []


@pytest.mark.asyncio
async def test_forget_the_cafes_just_do_events_replaces_the_angle():
    run = await _drive("tools", "geo_pois_confirmation", "forget the cafes, just do events")
    assert run.bs["filled"]["det_type"] == "event_based"


@pytest.mark.asyncio
async def test_one_locations_circle_is_refused_honestly():
    """Only Montreal exists here, so "Laval's circle" can't be applied: the
    router must scope it (location_ring + target) rather than resize everything."""
    run = await _drive("tools", LOC_STEP, "just make Laval's circle 3 km")
    assert run.intent.target_field == "location_ring" and "laval" in (run.intent.edit_target or "").lower()
    assert _ring(run) == 12.0


@pytest.mark.asyncio
async def test_what_can_i_change_never_mutates():
    run = await _drive("tools", MAID_STEP, "what else can I change?")
    assert run.intent.lane in ("handoff", "query")
    assert run.report.outcomes == []


@pytest.mark.asyncio
async def test_unsupported_ask_is_reported_not_forced_into_a_field():
    """Two honest routes, both fine: `unhandled`, or (at the audience screen)
    filter_audience carrying ONLY the clause in `unsupported` — the audience
    recompute then reports it. What must never happen is a real field written."""
    run = await _drive("tools", MAID_STEP, "only target people with a household income over 100k")
    assert run.report.outcomes == []
    if run.intent.lane == "edit":
        patch_ = run.edits.get("_audience_filter_patch") or {}
        assert set(patch_) == {"unsupported"}, run.edits
    else:
        assert run.intent.lane == "unhandled"


# ── typed changes to the built plan + the map's per-location decisions ────────


def _built_bs() -> dict:
    bs = _bs()
    bs["ops_done"] = ["geo_discover", "maid_query", "generate_meta_json"]
    bs["stages_complete"] = ["geo", "maid", "campaign"]
    bs["marketing_plan"] = {"adsets": [{"name": "Seed", "audience_role": "seed"}]}
    bs["geo_ws"]["_manual_pins"] = [{"location_name": "Griffintown", "ui_mode": "pin_radius",
                                     "_source_name": "__manual_pin_1__", "search_radius_km": 5.0}]
    return bs


async def _classify(step: str, raw: str, bs: dict) -> "SimpleNamespace":
    state = _state(bs)
    intent = await classify_resume_intent_tools(raw, step, state)
    fields = [intent.target_field] + [e.target_field for e in intent.extra_edits]
    return SimpleNamespace(intent=intent, fields=fields)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,field", [
    ("make the daily budget $80", "budget"),
    ("end the campaign on December 24", "campaign_end_date"),
    ("only run it on Instagram", "publisher_platforms"),
    ("remove the pin I dropped", "map_pins"),
    ("move the circle to 123 Main Street", "location_center"),
])
async def test_the_right_setting_for_plan_and_map_changes(raw, field):
    run = await _classify("campaign_plan_confirm" if field in ("budget", "campaign_end_date", "publisher_platforms")
                          else LOC_STEP, raw, _built_bs())
    assert field in run.fields, (raw, run.fields, run.intent)


@pytest.mark.asyncio
async def test_a_named_locations_circle_is_scoped_to_it():
    bs = _built_bs()
    bs["geo_ws"]["_geocoded_locations"].append({
        "location_name": "Laval", "ui_mode": "pin_radius", "search_radius_km": 12.0, "_source_name": "Laval"})
    run = await _classify(LOC_STEP, "make just Laval's circle 3 km", bs)
    assert run.intent.target_field == "location_ring"
    assert "laval" in (run.intent.edit_target or "").lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [
    "target everywhere except downtown",
    "leave out the airport area",
    "not Mile End though",
])
async def test_carving_a_place_out_is_an_exclusion_not_a_location_removal(raw):
    run = await _classify(LOC_STEP, raw, _built_bs())
    assert "excluded_areas" in run.fields or (
        "location" in run.fields and run.intent.is_remove
    ), (raw, run.fields, run.intent)
    # Either route lands as an exclusion (the dispatcher redirects an unlisted
    # place), but the direct pick is what we want to see most of the time.
    assert "excluded_areas" in run.fields, (raw, run.fields)


@pytest.mark.asyncio
async def test_removing_a_whole_targeted_city_is_still_a_location_removal():
    bs = _built_bs()
    bs["filled"]["locations"] = "Montreal, Laval"
    run = await _classify(LOC_STEP, "drop Laval", bs)
    assert run.intent.target_field == "location" and run.intent.is_remove


# ── a place / a ring tied to ONE search or group of spots ─────────────────────


def _two_search_bs() -> dict:
    bs = _bs()
    bs["filled"].update({"locations": "Montreal, Toronto", "det_type": "category,event_based",
                         "event_queries": "food festival"})
    bs["geo_result"]["targetable_pois"] = [
        {"name": "Iron Gym", "lat": 45.5, "lng": -73.5, "source_angle": "category", "parent_poi_type": "gym"},
        {"name": "Bean Bar", "lat": 45.52, "lng": -73.52, "source_angle": "category", "parent_poi_type": "cafe"},
    ]
    return bs


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [
    "only search the events in Montreal",
    "the food festivals should just be in Montreal",
])
async def test_a_place_for_one_search_is_scoped_to_it(raw):
    run = await _classify(LOC_STEP, raw, _two_search_bs())
    assert run.intent.target_field in ("location", "geo_locations"), (raw, run.intent)
    assert run.intent.edit_target and any(
        w in run.intent.edit_target.lower() for w in ("event", "festival")
    ), (raw, run.intent.edit_target)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [
    "make the visit ring 100 m just for the gyms",
    "tighter ring around the gyms, 100 metres",
])
async def test_a_visit_ring_for_some_spots_is_scoped_to_them(raw):
    run = await _classify(MAID_STEP, raw, _two_search_bs())
    assert run.intent.target_field == "poi_radius_m", (raw, run.intent)
    assert run.intent.edit_target and "gym" in run.intent.edit_target.lower(), (raw, run.intent.edit_target)


@pytest.mark.asyncio
async def test_an_every_spot_ring_stays_unscoped():
    run = await _classify(MAID_STEP, "make the visit ring 300 feet", _two_search_bs())
    assert run.intent.target_field == "poi_radius_m" and not run.intent.edit_target


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [
    "make the fort collins radius to 5 miles",     # the live thread that resized every circle
    "fort collins 5 miles",
    "change the radius of Denver to 20 km",
])
async def test_a_radius_naming_one_of_two_cities_is_scoped_to_it(raw):
    bs = _bs()
    bs["filled"]["locations"] = "Denver, fort collins"
    bs["geo_ws"]["_geocoded_locations"] = [
        {"location_name": n, "formatted_address": f"{n}, CO, USA", "ui_mode": "pin_radius",
         "search_radius_km": r, "default_radius_km": r, "latitude": 40.0, "longitude": -105.0, "_source_name": n}
        for n, r in (("Denver", 27.5), ("fort collins", 11.8))
    ]
    run = await _classify(LOC_STEP, raw, bs)
    assert run.intent.target_field == "location_ring", (raw, run.intent)
    want = "denver" if "denver" in raw.lower() else "fort"
    assert want in (run.intent.edit_target or "").lower(), (raw, run.intent.edit_target)


@pytest.mark.asyncio
async def test_several_trims_in_one_reply_all_execute():
    """Live thread: understood as three trims, but only the first ran, so the POI
    count never changed while the reply said it had."""
    from collections import Counter

    from app.graph.builder.builder_node import _apply_geo_poi_selection_edit

    pois = [
        {"name": f"{t} {i}", "lat": 39.7 + i * 0.001, "lng": -105.0 + len(t) * 0.001, "source_angle": "category",
         "parent_poi_type": t, "rating": 4.0 + (i % 10) / 20, "user_ratings_total": 10 + i}
        for t, n in (("dog park", 18), ("pet store", 30), ("veterinary clinic", 25)) for i in range(n)
    ]
    bs = _bs()
    bs["geo_result"] = {"targetable_pois": list(pois), "pois_found": len(pois)}
    bs["geo_ws"]["_all_pois_cache"] = list(pois)
    bs["geo_ws"]["_det_center"] = {"latitude": 39.7, "longitude": -105.0}
    state = _state(bs)
    raw = "I want the top 20 dog parks and 15 each of pet stores and vet clinics"
    intent = await classify_resume_intent_tools(raw, "geo_pois_confirmation", state)
    edits: dict = {}
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
        await _dispatch_edit_intent(
            intent=intent, state=state, writer=lambda _e: None, pending={"step_key": "geo_pois_confirmation", "prefill": None},
            cfg={"field": None}, edits=edits, edit_base=E.current_edit_base(state, bs),
        )
    await _apply_geo_poi_selection_edit(bs, state, edits["_poi_selection"], narrate=False)
    kept = Counter(p["parent_poi_type"] for p in bs["geo_result"]["targetable_pois"])
    assert kept == {"dog park": 18, "pet store": 15, "veterinary clinic": 15}, kept


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [
    "keep only the locations has visit",
    "remove the spots nobody visited",
    "drop the locations with no visits",
])
async def test_spots_without_visitors_are_trimmed_not_filtered_as_people(raw):
    """Live thread: read as an audience filter (min_visits 1), so every zero-visitor
    spot stayed on the map."""
    from app.graph.builder.builder_node import _apply_geo_poi_selection_edit

    pois = [
        {"name": f"Spot {i}", "lat": 39.7 + i * 0.01, "lng": -105.0, "source_angle": "category",
         "parent_poi_type": "dog park", "audience_count": 5 if i < 3 else 0}
        for i in range(10)
    ]
    bs = _bs()
    bs["geo_result"] = {"targetable_pois": list(pois), "pois_found": 10, "maid_extraction_id": "x"}
    bs["geo_ws"]["_all_pois_cache"] = list(pois)
    state = _state(bs)
    intent = await classify_resume_intent_tools(raw, MAID_STEP, state)
    edits: dict = {}
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
        await _dispatch_edit_intent(
            intent=intent, state=state, writer=lambda _e: None, pending={"step_key": MAID_STEP, "prefill": None},
            cfg={"field": None}, edits=edits, edit_base=E.current_edit_base(state, bs),
        )
    assert "_poi_selection" in edits and "audience_filter" not in edits, edits
    with patch("app.graph.builder.builder_node._apply_maid_poi_edits", new=AsyncMock()):
        await _apply_geo_poi_selection_edit(bs, state, edits["_poi_selection"], narrate=False)
    assert len(bs["geo_result"]["targetable_pois"]) == 3
