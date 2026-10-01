"""
graph/meta_spec/models.py
─────────────────────────
Strict Pydantic models for the Meta campaign payload.

These replace ``MetaCampaignModel`` (``builder/executors/campaign.py``), which
was ``extra="allow"`` and required only ``campaign.name``, ``campaign.objective``
and one ad set carrying a ``targeting`` dict — so an LLM could emit almost
anything and still "validate", after which the publish path quietly ignored most
of it and rebuilt the payload from ``geo_data``.

Two rules govern everything here:

1. ``extra="forbid"``. A key we do not model is a bug, not a passthrough. The
   old permissive model is exactly why per-ad-set budgets could sit in the plan,
   be shown to the user, and never reach Meta — nothing was checking.

2. **What you validate is what gets sent.** Each spec owns a ``to_payload()``
   that produces the literal Graph API body. There is no second translation step
   where fields can drift.

Validation that needs to know the campaign objective (optimization goal, billing
event, promoted object) lives on ``CampaignSpec`` rather than ``AdSetSpec``,
because an ad set in isolation does not know its objective.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.core.config import settings
from app.graph.meta_spec.enums import (
    ATTRIBUTION_CLICK_WINDOWS,
    ATTRIBUTION_ENGAGED_VIEW_WINDOWS,
    ATTRIBUTION_VIEW_WINDOWS,
    BID_STRATEGIES_REQUIRING_AMOUNT,
    BID_STRATEGY_REQUIRING_ROAS_FLOOR,
    BUDGET_SCHEDULE_MAX_MULTIPLIER,
    ROAS_FLOOR_MAX,
    ROAS_FLOOR_MIN,
    CAROUSEL_MAX_CARDS,
    CAROUSEL_MIN_CARDS,
    CATEGORIES_BLOCKING_DEMOGRAPHICS,
    CREATIVE_BODY_MAX,
    CREATIVE_DESCRIPTION_MAX,
    CREATIVE_TITLE_MAX,
    FREQUENCY_MAX_INTERVAL_DAYS,
    LEAD_FORM_INTRO_TITLE_MAX,
    LEAD_FORM_LABEL_MAX,
    LEAD_FORM_MAX_INTRO_LINES,
    LEAD_FORM_MAX_OPTIONS,
    LEAD_FORM_QUESTION_TYPES,
    PLATFORM_POSITION_FIELDS,
    PUBLISHER_PLATFORMS,
    SPECIAL_CATEGORY_MIN_RADIUS_MILES,
    radius_meets_special_category_floor,
    AdFormat,
    BidStrategy,
    BillingEvent,
    CallToAction,
    DestinationType,
    EntityStatus,
    Objective,
    OptimizationGoal,
    SpecialAdCategory,
)
from app.graph.meta_spec.objective_matrix import (
    PROMOTED_APPLICATION,
    PROMOTED_NONE,
    PROMOTED_PAGE,
    PROMOTED_PIXEL,
    MESSENGER_NEEDS_COMPANION,
    OBJECTIVE_MATRIX,
    DestinationRules,
    GoalRules,
    MediaKind,
    ObjectiveRules,
    goal_rules,
    matrix_for,
)

# The absolute floor, in minor units. USD-derived and therefore only a sanity
# bound — the real minimum is per-currency and per-account (see min_budget_cents
# below). Kept static because it backs a Pydantic ``ge=`` constraint, which must
# be a constant; it exists to reject zero and negative budgets, not to be right
# about Bangladesh.
MIN_BUDGET_CENTS: int = max(int(settings.CAMPAIGN_MIN_DAILY_BUDGET_USD * 100), 100)


# Meta's floor is higher when the ad set pays per result instead of per
# impression, and the account only publishes the impression number. Measured on
# act_997… (CAD): min_daily_budget reported 142 and a LINK_CLICKS-billed ad set
# was rejected under 708 — "Your ad set budget must be more than CA$7.08", five
# times the value the account gave us.
#
# ponytail: one measured multiplier, not a per-billing-event table. Meta
# publishes no such table; if a second billing event turns out to differ, this
# becomes a dict keyed by BillingEvent.
NON_IMPRESSION_BUDGET_MULTIPLIER: int = 5


def min_budget_cents(user_info: dict, *, per_result_billing: bool = False) -> int:
    """Meta's minimum daily budget for THIS ad account, in its own minor units.

    Budgets are sent in the ad account's currency, and Meta's floor is
    per-currency — BDT 120 where USD is 1.00 (rejected with subcode 1885272,
    "Your ad set budget must be more than BDT120.00"). ``min_daily_budget`` is
    read off the account at connect time (``meta_ads.fetch_ad_account_currency``)
    and is the only floor that is right across US, Canada and Bangladesh.

    It is also only the *impression* floor. ``per_result_billing`` raises it for
    an ad set billed per click, per install or per like, where Meta charges a
    higher minimum than the account advertises — see the multiplier above. Pass
    it whenever the billing event is not IMPRESSIONS, or a plan built at the
    stated minimum dies at preflight with a number the user was never shown.

    Falls back to the static constant when the account was never read — an
    unknown floor must not block plan building, and Meta's own ``validate_only``
    preflight still rejects an under-minimum budget before anything is created.
    """
    raw = user_info.get("min_daily_budget")
    try:
        floor = max(int(raw), MIN_BUDGET_CENTS) if raw else MIN_BUDGET_CENTS
    except (TypeError, ValueError):
        floor = MIN_BUDGET_CENTS
    return floor * NON_IMPRESSION_BUDGET_MULTIPLIER if per_result_billing else floor


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


# ── promoted_object ──────────────────────────────────────────────────────────


class PromotedObject(_Strict):
    """What the ad set is optimizing toward.

    Exactly one shape is valid per optimization goal — see
    ``ObjectiveRules.promoted_object_kind``. Which one is enforced at
    ``CampaignSpec`` level, where the objective is known.
    """

    pixel_id: str | None = None
    custom_event_type: str | None = None
    # A custom conversion — a rule the advertiser defined over events the dataset
    # already receives, most usefully "any page view whose URL contains
    # /thank-you". It is the only route to conversion optimization for the
    # advertiser who has the base pixel on their site and no event code anywhere,
    # so it satisfies the pixel requirement on its own and carries its own event
    # definition (hence no custom_event_type alongside it).
    #
    # Unprobed pairing: whether Meta wants pixel_id sent beside it is not measured.
    # We send both when both are known and let preflight (validate_only) be the
    # authority, the way the rest of this matrix defers.
    custom_conversion_id: str | None = None
    page_id: str | None = None
    application_id: str | None = None
    object_store_url: str | None = None

    def kind(self) -> str:
        """Which PROMOTED_* shape this instance actually populates."""
        if self.pixel_id or self.custom_conversion_id:
            return PROMOTED_PIXEL
        if self.application_id:
            return PROMOTED_APPLICATION
        if self.page_id:
            return PROMOTED_PAGE
        return PROMOTED_NONE

    def to_payload(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump().items() if v}


# ── Creative ─────────────────────────────────────────────────────────────────


# How many AI copy suggestions the editor may carry per field for its picklist,
# and — separately — how many text variations one creative may publish. Both are
# five because five is Meta's cap on asset_feed_spec titles/bodies.
CREATIVE_MAX_SUGGESTIONS: int = 5

# How many images/videos one single-image-or-video ad may carry. Meta's real cap
# on an asset feed is 10 images *and* 10 videos (30 assets total across every
# field), so a flat 10 is safely inside it either way.
#
# ponytail: flat total instead of per-kind counting. Split into separate image
# and video caps if anyone actually hits this and wants the other 10.
CREATIVE_MAX_MEDIA: int = 10


def validate_ad_link(v: str) -> str:
    """Where an ad sends people — the syntax every link must satisfy.

    Shape only. Whether the domain *exists* is not decidable here (nothing
    separates a typo'd ``www.emptyadccom`` from a real host by inspection), so
    that is checked by resolving it before publish — see
    ``_unreachable_link_hosts`` in the publish executor. What this catches is the
    class Meta rejects
    outright: a relative path, a non-http scheme, a pasted link with a space in
    it, a single-label host.

    ``urlsplit`` rather than a regex: it already knows userinfo, ports, IPv6 and
    every other shape a hand-typed URL takes, and the editor's link field is free
    text.
    """
    if any(c.isspace() for c in v):
        raise ValueError("link must not contain spaces")
    try:
        parts = urlsplit(v)
    except ValueError as exc:  # malformed IPv6 literal, bad port
        raise ValueError(f"link is not a valid URL: {exc}") from exc
    if parts.scheme not in ("http", "https"):
        raise ValueError("link must be an absolute http(s) URL")
    host = parts.hostname or ""
    if "." not in host.strip("."):
        raise ValueError(
            f"link needs a full domain name — {host or v!r} has no domain ending "
            "(check for a missing dot, e.g. .com)"
        )
    return v


# One destination type for every link in the plan: the ad's own, and each
# carousel card's. Annotated rather than two `field_validator` reuses — a
# validator assigned to an underscore-prefixed class attribute is read as a
# private attribute and silently never runs.
AdLink = Annotated[str, AfterValidator(validate_ad_link)]


def validate_url_tags(v: str) -> str:
    """Ads Manager's "URL parameters" — a query string, not a URL.

    Meta appends this to the destination link, so the three shapes that break the
    resulting URL are worth catching in the editor rather than discovering in the
    advertiser's analytics a week later, when every session is attributed to
    "direct":

      * a leading ``?`` or ``&`` — Meta adds the separator itself, so the link
        becomes ``…?&utm_source=…`` or ``…??utm_source=…``
      * a whole URL pasted in — the query becomes ``?https://…``
      * whitespace — silently breaks the link at the space

    Meta's dynamic macros (``{{campaign.name}}``, ``{{ad.name}}``,
    ``{{placement}}``, ``{{site_source_name}}``) are deliberately allowed through:
    braces are legal here and Meta substitutes them at delivery.
    """
    raw = v.strip()
    if not raw:
        return raw
    if any(c.isspace() for c in raw):
        raise ValueError(
            "URL parameters must not contain spaces — they are appended to the "
            "link as a query string"
        )
    if raw[0] in "?&":
        raise ValueError(
            f"URL parameters must not start with {raw[0]!r} — Meta adds the "
            "separator, so write utm_source=facebook&utm_medium=paid"
        )
    if "://" in raw:
        raise ValueError(
            "URL parameters take only the query string, not a full URL — write "
            "utm_source=facebook&utm_medium=paid"
        )
    return raw


UrlTags = Annotated[str, AfterValidator(validate_url_tags)]


class MediaRef(_Strict):
    """One extra image or video on a single-image-or-video ad.

    Ads Manager lets an ad carry several media and combines them with the copy
    per viewer — the ad-level replacement for the retired ad-set Dynamic Creative
    toggle. The primary reference stays on ``CreativeSpec`` itself; these are the
    ones beside it, and publish sends the whole list as ``asset_feed_spec``.

    Deliberately the same four fields as ``CreativeSpec``'s own media block, so
    ``_iter_creative_media_slots`` walks these without special-casing them.
    """

    media_id: str | None = None
    image_hash: str | None = None
    video_id: str | None = None
    media_kind: MediaKind | None = None

    @model_validator(mode="after")
    def _has_a_reference(self) -> MediaRef:
        if not (self.media_id or self.image_hash or self.video_id):
            raise ValueError("extra media needs an image or video")
        # Same rule as CreativeSpec: a post-upload reference names its own kind,
        # so trust it over a stale hint and fill the hint in when it is missing.
        if self.video_id:
            self.media_kind = "video"
        elif self.image_hash:
            self.media_kind = "image"
        return self


class CarouselCard(_Strict):
    """One card of a carousel ad — a ``child_attachments`` entry on the wire.

    Each card is its own image/video, headline, description and destination, so a
    carousel is genuinely N mini-ads rather than one ad with extra pictures.
    ``body`` maps to the card's ``description`` (the small grey line), not to the
    ad's primary text, which stays on the parent ``CreativeSpec``.
    """

    title: str = Field(min_length=1, max_length=CREATIVE_TITLE_MAX)
    body: str | None = Field(default=None, max_length=CREATIVE_BODY_MAX)
    link: AdLink = Field(min_length=1)
    # Same three-way media reference as CreativeSpec, resolved at publish time.
    media_id: str | None = None
    image_hash: str | None = None
    video_id: str | None = None
    # See CreativeSpec.media_kind — same field, same reason.
    media_kind: MediaKind | None = None

    @model_validator(mode="after")
    def _card_has_media(self) -> CarouselCard:
        """Every card needs its own image or video.

        A card without one used to reach publish, where ``_child_attachment``
        sent ``image_hash: None`` and Meta rejected the creative — or, if the
        skip path caught it first, the whole ad was dropped and the user only
        learned from a passing line in the thinking stream. Both are worse than
        a form error next to the empty card.
        """
        if not (self.media_id or self.image_hash or self.video_id):
            raise ValueError("each carousel card needs an image or video")
        return self


class CreativeSpec(_Strict):
    """Ad copy plus the media reference.

    Length limits are validation errors, not truncation. ``meta_ads`` used to do
    ``title[:40]`` / ``body[:125]``, silently mangling the copy the user
    approved — the user saw one headline and Meta ran another.

    ``title`` / ``body`` / ``call_to_action`` are the primary published values.

    Two separate lists sit beside them, and the difference matters:

    * ``title_suggestions`` / ``body_suggestions`` are the plan LLM's other
      ideas. They are a **picklist only** — the editor offers them in a dropdown
      and picking one replaces the primary. They never publish. The brief writes
      five of each whatever the ad format.
    * ``title_variants`` / ``body_variants`` are the extra options the user
      explicitly added in the editor. These **do** publish: primary + variants
      become Meta text variations (``asset_feed_spec``), Ads Manager's "Add
      another option", where Meta combines them and learns which mix performs.
      Empty by default, so an untouched ad ships exactly one headline and one
      body.

    They used to be one list, which meant the five AI suggestions turned every
    ad into a five-variation dynamic creative nobody asked for.

    Only a single image or video ad can carry variants. A carousel keeps its copy
    on each card and a boosted post already has its own, so publish sends the
    primary alone for both — see ``meta_ads.create_ad_creative``.

    ``extra_media`` is the same idea for pictures: extra images/videos combined
    into this one ad rather than fanned out into separate ads. It rides the same
    ``asset_feed_spec``, and the same two formats are excluded for the same
    reasons.
    """

    title: str = Field(min_length=1, max_length=CREATIVE_TITLE_MAX)
    body: str = Field(min_length=1, max_length=CREATIVE_BODY_MAX)
    call_to_action: CallToAction
    link: AdLink = Field(min_length=1)
    # Ads Manager's "Description" — the grey line under the headline. Optional;
    # Meta shows it only where the placement has room.
    description: str | None = Field(default=None, max_length=CREATIVE_DESCRIPTION_MAX)
    # The AI's other ideas — the editor's dropdown. Picking one replaces the
    # primary; nothing here reaches Meta. See the class docstring.
    title_suggestions: list[str] | None = Field(
        default=None, max_length=CREATIVE_MAX_SUGGESTIONS
    )
    body_suggestions: list[str] | None = Field(
        default=None, max_length=CREATIVE_MAX_SUGGESTIONS
    )
    # The extra options the user added by hand. Published alongside the primary
    # as Meta text variations; the editor adds and removes them one at a time.
    title_variants: list[str] | None = Field(
        default=None, max_length=CREATIVE_MAX_SUGGESTIONS
    )
    body_variants: list[str] | None = Field(
        default=None, max_length=CREATIVE_MAX_SUGGESTIONS
    )
    # Optional URL parameters appended to the destination link on click — the
    # "URL parameters" field in Ads Manager (e.g. "utm_source=facebook&utm_medium=paid").
    url_tags: UrlTags | None = None
    # Ads Manager's "Ad setup". SINGLE uses the media reference below; CAROUSEL
    # uses ``cards`` instead. Which formats are offered depends on the conversion
    # location — see DestinationRules.ad_formats.
    format: AdFormat = AdFormat.SINGLE
    cards: list[CarouselCard] | None = None
    # Instant Form id, required when the conversion location is Instant forms.
    # Created against the Page at publish time if the user asked us to generate one.
    lead_gen_form_id: str | None = None
    # "<page_id>_<post_id>" — the existing Page post this ad boosts. Required by
    # the boost destinations (On your post / video / event), where the ad IS that
    # post: its photo, its caption, and the reactions it has already collected.
    # Also allowed wherever ``DestinationRules.allows_existing_post`` is set, which
    # is how "run my existing post as a Traffic ad" works.
    # When set, the copy and media fields below are ignored by Meta.
    object_story_id: str | None = None
    # The same thing from Instagram: an IG post promoted as the ad, keeping its own
    # caption and engagement. Mutually exclusive with object_story_id — one ad
    # promotes one post — and needs the Page's linked Instagram account at publish.
    source_instagram_media_id: str | None = None
    # Exactly one media reference, resolved at publish time. SINGLE format only.
    media_id: str | None = None      # Punk MediaFile UUID (pre-upload)
    image_hash: str | None = None    # Meta adimages hash (post-upload)
    video_id: str | None = None      # Meta advideos id (post-upload)
    # "image" or "video" — which kind the reference above points at.
    #
    # Some optimization goals require a video (ThruPlay optimizes for watch time),
    # and that has to be checkable while the user is still in the form. A
    # ``video_id``/``image_hash`` says it outright; a ``media_id`` does not, so
    # the editor sets this from ``MediaFile.media_type`` when it attaches media.
    media_kind: MediaKind | None = None
    # The other media on this ad, beside the primary above. Publishing more than
    # one turns the creative into an asset feed, where Meta pairs the media with
    # the copy per viewer — Ads Manager's "select up to 10 media in a Single image
    # or video ad". Empty by default, so an untouched ad ships exactly one asset.
    #
    # This is the alternative to fanning the media out into separate ads, not a
    # replacement for it: the editor still offers both, because several ads in one
    # ad set give per-ad reporting that a combined creative cannot.
    extra_media: list[MediaRef] | None = Field(
        default=None, max_length=CREATIVE_MAX_MEDIA - 1
    )

    @model_validator(mode="after")
    def _media_kind_follows_the_reference(self) -> CreativeSpec:
        """A post-upload reference names the kind on its own — trust it over a
        stale hint, and fill the hint in when it is missing."""
        implied = "video" if self.video_id else "image" if self.image_hash else None
        if implied:
            self.media_kind = implied
        return self

    @model_validator(mode="after")
    def _format_matches_media(self) -> CreativeSpec:
        """The format and the media have to agree, or publish builds the wrong
        ``object_story_spec`` and Meta rejects it with an opaque error.

        The ``format: `` / ``object_story_id: `` openers are the field this rule
        blames — ``errors_to_form_keys`` appends it to Pydantic's own location so
        the ad's format toggle is marked. Without one the error keys to
        ``…creative``, which no control in the editor is named after, and the
        whole thing renders as a page banner. Left off where the offending value
        has no control of its own (extra media is managed by the media picker).
        """
        if self.format is AdFormat.CAROUSEL:
            count = len(self.cards or [])
            if not CAROUSEL_MIN_CARDS <= count <= CAROUSEL_MAX_CARDS:
                raise ValueError(
                    f"format: a carousel needs between {CAROUSEL_MIN_CARDS} and "
                    f"{CAROUSEL_MAX_CARDS} cards, got {count}"
                )
            if (
                self.media_id or self.image_hash or self.video_id
                or self.extra_media
            ):
                raise ValueError(
                    "format: a carousel carries its media on each card, not on the ad"
                )
        elif self.cards:
            raise ValueError("format: cards are only accepted on a carousel ad")

        if self.extra_media:
            # A boosted post IS an existing Page post — Meta ignores anything we
            # compose beside it, so extra media would silently do nothing.
            if self.object_story_id:
                raise ValueError(
                    "object_story_id: a boosted post already has its media; "
                    "extra media is ignored"
                )
            # Extras sit beside a primary, they do not stand in for one. Without
            # this, publish would skip the ad for having no media while the editor
            # showed several attached.
            if not (self.media_id or self.image_hash or self.video_id):
                raise ValueError("extra media needs a primary image or video first")
            # Combining media on one ad works for IMAGES ONLY. Measured against a
            # live ad account (scripts/probe_mixed_feed.py): Meta strips `videos`
            # out of an asset_feed_spec every single time — with SINGLE_VIDEO and
            # with AUTOMATIC_FORMAT, with a thumbnail_url, with a thumbnail_hash,
            # with no thumbnail, against a video whose status is "ready", and even
            # in a feed carrying nothing but that one video. It returns 200 and
            # stores the feed without it, so the ad publishes looking correct and
            # runs one asset.
            #
            # A second video therefore has to be its own ad, and so does an image
            # sitting next to a video primary.
            #
            # ``media_kind`` is authoritative by here: the validator above and
            # ``MediaRef._has_a_reference`` both fill it in from image_hash /
            # video_id. It stays None only for a bare media_id, which says nothing
            # about the file — those are re-checked at publish, where the MediaFile
            # row names the real kind.
            if self.media_kind == "video" or any(
                e.media_kind == "video" for e in self.extra_media
            ):
                raise ValueError(
                    "several media on one ad works for images only — Meta drops "
                    "videos from a combined ad, so give each video its own ad"
                )
        return self

    def text_variations(self) -> tuple[list[str], list[str]]:
        """``(titles, bodies)`` to publish — the primary first, then the
        user-added variants, de-duplicated and capped at Meta's five.

        ``*_suggestions`` is the editor's picklist, not an instruction to publish,
        and is read here in exactly one case — see below. The variants may repeat
        the primary and the editor can leave a blank entry behind, so both are
        filtered here rather than at every call site. Single-element lists are the
        normal result of an ad with no variants — the common case — and publish
        calls this unconditionally, letting the length pick the wire shape.

        **The one case.** An ad carrying several images needs more than one text
        option or Meta keeps none of them. Measured against a live ad account
        (``scripts/probe_mixed_feed.py --mode solo``): three images with one
        headline and one body come back with the whole ``asset_feed_spec``
        discarded — a 200, an ad that looks right, and one image running. The same
        three images with two headlines keep all three.

        So when the media is what varies and the copy is not, a second headline is
        taken from the AI's own suggestions. It is the difference between the
        user's images running and silently not, and the suggestions were written
        for this ad and already shown to them in the editor's dropdown.
        """
        def _merge(primary: str, extras: list[str] | None) -> list[str]:
            seen: set[str] = set()
            return [
                x for x in [primary, *(extras or [])]
                if x and not (x in seen or seen.add(x))
            ][:CREATIVE_MAX_SUGGESTIONS]

        titles = _merge(self.title, self.title_variants)
        bodies = _merge(self.body, self.body_variants)
        if self.extra_media and len(titles) == 1 and len(bodies) == 1:
            titles = _merge(self.title, [*(self.title_variants or []),
                                         *(self.title_suggestions or [])])[:2]
            if len(titles) == 1:
                # No usable headline suggestion — try the body instead. Either
                # field varying is enough to make Meta keep the feed.
                bodies = _merge(self.body, [*(self.body_variants or []),
                                            *(self.body_suggestions or [])])[:2]
        return titles, bodies


class AdSpec(_Strict):
    """One ad. Note the exception to rule 2 in the module docstring: the ad body
    is built by ``meta_ads.create_ad``, which pins ``status`` to PAUSED and
    ignores ``status`` below — publish activates every ad afterwards, so a
    per-ad status has nowhere to take effect. The field is kept because the
    editor and the draft row round-trip it."""

    name: str = Field(min_length=1, max_length=255)
    creative: CreativeSpec
    status: EntityStatus = EntityStatus.PAUSED
    # Which domain the conversion happens on. Meta needs it to attribute
    # conversions under Aggregated Event Measurement — the iOS-opt-out path, where
    # only the highest-priority event on a *verified domain* is reported. Filled
    # from the creative's own link below, so a plan never has to carry it and an
    # edited plan cannot drop it.
    conversion_domain: str | None = None

    @model_validator(mode="after")
    def _conversion_domain_follows_the_link(self) -> AdSpec:
        """Derive the domain from the ad's link when nobody set one.

        Here rather than in the builder because the plan is editable: the editor
        submits a whole spec and a template import builds one from an existing
        campaign, so a builder-only derivation would be missing on two of the three
        paths into publish.
        """
        if self.conversion_domain:
            return self
        host = (urlsplit(self.creative.link).hostname or "").lower()
        # ponytail: strip a leading "www." and use the host as-is rather than
        # computing the registrable domain. Doing that properly needs a public
        # suffix list (shop.example.co.uk); add one if Meta ever rejects a subdomain.
        if host:
            self.conversion_domain = host.removeprefix("www.")
        return self


# ── Ad set ───────────────────────────────────────────────────────────────────


AudienceRole = Literal["seed", "lookalike", "broad"]


class DayPartSpec(_Strict):
    """One dayparting window — mirrors the SDK ``DayPart`` shape.

    Meta only honours ad scheduling on lifetime-budget ad sets; that coupling is
    checked on ``CampaignSpec``, where the campaign-level (CBO) budget is also
    visible.
    """

    days: list[int] = Field(min_length=1)          # 0=Sunday … 6=Saturday
    start_minute: int = Field(ge=0, le=1439)
    end_minute: int = Field(ge=1, le=1440)

    @field_validator("days")
    @classmethod
    def _days_in_week(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("days must be 0 (Sunday) through 6 (Saturday)")
        return sorted(set(v))

    @model_validator(mode="after")
    def _window_is_ordered(self) -> DayPartSpec:
        if self.end_minute <= self.start_minute:
            raise ValueError("end_minute must be after start_minute")
        return self


_ATTRIBUTION_WINDOWS_BY_EVENT: dict[str, tuple[int, ...]] = {
    "CLICK_THROUGH": ATTRIBUTION_CLICK_WINDOWS,
    "VIEW_THROUGH": ATTRIBUTION_VIEW_WINDOWS,
    "ENGAGED_VIDEO_VIEW": ATTRIBUTION_ENGAGED_VIEW_WINDOWS,
}


class AttributionWindow(_Strict):
    """One attribution_spec entry — {event_type, window_days} on the wire.

    ``ENGAGED_VIDEO_VIEW`` is Ads Manager's "engage-through" (see enums).
    """

    event_type: Literal["CLICK_THROUGH", "VIEW_THROUGH", "ENGAGED_VIDEO_VIEW"]
    window_days: int

    @model_validator(mode="after")
    def _window_allowed(self) -> AttributionWindow:
        allowed = _ATTRIBUTION_WINDOWS_BY_EVENT[self.event_type]
        if self.window_days not in allowed:
            raise ValueError(
                f"{self.event_type} window_days must be one of {allowed}"
            )
        return self


class BudgetScheduleSpec(_Strict):
    """One "high demand period" — a temporary budget increase over a window.

    Ads Manager calls this **budget scheduling**, and it is the counterpart to
    dayparting: dayparting (``adset_schedule``) restricts *when a lifetime-budget
    ad set runs*, budget scheduling raises the *daily* budget for a sale, a
    holiday or a product launch. We had neither concept for daily budgets, so a
    user could only express "spend the same every day, forever".

    ``budget_value`` is read according to ``budget_value_type``: ABSOLUTE is
    cents, MULTIPLIER is a multiple of the normal budget scaled 100x (``200`` =
    2×). Meta caps the raised budget at 8× the daily budget.

    Sent as ``budget_schedule_specs`` on the create call, which is why this is a
    spec rather than a call to ``POST /{id}/budget_schedules`` after the fact.

    The window goes out as **Unix timestamps**, not ISO-8601 like every other
    datetime in this module. That is not a style choice: the entries are
    ``HighDemandPeriod`` objects, and the SDK declares
    ``POST /{id}/budget_schedules`` with ``'time_start': 'unsigned int'``
    (``facebook_business/adobjects/campaign.py``). ISO only appears on the GET,
    for filtering, and on the field as Meta reads it back.
    """

    time_start: datetime
    time_end: datetime
    budget_value: int = Field(ge=1)
    budget_value_type: Literal["ABSOLUTE", "MULTIPLIER"] = "MULTIPLIER"

    @field_validator("time_start", "time_end")
    @classmethod
    def _snap_to_quarter_hour(cls, v: datetime) -> datetime:
        """Meta only accepts a high-demand window on a 15-minute boundary.

        Snapped rather than rejected: the exact minute is never the point of a
        budget schedule, and an error here would make the form reject a time the
        user has no reason to think is wrong ("The time entered for a high demand
        period must be in a 15-minute interval (0, 15, 30, 45)").
        """
        return v.replace(
            minute=(v.minute // 15) * 15, second=0, microsecond=0
        )

    @model_validator(mode="after")
    def _window_is_ordered(self) -> BudgetScheduleSpec:
        if self.time_end <= self.time_start:
            raise ValueError("budget schedule time_end must be after time_start")
        if self.budget_value_type == "MULTIPLIER" and self.budget_value > BUDGET_SCHEDULE_MAX_MULTIPLIER:
            raise ValueError(
                "a scheduled budget cannot exceed "
                f"{BUDGET_SCHEDULE_MAX_MULTIPLIER // 100}x the normal budget"
            )
        return self

    def to_payload(self) -> dict[str, Any]:
        return {
            "time_start": _epoch(self.time_start),
            "time_end": _epoch(self.time_end),
            "budget_value": self.budget_value,
            "budget_value_type": self.budget_value_type,
        }


class BidConstraints(_Strict):
    """The ROAS floor for a ``LOWEST_COST_WITH_MIN_ROAS`` ad set.

    Meta scales the value 10000× — ``10000`` means 1.0 (break even), ``30000``
    means 3.0. The accepted range is 100–10,000,000, i.e. 0.01× to 1000×.

    This strategy takes ``bid_constraints`` and explicitly forbids ``bid_amount``,
    which is why it is a separate model rather than another cents field: the ROAS
    goal was selectable in the editor with nowhere to put the number, so it could
    never publish.
    """

    roas_average_floor: int = Field(ge=ROAS_FLOOR_MIN, le=ROAS_FLOOR_MAX)

    def to_payload(self) -> dict[str, Any]:
        return {"roas_average_floor": self.roas_average_floor}


class FrequencyControlSpec(_Strict):
    """One frequency_control_specs entry — caps how often one person sees the ad.

    Meta only honours this on Reach ad sets (optimization_goal == REACH); the
    REACH-only rule is enforced on AdSetSpec, which knows the goal.
    """

    event: Literal["IMPRESSIONS"] = "IMPRESSIONS"
    interval_days: int = Field(ge=1, le=FREQUENCY_MAX_INTERVAL_DAYS)
    max_frequency: int = Field(ge=1)


class LeadFormQuestionSpec(_Strict):
    """One question on an Instant Form.

    A prefill question is just its Meta type ("EMAIL") and Meta answers it from
    the person's profile. A custom question is written by the advertiser and
    needs a ``label``; ``options`` turns it into a multiple choice.
    """

    type: str = Field(min_length=1)
    label: str | None = Field(default=None, max_length=LEAD_FORM_LABEL_MAX)
    options: list[str] | None = Field(default=None, max_length=LEAD_FORM_MAX_OPTIONS)

    @model_validator(mode="after")
    def _custom_needs_label(self) -> "LeadFormQuestionSpec":
        if self.type.upper() == "CUSTOM":
            if not (self.label or "").strip():
                raise ValueError("a custom question needs a label — it is what the person reads")
        elif self.type.upper() not in LEAD_FORM_QUESTION_TYPES:
            raise ValueError(
                f"unknown lead form question type {self.type!r} — "
                f"use one of {', '.join(LEAD_FORM_QUESTION_TYPES)} or CUSTOM"
            )
        if self.options and self.type.upper() != "CUSTOM":
            raise ValueError("only a custom question can carry answer options")
        return self


class LeadFormSpec(_Strict):
    """An Instant Form to create on the Page at publish time.

    The alternative to ``CreativeSpec.lead_gen_form_id``, which names a form that
    already exists. A draft is carried through the plan so the user can design
    the form in the editor without anything being created on their Page until
    they publish — and so an abandoned campaign leaves no litter behind.
    """

    name: str = Field(min_length=1, max_length=255)
    questions: list[LeadFormQuestionSpec] = Field(min_length=1)
    privacy_policy_url: str = Field(min_length=1)
    intro_title: str | None = Field(default=None, max_length=LEAD_FORM_INTRO_TITLE_MAX)
    intro_body: list[str] | None = Field(default=None, max_length=LEAD_FORM_MAX_INTRO_LINES)
    follow_up_url: str | None = None
    # Meta's review step before submission: fewer leads, better ones.
    higher_intent: bool = False

    @field_validator("privacy_policy_url", "follow_up_url")
    @classmethod
    def _url_is_absolute(cls, v: str | None) -> str | None:
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("must be an absolute http(s) URL")
        return v


class AdSetSpec(_Strict):
    name: str = Field(min_length=1, max_length=255)
    # Which audience this ad set is for. The MAID custom audience and its
    # lookalike do not exist until publish creates them, so their ids cannot be
    # in a spec built at plan time. Rather than carry a
    # "CUSTOM_AUDIENCE_PLACEHOLDER" string and substitute it later — the exact
    # pattern that let the plan and the published payload drift apart — the spec
    # records the *intent* and ``bind_audiences`` injects the real ids once they
    # exist. Everything else in the payload is final at validation time.
    audience_role: AudienceRole = "broad"
    # Audiences the USER picked in the plan editor, by id. Separate from
    # ``audience_role`` on purpose: the role is an intent Punk resolves at publish
    # (the MAID list and its lookalike, which do not exist yet), while these are
    # real ids for audiences that already exist on the ad account. One is a
    # promise, the other is a fact, and collapsing them would make an explicit
    # pick look like something publish is free to substitute.
    #
    # The exclusion is what makes conversion tracking pay for itself twice: a
    # dataset that knows who converted can keep prospecting from being sold to
    # people who already bought. Until this field existed no ad set Punk published
    # could exclude anybody.
    attached_audience_ids: list[str] = Field(default_factory=list)
    excluded_audience_ids: list[str] = Field(default_factory=list)
    optimization_goal: OptimizationGoal
    billing_event: BillingEvent
    # Required: the conversion location is the second axis of the objective
    # matrix, so nothing below it (goal, billing, CTA, promoted object, ad format)
    # can be validated without it. It was optional when the matrix was flat.
    destination_type: DestinationType
    bid_strategy: BidStrategy = BidStrategy.LOWEST_COST_WITHOUT_CAP
    # validate_default on all three of bid_amount / bid_constraints / end_time:
    # their validators enforce a rule about a MISSING value, which Pydantic
    # otherwise never runs because the field fell back to its default.
    bid_amount: int | None = Field(default=None, ge=1, validate_default=True)   # cents
    # The ROAS goal's target. Mutually exclusive with bid_amount — see
    # BidConstraints.
    bid_constraints: BidConstraints | None = Field(default=None, validate_default=True)
    # Both optional: under Advantage+ campaign budget (CBO) the campaign owns
    # the budget and every ad set carries none. The "exactly one" rule is
    # CBO-aware and therefore lives on CampaignSpec, which sees both levels.
    daily_budget: int | None = Field(default=None, ge=MIN_BUDGET_CENTS)
    lifetime_budget: int | None = Field(default=None, ge=MIN_BUDGET_CENTS)
    targeting: dict[str, Any]
    start_time: datetime
    end_time: datetime | None = Field(default=None, validate_default=True)
    promoted_object: PromotedObject | None = None
    adset_schedule: list[DayPartSpec] | None = None
    # Temporary budget increases. The counterpart to adset_schedule: dayparting
    # needs a lifetime budget, budget scheduling needs a daily one.
    budget_schedule_specs: list[BudgetScheduleSpec] | None = None
    attribution_spec: list[AttributionWindow] | None = None
    frequency_control_specs: list[FrequencyControlSpec] | None = None
    # Each ad set owns one or more ads, each with its own creative. Meta Ads
    # Manager lets you run several ads (distinct copy + image) against the same
    # audience; the editor mirrors that, so ads are nested here rather than a
    # flat campaign-level list paired to ad sets by index.
    ads: list[AdSpec] = Field(min_length=1)
    # The Instant Form to create at publish, when the user designed one in the
    # editor instead of picking an existing one. Mutually exclusive with the ads'
    # lead_gen_form_id — see _check_creative_against_destination.
    lead_form_draft: LeadFormSpec | None = None
    status: EntityStatus = EntityStatus.PAUSED

    # Set by CampaignSpec validation, which is the only place that knows the
    # objective — and the (objective, destination) pair is what decides whether
    # Meta wants destination_type on the wire at all. Private so it can never be
    # supplied by a client or leak into a payload.
    _omit_destination_type: bool = PrivateAttr(default=False)

    @field_validator("targeting")
    @classmethod
    def _targeting_has_geo(cls, v: dict[str, Any]) -> dict[str, Any]:
        # meta_ads.create_adset used to paper over a missing geo block with a
        # blanket {"countries": ["US"]} — a silent nationwide spend for a
        # campaign the user scoped to one neighbourhood.
        if not v.get("geo_locations"):
            raise ValueError("targeting must carry a geo_locations block")
        return v

    @field_validator("targeting")
    @classmethod
    def _targeting_placements_valid(cls, v: dict[str, Any]) -> dict[str, Any]:
        # Absent placement keys = Advantage+ placements. When platforms are
        # named, positions may only be set for a named platform and must come
        # from the curated vocabulary — Meta rejects unknown position strings
        # with an opaque error at create time.
        platforms = v.get("publisher_platforms")
        if platforms is not None:
            unknown = set(platforms) - set(PUBLISHER_PLATFORMS)
            if unknown:
                raise ValueError(
                    f"unknown publisher_platforms: {sorted(unknown)}; "
                    f"allowed: {list(PUBLISHER_PLATFORMS)}"
                )
        for platform, (pos_key, allowed) in PLATFORM_POSITION_FIELDS.items():
            positions = v.get(pos_key)
            if not positions:
                continue
            if platforms is None or platform not in platforms:
                raise ValueError(
                    f"{pos_key} requires {platform!r} in publisher_platforms"
                )
            bad = set(positions) - set(allowed)
            if bad:
                raise ValueError(
                    f"unknown {pos_key}: {sorted(bad)}; allowed: {list(allowed)}"
                )
        return v

    # ── rules that blame one field ───────────────────────────────────────────
    # Field validators rather than lines inside the model validator below, for
    # one reason: Pydantic reports a model validator's error at the ad set
    # (``loc=('adsets', 1)``), so ``errors_to_form_keys`` produced the bare key
    # `adsets[1]` and the editor — which looks up `adsets[1].bid_amount` — marked
    # nothing. The user saw a page banner reading "LOWEST_COST_WITH_BID_CAP
    # requires a bid_amount" while looking at the amount they HAD typed on the
    # other ad set. A field validator's loc carries the field name, so the box
    # that is actually empty turns red.
    #
    # Each of the three fields declares `validate_default=True`: they all default
    # to None, and Pydantic skips validators for defaults, so a payload that
    # omits the key entirely (rather than sending null) would walk straight past
    # the rule the model validator used to catch.

    @field_validator("bid_amount")
    @classmethod
    def _bid_amount_matches_strategy(cls, v: int | None, info: ValidationInfo) -> int | None:
        # .get, not [...]: a field that failed its own validation is absent from
        # info.data, and a KeyError there would replace a readable error.
        strategy = info.data.get("bid_strategy")
        if strategy is None:
            return v
        if strategy in BID_STRATEGIES_REQUIRING_AMOUNT and not v:
            raise ValueError(f"{strategy.value} requires a bid_amount")
        if strategy not in BID_STRATEGIES_REQUIRING_AMOUNT and v:
            raise ValueError(f"bid_amount is not accepted with {strategy.value}")
        return v

    @field_validator("bid_constraints")
    @classmethod
    def _roas_floor_matches_strategy(
        cls, v: BidConstraints | None, info: ValidationInfo
    ) -> BidConstraints | None:
        # The ROAS goal takes its target here instead of in bid_amount, and Meta
        # rejects the ad set when both are present.
        strategy = info.data.get("bid_strategy")
        if strategy is None:
            return v
        if strategy == BID_STRATEGY_REQUIRING_ROAS_FLOOR and not v:
            raise ValueError(
                f"{strategy.value} requires a bid_constraints.roas_average_floor "
                f"between {ROAS_FLOOR_MIN} and {ROAS_FLOOR_MAX} (scaled 10000x, so "
                "10000 means a 1.0x return)"
            )
        if strategy != BID_STRATEGY_REQUIRING_ROAS_FLOOR and v:
            raise ValueError(
                f"bid_constraints is only accepted with {BID_STRATEGY_REQUIRING_ROAS_FLOOR}"
            )
        return v

    @field_validator("end_time")
    @classmethod
    def _end_time_closes_the_flight(
        cls, v: datetime | None, info: ValidationInfo
    ) -> datetime | None:
        if info.data.get("lifetime_budget") and not v:
            raise ValueError("lifetime_budget requires an end_time")
        start = info.data.get("start_time")
        if v and start and v <= start:
            raise ValueError("end_time must be after start_time")
        return v

    @model_validator(mode="after")
    def _check_budget_and_schedule(self) -> AdSetSpec:
        # Two fields at fault, so there is no single control to mark — this one
        # stays keyed to the ad set as a whole.
        if self.daily_budget and self.lifetime_budget:
            raise ValueError("set at most one of daily_budget or lifetime_budget")
        return self

    @model_validator(mode="after")
    def _check_audiences(self) -> AdSetSpec:
        """An audience cannot be both targeted and excluded on one ad set.

        Meta accepts the payload and then delivers to nobody — the exclusion wins
        over the inclusion — so the ad set spends its budget on nothing and looks
        like a targeting problem for days. Caught here because the editor's two
        pickers are the obvious way to do it by accident.
        """
        both = [i for i in self.attached_audience_ids if i in set(self.excluded_audience_ids)]
        if both:
            raise ValueError(
                "the same audience is both targeted and excluded "
                f"({', '.join(sorted(set(both)))}) — Meta would deliver this ad set "
                "to nobody"
            )
        return self

    def _wire_targeting(self) -> dict[str, Any]:
        """``targeting`` with the two keys Meta demands but nobody chooses.

        ``advantage_audience`` is not optional any more: Meta rejects an ad set
        whose ``targeting_automation`` does not say 0 or 1 outright ("you need to
        enable or disable the Advantage audience feature"). ``bind_audiences``
        only sets it for a seed/lookalike ad set that lost its audience, so a
        ``broad`` one — the default role, and what a publish-without-audience
        produces — reached Meta with the key missing. 0 is the honest default:
        the plan carries the targeting the user chose.

        ``excluded_connections`` is the same class of rule for Page likes. Meta
        refuses a PAGE_LIKES ad set that can serve to people who already like the
        Page ("you must target your ads to people who have not already
        converted"), and it is the Page being promoted that has to be excluded.

        Both live here rather than in the builder because the plan is editable
        and importable — this is the one point every path passes through.
        """
        targeting = dict(self.targeting)
        automation = dict(targeting.get("targeting_automation") or {})
        automation.setdefault("advantage_audience", 0)
        targeting["targeting_automation"] = automation

        # Advantage+ audience treats age/gender as suggestions and refuses an
        # upper bound outright ("you can add a lower maximum age as a suggestion
        # instead"). age_min survives as the suggestion; age_max cannot. A
        # lookalike ad set is built with the flag on, and bind_audiences turns it
        # on for any seed/lookalike that lost its audience — so a plan the user
        # never edited reaches Meta with both set and the whole publish fails.
        if int(automation.get("advantage_audience") or 0) == 1:
            targeting.pop("age_max", None)

        page_id = self.promoted_object.page_id if self.promoted_object else None
        if (
            self.optimization_goal is OptimizationGoal.PAGE_LIKES
            and page_id
            and not targeting.get("excluded_connections")
        ):
            targeting["excluded_connections"] = [{"id": str(page_id)}]
        return targeting

    def to_payload(
        self,
        *,
        campaign_id: str,
        ad_account_id: str,
        campaign_has_budget: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "campaign_id": campaign_id,
            "optimization_goal": self.optimization_goal.value,
            "billing_event": self.billing_event.value,
            "targeting": self._wire_targeting(),
            "start_time": _iso(self.start_time),
            "status": self.status.value,
        }
        # Under CBO the campaign owns budget + bid strategy; sending them on
        # the ad set makes Meta reject the create.
        if not campaign_has_budget:
            payload["bid_strategy"] = self.bid_strategy.value
            if self.bid_amount:
                payload["bid_amount"] = self.bid_amount
            if self.daily_budget:
                payload["daily_budget"] = self.daily_budget
            if self.lifetime_budget:
                payload["lifetime_budget"] = self.lifetime_budget
        elif self.bid_amount:
            # A capped campaign strategy still takes its per-ad-set cap amount.
            payload["bid_amount"] = self.bid_amount
        # The ROAS floor rides on the ad set under both budget models — the
        # campaign carries the strategy, each ad set carries its own target.
        if self.bid_constraints:
            payload["bid_constraints"] = self.bid_constraints.to_payload()
        if self.end_time:
            payload["end_time"] = _iso(self.end_time)
        # Absent for conversion locations Meta expresses by omission — see
        # DestinationRules.omit_destination_type.
        if not self._omit_destination_type:
            payload["destination_type"] = self.destination_type.value
        if self.promoted_object:
            payload["promoted_object"] = self.promoted_object.to_payload()
        if self.adset_schedule:
            payload["adset_schedule"] = [d.model_dump() for d in self.adset_schedule]
            # Meta pairs dayparting with a pacing type and rejects the schedule
            # without it ("This pacing requires a campaign with not day parting"),
            # so ad scheduling was fully modelled and could never publish.
            payload["pacing_type"] = ["day_parting"]
        if self.budget_schedule_specs:
            payload["budget_schedule_specs"] = [
                b.to_payload() for b in self.budget_schedule_specs
            ]
        if self.attribution_spec:
            # Meta's list carries what is ENABLED — "off" is an absent entry, not a
            # 0-day one. 0 is our sentinel so the editor's selects can offer "Off";
            # it must not reach the wire. The client already drops them, but the
            # template importer copies attribution_spec verbatim off a previous
            # campaign, so the guard belongs here where every path passes.
            windows = [a.model_dump() for a in self.attribution_spec if a.window_days > 0]
            if windows:
                payload["attribution_spec"] = windows
        if self.frequency_control_specs:
            payload["frequency_control_specs"] = [
                f.model_dump() for f in self.frequency_control_specs
            ]
        return payload


# ── Campaign ─────────────────────────────────────────────────────────────────


class CampaignSpec(_Strict):
    """The whole approved plan — campaign, ad sets, ads.

    This object is simultaneously: what the form renders, what the user edits,
    what gets persisted to the ``campaigns`` draft row, what Meta's
    ``validate_only`` preflight checks, and what publish sends. One artefact, so
    the three cannot diverge.
    """

    name: str = Field(min_length=1, max_length=255)
    objective: Objective
    special_ad_categories: list[SpecialAdCategory] = Field(default_factory=list)
    # Which country's rules the declaration is made under. Meta requires it
    # alongside any special ad category and rejects the campaign without it — we
    # never sent it, so every regulated campaign failed at create.
    special_ad_category_country: list[str] = Field(default_factory=list)
    # AUCTION only. Meta's other buying type, RESERVED (Reach & Frequency), needs
    # an rf_prediction_id bought ahead of time through a separate flow — offering
    # it here produced a campaign that could never be created.
    buying_type: Literal["AUCTION"] = "AUCTION"
    status: EntityStatus = EntityStatus.PAUSED
    # Advantage+ campaign budget (CBO): a campaign-level budget IS the toggle —
    # there is no separate flag on the wire. Setting one moves budget + bid
    # strategy ownership up here; ad sets then carry neither.
    daily_budget: int | None = Field(default=None, ge=MIN_BUDGET_CENTS)
    lifetime_budget: int | None = Field(default=None, ge=MIN_BUDGET_CENTS)
    bid_strategy: BidStrategy | None = None
    # Ad-set budgets (ABO) only. Meta has no default for this and rejects the
    # campaign outright without an explicit True/False. True lets ad sets lend
    # each other up to 20% of their budget; False keeps every ad set on the slice
    # the plan gave it.
    is_adset_budget_sharing_enabled: bool = False
    # Under CBO the campaign owns the budget, so it owns its schedule too.
    budget_schedule_specs: list[BudgetScheduleSpec] | None = None
    adsets: list[AdSetSpec] = Field(min_length=1)
    # ── app promotion, campaign level ────────────────────────────────────────
    # Meta puts the promoted app and its attribution mode on the CAMPAIGN, not
    # the ad set: an iOS 14.5+ install campaign is a dedicated SKAdNetwork
    # campaign type and cannot carry Android ad sets. Both are set by
    # ``builder.split_for_publish`` when it derives the per-store campaigns; they
    # stay None/False for every other objective, so no other payload changes.
    promoted_object: PromotedObject | None = None
    is_skadnetwork_attribution: bool = False
    # ── publishing identity ──────────────────────────────────────────────────
    # Which Facebook Page the ads run as, and which Instagram account they run as
    # on Instagram placements. Both live on the campaign because they are one
    # decision for the whole plan, and both live on the SPEC — not on user_info —
    # because an advertiser with several Pages picks in the editor, and publish
    # must use what they picked rather than whichever Page Meta happened to list
    # first at OAuth time. Neither is sent on the campaign create payload:
    # page_id reaches Meta through promoted_object / object_story_spec and
    # instagram_user_id through the ad creative.
    page_id: str | None = None
    instagram_user_id: str | None = None
    # Display-only, carried so the form and the plan card agree on the numbers.
    estimated_reach: dict[str, Any] = Field(default_factory=dict)
    # Display-only. What a special ad category forced us to remove from the plan
    # (ZIP targeting, the lookalike, detailed targeting). The user is entitled to
    # know their campaign was narrowed and why, rather than noticing later that
    # the audience is not what they asked for.
    compliance_notes: list[str] = Field(default_factory=list)

    @property
    def has_campaign_budget(self) -> bool:
        return bool(self.daily_budget or self.lifetime_budget)

    @model_validator(mode="after")
    def _check_against_objective_matrix(self) -> CampaignSpec:
        rules = matrix_for(self.objective)
        # The same categories that block age/gender also block ZIPs, sub-15-mile
        # radii, detailed targeting and lookalikes — one flag, one check.
        restricted_category = bool(
            {c.value for c in self.special_ad_categories} & CATEGORIES_BLOCKING_DEMOGRAPHICS
        )

        self._check_special_ad_category_country()
        self._check_budget_ownership(rules)

        for idx, adset in enumerate(self.adsets):
            where = f"adsets[{idx}]"

            # The conversion location is checked first: everything below it is
            # validated against ITS rules, not the objective's flat union. A goal
            # that is legal for the objective can still be illegal for the chosen
            # destination — LEAD_GENERATION on a WEBSITE destination is exactly
            # that case, and it used to be the shipped default.
            try:
                dest = rules.for_destination(adset.destination_type)
            except KeyError:
                allowed = ", ".join(d.value for d in rules.destination_types)
                raise ValueError(
                    f"{where}.destination_type {adset.destination_type.value} is not a "
                    f"conversion location for {self.objective.value}; allowed: {allowed}"
                ) from None

            if not dest.allows_optimization_goal(adset.optimization_goal.value):
                allowed = ", ".join(g.value for g in dest.optimization_goals)
                raise ValueError(
                    f"{where}.optimization_goal {adset.optimization_goal.value} is not valid "
                    f"for {self.objective.value} → {dest.label}; allowed: {allowed}"
                )

            # The goal's own rules. Everything from here is the *intersection* of
            # what the conversion location allows and what the goal allows — the
            # two used to be checked independently, which let through pairs that
            # were individually legal and jointly rejected.
            goal = goal_rules(adset.optimization_goal)

            adset._omit_destination_type = dest.omit_destination_type

            # Placements against the conversion location. AdSetSpec's own
            # targeting validator checks the *vocabulary* and platform↔position
            # consistency; it cannot see the destination, so nothing rejected
            # audience_network on a Messenger ad set until here. Both rules are
            # measured — see DestinationRules.publisher_platforms.
            platforms = adset.targeting.get("publisher_platforms")
            rejected = dest.rejected_platforms(platforms)
            if rejected:
                allowed = ", ".join(dest.publisher_platforms or ())
                raise ValueError(
                    f"{where}.targeting.publisher_platforms {rejected} cannot deliver "
                    f"to {dest.label}; allowed: {allowed}"
                )
            if platforms and "messenger" in platforms and not (
                set(platforms) & set(MESSENGER_NEEDS_COMPANION)
            ):
                raise ValueError(
                    f"{where}.targeting.publisher_platforms has messenger on its own; "
                    f"Meta needs one of {', '.join(MESSENGER_NEEDS_COMPANION)} alongside it"
                )

            if not dest.allows_billing_event(adset.billing_event.value):
                allowed = ", ".join(e.value for e in dest.billing_events)
                raise ValueError(
                    f"{where}.billing_event {adset.billing_event.value} is not valid "
                    f"for {self.objective.value} → {dest.label}; allowed: {allowed}"
                )

            if not goal.allows_billing_event(adset.billing_event.value):
                allowed = ", ".join(e.value for e in goal.billing_events)
                raise ValueError(
                    f"{where}.billing_event {adset.billing_event.value} cannot be "
                    f"paired with optimization_goal {adset.optimization_goal.value}; "
                    f"allowed: {allowed}"
                )

            if not rules.allows_bid_strategy(adset.bid_strategy.value):
                allowed = ", ".join(s.value for s in rules.bid_strategies)
                raise ValueError(
                    f"{where}.bid_strategy {adset.bid_strategy.value} is not valid "
                    f"for {self.objective.value}; allowed: {allowed}"
                )

            if not goal.allows_bid_strategy(adset.bid_strategy.value):
                allowed = ", ".join(s.value for s in goal.bid_strategies)
                raise ValueError(
                    f"{where}.bid_strategy {adset.bid_strategy.value} cannot be "
                    f"paired with optimization_goal {adset.optimization_goal.value}; "
                    f"allowed: {allowed}"
                )

            # No billing_event -> bid_strategy rule here. Meta's "You cannot use
            # autobidding with the specified billing_event: APP_INSTALLS" looked
            # like one, but pairing that billing event with a capped strategy is
            # answered "CPA billing is no longer available" — the event is
            # retired, so GOAL_RULES simply no longer offers it and there is
            # nothing left for a validator to catch.
            self._check_goal_only_fields(rules, goal, adset, where)
            self._check_promoted_object(dest, adset, where, self.page_id)
            self._check_lead_form_draft(dest, adset, where)

            if restricted_category:
                self._check_special_category_targeting(adset, where)

            for jdx, ad in enumerate(adset.ads):
                self._check_creative(
                    dest,
                    goal,
                    adset.optimization_goal.value,
                    ad,
                    f"{where}.ads[{jdx}]",
                    self.objective,
                )

        return self

    @staticmethod
    def _check_lead_form_draft(dest: DestinationRules, adset: AdSetSpec, where: str) -> None:
        """A form to create at publish, or one that already exists — not both.

        Both are legal on their own and neither is required (a null pair means
        "generate a default form", which publish still does). Two answers to
        "which form do these ads submit to?" is the one state that cannot be
        resolved at publish without guessing.
        """
        draft = adset.lead_form_draft
        if not draft:
            return
        if not dest.requires_lead_form:
            raise ValueError(
                f"{where}.lead_form_draft is only used when the conversion location "
                f"is an instant form, not {dest.label}"
            )
        if any(ad.creative.lead_gen_form_id for ad in adset.ads):
            raise ValueError(
                f"{where} has both a lead_form_draft and an existing "
                f"lead_gen_form_id — pick one form for the ad set"
            )

    @staticmethod
    def _check_goal_only_fields(
        rules: ObjectiveRules, goal: GoalRules, adset: AdSetSpec, where: str
    ) -> None:
        """Ad set fields Meta only accepts for certain objectives / goals.

        Both were previously either unchecked or checked against a single
        hardcoded goal, so a valid combination was rejected and an invalid one
        was sent. The frequency cap needs BOTH gates: the Reach goal is offered
        under Traffic and Sales, where Meta rejects the field on the objective.
        """
        if adset.frequency_control_specs and not rules.allows_frequency_control:
            raise ValueError(
                f"{where}.frequency_control_specs is only accepted on "
                f"{', '.join(r.label for r in OBJECTIVE_MATRIX.values() if r.allows_frequency_control)} "
                f"campaigns, not {rules.label}"
            )
        if adset.frequency_control_specs and not goal.allows_frequency_control:
            raise ValueError(
                f"{where}.frequency_control_specs is only accepted with an "
                f"optimization goal Meta caps frequency on (Reach or ThruPlay), "
                f"not {adset.optimization_goal.value}"
            )
        if adset.attribution_spec and not goal.allows_attribution_spec:
            raise ValueError(
                f"{where}.attribution_spec needs a conversion to attribute — "
                f"{adset.optimization_goal.value} does not report one"
            )

    @staticmethod
    def _check_creative(
        dest: DestinationRules,
        goal: GoalRules,
        goal_value: str,
        ad: AdSpec,
        where: str,
        objective: Objective,
    ) -> None:
        creative = ad.creative
        if not dest.allows_call_to_action(creative.call_to_action.value):
            allowed = ", ".join(c.value for c in dest.call_to_actions)
            raise ValueError(
                f"{where}.creative.call_to_action {creative.call_to_action.value} is not "
                f"valid for {objective.value} → {dest.label}; allowed: {allowed}"
            )

        if not dest.allows_ad_format(creative.format.value):
            allowed = ", ".join(f.value for f in dest.ad_formats)
            raise ValueError(
                f"{where}.creative.format {creative.format.value} is not available for "
                f"{objective.value} → {dest.label}; allowed: {allowed}"
            )

        # The goal can narrow the format further than the destination does:
        # ThruPlay optimizes for watch time, and publish expresses that as a
        # single `video_data` creative, which a carousel cannot be.
        if goal.ad_formats and creative.format not in goal.ad_formats:
            allowed = ", ".join(f.value for f in goal.ad_formats)
            raise ValueError(
                f"{where}.creative.format {creative.format.value} cannot be used with "
                f"optimization_goal {goal_value}; allowed: {allowed}"
            )

        # ...and it can demand a particular kind of asset. This is the reported
        # bug: an Awareness campaign optimizing for ThruPlay happily accepted an
        # image, then ran an ad Meta could not optimize.
        #
        # Only checked once media exists. A freshly built plan carries none — the
        # user attaches it in the editor — and refusing to build the plan at all
        # would leave them nothing to attach media to. Publish is the second gate:
        # it re-resolves the real media type and skips an ad that still mismatches.
        if (
            goal.media_kind == "video"
            and creative.media_kind is not None
            and creative.media_kind != "video"
        ):
            raise ValueError(
                f"{where}.creative needs a video, not an image — "
                f"{goal_value} pays for watch time"
            )

        # A boost destination without a post is an ad with nothing to boost.
        if dest.object_story_kind and not (
            creative.object_story_id or creative.source_instagram_media_id
        ):
            raise ValueError(
                f"{where}.creative.object_story_id is required for {dest.label} — "
                f"pick the {dest.object_story_kind} you want to promote"
            )
        # One ad promotes one post.
        if creative.object_story_id and creative.source_instagram_media_id:
            raise ValueError(
                f"{where}.creative names both a Facebook post and an Instagram post "
                f"— an ad promotes one or the other"
            )
        # Elsewhere an existing post is allowed only where it is known to work.
        # ``allows_existing_post`` is measured, not assumed — see DestinationRules.
        promotes_a_post = bool(
            creative.object_story_id or creative.source_instagram_media_id
        )
        if promotes_a_post and not (dest.object_story_kind or dest.allows_existing_post):
            raise ValueError(
                f"{where}.creative.object_story_id is only used when the ad "
                f"promotes an existing post, not {dest.label}"
            )

        # A null lead_gen_form_id on an instant-form ad is NOT an error: it means
        # "create one for me", and publish does (executors/media._resolve_lead_form,
        # ledger-backed). Requiring it here made every Leads instant-form run
        # unbuildable, since the form is created against the finished campaign's
        # name and copy — after the spec exists. Publish is the real gate.
        if creative.lead_gen_form_id and not dest.requires_lead_form:
            raise ValueError(
                f"{where}.creative.lead_gen_form_id is only used when the conversion "
                f"location is an instant form, not {dest.label}"
            )

    def _check_special_ad_category_country(self) -> None:
        """A declaration is made under a country's rules, so Meta wants both.

        The pair is checked here rather than on the field so the error names the
        country input the user has to fill, not the category they already chose.
        """
        if self.special_ad_categories and not self.special_ad_category_country:
            raise ValueError(
                "special_ad_category_country is required when a special ad "
                "category is declared — pick the country whose rules apply"
            )
        if self.special_ad_category_country and not self.special_ad_categories:
            raise ValueError(
                "special_ad_category_country is only used with a special ad category"
            )
        bad = [c for c in self.special_ad_category_country if len(c) != 2 or not c.isalpha()]
        if bad:
            raise ValueError(
                f"special_ad_category_country takes two-letter country codes, got {bad}"
            )

    def _check_budget_ownership(self, rules) -> None:
        """CBO vs per-ad-set budgets: exactly one level owns the money.

        Meta rejects an ad set carrying a budget under a CBO campaign, and a
        campaign where neither level has one never spends — both are caught
        here so the user sees a form error, not a publish failure.
        """
        if self.daily_budget and self.lifetime_budget:
            raise ValueError("set at most one of campaign daily_budget or lifetime_budget")

        # Ad set budget sharing is ABO-only (it is normalized away under a
        # campaign budget below), but Meta still wants the campaign-level bid
        # strategy that goes with it — "You cannot enable ad set budget sharing
        # without bid strategy" rejects the campaign at preflight otherwise.
        if (
            self.is_adset_budget_sharing_enabled
            and not self.has_campaign_budget
            and not self.bid_strategy
        ):
            raise ValueError(
                "ad set budget sharing requires a campaign-level bid_strategy — "
                "pick one, or turn the sharing option off"
            )

        if self.has_campaign_budget:
            if not self.bid_strategy:
                raise ValueError(
                    "a campaign budget (Advantage+ campaign budget) requires a "
                    "campaign-level bid_strategy"
                )
            # Under a lowest-cost campaign budget Meta makes every ad set
            # optimize for the same thing: "The same optimization for ad delivery
            # selection is required if the campaign bid strategy is lowest cost."
            # The two-stage preflight cannot catch this — each ad set is
            # validated alone against an empty campaign, where no sibling exists
            # to conflict with — so the first ad set is created and the second
            # fails, leaving a half-built campaign behind.
            if self.bid_strategy is BidStrategy.LOWEST_COST_WITHOUT_CAP:
                goals = {a.optimization_goal for a in self.adsets}
                if len(goals) > 1:
                    named = ", ".join(sorted(g.value for g in goals))
                    raise ValueError(
                        "every ad set must share one optimization_goal under an "
                        f"Advantage+ campaign budget on {self.bid_strategy.value}; "
                        f"this plan mixes {named}"
                    )
            # ABO-only, and never sent under CBO (see to_payload) — so a stale
            # True is not a user choice to reject, it is state to normalize.
            # Rejecting it wedged the editor: the checkbox that clears it is
            # hidden under a campaign budget, so the error had no control to
            # act on and the form just re-emitted.
            self.is_adset_budget_sharing_enabled = False
            if not rules.allows_bid_strategy(self.bid_strategy.value):
                allowed = ", ".join(s.value for s in rules.bid_strategies)
                raise ValueError(
                    f"bid_strategy {self.bid_strategy.value} is not valid for "
                    f"{self.objective.value}; allowed: {allowed}"
                )
            for idx, adset in enumerate(self.adsets):
                if adset.daily_budget or adset.lifetime_budget:
                    raise ValueError(
                        f"adsets[{idx}] must not carry a budget under an "
                        "Advantage+ campaign budget"
                    )
                if self.lifetime_budget and not adset.end_time:
                    raise ValueError(
                        f"adsets[{idx}].end_time is required with a campaign "
                        "lifetime_budget"
                    )
                if (
                    self.bid_strategy in BID_STRATEGIES_REQUIRING_AMOUNT
                    and not adset.bid_amount
                ):
                    raise ValueError(
                        f"adsets[{idx}].bid_amount is required with campaign "
                        f"bid_strategy {self.bid_strategy.value}"
                    )
                if (
                    self.bid_strategy == BID_STRATEGY_REQUIRING_ROAS_FLOOR
                    and not adset.bid_constraints
                ):
                    raise ValueError(
                        f"adsets[{idx}].bid_constraints.roas_average_floor is "
                        f"required with campaign bid_strategy {self.bid_strategy.value}"
                    )
        else:
            for idx, adset in enumerate(self.adsets):
                if not (adset.daily_budget or adset.lifetime_budget):
                    raise ValueError(
                        f"adsets[{idx}] needs a daily_budget or lifetime_budget "
                        "(or switch to an Advantage+ campaign budget)"
                    )

        # The two scheduling features are opposites, and each belongs to one
        # budget kind: dayparting restricts when a lifetime-budget ad set runs;
        # budget scheduling raises a *daily* budget over a window. Offering both
        # regardless of budget type is what made the form inconsistent.
        for idx, adset in enumerate(self.adsets):
            has_lifetime = bool(adset.lifetime_budget or self.lifetime_budget)
            if adset.adset_schedule and not has_lifetime:
                raise ValueError(
                    f"adsets[{idx}].adset_schedule (ad scheduling) requires a "
                    "lifetime budget"
                )
            if adset.budget_schedule_specs and has_lifetime:
                raise ValueError(
                    f"adsets[{idx}].budget_schedule_specs (budget scheduling) "
                    "applies to a daily budget — a lifetime budget is already "
                    "spread across the run, so use ad scheduling instead"
                )
            # Budget scheduling raises *a budget*, and under a campaign budget
            # the ad set has none — to_payload strips it. The window therefore
            # has to ride on the campaign, which is what carries the money.
            if adset.budget_schedule_specs and self.has_campaign_budget:
                raise ValueError(
                    f"adsets[{idx}].budget_schedule_specs cannot be set under an "
                    "Advantage+ campaign budget — the campaign owns the budget, so "
                    "schedule the increase on the campaign instead"
                )
        if self.budget_schedule_specs and not self.daily_budget:
            raise ValueError(
                "budget_schedule_specs on the campaign requires a campaign daily "
                "budget"
            )

    @staticmethod
    def _check_promoted_object(
        dest: DestinationRules, adset: AdSetSpec, where: str, campaign_page_id: str | None = None
    ) -> None:
        """A conversion goal without its promoted_object is the expensive failure
        mode: Meta accepts the ad set, then optimizes against a signal that never
        arrives. The old media.py published exactly this whenever the account had
        no pixel.

        Which kind is required depends on the conversion location, not the goal
        alone: LEAD_GENERATION wants the Page on an Instant Form ad and a pixel on
        a website ad.
        """
        required = dest.promoted_object_kind(adset.optimization_goal)
        actual = adset.promoted_object.kind() if adset.promoted_object else PROMOTED_NONE

        # One plan, one Page — checked before the kind rules below, because an ad
        # set can name a Page whatever kind it promotes. The creative's
        # object_story_spec is built from the campaign's page_id at publish, so a
        # mismatch advertises Page A with Page B's post.
        po_page = adset.promoted_object.page_id if adset.promoted_object else None
        if po_page and campaign_page_id and str(po_page) != str(campaign_page_id):
            raise ValueError(
                f"{where}.promoted_object.page_id is a different Facebook Page "
                f"than the campaign's page_id — one campaign publishes under one Page"
            )

        if required == PROMOTED_NONE:
            return

        if actual != required:
            # Named down to the field, not just ``.promoted_object``: this is a
            # whole-model validator so Pydantic reports no loc, and
            # errors_to_form_keys re-anchors the error off this leading path.
            # The editor highlights the pixel/page control the user has to fix
            # instead of only showing a form-level banner.
            field, hint = {
                PROMOTED_PIXEL: ("pixel_id",
                                 "a Meta Pixel or custom conversion is required — "
                                 "connect one or choose a non-conversion "
                                 "optimization goal"),
                PROMOTED_PAGE: ("page_id", "a connected Facebook Page is required"),
                PROMOTED_APPLICATION: ("application_id",
                                       "a registered app and store URL are required"),
            }[required]
            raise ValueError(
                f"{where}.promoted_object.{field} is required for "
                f"optimization_goal {adset.optimization_goal.value}: {hint}"
            )

        po = adset.promoted_object
        # A custom conversion IS the event definition, so it answers this on its
        # own; a bare pixel still has to name which event to optimize toward.
        if required == PROMOTED_PIXEL and not (po.custom_event_type or po.custom_conversion_id):
            raise ValueError(f"{where}.promoted_object.custom_event_type is required with a pixel")
        if required == PROMOTED_APPLICATION and not po.object_store_url:
            raise ValueError(f"{where}.promoted_object.object_store_url is required with an app")

    @staticmethod
    def _check_special_category_targeting(adset: AdSetSpec, where: str) -> None:
        """Every narrowing a credit / employment / housing campaign may not use.

        ``builder._sanitize_for_special_category`` already strips these at build
        time, so for a freshly built plan this check never fires. It exists
        because the plan is **editable**: the form submits a whole spec, and
        nothing stopped a user from putting the ZIPs, the interests or the
        lookalike back after the builder removed them. Meta rejects the ad set,
        and repeat offences put the ad account at risk — so the rule belongs
        where every path validates, not only where the builder assembles.
        """
        t = adset.targeting

        if t.get("genders"):
            raise ValueError(
                f"{where}.targeting.genders must be empty for a special ad category campaign"
            )
        if int(t.get("age_min") or 18) != 18 or int(t.get("age_max") or 65) != 65:
            raise ValueError(
                f"{where}.targeting age range must stay 18-65 for a special ad category campaign"
            )

        geo = t.get("geo_locations") or {}
        if geo.get("zips"):
            raise ValueError(
                f"{where}.targeting.geo_locations.zips is not allowed for a special ad "
                f"category campaign — use a city or a "
                f"{SPECIAL_CATEGORY_MIN_RADIUS_MILES}-mile radius"
            )
        for pin in geo.get("custom_locations") or []:
            if not radius_meets_special_category_floor(
                pin.get("radius"), pin.get("distance_unit")
            ):
                raise ValueError(
                    f"{where}.targeting radius must be at least "
                    f"{SPECIAL_CATEGORY_MIN_RADIUS_MILES} miles for a special ad "
                    f"category campaign (got {pin.get('radius')} "
                    f"{pin.get('distance_unit') or 'mile'})"
                )

        if t.get("flexible_spec"):
            raise ValueError(
                f"{where}.targeting.flexible_spec (interest and behavior targeting) is not "
                f"allowed for a special ad category campaign"
            )
        if t.get("exclusions"):
            raise ValueError(
                f"{where}.targeting.exclusions are not allowed for a special ad category campaign"
            )
        if adset.audience_role == "lookalike":
            raise ValueError(
                f"{where}.audience_role cannot be 'lookalike' for a special ad category "
                f"campaign — Special Ad Audiences were retired in 2022"
            )
        # Same rule, reached the other way. A category campaign cannot use a
        # custom audience at all, so an id the user picked in the editor is
        # refused here rather than by Meta after the campaign object already
        # exists — the audience_role check above only covers the ones Punk builds.
        if adset.attached_audience_ids or adset.excluded_audience_ids:
            raise ValueError(
                f"{where} cannot target or exclude a saved audience for a special ad "
                f"category campaign — Meta does not allow audience targeting on "
                f"housing, employment, credit, social issues, or financial products"
            )

    def bind_audiences(
        self,
        *,
        custom_audience_id: str | None,
        lookalike_audience_id: str | None,
    ) -> CampaignSpec:
        """Return a copy with the real audience ids written into each ad set's
        targeting, according to its ``audience_role``.

        Called once at publish, after the audiences have been created. A role
        whose audience does not exist degrades to **Advantage+ audience** — a
        lookalike can legitimately fail to build (seed too small, not yet
        populated), and the user can choose to publish without the visitor
        audience at all when Meta refuses to hold one. Neither should leave the
        ad set on raw geo: a seed ad set carries ``advantage_audience: 0`` from
        build time (the MAID list IS its audience), so dropping that list
        without flipping the toggle published the narrowest possible targeting
        with nothing to narrow.

        That degrade applies ONLY to a role that expected an audience. A
        ``broad`` ad set never had one, so its ``advantage_audience`` is
        whatever the user chose in the editor and is left alone — forcing it on
        here discarded an explicit "use my targeting only" on every ad set the
        editor adds (they are all created broad).

        Audiences the user picked in the editor (``attached_audience_ids`` /
        ``excluded_audience_ids``) are written here too, and they are **added to**
        the role's audience rather than replacing it: an ad set can prospect
        against the lookalike while excluding people who already converted, which
        is the entire point of having the exclusion. Because those ids are real
        targeting, an ad set carrying them never takes the Advantage+ degrade
        above — it did not lose its audience, it has a different one.

        Re-validates, so a bound spec is still a checked spec.
        """
        bound: list[dict[str, Any]] = []
        for adset in self.adsets:
            data = adset.model_dump()
            targeting = dict(data["targeting"])

            role_id: str | None = None
            if adset.audience_role == "seed":
                role_id = custom_audience_id
            elif adset.audience_role == "lookalike":
                role_id = lookalike_audience_id

            # The role's audience and the user's picks are both real targeting;
            # neither replaces the other. Order and de-duplication are explicit
            # because Meta ORs the list — a repeated id is not an error, it is
            # just noise in a payload somebody will read during a support case.
            include = [i for i in ([role_id] if role_id else []) + list(adset.attached_audience_ids) if i]
            include = list(dict.fromkeys(include))
            if include:
                targeting["custom_audiences"] = [{"id": i} for i in include]
            else:
                targeting.pop("custom_audiences", None)
                # Only a role that EXPECTED an audience degrades. A broad ad set
                # never had one, so its advantage_audience is the user's own
                # choice in the editor and forcing it on here would discard an
                # explicit "use my targeting only".
                if adset.audience_role in ("seed", "lookalike"):
                    targeting["targeting_automation"] = {"advantage_audience": 1}

            excluded = list(dict.fromkeys(i for i in adset.excluded_audience_ids if i))
            if excluded:
                targeting["excluded_custom_audiences"] = [{"id": i} for i in excluded]
            else:
                targeting.pop("excluded_custom_audiences", None)

            data["targeting"] = targeting
            bound.append(data)

        return self.model_validate({**self.model_dump(), "adsets": bound})

    def to_payload(self) -> dict[str, Any]:
        """The Graph API campaign-create body."""
        payload: dict[str, Any] = {
            "name": self.name,
            "objective": self.objective.value,
            "status": self.status.value,
            "buying_type": self.buying_type,
            # Meta wants [] for "no category" — the NONE enum member is not a
            # valid list element.
            "special_ad_categories": [c.value for c in self.special_ad_categories],
        }
        if self.special_ad_category_country:
            payload["special_ad_category_country"] = [
                c.upper() for c in self.special_ad_category_country
            ]
        if self.daily_budget:
            payload["daily_budget"] = self.daily_budget
        if self.lifetime_budget:
            payload["lifetime_budget"] = self.lifetime_budget
        if self.bid_strategy:
            payload["bid_strategy"] = self.bid_strategy.value
        if not self.has_campaign_budget:
            # Required under ABO, rejected under CBO — hence the gate. Meta:
            # "You must specify True or False in the field
            # is_adset_budget_sharing_enabled if you are not using campaign budget."
            payload["is_adset_budget_sharing_enabled"] = self.is_adset_budget_sharing_enabled
        if self.budget_schedule_specs:
            payload["budget_schedule_specs"] = [
                b.to_payload() for b in self.budget_schedule_specs
            ]
        # App promotion only. Absent for every other objective, because Meta
        # rejects a campaign-level promoted_object where the objective has no app.
        if self.promoted_object:
            payload["promoted_object"] = self.promoted_object.to_payload()
        if self.is_skadnetwork_attribution:
            payload["is_skadnetwork_attribution"] = True
        return payload

    def total_budget_cents(self) -> int:
        if self.has_campaign_budget:
            return self.daily_budget or self.lifetime_budget or 0
        return sum((a.daily_budget or a.lifetime_budget or 0) for a in self.adsets)


def _iso(dt: datetime) -> str:
    """Meta wants ISO-8601 with an offset. Naive datetimes are treated as UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _epoch(dt: datetime) -> int:
    """Unix seconds, for the fields Meta types as ``unsigned int``.

    Only budget scheduling wants this shape — see ``BudgetScheduleSpec``. Same
    naive-is-UTC convention as ``_iso`` so the two cannot disagree about what a
    tz-less datetime means.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())
