"""
services/meta_capi.py
─────────────────────
Meta Conversions API (CAPI) sender — the server-side half of event tracking.

The browser pixel reports what a visitor's browser is willing and able to report:
nothing when an ad blocker eats the tag, nothing when the conversion happens on a
phone call or in a CRM three days later, and progressively less as cookie lifetimes
shrink. CAPI is the same dataset reached from the server instead
(``POST /{dataset_id}/events``), so a conversion Punk *knows* happened is reported
whether or not the browser managed to.

Why this matters beyond reporting: an ad set optimizing for ``OFFSITE_CONVERSIONS``
learns from the events that arrive in its dataset. A dataset receiving none makes
the campaign publish cleanly and then optimize toward an event that never comes —
which is the failure mode this module exists to close.

Two rules do most of the work and are the easiest to get wrong:

  * **Hash the identifiers, not the signals.** Email, phone, name, city, state,
    zip, country, birthdate and gender are normalized then SHA-256'd before they
    leave this process. ``fbp``/``fbc`` (Meta's own cookies), the client IP, the
    user agent, ``external_id`` and ``lead_id`` are sent RAW — hashing those
    destroys the match instead of protecting it.
  * **Send the same ``event_id`` from both sides.** The browser and the server both
    report one purchase; Meta collapses them only when the ``event_id`` and
    ``event_name`` agree. Without it every conversion counts twice, which quietly
    doubles reported ROAS. ``make_event_id`` is the shared derivation, so the
    snippet Punk hands the customer and the event Punk sends produce the same id
    for the same action.

Transport is ``meta_ads._request`` rather than a second httpx stack: it already
carries the retry policy, the appsecret proof, and the dead-token handling that
flips a connection to invalid on code 190. A CAPI feed is long-lived, so it is the
call most likely to be the one that discovers a revoked token.

Tokens are per-tenant — the connected user's OAuth token, or a system user token
they generated in their own Business Settings. Punk holds no platform-wide Meta
credential and owns no dataset.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import uuid
from typing import Any, Iterable

from app.services.meta_ads import MetaAdsError, _request

logger = logging.getLogger(__name__)

# Meta's own cap on one request's ``data`` array.
MAX_EVENTS_PER_REQUEST = 1000

# How far back Meta accepts an event for a dataset. Anything older is dropped on
# their side without an error, so we refuse it here instead — a silently discarded
# conversion looks exactly like a tracking bug for days afterwards.
MAX_EVENT_AGE_S = 7 * 24 * 60 * 60

# Standard events. A name outside this set is a *custom* event, which Meta accepts
# and which optimization can still target, so this is a hint for callers and the
# editor's vocabulary — not a gate.
STANDARD_EVENTS: frozenset[str] = frozenset({
    "AddPaymentInfo", "AddToCart", "AddToWishlist", "CompleteRegistration",
    "Contact", "CustomizeProduct", "Donate", "FindLocation", "InitiateCheckout",
    "Lead", "PageView", "Purchase", "Schedule", "Search", "StartTrial",
    "SubmitApplication", "Subscribe", "ViewContent",
})


def event_name_for(custom_event_type: str) -> str:
    """``"PURCHASE"`` → ``"Purchase"``. Meta spells one event two ways.

    An ad set names the event it optimizes for with the ``custom_event_type``
    enum on ``promoted_object``; the pixel and the Conversions API name the same
    event in PascalCase on the wire. Nothing in Meta translates between them, so
    handing an advertiser a snippet that fires ``Purchase`` while their ad set
    optimizes for ``LEAD`` produces a dataset receiving everything except the one
    event delivery is learning from — which reads as working tracking.

    Mechanical rather than a lookup table: the transform is exact for every value
    in ``STANDARD_EVENTS`` and for every ``custom_event_type`` Meta defines, and a
    second hand-maintained list is a second thing to drift.
    """
    return "".join(w.capitalize() for w in str(custom_event_type or "").split("_"))

# Where the conversion happened. Required on every event, and it changes how Meta
# attributes: a "website" event with no browser identifiers matches far worse than
# a "phone_call" one, because the website case is expected to carry fbp/fbc.
ACTION_SOURCES: frozenset[str] = frozenset({
    "website", "app", "email", "phone_call", "chat", "physical_store",
    "system_generated", "business_messaging", "other",
})

# Identifiers Meta wants SHA-256'd, mapped to the short key it expects. Callers use
# readable names; the wire uses Meta's.
USER_DATA_HASHED: dict[str, str] = {
    "email": "em",
    "phone": "ph",
    "first_name": "fn",
    "last_name": "ln",
    "city": "ct",
    "state": "st",
    "zip": "zp",
    "country": "country",
    "date_of_birth": "db",
    "gender": "ge",
}

# Identifiers that must NOT be hashed. Meta matches these by exact value: fbp/fbc
# are cookies it set itself, and a hashed IP or user agent is unusable.
USER_DATA_RAW: dict[str, str] = {
    "fbp": "fbp",
    "fbc": "fbc",
    "client_ip_address": "client_ip_address",
    "client_user_agent": "client_user_agent",
    "external_id": "external_id",
    "lead_id": "lead_id",
    "subscription_id": "subscription_id",
    "fb_login_id": "fb_login_id",
}

# Stable namespace for derived event ids. Fixed forever: changing it re-ids every
# event and breaks deduplication against snippets already installed on customer
# sites.
_EVENT_ID_NAMESPACE = uuid.UUID("6f9b1e42-3d5c-5a7e-9c31-8f2a4b6d0001")

_NON_DIGITS = re.compile(r"\D+")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def normalize_user_field(field: str, value: str) -> str:
    """Meta's normalization for one identifier, applied before hashing.

    Hashing is only useful if both sides hash the *same* bytes, so the rules are
    Meta's, not ours: " Bob@Example.COM " and "bob@example.com" have to produce one
    digest or the match silently fails and the event still looks accepted.
    """
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if field == "email":
        return raw
    if field == "phone":
        # Digits only, country code included. A leading "+" or "00" is dropped —
        # Meta matches on the digit string.
        digits = _NON_DIGITS.sub("", raw)
        return digits.lstrip("0") if digits.startswith("00") else digits
    if field in ("first_name", "last_name", "city"):
        return _NON_ALNUM.sub("", raw)
    if field == "state":
        # Two-letter code where there is one (US/CA); otherwise the collapsed name.
        return _NON_ALNUM.sub("", raw)
    if field == "zip":
        # US zips match on the 5-digit prefix, so "94103-1234" and "94103" agree.
        cleaned = raw.split("-")[0].replace(" ", "")
        return cleaned
    if field == "country":
        return _NON_ALNUM.sub("", raw)[:2]
    if field == "date_of_birth":
        return _NON_DIGITS.sub("", raw)  # YYYYMMDD
    if field == "gender":
        return "f" if raw.startswith("f") else "m" if raw.startswith("m") else ""
    return raw


def hash_user_field(field: str, value: str) -> str:
    """Normalized SHA-256 hex digest, or "" when there is nothing to hash."""
    normalized = normalize_user_field(field, value)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_user_data(**identifiers: Any) -> dict[str, Any]:
    """Assemble ``user_data``, hashing exactly what has to be hashed.

    Unknown keys are dropped rather than passed through: an unrecognized key on
    ``user_data`` is accepted by Meta and ignored, which reads as a working
    integration that quietly matches nothing.

    Hashed values go out as single-element lists — Meta's multi-value form, and the
    shape that stays right if a caller ever has two emails for one person.

    A caller that already hashed passes ``<field>_sha256`` instead of ``<field>``
    and the digest goes out verbatim. That is the whole point of accepting it: a
    customer who hashes on their own side means the raw identifier never reaches
    this process at all. They own the normalization in that case — the rules in
    ``normalize_user_field``, applied before their hash — because we cannot
    re-derive it from a digest.
    """
    out: dict[str, Any] = {}
    for name, wire in USER_DATA_HASHED.items():
        # Already-hashed wins. The schema refuses a request carrying both, so
        # reaching here with both set is a non-HTTP caller's bug, and preferring
        # the digest keeps the raw value from leaving on a path that asked for it
        # not to.
        digest = str(identifiers.get(f"{name}_sha256") or "").strip()
        if not digest:
            digest = hash_user_field(name, identifiers.get(name) or "")
        if digest:
            out[wire] = [digest]
    for name, wire in USER_DATA_RAW.items():
        value = identifiers.get(name)
        if value:
            out[wire] = str(value)
    return out


def make_event_id(
    *,
    event_name: str,
    identity: str,
    event_time: int,
    scope: str = "",
) -> str:
    """A deduplication id both the browser and the server can derive.

    Same inputs → same id, so the pixel's ``eventID`` and this event collapse into
    one conversion. ``event_time`` is bucketed to the minute because the two sides
    never agree to the second: the browser fires on the confirmation page, the
    server fires when the order commits.

    ``identity`` is whatever names the person (order id, external id, email) and
    ``scope`` is usually the campaign or dataset. A caller with no identity at all
    should pass the order/transaction id — passing "" makes every event in a minute
    share an id, which deduplicates real conversions away.
    """
    key = f"{scope}|{event_name}|{identity}|{int(event_time) // 60}"
    return str(uuid.uuid5(_EVENT_ID_NAMESPACE, key))


def build_event(
    *,
    event_name: str,
    user_data: dict[str, Any],
    action_source: str = "website",
    event_time: int | None = None,
    event_id: str | None = None,
    event_source_url: str | None = None,
    custom_data: dict[str, Any] | None = None,
    opt_out: bool = False,
    limited_data_use: bool = False,
) -> dict[str, Any]:
    """One server event, validated on the fields Meta rejects or silently drops.

    Raises ValueError rather than sending something Meta will discard: an event
    that vanishes on their side is indistinguishable from tracking never having
    been installed, and that ambiguity costs days.
    """
    if not event_name:
        raise ValueError("event_name is required")
    if action_source not in ACTION_SOURCES:
        raise ValueError(
            f"action_source must be one of {sorted(ACTION_SOURCES)}, got {action_source!r}"
        )
    if not user_data:
        raise ValueError(
            f"{event_name} has no user_data — Meta cannot attribute an event with "
            "no identifiers, so it would be accepted and matched to nobody"
        )

    now = int(time.time())
    stamp = int(event_time) if event_time else now
    if now - stamp > MAX_EVENT_AGE_S:
        raise ValueError(
            f"event_time is more than 7 days old ({now - stamp}s) — Meta drops "
            "these without an error, so it is refused here instead"
        )
    # A clock ahead of ours is a client's clock, not an error worth losing the
    # conversion over.
    stamp = min(stamp, now)

    event: dict[str, Any] = {
        "event_name": event_name,
        "event_time": stamp,
        "action_source": action_source,
        "user_data": user_data,
    }
    if event_id:
        event["event_id"] = event_id
    if event_source_url:
        event["event_source_url"] = event_source_url
    if custom_data:
        event["custom_data"] = custom_data
    if opt_out:
        # Attribution only — the event will not feed optimization.
        event["opt_out"] = True
    if limited_data_use:
        # Limited Data Use, US only. ``0`` for the state means "geolocate it from
        # the IP we already sent", which is the right answer when we do not know
        # where the person is beyond the request.
        event["data_processing_options"] = ["LDU"]
        event["data_processing_options_country"] = 1
        event["data_processing_options_state"] = 0
    return event


def _chunks(events: list[dict], size: int = MAX_EVENTS_PER_REQUEST) -> Iterable[list[dict]]:
    for start in range(0, len(events), size):
        yield events[start:start + size]


async def send_events(
    dataset_id: str,
    events: list[dict[str, Any]],
    *,
    access_token: str,
    test_event_code: str | None = None,
) -> dict[str, Any]:
    """POST events to the dataset. Returns ``{events_received, batches, errors}``.

    Partial success is the normal outcome at scale — one rejected batch must not
    discard the ones that landed — so a failed batch is recorded in ``errors`` and
    the rest are still sent. The caller decides whether a non-empty ``errors`` is
    worth surfacing; ``events_received`` is Meta's own count, not ours.

    ``test_event_code`` routes events to Events Manager's Test Events tab instead
    of live reporting. It must never be set in production, which is why it is an
    explicit argument rather than read from config.
    """
    if not dataset_id:
        raise MetaAdsError("no dataset id — cannot send conversion events")
    if not events:
        return {"events_received": 0, "batches": 0, "errors": []}

    received = 0
    batches = 0
    errors: list[str] = []
    for batch in _chunks(list(events)):
        payload: dict[str, Any] = {"data": batch}
        if test_event_code:
            payload["test_event_code"] = test_event_code
        batches += 1
        try:
            result = await _request(
                "POST", f"{dataset_id}/events", access_token, json_data=payload,
            )
        except MetaAdsError as exc:
            logger.warning(
                "send_events(%s): batch of %d rejected — %s", dataset_id, len(batch), exc,
            )
            errors.append(str(exc))
            continue
        received += int(result.get("events_received") or 0)

    logger.info(
        "send_events(%s): %d/%d events accepted across %d batch(es)%s",
        dataset_id, received, len(events), batches,
        " [TEST]" if test_event_code else "",
    )
    return {"events_received": received, "batches": batches, "errors": errors}
