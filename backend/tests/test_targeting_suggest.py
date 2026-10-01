"""Autofill options for the plan editor's detailed-targeting field.

Covers the two sources — Meta's "more like this" when interests are already
picked, and business-context phrases when none are — plus the dedupe/cap that
keeps the row short.
"""

import pytest

from app.modules.ads.repository import AdsRepository
from app.modules.ads.service import AdsService


def _row(rid: str, name: str) -> dict:
    return {"id": rid, "name": name, "flex_field": "interests"}


@pytest.fixture
def service(monkeypatch):
    svc = AdsService(AdsRepository())

    async def _token(*_a, **_k):
        return "tok"

    monkeypatch.setattr(svc, "get_meta_access_token", _token)
    return svc


@pytest.mark.asyncio
async def test_seeds_ask_meta_for_more_like_this(service, monkeypatch):
    calls: list[dict] = []

    async def _search(query, token, *, kind="interests", limit=25):
        calls.append({"query": query, "kind": kind})
        return [_row("1", "Related")]

    monkeypatch.setattr("app.services.meta_ads.search_targeting_interests", _search)

    out = await service.suggest_meta_targeting(None, "u", "sess", "Coffee,Espresso")

    assert out == [_row("1", "Related")]
    assert calls == [{"query": "Coffee,Espresso", "kind": "suggestions"}]


@pytest.mark.asyncio
async def test_no_seeds_defaults_to_broad_targeting_empty(service):
    """When no seeds are provided, suggest_meta_targeting returns [] (broad audience)."""
    out = await service.suggest_meta_targeting(None, "u", "sess", "")
    assert out == []


@pytest.mark.asyncio
async def test_meta_not_connected_degrades_to_empty(monkeypatch):
    svc = AdsService(AdsRepository())

    async def _no_token(*_a, **_k):
        return None

    monkeypatch.setattr(svc, "get_meta_access_token", _no_token)

    assert await svc.suggest_meta_targeting(None, "u", "sess", "Coffee") == []


@pytest.mark.asyncio
async def test_phrases_empty_without_session():
    svc = AdsService(AdsRepository())
    assert await svc._business_interest_phrases(None, "u", None) == []


@pytest.mark.asyncio
async def test_phrases_refuses_a_session_the_caller_does_not_own(monkeypatch):
    """The session_id comes off the query string. Reading graph state for one the
    caller does not own leaked another tenant's business context."""
    svc = AdsService(AdsRepository())

    async def _not_owned(_self, _db, _session_id, _user_id):
        return None

    def _boom():
        raise AssertionError("graph state must not be read for an unowned session")

    monkeypatch.setattr(
        "app.modules.chat.repository.ChatRepository.find_specific_user_chat",
        _not_owned,
    )
    monkeypatch.setattr("app.graph.graph.get_graph", _boom)

    assert await svc._business_interest_phrases(None, "attacker", "someone-elses") == []
