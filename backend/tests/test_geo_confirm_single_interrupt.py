"""
Location confirm under the one-interrupt-per-task contract, through the real geo
executor: a reply that isn't a confirmation must never confirm the locations,
must park its edits, and — for the original radius bug — the typed circle must
be what the re-run's Places search actually uses.
"""
from __future__ import annotations

import asyncio

import pytest

from app.graph.builder.edits import apply_edits
from app.graph.builder.executors import geo
from app.graph.resume_router import ResumeResult
from tests.test_geo_pin_radius_confirm import _AUSTIN_BOUNDS, _patch


def _drive_once(ws):
    async def _go():
        await geo._execute_deterministic(
            "granular_local", "category", ["Austin"], "a gym brand",
            lambda ev: None, {"poi_types_list": ["gym"]}, ws, state=None,
        )
    try:
        asyncio.run(_go())
        return False
    except geo._GeoStepPaused:
        return True


def _setup(monkeypatch, replies):
    return _patch(monkeypatch, replies, {"Austin": "locality"}, {"Austin": _AUSTIN_BOUNDS})


def test_a_non_answer_at_the_location_confirm_does_not_confirm_it(monkeypatch):
    _setup(monkeypatch, [ResumeResult("bump my budget to 500", edits={"budget": "500"}, answered=False)])
    ws: dict = {}

    assert _drive_once(ws) is True                       # ended its task (paused)
    assert not ws.get("_location_confirmed")             # NOT confirmed by a budget edit
    assert ws["_pending_edits"] == {"budget": "500"}     # parked for builder_plan


def test_an_answer_still_confirms(monkeypatch):
    _setup(monkeypatch, ["yes"])
    ws: dict = {}
    _drive_once(ws)
    assert ws["_location_confirmed"] is True


def test_typed_circle_is_applied_then_the_research_uses_it(monkeypatch):
    searches = _setup(monkeypatch, [
        ResumeResult("make the circle 5 km", edits={"search_radius_km": "5 km"}, answered=False),
        "yes",
    ])
    ws: dict = {}

    assert _drive_once(ws) is True                       # the typed radius paused the confirm
    assert not ws.get("_location_confirmed")

    # What builder_plan does between the two tasks:
    bs = {"geo_ws": ws, "ops_done": ["geo_discover"], "filled": {
        "location_scope": "granular_local", "locations": "Austin", "det_type": "category"}}
    report = apply_edits(bs)
    assert [o.status for o in report.outcomes] == ["applied"]
    assert "geo_discover" not in bs["ops_done"]          # the Places search will re-run
    ws = bs["geo_ws"]
    assert ws["_search_ring_km"] == 5.0

    while _drive_once(ws):                               # remaining tasks: confirm, then search
        pass

    loc = ws["_det_result"]["locations"][0]
    assert loc["search_radius_km"] == 5.0
    assert searches[-1]["search_radius_km"] == 5.0       # the typed ring, not the bounds-derived default
