"""
tests/test_lead_retrieval_permission.py
───────────────────────────────────────
Reading an instant form's leads needs its own grant (``leads_retrieval``), which
``pages_manage_ads`` does not imply. When it is missing, Meta answers with a
permission code — and an empty leads table is the one wrong way to render that,
because it is indistinguishable from "nobody has submitted yet" and never
resolves on its own.

Two things are locked here: the scope is requested at connect time, and a
permission failure surfaces instead of degrading to ``[]``.
"""
from __future__ import annotations

import pytest

from app.modules.ads.service import META_SCOPES
from app.services import meta_ads


def test_leads_retrieval_is_requested():
    assert "leads_retrieval" in META_SCOPES


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [3, 10, 190, 200])
async def test_permission_failure_raises_with_actionable_wording(monkeypatch, code):
    async def _fake_request(*_a, **_kw):
        raise meta_ads.MetaAdsError("(#200) Requires leads_retrieval", code=code)

    monkeypatch.setattr(meta_ads, "_request", _fake_request)

    with pytest.raises(meta_ads.MetaAdsError) as excinfo:
        await meta_ads.fetch_form_leads("999", "tok")

    # The raw Graph text names an OAuth scope, which means nothing to an
    # advertiser; user_msg is what the router puts on screen.
    assert "lead access" in (excinfo.value.user_msg or "")


@pytest.mark.asyncio
async def test_transient_failure_still_degrades_to_empty(monkeypatch):
    async def _fake_request(*_a, **_kw):
        raise meta_ads.MetaAdsError("temporarily unavailable", code=2)

    monkeypatch.setattr(meta_ads, "_request", _fake_request)

    assert await meta_ads.fetch_form_leads("999", "tok") == []


@pytest.mark.asyncio
async def test_leads_are_flattened(monkeypatch):
    async def _fake_request(*_a, **_kw):
        return {"data": [{
            "id": "1",
            "created_time": "2026-08-08T00:00:00+0000",
            "field_data": [
                {"name": "email", "values": ["a@b.com"]},
                {"name": "phone", "values": []},
            ],
        }]}

    monkeypatch.setattr(meta_ads, "_request", _fake_request)

    leads = await meta_ads.fetch_form_leads("999", "tok")
    assert leads == [{
        "id": "1",
        "created_time": "2026-08-08T00:00:00+0000",
        "fields": {"email": "a@b.com", "phone": None},
    }]


# ── Instant-form writes use the Page token ──────────────────────────────────
# leadgen_forms answers a user token with "(#190) This method must be called with a
# Page Access Token". The read (list_lead_forms) already traded for one; the write
# did not, so every publish that had to create a form failed on it.


def _record_requests(monkeypatch, *, pages: dict[str, str]):
    seen: list[tuple[str, str, str]] = []

    async def _fake_request(method, path, token, json_data=None, **_):
        seen.append((method, path, token))
        if path == "me/accounts":
            return {"data": [{"id": p, "access_token": t} for p, t in pages.items()]}
        return {"id": "form-1"}

    monkeypatch.setattr(meta_ads, "_request", _fake_request)
    return seen


@pytest.mark.asyncio
async def test_create_lead_form_writes_with_the_traded_page_token(monkeypatch):
    seen = _record_requests(monkeypatch, pages={"pg_1": "page-tok"})

    await meta_ads.create_lead_form(
        "pg_1", name="F", questions=["EMAIL"],
        privacy_policy_url="https://x.example/p", access_token="user-tok",
    )

    assert ("POST", "pg_1/leadgen_forms", "page-tok") in seen
    assert not any(t == "user-tok" and p.endswith("leadgen_forms") for _, p, t in seen)


@pytest.mark.asyncio
async def test_create_lead_form_uses_a_page_token_the_caller_already_traded(monkeypatch):
    seen = _record_requests(monkeypatch, pages={})

    await meta_ads.create_lead_form(
        "pg_1", name="F", questions=["EMAIL"],
        privacy_policy_url="https://x.example/p", access_token="user-tok",
        page_token="handed-in",
    )

    assert seen == [("POST", "pg_1/leadgen_forms", "handed-in")]


@pytest.mark.asyncio
async def test_create_lead_form_falls_back_to_the_user_token_when_no_trade(monkeypatch):
    """No Page token obtainable is not a reason to send nothing — the user token
    is what it did before, and Meta gets to say no."""
    seen = _record_requests(monkeypatch, pages={})

    async def _no_grants(_token):
        return {"scopes": [], "type": "", "expires_at": None, "granular_scopes": []}

    monkeypatch.setattr(meta_ads, "fetch_token_info", _no_grants)

    await meta_ads.create_lead_form(
        "pg_1", name="F", questions=["EMAIL"],
        privacy_policy_url="https://x.example/p", access_token="user-tok",
    )

    assert ("POST", "pg_1/leadgen_forms", "user-tok") in seen


# ── the leads table's two reads ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_leads_are_read_with_the_forms_page_token_when_given(monkeypatch):
    seen = []

    async def _fake(method, path, token, json_data=None, **_):
        seen.append((path, token))
        return {"data": []}

    monkeypatch.setattr(meta_ads, "_request", _fake)

    await meta_ads.fetch_form_leads("f1", "user-tok", page_token="page-tok")
    await meta_ads.fetch_form_leads("f1", "user-tok")

    assert seen == [("f1/leads", "page-tok"), ("f1/leads", "user-tok")]


@pytest.mark.asyncio
async def test_the_form_list_carries_each_forms_page(monkeypatch):
    from types import SimpleNamespace

    from app.modules.ads.service import AdsService

    async def _pages(_t):
        return [{"id": "p1", "name": "One"}, {"id": "p2", "name": "Two"}]

    async def _tokens(_t):
        return {"p1": "t1"}

    async def _forms(page_id, _t, page_token=""):
        return [{"id": f"f-{page_id}", "name": "F", "status": "ACTIVE", "_tok": page_token}]

    monkeypatch.setattr(meta_ads, "list_meta_pages", _pages)
    monkeypatch.setattr(meta_ads, "list_page_tokens", _tokens)
    monkeypatch.setattr(meta_ads, "list_lead_forms", _forms)
    svc = AdsService(repository=SimpleNamespace())

    async def _tok(*_):
        return "tok"

    monkeypatch.setattr(svc, "get_meta_access_token", _tok)

    rows = await svc.list_lead_form_choices(db=object(), user_id="u")

    assert [(r["id"], r["page_id"], r["page_name"]) for r in rows] == [
        ("f-p1", "p1", "One"), ("f-p2", "p2", "Two"),
    ]
    # Each Page's own token went to its own form list.
    assert [r["_tok"] for r in rows] == ["t1", ""]
