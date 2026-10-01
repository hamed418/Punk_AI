"""
services/oauth.py
─────────────────
Meta OAuth token storage and retrieval helpers.

Used by media_wizard to check whether the current user has already connected
their Meta Ads account. The authorization URL itself is built by
``ads_service.build_meta_auth_url``, which owns the scope list.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.modules.ads.models import OAuthToken

logger = logging.getLogger(__name__)

# Meta long-lived tokens last ~60 days. Renewing inside the last week is early
# enough that an idle account still gets refreshed by ordinary use, and late
# enough that this is not doing an exchange on every call.
_REFRESH_WHEN_WITHIN = timedelta(days=7)


async def _try_refresh(user_id: str, db) -> bool:
    """Exchange the Meta token for a fresh one. Never raises.

    Imported inside the call to keep this module free of the ads-service import
    chain, which reaches back into the request layer.
    """
    try:
        from app.services.ads_service import refresh_oauth_token
        from app.shared.enums import AdPlatform

        return await refresh_oauth_token(user_id, AdPlatform.meta, db)
    except Exception as exc:  # noqa: BLE001 — a failed renewal must not break a valid token
        logger.warning("oauth: Meta token refresh for user %s failed — %s", user_id, exc)
        return False


async def get_meta_credentials(user_id: str) -> dict[str, Any] | None:
    """
    Return stored Meta OAuth credentials for user_id, or None if not connected.

    Keys in result: access_token, ad_account_id, ad_account_name,
    accessible_accounts (list[dict with id/name]), selected_account, page_id,
    page_name.
    """
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(OAuthToken).where(
                    OAuthToken.user_id == user_id,
                    OAuthToken.platform == "meta",
                    OAuthToken.is_valid.is_(True),
                )
            )
            token = result.scalar_one_or_none()
            if token is None:
                return None
            # An expired token is effectively "not connected" — return None so
            # callers (media_check_meta_auth) re-fire the Connect-Meta widget
            # instead of trusting a dead access_token.
            if token.expires_at is not None:
                exp = token.expires_at
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                if exp <= now:
                    logger.info("oauth: Meta token for user %s expired at %s — treating as not connected", user_id, exp)
                    return None
                # Renew before it dies rather than after. Nothing schedules a
                # refresh, so without this the 60-day token simply lapsed and the
                # next publish failed on a token that was still renewable an hour
                # earlier. Best-effort: a failed refresh leaves the still-valid
                # token in place and this call proceeds with it.
                if exp - now <= _REFRESH_WHEN_WITHIN:
                    if await _try_refresh(user_id, db):
                        await db.refresh(token)
            return {
                "access_token": token.access_token,
                # selected_account is the single column of record — the one
                # AdsRepository.update_selected_account writes and the one the
                # picker/reconnect logic (AdsRepository.save_user_oauth_tokens)
                # keeps in sync with what Meta actually granted.  ad_account_id
                # is legacy bookkeeping (whichever account was first on the
                # list at initial connect) and stays only as a fallback for
                # rows written before selected_account existed. Every caller in
                # the codebase reads this dict's "ad_account_id" key expecting
                # it to mean "the account we publish into" — two of them
                # (media.py, campaign_manager_node.py) took the raw column
                # literally and kept publishing into the account a user had
                # switched away from. Fix it here, once, so no caller can get
                # it wrong again.
                "ad_account_id": token.selected_account or token.ad_account_id,
                "ad_account_name": token.ad_account_name,
                "accessible_accounts": token.accessible_accounts or [],
                "selected_account": token.selected_account,
                "page_id": token.page_id,
                "page_name": token.page_name,
            }
    except Exception as exc:
        # error, not warning: every caller reads None as "this user has not
        # connected Meta", so a database or mapper problem here shows a connected
        # user the Connect-Meta widget with nothing in the logs to explain it.
        # Reached during this audit when a script imported only some ORM models —
        # SQLAlchemy could not resolve a relationship, mapper configuration
        # raised, and the account read as disconnected.
        logger.error(
            "oauth: Meta credential lookup FAILED for user %s — reporting 'not "
            "connected', which is probably wrong. %s: %s",
            user_id, type(exc).__name__, exc, exc_info=True,
        )
        return None


async def mark_meta_token_invalid(user_id: str, reason: str = "") -> None:
    """Flag this user's Meta token dead so the app stops pretending it works.

    Nothing used to clear ``is_valid`` in response to Meta rejecting a token —
    only a failed *refresh* did. So a user who revoked Punk in their Business
    Settings (or changed their password, or lost their ad-account role) kept a
    row that said "connected" while every publish failed on error 190, with no
    path back other than noticing and reconnecting by hand.

    Best-effort by design: this runs on an error path, and failing to record the
    invalidation must not replace the original Meta error with a database one.
    """
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(OAuthToken).where(
                    OAuthToken.user_id == user_id,
                    OAuthToken.platform == "meta",
                )
            )
            token = result.scalar_one_or_none()
            if token is None or not token.is_valid:
                return
            token.is_valid = False
            await db.commit()
            logger.warning(
                "oauth: marked Meta token for user %s invalid — %s",
                user_id, reason or "rejected by Meta",
            )
    except Exception as exc:  # noqa: BLE001 — never mask the caller's real error
        logger.warning("oauth: could not invalidate Meta token for %s — %s", user_id, exc)


async def list_meta_ad_accounts(access_token: str) -> list[dict[str, Any]]:
    """
    Fetch all ad accounts accessible to this token from the Meta Graph API.
    Returns list of {id, name} dicts. Empty list on any failure.
    """
    from app.services.meta_ads import MetaAdsError, _request

    try:
        result = await _request(
            "GET", "me/adaccounts", access_token,
            json_data={"fields": "id,name,account_status"}, timeout=10.0,
        )
        return result.get("data") or []
    except MetaAdsError as exc:
        logger.warning("oauth: list_meta_ad_accounts failed — %s", exc)
        return []
