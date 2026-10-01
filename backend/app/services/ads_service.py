"""
app/services/ads_service.py
Handles OAuth flows for Google Ads and Meta Ads.
Stores tokens securely and provides authenticated API client builders.

NOTE: This is a scaffold. Replace TODOs with production OAuth + API logic.
"""
from __future__ import annotations

import secrets
from typing import Any, Dict, List
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.modules.ads.models import OAuthToken
from sqlalchemy import select
from datetime import datetime, timedelta, timezone
 
from app.shared.enums import AdPlatform

# ── CSRF state store (in-memory; use a shared store in production) ────────────
_OAUTH_STATE_STORE: Dict[str, str] = {}  # state_token -> user_id


# ════════════════════════════════════════════════════════════════
# Google Ads OAuth
# ════════════════════════════════════════════════════════════════

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/adwords",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

 

def build_google_auth_url(user_id: str) -> Dict[str, str]:
    """
    Step 1: Generate Google OAuth authorization URL.
    The user is redirected here to grant ad account access.
    """
    state = secrets.token_urlsafe(32)
    _OAUTH_STATE_STORE[state] = user_id

    params = {
        "client_id": settings.GOOGLE_ADS_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_ADS_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }

    # query_string = "&".join(f"{k}={v}" for k, v in params.items())
    from urllib.parse import urlencode
    query_string = urlencode(params)
    auth_url = f"{GOOGLE_AUTH_URL}?{query_string}"

    return {"authorization_url": auth_url, "state": state}


async def exchange_google_code(code: str, state: str, db: AsyncSession) -> Dict[str, Any]:
    """
    Step 2: Exchange authorization code for access + refresh tokens.
    Stores tokens in DB.
    """
    user_id = _OAUTH_STATE_STORE.pop(state, None)
    if not user_id:
        raise ValueError("Invalid or expired OAuth state token")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_ADS_CLIENT_ID,
                "client_secret": settings.GOOGLE_ADS_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_ADS_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        if resp.is_error:
            logger.error("Google token exchange failed", status_code=resp.status_code, body=resp.text)
        resp.raise_for_status()
        tokens = resp.json()

    # Discover and store accessible accounts
    try:
        accounts = await list_google_ads_accounts_from_tokens(
            refresh_token=tokens.get("refresh_token") or "",
            user_id=user_id
        )
        tokens["accessible_accounts"] = accounts
    except Exception as exc:
        logger.warning("Auto account discovery failed", user_id=user_id, error=str(exc))

    # Store tokens + discovered accounts in DB
    await save_user_google_tokens(user_id, tokens, db)

    logger.info("Google OAuth token exchanged and accounts discovered", user_id=user_id)
    return {"user_id": user_id, "platform": "google", "connected": True, "access_token": tokens.get("access_token")}


async def save_user_oauth_tokens(
    user_id: str,
    platform: AdPlatform,
    tokens: Dict[str, Any],
    db: AsyncSession
) -> None:
    """Save or update OAuth tokens for a specific platform in the database.

    Delegates to ``AdsRepository``. This used to be a second, near-identical copy
    of that method — identical except that it did not maintain
    ``selected_account``, so which writer ran decided whether the user's account
    choice survived. One writer, one behaviour.
    """
    from app.modules.ads.repository import AdsRepository

    await AdsRepository().save_user_oauth_tokens(user_id, platform, tokens, db)


async def save_user_google_tokens(user_id: str, tokens: Dict[str, Any], db: AsyncSession) -> None:
    """Legacy helper, now wraps generic save_user_oauth_tokens."""
    await save_user_oauth_tokens(user_id, AdPlatform.google, tokens, db)


async def refresh_oauth_token(user_id: str, platform: AdPlatform, db: AsyncSession) -> bool:
    """
    Refreshes the OAuth access token for a given platform and user.
    Returns True if successful, False otherwise.
    """
    stmt = select(OAuthToken).where(
        OAuthToken.user_id == user_id,
        OAuthToken.platform == platform
    )
    result = await db.execute(stmt)
    token_obj = result.scalar_one_or_none()

    if not token_obj:
        logger.warning("No token found to refresh", user_id=user_id, platform=platform)
        return False

    if platform == AdPlatform.google:
        if not token_obj.refresh_token:
            logger.warning("No refresh token for Google Ads", user_id=user_id)
            return False

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": settings.GOOGLE_ADS_CLIENT_ID,
                    "client_secret": settings.GOOGLE_ADS_CLIENT_SECRET,
                    "refresh_token": token_obj.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            if resp.is_error:
                logger.error("Google token refresh failed", status_code=resp.status_code, body=resp.text)
                if resp.status_code == 400 and "invalid_grant" in resp.text:
                    token_obj.is_valid = False
                    await db.commit()
                    logger.warning("Google refresh token revoked or expired. Marked as invalid.", user_id=user_id)
                return False

            tokens = resp.json()
            await save_user_oauth_tokens(user_id, platform, tokens, db)
            return True

    elif platform == AdPlatform.meta:
        # Meta long-lived tokens last 60 days and are refreshed by exchanging a
        # still-valid long-lived token for a fresh one. The grant is
        # ``fb_exchange_token`` — the same one the initial short→long exchange
        # uses (app.modules.ads.service). ``fb_extend_token`` is not a Meta grant
        # type; it silently failed here and the token was never actually renewed.
        if not token_obj.access_token:
            return False

        # A Business Integration System User token never expires and
        # fb_exchange_token errors on an already-long-lived token. Nothing to
        # refresh — report success so callers don't treat a no-op as a failure.
        if getattr(token_obj, "token_type", "user") == "system_user":
            return True

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                META_TOKEN_URL,
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": settings.META_APP_ID,
                    "client_secret": settings.META_APP_SECRET,
                    "fb_exchange_token": token_obj.access_token,
                },
            )
            if resp.is_error:
                logger.error("Meta token refresh failed", status_code=resp.status_code, body=resp.text)
                # A token Meta refuses to extend is dead or revoked — mark it so
                # callers re-fire the Connect-Meta widget instead of retrying a
                # refresh that cannot succeed.
                if resp.status_code in (400, 401):
                    token_obj.is_valid = False
                    await db.commit()
                return False

            tokens = resp.json()
            await save_user_oauth_tokens(user_id, platform, tokens, db)
            return True

    return False


# ════════════════════════════════════════════════════════════════
# Meta (Facebook) Ads OAuth
# ════════════════════════════════════════════════════════════════
# Only the token endpoint lives here now (refresh_platform_token above uses it).
# Authorization-URL building and code exchange belong to
# ``app.modules.ads.service`` — that module owns the CSRF state store the
# /ads/callback/meta route pops from, and a second copy here minted state
# tokens the callback could never resolve.

META_TOKEN_URL = f"{settings.META_GRAPH_URL}oauth/access_token"


async def list_google_ads_accounts_from_tokens(refresh_token: str, user_id: str) -> List[Dict[str, str]]:
    """Fetch accessible customer IDs given a refresh token."""
    credentials = {
        "developer_token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
        "client_id": settings.GOOGLE_ADS_CLIENT_ID,
        "client_secret": settings.GOOGLE_ADS_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "use_proto_plus": True,
    }

    try:
        from google.ads.googleads.client import GoogleAdsClient
        client = GoogleAdsClient.load_from_dict(credentials)
        customer_service = client.get_service("CustomerService")

        # list_accessible_customers returns a list of resource names
        accessible_customers = customer_service.list_accessible_customers()

        accounts = []
        for resource_name in accessible_customers.resource_names:
            customer_id = resource_name.split("/")[-1]
            accounts.append({
                "id": customer_id,
                "name": f"Account {customer_id}"
            })

        return accounts
    except Exception as exc:
        logger.error("Failed to discover Google Ads accounts", user_id=user_id, error=str(exc))
        raise ValueError(f"Google Ads API error: {str(exc)}")



async def disconnect_google_account(user_id: str, db: AsyncSession) -> bool:
    """Remove Google Ads OAuth token for the user."""
    stmt = select(OAuthToken).where(
        OAuthToken.user_id == user_id,
        OAuthToken.platform == AdPlatform.google
    )
    result = await db.execute(stmt)
    token_obj = result.scalar_one_or_none()

    if not token_obj:
        return False

    await db.delete(token_obj)
    await db.commit()
    logger.info("Google Ads account disconnected", user_id=user_id)
    return True


async def disconnect_meta_account(user_id: str, db: AsyncSession) -> bool:
    """Remove Meta Ads OAuth token for the user."""
    stmt = select(OAuthToken).where(
        OAuthToken.user_id == user_id,
        OAuthToken.platform == AdPlatform.meta
    )
    result = await db.execute(stmt)
    token_obj = result.scalar_one_or_none()

    if not token_obj:
        return False

    await db.delete(token_obj)
    await db.commit()
    logger.info("Meta Ads account disconnected", user_id=user_id)
    return True
