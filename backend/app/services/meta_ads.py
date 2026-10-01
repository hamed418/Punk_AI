"""
services/meta_ads.py
────────────────────
Async Meta Ads Graph API client for campaign publishing.

Responsibilities:
  - Media upload (images and videos)
  - Custom audience creation and MAID ingestion
  - Campaign / ad set / ad creative / ad creation
  - Ad previews (Meta's own rendering, per placement)
  - Activation of published items
  - Targeting spec construction from GeoData state

All functions raise MetaAdsError on API failure. Callers should catch it
and surface a user-friendly message rather than letting it propagate.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import hashlib
import hmac
import html
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl

import httpx

from datetime import datetime, timezone

from app.core.config import settings

# The hard ceilings Meta actually refuses — NOT the 40/125/30 recommended
# lengths. Slicing to the recommendation here is what used to silently mangle
# copy the user had already approved. ``enums`` is a leaf module (stdlib +
# facebook_business only), so importing it at runtime creates no cycle.
from app.graph.meta_spec.enums import (
    CREATIVE_BODY_MAX,
    CREATIVE_DESCRIPTION_MAX,
    CREATIVE_TITLE_MAX,
)

if TYPE_CHECKING:  # avoid a runtime cycle — meta_spec imports nothing from here
    from app.graph.meta_spec.models import AdSetSpec, CampaignSpec

logger = logging.getLogger(__name__)

# debug_token's ``type`` for a Business Integration System User token (minted by
# Facebook Login for Business when the configuration's access token type is
# "System User"). Everything else (plain "USER", "PAGE", "APP") is treated as
# the old person-bound shape. Measured live 2026-09-05: Meta returns "SYSTEM_USER",
# not the documented long form — both are kept (case-insensitively) so a Graph
# version that switches back does not silently reclassify every connection as a
# person token again.
BISU_TOKEN_TYPES = frozenset({
    "SYSTEM_USER",
    "BUSINESS_INTEGRATION_SYSTEM_USER_ACCESS_TOKEN",
})

_BASE = f"https://graph.facebook.com/{settings.META_API_VERSION}"

# Whose token is on the wire right now. Set by the publish/manager entry points so
# the transport can react to a dead token without every one of its ~40 call sites
# having to thread a user_id through. Same idiom as
# ``campaign_manager_tools``'s per-task credential contextvars.
_ACTING_USER_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "meta_acting_user_id", default=None
)


@contextlib.contextmanager
def acting_user(user_id: str | None):
    """Bind the user whose Meta token these calls use, for the duration of a block."""
    token = _ACTING_USER_ID.set(user_id or None)
    try:
        yield
    finally:
        _ACTING_USER_ID.reset(token)


def _appsecret_proof(access_token: str) -> str | None:
    """HMAC-SHA256 of the access token, keyed by the app secret.

    Meta's server-side hardening: proves the call came from something holding the
    app secret, so a token lifted from a log or a client cannot be replayed
    against the API on its own. Returns None when no app secret is configured,
    since sending a wrong proof is worse than sending none.
    """
    secret = settings.META_APP_SECRET
    if not secret or not access_token:
        return None
    return hmac.new(
        secret.encode("utf-8"), access_token.encode("utf-8"), hashlib.sha256
    ).hexdigest()


# Meta's "this token is dead" code. Distinct from 10/200, which mean the token is
# alive but lacks a scope — those must NOT invalidate the stored connection.
_TOKEN_DEAD_CODE = 190


async def _note_dead_token(exc: "MetaAdsError") -> None:
    """Mark the acting user's stored token invalid when Meta says it is dead.

    Without this a user who revoked Punk in Business Settings kept a row reading
    "connected" forever, and every publish failed on 190 with no route back.
    """
    if exc.code != _TOKEN_DEAD_CODE:
        return
    # Meta also answers 190 for "right token, wrong TYPE for this edge" — e.g.
    # "(#190) This method must be called with a Page Access Token" on
    # leadgen_forms. The stored user token is fine there; invalidating it bounced
    # the advertiser to "reconnect Meta", which mints the same token and repeats.
    if "must be called with" in str(exc).lower():
        return
    user_id = _ACTING_USER_ID.get()
    if not user_id:
        return
    # Imported here: oauth imports the ads module chain, so a module-level import
    # would close a cycle.
    from app.services.oauth import mark_meta_token_invalid

    await mark_meta_token_invalid(user_id, f"Graph error {exc.code}: {exc}")

# ── Objective mapping ─────────────────────────────────────────────────────────
# Objective/goal vocabulary lives in app/graph/meta_spec — this module is
# transport only. The flat OBJECTIVE_MAP / OPTIMIZATION_GOAL_MAP that used to sit
# here were the one-dimensional model that produced invalid objective+destination
# pairs; meta_spec.objective_matrix replaced them.

_IMAGE_CONTENT_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


# ── Exceptions ────────────────────────────────────────────────────────────────


class MetaAdsError(Exception):
    """Raised when the Meta Graph API returns an error or an HTTP failure occurs."""

    def __init__(
        self,
        message: str,
        code: int | None = None,
        *,
        subcode: int | None = None,
        user_msg: str | None = None,
        blame_field: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.subcode = subcode
        # Meta's own end-user-safe wording, when it supplies one. Better than our
        # paraphrase because it names the actual account/policy problem.
        self.user_msg = user_msg
        # The payload field names Meta objected to, when it says. Used to key
        # preflight errors back onto the campaign form.
        self.blame_field = blame_field or []

    @property
    def retryable(self) -> bool:
        return self.code in _RETRYABLE_CODES


# Transient Meta error codes. Everything else is a validation/permission problem
# where retrying just burns quota and delays the real error:
#   1   unknown/transient   2   service temporarily unavailable
#   4   app rate limit      17  user rate limit
#   32  page rate limit     613 custom-level rate limit
#   80004 ads-api throttle
_RETRYABLE_CODES: frozenset[int] = frozenset({1, 2, 4, 17, 32, 613, 80004})

# The subset that means "you are going too fast" rather than "something blipped".
# Meta's ads throttle is measured in minutes, not seconds — a 1.5s base backoff
# exhausts all four attempts inside 15s and reports a hard failure on a condition
# that would have cleared on its own, which is how a publish dies part-way.
_THROTTLE_CODES: frozenset[int] = frozenset({4, 17, 32, 613, 80004})

_MAX_ATTEMPTS = 4
_BACKOFF_BASE_S = 1.5
_THROTTLE_BACKOFF_BASE_S = 20.0


def _blame_fields(err: dict) -> list[str]:
    """The payload fields Meta names in ``error_data.blame_field_specs``.

    Meta sends ``error_data`` as a JSON **string** far more often than as an
    object — ``'{"blame_field_specs":[["lifetime_budget"]]}'`` — so the old
    isinstance-dict read never once fired and every rejection reached the plan
    editor as a field-less banner. The specs themselves are a list of paths
    (``[["targeting", "age_max"]]``); the last segment is the field that was
    actually refused, which is what the editor's form keys are named after.
    """
    data = err.get("error_data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return []
    if not isinstance(data, dict):
        return []

    fields: list[str] = []
    for spec in data.get("blame_field_specs") or []:
        name = spec[-1] if isinstance(spec, list) and spec else spec
        if isinstance(name, str) and name and name not in fields:
            fields.append(name)
    return fields


# ── Internal HTTP helper ──────────────────────────────────────────────────────


async def _request(
    method: str,
    endpoint: str,
    access_token: str,
    json_data: dict | None = None,
    files: dict | None = None,
    data: dict | None = None,
    timeout: float = 60.0,
    *,
    validate_only: bool = False,
    retries: int = _MAX_ATTEMPTS,
) -> dict:
    """One Graph API call, with bounded retries on transient failures.

    ``validate_only`` adds Meta's ``execution_options`` so the payload is checked
    against the real account without creating anything — the preflight backstop
    for our local objective matrix, which can drift from Meta's rules.

    Retries cover network errors, 5xx, and the throttling codes in
    ``_RETRYABLE_CODES``. Validation and permission errors are raised on the
    first attempt: retrying a rejected payload cannot make it valid.
    """
    # An endpoint may carry its own query ("{ad_id}/previews?ad_format=…"). It has
    # to be lifted into `params` here: httpx *replaces* a URL's query string when
    # a `params` dict is passed (httpx/_urls.py — "Replace any 'params' keyword
    # with the raw 'query' instead"), and `params` is never empty once an app
    # secret is configured. Left in the path it was dropped in flight, which is
    # what made every ad preview come back "(#100) … ad_format is required".
    path, _, inline_query = endpoint.partition("?")
    url = f"{_BASE}/{path.lstrip('/')}"
    # The token rides in the Authorization header, not the query string. As a
    # parameter it landed in every intermediary's access log and in Meta's own
    # request logs; the header is the documented alternative and is accepted on
    # every Graph endpoint, multipart uploads included.
    headers = {"Authorization": f"Bearer {access_token}"}
    params: dict[str, str] = dict(parse_qsl(inline_query))
    proof = _appsecret_proof(access_token)
    if proof:
        params["appsecret_proof"] = proof

    body = json_data
    if validate_only:
        body = {**(json_data or {}), "execution_options": ["validate_only"]}

    last_exc: Exception | None = None
    for attempt in range(1, max(retries, 1) + 1):
        try:
            return await _request_once(
                method, url, params, endpoint, body, files, data, timeout,
                headers=headers,
            )
        except MetaAdsError as exc:
            if not exc.retryable or attempt >= retries:
                raise
            last_exc = exc
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            if attempt >= retries:
                raise MetaAdsError(f"network error talking to Meta: {exc}") from exc
            last_exc = exc

        throttled = isinstance(last_exc, MetaAdsError) and last_exc.code in _THROTTLE_CODES
        base = _THROTTLE_BACKOFF_BASE_S if throttled else _BACKOFF_BASE_S
        delay = base * (2 ** (attempt - 1))
        logger.warning(
            "Meta request %s %s failed (attempt %d/%d): %s — retrying in %.1fs",
            method, endpoint, attempt, retries, last_exc, delay,
        )
        await asyncio.sleep(delay)

    # Unreachable: the loop either returns or raises.
    raise MetaAdsError(f"Meta request failed after {retries} attempts: {last_exc}")


_USAGE_WARN_PCT = 75  # matches the "alert above 75%" bar used for the tier review


def _log_usage_header(resp: httpx.Response, endpoint: str) -> None:
    """Log Meta's own rate-limit headroom for this call.

    Nothing read these before — every response header was discarded, so Punk
    had no visibility into the account-level throttle it was about to hit, and
    no data at all toward the Marketing API Access Tier's own error-rate
    assessment (which reads calls Meta itself is counting). Log-only for now:
    this is the capture point a rolling per-account counter builds on later,
    not that counter itself.

    ``X-Business-Use-Case-Usage`` is per ad account (JSON, keyed by
    ``act_<id>``); ``X-App-Usage`` is per app, one object. Either can be
    missing — plenty of read endpoints don't return them — so a missing or
    unparsable header is silently skipped rather than logged as a problem.
    """
    for header, per_account in (
        ("X-Business-Use-Case-Usage", True),
        ("X-App-Usage", False),
    ):
        raw = resp.headers.get(header)
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except ValueError:
            continue

        entries = []
        if per_account and isinstance(parsed, dict):
            for account_id, rows in parsed.items():
                for row in rows or []:
                    if isinstance(row, dict):
                        entries.append((account_id, row))
        elif isinstance(parsed, dict):
            entries.append((None, parsed))

        for account_id, row in entries:
            pct = max(
                (row.get(k) or 0 for k in ("call_count", "total_time", "total_cputime")),
                default=0,
            )
            level = logging.WARNING if pct >= _USAGE_WARN_PCT else logging.DEBUG
            logger.log(
                level,
                "Meta %s usage%s: %d%% (endpoint=%s)",
                header, f" for {account_id}" if account_id else "", pct, endpoint,
            )


async def _request_once(
    method: str,
    url: str,
    params: dict,
    endpoint: str,
    json_data: dict | None,
    files: dict | None,
    data: dict | None,
    timeout: float,
    headers: dict | None = None,
) -> dict:
    async with httpx.AsyncClient(timeout=timeout, headers=headers or {}) as client:
        if files:
            resp = await client.post(url, params=params, files=files, data=json_data or {})
        elif data and method.upper() == "POST":
            # Form-encoded POST — used for URL-direct media uploads where Meta
            # fetches the asset itself (adimages url=, advideos file_url=).
            #
            # The method check is load-bearing: this branch used to be reached on
            # `data` alone, which silently turned every GET carrying `data` into a
            # POST. That is what made ``wait_for_video_ready`` a no-op — its status
            # GET became a POST to /{video_id}, Meta rejected it, and the caller
            # logged "proceeding without the gate" and returned.
            resp = await client.post(url, params=params, data=data)
        elif method.upper() == "POST":
            resp = await client.post(url, params=params, json=json_data or {})
        elif method.upper() == "DELETE":
            # Explicit, because the fallthrough below is a GET. Without this
            # branch every DELETE was issued as a GET: Meta answered 200 with the
            # object's own fields, no "error" key, and the caller reported a
            # successful delete of something still sitting there. Measured —
            # three objects "deleted" three times and still listed afterwards.
            resp = await client.request(
                "DELETE", url, params={**params, **(json_data or {})},
            )
        else:
            resp = await client.get(
                url, params={**params, **(json_data or {}), **(data or {})}
            )

    _log_usage_header(resp, endpoint)

    result: dict = {}
    try:
        result = resp.json()
    except Exception:
        raise MetaAdsError(f"HTTP {resp.status_code}: non-JSON response")

    if "error" in result:
        err = result["error"]
        detail = err.get("error_user_msg") or err.get("error_user_title") or ""
        subcode = err.get("error_subcode")
        fbtrace = err.get("fbtrace_id", "")
        extra = f" | subcode={subcode}" if subcode else ""
        extra += f" | user_msg={detail}" if detail else ""
        extra += f" | fbtrace={fbtrace}" if fbtrace else ""
        logger.error(
            "Meta API error full payload: %s", err,
            extra={"endpoint": endpoint, "method": method},
        )
        error = MetaAdsError(
            f"{err.get('type', 'GraphAPIError')}: {err.get('message', 'unknown')}{extra}",
            code=err.get("code"),
            subcode=subcode,
            user_msg=detail or None,
            blame_field=_blame_fields(err),
        )
        await _note_dead_token(error)
        raise error
    if resp.status_code >= 400:
        raise MetaAdsError(f"HTTP {resp.status_code}: {resp.text[:200]}")

    return result


# ── Utilities ─────────────────────────────────────────────────────────────────


def _act(ad_account_id: str) -> str:
    """Normalize an ad account id to Meta's ``act_<id>`` form.

    Most helpers did this inline, but ``create_custom_audience``,
    ``upload_image`` and ``upload_video`` did not — so a caller passing a bare
    numeric id hit those three endpoints with a malformed path.
    """
    raw = str(ad_account_id or "").strip()
    if not raw:
        raise MetaAdsError("no ad account id provided")
    return raw if raw.startswith("act_") else f"act_{raw}"


# Budget and date parsing live in ``meta_spec.parsing`` — it raises on garbage
# instead of falling back to $50 / now(), which is what silently started
# campaigns on the wrong date. The copies that used to sit here had no callers.


# ── Media uploads ─────────────────────────────────────────────────────────────


async def upload_image(file_path: str, ad_account_id: str, access_token: str) -> str:
    """Upload an image to Meta and return the image hash.

    ``file_path`` may be a local filesystem path (uploaded as multipart) or a
    public ``http(s)`` URL — in the URL case Meta fetches the asset itself via
    the ``url`` param, skipping the byte round-trip through this backend.
    """
    if file_path.startswith(("http://", "https://")):
        result = await _request(
            "POST",
            f"{_act(ad_account_id)}/adimages",
            access_token,
            data={"url": file_path},
            timeout=60.0,
        )
    else:
        with open(file_path, "rb") as f:
            suffix = Path(file_path).suffix.lower()
            content_type = _IMAGE_CONTENT_TYPES.get(suffix, "image/jpeg")
            files = {"filename": (Path(file_path).name, f, content_type)}
            result = await _request(
                "POST",
                f"{_act(ad_account_id)}/adimages",
                access_token,
                files=files,
                timeout=60.0,
            )

    images = result.get("images", {})
    for entry in images.values():
        if isinstance(entry, dict) and "hash" in entry:
            return entry["hash"]
    raise MetaAdsError("Image upload returned no hash")


async def upload_video(file_path: str, ad_account_id: str, access_token: str) -> str:
    """Upload a video to Meta and return the video ID.

    ``file_path`` may be a local filesystem path (uploaded as multipart) or a
    public ``http(s)`` URL — in the URL case Meta ingests the asset itself via
    the ``file_url`` param, skipping the byte round-trip through this backend.
    """
    if file_path.startswith(("http://", "https://")):
        result = await _request(
            "POST",
            f"{_act(ad_account_id)}/advideos",
            access_token,
            data={"file_url": file_path},
            timeout=300.0,
        )
    else:
        with open(file_path, "rb") as f:
            files = {"source": (Path(file_path).name, f, "video/mp4")}
            result = await _request(
                "POST",
                f"{_act(ad_account_id)}/advideos",
                access_token,
                files=files,
                timeout=300.0,
            )

    vid_id = result.get("id")
    if not vid_id:
        raise MetaAdsError("Video upload returned no ID")
    return str(vid_id)


# How long to wait for Meta to finish transcoding, and how often to ask. Meta
# gives no completion callback, so this polls. Short clips are ready in seconds;
# the ceiling is generous because the alternative — building the creative anyway —
# fails the whole publish.
_VIDEO_READY_TIMEOUT_S = 180.0
_VIDEO_POLL_INTERVAL_S = 3.0


async def wait_for_video_ready(
    video_id: str,
    access_token: str,
    *,
    timeout: float = _VIDEO_READY_TIMEOUT_S,
) -> None:
    """Block until Meta has finished processing ``video_id``.

    ``POST /advideos`` returns an id the moment Meta accepts the bytes, not when
    the video is usable. An ad creative built against a still-transcoding video is
    rejected, or produces an ad stuck in review — a publish failure with no local
    cause and nothing in the payload to explain it.

    Raises ``MetaAdsError`` on an error status or on timeout. A read failure is
    *not* fatal: if we cannot see the status we let the creative attempt proceed
    and let Meta be the judge, which is the behaviour that existed before this
    gate and is strictly better than failing a publish over a flaky GET.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        try:
            result = await _request(
                "GET", video_id, access_token, data={"fields": "status"}, timeout=30.0,
            )
        except MetaAdsError as exc:
            logger.warning(
                "video %s: status check failed (%s) — proceeding without the gate",
                video_id, exc,
            )
            return

        status = (result.get("status") or {})
        phase = str(status.get("video_status") or "").lower()
        if phase == "ready":
            return
        if phase == "error":
            raise MetaAdsError(
                f"Meta could not process video {video_id}: "
                f"{status.get('processing_progress') or status}"
            )

        if asyncio.get_event_loop().time() >= deadline:
            raise MetaAdsError(
                f"video {video_id} was still processing after {timeout:.0f}s "
                f"(status: {phase or 'unknown'})"
            )
        await asyncio.sleep(_VIDEO_POLL_INTERVAL_S)


async def fetch_video_thumbnail(video_id: str, access_token: str) -> str | None:
    """A poster frame URI for ``video_id``, or None if Meta offers none yet.

    Meta rejects a ``video_data`` creative that names no poster frame — subcode
    1443226, "Please specify one of image_hash or image_url in the video_data
    field of object_story_spec" — which made every video ad unpublishable. It
    generates the candidates itself during transcode, so this only has to pick
    one; ``is_preferred`` is Meta's own choice and the first frame is the
    fallback.

    Never raises: a creative without a thumbnail is rejected with a clear message
    from Meta, which beats failing the publish on a flaky GET.
    """
    try:
        result = await _request(
            "GET", video_id, access_token,
            data={"fields": "thumbnails{uri,is_preferred}"}, timeout=30.0,
        )
    except MetaAdsError as exc:
        logger.warning("video %s: could not read thumbnails (%s)", video_id, exc)
        return None

    frames = ((result.get("thumbnails") or {}).get("data")) or []
    preferred = next((f for f in frames if f.get("is_preferred")), None)
    chosen = preferred or (frames[0] if frames else None)
    return str(chosen["uri"]) if chosen and chosen.get("uri") else None


# ── Custom audience ───────────────────────────────────────────────────────────


async def create_custom_audience(
    name: str, description: str, ad_account_id: str, access_token: str
) -> str:
    """Create a CUSTOM subtype audience and return its ID."""
    result = await _request(
        "POST",
        f"{_act(ad_account_id)}/customaudiences",
        access_token,
        json_data={
            "name": name,
            "subtype": "CUSTOM",
            "description": description,
            "customer_file_source": "USER_PROVIDED_ONLY",
        },
    )
    audience_id = result.get("id")
    if not audience_id:
        raise MetaAdsError("Custom audience creation returned no ID")
    return str(audience_id)


async def list_custom_audiences(ad_account_id: str, access_token: str) -> list[dict]:
    """The account's audiences, with the two fields that decide usability — ``[]``
    on any failure, like ``fetch_custom_conversions``.

    ``delivery_status`` is the point of reading these at all. A custom audience
    row exists the moment it is created and says nothing about whether Meta will
    serve it; the account audited on 2026-08-20 held seven lookalikes, every one
    of them reporting "Audience is too small to be used in campaign creation".
    Nothing surfaced that, so the plan offered ad sets Meta would never deliver.

    ``approximate_count_lower_bound`` is the seed check: Meta will not build a
    lookalike from a source it could not match enough people in, and that is
    knowable BEFORE the lookalike is created (a fresh one always reports
    "Updating", so reading the lookalike itself proves nothing).
    """
    if not ad_account_id:
        return []
    try:
        result = await _request(
            "GET",
            f"{_act(ad_account_id)}/customaudiences",
            access_token,
            json_data={
                "fields": (
                    "id,name,subtype,description,retention_days,"
                    "approximate_count_lower_bound,delivery_status,operation_status"
                ),
                "limit": 200,
            },
        )
    except MetaAdsError as exc:
        logger.warning("list_custom_audiences(%s): failed — %s", ad_account_id, exc)
        return []
    return [row for row in (result.get("data") or []) if row.get("id")]


async def fetch_delivery_estimate(
    ad_account_id: str,
    access_token: str,
    *,
    optimization_goal: str,
    targeting_spec: dict,
    promoted_object: dict | None = None,
) -> dict | None:
    """Meta's own reach estimate for a targeting spec, or ``None``.

    ``GET act_{id}/delivery_estimate`` — one of Meta's older endpoints; its
    own docs carry a standing deprecation warning ("you are calling a
    deprecated version of the Ads API", error 2635) without naming a
    replacement. Degrades to ``None`` on ANY failure rather than raising: a
    reach estimate is a nice-to-have on the plan screen, never worth blocking
    it, and this may simply error on some objectives/API versions regardless
    of anything the caller did wrong.

    ``targeting_spec`` is the same targeting dict ``AdSetSpec._wire_targeting``
    already builds for the real ad set — no second targeting construction to
    keep in sync. Complex params ride as JSON strings, the documented shape
    for this endpoint (unlike every POST body elsewhere in this module).

    Returns ``{"estimate_mau_lower_bound", "estimate_mau_upper_bound",
    "estimate_ready"}`` — Meta's monthly-active-user reach bounds for this
    targeting, and whether the estimate has finished computing (a very new or
    very narrow spec can report not-ready with no bounds yet).
    """
    if not ad_account_id or not targeting_spec:
        return None
    params: dict[str, Any] = {
        "optimization_goal": optimization_goal,
        "targeting_spec": json.dumps(targeting_spec),
    }
    if promoted_object:
        params["promoted_object"] = json.dumps(promoted_object)
    try:
        result = await _request(
            "GET", f"{_act(ad_account_id)}/delivery_estimate", access_token,
            json_data=params, retries=1,
        )
    except MetaAdsError as exc:
        logger.info("fetch_delivery_estimate(%s): failed — %s", ad_account_id, exc)
        return None
    data = result.get("data") or []
    if not data or not isinstance(data[0], dict):
        return None
    row = data[0]
    return {
        "estimate_mau_lower_bound": row.get("estimate_mau_lower_bound"),
        "estimate_mau_upper_bound": row.get("estimate_mau_upper_bound"),
        "estimate_ready": row.get("estimate_ready"),
    }


def audience_is_usable(audience: dict) -> bool:
    """Will Meta actually serve ads to this audience?

    ``delivery_status.code == 200`` is Meta's own answer. Anything else — too
    small, still populating, expired — means an ad set pointed at it does not
    deliver. An audience with no delivery_status at all is treated as usable: the
    field is absent on some reads, and refusing an audience because a projection
    was thin would hide the user's own working audiences from them.
    """
    code = (audience.get("delivery_status") or {}).get("code")
    return code is None or int(code) == 200


# One year, Meta's ceiling for a website audience. Chosen as the DEFAULT rather
# than something shorter because the window is the audience: a 30-day rule on a
# considered purchase (a mortgage, a car) excludes most of the people worth
# retargeting, and widening it later does not retroactively collect anybody.
MAX_AUDIENCE_RETENTION_DAYS = 365


async def create_website_audience(
    name: str,
    dataset_id: str,
    ad_account_id: str,
    access_token: str,
    *,
    event_name: str = "",
    retention_days: int = 180,
    description: str = "",
) -> str:
    """Create a WEBSITE audience over a dataset and return its id.

    This is the other half of conversion tracking, and the half Punk did not have:
    the pixel and the Conversions API fill a dataset, and until now nothing could
    advertise to the people in it. ``event_name`` empty means everyone the dataset
    has seen; a name means the people who fired that event, which is how a
    "converters" audience gets built — the one worth EXCLUDING from prospecting.

    The rule is Meta's flexible-rule grammar, not ours. ``retention_seconds`` on
    the rule is what Meta honours for these; ``retention_days`` is sent too so the
    value the user picked is visible on the audience in Ads Manager rather than
    only inside the rule.
    """
    days = max(1, min(int(retention_days or 180), MAX_AUDIENCE_RETENTION_DAYS))
    rule_entry: dict[str, Any] = {
        "event_sources": [{"id": str(dataset_id), "type": "pixel"}],
        "retention_seconds": days * 24 * 60 * 60,
    }
    if event_name:
        rule_entry["filter"] = {
            "operator": "and",
            "filters": [
                {"field": "event", "operator": "eq", "value": event_name},
            ],
        }
    else:
        rule_entry["template"] = "ALL_VISITORS"

    result = await _request(
        "POST",
        f"{_act(ad_account_id)}/customaudiences",
        access_token,
        json_data={
            "name": name,
            # **No subtype.** Measured live on v25.0: ``subtype: "WEBSITE"`` is
            # rejected outright — "The parameter 'subtype' is not supported in
            # the current API version" (subcode 1870053). A rule-based audience
            # is now defined by its ``rule`` alone and Meta infers the subtype
            # from it. This is NOT true of the customer-file audiences
            # ``create_custom_audience`` builds: those still require
            # ``subtype: "CUSTOM"`` and fail with "Missing parameter(s): subtype"
            # without it. Two different creates, two different rules.
            "retention_days": days,
            "description": description or (
                f"People who triggered {event_name} in the last {days} days"
                if event_name else
                f"Everyone your dataset saw in the last {days} days"
            ),
            "rule": json.dumps({"inclusions": {"operator": "or", "rules": [rule_entry]}}),
        },
    )
    audience_id = result.get("id")
    if not audience_id:
        raise MetaAdsError("Website audience creation returned no ID")
    return str(audience_id)


# Meta's cap on one /users request.
_AUDIENCE_UPLOAD_BATCH = 10_000

# Which schemas take a raw value and which take a digest. MADID is the odd one
# out and the reason this mapping exists: the ``MADID`` schema wants the device's
# real IDFA/AAID, and hashing it matched zero devices. Every other schema here is
# a person-identifier Meta expects SHA-256'd.
_AUDIENCE_SCHEMA_FIELDS: dict[str, str] = {
    "EMAIL": "email",
    "PHONE": "phone",
    "FN": "first_name",
    "LN": "last_name",
    "CT": "city",
    "ST": "state",
    "ZIP": "zip",
    "COUNTRY": "country",
    "DOBY": "date_of_birth",
    "GEN": "gender",
}


async def upload_audience_users(
    audience_id: str,
    rows: list[list[str]],
    access_token: str,
    *,
    schema: list[str],
) -> int:
    """Upload rows to a custom audience, hashing whatever Meta wants hashed.

    ``rows`` are parallel to ``schema``: ``schema=["EMAIL", "PHONE"]`` means each
    row is ``[email, phone]``. Normalization and hashing come from
    ``meta_capi.hash_user_field`` — the same rules the Conversions API sender uses,
    already implemented and tested there. A second copy of "lowercase, strip, digits
    only for a phone" is a second thing to drift, and a digest built the wrong way
    is accepted by Meta, matched to nobody, and reported as a working upload.

    ``MADID`` passes through raw, lowercased. Returns rows submitted.
    """
    from app.services import meta_capi

    unknown = [s for s in schema if s != "MADID" and s not in _AUDIENCE_SCHEMA_FIELDS]
    if unknown:
        raise MetaAdsError(f"unsupported audience schema field(s): {', '.join(unknown)}")

    prepared: list[list[str]] = []
    for row in rows:
        out: list[str] = []
        for column, raw in zip(schema, row):
            value = str(raw or "").strip()
            if not value:
                out.append("")
                continue
            if column == "MADID":
                out.append(value.lower())
            else:
                out.append(meta_capi.hash_user_field(_AUDIENCE_SCHEMA_FIELDS[column], value))
        # A row that hashed to nothing at all identifies no one; sending it just
        # dilutes the match rate Meta reports back.
        if any(out):
            prepared.append(out)

    total = 0
    for i in range(0, len(prepared), _AUDIENCE_UPLOAD_BATCH):
        batch = prepared[i : i + _AUDIENCE_UPLOAD_BATCH]
        await _request(
            "POST",
            f"{audience_id}/users",
            access_token,
            json_data={"payload": {"schema": list(schema), "data": batch}},
        )
        total += len(batch)
        logger.info(
            "audience upload (%s): %d/%d sent to %s",
            ",".join(schema), total, len(prepared), audience_id,
        )

    return total


async def upload_maids_to_audience(
    audience_id: str, maids: list[str], access_token: str
) -> int:
    """Upload MAIDs in batches of 10,000.

    MADIDs go to Meta **unhashed** — the ``MADID`` schema takes the raw mobile
    advertiser ID (SHA256 is for the email/phone/name schemas, and hashing here
    matched zero devices). Lowercase + strip is the whole normalization: the
    stored value is the device's real IDFA/AAID, so hyphens are passed through
    exactly as they came, never added or removed.

    Returns the total number of MAIDs successfully submitted.
    """
    from app.services.maid_store import suppress

    clean = [m for m in maids if m and m.strip()]
    clean = await suppress(clean)
    return await upload_audience_users(
        audience_id,
        [[m] for m in clean],
        access_token,
        schema=["MADID"],
    )


# ── Lookalike audience ────────────────────────────────────────────────────────


def _derive_lookalike_countries(geo_data: dict, user_info: dict) -> list[str]:
    """Best-effort ISO country codes for the lookalike seed expansion.

    Order, most to least authoritative:
      meta_targeting.geo_locations.countries
      -> target_zips prefixes ("CA:M5V" -> CA)
      -> geocoded locations' country_code
      -> explicit country fields
      -> ["US"].

    ``target_zips`` is the one source that always exists on a real run: it is
    what publish actually targets, and ``resolve_poi_zips`` builds every key as
    ``<ISO>:<postal>`` from the POI's own address components. The layers around
    it are never populated by the current builder, so without this the fallback
    swallowed every non-US run and built a US lookalike for a Canadian seed.
    """
    meta_geo = (
        (geo_data.get("meta_targeting") or {}).get("geo_locations") or {}
    )
    countries = meta_geo.get("countries")
    if countries:
        return [str(c).upper() for c in countries]

    from_zips = {
        z.split(":", 1)[0].strip().upper()
        for z in (geo_data.get("target_zips") or [])
        if isinstance(z, str) and ":" in z
    }
    if from_zips:
        return sorted(from_zips)

    # No zips resolved — publish falls back to city targeting, so read the
    # country off the same geocoded locations that path uses.
    from_locations = {
        str(loc.get("country_code")).strip().upper()
        for loc in (geo_data.get("locations") or [])
        if loc.get("country_code")
    }
    if from_locations:
        return sorted(from_locations)

    explicit = (
        geo_data.get("country")
        or user_info.get("country")
        or user_info.get("country_code")
    )
    if explicit:
        return [str(explicit).upper()]

    logger.warning("_derive_lookalike_countries: no country found — defaulting to US")
    return ["US"]


async def create_lookalike_audience(
    name: str,
    origin_audience_id: str,
    countries: list[str],
    ad_account_id: str,
    access_token: str,
    ratio: float = 0.01,
) -> str:
    """Create a LOOKALIKE audience seeded from a custom audience. Returns its id.

    Meta builds the lookalike asynchronously; the returned audience may be in a
    pending state. Callers should not poll for readiness — the campaign ships
    PAUSED regardless.
    """

    # ``country``/``countries`` deliberately absent. Marketing API v26.0 has
    # silently ignored both fields in lookalike_spec since 1 Sep 2026 — the
    # lookalike's geo now comes from the ad set's own targeting instead. Setting
    # them isn't an error, it's a no-op that looks like it did something;
    # ``countries``/``_derive_lookalike_countries`` stay as unused inputs on the
    # signature rather than touching every caller for a dead field.
    spec: dict[str, Any] = {"type": "similarity", "ratio": ratio}

    result = await _request(
        "POST",
        f"{_act(ad_account_id)}/customaudiences",
        access_token,
        json_data={
            "name": name,
            "subtype": "LOOKALIKE",
            "origin_audience_id": origin_audience_id,
            "lookalike_spec": spec,
        },
    )
    audience_id = result.get("id")
    if not audience_id:
        raise MetaAdsError("Lookalike audience creation returned no ID")
    return str(audience_id)


# ── Campaign creation ─────────────────────────────────────────────────────────


async def create_campaign_from_spec(
    spec: "CampaignSpec", *, ad_account_id: str, access_token: str
) -> str:
    """Create a campaign from a validated ``CampaignSpec``.

    Unlike ``create_campaign``, nothing is re-derived: the objective is already
    a checked Meta enum value and ``special_ad_categories`` carries whatever the
    user declared, instead of the hardcoded ``[]`` that shipped every regulated
    advertiser undeclared.
    """
    result = await _request(
        "POST",
        f"{_act(ad_account_id)}/campaigns",
        access_token,
        json_data=spec.to_payload(),
    )
    camp_id = result.get("id")
    if not camp_id:
        raise MetaAdsError("Campaign creation returned no ID")
    return str(camp_id)


async def create_adset_from_spec(
    adset: "AdSetSpec",
    *,
    campaign_id: str,
    ad_account_id: str,
    access_token: str,
    campaign_has_budget: bool = False,
) -> str:
    """Create an ad set from a validated ``AdSetSpec``.

    Sends the ad set's own budget, optimization goal, billing event, bid
    strategy and destination type. The previous ``create_adset`` hardcoded
    IMPRESSIONS + LOWEST_COST_WITHOUT_CAP and took a single budget shared by
    every ad set, silently discarding the plan's split.

    ``campaign_has_budget`` (Advantage+ campaign budget / CBO) tells the payload
    to omit budget + bid strategy — Meta rejects an ad set that carries them
    when the campaign owns the budget.
    """
    result = await _request(
        "POST",
        f"{_act(ad_account_id)}/adsets",
        access_token,
        json_data=adset.to_payload(
            campaign_id=campaign_id,
            ad_account_id=ad_account_id,
            campaign_has_budget=campaign_has_budget,
        ),
    )
    adset_id = result.get("id")
    if not adset_id:
        raise MetaAdsError("Ad set creation returned no ID")
    return str(adset_id)


async def validate_campaign_payload(
    spec: "CampaignSpec", *, ad_account_id: str, access_token: str
) -> None:
    """Ask Meta to check the campaign payload without creating it."""
    await _request(
        "POST",
        f"{_act(ad_account_id)}/campaigns",
        access_token,
        json_data=spec.to_payload(),
        validate_only=True,
    )


async def validate_adset_payload(
    adset: "AdSetSpec",
    *,
    campaign_id: str,
    ad_account_id: str,
    access_token: str,
    campaign_has_budget: bool = False,
) -> None:
    """Ask Meta to check one ad set payload without creating it.

    Needs a real ``campaign_id``, which is why the publish flow validates the
    campaign first, creates it, then validates every ad set against it before
    creating any — see ``preflight_publish``.
    """
    await _request(
        "POST",
        f"{_act(ad_account_id)}/adsets",
        access_token,
        json_data=adset.to_payload(
            campaign_id=campaign_id,
            ad_account_id=ad_account_id,
            campaign_has_budget=campaign_has_budget,
        ),
        validate_only=True,
    )


async def delete_campaign(campaign_id: str, access_token: str) -> None:
    """Delete a campaign. Used to roll back a preflight that failed partway.

    Meta only truly deletes campaigns with no spend; a campaign we created
    seconds ago and never activated qualifies. Best-effort — a failure here is
    logged, never raised, because it happens while already handling an error.
    """
    try:
        await _request("POST", campaign_id, access_token, json_data={"status": "DELETED"})
    except MetaAdsError as exc:
        logger.warning("rollback: could not delete campaign %s — %s", campaign_id, exc)


async def fetch_ad_pixels(ad_account_id: str, access_token: str) -> list[dict]:
    """Return list of {id, name, last_fired_time} pixel dicts for this account.

    Empty list on any failure. ``last_fired_time`` rides along because it is what
    separates a *warm* dataset — one already receiving events, with delivery
    history behind it — from a cold one nobody ever installed, and the resolver
    prefers warm. Reading it here rather than per-pixel in
    ``fetch_pixel_activity`` keeps that decision to one Graph call.
    """
    try:
        result = await _request(
            "GET",
            f"{_act(ad_account_id)}/adspixels",
            access_token,
            json_data={"fields": "id,name,last_fired_time"},
        )
        return result.get("data") or []
    except MetaAdsError as exc:
        logger.warning("fetch_ad_pixels: failed — %s", exc)
        return []


# Meta refuses a second pixel on an account that already has one. Both codes mean
# the same thing for us — someone created one between our read and our write — so
# the answer is to re-read rather than to fail.
_PIXEL_EXISTS_CODES = frozenset({6200, 6202})


async def create_ad_pixel(name: str, ad_account_id: str, access_token: str) -> str:
    """Create a Meta Pixel on the ad account and return its id.

    Called only when ``fetch_ad_pixels`` came back empty: a conversion objective
    cannot be published without one, and an advertiser who has never run ads has
    no reason to have made one yet.

    Creating the pixel is not the same as conversion tracking working — it still
    has to be installed on the site. Callers must say so; see
    ``fetch_pixel_activity`` for how to tell whether it ever fired.
    """
    try:
        result = await _request(
            "POST", f"{_act(ad_account_id)}/adspixels", access_token,
            json_data={"name": name},
        )
    except MetaAdsError as exc:
        if exc.code not in _PIXEL_EXISTS_CODES:
            raise
        # Lost a race with another client (or with the user in Events Manager).
        # The pixel we wanted now exists — take it.
        existing = await fetch_ad_pixels(ad_account_id, access_token)
        if not existing:
            raise
        logger.info(
            "create_ad_pixel(%s): account already had a pixel — using %s",
            ad_account_id, existing[0].get("id"),
        )
        return str(existing[0]["id"])

    pixel_id = result.get("id")
    if not pixel_id:
        raise MetaAdsError("Pixel creation returned no ID")
    return str(pixel_id)


async def fetch_pixel_activity(pixel_id: str, access_token: str) -> dict:
    """``{id, name, last_fired_time}`` for one pixel — {} on any failure.

    ``last_fired_time`` is the honest answer to "is this actually tracking
    anything?". A pixel that exists but has never fired makes a conversion
    campaign publish cleanly and then optimize toward an event that never
    arrives, so the publish-preview screen reads this before offering to go live.

    Degrades to {} on purpose: a missing preview row is never worth failing a
    gate the user is standing in front of.
    """
    try:
        return await _request(
            "GET", f"{pixel_id}?fields=id,name,last_fired_time", access_token, retries=1,
        )
    except MetaAdsError as exc:
        logger.warning("fetch_pixel_activity(%s): failed — %s", pixel_id, exc)
        return {}


# ── Datasets and custom conversions ───────────────────────────────────────────
#
# "Pixel" and "dataset" are the same object under two names: Meta folded the pixel
# into the dataset, and both are the ``adspixels`` edge with the same id. The
# functions below say *dataset* where the thing being talked about is the event
# store (which the Conversions API posts to) and *pixel* where it is the browser
# tag, but there is only one id.
#
# Every one of these runs against the CONNECTED USER's token and creates assets in
# the CONNECTED USER's business. Punk owns no Meta assets and holds no
# platform-wide Meta credential — see app/modules/tracking for the event path.


async def fetch_ad_account_business(
    ad_account_id: str, access_token: str
) -> dict | None:
    """``{id, name}`` of the business portfolio owning this ad account.

    A dataset created on the ad account is scoped to that account; one created in
    the owning business can be shared to it and reused across the advertiser's
    other accounts. So the resolver asks which portfolio the account is in before
    deciding where to create.

    Three distinct answers, and collapsing the last two is a real bug:

      * ``{id, name}`` — the account is in this portfolio.
      * ``{}``         — read fine, the account is in none. A personal ad account.
      * ``None``       — the read FAILED (throttle, permission), so we do not know.

    ``ad_account_blockers`` turns an unknown into "do not block", because
    telling someone their account is not in a Business when we simply could not
    ask is worse than staying quiet.
    """
    try:
        result = await _request(
            "GET",
            f"{_act(ad_account_id)}?fields=business{{id,name}}",
            access_token,
            retries=1,
        )
    except MetaAdsError as exc:
        logger.warning("fetch_ad_account_business(%s): failed — %s", ad_account_id, exc)
        return None
    business = result.get("business")
    return business if isinstance(business, dict) else {}


async def fetch_business_datasets(business_id: str, access_token: str) -> list[dict]:
    """Every dataset in the user's business portfolio — ``[]`` on any failure.

    Wider than ``fetch_ad_pixels``, which only sees what is attached to the one ad
    account. An advertiser whose dataset lives in their business but was never
    assigned to the account they are publishing from shows up here and nowhere
    else, and reusing it beats creating a second one that starts cold.
    """
    if not business_id:
        return []
    try:
        result = await _request(
            "GET",
            f"{business_id}/adspixels",
            access_token,
            json_data={"fields": "id,name,last_fired_time,owner_business"},
        )
        return result.get("data") or []
    except MetaAdsError as exc:
        logger.warning("fetch_business_datasets(%s): failed — %s", business_id, exc)
        return []


async def create_business_dataset(name: str, business_id: str, access_token: str) -> str:
    """Create a dataset in the user's business portfolio and return its id.

    Business-scoped rather than account-scoped (``create_ad_pixel``) so the
    advertiser can point every ad account they own at the same event store, and so
    the per-account "one pixel only" limit (_PIXEL_EXISTS_CODES) is not the thing
    that decides whether tracking is available.

    Raises rather than degrading: the caller offered the user a create, so a
    failure has to be reportable. It falls back to ``create_ad_pixel``.
    """
    result = await _request(
        "POST", f"{business_id}/adspixels", access_token, json_data={"name": name},
    )
    dataset_id = result.get("id")
    if not dataset_id:
        raise MetaAdsError("Dataset creation returned no ID")
    return str(dataset_id)


async def share_dataset_with_account(
    dataset_id: str, ad_account_id: str, access_token: str
) -> bool:
    """Assign a business-owned dataset to one ad account. True when it stuck.

    An ad set's ``promoted_object.pixel_id`` is only usable if the dataset is
    assigned to the ad account running the ads — owning it in the business is not
    enough. Returns False instead of raising because "already shared" and "no
    permission to share" both leave the caller with the same next move: try the
    dataset anyway, and let publish's preflight be the authority.
    """
    account = _act(ad_account_id)
    try:
        await _request(
            "POST",
            f"{dataset_id}/shared_accounts",
            access_token,
            json_data={"account_id": account.removeprefix("act_")},
        )
        return True
    except MetaAdsError as exc:
        logger.warning(
            "share_dataset_with_account(%s → %s): failed — %s", dataset_id, account, exc,
        )
        return False


async def fetch_token_info(access_token: str) -> dict:
    """Everything ``debug_token`` knows about this token in one call.

    One Graph call already in the OAuth flow (``fetch_token_scopes`` used to
    throw away everything but ``scopes``) answers four questions: which scopes,
    which token type (``USER`` vs a business-integration system-user type),
    when it expires (``0`` = never), and — via ``granular_scopes`` — the exact
    per-permission granted asset ids. That last field is the authoritative
    granted-asset list and is what the page-token fallback in
    ``list_page_tokens`` reads when ``/me/accounts`` comes back empty for a
    system-user token.

    ``{"scopes": [], "type": "", "expires_at": None, "granular_scopes": []}`` on
    any failure — the caller must treat that as "unknown", not "none granted":
    telling a working advertiser to reconnect because a throttle ate this read
    is worse than not knowing.
    """
    empty = {"scopes": [], "type": "", "expires_at": None, "granular_scopes": []}
    if not access_token:
        return empty
    # debug_token must be authenticated with the APP's own token, not the token
    # being inspected — Meta refuses otherwise: "(#100) You must provide an app
    # access token, or a user access token that is an owner or developer of the
    # app", measured live, which silently degraded every connection to the old
    # defensive branch (the exception here read as "unknown token type", not
    # "not a system user"). Sending that app token via the Authorization Bearer
    # header (meta_ads._request's normal contract, and the same shape
    # unsubscribe_page_leadgen uses successfully elsewhere) still hit the
    # identical error live — this endpoint apparently only honors the app token
    # as the documented ``access_token=`` query parameter. Bypasses _request
    # for this one call since its auth contract genuinely differs from every
    # other edge Punk calls.
    app_token = f"{settings.META_APP_ID}|{settings.META_APP_SECRET}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{_BASE}/debug_token",
                params={"input_token": access_token, "access_token": app_token},
            )
        result = resp.json()
        if "error" in result:
            err = result["error"]
            raise MetaAdsError(
                f"{err.get('type', 'OAuthException')}: {err.get('message', 'unknown')}",
                code=err.get("code"),
            )
    except (MetaAdsError, httpx.TransportError, httpx.TimeoutException) as exc:
        logger.warning("fetch_token_info: failed — %s", exc)
        return empty
    data = result.get("data") or {}
    scopes = data.get("scopes") or []
    logger.info(
        "fetch_token_info: type=%r expires_at=%r granular_scopes_count=%d",
        data.get("type"), data.get("expires_at"), len(data.get("granular_scopes") or []),
    )
    return {
        "scopes": [str(s) for s in scopes if s],
        "type": str(data.get("type") or ""),
        "expires_at": data.get("expires_at"),
        "granular_scopes": data.get("granular_scopes") or [],
    }


async def fetch_token_scopes(access_token: str) -> list[str]:
    """The permissions this token was actually granted, or ``[]``.

    Thin wrapper over ``fetch_token_info`` kept so existing callers (and
    ``test_meta_scope_and_subscription.py``) do not have to change shape.
    """
    return (await fetch_token_info(access_token))["scopes"]


def granted_ad_account_ids(granular_scopes: list[dict]) -> set[str] | None:
    """The ad account ids ``granular_scopes`` actually grants, bare numeric form.

    ``granular_scopes`` is the authoritative granted-asset list (see
    ``fetch_token_info``) — the same field ``list_page_tokens`` already reads
    for Pages. Returns ``None``, not ``set()``, when the grant is unreadable
    (no ``ads_management``/``ads_read`` entry, or one with no ``target_ids``
    key — Meta omits that key when the permission covers every asset): the
    caller must treat "unknown" as "don't filter", never as "grant nothing".
    An empty ``granular_scopes`` list — ``fetch_token_info``'s own failure
    value — hits the same `None` path for the same reason.
    """
    ids: set[str] = set()
    seen = False
    for entry in granular_scopes or []:
        if entry.get("scope") not in ("ads_management", "ads_read"):
            continue
        target_ids = entry.get("target_ids")
        if not target_ids:
            continue
        seen = True
        ids.update(str(t).removeprefix("act_") for t in target_ids)
    return ids if seen else None


async def page_leadgen_subscribed(page_id: str, page_token: str) -> bool | None:
    """Is this app actually subscribed to the Page's ``leadgen`` field?

    ``None`` when we could not ask — reading ``subscribed_apps`` needs
    ``pages_manage_metadata``, and a token minted before that scope was requested
    answers "(#200) Requires pages_manage_metadata". That is a different answer
    from "not subscribed", and conflating them would accuse a working setup on
    every account still holding an older token.
    """
    if not (page_id and page_token):
        return None
    try:
        result = await _request(
            "GET",
            f"{page_id}/subscribed_apps",
            page_token,
            json_data={"fields": "id,subscribed_fields"},
            retries=1,
        )
    except MetaAdsError as exc:
        logger.info(
            "page_leadgen_subscribed(%s): cannot read the subscription — %s",
            page_id, exc,
        )
        return None
    for row in result.get("data") or []:
        if str(row.get("id") or "") != str(settings.META_APP_ID):
            continue
        return "leadgen" in (row.get("subscribed_fields") or [])
    return False


async def subscribe_page_leadgen(page_id: str, page_token: str) -> bool:
    """Subscribe this app to the Page's ``leadgen`` webhook. True when it stuck.

    Without it a lead submitted on an instant form exists only inside Meta: the
    campaign optimizes fine (Meta counts the lead itself), but nothing tells the
    advertiser which leads arrived, and the advertiser who could POST them to
    /tracking/leads themselves is exactly the one who cannot.

    Needs the PAGE token, not the user token — subscribing an app to a Page is a
    Page-scoped write. Returns False rather than raising for the same reason as
    ``share_dataset_with_account``: the campaign publishes either way, and a
    missing subscription is a remediation card, never a failed publish.

    **The POST's own answer is not the result.** Measured on a live Page: the
    write returns success while ``subscribed_apps`` still lists nothing, which is
    what made ``lead_webhook_not_subscribed`` unraisable — the one signal it had
    said everything was fine. So the subscription is read back, and only a read
    that finds ``leadgen`` counts as True. A read we are not allowed to make
    (``None``) falls back to the POST's answer rather than reporting a working
    subscription as broken.
    """
    if not (page_id and page_token):
        return False
    try:
        await _request(
            "POST",
            f"{page_id}/subscribed_apps",
            page_token,
            json_data={"subscribed_fields": "leadgen"},
        )
    except MetaAdsError as exc:
        logger.warning("subscribe_page_leadgen(%s): failed — %s", page_id, exc)
        return False

    confirmed = await page_leadgen_subscribed(page_id, page_token)
    if confirmed is None:
        logger.warning(
            "subscribe_page_leadgen(%s): Meta accepted the write but the token "
            "cannot read subscribed_apps back (needs pages_manage_metadata) — "
            "treating it as subscribed, unverified",
            page_id,
        )
        return True
    if not confirmed:
        logger.warning(
            "subscribe_page_leadgen(%s): Meta accepted the write and the Page "
            "still is not subscribed to leadgen", page_id,
        )
    return confirmed


async def unsubscribe_page_leadgen(page_id: str) -> bool:
    """Drop this app's subscription to the Page. True when Meta accepted it.

    The other half of ``subscribe_page_leadgen``: until this existed a Page could
    be subscribed and never unsubscribed from Punk, so an advertiser who stopped
    running lead ads kept delivering leads into a dataset nobody watched.

    **Takes no token, and deliberately.** Measured live: the DELETE refuses a Page
    token with "(#15) This method must be called with an app access_token" — the
    subscription belongs to the APP, not to the Page or the user, so removing it
    is an app-level action. The app token is derived from config rather than
    passed in, because there is exactly one right answer and a caller reaching for
    the user's token would get a confusing #15 instead of a working unsubscribe.
    """
    if not (page_id and settings.META_APP_ID and settings.META_APP_SECRET):
        return False
    app_token = f"{settings.META_APP_ID}|{settings.META_APP_SECRET}"
    try:
        await _request("DELETE", f"{page_id}/subscribed_apps", app_token)
        return True
    except MetaAdsError as exc:
        logger.warning("unsubscribe_page_leadgen(%s): failed — %s", page_id, exc)
        return False


async def fetch_lead(leadgen_id: str, page_token: str) -> dict:
    """One instant-form lead, or ``{}``.

    The webhook delivery carries only ids — the answers live behind this read, and
    only the Page token can make it. ``{}`` on any failure: a lead we cannot read
    is a lead we cannot forward, and there is nothing for the caller to do about
    it that retrying the whole delivery would not do better.
    """
    if not (leadgen_id and page_token):
        return {}
    try:
        return await _request(
            "GET",
            str(leadgen_id),
            page_token,
            json_data={"fields": "created_time,field_data,form_id,ad_id,campaign_id"},
        ) or {}
    except MetaAdsError as exc:
        logger.warning("fetch_lead(%s): failed — %s", leadgen_id, exc)
        return {}


async def fetch_verified_domains(business_id: str, access_token: str) -> set[str] | None:
    """The domains this business has verified — ``None`` when we could not ask.

    Meta never errors on an unverified domain. It accepts the campaign, runs it,
    and quietly attributes a fraction of the web conversions it otherwise would —
    which is why ``domain_not_verified`` could not be raised off an exception like
    every other remediation entry, and sat in the catalog unreachable.

    ``None`` and ``set()`` are deliberately different answers, the same split as
    ``fetch_ad_account_business``: ``None`` is "the read failed", and accusing
    someone's working domain because a throttle ate the lookup is worse than
    saying nothing.

    No ``fields`` argument on purpose. Meta fails the WHOLE read with code 100 for
    one field a node does not have (see ``fetch_ad_account_currency``), and the
    default projection already carries the domain name — so whatever key it
    arrives under is read rather than demanded.

    **Measured 2026-08-20, and it returns None on every account today.** This edge
    answers ``(#100) Tried accessing nonexisting field (owned_domains)`` on Graph
    v25.0 with a token holding ``business_management``. That is NOT the edge being
    gone: ``scripts/probe_domain_edge.py`` shows Meta answering a name it does not
    know (``verified_domains``, ``business_domains``) with ``Unknown path
    components`` / code 2500 instead, while the business node itself reads fine
    with the same token. Code 100 here means the edge exists and this app is not
    allowed to see it — Punk's app has not been added to the advertiser's business
    portfolio (Business settings → Apps). No code change fixes it; the caller in
    ``builder_node`` records ``domain_check: "unavailable"`` so a check that could
    not run never reads as a domain that passed.
    """
    if not business_id:
        return None
    try:
        result = await _request(
            "GET", f"{business_id}/owned_domains", access_token, retries=1,
        )
    except MetaAdsError as exc:
        logger.warning("fetch_verified_domains(%s): failed — %s", business_id, exc)
        return None

    rows = result.get("data")
    if not isinstance(rows, list):
        return None
    domains: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("domain_name") or row.get("domain") or row.get("name") or ""
        if name:
            domains.add(str(name).strip().lower().removeprefix("www."))
    return domains


async def fetch_custom_conversions(ad_account_id: str, access_token: str) -> list[dict]:
    """The account's custom conversions — ``[]`` on any failure.

    A custom conversion is a rule over events the dataset already receives, most
    usefully a URL rule ("any page view whose URL contains /thank-you"). That
    matters for the advertiser who has the base pixel on their site and no event
    code anywhere: they can still optimize for a real conversion without touching
    their site again.

    ``custom_event_type`` comes back too because an ad set optimizing for a custom
    conversion still needs the underlying standard event named.
    """
    try:
        result = await _request(
            "GET",
            f"{_act(ad_account_id)}/customconversions",
            access_token,
            json_data={
                "fields": "id,name,custom_event_type,rule,is_archived,is_unavailable",
            },
        )
    except MetaAdsError as exc:
        logger.warning("fetch_custom_conversions: failed — %s", exc)
        return []
    # Archived is how Meta deletes one of these — the row stays readable forever.
    # Measured: a conversion deleted through the API comes back from this edge
    # with is_archived true, so without this filter the editor kept offering
    # conversions the advertiser had thrown away, and an ad set pointed at one
    # optimizes toward a rule that no longer fires. ``is_unavailable`` is the
    # same class of answer for one Meta has disabled.
    return [
        row for row in (result.get("data") or [])
        if not row.get("is_archived") and not row.get("is_unavailable")
    ]


async def create_custom_conversion(
    name: str,
    dataset_id: str,
    ad_account_id: str,
    access_token: str,
    *,
    url_contains: str,
    custom_event_type: str = "PURCHASE",
) -> str:
    """Create a URL-rule custom conversion and return its id.

    ``url_contains`` is matched case-insensitively against the whole URL, which is
    what Events Manager's own "URL contains" builds. The rule shape is Meta's
    filter grammar, not ours — a bare string is rejected.

    The dataset goes in ``event_source_id``, not ``pixel_id``. Measured live on
    v25.0: ``pixel_id`` is refused with "(#100) The parameter event_source_id is
    required". This function had no callers until the tracking card gained one,
    so nothing had ever put it in front of Meta.
    """
    rule = json.dumps({"url": {"i_contains": url_contains}})
    result = await _request(
        "POST",
        f"{_act(ad_account_id)}/customconversions",
        access_token,
        json_data={
            "name": name,
            "event_source_id": str(dataset_id),
            "custom_event_type": custom_event_type,
            "rule": rule,
        },
    )
    conversion_id = result.get("id")
    if not conversion_id:
        raise MetaAdsError("Custom conversion creation returned no ID")
    return str(conversion_id)


def _emq_score(raw: Any) -> float | None:
    """The number out of Meta's Event Match Quality envelope, at whatever depth.

    Meta has shipped this as a bare number, as ``{score: …}`` and as a nested
    object with diagnostics beside it. One tolerant reader beats a parse that
    breaks silently the next time the shape moves — and silent is the operative
    word here, because the caller degrades to None.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, dict):
        for key in ("score", "value", "event_match_quality"):
            found = _emq_score(raw.get(key))
            if found is not None:
                return found
    return None


async def fetch_event_match_quality(
    dataset_id: str, access_token: str, *, event_name: str = ""
) -> float | None:
    """Event Match Quality for one dataset (0–10), or None.

    EMQ is Meta's read on how well the identifiers we send resolve to real
    accounts: hashed email is worth the most, phone next, and a server integration
    sending only an IP scores near zero and optimizes badly. Punk shows it at the
    go-live gate so a bad integration is visible before money moves.

    Returns the score rather than Meta's envelope because both callers want the
    number, and the shape of that envelope is not ours — parsing it in two places
    is two places to break when it drifts. Every failure, including a shape we do
    not recognize, is None: this is a diagnostic on a screen the user is standing
    in front of, and a missing row must never break the gate.
    """
    try:
        result = await _request(
            "GET",
            # A TOP-LEVEL edge taking the dataset as a PARAMETER — NOT
            # ``/{dataset_id}/dataset_quality``. The Dataset Quality API is one of
            # the few Graph reads shaped this way. The nested form this used to
            # call, with an ``aggregation`` argument that does not exist, could
            # only ever fail — and since every failure here degrades to None, it
            # read as "Meta has no score for you yet" indefinitely rather than as
            # a broken call.
            "dataset_quality",
            access_token,
            json_data={
                "dataset_id": str(dataset_id),
                "fields": "web{event_match_quality,event_name}",
            },
            retries=1,
        )
    except MetaAdsError as exc:
        logger.warning("fetch_event_match_quality(%s): failed — %s", dataset_id, exc)
        return None

    try:
        scores: dict[str, float] = {}
        for row in result.get("web") or []:
            if not isinstance(row, dict):
                continue
            score = _emq_score(row.get("event_match_quality"))
            if score is not None:
                scores[str(row.get("event_name") or "")] = score
        if not scores:
            return None
        # Meta scores each event separately, so pick the one delivery actually
        # learns from when the caller named it. A dataset matching PageView
        # perfectly and Purchase badly optimizes badly, and the best-of number
        # hides precisely that.
        if event_name and event_name in scores:
            return scores[event_name]
        return max(scores.values())
    except Exception:  # pragma: no cover — shape drift must not break the gate
        logger.warning("fetch_event_match_quality(%s): unreadable payload", dataset_id)
    return None


async def fetch_dataset_event_stats(
    dataset_id: str, access_token: str, *, days: int = 7
) -> dict[str, int]:
    """``{event_name: count}`` the dataset received recently — ``{}`` on any failure.

    ``last_fired_time`` answers "did anything arrive"; this answers "did the event
    the ad set optimizes for arrive". They are different questions and only the
    second one catches the common failure: a base pixel installed site-wide fires
    ``PageView`` forever while the ``Purchase`` the campaign is learning from was
    never coded, so the dataset looks alive and delivery optimizes against nothing.

    Names come back in Meta's wire spelling (``Purchase``), not the ad set's
    ``custom_event_type`` enum (``PURCHASE``) — compare through
    ``meta_capi.event_name_for``.

    Degrades to ``{}`` on a failure OR on a shape we do not recognize, for the same
    reason as ``fetch_event_match_quality``: this feeds a diagnostic the user is
    standing in front of, and a missing row must never break the gate.
    """
    if not dataset_id:
        return {}
    start = int(datetime.now(timezone.utc).timestamp()) - days * 24 * 60 * 60
    try:
        result = await _request(
            "GET",
            f"{dataset_id}/stats",
            access_token,
            json_data={"aggregation": "event", "start_time": start},
            retries=1,
        )
    except MetaAdsError as exc:
        logger.warning("fetch_dataset_event_stats(%s): failed — %s", dataset_id, exc)
        return {}

    counts: dict[str, int] = {}
    try:
        for row in result.get("data") or []:
            # One row per time bucket, each carrying the whole event→count map, so
            # the buckets are summed rather than the last one winning.
            value = row.get("value")
            if not isinstance(value, dict):
                continue
            for name, count in value.items():
                if isinstance(count, (int, float)) and not isinstance(count, bool):
                    counts[str(name)] = counts.get(str(name), 0) + int(count)
    except Exception:  # pragma: no cover — shape drift must not break the gate
        logger.warning("fetch_dataset_event_stats(%s): unreadable payload", dataset_id)
        return {}
    return counts


# Meta's targeting search classes → the flexible_spec field they belong under.
_TARGETING_SEARCH_TYPES = {
    "interests": ("adinterest", "interests"),
    "behaviors": ("adTargetingCategory", "behaviors"),
    # "More like this" — Meta returns interests related to the ones already
    # picked. Seeded by interest *names*, not by a free-text query.
    "suggestions": ("adinterestsuggestion", "interests"),
}


async def search_targeting_interests(
    query: str,
    access_token: str,
    *,
    kind: str = "interests",
    limit: int = 25,
) -> list[dict]:
    """Typeahead over Meta's detailed-targeting catalog for the campaign editor.

    ``kind`` is ``"interests"`` (``/search?type=adinterest``), ``"behaviors"``
    (``/search?type=adTargetingCategory&class=behaviors``) or ``"suggestions"``
    (``/search?type=adinterestsuggestion``), where ``query`` is a comma-separated
    list of already-picked interest names to find related ones. Returns a list of
    ``{id, name, audience_size?, path?, flex_field}`` where ``flex_field`` names
    the ``flexible_spec`` bucket the id belongs under (``interests``/``behaviors``)
    so the editor stores it correctly. Empty list on any failure — a search that
    errors must degrade to "no suggestions", never break the editor.
    """
    search_type, flex_field = _TARGETING_SEARCH_TYPES.get(
        kind, _TARGETING_SEARCH_TYPES["interests"]
    )
    params: dict[str, str] = {
        "type": search_type,
        "q": query,
        "limit": str(limit),
        "fields": "id,name,audience_size_lower_bound,audience_size_upper_bound,path",
    }
    if search_type == "adTargetingCategory":
        params["class"] = "behaviors"
    elif search_type == "adinterestsuggestion":
        seeds = [s.strip() for s in query.split(",") if s.strip()][:10]
        if not seeds:
            return []
        params.pop("q")
        params["interest_list"] = json.dumps(seeds)
    try:
        result = await _request("GET", "search", access_token, json_data=params)
    except MetaAdsError as exc:
        logger.warning("search_targeting_interests(%s): failed — %s", kind, exc)
        return []

    out: list[dict] = []
    for row in result.get("data") or []:
        out.append({
            "id": str(row.get("id")),
            "name": row.get("name"),
            "audience_size": row.get("audience_size_upper_bound")
            or row.get("audience_size_lower_bound"),
            "path": row.get("path"),
            "flex_field": flex_field,
        })
    return out


def _child_attachment(card: dict, cta: dict, picture: str | None = None) -> dict:
    """One ``child_attachments`` entry — a carousel card on the wire.

    Meta names the card's headline ``name`` and its small grey line
    ``description``, which is why CarouselCard.body maps to the latter rather
    than to the ad's primary text.

    ``cta`` is the ad-level call to action; its *link* is re-pointed at this
    card. Every card carried the parent link before, so a carousel with per-card
    destinations sent the card's button somewhere the card was not. A CTA that
    carries no link (an Instant Form's ``lead_gen_form_id``, WhatsApp's
    ``app_destination``) is passed through untouched.

    ``picture`` is the poster frame for a VIDEO card. Meta rejects the whole
    creative without one — subcode 1443052, "The field picture or image_hash is
    required in the link_data field of object_story_spec" — so a carousel mixing
    a video card among images could not publish at all. Same rule as the
    single-video ``video_data``; the caller resolves it because it holds the
    token.
    """
    cta_value = cta.get("value") or {}
    entry: dict[str, Any] = {
        "link": card["link"],
        "name": card["title"][:CREATIVE_TITLE_MAX],
        "call_to_action": (
            {**cta, "value": {**cta_value, "link": card["link"]}}
            if "link" in cta_value else cta
        ),
    }
    if card.get("body"):
        entry["description"] = card["body"][:CREATIVE_BODY_MAX]
    if card.get("video_id"):
        entry["video_id"] = card["video_id"]
        if picture:
            entry["picture"] = picture
    else:
        entry["image_hash"] = card["image_hash"]
    return entry


# No "videos" entry: the feed never carries any (see create_ad_creative), so a
# comparison on that key could only ever report a loss that did not happen.
_FEED_ASSET_LABELS = (
    ("titles", "headlines"),
    ("bodies", "bodies"),
    ("images", "images"),
)


async def _feed_assets_dropped(
    creative_id: str, sent: dict, access_token: str
) -> str | None:
    """What Meta discarded from an ``asset_feed_spec`` it just ACCEPTED, if any.

    Meta does not only reject a feed it dislikes — it also takes one and quietly
    stores less than was sent, with a 200 and no warning:

      * a feed whose only multi-valued field is media (several images, one
        headline, one body) comes back with no ``asset_feed_spec`` at all —
        which is why ``CreativeSpec.text_variations`` borrows a second headline
        for an ad carrying combined media;
      * a feed can be accepted and stored holding fewer assets than it was sent.

    Both leave an ad that publishes fine and runs one headline and one image —
    exactly the "where did my extras go?" symptom, and undetectable without
    reading the creative back. Returns a human-readable summary of the loss, or
    None when everything stuck. Never raises: a failed read-back is not a reason
    to fail a publish that already succeeded.
    """
    try:
        back = await _request(
            "GET", creative_id, access_token, json_data={"fields": "asset_feed_spec"},
        )
    except MetaAdsError as exc:
        logger.warning("creative %s: could not read the asset feed back (%s)", creative_id, exc)
        return None

    stored = back.get("asset_feed_spec") or {}
    if not stored:
        return (
            "Meta kept the ad but not the extra options — it only combines several "
            "images on one ad when the ad also has more than one headline or body"
        )
    lost = [
        f"{len(stored.get(key) or [])} of {len(sent.get(key) or [])} {label}"
        for key, label in _FEED_ASSET_LABELS
        if len(sent.get(key) or []) > len(stored.get(key) or [])
    ]
    return f"Meta kept {', '.join(lost)}" if lost else None


async def create_ad_creative(
    name: str,
    page_id: str,
    media_type: str,
    media_ref: str | None,
    title: str,
    body: str,
    cta_type: str,
    link_url: str,
    ad_account_id: str,
    access_token: str,
    *,
    url_tags: str | None = None,
    ad_format: str = "SINGLE",
    cards: list[dict] | None = None,
    lead_gen_form_id: str | None = None,
    object_story_id: str | None = None,
    source_instagram_media_id: str | None = None,
    instagram_user_id: str | None = None,
    description: str | None = None,
    titles: list[str] | None = None,
    bodies: list[str] | None = None,
    extra_media: list[tuple[str, str]] | None = None,
    on_fallback: Callable[[str], None] | None = None,
) -> str:
    """Create an ad creative and return its ID.

    Four shapes, decided by the approved spec — never guessed here:

      * boosted post     — ``object_story_id`` alone: the ad IS an existing Page
                           post, so there is no copy or media to compose. Checked
                           first because it makes every other field irrelevant.
      * SINGLE           — one ``image_hash``/``video_id`` on ``link_data``/``video_data``
      * CAROUSEL         — ``link_data.child_attachments``, media per card
      * any + lead form  — the CTA carries ``lead_gen_form_id`` instead of a link,
                           because an Instant Form ad opens a form, not a page

    ``cards`` entries are resolved ``CarouselCard`` dicts: each already carries an
    ``image_hash`` or ``video_id`` (publish uploads per card before calling this).
    ``url_tags`` are optional URL parameters appended on click.

    ``instagram_user_id`` is the identity Instagram placements run under. It is a
    top-level creative field, NOT part of ``object_story_spec`` — Meta rejects it
    there. (``instagram_actor_id`` was the old name and stopped working on
    2026-01-21.) Omitted when the Page has no linked Instagram account, which is
    legal: Meta then picks the identity itself.

    ``titles`` / ``bodies`` carry text variations (Ads Manager's "Add another
    option") and ``extra_media`` carries the images/videos beside ``media_ref``
    as resolved ``(meta_ref, "image" | "video")`` pairs. More than one of any of
    them ADDS an ``asset_feed_spec`` so Meta can combine and optimize the assets
    per viewer — Ads Manager's "select up to 10 media in a Single image or video
    ad", which replaced the ad set's retired Dynamic Creative toggle.

    The feed is added *beside* the ordinary ``object_story_spec``, with
    ``optimization_type: DEGREES_OF_FREEDOM``, and both halves are load-bearing:
    a feed on a page-only story spec is a Dynamic Creative ad, which no ordinary
    ad set accepts (subcode 1885998 — it would need ``is_dynamic_creative`` on the
    ad set, one ad per ad set, and only the goals that toggle supports), while
    DEGREES_OF_FREEDOM without the full story spec is rejected outright ("The link
    field is required", subcode 2061015).

    Whether an account may do that still varies, so a rejection falls back to the
    single-asset creative built from ``title`` / ``body`` / ``media_ref`` and
    reports it through ``on_fallback`` rather than failing the publish.
    """
    # Boosting an existing post: reference it and stop. Meta ignores any
    # object_story_spec alongside object_story_id, and composing one would
    # silently replace the post the user picked.
    #
    # An Instagram post is the same idea from the other platform — the ad IS that
    # post, with the likes and comments it already collected — so it short-circuits
    # here too. It needs the Instagram identity: a Page id alone cannot say which
    # account the post belongs to.
    if object_story_id or source_instagram_media_id:
        boost_body: dict = {"name": name}
        if source_instagram_media_id:
            if not instagram_user_id:
                raise MetaAdsError(
                    "promoting an Instagram post needs the Page's linked Instagram "
                    "account — reconnect Meta and grant Instagram access"
                )
            boost_body["source_instagram_media_id"] = str(source_instagram_media_id)
        else:
            boost_body["object_story_id"] = str(object_story_id)
        if instagram_user_id:
            boost_body["instagram_user_id"] = str(instagram_user_id)
        result = await _request(
            "POST",
            f"{_act(ad_account_id)}/adcreatives",
            access_token,
            json_data=boost_body,
        )
        creative_id = result.get("id")
        if not creative_id:
            raise MetaAdsError("Ad creative creation returned no ID")
        return str(creative_id)

    # An Instant Form ad's button opens the form; a link there is ignored by Meta
    # and misleading in the plan. A Click-to-WhatsApp ad's button opens WhatsApp
    # at the Page's connected number, so it carries an app_destination instead of
    # a link — the link_data.link stays the generic api.whatsapp.com/send that
    # ``_destination_link`` builds.
    if lead_gen_form_id:
        cta_value: dict[str, Any] = {"lead_gen_form_id": str(lead_gen_form_id)}
    elif cta_type == "WHATSAPP_MESSAGE":
        cta_value = {"app_destination": "WHATSAPP"}
    else:
        cta_value = {"link": link_url}
    cta: dict[str, Any] = {"type": cta_type, "value": cta_value}

    story_spec: dict[str, Any]
    if ad_format == "CAROUSEL":
        if not cards:
            raise MetaAdsError("carousel creative requires cards")
        # A video card needs its poster frame resolved before the card is built;
        # image cards already carry their own hash.
        children = [
            _child_attachment(
                c,
                cta,
                picture=(
                    await fetch_video_thumbnail(str(c["video_id"]), access_token)
                    if c.get("video_id") else None
                ),
            )
            for c in cards
        ]
        story_spec = {
            "page_id": page_id,
            "link_data": {
                "link": link_url,
                "message": body[:CREATIVE_BODY_MAX],
                "child_attachments": children,
                # Meta appends its own end card unless told otherwise; the plan
                # decides the card list, so keep it exactly as approved.
                "multi_share_end_card": False,
            },
        }
    elif media_type == "video":
        video_data: dict[str, Any] = {
            "video_id": media_ref,
            "title": title[:CREATIVE_TITLE_MAX],
            "message": body[:CREATIVE_BODY_MAX],
            "call_to_action": cta,
        }
        # Meta will not build a video creative without a poster frame (subcode
        # 1443226). It generates the candidates during transcode, so this asks
        # for one rather than making the user supply it.
        thumbnail = await fetch_video_thumbnail(str(media_ref), access_token)
        if thumbnail:
            video_data["image_url"] = thumbnail
        story_spec = {"page_id": page_id, "video_data": video_data}
    else:
        link_data: dict[str, Any] = {
            "image_hash": media_ref,
            "name": title[:CREATIVE_TITLE_MAX],
            "message": body[:CREATIVE_BODY_MAX],
            "link": link_url,
            "call_to_action": cta,
        }
        if description:
            link_data["description"] = description[:CREATIVE_DESCRIPTION_MAX]
        story_spec = {"page_id": page_id, "link_data": link_data}

    single_body: dict = {"name": name, "object_story_spec": story_spec}
    if url_tags:
        single_body["url_tags"] = url_tags
    if instagram_user_id:
        single_body["instagram_user_id"] = str(instagram_user_id)

    # Variations: same identity, but the copy and media go in an asset feed
    # instead of the story spec. An Instant Form ad is excluded — its button opens
    # a form rather than a link_url, and asset_feed_spec has no place to put the
    # form id.
    bodies_out = [b for b in (bodies or []) if b]
    titles_out = [t for t in (titles or []) if t]
    media_out = [(media_ref, media_type), *(extra_media or [])]
    if (
        ad_format != "CAROUSEL"
        and not lead_gen_form_id
        and max(len(titles_out), len(bodies_out), len(media_out)) > 1
    ):
        # The feed never carries videos. Meta does not store them: every shape was
        # tried against a live ad account (scripts/probe_mixed_feed.py --mode
        # videos) — SINGLE_VIDEO and AUTOMATIC_FORMAT, thumbnail_url and
        # thumbnail_hash and no thumbnail, against a video reporting
        # "video_status": "ready", and in a feed carrying nothing else — and all
        # came back with the videos gone.
        #
        # Nothing is lost by leaving them out: a video ad's video rides
        # ``object_story_spec.video_data`` above, which is what actually runs. The
        # feed is only here to carry the copy variations. Sending the key anyway
        # cost nothing at Meta and everything in trust — the read-back below saw
        # "0 of 1 videos" stored and told the user their extras had not run, on
        # every video ad that had a second headline.
        #
        # ``extra_media`` is images-only (CreativeSpec rejects the rest), so for an
        # image ad every entry here is an image.
        is_video = media_type == "video"
        images = [] if is_video else [{"hash": ref} for ref, _kind in media_out]
        feed: dict[str, Any] = {
            # "An asset feed can have exactly one ad format" (subcode 1885374).
            # One kind per ad means there is only ever one to name.
            "ad_formats": ["SINGLE_VIDEO" if is_video else "SINGLE_IMAGE"],
            "titles": [{"text": t[:CREATIVE_TITLE_MAX]} for t in (titles_out or [title])],
            "bodies": [{"text": b[:CREATIVE_BODY_MAX]} for b in (bodies_out or [body])],
            "call_to_action_types": [cta_type],
            "link_urls": [{"website_url": link_url}],
            # This is the flexible-ad shape, not Dynamic Creative, and the two are
            # not interchangeable. A feed on a page-only object_story_spec is a
            # Dynamic Creative ad, which Meta refuses to put in an ordinary ad set
            # ("Dynamic Creative ads can only be created under Dynamic Creative Ad
            # Sets", subcode 1885998) — so it would need is_dynamic_creative on the
            # ad set, one ad per ad set, and the goals that toggle supports.
            # DEGREES_OF_FREEDOM instead keeps the normal creative below as the ad
            # and treats the feed as the extra options Meta may swap in, which is
            # exactly Ads Manager's "Add another option" / multi-media single ad.
            # It is only legal WITH the full story spec: on its own it fails as
            # "The link field is required" (subcode 2061015).
            "optimization_type": "DEGREES_OF_FREEDOM",
        }
        if images:
            feed["images"] = images
        if description:
            feed["descriptions"] = [{"text": description[:CREATIVE_DESCRIPTION_MAX]}]
        # The full creative, plus the feed. The story spec stays exactly as built
        # above — it is the ad that runs, and the feed only widens what Meta may
        # show in its place.
        feed_body = {**single_body, "asset_feed_spec": feed}
        try:
            result = await _request(
                "POST",
                f"{_act(ad_account_id)}/adcreatives",
                access_token,
                json_data=feed_body,
            )
            creative_id = result.get("id")
            if creative_id:
                dropped = await _feed_assets_dropped(str(creative_id), feed, access_token)
                if dropped:
                    logger.warning(
                        "asset_feed_spec accepted but trimmed for %s: %s | feed=%s",
                        name, dropped, json.dumps(feed, default=str),
                    )
                    if on_fallback:
                        on_fallback(dropped)
                return str(creative_id)
            raise MetaAdsError("Ad creative creation returned no ID")
        except MetaAdsError as exc:
            # The payload, not just the message: which field Meta objected to is
            # the whole diagnosis, and this path only ever shows up in a report
            # ("the extras are missing") long after the run it happened in.
            logger.warning(
                "asset_feed_spec rejected for %s — falling back to single-text: %s "
                "| feed=%s",
                name, exc, json.dumps(feed, default=str),
            )
            if on_fallback:
                on_fallback(str(exc))

    result = await _request(
        "POST",
        f"{_act(ad_account_id)}/adcreatives",
        access_token,
        json_data=single_body,
    )
    creative_id = result.get("id")
    if not creative_id:
        raise MetaAdsError("Ad creative creation returned no ID")
    return str(creative_id)


# ── Instant Forms (leadgen) ───────────────────────────────────────────────────
# Lead forms live on the Page, not the ad account, and need `pages_manage_ads`
# on the token. Both calls translate a permission failure into wording the user
# can act on — the raw Graph error names an OAuth scope, which means nothing to
# an advertiser looking at a campaign form.

_LEAD_FORM_PERMISSION_HINT = (
    "Punk needs permission to manage instant forms on your Facebook Page. "
    "Reconnect your Meta account and grant access to the Page you advertise under."
)

# Reading leads is a separate grant from creating the form (`leads_retrieval` vs
# `pages_manage_ads`), and it also needs a Page role that carries lead access —
# so it fails on its own, with wording that names both halves.
_LEAD_READ_PERMISSION_HINT = (
    "Punk needs permission to read the leads your form collected. Reconnect your "
    "Meta account, and make sure your Page role includes lead access "
    "(Page admin, or Leads Access granted in Business settings)."
)

# "Form Name already exists. Please enter a new one." Instant form names are
# unique per Page, so republishing a reused campaign setup hits this with the
# name the user typed into the draft.
_LEAD_FORM_NAME_TAKEN = 1892019


def is_permission_error(exc: MetaAdsError | None) -> bool:
    """True when Meta refused the call for access, not for a transient reason.

    200/10 are the permission codes; 3 is "this app does not have the capability
    for this endpoint" (app access level, not the user's token); 190 is an
    expired/invalid token. None of the four clear on retry, which is what the
    publish path needs to know before re-offering the Publish button.
    """
    return getattr(exc, "code", None) in (3, 10, 190, 200)


# ── Reading an existing campaign back ─────────────────────────────────────────
# For "start from a previous campaign": the advertiser's own account is the
# template library. Only the fields ``meta_spec.importer`` reuses are requested —
# targeting, audiences and budgets are deliberately NOT read, because the new
# campaign's audience is the whole point of the run.

_CAMPAIGN_LIST_FIELDS = "id,name,objective,effective_status,created_time"
# ``status`` is not read by the importer either — a Graph GET returns ONLY the
# fields it is asked for, so without it every read-back status is None and any
# "is this really paused?" check silently passes on nothing.
_TEMPLATE_CAMPAIGN_FIELDS = (
    "id,name,status,objective,bid_strategy,special_ad_categories,"
    "special_ad_category_country"
)
_TEMPLATE_ADSET_FIELDS = (
    "id,name,status,destination_type,optimization_goal,billing_event,bid_strategy,"
    "bid_amount,bid_constraints,attribution_spec,frequency_control_specs"
)
_TEMPLATE_AD_FIELDS = (
    # asset_feed_spec is not read by the importer — it is here so a caller can
    # tell a creative that really carries the copy and media variations from one
    # that quietly fell back to a single asset. Nothing else can: the fallback in
    # ``create_ad_creative`` returns an ordinary creative id either way.
    # ``effective_object_story_id`` is the one field that answers "which post does
    # this ad run?" for BOTH an organic post and an inline-created unpublished one —
    # ``object_story_id`` is null on the latter. It is what makes "copy an existing
    # ad" possible: the new ad promotes the same post, keeping the reactions and
    # comments the original collected.
    "id,name,status,creative{object_story_spec,object_story_id,"
    "effective_object_story_id,source_instagram_media_id,thumbnail_url,"
    "url_tags,asset_feed_spec}"
)

# Campaigns in these states are gone or archived — offering them as a starting
# point would list clutter the advertiser has already dismissed.
_HIDDEN_CAMPAIGN_STATES = frozenset({"DELETED", "ARCHIVED"})


async def list_account_campaigns(
    ad_account_id: str, access_token: str, *, limit: int = 25
) -> list[dict]:
    """The account's recent campaigns, for the intake form's "start from" select.

    Returns ``[{id, name, objective, created_time}]``. Empty on any failure —
    the intake form simply omits the field, which is the same as the behaviour
    before this feature existed. A lookup problem must never block someone from
    setting a campaign up.
    """
    # Query string, not a JSON body. A GET body is not where Graph reads its
    # parameters from: measured against act_116187595198313, the body form never
    # returned ``effective_status`` at all — so the DELETED/ARCHIVED filter below
    # compared None and kept everything, and the picker offered 69 deleted test
    # campaigns as templates. It also returned a different result set entirely
    # (82 rows vs 25 for the same limit).
    query = f"fields={_CAMPAIGN_LIST_FIELDS}&limit={int(limit)}"
    try:
        result = await _request(
            "GET", f"{_act(ad_account_id)}/campaigns?{query}", access_token,
        )
    except MetaAdsError as exc:
        logger.warning("list_account_campaigns(%s): failed — %s", ad_account_id, exc)
        return []

    return [
        {
            "id": str(c["id"]),
            "name": c.get("name") or str(c["id"]),
            "objective": c.get("objective"),
            "created_time": c.get("created_time"),
        }
        for c in (result.get("data") or [])
        if c.get("id") and c.get("effective_status") not in _HIDDEN_CAMPAIGN_STATES
    ]


async def list_account_ads(
    ad_account_id: str, access_token: str, *, limit: int = 25
) -> list[dict]:
    """The posts behind the account's recent ads, for the "reuse a post from an
    older ad" picker.

    Answers the same question as ``list_page_objects`` from the other side: that
    one lists what the Page published, this one lists what the account has
    already advertised — including the inline unpublished posts that never appear
    on the Page at all. Promoting the same post again keeps the reactions and
    comments the original collected instead of starting at zero.

    Returns the picker's shape — ``[{id, label, image, created_time, permalink,
    source}]`` — where ``id`` is the POST, not the ad: that is what the new
    creative promotes. ``source`` says which creative field it lands on, since an
    Instagram-sourced ad names its media instead of a story id.

    Ads whose copy was composed in the editor carry no post to reuse and are
    skipped, as are several ads running the SAME post — the picker offers posts,
    so one entry each. Empty on any failure, like every sibling list helper: a
    picker with no candidates reads as "nothing to reuse", an exception takes the
    editor down with it.
    """
    # Query string, not a JSON body — see list_account_campaigns above for what a
    # GET body silently drops.
    query = f"fields={_TEMPLATE_AD_FIELDS},created_time,effective_status&limit={int(limit)}"
    try:
        result = await _request("GET", f"{_act(ad_account_id)}/ads?{query}", access_token)
    except MetaAdsError as exc:
        logger.warning("list_account_ads(%s): failed — %s", ad_account_id, exc)
        return []

    out: list[dict] = []
    seen: set[str] = set()
    for ad in result.get("data") or []:
        if ad.get("effective_status") in _HIDDEN_CAMPAIGN_STATES:
            continue
        creative = ad.get("creative") or {}
        ig_id = str(creative.get("source_instagram_media_id") or "")
        # effective_object_story_id covers the unpublished inline post that
        # object_story_id leaves null — see _TEMPLATE_AD_FIELDS.
        post_id = str(
            creative.get("effective_object_story_id")
            or creative.get("object_story_id")
            or ""
        )
        chosen = ig_id or post_id
        if not chosen or chosen in seen:
            continue
        seen.add(chosen)
        out.append({
            "id": chosen,
            "label": (ad.get("name") or chosen)[:120],
            "image": creative.get("thumbnail_url"),
            "created_time": ad.get("created_time"),
            "permalink": None,
            "source": "instagram" if ig_id else "facebook",
        })
    return out


async def fetch_ad_account_timezone(ad_account_id: str, access_token: str) -> str:
    """The ad account's IANA timezone name, or "".

    Meta reads ad-set dayparting (``adset_schedule`` start/end minutes) in the
    **ad account's** timezone, not the viewer's. The editor collects those
    minutes from a browser clock, so without this the field silently means
    something else for anyone not sitting in the account's zone. Shipped to the
    editor so the dayparting control can say which clock it is on.

    Empty on any failure, like the other read helpers — an unlabelled control is
    better than no plan editor.
    """
    try:
        result = await _request(
            "GET", _act(ad_account_id), access_token, json_data={"fields": "timezone_name"},
        )
    except MetaAdsError as exc:
        logger.warning("fetch_ad_account_timezone(%s): failed — %s", ad_account_id, exc)
        return ""
    return str(result.get("timezone_name") or "")


async def fetch_ad_account_currency(ad_account_id: str, access_token: str) -> dict[str, Any]:
    """The ad account's currency and Meta's own minimum daily budget for it.

    Every budget Punk sends is in the **ad account's** currency, in minor units —
    not USD cents. Meta's floor is per-currency (subcode 1885272, e.g. "Your ad set
    budget must be more than BDT120.00"), so a USD-derived floor publishes fine on
    a USD account and is rejected on every BDT or CAD one. ``min_daily_budget``
    comes straight from Meta in those same minor units, which makes it the only
    floor worth trusting.

    Returns ``{}`` on any failure, like the other read helpers — callers fall back
    to the static floor and let Meta's preflight be the judge.
    """
    try:
        result = await _request(
            "GET", _act(ad_account_id), access_token,
            # Only fields the ad account actually has. Asking for one it does not
            # (``currency_offset`` is not an AdAccount field in v25) fails the
            # WHOLE read with code 100, and this degrades to {} — which silently
            # put every account back on the USD floor.
            json_data={"fields": "currency,min_daily_budget"},
        )
    except MetaAdsError as exc:
        logger.warning("fetch_ad_account_currency(%s): failed — %s", ad_account_id, exc)
        return {}

    out: dict[str, Any] = {}
    if result.get("currency"):
        out["currency"] = str(result["currency"])
    # Meta returns this as a string often enough to be worth coercing.
    for key in ("min_daily_budget",):
        raw = result.get(key)
        if raw not in (None, ""):
            try:
                out[key] = int(raw)
            except (TypeError, ValueError):
                pass
    return out


# Ad account states that stop a write. Meta's ``account_status`` enum:
#   1 ACTIVE  2 DISABLED  3 UNSETTLED  7 PENDING_RISK_REVIEW
#   8 PENDING_SETTLEMENT  9 IN_GRACE_PERIOD  100 PENDING_CLOSURE  101 CLOSED
# 9 (grace period) is deliberately absent: the account still delivers.
_DEAD_ACCOUNT_STATUSES: frozenset[int] = frozenset({2, 3, 8, 100, 101})
# The subset that is a money problem rather than a standing problem — different
# screen, different fix, so they must not share one message.
_UNPAID_ACCOUNT_STATUSES: frozenset[int] = frozenset({3, 8})


# Without these the token cannot publish at all, so a short grant is a block, not a
# nudge. The rest of REQUIRED_SCOPES cost a feature (leads, Instagram identity).
_PUBLISH_CRITICAL_SCOPES = frozenset({"ads_management", "pages_manage_ads"})


async def _grant_blockers(access_token: str) -> list:
    """A card for every permission the token was never granted, or ``[]``.

    The login configuration in the App Dashboard — not the ``scope=`` we send —
    decides what a connection carries, so a misconfigured (or rebuilt) app hands
    every advertiser a short token, and the first they hear of it is a ``(#200)``
    mid-publish. ``debug_token`` says now.

    ``[]`` when the read fails: an empty scope list means "could not ask", never
    "granted nothing" — the same unknown-is-not-an-accusation rule as
    ``ads.service.missing_scopes``.
    """
    from dataclasses import replace

    from app.modules.ads.service import REQUIRED_SCOPES  # cycle: it imports this module
    from app.services import meta_remediation

    granted = set((await fetch_token_info(access_token)).get("scopes") or [])
    if not granted:
        return []
    missing = [s for s in REQUIRED_SCOPES if s not in granted]
    if not missing:
        return []
    card = meta_remediation.CATALOG["meta_scopes_outdated"]
    blocking = bool(_PUBLISH_CRITICAL_SCOPES & set(missing))
    return [replace(
        card,
        cause=card.cause.format(missing=", ".join(missing)),
        severity="blocks" if blocking else card.severity,
        effect=(
            "Meta will refuse to publish until this permission is granted."
            if blocking else card.effect
        ),
    )]


async def ad_account_blockers(ad_account_id: str, access_token: str) -> list:
    """Everything about this ad account that will stop a publish, before we start.

    Returns ``list[meta_remediation.Remediation]`` — each one a thing the user has
    to go do on a Meta screen, because none of them can be done through the API.

    All of it comes off ONE read. Meta only says no to most of this at write time,
    after the whole campaign has been built (a customer-list Custom Audience on an
    account outside a Business fails with subcode 1870050 at publish); asking now
    costs a single GET on a call this module was already making for the business
    field alone.

    Returns ``[]`` on any lookup failure — an unknown answer must never block a
    publish that might well have succeeded, which is the same degradation every
    other read helper here uses.
    """
    from app.services import meta_remediation

    grant = await _grant_blockers(access_token)
    result: dict = {}
    knows_funding = False
    knows_spend = False
    knows_roles = False
    # Same shape as _PAGE_FIELD_LADDER, for the same reason and the same lesson
    # fetch_ad_account_currency learned the hard way: asking for one field the
    # account will not answer fails the WHOLE read, and losing the business check
    # (which works today) to learn about billing would be a bad trade.
    for attempt in (
        # ``user_tasks`` is the caller's role on THIS ad account (plain strings —
        # measured: ["DRAFT", "ANALYZE", "ADVERTISE", "MANAGE"]). Its own top rung so
        # a token that refuses it still keeps the spend fields on the next one.
        "account_status,disable_reason,funding_source_details,spend_cap,amount_spent,"
        "user_tasks,business{id,name}",
        "account_status,disable_reason,funding_source_details,spend_cap,amount_spent,"
        "business{id,name}",
        "account_status,disable_reason,funding_source_details,business{id,name}",
        "account_status,business{id,name}",
        "business{id,name}",
    ):
        try:
            result = await _request(
                "GET", _act(ad_account_id), access_token,
                json_data={"fields": attempt}, retries=1,
            )
        except MetaAdsError as exc:
            logger.warning(
                "ad_account_blockers(%s, fields=%s): failed — %s", ad_account_id, attempt, exc,
            )
            continue
        knows_funding = "funding_source_details" in attempt
        knows_spend = "spend_cap" in attempt
        knows_roles = "user_tasks" in attempt
        break
    else:
        return grant

    found = list(grant)
    status = int(result.get("account_status") or 0)
    if status in _UNPAID_ACCOUNT_STATUSES:
        found.append(meta_remediation.CATALOG["ad_account_no_payment"])
    elif status in _DEAD_ACCOUNT_STATUSES:
        found.append(meta_remediation.CATALOG["ad_account_disabled"])
    elif knows_funding and not result.get("funding_source_details"):
        # An ACTIVE account with nothing to bill. Meta lets the objects be created
        # and then refuses to deliver. Only claimed when the rung that answered
        # actually carried the field — an unreadable field is not evidence of a
        # missing card.
        found.append(meta_remediation.CATALOG["ad_account_no_payment"])

    if not (result.get("business") or {}).get("id"):
        found.append(meta_remediation.CATALOG["audience_needs_business"])

    # Creating ads needs ADVERTISE (an admin also carries MANAGE). Without either,
    # every write is a (#200)/(#10) at publish. Only claimed from a NON-EMPTY list off
    # a rung that asked: an empty answer is "could not tell", never "no role" — an
    # account the token can read at all is one it has some role on.
    if knows_roles:
        tasks = {str(t).upper() for t in (result.get("user_tasks") or [])}
        if tasks and not tasks & {"ADVERTISE", "MANAGE"}:
            found.append(meta_remediation.CATALOG["ad_account_role_missing"])

    # A reached cap leaves ``account_status`` untouched — which is why the checks
    # above miss it — and Meta then simply does not deliver. Meta reports
    # ``spend_cap`` "0" for NO cap, not a cap of zero; both are minor-unit strings in
    # the account's currency, so the comparison needs no currency. Only claimed when
    # the rung that answered carried the field.
    if knows_spend:
        try:
            cap, spent = int(result.get("spend_cap") or 0), int(result.get("amount_spent") or 0)
        except (TypeError, ValueError):
            cap = spent = 0
        if cap > 0 and spent >= cap:
            from dataclasses import replace

            found.append(replace(
                meta_remediation.CATALOG["ad_account_spend_limit"],
                # The catalog line says "already built is PAUSED" — written for a
                # refusal at publish. Here nothing has been built yet.
                effect="Nothing has been built yet — a campaign published now would not deliver.",
            ))

    logger.info(
        "ad_account_blockers(%s): status=%s disable_reason=%s spend=%s/%s blockers=%s",
        ad_account_id, status or "?", result.get("disable_reason", "?"),
        result.get("amount_spent", "?"), result.get("spend_cap", "?"),
        [r.key for r in found] or "none",
    )
    return found


async def fetch_custom_audience_tos(ad_account_id: str, access_token: str) -> bool | None:
    """Whether this ad account has accepted the Custom Audience Terms.

    ``True`` accepted, ``False`` provably not, ``None`` could not tell — and ``None``
    is the answer to anything unexpected, because "not accepted" is an accusation.

    Its own read, not a rung of ``ad_account_blockers``: one refused field there
    would drop every other check with it. Measured live 2026-09-22: an accepted
    account answers ``{"tos_accepted": {"custom_audience_tos": 1}}``. The
    not-accepted shape has not been seen, so only a present dict whose flag is falsy
    counts as ``False``; an absent field, a list or a null stays ``None`` and the
    caller keeps asking the user to confirm.
    """
    if not ad_account_id:
        return None
    try:
        result = await _request(
            "GET", _act(ad_account_id), access_token,
            json_data={"fields": "tos_accepted"}, retries=1,
        )
    except MetaAdsError as exc:
        logger.warning("fetch_custom_audience_tos(%s): failed — %s", ad_account_id, exc)
        return None
    tos = result.get("tos_accepted")
    if not isinstance(tos, dict):
        return None
    return bool(tos.get("custom_audience_tos"))


async def fetch_ad_review(campaign_id: str, access_token: str) -> list[dict]:
    """``[{id, name, effective_status, ad_review_feedback}]`` for a campaign's ads.

    Meta reviews every new ad before it delivers; this is the only place Punk can see
    the outcome. ``[]`` on failure — an unreadable status must never read as a problem
    (or as an all-clear the caller then acts on), so callers treat empty as "nothing
    to say".
    """
    try:
        result = await _request(
            "GET", f"{campaign_id}/ads", access_token,
            json_data={"fields": "id,name,effective_status,ad_review_feedback", "limit": 100},
            retries=1,
        )
    except MetaAdsError as exc:
        logger.warning("fetch_ad_review(%s): failed — %s", campaign_id, exc)
        return []
    return list(result.get("data") or [])


async def fetch_campaign_tree(campaign_id: str, access_token: str) -> dict:
    """One campaign with its ad sets and ads, as ``{campaign, adsets: [...]}``.

    Each ad set carries its ``ads`` inline, mirroring the shape ``CampaignSpec``
    uses, so ``meta_spec.importer`` reads one nested structure rather than three
    flat lists it has to re-associate.

    Raises ``MetaAdsError`` rather than degrading: the user explicitly picked
    this campaign, so failing to read it needs to be said out loud, not silently
    turned into a blank template.
    """
    campaign = await _request(
        "GET", campaign_id, access_token,
        json_data={"fields": _TEMPLATE_CAMPAIGN_FIELDS},
    )
    adsets_result = await _request(
        "GET", f"{campaign_id}/adsets", access_token,
        json_data={"fields": _TEMPLATE_ADSET_FIELDS, "limit": 50},
    )

    adsets: list[dict] = []
    for adset in adsets_result.get("data") or []:
        if not adset.get("id"):
            continue
        ads_result = await _request(
            "GET", f"{adset['id']}/ads", access_token,
            json_data={"fields": _TEMPLATE_AD_FIELDS, "limit": 50},
        )
        adsets.append({**adset, "ads": ads_result.get("data") or []})

    return {"campaign": campaign, "adsets": adsets}


# Which Graph edge holds each kind of boostable object, and what to read off it.
# Same shape for all three so the picker renders one gallery.
_PAGE_OBJECT_EDGES: dict[str, tuple[str, str]] = {
    "post": ("published_posts", "id,message,full_picture,created_time,permalink_url"),
    "video": ("videos", "id,description,picture,created_time,permalink_url"),
    "event": ("events", "id,name,description,cover,start_time"),
}


async def list_instagram_media(
    page_id: str, access_token: str, *, limit: int = 25, page_token: str = ""
) -> list[dict]:
    """The Page's linked Instagram account's recent posts, or ``[]``.

    Same shape as ``list_page_objects`` so the editor's picker renders one gallery
    with an Instagram tab rather than a second component. Keyed off the PAGE id,
    not the Instagram id, because that is what every other picker call already has
    and the link between them is a Page field.

    Only IMAGE, VIDEO and CAROUSEL_ALBUM media can be promoted; Stories and
    Reels-in-progress cannot, so anything else is dropped rather than offered and
    then rejected at publish.
    """
    token = page_token or await fetch_page_token(page_id, access_token) or access_token
    try:
        linked = await _request(
            "GET", f"{page_id}?fields=instagram_business_account{{id,username}}",
            token, retries=1,
        )
    except MetaAdsError as exc:
        logger.warning("list_instagram_media(%s): no IG account readable — %s", page_id, exc)
        return []
    ig_id = str((linked.get("instagram_business_account") or {}).get("id") or "")
    if not ig_id:
        return []

    try:
        result = await _request(
            "GET",
            f"{ig_id}/media",
            token,
            json_data={
                "fields": "id,caption,media_url,thumbnail_url,permalink,media_type,timestamp",
                "limit": limit,
            },
        )
    except MetaAdsError as exc:
        logger.warning("list_instagram_media(%s): failed — %s", ig_id, exc)
        return []

    promotable = {"IMAGE", "VIDEO", "CAROUSEL_ALBUM"}
    out: list[dict] = []
    for row in result.get("data") or []:
        if not row.get("id") or str(row.get("media_type") or "") not in promotable:
            continue
        out.append({
            "id": str(row["id"]),
            "label": (row.get("caption") or "")[:120],
            # A video's media_url is the video file; the thumbnail is what a picker
            # can actually show.
            "image": row.get("thumbnail_url") or row.get("media_url"),
            "created_time": row.get("timestamp"),
            "permalink": row.get("permalink"),
        })
    return out


async def list_page_objects(
    page_id: str, access_token: str, *, kind: str = "post", limit: int = 25,
    page_token: str = "",
) -> list[dict]:
    """The Page's recent posts / videos / events, for the boost-destination picker.

    Engagement's "On your post / video / event" conversion locations promote
    something that already exists on the Page — the ad IS that post, with the
    reactions and comments it has already collected. Publishing one needs its
    ``object_story_id``, so the user has to choose it.

    Returns ``[{id, label, image, created_time, permalink}]``. Empty on any
    failure, like ``list_lead_forms`` and ``fetch_ad_pixels``: a picker with no
    candidates is a visible "nothing to boost", while an exception here would
    take down the whole plan form.

    Note ``published_posts`` rather than ``feed``: ``feed`` includes visitor
    posts, which cannot be boosted.

    All three edges are Page-owned, so this reads with the Page token — see
    ``list_page_tokens``.
    """
    if kind == "instagram":
        # Different owner (the linked IG account), different edge, different field
        # names — but the same answer shape, so the picker does not care.
        return await list_instagram_media(
            page_id, access_token, limit=limit, page_token=page_token,
        )
    edge, fields = _PAGE_OBJECT_EDGES.get(kind, _PAGE_OBJECT_EDGES["post"])
    token = page_token or await fetch_page_token(page_id, access_token) or access_token
    try:
        result = await _request(
            "GET",
            f"{page_id}/{edge}",
            token,
            json_data={"fields": fields, "limit": limit},
        )
    except MetaAdsError as exc:
        logger.warning("list_page_objects(%s, %s): failed — %s", page_id, kind, exc)
        return []

    out: list[dict] = []
    for row in result.get("data") or []:
        if not row.get("id"):
            continue
        # An event's cover is nested; posts and videos carry a flat image field.
        image = (
            row.get("full_picture")
            or row.get("picture")
            or ((row.get("cover") or {}).get("source") if isinstance(row.get("cover"), dict) else None)
        )
        out.append({
            "id": str(row["id"]),
            # Events have a name; posts and videos only have their text.
            "label": (row.get("name") or row.get("message") or row.get("description") or "")[:120],
            "image": image,
            "created_time": row.get("start_time") or row.get("created_time"),
            "permalink": row.get("permalink_url"),
        })
    return out


async def fetch_page_website(page_id: str, access_token: str) -> str:
    """The website the advertiser already told Meta about, or "".

    The intake form does not ask for a URL — three questions is the whole point of
    it — but the website scrape behind ``enrich_website`` is worth keeping, and a
    Page that runs ads almost always has this field filled in. Empty on any
    failure: an absent website is a normal outcome, not an error.
    """
    try:
        result = await _request(
            "GET", page_id, access_token, json_data={"fields": "website"},
        )
    except MetaAdsError as exc:
        logger.warning("fetch_page_website(%s): failed — %s", page_id, exc)
        return ""
    return str(result.get("website") or "").strip()


# The `me/accounts` field sets, most informative first. Each rung drops whatever
# the rung above it might not be allowed to read, because Graph fails the WHOLE
# call on one unreadable field — losing the Page list over an optional extra is
# the outcome to avoid.
#
# Instagram and WhatsApp are gated by DIFFERENT scopes, so the ladder drops them
# separately: rung 4 keeps WhatsApp for a token that has it but lacks
# instagram_basic, which is a real token shape (see the fallback test) and the
# whole point of reading WhatsApp at all.
#
# The WhatsApp fields come in two spellings on purpose: Meta exposes the Page's
# linked number as `whatsapp_number` and the business account behind it as
# `connected_whatsapp_business_account`, and which one a token may read depends
# on its scopes. Either answers the only question we ask — is there a number for
# a Click-to-WhatsApp ad to dial.
_WHATSAPP_FIELDS = "whatsapp_number,connected_whatsapp_business_account{id}"
_IG_FIELDS = "instagram_business_account{id,username}"
_PAGE_FIELD_LADDER: tuple[str, ...] = (
    # ``is_published`` and ``tasks`` (the caller's roles on the Page) exist on the
    # ``me/accounts`` edge only — measured 2026-09-22: ``tasks`` is "nonexisting" on
    # the Page node itself. Their own top rung so a token that refuses them still
    # gets every rung below unchanged.
    f"id,name,is_published,tasks,{_IG_FIELDS},{_WHATSAPP_FIELDS}",
    f"id,name,{_IG_FIELDS},{_WHATSAPP_FIELDS}",
    f"id,name,{_IG_FIELDS},whatsapp_number",
    f"id,name,{_IG_FIELDS}",
    f"id,name,{_WHATSAPP_FIELDS}",
    "id,name",
)


async def list_meta_pages(access_token: str) -> list[dict]:
    """``[{id, name, instagram, whatsapp?}]`` for every Page this token can
    advertise under.

    ``instagram`` is ``{id, username}`` for the Page's linked Instagram account, or
    None. Both identities come from one call because they are one decision: the
    Page you publish under determines the Instagram account the ad runs as.

    ``whatsapp`` is ``{number}`` when the Page has a WhatsApp Business account
    linked and None when it provably does not. **It is absent when we could not
    read it at all** — a token without the scope answers the same as a Page with
    no number, and those must not be confused: Click-to-WhatsApp is the one
    conversion location Meta refuses outright without a number
    (``preflight_adset``, nothing created), so the editor blocks on False and
    stays out of the way on absent.

    ``is_published`` and ``can_advertise`` (an ADVERTISE or MANAGE role on the Page)
    follow the same contract: a bool when read, absent when not.

    The IG edge needs ``instagram_basic``, which tokens minted before that scope
    was requested do not carry. Rather than lose the whole Page list to a
    permission error, walk ``_PAGE_FIELD_LADDER`` down — a Page list with no
    Instagram beats no Page list at all. Empty on total failure, same degradation
    as ``list_lead_forms``.
    """
    for rung, attempt in enumerate(_PAGE_FIELD_LADDER):
        try:
            result = await _request(
                "GET", "me/accounts", access_token, json_data={"fields": attempt},
            )
        except MetaAdsError as exc:
            logger.warning("list_meta_pages(fields=%s): failed — %s", attempt, exc)
            continue
        # Logged at info: which rung a real token clears is the only evidence we
        # get for whether the WhatsApp fields are readable in practice.
        if rung:
            logger.info("list_meta_pages: fell back to rung %d (%s)", rung, attempt)
        # Read off the rung that actually answered rather than a rung index, so
        # reordering the ladder cannot silently turn "unknown" into "no number".
        knows_whatsapp = "whatsapp" in attempt
        knows_published = "is_published" in attempt
        knows_tasks = "tasks" in attempt
        out: list[dict] = []
        for row in result.get("data") or []:
            if not row.get("id"):
                continue
            ig = row.get("instagram_business_account") or {}
            page = {
                "id": str(row["id"]),
                "name": row.get("name") or "",
                "instagram": (
                    {"id": str(ig["id"]), "username": ig.get("username") or ""}
                    if ig.get("id") else None
                ),
            }
            if knows_whatsapp:
                number = str(row.get("whatsapp_number") or "").strip()
                waba = (row.get("connected_whatsapp_business_account") or {}).get("id")
                # A linked business account with no number still dials: the number
                # lives on the WABA, and Meta resolves it at delivery.
                page["whatsapp"] = {"number": number} if (number or waba) else None
            # Same three states as ``whatsapp``: the key is ABSENT when the rung that
            # answered never asked, and absent must never read as "unpublished" or
            # "no role". ``can_advertise`` is derived rather than passing ``tasks``
            # through — this dict is streamed to the browser and the raw list carries
            # nothing the only question asked needs.
            # ...and absent from the ROW too: asking is not the same as being told, and
            # ``bool(None)`` would turn a missing key into an accusation.
            if knows_published and "is_published" in row:
                page["is_published"] = bool(row["is_published"])
            if knows_tasks and "tasks" in row:
                page["can_advertise"] = bool(
                    {str(t).upper() for t in (row.get("tasks") or [])} & {"ADVERTISE", "MANAGE"}
                )
            out.append(page)
        return out
    return []


async def list_page_tokens(access_token: str) -> dict[str, str]:
    """``{page_id: page_access_token}``, traded from the user token.

    Anything owned by the Page rather than the ad account rejects a user token,
    each edge in its own way: ``leadgen_forms`` answers "(#190) This method must
    be called with a Page Access Token", ``published_posts`` answers "(#210) A
    page access token is required", and ``videos`` — worst of the three — answers
    200 OK with an empty ``data`` array, which reads as "this Page has no videos"
    all the way to the picker. So every Page-owned read goes through here.

    Empty dict on failure: callers fall back to the user token and degrade to the
    empty list they already returned, rather than taking the editor down.

    These must never reach the browser. A Page token acts AS the Page — posting,
    messaging, deleting — for as long as it lives, so it stays server-side and
    out of anything serialized into the plan-editor catalog.
    """
    try:
        result = await _request(
            "GET", "me/accounts", access_token,
            json_data={"fields": "id,access_token", "limit": 100},
        )
        pages = {
            str(p["id"]): str(p["access_token"])
            for p in (result.get("data") or [])
            if p.get("id") and p.get("access_token")
        }
        if pages:
            return pages
    except MetaAdsError as exc:
        logger.warning("list_page_tokens: me/accounts failed — %s", exc)

    # Unverified whether a Business Integration System User token's Page grants
    # show up on /me/accounts at all — this is the fallback for "empty", tried
    # only when the call above returned nothing. granular_scopes.target_ids is
    # the authoritative list of Pages this token was actually granted, and a
    # Page's own access_token field is readable directly once the token holds
    # one of the pages_* permissions on it.
    info = await fetch_token_info(access_token)
    page_ids: set[str] = set()
    for entry in info.get("granular_scopes") or []:
        if entry.get("scope") in ("pages_show_list", "pages_manage_ads", "pages_manage_metadata"):
            page_ids.update(str(t) for t in (entry.get("target_ids") or []))
    if not page_ids:
        return {}

    out: dict[str, str] = {}
    for page_id in page_ids:
        try:
            row = await _request(
                "GET", page_id, access_token, json_data={"fields": "access_token"}, retries=1,
            )
        except MetaAdsError as exc:
            logger.warning("list_page_tokens: fallback read for %s failed — %s", page_id, exc)
            continue
        token = row.get("access_token")
        if token:
            out[page_id] = str(token)
    return out


async def fetch_page_token(page_id: str, access_token: str) -> str:
    """This one Page's token, or "". See ``list_page_tokens``.

    Meta has no per-Page token endpoint — ``me/accounts`` is the only way to get
    one — so this is that call plus a lookup, for callers that hold a single
    Page id (the on-demand ``/ads/page-objects`` route).
    """
    return (await list_page_tokens(access_token)).get(str(page_id), "")


async def list_lead_forms(
    page_id: str, access_token: str, *, page_token: str = ""
) -> list[dict]:
    """``[{id, name, status}]`` for the Page's instant forms.

    Reads with the **Page** token — see ``list_page_tokens``. Pass ``page_token``
    when the caller already traded for one (the builder resolves every Page in a
    single ``me/accounts`` call); otherwise this trades for its own.

    Empty list on any failure — the editor then offers "create one for me"
    instead of breaking, same degradation as ``fetch_ad_pixels``.
    """
    token = page_token or await fetch_page_token(page_id, access_token) or access_token
    try:
        result = await _request(
            "GET",
            f"{page_id}/leadgen_forms",
            token,
            json_data={"fields": "id,name,status"},
        )
    except MetaAdsError as exc:
        logger.warning("list_lead_forms(%s): failed — %s", page_id, exc)
        return []
    return [
        {"id": str(f["id"]), "name": f.get("name"), "status": f.get("status")}
        for f in (result.get("data") or [])
        if f.get("id")
    ]


async def fetch_form_leads(
    form_id: str, access_token: str, *, limit: int = 100, page_token: str = ""
) -> list[dict]:
    """The leads submitted to one instant form.

    Without this, a lead campaign delivers into Meta and the user has to leave
    Punk to do anything with the result — which is most of the point of running
    one. Returns ``[{id, created_time, fields: {question: answer}}]``.

    Meta returns ``field_data`` as ``[{name, values: [...]}]``; it is flattened
    here because every standard question has exactly one answer, and a dict is
    what a table or an export actually wants.

    Empty on transient failure, like the other read helpers — a leads panel that
    shows nothing beats one that takes the page down. Permission failures are the
    exception and are raised: "no leads yet" and "you never granted
    leads_retrieval" look identical to the user, and the second one never fixes
    itself, so swallowing it hides a campaign's entire output behind an empty
    table.

    ``page_token`` is the form's Page token when the caller has traded for one —
    Meta's lead-retrieval docs read leads with the Page's token, the way
    ``leadgen_forms`` itself demands one. Falls back to the user token, so a caller
    without a Page id behaves as before.
    """
    try:
        result = await _request(
            "GET",
            f"{form_id}/leads",
            page_token or access_token,
            json_data={"fields": "id,created_time,field_data", "limit": limit},
        )
    except MetaAdsError as exc:
        if is_permission_error(exc):
            raise MetaAdsError(
                _LEAD_READ_PERMISSION_HINT, code=exc.code,
                user_msg=_LEAD_READ_PERMISSION_HINT,
            ) from exc
        logger.warning("fetch_form_leads(%s): failed — %s", form_id, exc)
        return []

    leads: list[dict] = []
    for row in result.get("data") or []:
        fields = {
            f.get("name"): (f.get("values") or [None])[0]
            for f in (row.get("field_data") or [])
            if f.get("name")
        }
        leads.append({
            "id": str(row.get("id")),
            "created_time": row.get("created_time"),
            "fields": fields,
        })
    return leads


def _lead_form_question(q: str | dict) -> dict[str, Any]:
    """One entry of the Graph API's ``questions`` array.

    A plain string is one of Meta's prefill types ("EMAIL"), which the profile
    answers for the user. A dict is a question the advertiser wrote themselves:
    ``{"type": "CUSTOM", "key", "label", "options": [...]}``. Only the keys Meta
    accepts are forwarded — an unknown key rejects the whole form.

    ``options`` may be plain strings (what ``LeadFormSpec`` carries) or Meta's
    own ``{"key", "value"}`` pairs; both end up as pairs, since Meta requires the
    key and generating it from the answer text is what a user means anyway.
    """
    if isinstance(q, str):
        return {"type": q}
    out: dict[str, Any] = {"type": q.get("type") or "CUSTOM"}
    for key in ("key", "label"):
        if q.get(key):
            out[key] = str(q[key])
    options: list[dict[str, str]] = []
    for opt in q.get("options") or []:
        value = str(opt if isinstance(opt, str) else opt.get("value") or "").strip()
        if not value:
            continue
        key = str(opt.get("key") or value) if isinstance(opt, dict) else value
        options.append({"key": key, "value": value})
    if options:
        out["options"] = options
    return out


async def create_lead_form(
    page_id: str,
    name: str,
    questions: list[str] | list[dict] | list[str | dict],
    privacy_policy_url: str,
    access_token: str,
    *,
    context_headline: str | None = None,
    context_body: list[str] | None = None,
    follow_up_url: str | None = None,
    higher_intent: bool = False,
    page_token: str = "",
) -> str:
    """Create an instant form on the Page and return its id.

    Meta requires a privacy policy URL on every lead form — it is shown to the
    person filling it in, and form creation is rejected without one.

    Writes with the **Page** token, like ``list_lead_forms`` reads with it:
    ``leadgen_forms`` answers "(#190) This method must be called with a Page Access
    Token" to a user token. Pass ``page_token`` when the caller already traded for
    one; otherwise this trades for its own, and falls back to the user token when
    the trade comes back empty.

    ``questions`` mixes Meta's prefill types (plain strings) with custom
    questions the advertiser wrote (dicts) — see ``_lead_form_question``.

    ``higher_intent`` adds Meta's review step before submission: fewer leads,
    better ones. It is the "more volume vs higher intent" choice Ads Manager
    offers and we did not.

    ``follow_up_url`` is where the person goes *after* submitting. It used to be
    set to the privacy policy URL for want of anything better, which sent every
    new lead to a legal page instead of the business.
    """
    payload: dict[str, Any] = {
        "name": name[:255],
        "questions": [_lead_form_question(q) for q in questions],
        "privacy_policy": {"url": privacy_policy_url, "link_text": "Privacy Policy"},
        "follow_up_action_url": follow_up_url or privacy_policy_url,
        # Organic leads (someone finding the form outside the ad) arrive without
        # the campaign attribution the user is paying to measure.
        "block_display_for_non_targeted_viewer": True,
    }
    if higher_intent:
        payload["is_optimized_for_quality"] = True
    # The intro card shown before the questions. `content` is the bullet list
    # under the headline — a form that only says "Continue" converts worse than
    # one that says what the person is signing up for.
    #
    # A LIST_STYLE card without content is rejected outright: "(#100) Context
    # card content is not provided". The card used to be built from the headline
    # alone, and the generated form always has a headline (the ad's own title)
    # and no body, so every auto-generated instant form failed. Content is what
    # decides whether the card exists at all.
    card_body = [str(line).strip() for line in (context_body or []) if str(line).strip()]
    if card_body:
        payload["context_card"] = {
            "title": (context_headline or name)[:60],
            "style": "LIST_STYLE",
            "button_text": "Continue",
            "content": card_body,
        }
    token = page_token or await fetch_page_token(page_id, access_token) or access_token
    try:
        result = await _request(
            "POST", f"{page_id}/leadgen_forms", token, json_data=payload
        )
    except MetaAdsError as exc:
        if is_permission_error(exc):
            raise MetaAdsError(
                _LEAD_FORM_PERMISSION_HINT, code=exc.code, user_msg=_LEAD_FORM_PERMISSION_HINT
            ) from exc
        # Form names are unique per Page, and a drafted form carries the name the
        # user typed — so republishing a reused campaign setup collides with the
        # form the first publish left behind (subcode 1892019, "Form Name already
        # exists"). The user asked for this form, not for an error, so it is
        # created under a disambiguated name rather than failing the publish.
        if exc.subcode != _LEAD_FORM_NAME_TAKEN:
            raise
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        payload["name"] = f"{name[:240]} {stamp}"
        logger.info("lead form %r already exists on page %s — retrying as %r",
                    name, page_id, payload["name"])
        result = await _request(
            "POST", f"{page_id}/leadgen_forms", token, json_data=payload
        )
    form_id = result.get("id")
    if not form_id:
        raise MetaAdsError("Instant form creation returned no ID")
    return str(form_id)


async def create_ad(
    name: str,
    adset_id: str,
    creative_id: str,
    ad_account_id: str,
    access_token: str,
    *,
    conversion_domain: str = "",
) -> str:
    """Create a PAUSED ad and return its ID.

    The status is pinned here rather than read off ``AdSpec.status``: publish
    activates every ad it created in one pass at the end, so a per-ad status has
    nowhere to take effect and a spec claiming ACTIVE would go live before the
    rest of the campaign exists.

    ``conversion_domain`` is the domain conversions are counted on. Meta uses it
    for Aggregated Event Measurement, the reporting path for people who opted out
    of tracking on iOS: without it those conversions have no verified domain to be
    attributed against. Sent only when known — an ad promoting a Page post to an
    on-Meta destination has no website to name.
    """
    payload: dict[str, Any] = {
        "name": name,
        "adset_id": adset_id,
        "creative": {"creative_id": creative_id},
        "status": "PAUSED",
    }
    if conversion_domain:
        payload["conversion_domain"] = conversion_domain
    result = await _request(
        "POST", f"{_act(ad_account_id)}/ads", access_token, json_data=payload,
    )
    ad_id = result.get("id")
    if not ad_id:
        raise MetaAdsError("Ad creation returned no ID")
    return str(ad_id)


async def update_ad_creative(ad_id: str, creative_id: str, access_token: str) -> None:
    """Point an existing ad at a different creative.

    Used when a plan is edited after a publish attempt already created the ad:
    the copy or media changed, so a new creative is built, and the ad that a
    previous attempt left behind has to follow it rather than keep running the
    version the user replaced. Editing the ad also avoids leaving a duplicate ad
    in the ad set.
    """
    await _request(
        "POST", ad_id, access_token, json_data={"creative": {"creative_id": creative_id}},
    )


# ── Ad previews ───────────────────────────────────────────────────────────────

# Meta's own rendering of a published ad, one placement per ad_format. Ordered
# the way the preview tab strip shows them. Not every format is valid for every
# creative (a single-image ad has no Reels rendering, a carousel has no Stories
# one) and Meta answers those with an error rather than an empty preview — so the
# set below is a superset and whatever comes back is what the user gets.
_PREVIEW_FORMATS: dict[str, str] = {
    "MOBILE_FEED_STANDARD": "Facebook Feed",
    "FACEBOOK_REELS_MOBILE": "Facebook Reels",
    "FACEBOOK_STORY_MOBILE": "Facebook Stories",
    "INSTAGRAM_STANDARD": "Instagram Feed",
    "INSTAGRAM_REELS": "Instagram Reels",
    "INSTAGRAM_STORY": "Instagram Stories",
    "DESKTOP_FEED_STANDARD": "Facebook Desktop",
}

# Meta returns the preview as a full <iframe …> string. Only the src is kept, so
# the client renders an iframe it built itself instead of injecting Meta's HTML.
_IFRAME_SRC_RE = re.compile(r'src="([^"]+)"')


async def _one_preview(ad_id: str, ad_format: str, access_token: str) -> str | None:
    """The preview iframe src for one placement, or None when it doesn't apply."""
    try:
        # No retries: an unsupported format is a permanent 400, and the caller
        # asks for seven formats at once — retrying each would multiply a
        # guaranteed failure by the backoff schedule.
        result = await _request(
            "GET", f"{ad_id}/previews?ad_format={ad_format}", access_token, retries=1,
        )
    except MetaAdsError as exc:
        logger.info("preview %s for ad %s unavailable — %s", ad_format, ad_id, exc)
        return None
    body = ((result.get("data") or [{}])[0]).get("body") or ""
    match = _IFRAME_SRC_RE.search(body)
    return html.unescape(match.group(1)) if match else None


async def generate_ad_previews(ad_id: str, access_token: str) -> list[dict]:
    """Meta's rendering of a published ad, one entry per supported placement.

    Returns ``[{"format", "label", "src"}]`` in ``_PREVIEW_FORMATS`` order, with
    the placements this creative cannot render dropped. Needs a **user** access
    token — Meta rejects previews requested with a Page token.

    Empty is a legitimate answer (a brand-new ad can take a moment before Meta
    will render it); the caller shows the summary without previews rather than
    failing the step.
    """
    formats = list(_PREVIEW_FORMATS)
    srcs = await asyncio.gather(
        *(_one_preview(ad_id, fmt, access_token) for fmt in formats)
    )
    return [
        {"format": fmt, "label": _PREVIEW_FORMATS[fmt], "src": src}
        for fmt, src in zip(formats, srcs)
        if src
    ]


# ── Activation ────────────────────────────────────────────────────────────────


async def activate_campaign(campaign_id: str, access_token: str) -> None:
    await _request("POST", campaign_id, access_token, json_data={"status": "ACTIVE"})


async def activate_adsets(
    adset_ids: list[str], access_token: str, on_activated: Callable | None = None
) -> None:
    """Flip each ad set live, reporting each success as it happens.

    Serial and unguarded, a failure part-way through this loop leaves some objects
    ACTIVE and some PAUSED with nothing recording which — so the retry re-activates
    from the top. ``on_activated`` lets the caller record each id as it lands, so a
    resume skips what is already live.
    """
    for adset_id in adset_ids:
        await _request("POST", adset_id, access_token, json_data={"status": "ACTIVE"})
        if on_activated is not None:
            await on_activated(adset_id)


async def activate_ads(
    ad_ids: list[str], access_token: str, on_activated: Callable | None = None
) -> None:
    """Flip each ad live. See ``activate_adsets`` for ``on_activated``."""
    for ad_id in ad_ids:
        await _request("POST", ad_id, access_token, json_data={"status": "ACTIVE"})
        if on_activated is not None:
            await on_activated(ad_id)


# ── Targeting builder ─────────────────────────────────────────────────────────

# What a radius fallback covers when geo never recorded one, and Meta's own
# bounds on custom_locations.radius — shared with the geo discovery pin+radius
# confirm (executors/geo.py) via settings so the search-time ring and this
# publish-time fallback ring can never drift apart.
_FALLBACK_RADIUS_KM = settings.GEO_PIN_RADIUS_FALLBACK_KM
_RADIUS_MIN_KM = settings.GEO_PIN_RADIUS_MIN_KM
_RADIUS_MAX_KM = settings.GEO_PIN_RADIUS_MAX_KM


def _radius_pins(geo_data: dict) -> list[dict]:
    """``geo_locations.custom_locations`` from the geocoded locations.

    The radius follows the POI search the plan was built around, so the ad set
    covers what the user actually scoped rather than a fixed guess.
    """
    try:
        km = float(geo_data.get("poi_radius_km") or 0) or _FALLBACK_RADIUS_KM
    except (TypeError, ValueError):
        km = _FALLBACK_RADIUS_KM
    km = round(min(max(km, _RADIUS_MIN_KM), _RADIUS_MAX_KM), 1)

    pins: list[dict] = []
    for loc in geo_data.get("locations") or []:
        try:
            pins.append({
                "latitude": float(loc["latitude"]),
                "longitude": float(loc["longitude"]),
                "radius": km,
                "distance_unit": "kilometer",
            })
        except (KeyError, TypeError, ValueError):
            continue
    return pins


async def build_targeting(
    geo_data: dict,
    custom_audience_id: str | None = None,
    access_token: str | None = None,
    lookalike_audience_id: str | None = None,
    broad: bool = False,
) -> dict:
    """Construct a Meta targeting spec from GeoData state.

    Geo targeting is by **ZIP code**: the unique postal codes reverse-geocoded
    from the discovered POIs (``geo_data["target_zips"]``, populated by
    ``tools.resolve_poi_zips`` before this is called). The same zip set is used
    for every ad set role — seed, broad, and lookalike alike — so ``broad`` no
    longer changes the geography, only the audience attachment differs.

    Falls back to a radius around each geocoded location when no zips resolved
    (geocoder miss or a city-only run with no POIs). It used to fall back to
    ``cities: [{"name": …}]``, which Meta rejects — the ``cities`` block takes an
    adgeolocation **key**, and ``name`` is only ever an output field. Coordinates
    are already on ``geo_data`` and need no extra Graph API call.

    A lookalike (passed via ``lookalike_audience_id``) is attached the way Meta
    expects — as a ``custom_audiences`` entry.
    """
    targeting: dict = {}

    if custom_audience_id:
        targeting["custom_audiences"] = [{"id": custom_audience_id}]
    if lookalike_audience_id:
        targeting.setdefault("custom_audiences", []).append({"id": lookalike_audience_id})

    zips = geo_data.get("target_zips") or []
    if zips:
        targeting["geo_locations"] = {
            "zips": [{"key": z} for z in zips],
            "location_types": ["home", "recent"],
        }
    else:
        pins = _radius_pins(geo_data)
        if pins:
            targeting["geo_locations"] = {
                "custom_locations": pins,
                "location_types": ["home", "recent"],
            }

    return targeting
