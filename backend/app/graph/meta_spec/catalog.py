"""
graph/meta_spec/catalog.py
──────────────────────────
The option catalog the campaign editor renders from.

The editor is a hand-built Ads-Manager surface (Campaign panel · Ad Set tabs · Ad
cards), so it does not need per-field descriptors — it needs the *vocabulary*.

That vocabulary is **two-dimensional**, because Meta's is: the objective decides
which conversion locations exist, and the conversion location decides the
optimization goals, billing events, CTAs, ad formats and promoted object. Shipping
flat `*_by_objective` lists is what let the editor offer a goal that was legal for
the objective but illegal for the destination — see ``objective_matrix``.

So the shape is::

    destinations_by_objective: {objective: [{value, label, optimization_goals, …}]}

Everything is derived straight from ``objective_matrix`` + ``enums`` so there is
still no Meta knowledge in the frontend: changing the matrix changes the editor's
dropdowns, nobody edits React. Labels come from ``META_LABELS`` rather than
Title-casing the enum, so the words match what the user sees in Ads Manager.

The whole catalog ships regardless of the current objective, so switching
objective or destination re-renders locally with no round trip — which matters
because the user tries several before committing. The server ``CampaignSpec``
remains the authority; the catalog only drives the UI.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from app.graph.meta_spec.enums import (
    APP_PLATFORMS,
    ATTRIBUTION_CLICK_WINDOWS,
    ATTRIBUTION_DEFAULT,
    ATTRIBUTION_ENGAGED_VIEW_WINDOWS,
    ATTRIBUTION_VIEW_WINDOWS,
    BID_STRATEGY_REQUIRING_ROAS_FLOOR,
    BUDGET_SCHEDULE_MAX_MULTIPLIER,
    BUDGET_SCHEDULE_MULTIPLIER_SCALE,
    ROAS_FLOOR_MAX,
    ROAS_FLOOR_MIN,
    ROAS_FLOOR_SCALE,
    CATEGORIES_BLOCKING_DEMOGRAPHICS,
    CREATIVE_BODY_MAX,
    CREATIVE_BODY_RECOMMENDED,
    CREATIVE_DESCRIPTION_MAX,
    CREATIVE_DESCRIPTION_RECOMMENDED,
    CREATIVE_TITLE_MAX,
    CREATIVE_TITLE_RECOMMENDED,
    CAROUSEL_MAX_CARDS,
    CAROUSEL_MIN_CARDS,
    FREQUENCY_DEFAULT_INTERVAL_DAYS,
    FREQUENCY_DEFAULT_MAX,
    FREQUENCY_MAX_INTERVAL_DAYS,
    LEAD_FORM_DEFAULT_QUESTIONS,
    LEAD_FORM_INTRO_TITLE_MAX,
    LEAD_FORM_LABEL_MAX,
    LEAD_FORM_MAX_INTRO_LINES,
    LEAD_FORM_MAX_OPTIONS,
    LEAD_FORM_QUESTION_TYPES,
    PLATFORM_POSITION_FIELDS,
    PUBLISHER_PLATFORMS,
    SPECIAL_AD_CATEGORY_COUNTRIES,
    AdFormat,
    BidStrategy,
    CallToAction,
    Objective,
    SpecialAdCategory,
    meta_label,
)
from app.graph.meta_spec.models import (
    CREATIVE_MAX_MEDIA,
    CREATIVE_MAX_SUGGESTIONS,
    min_budget_cents,
)
from app.graph.meta_spec.objective_matrix import (
    DEFAULT_PIXEL_EVENT,
    GOAL_RULES,
    OBJECTIVE_MATRIX,
    PAGE_SCOPED_PREREQUISITES,
    DestinationRules,
)


# Every user_info key any destination can demand, collected from the matrix so a
# new prerequisite is reported to the editor without an edit here. app_store_url
# stands for "a store link" — either store satisfies it, exactly as the intake
# form's validation treats it.
#
# PAGE_SCOPED_PREREQUISITES are excluded: their answer lives on the chosen Page,
# not in user_info, so a flat True/False here would read "missing" for every user
# and light up a warning on a Page that is perfectly fine. The editor answers
# those off page_candidates instead.
_PREREQUISITE_KEYS: tuple[str, ...] = tuple(sorted({
    key
    for rules in OBJECTIVE_MATRIX.values()
    for dest in rules.destinations
    for key in dest.required_user_info
    if key not in PAGE_SCOPED_PREREQUISITES
}))

# Standard Meta pixel conversion events. Meta's accepted set is account-dependent
# and CampaignSpec + preflight_publish are the real gates; this is the vocabulary
# the editor offers.
PIXEL_EVENTS: tuple[str, ...] = (
    "PURCHASE", "LEAD", "COMPLETE_REGISTRATION", "ADD_TO_CART",
    "INITIATE_CHECKOUT", "ADD_PAYMENT_INFO", "SUBSCRIBE", "CONTACT",
    "SEARCH", "VIEW_CONTENT", "ADD_TO_WISHLIST", "START_TRIAL",
    "SUBMIT_APPLICATION",
)


def _prerequisite_present(user_info: dict, key: str) -> bool:
    values = [user_info.get(key)]
    if key == "app_store_url":
        values.append(user_info.get("play_store_url"))
    return any(str(v or "").strip() for v in values)


def _opt(value: str, label: Optional[str] = None) -> dict[str, str]:
    """One select option. Labels default to Meta's own wording — Title-casing the
    enum invents vocabulary ("Offsite Conversions" for what Ads Manager calls
    "Conversions") and users compare the two surfaces side by side."""
    return {"value": value, "label": label or meta_label(value)}


def _destination(dest: DestinationRules) -> dict[str, Any]:
    """One conversion location and everything it decides."""
    return {
        "value": dest.destination_type.value,
        "label": dest.label,
        "help": dest.help_text,
        "optimization_goals": [_opt(g.value) for g in dest.optimization_goals],
        "billing_events": [_opt(e.value) for e in dest.billing_events],
        "call_to_actions": [_opt(c.value) for c in dest.call_to_actions],
        "ad_formats": [_opt(f.value) for f in dest.ad_formats],
        # {goal: "none"|"pixel"|"page"|"application"} — lets the editor show the
        # pixel picker (or an app/page warning) before the user hits publish.
        "promoted_object_kind_by_goal": {
            goal.value: dest.promoted_object_kind(goal)
            for goal in dest.optimization_goals
        },
        "requires_lead_form": dest.requires_lead_form,
        # "" for a normal composed ad; "post"/"video"/"event" when the ad
        # promotes something that already exists on the Page, which the editor
        # renders as a picker instead of copy + media fields.
        "object_story_kind": dest.object_story_kind,
        # Whether the editor may OFFER an existing post here (Facebook or
        # Instagram) as an alternative to composing one. Distinct from
        # object_story_kind, which means the post is mandatory.
        "allows_existing_post": dest.allows_existing_post,
        "required_user_info": list(dest.required_user_info),
    }


def _goal_rules_payload() -> dict[str, Any]:
    """What each optimization goal decides, for the editor's cascade.

    The destination lists alone are not enough: picking a goal narrows the
    billing events and bid strategies further, and can require a video. Shipping
    the goal layer means the editor stops offering a pair the server will reject.
    """
    return {
        goal.value: {
            "billing_events": [e.value for e in rules.billing_events],
            "bid_strategies": [s.value for s in rules.bid_strategies],
            # null means "either" — the editor only constrains when set.
            "media_kind": rules.media_kind,
            "ad_formats": (
                [f.value for f in rules.ad_formats] if rules.ad_formats else None
            ),
            "allows_frequency_control": rules.allows_frequency_control,
            "allows_attribution_spec": rules.allows_attribution_spec,
        }
        for goal, rules in GOAL_RULES.items()
    }


def build_editor_catalog(
    objective: Objective | str | None = None,
    pixel_candidates: Optional[list[dict]] = None,
    custom_conversions: Optional[list[dict]] = None,
    audience_candidates: Optional[list[dict]] = None,
    lead_form_candidates: Optional[list[dict]] = None,
    page_id: Optional[str] = None,
    page_candidates: Optional[list[dict]] = None,
    user_info: Optional[dict] = None,
    previous_campaigns: Optional[list[dict]] = None,
    ad_account_timezone: Optional[str] = None,
) -> dict[str, Any]:
    """Everything the campaign editor needs to render dependent dropdowns.

    ``objective`` is informational only (the current campaign objective); every
    objective's option lists ship regardless, so switching is instant client-side.

    ``user_info`` is read only to answer "do we have this prerequisite?" — the
    destination lists already carry ``required_user_info``, but without knowing
    what the run actually collected the editor could not tell the user that the
    conversion location they just picked has nowhere to send people. The values
    themselves are not shipped, only whether each is present.
    """
    positions = {
        platform: [_opt(p) for p in allowed]
        for platform, (_pos_key, allowed) in PLATFORM_POSITION_FIELDS.items()
    }
    position_field_by_platform = {
        platform: pos_key
        for platform, (pos_key, _allowed) in PLATFORM_POSITION_FIELDS.items()
    }
    return {
        "current_objective": (
            objective.value if isinstance(objective, Objective) else objective
        ),
        "objectives": [
            {"value": obj.value, "label": rules.label, "help": rules.help_text}
            for obj, rules in OBJECTIVE_MATRIX.items()
        ],
        # The second axis. Everything goal/billing/CTA/format-shaped hangs off an
        # entry in here, not off the objective.
        "destinations_by_objective": {
            obj.value: [_destination(d) for d in rules.destinations]
            for obj, rules in OBJECTIVE_MATRIX.items()
        },
        "special_ad_categories": [_opt(c.value) for c in SpecialAdCategory],
        # Plain codes, not {value, label} — _opt() exists so Meta enum wording
        # matches Ads Manager, and meta_label("US") would say "Us". A country name
        # is a locale concern, so the browser resolves it with Intl.DisplayNames.
        "special_ad_category_countries": list(SPECIAL_AD_CATEGORY_COUNTRIES),
        "categories_blocking_demographics": sorted(CATEGORIES_BLOCKING_DEMOGRAPHICS),
        # Bid strategy is decided at campaign level, so it stays per-objective.
        "bid_strategies": [_opt(s.value) for s in BidStrategy],
        # The third rule layer: what the optimization goal itself decides.
        "goal_rules": _goal_rules_payload(),
        "bid_strategies_by_objective": {
            obj.value: [_opt(s.value) for s in rules.bid_strategies]
            for obj, rules in OBJECTIVE_MATRIX.items()
        },
        # The frequency cap has an objective gate on top of the goal gate in
        # `goal_rules` — Meta accepts it on Awareness and Engagement only, even
        # though the Reach goal is offered under Traffic and Sales too.
        "frequency_control_by_objective": {
            obj.value: rules.allows_frequency_control
            for obj, rules in OBJECTIVE_MATRIX.items()
        },
        "bid_strategies_requiring_amount": [
            BidStrategy.COST_CAP.value,
            BidStrategy.LOWEST_COST_WITH_BID_CAP.value,
        ],
        # The ROAS goal is the odd one out: its target rides in bid_constraints,
        # scaled 10000x, and Meta rejects a bid_amount alongside it.
        "roas_goal": {
            "bid_strategy": BID_STRATEGY_REQUIRING_ROAS_FLOOR,
            "scale": ROAS_FLOOR_SCALE,
            "min": ROAS_FLOOR_MIN,
            "max": ROAS_FLOOR_MAX,
        },
        # Targeting vocabulary.
        "genders": [_opt("all", "All"), _opt("male", "Men"), _opt("female", "Women")],
        "placements": {
            "publisher_platforms": [_opt(p) for p in PUBLISHER_PLATFORMS],
            "positions": positions,
            "position_field_by_platform": position_field_by_platform,
        },
        # Three windows, matching Ads Manager: click-through, engage-through
        # (ENGAGED_VIDEO_VIEW on the wire) and view-through.
        #
        # ponytail: goal-level gating only. Meta says supported window lengths
        # "differ by optimization goal and campaign objective", but
        # validate_adset_payload preflights the real combination with
        # validate_only=True before any spend, so a rejected pairing surfaces as a
        # form error. Build the full matrix only if that preflight stops being run.
        "attribution": {
            "click_windows": list(ATTRIBUTION_CLICK_WINDOWS),
            "view_windows": list(ATTRIBUTION_VIEW_WINDOWS),
            "engaged_view_windows": list(ATTRIBUTION_ENGAGED_VIEW_WINDOWS),
            # Display-only, unlike frequency_cap's seed below: the editor shows
            # these as the selected values but writes nothing to the spec until the
            # user changes one, so an untouched ad set keeps following Meta's own
            # default rather than freezing today's into the campaign.
            "default": [dict(w) for w in ATTRIBUTION_DEFAULT],
        },
        # What the editor seeds a frequency cap with when the user switches TO a
        # goal that allows one — the same values build_campaign_spec starts from,
        # so the field is never blank on a Reach/ThruPlay ad set.
        "frequency_cap": {
            "event": "IMPRESSIONS",
            "interval_days": FREQUENCY_DEFAULT_INTERVAL_DAYS,
            "max_frequency": FREQUENCY_DEFAULT_MAX,
            "max_interval_days": FREQUENCY_MAX_INTERVAL_DAYS,
        },
        # Meta targets one app store per ad set (promoted_object.object_store_url
        # is a single URL), so an App-promotion campaign runs one ad set per OS.
        # The editor renders the store URL + OS picker from this.
        "app_platforms": [
            {"value": user_os, "label": label} for _key, user_os, label in APP_PLATFORMS
        ],
        # Supersets. The valid set for a given ad always comes from the ad set's
        # destination entry above; these exist so the editor can label a value it
        # is about to discard during a cascade.
        "call_to_actions": [_opt(c.value) for c in CallToAction],
        "ad_formats": [_opt(f.value) for f in AdFormat],
        "creative_limits": {
            # Two numbers per field. ``*_max`` is the hard ceiling — the editor
            # stops typing there and CreativeSpec rejects past it. ``*_recommended``
            # is Meta's design guidance (the feed's truncation point); the editor
            # shows it as an amber counter and lets the user publish anyway,
            # exactly like Ads Manager does.
            "title_max": CREATIVE_TITLE_MAX,
            "title_recommended": CREATIVE_TITLE_RECOMMENDED,
            "body_max": CREATIVE_BODY_MAX,
            "body_recommended": CREATIVE_BODY_RECOMMENDED,
            "description_max": CREATIVE_DESCRIPTION_MAX,
            "description_recommended": CREATIVE_DESCRIPTION_RECOMMENDED,
            "carousel_min_cards": CAROUSEL_MIN_CARDS,
            "carousel_max_cards": CAROUSEL_MAX_CARDS,
            # Meta's cap on asset_feed_spec titles/bodies — the editor's "add
            # another option" stops here.
            "max_text_variants": CREATIVE_MAX_SUGGESTIONS,
            # How many images/videos one ad may combine before the editor makes
            # the user fan them out into separate ads instead.
            "max_media_per_ad": CREATIVE_MAX_MEDIA,
        },
        "lead_form": {
            "question_types": [_opt(q) for q in LEAD_FORM_QUESTION_TYPES],
            "default_questions": list(LEAD_FORM_DEFAULT_QUESTIONS),
            "candidates": lead_form_candidates or [],
            # Meta rejects a form without a privacy policy URL, so the builder
            # prefills the advertiser's site rather than making them retype it.
            # Publish falls back to the same value (executors/media).
            "privacy_policy_url": (user_info or {}).get("website_url") or None,
            "label_max": LEAD_FORM_LABEL_MAX,
            "max_options": LEAD_FORM_MAX_OPTIONS,
            "intro_title_max": LEAD_FORM_INTRO_TITLE_MAX,
            "max_intro_lines": LEAD_FORM_MAX_INTRO_LINES,
        },
        # The ad account's IANA zone (e.g. "America/Toronto"), or "" when the
        # lookup failed. Meta reads dayparting start/end minutes in THIS zone,
        # not the viewer's, so the editor labels the control with it rather than
        # letting a browser clock imply local time.
        "ad_account_timezone": ad_account_timezone or "",
        # Budget scheduling (Ads Manager's "high demand periods"). Daily budgets
        # only — a lifetime budget uses ad scheduling instead.
        "budget_schedule": {
            "max_multiplier": BUDGET_SCHEDULE_MAX_MULTIPLIER,
            "multiplier_scale": BUDGET_SCHEDULE_MULTIPLIER_SCALE,
            "value_types": [_opt("MULTIPLIER", "Multiple of budget"), _opt("ABSOLUTE", "Fixed amount")],
        },
        # The connected Page. The post picker queries /ads/page-objects with it
        # on demand rather than pre-fetching on every plan render — the user only
        # opens the picker on a boost destination.
        "page_id": page_id,
        # Every Page this token can advertise under: {id, name, instagram, lead_forms}.
        # OAuth stores one Page (whichever Meta listed first), so without this an
        # advertiser managing several brands published under an arbitrary one and
        # only found out from the delivered ad. The editor shows the picker when
        # there is more than one; `page_id` above is the default selection.
        "page_candidates": page_candidates or [],
        # This ad account's real floor, in its own currency's minor units — not
        # USD cents. Meta's minimum daily budget is per-currency (BDT 120 where
        # USD is 1.00), so an editor validating against the static USD constant
        # accepts a budget Meta then rejects at publish. The currency code ships
        # alongside it so the control can label the amount correctly.
        "min_budget_cents": min_budget_cents(user_info or {}),
        "ad_account_currency": (user_info or {}).get("ad_account_currency") or "",
        "pixel_candidates": pixel_candidates or [],
        # What "Create one for me" submits. Shipped rather than hardcoded in React
        # so the editor's picker and the intake form agree on one string — and so
        # an account with no dataset has something to pick instead of a dead
        # "No pixel found" placeholder.
        "create_dataset_value": CREATE_DATASET,
        # How conversions get back to Meta. A campaign-level choice, so the editor
        # renders it in the Campaign panel rather than per ad set.
        "tracking_methods": list(TRACKING_METHODS),
        # Standard pixel conversion events, and the one each objective defaults
        # to. Both used to live as a hardcoded array in the editor — the single
        # place Meta vocabulary had leaked into React.
        "pixel_events": list(PIXEL_EVENTS),
        "default_pixel_event_by_objective": {
            obj.value: event for obj, event in DEFAULT_PIXEL_EVENT.items()
        },
        # The account's custom conversions — rules the advertiser already defined
        # over their dataset ("URL contains /thank-you"). Offered beside the
        # standard events because for an advertiser with the base pixel and no
        # event code, this is the only conversion they can actually optimize for.
        "custom_conversions": [
            {
                "id": str(c["id"]),
                "name": c.get("name") or str(c["id"]),
                "custom_event_type": c.get("custom_event_type") or "",
            }
            for c in (custom_conversions or [])
            if c.get("id")
        ],
        # The audiences already on the ad account, for the ad set's include and
        # exclude pickers. This is what turns a dataset from something Punk only
        # reports into to something it can advertise at: without it the pixel
        # collects visitors nobody can target and converters nobody can exclude.
        # ``usable`` is Meta's own delivery verdict — an audience it calls too
        # small is still listed, because hiding the user's own audience reads as
        # a bug, but it is not silently selectable either.
        "audience_candidates": [
            {
                "id": str(a["id"]),
                "name": a.get("name") or str(a["id"]),
                "subtype": a.get("subtype") or "",
                "size": a.get("size"),
                "usable": bool(a.get("usable", True)),
                "status": a.get("status") or "",
            }
            for a in (audience_candidates or [])
            if a.get("id")
        ],
        # {user_info key: bool} for every prerequisite any destination can ask
        # for, so the editor can warn before publish instead of after.
        "user_info_present": {
            key: _prerequisite_present(user_info or {}, key)
            for key in _PREREQUISITE_KEYS
        },
        # The account's own campaigns, offered as "start from a previous campaign".
        # Applying one is a server round-trip (the overlay reads the old campaign
        # from Meta), so this is just the picker's option list.
        "previous_campaigns": [
            {
                "id": c["id"],
                "name": c.get("name") or c["id"],
                "objective": c.get("objective"),
                "created_time": c.get("created_time"),
            }
            for c in (previous_campaigns or [])
            if c.get("id")
        ],
    }


# A message that opens by naming its own field, e.g.
# "adsets[0].promoted_object.pixel_id is required for …". Every whole-model check
# in models.py writes messages this way (see CampaignSpec._check_*), which is the
# only location information Pydantic gives us for them — see errors_to_form_keys.
#
# An indexed first segment AND a dotted tail are both required, so that ordinary
# English openings ("cards are only accepted on a carousel ad", "set at most one
# of daily_budget or lifetime_budget") are not mistaken for paths, and so that a
# message about a whole ad set ("adsets[0] must not carry a budget under …")
# stays a banner rather than keying to a control that does not exist.
_LEADING_PATH = re.compile(r"^([a-z_0-9]+\[\d+\](?:\.[a-z_0-9]+(?:\[\d+\])?)+)\s")

# The same idea one level down. A model validator on a NESTED model (CreativeSpec,
# AdSetSpec) does get a location from Pydantic — but only as far as the model
# itself, `adsets[0].ads[0].creative`, and the editor addresses controls by their
# field: `creative.format`. So the bare key marked nothing.
#
# Where the rule blames one control, the message says so with a `field: ` opener
# and the field is appended to Pydantic's own key. Explicit rather than "read the
# first word as a field name": a rule that genuinely blames the whole model
# ("several media on one ad works for images only") must keep landing on the
# model, and a sentence opening with an ordinary word would otherwise key to a
# control that does not exist.
_FIELD_PREFIX = re.compile(r"^([a-z_][a-z_0-9]*): ")


def errors_to_form_keys(exc: Exception) -> dict[str, str]:
    """Turn a Pydantic ``ValidationError`` into ``{field_path: message}``.

    Pydantic reports ``('adsets', 0, 'ads', 1, 'creative', 'title')``; the editor
    addresses that as ``adsets[0].ads[1].creative.title``. Whole-model validators
    have no field location, so their message's own leading path is used instead —
    without it a "this ad set needs a Meta Pixel" error renders as a form-level
    banner with nothing marked, and the pixel control the user has to fix shows
    no error at all. Messages that name no field keep landing under ``__root__``
    and stay a banner — where cross-field objective/goal errors belong.
    """
    errors: dict[str, str] = {}
    raw = getattr(exc, "errors", None)
    if not callable(raw):
        return {"__root__": str(exc)}

    for err in raw():
        parts: list[str] = []
        for loc in err.get("loc", ()):
            if isinstance(loc, int):
                if parts:
                    parts[-1] = f"{parts[-1]}[{loc}]"
                else:
                    parts.append(f"[{loc}]")
            else:
                parts.append(str(loc))
        key = ".".join(parts) if parts else "__root__"
        # Pydantic prefixes custom ValueErrors; the raw sentence reads better.
        message = err.get("msg", "invalid value").removeprefix("Value error, ")
        if key == "__root__" and (m := _LEADING_PATH.match(message)):
            key = m.group(1)
        elif key != "__root__" and (m := _FIELD_PREFIX.match(message)):
            key = f"{key}.{m.group(1)}"
            message = message[m.end():]
        errors[key] = message
    return errors


__all__ = ["PIXEL_EVENTS", "build_editor_catalog", "errors_to_form_keys"]


# ── conversion tracking vocabulary ──────────────────────────────
# What "Create one for me" submits. media_select_pixel reads it.
CREATE_DATASET = "__create__"

# Custom-conversion option values are prefixed so one select can offer Meta's
# standard events and the advertiser's own rules side by side — they are the same
# question ("what counts as a conversion?") with two kinds of answer.
CUSTOM_CONVERSION_PREFIX = "cc:"

# How conversions get back to Meta. Not cosmetic: it decides whether Punk hands
# over an install snippet, whether it mints a server ingest key, and whether a
# dataset that has never fired is worth warning about — a CRM upload never fires a
# browser event, so that warning is permanent and wrong for it. Read by
# TrackingService.snippet / .health and by the publish gate.
TRACKING_METHODS: list[dict[str, str]] = [
    {
        "value": "pixel_only",
        "label": "Website pixel only (recommended)",
        "description": (
            "The browser tag talks straight to Meta and nothing about your "
            "customers reaches Punk. Simplest to install; ad blockers and iOS "
            "opt-outs will cost you some conversions."
        ),
    },
    {
        "value": "pixel_and_server",
        "label": "Website pixel + server events",
        "description": (
            "Adds the conversions the browser loses: your server reports what "
            "actually happened. Those reports are posted through Punk, which "
            "forwards them to your dataset — or straight to Meta, if you would "
            "rather we never saw them."
        ),
    },
    {
        "value": "lead_forms",
        "label": "Instant form leads",
        "description": (
            "People fill the form inside Facebook or Instagram. Nothing to install "
            "on your site. Meta pushes each lead to Punk, which reports it back as "
            "a conversion using Meta's own lead id — no names or emails involved."
        ),
    },
    {
        "value": "offline_crm",
        "label": "Offline / CRM",
        "description": (
            "Sales close on the phone or in person and your CRM sends them back "
            "through Punk."
        ),
    },
]
