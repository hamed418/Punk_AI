"""
scripts/live_publish_matrix.py
──────────────────────────────
Publish EVERY parameter and creative combination for real, verify it landed
PAUSED, then delete it.

``live_publish_test.py`` proves one campaign publishes end to end. This proves
the *combination space* does: every objective × conversion location ×
optimization goal the matrix offers, every billing event and bid strategy that
pairs with them, both budget models, the scheduling and frequency and attribution
extras, the special ad categories, the targeting shapes, and every creative
format — single image, single video, carousel, asset-feed text variations,
combined extra media, instant forms.

Each case is its own campaign, published through the real executor
(``publish_campaign_to_meta``), read back from Meta, and deleted before the next
one starts. One case failing therefore says exactly which combination is broken
and leaves nothing behind — which a single campaign carrying every ad set could
not do, because the executor rolls the whole campaign back when one ad set fails
preflight.

Safety, unchanged from live_publish_test.py:

  1. ``META_PUBLISH_ACTIVATE=false`` keeps the activation pass switched off, so
     nothing ever goes live. The script refuses to run without it, and asserts
     per case that Meta really reports PAUSED.
  2. ``geo_data`` carries no ``maid_extraction_id``, so no custom audience and no
     lookalike is created. Publishing without an audience is the point here.
  3. Everything created is left in the ad account PAUSED for inspection, and
     every id is recorded in the results JSON. ``--cleanup <results.json>``
     deletes it all again — campaigns (ad sets and ads go with them), any
     instant form created on the Page, and the draft rows in Postgres.
     ``--delete-after`` instead cleans up case by case as the run goes.

Budgets are real. They are also never spent: a PAUSED campaign does not deliver.

    .venv/Scripts/python.exe scripts/live_publish_matrix.py --user-id <uuid> --list
    .venv/Scripts/python.exe scripts/live_publish_matrix.py --user-id <uuid>
    .venv/Scripts/python.exe scripts/live_publish_matrix.py --user-id <uuid> --only carousel
    .venv/Scripts/python.exe scripts/live_publish_matrix.py --user-id <uuid> --from sales
    .venv/Scripts/python.exe scripts/live_publish_matrix.py --user-id <uuid> \
        --cleanup matrix_results.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.db import model_registry  # noqa: F401,E402  — registers every ORM model
from app.graph.builder.executors.media import (  # noqa: E402
    MetaPublishError,
    publish_campaign_to_meta,
)
from app.graph.meta_spec import CampaignSpec  # noqa: E402
from app.graph.meta_spec.enums import (  # noqa: E402
    AdFormat,
    BidStrategy,
    BillingEvent,
    CallToAction,
    DestinationType,
    Objective,
    OptimizationGoal,
    SpecialAdCategory,
)
from app.graph.meta_spec.models import (  # noqa: E402
    AdSetSpec,
    AdSpec,
    AttributionWindow,
    BidConstraints,
    BudgetScheduleSpec,
    CarouselCard,
    CreativeSpec,
    DayPartSpec,
    FrequencyControlSpec,
    LeadFormQuestionSpec,
    LeadFormSpec,
    MediaRef,
    PromotedObject,
    min_budget_cents,
)
from app.graph.meta_spec.objective_matrix import (  # noqa: E402
    DEFAULT_PIXEL_EVENT,
    PROMOTED_APPLICATION,
    PROMOTED_PAGE,
    PROMOTED_PIXEL,
    rules_for,
)
from app.services import meta_ads as _meta  # noqa: E402
from app.services.oauth import get_meta_credentials  # noqa: E402

_O, _B, _D, _S, _A, _F = (
    OptimizationGoal, BillingEvent, DestinationType, BidStrategy, CallToAction, AdFormat,
)

# Sleep between cases. Publishing is ~10 Graph writes per case and Meta throttles
# an ad account on a rolling score, not a fixed rate — the executor already backs
# off on the throttle codes, this just keeps the score from climbing there.
# Measured on a new ad account: 1.5s was far too fast, subcode 2446079 ("User
# request limit reached") landed on the fifth case; 8s still exhausted a budget
# already spent by an earlier run. A case is ~10 writes, so this is the knob to
# turn when a sweep keeps stalling — the limit is a rolling budget, not a rate.
_PACE_S = 15.0

# How long to stand down when the ad account throttles anyway, and how many times.
# The limit is a rolling budget that decays, so waiting is the only fix — and the
# retry reuses the case's thread id, so the ledger RESUMES the half-built campaign
# instead of building a second one. That is the resume path, exercised for real.
_THROTTLE_SLEEP_S = 420.0
_THROTTLE_RETRIES = 2


def _is_throttle(exc: BaseException) -> bool:
    code = getattr(exc, "code", None) or getattr(getattr(exc, "__cause__", None), "code", None)
    return code in (2446079, 4, 17, 32, 613) or "request limit" in str(exc).lower()


# ── shared context ───────────────────────────────────────────────────────────


@dataclass
class Ctx:
    """Everything the cases build specs out of. Assets are uploaded once."""

    floor: int                     # min daily budget, account's minor units
    website: str
    page_id: str | None
    pixel_id: str | None
    app_id: str | None
    store_url: str
    image_a: str                   # Meta image hashes, pre-uploaded
    image_b: str
    image_c: str
    video_id: str | None           # Meta video id, already processed
    media_uuid: str | None         # a Punk MediaFile UUID (exercises the R2 path)
    # Existing Page objects the boost destinations promote. Discovered read-only
    # with the Page access token; nothing is ever posted to the Page.
    post_id: str | None = None
    video_post_id: str | None = None
    event_id: str | None = None
    caps: set[str] = field(default_factory=set)

    @property
    def start(self) -> datetime:
        return datetime.now(timezone.utc) + timedelta(days=1)

    @property
    def end(self) -> datetime:
        return datetime.now(timezone.utc) + timedelta(days=15)

    @property
    def daily(self) -> int:
        # Six times the account floor, not two. ``min_daily_budget`` is the
        # IMPRESSION-billed minimum; a click-billed ad set on the same account is
        # rejected under roughly five times it ("Your ad set budget must be more
        # than CA$7.08" where min_daily_budget says CA$1.42). Sized to clear both
        # so a budget floor cannot masquerade as a combination failure.
        return self.floor * 6

    @property
    def lifetime(self) -> int:
        return self.floor * 40


# ── spec construction helpers ────────────────────────────────────────────────


def _promoted(ctx: Ctx, objective: Objective, dest, goal: OptimizationGoal) -> PromotedObject | None:
    """The promoted_object this (destination, goal) pair demands, from real ids."""
    kind = dest.promoted_object_kind(goal)
    if kind == PROMOTED_PAGE:
        return PromotedObject(page_id=ctx.page_id)
    if kind == PROMOTED_PIXEL:
        return PromotedObject(
            pixel_id=ctx.pixel_id,
            custom_event_type=DEFAULT_PIXEL_EVENT.get(objective, "LEAD"),
        )
    if kind == PROMOTED_APPLICATION:
        return PromotedObject(application_id=ctx.app_id, object_store_url=ctx.store_url)
    return None


def creative(
    ctx: Ctx,
    cta: CallToAction,
    *,
    title: str = "Matrix test headline",
    body: str = "Published by the live matrix runner and deleted again.",
    video: bool = False,
    **kw: Any,
) -> CreativeSpec:
    """A single-asset creative. ``kw`` overrides anything on CreativeSpec."""
    if not any(k in kw for k in ("image_hash", "video_id", "media_id", "cards")):
        kw["video_id" if video else "image_hash"] = ctx.video_id if video else ctx.image_a
    kw.setdefault("link", ctx.website)
    return CreativeSpec(title=title, body=body, call_to_action=cta, **kw)


def adset(
    ctx: Ctx,
    objective: Objective,
    dest_type: DestinationType,
    goal: OptimizationGoal,
    *,
    name: str = "Matrix ad set",
    billing: BillingEvent | None = None,
    bid_strategy: BidStrategy = _S.LOWEST_COST_WITHOUT_CAP,
    cta: CallToAction | None = None,
    ads: list[AdSpec] | None = None,
    targeting: dict | None = None,
    budget: str = "daily",          # "daily" | "lifetime" | "none" (CBO)
    **kw: Any,
) -> AdSetSpec:
    """One ad set with the matrix's own defaults filled in for this combination."""
    _, dest = rules_for(objective, dest_type)
    cta = cta or dest.default_call_to_action
    if budget == "daily":
        kw.setdefault("daily_budget", ctx.daily)
    elif budget == "lifetime":
        kw.setdefault("lifetime_budget", ctx.lifetime)
        kw.setdefault("end_time", ctx.end)
    kw.setdefault("promoted_object", _promoted(ctx, objective, dest, goal))
    return AdSetSpec(
        name=name,
        optimization_goal=goal,
        billing_event=billing or dest.default_billing_event,
        destination_type=dest_type,
        bid_strategy=bid_strategy,
        targeting=targeting or {"geo_locations": {"countries": ["US"]}},
        start_time=ctx.start,
        ads=ads or [AdSpec(name="Matrix ad", creative=creative(ctx, cta))],
        **kw,
    )


def campaign(
    ctx: Ctx, objective: Objective, adsets: list[AdSetSpec], **kw: Any
) -> CampaignSpec:
    return CampaignSpec(
        name="placeholder",           # replaced per run, see _run_case
        objective=objective,
        special_ad_categories=kw.pop("special_ad_categories", []),
        page_id=ctx.page_id,
        adsets=adsets,
        **kw,
    )


def simple(
    objective: Objective,
    dest_type: DestinationType,
    goal: OptimizationGoal,
    **kw: Any,
) -> Callable[[Ctx], CampaignSpec]:
    """The common case: one campaign, one ad set, one single-image ad."""
    def build(ctx: Ctx) -> CampaignSpec:
        return campaign(ctx, objective, [adset(ctx, objective, dest_type, goal, **kw)])
    return build


# ── the case list ────────────────────────────────────────────────────────────


@dataclass
class Case:
    id: str
    what: str
    build: Callable[[Ctx], CampaignSpec]
    # Account capabilities this case cannot run without. Missing one is a SKIP
    # with a named reason, not a failure — the ad account, not the code, is what
    # is short.
    needs: tuple[str, ...] = ()
    # Asset-feed shapes to expect at Meta, ``(titles, bodies, media)`` per ad, when
    # they differ from what the plan asks for. Only set where Meta itself keeps
    # less than it was sent — the drop is the documented behaviour under test, not
    # a bug this run should report every time.
    expect_feeds: tuple[tuple[int, int, int], ...] | None = None


def _cases() -> list[Case]:
    C = Case
    return [
        # ── objective × conversion location × optimization goal ───────────────
        C("awareness.reach", "Awareness → Website, Reach",
          simple(Objective.AWARENESS, _D.WEBSITE, _O.REACH)),
        C("awareness.impressions", "Awareness → Website, Impressions",
          simple(Objective.AWARENESS, _D.WEBSITE, _O.IMPRESSIONS)),
        C("awareness.ad_recall", "Awareness → Website, Ad recall lift",
          simple(Objective.AWARENESS, _D.WEBSITE, _O.AD_RECALL_LIFT)),
        C("awareness.thruplay", "Awareness → Website, ThruPlay + video + ThruPlay billing",
          lambda ctx: campaign(ctx, Objective.AWARENESS, [adset(
              ctx, Objective.AWARENESS, _D.WEBSITE, _O.THRUPLAY,
              billing=_B.THRUPLAY, bid_strategy=_S.LOWEST_COST_WITHOUT_CAP,
              ads=[AdSpec(name="Video ad", creative=creative(
                  ctx, _A.WATCH_MORE, video=True))],
          )]), needs=("video",)),

        C("traffic.link_clicks", "Traffic → Website, Link clicks (CPM)",
          simple(Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS)),
        C("traffic.link_clicks.cpc", "Traffic → Website, Link clicks billed per click",
          simple(Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS, billing=_B.LINK_CLICKS)),
        C("traffic.landing_page_views", "Traffic → Website, Landing page views",
          simple(Objective.TRAFFIC, _D.WEBSITE, _O.LANDING_PAGE_VIEWS)),
        C("traffic.reach", "Traffic → Website, Reach",
          simple(Objective.TRAFFIC, _D.WEBSITE, _O.REACH)),
        C("traffic.impressions", "Traffic → Website, Impressions",
          simple(Objective.TRAFFIC, _D.WEBSITE, _O.IMPRESSIONS)),
        C("traffic.ig_profile", "Traffic → Instagram profile, Profile visits",
          simple(Objective.TRAFFIC, _D.INSTAGRAM_PROFILE, _O.VISIT_INSTAGRAM_PROFILE)),
        C("traffic.ig_profile.clicks", "Traffic → Instagram profile, Link clicks",
          simple(Objective.TRAFFIC, _D.INSTAGRAM_PROFILE, _O.LINK_CLICKS)),
        C("traffic.app", "Traffic → App store listing, Link clicks",
          lambda ctx: campaign(ctx, Objective.TRAFFIC, [adset(
              ctx, Objective.TRAFFIC, _D.APP, _O.LINK_CLICKS,
              cta=_A.INSTALL_MOBILE_APP,
              ads=[AdSpec(name="App ad", creative=creative(
                  ctx, _A.INSTALL_MOBILE_APP, link=ctx.store_url))],
          )])),
        C("traffic.messenger", "Traffic → Messenger, Link clicks",
          simple(Objective.TRAFFIC, _D.MESSENGER, _O.LINK_CLICKS), needs=("page",)),
        C("traffic.messenger.reach", "Traffic → Messenger, Reach",
          simple(Objective.TRAFFIC, _D.MESSENGER, _O.REACH), needs=("page",)),
        C("traffic.whatsapp", "Traffic → WhatsApp, Link clicks (Page promoted)",
          simple(Objective.TRAFFIC, _D.WHATSAPP, _O.LINK_CLICKS), needs=("page",)),

        # No POST_ENGAGEMENT on Website. Measured on two accounts: accepted at
        # preflight, then rejected at AD creation (subcode 1885154) because a
        # website link ad has no post to engage with. It is gone from that
        # conversion location; engagement.boost_post below covers the goal where
        # it does publish.
        # No POST_ENGAGEMENT-billed case. Four DestinationRules offer that billing
        # event, but no GoalRules accepts it — GOAL_RULES pins POST_ENGAGEMENT,
        # EVENT_RESPONSES and PAGE_LIKES to impressions (or per-like), so the
        # intersection makes it unreachable for every objective. The option is dead
        # in the editor rather than wrong at Meta; see the run notes.
        C("engagement.link_clicks", "Engagement → Website, Link clicks",
          simple(Objective.ENGAGEMENT, _D.WEBSITE, _O.LINK_CLICKS)),
        C("engagement.reach", "Engagement → Website, Reach",
          simple(Objective.ENGAGEMENT, _D.WEBSITE, _O.REACH)),
        C("engagement.messenger", "Engagement → Messenger, Conversations",
          simple(Objective.ENGAGEMENT, _D.MESSENGER, _O.CONVERSATIONS), needs=("page",)),
        C("engagement.whatsapp", "Engagement → WhatsApp, Conversations",
          simple(Objective.ENGAGEMENT, _D.WHATSAPP, _O.CONVERSATIONS), needs=("page",)),
        C("engagement.page_likes", "Engagement → Facebook Page, Page likes (per-like billing)",
          simple(Objective.ENGAGEMENT, _D.ON_PAGE, _O.PAGE_LIKES, billing=_B.PAGE_LIKES),
          needs=("page",)),
        C("engagement.boost_post", "Engagement → boost an existing Page post",
          lambda ctx: campaign(ctx, Objective.ENGAGEMENT, [adset(
              ctx, Objective.ENGAGEMENT, _D.ON_POST, _O.POST_ENGAGEMENT,
              ads=[AdSpec(name="Boosted post", creative=creative(
                  ctx, _A.LEARN_MORE, image_hash=None,
                  object_story_id=ctx.post_id))],
          )]), needs=("post",)),
        C("engagement.boost_video", "Engagement → boost an existing Page video",
          lambda ctx: campaign(ctx, Objective.ENGAGEMENT, [adset(
              ctx, Objective.ENGAGEMENT, _D.ON_VIDEO, _O.THRUPLAY,
              ads=[AdSpec(name="Boosted video", creative=creative(
                  ctx, _A.WATCH_MORE, image_hash=None, media_kind="video",
                  object_story_id=ctx.video_post_id))],
          )]), needs=("video_post",)),
        C("engagement.boost_event", "Engagement → boost a Facebook event",
          lambda ctx: campaign(ctx, Objective.ENGAGEMENT, [adset(
              ctx, Objective.ENGAGEMENT, _D.ON_EVENT, _O.EVENT_RESPONSES,
              ads=[AdSpec(name="Boosted event", creative=creative(
                  ctx, _A.EVENT_RSVP, image_hash=None,
                  object_story_id=ctx.event_id))],
          )]), needs=("event",)),

        C("leads.instant_form", "Leads → Instant form (form generated at publish)",
          simple(Objective.LEADS, _D.ON_AD, _O.LEAD_GENERATION), needs=("page",)),
        C("leads.instant_form.drafted", "Leads → Instant form from a drafted form, higher intent",
          lambda ctx: campaign(ctx, Objective.LEADS, [adset(
              ctx, Objective.LEADS, _D.ON_AD, _O.QUALITY_LEAD,
              lead_form_draft=LeadFormSpec(
                  name="Matrix drafted form",
                  questions=[
                      LeadFormQuestionSpec(type="FULL_NAME"),
                      LeadFormQuestionSpec(type="EMAIL"),
                      LeadFormQuestionSpec(
                          type="CUSTOM", label="Which service are you after?",
                          options=["Consulting", "Support"],
                      ),
                  ],
                  privacy_policy_url=ctx.website,
                  intro_title="Tell us what you need",
                  intro_body=["Quick form", "We reply same day"],
                  higher_intent=True,
              ),
          )]), needs=("page",)),
        C("leads.website.conversions", "Leads → Website, Offsite conversions + pixel + attribution",
          lambda ctx: campaign(ctx, Objective.LEADS, [adset(
              ctx, Objective.LEADS, _D.WEBSITE, _O.OFFSITE_CONVERSIONS,
              attribution_spec=[
                  AttributionWindow(event_type="CLICK_THROUGH", window_days=7),
                  AttributionWindow(event_type="VIEW_THROUGH", window_days=1),
              ],
          )]), needs=("pixel",)),
        C("leads.website.lpv", "Leads → Website, Landing page views",
          simple(Objective.LEADS, _D.WEBSITE, _O.LANDING_PAGE_VIEWS)),
        C("leads.website.link_clicks", "Leads → Website, Link clicks",
          simple(Objective.LEADS, _D.WEBSITE, _O.LINK_CLICKS)),
        C("leads.messenger", "Leads → Messenger, Lead generation",
          simple(Objective.LEADS, _D.MESSENGER, _O.LEAD_GENERATION), needs=("page",)),
        C("leads.whatsapp", "Leads → WhatsApp, Conversations",
          simple(Objective.LEADS, _D.WHATSAPP, _O.CONVERSATIONS), needs=("page",)),

        C("app.installs", "App promotion → App installs",
          lambda ctx: campaign(ctx, Objective.APP_PROMOTION, [adset(
              ctx, Objective.APP_PROMOTION, _D.APP, _O.APP_INSTALLS,
              ads=[AdSpec(name="Install ad", creative=creative(
                  ctx, _A.INSTALL_MOBILE_APP, link=ctx.store_url))],
          )]), needs=("app",)),
        # No per-install-billed case. Meta retired the billing event — "CPA
        # billing is no longer available. Select impressions to avoid making
        # changes later" — so GOAL_RULES no longer offers it and a spec carrying
        # it is rejected locally. test_live_publish_regressions covers the
        # retirement; publishing it again would only re-prove our own validator.

        C("sales.conversions", "Sales → Website, Offsite conversions + Purchase pixel",
          simple(Objective.SALES, _D.WEBSITE, _O.OFFSITE_CONVERSIONS), needs=("pixel",)),
        C("sales.value.roas", "Sales → Website, Value + minimum ROAS bid strategy",
          lambda ctx: campaign(ctx, Objective.SALES, [adset(
              ctx, Objective.SALES, _D.WEBSITE, _O.VALUE,
              bid_strategy=_S.LOWEST_COST_WITH_MIN_ROAS,
              bid_constraints=BidConstraints(roas_average_floor=15000),
          )]), needs=("pixel",)),
        C("sales.lpv", "Sales → Website, Landing page views",
          simple(Objective.SALES, _D.WEBSITE, _O.LANDING_PAGE_VIEWS)),
        C("sales.link_clicks.cpc", "Sales → Website, Link clicks billed per click",
          simple(Objective.SALES, _D.WEBSITE, _O.LINK_CLICKS, billing=_B.LINK_CLICKS)),
        C("sales.reach", "Sales → Website, Reach",
          simple(Objective.SALES, _D.WEBSITE, _O.REACH)),
        C("sales.app", "Sales → App, Offsite conversions on the app",
          lambda ctx: campaign(ctx, Objective.SALES, [adset(
              ctx, Objective.SALES, _D.APP, _O.OFFSITE_CONVERSIONS,
              ads=[AdSpec(name="App sales ad", creative=creative(
                  ctx, _A.SHOP_NOW, link=ctx.store_url))],
          )]), needs=("app",)),
        # No Sales → App VALUE case. Published once for real and rejected at ad set
        # creation, subcode 2490408 blaming optimization_goal ("Performance goal
        # isn't available"): value optimization needs a pixel reporting purchase
        # values, which an app destination has none of. The goal is gone from that
        # DestinationRules, so the spec is now rejected locally —
        # test_live_publish_regressions covers it.
        C("sales.messenger", "Sales → Messenger, Conversations",
          simple(Objective.SALES, _D.MESSENGER, _O.CONVERSATIONS), needs=("page",)),
        C("sales.whatsapp", "Sales → WhatsApp, Conversations",
          simple(Objective.SALES, _D.WHATSAPP, _O.CONVERSATIONS), needs=("page",)),

        # ── bid strategies ───────────────────────────────────────────────────
        C("bid.cost_cap", "Bid strategy: cost cap + bid amount",
          simple(Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
                 bid_strategy=_S.COST_CAP, bid_amount=200)),
        C("bid.bid_cap", "Bid strategy: bid cap + bid amount",
          simple(Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
                 bid_strategy=_S.LOWEST_COST_WITH_BID_CAP, bid_amount=150)),

        # ── budget models ────────────────────────────────────────────────────
        C("budget.abo.daily.multi", "ABO: three ad sets, different daily budgets",
          lambda ctx: campaign(ctx, Objective.TRAFFIC, [
              adset(ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
                    name="Ad set A", daily_budget=ctx.floor * 2),
              adset(ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LANDING_PAGE_VIEWS,
                    name="Ad set B", daily_budget=ctx.floor * 3),
              adset(ctx, Objective.TRAFFIC, _D.WEBSITE, _O.REACH,
                    name="Ad set C", daily_budget=ctx.floor * 5),
          ])),
        C("budget.abo.lifetime", "ABO: lifetime budget with an end date",
          simple(Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS, budget="lifetime")),
        C("budget.abo.lifetime.dayparting", "ABO lifetime + ad scheduling (dayparting)",
          simple(Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS, budget="lifetime",
                 adset_schedule=[
                     DayPartSpec(days=[1, 2, 3, 4, 5], start_minute=540, end_minute=1080),
                     DayPartSpec(days=[0, 6], start_minute=600, end_minute=1320),
                 ])),
        C("budget.abo.daily.schedule", "ABO daily + a scheduled budget increase",
          lambda ctx: campaign(ctx, Objective.TRAFFIC, [adset(
              ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
              budget_schedule_specs=[BudgetScheduleSpec(
                  time_start=ctx.start + timedelta(days=2),
                  time_end=ctx.start + timedelta(days=4),
                  budget_value=200, budget_value_type="MULTIPLIER",
              )],
          )])),
        # Both ad sets share one optimization goal: Meta requires it under a
        # lowest-cost campaign budget, and mixing them is now a spec error rather
        # than a half-built campaign.
        C("budget.cbo.daily", "CBO: campaign daily budget across two ad sets",
          lambda ctx: campaign(
              ctx, Objective.TRAFFIC,
              [adset(ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
                     name="CBO A", budget="none"),
               adset(ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
                     name="CBO B", budget="none")],
              daily_budget=ctx.floor * 6, bid_strategy=_S.LOWEST_COST_WITHOUT_CAP,
          )),
        C("budget.cbo.lifetime", "CBO: campaign lifetime budget, both ad sets ending",
          lambda ctx: campaign(
              ctx, Objective.TRAFFIC,
              [adset(ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
                     name="CBO A", budget="none", end_time=ctx.end),
               adset(ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
                     name="CBO B", budget="none", end_time=ctx.end)],
              lifetime_budget=ctx.floor * 60, bid_strategy=_S.LOWEST_COST_WITHOUT_CAP,
          )),
        C("budget.cbo.cost_cap", "CBO with a campaign cost cap and per-ad-set amounts",
          lambda ctx: campaign(
              ctx, Objective.TRAFFIC,
              # The ad set mirrors the campaign's capped strategy: to_payload
              # strips bid_strategy under CBO, but AdSetSpec will not carry a
              # bid_amount beside an uncapped strategy.
              [adset(ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
                     name="Capped A", budget="none",
                     bid_strategy=_S.COST_CAP, bid_amount=200),
               adset(ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LANDING_PAGE_VIEWS,
                     name="Capped B", budget="none",
                     bid_strategy=_S.COST_CAP, bid_amount=250)],
              daily_budget=ctx.floor * 6, bid_strategy=_S.COST_CAP,
          )),
        C("budget.abo.sharing", "ABO with ad set budget sharing enabled",
          lambda ctx: campaign(
              ctx, Objective.TRAFFIC,
              [adset(ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS, name="Share A"),
               adset(ctx, Objective.TRAFFIC, _D.WEBSITE, _O.REACH, name="Share B")],
              # Meta wants a campaign-level strategy beside the sharing flag.
              # Mixed goals are fine here: the same-goal rule belongs to a
              # campaign BUDGET, and this plan is ABO.
              is_adset_budget_sharing_enabled=True,
              bid_strategy=_S.LOWEST_COST_WITHOUT_CAP,
          )),

        # ── frequency caps ───────────────────────────────────────────────────
        C("extras.frequency.reach", "Awareness Reach + frequency cap",
          simple(Objective.AWARENESS, _D.WEBSITE, _O.REACH,
                 frequency_control_specs=[
                     FrequencyControlSpec(interval_days=7, max_frequency=2)])),
        C("extras.frequency.thruplay", "Awareness ThruPlay + frequency cap + video",
          lambda ctx: campaign(ctx, Objective.AWARENESS, [adset(
              ctx, Objective.AWARENESS, _D.WEBSITE, _O.THRUPLAY,
              frequency_control_specs=[
                  FrequencyControlSpec(interval_days=3, max_frequency=1)],
              ads=[AdSpec(name="Video ad", creative=creative(
                  ctx, _A.WATCH_VIDEO, video=True))],
          )]), needs=("video",)),

        # ── targeting shapes ─────────────────────────────────────────────────
        C("targeting.zips", "Targeting: US ZIP codes (the product's own geo shape)",
          simple(Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS, targeting={
              "geo_locations": {"zips": [
                  {"key": "US:90210"}, {"key": "US:10001"}, {"key": "US:60601"},
              ]}})),
        C("targeting.radius_pin", "Targeting: latitude/longitude radius pin",
          simple(Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS, targeting={
              "geo_locations": {"custom_locations": [
                  {"latitude": 43.6532, "longitude": -79.3832,
                   "radius": 10, "distance_unit": "mile"},
              ]}})),
        C("targeting.multi_country", "Targeting: US + Canada together",
          simple(Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS, targeting={
              "geo_locations": {"countries": ["US", "CA"]}})),
        C("targeting.demographics", "Targeting: age, gender and locales",
          simple(Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS, targeting={
              "geo_locations": {"countries": ["CA"]},
              "age_min": 25, "age_max": 54, "genders": [2], "locales": [6],
          })),
        C("targeting.placements", "Targeting: explicit platforms, positions and devices",
          simple(Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS, targeting={
              "geo_locations": {"countries": ["US"]},
              "publisher_platforms": ["facebook", "instagram"],
              "facebook_positions": ["feed", "story", "facebook_reels"],
              "instagram_positions": ["stream", "story", "reels"],
              "device_platforms": ["mobile", "desktop"],
          })),
        C("targeting.exclusions", "Targeting: an excluded geography",
          simple(Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS, targeting={
              "geo_locations": {"countries": ["US"]},
              "excluded_geo_locations": {"zips": [{"key": "US:90210"}]},
          })),
        C("targeting.interests", "Targeting: detailed interests (flexible_spec)",
          lambda ctx: campaign(ctx, Objective.TRAFFIC, [adset(
              ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
              targeting={
                  "geo_locations": {"countries": ["US"]},
                  "flexible_spec": [{"interests": _INTERESTS}],
              },
          )]), needs=("interests",)),
        # Behaviours live in their own flexible_spec bucket, not under interests —
        # Meta's typeahead says which bucket an id belongs to (``flex_field``), and
        # sending a behaviour id as an interest is silently accepted and ignored.
        C("targeting.behaviors", "Targeting: detailed behaviours (flexible_spec)",
          lambda ctx: campaign(ctx, Objective.TRAFFIC, [adset(
              ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
              targeting={
                  "geo_locations": {"countries": ["US"]},
                  "flexible_spec": [{"behaviors": _BEHAVIORS}],
              },
          )]), needs=("behaviors",)),

        # ── special ad categories ────────────────────────────────────────────
        C("special.employment", "Special ad category: Employment (CA)",
          lambda ctx: campaign(
              ctx, Objective.TRAFFIC,
              [adset(ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
                     targeting={"geo_locations": {"countries": ["CA"]}})],
              special_ad_categories=[SpecialAdCategory.EMPLOYMENT],
              special_ad_category_country=["CA"],
          )),
        C("special.housing", "Special ad category: Housing (US)",
          lambda ctx: campaign(
              ctx, Objective.TRAFFIC,
              [adset(ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
                     targeting={"geo_locations": {"countries": ["US"]}})],
              special_ad_categories=[SpecialAdCategory.HOUSING],
              special_ad_category_country=["US"],
          )),
        C("special.financial", "Special ad category: Financial products (CA)",
          lambda ctx: campaign(
              ctx, Objective.TRAFFIC,
              [adset(ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
                     targeting={"geo_locations": {"countries": ["CA"]}})],
              special_ad_categories=[SpecialAdCategory.FINANCIAL_PRODUCTS_SERVICES],
              special_ad_category_country=["CA"],
          )),

        # ── creatives ────────────────────────────────────────────────────────
        C("creative.image_hash", "Creative: single image from a pre-uploaded hash",
          simple(Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS)),
        C("creative.media_id", "Creative: single image resolved from a Punk media id (R2)",
          lambda ctx: campaign(ctx, Objective.TRAFFIC, [adset(
              ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
              ads=[AdSpec(name="R2 ad", creative=creative(
                  ctx, _A.LEARN_MORE, media_id=ctx.media_uuid, media_kind="image"))],
          )]), needs=("media_uuid",)),
        C("creative.video", "Creative: single video ad",
          lambda ctx: campaign(ctx, Objective.TRAFFIC, [adset(
              ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
              ads=[AdSpec(name="Video ad", creative=creative(
                  ctx, _A.WATCH_MORE, video=True))],
          )]), needs=("video",)),
        C("creative.carousel2", "Creative: two-card image carousel",
          lambda ctx: campaign(ctx, Objective.TRAFFIC, [adset(
              ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
              ads=[AdSpec(name="Carousel ad", creative=creative(
                  ctx, _A.SHOP_NOW, format=_F.CAROUSEL, cards=[
                      CarouselCard(title="Card one", body="First card",
                                   link=ctx.website, image_hash=ctx.image_a),
                      CarouselCard(title="Card two", body="Second card",
                                   link=ctx.website, image_hash=ctx.image_b),
                  ]))],
          )])),
        C("creative.carousel5", "Creative: five-card carousel",
          lambda ctx: campaign(ctx, Objective.TRAFFIC, [adset(
              ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
              ads=[AdSpec(name="Carousel ad", creative=creative(
                  ctx, _A.LEARN_MORE, format=_F.CAROUSEL, cards=[
                      CarouselCard(title=f"Card {i + 1}", body=f"Card {i + 1} body",
                                   link=ctx.website,
                                   image_hash=[ctx.image_a, ctx.image_b, ctx.image_c][i % 3])
                      for i in range(5)
                  ]))],
          )])),
        C("creative.carousel.video_card", "Creative: carousel mixing an image and a video card",
          lambda ctx: campaign(ctx, Objective.TRAFFIC, [adset(
              ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
              ads=[AdSpec(name="Mixed carousel", creative=creative(
                  ctx, _A.LEARN_MORE, format=_F.CAROUSEL, cards=[
                      CarouselCard(title="Image card", body="Still",
                                   link=ctx.website, image_hash=ctx.image_a),
                      CarouselCard(title="Video card", body="Moving",
                                   link=ctx.website, video_id=ctx.video_id),
                  ]))],
          )]), needs=("video",)),
        # A VIDEO ad that also varies its copy. The feed must carry the copy and
        # NOT the video (the video rides object_story_spec.video_data) — Meta never
        # stores `videos` in a feed, and sending them made the read-back report a
        # loss that had not happened on every video ad with a second headline.
        C("creative.video_text_variations",
          "Creative: video ad with headline variations (feed carries copy only)",
          lambda ctx: campaign(ctx, Objective.TRAFFIC, [adset(
              ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
              ads=[AdSpec(name="Video variations ad", creative=creative(
                  ctx, _A.WATCH_MORE, video=True,
                  title_variants=["Second headline"]))],
          )]), needs=("video",)),
        C("creative.text_variations", "Creative: headline and body variations (asset feed)",
          lambda ctx: campaign(ctx, Objective.TRAFFIC, [adset(
              ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
              ads=[AdSpec(name="Variations ad", creative=creative(
                  ctx, _A.LEARN_MORE,
                  title_variants=["Second headline", "Third headline"],
                  body_variants=["A second body line.", "A third body line."],
              ))],
          )])),
        # The second headline is not decoration: Meta accepts a feed whose only
        # multi-valued field is media and then stores no feed at all, so combined
        # media only survives on an ad that also varies its copy.
        C("creative.extra_media", "Creative: three images combined into one ad",
          lambda ctx: campaign(ctx, Objective.TRAFFIC, [adset(
              ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
              ads=[AdSpec(name="Multi-media ad", creative=creative(
                  ctx, _A.LEARN_MORE, title_variants=["Second headline"],
                  extra_media=[
                      MediaRef(image_hash=ctx.image_b, media_kind="image"),
                      MediaRef(image_hash=ctx.image_c, media_kind="image"),
                  ]))],
          )])),
        # The reported bug, as a live case: several images on an ad the user gave
        # ONE headline and ONE body. Meta discards a media-only feed whole (a 200
        # and an ad running one image), so ``text_variations`` borrows a second
        # headline from the AI's suggestions. Publishing 3 media proves the borrow
        # happened — without it this case comes back with no feed at all.
        C("creative.extra_media.solo",
          "Creative: three images on an ad with one headline (feed must survive)",
          lambda ctx: campaign(ctx, Objective.TRAFFIC, [adset(
              ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
              ads=[AdSpec(name="Solo-copy multi-media ad", creative=creative(
                  ctx, _A.LEARN_MORE,
                  title_suggestions=["Borrowed headline", "Another idea"],
                  extra_media=[
                      MediaRef(image_hash=ctx.image_b, media_kind="image"),
                      MediaRef(image_hash=ctx.image_c, media_kind="image"),
                  ]))],
          )])),
        # No mixed-media case any more: CreativeSpec rejects an ad that combines a
        # video with other media, because Meta strips `videos` out of every asset
        # feed it is sent (scripts/probe_mixed_feed.py). That rule is a local
        # validation test — tests/test_creative_variations.py — not a live publish.
        C("creative.full_copy", "Creative: description and URL parameters set",
          lambda ctx: campaign(ctx, Objective.TRAFFIC, [adset(
              ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
              ads=[AdSpec(name="Full copy ad", creative=creative(
                  ctx, _A.GET_OFFER,
                  description="Free shipping today",
                  url_tags="utm_source=facebook&utm_medium=paid&utm_campaign=matrix",
              ))],
          )])),
        C("creative.cta_sweep", "Creative: one ad per call-to-action Traffic → Website allows",
          lambda ctx: campaign(ctx, Objective.TRAFFIC, [adset(
              ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
              ads=[
                  AdSpec(name=f"CTA {cta.value}", creative=creative(
                      ctx, cta, title=f"Headline {i + 1}"))
                  for i, cta in enumerate(
                      rules_for(Objective.TRAFFIC, _D.WEBSITE)[1].call_to_actions)
              ],
          )])),
        C("creative.many_ads", "Creative: three ads in one ad set, different media each",
          lambda ctx: campaign(ctx, Objective.TRAFFIC, [adset(
              ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
              ads=[
                  AdSpec(name="Ad one", creative=creative(
                      ctx, _A.LEARN_MORE, title="One", image_hash=ctx.image_a)),
                  AdSpec(name="Ad two", creative=creative(
                      ctx, _A.SHOP_NOW, title="Two", image_hash=ctx.image_b)),
                  AdSpec(name="Ad three", creative=creative(
                      ctx, _A.SIGN_UP, title="Three", image_hash=ctx.image_c)),
              ],
          )])),
        C("creative.mixed_formats", "Creative: single, carousel and video ads in one ad set",
          lambda ctx: campaign(ctx, Objective.TRAFFIC, [adset(
              ctx, Objective.TRAFFIC, _D.WEBSITE, _O.LINK_CLICKS,
              ads=[
                  AdSpec(name="Single", creative=creative(ctx, _A.LEARN_MORE)),
                  AdSpec(name="Carousel", creative=creative(
                      ctx, _A.SHOP_NOW, format=_F.CAROUSEL, cards=[
                          CarouselCard(title="One", link=ctx.website, image_hash=ctx.image_a),
                          CarouselCard(title="Two", link=ctx.website, image_hash=ctx.image_b),
                      ])),
                  AdSpec(name="Video", creative=creative(ctx, _A.WATCH_MORE, video=True)),
              ],
          )]), needs=("video",)),
    ]


# Filled at startup from Meta's own typeahead, so the ids are real.
_INTERESTS: list[dict] = []
_BEHAVIORS: list[dict] = []


# ── assets ───────────────────────────────────────────────────────────────────


async def _upload_images(account: str, token: str) -> tuple[str, str, str]:
    from PIL import Image

    hashes = []
    for name, colour in (
        ("a", (32, 32, 48)), ("b", (120, 40, 70)), ("c", (40, 100, 90)),
    ):
        path = Path(tempfile.gettempdir()) / f"punk_matrix_{name}.png"
        Image.new("RGB", (1080, 1080), colour).save(path)
        hashes.append(await _meta.upload_image(str(path), account, token))
    return tuple(hashes)  # type: ignore[return-value]


async def _upload_video(account: str, token: str) -> str | None:
    """A short generated MP4, uploaded and waited on until Meta can use it."""
    try:
        import imageio_ffmpeg
        import numpy as np
    except ImportError:
        print("   no imageio-ffmpeg installed — video cases will be skipped")
        return None

    path = Path(tempfile.gettempdir()) / "punk_matrix_clip.mp4"
    if not path.exists():
        writer = imageio_ffmpeg.write_frames(
            str(path), (1080, 1080), fps=24, quality=6, macro_block_size=1
        )
        writer.send(None)
        for i in range(24 * 6):                       # 6 seconds, ThruPlay needs >3
            frame = np.zeros((1080, 1080, 3), dtype="uint8")
            frame[:, :, 0] = (i * 4) % 256
            frame[:, :, 2] = 200
            writer.send(frame.tobytes())
        writer.close()
    video_id = await _meta.upload_video(str(path), account, token)
    await _meta.wait_for_video_ready(video_id, token)
    return video_id


async def _page_assets(page_id: str | None, token: str) -> dict[str, str | None]:
    """Existing posts / videos / events on the Page, for the boost destinations.

    The user token cannot read a Page's own feed (Graph answers "(#210) A page
    access token is required"), so this trades it for the Page token via
    ``me/accounts`` first. Strictly read-only — the boost destinations promote
    something that already exists, and this script never creates Page content.
    """
    out: dict[str, str | None] = {"post": None, "video_post": None, "event": None}
    if not page_id:
        return out
    try:
        accounts = (await _meta._request(
            "GET", "me/accounts?fields=id,access_token&limit=50", token,
        )).get("data") or []
        page_token = next(
            (a.get("access_token") for a in accounts if str(a.get("id")) == str(page_id)),
            None,
        )
    except Exception as exc:                                        # noqa: BLE001
        print(f"   page token lookup failed ({exc}) — boost cases will be skipped")
        return out
    if not page_token:
        return out

    for key, edge in (
        ("post", "published_posts"), ("video_post", "videos"), ("event", "events"),
    ):
        try:
            data = (await _meta._request(
                "GET", f"{page_id}/{edge}?fields=id&limit=5", page_token,
            )).get("data") or []
        except Exception:                                           # noqa: BLE001
            continue
        if not data:
            continue
        obj = str(data[0]["id"])
        # A boost creative wants "<page_id>_<object_id>"; published_posts already
        # returns that shape, the video and event edges return a bare id.
        out[key] = obj if "_" in obj else f"{page_id}_{obj}"
    return out


async def _first_media_uuid(user_id: str) -> str | None:
    from sqlalchemy import text

    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        return (await db.execute(
            text("SELECT id::text FROM media_files WHERE user_id = :u "
                 "AND media_type = 'image' ORDER BY created_at DESC LIMIT 1"),
            {"u": user_id},
        )).scalar_one_or_none()


# ── per-case run ─────────────────────────────────────────────────────────────


def _campaign_ids(ids: dict | None) -> list[str]:
    out = [str(c) for c in ((ids or {}).get("campaign_ids") or []) if c]
    primary = (ids or {}).get("campaign_id")
    if primary and str(primary) not in out:
        out.append(str(primary))
    return out


async def _publish_state(name: str) -> dict | None:
    from sqlalchemy import text

    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            text("SELECT publish_state FROM campaigns WHERE name = :n"), {"n": name},
        )).scalar_one_or_none()
    if row is None:
        return None
    return row if isinstance(row, dict) else json.loads(row)


async def _drop_draft(name: str) -> None:
    from sqlalchemy import text

    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM campaigns WHERE name = :n"), {"n": name})
        await db.commit()


async def _cleanup(
    name: str, campaigns: list[str], extras: dict, token: str, notes: list[str]
) -> None:
    """Delete the campaign(s), any instant form created on the Page, the draft row.

    Deleting a campaign removes its ad sets and ads with it. The instant form is a
    separate object living on the Page, so it is deleted explicitly — that is how a
    test run used to leave a form behind on every Leads case.
    """
    for cid in campaigns:
        try:
            await _meta.delete_campaign(str(cid), token)
        except Exception as exc:                                    # noqa: BLE001
            notes.append(f"campaign {cid} not deleted: {exc}")
    for key in ("custom_audience_id", "lookalike_audience_id", "lead_form_id"):
        obj = extras.get(key)
        if not obj:
            continue
        try:
            await _meta._request("DELETE", str(obj), token)
        except Exception as exc:                                    # noqa: BLE001
            notes.append(f"{key} {obj} not deleted: {exc}")
    await _drop_draft(name)


async def cleanup_run(results_path: str, token: str) -> int:
    """Undo a whole run from its results file. Every id it created is in there."""
    results = json.loads(Path(results_path).read_text(encoding="utf-8"))
    removed = 0
    for r in results:
        if not r.get("campaigns") and not r.get("name"):
            continue
        notes: list[str] = []
        await _cleanup(
            r.get("name") or "", r.get("campaigns") or [], r.get("extras") or {},
            token, notes,
        )
        removed += len(r.get("campaigns") or [])
        for note in notes:
            print(f"   {r['id']}: {note}")
    print(f"deleted {removed} campaign(s) named in {results_path}")
    return 0


def _wanted_feed_shape(creative: CreativeSpec) -> tuple[int, int, int] | None:
    """``(titles, bodies, media)`` this creative expects Meta to store in an asset
    feed, or None when it publishes as a plain single-asset creative.

    Mirrors the switch in ``meta_ads.create_ad_creative``: a carousel and an
    instant-form ad never use a feed, and one of everything is a normal creative.
    """
    if creative.format is AdFormat.CAROUSEL or creative.lead_gen_form_id:
        return None
    titles, bodies = creative.text_variations()
    media = 1 + len(creative.extra_media or [])
    if max(len(titles), len(bodies), media) <= 1:
        return None
    # A video ad's feed carries copy only: the video rides
    # object_story_spec.video_data, and Meta never stores `videos` in a feed, so
    # create_ad_creative stops sending them. The gate above still counts the video
    # — one video and one headline is a plain creative with no feed at all.
    if creative.media_kind == "video":
        return len(titles), len(bodies), 0
    return len(titles), len(bodies), media


def _feed_shape(feed: dict) -> tuple[int, int, int]:
    """The same triple, read off a creative's ``asset_feed_spec``."""
    return (
        len(feed.get("titles") or []),
        len(feed.get("bodies") or []),
        len(feed.get("images") or []) + len(feed.get("videos") or []),
    )


async def _verify(
    spec: CampaignSpec, ids: dict, token: str,
    expect_feeds: "tuple[tuple[int, int, int], ...] | None" = None,
) -> list[str]:
    """Read the campaign back from Meta, once the tree has settled.

    Meta's reads lag its writes: ``awareness.ad_recall`` reported "expected 1
    ad(s), found 0" on one run and passed on the next from an identical spec,
    because ``fetch_campaign_tree`` was called before the ad appeared. A short
    re-read is the difference between measuring the product and measuring
    replication delay.
    """
    problems = await _verify_once(spec, ids, token, expect_feeds)
    if any("found" in p for p in problems):
        await asyncio.sleep(6.0)
        problems = await _verify_once(spec, ids, token, expect_feeds)
    return problems


async def _verify_once(
    spec: CampaignSpec, ids: dict, token: str,
    expect_feeds: "tuple[tuple[int, int, int], ...] | None" = None,
) -> list[str]:
    """One pass over the campaign tree. Returns the problems found."""
    problems: list[str] = []
    campaigns = _campaign_ids(ids)
    if not campaigns:
        return ["publish created objects but reported no campaign id"]

    seen_adsets = seen_ads = 0
    got_feeds: list[tuple[int, int, int]] = []
    for cid in campaigns:
        tree = await _meta.fetch_campaign_tree(str(cid), token)
        statuses = [(tree.get("campaign") or {}).get("status")]
        for a in tree.get("adsets", []):
            seen_adsets += 1
            statuses.append(a.get("status"))
            for ad in a.get("ads", []):
                seen_ads += 1
                statuses.append(ad.get("status"))
                feed = (ad.get("creative") or {}).get("asset_feed_spec")
                if feed:
                    got_feeds.append(_feed_shape(feed))
        live = [s for s in statuses if s and s != "PAUSED"]
        if live:
            problems.append(f"{cid} is not fully PAUSED: {live}")

    # Copy and media variations are the one thing the counts above cannot see:
    # ``create_ad_creative`` falls back to a single-asset creative when Meta
    # refuses the asset feed, and the fallback returns an ordinary creative id, so
    # the ad exists, is PAUSED, and carries one headline and one image. Comparing
    # the shapes the plan asked for against the ones Meta actually stored is what
    # tells a published variation from a silently dropped one.
    want_feeds = sorted(expect_feeds) if expect_feeds is not None else sorted(
        shape
        for a in spec.adsets
        for ad in a.ads
        if (shape := _wanted_feed_shape(ad.creative))
    )
    if want_feeds != sorted(got_feeds):
        problems.append(
            "asset feed (titles, bodies, media) mismatch — plan asked for "
            f"{want_feeds}, Meta stored {sorted(got_feeds)}"
        )

    if ids.get("activated"):
        problems.append("activation ran with META_PUBLISH_ACTIVATE=false")
    if seen_adsets != len(spec.adsets):
        problems.append(f"expected {len(spec.adsets)} ad set(s) at Meta, found {seen_adsets}")
    want_ads = sum(len(a.ads) for a in spec.adsets)
    if seen_ads != want_ads:
        problems.append(f"expected {want_ads} ad(s) at Meta, found {seen_ads}")
    if len(ids.get("adset_ids") or []) != len(spec.adsets):
        problems.append("publish reported a different ad set count than the plan")
    return problems


async def _run_case(
    case: Case, ctx: Ctx, user_info: dict, user_id: str, token: str,
    *, delete_after: bool,
) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%m%d-%H%M%S")
    result: dict[str, Any] = {"id": case.id, "what": case.what, "notes": []}

    missing = [n for n in case.needs if n not in ctx.caps]
    if missing:
        result["status"] = "SKIP"
        result["detail"] = f"account has no {', '.join(missing)}"
        return result

    try:
        spec = case.build(ctx)
        spec = spec.model_copy(update={"name": f"[punk matrix] {case.id} {stamp}"[:255]})
        spec = CampaignSpec.model_validate(spec.model_dump())      # re-validate the rename
    except Exception as exc:                                       # noqa: BLE001
        result["status"] = "FAIL"
        result["detail"] = f"our own validation rejected the spec: {exc}"
        return result

    ids: dict | None = None
    thread_id = f"live-matrix-{case.id}-{stamp}"

    async def _publish_and_verify() -> tuple[dict | None, list[str]]:
        """Publish then read back, standing down when the ad account throttles.

        Both halves sit inside the retry on purpose. Wrapping only the publish
        left the read-back exposed: a case whose campaign was built correctly
        still came back ERROR because ``fetch_campaign_tree`` was the call that
        hit the limit, which reads as a broken combination and is not one.
        """
        nonlocal ids
        for attempt in range(_THROTTLE_RETRIES + 1):
            try:
                if ids is None:
                    ids = await publish_campaign_to_meta(
                        user_info=user_info,
                        geo_data={},          # no maid_extraction_id -> no audience
                        marketing_plan=spec.model_dump(mode="json"),
                        campaign_brief={},
                        writer=lambda e: None,
                        user_id=user_id,
                        # Same id on every attempt, so the ledger continues the
                        # campaign the throttled attempt already started rather
                        # than building a second one.
                        thread_id=thread_id,
                        allow_without_audience=True,
                    )
                return ids, (
                    await _verify(spec, ids, token, case.expect_feeds) if ids else []
                )
            except Exception as exc:                               # noqa: BLE001
                if not _is_throttle(exc) or attempt == _THROTTLE_RETRIES:
                    raise
                result["notes"].append(
                    f"throttled (attempt {attempt + 1}), waited {_THROTTLE_SLEEP_S:.0f}s"
                )
                print(f"        throttled — waiting {_THROTTLE_SLEEP_S:.0f}s")
                await asyncio.sleep(_THROTTLE_SLEEP_S)
        return ids, []

    try:
        ids, problems = await _publish_and_verify()
        if not ids:
            result["status"] = "FAIL"
            result["detail"] = "publish returned nothing"
        else:
            result["status"] = "PASS" if not problems else "FAIL"
            result["detail"] = "; ".join(problems) or (
                f"{len(spec.adsets)} ad set(s), "
                f"{sum(len(a.ads) for a in spec.adsets)} ad(s), all PAUSED"
            )
            result["campaigns"] = _campaign_ids(ids)
    except MetaPublishError as exc:
        result["status"] = "FAIL"
        result["detail"] = f"[{exc.step}] {exc}"
    except Exception as exc:                                       # noqa: BLE001
        result["status"] = "ERROR"
        result["detail"] = f"{type(exc).__name__}: {exc}"
        result["trace"] = traceback.format_exc(limit=4)
    finally:
        # Recorded whatever happened, so --cleanup can undo a run that died
        # half way and the ids are not only in a scrolled-past log line. The
        # ledger is the authority for the instant form: publish creates it on the
        # Page and does not return it in ``ids``.
        result["name"] = spec.name
        state = await _publish_state(spec.name) or {}
        result["campaigns"] = _campaign_ids(ids) or [
            str(c) for c in (state.get("campaigns") or {}).values()
        ]
        result["extras"] = {
            k: (ids or {}).get(k) or state.get(k)
            for k in ("custom_audience_id", "lookalike_audience_id", "lead_form_id")
            if (ids or {}).get(k) or state.get(k)
        }
        if delete_after:
            await _cleanup(
                spec.name, result["campaigns"], result["extras"], token, result["notes"],
            )
            result["campaigns"], result["extras"] = [], {}
    return result


# ── main ─────────────────────────────────────────────────────────────────────


async def main(
    user_id: str, only: str | None, start_at: str | None, out: str,
    stop_before: str | None = None,
    *, delete_after: bool = False, cleanup: str | None = None,
) -> int:
    if settings.META_PUBLISH_ACTIVATE:
        print("REFUSING: META_PUBLISH_ACTIVATE is true, so this would activate real "
              "ads. Set it false in .env before running a live publish test.",
              file=sys.stderr)
        return 2

    creds = await get_meta_credentials(user_id)
    if not creds:
        print(f"user {user_id} has no connected Meta account", file=sys.stderr)
        return 2
    token, account = creds["access_token"], creds["ad_account_id"]
    page_id = creds.get("page_id")
    if cleanup:
        return await cleanup_run(cleanup, token)
    currency = await _meta.fetch_ad_account_currency(account, token)
    floor = min_budget_cents(currency)

    print(f"account {account}  currency={currency.get('currency')}  "
          f"min daily budget={floor}  page={page_id}")

    pixels = await _meta.fetch_ad_pixels(account, token)
    pixel_id = str(pixels[0]["id"]) if pixels else None
    apps = (await _meta._request(
        "GET", f"{account if str(account).startswith('act_') else 'act_' + str(account)}"
               "/advertisable_applications?fields=id,name&limit=5", token,
    )).get("data") or []
    app_id = str(apps[0]["id"]) if apps else None

    print("uploading shared creative assets...")
    image_a, image_b, image_c = await _upload_images(account, token)
    video_id = await _upload_video(account, token)
    media_uuid = await _first_media_uuid(user_id)
    print(f"   images={image_a[:12]}… video={video_id} media_uuid={media_uuid}")

    global _INTERESTS, _BEHAVIORS
    for kind, query, target in (
        ("interests", "coffee", "_INTERESTS"), ("behaviors", "travel", "_BEHAVIORS"),
    ):
        try:
            found = await _meta.search_targeting_interests(
                query, token, kind=kind, limit=5,
            )
            picked = [{"id": str(i["id"]), "name": i.get("name", "")} for i in found[:2]]
        except Exception as exc:                                   # noqa: BLE001
            print(f"   {kind} lookup failed ({exc}) — that case will be skipped")
            continue
        globals()[target] = picked
        if not picked:
            print(f"   no {kind} matched '{query}' — that case will be skipped")

    page_objects = await _page_assets(page_id, token)

    ctx = Ctx(
        floor=floor,
        website=creds.get("website_url") or "https://example.com",
        page_id=page_id,
        pixel_id=pixel_id,
        app_id=app_id,
        store_url="https://apps.apple.com/us/app/facebook/id284882215",
        image_a=image_a, image_b=image_b, image_c=image_c,
        video_id=video_id,
        media_uuid=media_uuid,
        post_id=page_objects["post"],
        video_post_id=page_objects["video_post"],
        event_id=page_objects["event"],
    )
    ctx.caps = {
        *(["page"] if page_id else []),
        *(["pixel"] if pixel_id else []),
        *(["app"] if app_id else []),
        *(["video"] if video_id else []),
        *(["media_uuid"] if media_uuid else []),
        *(["interests"] if _INTERESTS else []),
        *(["behaviors"] if _BEHAVIORS else []),
        # The boost destinations promote something that already exists on the
        # Page. Nothing is posted to unlock them — an empty Page is a SKIP.
        *(["post"] if page_objects["post"] else []),
        *(["video_post"] if page_objects["video_post"] else []),
        *(["event"] if page_objects["event"] else []),
    }
    print(f"   capabilities: {sorted(ctx.caps) or 'none'}")

    user_info = {
        "meta_access_token": token,
        "meta_ad_account_id": account,
        "meta_page_id": page_id,
        "page_id": page_id,
        "business_name": "Punk matrix test",
        "website_url": ctx.website,
        **currency,
    }

    cases = _cases()
    if start_at:
        idx = next((i for i, c in enumerate(cases) if start_at in c.id), 0)
        cases = cases[idx:]
    if stop_before:
        # Exclusive, so ``--from X`` and ``--to X`` split the list cleanly between
        # two runs without repeating a case. Repeating is not free: the ad
        # account's rate limit is a rolling budget of calls.
        end = next((i for i, c in enumerate(cases) if stop_before in c.id), len(cases))
        cases = cases[:end]
    if only:
        wanted = [o.strip() for o in only.split(",") if o.strip()]
        cases = [c for c in cases if any(o in c.id for o in wanted)]
    if not cases:
        print("no cases matched", file=sys.stderr)
        return 2

    results: list[dict] = []
    print(f"\nrunning {len(cases)} case(s)\n")
    for n, case in enumerate(cases, 1):
        print(f"[{n}/{len(cases)}] {case.id} — {case.what}")
        started = time.monotonic()
        res = await _run_case(
            case, ctx, user_info, user_id, token, delete_after=delete_after,
        )
        res["seconds"] = round(time.monotonic() - started, 1)
        results.append(res)
        print(f"        {res['status']}: {res['detail']}  ({res['seconds']}s)")
        for note in res["notes"]:
            print(f"        note: {note}")
        # Written after every case: a throttled run keeps what it proved.
        Path(out).write_text(json.dumps(results, indent=2), encoding="utf-8")
        await asyncio.sleep(_PACE_S)

    passed = [r for r in results if r["status"] == "PASS"]
    failed = [r for r in results if r["status"] in ("FAIL", "ERROR")]
    skipped = [r for r in results if r["status"] == "SKIP"]
    print(f"\n{'=' * 70}\n{len(passed)} passed  {len(failed)} failed  "
          f"{len(skipped)} skipped   (results: {out})")
    for r in failed:
        print(f"  FAIL {r['id']}: {r['detail']}")
    for r in skipped:
        print(f"  SKIP {r['id']}: {r['detail']}")
    if not delete_after:
        left = sum(len(r.get("campaigns") or []) for r in results)
        print(f"\n{left} PAUSED campaign(s) left in {account} for inspection. "
              f"Remove them with:\n  --user-id {user_id} --cleanup {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    # Case names carry "→". Redirected to a file on Windows, stdout is cp1252 and
    # the first print crashes the run — after the assets were uploaded.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[3])
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--only", help="substring filter on the case id; comma-separated "
                                       "for several, so one run can share the asset uploads")
    parser.add_argument("--from", dest="start_at", help="start at the first case id containing this")
    parser.add_argument("--to", dest="stop_before", metavar="CASE_ID",
                        help="stop BEFORE the first case id containing this, so "
                             "--to X and --from X split the run with no overlap")
    parser.add_argument("--list", action="store_true", help="print the cases and exit")
    parser.add_argument("--out", default="matrix_results.json")
    parser.add_argument("--delete-after", action="store_true",
                        help="delete each case as soon as it is verified, instead of "
                             "leaving it PAUSED in the account")
    parser.add_argument("--cleanup", metavar="RESULTS_JSON",
                        help="delete everything a previous run created, then exit")
    args = parser.parse_args()
    if args.list:
        for c in _cases():
            print(f"{c.id:38} {c.what}"
                  + (f"   [needs {', '.join(c.needs)}]" if c.needs else ""))
        raise SystemExit(0)
    raise SystemExit(asyncio.run(main(
        args.user_id, args.only, args.start_at, args.out,
        stop_before=args.stop_before,
        delete_after=args.delete_after, cleanup=args.cleanup,
    )))
