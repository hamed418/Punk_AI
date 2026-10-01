"""
graph/meta_spec/enums.py
────────────────────────
Meta enum vocabulary, sourced from the installed ``facebook_business`` SDK
rather than retyped by hand.

``facebook_business==25.0.1`` ships every Graph API enum as plain class
attributes (``Campaign.Objective.outcome_sales == "OUTCOME_SALES"``). Reading
them here means an SDK bump updates our vocabulary for free, and a value we
reference that Meta has retired fails at import time instead of at publish time.

The SDK is used for **values only**. Transport stays raw ``httpx`` in
``app/services/meta_ads.py`` — ``FacebookAdsApi`` is synchronous and would block
the event loop.

Each ``StrEnum`` below is a curated subset: the values Punk can actually produce.
The full SDK enum is far wider (101 CTA codes, 23 destination types); offering
all of them in a form would be noise. ``*_ALL`` frozensets keep the full SDK set
available for permissive validation of values that arrive from elsewhere.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from facebook_business.adobjects.adcreative import AdCreative
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.campaign import Campaign

_C = Campaign
_A = AdSet
_CR = AdCreative


def _sdk_values(enum_cls: type) -> frozenset[str]:
    """Every string constant on an SDK enum class."""
    return frozenset(
        v for k, v in vars(enum_cls).items()
        if not k.startswith("_") and isinstance(v, str)
    )


# ── Campaign objective ───────────────────────────────────────────────────────
# ODAX outcome objectives only. The SDK still carries the pre-2022 vocabulary
# (LINK_CLICKS, CONVERSIONS, BRAND_AWARENESS…); Meta rejects those for new
# campaigns, so they are deliberately absent here.


class Objective(StrEnum):
    AWARENESS = _C.Objective.outcome_awareness
    TRAFFIC = _C.Objective.outcome_traffic
    ENGAGEMENT = _C.Objective.outcome_engagement
    LEADS = _C.Objective.outcome_leads
    APP_PROMOTION = _C.Objective.outcome_app_promotion
    SALES = _C.Objective.outcome_sales


OBJECTIVE_ALL: frozenset[str] = _sdk_values(_C.Objective)


# Punk's internal short names (used throughout user_info, slots, and the brief
# prompts) → the Meta wire value. Kept here so the mapping has one home; it was
# previously duplicated in meta_ads.OBJECTIVE_MAP and campaign._VALID_OBJECTIVES.
_SHORT_TO_OBJECTIVE: dict[str, Objective] = {
    "AWARENESS": Objective.AWARENESS,
    "TRAFFIC": Objective.TRAFFIC,
    "ENGAGEMENT": Objective.ENGAGEMENT,
    "LEADS": Objective.LEADS,
    "APP_PROMOTION": Objective.APP_PROMOTION,
    "SALES": Objective.SALES,
}


def normalize_objective(raw: str | None) -> Objective | None:
    """Accept a short name ("SALES"), a display name ("App Promotion"), or the
    wire value ("OUTCOME_SALES") and return the canonical ``Objective``.

    Returns ``None`` for anything unrecognized — callers decide whether that is
    a re-ask or an error. It never silently defaults; the old
    ``meta_ads.create_campaign`` fell back to ``OUTCOME_AWARENESS``, which
    published a campaign optimizing for something the user never asked for.
    """
    if not raw:
        return None
    token = str(raw).strip().upper().replace(" ", "_").replace("-", "_")
    if token in _SHORT_TO_OBJECTIVE:
        return _SHORT_TO_OBJECTIVE[token]
    try:
        return Objective(token)
    except ValueError:
        return None


# ── Ad set optimization goal ─────────────────────────────────────────────────


class OptimizationGoal(StrEnum):
    AD_RECALL_LIFT = _A.OptimizationGoal.ad_recall_lift
    APP_INSTALLS = _A.OptimizationGoal.app_installs
    CONVERSATIONS = _A.OptimizationGoal.conversations
    ENGAGED_USERS = _A.OptimizationGoal.engaged_users
    EVENT_RESPONSES = _A.OptimizationGoal.event_responses
    IMPRESSIONS = _A.OptimizationGoal.impressions
    LANDING_PAGE_VIEWS = _A.OptimizationGoal.landing_page_views
    LEAD_GENERATION = _A.OptimizationGoal.lead_generation
    LINK_CLICKS = _A.OptimizationGoal.link_clicks
    OFFSITE_CONVERSIONS = _A.OptimizationGoal.offsite_conversions
    PAGE_LIKES = _A.OptimizationGoal.page_likes
    POST_ENGAGEMENT = _A.OptimizationGoal.post_engagement
    # Both names validate, but VISIT_INSTAGRAM_PROFILE is the one Meta returns
    # as accepted for OUTCOME_TRAFFIC at objective level, and PROFILE_VISIT is
    # not accepted there at all — a legacy alias that still passes when a
    # destination_type pins the meaning. Measured on act_997894704000491:
    # Traffic + Instagram profile accepts both; Engagement accepts neither.
    VISIT_INSTAGRAM_PROFILE = _A.OptimizationGoal.visit_instagram_profile
    QUALITY_CALL = _A.OptimizationGoal.quality_call
    QUALITY_LEAD = _A.OptimizationGoal.quality_lead
    REACH = _A.OptimizationGoal.reach
    THRUPLAY = _A.OptimizationGoal.thruplay
    VALUE = _A.OptimizationGoal.value


OPTIMIZATION_GOAL_ALL: frozenset[str] = _sdk_values(_A.OptimizationGoal)


# ── Ad set billing event ─────────────────────────────────────────────────────


class BillingEvent(StrEnum):
    APP_INSTALLS = _A.BillingEvent.app_installs
    IMPRESSIONS = _A.BillingEvent.impressions
    LINK_CLICKS = _A.BillingEvent.link_clicks
    PAGE_LIKES = _A.BillingEvent.page_likes
    POST_ENGAGEMENT = _A.BillingEvent.post_engagement
    THRUPLAY = _A.BillingEvent.thruplay


BILLING_EVENT_ALL: frozenset[str] = _sdk_values(_A.BillingEvent)


# ── Ad set destination type (Ads Manager calls this "conversion location") ───
# NOTE: there is no PHONE_CALL member in the v25 SDK — call ads are expressed
# through the creative's CALL_NOW CTA, not a destination type. Only values the
# SDK actually defines appear here.


class DestinationType(StrEnum):
    APP = _A.DestinationType.app
    FACEBOOK = _A.DestinationType.facebook
    INSTAGRAM_PROFILE = _A.DestinationType.instagram_profile
    MESSENGER = _A.DestinationType.messenger
    ON_AD = _A.DestinationType.on_ad
    ON_EVENT = _A.DestinationType.on_event
    ON_PAGE = _A.DestinationType.on_page
    ON_POST = _A.DestinationType.on_post
    ON_VIDEO = _A.DestinationType.on_video
    # Shops ads. Defined because it is a real SDK value, but deliberately not
    # offered by any objective: it needs a product catalog and product set on the
    # promoted object, and Meta documents its parent objective as
    # PRODUCT_CATALOG_SALES / CONVERSIONS — both retired for new ODAX campaigns.
    # Offering it under Sales produced a plan that could not publish.
    SHOP_AUTOMATIC = _A.DestinationType.shop_automatic
    WEBSITE = _A.DestinationType.website
    WHATSAPP = _A.DestinationType.whatsapp


DESTINATION_TYPE_ALL: frozenset[str] = _sdk_values(_A.DestinationType)


# ── Bid strategy ─────────────────────────────────────────────────────────────


class BidStrategy(StrEnum):
    LOWEST_COST_WITHOUT_CAP = _C.BidStrategy.lowest_cost_without_cap
    LOWEST_COST_WITH_BID_CAP = _C.BidStrategy.lowest_cost_with_bid_cap
    COST_CAP = _C.BidStrategy.cost_cap
    LOWEST_COST_WITH_MIN_ROAS = _C.BidStrategy.lowest_cost_with_min_roas


BID_STRATEGY_ALL: frozenset[str] = _sdk_values(_C.BidStrategy)

# Strategies that require a companion amount on the ad set. Enforced by
# AdSetSpec — Meta rejects COST_CAP without bid_amount with an opaque error.
BID_STRATEGIES_REQUIRING_AMOUNT: frozenset[str] = frozenset({
    BidStrategy.LOWEST_COST_WITH_BID_CAP,
    BidStrategy.COST_CAP,
})

# The ROAS goal is the odd one out: it takes its target in `bid_constraints`
# rather than `bid_amount`, and Meta rejects the ad set if `bid_amount` is also
# present. Enforced by AdSetSpec.
BID_STRATEGY_REQUIRING_ROAS_FLOOR: str = BidStrategy.LOWEST_COST_WITH_MIN_ROAS.value

# roas_average_floor is scaled 10000x on the wire: 10000 == 1.0x return.
ROAS_FLOOR_SCALE: int = 10_000
ROAS_FLOOR_MIN: int = 100          # 0.01x
ROAS_FLOOR_MAX: int = 10_000_000   # 1000x


# ── Special ad categories ────────────────────────────────────────────────────
# Regulated verticals. Declaring one restricts targeting (no age/gender, coarse
# geo); failing to declare one when it applies gets the campaign rejected or the
# account flagged. Punk hardcoded [] before this package existed.


class SpecialAdCategory(StrEnum):
    EMPLOYMENT = _C.SpecialAdCategories.employment
    HOUSING = _C.SpecialAdCategories.housing
    FINANCIAL_PRODUCTS_SERVICES = _C.SpecialAdCategories.financial_products_services
    # CREDIT is deliberately absent even though the SDK still carries the value.
    # Ads Manager no longer offers it as its own category — credit ads declare
    # under Financial products and services now — so offering it here would show
    # the user a choice their own Ads Manager does not have.
    #
    # ISSUES_ELECTIONS_POLITICS and ONLINE_GAMBLING_AND_GAMING are absent for a
    # different reason. Political ads require per-advertiser identity verification
    # and authorization, and gambling requires written permission from Meta —
    # neither is something Punk can obtain on the user's behalf, so declaring the
    # category here would produce a campaign Meta rejects at review.


SPECIAL_AD_CATEGORY_ALL: frozenset[str] = _sdk_values(_C.SpecialAdCategories)

# The "no special category" sentinel. Meta wants an empty list, not ["NONE"],
# on the campaign payload — NONE exists in the enum but is not a valid element.
SPECIAL_AD_CATEGORY_NONE: str = _C.SpecialAdCategories.none

# Meta's geo floor for a regulated category: ZIP targeting is forbidden outright
# and any radius must be at least 15 miles. Applies to the same categories that
# block demographics, so the two are enforced together.
SPECIAL_CATEGORY_MIN_RADIUS_MILES: int = 15

MILES_PER_KM: float = 0.621371


def radius_meets_special_category_floor(radius: Any, distance_unit: Any) -> bool:
    """Is this ``custom_locations`` ring at or above Meta's 15-mile floor?

    One home for the comparison because it has a trap in it. Ads Manager offers
    metric advertisers **24 km** as the minimum, and 24 km is 14.91 miles — a
    strict ``>= 15`` rejects the value Meta's own UI produces. The 1% tolerance
    covers that rounding without letting a real 14-mile ring through.

    An unparseable radius is treated as compliant: it is not this function's job
    to reject a malformed field, and Meta's preflight is the authority anyway.
    """
    try:
        value = float(radius)
    except (TypeError, ValueError):
        return True
    miles = (
        value * MILES_PER_KM
        if str(distance_unit or "").strip().lower().startswith("kilo")
        else value
    )
    return miles >= SPECIAL_CATEGORY_MIN_RADIUS_MILES * 0.99

# Categories that forbid age and gender narrowing entirely. Credit used to be the
# third entry here; now that credit ads declare under Financial products and
# services, that category inherits the restriction. Over-restricting costs the
# user some targeting reach — under-restricting costs them the ad account.
CATEGORIES_BLOCKING_DEMOGRAPHICS: frozenset[str] = frozenset({
    SpecialAdCategory.EMPLOYMENT,
    SpecialAdCategory.HOUSING,
    SpecialAdCategory.FINANCIAL_PRODUCTS_SERVICES,
})

# The country whose rules a special ad category declaration is made under. Meta
# requires it alongside any category and accepts any ISO 3166-1 alpha-2 code, so
# this is the full set — the editor used to ship six, which left an advertiser
# outside those markets unable to declare at all.
#
# Hand-listed rather than read off the SDK: facebook_business carries no country
# enum, Meta's geo vocabulary is a live /search?type=adgeolocation call, and this
# list has to stay pure — build_campaign_spec runs on every plan build and every
# checkpoint replay. Codes only; the browser renders the names via
# Intl.DisplayNames rather than us maintaining a translation table.
#
# US and CA first — Punk's markets — then alphabetical, so the common pick is at
# the top of a 249-item list without the client sorting anything.
SPECIAL_AD_CATEGORY_COUNTRIES: tuple[str, ...] = (
    "US", "CA",
    "AD", "AE", "AF", "AG", "AI", "AL", "AM", "AO", "AQ", "AR", "AS", "AT",
    "AU", "AW", "AX", "AZ", "BA", "BB", "BD", "BE", "BF", "BG", "BH", "BI",
    "BJ", "BL", "BM", "BN", "BO", "BQ", "BR", "BS", "BT", "BV", "BW", "BY",
    "BZ", "CC", "CD", "CF", "CG", "CH", "CI", "CK", "CL", "CM", "CN", "CO",
    "CR", "CU", "CV", "CW", "CX", "CY", "CZ", "DE", "DJ", "DK", "DM", "DO",
    "DZ", "EC", "EE", "EG", "EH", "ER", "ES", "ET", "FI", "FJ", "FK", "FM",
    "FO", "FR", "GA", "GB", "GD", "GE", "GF", "GG", "GH", "GI", "GL", "GM",
    "GN", "GP", "GQ", "GR", "GS", "GT", "GU", "GW", "GY", "HK", "HM", "HN",
    "HR", "HT", "HU", "ID", "IE", "IL", "IM", "IN", "IO", "IQ", "IR", "IS",
    "IT", "JE", "JM", "JO", "JP", "KE", "KG", "KH", "KI", "KM", "KN", "KP",
    "KR", "KW", "KY", "KZ", "LA", "LB", "LC", "LI", "LK", "LR", "LS", "LT",
    "LU", "LV", "LY", "MA", "MC", "MD", "ME", "MF", "MG", "MH", "MK", "ML",
    "MM", "MN", "MO", "MP", "MQ", "MR", "MS", "MT", "MU", "MV", "MW", "MX",
    "MY", "MZ", "NA", "NC", "NE", "NF", "NG", "NI", "NL", "NO", "NP", "NR",
    "NU", "NZ", "OM", "PA", "PE", "PF", "PG", "PH", "PK", "PL", "PM", "PN",
    "PR", "PS", "PT", "PW", "PY", "QA", "RE", "RO", "RS", "RU", "RW", "SA",
    "SB", "SC", "SD", "SE", "SG", "SH", "SI", "SJ", "SK", "SL", "SM", "SN",
    "SO", "SR", "SS", "ST", "SV", "SX", "SY", "SZ", "TC", "TD", "TF", "TG",
    "TH", "TJ", "TK", "TL", "TM", "TN", "TO", "TR", "TT", "TV", "TW", "TZ",
    "UA", "UG", "UM", "UY", "UZ", "VA", "VC", "VE", "VG", "VI", "VN", "VU",
    "WF", "WS", "YE", "YT", "ZA", "ZM", "ZW",
)


# ── Creative call-to-action ──────────────────────────────────────────────────
# The SDK defines 101 CTA codes. This is the subset Punk offers.
#
# Three corrections against the previous hand-typed META_CTA_OPTIONS list:
#   - SEE_MENU and SEND_MESSAGE are NOT Meta CTA codes. Both were offered in the
#     creative picker and would have been rejected at ad-creative time. The real
#     codes are START_ORDER (food/menu ordering) and MESSAGE_PAGE (messaging).
#   - INSTALL_MOBILE_APP was already used as the app-promotion default at publish
#     but was missing from the picker, so a user who changed it could never get
#     back to it.


class CallToAction(StrEnum):
    LEARN_MORE = _CR.CallToActionType.learn_more
    SHOP_NOW = _CR.CallToActionType.shop_now
    GET_STARTED = _CR.CallToActionType.get_started
    SIGN_UP = _CR.CallToActionType.sign_up
    SUBSCRIBE = _CR.CallToActionType.subscribe
    GET_OFFER = _CR.CallToActionType.get_offer
    BUY_NOW = _CR.CallToActionType.buy_now
    BOOK_NOW = _CR.CallToActionType.book_now
    BOOK_TRAVEL = _CR.CallToActionType.book_travel
    ORDER_NOW = _CR.CallToActionType.order_now
    START_ORDER = _CR.CallToActionType.start_order
    CONTACT_US = _CR.CallToActionType.contact_us
    GET_QUOTE = _CR.CallToActionType.get_quote
    REQUEST_TIME = _CR.CallToActionType.request_time
    MAKE_AN_APPOINTMENT = _CR.CallToActionType.make_an_appointment
    GET_DIRECTIONS = _CR.CallToActionType.get_directions
    APPLY_NOW = _CR.CallToActionType.apply_now
    DOWNLOAD = _CR.CallToActionType.download
    CALL_NOW = _CR.CallToActionType.call_now
    MESSAGE_PAGE = _CR.CallToActionType.message_page
    WHATSAPP_MESSAGE = _CR.CallToActionType.whatsapp_message
    SEE_MORE = _CR.CallToActionType.see_more
    WATCH_MORE = _CR.CallToActionType.watch_more
    WATCH_VIDEO = _CR.CallToActionType.watch_video
    LISTEN_NOW = _CR.CallToActionType.listen_now
    PLAY_GAME = _CR.CallToActionType.play_game
    BUY_TICKETS = _CR.CallToActionType.buy_tickets
    GET_SHOWTIMES = _CR.CallToActionType.get_showtimes
    EVENT_RSVP = _CR.CallToActionType.event_rsvp
    FOLLOW_PAGE = _CR.CallToActionType.follow_page
    LIKE_PAGE = _CR.CallToActionType.like_page
    # Not in the SDK — a fourth place where it trails the API, alongside the
    # three named at the top of this module. Meta names it in the rejection it
    # returns for an Instagram-profile ad ("call_to_action[type] must be one of
    # the following values: … VIEW_INSTAGRAM_PROFILE …"), which is where the
    # value comes from.
    VIEW_INSTAGRAM_PROFILE = "VIEW_INSTAGRAM_PROFILE"
    DONATE_NOW = _CR.CallToActionType.donate_now
    INSTALL_MOBILE_APP = _CR.CallToActionType.install_mobile_app


# The CTA codes Meta itself named as valid for a link creative, verbatim from
# its own rejection: "(#100) call_to_action[type] must be one of the following
# values: …" (act_116187595198313, a Page-linked Traffic ad). This is the only
# authoritative list there is — Meta publishes none, and the SDK's enum is both
# larger and, in places, stale.
#
# Two values Punk offered are absent from it and were rejected at ad-creative
# time, after the campaign and ad set already existed:
#   GET_STARTED  — offered on Traffic → Website and Leads → Website
#   FOLLOW_PAGE  — offered on Awareness, Instagram profile and Page likes
# LIKE_PAGE and VIEW_INSTAGRAM_PROFILE replaced them.
#
# Account-specific eligibility can still narrow this further, so it is a
# build-time guard on the option lists, not a runtime gate.
CALL_TO_ACTION_ACCEPTED: frozenset[str] = frozenset({
    "ADD_TO_CART", "APPLY_NOW", "ASK_ABOUT_SERVICES", "ASK_A_QUESTION",
    "ASK_FOR_MORE_INFO", "ASK_US", "BET_NOW", "BOOK_A_CONSULTATION",
    "BOOK_NOW", "BOOK_TRAVEL", "BUY", "BUY_NOW", "BUY_TICKETS",
    "BUY_VIA_MESSAGE", "CALL", "CALL_ME", "CALL_NOW", "CHAT_NOW",
    "CHAT_ON_WHATSAPP", "CHAT_WITH_US", "CHECK_AVAILABILITY",
    "CIVIC_ACTION", "CONFIRM", "CONTACT_US", "DIAL_CODE", "DONATE",
    "DONATE_NOW", "DOWNLOAD", "EVENT_RSVP", "EXPLORE_MORE",
    "FIND_YOUR_GROUPS", "GET_A_QUOTE", "GET_DIRECTIONS",
    "GET_EVENT_TICKETS", "GET_IN_TOUCH", "GET_MOBILE_APP", "GET_OFFER",
    "GET_OFFER_VIEW", "GET_PROMOTIONS", "GET_QUOTE", "GET_SHOWTIMES",
    "GIVE_FREE_RIDES", "GO_LIVE", "IMAGINE", "INQUIRE_NOW",
    "INSTAGRAM_MESSAGE", "INSTALL_APP", "INSTALL_MOBILE_APP",
    "INTERESTED", "JOIN_CHANNEL", "JOIN_GROUP", "JOIN_LIVE_VIDEO",
    "LEARN_MORE", "LIKE_PAGE", "LINK_CARD", "LISTEN_MUSIC",
    "LISTEN_NOW", "LOYALTY_LEARN_MORE", "MAKE_AN_APPOINTMENT",
    "MESSAGE_PAGE", "MISSED_CALL", "MOBILE_DOWNLOAD", "NO_BUTTON",
    "OPEN_INSTANT_APP", "OPEN_LINK", "OPEN_MESSENGER_EXT", "ORDER_NOW",
    "PAY_TO_ACCESS", "PLAY_GAME", "PLAY_GAME_ON_FACEBOOK",
    "PRE_REGISTER", "PURCHASE_GIFT_CARDS", "RAISE_MONEY", "RECORD_NOW",
    "REFER_FRIENDS", "REGISTER_NOW", "REMIND_ME", "REQUEST_TIME",
    "SAVE", "SEARCH", "SEARCH_MORE", "SEE_DETAILS",
    "SEE_MORE", "SELL_NOW", "SEND_INVITES", "SEND_TIP", "SEND_UPDATES",
    "SHOP_NOW", "SIGN_UP", "START_A_CHAT", "START_ORDER", "SUBSCRIBE",
    "SWIPE_UP_PRODUCT", "SWIPE_UP_SHOP", "TRY_DEMO", "TRY_IN_CAMERA",
    "TRY_IT", "TRY_NOW", "TRY_ON", "UPDATE_APP", "USE_APP",
    "USE_MOBILE_APP", "VIEW_CHANNEL", "VIEW_INSTAGRAM_PROFILE",
    "VIEW_PRODUCT", "VISIT_PROFILE", "VISIT_WORLD", "VOTE_NOW",
    "WATCH_LIVE_VIDEO", "WATCH_MORE", "WATCH_VIDEO", "WHATSAPP_LINK",
    "WHATSAPP_MESSAGE",
})

# "Is this a real Meta code" — the SDK's set plus anything Meta has been
# measured accepting. The SDK still matters because it carries codes this one
# rejection did not enumerate (it is per creative kind); the measured set covers
# what the SDK has not caught up with, e.g. VIEW_INSTAGRAM_PROFILE.
CALL_TO_ACTION_ALL: frozenset[str] = (
    _sdk_values(_CR.CallToActionType) | CALL_TO_ACTION_ACCEPTED
)


# ── Ad format ────────────────────────────────────────────────────────────────
# Ads Manager's "Ad setup" choice. Not a Graph API enum — it selects the shape of
# ``object_story_spec.link_data``: a single ``image_hash``/``video_id``, or a list
# of ``child_attachments``.
#
# Instant Form and catalog sales are deliberately NOT formats here: at Meta they
# are *conversion locations* (destination_type), and an Instant-Form ad can still
# be single or carousel. They live in the objective matrix, not this enum.


class AdFormat(StrEnum):
    SINGLE = "SINGLE"
    CAROUSEL = "CAROUSEL"


# Meta's carousel limits.
CAROUSEL_MIN_CARDS: int = 2
CAROUSEL_MAX_CARDS: int = 10


# ── Instant Form (leadgen) question types ────────────────────────────────────
# The prefill questions Meta can answer from the user's profile. Offered when the
# conversion location is Instant forms; `POST /{page_id}/leadgen_forms` takes them
# as ``questions: [{"type": …}]``.

LEAD_FORM_QUESTION_TYPES: tuple[str, ...] = (
    "FULL_NAME", "EMAIL", "PHONE", "CITY", "STATE", "ZIP",
    "COMPANY_NAME", "JOB_TITLE",
)
# What a generated form asks when the user expresses no preference.
LEAD_FORM_DEFAULT_QUESTIONS: tuple[str, ...] = ("FULL_NAME", "EMAIL", "PHONE")
# Custom questions (type "CUSTOM") are written by the advertiser rather than
# answered from the person's profile. Meta's own limits are higher; these keep a
# form readable — and a 300-character question nobody answers is not a feature.
LEAD_FORM_LABEL_MAX: int = 200
LEAD_FORM_MAX_OPTIONS: int = 20
# The intro ("context") card shown before the questions.
LEAD_FORM_INTRO_TITLE_MAX: int = 60
LEAD_FORM_MAX_INTRO_LINES: int = 5


# ── Display labels ───────────────────────────────────────────────────────────
# Title-casing the raw enum gets most values right ("LINK_CLICKS" → "Link Clicks")
# but silently invents vocabulary for the rest: Ads Manager says "Conversions",
# not "Offsite Conversions"; "Instant forms", not "On Ad". Users compare our form
# against Ads Manager side by side, so the words have to match.
#
# One dict for every enum — keys are unique across them. Anything absent falls
# back to the auto-Title, which is correct for the majority.

META_LABELS: dict[str, str] = {
    # Optimization goals
    "OFFSITE_CONVERSIONS": "Conversions",
    "LANDING_PAGE_VIEWS": "Landing page views",
    "LINK_CLICKS": "Link clicks",
    "POST_ENGAGEMENT": "Post engagement",
    "PAGE_LIKES": "Page likes",
    "EVENT_RESPONSES": "Event responses",
    "AD_RECALL_LIFT": "Ad recall lift",
    "APP_INSTALLS": "App installs",
    "THRUPLAY": "ThruPlay",
    "VALUE": "Value",
    "LEAD_GENERATION": "Leads",
    "QUALITY_LEAD": "Conversion leads",
    "QUALITY_CALL": "Calls",
    "CONVERSATIONS": "Conversations",
    "VISIT_INSTAGRAM_PROFILE": "Instagram profile visits",
    "ENGAGED_USERS": "Engaged users",
    "REACH": "Reach",
    "IMPRESSIONS": "Impressions",
    # Destination types (Ads Manager: "conversion location")
    "ON_AD": "Instant forms",
    "ON_POST": "On your post",
    "ON_PAGE": "On your Page",
    "ON_EVENT": "On your event",
    "ON_VIDEO": "On your video",
    "SHOP_AUTOMATIC": "Shop",
    "INSTAGRAM_PROFILE": "Instagram profile",
    "APP": "Your app",
    "WEBSITE": "Website",
    "MESSENGER": "Messenger",
    "WHATSAPP": "WhatsApp",
    "FACEBOOK": "Facebook",
    # Bid strategies
    "LOWEST_COST_WITHOUT_CAP": "Highest volume",
    "LOWEST_COST_WITH_BID_CAP": "Bid cap",
    "COST_CAP": "Cost per result goal",
    "LOWEST_COST_WITH_MIN_ROAS": "ROAS goal",
    # Ad formats
    "SINGLE": "Single image or video",
    "CAROUSEL": "Carousel",
    # Special ad categories
    "FINANCIAL_PRODUCTS_SERVICES": "Financial products and services",
}


def meta_label(value: str) -> str:
    """Ads Manager's wording for an enum value, or a Title-cased fallback."""
    return META_LABELS.get(value) or value.replace("_", " ").title()


# ── Campaign / ad set / ad status ────────────────────────────────────────────


class EntityStatus(StrEnum):
    ACTIVE = _C.Status.active
    PAUSED = _C.Status.paused
    ARCHIVED = _C.Status.archived
    DELETED = _C.Status.deleted


# ── Placements ───────────────────────────────────────────────────────────────
# The SDK exposes the *field names* (Targeting.Field.publisher_platforms,
# facebook_positions, …) but not the position values — those are plain strings
# in the Graph API. Curated to the surfaces Punk offers; omitting every
# placement key from targeting means Advantage+ placements (Meta's default).

PUBLISHER_PLATFORMS: tuple[str, ...] = (
    "facebook", "instagram", "audience_network", "messenger",
)
FACEBOOK_POSITIONS: tuple[str, ...] = (
    "feed", "story", "facebook_reels", "video_feeds", "marketplace", "search",
)
# ``explore`` (Instagram Explore Feed) and messenger ``story`` (Messenger
# Stories) are deliberately absent. Both were removed in Marketing API v26.0 on
# 29 Jul 2026 — an explicit Explore request now ERRORS, Messenger Stories is
# stripped without one — and on 27 Oct 2026 that extends to every supported
# version including the v25.0 pinned in settings. Offering either in the editor
# buys a dated hard publish failure; Meta reallocates the delivery anyway.
INSTAGRAM_POSITIONS: tuple[str, ...] = (
    "stream", "story", "reels", "profile_feed",
)
AUDIENCE_NETWORK_POSITIONS: tuple[str, ...] = ("classic", "rewarded_video")
MESSENGER_POSITIONS: tuple[str, ...] = ("messenger_home",)

# platform → (positions targeting key, allowed values). One home for the
# coupling used by the targeting validator and the form schema.
PLATFORM_POSITION_FIELDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "facebook": ("facebook_positions", FACEBOOK_POSITIONS),
    "instagram": ("instagram_positions", INSTAGRAM_POSITIONS),
    "audience_network": ("audience_network_positions", AUDIENCE_NETWORK_POSITIONS),
    "messenger": ("messenger_positions", MESSENGER_POSITIONS),
}


# ── Attribution windows ──────────────────────────────────────────────────────
# AdSet.attribution_spec: list of {event_type, window_days}. Meta's event_type
# enum is CLICK_THROUGH / VIEW_THROUGH / ENGAGED_VIDEO_VIEW — three windows, which
# is what Ads Manager shows. ENGAGED_VIDEO_VIEW is the wire name for what the UI
# now calls "engage-through": since March 2026 it credits a 5s+ video view OR a
# non-link interaction (like, share, save, comment, profile visit) followed by a
# conversion within a day. 1 day is its only length.
#
# The list carries what is ENABLED, so "off" is an absent entry, not a zero. 0 is
# our own sentinel for the two optional types — it gives the selects an "Off"
# option — and AdSetSpec.to_payload strips 0-day entries before they reach Meta.

ATTRIBUTION_CLICK_WINDOWS: tuple[int, ...] = (1, 7)
ATTRIBUTION_VIEW_WINDOWS: tuple[int, ...] = (0, 1)
ATTRIBUTION_ENGAGED_VIEW_WINDOWS: tuple[int, ...] = (0, 1)

# Meta's own default for a conversion-optimizing ad set since March 2026. We do
# NOT write this into the spec — it is what the editor DISPLAYS, so the field
# stops reading "Off" for windows that are actually live. An untouched field
# publishes no attribution_spec at all and Meta applies this itself, which also
# means a campaign follows Meta if this default moves again.
ATTRIBUTION_DEFAULT: tuple[dict[str, object], ...] = (
    {"event_type": "CLICK_THROUGH", "window_days": 7},
    {"event_type": "ENGAGED_VIDEO_VIEW", "window_days": 1},
    {"event_type": "VIEW_THROUGH", "window_days": 1},
)


# ── Budget scheduling (high demand periods) ──────────────────────────────────
# A temporary budget increase over a window — Ads Manager's "budget scheduling".
# Meta caps the raised budget at 8x the normal daily budget; the multiplier is
# scaled 100x on the wire, so 800 is that ceiling.

BUDGET_SCHEDULE_MAX_MULTIPLIER: int = 800
BUDGET_SCHEDULE_MULTIPLIER_SCALE: int = 100


# ── Frequency cap ────────────────────────────────────────────────────────────
# AdSet.frequency_control_specs: [{event, interval_days, max_frequency}]. Meta
# only honours this on the frequency goals — REACH and THRUPLAY; anywhere else the
# auction manages frequency and the field is rejected. ``GoalRules
# .allows_frequency_control`` is the authority, not this comment. Interval is
# capped at 90 days.

FREQUENCY_MAX_INTERVAL_DAYS: int = 90

# What a frequency-capped ad set starts at. Ads Manager pre-fills the Reach cap
# rather than leaving it blank, and so do we: the plan editor shows every other
# field filled in, so two empty boxes read as a broken field rather than as
# "no cap". 1 impression per 7 days is Meta's own Reach default.
FREQUENCY_DEFAULT_MAX: int = 1
FREQUENCY_DEFAULT_INTERVAL_DAYS: int = 7


# ── App promotion: one ad set per store ──────────────────────────────────────
# promoted_object.object_store_url is a SINGLE url and targeting.user_os names
# one platform, so an app campaign that wants both stores needs two ad sets.
# (user_info key, targeting.user_os value, label)

APP_PLATFORMS: tuple[tuple[str, str, str], ...] = (
    ("app_store_url", "iOS", "iOS"),
    ("play_store_url", "Android", "Android"),
)


# ── Creative text limits ─────────────────────────────────────────────────────
# Two different numbers, and conflating them was a bug.
#
# 40 / 125 / 30 are Meta's *recommended* lengths — the point at which the feed
# renderer adds an ellipsis. They are design guidance in Ads Manager, which
# shows a "may be truncated" hint and lets you publish anyway. The Marketing
# API does not reject longer copy.
#
# The MAX values below are the hard ceilings we validate against: real limits
# that exist (Instagram hard-caps a caption at 2200 characters, and it is the
# tightest surface an ad's primary text actually lands on), generous enough
# that neither the plan LLM nor a user writing a real paragraph gets clipped.
#
# RECOMMENDED drives advisory UI only — a counter that turns amber, never a
# refused keystroke and never a validation error.

CREATIVE_TITLE_MAX: int = 255
CREATIVE_TITLE_RECOMMENDED: int = 40
CREATIVE_BODY_MAX: int = 2200
CREATIVE_BODY_RECOMMENDED: int = 125
# The link description — Ads Manager's "Description", the grey line under the
# headline on feed placements. Optional; Meta drops it on placements that have
# no room for it.
CREATIVE_DESCRIPTION_MAX: int = 255
CREATIVE_DESCRIPTION_RECOMMENDED: int = 30
