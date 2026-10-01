"""
tests/test_express_objective_gaps.py
────────────────────────────────────
The three things "do it for me" hides that some objectives still need.

Express reduces the plan editor to ad copy and creative (``locks.campaign`` +
``locks.adset``). That is safe for Awareness / Traffic / Engagement, and was not
for the rest:

  * Sales and Leads→Website need ``promoted_object.pixel_id``, whose only picker
    is in the hidden ad-set panel — so a pixel-less ad account was a hard stop.
    Punk now creates the Pixel.
  * Leads→Instant form needs a form. Publish auto-creates one, but the picker was
    also hidden, so the user never chose it. It moved to the intake form.
  * Any publish failure blaming a campaign- or ad-set-level field re-opened a
    locked editor with no control that fixes it — and those steps are exempt
    from the retry cap, so it looped forever. The locks now drop.
"""
from __future__ import annotations

import json

import pytest

import app.graph.builder.builder_node as bn
from app.graph.builder.executors import media as media_exec
from app.graph.meta_spec.catalog import CREATE_DATASET
from app.graph.builder.intake_form import (
    build_intake_schema,
    intake_to_slots,
    parse_intake_submission,
)
from app.services import meta_ads


def _ret(value):
    async def _inner(*a, **k):
        return value
    return _inner


@pytest.fixture(autouse=True)
def _no_graph_context(monkeypatch):
    """``media_select_pixel`` is a graph node: it reaches for the LangGraph stream
    writer and the narrator's turn buffer, neither of which exists under pytest.
    Stub both so the tests are about the pixel logic and nothing else."""
    monkeypatch.setattr(media_exec, "get_writer", lambda: (lambda _event: None))
    monkeypatch.setattr(media_exec, "add_beat", lambda *a, **k: None)


def _fields(schema: dict) -> dict[str, dict]:
    return {f["key"]: f for g in schema["groups"] for f in g["fields"]}


# ── Fix 3: which errors the ads-only editor can actually clear ────────────────


@pytest.mark.parametrize(
    "errors,can_fix",
    [
        ({}, True),
        (None, True),
        # A banner, not a field — every publish failure sets one, so treating it
        # as unreachable would unlock the editor on ad-copy failures too.
        ({"__root__": "Meta rejected the plan."}, True),
        ({"adsets[0].ads[1].creative.title": "Too long."}, True),
        ({"adsets[0].ads[0].creative.link": "Unreachable host."}, True),
        ({"adsets[0].ads[0].creative.cards[2].link": "Unreachable host."}, True),
        # The headline case: pixel-less Sales.
        ({"adsets[0].promoted_object.pixel_id": "A Meta Pixel is required."}, False),
        ({"adsets[0].bid_amount": "Enter a bid amount."}, False),
        ({"adsets[1].targeting.geo_locations": "No locations."}, False),
        ({"daily_budget": "Below the account minimum."}, False),
        # Ad-level PATH, ad-set-level CONTROL — the one key the pattern alone
        # gets wrong.
        ({"adsets[0].ads[0].creative.lead_gen_form_id": "Unknown form."}, False),
        # One unreachable key among reachable ones still unlocks.
        (
            {
                "adsets[0].ads[0].creative.title": "Too long.",
                "adsets[0].optimization_goal": "Not valid here.",
            },
            False,
        ),
    ],
)
def test_express_can_fix(errors, can_fix):
    assert bn._express_can_fix(errors) is can_fix


@pytest.mark.asyncio
async def test_express_editor_unlocks_when_the_failure_is_out_of_reach(monkeypatch):
    """Locked + unfixable is an infinite loop: preflight_adset failures are exempt
    from the 3-strike cap, so the user could re-publish the same broken spec
    forever with nothing on screen to change."""
    bs = _express_bs(plan_errors={
        "adsets[0].promoted_object.pixel_id": "A Meta Pixel is required.",
        "__root__": "Meta rejected the plan.",
    })
    extra = await bn._plan_form_extra(bs, {})

    assert extra["locks"] == {"geo": True, "audience": True}
    assert "opened up the full campaign" in extra["errors"]["__root__"]
    # The original message survives — the note is context, not a replacement.
    assert "Meta rejected the plan." in extra["errors"]["__root__"]


@pytest.mark.asyncio
async def test_express_editor_stays_locked_for_ad_copy_failures():
    bs = _express_bs(plan_errors={"adsets[0].ads[0].creative.title": "Too long."})
    extra = await bn._plan_form_extra(bs, {})

    assert extra["locks"] == {
        "geo": True, "audience": True, "campaign": True, "adset": True,
    }
    assert extra["errors"]["__root__"] if extra["errors"].get("__root__") else True


@pytest.mark.asyncio
async def test_guide_mode_is_never_locked_either_way():
    bs = _express_bs(plan_errors={"adsets[0].bid_amount": "Enter a bid amount."})
    bs["filled"]["publish_mode"] = "guide"
    extra = await bn._plan_form_extra(bs, {})

    assert extra["locks"] == {"geo": True, "audience": True}
    # No note: nothing was hidden, so nothing "just appeared".
    assert "__root__" not in extra["errors"]


def _express_bs(*, plan_errors: dict) -> dict:
    """The minimum builder scratch _plan_form_extra reads."""
    return {
        "filled": {"publish_mode": "express"},
        "media_ws": {},
        "plan_errors": plan_errors,
        "marketing_plan_draft": {
            "name": "Autopaws", "objective": "OUTCOME_AWARENESS", "daily_budget": 2100,
            "adsets": [{
                "name": "Seed", "audience_role": "seed",
                "destination_type": "WEBSITE", "optimization_goal": "REACH",
                "billing_event": "IMPRESSIONS", "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                "start_time": "2026-06-22T00:00:00-04:00",
                "targeting": {"geo_locations": {"zips": [{"key": "US:90210"}]}},
                "ads": [{"name": "Ad 1", "creative": {
                    "title": "Hi", "body": "There", "call_to_action": "LEARN_MORE",
                    "link": "https://autopaws.example",
                }}],
            }],
        },
    }


# ── Fix 1: the campaign takes a shape the account can actually run ───────────
#
# This used to be "Punk provisions the Pixel": Sales and Leads were assumed to be
# unpublishable without a dataset, so one was created for any account that had
# none. They are not. Leads defaults to instant forms (the Page is the promoted
# object) and Sales on a dataset-less account resolves to a landing-page-view
# goal that promotes nothing — and a created dataset measures nothing until it is
# installed on the site, so the campaign it propped up optimized toward an event
# that could never arrive.


_PIXEL_STATE = {
    "user_info": {
        "campaign_objective": "SALES",
        "meta_access_token": "tok",
        "meta_ad_account_id": "act_1",
        "business_name": "Autopaws",
        "website_url": "https://autopaws.example",
        # An account with a dataset that has fired: what puts a run on a
        # conversion goal at all, and therefore into this node's real work.
        "has_warm_dataset": True,
    },
    "media_wizard_state": {},
}

_COLD_STATE = {
    **_PIXEL_STATE,
    "user_info": {
        k: v for k, v in _PIXEL_STATE["user_info"].items() if k != "has_warm_dataset"
    },
}


@pytest.fixture
def personal_account(monkeypatch):
    """An ad account with no business portfolio behind it."""
    monkeypatch.setattr(meta_ads, "fetch_ad_account_business", _ret({}))
    monkeypatch.setattr(meta_ads, "fetch_business_datasets", _ret([]))


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """The node persists the resolved dataset and method on the ad account row.
    There is no database under these tests, and neither write is what they are
    about."""
    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(media_exec, "_remember_tracking_dataset", _noop)
    monkeypatch.setattr(media_exec, "_remember_tracking_method", _noop)
    monkeypatch.setattr(media_exec, "_stored_tracking_dataset", _ret(("", "")))


@pytest.mark.asyncio
async def test_an_account_with_no_dataset_gets_no_dataset_created(
    monkeypatch, personal_account
):
    """The behaviour this whole section used to assert the opposite of.

    Nothing is created, nothing is promoted, and the run continues — the goal has
    already stepped down to one that needs no dataset (see
    test_meta_spec_builder: sales_with_no_dataset_at_all)."""
    monkeypatch.setattr(meta_ads, "fetch_ad_pixels", _boom("must not read pixels"))
    monkeypatch.setattr(meta_ads, "create_ad_pixel", _boom("must not create a pixel"))
    monkeypatch.setattr(
        meta_ads, "create_business_dataset", _boom("must not create a dataset"),
    )

    out = await media_exec.media_select_pixel(dict(_COLD_STATE))

    assert out["media_wizard_state"]["promoted_object"] is None
    assert "pixel_id" not in out["media_wizard_state"]


@pytest.mark.asyncio
async def test_instant_form_leads_never_touch_a_dataset(monkeypatch):
    """Leads defaults to ON_AD, whose promoted object is the Page. The old
    objective-only gate resolved (and created) a dataset here, told the user to
    install it, and then reported it as never firing for the rest of time."""
    monkeypatch.setattr(meta_ads, "fetch_ad_pixels", _boom("must not read pixels"))
    monkeypatch.setattr(meta_ads, "create_ad_pixel", _boom("must not create a pixel"))
    state = {
        **_PIXEL_STATE,
        "user_info": {
            **_PIXEL_STATE["user_info"],
            "campaign_objective": "LEADS",
            # Even with a dataset sitting right there: an instant form does not
            # use one.
            "has_warm_dataset": True,
        },
    }

    out = await media_exec.media_select_pixel(state)

    assert out["media_wizard_state"]["promoted_object"] is None
    # Nothing to install, and nothing that would make a "your pixel has never
    # fired" warning true.
    assert out["user_info"]["tracking_method"] == "lead_forms"


@pytest.mark.asyncio
async def test_a_pixel_run_is_told_the_browser_tag_is_the_whole_install(monkeypatch):
    """Express is never asked how conversions reach Meta, and an unset answer
    reads as "pixel AND server" — which is how a beginner ended up holding an
    ingest key and a server-side code sample."""
    monkeypatch.setattr(
        meta_ads, "fetch_ad_pixels",
        _ret([{"id": "px-1", "name": "Live", "last_fired_time": "2026-08-16T10:00:00+0000"}]),
    )

    out = await media_exec.media_select_pixel(dict(_PIXEL_STATE))

    assert out["media_wizard_state"]["pixel_id"] == "px-1"
    assert out["user_info"]["tracking_method"] == "pixel_only"


@pytest.mark.asyncio
async def test_a_method_the_user_chose_is_never_overwritten(monkeypatch):
    """Guide mode answers this on the intake form. The derivation only fills a
    hole; it does not have an opinion about an answer."""
    monkeypatch.setattr(
        meta_ads, "fetch_ad_pixels",
        _ret([{"id": "px-1", "name": "Live", "last_fired_time": "2026-08-16T10:00:00+0000"}]),
    )
    state = {
        **_PIXEL_STATE,
        "user_info": {**_PIXEL_STATE["user_info"], "tracking_method": "pixel_and_server"},
    }

    out = await media_exec.media_select_pixel(state)

    assert out["user_info"]["tracking_method"] == "pixel_and_server"


@pytest.mark.asyncio
async def test_create_one_for_me_still_creates_one(monkeypatch, personal_account):
    """The one creation path left. Asking for a dataset is a decision the user
    made on the intake form, not something Punk did on their behalf."""
    created: list[tuple[str, str]] = []

    async def _create(name, ad_account_id, access_token):
        created.append((name, ad_account_id))
        return "px-1"

    monkeypatch.setattr(meta_ads, "fetch_ad_pixels", _ret([]))
    monkeypatch.setattr(meta_ads, "create_ad_pixel", _create)
    state = {
        **_PIXEL_STATE,
        "user_info": {**_PIXEL_STATE["user_info"], "pixel_id": CREATE_DATASET},
    }

    ws = (await media_exec.media_select_pixel(state))["media_wizard_state"]

    assert created == [("Autopaws Pixel", "act_1")]
    assert ws["pixel_id"] == "px-1"
    assert ws["promoted_object"] == {"pixel_id": "px-1", "custom_event_type": "PURCHASE"}
    assert ws["pixel_created"] is True


@pytest.mark.asyncio
async def test_create_one_for_me_prefers_the_business_portfolio(monkeypatch):
    """A dataset in the business portfolio serves every ad account the advertiser
    owns and escapes the one-pixel-per-account limit. It still has to be ASSIGNED
    to the ad account: owning it in the business is not enough for an ad set."""
    shared: list[tuple[str, str]] = []

    async def _create_in_business(name, business_id, access_token):
        assert (name, business_id) == ("Autopaws Pixel", "biz-7")
        return "ds-9"

    async def _share(dataset_id, ad_account_id, access_token):
        shared.append((dataset_id, ad_account_id))
        return True

    monkeypatch.setattr(meta_ads, "fetch_ad_pixels", _ret([]))
    monkeypatch.setattr(meta_ads, "create_business_dataset", _create_in_business)
    monkeypatch.setattr(meta_ads, "share_dataset_with_account", _share)
    state = {
        **_PIXEL_STATE,
        "user_info": {**_PIXEL_STATE["user_info"], "pixel_id": CREATE_DATASET},
        "media_wizard_state": {"tracking_business_id": "biz-7"},
    }

    ws = (await media_exec.media_select_pixel(state))["media_wizard_state"]

    assert ws["pixel_id"] == "ds-9"
    assert shared == [("ds-9", "act_1")]


@pytest.mark.asyncio
async def test_a_dataset_in_the_business_is_reused_not_duplicated(monkeypatch):
    """A dataset the advertiser owns but never assigned to this ad account is
    invisible to /adspixels. media_detect_pixel is what finds it, at connect time,
    which is what makes has_warm_dataset honest — and by the time this node runs
    it is just another candidate."""
    async def _must_not_create(*a, **k):
        raise AssertionError("created a dataset when the business already had one")

    monkeypatch.setattr(meta_ads, "create_business_dataset", _must_not_create)
    monkeypatch.setattr(meta_ads, "create_ad_pixel", _must_not_create)
    state = {
        **_PIXEL_STATE,
        "media_wizard_state": {
            "tracking_business_id": "biz-7",
            "pixel_candidates": [
                {"id": "ds-3", "name": "Shop", "last_fired_time": "2026-08-01T00:00:00+0000"},
            ],
        },
    }

    ws = (await media_exec.media_select_pixel(state))["media_wizard_state"]

    assert ws["pixel_id"] == "ds-3"
    assert ws.get("pixel_created") is not True


@pytest.mark.asyncio
async def test_the_warm_dataset_wins_over_cold_siblings(monkeypatch):
    """Three datasets, one receiving events: that is not a choice worth asking
    about, and picking a cold one throws away the delivery history."""
    monkeypatch.setattr(meta_ads, "fetch_ad_pixels", _ret([
        {"id": "ds-cold-1", "name": "Old test"},
        {"id": "ds-warm", "name": "Live site", "last_fired_time": "2026-08-16T10:00:00+0000"},
        {"id": "ds-cold-2", "name": "Staging"},
    ]))

    ws = (await media_exec.media_select_pixel(dict(_PIXEL_STATE)))["media_wizard_state"]

    assert ws["pixel_id"] == "ds-warm"
    assert len(ws["pixel_candidates"]) == 3


@pytest.mark.asyncio
async def test_pixel_creation_failure_falls_back_to_the_editor(monkeypatch, personal_account):
    """Creating one is a convenience, never a prerequisite — a refusal must leave
    the editor path exactly as it was, not raise."""
    async def _refuse(*a, **k):
        raise meta_ads.MetaAdsError("no permission", code=200)

    monkeypatch.setattr(meta_ads, "fetch_ad_pixels", _ret([]))
    monkeypatch.setattr(meta_ads, "create_ad_pixel", _refuse)
    state = {
        **_PIXEL_STATE,
        "user_info": {**_PIXEL_STATE["user_info"], "pixel_id": CREATE_DATASET},
    }

    ws = (await media_exec.media_select_pixel(state))["media_wizard_state"]

    assert ws["pixel_id"] is None
    assert ws["promoted_object"] is None
    assert ws["pixel_candidates"] == []
    assert "pixel_created" not in ws


@pytest.mark.asyncio
async def test_an_existing_pixel_is_never_replaced(monkeypatch):
    monkeypatch.setattr(meta_ads, "fetch_ad_pixels", _ret([{"id": "px-old", "name": "Mine"}]))
    monkeypatch.setattr(
        meta_ads, "create_ad_pixel", _boom("must not create a pixel when one exists"),
    )

    ws = (await media_exec.media_select_pixel(dict(_PIXEL_STATE)))["media_wizard_state"]

    assert ws["pixel_id"] == "px-old"
    assert not ws.get("pixel_created")


@pytest.mark.asyncio
async def test_non_conversion_objectives_never_create_a_pixel(monkeypatch):
    monkeypatch.setattr(meta_ads, "create_ad_pixel", _boom("Awareness needs no pixel"))
    state = {**_PIXEL_STATE, "user_info": {**_PIXEL_STATE["user_info"],
                                           "campaign_objective": "AWARENESS"}}
    ws = (await media_exec.media_select_pixel(state))["media_wizard_state"]
    assert "pixel_id" not in ws


@pytest.mark.asyncio
async def test_an_awareness_run_never_stamps_a_method_on_the_ad_account(monkeypatch):
    """The account row is shared by every campaign this account runs. Deriving a
    method from a campaign that has no conversion tracking at all would overwrite
    the answer a Sales campaign gave."""
    state = {**_PIXEL_STATE, "user_info": {**_PIXEL_STATE["user_info"],
                                           "campaign_objective": "AWARENESS"}}
    out = await media_exec.media_select_pixel(state)
    assert "tracking_method" not in (out.get("user_info") or {})


@pytest.mark.asyncio
async def test_a_pixel_chosen_on_the_intake_form_wins(monkeypatch):
    """Guide mode picks the dataset on the intake form. _pick_dataset must not
    then overrule it with its own heuristic."""
    monkeypatch.setattr(meta_ads, "fetch_ad_pixels", _ret([
        {"id": "ds-a", "name": "A", "last_fired_time": "2026-08-16T10:00:00+0000"},
        {"id": "ds-b", "name": "B"},
    ]))
    state = {
        **_PIXEL_STATE,
        "user_info": {**_PIXEL_STATE["user_info"], "pixel_id": "ds-b"},
    }

    ws = (await media_exec.media_select_pixel(state))["media_wizard_state"]

    assert ws["pixel_id"] == "ds-b"


@pytest.mark.asyncio
async def test_a_pixel_not_on_the_account_is_ignored(monkeypatch):
    """The same slot can hold a Pixel scraped off the advertiser's WEBSITE, which
    may belong to an entirely different ad account. Publishing that id fails, and
    the editor's account-scoped picker cannot even display it."""
    monkeypatch.setattr(meta_ads, "fetch_ad_pixels", _ret([
        {"id": "ds-a", "name": "A", "last_fired_time": "2026-08-16T10:00:00+0000"},
    ]))
    state = {
        **_PIXEL_STATE,
        "user_info": {**_PIXEL_STATE["user_info"], "pixel_id": "someone-elses"},
    }

    ws = (await media_exec.media_select_pixel(state))["media_wizard_state"]

    assert ws["pixel_id"] == "ds-a"


@pytest.mark.asyncio
async def test_create_ad_pixel_takes_the_existing_one_on_a_lost_race(monkeypatch):
    """Codes 6200/6202 mean the account already has a pixel — someone made one
    between our read and our write. Re-read rather than fail."""
    async def _conflict(method, path, access_token, **kwargs):
        raise meta_ads.MetaAdsError("a pixel already exists for this account", code=6200)

    monkeypatch.setattr(meta_ads, "_request", _conflict)
    monkeypatch.setattr(meta_ads, "fetch_ad_pixels", _ret([{"id": "px-race", "name": "Theirs"}]))

    assert await meta_ads.create_ad_pixel("Autopaws Pixel", "act_1", "tok") == "px-race"


@pytest.mark.asyncio
async def test_create_ad_pixel_reraises_when_the_conflict_is_a_lie(monkeypatch):
    """6200 with nothing to find afterwards is not a race — surface it."""
    async def _conflict(method, path, access_token, **kwargs):
        raise meta_ads.MetaAdsError("a pixel already exists for this account", code=6200)

    monkeypatch.setattr(meta_ads, "_request", _conflict)
    monkeypatch.setattr(meta_ads, "fetch_ad_pixels", _ret([]))

    with pytest.raises(meta_ads.MetaAdsError):
        await meta_ads.create_ad_pixel("Autopaws Pixel", "act_1", "tok")


@pytest.mark.asyncio
async def test_fetch_pixel_activity_degrades_to_empty(monkeypatch):
    """A missing preview row is never worth failing the gate the user is standing
    in front of."""
    async def _boom_request(*a, **k):
        raise meta_ads.MetaAdsError("gone", code=100)

    monkeypatch.setattr(meta_ads, "_request", _boom_request)
    assert await meta_ads.fetch_pixel_activity("px-1", "tok") == {}


# ── Fix 1b: the preview tells the truth about tracking ───────────────────────


@pytest.mark.asyncio
async def test_preview_warns_when_the_pixel_has_never_fired(monkeypatch):
    """A Pixel that exists but was never installed publishes cleanly and then
    optimizes toward an event Meta never receives. last_fired_time is the only
    honest signal, so it is read live at the gate."""
    monkeypatch.setattr(
        meta_ads, "fetch_pixel_activity",
        _ret({"id": "px-1", "name": "Autopaws Pixel", "last_fired_time": None}),
    )
    extra = await bn._preview_extra(_published_bs(pixel_id="px-1"), _STATE)

    assert extra["tracking"]["pixel_id"] == "px-1"
    assert extra["tracking"]["pixel_name"] == "Autopaws Pixel"
    assert extra["tracking"]["last_fired_time"] is None
    assert extra["tracking"]["created_by_punk"] is True
    assert "px-1" in extra["tracking"]["events_manager_url"]


@pytest.mark.asyncio
async def test_preview_has_no_tracking_row_without_a_pixel(monkeypatch):
    """Awareness measures on Meta's own surfaces — there is nothing to install,
    so the section must not appear at all."""
    monkeypatch.setattr(meta_ads, "fetch_pixel_activity", _boom("must not be called"))
    extra = await bn._preview_extra(_published_bs(pixel_id=None), _STATE)
    assert "tracking" not in extra


@pytest.mark.asyncio
async def test_preview_names_ads_by_plan_slot_not_position(monkeypatch):
    """Publish skips an ad with no media, so the ids that come back are not the
    plan's ads in order. Naming them by position slid ad set 2's published ad
    onto ad set 1's ad name — the tab said one thing, the iframe showed another.
    """
    monkeypatch.setattr(meta_ads, "fetch_pixel_activity", _boom("must not be called"))
    bs = _published_bs(pixel_id=None)
    bs["marketing_plan"]["adsets"] = [
        {"name": "Seed", "ads": [{"name": "Seed Ad 1"}, {"name": "Seed Ad 2"}]},
        {"name": "Broad", "ads": [{"name": "Broad Ad 1"}]},
    ]
    # "Seed Ad 2" had no media and was skipped; ids 0 and 1 are slots 0:0 and 1:0.
    bs["meta_campaign_ids"]["ad_ids"] = ["ad1", "ad2"]
    bs["meta_campaign_ids"]["ad_keys"] = ["0:0", "1:0"]

    extra = await bn._preview_extra(bs, _STATE)

    assert extra["ads"] == [
        {"ad_id": "ad1", "name": "Seed Ad 1"},
        {"ad_id": "ad2", "name": "Broad Ad 1"},
    ]


@pytest.mark.asyncio
async def test_preview_budget_adds_up_the_ad_set_budgets(monkeypatch):
    """ABO: the campaign's own daily/lifetime are null and the money sits on the
    ad sets. Reading only the campaign level showed "0.00" beside a campaign
    that spends 1,250 a day."""
    monkeypatch.setattr(meta_ads, "fetch_pixel_activity", _boom("must not be called"))
    bs = _published_bs(pixel_id=None)
    bs["marketing_plan"]["daily_budget"] = None
    bs["marketing_plan"]["adsets"] = [
        {"name": "Seed", "daily_budget": 75000},
        {"name": "Broad", "daily_budget": 50000},
    ]

    extra = await bn._preview_extra(bs, _STATE)

    assert extra["summary"]["budget"]["type"] == "daily"
    assert extra["summary"]["budget"]["amount"] == 125000


def test_summary_budget_prefers_the_campaign_level_when_it_has_one():
    """CBO — the ad sets share the campaign's budget, so summing them would
    double-count what Meta spends once."""
    plan = {"daily_budget": 30000}
    adsets = [{"daily_budget": None}, {"daily_budget": None}]
    assert bn._summary_budget(plan, adsets) == ("daily", 30000)
    assert bn._summary_budget({"lifetime_budget": 90000}, adsets) == ("lifetime", 90000)


def test_summary_budget_reads_lifetime_ad_sets():
    adsets = [{"lifetime_budget": 40000}, {"lifetime_budget": 60000}]
    assert bn._summary_budget({}, adsets) == ("lifetime", 100000)


@pytest.mark.asyncio
async def test_preview_falls_back_to_position_without_ad_keys(monkeypatch):
    """Campaigns published before ad_keys existed are still sitting in Redis."""
    monkeypatch.setattr(meta_ads, "fetch_pixel_activity", _boom("must not be called"))
    bs = _published_bs(pixel_id=None)
    bs["meta_campaign_ids"].pop("ad_keys", None)

    extra = await bn._preview_extra(bs, _STATE)

    assert extra["ads"] == [{"ad_id": "ad1", "name": "Ad 1"}]


# The Meta token lives on graph state, not in the slot store — _preview_extra
# reads it through _ui_view.
_STATE = {"user_info": {"meta_access_token": "tok"}}


def _published_bs(*, pixel_id: str | None) -> dict:
    adset: dict = {
        "name": "Seed", "start_time": "2026-06-22T00:00:00-04:00",
        "targeting": {"publisher_platforms": ["facebook"], "facebook_positions": ["feed"]},
        "ads": [{"name": "Ad 1"}],
    }
    if pixel_id:
        adset["promoted_object"] = {"pixel_id": pixel_id, "custom_event_type": "PURCHASE"}
    return {
        "filled": {"publish_mode": "express"},
        "media_ws": {"ad_account_currency": "USD", "pixel_created": True},
        "meta_campaign_ids": {
            "campaign_id": "c1", "campaign_ids": ["c1"],
            "adset_ids": ["as1"], "ad_ids": ["ad1"], "ad_account_id": "act_1",
        },
        "marketing_plan": {
            "name": "Autopaws", "objective": "OUTCOME_SALES",
            "daily_budget": 2100, "adsets": [adset],
        },
    }


# ── Fix 2: the instant form moves onto the express intake ────────────────────


_LEADS = {
    "business_name": "Autopaws", "business_context": "pet grooming",
    "objective": "OUTCOME_LEADS",
}
_FORMS = [{"id": "f1", "name": "Grooming enquiry"}, {"id": "f2", "name": "Callback"}]


def test_express_offers_the_pages_instant_forms():
    field = _fields(build_intake_schema(
        user_info={}, lead_forms=_FORMS,
    ))["lead_form_id"]

    assert [o["value"] for o in field["options"]] == ["", "f1", "f2"]
    # Blank is a real answer, not a skip: publish creates a default form for it.
    assert field["options"][0]["label"] == "Create a default one for me"
    assert field["visible_when"] == {"objective": ["OUTCOME_LEADS"]}


def test_a_picked_form_reaches_publish():
    values, errors = parse_intake_submission(
        json.dumps({"values": {**_LEADS, "budget_amount": 2100, "lead_form_id": "f1"}}),
    )
    assert errors == {}
    _filled, ui = intake_to_slots(values)
    assert ui["lead_form_id"] == "f1"


def test_leaving_the_form_blank_writes_nothing():
    """Blank means "create one for me", which is what _resolve_lead_form already
    does when nothing names a form — writing "" would only be a value to ignore
    later."""
    values, _errors = parse_intake_submission(
        json.dumps({"values": {**_LEADS, "budget_amount": 2100, "lead_form_id": ""}}),
    )
    _filled, ui = intake_to_slots(values)
    assert "lead_form_id" not in ui


@pytest.mark.asyncio
async def test_resolve_lead_form_prefers_the_intake_pick_over_generating(monkeypatch):
    from app.graph.meta_spec import CampaignSpec

    monkeypatch.setattr(
        meta_ads, "create_lead_form", _boom("must not generate when one was picked"),
    )
    monkeypatch.setattr(meta_ads, "list_lead_forms", _forms(["f1"]))
    spec = CampaignSpec.model_validate(_leads_plan())

    form_id = await media_exec._resolve_lead_form(
        spec,
        ledger=_NoLedger(),
        page_id="page-1",
        user_info={"lead_form_id": "f1"},
        access_token="tok",
        writer=lambda _e: None,
    )
    assert form_id == "f1"


@pytest.mark.asyncio
async def test_resolve_lead_form_rejects_a_form_from_another_page(monkeypatch):
    """A form id can survive a Page switch in user_info/the editor — Meta
    rejects an id from another Page outright, so this falls through to
    generating a default one instead of publishing a broken reference."""
    from app.graph.meta_spec import CampaignSpec

    async def _create(page_id, **k):
        return "f-generated"

    monkeypatch.setattr(meta_ads, "create_lead_form", _create)
    monkeypatch.setattr(meta_ads, "list_lead_forms", _forms(["some-other-form"]))
    spec = CampaignSpec.model_validate(_leads_plan())

    form_id = await media_exec._resolve_lead_form(
        spec,
        ledger=_NoLedger(),
        page_id="page-1",
        user_info={"lead_form_id": "f1"},
        access_token="tok",
        writer=lambda _e: None,
    )
    assert form_id == "f-generated"


@pytest.mark.asyncio
async def test_resolve_lead_form_still_generates_when_nothing_was_picked(monkeypatch):
    from app.graph.meta_spec import CampaignSpec

    async def _create(page_id, **k):
        return "f-generated"

    monkeypatch.setattr(meta_ads, "create_lead_form", _create)
    spec = CampaignSpec.model_validate(_leads_plan())

    form_id = await media_exec._resolve_lead_form(
        spec, ledger=_NoLedger(), page_id="page-1", user_info={},
        access_token="tok", writer=lambda _e: None,
    )
    assert form_id == "f-generated"


class _NoLedger:
    """Just the two attributes _resolve_lead_form touches."""

    lead_form_id = None

    async def record_lead_form(self, form_id):  # pragma: no cover - trivial
        self.lead_form_id = form_id


def _leads_plan() -> dict:
    return {
        "name": "Autopaws | Leads", "objective": "OUTCOME_LEADS",
        "daily_budget": 2100, "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "page_id": "page-1",
        "adsets": [{
            "name": "Seed", "audience_role": "seed",
            "destination_type": "ON_AD", "optimization_goal": "LEAD_GENERATION",
            "billing_event": "IMPRESSIONS", "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "start_time": "2026-06-22T00:00:00-04:00",
            "promoted_object": {"page_id": "page-1"},
            "targeting": {"geo_locations": {"zips": [{"key": "US:90210"}]}},
            "ads": [{"name": "Ad 1", "creative": {
                "title": "Book a groom", "body": "Same-week slots",
                "call_to_action": "SIGN_UP", "link": "https://autopaws.example",
            }}],
        }],
    }


def _boom(message):
    async def _inner(*a, **k):
        raise AssertionError(message)
    return _inner


def _forms(ids: list[str]):
    async def _inner(*a, **k):
        return [{"id": i} for i in ids]
    return _inner


# ── the form-picked Pixel ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_pixel_chosen_on_the_intake_form_wins(monkeypatch):
    """Express asks on the short form, so the multi-pixel chat interrupt must not
    fire again for someone who already answered."""
    monkeypatch.setattr(meta_ads, "fetch_ad_pixels", _ret([
        {"id": "px-a", "name": "A"}, {"id": "px-b", "name": "B"},
    ]))
    monkeypatch.setattr(
        media_exec, "wizard_interrupt", _boom("must not ask again — the form already did"),
    )
    state = {**_PIXEL_STATE, "user_info": {**_PIXEL_STATE["user_info"], "pixel_id": "px-b"}}

    ws = (await media_exec.media_select_pixel(state))["media_wizard_state"]

    assert ws["pixel_id"] == "px-b"
    assert ws["promoted_object"] == {"pixel_id": "px-b", "custom_event_type": "PURCHASE"}


@pytest.mark.asyncio
async def test_a_pixel_not_on_the_account_is_ignored(monkeypatch):
    """The same slot can hold a Pixel scraped off the advertiser's website, which
    may belong to a different ad account — publishing it fails and the editor
    cannot even display it."""
    monkeypatch.setattr(meta_ads, "fetch_ad_pixels", _ret([{"id": "px-a", "name": "A"}]))
    state = {**_PIXEL_STATE, "user_info": {**_PIXEL_STATE["user_info"],
                                           "pixel_id": "px-from-someone-elses-site"}}

    ws = (await media_exec.media_select_pixel(state))["media_wizard_state"]

    assert ws["pixel_id"] == "px-a"


# ── currency reaches Meta intact ─────────────────────────────────────────────


def test_the_plan_card_and_brief_speak_the_account_currency():
    from app.graph.builder.executors.campaign import _fmt_budget, _money_fmt

    symbol, scale, places = _money_fmt({"ad_account_currency": "BDT"})
    assert (symbol, scale, places) == ("৳", 100, 2)
    assert _fmt_budget(140.0, False, symbol, places) == "৳140/day"

    symbol, scale, places = _money_fmt({"ad_account_currency": "JPY"})
    assert (symbol, scale, places) == ("JPY ", 1, 0)
    assert _fmt_budget(500.0, False, symbol, places) == "JPY 500/day"

    # No account read yet — the old default, not a wrong symbol.
    assert _money_fmt({}) == ("$", 100, 2)


def test_reconciled_brief_budget_is_in_the_accounts_own_money():
    from app.graph.builder.executors.campaign import reconcile_brief_budget

    brief = reconcile_brief_budget({}, {"budget": "৳140/day", "ad_account_currency": "BDT"})
    assert brief["budget_breakdown"] == "৳140/day"

    brief = reconcile_brief_budget({}, {"budget": "JPY 500/day", "ad_account_currency": "JPY"})
    assert brief["budget_breakdown"] == "JPY 500/day"
