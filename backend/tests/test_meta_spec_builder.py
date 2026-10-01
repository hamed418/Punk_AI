"""
Unit tests for build_campaign_spec — the deterministic replacement for the
Gemini call that used to invent the Meta JSON.

Pure: no LLM, no network, no ad account.
"""

import pytest
from pydantic import ValidationError

from app.graph.meta_spec.models import CampaignSpec
from app.graph.meta_spec.builder import (
    split_for_publish,
    SpecBuildError,
    build_campaign_spec,
    build_campaign_tree,
)
from app.graph.meta_spec.enums import (
    FREQUENCY_DEFAULT_INTERVAL_DAYS,
    FREQUENCY_DEFAULT_MAX,
    BidStrategy,
    DestinationType,
    Objective,
    OptimizationGoal,
)
from app.graph.meta_spec.parsing import (
    BudgetParseError,
    DateParseError,
    parse_budget_to_cents,
    parse_campaign_date,
    resolve_flight,
)

SEED = {"geo_locations": {"custom_locations": [{"latitude": 43.6, "longitude": -79.4, "radius": 2}]}}
BROAD = {"geo_locations": {"cities": [{"name": "Toronto"}]}}
LOOKALIKE = {"geo_locations": {"cities": [{"name": "Toronto"}]}}

USER_INFO = {
    "campaign_objective": "TRAFFIC",
    "business_name": "Bean There",
    "business_description": "Specialty coffee roaster",
    "website_url": "https://beanthere.example",
    "budget": "$50/day",
    "budget_type": "daily",
    "campaign_start_date": "August 1, 2026",
}

GEO_DATA = {"maid_count": 12000, "poi_radius_km": 1.5}

BRIEF = {
    "campaign_name": "Bean There — Summer Traffic",
    "adset_budget_breakdown": [
        {"adset_name": "Visitors", "budget_pct": 70, "audience_type": "primary"},
        {"adset_name": "Prospecting", "budget_pct": 30, "audience_type": "lookalike"},
    ],
    "headline_suggestions": ["Fresh roast, daily"],
    "body_copy_suggestions": ["Come taste the difference."],
    "cta_recommendation": "LEARN_MORE — invites a click",
}


def _build(**kwargs):
    params = dict(
        user_info=dict(USER_INFO),
        geo_data=dict(GEO_DATA),
        brief=dict(BRIEF),
        seed_targeting=dict(SEED),
        broad_targeting=dict(BROAD),
        lookalike_targeting=dict(LOOKALIKE),
        page_id="pg1",
    )
    params.update(kwargs)
    return build_campaign_spec(**params)


def _tree(**kwargs):
    """The same inputs, stopping before validation — what the plan editor gets
    when the tree cannot validate yet (a conversion goal with no pixel)."""
    params = dict(
        user_info=dict(USER_INFO),
        geo_data=dict(GEO_DATA),
        brief=dict(BRIEF),
        seed_targeting=dict(SEED),
        broad_targeting=dict(BROAD),
        lookalike_targeting=dict(LOOKALIKE),
        page_id="pg1",
    )
    params.update(kwargs)
    return build_campaign_tree(**params)


# ── parsing ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,cents",
    [
        ("$50/day", 5000),
        ("Recommended: $55/day", 5500),
        ("$1,650 total", 165000),
        ("50", 5000),
        (50, 5000),
        (12.5, 1250),
    ],
)
def test_parse_budget(raw, cents):
    assert parse_budget_to_cents(raw) == cents


def test_budget_label_digits_do_not_win():
    """'Tier 2: $80/day' must parse as 80, not 2."""
    assert parse_budget_to_cents("Tier 2: $80/day") == 8000


@pytest.mark.parametrize("raw", ["no numbers here", "", None, 0, -5])
def test_budget_without_a_number_raises(raw):
    """Both old implementations silently returned $50 — real money at a rate
    nobody chose."""
    with pytest.raises(BudgetParseError):
        parse_budget_to_cents(raw)


@pytest.mark.parametrize(
    "raw",
    ["2026-05-01", "May 1, 2026", "05/01/2026", "2026-05-01T00:00:00+00:00"],
)
def test_parse_campaign_date_formats(raw):
    assert parse_campaign_date(raw).year == 2026


def test_unparseable_date_raises_instead_of_defaulting_to_now():
    """meta_ads.parse_campaign_date fell back to now(), silently starting the
    campaign immediately instead of when the user asked."""
    with pytest.raises(DateParseError):
        parse_campaign_date("next Tuesday-ish")


def test_absent_start_means_now_but_bad_start_still_raises():
    start, end = resolve_flight(None, None, is_lifetime=False)
    assert start.tzinfo is not None
    assert end is None
    with pytest.raises(DateParseError):
        resolve_flight("gibberish", None, is_lifetime=False)


def test_lifetime_budget_gets_a_default_end_date():
    start, end = resolve_flight("2026-08-01", None, is_lifetime=True)
    assert end is not None and (end - start).days == 30


@pytest.mark.parametrize("raw", ["ongoing", "no end", "none", ""])
def test_open_ended_end_dates_mean_no_end(raw):
    _, end = resolve_flight("2026-08-01", raw, is_lifetime=False)
    assert end is None


# ── build: structure ─────────────────────────────────────────────────────────


def test_builds_one_adset_per_budget_slice():
    """One ad set per slice. The brief's own ad set names are not used — names
    come from the resolved audience role, see the naming test below."""
    spec = _build()
    assert len(spec.adsets) == 2


def test_budget_split_is_honoured():
    """The regression this package exists for: the split was computed, shown to
    the user, and then discarded — every ad set got the same budget."""
    spec = _build()
    assert [a.daily_budget for a in spec.adsets] == [3500, 1500]
    assert spec.total_budget_cents() == 5000


def test_budget_slices_are_floored_at_meta_minimum():
    brief = {**BRIEF, "adset_budget_breakdown": [
        {"adset_name": "Tiny", "budget_pct": 1, "audience_type": "primary"},
        {"adset_name": "Rest", "budget_pct": 99, "audience_type": "lookalike"},
    ]}
    spec = _build(user_info={**USER_INFO, "budget": "$10/day"}, brief=brief)
    assert spec.adsets[0].daily_budget >= 100


def test_no_breakdown_still_yields_a_seed_and_a_broader_adset():
    """A brief with no split is not a plan with no prospecting — the second ad
    set is synthesized 60/40 and the full budget is still spent."""
    spec = _build(brief={k: v for k, v in BRIEF.items() if k != "adset_budget_breakdown"})
    assert len(spec.adsets) == 2
    assert [a.audience_role for a in spec.adsets] == ["seed", "lookalike"]
    assert [a.daily_budget for a in spec.adsets] == [3000, 2000]
    assert spec.total_budget_cents() == 5000


def test_audience_roles_are_assigned_seed_first():
    spec = _build()
    assert [a.audience_role for a in spec.adsets] == ["seed", "lookalike"]


def test_lookalike_role_degrades_to_broad_when_no_lookalike_exists():
    spec = _build(lookalike_targeting=None)
    assert [a.audience_role for a in spec.adsets] == ["seed", "broad"]


def test_adset_names_describe_the_audience_and_follow_the_resolved_role():
    """The name is the explanation most users ever read, so it comes from the
    role, not from the brief — a broad ad set must not be sold as an expansion
    of a visitor list it was never built from."""
    named = _build().adsets
    assert [a.name for a in named] == ["Real Visitors", "Lookalike of Visitors"]
    degraded = _build(lookalike_targeting=None).adsets
    assert degraded[1].name == "New Prospects · Broad Reach"


_NAMED_GEO = {
    **GEO_DATA,
    "locations": [{"location_name": "Toronto, ON, Canada", "locality": "Toronto"}],
    "targetable_pois": [
        {"parent_poi_type": "coffee shop"},
        {"parent_poi_type": "coffee shop"},
        {"parent_poi_type": "Starbucks"},
    ],
}


def test_names_say_what_differs_and_never_the_business():
    """The business name is the same on every campaign the user makes, so it
    cannot be what tells them apart. Goal, who, where and when can."""
    spec = _build(geo_data=dict(_NAMED_GEO))
    assert spec.name == "Summer Traffic · Toronto · Aug 2026"
    assert [a.name for a in spec.adsets] == [
        "Real Visitors · Coffee Shop +1",
        "Lookalike of Visitors · Coffee Shop +1",
    ]
    assert spec.adsets[0].ads[0].name == "Fresh roast, daily · Real Visitors · Coffee Shop +1"
    assert "Bean There" not in " ".join(
        [spec.name, *(a.name for a in spec.adsets), *(ad.name for a in spec.adsets for ad in a.ads)]
    )


def test_a_page_or_business_change_cannot_rename_the_campaign():
    """The regression: names were minted from business_name once and carried the
    first Page's name forever."""
    a = _build(user_info={**USER_INFO, "business_name": "Page One"}, geo_data=dict(_NAMED_GEO))
    b = _build(user_info={**USER_INFO, "business_name": "Page Two"}, geo_data=dict(_NAMED_GEO))
    assert a.name == b.name and [x.name for x in a.adsets] == [x.name for x in b.adsets]


def test_a_brief_that_still_leads_with_the_business_is_stripped():
    brief = {**BRIEF, "campaign_name": "Bean There — Prospecting | Local Coffee Lovers | May 2024"}
    assert _build(brief=brief, geo_data=dict(_NAMED_GEO)).name == (
        "Prospecting | Local Coffee Lovers · Toronto · Aug 2026"
    )


def test_a_city_the_brief_already_named_is_not_repeated():
    brief = {**BRIEF, "campaign_name": "Prospecting · Toronto Coffee Lovers"}
    assert _build(brief=brief, geo_data=dict(_NAMED_GEO)).name == (
        "Prospecting · Toronto Coffee Lovers · Aug 2026"
    )


def test_with_no_brief_name_the_objective_is_the_name():
    brief = {k: v for k, v in BRIEF.items() if k != "campaign_name"}
    assert _build(brief=brief).name == "Traffic · Aug 2026"


def test_broad_adsets_are_named_by_the_demographic_that_publishes():
    info = {**USER_INFO, "target_age_min": 25, "target_age_max": 44, "target_gender": "female"}
    spec = _build(user_info=info, lookalike_targeting=None)
    assert spec.adsets[1].name == "New Prospects · 25–44 Women"


def test_extra_broad_adsets_are_numbered_apart():
    brief = {**BRIEF, "adset_budget_breakdown": [
        {"budget_pct": 40, "audience_type": "primary"},
        {"budget_pct": 30, "audience_type": "interest"},
        {"budget_pct": 30, "audience_type": "interest"},
    ]}
    names = [a.name for a in _build(brief=brief, lookalike_targeting=None).adsets]
    assert len(set(names)) == 3


def test_an_address_is_not_a_place_name():
    geo = {**GEO_DATA, "locations": [{"location_name": "123 Main St, Toronto"}]}
    assert _build(geo_data=geo).name == "Summer Traffic · Aug 2026"


# ── build: objective-driven fields ───────────────────────────────────────────


def test_fields_come_from_the_objective_matrix():
    spec = _build()
    rules_defaults = (
        OptimizationGoal.LINK_CLICKS,
        BidStrategy.LOWEST_COST_WITHOUT_CAP,
    )
    assert spec.adsets[0].optimization_goal is rules_defaults[0]
    assert spec.adsets[0].bid_strategy is rules_defaults[1]


SALES_WITH_DATASET = {**USER_INFO, "campaign_objective": "SALES", "has_warm_dataset": True}


def test_sales_objective_without_a_pixel_fails_validation_not_the_build():
    """A conversion goal whose pixel id never arrived is an editor-fixable hole,
    not a missing prerequisite: the tree builds (so the plan editor can open on
    it) and CampaignSpec is what refuses. The objective is never downgraded on
    the user's behalf.

    ``has_warm_dataset`` is what puts the run on a conversion goal in the first
    place — without it Sales resolves to LANDING_PAGE_VIEWS, which promotes
    nothing and validates cleanly (see the pixel-less tests below)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match=r"promoted_object\.pixel_id is required"):
        _build(user_info=dict(SALES_WITH_DATASET))

    tree = _tree(user_info=dict(SALES_WITH_DATASET))
    assert tree["objective"] == "OUTCOME_SALES"
    po = tree["adsets"][0]["promoted_object"]
    assert "pixel_id" not in po                    # the one thing the editor asks
    assert po["custom_event_type"] == "PURCHASE"   # prefilled, so it doesn't


def test_sales_with_no_dataset_at_all_builds_a_goal_that_needs_none():
    """The account has never had a dataset fire. Optimizing for purchases would
    publish an ad set learning from an event that cannot arrive, so the goal
    steps down to the first one on this destination that promotes nothing — and
    the plan VALIDATES, instead of dead-ending the run on a pixel picker with no
    options."""
    spec = _build(user_info={**USER_INFO, "campaign_objective": "SALES"})
    adset = spec.adsets[0]
    assert adset.optimization_goal is OptimizationGoal.LANDING_PAGE_VIEWS
    assert adset.promoted_object is None
    assert spec.objective.value == "OUTCOME_SALES"   # the objective is NOT changed


def test_sales_with_no_dataset_can_still_be_sold_through_messenger():
    """The other pixel-less shape, and the one a chat-led business wants: the
    conversion happens in a Messenger thread, which Meta counts itself."""
    spec = _build(user_info={
        **USER_INFO, "campaign_objective": "SALES", "conversion_location": "MESSENGER",
    })
    adset = spec.adsets[0]
    assert adset.optimization_goal is OptimizationGoal.CONVERSATIONS
    assert adset.promoted_object is None


def test_a_dataset_that_has_fired_puts_the_conversion_goal_back():
    """The step-down is about the account's state, not a permanent downgrade."""
    spec = _build(user_info=dict(SALES_WITH_DATASET), pixel_id="99887766")
    assert spec.adsets[0].optimization_goal is OptimizationGoal.OFFSITE_CONVERSIONS
    assert spec.adsets[0].promoted_object.pixel_id == "99887766"


def test_a_resolved_pixel_id_is_enough_on_its_own():
    """media_select_pixel only resolves an id for a pixel-promoted campaign, so a
    caller that passes one has already answered the question — the tree must not
    then step the goal down underneath it."""
    spec = _build(
        user_info={**USER_INFO, "campaign_objective": "SALES"}, pixel_id="99887766",
    )
    assert spec.adsets[0].optimization_goal is OptimizationGoal.OFFSITE_CONVERSIONS


def test_missing_pixel_error_lands_on_the_pixel_field_not_the_form():
    """The plan editor renders the Meta Pixel select against
    ``adsets[0].promoted_object.pixel_id``. _check_promoted_object is a
    whole-model validator, so Pydantic gives it no loc — without the message's
    own leading path this error is a banner and the control the user has to fix
    is left unmarked."""
    from app.graph.meta_spec.catalog import errors_to_form_keys

    with pytest.raises(ValidationError) as exc:
        _build(user_info=dict(SALES_WITH_DATASET))

    keys = errors_to_form_keys(exc.value)
    assert "adsets[0].promoted_object.pixel_id" in keys
    assert "__root__" not in keys


def test_sales_objective_with_pixel_builds_promoted_object():
    spec = _build(user_info={**USER_INFO, "campaign_objective": "SALES"}, pixel_id="99887766")
    po = spec.adsets[0].promoted_object
    assert po.pixel_id == "99887766"
    assert po.custom_event_type == "PURCHASE"


def test_brief_prose_cannot_downgrade_sales_off_a_pixel_goal():
    """SALES → WEBSITE also offers REACH / LINK_CLICKS / LANDING_PAGE_VIEWS, none
    of which carry a promoted_object — and the goal is read out of LLM prose by
    earliest enum mention, so "reach ..." used to win over the conversion goal
    named after it. That silently published a Sales campaign with no pixel and
    made the editor's pixel picker vanish on some runs and not others."""
    spec = _build(
        user_info={**USER_INFO, "campaign_objective": "SALES"},
        brief={**BRIEF, "optimization_goal": "REACH purchase-ready shoppers, "
                                             "then OFFSITE_CONVERSIONS"},
        pixel_id="99887766",
    )
    adset = spec.adsets[0]
    assert adset.optimization_goal is OptimizationGoal.OFFSITE_CONVERSIONS
    assert adset.promoted_object.pixel_id == "99887766"


def test_brief_may_still_pick_the_other_pixel_goal():
    spec = _build(
        user_info={**USER_INFO, "campaign_objective": "SALES"},
        brief={**BRIEF, "optimization_goal": "VALUE"},
        pixel_id="99887766",
    )
    assert spec.adsets[0].optimization_goal is OptimizationGoal.VALUE


def test_destinations_with_no_pixel_goal_still_honour_the_brief():
    """The rule is scoped to destinations that CAN promote a pixel. TRAFFIC has
    none, so a brief naming LANDING_PAGE_VIEWS is still obeyed."""
    spec = _build(brief={**BRIEF, "optimization_goal": "LANDING_PAGE_VIEWS"})
    assert spec.adsets[0].optimization_goal is OptimizationGoal.LANDING_PAGE_VIEWS


def test_leads_defaults_to_instant_forms_and_promotes_the_page():
    """Leads defaults to the Instant Form conversion location, whose goal is
    LEAD_GENERATION and whose promoted object is the Page. The old default paired
    that goal with a WEBSITE destination — a combination Meta rejects."""
    spec = _build(user_info={**USER_INFO, "campaign_objective": "LEADS"})
    adset = spec.adsets[0]
    assert adset.destination_type.value == "ON_AD"
    assert adset.optimization_goal.value == "LEAD_GENERATION"
    assert adset.promoted_object.page_id == "pg1"


def test_instant_form_leads_opens_with_no_form_chosen():
    """Nothing collects a form before the spec exists, so the initial tree names
    none: the editor is where the user picks an existing form, designs one
    (lead_form_draft), or leaves both blank and lets publish generate one.
    Demanding an id here made every Leads instant-form run unbuildable."""
    spec = _build(user_info={**USER_INFO, "campaign_objective": "LEADS"})
    assert spec.adsets[0].destination_type.value == "ON_AD"
    assert spec.adsets[0].ads[0].creative.lead_gen_form_id is None
    assert spec.adsets[0].lead_form_draft is None


def test_website_leads_uses_the_pixel_not_the_page():
    """Same objective, different conversion location, entirely different shape."""
    spec = _build(
        user_info={
            **USER_INFO,
            "campaign_objective": "LEADS",
            "conversion_location": "WEBSITE",
        },
        pixel_id="55443322",
    )
    adset = spec.adsets[0]
    assert adset.destination_type.value == "WEBSITE"
    assert adset.optimization_goal.value == "OFFSITE_CONVERSIONS"
    assert adset.promoted_object.pixel_id == "55443322"
    assert adset.promoted_object.custom_event_type == "LEAD"
    assert adset.ads[0].creative.lead_gen_form_id is None


def test_conversion_location_the_objective_does_not_offer_is_rejected():
    with pytest.raises(SpecBuildError, match="not a conversion location"):
        _build(user_info={
            **USER_INFO, "campaign_objective": "AWARENESS",
            "conversion_location": "SHOP_AUTOMATIC",
        })


def test_app_promotion_requires_store_url():
    with pytest.raises(SpecBuildError, match="app linked to your ad account"):
        _build(user_info={**USER_INFO, "campaign_objective": "APP_PROMOTION"})


def test_unknown_objective_raises():
    with pytest.raises(SpecBuildError, match="unrecognized campaign objective"):
        _build(user_info={**USER_INFO, "campaign_objective": "vibes"})


# ── build: destination link ──────────────────────────────────────────────────


def test_link_falls_back_to_facebook_page_not_example_com():
    """The old publish path fell through to https://example.com — a live ad
    pointing at a placeholder domain."""
    spec = _build(user_info={k: v for k, v in USER_INFO.items() if k != "website_url"})
    assert spec.adsets[0].ads[0].creative.link == "https://www.facebook.com/pg1"


def test_no_destination_at_all_is_an_error():
    ui = {k: v for k, v in USER_INFO.items() if k != "website_url"}
    with pytest.raises(SpecBuildError, match="nowhere to send people"):
        _build(user_info=ui, page_id=None)


def test_bare_domain_gets_a_scheme():
    spec = _build(user_info={**USER_INFO, "website_url": "beanthere.example"})
    assert spec.adsets[0].ads[0].creative.link == "https://beanthere.example"


# ── build: demographics ──────────────────────────────────────────────────────


def test_user_demographics_reach_the_targeting_spec():
    """Age/gender lived in build_meta_precomputed's targeting_spec, which never
    reached Meta because publish used build_targeting's output directly."""
    spec = _build(user_info={**USER_INFO, "target_age_min": 25, "target_age_max": 45,
                             "target_gender": "female"})
    t = spec.adsets[0].targeting
    assert (t["age_min"], t["age_max"], t["genders"]) == (25, 45, [2])


# ── build: app promotion platform split ──────────────────────────────────────
# One ad set per store: promoted_object.object_store_url is a single URL and an
# ad set targets one platform. The builder used to take the App Store link and
# drop the Play link, so an advertiser who gave us both got an iOS-only campaign
# with no indication why.

_APP_INFO = {
    **USER_INFO,
    "campaign_objective": "APP_PROMOTION",
    "conversion_location": "APP",
    "app_store_url": "https://apps.apple.com/app/id123",
    "play_store_url": "https://play.google.com/store/apps/details?id=x",
}


def _app_build(**info):
    return _build(user_info={**_APP_INFO, **info}, application_id="app-1")


def test_both_store_links_produce_one_adset_per_platform():
    spec = _app_build()
    oses = [a.targeting.get("user_os") for a in spec.adsets]
    assert ["iOS"] in oses and ["Android"] in oses


def test_each_platform_adset_points_at_its_own_store():
    spec = _app_build()
    by_os = {a.targeting["user_os"][0]: a for a in spec.adsets}
    assert "apple.com" in by_os["iOS"].promoted_object.object_store_url
    assert "play.google" in by_os["Android"].promoted_object.object_store_url
    # ...and the ad's link follows it, rather than the campaign-wide one.
    assert "apple.com" in by_os["iOS"].ads[0].creative.link
    assert "play.google" in by_os["Android"].ads[0].creative.link


def test_a_single_store_link_is_left_alone():
    """One store means one ad set — no split, no halved budget."""
    spec = _app_build(play_store_url="")
    assert all("user_os" not in a.targeting for a in spec.adsets)


def test_the_platform_split_is_reported():
    """Including the bit the split cannot fix: iOS installs need their own
    SKAdNetwork campaign."""
    notes = _app_build().compliance_notes
    assert any("app store" in n.lower() for n in notes)
    assert any("SKAdNetwork" in n for n in notes)


# ── build: special ad category compliance ────────────────────────────────────
# Housing/employment/credit ads may not target by ZIP, may not use a lookalike,
# and may not use detailed targeting. Punk's whole geo model is ZIPs resolved
# from POIs, seeded into a MAID lookalike — so a detected category used to
# produce a plan that was non-compliant, not merely narrow.

_ZIP_TARGETING = {
    "geo_locations": {
        "zips": [{"key": "US:94104"}, {"key": "US:94105"}],
        "location_types": ["home", "recent"],
    },
    "flexible_spec": [{"interests": [{"id": "1", "name": "Renting"}]}],
    "exclusions": {"interests": [{"id": "2", "name": "Camping"}]},
}
_HOUSING_INFO = {**USER_INFO, "business_description": "Apartments for rent downtown"}


def _housing_build(**kwargs):
    params = dict(
        user_info=_HOUSING_INFO,
        seed_targeting=dict(_ZIP_TARGETING),
        broad_targeting=dict(_ZIP_TARGETING),
    )
    params.update(kwargs)
    return _build(**params)


_TORONTO = {
    "location_name": "Toronto",
    "latitude": 43.6532,
    "longitude": -79.3832,
    "country_code": "CA",
}


def test_special_ad_category_drops_zip_targeting():
    """Meta's floor for a regulated ad is a 15-mile radius. ZIPs are forbidden
    outright, so leaving them in ships an illegal campaign."""
    spec = _housing_build(geo_data={**GEO_DATA, "locations": [_TORONTO]})
    for adset in spec.adsets:
        geo = adset.targeting["geo_locations"]
        assert "zips" not in geo
        assert geo["custom_locations"] == [{
            "latitude": 43.6532,
            "longitude": -79.3832,
            "radius": 15,
            "distance_unit": "mile",
        }]


def test_zip_replacement_never_uses_a_city_name():
    """``cities`` takes an adgeolocation key, not a name. ``{"name": "Toronto"}``
    is what the API returns on a read and is rejected on a write — it used to be
    what this path built."""
    geo = _housing_build(
        geo_data={**GEO_DATA, "locations": [_TORONTO]}
    ).adsets[0].targeting["geo_locations"]
    assert "cities" not in geo


def test_special_ad_category_falls_back_to_country_without_coordinates():
    """No geocoded coordinates is still no excuse to leave the ZIPs in. Country is
    coarse but legal — and never an empty geo block, which AdSetSpec rejects."""
    spec = _housing_build()
    geo = spec.adsets[0].targeting["geo_locations"]
    assert "zips" not in geo
    assert geo["countries"] == ["US"]


def test_special_ad_category_widens_a_radius_under_the_floor():
    """The MAID seed ad set rings each POI at ~2 km. That is legal normally and
    illegal for a regulated category, and the ring was left untouched because
    only ZIP targeting was being rewritten."""
    spec = _housing_build(seed_targeting={
        "geo_locations": {
            "custom_locations": [
                {"latitude": 43.6, "longitude": -79.4, "radius": 2, "distance_unit": "kilometer"}
            ]
        }
    })
    pin = spec.adsets[0].targeting["geo_locations"]["custom_locations"][0]
    assert (pin["radius"], pin["distance_unit"]) == (15, "mile")
    assert any("15-mile" in n for n in spec.compliance_notes)


def test_dropping_zips_keeps_the_rings_the_ad_set_already_had():
    """The POI rings ARE the campaign's geography. Replacing the ZIPs by
    synthesizing new pins over them would throw that away."""
    spec = _housing_build(
        seed_targeting={
            "geo_locations": {
                "zips": [{"key": "CA:M5V"}],
                "custom_locations": [
                    {"latitude": 43.6, "longitude": -79.4, "radius": 2, "distance_unit": "kilometer"}
                ],
            }
        },
        geo_data={**GEO_DATA, "locations": [_TORONTO]},
    )
    pins = spec.adsets[0].targeting["geo_locations"]["custom_locations"]
    assert [(p["latitude"], p["longitude"]) for p in pins] == [(43.6, -79.4)]
    assert pins[0]["radius"] == 15


def test_widening_does_not_mutate_the_caller_targeting():
    """``geo_locations`` is shallow-copied, so editing a pin in place reaches back
    into the seed_targeting dict the caller still holds."""
    seed = {
        "geo_locations": {
            "custom_locations": [
                {"latitude": 43.6, "longitude": -79.4, "radius": 2, "distance_unit": "kilometer"}
            ]
        }
    }
    _housing_build(seed_targeting=seed)
    assert seed["geo_locations"]["custom_locations"][0]["radius"] == 2


def test_special_ad_category_country_survives_the_zip_strip():
    """The ZIP prefix is the most reliable country source we have, and it is the
    first thing sanitization deletes — so it has to be read from geo_data, not
    from the targeting that was just cleaned. A Toronto advertiser declaring
    under US rules is a compliance failure, not a cosmetic one."""
    spec = _housing_build(geo_data={
        **GEO_DATA,
        "locations": [_TORONTO],
        "target_zips": ["CA:M5V", "CA:M5H"],
    })
    assert spec.special_ad_category_country == ["CA"]


def test_special_ad_category_drops_detailed_targeting():
    """Interests are restricted for regulated categories and exclusions are
    forbidden."""
    t = _housing_build().adsets[0].targeting
    assert "flexible_spec" not in t
    assert "exclusions" not in t


def test_special_ad_category_drops_the_lookalike():
    """Special Ad Audiences were retired in 2022, so the MAID-seeded lookalike
    that the rest of the product depends on cannot be used here."""
    spec = _housing_build()
    assert "lookalike" not in {a.audience_role for a in spec.adsets}


def test_special_ad_category_reports_what_it_removed():
    """Silently shrinking someone's campaign is the wrong failure mode — the plan
    carries the reasons so the editor can show them."""
    notes = _housing_build().compliance_notes
    assert any("ZIP" in n for n in notes)
    assert any("interest" in n for n in notes)
    assert any("exclusion" in n for n in notes)


def test_no_category_leaves_targeting_untouched():
    spec = _build(seed_targeting=dict(_ZIP_TARGETING), broad_targeting=dict(_ZIP_TARGETING))
    assert spec.compliance_notes == []
    assert spec.adsets[0].targeting["geo_locations"]["zips"]
    assert spec.adsets[0].targeting["flexible_spec"]


def test_special_ad_category_strips_demographics():
    """Detected housing advertiser: Meta forbids age/gender narrowing, so the
    build clears it rather than producing a plan that cannot validate."""
    spec = _build(user_info={
        **USER_INFO,
        "business_description": "Apartments for rent downtown",
        "target_age_min": 30,
        "target_gender": "male",
    })
    assert [c.value for c in spec.special_ad_categories] == ["HOUSING"]
    t = spec.adsets[0].targeting
    assert (t["age_min"], t["age_max"], t["genders"]) == (18, 65, [])


# ── validate: the editable plan can put back what the builder removed ─────────
# The builder sanitizes, but the plan form submits a whole edited spec. Every
# rule below was enforced at build time only, so a user edit walked straight past
# it — CampaignSpec now rejects it wherever the spec came from.


def _edited_housing_spec(**targeting_patch):
    """A built housing spec, edited the way the plan form would submit it."""
    spec = _housing_build(geo_data={**GEO_DATA, "locations": [_TORONTO]})
    data = spec.model_dump()
    data["adsets"][0]["targeting"] = {**data["adsets"][0]["targeting"], **targeting_patch}
    return data


@pytest.mark.parametrize(
    "patch,message",
    [
        ({"geo_locations": {"zips": [{"key": "US:94104"}]}}, "zips"),
        ({"flexible_spec": [{"interests": [{"id": "1", "name": "Renting"}]}]}, "flexible_spec"),
        ({"exclusions": {"interests": [{"id": "2", "name": "Camping"}]}}, "exclusions"),
        ({"genders": [1]}, "genders"),
        ({"age_min": 30}, "age range"),
    ],
)
def test_edited_plan_cannot_reintroduce_forbidden_targeting(patch, message):
    with pytest.raises(ValidationError, match=message):
        CampaignSpec.model_validate(_edited_housing_spec(**patch))


def test_edited_plan_cannot_shrink_the_radius_below_the_floor():
    data = _edited_housing_spec(geo_locations={
        "custom_locations": [
            {"latitude": 43.6, "longitude": -79.4, "radius": 5, "distance_unit": "mile"}
        ]
    })
    with pytest.raises(ValidationError, match="at least 15 miles"):
        CampaignSpec.model_validate(data)


def test_metric_spelling_of_the_floor_is_accepted():
    """24 km is Meta's own metric spelling of 15 miles and lands a hair under in
    floating point — rejecting it would fail a compliant ad set."""
    data = _edited_housing_spec(geo_locations={
        "custom_locations": [
            {"latitude": 43.6, "longitude": -79.4, "radius": 24, "distance_unit": "kilometer"}
        ]
    })
    assert CampaignSpec.model_validate(data)


def test_edited_plan_cannot_reintroduce_the_lookalike():
    spec = _housing_build(geo_data={**GEO_DATA, "locations": [_TORONTO]})
    data = spec.model_dump()
    data["adsets"][0]["audience_role"] = "lookalike"
    with pytest.raises(ValidationError, match="lookalike"):
        CampaignSpec.model_validate(data)


def test_an_unregulated_campaign_keeps_every_one_of_those():
    """The checks are gated on the category, not applied to everyone — a coffee
    roaster still gets ZIPs, interests and a lookalike."""
    spec = _build(seed_targeting=dict(_ZIP_TARGETING), broad_targeting=dict(_ZIP_TARGETING))
    assert CampaignSpec.model_validate(spec.model_dump())


# ── build: Advantage+ audience defaults ──────────────────────────────────────


def test_advantage_audience_defaults_off_for_seed_on_for_prospecting():
    spec = _build()
    assert spec.adsets[0].targeting["targeting_automation"]["advantage_audience"] == 0
    assert spec.adsets[1].targeting["targeting_automation"]["advantage_audience"] == 1


# ── build: audience binding ──────────────────────────────────────────────────


def test_bind_audiences_injects_real_ids_by_role():
    spec = _build()
    bound = spec.bind_audiences(custom_audience_id="ca1", lookalike_audience_id="la1")
    assert bound.adsets[0].targeting["custom_audiences"] == [{"id": "ca1"}]
    assert bound.adsets[1].targeting["custom_audiences"] == [{"id": "la1"}]


def test_bind_audiences_degrades_to_broad_when_lookalike_missing():
    """A lookalike can legitimately fail to build (seed too small); that should
    widen the ad set, not abort the publish."""
    spec = _build()
    bound = spec.bind_audiences(custom_audience_id="ca1", lookalike_audience_id=None)
    assert "custom_audiences" not in bound.adsets[1].targeting


def test_bound_spec_is_still_validated():
    spec = _build()
    bound = spec.bind_audiences(custom_audience_id="ca1", lookalike_audience_id="la1")
    assert bound.objective is Objective.TRAFFIC
    assert [a.daily_budget for a in bound.adsets] == [3500, 1500]


# ── build: payload fidelity ──────────────────────────────────────────────────


def test_payload_carries_every_field_the_matrix_chose():
    """What you validate is what gets sent — no second translation step."""
    spec = _build()
    payload = spec.adsets[0].to_payload(campaign_id="c1", ad_account_id="act_1")
    assert payload["optimization_goal"] == "LINK_CLICKS"
    assert payload["billing_event"] == "IMPRESSIONS"
    assert payload["bid_strategy"] == "LOWEST_COST_WITHOUT_CAP"
    assert payload["destination_type"] == "WEBSITE"
    assert payload["daily_budget"] == 3500


def test_reach_adsets_open_with_a_frequency_cap_not_a_blank_field():
    """Awareness optimizes for REACH, which is one of the two goals Meta accepts
    a frequency cap on. The plan editor renders every other field pre-filled, so
    shipping the cap empty read as a broken field rather than as "no cap"."""
    spec = _build(user_info={**USER_INFO, "campaign_objective": "AWARENESS"})
    caps = spec.adsets[0].frequency_control_specs
    assert caps and caps[0].max_frequency == FREQUENCY_DEFAULT_MAX
    assert caps[0].interval_days == FREQUENCY_DEFAULT_INTERVAL_DAYS


def test_a_reach_goal_outside_awareness_gets_no_frequency_cap():
    """Meta gates frequency_control_specs on the OBJECTIVE as well as the goal —
    "can only be used within … BRAND_AWARENESS, REACH, POST_ENGAGEMENT or
    RESEARCH_POLL". REACH is a goal under Traffic too, and the goal-only check
    shipped a capped Traffic ad set that died at preflight_adset."""
    spec = _build(brief={**BRIEF, "optimization_goal": "REACH",
                         "frequency_recommendation": "2 times per week"})
    assert spec.adsets[0].optimization_goal.value == "REACH"
    assert spec.adsets[0].frequency_control_specs is None

    bad = spec.model_dump(mode="json")
    bad["adsets"][0]["frequency_control_specs"] = [
        {"event": "IMPRESSIONS", "interval_days": 7, "max_frequency": 2}
    ]
    with pytest.raises(ValidationError, match="frequency_control_specs"):
        CampaignSpec.model_validate(bad)


def test_a_built_plan_never_seeds_an_attribution_window():
    """The opposite call to the frequency cap above, and deliberate. The editor
    DISPLAYS Meta's default (7d click / 1d engage / 1d view) so the field does not
    read "Off" for windows that are live — but writing it would freeze today's
    default into the ad set, and Meta moved it twice in 2026. Untouched publishes
    nothing and follows Meta."""
    spec = _build(user_info={**USER_INFO, "campaign_objective": "SALES"}, pixel_id="px1")
    assert spec.adsets[0].optimization_goal.value == "OFFSITE_CONVERSIONS"  # allows one
    assert all(a.attribution_spec is None for a in spec.adsets)


def test_traffic_adsets_carry_no_frequency_cap():
    """LINK_CLICKS is not a frequency-capped goal; Meta rejects the field there,
    so the default must not leak onto every ad set."""
    assert _build().adsets[0].frequency_control_specs is None


# ── app promotion: one campaign per store ────────────────────────────────────
# Meta carries the promoted app on the CAMPAIGN, and an iOS 14.5+ install
# campaign is a dedicated SKAdNetwork type that cannot hold Android ad sets. We
# used to publish one campaign holding both — a shape Meta accepts and then
# silently denies SKAdNetwork attribution on, which is worse than a rejection.

APP_INFO = {
    **USER_INFO,
    "campaign_objective": "APP_PROMOTION",
    "app_store_url": "https://apps.apple.com/app/id1",
    "play_store_url": "https://play.google.com/store/apps/details?id=x",
}


def _app_spec(**user_info_overrides):
    return _build(user_info={**APP_INFO, **user_info_overrides}, application_id="555")


def test_both_store_links_split_into_two_campaigns_ios_first():
    parts = split_for_publish(_app_spec())
    assert len(parts) == 2

    (ios, ios_idx), (android, android_idx) = parts
    assert ios.is_skadnetwork_attribution is True
    assert android.is_skadnetwork_attribution is False
    assert ios.promoted_object.object_store_url == APP_INFO["app_store_url"]
    assert android.promoted_object.object_store_url == APP_INFO["play_store_url"]
    # Each campaign is single-platform — the whole point.
    assert {tuple(a.targeting["user_os"]) for a in ios.adsets} == {("iOS",)}
    assert {tuple(a.targeting["user_os"]) for a in android.adsets} == {("Android",)}
    # Ad sets are partitioned, never duplicated or dropped.
    assert sorted(ios_idx + android_idx) == list(range(len(_app_spec().adsets)))
    assert not set(ios_idx) & set(android_idx)


def test_split_carries_the_plan_wide_adset_indices():
    """The publish ledger keys media/creatives/adsets/ads by the ad set's index
    in the WHOLE plan. Re-enumerating per campaign would collide those keys and
    break resume; the interleaved indices here are what makes that non-obvious."""
    (_ios, ios_idx), (_android, android_idx) = split_for_publish(_app_spec())
    assert ios_idx == [0, 2]
    assert android_idx == [1, 3]


def test_split_preserves_every_adset_budget():
    spec = _app_spec()
    before = sum(a.daily_budget or 0 for a in spec.adsets)
    after = sum(a.daily_budget or 0 for sub, _ in split_for_publish(spec) for a in sub.adsets)
    assert before == after


def test_one_store_link_stays_one_campaign():
    parts = split_for_publish(_app_spec(play_store_url=""))
    assert len(parts) == 1
    sub, indices = parts[0]
    assert sub.is_skadnetwork_attribution is False
    assert indices == list(range(len(sub.adsets)))


@pytest.mark.parametrize(
    "objective", ["AWARENESS", "TRAFFIC", "ENGAGEMENT", "LEADS", "SALES"]
)
def test_non_app_objectives_are_never_split(objective):
    """The guard on the whole change: every other objective must take exactly
    the path it took before, one campaign, indices untouched."""
    kwargs = {"user_info": {**USER_INFO, "campaign_objective": objective}}
    if objective in ("SALES", "LEADS"):
        kwargs["pixel_id"] = "99887766"
    spec = _build(**kwargs)

    parts = split_for_publish(spec)
    assert len(parts) == 1
    sub, indices = parts[0]
    assert sub is spec
    assert indices == list(range(len(spec.adsets)))
    assert sub.promoted_object is None or sub.objective is not Objective.APP_PROMOTION
    assert sub.is_skadnetwork_attribution is False


def test_split_campaigns_carry_the_app_fields_into_the_meta_payload():
    """to_payload is what actually reaches Meta — the fields are useless if the
    split sets them and the serializer drops them."""
    ios, android = (sub for sub, _ in split_for_publish(_app_spec()))
    assert ios.to_payload()["is_skadnetwork_attribution"] is True
    assert ios.to_payload()["promoted_object"]["object_store_url"] == APP_INFO["app_store_url"]
    # Absent, not False — Meta rejects the flag where it does not apply.
    assert "is_skadnetwork_attribution" not in android.to_payload()
    assert android.to_payload()["promoted_object"]["application_id"] == "555"


def test_non_app_campaign_payload_gains_no_app_fields():
    payload = _build().to_payload()
    assert "promoted_object" not in payload
    assert "is_skadnetwork_attribution" not in payload


# ── publishing identity ──────────────────────────────────────────────────────


def test_the_plan_carries_the_page_and_instagram_it_publishes_as():
    """Publish reads these off the plan, not off user_info: an advertiser with
    several Pages picks one in the editor and user_info still holds whichever
    Page OAuth stored first."""
    spec = _build(page_id="pg_chosen", instagram_user_id="ig_77")
    assert spec.page_id == "pg_chosen"
    assert spec.instagram_user_id == "ig_77"
    # …and neither leaks into the campaign create call.
    payload = spec.to_payload()
    assert "page_id" not in payload
    assert "instagram_user_id" not in payload


def test_an_adset_may_not_promote_a_different_page_than_the_campaign():
    tree = _tree()
    tree["page_id"] = "pg_1"
    tree["adsets"][0]["promoted_object"] = {"page_id": "pg_2"}
    with pytest.raises(Exception, match="different Facebook Page"):
        from app.graph.meta_spec.models import CampaignSpec
        CampaignSpec.model_validate(tree)


def test_whatsapp_ads_open_whatsapp_and_promote_the_page():
    """Click-to-WhatsApp: the number comes off the promoted Page. Without the
    promoted_object this publishes as a plain link-click ad that merely says
    WhatsApp on the button — and the link used to fall through to facebook.com
    because nothing ever collected a phone number."""
    spec = _build(
        user_info={**USER_INFO, "conversion_location": "WHATSAPP"},
        page_id="pg_wa",
    )
    adset = spec.adsets[0]
    assert adset.destination_type.value == "WHATSAPP"
    assert adset.promoted_object.page_id == "pg_wa"
    assert adset.ads[0].creative.link == "https://api.whatsapp.com/send"
    # Not the brief's suggested LEARN_MORE — that CTA carries a link value and
    # would open a browser instead of a conversation.
    assert adset.ads[0].creative.call_to_action.value == "WHATSAPP_MESSAGE"
    payload = adset.to_payload(campaign_id="c1", ad_account_id="act_1")
    assert payload["destination_type"] == "WHATSAPP"
    assert payload["promoted_object"] == {"page_id": "pg_wa"}


@pytest.mark.parametrize(
    "objective", ["TRAFFIC", "OUTCOME_ENGAGEMENT", "OUTCOME_LEADS", "OUTCOME_SALES"]
)
def test_whatsapp_is_offered_wherever_ads_manager_offers_it(objective):
    from app.graph.meta_spec.enums import normalize_objective
    from app.graph.meta_spec.objective_matrix import matrix_for

    rules = matrix_for(normalize_objective(objective))
    assert "WHATSAPP" in {d.destination_type.value for d in rules.destinations}


# ── the brief's structural picks ─────────────────────────────────────────────
# The brief recommends a conversion location, an optimization goal, a bid
# strategy, CBO vs ABO, a frequency cap and placements. Those were generated,
# printed on the plan card, and then dropped — the tree took the matrix default
# regardless, so the card could promise a setup the plan did not have. Each pick
# now reaches the spec, and each falls back rather than raising.


def test_the_brief_picks_the_conversion_location():
    """Leads via instant forms is a different ad set to Leads via a website:
    different goal, different promoted object, different prerequisites. Nothing
    downstream can infer which one the business needs — the brief can."""
    spec = _build(
        user_info={**USER_INFO, "campaign_objective": "LEADS"},
        brief={**BRIEF, "conversion_location": "ON_AD",
               "optimization_goal": "LEAD_GENERATION"},
    )
    adset = spec.adsets[0]
    assert adset.destination_type is DestinationType.ON_AD
    assert adset.optimization_goal is OptimizationGoal.LEAD_GENERATION
    # The pair Meta demands for an instant form, and the doc's most-cited error.
    assert adset.promoted_object.page_id == "pg1"


def test_a_conversion_location_the_objective_does_not_offer_falls_back():
    """A hallucinated destination narrows the plan to the objective's default —
    it must never kill a run that is otherwise fine."""
    spec = _build(brief={**BRIEF, "conversion_location": "ON_EVENT"})
    assert spec.adsets[0].destination_type is DestinationType.WEBSITE


def test_a_users_own_conversion_location_beats_the_briefs():
    """user_info carries a human choice; the brief carries a suggestion."""
    spec = _build(
        user_info={**USER_INFO, "conversion_location": "MESSENGER"},
        brief={**BRIEF, "conversion_location": "WEBSITE"},
    )
    assert spec.adsets[0].destination_type is DestinationType.MESSENGER


def test_a_goal_the_destination_does_not_allow_falls_back():
    """LEAD_GENERATION is legal for the Leads objective and illegal on its
    WEBSITE destination — the exact pair the two-axis matrix exists to reject."""
    spec = _build(
        user_info={**USER_INFO, "campaign_objective": "LEADS",
                   "conversion_location": "WEBSITE", "pixel_id": "px1",
                   "has_warm_dataset": True},
        brief={**BRIEF, "optimization_goal": "LEAD_GENERATION"},
    )
    assert spec.adsets[0].optimization_goal is OptimizationGoal.OFFSITE_CONVERSIONS


def test_a_capped_bid_strategy_is_declined_not_guessed_at():
    """COST_CAP needs a bid_amount the brief has no number for. Inventing one is
    inventing a spend limit, so the pick is declined and the editor asks."""
    spec = _build(brief={**BRIEF, "bid_strategy": "COST_CAP at ~1.5x estimated CPA"})
    assert spec.adsets[0].bid_strategy is BidStrategy.LOWEST_COST_WITHOUT_CAP
    assert spec.adsets[0].bid_amount is None


def test_the_bid_strategy_default_is_intersected_with_the_goal():
    """Awareness allows COST_CAP; its REACH goal does not — a frequency goal has
    no per-result cost for Meta to cap. Whatever ships must satisfy both."""
    from app.graph.meta_spec.objective_matrix import goal_rules

    spec = _build(user_info={**USER_INFO, "campaign_objective": "AWARENESS"})
    adset = spec.adsets[0]
    assert goal_rules(adset.optimization_goal).allows_bid_strategy(adset.bid_strategy.value)


def test_cbo_moves_the_budget_to_the_campaign():
    """CBO means one budget Meta distributes. The card said CBO and the spec was
    always per-ad-set — visibly contradicting itself on the same screen."""
    spec = _build(brief={**BRIEF, "budget_optimization_type": "CBO — three ad sets"})
    assert spec.has_campaign_budget
    assert spec.daily_budget == 5000
    assert spec.bid_strategy is BidStrategy.LOWEST_COST_WITHOUT_CAP
    assert all(a.daily_budget is None and a.lifetime_budget is None for a in spec.adsets)


def test_abo_keeps_the_budget_on_each_adset():
    spec = _build(brief={**BRIEF, "budget_optimization_type": "ABO — testing audiences"})
    assert not spec.has_campaign_budget
    assert [a.daily_budget for a in spec.adsets] == [3500, 1500]


def test_the_brief_sets_the_frequency_cap_on_a_capped_goal():
    spec = _build(
        user_info={**USER_INFO, "campaign_objective": "AWARENESS"},
        brief={**BRIEF, "frequency_recommendation": "Cap 3/week to avoid fatigue"},
    )
    cap = spec.adsets[0].frequency_control_specs[0]
    assert (cap.max_frequency, cap.interval_days) == (3, 7)


def test_no_cap_is_honoured():
    spec = _build(
        user_info={**USER_INFO, "campaign_objective": "AWARENESS"},
        brief={**BRIEF, "frequency_recommendation": "No cap — the lookalike refreshes"},
    )
    assert spec.adsets[0].frequency_control_specs is None


def test_an_unparseable_cap_falls_back_to_metas_default_not_to_no_cap():
    """The brief asked for a cap either way, and the field is immutable once the
    ad set is written — so a bad parse must not silently uncap delivery."""
    spec = _build(
        user_info={**USER_INFO, "campaign_objective": "AWARENESS"},
        brief={**BRIEF, "frequency_recommendation": "keep it sensible"},
    )
    cap = spec.adsets[0].frequency_control_specs[0]
    assert (cap.max_frequency, cap.interval_days) == (
        FREQUENCY_DEFAULT_MAX, FREQUENCY_DEFAULT_INTERVAL_DAYS
    )


def test_a_frequency_cap_never_leaks_onto_a_goal_that_rejects_it():
    """LINK_CLICKS is not a frequency goal — Meta rejects the field there however
    loudly the brief recommends one."""
    spec = _build(brief={**BRIEF, "frequency_recommendation": "Cap 2/week"})
    assert spec.adsets[0].frequency_control_specs is None


def test_named_platforms_restrict_delivery():
    spec = _build(brief={**BRIEF, "placement_strategy": "Facebook Feed + Instagram Feed"})
    assert spec.adsets[0].targeting["publisher_platforms"] == ["facebook", "instagram"]


def test_advantage_plus_placements_stay_absent():
    """An absent publisher_platforms key IS Advantage+ placements."""
    spec = _build(brief={**BRIEF, "placement_strategy": "Advantage+ placements"})
    assert "publisher_platforms" not in spec.adsets[0].targeting


def test_a_vague_placement_strategy_leaves_placements_automatic():
    spec = _build(brief={**BRIEF, "placement_strategy": "wherever converts best"})
    assert "publisher_platforms" not in spec.adsets[0].targeting


# ── campaign name month ──────────────────────────────────────────────────────
# The brief has no clock: it named an August 2026 campaign "May 2024". The month
# is stamped from the resolved flight start instead, whatever the brief guessed.


def test_campaign_name_carries_the_real_launch_month():
    spec = _build()
    assert spec.name == "Summer Traffic · Aug 2026"


def test_a_month_the_brief_guessed_is_replaced_not_appended():
    spec = _build(brief={**BRIEF, "campaign_name": "Bean There — Traffic | May 2024"})
    assert spec.name == "Traffic · Aug 2026"


def test_the_fallback_name_is_dated_too():
    spec = _build(brief={k: v for k, v in BRIEF.items() if k != "campaign_name"})
    assert spec.name.endswith(" · Aug 2026")


# ── boost destinations ───────────────────────────────────────────────────────
# "On your post" is an ad that IS an existing Page post. The brief cannot know
# which post exists, so a suggested one built a plan that opened on a blocking
# object_story_id error beside copy the destination ignores.


def test_a_boost_destination_suggested_by_the_brief_is_ignored():
    spec = _build(
        user_info={**USER_INFO, "campaign_objective": "ENGAGEMENT"},
        brief={**BRIEF, "conversion_location": "ON_POST"},
    )
    assert spec.adsets[0].destination_type is not DestinationType.ON_POST


def test_the_user_can_still_choose_a_boost_destination_deliberately():
    """Chosen in the editor, it arrives in user_info and must be honoured — that
    is the path where the post picker appears."""
    tree = _tree(
        user_info={
            **USER_INFO,
            "campaign_objective": "ENGAGEMENT",
            "conversion_location": "ON_POST",
        },
    )
    assert tree["adsets"][0]["destination_type"] == "ON_POST"


def test_the_brief_is_never_offered_a_location_it_cannot_launch():
    from app.graph.builder.executors.campaign import _objective_options

    offered = {
        d["value"]
        for d in _objective_options("ENGAGEMENT", {"business_name": "Bean There"})[
            "conversion_locations"
        ]
    }
    # No post to boost, and no website URL in user_info.
    assert not offered & {"ON_POST", "ON_VIDEO", "ON_EVENT", "WEBSITE"}
    assert offered, "engagement still has messaging and Page locations"

    with_site = {
        d["value"]
        for d in _objective_options("ENGAGEMENT", USER_INFO)["conversion_locations"]
    }
    assert "WEBSITE" in with_site


def test_a_zero_decimal_account_publishes_whole_units_not_hundredths():
    """The money test. Meta stores budgets in the ad account currency's MINOR
    unit, and JPY has none — its number IS whole yen. Treating it as cents
    everywhere means a ¥500 budget publishes as ¥50,000."""
    spec = _build(
        user_info={
            **USER_INFO,
            "budget": "JPY 500/day",
            "ad_account_currency": "JPY",
            "min_daily_budget": 100,
        },
        brief={**BRIEF, "budget_optimization_type": "CBO — one budget"},
    )
    assert spec.daily_budget == 500

    # Same number, two-decimal account: 500 whole units is 50,000 minor ones.
    spec = _build(
        user_info={
            **USER_INFO,
            "budget": "৳500/day",
            "ad_account_currency": "BDT",
            "min_daily_budget": 12435,
        },
        brief={**BRIEF, "budget_optimization_type": "CBO — one budget"},
    )
    assert spec.daily_budget == 50000
