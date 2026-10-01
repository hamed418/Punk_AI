"""
Plan preservation: a geo/audience edit after the plan exists must keep what the
user did in the editor, and must never keep stale build-owned data.
"""

from __future__ import annotations

import copy

import pytest

from app.graph.meta_spec.merge import merge_or_fallback, merge_plan


def _ad(n: int = 1, title: str = "Fresh coffee") -> dict:
    return {"name": f"Ad {n}", "status": "PAUSED",
            "creative": {"title": title, "body": "Body", "call_to_action": "LEARN_MORE",
                         "link": "https://x.co", "media_id": None}}


def _adset(name: str, role: str, zips=("H2X",), budget: int = 1000, ads=None) -> dict:
    return {
        "name": name, "audience_role": role, "daily_budget": budget, "lifetime_budget": None,
        "optimization_goal": "LINK_CLICKS", "billing_event": "IMPRESSIONS",
        "start_time": "2026-10-01T00:00:00+00:00", "end_time": None,
        "attached_audience_ids": [], "excluded_audience_ids": [],
        "targeting": {"geo_locations": {"zips": list(zips)}, "age_min": 18,
                      "publisher_platforms": ["facebook", "instagram"]},
        "ads": ads or [_ad()],
    }


def _spec(*adsets, name="Camp", budget=5000) -> dict:
    return {"name": name, "objective": "OUTCOME_TRAFFIC", "daily_budget": budget,
            "adsets": list(adsets) or [_adset("Seed", "seed"), _adset("Broad", "broad")]}


def test_untouched_plan_equals_the_regenerated_one():
    base = _spec()
    theirs = _spec(_adset("Seed", "seed", zips=("H3A",)), _adset("Broad", "broad", zips=("H3A",)))
    result = merge_plan(base, copy.deepcopy(base), theirs)
    assert result.spec == theirs and result.kept == [] and result.conflicts == []


def test_edited_budget_survives_and_new_geo_comes_from_the_rebuild():
    base = _spec()
    ours = copy.deepcopy(base)
    ours["adsets"][0]["daily_budget"] = 4000
    ours["daily_budget"] = 9000
    theirs = _spec(_adset("Seed", "seed", zips=("H3A", "H3B")), _adset("Broad", "broad", zips=("H3A",)))

    result = merge_plan(base, ours, theirs)

    seed = result.spec["adsets"][0]
    assert seed["daily_budget"] == 4000 and result.spec["daily_budget"] == 9000
    assert seed["targeting"]["geo_locations"] == {"zips": ["H3A", "H3B"]}      # never the stale zips
    assert result.spec["adsets"][1]["daily_budget"] == 1000                     # untouched → regenerated


def test_edited_ad_copy_survives_but_untouched_ads_are_regenerated():
    base = _spec()
    ours = copy.deepcopy(base)
    ours["adsets"][0]["ads"][0]["creative"]["title"] = "My own headline"
    theirs = _spec(_adset("Seed", "seed", ads=[_ad(title="New brief headline")]),
                   _adset("Broad", "broad", ads=[_ad(title="New brief headline")]))

    result = merge_plan(base, ours, theirs)

    assert result.spec["adsets"][0]["ads"][0]["creative"]["title"] == "My own headline"
    assert result.spec["adsets"][1]["ads"][0]["creative"]["title"] == "New brief headline"


def test_user_added_ad_set_is_carried_over_on_the_new_geo():
    base = _spec()
    ours = copy.deepcopy(base)
    ours["adsets"].append(_adset("Retargeting", "broad", zips=("OLD",), budget=700))
    theirs = _spec(_adset("Seed", "seed", zips=("NEW",)), _adset("Broad", "broad", zips=("NEW",)))

    result = merge_plan(base, ours, theirs)

    names = [a["name"] for a in result.spec["adsets"]]
    assert names == ["Seed", "Broad", "Retargeting"]
    added = result.spec["adsets"][2]
    assert added["daily_budget"] == 700 and added["targeting"]["geo_locations"] == {"zips": ["NEW"]}


def test_user_deleted_ad_set_stays_deleted():
    base = _spec()
    ours = copy.deepcopy(base)
    del ours["adsets"][1]
    theirs = _spec(_adset("Seed", "seed"), _adset("Broad", "broad"))

    result = merge_plan(base, ours, theirs)

    assert [a["name"] for a in result.spec["adsets"]] == ["Seed"]


def test_renamed_ad_set_is_matched_by_its_role():
    base = _spec()
    ours = copy.deepcopy(base)
    ours["adsets"][0]["name"] = "My warm audience"
    ours["adsets"][0]["daily_budget"] = 2500
    theirs = _spec(_adset("Seed", "seed", zips=("H3A",)), _adset("Broad", "broad"))

    result = merge_plan(base, ours, theirs)

    seed = result.spec["adsets"][0]
    assert seed["name"] == "My warm audience" and seed["daily_budget"] == 2500
    assert seed["targeting"]["geo_locations"] == {"zips": ["H3A"]}


def test_user_edited_ad_set_whose_audience_disappeared_is_a_conflict_not_a_silent_drop():
    base = _spec()
    ours = copy.deepcopy(base)
    ours["adsets"][0]["daily_budget"] = 4000
    theirs = _spec(_adset("Broad", "broad"))                 # the seed audience is gone

    result = merge_plan(base, ours, theirs)

    assert [a["name"] for a in result.spec["adsets"]] == ["Broad"]
    assert len(result.conflicts) == 1 and "'Seed'" in result.conflicts[0]


def test_locked_targeting_is_always_the_rebuilds_but_placements_are_the_users():
    base = _spec()
    ours = copy.deepcopy(base)
    ours["adsets"][0]["targeting"]["geo_locations"] = {"zips": ["STALE"]}
    ours["adsets"][0]["targeting"]["publisher_platforms"] = ["instagram"]
    theirs = _spec(_adset("Seed", "seed", zips=("FRESH",)), _adset("Broad", "broad"))

    seed = merge_plan(base, ours, theirs).spec["adsets"][0]

    assert seed["targeting"]["geo_locations"] == {"zips": ["FRESH"]}
    assert seed["targeting"]["publisher_platforms"] == ["instagram"]


def test_no_base_or_no_prior_plan_just_uses_the_new_one():
    theirs = _spec()
    assert merge_plan(None, _spec(), theirs).spec == theirs
    assert merge_plan(_spec(), None, theirs).spec == theirs


def test_everything_deleted_keeps_the_rebuilt_plan_and_says_so():
    base = _spec()
    ours = copy.deepcopy(base)
    ours["adsets"] = []
    result = merge_plan(base, ours, _spec())
    assert len(result.spec["adsets"]) == 2 and result.conflicts


def test_a_merged_spec_that_fails_validation_falls_back_honestly():
    base = _spec()
    ours = copy.deepcopy(base)
    ours["daily_budget"] = 1

    def _validate(_spec):
        raise ValueError("budget below minimum")

    theirs = _spec(name="Rebuilt")
    result = merge_or_fallback(base, ours, theirs, _validate)
    assert result.spec == theirs and "couldn't be carried over" in result.conflicts[0]


@pytest.mark.parametrize("bad", [{"adsets": "nope"}, {"adsets": [None]}])
def test_shape_surprises_never_raise(bad):
    theirs = _spec()
    result = merge_or_fallback(_spec(), bad, theirs)
    assert result.spec == theirs or result.spec["adsets"]


# ── wiring: invalidate_from keeps the user's plan aside ───────────────────────


def test_geo_rollback_keeps_the_users_plan_when_a_base_exists():
    from app.graph.builder.edits import invalidate_from

    plan = _spec()
    bs = {
        "ops_done": ["geo_discover", "maid_query", "generate_meta_json"],
        "stages_complete": ["geo", "maid", "campaign"], "filled": {},
        "marketing_plan": plan, "plan_base": _spec(), "brief": {"h": 1},
    }
    invalidate_from(bs, bs["filled"], "geocode")

    assert bs["marketing_plan_prev"] == plan
    assert "marketing_plan" not in bs and "brief" not in bs          # still rebuilt
    assert "generate_meta_json" not in bs["ops_done"]
    assert bs["plan_base"] == _spec()                                # base survives for the diff


def test_an_older_plan_with_no_base_is_dropped_as_before():
    from app.graph.builder.edits import invalidate_from

    bs = {"ops_done": ["generate_meta_json"], "stages_complete": ["campaign"], "filled": {},
          "marketing_plan": _spec()}
    invalidate_from(bs, bs["filled"], "campaign")
    assert "marketing_plan_prev" not in bs and "marketing_plan" not in bs


def test_the_rebuilt_plan_beat_says_the_edits_carry_over():
    import inspect

    from app.graph.builder import builder_node

    src = inspect.getsource(builder_node.builder_plan)
    assert "keeps_plan_edits" in src and "_keeps_plan" in src


def test_generate_step_merges_and_reports_through_the_ledger():
    from langchain_core.messages import HumanMessage

    from app.graph.builder.builder_node import _merge_regenerated_plan
    from app.graph.narrator.beats import drain_changes

    state = {"messages": [HumanMessage(content="x", id="pm-gen")]}
    base = _spec()
    ours = copy.deepcopy(base)
    ours["adsets"][0]["daily_budget"] = 4000
    bs = {"plan_base": base, "marketing_plan_prev": ours}
    theirs = _spec(_adset("Seed", "seed", zips=("NEW",)), _adset("Broad", "broad", zips=("NEW",)))

    with_validation_stub = _merge_regenerated_plan
    import app.graph.builder.builder_node as bn
    original = bn.CampaignSpec
    try:
        bn.CampaignSpec = type("V", (), {"model_validate": staticmethod(lambda d: d)})
        final = with_validation_stub(bs, state, theirs)
    finally:
        bn.CampaignSpec = original

    assert final["adsets"][0]["daily_budget"] == 4000
    assert final["adsets"][0]["targeting"]["geo_locations"] == {"zips": ["NEW"]}
    assert "marketing_plan_prev" not in bs
    assert any("kept your plan edits" in a for a in drain_changes(state)["applied"])


def test_no_previous_plan_returns_the_generated_one_untouched():
    from app.graph.builder.builder_node import _merge_regenerated_plan

    theirs = _spec()
    assert _merge_regenerated_plan({"plan_base": _spec()}, {}, theirs) is theirs
