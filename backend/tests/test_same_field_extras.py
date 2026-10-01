"""
One reply carrying several instructions for the SAME field must keep them all:
"top 20 dog parks and 15 each of pet stores and vet clinics" is three POI
trims; "events only in Montreal, gyms only in Toronto" is two scoped location
edits. The dispatcher used to skip every extra whose field matched the primary's,
so only the first landed while the reply was answered as if all had.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage

from app.graph.builder.builder_node import _apply_geo_poi_selection_edit
from app.graph.resume_router import ExtraEdit, ResumeIntent
from app.graph.wizard_helpers import _dispatch_edit_intent


async def _dispatch(intent, msg_id):
    state = {"messages": [HumanMessage(content="x", id=msg_id)], "user_info": {},
             "campaign_builder_state": {"filled": {"det_type": "category,event_based"}}}
    edits: dict = {}
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
        await _dispatch_edit_intent(
            intent=intent, state=state, writer=lambda _e: None, pending={"step_key": "s", "prefill": None},
            cfg={"field": None}, edits=edits, edit_base={},
        )
    return edits


@pytest.mark.asyncio
async def test_every_poi_trim_in_one_reply_is_kept():
    intent = ResumeIntent(
        lane="edit", target_field="poi_selection", new_value={"op": "keep", "n": 20, "match": "dog park"},
        confidence=0.9, extra_edits=[
            ExtraEdit(target_field="poi_selection", new_value={"op": "keep", "n": 15, "match": "pet store"}),
            ExtraEdit(target_field="poi_selection", new_value={"op": "keep", "n": 15, "match": "vet clinic"}),
        ])
    edits = await _dispatch(intent, "sf-poi")
    assert sorted(s["match"] for s in edits["_poi_selection"]) == ["dog park", "pet store", "vet clinic"]


@pytest.mark.asyncio
async def test_scoped_location_edits_for_two_searches_are_both_kept():
    intent = ResumeIntent(
        lane="edit", target_field="location", new_value=["Montreal"], edit_target="events",
        is_replace=True, confidence=0.9, extra_edits=[
            ExtraEdit(target_field="location", new_value=["Toronto"], edit_target="gyms", is_replace=True)])
    edits = await _dispatch(intent, "sf-loc")
    assert sorted((o["target"], o["names"][0]) for o in edits["_angle_locations"]) == [
        ("events", "Montreal"), ("gyms", "Toronto")]


@pytest.mark.asyncio
async def test_an_exact_repeat_of_the_primary_is_still_skipped():
    spec = {"op": "keep", "n": 10}
    intent = ResumeIntent(lane="edit", target_field="poi_selection", new_value=spec, confidence=0.9,
                          extra_edits=[ExtraEdit(target_field="poi_selection", new_value=dict(spec))])
    edits = await _dispatch(intent, "sf-dup")
    assert edits["_poi_selection"] == [spec]


def test_asking_for_more_than_exist_is_said_in_the_users_terms():
    pois = [{"name": f"P{i}", "lat": 39.7 + i * 0.001, "lng": -105.0, "source_angle": "category",
             "parent_poi_type": "dog park"} for i in range(18)]
    bs = {"geo_result": {"targetable_pois": list(pois), "pois_found": 18}, "geo_ws": {"_all_pois_cache": list(pois)}}
    note = asyncio.run(_apply_geo_poi_selection_edit(
        bs, {}, [{"op": "keep", "n": 20, "match": "dog park"}], narrate=False))
    assert "only 18" in note and "fewer than the 20" in note
    assert len(bs["geo_result"]["targetable_pois"]) == 18


@pytest.mark.asyncio
async def test_an_understood_change_that_cannot_run_is_reported_not_dropped():
    from app.graph.narrator.beats import drain_changes

    state = {"messages": [HumanMessage(content="x", id="sf-drop")], "user_info": {}, "campaign_builder_state": {}}
    intent = ResumeIntent(lane="edit", target_field="budget", new_value="$50", confidence=0.9,
                          extra_edits=[ExtraEdit(target_field="budget", new_value="$80")])
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
        await _dispatch_edit_intent(
            intent=intent, state=state, writer=lambda _e: None, pending={"step_key": "s", "prefill": None},
            cfg={"field": None}, edits={}, edit_base={},
        )
    assert any("$80" in u for u in drain_changes(state)["unsupported"])


def test_an_abbreviated_group_name_still_matches():
    from app.graph.builder.executors.poi_selection import resolve_drop_predicate

    pois = [{"name": "Paws Vet", "parent_poi_type": "veterinary clinic"}, {"name": "Bean Bar", "parent_poi_type": "cafe"}]
    assert [p["name"] for p in resolve_drop_predicate(pois, "vet clinics")] == ["Paws Vet"]
    assert resolve_drop_predicate(pois, "zoo") == []                    # nothing invented


def _curation_bs():
    pois = []
    for label, city, n in (("dog park", "Denver", 15), ("dog park", "Fort Collins", 3),
                           ("pet store", "Denver", 15), ("pet store", "Fort Collins", 8),
                           ("veterinary clinic", "Denver", 0), ("veterinary clinic", "Fort Collins", 7)):
        pois += [{"name": f"{label} {city} {i}", "lat": 39.7 + i * 0.001 + (0.8 if city == "Fort Collins" else 0),
                  "lng": -105.0, "source_angle": "category", "parent_poi_type": label,
                  "locality_tokens": [city], "formatted_address": f"{i} St, {city}, CO"} for i in range(n)]
    return {"geo_result": {"targetable_pois": list(pois), "pois_found": len(pois)},
            "geo_ws": {"_all_pois_cache": list(pois)}}


def test_a_later_trim_reports_its_own_result_per_category_and_not_old_notes(monkeypatch):
    """Live thread: after 'top 20 dog parks…' a later 'remove the Denver spots' was
    narrated as '18 dog parks' — the old note replayed and the TOTAL read as one
    category. Now: only this turn's notes, and the count is broken down."""
    from app.graph.builder import builder_node as bn

    beats: list = []
    monkeypatch.setattr(bn, "add_beat", lambda state, kind, facts, fallback="": beats.append((facts, fallback)))
    bs = _curation_bs()
    asyncio.run(_apply_geo_poi_selection_edit(
        bs, {}, [{"op": "keep", "n": 20, "match": "dog park"}, {"op": "keep", "n": 15, "match": "pet store"}],
        narrate=False))
    beats.clear()

    asyncio.run(_apply_geo_poi_selection_edit(bs, {}, [{"op": "drop", "match": "Denver"}], narrate=True))

    from collections import Counter

    facts, fallback = beats[-1]
    shown = Counter(p["parent_poi_type"] for p in bs["geo_result"]["targetable_pois"])
    assert facts["breakdown"] == dict(shown) and sum(shown.values()) == facts["poi_count"]
    assert facts["breakdown"]["dog park"] == 3               # the total is not one category's count
    assert not facts["deviations"]                          # the old "only N match" note is not replayed
    assert "3 dog park" in fallback


def test_grounding_gives_the_narrator_the_per_category_split():
    from app.graph.narrator.grounding import _build_geo

    geo = {"pois_found": 4, "targetable_pois": [
        {"parent_poi_type": "dog park"}, {"parent_poi_type": "pet store"},
        {"parent_poi_type": "pet store"}, {"parent_poi_type": "pet store"}]}
    out = _build_geo(geo, {})
    assert out["poi_count"] == 4 and out["poi_counts_by_category"] == {"dog park": 1, "pet store": 3}
