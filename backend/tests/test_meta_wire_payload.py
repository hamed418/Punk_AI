"""
tests/test_meta_wire_payload.py
───────────────────────────────
Wire-level coverage for the spec → Graph API seam.

Every other Meta test stubs ``meta_ads.create_*``, so the code that turns a
validated ``CampaignSpec`` into an actual HTTP body has never been exercised.
That seam is exactly where the old publish path lost the plan: budgets,
optimization goals and targeting were recomputed on the way out.

Here the fake stops at the transport, so ``to_payload`` → ``_request`` →
``httpx`` runs for real and the assertions are on the JSON body Meta would
receive. No network: an ``httpx.MockTransport`` answers every call, and a
guard test fails loudly if a request ever escapes to graph.facebook.com.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import settings
from app.graph.meta_spec import CampaignSpec
from app.graph.meta_spec.objective_matrix import OBJECTIVE_MATRIX
from app.services import meta_ads

# Pinned wire paths follow META_API_VERSION rather than a hardcoded string —
# the app id this session's Meta app migration moved onto can never call
# v25.0 again (Graph's no-rollback-lane rule), so the version pin moves with
# whatever config.py actually says.
_V = settings.META_API_VERSION


# ── Transport fake ─────────────────────────────────────────────────────────────


class _Wire:
    """Records every outgoing request and replies from a scripted queue."""

    def __init__(self, responses):
        self.requests: list[httpx.Request] = []
        self._responses = list(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "graph.facebook.com", (
            f"request escaped to unexpected host: {request.url}"
        )
        self.requests.append(request)
        payload = self._responses.pop(0) if self._responses else {"id": "123"}
        status = 200
        if isinstance(payload, tuple):
            status, payload = payload
        return httpx.Response(status, json=payload)

    # Convenience accessors — the body as Meta would parse it.
    def body(self, index: int = 0) -> dict:
        return json.loads(self.requests[index].content or b"{}")

    def path(self, index: int = 0) -> str:
        return self.requests[index].url.path

    def token(self, index: int = 0) -> str | None:
        """The bearer token, read off the Authorization header.

        It used to travel as an ``access_token`` query parameter, which put a
        live 60-day credential into every proxy and CDN access log on the way.
        """
        auth = self.requests[index].headers.get("authorization") or ""
        return auth[len("Bearer "):] if auth.startswith("Bearer ") else None

    @property
    def count(self) -> int:
        return len(self.requests)


@pytest.fixture
def wire(monkeypatch):
    """Swap meta_ads' httpx for one whose clients never leave the process."""

    def _install(*responses):
        w = _Wire(responses)

        def _client_factory(*args, **kwargs):
            kwargs.pop("transport", None)
            return httpx.AsyncClient(transport=httpx.MockTransport(w.handler), **kwargs)

        monkeypatch.setattr(
            meta_ads,
            "httpx",
            SimpleNamespace(
                AsyncClient=_client_factory,
                TransportError=httpx.TransportError,
                TimeoutException=httpx.TimeoutException,
            ),
        )
        return w

    return _install


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch):
    """Retry tests must not actually wait 1.5s + 3s + 6s."""

    async def _instant(_seconds):
        return None

    monkeypatch.setattr(meta_ads.asyncio, "sleep", _instant)


# ── Spec fixtures ──────────────────────────────────────────────────────────────

# One nested ad, valid for every objective these tests exercise (LEARN_MORE is
# in each objective's CTA set).
_AD = {
    "name": "Ad",
    "creative": {
        "title": "t", "body": "b",
        "call_to_action": "LEARN_MORE", "link": "https://x.example",
    },
}


def _spec(**overrides) -> CampaignSpec:
    plan = {
        "name": "Summer Push",
        "objective": "OUTCOME_TRAFFIC",
        "special_ad_categories": [],
        "adsets": [
            {
                "name": "Seed",
                "audience_role": "seed",
                "optimization_goal": "LINK_CLICKS",
                "billing_event": "LINK_CLICKS",
                "destination_type": "WEBSITE",
                "daily_budget": 7500,
                "targeting": {"geo_locations": {"countries": ["US"]}},
                "start_time": "2026-08-01T00:00:00+00:00",
                "ads": [
                    {
                        "name": "Seed Ad",
                        "creative": {
                            "title": "t", "body": "b",
                            "call_to_action": "LEARN_MORE",
                            "link": "https://x.example",
                        },
                    }
                ],
            },
            {
                "name": "Broad",
                "audience_role": "broad",
                "optimization_goal": "LANDING_PAGE_VIEWS",
                "billing_event": "IMPRESSIONS",
                "destination_type": "WEBSITE",
                "daily_budget": 2500,
                "targeting": {"geo_locations": {"countries": ["CA"]}},
                "start_time": "2026-08-01T00:00:00+00:00",
                "ads": [
                    {
                        "name": "Broad Ad",
                        "creative": {
                            "title": "t", "body": "b",
                            "call_to_action": "LEARN_MORE",
                            "link": "https://x.example",
                        },
                    }
                ],
            },
        ],
    }
    plan.update(overrides)
    return CampaignSpec.model_validate(plan)


# ── Every offered combination, end to end on the wire ──────────────────────────
# test_meta_spec_matrix proves each objective × conversion location BUILDS a
# valid spec. It stops there — nothing checked what those 22 combinations
# actually put on the wire, which is the seam this module exists for. Here the
# whole publish runs against the transport fake, so a combination that validates
# locally and then ships a malformed body fails in CI rather than in someone's
# ad account.


_PUBLISH_USER = {
    "meta_access_token": "tok",
    "meta_ad_account_id": "act_1",
    # Matches the PROMOTED_PAGE page id _spec_from_defaults uses, so the
    # creative's object_story_spec and the promoted object name one Page.
    "meta_page_id": "987654321",
    "business_name": "Acme",
}


def _publishable_plan(objective, destination) -> dict:
    """The matrix's own defaults for one combination, with media attached.

    ``_spec_from_defaults`` builds a plan the editor would produce *before* the
    user adds an image; publish skips an ad with no media, which would leave
    nothing to assert. A pre-uploaded ``image_hash`` is used rather than a
    ``media_id`` so no MediaFile row or upload is involved.
    """
    from app.graph.meta_spec.objective_matrix import goal_rules
    from tests.test_meta_spec_matrix import _spec_from_defaults

    spec = _spec_from_defaults(objective, destination)
    plan = spec.model_dump(mode="json")
    for adset, src in zip(plan["adsets"], spec.adsets):
        needs_video = goal_rules(src.optimization_goal).media_kind == "video"
        for ad in adset["ads"]:
            creative = ad["creative"]
            # A boost ad IS an existing Page post; a carousel carries media per
            # card. Neither takes an ad-level reference.
            if creative.get("object_story_id") or creative.get("cards"):
                continue
            if needs_video:
                creative["video_id"] = "vid_1"
            else:
                creative["image_hash"] = "img_1"
    # Still a checked payload after the edit — this is what publish re-validates.
    CampaignSpec.model_validate(plan)
    return plan


def _bodies(w: _Wire, endpoint: str) -> list[dict]:
    """Every request body sent to ``act_1/<endpoint>``, in order."""
    return [
        json.loads(r.content or b"{}")
        for r in w.requests
        if r.url.path.endswith(f"/act_1/{endpoint}")
    ]


@pytest.mark.parametrize(
    "objective,destination",
    [
        (obj, dest.destination_type)
        for obj, rules in OBJECTIVE_MATRIX.items()
        for dest in rules.destinations
    ],
)
@pytest.mark.asyncio
async def test_every_offered_combination_publishes_a_well_formed_payload(
    wire, monkeypatch, objective, destination
):
    from app.graph.builder.executors import media as media_exec
    from app.graph.builder.executors.publish_ledger import PublishLedger
    from app.graph.meta_spec.enums import OptimizationGoal
    from app.graph.meta_spec.objective_matrix import (
        PROMOTED_APPLICATION,
        PROMOTED_NONE,
        PROMOTED_PAGE,
        PROMOTED_PIXEL,
        matrix_for,
    )

    async def _memory_ledger(*a, **k):
        return PublishLedger()

    monkeypatch.setattr(media_exec, "_load_ledger", _memory_ledger)

    w = wire()  # empty queue → every create answers {"id": "123"}
    plan = _publishable_plan(objective, destination)

    # Publish only reuses a plan's instant form when it is a live form on the Page
    # (an id from another Page is rejected by Meta), and otherwise builds a default
    # one. The empty wire answers the Page's form list with nothing, so seed it with
    # the plan's own form — that is the case this test asserts on.
    _plan_forms = [
        {"id": ad["creative"]["lead_gen_form_id"], "name": "F", "status": "ACTIVE"}
        for adset in plan["adsets"]
        for ad in adset["ads"]
        if ad["creative"].get("lead_gen_form_id")
    ]

    async def _page_forms(*a, **k):
        return _plan_forms

    monkeypatch.setattr(meta_ads, "list_lead_forms", _page_forms)

    ids = await media_exec.publish_campaign_to_meta(
        _PUBLISH_USER, {}, plan, {}, lambda _event: None,
    )
    assert ids is not None
    assert ids["ad_ids"], "no ad was created — the combination published nothing"

    dest = matrix_for(objective).for_destination(destination)
    adset_plan = plan["adsets"][0]

    # ── campaign ──────────────────────────────────────────────────────────────
    campaigns = _bodies(w, "campaigns")
    # First call is the validate_only preflight, second is the real create.
    assert campaigns[0]["execution_options"] == ["validate_only"]
    campaign = campaigns[1]
    assert "execution_options" not in campaign
    assert campaign["objective"] == objective.value
    assert campaign["status"] == "PAUSED"
    assert campaign["buying_type"] == "AUCTION"
    assert campaign["special_ad_categories"] == []
    # ABO plan (budgets live on the ad sets) — Meta rejects the campaign without
    # an explicit True/False here.
    assert campaign["is_adset_budget_sharing_enabled"] is False
    assert "daily_budget" not in campaign

    # ── ad set ────────────────────────────────────────────────────────────────
    adsets = _bodies(w, "adsets")
    assert adsets[0]["execution_options"] == ["validate_only"]
    adset = adsets[1]
    # Absent for the conversion locations Meta expresses by omission — Engagement
    # → Website is one, and sending the field there is rejected outright. See
    # DestinationRules.omit_destination_type.
    if dest.omit_destination_type:
        assert "destination_type" not in adset
    else:
        assert adset["destination_type"] == destination.value
    assert adset["optimization_goal"] == adset_plan["optimization_goal"]
    assert adset["billing_event"] == adset_plan["billing_event"]
    assert adset["status"] == "PAUSED"
    assert adset["daily_budget"] == adset_plan["daily_budget"]
    assert adset["bid_strategy"] == adset_plan["bid_strategy"]
    assert adset["targeting"]["geo_locations"], "an ad set with no geo spends nationwide"

    required = dest.promoted_object_kind(
        OptimizationGoal(adset_plan["optimization_goal"])
    )
    promoted = adset.get("promoted_object")
    if required == PROMOTED_NONE:
        assert promoted is None
    elif required == PROMOTED_PIXEL:
        assert promoted["pixel_id"] and promoted["custom_event_type"]
    elif required == PROMOTED_PAGE:
        assert promoted["page_id"]
    elif required == PROMOTED_APPLICATION:
        assert promoted["application_id"] and promoted["object_store_url"]

    # ── creative ──────────────────────────────────────────────────────────────
    creative = _bodies(w, "adcreatives")[0]
    plan_creative = adset_plan["ads"][0]["creative"]
    if dest.object_story_kind:
        # The ad IS the Page post: no composed copy, no media, no story spec.
        assert creative["object_story_id"] == plan_creative["object_story_id"]
        assert "object_story_spec" not in creative
    else:
        story = creative["object_story_spec"]
        assert story["page_id"] == _PUBLISH_USER["meta_page_id"]
        data = story.get("video_data") or story["link_data"]
        cta_value = data["call_to_action"]["value"]
        if dest.requires_lead_form:
            assert cta_value == {"lead_gen_form_id": plan_creative["lead_gen_form_id"]}
        elif plan_creative["call_to_action"] == "WHATSAPP_MESSAGE":
            assert cta_value == {"app_destination": "WHATSAPP"}
        else:
            assert cta_value == {"link": plan_creative["link"]}
        assert data["call_to_action"]["type"] == plan_creative["call_to_action"]

    # ── ad ────────────────────────────────────────────────────────────────────
    ad = _bodies(w, "ads")[0]
    assert ad["status"] == "PAUSED"
    assert ad["creative"] == {"creative_id": "123"}


# ── Campaign payload ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_campaign_payload_reaches_meta_intact(wire):
    w = wire({"id": "camp_1"})

    camp_id = await meta_ads.create_campaign_from_spec(
        _spec(), ad_account_id="act_999", access_token="tok"
    )

    assert camp_id == "camp_1"
    assert w.path() == f"/{_V}/act_999/campaigns"
    assert w.token() == "tok"
    body = w.body()
    assert body["name"] == "Summer Push"
    assert body["objective"] == "OUTCOME_TRAFFIC"
    assert body["special_ad_categories"] == []
    # validate_only must NOT leak into a real create.
    assert "execution_options" not in body


@pytest.mark.asyncio
async def test_special_ad_categories_are_declared_not_blanked(wire):
    """The old create_campaign hardcoded [] and shipped regulated ads undeclared."""
    w = wire({"id": "camp_1"})

    await meta_ads.create_campaign_from_spec(
        _spec(
            special_ad_categories=["HOUSING"],
            special_ad_category_country=["US"],
        ),
        ad_account_id="act_1",
        access_token="tok",
    )

    body = w.body()
    assert body["special_ad_categories"] == ["HOUSING"]
    # Meta rejects the campaign when the category has no country beside it.
    assert body["special_ad_category_country"] == ["US"]


@pytest.mark.asyncio
async def test_campaign_creation_without_id_raises(wire):
    wire({"no_id_here": True})

    with pytest.raises(meta_ads.MetaAdsError, match="no ID"):
        await meta_ads.create_campaign_from_spec(
            _spec(), ad_account_id="act_1", access_token="tok"
        )


# ── Ad set payload — the regression the whole spec rewrite exists to prevent ────


@pytest.mark.asyncio
async def test_each_adset_sends_its_own_budget_and_goal(wire):
    """Previously every ad set got the same budget and a hardcoded IMPRESSIONS."""
    w = wire({"id": "as_1"}, {"id": "as_2"})
    spec = _spec()

    for adset in spec.adsets:
        await meta_ads.create_adset_from_spec(
            adset, campaign_id="camp_1", ad_account_id="act_1", access_token="tok"
        )

    first, second = w.body(0), w.body(1)

    assert (first["daily_budget"], second["daily_budget"]) == (7500, 2500)
    assert first["optimization_goal"] == "LINK_CLICKS"
    assert second["optimization_goal"] == "LANDING_PAGE_VIEWS"
    assert first["billing_event"] == "LINK_CLICKS"
    assert second["billing_event"] == "IMPRESSIONS"


@pytest.mark.asyncio
async def test_adset_payload_carries_targeting_and_campaign_id(wire):
    """The plan's targeting used to be discarded and rebuilt at publish time."""
    w = wire({"id": "as_1"})
    spec = _spec()

    await meta_ads.create_adset_from_spec(
        spec.adsets[0], campaign_id="camp_77", ad_account_id="act_1", access_token="tok"
    )

    body = w.body()
    assert w.path() == f"/{_V}/act_1/adsets"
    assert body["campaign_id"] == "camp_77"
    assert body["targeting"]["geo_locations"]["countries"] == ["US"]
    assert body["bid_strategy"] == "LOWEST_COST_WITHOUT_CAP"
    assert body["name"] == "Seed"


@pytest.mark.asyncio
async def test_promoted_object_reaches_the_wire(wire):
    w = wire({"id": "as_1"})
    spec = _spec(
        objective="OUTCOME_SALES",
        adsets=[
            {
                "name": "Purchases",
                "audience_role": "broad",
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "billing_event": "IMPRESSIONS",
                "destination_type": "WEBSITE",
                "daily_budget": 5000,
                "targeting": {"geo_locations": {"countries": ["US"]}},
                "start_time": "2026-08-01T00:00:00+00:00",
                "promoted_object": {"pixel_id": "px_9", "custom_event_type": "PURCHASE"},
                "ads": [_AD],
            }
        ],
    )

    await meta_ads.create_adset_from_spec(
        spec.adsets[0], campaign_id="c1", ad_account_id="act_1", access_token="tok"
    )

    assert w.body()["promoted_object"] == {
        "pixel_id": "px_9",
        "custom_event_type": "PURCHASE",
    }


# ── Advantage+ campaign budget (CBO) on the wire ────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("sharing", [False, True])
async def test_abo_campaign_states_adset_budget_sharing(wire, sharing):
    """Meta: "You must specify True or False in the field
    is_adset_budget_sharing_enabled if you are not using campaign budget." It has
    no default, so omitting it rejected every ABO campaign at preflight.

    Turning it ON also needs a campaign-level bid strategy — measured, "You
    cannot enable ad set budget sharing without bid strategy" — so the spec is
    built with one. ``to_payload`` sends ``bid_strategy`` whenever it is set,
    campaign budget or not, so it reaches the wire under ABO too.
    """
    w = wire({"id": "camp_1"})

    await meta_ads.create_campaign_from_spec(
        _spec(
            is_adset_budget_sharing_enabled=sharing,
            bid_strategy="LOWEST_COST_WITHOUT_CAP",
        ),
        ad_account_id="act_1",
        access_token="tok",
    )

    assert w.body()["is_adset_budget_sharing_enabled"] is sharing


@pytest.mark.asyncio
async def test_cbo_campaign_omits_adset_budget_sharing(wire):
    """The flag is ABO-only — Meta rejects it beside a campaign budget."""
    w = wire({"id": "camp_1"})

    await meta_ads.create_campaign_from_spec(
        _spec(
            daily_budget=10000,
            bid_strategy="LOWEST_COST_WITHOUT_CAP",
            adsets=[
                {
                    "name": "Seed",
                    "audience_role": "seed",
                    "optimization_goal": "LINK_CLICKS",
                    "billing_event": "LINK_CLICKS",
                    "destination_type": "WEBSITE",
                    "targeting": {"geo_locations": {"countries": ["US"]}},
                    "start_time": "2026-08-01T00:00:00+00:00",
                    "ads": [_AD],
                },
            ],
        ),
        ad_account_id="act_1",
        access_token="tok",
    )

    assert "is_adset_budget_sharing_enabled" not in w.body()


@pytest.mark.asyncio
async def test_cbo_campaign_carries_budget_and_bid(wire):
    w = wire({"id": "camp_1"})
    spec = _spec(
        daily_budget=10000,
        bid_strategy="LOWEST_COST_WITHOUT_CAP",
        adsets=[
            {
                "name": "Seed",
                "audience_role": "seed",
                "optimization_goal": "LINK_CLICKS",
                "billing_event": "LINK_CLICKS",
                "destination_type": "WEBSITE",
                "targeting": {"geo_locations": {"countries": ["US"]}},
                "start_time": "2026-08-01T00:00:00+00:00",
                "ads": [_AD],
            },
        ],
    )

    await meta_ads.create_campaign_from_spec(
        spec, ad_account_id="act_1", access_token="tok"
    )

    body = w.body()
    assert body["daily_budget"] == 10000
    assert body["bid_strategy"] == "LOWEST_COST_WITHOUT_CAP"


@pytest.mark.asyncio
async def test_cbo_adset_omits_budget_and_bid_on_the_wire(wire):
    w = wire({"id": "as_1"})
    spec = _spec(
        daily_budget=10000,
        bid_strategy="LOWEST_COST_WITHOUT_CAP",
        adsets=[
            {
                "name": "Seed",
                "audience_role": "seed",
                "optimization_goal": "LINK_CLICKS",
                "billing_event": "LINK_CLICKS",
                "destination_type": "WEBSITE",
                "targeting": {"geo_locations": {"countries": ["US"]}},
                "start_time": "2026-08-01T00:00:00+00:00",
                "ads": [_AD],
            },
        ],
    )

    await meta_ads.create_adset_from_spec(
        spec.adsets[0], campaign_id="c1", ad_account_id="act_1",
        access_token="tok", campaign_has_budget=True,
    )

    body = w.body()
    assert "daily_budget" not in body
    assert "lifetime_budget" not in body
    assert "bid_strategy" not in body


@pytest.mark.asyncio
async def test_schedule_and_attribution_reach_the_wire(wire):
    """Dayparting needs a lifetime budget; an attribution window needs a
    conversion to attribute, so it rides on a pixel-optimized ad set."""
    w = wire({"id": "as_1"})
    spec = _spec(
        objective="OUTCOME_SALES",
        adsets=[
            {
                "name": "Seed",
                "audience_role": "seed",
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "billing_event": "IMPRESSIONS",
                "destination_type": "WEBSITE",
                "lifetime_budget": 50000,
                "end_time": "2026-09-01T00:00:00+00:00",
                "targeting": {"geo_locations": {"countries": ["US"]}},
                "start_time": "2026-08-01T00:00:00+00:00",
                "promoted_object": {
                    "pixel_id": "px_1", "custom_event_type": "PURCHASE",
                },
                "adset_schedule": [
                    {"days": [1, 2, 3], "start_minute": 540, "end_minute": 1020}
                ],
                "attribution_spec": [
                    {"event_type": "CLICK_THROUGH", "window_days": 7}
                ],
                "ads": [_AD],
            },
        ],
    )

    await meta_ads.create_adset_from_spec(
        spec.adsets[0], campaign_id="c1", ad_account_id="act_1", access_token="tok"
    )

    body = w.body()
    assert body["adset_schedule"] == [
        {"days": [1, 2, 3], "start_minute": 540, "end_minute": 1020}
    ]
    assert body["attribution_spec"] == [
        {"event_type": "CLICK_THROUGH", "window_days": 7}
    ]


@pytest.mark.asyncio
async def test_budget_scheduling_reaches_the_campaign_wire(wire):
    """"High demand periods" under a campaign (Advantage+) budget. The only field
    in the scheduling group that had never been asserted at the HTTP layer.

    The window is Unix seconds — these entries are HighDemandPeriod objects and
    the SDK types ``POST /{id}/budget_schedules`` with
    ``'time_start': 'unsigned int'``. Everything else we send Meta is ISO-8601,
    so this test is what stops someone "fixing" the inconsistency."""
    w = wire({"id": "camp_sched"})
    spec = _spec(
        daily_budget=100_00,
        bid_strategy="LOWEST_COST_WITHOUT_CAP",
        budget_schedule_specs=[{
            "time_start": "2026-08-10T00:00:00+00:00",
            "time_end": "2026-08-12T00:00:00+00:00",
            "budget_value": 200,
            "budget_value_type": "MULTIPLIER",
        }],
        adsets=[{
            "name": "Seed",
            "audience_role": "seed",
            "optimization_goal": "LINK_CLICKS",
            "billing_event": "LINK_CLICKS",
            "destination_type": "WEBSITE",
            "targeting": {"geo_locations": {"countries": ["US"]}},
            "start_time": "2026-08-01T00:00:00+00:00",
            "ads": [_AD],
        }],
    )

    await meta_ads.create_campaign_from_spec(
        spec, ad_account_id="act_1", access_token="tok"
    )

    entry = w.body()["budget_schedule_specs"][0]
    assert entry["budget_value"] == 200
    assert entry["budget_value_type"] == "MULTIPLIER"
    assert entry["time_start"] == 1786320000      # 2026-08-10T00:00:00Z
    assert entry["time_end"] == 1786492800        # 2026-08-12T00:00:00Z


@pytest.mark.asyncio
async def test_detailed_targeting_groups_reach_the_wire(wire):
    """flexible_spec / exclusions were only ever tested as FORBIDDEN (special ad
    categories). Nothing asserted that a well-formed group survives — and the
    shapes differ: flexible_spec is a list of AND-ed groups, exclusions is one
    bare object."""
    w = wire({"id": "as_flex"})
    spec = _spec(adsets=[{
        "name": "Seed",
        "audience_role": "seed",
        "optimization_goal": "LINK_CLICKS",
        "billing_event": "LINK_CLICKS",
        "destination_type": "WEBSITE",
        "daily_budget": 5000,
        "targeting": {
            "geo_locations": {"countries": ["US"]},
            "flexible_spec": [{
                "interests": [{"id": "6003", "name": "Coffee"}],
                "behaviors": [{"id": "6002", "name": "Frequent travellers"}],
            }],
            "exclusions": {"interests": [{"id": "6004", "name": "Tea"}]},
        },
        "start_time": "2026-08-01T00:00:00+00:00",
        "ads": [_AD],
    }])

    await meta_ads.create_adset_from_spec(
        spec.adsets[0], campaign_id="c1", ad_account_id="act_1", access_token="tok"
    )

    targeting = w.body()["targeting"]
    assert targeting["flexible_spec"] == [{
        "interests": [{"id": "6003", "name": "Coffee"}],
        "behaviors": [{"id": "6002", "name": "Frequent travellers"}],
    }]
    assert targeting["exclusions"] == {"interests": [{"id": "6004", "name": "Tea"}]}


@pytest.mark.asyncio
async def test_zip_geo_targeting_reaches_the_wire(wire):
    from app.services.meta_ads import build_targeting

    targeting = await build_targeting(
        {"target_zips": ["US:94104", "US:94105"]}, custom_audience_id="ca_1"
    )
    assert targeting["geo_locations"]["zips"] == [
        {"key": "US:94104"}, {"key": "US:94105"}
    ]
    assert "custom_locations" not in targeting["geo_locations"]


@pytest.mark.asyncio
async def test_targeting_falls_back_to_a_radius_without_zips(wire):
    """``cities`` takes an adgeolocation key, not a name — Meta rejects
    ``{"name": "Toronto"}``, which is what this fallback used to send. Coordinates
    are already on geo_data and cost no extra Graph API call."""
    from app.services.meta_ads import build_targeting

    targeting = await build_targeting({
        "target_zips": [],
        "poi_radius_km": 4,
        "locations": [{"location_name": "Toronto", "latitude": 43.6532, "longitude": -79.3832}],
    })
    assert "cities" not in targeting["geo_locations"]
    assert targeting["geo_locations"]["custom_locations"] == [{
        "latitude": 43.6532,
        "longitude": -79.3832,
        "radius": 4.0,
        "distance_unit": "kilometer",
    }]


@pytest.mark.asyncio
async def test_radius_fallback_skips_locations_with_no_coordinates(wire):
    """A geocoder miss leaves a name and nothing else. Better no geo block —
    AdSetSpec rejects that loudly — than a nationwide spend."""
    from app.services.meta_ads import build_targeting

    targeting = await build_targeting(
        {"target_zips": [], "locations": [{"location_name": "Toronto"}]}
    )
    assert "geo_locations" not in targeting


# ── validate_only preflight ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_campaign_sends_execution_options(wire):
    w = wire({"success": True})

    await meta_ads.validate_campaign_payload(
        _spec(), ad_account_id="act_1", access_token="tok"
    )

    body = w.body()
    assert body["execution_options"] == ["validate_only"]
    # Same payload as the real create, plus the flag — that is the whole point.
    assert body["objective"] == "OUTCOME_TRAFFIC"


@pytest.mark.asyncio
async def test_validate_adset_sends_execution_options(wire):
    w = wire({"success": True})
    spec = _spec()

    await meta_ads.validate_adset_payload(
        spec.adsets[0], campaign_id="c1", ad_account_id="act_1", access_token="tok"
    )

    body = w.body()
    assert body["execution_options"] == ["validate_only"]
    assert body["daily_budget"] == 7500


@pytest.mark.asyncio
async def test_preflight_rejection_surfaces_meta_error_detail(wire):
    """Meta's own verdict is the backstop when our matrix drifts."""
    wire(
        {
            "error": {
                "type": "OAuthException",
                "message": "Invalid parameter",
                "code": 100,
                "error_subcode": 1487079,
                "error_user_msg": "Daily budget is below the minimum.",
                "error_data": {"blame_field_specs": [["daily_budget"]]},
            }
        }
    )

    with pytest.raises(meta_ads.MetaAdsError) as exc_info:
        await meta_ads.validate_campaign_payload(
            _spec(), ad_account_id="act_1", access_token="tok"
        )

    err = exc_info.value
    assert err.code == 100
    assert err.subcode == 1487079
    assert err.user_msg == "Daily budget is below the minimum."
    assert err.blame_field == ["daily_budget"]
    assert not err.retryable


# ── act_ normalization ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bare_account_id_gets_act_prefix(wire):
    w = wire({"id": "c1"})

    await meta_ads.create_campaign_from_spec(
        _spec(), ad_account_id="123456", access_token="tok"
    )

    assert w.path() == f"/{_V}/act_123456/campaigns"


@pytest.mark.asyncio
async def test_prefixed_account_id_is_not_double_prefixed(wire):
    w = wire({"id": "c1"})

    await meta_ads.create_campaign_from_spec(
        _spec(), ad_account_id="act_123456", access_token="tok"
    )

    assert w.path() == f"/{_V}/act_123456/campaigns"
    assert "act_act_" not in w.path()


# ── Retry policy ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_throttle_code_is_retried_then_succeeds(wire):
    w = wire(
        {"error": {"type": "OAuthException", "message": "rate limit", "code": 17}},
        {"error": {"type": "OAuthException", "message": "rate limit", "code": 17}},
        {"id": "camp_ok"},
    )

    camp_id = await meta_ads.create_campaign_from_spec(
        _spec(), ad_account_id="act_1", access_token="tok"
    )

    assert camp_id == "camp_ok"
    assert w.count == 3


@pytest.mark.asyncio
async def test_validation_error_is_not_retried(wire):
    """Retrying a rejected payload cannot make it valid — it just burns quota."""
    w = wire(
        {"error": {"type": "OAuthException", "message": "Invalid parameter", "code": 100}},
        {"id": "should_never_be_reached"},
    )

    with pytest.raises(meta_ads.MetaAdsError):
        await meta_ads.create_campaign_from_spec(
            _spec(), ad_account_id="act_1", access_token="tok"
        )

    assert w.count == 1


@pytest.mark.asyncio
async def test_retries_are_bounded(wire):
    w = wire(*[{"error": {"message": "throttled", "code": 4}}] * 10)

    with pytest.raises(meta_ads.MetaAdsError):
        await meta_ads.create_campaign_from_spec(
            _spec(), ad_account_id="act_1", access_token="tok"
        )

    assert w.count == meta_ads._MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_network_error_is_retried_then_wrapped(monkeypatch):
    attempts = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        raise httpx.ConnectError("connection refused", request=request)

    def _client_factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return httpx.AsyncClient(transport=httpx.MockTransport(_handler), **kwargs)

    monkeypatch.setattr(
        meta_ads,
        "httpx",
        SimpleNamespace(
            AsyncClient=_client_factory,
            TransportError=httpx.TransportError,
            TimeoutException=httpx.TimeoutException,
        ),
    )

    with pytest.raises(meta_ads.MetaAdsError, match="network error"):
        await meta_ads.create_campaign_from_spec(
            _spec(), ad_account_id="act_1", access_token="tok"
        )

    assert attempts["n"] == meta_ads._MAX_ATTEMPTS


# ── targeting search (detailed-targeting typeahead for the editor) ──────────────


@pytest.mark.asyncio
async def test_search_targeting_interests_parses_results(wire):
    w = wire({"data": [
        {"id": "6003107902433", "name": "Coffee",
         "audience_size_lower_bound": 100, "audience_size_upper_bound": 200,
         "path": ["Interests", "Food and drink", "Coffee"]},
    ]})

    out = await meta_ads.search_targeting_interests("coffee", "tok")

    assert w.path() == f"/{_V}/search"
    params = w.requests[0].url.params
    assert params.get("type") == "adinterest"
    assert params.get("q") == "coffee"
    assert out == [{
        "id": "6003107902433",
        "name": "Coffee",
        "audience_size": 200,
        "path": ["Interests", "Food and drink", "Coffee"],
        "flex_field": "interests",
    }]


@pytest.mark.asyncio
async def test_search_targeting_behaviors_uses_category_class(wire):
    w = wire({"data": []})

    await meta_ads.search_targeting_interests("frequent", "tok", kind="behaviors")

    params = w.requests[0].url.params
    assert params.get("type") == "adTargetingCategory"
    assert params.get("class") == "behaviors"


@pytest.mark.asyncio
async def test_search_targeting_degrades_to_empty_on_error(wire):
    wire({"error": {"message": "bad", "code": 100}})
    out = await meta_ads.search_targeting_interests("coffee", "tok")
    assert out == []


# ── Instant form creation wire ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lead_form_wire_carries_custom_questions_and_the_intro_card(wire):
    """The form the user designed in the editor, in the shape Graph accepts.

    A custom question's answer options travel as {key, value} pairs — the spec
    carries plain strings, so the key is derived here rather than making the
    editor invent one.
    """
    w = wire({"id": "form_77"})

    form_id = await meta_ads.create_lead_form(
        "pg_1",
        name="Quote request",
        questions=[
            "EMAIL",
            {"type": "CUSTOM", "label": "Which service?",
             "options": ["Roofing", "Siding"]},
        ],
        privacy_policy_url="https://acme.example/privacy",
        access_token="tok",
        page_token="pt",
        context_headline="Get a free quote",
        context_body=["Same-day estimate", "  ", "No obligation"],
        higher_intent=True,
    )

    body = w.body()
    assert form_id == "form_77"
    assert body["questions"][0] == {"type": "EMAIL"}
    assert body["questions"][1] == {
        "type": "CUSTOM",
        "label": "Which service?",
        "options": [
            {"key": "Roofing", "value": "Roofing"},
            {"key": "Siding", "value": "Siding"},
        ],
    }
    # Blank lines are dropped rather than shipped as empty bullets.
    assert body["context_card"]["content"] == ["Same-day estimate", "No obligation"]
    assert body["context_card"]["title"] == "Get a free quote"
    assert body["is_optimized_for_quality"] is True
    assert body["privacy_policy"]["url"] == "https://acme.example/privacy"


@pytest.mark.asyncio
async def test_lead_form_without_an_intro_card_omits_it(wire):
    """Meta rejects an empty context_card, and the three default questions are
    still plain type strings."""
    w = wire({"id": "form_78"})

    await meta_ads.create_lead_form(
        "pg_1",
        name="Default form",
        questions=["FULL_NAME", "EMAIL", "PHONE"],
        privacy_policy_url="https://acme.example/privacy",
        access_token="tok",
        page_token="pt",
    )

    body = w.body()
    assert "context_card" not in body
    assert "is_optimized_for_quality" not in body
    assert body["questions"] == [
        {"type": "FULL_NAME"}, {"type": "EMAIL"}, {"type": "PHONE"}
    ]


@pytest.mark.asyncio
async def test_create_lead_form_service_maps_the_spec_onto_the_call(monkeypatch):
    """The editor's "create it now" path. The request body is a LeadFormSpec, so
    this is the one place its field names are translated to meta_ads' arguments —
    a rename on either side has to break here rather than at runtime."""
    from app.graph.meta_spec.models import LeadFormSpec
    from app.modules.ads.service import AdsService
    from app.services import meta_ads as _meta

    seen: dict = {}

    async def _fake_create(page_id, **kwargs):
        seen.update({"page_id": page_id, **kwargs})
        return "form_99"

    monkeypatch.setattr(_meta, "create_lead_form", _fake_create)

    service = AdsService(repository=None)
    monkeypatch.setattr(
        AdsService, "get_meta_access_token", lambda self, db, uid: _async("tok")
    )

    form = LeadFormSpec(
        name="Quote request",
        questions=[{"type": "CUSTOM", "label": "Which service?", "options": ["Roofing"]}],
        privacy_policy_url="https://acme.example/privacy",
        intro_title="Get a quote",
        higher_intent=True,
    )
    out = await service.create_page_lead_form(None, "u1", "pg_1", form)

    assert out == {"id": "form_99", "name": "Quote request"}
    assert seen["page_id"] == "pg_1"
    assert seen["access_token"] == "tok"
    assert seen["context_headline"] == "Get a quote"
    assert seen["higher_intent"] is True
    # exclude_none: an absent option list must not become "options": null, which
    # Graph rejects.
    assert seen["questions"] == [
        {"type": "CUSTOM", "label": "Which service?", "options": ["Roofing"]}
    ]


@pytest.mark.asyncio
async def test_a_form_created_now_sends_people_to_the_business_not_the_policy(monkeypatch):
    """``create_lead_form`` defaults follow_up_action_url to the privacy policy
    when it gets nothing. Publish works around that with the advertiser's site;
    this endpoint did not, so every lead collected through "create it now" landed
    on a legal page. The Page's own website is the same answer, one GET away."""
    from app.graph.meta_spec.models import LeadFormSpec
    from app.modules.ads.service import AdsService
    from app.services import meta_ads as _meta

    seen: dict = {}

    async def _fake_create(page_id, **kwargs):
        seen.update(kwargs)
        return "form_99"

    monkeypatch.setattr(_meta, "create_lead_form", _fake_create)
    monkeypatch.setattr(_meta, "fetch_page_website", lambda *a, **k: _async("https://acme.example"))

    service = AdsService(repository=None)
    monkeypatch.setattr(
        AdsService, "get_meta_access_token", lambda self, db, uid: _async("tok")
    )

    form = LeadFormSpec(
        name="Quote request",
        questions=[{"type": "EMAIL"}],
        privacy_policy_url="https://acme.example/privacy",
    )
    await service.create_page_lead_form(None, "u1", "pg_1", form)
    assert seen["follow_up_url"] == "https://acme.example"


@pytest.mark.asyncio
async def test_an_explicit_follow_up_url_is_not_overridden(monkeypatch):
    """The fallback is a floor, not a policy — what the user typed wins."""
    from app.graph.meta_spec.models import LeadFormSpec
    from app.modules.ads.service import AdsService
    from app.services import meta_ads as _meta

    seen: dict = {}

    async def _fake_create(page_id, **kwargs):
        seen.update(kwargs)
        return "form_99"

    monkeypatch.setattr(_meta, "create_lead_form", _fake_create)
    monkeypatch.setattr(_meta, "fetch_page_website", lambda *a, **k: _async("https://page.example"))

    service = AdsService(repository=None)
    monkeypatch.setattr(
        AdsService, "get_meta_access_token", lambda self, db, uid: _async("tok")
    )

    form = LeadFormSpec(
        name="Quote request",
        questions=[{"type": "EMAIL"}],
        privacy_policy_url="https://acme.example/privacy",
        follow_up_url="https://acme.example/thanks",
    )
    await service.create_page_lead_form(None, "u1", "pg_1", form)
    assert seen["follow_up_url"] == "https://acme.example/thanks"


@pytest.mark.asyncio
async def test_create_lead_form_service_refuses_without_a_meta_connection(monkeypatch):
    """The read helpers degrade to []; a create must not — a form the user
    believes exists takes the campaign down at publish."""
    from app.graph.meta_spec.models import LeadFormSpec
    from app.modules.ads.service import AdsService

    monkeypatch.setattr(
        AdsService, "get_meta_access_token", lambda self, db, uid: _async(None)
    )
    form = LeadFormSpec(
        name="F", questions=[{"type": "EMAIL"}],
        privacy_policy_url="https://acme.example/privacy",
    )
    with pytest.raises(ValueError, match="not connected"):
        await AdsService(repository=None).create_page_lead_form(None, "u1", "pg_1", form)


async def _async(value):
    return value


# ── Copy: URL params + display-only suggestion pool ─────────────────────────────


@pytest.mark.asyncio
async def test_url_tags_reach_the_creative_wire(wire):
    w = wire({"id": "cr_utm"})

    await meta_ads.create_ad_creative(
        name="Ad Creative",
        page_id="pg_1",
        media_type="image",
        media_ref="hash_abc",
        title="t",
        body="b",
        cta_type="LEARN_MORE",
        link_url="https://x.example",
        ad_account_id="act_1",
        access_token="tok",
        url_tags="utm_source=facebook&utm_medium=paid",
    )

    assert w.body()["url_tags"] == "utm_source=facebook&utm_medium=paid"


def test_copy_suggestions_are_display_only_not_published():
    # The AI suggestion pool the editor dropdown lists is carried on the spec but
    # must never leak into what Meta receives — the creative publishes the single
    # chosen title/body only.
    adset = {
        "name": "Seed",
        "audience_role": "seed",
        "optimization_goal": "LINK_CLICKS",
        "billing_event": "LINK_CLICKS",
        "destination_type": "WEBSITE",
        "daily_budget": 7500,
        "targeting": {"geo_locations": {"countries": ["US"]}},
        "start_time": "2026-08-01T00:00:00+00:00",
        "ads": [
            {
                "name": "Seed Ad",
                "creative": {
                    "title": "Chosen headline",
                    "body": "Chosen body",
                    "call_to_action": "LEARN_MORE",
                    "link": "https://x.example",
                    "title_suggestions": ["Chosen headline", "Alt headline"],
                    "body_suggestions": ["Chosen body", "Alt body"],
                },
            }
        ],
    }
    spec = _spec(adsets=[adset])
    creative = spec.adsets[0].ads[0].creative
    assert creative.title == "Chosen headline"
    assert creative.title_suggestions == ["Chosen headline", "Alt headline"]
    # The pool is not a variation list: publish sends the chosen copy alone, so
    # the creative stays an object_story_spec rather than an asset_feed_spec.
    assert creative.text_variations() == (["Chosen headline"], ["Chosen body"])
    # The ad-set wire payload never mentions suggestions or dynamic creative.
    payload = spec.adsets[0].to_payload(campaign_id="c1", ad_account_id="act_1")
    assert "is_dynamic_creative" not in payload
    assert "title_suggestions" not in str(payload)


def test_backfill_copy_suggestions_from_brief_for_stale_plan():
    # A plan checkpointed before the suggestion pool existed has a creative with no
    # *_suggestions. _plan_form_extra backfills them from the cached brief so the
    # editor dropdown appears without a rebuild — the published title/body are kept.
    from app.graph.builder.builder_node import _backfill_copy_suggestions

    plan = {
        "adsets": [
            {
                "ads": [
                    {"creative": {"title": "Head One", "body": "Body one text"}}
                ]
            }
        ]
    }
    brief = {
        "headline_suggestions": ["Head One", "Head Two", "Head Three", "Head Four"],
        "body_copy_suggestions": ["Body one text", "Body two text", "Body three text"],
    }
    _backfill_copy_suggestions(plan, brief)
    creative = plan["adsets"][0]["ads"][0]["creative"]
    assert creative["title"] == "Head One"       # published value untouched
    assert creative["body"] == "Body one text"
    assert creative["title_suggestions"] == [
        "Head One", "Head Two", "Head Three", "Head Four",
    ]
    assert creative["body_suggestions"] == [
        "Body one text", "Body two text", "Body three text",
    ]


def test_backfill_copy_suggestions_noop_when_present_or_brief_empty():
    from app.graph.builder.builder_node import _backfill_copy_suggestions

    # Existing suggestions are not overwritten.
    plan = {
        "adsets": [
            {"ads": [{"creative": {"title": "A", "body": "B",
                                   "title_suggestions": ["A", "Keep"]}}]}
        ]
    }
    _backfill_copy_suggestions(plan, {"headline_suggestions": ["A", "Other"]})
    assert plan["adsets"][0]["ads"][0]["creative"]["title_suggestions"] == ["A", "Keep"]

    # No brief candidates ⇒ nothing added (a single fallback is not a dropdown).
    plan2 = {"adsets": [{"ads": [{"creative": {"title": "A", "body": "B"}}]}]}
    _backfill_copy_suggestions(plan2, {})
    creative = plan2["adsets"][0]["ads"][0]["creative"]
    assert "title_suggestions" not in creative
    assert "body_suggestions" not in creative


# ── Ad format: carousel + instant form on the wire ─────────────────────────────


def _card(i: int) -> dict:
    return {
        "title": f"Card {i}",
        "body": f"desc {i}",
        "link": f"https://x.example/{i}",
        "image_hash": f"hash_{i}",
        "video_id": None,
    }


@pytest.mark.asyncio
async def test_carousel_sends_child_attachments_in_order(wire):
    w = wire({"id": "cr_carousel"})

    await meta_ads.create_ad_creative(
        name="Carousel Creative",
        page_id="pg_1",
        media_type="image",
        media_ref=None,
        title="t",
        body="primary text",
        cta_type="SHOP_NOW",
        link_url="https://x.example",
        ad_account_id="act_1",
        access_token="tok",
        ad_format="CAROUSEL",
        cards=[_card(1), _card(2), _card(3)],
    )

    link_data = w.body()["object_story_spec"]["link_data"]
    children = link_data["child_attachments"]
    assert len(children) == 3
    # Order is the plan's order — Meta renders the cards in the order it receives.
    assert [c["name"] for c in children] == ["Card 1", "Card 2", "Card 3"]
    assert [c["image_hash"] for c in children] == ["hash_1", "hash_2", "hash_3"]
    # A card's body is its small description line, not the ad's primary text.
    assert children[0]["description"] == "desc 1"
    assert link_data["message"] == "primary text"
    # No single-image reference leaks onto a carousel.
    assert "image_hash" not in link_data
    # Each card's BUTTON goes where the card goes. One shared CTA object sent
    # every card's click to the ad-level link, so a carousel with per-card
    # destinations (the editor lets you set one per card) misrouted every tap
    # but the first card's own.
    assert [c["call_to_action"]["value"]["link"] for c in children] == [
        "https://x.example/1", "https://x.example/2", "https://x.example/3",
    ]
    assert all(c["call_to_action"]["type"] == "SHOP_NOW" for c in children)


@pytest.mark.asyncio
async def test_carousel_cta_without_a_link_is_passed_through_untouched(wire):
    """A WhatsApp card's button carries an app_destination, not a link. Re-pointing
    it at the card would turn a Click-to-WhatsApp ad into a browser link."""
    w = wire({"id": "cr_wa"})

    await meta_ads.create_ad_creative(
        name="WA Carousel",
        page_id="pg_1",
        media_type="image",
        media_ref=None,
        title="t",
        body="b",
        cta_type="WHATSAPP_MESSAGE",
        link_url="https://api.whatsapp.com/send",
        ad_account_id="act_1",
        access_token="tok",
        ad_format="CAROUSEL",
        cards=[_card(1), _card(2)],
    )

    children = w.body()["object_story_spec"]["link_data"]["child_attachments"]
    assert all(
        c["call_to_action"]["value"] == {"app_destination": "WHATSAPP"} for c in children
    )


@pytest.mark.asyncio
async def test_carousel_without_cards_is_refused_before_the_request(wire):
    wire({"id": "never"})
    with pytest.raises(meta_ads.MetaAdsError, match="requires cards"):
        await meta_ads.create_ad_creative(
            name="Broken", page_id="pg_1", media_type="image", media_ref=None,
            title="t", body="b", cta_type="SHOP_NOW", link_url="https://x.example",
            ad_account_id="act_1", access_token="tok", ad_format="CAROUSEL", cards=[],
        )


@pytest.mark.asyncio
async def test_instant_form_cta_carries_the_form_not_a_link(wire):
    """An Instant Form ad's button opens the form. Sending a link there is
    ignored by Meta and misrepresents the ad in the plan."""
    w = wire({"id": "cr_lead"})

    await meta_ads.create_ad_creative(
        name="Lead Creative",
        page_id="pg_1",
        media_type="image",
        media_ref="hash_abc",
        title="t",
        body="b",
        cta_type="SIGN_UP",
        link_url="https://x.example",
        ad_account_id="act_1",
        access_token="tok",
        lead_gen_form_id="form-9",
    )

    cta = w.body()["object_story_spec"]["link_data"]["call_to_action"]
    assert cta["type"] == "SIGN_UP"
    assert cta["value"] == {"lead_gen_form_id": "form-9"}


@pytest.mark.asyncio
async def test_create_lead_form_sends_questions_and_privacy_policy(wire):
    w = wire({"id": "form-new"})

    form_id = await meta_ads.create_lead_form(
        "pg_1",
        name="Acme — Instant Form",
        questions=["FULL_NAME", "EMAIL"],
        privacy_policy_url="https://acme.example/privacy",
        access_token="tok",
        page_token="pt",
    )

    assert form_id == "form-new"
    assert w.path() == "/v23.0/pg_1/leadgen_forms" or w.path().endswith("/pg_1/leadgen_forms")
    body = w.body()
    assert body["questions"] == [{"type": "FULL_NAME"}, {"type": "EMAIL"}]
    # Meta rejects a lead form with no privacy policy.
    assert body["privacy_policy"]["url"] == "https://acme.example/privacy"


@pytest.mark.asyncio
async def test_lead_form_permission_error_is_translated(wire):
    """The raw Graph error names an OAuth scope, which means nothing to someone
    looking at a campaign form."""
    wire({"error": {"message": "(#200) permission", "code": 200}})

    with pytest.raises(meta_ads.MetaAdsError, match="Reconnect your Meta account"):
        await meta_ads.create_lead_form(
            "pg_1", name="F", questions=["EMAIL"],
            privacy_policy_url="https://x.example/p", access_token="tok",
            page_token="pt",
        )


@pytest.mark.asyncio
async def test_lead_form_carries_the_new_options(wire):
    """Higher intent adds Meta's review step; the follow-up URL used to be the
    privacy policy, which sent every new lead to a legal page; organic leads are
    blocked because they arrive without the campaign attribution being paid for."""
    w = wire({"id": "form_2"})

    await meta_ads.create_lead_form(
        "pg_1",
        name="F",
        questions=["EMAIL"],
        privacy_policy_url="https://acme.example/privacy",
        access_token="tok",
        page_token="pt",
        follow_up_url="https://acme.example",
        higher_intent=True,
    )

    body = w.body()
    assert body["is_optimized_for_quality"] is True
    assert body["follow_up_action_url"] == "https://acme.example"
    assert body["block_display_for_non_targeted_viewer"] is True


@pytest.mark.asyncio
async def test_form_leads_are_flattened_for_a_table(wire):
    """Meta returns field_data as [{name, values}]; a table or a CSV wants
    {question: answer}."""
    wire({"data": [
        {
            "id": "lead_1",
            "created_time": "2026-08-02T10:00:00+0000",
            "field_data": [
                {"name": "email", "values": ["a@b.example"]},
                {"name": "full_name", "values": ["Ada"]},
            ],
        }
    ]})

    leads = await meta_ads.fetch_form_leads("form_1", "tok")

    assert leads == [{
        "id": "lead_1",
        "created_time": "2026-08-02T10:00:00+0000",
        "fields": {"email": "a@b.example", "full_name": "Ada"},
    }]


@pytest.mark.asyncio
async def test_form_leads_degrade_to_empty(wire):
    wire({"error": {"message": "boom", "code": 100}})
    assert await meta_ads.fetch_form_leads("form_1", "tok") == []


# Every Page-owned read trades the user token for the Page's own via me/accounts
# first, so these tests script that hop ahead of the payload under test. See
# tests/test_page_token_trade.py for why the trade exists.
_ACCOUNTS = {"data": [{"id": "pg_1", "access_token": "page-tok"}]}


@pytest.mark.asyncio
async def test_page_objects_are_normalized_for_the_picker(wire):
    """Posts, videos and events carry their text and image under different keys;
    the picker renders one gallery."""
    w = wire(_ACCOUNTS, {"data": [
        {"id": "1_2", "message": "Our summer sale", "full_picture": "https://img/1",
         "created_time": "2026-07-01T00:00:00+0000"},
        {"id": "1_3"},
    ]})

    items = await meta_ads.list_page_objects("pg_1", "tok", kind="post")

    assert items[0]["label"] == "Our summer sale"
    assert items[0]["image"] == "https://img/1"
    assert items[1]["label"] == ""
    # The edge itself is read as the Page — with "tok" Meta answers (#210).
    assert w.token(1) == "page-tok"


@pytest.mark.asyncio
async def test_page_objects_degrade_to_empty(wire):
    wire(_ACCOUNTS, {"error": {"message": "no perms", "code": 200}})
    assert await meta_ads.list_page_objects("pg_1", "tok") == []


@pytest.mark.asyncio
async def test_boosted_post_creative_references_the_post_and_nothing_else(wire):
    """The ad IS the existing post — composing an object_story_spec alongside it
    would silently replace what the user picked."""
    w = wire({"id": "cr_9"})

    creative_id = await meta_ads.create_ad_creative(
        name="Boost",
        page_id="pg_1",
        media_type="image",
        media_ref=None,
        title="ignored",
        body="ignored",
        cta_type="LEARN_MORE",
        link_url="https://x.example",
        ad_account_id="act_1",
        access_token="tok",
        object_story_id="pg_1_555",
    )

    assert creative_id == "cr_9"
    body = w.body()
    assert body["object_story_id"] == "pg_1_555"
    assert "object_story_spec" not in body


@pytest.mark.asyncio
async def test_list_lead_forms_degrades_to_empty(wire):
    wire(_ACCOUNTS, {"error": {"message": "boom", "code": 100}})
    assert await meta_ads.list_lead_forms("pg_1", "tok") == []


@pytest.mark.asyncio
async def test_lead_forms_are_read_as_the_page(wire):
    """(#190) with the user token — the dropdown was empty for every advertiser."""
    w = wire(_ACCOUNTS, {"data": [{"id": "f_1", "name": "Contact us", "status": "ACTIVE"}]})

    forms = await meta_ads.list_lead_forms("pg_1", "tok")

    assert forms == [{"id": "f_1", "name": "Contact us", "status": "ACTIVE"}]
    assert w.path(1).endswith("/pg_1/leadgen_forms")
    assert w.token(1) == "page-tok"


# ── Publishing identity: Page, Instagram, WhatsApp ────────────────────────────


@pytest.mark.asyncio
async def test_pages_carry_their_instagram_account(wire):
    """The Page and its Instagram account are one decision — the Page you publish
    under decides the identity Instagram placements run as."""
    w = wire({"data": [
        {"id": "pg_1", "name": "Bean There",
         "instagram_business_account": {"id": "ig_77", "username": "beanthere"}},
        {"id": "pg_2", "name": "Bean There Roasters"},
    ]})

    pages = await meta_ads.list_meta_pages("tok")

    assert "instagram_business_account" in w.requests[0].url.params["fields"]
    assert pages == [
        {"id": "pg_1", "name": "Bean There",
         "instagram": {"id": "ig_77", "username": "beanthere"},
         "whatsapp": None},
        {"id": "pg_2", "name": "Bean There Roasters", "instagram": None,
         "whatsapp": None},
    ]


@pytest.mark.asyncio
async def test_pages_survive_a_token_without_the_instagram_scope(wire):
    """Tokens minted before instagram_basic was requested cannot read the IG edge.
    A Page list with no Instagram beats no Page list — that fallback is the only
    thing standing between an old token and an empty Page picker."""
    # Every rung carrying the IG edge is refused; the first one without it answers.
    w = wire(
        {"error": {"message": "(#278) instagram_basic required", "code": 278}},
        {"error": {"message": "(#278) instagram_basic required", "code": 278}},
        {"error": {"message": "(#278) instagram_basic required", "code": 278}},
        {"error": {"message": "(#278) instagram_basic required", "code": 278}},
        {"data": [{"id": "pg_1", "name": "Bean There", "whatsapp_number": "+15550101"}]},
    )

    pages = await meta_ads.list_meta_pages("tok")

    assert w.count == 5
    # The rung that answered still carried WhatsApp: the two edges are gated by
    # different scopes, so losing Instagram must not cost the WhatsApp answer.
    assert "instagram_business_account" not in w.requests[-1].url.params["fields"]
    assert "whatsapp_number" in w.requests[-1].url.params["fields"]
    assert pages == [{
        "id": "pg_1", "name": "Bean There", "instagram": None,
        "whatsapp": {"number": "+15550101"},
    }]


@pytest.mark.asyncio
async def test_pages_report_whatsapp_linkage_as_three_states(wire):
    """Linked / provably not linked / unreadable are three different answers.

    Click-to-WhatsApp is the one conversion location Meta refuses outright when
    the Page has no number, so the editor blocks on it — which makes conflating
    "no number" with "we could not look" a way to block a campaign that would
    have published fine. Absent key is the third state.
    """
    w = wire({"data": [
        {"id": "pg_1", "name": "Has a number", "whatsapp_number": "+15550101"},
        # The number lives on the business account here; Meta resolves it at
        # delivery, so a linked WABA counts as linked.
        {"id": "pg_2", "name": "Has a WABA",
         "connected_whatsapp_business_account": {"id": "waba_9"}},
        {"id": "pg_3", "name": "Has neither"},
    ]})

    pages = await meta_ads.list_meta_pages("tok")

    assert "whatsapp_number" in w.requests[0].url.params["fields"]
    assert [p["whatsapp"] for p in pages] == [
        {"number": "+15550101"}, {"number": ""}, None,
    ]


@pytest.mark.asyncio
async def test_pages_omit_whatsapp_when_it_could_not_be_read(wire):
    """A token that cannot read either WhatsApp field must not report "no number"
    — it reports nothing, and the editor leaves the plan alone."""
    w = wire(
        {"error": {"message": "(#278) permission required", "code": 278}},
        {"error": {"message": "(#278) permission required", "code": 278}},
        {"error": {"message": "(#278) permission required", "code": 278}},
        {"data": [{"id": "pg_1", "name": "Bean There"}]},
    )

    pages = await meta_ads.list_meta_pages("tok")

    assert w.count == 4
    assert "whatsapp" not in pages[0]


# ── Page readiness: published, and allowed to advertise ───────────────────────
# ``is_published`` and ``tasks`` exist on the me/accounts edge only (measured
# 2026-09-22). Same three-state contract as WhatsApp: a bool when Meta answered,
# ABSENT when it did not — absent must never read as "unpublished" or "no role".


@pytest.mark.asyncio
async def test_pages_report_published_and_advertising_role_when_read(wire):
    w = wire({"data": [
        {"id": "pg_1", "name": "Live", "is_published": True,
         "tasks": ["CREATE_CONTENT", "ADVERTISE", "MANAGE"]},
        {"id": "pg_2", "name": "Draft", "is_published": False, "tasks": ["ANALYZE"]},
        {"id": "pg_3", "name": "Admin only", "is_published": True, "tasks": ["MANAGE"]},
    ]})

    pages = await meta_ads.list_meta_pages("tok")

    fields = w.requests[0].url.params["fields"]
    assert "is_published" in fields and "tasks" in fields
    assert [(p["is_published"], p["can_advertise"]) for p in pages] == [
        (True, True), (False, False), (True, True),
    ]
    # Derived, not the raw list: this dict is streamed to the browser.
    assert not any("tasks" in p for p in pages)


@pytest.mark.asyncio
async def test_a_token_that_refuses_the_readiness_fields_keeps_everything_else(wire):
    """The new fields ride their own top rung, so refusing them costs one request and
    nothing else — Instagram and WhatsApp still come back, and nothing is invented."""
    w = wire(
        {"error": {"message": "(#10) not allowed", "code": 10}},
        {"data": [{"id": "pg_1", "name": "Bean There",
                   "instagram_business_account": {"id": "ig_77", "username": "bt"},
                   "whatsapp_number": "+15550101"}]},
    )

    pages = await meta_ads.list_meta_pages("tok")

    assert w.count == 2
    assert "is_published" not in w.requests[-1].url.params["fields"]
    assert pages == [{
        "id": "pg_1", "name": "Bean There",
        "instagram": {"id": "ig_77", "username": "bt"},
        "whatsapp": {"number": "+15550101"},
    }]
    assert "is_published" not in pages[0] and "can_advertise" not in pages[0]


@pytest.mark.asyncio
async def test_a_row_missing_the_fields_is_not_read_as_no(wire):
    """Asked for, but Meta left the key out of this row: unknown, not False."""
    wire({"data": [{"id": "pg_1", "name": "Bean There"}]})

    (page,) = await meta_ads.list_meta_pages("tok")

    assert "is_published" not in page and "can_advertise" not in page


@pytest.mark.asyncio
async def test_list_meta_pages_degrades_to_empty(wire):
    wire(
        {"error": {"message": "boom", "code": 100}},
        {"error": {"message": "boom", "code": 100}},
    )
    assert await meta_ads.list_meta_pages("tok") == []


@pytest.mark.asyncio
async def test_creative_carries_the_instagram_identity_at_top_level(wire):
    """``instagram_user_id`` is a creative field, not part of object_story_spec —
    Meta rejects it there. (It replaced ``instagram_actor_id`` on 2026-01-21.)"""
    w = wire({"id": "cr_ig"})

    await meta_ads.create_ad_creative(
        name="Creative",
        page_id="pg_1",
        media_type="image",
        media_ref="hash_abc",
        title="t",
        body="b",
        cta_type="LEARN_MORE",
        link_url="https://x.example",
        ad_account_id="act_1",
        access_token="tok",
        instagram_user_id="ig_77",
    )

    body = w.body()
    assert body["instagram_user_id"] == "ig_77"
    assert "instagram_user_id" not in body["object_story_spec"]


@pytest.mark.asyncio
async def test_creative_omits_the_instagram_identity_when_there_is_none(wire):
    """A Page with no linked Instagram account is normal. Sending an empty
    identity is not — Meta rejects it."""
    w = wire({"id": "cr_no_ig"})

    await meta_ads.create_ad_creative(
        name="Creative",
        page_id="pg_1",
        media_type="image",
        media_ref="hash_abc",
        title="t",
        body="b",
        cta_type="LEARN_MORE",
        link_url="https://x.example",
        ad_account_id="act_1",
        access_token="tok",
    )

    assert "instagram_user_id" not in w.body()


@pytest.mark.asyncio
async def test_whatsapp_cta_opens_the_app_not_a_link(wire):
    """Click-to-WhatsApp routes through app_destination, not the URL: Meta dials
    the number linked to the promoted Page. A link value here produces an ad that
    opens a browser instead of a conversation."""
    w = wire({"id": "cr_wa"})

    await meta_ads.create_ad_creative(
        name="WA Creative",
        page_id="pg_1",
        media_type="image",
        media_ref="hash_abc",
        title="t",
        body="b",
        cta_type="WHATSAPP_MESSAGE",
        link_url="https://api.whatsapp.com/send",
        ad_account_id="act_1",
        access_token="tok",
    )

    link_data = w.body()["object_story_spec"]["link_data"]
    assert link_data["call_to_action"] == {
        "type": "WHATSAPP_MESSAGE", "value": {"app_destination": "WHATSAPP"},
    }
    assert link_data["link"] == "https://api.whatsapp.com/send"


