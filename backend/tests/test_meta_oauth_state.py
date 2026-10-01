"""Meta OAuth: one state store, one scope list, one liveness rule.

The chat-path connect step used to mint its authorization URL from a *second*
``_OAUTH_STATE_STORE`` (``app/services/ads_service.py``) while
``/ads/callback/meta`` popped from the one in ``app/modules/ads/service.py``.
Every state token the graph produced was therefore unresolvable at the callback
("Invalid or expired OAuth state token"), so connecting from a conversation
never stored a token — while the profile page, which used the module store on
both ends, worked. These tests pin the invariants that regression violated.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.ads.service import (
    META_SCOPES,
    AdsService,
    _token_is_live,
    build_meta_auth_url,
)
from app.services import meta_ads

# A Business Integration System User token — what every login configuration in
# use now mints. Feeding this through fetch_token_info makes exchange_meta_code
# take the BISU branch (skip fb_exchange_token) that these tests exercise. Meta's
# debug_token reports this as "SYSTEM_USER" (measured live), not the documented
# long form — both are members of BISU_TOKEN_TYPES.
_FAKE_BISU_INFO = {
    "scopes": [], "type": "SYSTEM_USER", "expires_at": 0, "granular_scopes": [],
}


def _service() -> AdsService:
    return AdsService(repository=SimpleNamespace())


@pytest.mark.asyncio
async def test_graph_built_state_resolves_at_the_callback():
    """A URL built by the module-level helper (what the graph calls) must be
    redeemable by exchange_meta_code (what the callback calls)."""
    state = build_meta_auth_url("user-42")["state"]

    svc = _service()
    svc.repository = SimpleNamespace(save_user_oauth_tokens=AsyncMock())
    svc._list_meta_ads_accounts_from_token = AsyncMock(return_value=[])

    client = AsyncMock()
    client.get = AsyncMock(return_value=SimpleNamespace(json=lambda: {"access_token": "short-token"}))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.modules.ads.service.httpx.AsyncClient", return_value=client), \
         patch.object(meta_ads, "fetch_token_info", AsyncMock(return_value=_FAKE_BISU_INFO)), \
         patch.object(meta_ads, "list_meta_pages", AsyncMock(return_value=[])):
        result = await svc.exchange_meta_code(db=object(), code="c0de", state=state)

    assert result["user_id"] == "user-42"
    assert result["connected"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reported_type",
    ["SYSTEM_USER", "system_user", "business_integration_system_user_access_token"],
)
async def test_bisu_type_is_recognized_regardless_of_casing_or_form(reported_type):
    """The bug this pins: debug_token returns "SYSTEM_USER" live, not the
    documented "business_integration_system_user_access_token" the classifier
    used to compare against — so every BISU token was silently stored as
    token_type='user' and took the fb_exchange_token hop below, which errors on
    an already-long-lived token."""
    state = build_meta_auth_url("user-42")["state"]
    svc = _service()
    saved: dict = {}
    # save_user_oauth_tokens(user_id, platform, tokens, db) — positional.
    svc.repository = SimpleNamespace(
        save_user_oauth_tokens=AsyncMock(side_effect=lambda *a, **kw: saved.update(tokens=a[2]))
    )
    svc._list_meta_ads_accounts_from_token = AsyncMock(return_value=[])

    client = AsyncMock()
    client.get = AsyncMock(return_value=SimpleNamespace(json=lambda: {"access_token": "short-token"}))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    fake_info = {**_FAKE_BISU_INFO, "type": reported_type}
    with patch("app.modules.ads.service.httpx.AsyncClient", return_value=client) as client_cls, \
         patch.object(meta_ads, "fetch_token_info", AsyncMock(return_value=fake_info)), \
         patch.object(meta_ads, "list_meta_pages", AsyncMock(return_value=[])):
        await svc.exchange_meta_code(db=object(), code="c0de", state=state)

    # fb_exchange_token is a second call through the same AsyncClient context
    # manager — a BISU token must never take that hop.
    assert client_cls.call_count == 1, "fb_exchange_token ran against a BISU token"
    assert saved["tokens"]["token_type"] == "system_user"


@pytest.mark.asyncio
async def test_state_is_single_use():
    """Redeeming twice must fail — the retry path mints a fresh URL for exactly
    this reason."""
    state = build_meta_auth_url("user-42")["state"]
    svc = _service()
    svc.repository = SimpleNamespace(save_user_oauth_tokens=AsyncMock())
    svc._list_meta_ads_accounts_from_token = AsyncMock(return_value=[])

    client = AsyncMock()
    client.get = AsyncMock(return_value=SimpleNamespace(json=lambda: {"access_token": "t"}))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.modules.ads.service.httpx.AsyncClient", return_value=client), \
         patch.object(meta_ads, "fetch_token_info", AsyncMock(return_value=_FAKE_BISU_INFO)), \
         patch.object(meta_ads, "list_meta_pages", AsyncMock(return_value=[])):
        await svc.exchange_meta_code(db=object(), code="c0de", state=state)
        with pytest.raises(ValueError, match="Invalid or expired OAuth state token"):
            await svc.exchange_meta_code(db=object(), code="c0de", state=state)


def test_graph_and_profile_build_identical_urls():
    """The graph imports the function; the router calls the method. Divergence
    here is how the two scope lists drifted apart in the first place."""
    from app.graph.builder.executors.media import build_meta_auth_url as graph_fn

    assert graph_fn is build_meta_auth_url

    url = build_meta_auth_url("u")["authorization_url"]
    method_url = _service().build_meta_auth_url("u")["authorization_url"]
    # Only the state token differs.
    assert url.split("&state=")[0] == method_url.split("&state=")[0]


def test_scopes_cover_page_and_instagram_assets():
    """media_detect_page_assets reads /me/accounts and the Page's linked IG
    account; without these the builder resolves neither."""
    for scope in ("pages_show_list", "pages_manage_ads", "instagram_basic"):
        assert scope in META_SCOPES


@pytest.mark.parametrize(
    "token, expected",
    [
        (None, False),
        (SimpleNamespace(is_valid=False, expires_at=None), False),
        (SimpleNamespace(is_valid=True, expires_at=None), True),
        (
            SimpleNamespace(
                is_valid=True,
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            ),
            False,
        ),
        (
            SimpleNamespace(
                is_valid=True,
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            ),
            True,
        ),
        # Naive datetimes come back from some drivers — treated as UTC, not crash.
        (
            SimpleNamespace(
                is_valid=True,
                expires_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1),
            ),
            False,
        ),
    ],
)
def test_status_liveness_matches_get_meta_credentials(token, expected):
    """/ads/status is what the chat widget polls to decide the OAuth landed. If
    it calls a dead token "connected", the widget resumes into a graph that
    disagrees and the run dies on 'Meta credentials unavailable after auth flow'."""
    assert _token_is_live(token) is expected


# ── the login configuration id ───────────────────────────────────────────────
# The configuration in the App Dashboard — not ``scope=`` — decides what a token
# carries, and its id is consumed in exactly one f-string. Empty used to produce a
# URL Meta answers with an error page, indistinguishable from "Meta is down".


@pytest.fixture(autouse=True)
def _login_config_id(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "META_LOGIN_CONFIG_ID", "cfg-test")


def test_the_auth_url_carries_the_login_configuration():
    assert "config_id=cfg-test" in build_meta_auth_url("u")["authorization_url"]


def test_an_unset_login_configuration_refuses_to_build_a_url(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "META_LOGIN_CONFIG_ID", "")
    with pytest.raises(ValueError, match="META_LOGIN_CONFIG_ID"):
        build_meta_auth_url("u")
