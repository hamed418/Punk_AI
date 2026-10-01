"""
tests/test_tracking_leadgen.py
──────────────────────────────
Meta's leadgen webhook: the one piece of event listening Punk can do on the
advertiser's behalf.

``POST /tracking/leads`` only ever fires if the advertiser's own system posts to
it, and the advertiser who picked "do it for me" has no system. Here Meta is the
caller — which makes this the only route in Punk with no login, no API key and no
ingest key behind it, so the HMAC signature is the whole of its authentication.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.modules.tracking import router as tracking_router
from app.modules.tracking.service import TrackingService

PAGE_ID = "pg-77"
LEAD_ID = "lead-123"


class _Repo:
    """The AdsRepository methods the leadgen path uses."""

    def __init__(self, conn, *, page_id: str = PAGE_ID):
        self.conn = conn
        self.page_id = page_id

    async def get_account_by_lead_page_id(self, db, page_id):
        return self.conn if page_id == self.page_id else None

    async def get_tracking_account(self, db, user_id):
        return self.conn


def _conn(**overrides):
    base = dict(
        id="acct-1",
        user_id="user-1",
        ad_account_id="act_123",
        oauth_token=SimpleNamespace(access_token="user-oauth-token", is_valid=True),
        tracking_system_user_token=None,
        tracking_dataset_id="ds-1",
        tracking_business_id="biz-1",
        tracking_ingest_key="key",
        tracking_event_type="LEAD",
        tracking_method="lead_forms",
        tracking_lead_page_id=PAGE_ID,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _delivery(**value_overrides):
    value = {"page_id": PAGE_ID, "leadgen_id": LEAD_ID, "form_id": "form-1"}
    value.update(value_overrides)
    return [{"id": PAGE_ID, "changes": [{"field": "leadgen", "value": value}]}]


@pytest.fixture
def graph(monkeypatch):
    """Meta's side of the conversation: the Page token, the lead read, and the
    CAPI send."""
    from app.services import meta_ads, meta_capi

    state = {
        "lead": {
            "created_time": "2026-08-20T09:00:00+0000",
            "field_data": [
                {"name": "email", "values": ["Lead@Example.COM "]},
                {"name": "phone_number", "values": ["+1 555 0100"]},
                {"name": "full_name", "values": ["Ada Lovelace"]},
            ],
        },
        "sent": [],
    }

    # Still patched, now as tripwires: nothing on this path should call either.
    # Left in place rather than deleted so a reintroduced read fails loudly here
    # instead of quietly reaching Graph in a test run.
    async def _page_token(page_id, access_token):
        state["read_with"] = ("page_token", page_id)
        return f"page-token-for-{page_id}"

    async def _fetch_lead(leadgen_id, token):
        state["read_with"] = (leadgen_id, token)
        return state["lead"]

    async def _send(dataset_id, events, *, access_token, test_event_code=None):
        state["sent"].append((dataset_id, events))
        return {"events_received": len(events), "errors": []}

    monkeypatch.setattr(meta_ads, "fetch_page_token", _page_token)
    monkeypatch.setattr(meta_ads, "fetch_lead", _fetch_lead)
    monkeypatch.setattr(meta_capi, "send_events", _send)

    async def _log(self, db, **kwargs):
        state["logged"] = kwargs

    from app.modules.tracking.repository import TrackingRepository

    monkeypatch.setattr(TrackingRepository, "log_batch", _log)
    return state


# ── the pipe ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_lead_meta_pushed_is_reported_back_as_a_conversion(graph):
    result = await TrackingService(_Repo(_conn())).ingest_leadgen(None, _delivery())

    assert result == {"forwarded": 1}
    dataset_id, events = graph["sent"][0]
    assert dataset_id == "ds-1"
    assert events[0]["event_name"] == "Lead"
    # Submitted inside Facebook, not on a website.
    assert events[0]["action_source"] == "system_generated"


@pytest.mark.asyncio
async def test_nothing_about_the_person_is_ever_read(graph):
    """Punk used to trade a Page token, read the lead, and hash the name, email
    and phone — pulling the advertiser's customer out of Meta to send them back
    to Meta. lead_id is Meta's own id for the submission and the key Conversion
    Leads matches on, so the read bought no extra matching and is gone."""
    await TrackingService(_Repo(_conn())).ingest_leadgen(None, _delivery())

    assert "read_with" not in graph
    assert graph["sent"], "the lead should still have been forwarded"


@pytest.mark.asyncio
async def test_the_event_identifies_the_submission_and_nobody_else(graph):
    """lead_id and nothing else. Not the hash of an email either — a digest is
    still the person, and Meta does not need one to match its own lead."""
    await TrackingService(_Repo(_conn())).ingest_leadgen(None, _delivery())

    _, events = graph["sent"][0]
    assert events[0]["user_data"] == {"lead_id": LEAD_ID}
    # Belt and braces over the whole payload: no answer from the form, in any
    # form, including the hash of one.
    wire = json.dumps(events[0]).lower()
    assert "lead@example.com" not in wire
    assert hashlib.sha256(b"lead@example.com").hexdigest() not in wire
    assert "ada" not in wire


@pytest.mark.asyncio
async def test_the_submission_time_comes_off_the_delivery(graph):
    """Meta rejects an event more than seven days old, so a redelivered or
    backfilled lead has to carry its real time. It used to have a second source
    in the lead read; the delivery is now the only one.

    Relative to now, not a fixed epoch: a hardcoded timestamp passes until it
    ages past the seven-day window and then fails for a reason that has nothing
    to do with what is being tested."""
    import time

    submitted = int(time.time()) - 3600
    await TrackingService(_Repo(_conn())).ingest_leadgen(
        None, _delivery(created_time=submitted),
    )

    _, events = graph["sent"][0]
    assert events[0]["event_time"] == submitted


@pytest.mark.asyncio
async def test_the_same_lead_delivered_twice_is_the_same_event(graph):
    """Meta redelivers anything we do not 200 fast enough. The leadgen id is the
    dedup key, so a redelivery is the same conversion rather than a second one."""
    service = TrackingService(_Repo(_conn()))
    await service.ingest_leadgen(None, _delivery())
    await service.ingest_leadgen(None, _delivery())

    first, second = (events[0]["event_id"] for _, events in graph["sent"])
    assert first == second == LEAD_ID


@pytest.mark.asyncio
async def test_a_page_we_never_subscribed_is_dropped_quietly(graph):
    """Our app may be on Pages other tenants own. Nothing to do, nothing wrong —
    and above all not an error, which would make Meta retry it forever."""
    result = await TrackingService(_Repo(_conn())).ingest_leadgen(
        None, _delivery(page_id="someone-elses-page"),
    )

    assert result == {"forwarded": 0}
    assert graph["sent"] == []


@pytest.mark.asyncio
async def test_one_failed_lead_never_costs_the_rest_of_the_batch(graph, monkeypatch):
    """A non-200 makes Meta redeliver everything and eventually disable the
    subscription, so a single failure must not escape. The failure moved with the
    read: the only call left per lead is the send."""
    from app.services import meta_capi

    calls = {"n": 0}

    async def _sometimes(dataset_id, events, *, access_token, test_event_code=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Graph is having a day")
        graph["sent"].append((dataset_id, events))
        return {"events_received": len(events), "errors": []}

    monkeypatch.setattr(meta_capi, "send_events", _sometimes)
    delivery = _delivery() + _delivery(leadgen_id="lead-456")

    result = await TrackingService(_Repo(_conn())).ingest_leadgen(None, delivery)

    assert result == {"forwarded": 1}


@pytest.mark.asyncio
async def test_a_change_that_is_not_a_lead_is_ignored(graph):
    """One Page subscription can carry several fields. Only leadgen is ours."""
    delivery = [{"id": PAGE_ID, "changes": [{"field": "feed", "value": {"page_id": PAGE_ID}}]}]

    assert await TrackingService(_Repo(_conn())).ingest_leadgen(None, delivery) == {
        "forwarded": 0,
    }


# ── the endpoint's authentication ────────────────────────────────────────────


class _Request:
    """Just enough of a Starlette request for the handler."""

    def __init__(self, body: bytes):
        self._body = body

    async def body(self) -> bytes:
        return self._body

    async def json(self):
        return json.loads(self._body)


def _signed(body: bytes) -> str:
    return "sha256=" + hmac.new(
        settings.META_APP_SECRET.encode(), body, hashlib.sha256,
    ).hexdigest()


@pytest.mark.asyncio
async def test_an_unsigned_delivery_is_refused_and_nothing_is_written(monkeypatch):
    """This route has no login, no API key and no ingest key. Without the
    signature check anyone who learned the URL could report conversions into any
    tenant's dataset."""
    called = {"n": 0}

    async def _never(*a, **k):
        called["n"] += 1
        return {"forwarded": 1}

    monkeypatch.setattr(tracking_router.service, "ingest_leadgen", _never)
    body = json.dumps({"object": "page", "entry": _delivery()}).encode()

    from fastapi import HTTPException

    for signature in ("", "sha256=deadbeef", _signed(b"a different body")):
        with pytest.raises(HTTPException) as exc:
            await tracking_router.receive_webhook.__wrapped__(
                _Request(body), signature=signature, db=None,
            )
        assert exc.value.status_code == 401
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_a_correctly_signed_delivery_is_forwarded(monkeypatch):
    seen: dict = {}

    async def _ingest(db, entries):
        seen["entries"] = entries
        return {"forwarded": 1}

    monkeypatch.setattr(tracking_router.service, "ingest_leadgen", _ingest)
    body = json.dumps({"object": "page", "entry": _delivery()}).encode()

    out = await tracking_router.receive_webhook.__wrapped__(
        _Request(body), signature=_signed(body), db=None,
    )

    assert out == {"forwarded": 1}
    assert seen["entries"][0]["changes"][0]["field"] == "leadgen"


@pytest.mark.asyncio
async def test_a_subscription_that_is_not_a_page_is_acknowledged_not_acted_on(monkeypatch):
    monkeypatch.setattr(
        tracking_router.service, "ingest_leadgen", _boom := _unused_ingest(),
    )
    body = json.dumps({"object": "instagram", "entry": []}).encode()

    out = await tracking_router.receive_webhook.__wrapped__(
        _Request(body), signature=_signed(body), db=None,
    )

    assert out == {"forwarded": 0}


def _unused_ingest():
    async def _inner(*a, **k):
        raise AssertionError("acted on a subscription that is not a Page")
    return _inner


# ── the verification handshake ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_challenge_comes_back_verbatim(monkeypatch):
    """Meta compares the response body against what it sent, so a JSON-quoted copy
    fails the handshake."""
    monkeypatch.setattr(settings, "META_WEBHOOK_VERIFY_TOKEN", "shared-secret")

    response = await tracking_router.verify_webhook(
        mode="subscribe", token="shared-secret", challenge="1158201444",
    )

    assert response.body == b"1158201444"


@pytest.mark.asyncio
async def test_a_wrong_or_unconfigured_verify_token_refuses(monkeypatch):
    """An unset token must refuse every handshake rather than accept any token
    offered — a deployment that has not configured the webhook should not be
    subscribable by whoever asks first."""
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "META_WEBHOOK_VERIFY_TOKEN", "shared-secret")
    with pytest.raises(HTTPException) as exc:
        await tracking_router.verify_webhook(
            mode="subscribe", token="guessed", challenge="x",
        )
    assert exc.value.status_code == 403

    monkeypatch.setattr(settings, "META_WEBHOOK_VERIFY_TOKEN", "")
    with pytest.raises(HTTPException):
        await tracking_router.verify_webhook(
            mode="subscribe", token="", challenge="x",
        )


# ── the state publish actually produced ──────────────────────────────────────
# _conn() above pairs tracking_method="lead_forms" with a dataset, which is what
# the fixture assumed and what publish never wrote: an instant-form ad set
# promotes the Page, so media_select_pixel returned before resolving one. Every
# lead Meta pushed was read and then dropped.


@pytest.mark.asyncio
async def test_a_lead_with_no_dataset_to_report_into_is_named_not_swallowed(
    graph, monkeypatch,
):
    """It used to die inside ingest_leadgen's catch-all as "could not forward
    lead", which reads as something transient a redelivery might fix. It is a
    permanent misconfiguration that drops every lead until somebody attaches a
    dataset.

    Asserted on the logger call rather than caplog: app logging goes through
    structlog, which does not propagate to pytest's capture handler — the message
    shows up on stdout and caplog.text stays empty.
    """
    from app.modules.tracking import service as tracking_service

    warnings: list[tuple] = []
    monkeypatch.setattr(
        tracking_service.logger,
        "warning",
        lambda msg, *args, **kwargs: warnings.append(msg % args if args else msg),
    )

    result = await TrackingService(
        _Repo(_conn(tracking_dataset_id=None))
    ).ingest_leadgen(None, _delivery())

    assert result == {"forwarded": 0}
    assert graph["sent"] == []
    named = " ".join(warnings)
    assert "no dataset" in named
    assert LEAD_ID in named and PAGE_ID in named


@pytest.mark.asyncio
async def test_the_dataset_guard_short_circuits_before_the_send(graph):
    """The guard has to come before _send_for_account, not be discovered by it —
    a 409 raised inside the send is swallowed by ingest_leadgen's catch-all and
    reported as "could not forward lead", which reads as transient."""
    await TrackingService(_Repo(_conn(tracking_dataset_id=None))).ingest_leadgen(
        None, _delivery(),
    )

    assert graph["sent"] == []


# ── the publish step that stops it happening ─────────────────────────────────


@pytest.fixture
def subscribe(monkeypatch):
    """Meta's side of subscribing a Page, plus the row the result is written to."""
    from app.graph.builder.executors import media
    from app.services import meta_ads

    state = {"pixels": [], "saved": {}, "notes": []}

    async def _page_token(page_id, access_token):
        return "page-token"

    async def _subscribe(page_id, page_token):
        return True

    async def _pixels(ad_account_id, access_token):
        return state["pixels"]

    monkeypatch.setattr(meta_ads, "fetch_page_token", _page_token)
    monkeypatch.setattr(meta_ads, "subscribe_page_leadgen", _subscribe)
    monkeypatch.setattr(meta_ads, "fetch_ad_pixels", _pixels)

    async def _stored(user_id):
        return str(state["saved"].get("tracking_dataset_id") or ""), "biz-1"

    async def _remember(user_id, dataset_id, business_id="", event_type="", method=""):
        state["saved"].update(
            tracking_dataset_id=dataset_id,
            tracking_business_id=business_id,
            tracking_event_type=event_type,
            tracking_method=method,
        )

    monkeypatch.setattr(media, "_stored_tracking_dataset", _stored)
    monkeypatch.setattr(media, "_remember_tracking_dataset", _remember)

    # The Page id write goes through the repository; no database in this test.
    class _Repo2:
        async def save_tracking_state(self, db, user_id, **fields):
            state["saved"].update(fields)
            return True

    monkeypatch.setattr(media, "AdsRepository", _Repo2)

    class _Session:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(media, "AsyncSessionLocal", _Session)
    return state


async def _subscribe_page(state):
    from app.graph.builder.executors import media

    return await media._subscribe_lead_webhook(
        page_id=PAGE_ID,
        ad_account_id="act_123",
        access_token="tok",
        user_id="user-1",
        writer=lambda event: state["notes"].append(event.get("content", "")),
    )


@pytest.mark.asyncio
async def test_subscribing_a_page_gives_its_leads_somewhere_to_land(subscribe):
    subscribe["pixels"] = [{"id": "ds-9", "name": "Shop", "last_fired_time": ""}]

    assert await _subscribe_page(subscribe) is None
    assert subscribe["saved"]["tracking_lead_page_id"] == PAGE_ID
    assert subscribe["saved"]["tracking_dataset_id"] == "ds-9"
    # LEAD, not the objective default — every event this feed sends is a lead.
    assert subscribe["saved"]["tracking_event_type"] == "LEAD"
    assert subscribe["saved"]["tracking_method"] == "lead_forms"


@pytest.mark.asyncio
async def test_an_account_with_no_dataset_is_not_given_one(subscribe):
    """Punk does not create a dataset on its own initiative. One made here
    measures nothing until somebody installs it, and the tracking card raises
    lead_dataset_missing so the gap is visible instead of silent."""
    subscribe["pixels"] = []

    assert await _subscribe_page(subscribe) is None
    assert subscribe["saved"]["tracking_lead_page_id"] == PAGE_ID
    assert "tracking_dataset_id" not in subscribe["saved"]


@pytest.mark.asyncio
async def test_a_real_choice_between_datasets_is_left_to_the_user(subscribe):
    """Two cold datasets is a question Punk cannot answer for them, and guessing
    means reporting leads into an event store with none of the history."""
    subscribe["pixels"] = [
        {"id": "ds-1", "name": "One", "last_fired_time": ""},
        {"id": "ds-2", "name": "Two", "last_fired_time": ""},
    ]

    await _subscribe_page(subscribe)

    assert "tracking_dataset_id" not in subscribe["saved"]
