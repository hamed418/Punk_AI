"""A brand-new advertiser connects Meta and has nothing to publish with.

Finishing Meta's login says nothing about what the connection *contains*. A new
advertiser can arrive with no ad account and no Page — both are created by the
person, on Meta, and both reach Punk only when ticked on the consent screen. These
used to end in a bare "Meta credentials unavailable" crash (no ad account) or in
silence until publish (no Page). Each must instead say what to do, and hand back the
same connect button so the retry re-reads what Meta now shares.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from app.graph.builder.executors import media as media_exec
from app.services import meta_remediation as rem


# ── the cards ────────────────────────────────────────────────────────────────


def test_the_zero_state_cards_are_blocking_and_actionable():
    for key in ("no_ad_account", "no_facebook_page"):
        card = rem.render(rem.CATALOG[key])
        assert card["severity"] == "blocks"
        assert card["url"].startswith("https://")
        assert len(card["steps"]) >= 2
        # "connect again, and tick it": the asset only reaches Punk when shared.
        assert any("connect Meta again" in step for step in card["steps"])


def test_a_zero_state_card_is_never_matched_off_an_exception():
    """It describes what a connection contains, not a Meta refusal — nothing may
    resolve to it from an error, or a real permission error would show it."""
    for key in ("no_ad_account", "no_facebook_page"):
        entry = rem.CATALOG[key]
        assert not (entry.codes or entry.subcodes or entry.phrases)


def test_readiness_puts_the_missing_assets_first():
    keys = [c["key"] for c in rem.readiness(
        [rem.CATALOG["ad_account_no_payment"], rem.CATALOG["no_facebook_page"],
         rem.CATALOG["no_ad_account"]],
        ad_account_id="act_1",
    )]

    assert keys.index("no_ad_account") < keys.index("ad_account_no_payment")
    assert keys.index("no_facebook_page") < keys.index("ad_account_no_payment")


def test_prose_reads_as_one_paragraph_with_numbered_steps():
    text = rem.prose(rem.CATALOG["no_ad_account"])

    assert text.startswith("Meta shared no ad account with Punk.")
    assert "1) " in text and "2) " in text


# ── no Page ──────────────────────────────────────────────────────────────────


def _detect_pages(pages, *, ws=None):
    state = {
        "user_info": {"meta_access_token": "tok", "website_url": "https://x.example"},
        "media_wizard_state": dict(ws or {}),
    }

    async def _pages(_tok):
        return [dict(p) for p in pages]

    async def _tokens(_tok):
        return {}

    async def _forms(*_a, **_k):
        return []

    with patch.object(media_exec, "get_writer", return_value=lambda e: None), \
         patch("app.services.meta_ads.list_meta_pages", side_effect=_pages), \
         patch("app.services.meta_ads.list_page_tokens", side_effect=_tokens), \
         patch("app.services.meta_ads.list_lead_forms", side_effect=_forms):
        return asyncio.run(media_exec.media_detect_page_assets(state))["media_wizard_state"]


def test_no_pages_is_flagged_not_silent():
    ws = _detect_pages([])

    assert ws["no_facebook_page"] is True
    assert not ws.get("page_id")


def test_a_page_clears_a_stale_flag():
    ws = _detect_pages([{"id": "pg_1", "name": "P", "instagram": None}],
                       ws={"no_facebook_page": True})

    assert "no_facebook_page" not in ws
    assert ws["page_id"] == "pg_1"


# ── no ad account ────────────────────────────────────────────────────────────


def _check_auth(creds_sequence):
    """``media_check_meta_auth`` for a user who is already connected, with the
    credential reads returning ``creds_sequence`` in turn."""
    asks: list[dict] = []
    reads = iter(creds_sequence)
    last = {}

    async def _creds(_uid):
        nonlocal last
        last = next(reads, last)
        return last

    async def _no_accounts(_tok):
        return []

    async def _interrupt(_writer, **kw):
        asks.append(kw)
        return None

    state = {
        "user_id": "u1",
        "user_info": {},
        # Skips the first-entry handoff, which talks to the narrator.
        "media_wizard_state": {"_media_entry_done": True},
    }
    with patch.object(media_exec, "get_writer", return_value=lambda e: None), \
         patch.object(media_exec, "get_meta_credentials", side_effect=_creds), \
         patch.object(media_exec, "list_meta_ad_accounts", side_effect=_no_accounts), \
         patch.object(media_exec, "wizard_interrupt", side_effect=_interrupt), \
         patch.object(media_exec, "stash_edits", lambda *a, **k: None):
        out = asyncio.run(media_exec.media_check_meta_auth(state))
    return out, asks


def _creds(accounts):
    return {
        "access_token": "tok", "ad_account_id": None, "accessible_accounts": accounts,
        "page_id": "", "page_name": "", "ad_account_name": "",
    }


def test_connected_with_no_ad_account_asks_for_a_reconnect_and_then_proceeds():
    out, asks = _check_auth([_creds([]), _creds([{"id": "act_9", "name": "New"}])])

    assert len(asks) == 1
    assert asks[0]["action_type_override"] == "oauth_connect"
    assert "Meta shared no ad account" in asks[0]["prompt_override"]
    assert asks[0]["options_override"][0].startswith("https://")
    assert out["media_wizard_state"]["ad_account_id"] == "act_9"


def test_still_no_ad_account_after_two_asks_gives_up_without_a_third():
    out, asks = _check_auth([_creds([])])

    assert len(asks) == 2
    assert out["media_wizard_state"]["ad_account_id"] is None


def test_an_account_already_there_asks_nothing():
    out, asks = _check_auth([_creds([{"id": "act_1", "name": "A"}])])

    assert asks == []
    assert out["media_wizard_state"]["ad_account_id"] == "act_1"


# -- Page readiness flags: set only on a provable answer --


def test_an_unpublished_default_page_is_flagged():
    ws = _detect_pages([{"id": "p1", "name": "Draft", "instagram": None, "is_published": False}])
    assert ws["page_unpublished"] is True


def test_a_page_without_the_role_is_flagged():
    ws = _detect_pages([{"id": "p1", "name": "X", "instagram": None, "can_advertise": False}])
    assert ws["page_role_missing"] is True


def test_absent_readiness_fields_flag_nothing():
    ws = _detect_pages([{"id": "p1", "name": "X", "instagram": None}])
    assert "page_unpublished" not in ws and "page_role_missing" not in ws


def test_a_healthy_page_clears_a_stale_flag():
    ws = _detect_pages(
        [{"id": "p1", "name": "X", "instagram": None, "is_published": True, "can_advertise": True}],
        ws={"page_unpublished": True, "page_role_missing": True},
    )
    assert "page_unpublished" not in ws and "page_role_missing" not in ws
