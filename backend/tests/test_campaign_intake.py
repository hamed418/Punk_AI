"""
tests/test_campaign_intake.py
─────────────────────────────
The campaign intake form: the dynamic schema the client renders, the pure
validation of a submission, and the mapping onto the filled / user_info shape the
downstream brief and spec builders read.

Express-only now (see intake_form.py's module docstring) — guide mode never
sees this form, so there is no more guide/express split to test here. Most of
these tests still guard what it does NOT ask — everything the plan editor
shows filled in and editable (destination, WhatsApp number, instant-form mode,
which event counts, how conversions reach Meta) is a question that used to be
asked twice, once before the user had seen a plan and once after.
"""
from __future__ import annotations

import json

import pytest

from app.graph.builder.intake_form import (
    build_intake_schema,
    intake_to_slots,
    normalize_url,
    parse_intake_submission,
)


def _fields(schema: dict) -> dict[str, dict]:
    return {f["key"]: f for g in schema["groups"] for f in g["fields"]}


def _shows(condition, **values) -> bool:
    """Evaluate a visible_when the way the client does.

    Mirrors ``conditionMatches`` in DynamicForm.tsx: a list of clauses is OR'd,
    the keys inside one clause are AND'ed. Asserting through this rather than on
    the literal dict keeps the tests about behaviour — which answer shows a field
    — instead of about the shape we happen to emit it in.
    """
    if condition is None:
        return True
    clauses = condition if isinstance(condition, list) else [condition]
    return any(
        all(str(values.get(key, "")) in allowed for key, allowed in clause.items())
        for clause in clauses
    )


# ── schema shape ──────────────────────────────────────────────────────────────


def test_the_form_asks_only_what_cannot_be_defaulted():
    """Guide mode never opens this form at all now (see slots.py) — its
    campaign/ad-set editor panes are wide open, so business name/what-you-sell
    come from the entry gate and the objective is inferred by generate_brief.
    Express still locks those panes entirely, so this is the only surface left
    for what publishing genuinely cannot default: the objective, budget,
    flight, which Page, and where the ad points.

    Single vs. carousel is asked in the ad section of the plan editor
    instead (``AdCard.tsx``) — the editor is the only surface that can run
    the real legality check (which destination/goal combos even allow a
    carousel), so asking here up front would just be a starting point the
    editor immediately has to double-check anyway.
    """
    fields = _fields(build_intake_schema(user_info={}, pages=_PAGES))
    assert set(fields) == {
        "business_name", "business_context", "objective",
        # App Promotion only — hidden for every other objective.
        "app_store_url", "play_store_url",
        # Only when the account has more than one Page.
        "page_id",
        # Only when the connected Page carried none.
        "website_url",
        # Leads only — hidden for the rest.
        "lead_form_id",
        "budget_type", "budget_amount",
        "campaign_start_date", "campaign_end_date",
    }


def test_the_form_no_longer_asks_what_the_plan_editor_shows_filled_in():
    fields = _fields(build_intake_schema(user_info={}))
    for gone in (
        "conversion_location", "duration_mode",
        "whatsapp_number", "lead_form_mode", "start_from_campaign",
        # The ad-set panel's event select and the campaign panel's tracking
        # method select both render these, pre-filled, a few steps later.
        "conversion_event", "tracking_method",
    ):
        assert gone not in fields, gone


def test_objective_options_carry_descriptions():
    obj = _fields(build_intake_schema(user_info={}))["objective"]
    values = {o["value"] for o in obj["options"]}
    assert "OUTCOME_SALES" in values and "OUTCOME_TRAFFIC" in values
    assert all(o.get("description") for o in obj["options"])   # help text per option


def test_store_links_appear_only_for_app_promotion():
    """The one prerequisite with no fallback: Meta needs the app being promoted,
    and a Facebook Page cannot stand in for it the way it can for a website."""
    fields = _fields(build_intake_schema(user_info={}))
    for key in ("app_store_url", "play_store_url"):
        cond = fields[key]["visible_when"]
        assert _shows(cond, objective="OUTCOME_APP_PROMOTION")
        assert not _shows(cond, objective="OUTCOME_SALES")
        assert not _shows(cond, objective="OUTCOME_TRAFFIC")


def test_prefill_flows_into_suggestions():
    fields = _fields(build_intake_schema(user_info={
        "business_name": "Bean There", "business_description": "coffee",
        "campaign_objective": "SALES", "website_url": "https://beanthere.example",
    }))
    assert fields["business_name"]["suggestion"] == "Bean There"
    assert fields["objective"]["suggestion"] == "OUTCOME_SALES"


def test_enrichment_fills_the_business_text_when_the_user_has_not():
    fields = _fields(build_intake_schema(
        user_info={},
        enrichment={"business_name": "Bean There", "products_services": "specialty coffee"},
    ))
    assert fields["business_name"]["suggestion"] == "Bean There"
    assert fields["business_context"]["suggestion"] == "specialty coffee"


# ── validation ────────────────────────────────────────────────────────────────


def _submit(values: dict) -> tuple[dict, dict]:
    return parse_intake_submission(json.dumps({"values": values}))


_OK = {
    "business_name": "Bean There",
    "business_context": "coffee",
    "objective": "TRAFFIC",
}
# This form is express-only now, so a submission always carries the one thing
# publishing genuinely cannot default — see test_express_requires_a_budget.
_SUBMIT_OK = {**_OK, "budget_amount": 2100}


def test_valid_submission_has_no_errors():
    _values, errors = _submit(_SUBMIT_OK)
    assert errors == {}


def test_a_website_is_never_asked_for_or_required():
    """It comes off the connected Page (media_detect_page_assets); absent even
    there, the ad's link falls back to the Page itself and the editor's Link field
    is one click away."""
    _values, errors = _submit(_SUBMIT_OK)
    assert errors == {}


def test_missing_business_and_objective_error():
    _values, errors = _submit({})
    assert "business_name" in errors
    assert "business_context" in errors
    assert "objective" in errors


def test_app_promotion_needs_at_least_one_store_url():
    _v, errors = _submit({
        "business_name": "Fit", "business_context": "workouts",
        "objective": "APP_PROMOTION", "budget_amount": 2100,
    })
    assert "app_store_url" in errors
    _v, ok = _submit({
        "business_name": "Fit", "business_context": "workouts",
        "objective": "APP_PROMOTION", "budget_amount": 2100,
        "play_store_url": "play.google.com/store/apps/details?id=fit",
    })
    assert ok == {}


def test_non_json_reply_is_a_root_error():
    _values, errors = parse_intake_submission("I want more sales")
    assert list(errors) == ["__root__"]


# ── submission → slots ────────────────────────────────────────────────────────


def test_intake_to_slots_maps_filled_and_user_info():
    values, _errors = _submit(_OK)
    filled, ui = intake_to_slots(values)
    assert filled["campaign_intake"] == "done"
    assert filled["objective"] == "TRAFFIC"        # short form for slot predicates
    assert filled["business_name"] == "Bean There"
    assert ui["campaign_objective"] == "TRAFFIC"
    assert ui["business_description"] == "coffee"
    assert ui["product_offer"] == "coffee"


def test_intake_never_writes_website_url():
    """connect_meta resolved it from the Page before this form was shown. Writing
    "" here would overwrite that AND block enrich_website, whose prereqs read the
    slot store."""
    values, _errors = _submit(_OK)
    filled, ui = intake_to_slots(values)
    assert "website_url" not in filled
    assert "website_url" not in ui


def test_dates_are_left_for_resolve_flight_to_default():
    """Empty start means "begin now"; empty end means open-ended. Both are per-ad-set
    fields in the editor, so defaulting them costs the user nothing."""
    values, _errors = _submit(_OK)
    _filled, ui = intake_to_slots(values)
    assert ui["campaign_start_date"] == ""
    assert ui["campaign_end_date"] == ""
    assert ui["budget_type"] == "daily"
    # This submission left budget_amount out — the amount itself is required by
    # the server (see test_express_requires_a_budget), but intake_to_slots only
    # ever writes ui["budget"] for what was actually submitted.
    assert "budget" not in ui


@pytest.mark.parametrize("objective", ["LEADS", "SALES", "OUTCOME_APP_PROMOTION"])
def test_the_intake_leaves_the_conversion_location_to_the_brief(objective):
    """This form only asks the objective, so writing the objective's first
    destination looked like a choice and behaved like one — build_campaign_tree
    treats a present conversion_location as the user's own pick and lets it beat
    the brief's recommendation. Left absent, the brief recommends one from the
    business and geo, and the matrix default still applies when it does not."""
    values, _errors = _submit({
        **_OK, "objective": objective, "app_store_url": "apps.apple.com/app/fit",
    })
    filled, ui = intake_to_slots(values)
    assert "conversion_location" not in filled
    assert "conversion_location" not in ui


def test_intake_to_slots_app_promotion_short_form_and_store_urls():
    values, _errors = _submit({
        "business_name": "Fit", "business_context": "workouts",
        "objective": "OUTCOME_APP_PROMOTION", "app_store_url": "apps.apple.com/app/fit",
    })
    filled, ui = intake_to_slots(values)
    assert filled["objective"] == "APP_PROMOTION"
    assert filled["app_store_url"] == "https://apps.apple.com/app/fit"
    assert ui["app_store_url"] == "https://apps.apple.com/app/fit"


def test_normalize_url_handles_skip_and_scheme():
    assert normalize_url("skip") == ""
    assert normalize_url("") == ""
    assert normalize_url("beanthere.example") == "https://beanthere.example"
    assert normalize_url("http://x.com") == "http://x.com"


# ── express-only fields ────────────────────────────────────────────────────
#
# This form is express-only (guide walks straight from publish_mode to the
# plan editor — see slots.py), so these are unconditional now: the handful of
# answers publishing genuinely cannot default without the campaign/ad-set
# editor panes to fall back on.


_BASE = {
    "business_name": "Autopaws", "business_context": "pet grooming",
    "objective": "OUTCOME_AWARENESS",
}
_PAGES = [{"id": "1", "name": "Autopaws"}, {"id": "2", "name": "Autopaws BD"}]


def test_asks_budget_and_flight():
    fields = _fields(build_intake_schema(user_info={}))
    assert fields["budget_type"]["type"] == "select"
    assert {o["value"] for o in fields["budget_type"]["options"]} == {"daily", "lifetime"}
    assert fields["budget_amount"]["type"] == "currency"
    assert fields["campaign_start_date"]["type"] == "date"
    # Meta rejects a lifetime budget with no window to spread it over.
    assert _shows(fields["campaign_end_date"]["required_when"], budget_type="lifetime")
    assert not _shows(fields["campaign_end_date"]["required_when"], budget_type="daily")


def test_asks_the_page_only_when_there_is_a_choice():
    one = _fields(build_intake_schema(user_info={}, pages=_PAGES[:1]))
    assert "page_id" not in one
    many = _fields(build_intake_schema(user_info={}, pages=_PAGES))
    assert [o["value"] for o in many["page_id"]["options"]] == ["1", "2"]


def test_asks_the_website_only_when_the_page_had_none():
    """connect_meta reads the Page's website before this form is shown; asking
    for something we already have is the exact duplication the slimmed-down
    intake exists to avoid."""
    known = _fields(build_intake_schema(
        user_info={}, page_website="https://autopaws.example",
    ))
    assert "website_url" not in known
    assert "website_url" in _fields(build_intake_schema(user_info={}))


def test_the_website_is_never_required_because_a_destination_needs_it_not_an_objective():
    """Every objective has a shape that needs no site — Sales through Messenger
    or WhatsApp, Engagement on a post, Leads on an instant form. Requiring one
    per objective would ask for something the campaign may never use;
    build_conversion_options drops the destinations that do need it instead."""
    field = _fields(build_intake_schema(user_info={}))["website_url"]

    assert field["required"] is False
    assert "required_when" not in field


def test_currency_is_the_ad_accounts_not_usd():
    """Ad accounts are not all USD and Meta's daily minimum is per-currency."""
    cad = _fields(build_intake_schema(
        user_info={}, currency="CAD", min_budget_cents=500,
    ))["budget_amount"]
    assert cad["prefix"] == "CA$"
    assert cad["min"] == 500
    # An unknown code still labels the field rather than lying with a "$".
    zar = _fields(build_intake_schema(user_info={}, currency="ZAR"))
    assert zar["budget_amount"]["prefix"] == "ZAR "


def test_requires_a_budget():
    _values, errors = parse_intake_submission(json.dumps({"values": {**_BASE}}))
    assert "budget_amount" in errors


def test_requires_an_end_date_for_a_lifetime_budget():
    _values, errors = parse_intake_submission(
        json.dumps({"values": {**_BASE, "budget_amount": 2100, "budget_type": "lifetime"}}),
    )
    assert "campaign_end_date" in errors
    _values, errors = parse_intake_submission(
        json.dumps({"values": {
            **_BASE, "budget_amount": 2100, "budget_type": "lifetime",
            "campaign_end_date": "2026-07-04",
        }}),
    )
    assert errors == {}


def test_answers_reach_the_spec_builders():
    """The currency widget submits CENTS; parse_budget_to_cents reads a bare
    number as DOLLARS. Getting that wrong spends 100x what the user typed."""
    from app.graph.meta_spec.parsing import parse_budget_to_cents

    values, errors = parse_intake_submission(json.dumps({"values": {
        **_BASE, "budget_amount": 2100, "budget_type": "daily",
        "campaign_start_date": "2026-06-22", "campaign_end_date": "2026-07-04",
        "website_url": "autopaws.example", "page_id": "2",
    }}))
    assert errors == {}
    filled, ui = intake_to_slots(values)

    assert parse_budget_to_cents(ui["budget"]) == 2100
    assert ui["budget_type"] == "daily"
    assert ui["campaign_start_date"] == "2026-06-22"
    assert ui["campaign_end_date"] == "2026-07-04"
    assert ui["website_url"] == "https://autopaws.example"
    assert filled["website_url"] == "https://autopaws.example"
    assert ui["meta_page_id"] == "2"


# ── the crash: budget must be a STRING ───────────────────────────────────────
# Storing it as a float made generate_brief raise
# "expected string or bytes-like object, got 'float'" and dead-ended the whole
# Do-It-For-Me flow — two readers of this slot are regexes.


def _express_ui(**overrides) -> dict:
    payload = {
        **_BASE, "budget_amount": 14000, "budget_type": "daily",
        "campaign_start_date": "2026-08-10", "campaign_end_date": "2026-08-30",
        **{k: v for k, v in overrides.items() if k != "currency"},
    }
    values, errors = parse_intake_submission(json.dumps({"values": payload}))
    assert errors == {}
    _filled, ui = intake_to_slots(values, currency=overrides.get("currency", "USD"))
    return ui


def test_budget_slot_is_a_string_the_brief_readers_can_regex():
    """The regression. Both readers take the slot value straight from user_info."""
    from app.graph.builder.builder_node import _extract_budget_amount
    from app.graph.builder.executors.campaign import (
        _selected_tier_reach,
        reconcile_brief_reach,
    )

    ui = _express_ui(currency="BDT")
    assert isinstance(ui["budget"], str)

    # Neither may raise. A custom amount carries no reach copy, so the brief's
    # own estimate is left untouched.
    assert _selected_tier_reach(ui["budget"]) is None
    assert reconcile_brief_reach({"kpi_targets": {"reach": "9,000"}}, ui) == {
        "kpi_targets": {"reach": "9,000"}
    }
    _extract_budget_amount(ui["budget"])


def test_budget_slot_carries_the_account_currency():
    assert _express_ui(currency="BDT")["budget"] == "৳140/day"
    assert _express_ui(currency="USD")["budget"] == "$140/day"
    assert _express_ui(currency="CAD")["budget"] == "CA$140/day"
    # Unknown code → the ISO code itself, never a wrong symbol.
    assert _express_ui(currency="SEK")["budget"] == "SEK 140/day"


def test_budget_slot_says_total_for_a_lifetime_budget():
    ui = _express_ui(budget_type="lifetime", currency="USD")
    assert ui["budget"] == "$140 total"
    assert ui["budget_type"] == "lifetime"


def test_budget_slot_survives_a_seven_figure_amount():
    """%g would render this as 1.23457e+06 and parse back to 1.23457."""
    from app.graph.meta_spec.parsing import parse_budget_to_cents

    ui = _express_ui(budget_amount=123456700, currency="BDT")
    assert "e+" not in ui["budget"]
    assert parse_budget_to_cents(ui["budget"], "BDT") == 123456700


# ── zero-decimal currencies ──────────────────────────────────────────────────


def test_budget_round_trips_in_every_currency():
    """The money test. What the widget submits is what Meta is told to spend —
    on a JPY account 500 means ¥500, and dividing it by 100 anywhere in between
    publishes a hundredth, or bills a hundred times."""
    from app.graph.meta_spec.parsing import parse_budget_to_cents

    for currency, submitted in (
        ("USD", 14000), ("CAD", 14000), ("BDT", 14000), ("JPY", 500), ("KRW", 20000),
    ):
        ui = _express_ui(budget_amount=submitted, currency=currency)
        assert parse_budget_to_cents(ui["budget"], currency) == submitted, currency


def test_zero_decimal_budget_shows_no_fraction():
    assert _express_ui(budget_amount=500, currency="JPY")["budget"] == "JPY 500/day"


def test_budget_field_tells_the_widget_its_divisor():
    jpy = _fields(build_intake_schema(user_info={}, currency="JPY",
                                      min_budget_cents=100))["budget_amount"]
    usd = _fields(build_intake_schema(user_info={}, currency="USD",
                                      min_budget_cents=100))["budget_amount"]
    assert jpy["minor_units"] == 1
    assert usd["minor_units"] == 100


def test_minor_units_follows_meta_not_iso():
    """Meta gives HUF and TWD an offset of 1; ISO gives them two decimals.
    Following ISO here is a 100x error on those accounts."""
    from app.graph.meta_spec.parsing import minor_units

    for code in ("JPY", "KRW", "VND", "CLP", "COP", "CRC", "HUF", "ISK", "IDR", "PYG", "TWD"):
        assert minor_units(code) == 1, code
    for code in ("USD", "CAD", "BDT", "EUR", "GBP", "SEK", "", None):
        assert minor_units(code) == 100, code
    assert minor_units("jpy") == 1


# ── the Pixel select ─────────────────────────────────────────────────────────
#
# Guide's own dataset select (with a "Create one for me" option for an account
# with nothing to pick) moved out of this form entirely — the plan editor's
# ad-set panel already renders the real picker, and now offers a switch onto a
# pixel-promoting goal to reach it (see AdSetPanel.tsx). Express keeps a
# narrower version: only warm datasets, never "create one for me" (see
# _express_fields; the tests below cover that shape).

_PIXELS = [{"id": "111", "name": "Site Pixel"}, {"id": "222", "name": "Old Pixel"}]
_PIXELS_WARM = [
    {"id": "111", "name": "Site Pixel", "last_fired_time": "2026-08-16T10:00:00+0000"},
    {"id": "222", "name": "Old Pixel", "last_fired_time": "2026-08-16T10:00:00+0000"},
]


def test_the_create_sentinel_reaches_the_executor():
    """It used to be dropped here, on the theory that media_select_pixel's create
    branch runs anyway when no dataset resolves. That is true only on an account
    with NO pixels — on any other account the answer vanished and _pick_dataset
    quietly reused an existing dataset, so "Create one for me" did nothing.

    ``meta_spec.builder._real_pixel_id`` is what keeps it out of a published spec.
    """
    values, _ = parse_intake_submission(
        json.dumps({"values": {**_BASE, "pixel_id": "__create__"}}),
    )
    _filled, ui = intake_to_slots(values)

    assert ui["pixel_id"] == "__create__"


def test_the_dataset_answer_unlocks_the_conversion_goal():
    """The whole reason this one question survived. has_warm_dataset is what
    campaign._objective_options and builder._resolve_goal read before deciding
    whether a pixel-promoting optimization goal may be offered at all — and it is
    set by naming a WARM dataset here, not by anything the editor can do later.

    Neither of the two questions that used to stand beside it is read any more.
    """
    values, _ = parse_intake_submission(json.dumps({"values": {**_BASE, "pixel_id": "111"}}))
    filled, ui = intake_to_slots(
        values, pixel_candidates=[{"id": "111", "last_fired_time": "2026-08-16T10:00:00+0000"}],
    )

    assert ui["pixel_id"] == "111"
    assert ui["has_warm_dataset"] is True
    assert "pixel_event" not in ui
    assert "custom_conversion_id" not in ui
    # The editor owns this now — _apply_plan_form_submission writes the slot.
    assert "tracking_method" not in ui
    assert "tracking_method" not in filled


def test_a_cold_pick_does_not_unlock_the_conversion_goal():
    """Naming a dataset that has never fired — or the __create__ sentinel for
    one that does not exist yet — measures nothing yet, so the goal still
    steps down honestly, same as if nothing had been picked at all. This used
    to be forced True on ANY pick, which let a brand-new dataset carry a Sales
    campaign it could never actually optimize.
    """
    values, _ = parse_intake_submission(json.dumps({"values": {**_BASE, "pixel_id": "111"}}))
    _filled, ui = intake_to_slots(
        values, pixel_candidates=[{"id": "111", "last_fired_time": ""}],
    )
    assert "has_warm_dataset" not in ui

    values, _ = parse_intake_submission(
        json.dumps({"values": {**_BASE, "pixel_id": "__create__"}}),
    )
    _filled, ui = intake_to_slots(values, pixel_candidates=[])
    assert "has_warm_dataset" not in ui


def test_never_shown_a_cold_dataset():
    """"Do it for me" is the mode for someone who does not know what a dataset is.
    The form gets the dataset line only when one on the account has actually
    fired (see _express_fields) — these two never have, so it is asked nothing.

    It was briefly the full tracking group, where the client's required-by-default
    rule turned it into a hard block on three questions the server never enforced.
    """
    fields = _fields(build_intake_schema(user_info={}, pixels=_PIXELS))

    assert "pixel_id" not in fields


def test_only_what_the_server_enforces_is_marked_required():
    """The client requires every editable field that does not say otherwise, so a
    field the backend happily defaults must say required=False out loud."""
    fields = _fields(build_intake_schema(user_info={}, pages=_PAGES))

    assert {k for k, f in fields.items() if f["required"]} == {
        "business_name", "business_context", "objective", "budget_amount",
    }
    # Present on every field, never omitted — absent means "fall back to required".
    assert all("required" in f for f in fields.values())


def test_ad_format_is_not_asked_by_the_intake_form():
    """Moved to the ad section of the plan editor (AdCard.tsx) — see
    test_the_form_asks_only_what_cannot_be_defaulted."""
    fields = _fields(build_intake_schema(user_info={}))
    assert "ad_format" not in fields


def test_creative_source_is_never_asked():
    """"Punk writes it" is the default, and promoting an existing post is still
    a per-ad-set choice in the plan editor's own ad card (AdCard.tsx), not a
    form question."""
    assert "creative_source" not in _fields(build_intake_schema(user_info={}))


def test_creative_source_is_carried_into_user_info():
    values, _ = parse_intake_submission(
        json.dumps({"values": {**_BASE, "creative_source": "existing_post"}}),
    )
    _filled, ui = intake_to_slots(values)

    assert ui["creative_source"] == "existing_post"


def test_pixel_select_prefers_the_already_resolved_pixel():
    # Only warm datasets render at all (see test_never_shown_a_cold_dataset),
    # so exercise the suggestion with pixels that have actually fired.
    fields = _fields(build_intake_schema(
        user_info={"pixel_id": "222"}, pixels=_PIXELS_WARM,
    ))
    assert fields["pixel_id"]["suggestion"] == "222"


def test_pixel_pick_is_written_only_when_chosen():
    values, _ = parse_intake_submission(
        json.dumps({"values": {**_BASE, "pixel_id": "222"}}),
    )
    _filled, ui = intake_to_slots(values)
    assert ui["pixel_id"] == "222"

    values, _ = parse_intake_submission(
        json.dumps({"values": {**_BASE, "budget_amount": 14000}}),
    )
    _filled, ui = intake_to_slots(values)
    assert "pixel_id" not in ui


# ── the one tracking line this form gets ─────────────────────────────────────


def _with(**kwargs):
    return _fields(build_intake_schema(user_info={}, **kwargs))


def test_names_the_dataset_the_money_is_measured_against():
    """This form does not get the tracking GROUP — which dataset is the only
    part of it that is a fact rather than a question, and a Sales campaign is
    about to be built on it."""
    field = _with(pixels=[{"id": "ds-1", "name": "Live site", "last_fired_time": "2026-08-16T10:00:00+0000"}]).get("pixel_id")

    assert field is not None
    assert field["label"] == "Conversion tracking"
    # No auto-suggest when nothing was already resolved — see
    # test_pixel_select_prefers_the_already_resolved_pixel for when it is.
    assert "suggestion" not in field
    # Sales only: Leads runs on an instant form, whose conversions Meta counts
    # with no dataset in the picture at all.
    assert field["visible_when"] == {"objective": ["OUTCOME_SALES"]}


def test_says_nothing_about_a_dataset_that_has_never_fired():
    """A cold dataset cannot carry the campaign — _resolve_goal steers the ad set
    off the conversion goal entirely — so naming it here would promise
    measurement that is not going to happen."""
    assert "pixel_id" not in _with(pixels=[{"id": "ds-2", "name": "Staging"}])
    assert "pixel_id" not in _with(pixels=[])


def test_never_asked_how_conversions_reach_meta():
    """Both questions a beginner cannot answer stay out:
    media._derived_tracking_method supplies the method, DEFAULT_PIXEL_EVENT the
    event, and the plan editor renders both pre-filled — the ad-set panel's
    event select and the campaign panel's method select."""
    warm = [{"id": "ds-1", "name": "Live site", "last_fired_time": "2026-08-16T10:00:00+0000"}]
    fields = _with(pixels=warm)
    assert "tracking_method" not in fields
    assert "conversion_event" not in fields
