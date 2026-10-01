"""
tests/test_page_token_trade.py
──────────────────────────────
Page-owned edges reject the user access token. Measured against Page
1803996873218871 with a token carrying every scope in ``META_SCOPES``:

    leadgen_forms    user → (#190) must be called with a Page Access Token
    published_posts  user → (#210) a page access token is required
    videos           user → 200 OK, data: []          ← the dangerous one

The third is why this is a test and not a comment: the empty array is
indistinguishable from a Page with no videos, so the boost picker rendered
"nothing here" and the instant-form dropdown offered only "create one for me",
for every advertiser, silently.

What is locked: both readers send the PAGE token, and an explicitly supplied one
skips the ``me/accounts`` trade (the builder resolves every Page in one call —
without that, it is one extra Graph round trip per Page).
"""
from __future__ import annotations

import pytest

from app.services import meta_ads

USER_TOKEN = "user-token"
PAGE_TOKEN = "page-token-123"
PAGE_ID = "1803996873218871"


def _spy(monkeypatch, *, accounts_data=None):
    """Record (endpoint, token) per call; answer me/accounts with one Page."""
    calls: list[tuple[str, str]] = []

    async def _fake_request(_method, endpoint, access_token, **_kw):
        calls.append((endpoint, access_token))
        if endpoint == "me/accounts":
            return {"data": accounts_data if accounts_data is not None
                    else [{"id": PAGE_ID, "access_token": PAGE_TOKEN}]}
        if endpoint == "debug_token":
            # list_page_tokens' granular_scopes fallback, tried when me/accounts
            # comes back empty. No page grants here — the fallback should find
            # nothing and give up rather than crash on the shape.
            return {"data": {"scopes": [], "type": "USER", "granular_scopes": []}}
        return {"data": [{"id": "form-1", "name": "Existing form", "status": "ACTIVE"}]}

    monkeypatch.setattr(meta_ads, "_request", _fake_request)
    return calls


@pytest.mark.asyncio
async def test_lead_forms_read_with_the_page_token(monkeypatch):
    calls = _spy(monkeypatch)

    forms = await meta_ads.list_lead_forms(PAGE_ID, USER_TOKEN)

    assert forms == [{"id": "form-1", "name": "Existing form", "status": "ACTIVE"}]
    assert (f"{PAGE_ID}/leadgen_forms", PAGE_TOKEN) in calls


@pytest.mark.asyncio
async def test_page_objects_read_with_the_page_token(monkeypatch):
    calls = _spy(monkeypatch)

    await meta_ads.list_page_objects(PAGE_ID, USER_TOKEN, kind="post")

    assert (f"{PAGE_ID}/published_posts", PAGE_TOKEN) in calls


@pytest.mark.asyncio
async def test_supplied_page_token_skips_the_trade(monkeypatch):
    calls = _spy(monkeypatch)

    await meta_ads.list_lead_forms(PAGE_ID, USER_TOKEN, page_token="already-have-it")

    assert calls == [(f"{PAGE_ID}/leadgen_forms", "already-have-it")]


@pytest.mark.asyncio
async def test_untradeable_page_falls_back_instead_of_breaking(monkeypatch):
    """A Page me/accounts does not list still gets a (failing) attempt, not a crash."""
    calls = _spy(monkeypatch, accounts_data=[])

    await meta_ads.list_lead_forms(PAGE_ID, USER_TOKEN)

    assert (f"{PAGE_ID}/leadgen_forms", USER_TOKEN) in calls


@pytest.mark.asyncio
async def test_me_accounts_failure_degrades_to_empty(monkeypatch):
    async def _fake_request(_method, endpoint, _token, **_kw):
        raise meta_ads.MetaAdsError("token expired", code=190)

    monkeypatch.setattr(meta_ads, "_request", _fake_request)

    assert await meta_ads.list_page_tokens(USER_TOKEN) == {}
    assert await meta_ads.list_lead_forms(PAGE_ID, USER_TOKEN) == []
    assert await meta_ads.list_page_objects(PAGE_ID, USER_TOKEN) == []


@pytest.mark.asyncio
async def test_page_tokens_never_reach_the_editor_catalog(monkeypatch):
    """page_candidates is streamed to the browser; a Page token acts AS the Page."""
    from app.graph.builder.executors import media

    async def _pages(_token):
        return [{"id": PAGE_ID, "name": "HTPL", "instagram": None}]

    async def _tokens(_token):
        return {PAGE_ID: PAGE_TOKEN}

    async def _forms(_page_id, _token, *, page_token=""):
        assert page_token == PAGE_TOKEN, "builder must pass the traded token through"
        return [{"id": "form-1", "name": "Existing form", "status": "ACTIVE"}]

    async def _website(*_a, **_kw):
        return ""

    monkeypatch.setattr(meta_ads, "list_meta_pages", _pages)
    monkeypatch.setattr(meta_ads, "list_page_tokens", _tokens)
    monkeypatch.setattr(meta_ads, "list_lead_forms", _forms)
    monkeypatch.setattr(meta_ads, "fetch_page_website", _website)

    out = await media.media_detect_page_assets(
        {"user_info": {"meta_access_token": USER_TOKEN, "meta_page_id": PAGE_ID}}
    )
    ws = out["media_wizard_state"]

    assert ws["lead_form_candidates"] == [
        {"id": "form-1", "name": "Existing form", "status": "ACTIVE"}
    ]
    assert PAGE_TOKEN not in repr(ws)
