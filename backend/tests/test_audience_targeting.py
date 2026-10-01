"""
tests/test_audience_targeting.py
────────────────────────────────
The half of conversion tracking Punk did not have: spending the signal.

The pixel and the Conversions API fill a dataset. Until these fields existed
nothing could advertise to the people in it, and no ad set Punk published could
exclude anybody — so prospecting kept being sold to customers who had already
bought. ``bind_audiences`` is where the user's picks become real targeting, and
it has to do that WITHOUT disturbing the MAID seed/lookalike machinery that was
already there.

Also covered: the audience upload, which now carries any of Meta's schemas and
must hash exactly the ones Meta wants hashed — a digest built the wrong way is
accepted, matches nobody, and reports success.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.graph.meta_spec import CampaignSpec
from app.services import meta_ads, meta_capi


def _adset(name, role, **extra):
    base = {
        "name": name,
        "audience_role": role,
        "optimization_goal": "LINK_CLICKS",
        "billing_event": "LINK_CLICKS",
        "destination_type": "WEBSITE",
        "daily_budget": 5000,
        "targeting": {"geo_locations": {"countries": ["US"]}},
        "start_time": "2026-09-01T00:00:00+00:00",
        "ads": [{
            "name": name + " Ad",
            "creative": {
                "title": "t", "body": "b",
                "call_to_action": "LEARN_MORE",
                "link": "https://x.example",
            },
        }],
    }
    base.update(extra)
    return base


def _plan(adsets, **overrides):
    plan = {
        "name": "Audience Test",
        "objective": "OUTCOME_TRAFFIC",
        "special_ad_categories": [],
        "adsets": adsets,
    }
    plan.update(overrides)
    return CampaignSpec.model_validate(plan)


def _spec(seed_extra=None, broad_extra=None) -> CampaignSpec:
    return _plan([
        _adset("Seed", "seed", **(seed_extra or {})),
        _adset("Broad", "broad", **(broad_extra or {})),
    ])


def _targeting(spec: CampaignSpec, name: str) -> dict:
    return next(a.targeting for a in spec.adsets if a.name == name)


# ── binding ───────────────────────────────────────────────────────────────────


def test_the_maid_machinery_is_unchanged_when_nobody_picked_anything():
    """The regression guard. Everything below is additive to this behaviour."""
    bound = _spec().bind_audiences(
        custom_audience_id="ca-1", lookalike_audience_id="lal-1",
    )
    assert _targeting(bound, "Seed")["custom_audiences"] == [{"id": "ca-1"}]
    assert "custom_audiences" not in _targeting(bound, "Broad")


def test_a_picked_audience_joins_the_roles_audience_rather_than_replacing_it():
    """Prospect against the seed list AND a saved audience — Meta ORs them."""
    bound = _spec(seed_extra={"attached_audience_ids": ["saved-9"]}).bind_audiences(
        custom_audience_id="ca-1", lookalike_audience_id=None,
    )
    assert _targeting(bound, "Seed")["custom_audiences"] == [
        {"id": "ca-1"}, {"id": "saved-9"},
    ]


def test_exclusions_reach_the_targeting():
    """The whole point: stop paying to re-acquire people who already converted."""
    bound = _spec(broad_extra={"excluded_audience_ids": ["converters"]}).bind_audiences(
        custom_audience_id=None, lookalike_audience_id=None,
    )
    assert _targeting(bound, "Broad")["excluded_custom_audiences"] == [
        {"id": "converters"},
    ]


def test_an_adset_with_a_picked_audience_is_not_handed_to_advantage_plus():
    """A lookalike ad set whose lookalike failed normally degrades to Advantage+.

    Not when the user attached their own audience: that ad set did not lose its
    targeting, it has different targeting, and switching Advantage+ on would
    quietly widen the audience the user explicitly chose.
    """
    spec = _plan([
        _adset("Prospect", "lookalike", attached_audience_ids=["saved-9"]),
    ])
    bound = spec.bind_audiences(custom_audience_id=None, lookalike_audience_id=None)
    targeting = _targeting(bound, "Prospect")
    assert targeting["custom_audiences"] == [{"id": "saved-9"}]
    assert targeting.get("targeting_automation", {}).get("advantage_audience") != 1


def test_a_lookalike_that_failed_still_degrades_when_nothing_was_picked():
    """The existing behaviour, unchanged — a role that lost its audience widens."""
    spec = _plan([_adset("Prospect", "lookalike")])
    bound = spec.bind_audiences(custom_audience_id=None, lookalike_audience_id=None)
    targeting = _targeting(bound, "Prospect")
    assert "custom_audiences" not in targeting
    assert targeting["targeting_automation"]["advantage_audience"] == 1


def test_binding_is_idempotent_and_does_not_accumulate_ids():
    once = _spec(broad_extra={"excluded_audience_ids": ["x"]}).bind_audiences(
        custom_audience_id="ca-1", lookalike_audience_id="lal-1",
    )
    twice = once.bind_audiences(custom_audience_id="ca-1", lookalike_audience_id="lal-1")
    assert _targeting(twice, "Seed")["custom_audiences"] == [{"id": "ca-1"}]
    assert _targeting(twice, "Broad")["excluded_custom_audiences"] == [{"id": "x"}]


def test_targeting_and_excluding_the_same_audience_is_refused():
    """Meta accepts it and delivers to nobody — the exclusion wins."""
    with pytest.raises(ValidationError, match="both targeted and excluded"):
        _spec(seed_extra={
            "attached_audience_ids": ["same"],
            "excluded_audience_ids": ["same"],
        })


def test_a_special_ad_category_campaign_refuses_a_saved_audience():
    """Housing, employment and credit cannot use audience targeting at all."""
    with pytest.raises(ValidationError, match="special ad category"):
        _plan(
            [_adset("S", "broad", attached_audience_ids=["saved-9"])],
            special_ad_categories=["HOUSING"],
        )


# ── the upload ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_person_identifiers_are_hashed_and_device_ids_are_not(monkeypatch):
    """The rule that makes the whole upload work, or silently match nobody."""
    sent = {}

    async def fake(method, endpoint, token, *a, **kw):
        sent.update(kw["json_data"]["payload"])
        return {"audience_id": "aud-1"}

    monkeypatch.setattr(meta_ads, "_request", fake)

    await meta_ads.upload_audience_users(
        "aud-1", [[" Bob@Example.COM ", "+1 (415) 555-0100"]], "tok",
        schema=["EMAIL", "PHONE"],
    )
    assert sent["schema"] == ["EMAIL", "PHONE"]
    assert sent["data"] == [[
        meta_capi.hash_user_field("email", "bob@example.com"),
        meta_capi.hash_user_field("phone", "14155550100"),
    ]]

    await meta_ads.upload_maids_to_audience("aud-1", ["AB-12-CD"], "tok")
    assert sent["schema"] == ["MADID"]
    assert sent["data"] == [["ab-12-cd"]], "a hashed MADID matches zero devices"


@pytest.mark.asyncio
async def test_a_row_that_identifies_nobody_is_dropped(monkeypatch):
    sent = {}

    async def fake(method, endpoint, token, *a, **kw):
        sent.update(kw["json_data"]["payload"])
        return {}

    monkeypatch.setattr(meta_ads, "_request", fake)
    await meta_ads.upload_audience_users(
        "aud-1", [["a@b.com"], [""], ["  "]], "tok", schema=["EMAIL"],
    )
    assert len(sent["data"]) == 1


@pytest.mark.asyncio
async def test_an_unknown_schema_field_is_refused_before_anything_is_sent(monkeypatch):
    async def fake(*a, **kw):
        raise AssertionError("nothing should reach Meta")

    monkeypatch.setattr(meta_ads, "_request", fake)
    with pytest.raises(meta_ads.MetaAdsError, match="unsupported audience schema"):
        await meta_ads.upload_audience_users(
            "aud-1", [["x"]], "tok", schema=["MADE_UP"],
        )


# ── delivery status ───────────────────────────────────────────────────────────


def test_an_audience_meta_will_not_serve_is_not_usable():
    """The live finding: seven lookalikes, all undeliverable, nothing noticed."""
    too_small = {"delivery_status": {"code": 300, "description": "Audience is too small"}}
    assert meta_ads.audience_is_usable(too_small) is False
    assert meta_ads.audience_is_usable({"delivery_status": {"code": 200}}) is True


def test_an_audience_with_no_verdict_is_left_alone():
    """A thin projection must not hide the user's own audiences from them."""
    assert meta_ads.audience_is_usable({"id": "a"}) is True


# ── the website audience rule ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_event_audience_filters_on_that_event(monkeypatch):
    """A converters list — the audience worth EXCLUDING from prospecting."""
    import json

    sent = {}

    async def fake(method, endpoint, token, *a, **kw):
        sent.update(kw["json_data"])
        return {"id": "aud-new"}

    monkeypatch.setattr(meta_ads, "_request", fake)
    await meta_ads.create_website_audience(
        "Converters", "ds-1", "act_1", "tok", event_name="Purchase", retention_days=90,
    )
    # No subtype: measured live, v25.0 rejects subtype=WEBSITE outright and
    # infers a rule-based audience from the rule itself. The customer-file path
    # in create_custom_audience still requires subtype=CUSTOM — different create,
    # different rule, and this asserts they have not been conflated.
    assert "subtype" not in sent
    assert sent["retention_days"] == 90
    rule = json.loads(sent["rule"])["inclusions"]["rules"][0]
    assert rule["event_sources"] == [{"id": "ds-1", "type": "pixel"}]
    assert rule["retention_seconds"] == 90 * 24 * 60 * 60
    assert rule["filter"]["filters"][0]["value"] == "Purchase"


@pytest.mark.asyncio
async def test_an_audience_with_no_event_is_everyone_the_dataset_saw(monkeypatch):
    import json

    sent = {}

    async def fake(method, endpoint, token, *a, **kw):
        sent.update(kw["json_data"])
        return {"id": "aud-new"}

    monkeypatch.setattr(meta_ads, "_request", fake)
    await meta_ads.create_website_audience("Visitors", "ds-1", "act_1", "tok")
    rule = json.loads(sent["rule"])["inclusions"]["rules"][0]
    assert rule["template"] == "ALL_VISITORS"
    assert "filter" not in rule


@pytest.mark.asyncio
async def test_retention_is_clamped_to_metas_ceiling(monkeypatch):
    sent = {}

    async def fake(method, endpoint, token, *a, **kw):
        sent.update(kw["json_data"])
        return {"id": "aud-new"}

    monkeypatch.setattr(meta_ads, "_request", fake)
    await meta_ads.create_website_audience(
        "V", "ds-1", "act_1", "tok", retention_days=9999,
    )
    assert sent["retention_days"] == meta_ads.MAX_AUDIENCE_RETENTION_DAYS


# ── what Meta actually answered, live ─────────────────────────────────────────


def test_the_custom_audience_tos_rejection_is_recognised():
    """Measured live: building a website audience answers code 2663.

    The customer-list path answers 2654 for the same consent. Only a user with an
    admin role can accept it — Meta will not let an API do it — so this is the one
    rejection here that MUST come back as instructions rather than a Graph string.
    """
    from app.services import meta_remediation as fix
    from app.services.meta_ads import MetaAdsError

    exc = MetaAdsError(
        "OAuthException: (#2663) Terms of service has not been accepted.", code=2663,
    )
    rem = fix.resolve(exc, step="custom_audience", scope="audience")
    assert rem is not None and rem.key == "custom_audience_tos"


def test_a_card_link_carries_the_bare_account_number():
    """Meta's consoles take ?act=123, the Graph API wants act_123.

    Rendering the Graph form into the link sent the user to an error page at the
    exact moment they were trying to fix something.
    """
    from app.services import meta_remediation as fix

    url = fix.render(fix.CATALOG["custom_audience_tos"], ad_account_id="act_123")["url"]
    assert "act=123" in url and "act_123" not in url


# ── the lookalike seed gate ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_seed_too_small_to_model_skips_the_lookalike(monkeypatch):
    """Live, every lookalike on the audited account was undeliverable.

    Each was built from a 1,000-MAID seed and reported "too small to be used in
    campaign creation" — and nothing noticed, because reading a lookalike back
    right after creating it always answers "Updating". The seed is what Meta
    actually refuses on, and it is knowable first.
    """
    from app.graph.builder.executors import media

    async def small(ad_account_id, token):
        return [{"id": "seed-1", "approximate_count_lower_bound": 12}]

    monkeypatch.setattr(meta_ads, "list_custom_audiences", small)
    supports, matched = await media._seed_supports_lookalike(
        "seed-1", "act_1", "tok", lambda _e: None,
    )
    assert supports is False
    # The matched count is returned even when it fails the lookalike floor —
    # it is the honest match-rate figure, not just a boolean gate.
    assert matched == 12


@pytest.mark.asyncio
async def test_a_seed_big_enough_still_builds_one(monkeypatch):
    from app.graph.builder.executors import media

    async def big(ad_account_id, token):
        return [{"id": "seed-1", "approximate_count_lower_bound": 250_000}]

    monkeypatch.setattr(meta_ads, "list_custom_audiences", big)
    supports, matched = await media._seed_supports_lookalike(
        "seed-1", "act_1", "tok", lambda _e: None,
    )
    assert supports is True
    assert matched == 250_000


@pytest.mark.asyncio
async def test_an_uncounted_seed_is_given_the_benefit_of_the_doubt(monkeypatch):
    """A freshly uploaded audience reports no count for a while.

    Refusing to build a lookalike over a timing detail would cost the campaign an
    ad set. The failure being guarded against is a permanently small seed.
    """
    from app.graph.builder.executors import media

    async def uncounted(ad_account_id, token):
        return [{"id": "seed-1", "approximate_count_lower_bound": None}]

    monkeypatch.setattr(meta_ads, "list_custom_audiences", uncounted)
    supports, matched = await media._seed_supports_lookalike(
        "seed-1", "act_1", "tok", lambda _e: None,
    )
    assert supports is True
    assert matched is None


@pytest.mark.asyncio
async def test_a_failed_read_never_costs_the_campaign_an_adset(monkeypatch):
    from app.graph.builder.executors import media

    async def boom(ad_account_id, token):
        raise RuntimeError("Meta is down")

    monkeypatch.setattr(meta_ads, "list_custom_audiences", boom)
    supports, matched = await media._seed_supports_lookalike(
        "seed-1", "act_1", "tok", lambda _e: None,
    )
    assert supports is True
    assert matched is None


# ── the transport ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_delete_is_actually_sent_as_a_delete(monkeypatch):
    """It was sent as a GET, which Meta answers 200 with the object's fields.

    Every caller then reported a successful delete of something still sitting on
    the account — measured by deleting three objects three times and finding all
    three still there.
    """
    import httpx

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        return httpx.Response(200, json={"success": True})

    real_client = httpx.AsyncClient

    def client(*a, **kw):
        return real_client(*a, **{**kw, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(meta_ads.httpx, "AsyncClient", client)
    await meta_ads._request("DELETE", "obj-1", "tok", retries=1)
    assert seen["method"] == "DELETE"


# ── the custom conversion picker ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_archived_custom_conversion_is_not_offered(monkeypatch):
    """Archived is how Meta deletes one; the row stays readable forever.

    Offering it puts an ad set on a rule that no longer fires — the exact failure
    the conversion picker exists to prevent.
    """
    async def fake(method, endpoint, token, *a, **kw):
        return {"data": [
            {"id": "1", "name": "live", "custom_event_type": "PURCHASE"},
            {"id": "2", "name": "deleted", "is_archived": True},
            {"id": "3", "name": "disabled", "is_unavailable": True},
        ]}

    monkeypatch.setattr(meta_ads, "_request", fake)
    offered = await meta_ads.fetch_custom_conversions("act_1", "tok")
    assert [c["id"] for c in offered] == ["1"]
