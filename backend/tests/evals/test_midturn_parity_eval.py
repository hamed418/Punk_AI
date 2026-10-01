"""
tests/evals/test_midturn_parity_eval.py
────────────────────────────────────────
Mid-build changes, end to end, on BOTH resume-router backends.

Each row types one phrase at one builder step and follows it through the real
code: classifier (live Gemini) -> `_dispatch_edit_intent` -> `stash_edits` ->
`apply_pending_edits` (or the POI-trim applier) — asserting the resulting BUILD
STATE, never prose. Same corpus, two backends: a row that passes on one and not
the other is a parity bug, which is what gates flipping
`settings.RESUME_ROUTER_TOOLCALLING` on by default.

Hits the live model, so it is gated behind `pytest -m eval` and never runs
per-commit. It touches no database (state is synthetic, nothing here opens a
session); to be certain on a machine whose `.env` points at a real DB, run with
the connection pointed somewhere dead:

    POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=9 PYTHONIOENCODING=utf-8 \\
        pytest -m eval tests/evals/test_midturn_parity_eval.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage

from app.graph.builder import edits as E
from app.graph.prompts_registry import STEP_PROMPTS
from app.graph.resume_router import (
    _intent_cache,
    classify_resume_intent,
    classify_resume_intent_tools,
)
from app.graph.wizard_helpers import _dispatch_edit_intent

pytestmark = pytest.mark.eval

BACKENDS = {"json": classify_resume_intent, "tools": classify_resume_intent_tools}
POI_STEP = "geo_pois_confirmation"
MAID_STEP = "maid_confirm_results"


@pytest.fixture(autouse=True)
def _fresh():
    _intent_cache.clear()
    yield
    _intent_cache.clear()


# ── a realistic mid-build state: LA comic/gaming search finished, at the POI gate ──

_OPS = ["geo_discover", "maid_query", "generate_brief"]


def _pois() -> list[dict]:
    out = []
    for kind, n in (("comic book store", 60), ("game store", 50), ("tabletop gaming center", 30)):
        for i in range(n):
            out.append({
                "name": f"{kind.title()} {i}", "lat": 34.0 + i * 0.001, "lng": -118.2,
                "source_angle": "category", "parent_poi_type": kind, "parent_label": "Los Angeles",
                "types": [kind], "rating": 3.0 + (i % 20) / 10, "user_ratings_total": 10 + i,
            })
    return out


def _bs(**over) -> dict:
    bs = {
        "filled": {
            "location_scope": "granular_local", "locations": "Los Angeles", "det_type": "category",
            "poi_types": "comic book store, game store, tabletop gaming center",
            "poi_confirm": "", "poi_radius_m": "200", "lookback_days": "30",
        },
        "ops_done": list(_OPS),
        "stages_complete": ["geo"],
        "geo_result": {"targetable_pois": _pois(), "pois_found": 140},
        "geo_ws": {"_all_pois_cache": _pois(), "_location_confirmed": True, "_geocoded_locations": ["la"]},
    }
    bs.update(over)
    return bs


def _state(bs: dict, **user_info) -> dict:
    ui = {"location": ["Los Angeles"], "deterministic_subtype": "category",
          "poi_types": ["comic book store", "game store", "tabletop gaming center"], **user_info}
    return {
        "messages": [HumanMessage(content="hi", id="midturn-parity-eval")],
        "user_info": ui, "campaign_builder_state": bs,
    }


class Run(SimpleNamespace):
    """intent, the dispatch `edits`, and (for field edits) the post-apply build."""


async def _drive(backend: str, step: str, raw: str, bs: dict | None = None, **user_info) -> Run:
    bs = bs or _bs()
    state = _state(bs, **user_info)
    intent = await BACKENDS[backend](raw, step, state)
    edits: dict = {}
    pending = {"step_key": step, "prefill": None}
    reframe = None
    if intent.lane == "edit":
        with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
            reframe = await _dispatch_edit_intent(
                intent=intent, state=state, writer=lambda _ev: None, pending=pending,
                cfg={"field": (STEP_PROMPTS.get(step) or {}).get("field")}, edits=edits,
                edit_base=E.current_edit_base(state, bs),
            )
    return Run(intent=intent, edits=edits, bs=bs, state=state, reframe=reframe, rolled_back=[])


def _apply_fields(run: Run) -> Run:
    """The generic commit `builder_plan` runs — no DB, no LLM."""
    fields = {k: v for k, v in run.edits.items() if not k.startswith("_")}
    E.stash_edits(run.bs, SimpleNamespace(edits=fields))
    _ui, run.rolled_back, _note = E.apply_pending_edits(run.bs, run.state)
    return run


def _lane_is_question(run: Run) -> bool:
    return run.intent.lane in ("query", "handoff")


# ── POI curation (tier-1 overlay: no re-search, no rollback) ─────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_target_the_best_20_spots(backend):
    run = await _drive(backend, POI_STEP, "target the best 20 spots")
    assert run.intent.lane == "edit" and run.intent.target_field == "poi_selection", run.intent
    (spec,) = run.edits["_poi_selection"]
    assert spec.get("n") == 20 and spec.get("op", "keep") == "keep"

    from app.graph.builder.builder_node import _apply_geo_poi_selection_edit

    await _apply_geo_poi_selection_edit(run.bs, run.state, run.edits["_poi_selection"], narrate=False)
    assert len(run.bs["geo_result"]["targetable_pois"]) == 20
    assert run.bs["ops_done"] == _OPS  # a curation is not a re-search


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_remove_the_tabletop_gaming_center(backend):
    run = await _drive(backend, POI_STEP, "remove the tabletop gaming center")
    assert run.intent.lane == "edit" and run.intent.target_field == "poi_selection", run.intent

    from app.graph.builder.builder_node import _apply_geo_poi_selection_edit

    await _apply_geo_poi_selection_edit(run.bs, run.state, run.edits["_poi_selection"], narrate=False)
    kept = run.bs["geo_result"]["targetable_pois"]
    assert kept and len(kept) < 140
    assert not any(p["parent_poi_type"] == "tabletop gaming center" for p in kept)
    assert run.bs["ops_done"] == _OPS


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_curation_can_be_widened_back_out(backend):
    from app.graph.builder.builder_node import _apply_geo_poi_selection_edit

    bs = _bs()
    first = await _drive(backend, POI_STEP, "just the top 10", bs)
    await _apply_geo_poi_selection_edit(bs, first.state, first.edits["_poi_selection"], narrate=False)
    assert len(bs["geo_result"]["targetable_pois"]) == 10
    _intent_cache.clear()
    # "make it 30" alone is genuinely ambiguous here (lookback_days is 30) — say what is meant.
    second = await _drive(backend, POI_STEP, "actually show me 30 spots", bs)
    assert second.intent.target_field == "poi_selection", second.intent
    await _apply_geo_poi_selection_edit(bs, second.state, second.edits["_poi_selection"], narrate=False)
    assert len(bs["geo_result"]["targetable_pois"]) == 30


# ── location / list fields (tier-2: invalidate downstream, keep what is still true) ──

@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_change_my_location_to_toronto(backend):
    run = _apply_fields(await _drive(backend, POI_STEP, "change my location to Toronto"))
    assert run.intent.lane == "edit" and run.intent.target_field in ("location", "geo_locations"), run.intent
    assert "toronto" in run.bs["filled"]["locations"].lower()
    assert "los angeles" not in run.bs["filled"]["locations"].lower()  # a replace
    assert run.rolled_back[:1] == ["geo"]  # geocode-level: everything downstream rebuilds
    assert "geo_discover" not in run.bs["ops_done"]


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_also_add_laval_keeps_los_angeles(backend):
    run = _apply_fields(await _drive(backend, POI_STEP, "also add Laval"))
    assert run.intent.lane == "edit" and run.intent.is_append, run.intent
    filled = run.bs["filled"]["locations"].lower()
    assert "los angeles" in filled and "laval" in filled


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_also_target_gyms_researches_but_keeps_the_location(backend):
    run = _apply_fields(await _drive(backend, POI_STEP, "also target gyms"))
    assert run.intent.lane == "edit", run.intent
    assert "gym" in run.bs["filled"]["poi_types"].lower()
    assert "geo_discover" not in run.bs["ops_done"]          # the search re-runs
    assert run.bs["geo_ws"].get("_location_confirmed") is True  # ...without re-asking the location


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_add_starbucks_turns_the_brand_angle_on(backend):
    run = _apply_fields(await _drive(backend, POI_STEP, "also add Starbucks"))
    assert run.intent.lane == "edit", run.intent
    assert "competitor_brand" in run.bs["filled"]["det_type"]
    assert "starbucks" in run.bs["filled"].get("brand_names", "").lower()
    assert run.bs["geo_ws"].get("_location_confirmed") is True


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_change_the_location_type_to_gyms_means_the_place_category(backend):
    run = await _drive(backend, "geo_collect_poi_types", "change the location type to gyms")
    assert run.intent.lane == "edit", run.intent
    assert run.intent.target_field in ("poi_types", "geo_poi_types"), run.intent


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_budget_edit_only_rebuilds_the_campaign_stage(backend):
    bs = _bs()
    bs["filled"]["budget"] = "20"
    bs["ops_done"] = _OPS
    run = _apply_fields(await _drive(backend, POI_STEP, "change my budget to $50/day", bs))
    assert run.intent.lane == "edit" and run.intent.target_field == "budget", run.intent
    assert "geo" not in run.rolled_back and "maid" not in run.rolled_back
    assert "geo_discover" in run.bs["ops_done"] and "maid_query" in run.bs["ops_done"]


# ── audience (tier-1 overlay on the persisted extraction) ────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_only_weekends(backend):
    run = await _drive(backend, MAID_STEP, "now only weekends")
    assert run.intent.lane == "edit" and run.intent.target_field == "audience_filter", run.intent
    assert run.edits["_audience_filter_patch"].get("days_of_week") == [5, 6]


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_inexpressible_audience_clause_is_reported_not_dropped(backend):
    run = await _drive(backend, MAID_STEP, "men in their 30s")
    assert run.intent.lane == "edit" and run.intent.target_field == "audience_filter", run.intent
    assert "30" in str(run.edits["_audience_filter_patch"].get("unsupported", "")), run.edits


# ── questions and hypotheticals: NEVER a mutation ────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("raw", [
    "what's a POI?",
    "if I add Toronto does it cost more?",
    "which of these spots is best?",
    "what have we built so far?",
])
async def test_question_never_mutates_the_build(backend, raw):
    before_filled = dict(_bs()["filled"])
    run = await _drive(backend, POI_STEP, raw)
    assert _lane_is_question(run), f"{raw!r} -> {run.intent}"
    assert run.edits == {} and run.bs["filled"] == before_filled and run.bs["ops_done"] == _OPS


# ── refusals: named, and nothing reaches the apply gate ──────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_changing_the_ad_account_is_refused_not_applied(backend):
    run = await _drive(backend, POI_STEP, "use ad account act_123456 instead")
    assert run.edits == {}, run.edits
    assert run.bs["ops_done"] == _OPS


# ── routing: the SAME kind of thing must land in the same field on both backends ──
# A docstring saying "a specific venue is named_places" once made the tools backend
# file the city "Laval" there, so the boundaries are pinned row by row.

@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("raw,fields", [
    ("also add Toronto", {"location", "geo_locations"}),                  # a city  -> WHERE
    ("add Laval and Longueuil too", {"location", "geo_locations"}),
    ("also target coffee shops", {"poi_types", "geo_poi_types"}),         # a kind  -> poi_types
    ("also add Starbucks", {"competitor_brands", "geo_brand_names"}),     # a chain -> brands
    ("add Central Park to the list", {"named_places", "geo_named_places"}),  # a venue -> named
])
async def test_the_kind_of_thing_decides_the_field(backend, raw, fields):
    run = await _drive(backend, POI_STEP, raw)
    assert run.intent.lane == "edit", run.intent
    assert run.intent.target_field in fields, f"{raw!r} -> {run.intent.target_field}"


# ── paraphrases of the original failure: same intent, different words ────────

@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("raw,n", [
    ("give me the top 20", 20),
    ("keep only the 20 best spots", 20),
    ("i only want 20 places", 20),
    ("narrow it down to 15", 15),
])
async def test_curation_wording_variants_all_curate(backend, raw, n):
    run = await _drive(backend, POI_STEP, raw)
    assert run.intent.lane == "edit" and run.intent.target_field == "poi_selection", f"{raw!r} -> {run.intent}"
    assert run.edits["_poi_selection"][0].get("n") == n, run.edits


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("raw,gone", [
    ("get rid of the game stores", "game store"),
    ("drop the comic book stores", "comic book store"),
    ("take out the tabletop gaming center", "tabletop gaming center"),
])
async def test_removing_a_category_on_the_map_curates_and_never_researches(backend, raw, gone):
    from app.graph.builder.builder_node import _apply_geo_poi_selection_edit

    run = await _drive(backend, POI_STEP, raw)
    assert run.intent.target_field == "poi_selection", f"{raw!r} -> {run.intent}"
    await _apply_geo_poi_selection_edit(run.bs, run.state, run.edits["_poi_selection"], narrate=False)
    kept = run.bs["geo_result"]["targetable_pois"]
    assert kept and not any(p["parent_poi_type"] == gone for p in kept)
    assert run.bs["ops_done"] == _OPS  # free and reversible — no re-search, no Unacast re-buy


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", BACKENDS)
async def test_stop_searching_for_a_category_is_a_search_edit(backend):
    """The other side of the boundary: talking about the SEARCH itself re-runs it."""
    run = await _drive(backend, POI_STEP, "stop searching for game stores")
    assert run.intent.lane == "edit" and run.intent.target_field in ("poi_types", "geo_poi_types"), run.intent
    assert run.intent.is_remove
