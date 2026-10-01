"""
tests/test_meta_scope_and_subscription.py
─────────────────────────────────────────
Two live failures the audit found, and the rules that close them.

**The subscription.** ``POST /{page}/subscribed_apps`` answered success on a real
Page while the Page stayed unsubscribed — measured. Since that POST was the only
signal ``subscribe_page_leadgen`` had, ``lead_webhook_not_subscribed`` could never
be raised and instant-form leads silently never arrived. The write is now read
back, and only a read that finds ``leadgen`` counts.

**The scopes.** ``pages_manage_metadata`` was never asked for, so the read-back
above (and the DELETE that turns lead delivery off) is refused on every token
minted before it was added. A token is stamped with its scopes for life, so the
fix has to be visible to the user as "reconnect", not silent.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.modules.ads.service import REQUIRED_SCOPES, _scope_cards, missing_scopes
from app.services import meta_ads


# ── the subscription read-back ────────────────────────────────────────────────


def _graph(monkeypatch, *, on_post=None, on_get=None):
    """Stand in for ``meta_ads._request``, splitting POST from GET."""
    calls: list[tuple[str, str]] = []

    async def fake(method, endpoint, token, *a, **kw):
        calls.append((method, endpoint))
        if method == "POST":
            return on_post() if on_post else {"success": True}
        if method == "GET":
            return on_get() if on_get else {"data": []}
        return {}

    monkeypatch.setattr(meta_ads, "_request", fake)
    return calls


@pytest.mark.asyncio
async def test_a_write_meta_accepted_but_did_not_apply_is_not_a_subscription(monkeypatch):
    """The measured failure: POST says success, the Page lists nothing."""
    _graph(monkeypatch, on_get=lambda: {"data": []})
    assert await meta_ads.subscribe_page_leadgen("pg-1", "page-token") is False


@pytest.mark.asyncio
async def test_a_subscription_meta_confirms_is_true(monkeypatch):
    _graph(monkeypatch, on_get=lambda: {
        "data": [{"id": str(settings.META_APP_ID), "subscribed_fields": ["leadgen"]}]
    })
    assert await meta_ads.subscribe_page_leadgen("pg-1", "page-token") is True


@pytest.mark.asyncio
async def test_another_apps_subscription_is_not_ours(monkeypatch):
    """Pages carry several apps. Somebody else's leadgen is not our feed."""
    _graph(monkeypatch, on_get=lambda: {
        "data": [{"id": "999999", "subscribed_fields": ["leadgen"]}]
    })
    assert await meta_ads.subscribe_page_leadgen("pg-1", "page-token") is False


@pytest.mark.asyncio
async def test_a_token_that_cannot_read_the_edge_keeps_the_posts_answer(monkeypatch):
    """An older token cannot read subscribed_apps at all.

    Reporting that as "not subscribed" would tell every existing advertiser their
    working lead feed is broken, which is a worse lie than the one being fixed.
    """
    def refuse():
        raise meta_ads.MetaAdsError("(#200) Requires pages_manage_metadata", code=200)

    _graph(monkeypatch, on_get=refuse)
    assert await meta_ads.subscribe_page_leadgen("pg-1", "page-token") is True


@pytest.mark.asyncio
async def test_a_rejected_write_never_reads_back(monkeypatch):
    def refuse():
        raise meta_ads.MetaAdsError("nope", code=200)

    calls = _graph(monkeypatch, on_post=refuse)
    assert await meta_ads.subscribe_page_leadgen("pg-1", "page-token") is False
    assert [m for m, _ in calls] == ["POST"]


@pytest.mark.asyncio
async def test_unsubscribe_deletes_the_edge_with_the_app_token(monkeypatch):
    """Measured: a Page token is refused here with "(#15) … app access_token".

    The subscription belongs to the app, so removing it is an app-level action —
    which is why this call takes no token at all.
    """
    tokens: list[str] = []

    async def fake(method, endpoint, token, *a, **kw):
        tokens.append(token)
        return {"success": True}

    monkeypatch.setattr(meta_ads, "_request", fake)
    assert await meta_ads.unsubscribe_page_leadgen("pg-1") is True
    assert tokens == [f"{settings.META_APP_ID}|{settings.META_APP_SECRET}"]


# ── the scope check ───────────────────────────────────────────────────────────


def test_pages_manage_metadata_is_required():
    """The permission the audit found missing. Named so removing it fails here."""
    assert "pages_manage_metadata" in REQUIRED_SCOPES


def test_a_connection_short_a_permission_is_named():
    token = SimpleNamespace(scopes=[s for s in REQUIRED_SCOPES if s != "leads_retrieval"])
    assert missing_scopes(token) == ["leads_retrieval"]
    card = _scope_cards(missing_scopes(token))
    assert card and "leads_retrieval" in card[0]["cause"]


def test_a_complete_connection_says_nothing():
    assert missing_scopes(SimpleNamespace(scopes=list(REQUIRED_SCOPES))) == []
    assert _scope_cards([]) == []


def test_a_connection_predating_scope_recording_is_not_accused():
    """NULL scopes means "we never looked", not "none granted".

    Live, every row was NULL — treating that as missing everything would have put
    a reconnect card in front of every user of the product at once.
    """
    assert missing_scopes(SimpleNamespace(scopes=None)) == []
    assert missing_scopes(SimpleNamespace(scopes=[])) == []


# ── the grant, announced at connect ───────────────────────────────────────────
# The scopes a token carries are decided by the login configuration in the App
# Dashboard, not by what Punk asks for. A short grant used to surface as a (#200)
# mid-publish; ``ad_account_blockers`` now says so when the user connects.


def _account_and_grant(monkeypatch, *, scopes, account=None):
    async def fake_request(method, endpoint, token, *a, **kw):
        return account if account is not None else {
            "account_status": 1,
            "funding_source_details": {"id": "1"},
            "business": {"id": "b1", "name": "Biz"},
        }

    async def fake_info(_token):
        return {"scopes": scopes, "type": "", "expires_at": None, "granular_scopes": []}

    monkeypatch.setattr(meta_ads, "_request", fake_request)
    monkeypatch.setattr(meta_ads, "fetch_token_info", fake_info)


@pytest.mark.asyncio
async def test_a_full_grant_raises_nothing(monkeypatch):
    _account_and_grant(monkeypatch, scopes=list(REQUIRED_SCOPES))
    assert await meta_ads.ad_account_blockers("act_1", "tok") == []


@pytest.mark.asyncio
async def test_a_grant_short_ads_management_blocks_and_names_it(monkeypatch):
    _account_and_grant(
        monkeypatch, scopes=[s for s in REQUIRED_SCOPES if s != "ads_management"],
    )

    (card,) = await meta_ads.ad_account_blockers("act_1", "tok")

    assert card.key == "meta_scopes_outdated"
    assert card.severity == "blocks"
    assert "ads_management" in card.cause
    assert "{missing}" not in card.cause


@pytest.mark.asyncio
async def test_a_grant_short_only_a_feature_permission_warns(monkeypatch):
    _account_and_grant(
        monkeypatch, scopes=[s for s in REQUIRED_SCOPES if s != "leads_retrieval"],
    )

    (card,) = await meta_ads.ad_account_blockers("act_1", "tok")

    assert card.severity == "warns"
    assert "leads_retrieval" in card.cause


@pytest.mark.asyncio
async def test_an_unreadable_grant_is_not_an_accusation(monkeypatch):
    """``fetch_token_info`` returns no scopes when ``debug_token`` fails — "could not
    ask", which must never read as "granted nothing"."""
    _account_and_grant(monkeypatch, scopes=[])
    assert await meta_ads.ad_account_blockers("act_1", "tok") == []


@pytest.mark.asyncio
async def test_a_short_grant_survives_an_unreadable_account(monkeypatch):
    """The grant read is independent of the account read: losing one must not hide
    the other."""
    async def boom(*a, **kw):
        raise meta_ads.MetaAdsError("nope", code=100)

    async def fake_info(_token):
        return {"scopes": ["ads_read"], "type": "", "expires_at": None, "granular_scopes": []}

    monkeypatch.setattr(meta_ads, "_request", boom)
    monkeypatch.setattr(meta_ads, "fetch_token_info", fake_info)

    (card,) = await meta_ads.ad_account_blockers("act_1", "tok")
    assert card.key == "meta_scopes_outdated"


# ── the readiness route's service ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_readiness_reads_the_selected_account_and_orders_the_result(monkeypatch):
    from app.modules.ads.service import AdsService
    from app.services import meta_remediation

    seen = {}

    async def fake_blockers(ad_account_id, token):
        seen["args"] = (ad_account_id, token)
        return [meta_remediation.CATALOG["ad_account_no_payment"]]

    monkeypatch.setattr(meta_ads, "ad_account_blockers", fake_blockers)
    svc = AdsService(repository=SimpleNamespace())

    async def token(*_):
        return "tok"

    async def account(*_):
        return "act_9"

    monkeypatch.setattr(svc, "get_meta_access_token", token)
    monkeypatch.setattr(svc, "_selected_ad_account", account)

    cards = await svc.get_readiness(db=object(), user_id="u")

    assert seen["args"] == ("act_9", "tok")
    assert [c["key"] for c in cards] == ["ad_account_no_payment", "custom_audience_tos"]


@pytest.mark.asyncio
async def test_readiness_is_empty_when_meta_is_not_connected(monkeypatch):
    from app.modules.ads.service import AdsService

    svc = AdsService(repository=SimpleNamespace())

    async def nothing(*_):
        return None

    monkeypatch.setattr(svc, "get_meta_access_token", nothing)
    monkeypatch.setattr(svc, "_selected_ad_account", nothing)

    assert await svc.get_readiness(db=object(), user_id="u") == []


# ── the Lead delivery screen (pages_manage_metadata, visibly in use) ──────────


def _delivery_svc(monkeypatch, *, pages, tokens, subscribed, routed_page="", saved=None):
    from app.modules.ads.service import AdsService

    async def _pages(_t):
        return pages

    async def _tokens(_t):
        return tokens

    async def _sub_read(page_id, page_token):
        return subscribed[page_id]

    monkeypatch.setattr(meta_ads, "list_meta_pages", _pages)
    monkeypatch.setattr(meta_ads, "list_page_tokens", _tokens)
    monkeypatch.setattr(meta_ads, "page_leadgen_subscribed", _sub_read)

    async def _account(*_a):
        return SimpleNamespace(tracking_lead_page_id=routed_page)

    async def _save(_db, _uid, **fields):
        if saved is not None:
            saved.append(fields)
        return True

    svc = AdsService(repository=SimpleNamespace(
        get_tracking_account=_account, save_tracking_state=_save,
    ))

    async def _tok(*_):
        return "tok"

    monkeypatch.setattr(svc, "get_meta_access_token", _tok)
    return svc


@pytest.mark.asyncio
async def test_lead_delivery_reports_subscribed_routed_and_unknown_separately(monkeypatch):
    svc = _delivery_svc(
        monkeypatch,
        pages=[{"id": "p1", "name": "One"}, {"id": "p2", "name": "Two"},
               {"id": "p3", "name": "Three"}, {"id": "p4", "name": "Four"}],
        tokens={"p1": "t1", "p2": "t2", "p3": "t3"},   # p4: no Page token at all
        subscribed={"p1": True, "p2": True, "p3": False},
        routed_page="p1",
    )

    rows = {r["page_id"]: r for r in await svc.list_lead_delivery(db=object(), user_id="u")}

    assert (rows["p1"]["subscribed"], rows["p1"]["routed"]) == (True, True)
    # Subscribed on Meta, but the ad account receives a different Page's leads.
    assert (rows["p2"]["subscribed"], rows["p2"]["routed"]) == (True, False)
    assert rows["p3"]["subscribed"] is False
    # No Page token: unknown, never "off".
    assert rows["p4"]["subscribed"] is None


@pytest.mark.asyncio
async def test_connecting_subscribes_with_the_page_token_and_routes_the_page(monkeypatch):
    saved: list[dict] = []
    svc = _delivery_svc(monkeypatch, pages=[], tokens={}, subscribed={}, saved=saved)
    posted = []

    async def _page_token(page_id, _t):
        return "page-tok"

    async def _subscribe(page_id, page_token):
        posted.append((page_id, page_token))
        return True

    monkeypatch.setattr(meta_ads, "fetch_page_token", _page_token)
    monkeypatch.setattr(meta_ads, "subscribe_page_leadgen", _subscribe)

    row = await svc.connect_lead_delivery(db=object(), user_id="u", page_id="p1")

    assert posted == [("p1", "page-tok")]
    assert saved == [{"tracking_lead_page_id": "p1"}]      # and NOTHING about a dataset
    assert (row["subscribed"], row["routed"], row["remediation"]) == (True, True, [])


@pytest.mark.asyncio
async def test_a_failed_subscribe_returns_the_card_and_routes_nothing(monkeypatch):
    saved: list[dict] = []
    svc = _delivery_svc(monkeypatch, pages=[], tokens={}, subscribed={}, saved=saved)

    async def _page_token(*_):
        return "page-tok"

    async def _subscribe(*_):
        return False

    monkeypatch.setattr(meta_ads, "fetch_page_token", _page_token)
    monkeypatch.setattr(meta_ads, "subscribe_page_leadgen", _subscribe)

    row = await svc.connect_lead_delivery(db=object(), user_id="u", page_id="p1")

    assert row["subscribed"] is False and row["routed"] is False
    assert [c["key"] for c in row["remediation"]] == ["lead_webhook_not_subscribed"]
    assert saved == []


@pytest.mark.asyncio
async def test_a_page_meta_did_not_share_is_refused(monkeypatch):
    """Also what stops a user naming a Page id that is not theirs."""
    svc = _delivery_svc(monkeypatch, pages=[], tokens={}, subscribed={})

    async def _no_token(*_):
        return ""

    monkeypatch.setattr(meta_ads, "fetch_page_token", _no_token)

    with pytest.raises(ValueError, match="did not share that Page"):
        await svc.connect_lead_delivery(db=object(), user_id="u", page_id="someone-elses")


# ── the spending limit, announced at connect ─────────────────────────────────
# A reached cap leaves account_status alone and Meta simply stops delivering, so
# no status check can see it. The fields are only claimed from a rung that carried
# them (knows_spend), the same rule as the funding source.

_HEALTHY = {
    "account_status": 1,
    "funding_source_details": {"id": "1"},
    "business": {"id": "b1", "name": "Biz"},
}


def _account(monkeypatch, *, fields_refused=(), **fields):
    """An account answering ``fields``; a rung asking for anything in
    ``fields_refused`` fails like a scope Meta will not grant."""
    async def fake_request(method, endpoint, token, *a, json_data=None, **kw):
        asked = (json_data or {}).get("fields", "")
        if any(f in asked for f in fields_refused):
            raise meta_ads.MetaAdsError("(#200) no", code=200)
        return {**_HEALTHY, **fields}

    async def fake_info(_token):
        return {"scopes": list(REQUIRED_SCOPES), "type": "", "expires_at": None,
                "granular_scopes": []}

    monkeypatch.setattr(meta_ads, "_request", fake_request)
    monkeypatch.setattr(meta_ads, "fetch_token_info", fake_info)


@pytest.mark.asyncio
@pytest.mark.parametrize("cap,spent", [("50000", "50000"), ("50000", "61000")])
async def test_a_reached_cap_is_raised_and_says_nothing_was_built(monkeypatch, cap, spent):
    _account(monkeypatch, spend_cap=cap, amount_spent=spent)

    (card,) = await meta_ads.ad_account_blockers("act_1", "tok")

    assert card.key == "ad_account_spend_limit"
    assert card.severity == "blocks"
    # The catalog line is for a refusal at publish; here nothing is built yet.
    assert "PAUSED" not in card.effect and "Nothing has been built" in card.effect


@pytest.mark.asyncio
@pytest.mark.parametrize("cap,spent", [("0", "999999"), ("50000", "10000"), ("50000", "49999")])
async def test_no_cap_or_room_left_raises_nothing(monkeypatch, cap, spent):
    """spend_cap "0" is Meta's spelling of NO cap — not a cap of zero."""
    _account(monkeypatch, spend_cap=cap, amount_spent=spent)
    assert await meta_ads.ad_account_blockers("act_1", "tok") == []


@pytest.mark.asyncio
async def test_a_cap_is_not_claimed_from_a_rung_that_never_asked(monkeypatch):
    """The account refuses the spend fields, so a lower rung answers. Whatever that
    rung's dict happens to hold, an unread field is not evidence of a reached cap."""
    _account(monkeypatch, fields_refused=("spend_cap",), spend_cap="1", amount_spent="5")
    assert await meta_ads.ad_account_blockers("act_1", "tok") == []


@pytest.mark.asyncio
async def test_a_garbled_cap_is_not_an_accusation(monkeypatch):
    _account(monkeypatch, spend_cap="n/a", amount_spent="n/a")
    assert await meta_ads.ad_account_blockers("act_1", "tok") == []


# -- the advertiser role, announced at connect --
# user_tasks answers plain strings (measured 2026-09-22:
# ["DRAFT", "ANALYZE", "ADVERTISE", "MANAGE"]). Creating ads needs ADVERTISE or
# MANAGE; without either every write is a (#200)/(#10) at publish.


@pytest.mark.asyncio
@pytest.mark.parametrize("tasks", [["ANALYZE"], ["DRAFT", "ANALYZE"]])
async def test_a_read_only_role_is_raised(monkeypatch, tasks):
    _account(monkeypatch, user_tasks=tasks)

    (card,) = await meta_ads.ad_account_blockers("act_1", "tok")

    assert card.key == "ad_account_role_missing"
    assert card.severity == "blocks"


@pytest.mark.asyncio
@pytest.mark.parametrize("tasks", [
    ["DRAFT", "ANALYZE", "ADVERTISE", "MANAGE"], ["ADVERTISE"], ["manage"],
])
async def test_an_advertising_role_raises_nothing(monkeypatch, tasks):
    _account(monkeypatch, user_tasks=tasks)
    assert await meta_ads.ad_account_blockers("act_1", "tok") == []


@pytest.mark.asyncio
async def test_an_empty_role_list_is_not_an_accusation(monkeypatch):
    _account(monkeypatch, user_tasks=[])
    assert await meta_ads.ad_account_blockers("act_1", "tok") == []


@pytest.mark.asyncio
async def test_a_role_is_not_claimed_from_a_rung_that_never_asked(monkeypatch):
    _account(monkeypatch, fields_refused=("user_tasks",), user_tasks=["ANALYZE"])
    assert await meta_ads.ad_account_blockers("act_1", "tok") == []


@pytest.mark.asyncio
async def test_refusing_the_role_field_keeps_the_spend_check(monkeypatch):
    _account(monkeypatch, fields_refused=("user_tasks",), spend_cap="100", amount_spent="100")

    (card,) = await meta_ads.ad_account_blockers("act_1", "tok")

    assert card.key == "ad_account_spend_limit"


# -- Custom Audience Terms: accepted / provably not / could not tell --


def _tos(monkeypatch, result=None, *, boom=False):
    async def fake(method, endpoint, token, *a, **kw):
        if boom:
            raise meta_ads.MetaAdsError("(#200) no", code=200)
        return result

    monkeypatch.setattr(meta_ads, "_request", fake)


@pytest.mark.asyncio
async def test_accepted_terms_read_true(monkeypatch):
    _tos(monkeypatch, {"tos_accepted": {"custom_audience_tos": 1}, "id": "act_1"})
    assert await meta_ads.fetch_custom_audience_tos("act_1", "tok") is True


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", [{"custom_audience_tos": 0}, {}])
async def test_a_present_dict_without_the_flag_reads_false(monkeypatch, shape):
    _tos(monkeypatch, {"tos_accepted": shape, "id": "act_1"})
    assert await meta_ads.fetch_custom_audience_tos("act_1", "tok") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [{"id": "act_1"}, {"tos_accepted": None}, {"tos_accepted": []}])
async def test_anything_unexpected_is_unknown_never_false(monkeypatch, result):
    _tos(monkeypatch, result)
    assert await meta_ads.fetch_custom_audience_tos("act_1", "tok") is None


@pytest.mark.asyncio
async def test_a_refused_terms_read_is_unknown(monkeypatch):
    _tos(monkeypatch, boom=True)
    assert await meta_ads.fetch_custom_audience_tos("act_1", "tok") is None
