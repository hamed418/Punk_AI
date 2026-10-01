"""Credentials must not leak out of the places that hold them.

Three separate paths used to hand a live 60-day Meta ``ads_management`` token to
somewhere it did not belong: the OAuth redirect URL, the ``/agent-state``
response body, and a reconnect that quietly reset the user's account choice.
"""
from types import SimpleNamespace

import pytest

from app.modules.ads.repository import AdsRepository
from app.modules.chat.service import _redact_secrets


# ── /chat/{id}/agent-state ───────────────────────────────────────────────────


def test_redacts_tokens_anywhere_in_the_state_tree():
    state = {
        "user_info": {
            "business_name": "Bean There",
            "meta_access_token": "EAA-live-token",
            "meta_ad_account_id": "act_1",
        },
        "media_wizard_state": {"access_token": "EAA-live-token", "page_id": "9"},
        "geo_data": {"pois": [{"name": "cafe", "refresh_token": "r-1"}]},
    }

    out = _redact_secrets(state)

    assert out["user_info"]["meta_access_token"] == "***redacted***"
    assert out["media_wizard_state"]["access_token"] == "***redacted***"
    assert out["geo_data"]["pois"][0]["refresh_token"] == "***redacted***"
    # Everything that is not a credential survives untouched — the endpoint
    # exists to return state, redaction must not gut it.
    assert out["user_info"]["business_name"] == "Bean There"
    assert out["user_info"]["meta_ad_account_id"] == "act_1"
    assert out["media_wizard_state"]["page_id"] == "9"
    assert out["geo_data"]["pois"][0]["name"] == "cafe"


def test_redaction_leaves_empty_credential_fields_alone():
    """An absent token reads as "not connected" in the UI. Replacing it with a
    redaction marker would make a disconnected account look connected."""
    assert _redact_secrets({"access_token": ""}) == {"access_token": ""}
    assert _redact_secrets({"access_token": None}) == {"access_token": None}


def test_redaction_passes_through_scalars_and_lists():
    assert _redact_secrets("plain") == "plain"
    assert _redact_secrets([1, {"password": "hunter2"}]) == [1, {"password": "***redacted***"}]


# ── OAuth callback ───────────────────────────────────────────────────────────


class _FakeToken:
    def __init__(self, **kw):
        # The ads_accounts rows the callback mirrors hang off this id.
        self.id = "token-1"
        self.access_token = None
        self.refresh_token = None
        self.expires_at = None
        self.scopes = None
        self.ad_account_id = None
        self.ad_account_name = None
        self.accessible_accounts = None
        self.selected_account = None
        self.page_id = None
        self.page_name = None
        self.is_valid = True
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeDB:
    """Enough AsyncSession for save_user_oauth_tokens."""

    def __init__(self, existing=None):
        self.existing = existing
        self.added = []
        self.committed = False

    async def execute(self, _stmt):
        existing = self.existing

        class _Result:
            def scalar_one_or_none(self):
                return existing

            def scalars(self):
                # The ads_accounts sweep that mirrors accessible_accounts into rows.
                # Nothing stored here: these tests are about which account the
                # connection points at, not about the mirror.
                return SimpleNamespace(all=lambda: [])

        return _Result()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def delete(self, obj):
        pass

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_empty_accessible_accounts_does_not_crash_the_callback():
    """A brand-new advertiser has no ad account yet. This used to be
    ``accessible_accounts[0]["id"]`` — an IndexError that 500'd /ads/callback/meta
    for exactly the users most likely to be signing up."""
    token = _FakeToken()
    db = _FakeDB(existing=token)

    await AdsRepository().save_user_oauth_tokens(
        "u1", "meta", {"access_token": "t", "accessible_accounts": []}, db
    )

    assert token.selected_account is None
    assert db.committed


@pytest.mark.asyncio
async def test_reconnect_keeps_the_users_chosen_account():
    """Reconnecting used to reset selected_account to accounts[0], silently
    moving a multi-account user back to their first ad account."""
    token = _FakeToken(selected_account="act_2")
    db = _FakeDB(existing=token)

    await AdsRepository().save_user_oauth_tokens(
        "u1",
        "meta",
        {
            "access_token": "t",
            "accessible_accounts": [{"id": "act_1"}, {"id": "act_2"}],
        },
        db,
    )

    assert token.selected_account == "act_2"


@pytest.mark.asyncio
async def test_a_stale_choice_falls_back_to_the_first_account():
    """If the account they had picked is no longer one they can reach, pick
    something real rather than leaving a dangling id."""
    token = _FakeToken(selected_account="act_gone")
    db = _FakeDB(existing=token)

    await AdsRepository().save_user_oauth_tokens(
        "u1",
        "meta",
        {"access_token": "t", "accessible_accounts": [{"id": "act_1"}]},
        db,
    )

    assert token.selected_account == "act_1"


# ── get_meta_credentials: selected_account is the account of record ────────────


@pytest.mark.asyncio
async def test_publish_reads_the_switched_account_not_the_first_one():
    """A user with several ad accounts switches via PUT /ads/update-selected-
    account, which writes only selected_account. media.py and
    campaign_manager_node.py both read creds["ad_account_id"] from this dict —
    if it does not prefer selected_account, a switch is invisible to publish
    and spend lands in the account the user switched away from."""
    from unittest.mock import AsyncMock, patch

    from app.services.oauth import get_meta_credentials

    token = _FakeToken(
        access_token="EAA-live",
        ad_account_id="act_1",
        selected_account="act_2",
        accessible_accounts=[{"id": "act_1"}, {"id": "act_2"}],
        is_valid=True,
    )

    class _Result:
        def scalar_one_or_none(self):
            return token

    class _Db:
        async def execute(self, _stmt):
            return _Result()

        async def refresh(self, _obj):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    with patch("app.services.oauth.AsyncSessionLocal", return_value=_Db()):
        creds = await get_meta_credentials("u1")

    assert creds["ad_account_id"] == "act_2"
    assert creds["selected_account"] == "act_2"


@pytest.mark.asyncio
async def test_publish_falls_back_to_ad_account_id_when_never_selected():
    """A row written before selected_account existed (or a single-account user
    who never hit the picker) must still resolve to something rather than
    None."""
    from unittest.mock import patch

    from app.services.oauth import get_meta_credentials

    token = _FakeToken(
        access_token="EAA-live",
        ad_account_id="act_1",
        selected_account=None,
        is_valid=True,
    )

    class _Result:
        def scalar_one_or_none(self):
            return token

    class _Db:
        async def execute(self, _stmt):
            return _Result()

        async def refresh(self, _obj):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    with patch("app.services.oauth.AsyncSessionLocal", return_value=_Db()):
        creds = await get_meta_credentials("u1")

    assert creds["ad_account_id"] == "act_1"


# ── app.log ──────────────────────────────────────────────────────────────────


def test_httpx_does_not_log_the_google_maps_key_into_app_log():
    """httpx logs the full request URL at INFO, and the Geocoding API takes its
    key in the query string — so `key=AIza...` was landing in app.log verbatim.
    (Places is safe: it passes the key in an X-Goog-Api-Key header.)"""
    import logging

    from app.core.logging import configure_logging

    configure_logging()

    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).level >= logging.WARNING, name
