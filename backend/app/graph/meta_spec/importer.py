"""
graph/meta_spec/importer.py
───────────────────────────
Turn a campaign that already exists on the ad account into a reusable template.

A returning advertiser rebuilds their whole setup every run: same objective, same
optimization goal, same bidding, often the same creative — all re-answered from
scratch after the audience is built. This reads one of their existing campaigns
and keeps the parts worth reusing.

**The audience is never one of them.** Targeting, custom audiences and budgets are
deliberately dropped: the freshly discovered POIs and the MAID seed/lookalike
built this run are the whole reason for the campaign, and reusing an old audience
would skip the product. What the template carries is the *shape* of the campaign
around that audience.

The template is applied by ``builder.apply_campaign_template``, which overlays it
onto the tree ``build_campaign_spec`` has already assembled from this session's
targeting — so the new audience cannot be clobbered by construction.

Nothing here validates. An imported campaign can legally exist on Meta and still
be a combination our matrix does not model (Meta accepts things we do not offer,
and accounts differ). Those surface as field-level errors in the plan editor via
the existing invalid-edit route, not as an exception here.
"""

from __future__ import annotations

import logging
from typing import Any

from app.graph.meta_spec.enums import normalize_objective

logger = logging.getLogger(__name__)

# promoted_object keys PromotedObject models. Anything else Meta returns (a
# product set, a place page set) belongs to a campaign shape we do not build, so
# it is dropped and reported rather than silently carried into a spec that would
# reject it.
_PROMOTED_OBJECT_KEYS = frozenset({
    "pixel_id", "custom_event_type", "page_id", "application_id", "object_store_url",
})

# Ad set fields reused verbatim. Budgets, schedule, targeting and status are
# absent on purpose — see the module docstring.
_ADSET_TEMPLATE_KEYS = (
    "destination_type",
    "optimization_goal",
    "billing_event",
    "bid_strategy",
    "bid_amount",
    "bid_constraints",
    "attribution_spec",
    "frequency_control_specs",
)


class TemplateImportError(ValueError):
    """The campaign cannot be used as a starting point at all.

    Distinct from the notes list, which reports parts that were dropped from an
    otherwise usable template.
    """


def select_tree_subset(
    tree: dict,
    adset_ids: list[str] | None = None,
    ad_ids: list[str] | None = None,
) -> dict:
    """A ``fetch_campaign_tree`` result narrowed to the ad sets / ads the user ticked.

    ``None`` means "no filter" — the whole campaign. That is both the behaviour
    from before the picker existed (so an older frontend keeps working) and the
    fallback when the picker could not read the tree.

    An **empty list** is not the same thing: it means the picker was used and
    nothing was ticked at that level. The distinction is the whole reason these
    are ``None``-defaulted rather than ``[]``-defaulted — unticking every ad under
    a ticked ad set has to copy zero ads, not all of them.

    An ad set ticked with *none* of its ads is not a degenerate case: it comes out
    with ``ads: []``, ``_adset_template`` then emits no ``creatives`` key, and the
    overlay copies that ad set's settings while leaving this run's generated copy
    alone. "Same targeting settings, my own copy" is a real thing to want.
    """
    adsets = tree.get("adsets") or []
    if adset_ids is not None:
        keep = {str(i) for i in adset_ids}
        adsets = [a for a in adsets if str(a.get("id")) in keep]
    if ad_ids is not None:
        keep_ads = {str(i) for i in ad_ids}
        adsets = [
            {**a, "ads": [ad for ad in (a.get("ads") or []) if str(ad.get("id")) in keep_ads]}
            for a in adsets
        ]
    return {**tree, "adsets": adsets}


def campaign_template(tree: dict) -> tuple[dict[str, Any], list[str]]:
    """``(template, notes)`` from a ``meta_ads.fetch_campaign_tree`` result.

    ``notes`` is user-facing: everything the template could not carry, so the
    plan says what changed instead of quietly differing from the campaign the
    user picked.
    """
    campaign = tree.get("campaign") or {}
    notes: list[str] = []

    objective = normalize_objective(campaign.get("objective"))
    if objective is None:
        # Pre-2022 objectives (LINK_CLICKS, CONVERSIONS, VIDEO_VIEWS) still exist
        # on old campaigns but Meta refuses them for new ones, so there is
        # nothing to copy them into.
        raise TemplateImportError(
            f"{campaign.get('name') or 'That campaign'} uses "
            f"{campaign.get('objective') or 'an older objective'}, which Meta no "
            "longer accepts for new campaigns. Pick a newer campaign, or set this "
            "one up fresh."
        )

    template: dict[str, Any] = {
        "objective": objective.value,
        "adsets": [
            _adset_template(a, notes, campaign.get("bid_strategy"))
            for a in (tree.get("adsets") or [])
        ],
    }

    if campaign.get("bid_strategy"):
        template["bid_strategy"] = campaign["bid_strategy"]

    # A regulated campaign stays regulated: carrying the declaration forward is
    # safer than making the user remember to re-tick it.
    categories = campaign.get("special_ad_categories") or []
    if categories:
        template["special_ad_categories"] = list(categories)
        country = campaign.get("special_ad_category_country") or []
        if country:
            template["special_ad_category_country"] = list(country)

    if not template["adsets"]:
        raise TemplateImportError(
            f"{campaign.get('name') or 'That campaign'} has no ad sets to copy "
            "settings from."
        )

    return template, notes


def _adset_template(
    adset: dict, notes: list[str], campaign_bid_strategy: str | None = None
) -> dict[str, Any]:
    """One ad set's reusable settings, plus its ads' creatives."""
    out: dict[str, Any] = {
        key: adset[key] for key in _ADSET_TEMPLATE_KEYS if adset.get(key) is not None
    }

    # Under campaign budget optimization Meta keeps the strategy on the campaign
    # and returns nothing on the ad set, so an ad set can come back carrying a
    # bid_amount with no strategy to justify it. AdSetSpec rejects that pair, so
    # inherit the campaign's rather than importing a contradiction.
    if (out.get("bid_amount") or out.get("bid_constraints")) and not out.get("bid_strategy"):
        if campaign_bid_strategy:
            out["bid_strategy"] = campaign_bid_strategy
        else:
            out.pop("bid_amount", None)
            out.pop("bid_constraints", None)
            notes.append(
                f"{adset.get('name') or 'An ad set'} had a bid amount with no bid "
                "strategy on it — that part wasn't copied."
            )

    promoted = adset.get("promoted_object") or {}
    if promoted:
        kept = {k: v for k, v in promoted.items() if k in _PROMOTED_OBJECT_KEYS}
        dropped = sorted(set(promoted) - _PROMOTED_OBJECT_KEYS)
        if dropped:
            notes.append(
                f"{adset.get('name') or 'An ad set'} promotes something we don't "
                f"build yet ({', '.join(dropped)}) — that part wasn't copied."
            )
        if kept:
            out["promoted_object"] = kept

    creatives = [
        c for c in (_creative_template(ad, notes) for ad in (adset.get("ads") or []))
        if c
    ]
    if creatives:
        out["creatives"] = creatives
    return out


def _creative_template(ad: dict, notes: list[str]) -> dict[str, Any] | None:
    """One ad's copy and media, read back off its creative.

    Media comes across **by reference**: ``image_hash`` and ``video_id`` are
    account-level and permanent, so the old ad's assets are reused with no
    download and no re-upload. ``CreativeSpec`` derives ``media_kind`` from
    whichever is set, which is what keeps a video-only goal valid.

    The creative's ``thumbnail_url`` is deliberately NOT carried: ``media_url`` is
    a client-only preview the editor strips on submit, and ``CreativeSpec`` is
    ``extra="forbid"``, so writing it here makes the plan unvalidatable. No plan
    keeps its preview across a server round trip today, imported or not.
    """
    creative = ad.get("creative") or {}
    if not creative:
        return None

    # A boosted post is the whole ad — there is no composed copy to read.
    if creative.get("source_instagram_media_id"):
        return {
            "source_instagram_media_id": str(creative["source_instagram_media_id"])
        }
    if creative.get("object_story_id"):
        return {"object_story_id": str(creative["object_story_id"])}

    story = creative.get("object_story_spec") or {}
    link_data = story.get("link_data") or {}
    video_data = story.get("video_data") or {}
    source = link_data or video_data
    if not source:
        # No composed copy anywhere — but the ad clearly runs something, so it runs
        # a post. ``effective_object_story_id`` is the only field that names it:
        # an ad built from an inline unpublished post has a null
        # ``object_story_id``, which is the common shape for an ad created in Ads
        # Manager. Checked HERE rather than beside object_story_id above because
        # every ad has an effective id, including the ordinary composed ones — using
        # it earlier would turn "copy this campaign's copy" into "promote its posts"
        # for every template.
        effective = creative.get("effective_object_story_id")
        if effective:
            return {"object_story_id": str(effective)}
        return None

    out: dict[str, Any] = {}
    # Meta names the headline `name` on link data and `title` on video data.
    title = source.get("name") or source.get("title")
    if title:
        out["title"] = title
    if source.get("message"):
        out["body"] = source["message"]
    if creative.get("url_tags"):
        out["url_tags"] = creative["url_tags"]

    cta = (source.get("call_to_action") or {}).get("type")
    if cta:
        out["call_to_action"] = cta

    if link_data.get("child_attachments"):
        # A carousel's media lives per card, and the cards' links point at the old
        # campaign's destination. Copying the copy is useful; copying the cards
        # wholesale would carry stale links into a new campaign.
        out["format"] = "CAROUSEL"
        notes.append(
            "The previous ad was a carousel — its copy was copied, but you'll "
            "need to re-add the cards."
        )
        return out

    out["format"] = "SINGLE"
    if video_data.get("video_id"):
        out["video_id"] = str(video_data["video_id"])
    elif link_data.get("image_hash"):
        out["image_hash"] = str(link_data["image_hash"])
    return out


__all__ = ["TemplateImportError", "campaign_template", "select_tree_subset"]
