"""
Reusing a previous campaign's setup on a freshly built audience.

The feature's whole value rests on one asymmetry: the *setup* comes from the old
campaign, the *audience* comes from this run. Most of what follows guards that
line — a template that carried targeting or an audience id would defeat the point
of running Punk at all.

Pure: no network, no ad account. Graph payloads are inlined in the shape
``meta_ads.fetch_campaign_tree`` returns.
"""

import json

import pytest

from app.graph.meta_spec.builder import apply_campaign_template, build_campaign_spec
from app.graph.meta_spec.importer import (
    TemplateImportError,
    campaign_template,
    select_tree_subset,
)
from app.graph.meta_spec.models import CampaignSpec

# ── fixtures ─────────────────────────────────────────────────────────────────

SEED = {"geo_locations": {"zips": [{"key": "US:94104"}]}, "custom_audiences": [{"id": "new_seed"}]}
BROAD = {"geo_locations": {"zips": [{"key": "US:94104"}]}}

USER_INFO = {
    "campaign_objective": "TRAFFIC",
    "business_name": "Bean There",
    "business_description": "Specialty coffee roaster",
    "website_url": "https://beanthere.example",
    "budget": "$50/day",
    "budget_type": "daily",
    "campaign_start_date": "August 1, 2026",
}
BRIEF = {
    "campaign_name": "Bean There — August",
    "headline_suggestions": ["Fresh roast, daily"],
    "body_copy_suggestions": ["Come taste the difference."],
}


def _tree(**overrides) -> dict:
    """A previous campaign as Meta returns it: Sales, conversions, cost cap, one
    image ad — plus an old audience and an old geo that must NOT survive."""
    tree = {
        "campaign": {
            "id": "c_old",
            "name": "Summer Sale",
            "objective": "OUTCOME_SALES",
            "bid_strategy": "COST_CAP",
        },
        "adsets": [{
            "id": "as_old",
            "name": "Old ad set",
            "destination_type": "WEBSITE",
            "optimization_goal": "OFFSITE_CONVERSIONS",
            "billing_event": "IMPRESSIONS",
            "bid_strategy": "COST_CAP",
            "bid_amount": 1200,
            # Everything below is the old campaign's audience — the thing a new
            # run exists to replace.
            "targeting": {
                "geo_locations": {"zips": [{"key": "US:10001"}]},
                "custom_audiences": [{"id": "stale_audience"}],
            },
            "daily_budget": 999_00,
            "promoted_object": {"pixel_id": "old_pixel", "custom_event_type": "ADD_TO_CART"},
            "ads": [{
                "id": "ad_old",
                "creative": {
                    "object_story_spec": {
                        "link_data": {
                            "name": "Old headline",
                            "message": "Old body copy",
                            "image_hash": "HASH_OLD",
                            "call_to_action": {"type": "SHOP_NOW"},
                        }
                    },
                    "thumbnail_url": "https://img.example/old.jpg",
                },
            }],
        }],
    }
    tree.update(overrides)
    return tree


def _built(**kwargs) -> dict:
    """The tree build_campaign_spec produces from THIS run's audience."""
    params = dict(
        user_info=dict(USER_INFO),
        geo_data={},
        brief=dict(BRIEF),
        seed_targeting=dict(SEED),
        broad_targeting=dict(BROAD),
        page_id="pg1",
    )
    params.update(kwargs)
    return build_campaign_spec(**params).model_dump(mode="json")


# ── what the template takes ──────────────────────────────────────────────────


def test_template_carries_the_setup():
    tpl, _ = campaign_template(_tree())
    adset = tpl["adsets"][0]
    assert tpl["objective"] == "OUTCOME_SALES"
    assert adset["optimization_goal"] == "OFFSITE_CONVERSIONS"
    assert adset["billing_event"] == "IMPRESSIONS"
    assert adset["bid_strategy"] == "COST_CAP"
    assert adset["bid_amount"] == 1200
    assert adset["creatives"][0]["title"] == "Old headline"
    assert adset["creatives"][0]["call_to_action"] == "SHOP_NOW"


# ── contradictions Meta hands back ───────────────────────────────────────────
# Both of these are shapes the Graph API legitimately returns and AdSetSpec /
# CreativeSpec legitimately reject. The template has to reconcile them, or a
# perfectly ordinary previous campaign becomes unusable.


def _cbo_tree() -> dict:
    """Under campaign budget optimization Meta keeps bid_strategy on the campaign
    and returns nothing for it on the ad set — so the ad set comes back with a
    bid_amount and no strategy to justify it."""
    tree = _tree()
    del tree["adsets"][0]["bid_strategy"]
    return tree


def test_cbo_adset_inherits_the_campaigns_bid_strategy():
    tpl, notes = campaign_template(_cbo_tree())
    adset = tpl["adsets"][0]
    assert adset["bid_strategy"] == "COST_CAP"
    assert adset["bid_amount"] == 1200
    assert notes == []


def test_the_inherited_strategy_makes_the_overlay_valid():
    """The point of inheriting: without it the merged spec is a bid_amount with
    LOWEST_COST_WITHOUT_CAP, which AdSetSpec rejects."""
    tpl, _ = campaign_template(_cbo_tree())
    merged = apply_campaign_template(_built(), tpl)
    spec = CampaignSpec.model_validate(merged)
    assert spec.adsets[0].bid_strategy.value == "COST_CAP"
    assert spec.adsets[0].bid_amount == 1200


def test_an_orphan_bid_amount_is_dropped_and_reported():
    """No strategy anywhere to justify the amount — drop it rather than import a
    contradiction, and say so."""
    tree = _cbo_tree()
    del tree["campaign"]["bid_strategy"]
    tpl, notes = campaign_template(tree)
    assert "bid_amount" not in tpl["adsets"][0]
    assert any("bid amount" in n for n in notes)


def test_reusing_an_old_asset_clears_this_runs_upload_reference():
    """CreativeSpec allows exactly one media reference. A plan that already had an
    uploaded image must not end up carrying both it and the template's hash."""
    built = _built()
    built["adsets"][0]["ads"][0]["creative"]["media_id"] = "upload-from-this-run"

    tpl, _ = campaign_template(_tree())
    merged = apply_campaign_template(built, tpl)

    creative = merged["adsets"][0]["ads"][0]["creative"]
    assert creative["image_hash"] == "HASH_OLD"
    assert "media_id" not in creative
    # The real proof: the result is publishable.
    spec = CampaignSpec.model_validate(merged)
    assert spec.adsets[0].ads[0].creative.media_kind == "image"


def test_media_carries_by_reference_not_by_upload():
    """image_hash is account-level and permanent, so the old asset is reused with
    no download and no re-upload."""
    tpl, _ = campaign_template(_tree())
    creative = tpl["adsets"][0]["creatives"][0]
    assert creative["image_hash"] == "HASH_OLD"
    assert "media_id" not in creative


# ── what the template must NOT take ──────────────────────────────────────────


def test_template_never_carries_targeting_or_audiences():
    """The regression that would defeat the whole feature: reusing the old
    audience skips the POI + MAID work that is the product."""
    tpl, _ = campaign_template(_tree())
    flat = str(tpl)
    assert "targeting" not in tpl["adsets"][0]
    assert "stale_audience" not in flat
    assert "10001" not in flat          # the old campaign's ZIP


def test_template_never_carries_budgets_or_dates():
    """Budget and flight are what the user is actively choosing this run."""
    adset = campaign_template(_tree())[0]["adsets"][0]
    for absent in ("daily_budget", "lifetime_budget", "start_time", "end_time"):
        assert absent not in adset


# ── refusals and notes ───────────────────────────────────────────────────────


@pytest.mark.parametrize("objective", ["LINK_CLICKS", "CONVERSIONS", "VIDEO_VIEWS"])
def test_pre_odax_objective_is_refused_by_name(objective):
    """Those campaigns still exist but Meta will not accept the objective for a
    new one, so there is nothing to copy it into."""
    tree = _tree()
    tree["campaign"]["objective"] = objective
    with pytest.raises(TemplateImportError, match=objective):
        campaign_template(tree)


def test_a_campaign_with_no_adsets_is_refused():
    with pytest.raises(TemplateImportError, match="no ad sets"):
        campaign_template(_tree(adsets=[]))


def test_unmodelled_promoted_object_fields_are_dropped_and_reported():
    tree = _tree()
    tree["adsets"][0]["promoted_object"]["product_set_id"] = "ps_1"
    tpl, notes = campaign_template(tree)
    assert "product_set_id" not in tpl["adsets"][0]["promoted_object"]
    assert any("product_set_id" in n for n in notes)


def test_a_carousel_keeps_its_copy_and_says_the_cards_need_redoing():
    """The old cards' links point at the previous campaign's destination."""
    tree = _tree()
    tree["adsets"][0]["ads"][0]["creative"]["object_story_spec"]["link_data"][
        "child_attachments"
    ] = [{"link": "https://old.example/1"}]
    tpl, notes = campaign_template(tree)
    creative = tpl["adsets"][0]["creatives"][0]
    assert creative["title"] == "Old headline"
    assert "image_hash" not in creative
    assert any("carousel" in n.lower() for n in notes)


def test_a_boosted_post_template_carries_only_the_post():
    tree = _tree()
    tree["adsets"][0]["ads"][0]["creative"] = {"object_story_id": "pg_1_99"}
    tpl, _ = campaign_template(tree)
    creative = tpl["adsets"][0]["creatives"][0]
    assert creative["object_story_id"] == "pg_1_99"
    assert "title" not in creative


def test_an_instagram_post_template_carries_the_media_id():
    tree = _tree()
    tree["adsets"][0]["ads"][0]["creative"] = {"source_instagram_media_id": "ig_77"}
    tpl, _ = campaign_template(tree)
    creative = tpl["adsets"][0]["creatives"][0]
    assert creative["source_instagram_media_id"] == "ig_77"
    assert "title" not in creative


def test_a_composed_ad_is_not_mistaken_for_a_boosted_post():
    """Every ad has an ``effective_object_story_id``, including ordinary composed
    ones — Meta creates an unpublished post behind them. Reading it before the
    composed copy would turn "reuse this campaign's setup and copy" into "promote
    its posts" for every template, silently discarding the headlines.
    """
    tree = _tree()
    tree["adsets"][0]["ads"][0]["creative"]["effective_object_story_id"] = "pg_1_555"
    tpl, _ = campaign_template(tree)
    creative = tpl["adsets"][0]["creatives"][0]

    assert creative["title"] == "Old headline"
    assert "object_story_id" not in creative


def test_an_inline_post_ad_falls_back_to_the_effective_id():
    """An ad built from an inline unpublished post has a null ``object_story_id``
    and no readable copy — the effective id is the only thing that names what it
    runs, and it is what "copy an existing ad" needs."""
    tree = _tree()
    tree["adsets"][0]["ads"][0]["creative"] = {
        "object_story_id": None,
        "effective_object_story_id": "pg_1_777",
    }
    tpl, _ = campaign_template(tree)

    assert tpl["adsets"][0]["creatives"][0]["object_story_id"] == "pg_1_777"


# ── applying it ──────────────────────────────────────────────────────────────


def test_overlay_keeps_this_runs_audience():
    """The heart of it: settings from the old campaign, audience from this run."""
    tpl, _ = campaign_template(_tree())
    merged = apply_campaign_template(_built(), tpl)

    targeting = merged["adsets"][0]["targeting"]
    assert targeting["geo_locations"]["zips"] == [{"key": "US:94104"}]
    assert targeting["custom_audiences"] == [{"id": "new_seed"}]
    assert "stale_audience" not in str(merged)


def test_overlay_keeps_this_runs_budget():
    tpl, _ = campaign_template(_tree())
    merged = apply_campaign_template(_built(), tpl)
    # $50/day from the form, split 60/40 across this run's two ad sets. The old
    # campaign's budget is not what carries over — the bid strategy is.
    assert sum(a["daily_budget"] for a in merged["adsets"]) == 5000
    assert merged["adsets"][0]["daily_budget"] == 3000
    assert merged["adsets"][0]["bid_amount"] == 1200       # cost cap from the template


def test_overlay_applies_the_settings_and_copy():
    tpl, _ = campaign_template(_tree())
    merged = apply_campaign_template(_built(), tpl)
    adset = merged["adsets"][0]
    assert merged["objective"] == "OUTCOME_SALES"
    assert adset["optimization_goal"] == "OFFSITE_CONVERSIONS"
    creative = adset["ads"][0]["creative"]
    assert creative["title"] == "Old headline"
    assert creative["image_hash"] == "HASH_OLD"
    # Two media references on one creative is a validation error, so reusing the
    # old asset has to clear this run's (empty) upload slot.
    assert not creative.get("media_id")


def test_overlay_keeps_this_runs_destination_link():
    """The old campaign's link could point somewhere that no longer applies."""
    tpl, _ = campaign_template(_tree())
    merged = apply_campaign_template(_built(), tpl)
    assert merged["adsets"][0]["ads"][0]["creative"]["link"].startswith(
        "https://beanthere.example"
    )


def test_overlay_keeps_this_runs_pixel_but_the_old_event():
    """A stale pixel id points at the wrong account; the event type is the part
    the user actually chose."""
    built = _built(pixel_id="live_pixel", user_info={**USER_INFO, "campaign_objective": "SALES"})
    tpl, _ = campaign_template(_tree())
    merged = apply_campaign_template(built, tpl)
    promoted = merged["adsets"][0]["promoted_object"]
    assert promoted["pixel_id"] == "live_pixel"
    assert promoted["custom_event_type"] == "ADD_TO_CART"


def test_a_template_with_fewer_adsets_repeats_its_last():
    """The budget split comes from this run's brief and need not match the old
    campaign's shape."""
    brief = {**BRIEF, "adset_budget_breakdown": [
        {"adset_name": "Visitors", "budget_pct": 70, "audience_type": "primary"},
        {"adset_name": "Prospecting", "budget_pct": 30, "audience_type": "lookalike"},
    ]}
    built = build_campaign_spec(
        user_info=dict(USER_INFO), geo_data={}, brief=brief,
        seed_targeting=dict(SEED), broad_targeting=dict(BROAD), page_id="pg1",
    ).model_dump(mode="json")

    tpl, _ = campaign_template(_tree())
    merged = apply_campaign_template(built, tpl)

    assert len(merged["adsets"]) == 2
    assert all(a["optimization_goal"] == "OFFSITE_CONVERSIONS" for a in merged["adsets"])


def test_an_overlay_the_matrix_rejects_is_repaired_not_left_broken():
    """Meta accepts combinations we do not model. The plan editor still has to open
    on the user's reused campaign — an unopenable tree of field errors is worse
    than a repaired one, so the illegal value is replaced and the swap is noted."""
    tree = _tree()
    # Legal at Meta, not a pair our matrix offers: a Sales campaign optimizing
    # for page likes.
    tree["adsets"][0]["optimization_goal"] = "PAGE_LIKES"
    tpl, _ = campaign_template(tree)

    merged = apply_campaign_template(_built(), tpl)      # must not raise
    spec = CampaignSpec.model_validate(merged)           # nor leave an invalid tree
    assert spec.adsets[0].optimization_goal.value != "PAGE_LIKES"
    assert any("optimized for something" in n for n in spec.compliance_notes)


def test_a_template_from_another_objective_does_not_trap_the_editor():
    """The overlay copies the template's objective AND its ad set settings; a Leads
    instant-form ad set on a plan built for Awareness needs a lead form nothing
    collected. Reconciling against the merged objective is what keeps the editor
    openable on the values the user asked to start from."""
    tree = _tree()
    tree["campaign"]["objective"] = "OUTCOME_LEADS"
    tree["adsets"][0]["destination_type"] = "ON_AD"
    tree["adsets"][0]["optimization_goal"] = "LEAD_GENERATION"
    tpl, _ = campaign_template(tree)

    merged = apply_campaign_template(_built(), tpl, page_id="pg1")
    spec = CampaignSpec.model_validate(merged)
    assert spec.objective.value == "OUTCOME_LEADS"
    assert spec.adsets[0].destination_type.value == "ON_AD"
    assert spec.adsets[0].promoted_object.page_id == "pg1"
    # "Create one for me" — publish builds the form against the finished campaign.
    assert spec.adsets[0].ads[0].creative.lead_gen_form_id is None


def test_no_template_leaves_the_plan_untouched():
    built = _built()
    assert apply_campaign_template(built, {}) == built


# ── copying only part of a campaign ──────────────────────────────────────────
# All-or-nothing was the original shape. What advertisers actually want is "the
# settings off my winning ad set" or "those two proven creatives" — so the tree is
# filtered before it becomes a template, and the plan's own shape still wins.


def _multi_tree() -> dict:
    """Two ad sets, the first with two ads — the shape a picker exists for."""
    tree = _tree()
    first = tree["adsets"][0]
    first["ads"].append({
        "id": "ad_old_2",
        "name": "Second old ad",
        "creative": {
            "object_story_spec": {
                "link_data": {
                    "name": "Second headline",
                    "message": "Second body copy",
                    "image_hash": "HASH_TWO",
                    "call_to_action": {"type": "LEARN_MORE"},
                }
            }
        },
    })
    second = json.loads(json.dumps(first))
    second["id"] = "as_old_2"
    second["name"] = "Other old ad set"
    second["optimization_goal"] = "LINK_CLICKS"
    second["bid_amount"] = 4200
    second["ads"] = [{
        "id": "ad_other",
        "name": "Other ad",
        "creative": {
            "object_story_spec": {
                "link_data": {
                    "name": "Other headline",
                    "message": "Other body copy",
                    "image_hash": "HASH_OTHER",
                    "call_to_action": {"type": "SHOP_NOW"},
                }
            }
        },
    }]
    tree["adsets"].append(second)
    return tree


def test_only_the_picked_adsets_and_ads_are_copied():
    subset = select_tree_subset(_multi_tree(), ["as_old_2"], ["ad_other"])
    tpl, _ = campaign_template(subset)

    assert len(tpl["adsets"]) == 1
    assert tpl["adsets"][0]["optimization_goal"] == "LINK_CLICKS"
    assert [c["title"] for c in tpl["adsets"][0]["creatives"]] == ["Other headline"]


def test_no_selection_copies_the_whole_campaign():
    """Absent lists are the pre-picker behaviour — an older frontend, or an editor
    that could not read the campaign's structure, must still get everything."""
    tree = _multi_tree()
    assert select_tree_subset(tree) == tree
    assert select_tree_subset(tree, None, None) == tree


def test_picking_no_ads_is_not_the_same_as_picking_none():
    """[] means "the picker was used and nothing was ticked". Reading it as "no
    filter" would copy every ad the user just unticked."""
    subset = select_tree_subset(_multi_tree(), ["as_old"], [])
    assert [a["id"] for a in subset["adsets"]] == ["as_old"]
    assert subset["adsets"][0]["ads"] == []


def test_an_adset_picked_with_no_ads_copies_settings_but_keeps_this_runs_copy():
    subset = select_tree_subset(_multi_tree(), ["as_old"], [])
    tpl, _ = campaign_template(subset)
    assert "creatives" not in tpl["adsets"][0]

    merged = apply_campaign_template(_built(), tpl)
    creative = merged["adsets"][0]["ads"][0]["creative"]
    assert merged["adsets"][0]["optimization_goal"] == "OFFSITE_CONVERSIONS"
    assert creative["title"] == "Fresh roast, daily"      # this run's brief
    assert creative.get("image_hash") is None             # nor the old ad's asset


def test_extra_picked_adsets_are_dropped_and_reported():
    """This run owns the budget split and the seed/lookalike roles, so a third ad
    set cannot simply be added — but the user has to be told it wasn't."""
    tree = _multi_tree()
    third = json.loads(json.dumps(tree["adsets"][1]))
    third["id"] = "as_old_3"
    third["name"] = "A third old ad set"
    tree["adsets"].append(third)

    tpl, _ = campaign_template(tree)
    merged = apply_campaign_template(_built(), tpl)      # the plan has two ad sets

    assert len(merged["adsets"]) == 2
    assert any("ad set" in n and "didn't fit" in n for n in merged["compliance_notes"])


def test_extra_picked_ads_are_dropped_and_reported():
    subset = select_tree_subset(_multi_tree(), ["as_old"], ["ad_old", "ad_old_2"])
    tpl, _ = campaign_template(subset)
    merged = apply_campaign_template(_built(), tpl)      # the ad set has one ad

    assert len(merged["adsets"][0]["ads"]) == 1
    assert any("ads from that campaign" in n for n in merged["compliance_notes"])


def test_nothing_picked_at_all_is_refused_rather_than_silently_ignored():
    with pytest.raises(TemplateImportError):
        campaign_template(select_tree_subset(_multi_tree(), [], []))


# ── the wire from the plan editor ────────────────────────────────────────────
# The overlay is well covered above; what is not is the action that reaches it.
# A template is picked from inside the editor, so the id travels as an editor
# submission rather than as a user_info key — a rename on either side loses the
# feature silently: no error, just a plan that never changes.


@pytest.mark.asyncio
async def test_the_editors_apply_template_action_reaches_the_overlay(monkeypatch):
    from app.graph.builder import builder_node

    async def _fake_tree(campaign_id, access_token):
        assert campaign_id == "c_old"
        return _tree()

    monkeypatch.setattr(
        "app.services.meta_ads.fetch_campaign_tree", _fake_tree, raising=False
    )

    bs: dict = {"marketing_plan": _built()}
    state = {"user_info": {"meta_access_token": "tok", "meta_page_id": "pg1"}}
    note = await builder_node._apply_template_action(
        bs, state, {"action": "apply_template", "campaign_id": "c_old", "spec": _built()},
    )

    plan = bs["marketing_plan"]
    # The template's bidding survived; this run's audience did too.
    assert plan["adsets"][0]["bid_strategy"] == "COST_CAP"
    assert "old_lookalike" not in json.dumps(plan)
    assert "c_old" in note
    # generate_meta_json must not rebuild a brief-derived tree over this.
    assert "generate_meta_json" in bs["ops_done"]


@pytest.mark.asyncio
async def test_the_editors_selection_reaches_the_overlay(monkeypatch):
    """The ticked ids travel as editor submission keys. A rename on either side
    silently reverts the feature to copying whole campaigns."""
    from app.graph.builder import builder_node

    async def _fake_tree(campaign_id, access_token):
        return _multi_tree()

    monkeypatch.setattr(
        "app.services.meta_ads.fetch_campaign_tree", _fake_tree, raising=False
    )

    bs: dict = {"marketing_plan": _built()}
    state = {"user_info": {"meta_access_token": "tok", "meta_page_id": "pg1"}}
    await builder_node._apply_template_action(bs, state, {
        "action": "apply_template",
        "campaign_id": "c_old",
        "adset_ids": ["as_old_2"],
        "ad_ids": ["ad_other"],
        "spec": _built(),
    })

    plan = bs["marketing_plan"]
    assert plan["adsets"][0]["optimization_goal"] == "LINK_CLICKS"   # the picked one
    assert plan["adsets"][0]["ads"][0]["creative"]["title"] == "Other headline"
    # Nothing from the unticked ad set or its ads came along.
    assert "HASH_OLD" not in json.dumps(plan)


@pytest.mark.asyncio
async def test_choosing_set_up_fresh_keeps_the_plan_on_screen():
    from app.graph.builder import builder_node

    bs: dict = {"marketing_plan": _built()}
    edited = _built()
    edited["name"] = "Renamed in the editor"
    await builder_node._apply_template_action(
        bs, {"user_info": {}}, {"action": "apply_template", "campaign_id": "", "spec": edited},
    )
    assert bs["marketing_plan"]["name"] == "Renamed in the editor"


@pytest.mark.asyncio
async def test_an_unreadable_template_says_so_instead_of_silently_starting_fresh(monkeypatch):
    from app.graph.builder import builder_node

    async def _boom(campaign_id, access_token):
        raise RuntimeError("token expired")

    monkeypatch.setattr(
        "app.services.meta_ads.fetch_campaign_tree", _boom, raising=False
    )

    plan = await builder_node._apply_previous_campaign({}, {"meta_access_token": "t"}, _built(), "c_old")
    assert any("c_old" in n for n in plan["compliance_notes"])


# ── reconciling against a different objective ────────────────────────────────
# _reconcile_adset exists so a template from another objective produces an
# EDITABLE plan rather than a tree of field errors on values the user never
# typed. Four fields were left out of that repair.


def _awareness_built() -> dict:
    return _built(user_info={**USER_INFO, "campaign_objective": "AWARENESS"})


def test_a_capped_bid_strategy_the_new_goal_forbids_is_repaired():
    """The template is Sales + cost cap. Awareness's Reach goal takes no cost cap,
    and CampaignSpec checks the strategy against BOTH the objective and the goal —
    so this used to raise instead of opening."""
    # The template's objective always wins, so overriding it here is what puts a
    # Sales ad set under Awareness rules — the cross-objective case.
    merged = apply_campaign_template(
        _awareness_built(), {**campaign_template(_tree())[0], "objective": "OUTCOME_AWARENESS"}
    )
    adset = merged["adsets"][0]
    assert adset["bid_strategy"] != "COST_CAP"
    # A strategy that takes no amount must not carry one.
    assert not adset.get("bid_amount")
    CampaignSpec.model_validate(merged)      # the whole point: it opens


def test_a_frequency_cap_the_new_goal_forbids_is_dropped():
    """Meta only honours frequency_control_specs on Reach and ThruPlay. A template
    carrying one onto a conversion goal made the plan unopenable."""
    tpl = campaign_template(_tree())[0]
    tpl["adsets"][0]["frequency_control_specs"] = [
        {"event": "IMPRESSIONS", "interval_days": 7, "max_frequency": 2}
    ]
    merged = apply_campaign_template(_built(), tpl)
    assert not merged["adsets"][0].get("frequency_control_specs")
    CampaignSpec.model_validate(merged)


def test_an_attribution_window_survives_a_goal_that_reports_conversions():
    """The repair is targeted, not a blanket wipe: OFFSITE_CONVERSIONS does report
    a conversion, so its window is kept."""
    tpl = campaign_template(_tree())[0]
    tpl["adsets"][0]["attribution_spec"] = [
        {"event_type": "CLICK_THROUGH", "window_days": 7}
    ]
    merged = apply_campaign_template(_built(), tpl)
    assert merged["adsets"][0]["attribution_spec"] == [
        {"event_type": "CLICK_THROUGH", "window_days": 7}
    ]


def test_an_attribution_window_the_new_goal_cannot_report_is_dropped():
    tpl = campaign_template(_tree())[0]
    tpl["adsets"][0]["attribution_spec"] = [
        {"event_type": "CLICK_THROUGH", "window_days": 7}
    ]
    merged = apply_campaign_template(
        _awareness_built(), {**tpl, "objective": "OUTCOME_AWARENESS"}
    )
    assert not merged["adsets"][0].get("attribution_spec")
    CampaignSpec.model_validate(merged)


def test_a_billing_event_the_new_goal_forbids_is_repaired():
    """Sales → Website offers LINK_CLICKS billing, but only alongside the
    LINK_CLICKS goal — Conversions bills on impressions. The repair checked the
    destination alone, so this pair reached CampaignSpec and raised."""
    tpl = campaign_template(_tree())[0]
    tpl["adsets"][0]["billing_event"] = "LINK_CLICKS"
    merged = apply_campaign_template(_built(), tpl)
    assert merged["adsets"][0]["billing_event"] == "IMPRESSIONS"
    CampaignSpec.model_validate(merged)


def test_a_carousel_the_new_goal_forbids_is_repaired():
    """Awareness offers carousel, ThruPlay does not: it optimizes for watch time
    and publishes as a single video_data creative. Same missing intersection."""
    tpl = campaign_template(_tree())[0]
    tpl["objective"] = "OUTCOME_AWARENESS"
    tpl["adsets"][0]["optimization_goal"] = "THRUPLAY"
    tpl["adsets"][0]["creatives"][0]["format"] = "CAROUSEL"
    merged = apply_campaign_template(_awareness_built(), tpl)
    assert merged["adsets"][0]["ads"][0]["creative"]["format"] == "SINGLE"


def test_a_template_can_clear_a_special_ad_category():
    """The overlay was additive-only (`if template.get(key)`), so starting from an
    unregulated campaign could not undo a category already on the plan — and the
    country would have been left behind without its category, which Meta rejects."""
    built = _built()
    built["special_ad_categories"] = ["HOUSING"]
    built["special_ad_category_country"] = ["US"]

    merged = apply_campaign_template(built, campaign_template(_tree())[0])
    assert merged["special_ad_categories"] == []
    assert merged["special_ad_category_country"] == []


def test_a_template_still_applies_the_category_it_carries():
    tpl = campaign_template(_tree())[0]
    tpl["special_ad_categories"] = ["HOUSING"]
    tpl["special_ad_category_country"] = ["CA"]
    merged = apply_campaign_template(_built(), tpl)
    assert merged["special_ad_categories"] == ["HOUSING"]
    assert merged["special_ad_category_country"] == ["CA"]


@pytest.mark.asyncio
async def test_an_invalid_on_screen_spec_reopens_the_editor_instead_of_being_stored():
    """The template path stored the submitted spec with no validation, unlike the
    save path. An invalid tree in marketing_plan is not a local problem: the next
    render re-validates it, fails, drops generate_meta_json and rebuilds from the
    brief — silently throwing the user's whole plan away."""
    from app.graph.builder.builder_node import _apply_template_action

    broken = _built()
    broken["adsets"][0]["daily_budget"] = 1        # below Meta's floor

    bs: dict = {"marketing_plan": _built()}
    note = await _apply_template_action(
        bs, {"user_info": {}}, {"campaign_id": "c_old", "spec": broken}
    )

    assert "validation errors" in note
    assert bs["marketing_plan_draft"] is broken     # the editor re-renders what they typed
    assert bs["plan_errors"]
    assert bs["marketing_plan"] != broken           # the stored plan is untouched
