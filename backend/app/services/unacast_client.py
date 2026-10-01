"""
app/services/unacast_client.py
───────────────────────────────
Thin async HTTP transport for the Unacast/Gravy Analytics v1.1 API.

Auth: header ``Authorization: <raw api key>`` (no "Bearer" prefix — confirmed
against the vendor's own docs and the trial account in uncast_test/Nightfury).
This module owns ONLY transport (auth, retry, timeout) — no domain logic, no
batching, no admission control. Mirrors the separation already used for Meta
(app/services/meta_ads.py is domain logic over httpx; this is the httpx layer
for Unacast). See app/graph/unacast_query.py for the querier that calls this.

DIRECT-only account (see docs/maid_unacast_integration_plan.md) — every call
here is synchronous request/response, capped at 180s server-side per the
vendor's own docs (max DIRECT processing time).
"""
from __future__ import annotations

import logging

import httpx
from contextvars import ContextVar

from tenacity import (
    retry,
    retry_if_exception_type,
    retry_if_not_exception_type,
    wait_random_exponential,
)

from app.core.config import settings
from app.graph.maid_query import NonRetryableMAIDQueryError

logger = logging.getLogger(__name__)

_BASE_URLS = {
    "production": "https://api.gravyanalytics.com/v1.1/",
    "staging": "https://api.gravyanalytics.com/v1.1-staging/",
}

# Hard attempt ceiling. The wall-clock budget below usually bites first; this
# only caps a storm of instant 429s.
_MAX_ATTEMPTS = 4

# Longest tenacity may sleep between attempts. Deliberately small: it is part
# of the lease arithmetic in _retry_budget_s, and a long sleep inside a held
# concurrency slot wastes a scarce shared resource doing nothing.
_MAX_RETRY_WAIT_S = 10.0

# Slack between "the last attempt we allow to START" and the lease reaper, so
# _MAX_RETRY_WAIT_S of sleep plus clock skew still lands inside the lease.
_LEASE_SAFETY_MARGIN_S = 15.0


class UnacastAPIError(Exception):
    """A non-2xx response the API itself returned (4xx/5xx after retries)."""

    def __init__(self, status_code: int, body, url: str):
        self.status_code = status_code
        self.body = body
        self.url = url
        super().__init__(f"{status_code} from {url}: {body!r}")


class UnacastNoContact(Exception):
    """The request never reached the vendor — DNS, TCP or TLS failed before a
    byte of it went out, on every attempt.

    Exists purely for BILLING accuracy: the caller's budget ledger
    (unacast_query.reconcile_call) must count a call that arrived and then
    failed, and must NOT count one that never arrived. Any attempt that got a
    response — even a 500 — means the request landed, so this is raised only
    when no attempt ever made contact.
    """


class UnacastIPNotAllowlisted(UnacastAPIError, NonRetryableMAIDQueryError):
    """403 "Unauthorized IP address" — the request did not leave from an IP the
    vendor has allowlisted.

    This is an INFRASTRUCTURE fault, not a data one, and retrying is pointless
    — hence NonRetryableMAIDQueryError. Cloud Run egresses from a rotating
    shared pool by default, so traffic must be routed through the static NAT:

        allowlisted IP : <NAT_IP>
        NAT address    : unacast-nat-ip
        Cloud Router   : unacast-router
        region         : northamerica-northeast1

    Seeing this means egress stopped going through that NAT — a new/changed
    Cloud Run service, a different region, a VPC-egress setting reverted to
    default, or the vendor rotating their allowlist.
    """

    def __init__(self, status_code: int, body, url: str):
        super().__init__(status_code, body, url)
        self.args = (
            f"Unacast rejected this request's source IP ({status_code} from {url}). "
            f"Egress must leave via the static Cloud NAT <NAT_IP> "
            f"(unacast-nat-ip / unacast-router / northamerica-northeast1). "
            f"Vendor response: {body!r}",
        )


class UnacastRequestRejected(UnacastAPIError, NonRetryableMAIDQueryError):
    """The vendor refused THIS request's content — 400/404/413/422, e.g. a place
    outside the key's coverage or a malformed feature.

    Two consequences, both about not letting one request cost everyone else. It
    is non-retryable: the same body gets the same answer, and each re-send was
    another metered call. And it is not a vendor-health failure, so it never
    counts toward the platform-wide circuit breaker — one tenant's
    out-of-coverage search used to pause audiences for every tenant.
    """


class UnacastRateLimited(UnacastAPIError, NonRetryableMAIDQueryError):
    """429 after the transport's own retries — the key's DAILY request limit,
    which resets at 00:00 UTC. A retry seconds later cannot succeed."""


# Statuses that describe the request body rather than the account or the vendor.
_REQUEST_CONTENT_STATUSES = frozenset({400, 404, 413, 422})


def _is_ip_rejection(status_code: int, body) -> bool:
    """A 403 whose body names the IP. Matched on the message rather than the
    bare 403 so a genuine permissions/entitlement 403 (e.g. an endpoint the key
    isn't licensed for) stays a plain UnacastAPIError."""
    if status_code != 403:
        return False
    text = str(body).lower()
    return "ip address" in text or "unauthorized ip" in text


# How many HTTP requests the last call in THIS task actually made.
#
# `_attempt` already tracks `contacted` — "a response of any status proves the
# request reached the vendor and was therefore metered" — but only uses it to
# tell UnacastNoContact apart. That count is exactly what the budget ledger
# needs: retries happen inside this client, so one `reserve_call` in
# unacast_query._run_batch could cover up to _MAX_ATTEMPTS real requests, and
# the vendor's own limit is a daily REQUEST limit per key. The ledger read low.
#
# A ContextVar rather than an instance attribute because one client is shared
# across concurrently-running batches (see UnacastMAIDQuerier._fetch_gaps'
# bounded gather) — an attribute would race between them. Each batch runs in its
# own asyncio.Task, so a value set here is visible only to that task.
REQUESTS_MADE: ContextVar[int] = ContextVar("unacast_requests_made", default=0)


class _RetryableError(Exception):
    """429/5xx — tenacity retries these; anything else surfaces immediately.

    Carries the response detail so that when retries ARE exhausted the caller
    still gets a real UnacastAPIError instead of this private class — see
    ``UnacastClient._request``.
    """

    def __init__(self, status_code: int, body, url: str, retry_after: float | None = None):
        self.status_code = status_code
        self.body = body
        self.url = url
        self.retry_after = retry_after
        super().__init__(f"{status_code} on {url}: {body!r}")


def _retry_budget_s() -> float:
    """Wall-clock after which no NEW attempt may start.

    The caller holds one of UNACAST_MAX_CONCURRENT_CALLS shared concurrency
    leases for the whole duration of this request (see
    unacast_query.acquire_concurrency_slot), and the reaper frees that lease at
    UNACAST_LEASE_STALE_AFTER_S. A retry still running past that point means
    more than the vendor-agreed number of calls are in flight at once — so the
    LAST attempt allowed to start must still be able to run its full
    UNACAST_REQUEST_TIMEOUT_S and finish inside the lease.

    In practice this means retries are for FAST failures (a 429 or a 502 comes
    back in milliseconds). An attempt that burns the full timeout consumes the
    whole lease by itself and is not retried — correctly so: that timeout means
    the vendor was already at its own 180s DIRECT processing ceiling, which a
    retry does not change.
    """
    return max(
        0.0,
        float(settings.UNACAST_LEASE_STALE_AFTER_S)
        - float(settings.UNACAST_REQUEST_TIMEOUT_S)
        - _LEASE_SAFETY_MARGIN_S,
    )


def _stop(retry_state) -> bool:
    return (
        retry_state.attempt_number >= _MAX_ATTEMPTS
        or (retry_state.seconds_since_start or 0.0) >= _retry_budget_s()
    )


def _wait(retry_state) -> float:
    """Jittered exponential backoff, but honour the vendor's own Retry-After
    when it sends one.

    Jitter matters here because up to UNACAST_MAX_CONCURRENT_CALLS workers
    share ONE API key: a plain exponential makes them all retry in lockstep and
    re-trigger the same 429.
    """
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    after = getattr(exc, "retry_after", None)
    if after is not None:
        return min(float(after), _MAX_RETRY_WAIT_S)
    return wait_random_exponential(multiplier=1, max=_MAX_RETRY_WAIT_S)(retry_state)


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """Retry-After in delta-seconds form. The HTTP-date form is ignored rather
    than parsed — the vendor sends seconds, and a misparsed date could produce
    an absurd sleep inside a held concurrency lease."""
    raw = resp.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _base_url() -> str:
    env = (settings.UNACAST_ENV or "production").lower()
    if env not in _BASE_URLS:
        raise RuntimeError(f"UNACAST_ENV must be one of {list(_BASE_URLS)}, got {env!r}")
    return _BASE_URLS[env]


class UnacastClient:
    """One instance per process is fine — httpx.AsyncClient pools connections
    internally. Constructed lazily by the querier so importing this module
    never requires UNACAST_API_TOKEN to be set; get_maid_querier returns None
    instead when it is missing."""

    def __init__(self, token: str | None = None, base_url: str | None = None, timeout: float | None = None):
        # The vendor errors a request out at 190s; the default here sits just
        # above so the server's own error arrives rather than a client-side
        # timeout that would discard the reason.
        timeout = settings.UNACAST_REQUEST_TIMEOUT_S if timeout is None else timeout
        self.token = token or settings.UNACAST_API_TOKEN
        if not self.token:
            raise RuntimeError(
                "UNACAST_API_TOKEN not set — audience extraction needs it."
            )
        self.base_url = (base_url or _base_url()).rstrip("/") + "/"
        self._client = httpx.AsyncClient(
            timeout=timeout,
            # Empty in prod (the Cloud NAT supplies the allowlisted address);
            # set in local dev to tunnel out through it. See UNACAST_PROXY_URL.
            proxy=settings.UNACAST_PROXY_URL or None,
            headers={
                "Authorization": self.token,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
            },
        )

    @retry(
        retry=(
            retry_if_exception_type((_RetryableError, httpx.TransportError))
            & retry_if_not_exception_type(httpx.ReadTimeout)
        ),
        wait=_wait,
        stop=_stop,
        reraise=True,
    )
    async def _attempt(
        self, contacted: list, method: str, url: str, *, json_body=None, params=None
    ) -> httpx.Response:
        """One attempt. Appends to ``contacted`` the moment a response exists,
        because a response — of any status — proves the request reached the
        vendor and was therefore metered.

        httpx.TransportError is retried alongside 429/5xx: a dropped connection
        is exactly the transient fault a retry is for, and letting it escape
        instead sends the whole extraction back through executors/maid.py's
        outer retry, which re-reserves a SECOND unit of the shared monthly
        budget to do what one cheap retry here does for free.

        A READ timeout is the exception, twice over. The request was fully
        sent, so the vendor metered it — it counts as contacted. And it is
        deterministic: the vendor could not answer that body inside the
        timeout, so re-sending the same body cannot help. Thread 77e403d3 sent
        one 10-POI Midtown request four times, 195 s each, and got nothing. The
        caller splits it instead (UnacastMAIDQuerier._fetch_gaps).
        """
        try:
            resp = await self._client.request(method, url, json=json_body, params=params)
        except httpx.ReadTimeout:
            contacted.append(True)
            raise
        contacted.append(True)
        if resp.status_code == 429 or resp.status_code >= 500:
            raise _RetryableError(
                resp.status_code, resp.text[:500], url, _retry_after_seconds(resp)
            )
        return resp

    async def _request(self, method: str, url: str, *, json_body=None, params=None) -> httpx.Response:
        contacted: list = []
        REQUESTS_MADE.set(0)
        try:
            return await self._attempt(
                contacted, method, url, json_body=json_body, params=params
            )
        except _RetryableError as exc:
            # Retries exhausted. Surface the vendor's own failure as the public
            # error type — _RetryableError is private to this module and callers
            # cannot reasonably be asked to catch it. A 429 that survived every
            # retry is the daily key limit, which no outer retry can outlast.
            cls = UnacastRateLimited if exc.status_code == 429 else UnacastAPIError
            raise cls(exc.status_code, exc.body, exc.url) from exc
        except httpx.TransportError as exc:
            if contacted:
                raise
            raise UnacastNoContact(
                f"never reached Unacast at {url}: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            # Every path, success or failure: a request that reached the vendor
            # consumed quota whether or not it returned usable data.
            REQUESTS_MADE.set(len(contacted))

    def _raise_for_status(self, resp: httpx.Response, url: str) -> None:
        if resp.status_code < 400:
            return
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        if _is_ip_rejection(resp.status_code, body):
            raise UnacastIPNotAllowlisted(resp.status_code, body, url)
        if resp.status_code in _REQUEST_CONTENT_STATUSES:
            raise UnacastRequestRejected(resp.status_code, body, url)
        raise UnacastAPIError(resp.status_code, body, url)

    async def post(self, path: str, json_body: dict, params: dict | None = None) -> dict:
        url = self.base_url + path.lstrip("/")
        resp = await self._request("POST", url, json_body=json_body, params=params)
        self._raise_for_status(resp, url)
        return resp.json()

    async def get(self, path: str, params: dict | None = None) -> dict:
        url = self.base_url + path.lstrip("/")
        resp = await self._request("GET", url, params=params)
        self._raise_for_status(resp, url)
        return resp.json()

    async def aclose(self) -> None:
        await self._client.aclose()
