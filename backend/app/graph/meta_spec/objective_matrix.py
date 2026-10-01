"""
graph/meta_spec/objective_matrix.py
───────────────────────────────────
Per-objective field rules — the thing that makes the campaign form dynamic.

Meta's form is **two-dimensional**: objective × conversion location. Picking
"Leads" does not decide the optimization goal, the billing event, the CTA list or
the promoted object — picking Leads *and* "Instant forms" does. The two axes were
collapsed into one here originally (objective → flat tuples), which is why the
Leads default shipped as ``WEBSITE`` + ``LEAD_GENERATION``: each value was legal
for the objective, but the *pair* is not a thing Meta accepts.

There is a **third** axis under those two: the optimization goal. Picking
ThruPlay decides that the ad must be a single video, that billing may be per
ThruPlay, and that cost cap is not available — none of which the objective or the
conversion location knows. Validating goal and billing independently is what let
``REACH`` + ``THRUPLAY`` billing through, and why an Awareness campaign could
offer a carousel of images while optimizing for watch time.

So the rules are three layers:

  * ``ObjectiveRules``   — what the objective decides: its label, its bid
                           strategies, and which conversion locations it offers.
  * ``DestinationRules`` — everything the conversion location decides:
                           optimization goals, billing events, CTAs, ad formats,
                           promoted_object kind, and what user_info it needs.
  * ``GoalRules``        — what the optimization goal decides: which billing
                           events and bid strategies pair with it, what kind of
                           media the creative must carry, and whether frequency
                           caps or attribution windows apply.

A value has to satisfy every layer that constrains it — the layers intersect,
they do not override.

The first element of each tuple is the default. Ordering is therefore meaningful
— do not sort these.

Three consumers:

  * ``models.py``      — validation (reject a combination Meta would reject)
  * ``catalog.py``     — the editor's option lists per objective × destination
  * ``builder.py``     — the default when the user expresses no preference

This matrix encodes Meta's documented rules, but Meta changes them without
notice and account-level eligibility varies. It is a fast local check, not the
authority: ``meta_ads.preflight_publish`` runs the real payload past Meta's own
``validate_only`` before anything is created. When the two disagree, Meta wins
and the matrix is the thing that needs fixing.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from app.graph.meta_spec.enums import (
    AdFormat,
    BidStrategy,
    BillingEvent,
    CallToAction,
    DestinationType,
    Objective,
    OptimizationGoal,
    meta_label,
)

# ── promoted_object requirement kinds ────────────────────────────────────────
# What Meta demands in AdSet.promoted_object for a given optimization goal.
# NONE       – must be absent
# PIXEL      – {"pixel_id": …, "custom_event_type": …}
# PAGE       – {"page_id": …}
# APPLICATION– {"application_id": …, "object_store_url": …}

PROMOTED_NONE = "none"
PROMOTED_PIXEL = "pixel"
PROMOTED_PAGE = "page"
PROMOTED_APPLICATION = "application"

_BOTH_FORMATS = (AdFormat.SINGLE, AdFormat.CAROUSEL)

# What an ad's asset actually is. Used in two places: on a creative to say what
# it carries, and on a goal to say what it demands — None there meaning "either".
MediaKind = Literal["image", "video"]


@dataclass(frozen=True)
class GoalRules:
    """The third axis: what the **optimization goal** decides.

    The matrix was two-dimensional (objective × conversion location), so anything
    a goal decides had nowhere to live and ended up validated independently of
    it. Three bugs came out of that gap:

      * ``REACH`` + ``THRUPLAY`` billing — each legal for the destination, the
        pair rejected by Meta, because billing was checked against the
        destination's flat list rather than against the chosen goal.
      * ``COST_CAP`` on an Awareness campaign, where the goal is REACH and Meta
        has no cost-per-result to cap.
      * A ThruPlay ad set offering carousel and image ads. ThruPlay optimizes for
        watch time, so the creative has to be a single video — the case that
        started this rebuild.

    Everything here is intersected with the destination's own lists: a value has
    to satisfy the conversion location **and** the goal.
    """

    # Billing events legal *with this goal*. Almost everything bills on
    # impressions; the exceptions bill on the thing they optimize for.
    billing_events: tuple[BillingEvent, ...] = (BillingEvent.IMPRESSIONS,)
    bid_strategies: tuple[BidStrategy, ...] = (
        BidStrategy.LOWEST_COST_WITHOUT_CAP,
        BidStrategy.COST_CAP,
        BidStrategy.LOWEST_COST_WITH_BID_CAP,
    )
    # None means the goal accepts either. Same convention as ad_formats below.
    media_kind: MediaKind | None = None
    # None means "whatever the destination allows". A tuple narrows it further.
    ad_formats: tuple[AdFormat, ...] | None = None
    # Meta only accepts frequency_control_specs on REACH and THRUPLAY ad sets.
    allows_frequency_control: bool = False
    # attribution_spec is meaningless without a conversion to attribute.
    allows_attribution_spec: bool = False

    def allows_billing_event(self, event: str) -> bool:
        return event in {e.value for e in self.billing_events}

    def allows_bid_strategy(self, strategy: str) -> bool:
        return strategy in {s.value for s in self.bid_strategies}


# Goals with no per-result cost for Meta to cap — frequency goals and messaging
# conversations. Cost cap is out (subcode 2446166, "You are using wrong
# optimization goal with cost cap"); a bid cap still applies to the auction.
_REACH_BIDS = (BidStrategy.LOWEST_COST_WITHOUT_CAP, BidStrategy.LOWEST_COST_WITH_BID_CAP)
# The ROAS goal only exists where Meta knows the value of a conversion.
_VALUE_BIDS = (
    BidStrategy.LOWEST_COST_WITHOUT_CAP,
    BidStrategy.COST_CAP,
    BidStrategy.LOWEST_COST_WITH_BID_CAP,
    BidStrategy.LOWEST_COST_WITH_MIN_ROAS,
)

_O_ = OptimizationGoal
_B_ = BillingEvent

GOAL_RULES: dict[OptimizationGoal, GoalRules] = {
    # ── awareness / frequency goals ──────────────────────────────────────────
    _O_.REACH: GoalRules(
        bid_strategies=_REACH_BIDS,
        allows_frequency_control=True,
    ),
    _O_.IMPRESSIONS: GoalRules(bid_strategies=_REACH_BIDS),
    # Automatic bid only. Measured (scripts/probe_meta_matrix.py, act_9978947…):
    # a bid cap is rejected with subcode 1885204, "You need to set your bid to
    # automatic for the chosen optimization" — Meta optimizes ad recall against
    # a survey lift it will not let an advertiser price.
    _O_.AD_RECALL_LIFT: GoalRules(
        bid_strategies=(BidStrategy.LOWEST_COST_WITHOUT_CAP,),
    ),

    # ── video ────────────────────────────────────────────────────────────────
    # The reported bug: ThruPlay optimizes for watch time, so the ad must be a
    # single video. Publish builds `video_data` for it; an image or a carousel
    # cannot express the format at all.
    _O_.THRUPLAY: GoalRules(
        billing_events=(_B_.IMPRESSIONS, _B_.THRUPLAY),
        bid_strategies=_REACH_BIDS,
        media_kind="video",
        ad_formats=(AdFormat.SINGLE,),
        allows_frequency_control=True,
    ),

    # ── traffic ──────────────────────────────────────────────────────────────
    _O_.LINK_CLICKS: GoalRules(billing_events=(_B_.IMPRESSIONS, _B_.LINK_CLICKS)),
    # Impressions only. Measured: LANDING_PAGE_VIEWS + LINK_CLICKS billing is
    # rejected with subcode 1815117, "The specified billing event is not a valid
    # option for the optimization goal provided". CPC billing pairs with the
    # LINK_CLICKS goal, not with the landing-page-view goal that supersedes it.
    _O_.LANDING_PAGE_VIEWS: GoalRules(),

    # ── engagement ───────────────────────────────────────────────────────────
    # Impressions only. Measured: the POST_ENGAGEMENT goal rejects POST_ENGAGEMENT
    # billing with subcode 1815117, "The specified billing event is not a valid
    # option for the optimization goal provided" — the rule subcode, not the
    # account-maturity one (2446404), which this same account returns for
    # LINK_CLICKS billing. Meta's own two answers, so CPE really is gone here.
    _O_.POST_ENGAGEMENT: GoalRules(),
    _O_.PAGE_LIKES: GoalRules(billing_events=(_B_.IMPRESSIONS, _B_.PAGE_LIKES)),
    _O_.EVENT_RESPONSES: GoalRules(),
    # No cost cap: subcode 2446166, the same verdict REACH, IMPRESSIONS and
    # CONVERSATIONS get. A profile visit is not a conversion Meta prices per
    # result.
    _O_.VISIT_INSTAGRAM_PROFILE: GoalRules(bid_strategies=_REACH_BIDS),
    _O_.ENGAGED_USERS: GoalRules(),

    # ── conversion ───────────────────────────────────────────────────────────
    _O_.OFFSITE_CONVERSIONS: GoalRules(allows_attribution_spec=True),
    _O_.VALUE: GoalRules(bid_strategies=_VALUE_BIDS, allows_attribution_spec=True),
    # Impressions only. Measured: paying per install is gone — "CPA billing is no
    # longer available. Select impressions to avoid making changes later." The
    # same ad set answers "You cannot use autobidding with the specified
    # billing_event: APP_INSTALLS" when the bid is automatic, which reads like a
    # bid-strategy problem and is not — the billing event itself was retired.
    _O_.APP_INSTALLS: GoalRules(allows_attribution_spec=True),

    # ── leads / messaging ────────────────────────────────────────────────────
    _O_.LEAD_GENERATION: GoalRules(allows_attribution_spec=True),
    _O_.QUALITY_LEAD: GoalRules(allows_attribution_spec=True),
    _O_.QUALITY_CALL: GoalRules(),
    # No cost cap. Measured: subcode 2446166, "You are using wrong optimization
    # goal with cost cap." A messaging conversation is not a conversion Meta
    # prices per result, so there is nothing to cap.
    _O_.CONVERSATIONS: GoalRules(bid_strategies=_REACH_BIDS),
}

# A goal with no entry gets the permissive default rather than being rejected —
# the matrix is a fast local check, and Meta's preflight remains the authority.
DEFAULT_GOAL_RULES = GoalRules()


def goal_rules(goal: OptimizationGoal | str) -> GoalRules:
    """Rules for one optimization goal."""
    if not isinstance(goal, OptimizationGoal):
        try:
            goal = OptimizationGoal(str(goal).strip().upper())
        except ValueError:
            return DEFAULT_GOAL_RULES
    return GOAL_RULES.get(goal, DEFAULT_GOAL_RULES)


# Placements a messaging conversion location can serve on. Audience Network is
# out: an AN ad has no surface from which to open a Messenger or WhatsApp thread,
# and Meta rejects it with subcode 1815336 on every messaging destination probed
# (MESSENGER, MESSAGING_MESSENGER_WHATSAPP, MESSAGING_INSTAGRAM_DIRECT_WHATSAPP,
# MESSAGING_INSTAGRAM_DIRECT_MESSENGER, MESSAGING_INSTAGRAM_DIRECT_MESSENGER_WHATSAPP).
# WHATSAPP itself was not probed alone, but two of those five carry WhatsApp and
# behave identically.
#
# ``threads`` is absent because enums.PUBLISHER_PLATFORMS does not offer it, not
# because Meta refused it.
_MESSAGING_PLATFORMS: tuple[str, ...] = ("facebook", "instagram", "messenger")

# Prerequisites whose answer belongs to the Page, not to the run's user_info.
# "page_whatsapp" is the only one: Click-to-WhatsApp dials the number linked to
# the Page, and the Page is picked in the editor, so the answer changes when the
# user changes Page. It therefore travels per Page on ``page_candidates`` and is
# deliberately kept OUT of the catalog's flat ``user_info_present`` map, where a
# single global True/False would be wrong the moment the Page picker is touched.
PAGE_SCOPED_PREREQUISITES: frozenset[str] = frozenset({"page_whatsapp"})

# Meta rejects a lone ``messenger`` placement with subcode 1815985: "To use the
# Messenger Stories placement, please also select either Facebook Feeds or
# Instagram Stories." A combination rule rather than a destination rule, so it is
# enforced once for every destination instead of per DestinationRules.
MESSENGER_NEEDS_COMPANION: tuple[str, ...] = ("facebook", "instagram")


@dataclass(frozen=True)
class DestinationRules:
    """Everything a conversion location decides, given its objective."""

    destination_type: DestinationType
    optimization_goals: tuple[OptimizationGoal, ...]
    billing_events: tuple[BillingEvent, ...]
    call_to_actions: tuple[CallToAction, ...]
    ad_formats: tuple[AdFormat, ...] = _BOTH_FORMATS
    # Optimization goals that force a promoted_object, and of which kind.
    promoted_object_by_goal: dict[OptimizationGoal, str] = field(default_factory=dict)
    # Instant Form destinations need a lead_gen_form_id on every creative.
    requires_lead_form: bool = False
    # "Boost an existing thing" destinations: the ad IS a post that already lives
    # on the Page, so the creative is {"object_story_id": …} rather than fresh
    # copy and media. Set to the kind of object the picker should list
    # ("post" / "video" / "event"). We used to build a brand-new link_data
    # creative for these, which is the wrong shape and loses the destination's
    # whole meaning — the post being boosted.
    object_story_kind: str = ""
    # Whether this conversion location PERMITS an existing post (as opposed to
    # ``object_story_kind``, which REQUIRES one). Set where a user should be able
    # to promote a post they already published instead of a freshly composed
    # creative — the post keeps its likes, comments and shares, which a new ad
    # starts without.
    #
    # Default False because it is not measured yet: an existing-post creative is
    # accepted on some (objective, destination) pairs and not others, and this
    # matrix does not guess. Fill it from scripts/probe_meta_matrix.py the way
    # ``omit_destination_type`` and ``publisher_platforms`` were filled, and paste
    # the evidence table here.
    allows_existing_post: bool = False
    # Publisher platforms this conversion location can actually serve on. None
    # means no constraint — the safe default, since an unmeasured destination
    # must not be narrowed on a guess.
    #
    # Measured (scripts/probe_meta_matrix.py, one platform at a time per
    # destination). Every messaging destination probed rejected
    # ``audience_network`` with subcode 1815336, "The placement combination
    # selected is not supported by the set up of the campaign" — an Audience
    # Network ad has nowhere to open a Messenger or WhatsApp thread from:
    #
    #   MESSENGER                                     audience_network rejected
    #   MESSAGING_MESSENGER_WHATSAPP                  audience_network rejected
    #   MESSAGING_INSTAGRAM_DIRECT_WHATSAPP           audience_network rejected
    #   MESSAGING_INSTAGRAM_DIRECT_MESSENGER          audience_network rejected
    #   MESSAGING_INSTAGRAM_DIRECT_MESSENGER_WHATSAPP audience_network rejected
    #   FACEBOOK_LIVE                                 audience_network rejected
    #   WEBSITE, INSTAGRAM_DIRECT                     everything accepted
    #
    # Not encoded here: ``messenger`` and ``threads`` alone were also rejected on
    # those destinations, but with subcodes 1815985 / 2490494, whose messages say
    # to add a companion placement ("please also select either Facebook Feeds or
    # Instagram Stories"). That is a combination rule, not a destination rule —
    # see MESSENGER_NEEDS_COMPANION below.
    publisher_platforms: tuple[str, ...] | None = None
    # Some conversion locations are expressed by the ABSENCE of destination_type.
    # Meta shows "Website" under Engagement and Sales in Ads Manager, but for the
    # goals those objectives actually offer, the API wants an ad set with no
    # destination_type at all — the creative's link is what sends people to the
    # site. Sending ``destination_type: "WEBSITE"`` is rejected with subcode
    # 2490408, "You can't use the selected performance goal with your campaign
    # objective" (blame_field_specs: optimization_goal).
    #
    # Measured against act_997894704000491, every goal the objective accepts:
    #
    #   Sales      9 goals probed with the field -> 8 rejected 2490408
    #   Engagement 12 goals probed with the field -> 11 rejected 2490408
    #   Sales      LINK_CLICKS / LANDING_PAGE_VIEWS / REACH without it -> accepted
    #   Engagement POST_ENGAGEMENT / LINK_CLICKS / REACH / IMPRESSIONS
    #              / LANDING_PAGE_VIEWS without it -> accepted
    #
    # The single exception in both is DERIVED_EVENTS, which fails with 1815143
    # instead ("you need to provide a promoted object with a pixel_id") — a
    # different subcode, so that pairing passed the goal check and only wants a
    # pixel. ``destination_type: WEBSITE`` is therefore usable under these
    # objectives with a pixel-backed DERIVED_EVENTS ad set, which the matrix does
    # not offer anywhere. If it ever does, this flag has to become conditional on
    # the goal rather than fixed per destination.
    #
    # Notably OFFSITE_CONVERSIONS is NOT that exception: it is rejected 2490408
    # with the field present even though it is the objective's own default goal.
    #
    # Awareness → Website and Traffic → Website both accept the field, so this is
    # per conversion location, not global.
    omit_destination_type: bool = False
    # Prerequisite keys that must be satisfied before this destination can
    # publish. Most name a user_info field ("website_url"). The ones in
    # PAGE_SCOPED_PREREQUISITES instead name something about the Page the ads run
    # as, which is chosen in the editor rather than collected in the run — see
    # that constant for why they are answered from page_candidates.
    required_user_info: tuple[str, ...] = ()
    help_text: str = ""
    # Ads Manager sometimes names the same destination_type differently depending
    # on the objective: ON_AD is "Instant forms" under Leads but simply "On your
    # ad" under Awareness. Set this where the shared label would mislead.
    label_override: str = ""

    @property
    def label(self) -> str:
        return self.label_override or meta_label(self.destination_type.value)

    @property
    def default_optimization_goal(self) -> OptimizationGoal:
        return self.optimization_goals[0]

    @property
    def default_billing_event(self) -> BillingEvent:
        return self.billing_events[0]

    @property
    def default_call_to_action(self) -> CallToAction:
        return self.call_to_actions[0]

    @property
    def default_ad_format(self) -> AdFormat:
        return self.ad_formats[0]

    def promoted_object_kind(self, goal: OptimizationGoal) -> str:
        """Which promoted_object shape this goal needs (PROMOTED_* constant)."""
        return self.promoted_object_by_goal.get(goal, PROMOTED_NONE)

    def allows_optimization_goal(self, goal: str) -> bool:
        return goal in {g.value for g in self.optimization_goals}

    def rejected_platforms(self, platforms: Iterable[str] | None) -> list[str]:
        """Which of ``platforms`` this conversion location cannot serve on.

        Empty when the destination carries no constraint, or when placements are
        left to Meta (an absent publisher_platforms key IS Advantage+).
        """
        if self.publisher_platforms is None or not platforms:
            return []
        return sorted(set(platforms) - set(self.publisher_platforms))

    def allows_billing_event(self, event: str) -> bool:
        return event in {e.value for e in self.billing_events}

    def allows_call_to_action(self, cta: str) -> bool:
        return cta in {c.value for c in self.call_to_actions}

    def allows_ad_format(self, fmt: str) -> bool:
        return fmt in {f.value for f in self.ad_formats}


@dataclass(frozen=True)
class ObjectiveRules:
    """What the campaign objective itself decides.

    Bid strategy lives here rather than on the destination because Meta sets it
    at the campaign (or ad set) level, before a conversion location exists.
    """

    objective: Objective
    label: str
    destinations: tuple[DestinationRules, ...]
    bid_strategies: tuple[BidStrategy, ...]
    help_text: str = ""
    # Measured: Meta gates frequency_control_specs on the CAMPAIGN OBJECTIVE as
    # well as the goal — "the frequency_control_specs field can only be used
    # within the specified objectives … BRAND_AWARENESS, REACH, POST_ENGAGEMENT
    # or RESEARCH_POLL", which under ODAX is Awareness and Engagement. The Reach
    # goal exists under Traffic and Sales too, so a goal-only check let a capped
    # Traffic → Reach ad set through and it died at preflight.
    allows_frequency_control: bool = False

    # ── lookups ──────────────────────────────────────────────────────────────

    @property
    def default_destination(self) -> DestinationRules:
        return self.destinations[0]

    @property
    def default_destination_type(self) -> DestinationType:
        return self.destinations[0].destination_type

    @property
    def default_bid_strategy(self) -> BidStrategy:
        return self.bid_strategies[0]

    def for_destination(self, dest: DestinationType | str | None) -> DestinationRules:
        """Rules for one conversion location. ``None`` yields the default.

        Raises ``KeyError`` for a destination this objective does not offer —
        deliberately loud, same reasoning as ``matrix_for``: silently falling back
        to the default would publish a campaign pointed somewhere nobody chose.
        """
        if dest is None:
            return self.default_destination
        wanted = dest.value if isinstance(dest, DestinationType) else str(dest).strip().upper()
        for rules in self.destinations:
            if rules.destination_type.value == wanted:
                return rules
        raise KeyError(
            f"{wanted!r} is not a conversion location for {self.objective.value}; "
            f"allowed: {[d.destination_type.value for d in self.destinations]}"
        )

    def allows_destination_type(self, dest: str) -> bool:
        return dest in {d.destination_type.value for d in self.destinations}

    def allows_bid_strategy(self, strategy: str) -> bool:
        return strategy in {s.value for s in self.bid_strategies}

    # ── unions across destinations ───────────────────────────────────────────
    # For consumers that need "anything this objective can do" without knowing a
    # destination — the campaign-level CTA superset, and error messages. The
    # *precise* check always goes through ``for_destination``.

    def _union(self, attr: str) -> tuple:
        seen: dict = {}
        for dest in self.destinations:
            for value in getattr(dest, attr):
                seen[value] = None
        return tuple(seen)

    @property
    def destination_types(self) -> tuple[DestinationType, ...]:
        return tuple(d.destination_type for d in self.destinations)

    @property
    def optimization_goals(self) -> tuple[OptimizationGoal, ...]:
        return self._union("optimization_goals")

    @property
    def billing_events(self) -> tuple[BillingEvent, ...]:
        return self._union("billing_events")

    @property
    def call_to_actions(self) -> tuple[CallToAction, ...]:
        return self._union("call_to_actions")

    @property
    def required_user_info(self) -> tuple[str, ...]:
        """Only what EVERY destination needs — an intersection, not a union.

        A key one destination requires is not required by the objective: Leads
        via Instant forms needs no website, so making ``website_url`` an
        objective-level requirement would block a valid campaign.
        """
        sets = [set(d.required_user_info) for d in self.destinations]
        common = set.intersection(*sets) if sets else set()
        return tuple(sorted(common))


_O = OptimizationGoal
_B = BillingEvent
_D = DestinationType
_S = BidStrategy
_A = CallToAction
_F = AdFormat


OBJECTIVE_MATRIX: dict[Objective, ObjectiveRules] = {
    # ── Awareness ────────────────────────────────────────────────────────────
    # No conversion tracking, no promoted object. Optimizes for eyeballs.
    #
    # ONE destination on purpose. Ads Manager shows no conversion location on an
    # Awareness ad set — the ad simply carries a link (or does not), which is an
    # ad-level field. We used to offer Website vs "On your ad" here, a choice
    # Meta does not ask for and that nothing downstream varies on: the goals,
    # billing events and (absent) promoted object were identical between them.
    # The editor hides a single-destination select, so Awareness now matches.
    Objective.AWARENESS: ObjectiveRules(
        objective=Objective.AWARENESS,
        label="Awareness",
        bid_strategies=(_S.LOWEST_COST_WITHOUT_CAP, _S.COST_CAP, _S.LOWEST_COST_WITH_BID_CAP),
        help_text="Show your ad to as many relevant people as possible. No website or pixel required.",
        allows_frequency_control=True,
        destinations=(
            DestinationRules(
                destination_type=_D.WEBSITE,
                optimization_goals=(_O.REACH, _O.IMPRESSIONS, _O.AD_RECALL_LIFT, _O.THRUPLAY),
                billing_events=(_B.IMPRESSIONS, _B.THRUPLAY),
                call_to_actions=(
                    _A.LEARN_MORE, _A.WATCH_MORE, _A.WATCH_VIDEO, _A.SHOP_NOW,
                    _A.CONTACT_US, _A.SIGN_UP, _A.GET_OFFER, _A.BOOK_NOW,
                    _A.DOWNLOAD, _A.LISTEN_NOW, _A.LIKE_PAGE,
                ),
                # Deliberately no required_user_info: an Awareness ad does not
                # need a website. Without one the link falls back to the
                # connected Page (_destination_link), and the user can edit it
                # on the ad. Demanding a website here warned about a
                # prerequisite the objective never had.
                #
                # Measured, act_116187595198313 (scripts/probe_meta_matrix.py
                # --existing-post): an ad whose creative is {"object_story_id": …}
                # is ACCEPTED here, so "promote a post I already published" is
                # offered alongside composed copy. It suits the objective — a post
                # that already earned reactions carries that social proof into the
                # reach buy, where a fresh creative starts at zero.
                #
                #   OUTCOME_AWARENESS  WEBSITE  object_story_id creative -> accepted
                #                               conversion_domain        -> accepted
                #
                # The other five objectives are UNMEASURED, not rejected: that run
                # hit the ad-account rate limit (subcode 2446079) after Awareness.
                # They stay False until a resumed run answers for them.
                allows_existing_post=True,
                help_text="Reach is what we optimize for. The ad's link is optional — edit it on the ad below.",
            ),
        ),
    ),

    # ── Traffic ──────────────────────────────────────────────────────────────
    # Needs somewhere to send people. LANDING_PAGE_VIEWS is strictly better than
    # LINK_CLICKS when a pixel exists, but does not require one.
    Objective.TRAFFIC: ObjectiveRules(
        objective=Objective.TRAFFIC,
        label="Traffic",
        bid_strategies=(_S.LOWEST_COST_WITHOUT_CAP, _S.COST_CAP, _S.LOWEST_COST_WITH_BID_CAP),
        help_text="Send people to your website, app or chat. Cheapest way to buy visits.",
        destinations=(
            DestinationRules(
                destination_type=_D.WEBSITE,
                optimization_goals=(
                    _O.LINK_CLICKS, _O.LANDING_PAGE_VIEWS, _O.REACH, _O.IMPRESSIONS,
                ),
                billing_events=(_B.IMPRESSIONS, _B.LINK_CLICKS),
                # No GET_STARTED (Meta does not accept the code at all — see
                # CALL_TO_ACTION_ACCEPTED) and no GET_DIRECTIONS. The latter is a
                # real code, but its button carries a *place* rather than the
                # ad's link, and publish sets every CTA's value to the website
                # URL: "(#100) call_to_action[value][link] should represent a
                # valid URL". Offering it needs a map destination Punk does not
                # collect, so it is out until there is a field to put one in.
                call_to_actions=(
                    _A.LEARN_MORE, _A.SHOP_NOW, _A.BOOK_NOW,
                    _A.DOWNLOAD, _A.CONTACT_US, _A.GET_OFFER, _A.SIGN_UP,
                    _A.GET_QUOTE, _A.SEE_MORE, _A.WATCH_MORE,
                ),
                required_user_info=("website_url",),
                help_text="Send people to your website.",
            ),
            # Measured: this conversion location does NOT work under Engagement —
            # Instagram profile + PROFILE_VISIT and + VISIT_INSTAGRAM_PROFILE are
            # both rejected there with subcode 2490408, and Engagement accepts no
            # profile goal at all. Under Traffic both are accepted. It used to sit
            # on Engagement, where it could be picked and never published.
            DestinationRules(
                destination_type=_D.INSTAGRAM_PROFILE,
                optimization_goals=(_O.VISIT_INSTAGRAM_PROFILE, _O.LINK_CLICKS),
                billing_events=(_B.IMPRESSIONS,),
                # Measured: FOLLOW_PAGE — the default this shipped with — is
                # rejected by Meta on both goals with "(#100) call_to_action[type]
                # must be one of the following values: …", and the list it names
                # carries VIEW_INSTAGRAM_PROFILE and LIKE_PAGE instead. Every
                # Instagram-profile ad built from the defaults died at
                # ad_creative, after its campaign and ad set already existed.
                call_to_actions=(
                    _A.VIEW_INSTAGRAM_PROFILE, _A.LEARN_MORE, _A.SEE_MORE,
                ),
                ad_formats=(_F.SINGLE,),
                # Measured: without a linked Instagram account the ad is rejected
                # at creation — subcode 3907008, "Your ad must be associated with
                # an Instagram account". That is past the preflight rollback, so
                # the prerequisite is declared here and the editor can say so
                # while the destination is still being chosen.
                required_user_info=("meta_instagram_user_id",),
                help_text="Drive visits to your Instagram profile.",
            ),
            DestinationRules(
                destination_type=_D.APP,
                optimization_goals=(_O.LINK_CLICKS, _O.REACH, _O.IMPRESSIONS),
                billing_events=(_B.IMPRESSIONS, _B.LINK_CLICKS),
                call_to_actions=(
                    _A.INSTALL_MOBILE_APP, _A.DOWNLOAD, _A.LEARN_MORE, _A.PLAY_GAME,
                    _A.SHOP_NOW,
                ),
                # Measured: Meta rejects any APP destination without one —
                # "Application is required in Promoted Object for App Destination
                # Type" — whatever the goal. Without these three entries the
                # conversion location could be picked and never published.
                promoted_object_by_goal={
                    _O.LINK_CLICKS: PROMOTED_APPLICATION,
                    _O.REACH: PROMOTED_APPLICATION,
                    _O.IMPRESSIONS: PROMOTED_APPLICATION,
                },
                required_user_info=("app_store_url",),
                help_text="Send people to your app's store listing.",
            ),
            DestinationRules(
                destination_type=_D.MESSENGER,
                publisher_platforms=_MESSAGING_PLATFORMS,
                optimization_goals=(_O.LINK_CLICKS, _O.IMPRESSIONS, _O.REACH),
                billing_events=(_B.IMPRESSIONS,),
                call_to_actions=(_A.MESSAGE_PAGE, _A.LEARN_MORE, _A.CONTACT_US),
                # A messaging ad's tap opens a thread — a carousel of links is not
                # the shape Meta renders here.
                ad_formats=(_F.SINGLE,),
                help_text="Start a Messenger conversation with your Page.",
            ),
            DestinationRules(
                destination_type=_D.WHATSAPP,
                publisher_platforms=_MESSAGING_PLATFORMS,
                optimization_goals=(_O.LINK_CLICKS, _O.IMPRESSIONS, _O.REACH),
                billing_events=(_B.IMPRESSIONS,),
                # WHATSAPP_MESSAGE only. The other CTAs are legal Meta codes but
                # carry a link value instead of an app_destination, so picking one
                # turns a Click-to-WhatsApp ad into a browser link to WhatsApp's
                # generic send page — and the brief's own "LEARN_MORE" suggestion
                # was winning by default.
                call_to_actions=(_A.WHATSAPP_MESSAGE,),
                ad_formats=(_F.SINGLE,),
                # Click-to-WhatsApp is a Page-promoting ad set: Meta reads the
                # WhatsApp number off the Page, which is also why this no longer
                # asks the advertiser to type one. Every goal needs it — without a
                # promoted_object the ad set publishes as a plain link-click ad
                # that happens to say WhatsApp on the button.
                promoted_object_by_goal={
                    _O.LINK_CLICKS: PROMOTED_PAGE,
                    _O.IMPRESSIONS: PROMOTED_PAGE,
                    _O.REACH: PROMOTED_PAGE,
                },
                required_user_info=("page_whatsapp",),
                help_text="Start a WhatsApp conversation with your business number.",
            ),
        ),
    ),

    # ── Engagement ───────────────────────────────────────────────────────────
    # Each conversion location is a genuinely different ad here: boosting a post,
    # growing a Page, filling an event, or opening a chat.
    Objective.ENGAGEMENT: ObjectiveRules(
        objective=Objective.ENGAGEMENT,
        label="Engagement",
        bid_strategies=(_S.LOWEST_COST_WITHOUT_CAP, _S.COST_CAP),
        help_text="Get more post engagement, page likes, event responses or video views.",
        allows_frequency_control=True,
        destinations=(
            # Composable destinations first: the first entry is the default,
            # and the builder seeds the initial plan from it. A boost
            # destination cannot be seeded — it needs a Page post the user
            # has not picked yet — so defaulting to one left every Engagement
            # plan unbuildable.
            DestinationRules(
                destination_type=_D.WEBSITE,
                # No destination_type on the wire — see the field's comment.
                # All 12 goals Engagement accepts were probed with the field: 11
                # rejected 2490408, and the twelfth (DERIVED_EVENTS, which this
                # destination does not offer) only wanted a pixel. Engagement
                # defaults here, so sending it failed the whole objective.
                omit_destination_type=True,
                # No POST_ENGAGEMENT. Measured on two ad accounts in different
                # currencies: it is accepted at preflight and then fails at AD
                # creation with subcode 1885154, "Your campaign must include an ad
                # set with a selected object to promote related to your objective
                # (ex: Page, URL, event)" — past the rollback, leaving a campaign
                # and ad set behind. The same goal publishes fine on ON_POST,
                # where the post IS the object being promoted, and LINK_CLICKS and
                # REACH publish fine here. Engagement on a website link ad has no
                # post to engage with, so Meta has nothing to name.
                #
                # It was the FIRST entry, so it was also this objective's default:
                # a plain Engagement campaign built from defaults could not
                # publish an ad. LINK_CLICKS now leads.
                optimization_goals=(_O.LINK_CLICKS, _O.REACH),
                # No POST_ENGAGEMENT billing: GOAL_RULES pins every goal here to
                # impressions, so the pair was unreachable and the option was
                # dead in the editor's billing list.
                billing_events=(_B.IMPRESSIONS,),
                call_to_actions=(
                    _A.LEARN_MORE, _A.SHOP_NOW, _A.BOOK_NOW, _A.GET_OFFER,
                    _A.SIGN_UP,
                ),
                # NO promoted_object here, measured twice over. Attaching the
                # Page flips Meta's reading of the ad set to a Page-promoting one,
                # where these goals are not valid, and the whole thing is rejected
                # at preflight with subcode 2490408 ("You can't use the selected
                # performance goal with your campaign objective") — including
                # LINK_CLICKS and REACH, which publish fine without it.
                #
                # The goal that needed one (POST_ENGAGEMENT) is gone from this
                # conversion location — see the optimization_goals comment.
                required_user_info=("website_url",),
                help_text="Engagement ads that also link out to your site.",
            ),
            DestinationRules(
                destination_type=_D.MESSENGER,
                publisher_platforms=_MESSAGING_PLATFORMS,
                # CONVERSATIONS is a messaging goal — it belongs to a messaging
                # destination and nowhere else.
                #
                # No REACH. Measured: Engagement → Messenger rejects it with
                # subcode 2490408, "You can't use the selected performance goal
                # with your campaign objective". It is neither the objective nor
                # the destination on its own — Engagement accepts REACH at the
                # objective level and on FACEBOOK_LIVE, and Traffic → Messenger
                # accepts it too. Only the *pair* is rejected, which is precisely
                # the class of rule a two-axis matrix cannot express and the
                # reason the probe measures goal × destination separately.
                optimization_goals=(_O.CONVERSATIONS, _O.IMPRESSIONS),
                billing_events=(_B.IMPRESSIONS,),
                call_to_actions=(_A.MESSAGE_PAGE, _A.CONTACT_US, _A.LEARN_MORE),
                ad_formats=(_F.SINGLE,),
                help_text="Start conversations in Messenger.",
            ),
            DestinationRules(
                destination_type=_D.WHATSAPP,
                publisher_platforms=_MESSAGING_PLATFORMS,
                # No REACH, for the same measured reason as Messenger above.
                # WhatsApp alone was not probed, but all three messaging
                # destinations that were (MESSENGER, INSTAGRAM_DIRECT,
                # MESSAGING_INSTAGRAM_DIRECT_MESSENGER) reject it under this
                # objective and accept it under Traffic.
                optimization_goals=(_O.CONVERSATIONS, _O.IMPRESSIONS),
                billing_events=(_B.IMPRESSIONS,),
                call_to_actions=(_A.WHATSAPP_MESSAGE,),
                ad_formats=(_F.SINGLE,),
                promoted_object_by_goal={
                    _O.CONVERSATIONS: PROMOTED_PAGE,
                    _O.IMPRESSIONS: PROMOTED_PAGE,
                },
                required_user_info=("page_whatsapp",),
                help_text="Start conversations on WhatsApp.",
            ),
            DestinationRules(
                destination_type=_D.ON_PAGE,
                # Page likes only. Measured: POST_ENGAGEMENT and REACH are both
                # rejected here with subcode 2490408, "You can't use the selected
                # performance goal with your campaign objective" — not a missing
                # promoted object, which Meta reports separately as 1815430.
                # Growing a Page is the only thing this conversion location does.
                optimization_goals=(_O.PAGE_LIKES,),
                # POST_ENGAGEMENT billing dropped: GOAL_RULES[PAGE_LIKES] allows
                # impressions and per-like only, so the pair never validated.
                billing_events=(_B.IMPRESSIONS, _B.PAGE_LIKES),
                # LIKE_PAGE, not FOLLOW_PAGE: the latter is the value Meta
                # rejected on the Instagram-profile destination, and its accepted
                # list names LIKE_PAGE. It is also what this ad actually asks for.
                call_to_actions=(_A.LIKE_PAGE, _A.LEARN_MORE),
                ad_formats=(_F.SINGLE,),
                # Page likes is the one Engagement goal Meta ties to a promoted
                # object — it has to know which Page it is growing.
                promoted_object_by_goal={_O.PAGE_LIKES: PROMOTED_PAGE},
                help_text="Grow the following on your Facebook Page.",
            ),
            DestinationRules(
                destination_type=_D.ON_POST,
                object_story_kind="post",
                # No IMPRESSIONS. Measured, and Meta says why in as many words:
                # subcode 3858327, "Optimizing for impressions is no longer
                # available. You can optimize for reach instead."
                optimization_goals=(_O.POST_ENGAGEMENT, _O.REACH),
                # See the Engagement → Website row: POST_ENGAGEMENT billing is
                # accepted by no GoalRules, so offering it here only produced an
                # option the spec rejected before Meta ever saw it.
                billing_events=(_B.IMPRESSIONS,),
                call_to_actions=(
                    _A.LEARN_MORE, _A.SEE_MORE, _A.GET_OFFER, _A.SHOP_NOW,
                    _A.CONTACT_US,
                ),
                help_text="Reactions, comments and shares on your post.",
            ),
            DestinationRules(
                destination_type=_D.ON_VIDEO,
                object_story_kind="video",
                # ThruPlay only. Measured: REACH and IMPRESSIONS are both rejected
                # with 2490408. Boosting a video optimizes for watch time; the
                # frequency goals belong to a plain Awareness campaign.
                optimization_goals=(_O.THRUPLAY,),
                billing_events=(_B.IMPRESSIONS, _B.THRUPLAY),
                call_to_actions=(_A.WATCH_MORE, _A.WATCH_VIDEO, _A.LEARN_MORE),
                ad_formats=(_F.SINGLE,),
                help_text="Get people to watch your video through.",
            ),
            DestinationRules(
                destination_type=_D.ON_EVENT,
                object_story_kind="event",
                optimization_goals=(_O.EVENT_RESPONSES, _O.POST_ENGAGEMENT, _O.REACH),
                # POST_ENGAGEMENT billing dropped for the same reason as the two
                # rows above — no goal here accepts it.
                billing_events=(_B.IMPRESSIONS,),
                call_to_actions=(_A.EVENT_RSVP, _A.BUY_TICKETS, _A.LEARN_MORE),
                ad_formats=(_F.SINGLE,),
                help_text="Fill your Facebook event.",
            ),
        ),
    ),

    # ── Leads ────────────────────────────────────────────────────────────────
    # The clearest case for the two-axis matrix. Instant forms and Website leads
    # share nothing below the objective: different goal, different promoted
    # object, different creative requirements, different prerequisites.
    Objective.LEADS: ObjectiveRules(
        objective=Objective.LEADS,
        label="Leads",
        bid_strategies=(_S.LOWEST_COST_WITHOUT_CAP, _S.COST_CAP, _S.LOWEST_COST_WITH_BID_CAP),
        help_text="Collect leads through an instant form on Meta, or a form on your own site.",
        destinations=(
            DestinationRules(
                destination_type=_D.ON_AD,
                # LEAD_GENERATION is the Instant Form goal. It was previously
                # paired with the WEBSITE default — a combination Meta rejects.
                optimization_goals=(_O.LEAD_GENERATION, _O.QUALITY_LEAD),
                billing_events=(_B.IMPRESSIONS,),
                call_to_actions=(
                    _A.SIGN_UP, _A.APPLY_NOW, _A.GET_QUOTE, _A.LEARN_MORE,
                    _A.DOWNLOAD, _A.SUBSCRIBE, _A.GET_OFFER, _A.REQUEST_TIME,
                ),
                promoted_object_by_goal={
                    _O.LEAD_GENERATION: PROMOTED_PAGE,
                    _O.QUALITY_LEAD: PROMOTED_PAGE,
                },
                requires_lead_form=True,
                help_text="People fill in a form without leaving Meta. Highest volume, lowest intent.",
            ),
            DestinationRules(
                destination_type=_D.WEBSITE,
                optimization_goals=(
                    _O.OFFSITE_CONVERSIONS, _O.LANDING_PAGE_VIEWS, _O.LINK_CLICKS,
                ),
                billing_events=(_B.IMPRESSIONS, _B.LINK_CLICKS),
                call_to_actions=(
                    _A.SIGN_UP, _A.APPLY_NOW, _A.GET_QUOTE, _A.CONTACT_US,
                    _A.LEARN_MORE, _A.MAKE_AN_APPOINTMENT,
                    _A.DOWNLOAD, _A.SUBSCRIBE,
                ),
                promoted_object_by_goal={_O.OFFSITE_CONVERSIONS: PROMOTED_PIXEL},
                required_user_info=("website_url",),
                help_text="People fill in the form on your own site. Needs a pixel firing a Lead event.",
            ),
            DestinationRules(
                destination_type=_D.MESSENGER,
                publisher_platforms=_MESSAGING_PLATFORMS,
                optimization_goals=(_O.LEAD_GENERATION, _O.CONVERSATIONS),
                billing_events=(_B.IMPRESSIONS,),
                call_to_actions=(_A.MESSAGE_PAGE, _A.CONTACT_US, _A.LEARN_MORE),
                ad_formats=(_F.SINGLE,),
                promoted_object_by_goal={_O.LEAD_GENERATION: PROMOTED_PAGE},
                help_text="Qualify leads through a Messenger conversation.",
            ),
            DestinationRules(
                destination_type=_D.WHATSAPP,
                publisher_platforms=_MESSAGING_PLATFORMS,
                optimization_goals=(_O.LEAD_GENERATION, _O.CONVERSATIONS),
                billing_events=(_B.IMPRESSIONS,),
                call_to_actions=(_A.WHATSAPP_MESSAGE,),
                ad_formats=(_F.SINGLE,),
                promoted_object_by_goal={
                    _O.LEAD_GENERATION: PROMOTED_PAGE,
                    _O.CONVERSATIONS: PROMOTED_PAGE,
                },
                required_user_info=("page_whatsapp",),
                help_text="Qualify leads through a WhatsApp conversation.",
            ),
        ),
    ),

    # ── App promotion ────────────────────────────────────────────────────────
    # Always needs the app registered on the ad account plus a store URL.
    #
    # App installs is the only optimization goal offered. The other three
    # (link clicks, app events, value) all optimize for something that happens
    # *after* the install and need the Meta SDK reporting in-app events from a
    # live app — a prerequisite we neither collect nor can check. Offering them
    # produced ad sets Meta accepts and then cannot deliver against.
    Objective.APP_PROMOTION: ObjectiveRules(
        objective=Objective.APP_PROMOTION,
        label="App promotion",
        bid_strategies=(_S.LOWEST_COST_WITHOUT_CAP, _S.COST_CAP, _S.LOWEST_COST_WITH_BID_CAP),
        help_text="Drive app installs. Requires an app linked to your ad account and a store link.",
        destinations=(
            DestinationRules(
                destination_type=_D.APP,
                optimization_goals=(_O.APP_INSTALLS,),
                # Per-install billing retired by Meta — see GOAL_RULES above.
                billing_events=(_B.IMPRESSIONS,),
                call_to_actions=(
                    _A.INSTALL_MOBILE_APP, _A.DOWNLOAD, _A.LEARN_MORE, _A.PLAY_GAME,
                ),
                promoted_object_by_goal={_O.APP_INSTALLS: PROMOTED_APPLICATION},
                required_user_info=("app_store_url",),
                help_text="Send people to your app's store listing.",
            ),
        ),
    ),

    # ── Sales ────────────────────────────────────────────────────────────────
    # The conversion objective. Every goal except the soft fallbacks needs a
    # pixel — publishing OFFSITE_CONVERSIONS without one is what the old code
    # did silently, and it spends money optimizing on a signal that never fires.
    Objective.SALES: ObjectiveRules(
        objective=Objective.SALES,
        label="Sales",
        bid_strategies=(
            _S.LOWEST_COST_WITHOUT_CAP, _S.COST_CAP,
            _S.LOWEST_COST_WITH_BID_CAP, _S.LOWEST_COST_WITH_MIN_ROAS,
        ),
        help_text="Optimize for purchases or other high-value conversions. Requires a Meta Pixel.",
        destinations=(
            DestinationRules(
                destination_type=_D.WEBSITE,
                # No destination_type on the wire — see the field's comment.
                # All 9 goals Sales accepts were probed with the field, including
                # OFFSITE_CONVERSIONS and VALUE, the two this destination is for:
                # 8 rejected 2490408. LINK_CLICKS, LANDING_PAGE_VIEWS and REACH
                # were then accepted with it omitted. Sales defaults here, so this
                # broke the objective the product exists to sell.
                omit_destination_type=True,
                optimization_goals=(
                    _O.OFFSITE_CONVERSIONS, _O.VALUE, _O.LANDING_PAGE_VIEWS,
                    _O.LINK_CLICKS, _O.REACH,
                ),
                billing_events=(_B.IMPRESSIONS, _B.LINK_CLICKS),
                call_to_actions=(
                    _A.SHOP_NOW, _A.ORDER_NOW, _A.BUY_NOW, _A.BOOK_NOW, _A.GET_OFFER,
                    _A.SUBSCRIBE, _A.LEARN_MORE, _A.SIGN_UP, _A.GET_QUOTE,
                    _A.DOWNLOAD, _A.START_ORDER, _A.BUY_TICKETS,
                ),
                promoted_object_by_goal={
                    _O.OFFSITE_CONVERSIONS: PROMOTED_PIXEL,
                    _O.VALUE: PROMOTED_PIXEL,
                },
                required_user_info=("website_url",),
                help_text="Sell on your own site. Needs a Meta Pixel.",
            ),
            DestinationRules(
                destination_type=_D.APP,
                # No VALUE. Measured live (scripts/live_publish_matrix.py
                # sales.app.value): Meta rejects the ad set at creation with
                # subcode 2490408 blaming ``optimization_goal`` — "You can't use
                # the selected performance goal with your campaign objective."
                # Value optimization on this objective exists only on WEBSITE,
                # where a pixel reports purchase values; an app destination has
                # none to bid against. Offering it here produced a plan that could
                # never publish.
                optimization_goals=(_O.OFFSITE_CONVERSIONS, _O.LINK_CLICKS),
                billing_events=(_B.IMPRESSIONS, _B.LINK_CLICKS),
                call_to_actions=(
                    _A.SHOP_NOW, _A.BUY_NOW, _A.ORDER_NOW, _A.INSTALL_MOBILE_APP,
                    _A.LEARN_MORE,
                ),
                promoted_object_by_goal={
                    _O.OFFSITE_CONVERSIONS: PROMOTED_APPLICATION,
                    # LINK_CLICKS was missing, so this goal shipped an APP ad set
                    # with no promoted object — the same rejection Traffic → App
                    # gave: "Application is required in Promoted Object".
                    _O.LINK_CLICKS: PROMOTED_APPLICATION,
                },
                required_user_info=("app_store_url",),
                help_text="Sell inside your app.",
            ),
            DestinationRules(
                destination_type=_D.MESSENGER,
                publisher_platforms=_MESSAGING_PLATFORMS,
                optimization_goals=(_O.CONVERSATIONS, _O.OFFSITE_CONVERSIONS),
                billing_events=(_B.IMPRESSIONS,),
                call_to_actions=(_A.MESSAGE_PAGE, _A.SHOP_NOW, _A.LEARN_MORE),
                ad_formats=(_F.SINGLE,),
                promoted_object_by_goal={_O.OFFSITE_CONVERSIONS: PROMOTED_PIXEL},
                help_text="Close sales in a Messenger conversation.",
            ),
            DestinationRules(
                destination_type=_D.WHATSAPP,
                publisher_platforms=_MESSAGING_PLATFORMS,
                optimization_goals=(_O.CONVERSATIONS, _O.OFFSITE_CONVERSIONS),
                billing_events=(_B.IMPRESSIONS,),
                call_to_actions=(_A.WHATSAPP_MESSAGE,),
                ad_formats=(_F.SINGLE,),
                # Conversations promote the Page (that is where the WhatsApp
                # number lives); optimizing for purchases still needs the pixel
                # that records them, exactly as the Messenger row above.
                promoted_object_by_goal={
                    _O.CONVERSATIONS: PROMOTED_PAGE,
                    _O.OFFSITE_CONVERSIONS: PROMOTED_PIXEL,
                },
                required_user_info=("page_whatsapp",),
                help_text="Close sales in a WhatsApp conversation.",
            ),
        ),
    ),
}


# Default pixel event per objective, used when building promoted_object and the
# user has expressed no preference. Mirrors the old media.py behaviour
# (SALES → PURCHASE, LEADS → LEAD) but is now data rather than an inline
# ternary buried in the publish path.
DEFAULT_PIXEL_EVENT: dict[Objective, str] = {
    Objective.SALES: "PURCHASE",
    Objective.LEADS: "LEAD",
    Objective.APP_PROMOTION: "PURCHASE",
}


def matrix_for(objective: Objective | str) -> ObjectiveRules:
    """Rules for an objective. Accepts the enum or any form ``normalize_objective``
    understands.

    Raises ``KeyError`` for an unrecognized objective — deliberately loud. The
    previous behaviour silently fell back to awareness/REACH, which published a
    campaign optimizing for something nobody chose.
    """
    if isinstance(objective, Objective):
        return OBJECTIVE_MATRIX[objective]

    from app.graph.meta_spec.enums import normalize_objective

    resolved = normalize_objective(objective)
    if resolved is None:
        raise KeyError(f"unknown campaign objective: {objective!r}")
    return OBJECTIVE_MATRIX[resolved]


def rules_for(
    objective: Objective | str, destination: DestinationType | str | None = None
) -> tuple[ObjectiveRules, DestinationRules]:
    """Both halves at once — the pair almost every caller actually wants."""
    obj_rules = matrix_for(objective)
    return obj_rules, obj_rules.for_destination(destination)


__all__ = [
    "DEFAULT_GOAL_RULES",
    "DEFAULT_PIXEL_EVENT",
    "GOAL_RULES",
    "GoalRules",
    "MESSENGER_NEEDS_COMPANION",
    "MediaKind",
    "OBJECTIVE_MATRIX",
    "PROMOTED_APPLICATION",
    "PROMOTED_NONE",
    "PROMOTED_PAGE",
    "PROMOTED_PIXEL",
    "DestinationRules",
    "ObjectiveRules",
    "goal_rules",
    "matrix_for",
    "rules_for",
]
