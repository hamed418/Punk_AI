"""
tests/test_geo_interrupt_replay.py
──────────────────────────────────
Interrupt-durable act scratch.

LangGraph discards a node's writes when ``interrupt()`` raises, so ``builder_act``
replays from the top on resume. ``_execute_deterministic`` caches every expensive
lookup on ``ws`` and its docstrings call those caches "replay-safe" — but ``ws``
is a local copy of ``bs["geo_ws"]``, so nothing it learned before the pause ever
reached the checkpoint. With N ambiguous location names that is N pauses, each
re-probing every name: O(N²) throttled network calls.

``builder/scratch.py`` parks the live scratch on ``GraphInterrupt`` and pops it
when the same act replays, which is all those caches ever needed.
"""
from __future__ import annotations

import asyncio

import pytest

from app.graph.builder import scratch
from app.graph.builder.executors import geo
from tests._geo_run_helper import run_det as _run_det


# ── scratch.py contract ──────────────────────────────────────────────────────

CFG = {"configurable": {"thread_id": "t-1"}}


def setup_function():
    scratch.clear()


def test_scratch_spans_exactly_one_pause():
    stamp = scratch.act_stamp({"locations": "Springfield"})
    scratch.save_act_scratch(CFG, "geo_discover", {"geo_ws": {"_probes": 1}}, stamp)

    assert scratch.take_act_scratch(CFG, "geo_discover", stamp) == {"geo_ws": {"_probes": 1}}
    # Popped, not peeked: a later act starts from the checkpoint, never from
    # another run's leftovers.
    assert scratch.take_act_scratch(CFG, "geo_discover", stamp) == {}


def test_scratch_is_rejected_when_the_acts_inputs_changed():
    """An abandoned pause must not leak into a fresh run in the same thread.

    Same thread, same operation, different slots — the parked geocodes and
    ``_locations_synced`` belong to the abandoned run, and syncing those back
    would overwrite the new locations.
    """
    scratch.save_act_scratch(
        CFG, "geo_discover", {"geo_ws": {"_locations_synced": ["Springfield"]}},
        scratch.act_stamp({"locations": "Springfield"}),
    )
    assert scratch.take_act_scratch(
        CFG, "geo_discover", scratch.act_stamp({"locations": "Montreal"})
    ) == {}


def test_scratch_is_not_shared_across_threads_or_operations():
    stamp = scratch.act_stamp({"locations": "Montreal"})
    scratch.save_act_scratch(CFG, "geo_discover", {"geo_ws": {"a": 1}}, stamp)
    assert scratch.take_act_scratch(
        {"configurable": {"thread_id": "t-2"}}, "geo_discover", stamp) == {}
    assert scratch.take_act_scratch(CFG, "maid_query", stamp) == {}
    # Untouched by the misses above.
    assert scratch.take_act_scratch(CFG, "geo_discover", stamp) == {"geo_ws": {"a": 1}}


def test_scratch_degrades_to_a_miss_without_a_thread():
    """No thread id means no safe key — two users mid-geo would share one entry."""
    stamp = scratch.act_stamp({})
    scratch.save_act_scratch({}, "geo_discover", {"geo_ws": {"a": 1}}, stamp)
    assert scratch.take_act_scratch({}, "geo_discover", stamp) == {}


# ── The replay itself ────────────────────────────────────────────────────────

class _Pause(Exception):
    """Stands in for GraphInterrupt: aborts the act mid-flight."""


def _patch(monkeypatch, counts: dict, *, pauses: list):
    """Executor stubs that count every expensive call.

    ``pauses`` is consumed one entry per ``wizard_interrupt``: ``True`` raises
    (the act pauses), anything else is returned as the user's answer. Once it is
    exhausted every ask is answered "yes", which confirms a gate and falls back
    to the first candidate at a picker.
    """

    async def fake_probe(name):
        counts["probe"] = counts.get("probe", 0) + 1
        # Ambiguous ACROSS SCOPES (city vs province), which forces the picker
        # regardless of LLM confidence.
        return [
            {"latitude": 45.5, "longitude": -73.6, "label": f"{name} (city)",
             "place_type": "locality", "location_name": name, "bounds": None},
            {"latitude": 46.8, "longitude": -71.2, "label": f"{name} (province)",
             "place_type": "administrative_area_level_1", "location_name": name,
             "bounds": None},
        ]

    async def fake_disambiguate(*a, **k):
        counts["llm"] = counts.get("llm", 0) + 1
        return (0, 0.51)

    async def fake_wi(*a, **k):
        counts["ask"] = counts.get("ask", 0) + 1
        nxt = pauses.pop(0) if pauses else "yes"
        if nxt is True:
            raise _Pause()
        return nxt

    async def fake_call_tool(tool, args, writer=None, node_name=None):
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        if "pois_by_type" in name:
            counts["poi_search"] = counts.get("poi_search", 0) + 1
            return ({"targetable_poi_coordinates": [
                {"name": f"Spot {counts['poi_search']}", "lat": 45.505, "lng": -73.605},
            ]}, {"status": "ok"})
        return (None, {"status": "ok"})

    monkeypatch.setattr(geo, "probe_location_candidates", fake_probe)
    monkeypatch.setattr(geo, "disambiguate_location_candidates", fake_disambiguate)
    monkeypatch.setattr(geo, "wizard_interrupt", fake_wi)
    monkeypatch.setattr(geo, "add_beat", lambda *a, **k: None)
    monkeypatch.setattr(geo, "call_tool", fake_call_tool)
    monkeypatch.setattr(geo.settings, "GEO_REGION_POLYGON_FILTER", False)


def _run(ws: dict):
    _run_det(
        "granular_local", "category", ["Springfield", "Kingston"],
        "a gym chain", lambda ev: None,
        {"poi_types_list": ["gym"]}, ws, state=None,
    )


def test_replay_with_parked_scratch_refetches_nothing(monkeypatch):
    """Two ambiguous names → one pause per name. With the scratch carried across
    the pause, each name is probed and LLM-tiebroken exactly once."""
    counts: dict = {}
    # pass 1 pauses on Springfield; pass 2 answers it and pauses on Kingston;
    # pass 3 answers both and runs to completion.
    _patch(monkeypatch, counts, pauses=[True, "Springfield (city)", True])

    ws: dict = {}                      # the dict builder/scratch.py parks
    for _ in range(2):
        with pytest.raises(_Pause):
            _run(ws)
    _run(ws)

    assert ws["_det_result"]["pois_found"] > 0
    # One probe per name, not one per name PER PAUSE.
    assert counts["probe"] == 2, counts
    assert counts["llm"] == 2, counts
    # Places is only reached on the final pass (2 names × 1 type); a regression
    # that re-searched would push this above 2.
    assert counts["poi_search"] == 2, counts


def test_replay_without_scratch_is_the_bug_this_fixes(monkeypatch):
    """Baseline: a fresh ws per pass — what a discarded write leaves behind —
    re-probes and re-tiebreaks every name on every replay."""
    counts: dict = {}
    _patch(monkeypatch, counts, pauses=[True, "Springfield (city)", True])

    for _ in range(2):
        with pytest.raises(_Pause):
            _run({})
    _run({})

    # 2 names × 3 passes — the quadratic blowup, kept here so the assertion in
    # the test above is measuring something real.
    assert counts["probe"] == 6, counts


def test_arm_cache_keeps_a_finished_search_across_a_later_pause(monkeypatch):
    """A combo pauses in the named-place arm AFTER the category arm has run.

    ``_all_pois_cache`` is only written once EVERY arm completes, so without the
    per-arm cache the finished category search re-hit Places on each replay.
    """
    counts: dict = {}
    _patch(monkeypatch, counts, pauses=[])

    # Unambiguous locations: the pause must come from the named-place arm, not
    # from location disambiguation.
    async def fake_probe(name):
        counts["probe"] = counts.get("probe", 0) + 1
        return [{"latitude": 45.5, "longitude": -73.6, "label": name,
                 "place_type": "locality", "location_name": name, "bounds": None}]

    async def fake_resolve(name, city_name, latitude, longitude, hint="specific", **kw):
        counts["resolve"] = counts.get("resolve", 0) + 1
        return {"kind": "single", "candidates": [], "pois": [
            {"name": name, "lat": 45.5, "lng": -73.6},
        ]}

    async def pausing_resolve(*a, **k):
        raise _Pause()

    monkeypatch.setattr(geo, "probe_location_candidates", fake_probe)

    def _go(ws):
        _run_det(
            "granular_local", "category,named_places", ["Montreal"],
            "a gym chain", lambda ev: None,
            {"poi_types_list": ["gym"], "named_places_list": ["Fight Club"]},
            ws, state=None,
        )

    ws: dict = {}
    monkeypatch.setattr(geo, "resolve_named_target", pausing_resolve)
    with pytest.raises(_Pause):
        _go(ws)
    assert counts["poi_search"] == 1

    monkeypatch.setattr(geo, "resolve_named_target", fake_resolve)
    _go(ws)

    # The category arm was served from ws, not re-searched.
    assert counts["poi_search"] == 1, counts
    names = {p["name"] for p in ws["_det_result"]["targetable_pois"]}
    assert {"Spot 1", "Fight Club"} <= names, names
