"""``/ads/callback/meta`` — a Meta refusal must land the user back in the app.

When Meta will not complete a login (an account the app is not open to yet, a
cancelled consent screen, a misconfigured login) it redirects to the callback with
``error`` and NO ``code``. ``code`` and ``state`` were required parameters, so the
popup showed a raw 422 JSON page — the most likely failure of a private beta, and
the worst-worded one. Every other failure raised ``HTTPException``, also JSON, and
the 500 body echoed internal exception text.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from app.modules.ads import router as ads_router


def _query(response) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(response.headers["location"]).query).items()}


async def _callback(**kw):
    kw.setdefault("code", None)
    kw.setdefault("state", None)
    kw.setdefault("error", None)
    kw.setdefault("error_description", None)
    return await ads_router.meta_callback(db=object(), **kw)


@pytest.mark.asyncio
async def test_a_refusal_with_no_code_redirects_with_a_reason():
    response = await _callback(error="access_denied", error_description="User cancelled")

    assert response.status_code in (302, 307)
    assert _query(response) == {"meta_error": "denied", "meta_error_detail": "User cancelled"}


@pytest.mark.asyncio
async def test_a_bare_callback_with_nothing_is_a_refusal_not_a_422():
    assert _query(await _callback())["meta_error"] == "denied"


@pytest.mark.asyncio
async def test_metas_description_is_capped_and_encoded():
    response = await _callback(error="access_denied", error_description="a&b=c " * 100)

    query = _query(response)
    assert len(query["meta_error_detail"]) <= 200
    # Round-trips as ONE value: an ampersand in Meta's prose cannot inject a param.
    assert set(query) == {"meta_error", "meta_error_detail"}


@pytest.mark.asyncio
async def test_a_bad_state_says_expired(monkeypatch):
    async def _boom(*_a, **_k):
        raise ValueError("Invalid or expired OAuth state token")

    monkeypatch.setattr(ads_router.service, "exchange_meta_code", _boom)

    assert _query(await _callback(code="c", state="s")) == {"meta_error": "expired"}


@pytest.mark.asyncio
async def test_an_exchange_failure_never_echoes_internal_text(monkeypatch):
    async def _boom(*_a, **_k):
        raise RuntimeError("postgres password=hunter2 connection refused")

    monkeypatch.setattr(ads_router.service, "exchange_meta_code", _boom)

    response = await _callback(code="c", state="s")

    assert _query(response) == {"meta_error": "failed"}
    assert "hunter2" not in response.headers["location"]


@pytest.mark.asyncio
async def test_the_happy_path_is_unchanged(monkeypatch):
    async def _ok(*_a, **_k):
        return None

    monkeypatch.setattr(ads_router.service, "exchange_meta_code", _ok)

    assert _query(await _callback(code="c", state="s")) == {"connected": "meta"}
