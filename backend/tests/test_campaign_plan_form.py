"""
tests/test_campaign_plan_form.py
────────────────────────────────
The campaign editor contract: the option catalog the bespoke editor renders its
dropdowns from, the field-keyed validation errors, and the nested ad structure.

The invariant these tests protect is that **no Meta rule leaks into the
frontend** — every option list, limit and per-objective constraint travels in
the catalog, derived from the objective matrix.
"""
from __future__ import annotations

import asyncio
import copy

import pytest
from pydantic import ValidationError

from app.graph.builder.builder_node import _apply_plan_form_submission
from app.graph.meta_spec import (
    CampaignSpec,
    build_editor_catalog,
    errors_to_form_keys,
)
from app.graph.meta_spec.builder import build_campaign_spec, build_campaign_tree
from app.graph.meta_spec.enums import (
    CREATIVE_BODY_MAX,
    CREATIVE_BODY_RECOMMENDED,
    CREATIVE_TITLE_MAX,
    CREATIVE_TITLE_RECOMMENDED,
    Objective,
)

SEED = {"geo_locations": {"cities": [{"name": "Toronto"}]}}
BROAD = {"geo_locations": {"cities": [{"name": "Toronto"}]}}

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
    "campaign_name": "Bean There — Summer",
    "adset_budget_breakdown": [
        {"adset_name": "Visitors", "budget_pct": 70, "audience_type": "primary"},
        {"adset_name": "Prospecting", "budget_pct": 30, "audience_type": "lookalike"},
    ],
    "headline_suggestions": ["Fresh roast, daily"],
    "body_copy_suggestions": ["Come taste the difference."],
    "cta_recommendation": "LEARN_MORE",
}


def _spec(**overrides) -> CampaignSpec:
    params = dict(
        user_info=dict(USER_INFO),
        geo_data={"maid_count": 12000},
        brief=dict(BRIEF),
        seed_targeting=dict(SEED),
        broad_targeting=dict(BROAD),
        lookalike_targeting=dict(BROAD),
        page_id="pg1",
    )
    params.update(overrides)
    return build_campaign_spec(**params)


# ── nested ad structure (Ads-Manager shape) ─────────────────────────────────────


def test_spec_nests_one_ad_per_adset_by_default():
    spec = _spec()
    assert len(spec.adsets) == 2
    for adset in spec.adsets:
        assert len(adset.ads) == 1
        assert adset.ads[0].creative.title


def test_multiple_ads_per_adset_validate():
    spec = _spec()
    tree = spec.model_dump(mode="json")
    first = tree["adsets"][0]
    extra_ad = dict(first["ads"][0])
    extra_ad = {**extra_ad, "name": "Second ad"}
    extra_ad["creative"] = {**first["ads"][0]["creative"], "title": "Another headline"}
    first["ads"].append(extra_ad)
    # A second ad with its own creative is accepted.
    rebuilt = CampaignSpec.model_validate(tree)
    assert len(rebuilt.adsets[0].ads) == 2
    assert rebuilt.adsets[0].ads[1].creative.title == "Another headline"


# ── catalog: objective-scoped option lists ──────────────────────────────────────


def _dests(cat, objective):
    """{destination_value: entry} for one objective."""
    return {d["value"]: d for d in cat["destinations_by_objective"][objective.value]}


def test_catalog_option_lists_hang_off_the_destination_not_the_objective():
    """Meta's form is objective x conversion location. Flat per-objective lists
    let the editor offer a goal that was legal for the objective and rejected for
    the destination the user actually picked."""
    cat = build_editor_catalog(Objective.LEADS)
    leads = _dests(cat, Objective.LEADS)

    on_ad = {o["value"] for o in leads["ON_AD"]["optimization_goals"]}
    website = {o["value"] for o in leads["WEBSITE"]["optimization_goals"]}

    assert "LEAD_GENERATION" in on_ad
    # The pair that used to ship as the default.
    assert "LEAD_GENERATION" not in website
    assert "OFFSITE_CONVERSIONS" in website


def test_catalog_ships_every_objective_for_local_switching():
    """Switching objective must re-render dependent selects without a round trip,
    so the whole map travels in one payload."""
    cat = build_editor_catalog()
    by_obj = cat["destinations_by_objective"]
    assert set(by_obj) == {o.value for o in Objective}
    app_goals = {
        o["value"]
        for d in by_obj[Objective.APP_PROMOTION.value]
        for o in d["optimization_goals"]
    }
    assert "APP_INSTALLS" in app_goals


def test_catalog_reports_which_prerequisites_the_run_actually_has():
    """The destination lists say what a conversion location needs; without knowing
    what was collected, the editor can only find out at publish — after the user
    has left it."""
    cat = build_editor_catalog(user_info={"website_url": "https://beanthere.example"})
    assert cat["user_info_present"]["website_url"] is True
    assert cat["user_info_present"]["app_store_url"] is False

    # Either store link satisfies the app requirement, as the intake form's own
    # validation treats it.
    play_only = build_editor_catalog(user_info={"play_store_url": "https://play.example"})
    assert play_only["user_info_present"]["app_store_url"] is True


def test_catalog_owns_the_pixel_event_vocabulary():
    """The event list used to be a hardcoded array in the editor — the one place
    Meta vocabulary had leaked into React."""
    cat = build_editor_catalog(Objective.SALES)
    assert "PURCHASE" in cat["pixel_events"]
    assert cat["default_pixel_event_by_objective"][Objective.SALES.value] == "PURCHASE"
    assert cat["default_pixel_event_by_objective"][Objective.LEADS.value] == "LEAD"


def test_catalog_cta_options_are_destination_scoped():
    cat = build_editor_catalog()
    traffic_web = {
        o["value"] for o in _dests(cat, Objective.TRAFFIC)["WEBSITE"]["call_to_actions"]
    }
    app = {
        o["value"] for o in _dests(cat, Objective.APP_PROMOTION)["APP"]["call_to_actions"]
    }
    assert "LEARN_MORE" in traffic_web
    assert "INSTALL_MOBILE_APP" in app
    assert "INSTALL_MOBILE_APP" not in traffic_web


def test_catalog_destinations_differ_by_objective():
    cat = build_editor_catalog()
    assert set(_dests(cat, Objective.APP_PROMOTION)) == {"APP"}
    assert "ON_AD" in _dests(cat, Objective.LEADS)
    assert "ON_AD" not in _dests(cat, Objective.SALES)


def test_catalog_promoted_object_kind_flags_pixel_goals():
    """The editor uses this to warn a conversion goal needs a pixel before publish."""
    website = _dests(build_editor_catalog(), Objective.SALES)["WEBSITE"]
    assert website["promoted_object_kind_by_goal"]["OFFSITE_CONVERSIONS"] == "pixel"


def test_catalog_flags_the_instant_form_requirement():
    leads = _dests(build_editor_catalog(), Objective.LEADS)
    assert leads["ON_AD"]["requires_lead_form"] is True
    assert leads["WEBSITE"]["requires_lead_form"] is False


def test_catalog_ships_the_instant_form_builder_vocabulary():
    """The editor builds a form from this — question types, the limits it must
    enforce, and the privacy URL Meta refuses a form without."""
    lf = build_editor_catalog(user_info={"website_url": "https://beanthere.example"})["lead_form"]
    assert {o["value"] for o in lf["question_types"]} >= {"FULL_NAME", "EMAIL", "PHONE"}
    assert lf["default_questions"] == ["FULL_NAME", "EMAIL", "PHONE"]
    assert lf["privacy_policy_url"] == "https://beanthere.example"
    assert lf["intro_title_max"] > 0 and lf["max_options"] > 0
    # No site on the run → no prefill, and the builder asks for one.
    assert build_editor_catalog()["lead_form"]["privacy_policy_url"] is None


# ── instant form drafts ──────────────────────────────────────────────────────


def _leads_spec_tree(draft: dict | None) -> dict:
    tree = _spec(
        user_info={**USER_INFO, "campaign_objective": "LEADS"}
    ).model_dump(mode="json")
    if draft is not None:
        tree["adsets"][0]["lead_form_draft"] = draft
    return tree


_DRAFT = {
    "name": "Quote request",
    "questions": [{"type": "EMAIL"}],
    "privacy_policy_url": "https://beanthere.example/privacy",
}


def test_lead_form_draft_validates_on_an_instant_form_adset():
    spec = CampaignSpec.model_validate(_leads_spec_tree(_DRAFT))
    assert spec.adsets[0].lead_form_draft.name == "Quote request"


def test_lead_form_draft_is_rejected_when_the_destination_has_no_form():
    tree = _leads_spec_tree(_DRAFT)
    for adset in tree["adsets"]:
        adset["destination_type"] = "WEBSITE"
        adset["optimization_goal"] = "LINK_CLICKS"
        adset["promoted_object"] = None
    with pytest.raises(ValidationError, match="only used when the conversion location"):
        CampaignSpec.model_validate(tree)


def test_a_draft_and_an_existing_form_id_cannot_both_be_set():
    """Two answers to "which form do these ads submit to?" cannot be resolved at
    publish without guessing, so it is a form error while the user can still fix it."""
    tree = _leads_spec_tree(_DRAFT)
    tree["adsets"][0]["ads"][0]["creative"]["lead_gen_form_id"] = "form-9"
    with pytest.raises(ValidationError, match="pick one form"):
        CampaignSpec.model_validate(tree)


def test_a_custom_question_needs_a_label_and_a_known_type_does_not():
    tree = _leads_spec_tree({**_DRAFT, "questions": [{"type": "CUSTOM"}]})
    with pytest.raises(ValidationError, match="needs a label"):
        CampaignSpec.model_validate(tree)

    tree = _leads_spec_tree({**_DRAFT, "questions": [{"type": "FAVOURITE_COLOUR"}]})
    with pytest.raises(ValidationError, match="unknown lead form question type"):
        CampaignSpec.model_validate(tree)


def test_lead_form_draft_never_reaches_the_meta_adset_payload():
    """It instructs publish to create a form; Meta's ad set endpoint would reject
    the unknown field."""
    spec = CampaignSpec.model_validate(_leads_spec_tree(_DRAFT))
    payload = spec.adsets[0].to_payload(campaign_id="c1", ad_account_id="act_1")
    assert "lead_form_draft" not in payload


def test_catalog_ad_formats_are_destination_scoped():
    cat = build_editor_catalog()
    sales = _dests(cat, Objective.SALES)
    messenger = {o["value"] for o in sales["MESSENGER"]["ad_formats"]}
    website = {o["value"] for o in sales["WEBSITE"]["ad_formats"]}
    assert messenger == {"SINGLE"}            # a messaging ad renders one card
    assert website == {"SINGLE", "CAROUSEL"}


def test_shop_destination_is_not_offered():
    """Shops ads need a product catalog and set on the promoted object, and Meta
    documents their parent objective as one retired for new ODAX campaigns — so
    the option could be picked but never published."""
    cat = build_editor_catalog()
    for objective, dests in cat["destinations_by_objective"].items():
        assert "SHOP_AUTOMATIC" not in {d["value"] for d in dests}, objective


def test_catalog_labels_use_meta_wording():
    """"Offsite Conversions" is not a phrase that appears in Ads Manager."""
    cat = build_editor_catalog()
    leads = _dests(cat, Objective.LEADS)
    assert leads["ON_AD"]["label"] == "Instant forms"
    website_goals = {o["value"]: o["label"] for o in leads["WEBSITE"]["optimization_goals"]}
    assert website_goals["OFFSITE_CONVERSIONS"] == "Conversions"


# ── catalog: limits, floor, vocabulary ──────────────────────────────────────────


def test_catalog_carries_creative_limits():
    """The editor needs both numbers: the ceiling it stops typing at, and the
    recommendation its counter measures against."""
    cat = build_editor_catalog()["creative_limits"]
    assert cat["title_max"] == CREATIVE_TITLE_MAX
    assert cat["body_max"] == CREATIVE_BODY_MAX
    assert cat["title_recommended"] == CREATIVE_TITLE_RECOMMENDED
    assert cat["body_recommended"] == CREATIVE_BODY_RECOMMENDED
    # A recommendation at or above the ceiling would make the counter a wall.
    assert cat["title_recommended"] < cat["title_max"]
    assert cat["body_recommended"] < cat["body_max"]
    assert cat["description_recommended"] < cat["description_max"]


def test_catalog_carries_metas_budget_floor():
    assert build_editor_catalog()["min_budget_cents"] >= 100


def test_catalog_placements_vocabulary():
    cat = build_editor_catalog()
    platforms = {o["value"] for o in cat["placements"]["publisher_platforms"]}
    assert {"facebook", "instagram"} <= platforms
    # Positions available per platform for manual placement.
    assert "instagram" in cat["placements"]["positions"]


def test_catalog_genders_and_special_categories():
    cat = build_editor_catalog()
    assert {o["value"] for o in cat["genders"]} == {"all", "male", "female"}
    cats = {o["value"] for o in cat["special_ad_categories"]}
    assert "EMPLOYMENT" in cats
    assert "EMPLOYMENT" in cat["categories_blocking_demographics"]


def test_catalog_ships_every_country_the_spec_will_accept():
    """The country list used to be a six-entry const in CampaignEditor.tsx, which
    left an advertiser outside those markets unable to declare at all."""
    codes = build_editor_catalog()["special_ad_category_countries"]
    assert codes[:2] == ["US", "CA"]           # Punk's markets first
    assert len(codes) > 200                    # not the old six
    assert len(set(codes)) == len(codes)       # no duplicates
    # Every offered code must survive CampaignSpec's own validator.
    assert all(len(c) == 2 and c.isalpha() and c.isupper() for c in codes)


def test_catalog_pixel_candidates_pass_through():
    cat = build_editor_catalog(
        Objective.SALES,
        pixel_candidates=[{"id": "123", "name": "Main"}, {"id": "456", "name": "Backup"}],
    )
    assert [p["id"] for p in cat["pixel_candidates"]] == ["123", "456"]


def test_catalog_ships_every_page_the_user_can_publish_as():
    """OAuth stores one Page and Meta does not order /me/accounts meaningfully, so
    without the full list an advertiser running several brands publishes under an
    arbitrary one and only finds out from the delivered ad."""
    pages = [
        {"id": "pg_1", "name": "Bean There", "instagram": {"id": "ig_77", "username": "bt"}},
        {"id": "pg_2", "name": "Bean There Roasters", "instagram": None},
    ]
    cat = build_editor_catalog(Objective.ENGAGEMENT, page_id="pg_1", page_candidates=pages)
    assert [p["id"] for p in cat["page_candidates"]] == ["pg_1", "pg_2"]
    # The stored Page stays the default selection.
    assert cat["page_id"] == "pg_1"


def test_whatsapp_no_longer_demands_a_typed_phone_number():
    """Click-to-WhatsApp reads the number off the promoted Page. The old
    prerequisite was unsatisfiable — nothing in the app ever collected it."""
    cat = build_editor_catalog(Objective.TRAFFIC, user_info={})
    assert "whatsapp_number" not in cat["user_info_present"]


# ── errors keyed by nested field path ───────────────────────────────────────────


def test_errors_map_to_nested_ad_paths():
    """A rejected edit surfaces under the exact editor path so the field lights up."""
    spec = _spec()
    tree = spec.model_dump(mode="json")
    # Past CREATIVE_TITLE_MAX — not merely past the 40-char recommendation,
    # which is guidance the editor flags rather than an error.
    tree["adsets"][0]["ads"][0]["creative"]["title"] = "x" * (CREATIVE_TITLE_MAX + 1)
    with pytest.raises(ValidationError) as exc_info:
        CampaignSpec.model_validate(tree)
    keys = errors_to_form_keys(exc_info.value)
    assert "adsets[0].ads[0].creative.title" in keys


def test_cross_field_errors_are_anchored_by_the_message_they_carry():
    """Whole-model validators get no loc from Pydantic, but they write their own
    field path into the message. That path is the key, so an illegal goal marks
    the goal select rather than only raising a form-level banner."""
    spec = _spec()
    tree = spec.model_dump(mode="json")
    tree["adsets"][0]["optimization_goal"] = "APP_INSTALLS"   # invalid for TRAFFIC
    with pytest.raises(ValidationError) as exc_info:
        CampaignSpec.model_validate(tree)
    keys = errors_to_form_keys(exc_info.value)
    assert "adsets[0].optimization_goal" in keys


def test_a_capped_bid_marks_the_ad_set_that_is_actually_missing_an_amount():
    """The message named the strategy, never the ad set or the box, and landed on
    the bare `adsets[1]` key — a page banner. A user who had typed an amount on
    the FIRST ad set read it as being told they had not."""
    tree = _spec().model_dump(mode="json")
    for adset in tree["adsets"]:
        adset["bid_strategy"] = "LOWEST_COST_WITH_BID_CAP"
    tree["adsets"][0]["bid_amount"] = 1000
    tree["adsets"][1]["bid_amount"] = None

    with pytest.raises(ValidationError) as exc_info:
        CampaignSpec.model_validate(tree)
    keys = errors_to_form_keys(exc_info.value)

    assert "adsets[1].bid_amount" in keys
    assert "adsets[1]" not in keys
    assert "adsets[0].bid_amount" not in keys


def test_the_rule_fires_when_bid_amount_is_absent_not_only_null():
    """A field validator is skipped for a value that fell back to its default, so
    without validate_default an omitted key walked straight past the check the
    model validator used to catch."""
    tree = _spec().model_dump(mode="json")
    tree["adsets"][1]["bid_strategy"] = "LOWEST_COST_WITH_BID_CAP"
    tree["adsets"][1].pop("bid_amount", None)

    with pytest.raises(ValidationError) as exc_info:
        CampaignSpec.model_validate(tree)
    assert "adsets[1].bid_amount" in errors_to_form_keys(exc_info.value)


def test_a_lifetime_budget_without_an_end_marks_the_end_date():
    tree = _spec().model_dump(mode="json")
    adset = tree["adsets"][0]
    adset["daily_budget"] = None
    adset["lifetime_budget"] = 50000
    adset["end_time"] = None

    with pytest.raises(ValidationError) as exc_info:
        CampaignSpec.model_validate(tree)
    assert "adsets[0].end_time" in errors_to_form_keys(exc_info.value)


def test_two_budgets_on_one_ad_set_stay_keyed_to_the_ad_set():
    """Two fields at fault, so there is no single control to mark."""
    tree = _spec().model_dump(mode="json")
    adset = tree["adsets"][0]
    adset["daily_budget"] = 50000
    adset["lifetime_budget"] = 50000
    adset["end_time"] = "2030-01-01T00:00:00+00:00"

    with pytest.raises(ValidationError) as exc_info:
        CampaignSpec.model_validate(tree)
    assert "adsets[0]" in errors_to_form_keys(exc_info.value)


def test_a_creative_rule_marks_the_control_it_blames():
    """A model validator on a NESTED model does get a loc, but only as far as the
    model — `adsets[0].ads[0].creative`, which no control is named after. The
    format toggle is what the user has to change, so that is what gets marked."""
    tree = _spec().model_dump(mode="json")
    tree["adsets"][0]["ads"][0]["creative"]["format"] = "CAROUSEL"   # with no cards

    with pytest.raises(ValidationError) as exc_info:
        CampaignSpec.model_validate(tree)
    keys = errors_to_form_keys(exc_info.value)

    assert "adsets[0].ads[0].creative.format" in keys
    assert "adsets[0].ads[0].creative" not in keys
    # The `field: ` opener is addressing, not copy — it never reaches the user.
    assert not keys["adsets[0].ads[0].creative.format"].startswith("format:")


def test_a_message_naming_no_field_still_lands_on_root():
    """The fallback the editor renders as a banner is still reachable."""
    class _Boom(Exception):
        pass

    assert errors_to_form_keys(_Boom("something went wrong")) == {
        "__root__": "something went wrong"
    }


# ── the pixel is asked here, and nowhere else ────────────────────────────────


def test_a_conversion_plan_with_no_pixel_reaches_the_editor():
    """A conversion goal whose pixel id never arrived no longer kills the run
    (SpecBuildError) and no longer triggers a standalone interrupt: the tree
    builds, fails validation, and the editor opens on it with the error — which
    is where the account's pixels are the options.

    ``has_warm_dataset`` is what puts this run on a conversion goal at all: an
    account with no dataset gets LANDING_PAGE_VIEWS, which promotes nothing and
    never reaches this editor state."""
    tree = build_campaign_tree(
        user_info={
            **USER_INFO, "campaign_objective": "SALES", "has_warm_dataset": True,
        },
        geo_data={"maid_count": 12000},
        brief=dict(BRIEF),
        seed_targeting=dict(SEED),
        broad_targeting=dict(BROAD),
        lookalike_targeting=dict(BROAD),
        page_id="pg1",
    )
    assert tree["objective"] == "OUTCOME_SALES"          # never downgraded
    with pytest.raises(ValidationError) as exc_info:
        CampaignSpec.model_validate(tree)
    # Keyed to the control the editor renders the account's pixels in, so the
    # select itself carries the error instead of only a form-level banner.
    assert "adsets[0].promoted_object.pixel_id" in errors_to_form_keys(exc_info.value)

    # The editor payload is the invalid tree itself, plus the errors and the
    # account's (here empty) pixel options.
    from app.graph.builder.builder_node import _plan_form_extra

    bs = {
        "marketing_plan_draft": tree,
        "plan_errors": errors_to_form_keys(exc_info.value),
        "media_ws": {"pixel_candidates": [{"id": "123", "name": "Main"}]},
    }
    extra = asyncio.run(_plan_form_extra(bs, {"user_info": {}}))
    # Equal to the draft, but not the same object: the payload is a copy so the
    # image-preview hydration cannot plant media_url in stored state.
    assert extra["spec"] == tree
    assert "adsets[0].promoted_object.pixel_id" in extra["errors"]
    assert extra["catalog"]["pixel_candidates"] == [{"id": "123", "name": "Main"}]


# ── the editor submission seam ─────────────────────────────────────────────────
# The editor posts the WHOLE spec and it lands straight in
# CampaignSpec.model_validate — there is no mapping layer. Combined with
# extra="forbid", a client-only key is not ignored, it rejects the entire plan.
# Nothing exercised that seam with a realistic payload, which is how a carousel
# shipped unpublishable.


def _submission_spec() -> dict:
    """What the editor actually posts: a two-ad-set plan whose second ad is a
    carousel with per-card media, as CarouselCards + CardMediaButton build it."""
    plan = _spec().model_dump(mode="json")
    ad = plan["adsets"][0]["ads"][0]
    ad["creative"].update({
        "format": "CAROUSEL",
        "media_id": None,
        "image_hash": None,
        "video_id": None,
        "media_kind": None,
        "cards": [
            {
                "title": f"Card {i}",
                "body": f"desc {i}",
                "link": "https://beanthere.example",
                "media_id": f"media-{i}",
                "image_hash": None,
                "video_id": None,
                "media_kind": "image",
            }
            for i in (1, 2)
        ],
    })
    return plan


def test_a_carousel_submission_validates_once_previews_are_stripped():
    """The happy path the client is responsible for producing."""
    CampaignSpec.model_validate(_submission_spec())


def test_a_client_only_preview_on_a_card_rejects_the_whole_plan():
    """Why the client MUST strip it, and why the failure is so unhelpful: the
    error keys a field the editor renders no input for, so the user sees the plan
    bounce with nothing to fix."""
    plan = _submission_spec()
    plan["adsets"][0]["ads"][0]["creative"]["cards"][0]["media_url"] = "https://r2/x.png"

    with pytest.raises(ValidationError) as exc_info:
        CampaignSpec.model_validate(plan)
    assert (
        "adsets[0].ads[0].creative.cards[0].media_url"
        in errors_to_form_keys(exc_info.value)
    )


def test_deleting_an_adset_does_not_promote_another_one_to_seed():
    """audience_role is restored from the stored plan, and it used to be matched
    by list index. Deleting the seed ad set shifted the survivor into index 0 and
    silently made it the seed — so publish attached the MAID custom audience to an
    ad set the user never chose."""
    from app.graph.builder.builder_node import _restore_locked_targeting

    prior = _spec().model_dump(mode="json")
    assert prior["adsets"][0]["audience_role"] == "seed"
    prospecting_name = prior["adsets"][1]["name"]

    # The user deleted the seed ad set in the editor.
    submitted = {**prior, "adsets": [dict(prior["adsets"][1])]}
    _restore_locked_targeting(submitted, prior)

    assert submitted["adsets"][0]["name"] == prospecting_name
    assert submitted["adsets"][0]["audience_role"] != "seed"
    # Geo is still restored — it is the same zip set for every ad set.
    assert submitted["adsets"][0]["targeting"]["geo_locations"]


def test_a_renamed_adset_keeps_the_role_the_client_sent():
    """No prior ad set to match means new-or-renamed. The editor creates ad sets
    broad, and inventing a role for one would re-create the bug above."""
    from app.graph.builder.builder_node import _restore_locked_targeting

    prior = _spec().model_dump(mode="json")
    submitted = {**prior, "adsets": [
        {**prior["adsets"][0], "name": "Renamed", "audience_role": "broad"}
    ]}
    _restore_locked_targeting(submitted, prior)
    assert submitted["adsets"][0]["audience_role"] == "broad"


def test_an_unchanged_adset_still_has_its_locked_role_restored():
    """The lock still works: a client that drops or edits audience_role on an ad
    set that exists in the stored plan gets the stored value back."""
    from app.graph.builder.builder_node import _restore_locked_targeting

    prior = _spec().model_dump(mode="json")
    submitted = {**prior, "adsets": [
        {**prior["adsets"][0], "audience_role": "broad", "targeting": {}}
    ]}
    _restore_locked_targeting(submitted, prior)
    assert submitted["adsets"][0]["audience_role"] == "seed"
    assert submitted["adsets"][0]["targeting"]["geo_locations"]


# ── a resubmitted plan invalidates the resume ledger ──────────────────────────


def _submit(prior: dict, edited: dict, **bs_extra) -> dict:
    from app.graph.builder.builder_node import _apply_plan_form_submission

    bs = {"filled": {}, "marketing_plan": prior, **bs_extra}
    _apply_plan_form_submission(bs, {"action": "publish", "spec": edited})
    return bs


def test_an_edited_plan_marks_the_publish_ledger_stale():
    """Every publish failure reopens this editor, and the ledger from the failed
    attempt still holds the campaign built from the OLD plan. Without this flag
    the retry resumes those objects and the edit never runs."""
    prior = _spec().model_dump(mode="json")
    edited = {**prior, "name": "Renamed campaign"}
    assert _submit(prior, edited).get("publish_plan_dirty") is True


# ── express re-lock: the `unlocked` flag is two-way ────────────────────────────
#
# Express hides the campaign/ad-set panes behind a single ad-set-0 card unless
# the user hits "Unlock & edit". The flag used to only ever go one way
# (submission.get("unlocked") -> True, checked with `if`), so once set there was
# no way back to the mirrored, locked view — see CampaignEditor's relock().


def test_relock_submission_clears_express_unlocked_and_resumes_mirroring():
    prior = _spec().model_dump(mode="json")
    assert len(prior["adsets"]) == 2  # sanity: this fixture is genuinely multi-ad-set

    edited = copy.deepcopy(prior)
    edited["adsets"][0]["ads"][0]["creative"]["title"] = "Ad set 0's headline"
    bs = {"filled": {"publish_mode": "express"}, "marketing_plan": prior,
          "express_unlocked": True}  # was unlocked from a previous save
    _apply_plan_form_submission(bs, {"action": "save", "spec": edited, "unlocked": False})

    assert bs["express_unlocked"] is False
    # Re-locked -> the mirror runs again: ad set 1 gets ad set 0's creative.
    assert bs["marketing_plan"]["adsets"][1]["ads"][0]["creative"]["title"] == "Ad set 0's headline"


def test_unlock_submission_sets_the_flag_and_skips_the_mirror():
    prior = _spec().model_dump(mode="json")
    edited = copy.deepcopy(prior)
    edited["adsets"][0]["ads"][0]["creative"]["title"] = "Ad set 0's headline"
    edited["adsets"][1]["ads"][0]["creative"]["title"] = "Ad set 1's own headline"
    bs = {"filled": {"publish_mode": "express"}, "marketing_plan": prior}
    _apply_plan_form_submission(bs, {"action": "save", "spec": edited, "unlocked": True})

    assert bs["express_unlocked"] is True
    # Unlocked -> no mirror; ad set 1 keeps what the user actually typed.
    assert bs["marketing_plan"]["adsets"][1]["ads"][0]["creative"]["title"] == "Ad set 1's own headline"


def test_submission_omitting_unlocked_leaves_the_flag_untouched():
    """A plain save/publish carries no `unlocked` key at all — the flag must
    stay whatever it already was, not get reset to falsy by its absence."""
    prior = _spec().model_dump(mode="json")
    edited = copy.deepcopy(prior)
    bs = {"filled": {"publish_mode": "express"}, "marketing_plan": prior,
          "express_unlocked": True}
    _apply_plan_form_submission(bs, {"action": "save", "spec": edited})
    assert bs["express_unlocked"] is True


def test_a_normal_express_save_does_not_truncate_a_multi_adset_plan():
    """Punk's own generated plan can legitimately have more than one ad set —
    that's exactly why _mirror_first_ad exists instead of just dropping the
    extras. A locked express save must keep every ad set, not collapse to one."""
    prior = _spec().model_dump(mode="json")
    assert len(prior["adsets"]) == 2
    edited = copy.deepcopy(prior)
    bs = {"filled": {"publish_mode": "express"}, "marketing_plan": prior}
    _apply_plan_form_submission(bs, {"action": "publish", "spec": edited})
    assert len(bs["marketing_plan"]["adsets"]) == 2


def test_republishing_an_untouched_plan_still_resumes():
    """The other half: an unchanged resubmission must not throw away a campaign
    the last attempt already built."""
    prior = _spec().model_dump(mode="json")
    assert "publish_plan_dirty" not in _submit(prior, dict(prior))


def test_a_resubmitted_plan_is_a_fresh_attempt_for_the_retry_cap():
    """Counters only reset here — reopening the editor keeps them, or the 3-strike
    cap could never fire."""
    prior = _spec().model_dump(mode="json")
    bs = _submit(prior, {**prior, "name": "Renamed"}, publish_fail_counts={"ad": 2})
    assert "publish_fail_counts" not in bs


# ── "do it for me": one ad card stands for every ad set ───────────────────────


def _edited_first_ad(prior: dict) -> dict:
    """The one card the express editor renders, filled in by the user."""
    edited = copy.deepcopy(prior)
    creative = edited["adsets"][0]["ads"][0]["creative"]
    creative["title"] = "Roasted this morning"
    creative["media_id"] = "11111111-1111-1111-1111-111111111111"
    return edited


def test_express_copies_the_single_edited_ad_onto_every_adset():
    """Express hides every ad set but the first, so the untouched ads keep the
    brief's copy and never get an image — and a media-less ad is skipped at
    publish, shipping an ad set with no ad."""
    prior = _spec().model_dump(mode="json")
    edited = _edited_first_ad(prior)
    assert edited["adsets"][1]["ads"][0]["creative"].get("media_id") is None

    bs = _submit(prior, edited, filled={"publish_mode": "express"})
    adsets = bs["marketing_plan"]["adsets"]
    assert len(adsets) == 2
    first = adsets[0]["ads"][0]["creative"]
    for adset in adsets[1:]:
        assert len(adset["ads"]) == 1
        assert adset["ads"][0]["creative"] == first
        # Named after its own ad set, not ad set 0's.
        assert adset["ads"][0]["name"].endswith(f" · {adset['name']}")


def test_guided_mode_keeps_each_adsets_own_ads():
    """The full editor renders every card, so its ads are the user's — copying
    ad set 0 over them would delete what they typed."""
    prior = _spec().model_dump(mode="json")
    edited = _edited_first_ad(prior)
    edited["adsets"][1]["ads"][0]["creative"]["title"] = "Different on purpose"

    bs = _submit(prior, edited, filled={"publish_mode": "guide"})
    assert bs["marketing_plan"]["adsets"][1]["ads"][0]["creative"]["title"] == (
        "Different on purpose"
    )
