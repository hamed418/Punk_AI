"""``POST /tracking/events`` — the one public write surface in Punk.

It is called by the advertiser's own website or CRM, holds no login, and carries
personal data (emails, phones) belonging to their customers. Every test here is on
that boundary:

  * a wrong key must not resolve a tenant;
  * raw email/phone must never reach Meta — or a log;
  * the browser's IP and user agent come from the request, not the caller;
  * a lead event without a Meta lead_id is not a Conversion Leads signal.

No database and no network: the repository and the CAPI sender are both faked, the
same way ``test_express_objective_gaps`` fakes Graph.
"""
import hashlib
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.modules.tracking.schemas import TrackingEventBatch, TrackingEventRequest
from app.modules.tracking.service import TrackingError, TrackingService

KEY = "ingest-key-abc"


class _Repo:
    """The two AdsRepository methods the tracking service uses."""

    def __init__(self, conn):
        self.conn = conn
        self.saved: dict = {}

    async def get_account_by_ingest_key(self, db, ingest_key):
        if self.conn and str(self.conn.tracking_ingest_key) == ingest_key:
            return self.conn
        return None

    async def get_tracking_account(self, db, user_id):
        return self.conn

    async def save_tracking_state(self, db, user_id, **fields):
        self.saved.update(fields)
        # Write through to the row, so a second read sees what the first stored —
        # otherwise "minted once and reused" cannot be tested at all.
        for key, value in fields.items():
            setattr(self.conn, key, value)
        return True


def _conn(*, access_token="user-oauth-token", is_valid=True, **overrides):
    """One ``ads_accounts`` row — the ad account the user has selected.

    Tracking state hangs off the account, not the login: one connection spans every
    account in ``accessible_accounts``, and billing is per ad account. The
    credentials still come from the connection it points at.
    """
    base = dict(
        id="acct-1",
        user_id="user-1",
        ad_account_id="act_123",
        oauth_token=SimpleNamespace(access_token=access_token, is_valid=is_valid),
        tracking_system_user_token=None,
        tracking_dataset_id="ds-1",
        tracking_business_id="biz-1",
        tracking_ingest_key=KEY,
        # Null is the real default: express never answers the question, and every
        # account predating the column has it unset. Both read as "the full
        # pixel + server setup", which is what the helpers treat "" as.
        tracking_event_type=None,
        tracking_method=None,
        # Set only once an instant-form campaign has published and subscribed the
        # Page. It is what separates "this setup never uses a dataset" from "Meta
        # is pushing leads at an account with nowhere to put them".
        tracking_lead_page_id=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def account_currency(monkeypatch):
    """The snippet asks Meta what currency the ad account spends in.

    Not USD here on purpose: Punk sells into Canada and Bangladesh, and a snippet
    that hardcodes USD reports every conversion in the wrong money.
    """
    from app.services import meta_ads

    async def currency(ad_account_id, token):
        return {"currency": "CAD"}

    monkeypatch.setattr(meta_ads, "fetch_ad_account_currency", currency)


@pytest.fixture
def sent(monkeypatch):
    """Capture what would go to Meta."""
    calls: list[dict] = []

    async def fake_send(dataset_id, events, *, access_token, test_event_code=None):
        calls.append({
            "dataset_id": dataset_id,
            "events": events,
            "access_token": access_token,
            "test_event_code": test_event_code,
        })
        return {"events_received": len(events), "batches": 1, "errors": []}

    from app.services import meta_capi

    monkeypatch.setattr(meta_capi, "send_events", fake_send)
    return calls


def _batch(**overrides) -> TrackingEventBatch:
    base = dict(
        event_name="Purchase",
        email="Bob@Example.com",
        order_id="order-77",
        value=49.99,
        currency="usd",
    )
    base.update(overrides)
    return TrackingEventBatch(events=[TrackingEventRequest(**base)])


async def _send(repo, batch, *, key=KEY, ip="203.0.113.7", ua="Mozilla/5.0"):
    return await TrackingService(repo).send(
        None, ingest_key=key, batch=batch, client_ip=ip, user_agent=ua,
    )


# ── authentication ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_wrong_key_resolves_no_tenant(sent):
    with pytest.raises(TrackingError) as exc:
        await _send(_Repo(_conn()), _batch(), key="not-the-key")

    assert exc.value.status_code == 401
    assert sent == []


@pytest.mark.asyncio
async def test_a_missing_key_is_rejected_before_any_lookup(sent):
    with pytest.raises(TrackingError) as exc:
        await _send(_Repo(_conn()), _batch(), key="")

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_no_resolved_dataset_is_a_clear_409(sent):
    """Not a 500 and not a silent success: the customer has wired their site to an
    account that has no dataset yet, and needs to be told which end to fix."""
    with pytest.raises(TrackingError) as exc:
        await _send(_Repo(_conn(tracking_dataset_id=None)), _batch())

    assert exc.value.status_code == 409
    assert sent == []


# ── personal data ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_email_is_hashed_and_the_raw_value_never_leaves(sent):
    await _send(_Repo(_conn()), _batch())

    user_data = sent[0]["events"][0]["user_data"]
    assert user_data["em"] == [hashlib.sha256(b"bob@example.com").hexdigest()]
    assert "Bob@Example.com" not in str(sent[0]["events"][0])


@pytest.mark.asyncio
async def test_client_ip_and_user_agent_come_from_the_request(sent):
    """A server-to-server caller cannot know the browser's IP, and these two are
    part of how Meta matches a website conversion."""
    await _send(_Repo(_conn()), _batch())

    user_data = sent[0]["events"][0]["user_data"]
    assert user_data["client_ip_address"] == "203.0.113.7"
    assert user_data["client_user_agent"] == "Mozilla/5.0"


@pytest.mark.asyncio
async def test_the_caller_cannot_smuggle_meta_fields(sent):
    """The request schema forbids extras, so no caller can hand-set user_data or
    an unhashed identifier straight onto the wire."""
    with pytest.raises(Exception):
        TrackingEventRequest(event_name="Purchase", email="a@b.com", user_data={"em": "raw"})


# ── payload correctness ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_value_is_reported_with_its_currency(sent):
    await _send(_Repo(_conn()), _batch())

    custom = sent[0]["events"][0]["custom_data"]
    assert custom["value"] == 49.99
    assert custom["currency"] == "USD"


def test_a_value_without_a_currency_is_refused():
    """Punk sells into the US, Canada and Bangladesh — a bare amount would be
    silently reported as the account's currency and corrupt ROAS."""
    with pytest.raises(Exception, match="currency"):
        TrackingEventRequest(event_name="Purchase", email="a@b.com", value=10)


def test_an_event_with_nothing_to_match_on_is_refused():
    """Meta would accept it, match it to nobody, and report a conversion no
    campaign gets credit for — tracking that looks like it works."""
    with pytest.raises(Exception, match="at least one of"):
        TrackingEventRequest(event_name="Purchase")


@pytest.mark.asyncio
async def test_the_event_id_is_the_order_id_the_pixel_also_sends(sent):
    """The snippet fires ``eventID: ORDER_ID``. Meta collapses the browser event
    and the server event only when the two strings are equal — so this has to BE
    the order id, not a hash of it. Deriving one side while printing the other
    counted every conversion twice and doubled reported ROAS."""
    result = await _send(_Repo(_conn()), _batch())

    assert result["event_ids"] == ["order-77"]
    assert sent[0]["events"][0]["event_id"] == "order-77"


@pytest.mark.asyncio
async def test_an_event_with_no_order_id_still_gets_a_stable_id(sent):
    """Nothing is shared with a browser event here, so the derived id is only
    good for our own reconciliation — but it still has to be the same one twice,
    or a retry of the same conversion lands as a second conversion."""
    batch = _batch(order_id=None, external_id="cust-9")
    result = await _send(_Repo(_conn()), batch)
    again = await _send(_Repo(_conn()), batch)

    assert result["event_ids"] == again["event_ids"]
    assert result["event_ids"][0] != "cust-9"


# ── credentials ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_tenants_own_oauth_token_is_used(sent):
    await _send(_Repo(_conn()), _batch())

    assert sent[0]["access_token"] == "user-oauth-token"
    assert sent[0]["dataset_id"] == "ds-1"


@pytest.mark.asyncio
async def test_a_pasted_system_user_token_wins(sent):
    """An advertiser who generated a system user token in their own Business
    Settings gets a feed that outlives an OAuth token."""
    await _send(_Repo(_conn(tracking_system_user_token="their-system-token")), _batch())

    assert sent[0]["access_token"] == "their-system-token"


@pytest.mark.asyncio
async def test_no_token_at_all_is_a_409_not_a_meta_call(sent):
    with pytest.raises(TrackingError) as exc:
        await _send(
            _Repo(_conn(access_token=None, tracking_system_user_token=None)), _batch()
        )

    assert exc.value.status_code == 409
    assert sent == []


# ── kill switch ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_wholly_rejected_batch_is_a_502_so_the_caller_retries(monkeypatch):
    """The caller is the advertiser's own checkout webhook. A 2xx tells it the
    conversion was delivered and it never retries — and the log keeps no
    identifiers, so nothing here can replay it. 502 hands the retry back to the
    only party that still has the data."""
    from app.services import meta_capi

    async def rejected(dataset_id, events, *, access_token, test_event_code=None):
        return {"events_received": 0, "batches": 1, "errors": ["(#100) bad dataset"]}

    monkeypatch.setattr(meta_capi, "send_events", rejected)

    with pytest.raises(TrackingError) as exc:
        await _send(_Repo(_conn()), _batch())

    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_a_partly_rejected_batch_is_still_a_success(monkeypatch):
    """One rejected batch out of several must not throw away the ones Meta took."""
    from app.services import meta_capi

    async def partial(dataset_id, events, *, access_token, test_event_code=None):
        return {"events_received": 1, "batches": 2, "errors": ["(#100) one batch"]}

    monkeypatch.setattr(meta_capi, "send_events", partial)

    result = await _send(_Repo(_conn()), _batch())

    assert result["events_received"] == 1
    assert result["errors"]


@pytest.mark.asyncio
async def test_capi_disabled_still_answers_200(sent, monkeypatch):
    """The customer's site is in production. Switching the feature off here must
    not start erroring on their checkout page."""
    monkeypatch.setattr(settings, "CAPI_ENABLED", False)

    result = await _send(_Repo(_conn()), _batch())

    assert result == {"events_received": 0, "event_ids": [], "errors": []}
    assert sent == []


# ── ingest key lifecycle ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_ingest_key_is_minted_once_and_reused():
    repo = _Repo(_conn(tracking_ingest_key=None))
    service = TrackingService(repo)

    first = await service.ensure_ingest_key(None, "user-1")
    second = await service.ensure_ingest_key(None, "user-1")

    assert first == repo.saved["tracking_ingest_key"]
    assert len(first) >= 32
    # A second call must NOT mint a new one: the first is already installed in the
    # customer's site snippet.
    assert second == first


@pytest.mark.asyncio
async def test_rotation_replaces_the_key():
    repo = _Repo(_conn())
    service = TrackingService(repo)

    rotated = await service.rotate_ingest_key(None, "user-1")

    assert rotated != KEY
    assert repo.saved["tracking_ingest_key"] == rotated


# ── the event log ────────────────────────────────────────────────────────────


class _Events:
    """Stands in for TrackingRepository. ``fails`` proves the swallow."""

    def __init__(self, fails: bool = False):
        self.calls: list[dict] = []
        self.fails = fails

    async def log_batch(self, db, **kwargs):
        if self.fails:
            raise RuntimeError("database is down")
        self.calls.append(kwargs)


@pytest.mark.asyncio
async def test_forwarded_events_are_logged(sent):
    events = _Events()
    result = await TrackingService(_Repo(_conn()), events).send(
        None, ingest_key=KEY, batch=_batch(), client_ip="203.0.113.7", user_agent="UA",
    )

    assert len(events.calls) == 1
    logged = events.calls[0]
    assert logged["dataset_id"] == "ds-1"
    assert logged["event_ids"] == result["event_ids"]
    assert logged["events_received"] == 1


@pytest.mark.asyncio
async def test_a_failed_log_write_never_fails_a_delivered_conversion(sent):
    """The caller is the advertiser's checkout. Meta already accepted the event —
    turning that into a 500 loses a conversion over a bookkeeping problem."""
    result = await TrackingService(_Repo(_conn()), _Events(fails=True)).send(
        None, ingest_key=KEY, batch=_batch(), client_ip="203.0.113.7", user_agent="UA",
    )

    assert result["events_received"] == 1


@pytest.mark.asyncio
async def test_the_log_stores_no_identifiers():
    """The real repository, so the columns it writes are the ones under test: a
    log of WHO converted would be a second copy of the advertiser's customers'
    PII, reachable with an ingest key."""
    # The registry, not the module alone: instantiating any ORM class configures
    # every mapper, and a half-imported registry fails on an unrelated model.
    from app.db import model_registry  # noqa: F401
    from app.modules.tracking.repository import TrackingRepository

    rows: list = []

    class _Db:
        def add_all(self, objs):
            rows.extend(objs)

        async def commit(self):
            pass

    await TrackingRepository().log_batch(
        _Db(),
        ads_account_id="acct-1",
        dataset_id="ds-1",
        payloads=list(_batch().events),
        event_ids=["evt-1"],
        events_received=1,
        errors=[],
    )

    assert len(rows) == 1
    written = " ".join(str(v) for v in vars(rows[0]).values()).lower()
    for identifier in ("bob@example.com", "bob", "example.com"):
        assert identifier not in written
    assert rows[0].event_name == "Purchase"
    assert rows[0].currency == "USD"


@pytest.mark.asyncio
async def test_nothing_is_logged_when_capi_is_switched_off(sent, monkeypatch):
    monkeypatch.setattr(settings, "CAPI_ENABLED", False)
    events = _Events()

    await TrackingService(_Repo(_conn()), events).send(
        None, ingest_key=KEY, batch=_batch(), client_ip="203.0.113.7", user_agent="UA",
    )

    assert events.calls == []


# ── the snippet names the event the campaign optimizes for ───────────────────


@pytest.mark.asyncio
async def test_the_snippet_fires_the_accounts_own_conversion_event():
    """A Leads advertiser handed a Purchase snippet installs the one event their
    ad set is not learning from, and the dataset then looks healthy."""
    service = TrackingService(_Repo(_conn(tracking_event_type="LEAD")))

    result = await service.snippet(None, "user-1")

    assert result["event_name"] == "Lead"
    assert "fbq('track', 'Lead'" in result["pixel_snippet"]
    assert '"event_name": "Lead"' in result["server_example"]
    assert "Lead" in result["event_names"]


@pytest.mark.asyncio
async def test_the_snippet_reports_in_the_accounts_own_currency():
    """A hardcoded USD misprices every conversion on a CAD or BDT account, and
    the value it is priced against is what value-based bidding bids on."""
    result = await TrackingService(_Repo(_conn())).snippet(None, "user-1")

    assert result["currency"] == "CAD"
    assert "currency: 'CAD'" in result["pixel_snippet"]
    assert '"currency": "CAD"' in result["server_example"]
    # Zero would survive deduplication and make the conversion worth nothing.
    assert "value: 0.00" not in result["pixel_snippet"]


@pytest.mark.asyncio
async def test_an_explicit_event_still_wins():
    service = TrackingService(_Repo(_conn(tracking_event_type="LEAD")))

    result = await service.snippet(None, "user-1", event_name="ViewContent")

    assert result["event_name"] == "ViewContent"


@pytest.mark.asyncio
async def test_an_account_with_no_conversion_campaign_gets_purchase():
    """Also the custom-conversion case: a URL rule names no standard event."""
    service = TrackingService(_Repo(_conn(tracking_event_type=None)))

    result = await service.snippet(None, "user-1")

    assert result["event_name"] == "Purchase"


# ── health names which events actually arrive ────────────────────────────────


@pytest.fixture
def graph(monkeypatch):
    """The three dataset reads health does, faked at the meta_ads seam."""
    from app.services import meta_ads

    state = {"activity": {"name": "Shop", "last_fired_time": "2026-08-18T10:00:00+0000"},
             "quality": 8.1, "stats": {"PageView": 4000, "Purchase": 12}}

    async def activity(dataset_id, token):
        return state["activity"]

    async def quality(dataset_id, token, **kwargs):
        return state["quality"]

    async def stats(dataset_id, token, **kwargs):
        return state["stats"]

    monkeypatch.setattr(meta_ads, "fetch_pixel_activity", activity)
    monkeypatch.setattr(meta_ads, "fetch_event_match_quality", quality)
    monkeypatch.setattr(meta_ads, "fetch_dataset_event_stats", stats)

    # server_events_seen counts rows in tracking_events; these tests carry no DB.
    from app.modules.tracking.repository import TrackingRepository

    async def count(self, db, ads_account_id):
        return state.get("forwarded", 0)

    monkeypatch.setattr(TrackingRepository, "count", count)
    return state


@pytest.mark.asyncio
async def test_health_lists_what_the_dataset_received(graph):
    health = await TrackingService(_Repo(_conn(tracking_event_type="PURCHASE"))).health(
        None, "user-1",
    )

    # Biggest first — a dataset that is almost all PageView is the case to see.
    assert health["events"] == [
        {"name": "PageView", "count": 4000},
        {"name": "Purchase", "count": 12},
    ]
    assert health["conversion_event"] == "Purchase"
    assert health["remediation"] == []


@pytest.mark.asyncio
async def test_health_does_not_demand_a_dataset_a_setup_never_uses():
    """Instant-form leads are counted by Meta inside Facebook and a Messenger sale
    has nothing to install anywhere, so "no dataset" is the correct state for
    them — not a blocking "connect one" card. Same rule the never-fired warning
    already follows."""
    health = await TrackingService(
        _Repo(_conn(tracking_dataset_id=None, tracking_method="lead_forms"))
    ).health(None, "user-1")

    assert health["status"] == "ok"
    assert health["remediation"] == []


@pytest.mark.asyncio
async def test_health_still_demands_a_dataset_for_a_pixel_setup():
    """The card is right for anyone whose conversions are supposed to arrive from
    a browser tag — including the unanswered "" default."""
    for method in ("pixel_only", "pixel_and_server", None):
        health = await TrackingService(
            _Repo(_conn(tracking_dataset_id=None, tracking_method=method))
        ).health(None, "user-1")

        assert health["status"] == "no_dataset", method
        assert health["remediation"][0]["key"] == "tracking_no_dataset"


@pytest.mark.asyncio
async def test_health_flags_a_dataset_missing_the_optimized_event(graph):
    """The failure last_fired_time cannot see: a base pixel firing PageView
    forever while the Lead the ad set learns from was never coded."""
    graph["stats"] = {"PageView": 4000}

    health = await TrackingService(_Repo(_conn(tracking_event_type="LEAD"))).health(
        None, "user-1",
    )

    fix = health["remediation"][0]
    assert fix["key"] == "tracking_event_missing"
    # The id is substituted into the prose, not left as a raw placeholder.
    assert "Lead" in fix["cause"] and "{" not in fix["cause"]
    assert all("{" not in step for step in fix["steps"])


@pytest.mark.asyncio
async def test_an_unreadable_stats_call_accuses_nobody(graph):
    """An empty read is as likely to be a throttle as an empty dataset, and
    telling a working integration it is broken is worse than staying quiet."""
    graph["stats"] = {}

    health = await TrackingService(_Repo(_conn(tracking_event_type="LEAD"))).health(
        None, "user-1",
    )

    assert health["events"] == []
    assert health["remediation"] == []

# ── tracking_method actually decides something ───────────────────────────────
# It used to be four values with zero branches: one string, stored nowhere,
# shown once on the publish preview. These are the two questions it answers.


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["lead_forms", "offline_crm"])
async def test_a_setup_with_no_browser_tag_is_not_nagged_about_one(graph, method):
    """Instant-form leads happen inside Facebook; CRM uploads happen after the
    fact. Neither will ever fire a browser event, so "this Pixel has not received
    any events" is a permanent warning describing the setup working as chosen."""
    graph["activity"] = {"name": "Shop", "last_fired_time": None}

    health = await TrackingService(_Repo(_conn(tracking_method=method))).health(
        None, "user-1",
    )

    assert health["remediation"] == []
    assert health["status"] == "never_fired"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["pixel_and_server", "pixel_only", None])
async def test_a_setup_that_does_use_a_tag_still_is(graph, method):
    graph["activity"] = {"name": "Shop", "last_fired_time": None}

    health = await TrackingService(_Repo(_conn(tracking_method=method))).health(
        None, "user-1",
    )

    assert [c["key"] for c in health["remediation"]] == ["pixel_never_fired"]


@pytest.mark.asyncio
async def test_pixel_only_is_handed_no_key_it_has_no_use_for():
    """It asked for a browser tag and nothing else. Minting a secret and telling
    the user to keep it safe is an instruction with no purpose behind it."""
    snip = await TrackingService(_Repo(_conn(tracking_method="pixel_only"))).snippet(
        None, "user-1",
    )

    assert snip["pixel_snippet"]
    assert snip["ingest_key"] == ""
    assert snip["ingest_url"] == ""
    assert snip["server_example"] == ""


@pytest.mark.asyncio
async def test_offline_crm_is_handed_no_snippet_for_a_site_it_does_not_use():
    snip = await TrackingService(_Repo(_conn(tracking_method="offline_crm"))).snippet(
        None, "user-1",
    )

    assert snip["pixel_snippet"] == ""
    assert snip["ingest_key"]
    assert snip["ingest_url"].endswith("/tracking/events")


@pytest.mark.asyncio
async def test_instant_form_leads_are_pointed_at_the_leads_endpoint():
    """A lead is a lead_id and its status, not a purchase — different route."""
    snip = await TrackingService(_Repo(_conn(tracking_method="lead_forms"))).snippet(
        None, "user-1",
    )

    assert snip["ingest_url"].endswith("/tracking/leads")
    assert snip["pixel_snippet"] == ""


@pytest.mark.asyncio
async def test_the_default_setup_still_gets_both_halves():
    snip = await TrackingService(_Repo(_conn(tracking_method="pixel_and_server"))).snippet(
        None, "user-1",
    )

    assert snip["pixel_snippet"] and snip["server_example"]
    assert snip["ingest_url"].endswith("/tracking/events")


# ── the account with a feed and nowhere to put it ────────────────────────────
# The exemption above is right for a setup that never uses a dataset. It was also
# swallowing the one case that is genuinely broken, which is how every pushed lead
# came to be dropped without anything saying so.


@pytest.mark.asyncio
async def test_a_subscribed_page_with_no_dataset_is_not_called_healthy():
    """Meta is pushing leads at this account and _forward_lead has nowhere to send
    them. Warning, not blocking: Meta still counts every lead, so the campaign is
    fine and only the quality feedback loop is missing."""
    health = await TrackingService(
        _Repo(_conn(
            tracking_dataset_id=None,
            tracking_method="lead_forms",
            tracking_lead_page_id="pg-77",
        ))
    ).health(None, "user-1")

    assert health["status"] == "no_dataset"
    assert [c["key"] for c in health["remediation"]] == ["lead_dataset_missing"]
    assert all(c["severity"] == "warns" for c in health["remediation"])


@pytest.mark.asyncio
async def test_an_instant_form_setup_with_no_feed_yet_is_still_left_alone():
    """No subscribed Page means nothing is arriving to be dropped. Accusing this
    account describes a setup that has simply not published yet."""
    health = await TrackingService(
        _Repo(_conn(tracking_dataset_id=None, tracking_method="lead_forms"))
    ).health(None, "user-1")

    assert health["status"] == "ok"
    assert health["remediation"] == []


@pytest.mark.asyncio
async def test_offline_crm_keeps_its_exemption():
    """A CRM upload never involves a Page or a browser. Unchanged by the above."""
    health = await TrackingService(
        _Repo(_conn(
            tracking_dataset_id=None,
            tracking_method="offline_crm",
            tracking_lead_page_id="pg-77",
        ))
    ).health(None, "user-1")

    assert health["status"] == "ok"
    assert health["remediation"] == []


# ── attaching a dataset by hand ──────────────────────────────────────────────
# Two error messages told users to "pick a dataset in Punk" when nothing could.


@pytest.fixture
def pixels(monkeypatch):
    """What this ad account can write to, faked at the meta_ads seam."""
    from app.services import meta_ads

    found = [
        {"id": "ds-1", "name": "Shop", "last_fired_time": "2026-08-18T10:00:00+0000"},
        {"id": "ds-2", "name": "Second site", "last_fired_time": None},
    ]

    async def fetch(ad_account_id, token):
        return found

    monkeypatch.setattr(meta_ads, "fetch_ad_pixels", fetch)
    return found


@pytest.mark.asyncio
async def test_the_datasets_offered_are_the_ones_the_account_can_write_to(pixels):
    repo = _Repo(_conn())
    result = await TrackingService(repo).datasets(None, "user-1")

    assert [d["id"] for d in result["datasets"]] == ["ds-1", "ds-2"]
    assert result["selected"] == "ds-1"
    # A dataset nobody ever installed has to be distinguishable in the picker.
    assert result["datasets"][1]["last_fired_time"] == ""


@pytest.mark.asyncio
async def test_a_dataset_the_account_cannot_reach_is_refused(pixels):
    """Publishing an ad set against an unreachable id produces a campaign that
    optimizes toward an event which can never fire, and Meta reports that as
    delivering normally — so it is refused here rather than stored."""
    repo = _Repo(_conn())
    with pytest.raises(TrackingError) as exc:
        await TrackingService(repo).set_dataset(None, "user-1", "ds-999")

    assert exc.value.status_code == 422
    assert "tracking_dataset_id" not in repo.saved


@pytest.mark.asyncio
async def test_attaching_one_it_can_reach_sticks(pixels):
    repo = _Repo(_conn(tracking_dataset_id=None))
    assert await TrackingService(repo).set_dataset(None, "user-1", "ds-2") == "ds-2"
    assert repo.saved["tracking_dataset_id"] == "ds-2"


# ── switching how conversions reach Meta ─────────────────────────────────────
# An express Sales run is stamped pixel_only, whose own instructions tell the
# advertiser to switch to server events. Until now there was no switch.


@pytest.mark.asyncio
async def test_switching_to_server_events_hands_over_the_server_half():
    repo = _Repo(_conn(tracking_method="pixel_only"))
    service = TrackingService(repo)

    before = await service.snippet(None, "user-1")
    assert before["ingest_url"] == ""
    assert before["server_example"] == ""

    await service.set_method(None, "user-1", "pixel_and_server")
    after = await service.snippet(None, "user-1")

    assert after["ingest_url"].endswith("/tracking/events")
    assert after["server_example"]
    assert after["ingest_key"]


@pytest.mark.asyncio
async def test_switching_away_never_invalidates_a_key_that_is_live():
    """The key is in the customer's checkout by now. Rotation stays the explicit
    action it already is — a settings toggle must not silently break production."""
    repo = _Repo(_conn(tracking_method="pixel_and_server"))
    service = TrackingService(repo)

    key = (await service.snippet(None, "user-1"))["ingest_key"]
    await service.set_method(None, "user-1", "pixel_only")
    await service.set_method(None, "user-1", "pixel_and_server")

    assert (await service.snippet(None, "user-1"))["ingest_key"] == key


@pytest.mark.asyncio
async def test_a_method_nothing_downstream_honours_is_refused():
    repo = _Repo(_conn())
    with pytest.raises(TrackingError) as exc:
        await TrackingService(repo).set_method(None, "user-1", "carrier_pigeon")

    assert exc.value.status_code == 422
    assert "tracking_method" not in repo.saved


# ── what the install instructions now say ────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["pixel_and_server", "lead_forms", "offline_crm"])
async def test_every_setup_that_posts_events_is_told_about_consent(method):
    """opt_out and limited_data_use have been on the request schema all along and
    nothing user-facing mentioned them, so in practice nobody sent either."""
    snip = await TrackingService(_Repo(_conn(tracking_method=method))).snippet(
        None, "user-1",
    )
    steps = " ".join(snip["instructions"])

    assert "opt_out" in steps
    assert "limited_data_use" in steps


@pytest.mark.asyncio
async def test_the_default_setup_warns_about_a_second_sender():
    """The one deduplication case make_event_id cannot solve: a platform app that
    never sees our event_id. Two senders, and Meta counts every purchase twice."""
    snip = await TrackingService(_Repo(_conn(tracking_method="pixel_and_server"))).snippet(
        None, "user-1",
    )
    steps = " ".join(snip["instructions"])

    assert "Shopify" in steps
    assert "twice" in steps


@pytest.mark.asyncio
async def test_pixel_only_is_told_where_the_switch_is():
    """It was told to "switch to server events" by instructions that pointed at
    nothing. There is a control now, so the sentence names it."""
    snip = await TrackingService(_Repo(_conn(tracking_method="pixel_only"))).snippet(
        None, "user-1",
    )

    assert any("server events" in line for line in snip["instructions"])


# ── identifiers the caller hashed themselves ─────────────────────────────────
# The point of accepting these: a customer who hashes on their own side means the
# raw identifier never reaches this process at all.

_BOB = hashlib.sha256(b"bob@example.com").hexdigest()


@pytest.mark.asyncio
async def test_a_digest_the_caller_supplied_reaches_meta_unchanged(sent):
    """The forwarding path is an explicit keyword list, so a schema field nobody
    passes through is accepted, dropped before the sender, and reported as a
    conversion Meta matched to nobody."""
    await _send(_Repo(_conn()), _batch(email=None, email_sha256=_BOB))

    assert sent[0]["events"][0]["user_data"]["em"] == [_BOB]


@pytest.mark.asyncio
async def test_a_supplied_digest_matches_what_punk_would_have_hashed(sent):
    """Both halves have to agree or the two forms are not interchangeable."""
    await _send(_Repo(_conn()), _batch(email="Bob@Example.com"))
    await _send(_Repo(_conn()), _batch(email=None, email_sha256=_BOB))

    assert sent[0]["events"][0]["user_data"]["em"] == sent[1]["events"][0]["user_data"]["em"]


def test_a_malformed_digest_is_refused_rather_than_forwarded():
    """Meta accepts any string here and matches it to nobody, so a truncated or
    uppercase digest produces a dataset that looks healthy while attributing
    nothing."""
    for bad in (_BOB[:63], _BOB.upper(), "not-a-digest"):
        with pytest.raises(ValueError):
            TrackingEventRequest(event_name="Purchase", email_sha256=bad)


def test_both_forms_of_one_identifier_is_refused():
    """Which one won would be invisible, and the two can disagree — a digest of a
    different address than the plaintext beside it attributes to the wrong person."""
    with pytest.raises(ValueError):
        TrackingEventRequest(
            event_name="Purchase", email="bob@example.com", email_sha256=_BOB,
        )


def test_a_digest_alone_is_something_to_match_on():
    """Otherwise the privacy-preserving form is rejected by the check that exists
    to catch events with no identity at all."""
    TrackingEventRequest(event_name="Purchase", email_sha256=_BOB)


# ── the method is the boundary, not a label ──────────────────────────────────
# An ingest key outlives the setting that issued it, so without this an account
# that moved to pixel-only went on accepting conversions through Punk — and
# "pixel-only means nothing reaches us" was a claim the code did not keep.


@pytest.mark.asyncio
async def test_pixel_only_refuses_server_events(sent):
    with pytest.raises(TrackingError) as exc:
        await _send(_Repo(_conn(tracking_method="pixel_only")), _batch())

    assert exc.value.status_code == 409
    # The message has to name the setting: the caller is a developer looking at a
    # 409 from someone else's checkout integration.
    assert "pixel only" in str(exc.value).lower()
    assert sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method", ["pixel_and_server", "offline_crm", "lead_forms", None],
)
async def test_every_setup_with_a_server_half_still_posts(sent, method):
    """Including None — every account predating the column sits there, and
    breaking them to close a theoretical gap is the wrong trade."""
    await _send(_Repo(_conn(tracking_method=method)), _batch())

    assert len(sent) == 1


@pytest.mark.asyncio
async def test_the_gate_did_not_leak_into_the_shared_send(sent):
    """The leadgen webhook shares _send_for_account and is opted into by
    subscribing the Page, not by this setting. Gating the shared helper instead of
    the HTTP ingest would silently stop forwarding leads."""
    service = TrackingService(_Repo(_conn(tracking_method="pixel_only")))
    await service._send_for_account(None, _conn(tracking_method="pixel_only"), _batch())

    assert len(sent) == 1


# ── the recipe that takes Punk out of the path ───────────────────────────────


@pytest.mark.asyncio
async def test_the_direct_recipe_is_addressed_to_meta_not_to_punk():
    snip = await TrackingService(_Repo(_conn(tracking_method="pixel_and_server"))).snippet(
        None, "user-1",
    )
    direct = snip["server_direct_example"]

    assert "graph.facebook.com" in direct
    assert "ds-1/events" in direct
    # Whatever META_API_VERSION says — a version written out in the template is
    # the drift META_GRAPH_URL exists to prevent.
    assert f"/{settings.META_API_VERSION}/" in direct
    # The whole point: no Punk hostname anywhere in it.
    assert settings.BACKEND_PUBLIC_URL not in direct
    assert "X-Punk-Tracking-Key" not in direct


@pytest.mark.asyncio
async def test_the_direct_recipe_reports_in_the_accounts_own_currency():
    """Same rule as the relay example — a hardcoded USD misprices every ROAS
    number built on a CAD or BDT account."""
    snip = await TrackingService(_Repo(_conn(tracking_method="pixel_and_server"))).snippet(
        None, "user-1",
    )

    assert '"currency": "CAD"' in snip["server_direct_example"]


@pytest.mark.asyncio
async def test_a_pixel_only_setup_gets_neither_server_recipe():
    """It asked for a browser tag. Handing it two ways to post server events is
    the same mistake as handing it a key it has no use for."""
    snip = await TrackingService(_Repo(_conn(tracking_method="pixel_only"))).snippet(
        None, "user-1",
    )

    assert snip["server_example"] == ""
    assert snip["server_direct_example"] == ""
