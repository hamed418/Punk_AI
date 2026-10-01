"""
Unit tests for app/graph/meta_spec — the Meta vocabulary, the per-objective
matrix, and the strict payload models.

These are pure: no network, no ad account, no LLM. Every rule the old code got
wrong has a test here so it cannot regress.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import facebook_business
import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.graph.meta_spec.enums import (
    CALL_TO_ACTION_ALL,
    CATEGORIES_BLOCKING_DEMOGRAPHICS,
    CREATIVE_BODY_MAX,
    CREATIVE_DESCRIPTION_MAX,
    CREATIVE_TITLE_MAX,
    DESTINATION_TYPE_ALL,
    FREQUENCY_DEFAULT_INTERVAL_DAYS,
    FREQUENCY_DEFAULT_MAX,
    FREQUENCY_MAX_INTERVAL_DAYS,
    OPTIMIZATION_GOAL_ALL,
    AdFormat,
    BidStrategy,
    BillingEvent,
    CallToAction,
    DestinationType,
    Objective,
    OptimizationGoal,
    SpecialAdCategory,
    meta_label,
    normalize_objective,
)
from app.graph.meta_spec.catalog import build_editor_catalog
from app.graph.meta_spec.models import (
    MIN_BUDGET_CENTS,
    AdSetSpec,
    AdSpec,
    AttributionWindow,
    BidConstraints,
    BudgetScheduleSpec,
    DayPartSpec,
    CampaignSpec,
    CarouselCard,
    CreativeSpec,
    FrequencyControlSpec,
    PromotedObject,
)
from app.graph.meta_spec.objective_matrix import (
    OBJECTIVE_MATRIX,
    PROMOTED_APPLICATION,
    PROMOTED_PAGE,
    PROMOTED_PIXEL,
    goal_rules,
    matrix_for,
)
from app.graph.meta_spec.special_categories import detect_special_ad_categories

START = datetime(2026, 8, 1, tzinfo=timezone.utc)
END = START + timedelta(days=30)

GEO = {"geo_locations": {"countries": ["US"]}, "age_min": 18, "age_max": 65, "genders": []}


# ── enums ────────────────────────────────────────────────────────────────────


def test_every_enum_value_exists_in_the_sdk():
    """The whole point of sourcing from facebook_business is that a value we
    reference cannot drift from what Meta accepts."""
    assert {g.value for g in OptimizationGoal} <= OPTIMIZATION_GOAL_ALL
    assert {d.value for d in DestinationType} <= DESTINATION_TYPE_ALL
    assert {c.value for c in CallToAction} <= CALL_TO_ACTION_ALL


def test_retired_cta_codes_are_gone():
    """SEE_MENU and SEND_MESSAGE were in the old META_CTA_OPTIONS list but are
    not Meta CTA codes — selecting one produced a rejected ad creative."""
    codes = {c.value for c in CallToAction}
    assert "SEE_MENU" not in codes
    assert "SEND_MESSAGE" not in codes
    assert "START_ORDER" in codes
    assert "MESSAGE_PAGE" in codes


def test_install_mobile_app_is_selectable():
    """Used as the app-promotion default at publish, but previously missing from
    the picker — a user who changed it could not get back to it."""
    assert CallToAction.INSTALL_MOBILE_APP.value in {c.value for c in CallToAction}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("sales", Objective.SALES),
        ("SALES", Objective.SALES),
        ("App Promotion", Objective.APP_PROMOTION),
        ("app-promotion", Objective.APP_PROMOTION),
        ("OUTCOME_LEADS", Objective.LEADS),
        ("", None),
        (None, None),
        ("nonsense", None),
    ],
)
def test_normalize_objective(raw, expected):
    assert normalize_objective(raw) is expected


def test_unknown_objective_raises_instead_of_defaulting():
    """create_campaign used to fall back to OUTCOME_AWARENESS, publishing a
    campaign optimizing for something nobody chose."""
    with pytest.raises(KeyError):
        matrix_for("not-an-objective")


# ── matrix ───────────────────────────────────────────────────────────────────


def test_matrix_covers_every_objective():
    assert set(OBJECTIVE_MATRIX) == set(Objective)


@pytest.mark.parametrize("objective", list(Objective))
def test_matrix_defaults_are_self_consistent(objective):
    """Each destination's defaults must be members of its own allowed sets, and
    the objective's default destination must be one it offers."""
    rules = OBJECTIVE_MATRIX[objective]
    assert rules.allows_destination_type(rules.default_destination_type.value)
    assert rules.allows_bid_strategy(rules.default_bid_strategy.value)
    for dest in rules.destinations:
        assert dest.allows_optimization_goal(dest.default_optimization_goal.value)
        assert dest.allows_billing_event(dest.default_billing_event.value)
        assert dest.allows_call_to_action(dest.default_call_to_action.value)
        assert dest.allows_ad_format(dest.default_ad_format.value)


def test_objectives_differ_in_required_fields():
    """The premise of a dynamic form: the field set is not the same per
    objective."""
    awareness = matrix_for(Objective.AWARENESS)
    sales = matrix_for(Objective.SALES)
    app = matrix_for(Objective.APP_PROMOTION)

    # An Awareness ad needs nothing — no website, no pixel, no app. Its link
    # falls back to the connected Page.
    assert awareness.required_user_info == ()
    assert "website_url" in sales.for_destination(DestinationType.WEBSITE).required_user_info
    assert "app_store_url" in app.required_user_info

    assert awareness.default_destination.promoted_object_kind(OptimizationGoal.REACH) == "none"
    assert sales.for_destination(DestinationType.WEBSITE).promoted_object_kind(
        OptimizationGoal.OFFSITE_CONVERSIONS
    ) == PROMOTED_PIXEL
    assert app.default_destination.promoted_object_kind(
        OptimizationGoal.APP_INSTALLS
    ) == PROMOTED_APPLICATION


def test_objective_required_user_info_is_an_intersection_not_a_union():
    """Leads via Instant forms needs no website. Treating website_url as an
    objective-level requirement would block a perfectly valid campaign."""
    leads = matrix_for(Objective.LEADS)
    assert "website_url" not in leads.required_user_info
    assert "website_url" in leads.for_destination(DestinationType.WEBSITE).required_user_info


def test_leads_supports_both_instant_form_and_website():
    """One objective, two promoted-object shapes — the case a flat
    objective→goal dict could not express."""
    rules = matrix_for(Objective.LEADS)
    on_ad = rules.for_destination(DestinationType.ON_AD)
    website = rules.for_destination(DestinationType.WEBSITE)
    assert on_ad.promoted_object_kind(OptimizationGoal.LEAD_GENERATION) == PROMOTED_PAGE
    assert website.promoted_object_kind(OptimizationGoal.OFFSITE_CONVERSIONS) == PROMOTED_PIXEL
    assert on_ad.requires_lead_form and not website.requires_lead_form


def test_lead_generation_is_not_offered_on_a_website_destination():
    """The shipped default used to be LEADS + WEBSITE + LEAD_GENERATION — every
    value legal for the objective, the pair rejected by Meta. This is the
    regression that motivated the second matrix axis."""
    website = matrix_for(Objective.LEADS).for_destination(DestinationType.WEBSITE)
    assert not website.allows_optimization_goal(OptimizationGoal.LEAD_GENERATION.value)


def test_unknown_destination_for_an_objective_raises():
    with pytest.raises(KeyError):
        matrix_for(Objective.AWARENESS).for_destination(DestinationType.SHOP_AUTOMATIC)


# ── helpers ──────────────────────────────────────────────────────────────────


def _creative(**overrides) -> CreativeSpec:
    base = dict(
        title="Great headline",
        body="Some body copy that fits.",
        call_to_action=CallToAction.LEARN_MORE,
        link="https://example.com",
    )
    base.update(overrides)
    return CreativeSpec(**base)


def _adset(**overrides) -> AdSetSpec:
    # Ads are nested under their ad set; every ad set carries at least one.
    ads = overrides.pop("ads", None) or [AdSpec(name="Ad 1", creative=_creative())]
    base = dict(
        name="Ad Set 1",
        optimization_goal=OptimizationGoal.REACH,
        billing_event=BillingEvent.IMPRESSIONS,
        # Required now: the conversion location is the second matrix axis, so
        # nothing below it can be validated without it.
        destination_type=DestinationType.WEBSITE,
        daily_budget=5000,
        targeting=dict(GEO),
        start_time=START,
        ads=ads,
    )
    base.update(overrides)
    return AdSetSpec(**base)


def test_frequency_cap_accepted_on_reach_adset():
    """frequency_control_specs is valid when the goal is Reach; it reaches the
    ad-set payload verbatim."""
    aset = _adset(
        optimization_goal=OptimizationGoal.REACH,
        frequency_control_specs=[
            FrequencyControlSpec(interval_days=7, max_frequency=3)
        ],
    )
    payload = aset.to_payload(campaign_id="c1", ad_account_id="act_1")
    assert payload["frequency_control_specs"] == [
        {"event": "IMPRESSIONS", "interval_days": 7, "max_frequency": 3}
    ]


def test_frequency_cap_rejected_off_a_frequency_goal():
    """Meta accepts a frequency cap on Reach and ThruPlay ad sets. Anything else
    is a validation error, not a silently-dropped field.

    The check lives on CampaignSpec now: an ad set alone does not know its
    objective, and the rule belongs to the optimization goal."""
    with pytest.raises(ValidationError, match="frequency_control_specs is only accepted"):
        _campaign(
            objective=Objective.TRAFFIC,
            adsets=[_adset(
                optimization_goal=OptimizationGoal.LINK_CLICKS,
                billing_event=BillingEvent.IMPRESSIONS,
                destination_type=DestinationType.WEBSITE,
                frequency_control_specs=[
                    FrequencyControlSpec(interval_days=7, max_frequency=3)
                ],
            )],
        )


def _spec_from_defaults(objective: Objective, dest=None) -> CampaignSpec:
    """A minimal valid campaign built entirely from the matrix's own defaults for
    one objective × conversion location."""
    rules = matrix_for(objective)
    dest = rules.for_destination(dest) if dest is not None else rules.default_destination
    goal = dest.default_optimization_goal
    promoted = {
        PROMOTED_PIXEL: PromotedObject(pixel_id="123456789", custom_event_type="PURCHASE"),
        PROMOTED_PAGE: PromotedObject(page_id="987654321"),
        PROMOTED_APPLICATION: PromotedObject(
            application_id="111", object_store_url="https://apps.apple.com/app/id1"
        ),
        "none": None,
    }[dest.promoted_object_kind(goal)]

    creative_kwargs: dict = {
        "call_to_action": dest.default_call_to_action,
        "format": dest.default_ad_format,
    }
    if dest.default_ad_format is AdFormat.CAROUSEL:
        creative_kwargs["cards"] = [
            CarouselCard(title=f"Card {i}", link="https://example.com") for i in (1, 2)
        ]
    if dest.requires_lead_form:
        creative_kwargs["lead_gen_form_id"] = "form-1"
    if dest.object_story_kind:
        # A boost destination promotes a post that already exists on the Page.
        creative_kwargs["object_story_id"] = "1234_5678"

    return _campaign(
        objective=objective,
        adsets=[_adset(
            optimization_goal=goal,
            billing_event=dest.default_billing_event,
            destination_type=dest.destination_type,
            bid_strategy=rules.default_bid_strategy,
            promoted_object=promoted,
            ads=[AdSpec(name="Ad 1", creative=_creative(**creative_kwargs))],
        )],
    )


def _campaign(**overrides) -> CampaignSpec:
    base = dict(
        name="Test Campaign",
        objective=Objective.AWARENESS,
        adsets=[_adset()],
    )
    base.update(overrides)
    return CampaignSpec(**base)


# ── models: defaults validate ────────────────────────────────────────────────


@pytest.mark.parametrize("objective", list(Objective))
def test_matrix_defaults_build_a_valid_campaign(objective):
    """For every objective, its own defaults must produce a spec that passes
    validation — including whatever promoted_object that combination demands.

    This is the test that would have caught the Leads default: the pair was
    invalid even though each half was individually legal.
    """
    assert _spec_from_defaults(objective).objective is objective


@pytest.mark.parametrize(
    "objective,destination",
    [
        (obj, dest.destination_type)
        for obj, rules in OBJECTIVE_MATRIX.items()
        for dest in rules.destinations
    ],
)
def test_every_offered_destination_builds_a_valid_campaign(objective, destination):
    """The full cross-product. Every conversion location the catalog offers has
    to be reachable — an option the user can pick but not publish is worse than
    no option at all."""
    spec = _spec_from_defaults(objective, destination)
    assert spec.adsets[0].destination_type is destination


def test_a_goal_from_a_sibling_destination_is_rejected():
    """Legal for the objective, illegal for the chosen conversion location."""
    with pytest.raises(ValidationError, match="LEAD_GENERATION is not valid"):
        _campaign(
            objective=Objective.LEADS,
            adsets=[_adset(
                optimization_goal=OptimizationGoal.LEAD_GENERATION,
                destination_type=DestinationType.WEBSITE,
                promoted_object=PromotedObject(page_id="1"),
                ads=[AdSpec(name="Ad", creative=_creative(call_to_action=CallToAction.SIGN_UP))],
            )],
        )


def test_destination_not_offered_by_the_objective_is_rejected():
    with pytest.raises(ValidationError, match="not a conversion location"):
        _campaign(
            objective=Objective.AWARENESS,
            adsets=[_adset(destination_type=DestinationType.SHOP_AUTOMATIC)],
        )


# ── models: cross-objective rejections ───────────────────────────────────────


def test_optimization_goal_from_another_objective_is_rejected():
    with pytest.raises(ValidationError, match="OFFSITE_CONVERSIONS is not valid"):
        _campaign(
            objective=Objective.AWARENESS,
            adsets=[_adset(
                optimization_goal=OptimizationGoal.OFFSITE_CONVERSIONS,
                promoted_object=PromotedObject(pixel_id="1", custom_event_type="PURCHASE"),
            )],
        )


def test_billing_event_from_another_objective_is_rejected():
    with pytest.raises(ValidationError, match="billing_event"):
        _campaign(
            objective=Objective.LEADS,
            adsets=[_adset(
                optimization_goal=OptimizationGoal.LEAD_GENERATION,
                billing_event=BillingEvent.PAGE_LIKES,
                destination_type=DestinationType.ON_AD,
                promoted_object=PromotedObject(page_id="1"),
                ads=[AdSpec(name="Ad", creative=_creative(
                    call_to_action=CallToAction.SIGN_UP, lead_gen_form_id="form-1",
                ))],
            )],
        )


def test_cta_from_another_objective_is_rejected():
    with pytest.raises(ValidationError, match="call_to_action"):
        _campaign(
            objective=Objective.AWARENESS,
            adsets=[_adset(
                ads=[AdSpec(name="Ad", creative=_creative(call_to_action=CallToAction.INSTALL_MOBILE_APP))],
            )],
        )


# ── models: existing-post creatives ──────────────────────────────────────────


def _boost_campaign(**creative_overrides) -> CampaignSpec:
    """An Engagement → On your post campaign, the one destination that REQUIRES a
    post today."""
    return _campaign(
        objective=Objective.ENGAGEMENT,
        adsets=[_adset(
            destination_type=DestinationType.ON_POST,
            optimization_goal=OptimizationGoal.POST_ENGAGEMENT,
            billing_event=BillingEvent.IMPRESSIONS,
            ads=[AdSpec(name="Ad", creative=_creative(**creative_overrides))],
        )],
    )


def test_an_instagram_post_satisfies_a_boost_destination():
    """The ad IS the post either way — an Instagram post is the same idea from the
    other platform, and demanding a Facebook one would make IG unreachable."""
    spec = _boost_campaign(source_instagram_media_id="ig-123")

    assert spec.adsets[0].ads[0].creative.source_instagram_media_id == "ig-123"


def test_an_ad_cannot_promote_two_posts():
    with pytest.raises(ValidationError, match="one or the other"):
        _boost_campaign(object_story_id="123_456", source_instagram_media_id="ig-123")


def test_an_existing_post_is_rejected_where_it_is_not_known_to_work():
    """``allows_existing_post`` is measured per (objective, destination), not
    assumed — until a probe says a destination takes one, offering it would publish
    an ad Meta rejects."""
    with pytest.raises(ValidationError, match="promotes an existing post"):
        _campaign(
            objective=Objective.TRAFFIC,
            adsets=[_adset(
                optimization_goal=OptimizationGoal.LINK_CLICKS,
                billing_event=BillingEvent.IMPRESSIONS,
                ads=[AdSpec(name="Ad", creative=_creative(object_story_id="123_456"))],
            )],
        )


def test_a_boost_destination_still_needs_some_post():
    with pytest.raises(ValidationError, match="object_story_id is required"):
        _boost_campaign()


# ── models: conversion_domain and url_tags ───────────────────────────────────


def test_conversion_domain_is_derived_from_the_ad_link():
    """Aggregated Event Measurement needs a domain to attribute against, and no
    plan or editor submission carries one — so the model fills it."""
    ad = AdSpec(name="Ad", creative=_creative(link="https://www.shop.example.com/x?a=1"))

    assert ad.conversion_domain == "shop.example.com"


def test_explicit_conversion_domain_is_not_overwritten():
    ad = AdSpec(
        name="Ad",
        creative=_creative(link="https://www.shop.example.com/x"),
        conversion_domain="example.com",
    )

    assert ad.conversion_domain == "example.com"


@pytest.mark.parametrize(
    "bad,reason",
    [
        ("?utm_source=facebook", "separator"),
        ("&utm_source=facebook", "separator"),
        ("https://example.com?utm_source=x", "full URL"),
        ("utm_source=face book", "space"),
    ],
)
def test_url_tags_rejects_what_would_break_the_link(bad, reason):
    """Meta appends this to the link, so each of these produces a broken
    destination URL that only shows up as "direct" traffic weeks later."""
    with pytest.raises(ValidationError):
        _creative(url_tags=bad)


def test_url_tags_allows_metas_delivery_macros():
    """{{campaign.name}} is substituted by Meta per impression — it is the reason
    one default string stays correct across every ad in the plan."""
    creative = _creative(url_tags="utm_source=facebook&utm_campaign={{campaign.name}}")

    assert "{{campaign.name}}" in creative.url_tags


# ── models: promoted_object ──────────────────────────────────────────────────


def test_conversion_goal_without_pixel_is_rejected():
    """The expensive failure mode: media.py published this happily and then
    optimized against a signal that never fired."""
    with pytest.raises(ValidationError, match="Meta Pixel or custom conversion is required"):
        _campaign(
            objective=Objective.SALES,
            adsets=[_adset(optimization_goal=OptimizationGoal.OFFSITE_CONVERSIONS)],
        )


def test_custom_conversion_satisfies_the_pixel_requirement():
    """A custom conversion IS the event definition — it names the dataset and the
    rule — so it must be accepted where a bare pixel needs a custom_event_type.

    This is the route for the advertiser who has the base pixel on their site and
    no event code anywhere: without it, their only options are a conversion goal
    that can never be satisfied or no conversion optimization at all.
    """
    spec = _campaign(
        objective=Objective.SALES,
        adsets=[_adset(
            optimization_goal=OptimizationGoal.OFFSITE_CONVERSIONS,
            promoted_object=PromotedObject(
                pixel_id="123", custom_conversion_id="cc-9",
            ),
        )],
    )

    payload = spec.adsets[0].to_payload(campaign_id="c1", ad_account_id="act_1")
    assert payload["promoted_object"]["custom_conversion_id"] == "cc-9"


def test_custom_conversion_alone_names_a_pixel_shaped_promoted_object():
    """kind() reads by precedence, so a conversion with no pixel_id beside it must
    still register as the pixel shape — otherwise the goal check rejects it."""
    assert PromotedObject(custom_conversion_id="cc-9").kind() == PROMOTED_PIXEL


def test_pixel_without_custom_event_type_is_rejected():
    with pytest.raises(ValidationError, match="custom_event_type is required"):
        _campaign(
            objective=Objective.SALES,
            adsets=[_adset(
                optimization_goal=OptimizationGoal.OFFSITE_CONVERSIONS,
                promoted_object=PromotedObject(pixel_id="123"),
            )],
        )


def test_wrong_promoted_object_kind_is_rejected():
    """A page id where Meta wants a pixel."""
    with pytest.raises(ValidationError, match=r"promoted_object\.pixel_id is required"):
        _campaign(
            objective=Objective.SALES,
            adsets=[_adset(
                optimization_goal=OptimizationGoal.OFFSITE_CONVERSIONS,
                promoted_object=PromotedObject(page_id="123"),
            )],
        )


def test_app_promotion_requires_store_url():
    with pytest.raises(ValidationError, match="object_store_url is required"):
        _campaign(
            objective=Objective.APP_PROMOTION,
            adsets=[_adset(
                optimization_goal=OptimizationGoal.APP_INSTALLS,
                destination_type=DestinationType.APP,
                promoted_object=PromotedObject(application_id="111"),
            )],
        )


# ── models: budget and schedule ──────────────────────────────────────────────


def test_budget_below_floor_is_rejected():
    with pytest.raises(ValidationError):
        _adset(daily_budget=MIN_BUDGET_CENTS - 1)


def test_at_most_one_adset_budget_kind():
    # Both set is always wrong. Neither set is now legal at the ad-set level —
    # under Advantage+ campaign budget (CBO) the campaign owns the budget; the
    # "an ad set needs a budget" rule moved to CampaignSpec (see
    # test_meta_spec_builder for the CBO cases).
    with pytest.raises(ValidationError, match="at most one of daily_budget"):
        _adset(daily_budget=5000, lifetime_budget=50000, end_time=END)


def test_lifetime_budget_requires_end_time():
    with pytest.raises(ValidationError, match="lifetime_budget requires an end_time"):
        _adset(daily_budget=None, lifetime_budget=50000)


def test_campaign_lifetime_budget_requires_end_time_on_every_adset():
    """Under CBO the ad set carries no budget of its own, so AdSetSpec's own
    lifetime/end_time rule never fires — the campaign has to check it."""
    with pytest.raises(ValidationError, match="end_time is required with a campaign"):
        _campaign(
            lifetime_budget=50000,
            bid_strategy=BidStrategy.LOWEST_COST_WITHOUT_CAP,
            adsets=[_adset(daily_budget=None, end_time=None)],
        )


def test_cbo_normalizes_a_stale_adset_budget_sharing_flag():
    """ABO-only flag. Rejecting it wedged the editor — the checkbox that clears
    it is hidden under a campaign budget — and it never reaches the wire anyway."""
    spec = _campaign(
        daily_budget=10000,
        bid_strategy=BidStrategy.LOWEST_COST_WITHOUT_CAP,
        is_adset_budget_sharing_enabled=True,
        adsets=[_adset(daily_budget=None)],
    )
    assert spec.is_adset_budget_sharing_enabled is False


def test_end_time_must_follow_start_time():
    with pytest.raises(ValidationError, match="end_time must be after start_time"):
        _adset(end_time=START - timedelta(days=1))


def test_targeting_without_geo_is_rejected():
    """create_adset used to substitute a blanket {"countries": ["US"]} — a
    silent nationwide spend for a neighbourhood campaign."""
    with pytest.raises(ValidationError, match="geo_locations"):
        _adset(targeting={"age_min": 18})


# ── models: bid strategy ─────────────────────────────────────────────────────


def test_cost_cap_requires_bid_amount():
    with pytest.raises(ValidationError, match="requires a bid_amount"):
        _adset(bid_strategy=BidStrategy.COST_CAP)


def test_bid_amount_rejected_without_a_capped_strategy():
    with pytest.raises(ValidationError, match="not accepted with"):
        _adset(bid_strategy=BidStrategy.LOWEST_COST_WITHOUT_CAP, bid_amount=250)


def test_roas_goal_requires_a_floor():
    """The ROAS strategy was selectable with nowhere to put the target, so it
    could never publish: Meta takes it in bid_constraints, not bid_amount."""
    with pytest.raises(ValidationError, match="requires a bid_constraints"):
        _adset(bid_strategy=BidStrategy.LOWEST_COST_WITH_MIN_ROAS)


def test_roas_goal_refuses_a_bid_amount():
    with pytest.raises(ValidationError, match="not accepted with"):
        _adset(bid_strategy=BidStrategy.LOWEST_COST_WITH_MIN_ROAS, bid_amount=250)


def test_roas_floor_rejected_with_any_other_strategy():
    with pytest.raises(ValidationError, match="bid_constraints is only accepted"):
        _adset(bid_constraints=BidConstraints(roas_average_floor=20000))


@pytest.mark.parametrize("floor", [99, 10_000_001])
def test_roas_floor_is_bounded_to_metas_range(floor):
    with pytest.raises(ValidationError):
        BidConstraints(roas_average_floor=floor)


def test_roas_floor_reaches_the_adset_payload():
    """Scaled 10000x on the wire: 30000 means a 3.0x return."""
    payload = _adset(
        bid_strategy=BidStrategy.LOWEST_COST_WITH_MIN_ROAS,
        bid_constraints=BidConstraints(roas_average_floor=30000),
    ).to_payload(campaign_id="c1", ad_account_id="act_1")
    assert payload["bid_constraints"] == {"roas_average_floor": 30000}
    assert "bid_amount" not in payload


# ── models: the goal layer (pairwise rules) ──────────────────────────────────
# Goal and billing / bid strategy used to be checked independently against the
# destination, so a pair that is individually legal and jointly rejected sailed
# through. These are the cases Meta refuses.


def test_billing_event_must_pair_with_the_goal():
    """REACH + THRUPLAY billing: both legal for Awareness → Website, the pair is
    not. This is what independent membership checks could not catch."""
    with pytest.raises(ValidationError, match="cannot be paired with optimization_goal"):
        _campaign(
            objective=Objective.AWARENESS,
            adsets=[_adset(
                optimization_goal=OptimizationGoal.REACH,
                billing_event=BillingEvent.THRUPLAY,
            )],
        )


def test_cost_cap_is_rejected_on_a_frequency_goal():
    """Awareness offers cost cap and REACH; the combination has no cost-per-result
    for Meta to cap."""
    with pytest.raises(ValidationError, match="cannot be paired with optimization_goal"):
        _campaign(
            objective=Objective.AWARENESS,
            adsets=[_adset(
                optimization_goal=OptimizationGoal.REACH,
                bid_strategy=BidStrategy.COST_CAP,
                bid_amount=200,
            )],
        )


def test_roas_strategy_is_rejected_off_the_value_goal():
    """Sales offers the ROAS goal, but Meta only accepts it where it knows what a
    conversion is worth."""
    with pytest.raises(ValidationError, match="cannot be paired with optimization_goal"):
        _campaign(
            objective=Objective.SALES,
            adsets=[_adset(
                optimization_goal=OptimizationGoal.LINK_CLICKS,
                billing_event=BillingEvent.LINK_CLICKS,
                bid_strategy=BidStrategy.LOWEST_COST_WITH_MIN_ROAS,
                bid_constraints=BidConstraints(roas_average_floor=30000),
                ads=[AdSpec(name="Ad", creative=_creative(
                    call_to_action=CallToAction.SHOP_NOW
                ))],
            )],
        )


# ── models: the goal layer (media kind) ──────────────────────────────────────


def _video_goal_campaign(**creative_kwargs) -> CampaignSpec:
    """Engagement → On your video, whose default goal is ThruPlay."""
    return _campaign(
        objective=Objective.ENGAGEMENT,
        adsets=[_adset(
            optimization_goal=OptimizationGoal.THRUPLAY,
            billing_event=BillingEvent.IMPRESSIONS,
            destination_type=DestinationType.ON_VIDEO,
            ads=[AdSpec(name="Ad", creative=_creative(
                call_to_action=CallToAction.WATCH_MORE,
                object_story_id="1234_5678",
                **creative_kwargs
            ))],
        )],
    )


def test_thruplay_rejects_an_image():
    """The reported bug: a video goal accepted an image ad, then ran something
    Meta could not optimize."""
    with pytest.raises(ValidationError, match="needs a video, not an image"):
        _video_goal_campaign(image_hash="abc")


def test_thruplay_accepts_a_video():
    spec = _video_goal_campaign(video_id="v1")
    assert spec.adsets[0].ads[0].creative.media_kind == "video"


def test_thruplay_allows_a_plan_with_no_media_yet():
    """A freshly built plan carries no media — the user attaches it in the editor.
    Refusing to build it would leave them nothing to attach media to; publish
    re-checks the real file type."""
    assert _video_goal_campaign().adsets[0].optimization_goal is OptimizationGoal.THRUPLAY


def test_thruplay_rejects_a_carousel():
    """ThruPlay publishes as a single `video_data` creative, which a carousel
    cannot be."""
    with pytest.raises(ValidationError, match="cannot be used with optimization_goal"):
        _campaign(
            objective=Objective.AWARENESS,
            adsets=[_adset(
                optimization_goal=OptimizationGoal.THRUPLAY,
                ads=[AdSpec(name="Ad", creative=_creative(
                    format=AdFormat.CAROUSEL, cards=_cards(3)
                ))],
            )],
        )


def test_media_kind_follows_a_post_upload_reference():
    """image_hash / video_id say what the asset is outright — a stale hint from
    the editor must not override them."""
    assert _creative(image_hash="h", media_kind="video").media_kind == "image"
    assert _creative(video_id="v", media_kind="image").media_kind == "video"


def test_attribution_window_needs_a_conversion_goal():
    with pytest.raises(ValidationError, match="attribution_spec needs a conversion"):
        _campaign(
            objective=Objective.AWARENESS,
            adsets=[_adset(
                optimization_goal=OptimizationGoal.REACH,
                attribution_spec=[
                    AttributionWindow(event_type="CLICK_THROUGH", window_days=7)
                ],
            )],
        )


def test_engage_through_is_a_one_day_window():
    """Ads Manager's third attribution row. ENGAGED_VIDEO_VIEW is its wire name and
    1 day is the only length Meta offers — 7 belongs to click-through alone."""
    assert AttributionWindow(
        event_type="ENGAGED_VIDEO_VIEW", window_days=1
    ).window_days == 1
    with pytest.raises(ValidationError, match="ENGAGED_VIDEO_VIEW window_days"):
        AttributionWindow(event_type="ENGAGED_VIDEO_VIEW", window_days=7)


def test_attribution_off_is_an_absent_entry_not_a_zero_day_window():
    """0 is our sentinel so the editor's selects can offer "Off". Meta's list
    carries what is ENABLED, so a 0-day entry must never reach the wire."""
    payload = _adset(
        optimization_goal=OptimizationGoal.OFFSITE_CONVERSIONS,
        attribution_spec=[
            AttributionWindow(event_type="CLICK_THROUGH", window_days=7),
            AttributionWindow(event_type="ENGAGED_VIDEO_VIEW", window_days=0),
            AttributionWindow(event_type="VIEW_THROUGH", window_days=1),
        ],
    ).to_payload(campaign_id="c1", ad_account_id="act_1")
    assert payload["attribution_spec"] == [
        {"event_type": "CLICK_THROUGH", "window_days": 7},
        {"event_type": "VIEW_THROUGH", "window_days": 1},
    ]

    all_off = _adset(
        optimization_goal=OptimizationGoal.OFFSITE_CONVERSIONS,
        attribution_spec=[
            AttributionWindow(event_type="VIEW_THROUGH", window_days=0),
        ],
    ).to_payload(campaign_id="c1", ad_account_id="act_1")
    assert "attribution_spec" not in all_off


def test_editor_catalog_ships_three_windows_and_metas_default():
    """The editor shows the default rather than blanks; it does NOT write it, so
    an untouched ad set keeps following whatever Meta's own default is."""
    attribution = build_editor_catalog(Objective.SALES)["attribution"]
    assert attribution["click_windows"] == [1, 7]
    assert attribution["engaged_view_windows"] == [0, 1]
    assert attribution["default"] == [
        {"event_type": "CLICK_THROUGH", "window_days": 7},
        {"event_type": "ENGAGED_VIDEO_VIEW", "window_days": 1},
        {"event_type": "VIEW_THROUGH", "window_days": 1},
    ]


def test_frequency_cap_is_allowed_on_thruplay_too():
    """Meta accepts a frequency cap on REACH and THRUPLAY. Hardcoding REACH
    rejected a combination Meta allows."""
    spec = _video_goal_campaign()
    assert spec  # sanity: the fixture builds
    ok = _campaign(
        objective=Objective.AWARENESS,
        adsets=[_adset(
            optimization_goal=OptimizationGoal.THRUPLAY,
            frequency_control_specs=[FrequencyControlSpec(interval_days=7, max_frequency=3)],
        )],
    )
    assert ok.adsets[0].frequency_control_specs[0].max_frequency == 3


# ── models: budget scheduling vs ad scheduling ───────────────────────────────
# The two are opposites and each belongs to one budget kind. The editor used to
# offer dayparting regardless and only error after submit, and had no way to
# express a temporary budget increase at all.


def _schedule(**overrides) -> BudgetScheduleSpec:
    base = dict(
        time_start=START + timedelta(days=1),
        time_end=START + timedelta(days=3),
        budget_value=200,               # 2x, scaled 100x
        budget_value_type="MULTIPLIER",
    )
    base.update(overrides)
    return BudgetScheduleSpec(**base)


def test_budget_schedule_reaches_the_adset_payload():
    """The window goes out as Unix seconds, not ISO like every other datetime
    here: these entries are HighDemandPeriod objects, and the SDK types
    ``POST /{id}/budget_schedules`` with ``'time_start': 'unsigned int'``."""
    from datetime import datetime, timezone

    payload = _adset(budget_schedule_specs=[_schedule()]).to_payload(
        campaign_id="c1", ad_account_id="act_1"
    )
    entry = payload["budget_schedule_specs"][0]
    assert entry["budget_value"] == 200
    assert entry["budget_value_type"] == "MULTIPLIER"
    assert isinstance(entry["time_start"], int)
    assert (
        datetime.fromtimestamp(entry["time_start"], tz=timezone.utc)
        .strftime("%Y-%m-%d")
        == "2026-08-02"
    )


def test_budget_schedule_window_must_be_ordered():
    with pytest.raises(ValidationError, match="time_end must be after time_start"):
        _schedule(time_end=START)


def test_budget_schedule_multiplier_is_capped_at_metas_ceiling():
    """Meta will not raise a scheduled budget past 8x the daily budget."""
    with pytest.raises(ValidationError, match="cannot exceed 8x"):
        _schedule(budget_value=900)


def test_budget_schedule_is_rejected_on_a_lifetime_budget():
    """A lifetime budget is already spread across the run — the daily-budget
    boost has nothing to boost."""
    with pytest.raises(ValidationError, match="applies to a daily budget"):
        _campaign(adsets=[_adset(
            daily_budget=None,
            lifetime_budget=50000,
            end_time=END,
            budget_schedule_specs=[_schedule()],
        )])


def test_dayparting_is_rejected_on_a_daily_budget():
    with pytest.raises(ValidationError, match="requires a lifetime budget"):
        _campaign(adsets=[_adset(
            adset_schedule=[DayPartSpec(days=[1], start_minute=540, end_minute=1020)]
        )])


def test_budget_schedule_is_rejected_on_an_adset_under_a_campaign_budget():
    """Budget scheduling raises *a budget*, and under a campaign (Advantage+)
    budget the ad set has none — to_payload strips it. The window has to ride on
    the campaign, which is what holds the money."""
    with pytest.raises(ValidationError, match="cannot be set under an Advantage"):
        _campaign(
            daily_budget=100_00,
            bid_strategy=BidStrategy.LOWEST_COST_WITHOUT_CAP,
            adsets=[_adset(daily_budget=None, budget_schedule_specs=[_schedule()])],
        )


def test_budget_schedule_on_the_campaign_is_accepted_under_a_campaign_budget():
    """The counterpart: the same window, on the level that owns the budget."""
    spec = _campaign(
        daily_budget=100_00,
        bid_strategy=BidStrategy.LOWEST_COST_WITHOUT_CAP,
        budget_schedule_specs=[_schedule()],
        adsets=[_adset(daily_budget=None)],
    )
    payload = spec.to_payload()
    assert payload["budget_schedule_specs"][0]["budget_value"] == 200


# ── models: placements ───────────────────────────────────────────────────────
# _targeting_placements_valid guards the most free-form thing the editor sends:
# raw platform and position strings. It had no test at all.


def _placement_targeting(**keys) -> dict:
    return {**GEO, **keys}


def test_absent_placement_keys_mean_advantage_plus():
    """Omitting every key is how Advantage+ placements are expressed — not a
    missing value to be defaulted."""
    aset = _adset(targeting=_placement_targeting())
    payload = aset.to_payload(campaign_id="c1", ad_account_id="act_1")
    assert "publisher_platforms" not in payload["targeting"]


def test_manual_placements_reach_the_adset_payload():
    aset = _adset(targeting=_placement_targeting(
        publisher_platforms=["facebook", "instagram"],
        facebook_positions=["feed", "story"],
        instagram_positions=["reels"],
    ))
    targeting = aset.to_payload(campaign_id="c1", ad_account_id="act_1")["targeting"]
    assert targeting["publisher_platforms"] == ["facebook", "instagram"]
    assert targeting["facebook_positions"] == ["feed", "story"]
    assert targeting["instagram_positions"] == ["reels"]


def test_an_unknown_publisher_platform_is_rejected():
    with pytest.raises(ValidationError, match="unknown publisher_platforms"):
        _adset(targeting=_placement_targeting(publisher_platforms=["tiktok"]))


def test_positions_without_their_platform_are_rejected():
    """The editor bug this guards: deselecting a platform left its positions key
    behind, and Meta rejects the pair with an opaque error."""
    with pytest.raises(ValidationError, match="facebook_positions requires"):
        _adset(targeting=_placement_targeting(
            publisher_platforms=["instagram"], facebook_positions=["feed"],
        ))


def test_positions_with_no_platform_list_at_all_are_rejected():
    with pytest.raises(ValidationError, match="facebook_positions requires"):
        _adset(targeting=_placement_targeting(facebook_positions=["feed"]))


def test_an_unknown_position_value_is_rejected():
    with pytest.raises(ValidationError, match="unknown instagram_positions"):
        _adset(targeting=_placement_targeting(
            publisher_platforms=["instagram"], instagram_positions=["carousel"],
        ))


# ── models: special ad category country ──────────────────────────────────────


def test_special_ad_category_without_a_country_is_rejected():
    """Meta requires the pair. We never sent the country, so every regulated
    campaign failed at create with an error the user could not act on."""
    with pytest.raises(ValidationError, match="special_ad_category_country is required"):
        _campaign(special_ad_categories=[SpecialAdCategory.HOUSING])


def test_country_without_a_category_is_rejected():
    with pytest.raises(ValidationError, match="only used with a special ad category"):
        _campaign(special_ad_category_country=["US"])


def test_country_must_be_a_two_letter_code():
    with pytest.raises(ValidationError, match="two-letter country codes"):
        _campaign(
            special_ad_categories=[SpecialAdCategory.HOUSING],
            special_ad_category_country=["United States"],
        )


# ── models: creative limits ──────────────────────────────────────────────────


def test_recommended_length_is_guidance_not_a_wall():
    """40/125/30 are Meta's design guidance — the feed's truncation point — not
    API limits. Ads Manager warns and publishes anyway, so we accept them too."""
    assert _creative(title="x" * 80).title == "x" * 80
    assert _creative(body="x" * 400).body == "x" * 400
    assert _creative(description="x" * 90).description == "x" * 90


def test_over_long_copy_is_an_error_not_a_truncation():
    """Past the hard ceiling it is a validation error the user can see and fix.
    meta_ads used to slice instead, so the user approved one headline and Meta
    ran another."""
    with pytest.raises(ValidationError):
        _creative(title="x" * (CREATIVE_TITLE_MAX + 1))
    with pytest.raises(ValidationError):
        _creative(body="x" * (CREATIVE_BODY_MAX + 1))
    with pytest.raises(ValidationError):
        _creative(description="x" * (CREATIVE_DESCRIPTION_MAX + 1))


def test_relative_link_is_rejected():
    with pytest.raises(ValidationError, match="absolute http"):
        _creative(link="/landing")


def test_a_single_label_host_is_rejected():
    """Shape only — whether the domain resolves is checked before publish, not
    here, because nothing separates a typo'd host from a real one by inspection."""
    with pytest.raises(ValidationError, match="no domain ending"):
        _creative(link="https://emptyadccom")
    with pytest.raises(ValidationError, match="spaces"):
        _creative(link="https://example .com")
    # The shapes that must keep working.
    for good in (
        "https://example.com",
        "http://shop.example.co.uk/landing?utm=1",
        "https://apps.apple.com/app/id1",
        "https://api.whatsapp.com/send",
    ):
        assert _creative(link=good).link == good


# ── models: ad format ────────────────────────────────────────────────────────


def _cards(n: int) -> list[CarouselCard]:
    # Each card carries its own media — a media-less card is its own error now.
    return [
        CarouselCard(title=f"Card {i}", link="https://example.com", image_hash=f"h{i}")
        for i in range(n)
    ]


def test_a_carousel_card_without_media_is_rejected():
    """Publish used to send image_hash: None for a blank card, or drop the whole
    ad with only a line in the thinking stream. Both are worse than a form error
    next to the empty card."""
    with pytest.raises(ValidationError, match="needs an image or video"):
        CarouselCard(title="Card", link="https://example.com")


@pytest.mark.parametrize("count", [0, 1, 11])
def test_carousel_card_count_is_bounded(count):
    with pytest.raises(ValidationError, match="carousel needs between"):
        _creative(format=AdFormat.CAROUSEL, cards=_cards(count) or None)


def test_carousel_media_lives_on_the_cards():
    with pytest.raises(ValidationError, match="on each card"):
        _creative(format=AdFormat.CAROUSEL, cards=_cards(3), image_hash="abc")


def test_cards_are_rejected_on_a_single_image_ad():
    with pytest.raises(ValidationError, match="only accepted on a carousel"):
        _creative(cards=_cards(3))


def test_format_not_offered_by_the_destination_is_rejected():
    """Messenger renders one card. Offering a carousel there is an option the
    user can pick and never publish."""
    with pytest.raises(ValidationError, match="format CAROUSEL is not available"):
        _campaign(
            objective=Objective.TRAFFIC,
            adsets=[_adset(
                optimization_goal=OptimizationGoal.LINK_CLICKS,
                destination_type=DestinationType.MESSENGER,
                ads=[AdSpec(name="Ad", creative=_creative(
                    call_to_action=CallToAction.MESSAGE_PAGE,
                    format=AdFormat.CAROUSEL,
                    cards=_cards(3),
                ))],
            )],
        )


# ── models: boosted posts ────────────────────────────────────────────────────
# "On your post / video / event" promote something that already exists on the
# Page. We used to compose a brand-new creative for them, which loses the post
# being boosted entirely.


def _boost_campaign(**creative_kwargs) -> CampaignSpec:
    return _campaign(
        objective=Objective.ENGAGEMENT,
        adsets=[_adset(
            optimization_goal=OptimizationGoal.POST_ENGAGEMENT,
            destination_type=DestinationType.ON_POST,
            ads=[AdSpec(name="Ad", creative=_creative(**creative_kwargs))],
        )],
    )


def test_boost_destination_requires_a_post():
    with pytest.raises(ValidationError, match="object_story_id is required"):
        _boost_campaign()


def test_boost_destination_accepts_a_post():
    spec = _boost_campaign(object_story_id="1234_5678")
    assert spec.adsets[0].ads[0].creative.object_story_id == "1234_5678"


def test_a_post_id_is_rejected_on_a_composed_ad():
    """A website ad composes its own creative — pointing it at a Page post would
    silently replace everything the user wrote."""
    with pytest.raises(ValidationError, match="only used when the ad promotes"):
        _campaign(
            objective=Objective.TRAFFIC,
            adsets=[_adset(
                optimization_goal=OptimizationGoal.LINK_CLICKS,
                ads=[AdSpec(name="Ad", creative=_creative(object_story_id="1_2"))],
            )],
        )


# ── models: instant form ─────────────────────────────────────────────────────


def test_instant_form_destination_may_defer_the_form_to_publish():
    """A null form id means "create one for me" — publish builds it against the
    finished campaign (executors/media._resolve_lead_form). Rejecting it here made
    the spec unbuildable for the intake default."""
    spec = _campaign(
        objective=Objective.LEADS,
        adsets=[_adset(
            optimization_goal=OptimizationGoal.LEAD_GENERATION,
            destination_type=DestinationType.ON_AD,
            promoted_object=PromotedObject(page_id="1"),
            ads=[AdSpec(name="Ad", creative=_creative(call_to_action=CallToAction.SIGN_UP))],
        )],
    )
    assert spec.adsets[0].ads[0].creative.lead_gen_form_id is None


def test_lead_form_on_a_non_instant_form_destination_is_rejected():
    with pytest.raises(ValidationError, match="only used when the conversion location"):
        _campaign(
            objective=Objective.SALES,
            adsets=[_adset(
                optimization_goal=OptimizationGoal.LINK_CLICKS,
                ads=[AdSpec(name="Ad", creative=_creative(
                    call_to_action=CallToAction.SHOP_NOW, lead_gen_form_id="form-1",
                ))],
            )],
        )


# ── labels ───────────────────────────────────────────────────────────────────


def test_labels_match_ads_manager_not_the_raw_enum():
    """Users compare our dropdowns against Ads Manager side by side. Title-casing
    the enum invents vocabulary Meta does not use."""
    assert meta_label("OFFSITE_CONVERSIONS") == "Conversions"
    assert meta_label("ON_AD") == "Instant forms"
    assert meta_label("THRUPLAY") == "ThruPlay"
    assert meta_label("SHOP_AUTOMATIC") == "Shop"
    # Unmapped values still get a readable fallback.
    assert meta_label("APP_INSTALLS") == "App installs"


# ── models: special ad categories ────────────────────────────────────────────


def test_special_category_forbids_gender_targeting():
    with pytest.raises(ValidationError, match="genders must be empty"):
        _campaign(
            special_ad_categories=[SpecialAdCategory.HOUSING],
            special_ad_category_country=["US"],
            adsets=[_adset(targeting={**GEO, "genders": [1]})],
        )


def test_special_category_forbids_narrowed_age():
    with pytest.raises(ValidationError, match="age range must stay 18-65"):
        _campaign(
            special_ad_categories=[SpecialAdCategory.EMPLOYMENT],
            special_ad_category_country=["US"],
            adsets=[_adset(targeting={**GEO, "age_min": 25})],
        )


def test_financial_products_strips_demographics_now_that_credit_folds_into_it():
    """This category used to target normally. Credit no longer has a category of
    its own, so credit ads declare here — and they carry credit's restriction
    with them. Over-restricting costs reach; under-restricting costs the account."""
    with pytest.raises(ValidationError, match="genders must be empty"):
        _campaign(
            special_ad_categories=[SpecialAdCategory.FINANCIAL_PRODUCTS_SERVICES],
            special_ad_category_country=["US"],
            adsets=[_adset(targeting={**GEO, "age_min": 21, "genders": [1]})],
        )


def test_no_category_still_allows_demographics():
    """The restriction is the category's, not a blanket one."""
    spec = _campaign(adsets=[_adset(targeting={**GEO, "age_min": 21, "genders": [1]})])
    assert spec.adsets[0].targeting["genders"] == [1]


def test_categories_needing_meta_approval_are_not_offered():
    """Political ads need per-advertiser authorization and gambling needs written
    permission from Meta. Declaring either from here produces a campaign that
    fails review, so neither is in the enum."""
    offered = {c.value for c in SpecialAdCategory}
    assert "ISSUES_ELECTIONS_POLITICS" not in offered
    assert "ONLINE_GAMBLING_AND_GAMING" not in offered


def test_credit_is_not_offered_as_its_own_category():
    """The SDK still carries CREDIT, but Ads Manager dropped it — credit ads
    declare under Financial products and services. Offering it would show a
    choice the user's own Ads Manager does not have."""
    offered = {c.value for c in SpecialAdCategory}
    assert "CREDIT" not in offered
    assert "FINANCIAL_PRODUCTS_SERVICES" in offered
    # ...and it inherits credit's targeting restrictions.
    assert "FINANCIAL_PRODUCTS_SERVICES" in CATEGORIES_BLOCKING_DEMOGRAPHICS


@pytest.mark.parametrize(
    "text,expected",
    [
        ("We sell artisan coffee beans", []),
        ("Apartments for rent downtown", [SpecialAdCategory.HOUSING]),
        ("We're hiring full-time position", [SpecialAdCategory.EMPLOYMENT]),
        # Credit is not its own category any more — Ads Manager declares credit
        # ads under Financial products and services.
        ("Compare credit card offers", [SpecialAdCategory.FINANCIAL_PRODUCTS_SERVICES]),
        ("Refinance your home loan", [SpecialAdCategory.FINANCIAL_PRODUCTS_SERVICES]),
        # Gambling and politics are no longer detected: the category exists at
        # Meta but needs an approval we cannot get for the user.
        ("Online casino with sports betting", []),
        ("Vote for our candidate for mayor", []),
        ("", []),
        (None, []),
    ],
)
def test_detect_special_ad_categories(text, expected):
    assert detect_special_ad_categories(business_desc=text) == expected


# ── models: strictness and payloads ──────────────────────────────────────────


def test_unknown_field_is_rejected():
    """extra='forbid' is what stops a plan carrying fields that never reach
    Meta — the old extra='allow' model let per-ad-set budgets be displayed and
    then dropped."""
    with pytest.raises(ValidationError):
        _adset(hallucinated_field="oops")


def test_campaign_needs_at_least_one_adset():
    with pytest.raises(ValidationError):
        _campaign(adsets=[])


def test_campaign_payload_shape():
    spec = _campaign(
        special_ad_categories=[SpecialAdCategory.HOUSING],
        special_ad_category_country=["us"],   # normalized to upper on the wire
    )
    payload = spec.to_payload()
    assert payload == {
        "name": "Test Campaign",
        "objective": "OUTCOME_AWARENESS",
        "status": "PAUSED",
        "buying_type": "AUCTION",
        "special_ad_categories": ["HOUSING"],
        "special_ad_category_country": ["US"],
        # ABO campaign — Meta requires an explicit answer on ad set budget sharing.
        "is_adset_budget_sharing_enabled": False,
    }


def test_no_special_category_sends_empty_list_not_none_sentinel():
    assert _campaign().to_payload()["special_ad_categories"] == []


def test_adset_payload_carries_its_own_budget():
    """The regression that motivated this package: publish passed the same
    budget to every ad set, discarding the plan's split."""
    spec = _campaign(adsets=[
        _adset(name="Seed", daily_budget=7000),
        _adset(name="Prospecting", daily_budget=3000),
    ])
    payloads = [a.to_payload(campaign_id="c1", ad_account_id="act_1") for a in spec.adsets]
    assert [p["daily_budget"] for p in payloads] == [7000, 3000]
    assert spec.total_budget_cents() == 10000


def test_adset_payload_omits_absent_optionals():
    payload = _adset().to_payload(campaign_id="c1", ad_account_id="act_1")
    for absent in ("end_time", "lifetime_budget", "promoted_object", "bid_amount"):
        assert absent not in payload
    # destination_type is no longer optional — it always reaches Meta.
    assert payload["destination_type"] == "WEBSITE"
    assert payload["start_time"].startswith("2026-08-01T00:00:00")


def test_naive_start_time_is_treated_as_utc():
    payload = _adset(start_time=datetime(2026, 8, 1)).to_payload(
        campaign_id="c1", ad_account_id="act_1"
    )
    assert payload["start_time"].endswith("+00:00")


# ── matrix vs measured truth ─────────────────────────────────────────────────
# Every test above checks the matrix against itself. These check it against Meta.
#
# ``scripts/probe_meta_matrix.py`` walks the combination space with
# ``validate_only`` and writes what Meta accepted to
# ``tests/data/meta_matrix_probe.json``. Holding OBJECTIVE_MATRIX to that file is
# what stops a rule we invented from documentation — or one Meta changed without
# telling anyone — from surviving in the dropdowns.
#
# Skipped until the file exists: generating it needs a real ad account, and a
# fresh clone must not fail for want of Meta credentials.

PROBE_PATH = Path(__file__).parent / "data" / "meta_matrix_probe.json"


def _load_probe() -> dict | None:
    try:
        return json.loads(PROBE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


PROBE = _load_probe()

requires_probe = pytest.mark.skipif(
    PROBE is None,
    reason=(
        "no tests/data/meta_matrix_probe.json — run scripts/probe_meta_matrix.py "
        "against a real ad account to generate it"
    ),
)

# Parametrization is driven by the matrix, which is always importable, so
# collection works with or without the probe file.
_OFFERED = [
    (obj, dest)
    for obj, rules in OBJECTIVE_MATRIX.items()
    for dest in rules.destinations
]


def _probed(section: str, objective: Objective) -> dict | list | None:
    """One objective's slice of a probe section, or None if it was never probed.

    An objective absent from the file is not a failure — the probe runs per
    objective and can legitimately be partial.
    """
    return (PROBE or {}).get(section, {}).get(objective.value)


@requires_probe
@pytest.mark.parametrize("objective,dest", _OFFERED, ids=lambda v: getattr(v, "value", None) or getattr(v, "label", ""))
def test_offered_goals_are_accepted_by_meta(objective, dest):
    """Every optimization goal the catalog offers for a conversion location has
    to be one Meta accepted there. An option the user can pick but not publish is
    worse than no option at all."""
    by_dest = _probed("goals_by_objective_destination", objective)
    if by_dest is None or dest.destination_type.value not in by_dest:
        pytest.skip(f"{objective.value} → {dest.destination_type.value} not probed")
    if dest.omit_destination_type:
        # The probe always sends destination_type; we deliberately do not for
        # this conversion location. Its measurement describes a payload we never
        # build, so asserting against it compares the wrong two things — see
        # DestinationRules.omit_destination_type.
        pytest.skip(
            f"{objective.value} → {dest.destination_type.value} is published "
            "without destination_type; the probe measures it with"
        )

    accepted = set(by_dest[dest.destination_type.value])
    # A destination whose every "yes" was account-gated measured nothing. Sales →
    # App on an account with no registered app is the case: the only goal that
    # got through was DERIVED_EVENTS, and only because a missing pixel is bucketed
    # as gated. Asserting against that would delete a real conversion location on
    # the evidence of a prerequisite this account happens to lack.
    gated_goals = {
        key.rsplit("goal=", 1)[-1]
        for key in (PROBE.get("account_gated") or {})
        if f"{objective.value}|dest={dest.destination_type.value}|goal=" in key
    } | {
        key.rsplit("goal=", 1)[-1].split("|")[0]
        for key in (PROBE.get("account_gated") or {})
        if key.startswith(f"{objective.value}|goal=")
    }
    if accepted and accepted <= gated_goals:
        pytest.skip(
            f"{objective.value} → {dest.destination_type.value}: every accepted "
            f"goal was account-gated ({sorted(accepted)}), so nothing was measured"
        )

    offered = {g.value for g in dest.optimization_goals}
    assert offered <= accepted, (
        f"{objective.value} → {dest.label} offers goals Meta rejected: "
        f"{sorted(offered - accepted)}"
    )


@requires_probe
@pytest.mark.parametrize("objective,dest", _OFFERED, ids=lambda v: getattr(v, "value", None) or getattr(v, "label", ""))
def test_offered_billing_events_pair_with_each_goal(objective, dest):
    """The pairwise rule the two-axis matrix cannot express: we validate goal and
    billing event independently, so a pair that is individually legal and jointly
    rejected (REACH + THRUPLAY billing) passes our own validation today."""
    billing_by_goal = _probed("billing_by_goal", objective)
    if not billing_by_goal:
        pytest.skip(f"{objective.value} billing events not probed")

    dest_billing = {e.value for e in dest.billing_events}
    for goal in dest.optimization_goals:
        accepted = billing_by_goal.get(goal.value)
        if accepted is None:
            continue
        # What the editor actually offers is the intersection of the two layers
        # (``_goal_rules_payload`` in catalog.py) — asserting the destination
        # list alone fails on pairs the cascade already removes.
        offered_billing = dest_billing & {e.value for e in goal_rules(goal).billing_events}
        assert offered_billing <= set(accepted), (
            f"{objective.value} → {dest.label} offers billing events Meta rejects "
            f"with goal {goal.value}: {sorted(offered_billing - set(accepted))}"
        )


@requires_probe
@pytest.mark.parametrize("objective", list(Objective), ids=lambda o: o.value)
def test_offered_bid_strategies_pair_with_each_goal(objective):
    """Bid strategy is validated at objective level only, but Meta decides it
    against the goal — COST_CAP on a REACH ad set is the shipped example."""
    bids_by_goal = _probed("bid_strategies_by_goal", objective)
    if not bids_by_goal:
        pytest.skip(f"{objective.value} bid strategies not probed")

    rules = OBJECTIVE_MATRIX[objective]
    obj_bids = {s.value for s in rules.bid_strategies}
    for dest in rules.destinations:
        for goal in dest.optimization_goals:
            accepted = bids_by_goal.get(goal.value)
            if accepted is None:
                continue
            # Objective ∩ goal — the same cascade the editor applies. COST_CAP is
            # offered by Awareness and removed by every Awareness goal.
            offered = obj_bids & {s.value for s in goal_rules(goal).bid_strategies}
            assert offered <= set(accepted), (
                f"{objective.value} offers bid strategies Meta rejects with goal "
                f"{goal.value}: {sorted(offered - set(accepted))}"
            )


@requires_probe
@pytest.mark.parametrize("objective,dest", _OFFERED, ids=lambda v: getattr(v, "value", None) or getattr(v, "label", ""))
def test_existing_post_is_only_offered_where_meta_accepts_it(objective, dest):
    """``allows_existing_post`` must never be ahead of the measurement.

    Offering "promote one of my posts" where Meta rejects an ``object_story_id``
    creative fails the AD — after the campaign and ad set already exist, which is
    the expensive half of a publish. The flag therefore defaults to False and only
    moves once stage 7 of the probe (``--existing-post``) says the pair works.
    """
    by_dest = _probed("existing_post_by_objective_destination", objective)
    if by_dest is None or dest.destination_type.value not in by_dest:
        pytest.skip(
            f"{objective.value} → {dest.destination_type.value} existing-post not "
            "probed — run scripts/probe_meta_matrix.py --existing-post"
        )
    if dest.allows_existing_post:
        assert by_dest[dest.destination_type.value], (
            f"{objective.value} → {dest.destination_type.value} offers an existing "
            "post, but Meta rejected an object_story_id creative there"
        )


@requires_probe
def test_probe_was_taken_against_the_installed_sdk():
    """A probe recorded against a different API version describes rules that may
    no longer hold, so treat it as stale rather than as evidence."""
    assert PROBE.get("api_version") == settings.META_API_VERSION, (
        "meta_matrix_probe.json was recorded against API "
        f"{PROBE.get('api_version')}, but settings.META_API_VERSION is "
        f"{settings.META_API_VERSION} — re-run scripts/probe_meta_matrix.py"
    )
    assert PROBE.get("sdk_version") == facebook_business.__version__, (
        "meta_matrix_probe.json predates the installed facebook_business "
        f"{facebook_business.__version__} — re-run scripts/probe_meta_matrix.py"
    )


# ── Ads-Manager parity: what the ad set form actually offers ──────────────────


def test_awareness_and_app_promotion_have_no_conversion_location_choice():
    """Ads Manager shows no conversion location on an Awareness or an App
    promotion ad set. The editor hides a single-destination select, so "exactly
    one destination" is how that absence is expressed — offering Website vs
    "On your ad" under Awareness invented a choice Meta never asks for."""
    for objective in (Objective.AWARENESS, Objective.APP_PROMOTION):
        assert len(matrix_for(objective).destinations) == 1, (
            f"{objective.value} must offer exactly one conversion location"
        )


def test_app_promotion_optimizes_for_installs_only():
    """Link clicks / app events / value all optimize for something that happens
    after the install and need the Meta SDK reporting in-app events — a
    prerequisite we never collect. Offering them built ad sets Meta accepts and
    then cannot deliver against."""
    app = matrix_for(Objective.APP_PROMOTION).default_destination
    assert app.optimization_goals == (OptimizationGoal.APP_INSTALLS,)
    assert app.promoted_object_kind(OptimizationGoal.APP_INSTALLS) == PROMOTED_APPLICATION
    # Billing must still be legal with the one goal that survives.
    assert set(app.billing_events) <= set(
        goal_rules(OptimizationGoal.APP_INSTALLS).billing_events
    )


def test_frequency_capped_goals_open_with_a_default_not_a_blank_pair():
    """Every other field in the plan editor arrives filled in, so two empty
    boxes read as a broken field rather than as "no cap"."""
    assert FREQUENCY_DEFAULT_MAX >= 1
    assert 1 <= FREQUENCY_DEFAULT_INTERVAL_DAYS <= FREQUENCY_MAX_INTERVAL_DAYS
    # The default has to be a spec Meta (and FrequencyControlSpec) accepts.
    FrequencyControlSpec(
        event="IMPRESSIONS",
        interval_days=FREQUENCY_DEFAULT_INTERVAL_DAYS,
        max_frequency=FREQUENCY_DEFAULT_MAX,
    )
