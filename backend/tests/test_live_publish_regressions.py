"""Rules Meta enforces that the matrix and the wire payload used to miss.

Every case here is a real rejection observed by ``scripts/live_publish_matrix.py``
publishing to a live ad account — each one produced a plan the product accepted
and Meta refused. Several failed *after* the campaign and ad set already existed,
because the two-stage preflight only validates campaign and ad-set payloads:
creatives are never pre-validated, and an ad-set rule that needs a sibling or an
attached ad cannot fire while the campaign is still empty.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.graph.meta_spec.enums import (
    BidStrategy,
    BillingEvent,
    CallToAction,
    DestinationType,
    Objective,
    OptimizationGoal,
)
from app.graph.meta_spec.models import (
    BudgetScheduleSpec,
    DayPartSpec,
    min_budget_cents,
)
from app.graph.meta_spec.objective_matrix import (
    OBJECTIVE_MATRIX,
    PROMOTED_APPLICATION,
    goal_rules,
    matrix_for,
    rules_for,
)

from tests.test_meta_spec_matrix import _adset, _campaign

_PAGE = {"page_id": "pg_1"}


def _payload(**overrides):
    return _adset(**overrides).to_payload(campaign_id="c1", ad_account_id="act_1")


# ── targeting keys Meta demands but nobody picks ─────────────────────────────


def test_advantage_audience_is_always_stated():
    """Meta: "you need to enable or disable the Advantage audience feature…
    setting the advantage_audience flag to either 1 or 0". A broad ad set — the
    default role, and what publishing without an audience produces — carried no
    targeting_automation at all, so ZIP-targeted ad sets were rejected."""
    assert _payload()["targeting"]["targeting_automation"]["advantage_audience"] == 0


def test_an_explicit_advantage_audience_choice_is_kept():
    targeting = {
        "geo_locations": {"countries": ["US"]},
        "targeting_automation": {"advantage_audience": 1},
    }
    payload = _payload(targeting=targeting)
    assert payload["targeting"]["targeting_automation"]["advantage_audience"] == 1


def test_advantage_audience_drops_the_maximum_age():
    """Meta: "You can add a lower maximum age as a suggestion instead when
    creating or editing an ad set." Advantage+ audience refuses an age_max, and
    a lookalike ad set — or any seed that degrades in bind_audiences — carries
    both, so the whole publish failed before anything was created."""
    targeting = {
        "geo_locations": {"countries": ["US"]},
        "targeting_automation": {"advantage_audience": 1},
        "age_min": 18,
        "age_max": 35,
    }
    payload = _payload(targeting=targeting)
    assert "age_max" not in payload["targeting"]
    assert payload["targeting"]["age_min"] == 18


def test_age_max_survives_without_advantage_audience():
    payload = _payload(targeting={"geo_locations": {"countries": ["US"]}, "age_max": 35})
    assert payload["targeting"]["age_max"] == 35


def test_page_likes_excludes_people_who_already_like_the_page():
    """Meta refuses a PAGE_LIKES ad set that can serve to people who have already
    converted, and a Page like can only happen once."""
    payload = _payload(
        destination_type=DestinationType.ON_PAGE,
        optimization_goal=OptimizationGoal.PAGE_LIKES,
        promoted_object=_PAGE,
    )
    assert payload["targeting"]["excluded_connections"] == [{"id": "pg_1"}]


def test_other_goals_do_not_exclude_connections():
    assert "excluded_connections" not in _payload()["targeting"]


# ── wire fields with a required companion ────────────────────────────────────


def test_dayparting_sends_its_pacing_type():
    """Meta: "This pacing requires a campaign with not day parting". Ad
    scheduling was fully modelled and could never publish without this."""
    payload = _payload(
        daily_budget=None,
        lifetime_budget=50000,
        end_time="2026-09-01T00:00:00+00:00",
        adset_schedule=[DayPartSpec(days=[1, 2], start_minute=540, end_minute=1080)],
    )
    assert payload["pacing_type"] == ["day_parting"]


def test_no_pacing_type_without_dayparting():
    assert "pacing_type" not in _payload()


@pytest.mark.parametrize(
    "minute,expected", [(0, 0), (7, 0), (15, 15), (29, 15), (44, 30), (59, 45)]
)
def test_budget_schedule_snaps_to_the_quarter_hour(minute, expected):
    """Meta: "The time entered for a high demand period must be in a 15-minute
    interval (0, 15, 30, 45)"."""
    from datetime import datetime, timezone

    window = BudgetScheduleSpec(
        time_start=datetime(2026, 9, 1, 10, minute, 33, tzinfo=timezone.utc),
        time_end=datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc),
        budget_value=200,
    )
    assert window.time_start.minute == expected
    assert window.time_start.second == 0


# ── promoted objects the matrix left out ─────────────────────────────────────


@pytest.mark.parametrize("objective", [Objective.TRAFFIC, Objective.SALES])
def test_app_destinations_always_promote_the_app(objective):
    """Meta: "Application is required in Promoted Object for App Destination
    Type" — for every goal, not only the conversion ones."""
    _, dest = rules_for(objective, DestinationType.APP)
    for goal in dest.optimization_goals:
        assert dest.promoted_object_kind(goal) == PROMOTED_APPLICATION


def test_engagement_website_does_not_offer_post_engagement():
    """Measured on two ad accounts: POST_ENGAGEMENT passes preflight here and
    fails at AD creation with subcode 1885154, "Your campaign must include an ad
    set with a selected object to promote". A website link ad has no post to
    engage with. The same goal publishes on ON_POST, where the post is the
    object; LINK_CLICKS and REACH publish here.

    It was the first entry, so it was this objective's default — a plain
    Engagement campaign could not publish an ad.
    """
    dest = matrix_for(Objective.ENGAGEMENT).default_destination
    assert OptimizationGoal.POST_ENGAGEMENT not in dest.optimization_goals
    assert dest.default_optimization_goal is OptimizationGoal.LINK_CLICKS
    # Still available where it works.
    _, on_post = rules_for(Objective.ENGAGEMENT, DestinationType.ON_POST)
    assert OptimizationGoal.POST_ENGAGEMENT in on_post.optimization_goals


def test_engagement_website_promotes_nothing():
    """Engagement's DEFAULT conversion location takes NO promoted object.

    Attaching the Page here — an attempted fix for the POST_ENGAGEMENT ad
    failure, subcode 1885154 — made Meta read the ad set as a Page-promoting one
    and reject it at preflight with subcode 2490408, taking LINK_CLICKS and REACH
    down with it. Both of those publish end to end without it.
    """
    rules = matrix_for(Objective.ENGAGEMENT)
    dest = rules.default_destination
    assert dest.destination_type is DestinationType.WEBSITE
    assert dest.promoted_object_by_goal == {}


# ── option lists that could never publish ────────────────────────────────────


def test_no_destination_offers_a_billing_event_its_goals_reject():
    """The destination's billing list is intersected with the goal's, so an event
    no goal accepts is simply an option the editor shows and the spec refuses.
    POST_ENGAGEMENT billing was offered by four conversion locations."""
    dead = [
        (obj.value, d.destination_type.value, b.value)
        for obj, rules in matrix_for.__globals__["OBJECTIVE_MATRIX"].items()
        for d in rules.destinations
        for b in d.billing_events
        if not any(goal_rules(g).allows_billing_event(b.value) for g in d.optimization_goals)
    ]
    assert dead == []


def test_every_offered_cta_is_one_meta_accepts():
    """Meta enumerates the valid CTA codes in its own rejection, and the matrix
    offered two it does not take: GET_STARTED and FOLLOW_PAGE. Both failed at
    ad-creative time — past the preflight rollback — so the campaign and ad set
    were already created when the ad died."""
    from app.graph.meta_spec.enums import CALL_TO_ACTION_ACCEPTED

    offered = {
        cta.value
        for rules in OBJECTIVE_MATRIX.values()
        for dest in rules.destinations
        for cta in dest.call_to_actions
    }
    assert offered <= CALL_TO_ACTION_ACCEPTED, sorted(offered - CALL_TO_ACTION_ACCEPTED)


def test_no_website_destination_offers_get_directions():
    """GET_DIRECTIONS is a real Meta code, but its button carries a place, not
    the ad's link — and publish sets every CTA's value to the destination URL,
    so Meta answers "(#100) call_to_action[value][link] should represent a valid
    URL". Offering it needs a map destination Punk does not collect."""
    offenders = [
        (obj.value, dest.destination_type.value)
        for obj, rules in OBJECTIVE_MATRIX.items()
        for dest in rules.destinations
        if CallToAction.GET_DIRECTIONS in dest.call_to_actions
    ]
    assert offenders == []


def test_instagram_profile_cta_is_one_meta_accepts():
    """FOLLOW_PAGE was the default and Meta rejects it: "(#100)
    call_to_action[type] must be one of the following values: …"."""
    _, dest = rules_for(Objective.TRAFFIC, DestinationType.INSTAGRAM_PROFILE)
    assert dest.default_call_to_action is CallToAction.VIEW_INSTAGRAM_PROFILE
    assert CallToAction.FOLLOW_PAGE not in dest.call_to_actions


# ── pairings only a live publish exposed ─────────────────────────────────────


def test_per_install_billing_is_no_longer_offered():
    """Meta retired it: "CPA billing is no longer available. Select impressions
    to avoid making changes later."

    Its other answer on the same ad set — "You cannot use autobidding with the
    specified billing_event: APP_INSTALLS" — reads like a bid-strategy rule and
    sent the first fix down the wrong path. Pairing it with a capped strategy
    still fails, because the event itself is gone.
    """
    assert BillingEvent.APP_INSTALLS not in goal_rules(
        OptimizationGoal.APP_INSTALLS
    ).billing_events
    with pytest.raises(ValidationError, match="billing_event"):
        _campaign(
            objective=Objective.APP_PROMOTION,
            adsets=[_adset(
                destination_type=DestinationType.APP,
                optimization_goal=OptimizationGoal.APP_INSTALLS,
                billing_event=BillingEvent.APP_INSTALLS,
                bid_strategy=BidStrategy.COST_CAP,
                bid_amount=300,
                promoted_object={
                    "application_id": "app_1",
                    "object_store_url": "https://apps.apple.com/app/id1",
                },
            )],
        )


def test_value_optimization_is_not_offered_on_an_app_destination():
    """Meta rejects it at ad set creation, subcode 2490408 blaming
    ``optimization_goal``: "You can't use the selected performance goal with your
    campaign objective."

    Value optimization bids on the purchase value a pixel reports, so it lives on
    Sales → Website only. The matrix offered it on Sales → App too, which built a
    plan the executor could never publish (live case ``sales.app.value``).
    """
    _, dest = rules_for(Objective.SALES, DestinationType.APP)
    assert OptimizationGoal.VALUE not in dest.optimization_goals
    with pytest.raises(ValidationError, match="optimization_goal"):
        _campaign(
            objective=Objective.SALES,
            adsets=[_adset(
                destination_type=DestinationType.APP,
                optimization_goal=OptimizationGoal.VALUE,
                promoted_object={
                    "application_id": "app_1",
                    "object_store_url": "https://apps.apple.com/app/id1",
                },
            )],
        )


def test_lowest_cost_cbo_requires_one_shared_optimization_goal():
    """Meta: "The same optimization for ad delivery selection is required if the
    campaign bid strategy is lowest cost." The preflight cannot see it — each ad
    set validates alone against an empty campaign — so the first ad set was
    created and the second failed, leaving a half-built campaign."""
    with pytest.raises(ValidationError, match="share one optimization_goal"):
        _campaign(
            daily_budget=30000,
            bid_strategy=BidStrategy.LOWEST_COST_WITHOUT_CAP,
            adsets=[
                _adset(daily_budget=None, optimization_goal=OptimizationGoal.LINK_CLICKS),
                _adset(daily_budget=None, optimization_goal=OptimizationGoal.REACH),
            ],
        )


def test_matching_goals_are_fine_under_a_lowest_cost_campaign_budget():
    spec = _campaign(
        daily_budget=30000,
        bid_strategy=BidStrategy.LOWEST_COST_WITHOUT_CAP,
        # REACH twice: the helper's campaign is Awareness, whose goals are the
        # frequency ones. What matters is that the two agree.
        adsets=[
            _adset(daily_budget=None, optimization_goal=OptimizationGoal.REACH),
            _adset(daily_budget=None, optimization_goal=OptimizationGoal.REACH),
        ],
    )
    assert len(spec.adsets) == 2


def test_budget_sharing_needs_a_campaign_bid_strategy():
    """Meta: "You cannot enable ad set budget sharing without bid strategy"."""
    with pytest.raises(ValidationError, match="budget sharing requires"):
        _campaign(is_adset_budget_sharing_enabled=True)


def test_budget_sharing_with_a_bid_strategy_is_accepted():
    spec = _campaign(
        is_adset_budget_sharing_enabled=True,
        bid_strategy=BidStrategy.LOWEST_COST_WITHOUT_CAP,
    )
    assert spec.is_adset_budget_sharing_enabled is True


# ── video needs a poster frame, in both places it can appear ─────────────────


@pytest.mark.asyncio
async def test_a_video_ad_names_a_poster_frame(monkeypatch):
    """Meta: "Please specify one of image_hash or image_url in the video_data
    field of object_story_spec" (subcode 1443226). Nothing set one, so no video
    ad could publish — and THRUPLAY, which requires a video, was unreachable."""
    body = await _creative_body(monkeypatch, media_type="video", media_ref="vid-1")
    assert body["object_story_spec"]["video_data"]["image_url"] == "https://thumb/1.jpg"


@pytest.mark.asyncio
async def test_a_video_carousel_card_names_a_poster_frame(monkeypatch):
    """Same rule, different code path — subcode 1443052, "The field picture or
    image_hash is required in the link_data field". A carousel mixing a video
    card among images could not publish at all."""
    body = await _creative_body(
        monkeypatch,
        ad_format="CAROUSEL",
        cards=[
            {"title": "Still", "link": "https://example.com", "image_hash": "h1"},
            {"title": "Moving", "link": "https://example.com", "video_id": "vid-1"},
        ],
    )
    children = body["object_story_spec"]["link_data"]["child_attachments"]
    assert children[0]["image_hash"] == "h1" and "picture" not in children[0]
    assert children[1]["video_id"] == "vid-1"
    assert children[1]["picture"] == "https://thumb/1.jpg"


async def _creative_body(monkeypatch, **overrides) -> dict:
    """The ad-creative payload ``create_ad_creative`` would POST."""
    from app.services import meta_ads

    posted: list[dict] = []

    async def _fake_request(method, path, token, json_data=None, **kw):
        if str(path).endswith("/adcreatives"):
            posted.append(dict(json_data or {}))
            return {"id": "creative-1"}
        # the thumbnail read
        return {"thumbnails": {"data": [
            {"uri": "https://thumb/0.jpg", "is_preferred": False},
            {"uri": "https://thumb/1.jpg", "is_preferred": True},
        ]}}

    monkeypatch.setattr(meta_ads, "_request", _fake_request)
    kwargs = dict(
        name="Ad", page_id="pg_1", media_type="image", media_ref="img-hash",
        title="Headline", body="Body copy", cta_type="LEARN_MORE",
        link_url="https://example.com", ad_account_id="act_1", access_token="tok",
    )
    kwargs.update(overrides)
    await meta_ads.create_ad_creative(**kwargs)
    return posted[0]


# ── the instant form's intro card ────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [None, [], ["", "   "]])
async def test_an_intro_card_without_content_is_not_sent(monkeypatch, body):
    """Meta: "(#100) Context card content is not provided". The card was built
    from the headline alone, and a generated form always has a headline (the
    ad's title) and no body — so every auto-generated instant form failed."""
    payload = await _lead_form_payload(monkeypatch, context_headline="Sign up", context_body=body)
    assert "context_card" not in payload


@pytest.mark.asyncio
async def test_an_intro_card_with_content_is_sent(monkeypatch):
    payload = await _lead_form_payload(
        monkeypatch, context_headline="Sign up", context_body=["Fast", "", "Free"],
    )
    card = payload["context_card"]
    assert card["title"] == "Sign up"
    assert card["content"] == ["Fast", "Free"]


@pytest.mark.asyncio
async def test_a_taken_form_name_is_disambiguated(monkeypatch):
    """Meta: "Form Name already exists. Please enter a new one" (subcode
    1892019). Form names are unique per Page and a drafted form carries the name
    the user typed, so reusing a campaign setup collided with the form the first
    publish left behind. The user asked for the form, not for an error."""
    from app.services import meta_ads

    posted: list[dict] = []

    async def _fake_request(method, path, token, json_data=None, **_):
        # Snapshot: the retry renames the same payload dict in place.
        posted.append(dict(json_data or {}))
        if len(posted) == 1:
            raise meta_ads.MetaAdsError(
                "Form Name already exists", code=100, subcode=1892019
            )
        return {"id": "form-2"}

    monkeypatch.setattr(meta_ads, "_request", _fake_request)
    form_id = await meta_ads.create_lead_form(
        "pg_1", name="Spring leads", questions=["EMAIL"],
        privacy_policy_url="https://example.com/privacy", access_token="tok",
        page_token="pt",
    )
    assert form_id == "form-2"
    assert posted[0]["name"] == "Spring leads"
    assert posted[1]["name"].startswith("Spring leads ")
    assert posted[1]["name"] != posted[0]["name"]


@pytest.mark.asyncio
async def test_other_form_errors_still_raise(monkeypatch):
    """Only the name collision is retried — anything else must surface."""
    from app.services import meta_ads

    async def _fake_request(*a, **kw):
        raise meta_ads.MetaAdsError("Something else", code=100, subcode=999)

    monkeypatch.setattr(meta_ads, "_request", _fake_request)
    with pytest.raises(meta_ads.MetaAdsError):
        await meta_ads.create_lead_form(
            "pg_1", name="Form", questions=["EMAIL"],
            privacy_policy_url="https://example.com/privacy", access_token="tok",
            page_token="pt",
        )


async def _lead_form_payload(monkeypatch, **kw) -> dict:
    from app.services import meta_ads

    posted: list[dict] = []

    async def _fake_request(method, path, token, json_data=None, **_):
        # Snapshot: the retry renames the same payload dict in place.
        posted.append(dict(json_data or {}))
        return {"id": "form-1"}

    monkeypatch.setattr(meta_ads, "_request", _fake_request)
    await meta_ads.create_lead_form(
        "pg_1", name="Form", questions=["EMAIL"],
        privacy_policy_url="https://example.com/privacy", access_token="tok",
        page_token="pt", **kw,
    )
    return posted[0]


# ── the floor the account under-reports ──────────────────────────────────────


def test_per_result_billing_raises_the_budget_floor():
    """``min_daily_budget`` is the impression floor. Measured in CAD: the account
    reported 142 and Meta rejected a click-billed ad set under 708."""
    account = {"min_daily_budget": 142}
    assert min_budget_cents(account) == 142
    assert min_budget_cents(account, per_result_billing=True) >= 708
