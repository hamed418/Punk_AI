import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
import httpx
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.shared.enums import AdPlatform
from app.modules.ads.repository import AdsRepository

# How long a minted OAuth state stays valid. Long enough for a human to work
# through Meta's consent screens, short enough that a leaked URL is not a
# standing invitation.
_OAUTH_STATE_TTL = timedelta(minutes=30)
# Distinguishes this token from every other thing signed with SECRET_KEY, so a
# session JWT can never be replayed as an OAuth state (or the reverse), and a
# Meta state cannot be presented to the Google callback.
_OAUTH_STATE_AUDIENCE = "meta-oauth-state"
_GOOGLE_OAUTH_STATE_AUDIENCE = "google-oauth-state"


def _mint_oauth_state(user_id: str, audience: str = _OAUTH_STATE_AUDIENCE) -> str:
    """A signed, self-contained CSRF state carrying the user it was minted for.

    This used to be a random token in a module-level dict, which meant the
    callback only resolved when it happened to land on the same worker that built
    the URL — under more than one uvicorn worker, connecting Meta failed roughly
    (workers - 1) / workers of the time. Signing the state instead of storing it
    removes the shared-state problem entirely: any worker can verify it, and there
    is nothing to expire out of memory on a restart.
    """
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "aud": audience,
            # Random per mint. Two states for the same user in the same second
            # must not collide, or redeeming one would burn the other.
            "jti": secrets.token_urlsafe(12),
            "iat": now,
            "exp": now + _OAUTH_STATE_TTL,
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


# States already redeemed on this worker, so a replay is refused rather than
# connecting the account a second time.
# ponytail: process-local, so a replay landing on a *different* worker is not
# caught. Move to a shared store (a small nonces table keyed by jti) if replay
# protection has to be strict. Signature + `sub` binding + a 30-minute TTL do the
# real work; this only closes the same-worker window — which is still strictly
# better than the previous dict, where a state minted on another worker was
# rejected outright and connecting Meta failed under any multi-worker deploy.
_REDEEMED_OAUTH_STATES: set[str] = set()


def _read_oauth_state(state: str, audience: str = _OAUTH_STATE_AUDIENCE) -> str | None:
    """The user id inside a state token, or ``None`` if it is not ours/expired.

    Redeeming marks the token used: a second call with the same state returns
    ``None``, which the callers turn into "Invalid or expired OAuth state token".
    """
    try:
        payload = jwt.decode(
            state,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            audience=audience,
        )
    except JWTError:
        return None

    jti = payload.get("jti")
    if not jti or jti in _REDEEMED_OAUTH_STATES:
        return None
    _REDEEMED_OAUTH_STATES.add(jti)
    return payload.get("sub") or None

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/adwords",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

# Derived from settings.META_API_VERSION so a version bump moves every Meta
# call at once, not just the publish path.
META_AUTH_URL = f"https://www.facebook.com/{settings.META_API_VERSION}/dialog/oauth"
META_TOKEN_URL = f"{settings.META_GRAPH_URL}oauth/access_token"
META_SCOPES = [
    "ads_management",
    "ads_read",
    "business_management",
    "pages_read_engagement",
    # /me/accounts (the Page picker) and Click-to-WhatsApp both require these two
    # — Meta documents pages_show_list + pages_manage_ads as CTWA prerequisites.
    "pages_show_list",
    "pages_manage_ads",
    # Reads the leads an instant form has collected (GET {form_id}/leads). Without
    # it a lead campaign delivers only into Meta and Punk's leads panel is empty
    # forever — pages_manage_ads creates the form but does not read its submissions.
    "leads_retrieval",
    # Reads the Page's linked Instagram account, which becomes the creative's
    # instagram_user_id. Without it ads on Instagram placements run under an
    # identity nobody chose.
    "instagram_basic",
    # Reads and deletes the Page's app subscriptions. pages_manage_ads is enough
    # to CREATE the leadgen subscription, which is why this was missed: the POST
    # succeeds without it, and both the read-back that proves the subscription is
    # real and the DELETE that turns lead delivery off are refused with
    # "(#200) Requires pages_manage_metadata". Measured on a live Page.
    "pages_manage_metadata",
]

# The scopes a connection needs for every feature to work. Same list today, kept
# separate because they answer different questions: META_SCOPES is what we ASK
# for at the consent screen, this is what we CHECK a stored token against. A
# scope added to the ask does nothing for the tokens minted before it.
REQUIRED_SCOPES = tuple(META_SCOPES)


def missing_scopes(token) -> list[str]:
    """Which REQUIRED_SCOPES this stored connection does not have.

    ``[]`` when nothing is missing **and** when we do not know: a NULL
    ``scopes`` column is every row minted before Punk recorded them, and
    accusing those users of a broken connection they cannot see is worse than
    staying quiet until they reconnect for some other reason.
    """
    granted = getattr(token, "scopes", None)
    if not granted:
        return []
    have = {str(s) for s in granted}
    return [s for s in REQUIRED_SCOPES if s not in have]


def _scope_cards(missing: list[str]) -> list[dict]:
    """The reconnect card, rendered, or ``[]`` when nothing is missing.

    Imported inside the function: ``meta_remediation`` pulls in the Meta service
    layer, and this module is imported by the OAuth routes at startup.
    """
    if not missing:
        return []
    from app.services import meta_remediation

    card = meta_remediation.render(meta_remediation.CATALOG["meta_scopes_outdated"])
    card["cause"] = card["cause"].format(missing=", ".join(missing))
    return [card]


def _token_is_live(token) -> bool:
    """Is this OAuth token actually usable right now?

    Mirrors ``app.services.oauth.get_meta_credentials`` — a revoked or expired
    row is "not connected". Row existence alone is not enough: the graph refuses
    a dead token and re-fires the Connect widget, so a status endpoint that
    still reports ``connected`` sends the UI (and the chat widget's connect
    poll) chasing a token nothing else will accept.
    """
    if token is None or not token.is_valid:
        return False
    if token.expires_at is not None:
        exp = token.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= datetime.now(timezone.utc):
            return False
    return True


def _account_display_name(token) -> str | None:
    """Name for whichever account get_meta_credentials will resolve to.

    ``ad_account_name`` on the row is the name of ``ad_account_id`` (the first
    account seen at connect), not of ``selected_account`` — so after a switch
    it named the wrong account. ``accessible_accounts`` is the {id, name} list
    cached at connect/reconnect and covers the account actually selected.
    """
    target = token.selected_account or token.ad_account_id
    if not target:
        return None
    for acc in token.accessible_accounts or []:
        if isinstance(acc, dict) and acc.get("id") == target:
            return acc.get("name")
    return token.ad_account_name


def build_meta_auth_url(user_id: str) -> Dict[str, str]:
    """Generate the Meta OAuth authorization URL and register its CSRF state.

    Facebook Login for Business: the configuration id carries the permission
    set (``META_SCOPES`` documents what that configuration grants but is no
    longer sent as ``scope=`` — a business login configuration ignores it), and
    ``override_default_response_type=true`` + ``response_type=code`` is required
    to get an authorization-code exchange rather than the config's default.

    Module-level so the graph's connect-Meta interrupt
    (``graph/builder/executors/media.py``) can call it without constructing a
    service/repository. Critically, this MUST be the only place a Meta OAuth
    state token is minted: ``exchange_meta_code`` verifies with the matching
    reader, and a second minting scheme elsewhere means the callback rejects
    every URL built by the other one.
    """
    if not settings.META_LOGIN_CONFIG_ID:
        # Not a boot validator: local dev and CI never set it. But the URL below is
        # unusable without it — Meta's dialog opens on an error page and, worse, a
        # deploy that forgot it looks like "Meta is down" rather than "unset".
        raise ValueError(
            "META_LOGIN_CONFIG_ID is not set — the Meta connect URL has no login "
            "configuration, so no connection could carry the permissions Punk needs"
        )
    state = _mint_oauth_state(user_id)

    auth_url = (
        f"{META_AUTH_URL}?"
        f"client_id={settings.META_APP_ID}&"
        f"redirect_uri={settings.META_REDIRECT_URI}&"
        f"config_id={settings.META_LOGIN_CONFIG_ID}&"
        f"response_type=code&"
        f"override_default_response_type=true&"
        f"state={state}"
    )
    return {"authorization_url": auth_url, "state": state}


def _b64url_decode(data: str) -> bytes:
    """URL-safe base64 decode, padding restored — the parts of Meta's
    ``signed_request`` arrive unpadded, but Python's decoder demands a length
    that's a multiple of 4."""
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def parse_meta_signed_request(signed_request: str, app_secret: str) -> Dict[str, Any] | None:
    """Verify and decode Meta's ``signed_request`` (the Data Deletion Request
    Callback, and the older Canvas/Login format it reuses). ``None`` on ANY
    failure to parse or verify.

    Format: ``<base64url(hmac-sha256 signature)>.<base64url(json payload)>``.
    The signature covers the encoded payload STRING, not the decoded bytes —
    get that wrong and every request fails closed, which is the safe
    direction, but worth stating since it is the one step easy to invert by
    accident.

    This endpoint is unauthenticated in every ordinary sense (Meta calls it
    with no login, no API key) — the signature IS the authentication, exactly
    like the leadgen webhook's ``X-Hub-Signature-256`` (``tracking/router.py``)
    except the signature travels inside the body here instead of a header,
    because this is Meta's older signed_request convention, not the Hub one.
    """
    if not signed_request or "." not in signed_request:
        return None
    encoded_sig, payload_b64 = signed_request.split(".", 1)
    try:
        sig = _b64url_decode(encoded_sig)
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("algorithm") or "").upper() != "HMAC-SHA256":
        # Meta has only ever sent this one algorithm here, but trusting a
        # field we do not check is the same mistake as not checking at all.
        return None
    if not app_secret:
        return None
    expected = hmac.new(app_secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    return payload


class AdsService:
    def __init__(self, repository: AdsRepository):
        self.repository = repository

    def build_meta_auth_url(self, user_id: str) -> Dict[str, str]:
        return build_meta_auth_url(user_id)

    async def exchange_meta_code(self, db: AsyncSession, code: str, state: str) -> Dict[str, Any]:
        user_id = _read_oauth_state(state)
        if not user_id:
            raise ValueError("Invalid or expired OAuth state token")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                META_TOKEN_URL,
                params={
                    "client_id": settings.META_APP_ID,
                    "client_secret": settings.META_APP_SECRET,
                    "redirect_uri": settings.META_REDIRECT_URI,
                    "code": code,
                },
            )
            data = response.json()
            if "access_token" not in data:
                raise ValueError(f"Failed to get short token: {data}")
            access_token = data["access_token"]

        # debug_token answers, in one call, what fb_exchange_token alone never
        # said: which token type Meta actually minted. A Business Integration
        # System User token (the login configuration's "System User" access
        # type) arrives already long-lived — the fb_exchange_token hop below
        # errors on an already-long-lived token — and its ``/me`` identity is
        # the system user, not a person, which is why identity below is
        # resolved from the ad account's business rather than a profile call.
        from app.services.meta_ads import BISU_TOKEN_TYPES, fetch_token_info

        info = await fetch_token_info(access_token)
        is_system_user = info["type"].upper() in BISU_TOKEN_TYPES
        # What a connection carries is decided by the login configuration in the App
        # Dashboard, not by anything we send — so a short grant means that
        # configuration is wrong, and every advertiser connecting through it gets
        # the same short token. Logged loud, on the first connect, so ops hear it
        # here rather than from a (#200) mid-publish. Not raised: a partial token
        # still runs most of the product, and refusing the callback would lock the
        # user out over a setting they cannot change. An empty scope list is a
        # failed read, not a grant of nothing, so it is skipped.
        _granted = set(info["scopes"])
        _short = [s for s in REQUIRED_SCOPES if s not in _granted] if _granted else []
        if _short:
            logger.error(
                "meta connect: login configuration %s granted a short token, missing %s — "
                "fix Facebook Login for Business → Configurations in the App Dashboard",
                settings.META_LOGIN_CONFIG_ID, ", ".join(_short),
            )

        tokens: Dict[str, Any] = {
            "access_token": access_token,
            "token_type": "system_user" if is_system_user else "user",
            "scopes": info["scopes"],
        }

        if not is_system_user:
            # Defensive only — every login configuration in use mints System
            # User tokens now that the classic consumer-login path is gone.
            # Keeps a misconfigured configuration merely short-lived instead of
            # broken outright.
            async with httpx.AsyncClient() as client:
                long_token_res = await client.get(
                    META_TOKEN_URL,
                    params={
                        "grant_type": "fb_exchange_token",
                        "client_id": settings.META_APP_ID,
                        "client_secret": settings.META_APP_SECRET,
                        "fb_exchange_token": access_token,
                    },
                )
                long_data = long_token_res.json()
            if "access_token" in long_data:
                access_token = long_data["access_token"]
                tokens["access_token"] = access_token
            if "expires_in" in long_data:
                tokens["expires_in"] = long_data["expires_in"]
        # System-user branch deliberately sets no "expires_in": debug_token's
        # own expires_at is a UNIX timestamp (0 = never), not a duration, and
        # leaving the key absent is what lets the repository's unconditional
        # ``token_obj.expires_at = expires_at`` clear a stale 60-day value to
        # NULL on reconnect instead of computing a bogus expiry from it.

        try:
            accounts = await self._list_meta_ads_accounts_from_token(
                access_token, user_id, granular_scopes=info["granular_scopes"]
            )
            tokens["accessible_accounts"] = accounts
            ad_account_id = accounts[0]["id"] if accounts else None
            if ad_account_id:
                tokens["ad_account_id"] = ad_account_id

            # Identity for the connection card. Not a person's name/photo — the
            # old ``/me`` profile call returns the *system user* under a BISU
            # token, which would show every advertiser the same machine
            # identity. The business (or failing that, the ad account) name is
            # meaningful under both token types, so this is the one path now.
            from app.services.meta_ads import fetch_ad_account_business

            business = (
                await fetch_ad_account_business(ad_account_id, access_token)
                if ad_account_id else None
            )
            name = (business or {}).get("name") if business is not None else None
            if not name and accounts:
                name = accounts[0]["name"]
            tokens["meta_user_name"] = name or "Meta Business Account"
            tokens["meta_user_image"] = None
            # meta_user_id / select_meta_id deliberately NOT set here. Under a
            # system-user token /me returns the system user's own id, which can
            # never match the person's app-scoped id Meta's Data Deletion
            # signed_request carries — writing it would make that id actively
            # wrong instead of merely absent. See the migration plan's Open
            # Question 1.
        except Exception as exc:
            logger.warning("Meta auto account discovery failed", user_id=user_id, error=str(exc))

        try:
            from app.services.meta_ads import list_meta_pages

            pages = await list_meta_pages(access_token)
            if pages:
                tokens["page_id"] = pages[0]["id"]
                tokens["page_name"] = pages[0]["name"]
        except Exception as exc:
            logger.warning("Could not fetch Meta page_id", user_id=user_id, error=str(exc))

        await self.repository.save_user_oauth_tokens(user_id, AdPlatform.meta, tokens, db)
        return {"user_id": user_id, "platform": "meta", "connected": True, "access_token": tokens.get("access_token")}

    async def _list_meta_ads_accounts_from_token(
        self, access_token: str, user_id: str, granular_scopes: List[dict] | None = None
    ) -> List[Dict[str, str]]:
        from app.services.meta_ads import MetaAdsError, _request, granted_ad_account_ids

        try:
            result = await _request(
                "GET", "me/adaccounts", access_token,
                json_data={"fields": "id,name,account_id"},
            )
        except MetaAdsError as exc:
            raise ValueError(f"Meta API error: {exc}")
        accounts = []
        for item in result.get("data", []):
            accounts.append({
                "id": item["id"],
                "name": item.get("name") or f"Meta Account {item.get('account_id')}"
            })

        # /me/adaccounts lists every account the token can reach, which for a
        # Business system-user token is everything assigned to that system
        # user — not just what was picked in the Facebook login dialog.
        # granular_scopes is the actual grant; None means "couldn't tell" and
        # must not empty out a working connection.
        granted = granted_ad_account_ids(granular_scopes or [])
        if granted is not None:
            filtered = [a for a in accounts if a["id"].removeprefix("act_") in granted]
            if filtered:
                return filtered
            if accounts:
                logger.warning(
                    "Meta granular_scopes granted none of the %d reachable ad accounts "
                    "for user %s — keeping unfiltered list",
                    len(accounts), user_id,
                )
        return accounts

    def build_google_auth_url(self, user_id: str) -> Dict[str, str]:
        state = _mint_oauth_state(user_id, _GOOGLE_OAUTH_STATE_AUDIENCE)
        params = {
            "client_id": settings.GOOGLE_ADS_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_ADS_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(GOOGLE_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        from urllib.parse import urlencode
        query_string = urlencode(params)
        auth_url = f"{GOOGLE_AUTH_URL}?{query_string}"
        return {"authorization_url": auth_url, "state": state}

    async def exchange_google_code(self, db: AsyncSession, code: str, state: str) -> Dict[str, Any]:
        user_id = _read_oauth_state(state, _GOOGLE_OAUTH_STATE_AUDIENCE)
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
            resp.raise_for_status()
            tokens = resp.json()

        try:
            accounts = await self._list_google_ads_accounts_from_tokens(tokens.get("refresh_token") or "", user_id)
            tokens["accessible_accounts"] = accounts
        except Exception as exc:
            logger.warning("Auto account discovery failed", user_id=user_id, error=str(exc))

        await self.repository.save_user_oauth_tokens(user_id, AdPlatform.google, tokens, db)
        return {"user_id": user_id, "platform": "google", "connected": True, "access_token": tokens.get("access_token")}

    async def _list_google_ads_accounts_from_tokens(self, refresh_token: str, user_id: str) -> List[Dict[str, str]]:
        if not refresh_token:
            return []
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
            raise ValueError(f"Google Ads API error: {str(exc)}")

    async def get_connection_status(self, db: AsyncSession, user_id: str) -> list:
        tokens = await self.repository.get_user_tokens(db, user_id)
        token_map = {t.platform: t for t in tokens}
        status_list = []
        for platform in [AdPlatform.google, AdPlatform.meta]:
            token = token_map.get(platform)
            # A live connection can still be short a permission: scopes are fixed
            # when the token is minted, so a scope Punk started asking for later
            # is simply absent until the user reconnects. Surfaced here because
            # this is what the UI polls to decide whether Meta is "connected".
            needs = (
                missing_scopes(token)
                if token and platform == AdPlatform.meta and _token_is_live(token)
                else []
            )
            status_list.append({
                "platform": platform,
                "connected": _token_is_live(token),
                # selected_account first — the same precedence get_meta_credentials
                # uses — so this status panel never shows a different account than
                # the one a publish will actually use.
                "account_id": (token.selected_account or token.ad_account_id) if token else None,
                "account_name": _account_display_name(token) if token else None,
                "accessible_accounts": token.accessible_accounts if token and platform == AdPlatform.google else None,
                "missing_scopes": needs,
                "remediation": _scope_cards(needs),
            })
        return status_list

    async def get_meta_access_token(self, db: AsyncSession, user_id: str):
        """The connected Meta account's access token, or None if not connected."""
        tokens = await self.repository.get_user_tokens(db, user_id)
        for token in tokens:
            if token.platform == AdPlatform.meta and token.access_token:
                return token.access_token
        return None

    async def search_meta_targeting(
        self, db: AsyncSession, user_id: str, query: str, kind: str, limit: int = 25
    ) -> list[dict]:
        """Typeahead over Meta's detailed-targeting catalog (interests/behaviors).

        Returns [] when Meta is not connected or the query is empty — the editor
        treats that as "no suggestions" rather than an error.
        """
        query = (query or "").strip()
        if not query:
            return []
        access_token = await self.get_meta_access_token(db, user_id)
        if not access_token:
            return []
        from app.services.meta_ads import search_targeting_interests

        return await search_targeting_interests(
            query, access_token, kind=kind, limit=limit
        )

    async def suggest_meta_targeting(
        self,
        db: AsyncSession,
        user_id: str,
        session_id: str | None,
        seeds: str,
        limit: int = 12,
    ) -> list[dict]:
        """Suggestions for the editor's detailed-targeting field.

        - Seeds present (user selected or typed interests) → Meta's native
          ``adinterestsuggestion`` API ("more like what you chose").
        - No seeds present → Returns [] (Broad Audience / Advantage+ by default;
          avoids inaccurate LLM keyword guessing).

        Every returned row is a real Meta interest from Meta's catalog. [] on any failure.
        """
        access_token = await self.get_meta_access_token(db, user_id)
        if not access_token:
            return []
        from app.services.meta_ads import search_targeting_interests

        seed_list = [s.strip() for s in (seeds or "").split(",") if s.strip()]
        if not seed_list:
            # Broad audience by default. No blind LLM hallucinations.
            return []

        return await search_targeting_interests(
            ",".join(seed_list), access_token, kind="suggestions", limit=limit
        )

    async def _business_interest_phrases(
        self, db: AsyncSession, user_id: str, session_id: str | None
    ) -> list[str]:
        """Up to 5 Meta-catalog-shaped search phrases for the session's business.

        The business context the intake form collected lives in graph state, not
        in the plan the editor holds, so this reads the checkpointer directly.
        The phrases are what a media buyer would type into Meta's interest box
        for this advertiser — a SaaS gets "project management software", not the
        raw description, which never matches a catalog entry.

        Ownership is checked first. ``session_id`` arrives straight off the query
        string, and reading the checkpointer on an unowned one leaked another
        tenant's business name, industry and audience into this caller's
        suggestions.
        """
        if not session_id:
            return []

        from app.modules.chat.repository import ChatRepository

        if not await ChatRepository().find_specific_user_chat(db, session_id, user_id):
            logger.warning(
                "targeting autofill: user %s asked for session %s they do not own",
                user_id, session_id,
            )
            return []

        try:
            from app.graph.graph import get_graph

            graph = await get_graph()
            snap = await graph.aget_state(
                {"configurable": {"thread_id": session_id}}
            )
            values = getattr(snap, "values", None) or {}
        except Exception as exc:
            logger.warning("targeting autofill: state read failed — %s", exc)
            return []

        info = values.get("user_info") or {}
        context = " | ".join(
            str(v).strip()
            for v in (
                info.get("business_name"),
                info.get("industry"),
                info.get("business_description") or info.get("product_offer"),
                info.get("target_audience"),
            )
            if str(v or "").strip()
        )
        if not context:
            return []

        try:
            from app.graph.wizard_helpers import _make_llm

            reply = await _make_llm(temperature=0.0).ainvoke(
                "You pick Meta Ads detailed-targeting interests for an advertiser.\n"
                f"Advertiser: {context}\n\n"
                "List up to 5 short phrases that are likely to exist as interests "
                "in Meta's targeting catalog and that this advertiser's buyers "
                "would plausibly have. Prefer product categories, tools, and "
                "industry terms over adjectives. One phrase per line, no "
                "numbering, no commentary."
            )
            text = getattr(reply, "content", "") or ""
        except Exception as exc:
            logger.warning("targeting autofill: keyword LLM failed — %s", exc)
            return []

        phrases: list[str] = []
        for line in str(text).splitlines():
            phrase = line.strip().lstrip("-•*0123456789. ").strip()
            if phrase and len(phrase) < 60:
                phrases.append(phrase)
        return phrases[:5]

    async def list_page_objects(
        self, db: AsyncSession, user_id: str, page_id: str, kind: str, limit: int = 25
    ) -> list[dict]:
        """The Page's boostable posts / videos / events / Instagram media.

        ``kind="instagram"`` reads the Page's linked Instagram account instead of
        the Page itself, so the editor gets an Instagram tab without a second
        endpoint.

        Same degradation as the targeting typeahead: [] when Meta is not
        connected, so the picker shows "nothing to boost" instead of erroring.
        """
        page_id = (page_id or "").strip()
        if not page_id:
            return []
        access_token = await self.get_meta_access_token(db, user_id)
        if not access_token:
            return []
        from app.services.meta_ads import list_page_objects

        return await list_page_objects(page_id, access_token, kind=kind, limit=limit)

    async def list_previous_ad_posts(
        self, db: AsyncSession, user_id: str, limit: int = 25
    ) -> list[dict]:
        """The posts behind ads this account has already run.

        The other half of ``list_page_objects``: that one asks the Page what it
        published, this one asks the ad account what it advertised, which also
        surfaces the inline posts that never appear on the Page. Account-scoped,
        so it needs the selected ad account as well as the token.

        Same degradation — [] when Meta is not connected or no account is picked.
        """
        access_token = await self.get_meta_access_token(db, user_id)
        ad_account_id = await self._selected_ad_account(db, user_id)
        if not (access_token and ad_account_id):
            return []
        from app.services.meta_ads import list_account_ads

        return await list_account_ads(ad_account_id, access_token, limit=limit)

    async def list_ad_previews(
        self, db: AsyncSession, user_id: str, ad_id: str
    ) -> list[dict]:
        """Meta's rendering of one published ad, per placement.

        Returns ``[{format, label, src}]`` for the Preview & Publish screen.
        Degrades to [] like the other read-only pickers: the screen then shows
        the campaign summary without previews, which is worth strictly more than
        an error where a preview would have been.
        """
        ad_id = (ad_id or "").strip()
        if not ad_id:
            return []
        access_token = await self.get_meta_access_token(db, user_id)
        if not access_token:
            return []
        from app.services.meta_ads import generate_ad_previews

        return await generate_ad_previews(ad_id, access_token)

    async def list_campaign_structure(
        self, db: AsyncSession, user_id: str, campaign_id: str
    ) -> list[dict]:
        """One previous campaign's ad sets + ads, for the plan editor's copy picker.

        Returns ``[{id, name, ads: [{id, name}]}]``. Unlike ``fetch_campaign_tree``
        — which raises, because the graph must never silently start fresh from a
        campaign the user explicitly picked — this degrades to []: the picker then
        offers "copy the whole campaign", which is what the feature did before the
        picker existed.
        """
        campaign_id = (campaign_id or "").strip()
        if not campaign_id:
            return []
        access_token = await self.get_meta_access_token(db, user_id)
        if not access_token:
            return []
        from app.services.meta_ads import MetaAdsError, fetch_campaign_tree

        try:
            tree = await fetch_campaign_tree(campaign_id, access_token)
        except MetaAdsError as exc:
            logger.warning("list_campaign_structure(%s): failed — %s", campaign_id, exc)
            return []

        return [
            {
                "id": str(adset["id"]),
                "name": adset.get("name") or str(adset["id"]),
                "ads": [
                    {"id": str(ad["id"]), "name": ad.get("name") or str(ad["id"])}
                    for ad in (adset.get("ads") or [])
                    if ad.get("id")
                ],
            }
            for adset in (tree.get("adsets") or [])
            if adset.get("id")
        ]

    async def list_lead_form_choices(self, db: AsyncSession, user_id: str) -> list[dict]:
        """Every instant form on every Page the user shared, for the leads table.

        One row per form, carrying its Page so the leads read can use that Page's
        token. ``[]`` when not connected — same degradation as the other reads behind
        a picker.
        """
        access_token = await self.get_meta_access_token(db, user_id)
        if not access_token:
            return []
        import asyncio

        from app.services import meta_ads as _meta

        pages = await _meta.list_meta_pages(access_token)
        tokens = await _meta.list_page_tokens(access_token)
        # ponytail: one form list per Page, same as connect — slice if someone shows
        # up managing fifty.
        per_page = await asyncio.gather(
            *(
                _meta.list_lead_forms(p["id"], access_token, page_token=tokens.get(p["id"], ""))
                for p in pages
            )
        )
        return [
            {**form, "page_id": str(page["id"]), "page_name": page.get("name") or ""}
            for page, forms in zip(pages, per_page)
            for form in forms
        ]

    async def list_form_leads(
        self, db: AsyncSession, user_id: str, form_id: str, limit: int = 100,
        page_id: str = "",
    ) -> list[dict]:
        """Leads submitted to one of the user's instant forms.

        A lead campaign that delivers only into Meta makes the user leave Punk to
        collect the thing they paid for. Same degradation as the other Meta
        reads: [] when not connected. A permission failure propagates as
        ``MetaAdsError`` — see ``fetch_form_leads``.
        """
        form_id = (form_id or "").strip()
        if not form_id:
            return []
        access_token = await self.get_meta_access_token(db, user_id)
        if not access_token:
            return []
        from app.services.meta_ads import fetch_form_leads, fetch_page_token

        # The form's Page token when we know its Page; the user token otherwise.
        page_token = await fetch_page_token(page_id, access_token) if page_id else ""
        return await fetch_form_leads(
            form_id, access_token, limit=limit, page_token=page_token
        )

    async def list_lead_delivery(self, db: AsyncSession, user_id: str) -> list[dict]:
        """Per Page the user shared: is Meta pushing its leads at Punk, and to this account?

        Reading ``subscribed_apps`` is what ``pages_manage_metadata`` gates, so this is
        also where that permission is visibly in use. ``subscribed`` stays ``None`` when
        there is no Page token or the read is refused — unknown is never "off".
        ``[]`` when Meta is not connected.
        """
        access_token = await self.get_meta_access_token(db, user_id)
        if not access_token:
            return []
        import asyncio

        from app.services import meta_ads as _meta

        pages = await _meta.list_meta_pages(access_token)
        tokens = await _meta.list_page_tokens(access_token)
        account = await self.repository.get_tracking_account(db, user_id)
        routed_page = str(getattr(account, "tracking_lead_page_id", "") or "")

        async def _subscribed(page_id: str) -> bool | None:
            token = tokens.get(page_id, "")
            return await _meta.page_leadgen_subscribed(page_id, token) if token else None

        states = await asyncio.gather(*(_subscribed(str(p["id"])) for p in pages))
        return [
            {
                "page_id": str(p["id"]),
                "page_name": p.get("name") or "",
                "subscribed": state,
                "routed": str(p["id"]) == routed_page,
            }
            for p, state in zip(pages, states)
        ]

    async def connect_lead_delivery(self, db: AsyncSession, user_id: str, page_id: str) -> dict:
        """Subscribe Punk to this Page's leads and route them to the selected ad account.

        The same two steps publish performs for a lead campaign
        (``_subscribe_lead_webhook``): subscribe with the Page token, then remember the
        Page on the ad account — Meta's payload names the Page and nothing that
        identifies us, so that row is the only thing that can route a lead back.

        Deliberately NOT the dataset resolution publish also does: a button must never
        create a dataset on the user's behalf. A missing dataset stays the
        ``lead_dataset_missing`` card on the tracking settings.

        ponytail: one Page per ad account (``tracking_lead_page_id`` is a single
        column), so this MOVES routing if another Page was routed. Per-Page routing
        needs a join table.
        """
        access_token = await self.get_meta_access_token(db, user_id)
        if not access_token:
            raise ValueError("Meta is not connected")
        from app.services import meta_ads as _meta
        from app.services import meta_remediation

        page_token = await _meta.fetch_page_token(page_id, access_token)
        if not page_token:
            # Not one of the Pages Meta shared with Punk — also stops a user naming
            # a Page id that is not theirs.
            raise ValueError("Meta did not share that Page with Punk")
        if not await _meta.subscribe_page_leadgen(page_id, page_token):
            return {
                "page_id": page_id, "subscribed": False, "routed": False,
                "remediation": [
                    meta_remediation.render(
                        meta_remediation.CATALOG["lead_webhook_not_subscribed"], page_id=page_id,
                    )
                ],
            }
        routed = await self.repository.save_tracking_state(
            db, user_id, tracking_lead_page_id=page_id
        )
        return {"page_id": page_id, "subscribed": True, "routed": bool(routed), "remediation": []}

    async def get_readiness(self, db: AsyncSession, user_id: str) -> list[dict]:
        """What a new advertiser still has to do in Meta before publishing, in order.

        Live Graph reads, so a route of its own rather than a field on
        ``get_connection_status``, which is DB-only and polled in a loop while the
        connect popup is open. ``[]`` when Meta is not connected: there is nothing to
        prepare yet, and the connect step is its own prompt.
        """
        access_token = await self.get_meta_access_token(db, user_id)
        ad_account_id = await self._selected_ad_account(db, user_id)
        if not (access_token and ad_account_id):
            return []
        from app.services import meta_remediation
        from app.services.meta_ads import ad_account_blockers, fetch_custom_audience_tos

        return meta_remediation.readiness(
            await ad_account_blockers(ad_account_id, access_token),
            tos_accepted=await fetch_custom_audience_tos(ad_account_id, access_token),
            ad_account_id=ad_account_id,
        )

    async def list_audiences(self, db: AsyncSession, user_id: str) -> list[dict]:
        """The ad account's custom audiences, for the editor's pickers.

        Read live rather than off the session's catalog for the same reason the
        dataset list is: the user who opens this is often the one who just built
        an audience, in Ads Manager or through the route below, and a cached list
        is exactly the list without it. Degrades to ``[]`` like the other reads
        behind a picker.
        """
        access_token = await self.get_meta_access_token(db, user_id)
        ad_account_id = await self._selected_ad_account(db, user_id)
        if not (access_token and ad_account_id):
            return []
        from app.services.meta_ads import audience_is_usable, list_custom_audiences

        found = await list_custom_audiences(ad_account_id, access_token)
        return [
            {
                "id": str(a["id"]),
                "name": a.get("name") or str(a["id"]),
                "subtype": a.get("subtype") or "",
                "size": a.get("approximate_count_lower_bound"),
                "usable": audience_is_usable(a),
                "status": (a.get("delivery_status") or {}).get("description") or "",
            }
            for a in found
        ]

    async def create_website_audience(
        self,
        db: AsyncSession,
        user_id: str,
        *,
        name: str,
        dataset_id: str,
        event_name: str = "",
        retention_days: int = 180,
    ) -> dict:
        """Build an audience from the people a dataset has already seen.

        Raises rather than degrading, like ``create_page_lead_form``: an audience
        the user believes exists but does not is worse than an error, and this one
        would be discovered as an ad set delivering to nobody.
        """
        access_token = await self.get_meta_access_token(db, user_id)
        ad_account_id = await self._selected_ad_account(db, user_id)
        if not (access_token and ad_account_id):
            raise ValueError("Connect Meta and select an ad account first")
        from app.services.meta_ads import create_website_audience, list_custom_audiences

        audience_id = await create_website_audience(
            name,
            dataset_id,
            ad_account_id,
            access_token,
            event_name=event_name,
            retention_days=retention_days,
        )
        # Read it back so the picker gets the same shape as every other row,
        # including whatever Meta already says about delivery. A brand-new
        # audience is always still building, which the caller shows as-is rather
        # than pretending it is ready.
        for row in await list_custom_audiences(ad_account_id, access_token):
            if str(row.get("id")) == audience_id:
                from app.services.meta_ads import audience_is_usable

                return {
                    "id": audience_id,
                    "name": row.get("name") or name,
                    "subtype": row.get("subtype") or "WEBSITE",
                    "size": row.get("approximate_count_lower_bound"),
                    "usable": audience_is_usable(row),
                    "status": (row.get("delivery_status") or {}).get("description") or "",
                }
        return {
            "id": audience_id, "name": name, "subtype": "WEBSITE",
            "size": None, "usable": False, "status": "Still building",
        }

    async def add_audience_users(
        self,
        db: AsyncSession,
        user_id: str,
        audience_id: str,
        *,
        schema_fields: list[str],
        rows: list[list[str]],
    ) -> int:
        """Upload a customer list into an audience. Returns rows submitted."""
        access_token = await self.get_meta_access_token(db, user_id)
        if not access_token:
            raise ValueError("Connect Meta first")
        from app.services.meta_ads import upload_audience_users

        return await upload_audience_users(
            audience_id, rows, access_token, schema=[s.upper() for s in schema_fields],
        )

    async def _selected_ad_account(self, db: AsyncSession, user_id: str) -> str:
        """The ad account these audience calls act on.

        ``selected_account`` first: one login can reach several ad accounts, and
        an audience belongs to exactly one of them.
        """
        tokens = await self.repository.get_user_tokens(db, user_id)
        for token in tokens:
            if token.platform == AdPlatform.meta:
                return str(token.selected_account or token.ad_account_id or "")
        return ""

    async def create_page_lead_form(
        self, db: AsyncSession, user_id: str, page_id: str, form
    ) -> dict:
        """Create one Instant Form on the Page and return ``{id, name}``.

        The odd one out among the Meta helpers here: the reads degrade to `[]`
        because an empty picker beats a broken editor, but a create that quietly
        returns nothing would leave the user believing they have a form. Failures
        are raised so the caller can show them.

        A missing ``follow_up_url`` falls back to the Page's own website, the
        same way the publish path falls back to ``user_info["website_url"]``
        (``executors/media.py``). Without it ``create_lead_form`` defaults the
        follow-up to the privacy policy URL, so every lead created through this
        endpoint landed on a legal page instead of the business.
        """
        access_token = await self.get_meta_access_token(db, user_id)
        if not access_token:
            raise ValueError("Meta is not connected — reconnect your account to create a form.")
        from app.services.meta_ads import create_lead_form, fetch_page_website

        follow_up_url = form.follow_up_url or await fetch_page_website(page_id, access_token)

        form_id = await create_lead_form(
            page_id,
            name=form.name,
            questions=[q.model_dump(exclude_none=True) for q in form.questions],
            privacy_policy_url=form.privacy_policy_url,
            access_token=access_token,
            context_headline=form.intro_title,
            context_body=form.intro_body,
            follow_up_url=follow_up_url or None,
            higher_intent=form.higher_intent,
        )
        return {"id": form_id, "name": form.name}

    async def disconnect_meta(self, db: AsyncSession, user_id: str) -> bool:
        return await self.repository.disconnect_account(db, user_id, AdPlatform.meta)
        
    async def disconnect_connection_by_id(self, db: AsyncSession, user_id: str, oauth_token_id: str) -> bool:
        return await self.repository.disconnect_connection_by_id(db, user_id, oauth_token_id)
        
    async def disconnect_google(self, db: AsyncSession, user_id: str) -> bool:
        return await self.repository.disconnect_account(db, user_id, AdPlatform.google)

    async def remove_ads_account(self, db: AsyncSession, user_id: str, ad_account_id: str) -> str:
        return await self.repository.remove_ads_account(db, user_id, ad_account_id)