"""``meta_capi`` — hashing, deduplication ids, and batching.

Three things here are silent failures rather than errors, which is why they are
worth a test each:

  * hashing the wrong fields (or hashing the ones Meta matches by exact value)
    produces events Meta accepts and matches to nobody;
  * a non-deterministic ``event_id`` double-counts every conversion that the pixel
    also reported, which inflates reported ROAS;
  * a batch over 1000 events is rejected as a whole, so the chunking has to hold.

Nothing here talks to Meta: the transport is monkeypatched at ``meta_capi._request``,
the same seam ``test_meta_wire_payload`` uses.
"""
import hashlib

import pytest

from app.services import meta_capi


# ── Hashing ──────────────────────────────────────────────────────────────────


def test_email_is_normalized_before_hashing():
    """Both sides must hash the same bytes or the match silently fails."""
    expected = hashlib.sha256(b"bob@example.com").hexdigest()

    assert meta_capi.hash_user_field("email", "  Bob@Example.COM ") == expected
    assert meta_capi.hash_user_field("email", "bob@example.com") == expected


def test_phone_keeps_digits_only():
    digits = hashlib.sha256(b"14155551234").hexdigest()

    assert meta_capi.hash_user_field("phone", "+1 (415) 555-1234") == digits
    assert meta_capi.hash_user_field("phone", "1-415-555-1234") == digits


def test_us_zip_matches_on_the_five_digit_prefix():
    five = hashlib.sha256(b"94103").hexdigest()

    assert meta_capi.hash_user_field("zip", "94103-1234") == five
    assert meta_capi.hash_user_field("zip", " 94103 ") == five


def test_empty_identifier_hashes_to_nothing():
    """An absent field must be omitted, not sent as the digest of "" —
    which would be a constant every event shares."""
    assert meta_capi.hash_user_field("email", "") == ""
    assert meta_capi.hash_user_field("email", None) == ""


def test_meta_owned_identifiers_are_never_hashed():
    """fbp/fbc/IP/user-agent/external_id/lead_id match by exact value.

    Hashing any of them does not protect the user, it just guarantees no match —
    the single most common way a CAPI integration reports a perfect 0% match rate.
    """
    user_data = meta_capi.build_user_data(
        email="bob@example.com",
        fbp="fb.1.1558571054389.1098115397",
        fbc="fb.1.1554763741205.AbCdEf",
        client_ip_address="203.0.113.7",
        client_user_agent="Mozilla/5.0",
        external_id="cust-99",
        lead_id="1234567890123456",
    )

    assert user_data["fbp"] == "fb.1.1558571054389.1098115397"
    assert user_data["fbc"] == "fb.1.1554763741205.AbCdEf"
    assert user_data["client_ip_address"] == "203.0.113.7"
    assert user_data["client_user_agent"] == "Mozilla/5.0"
    assert user_data["external_id"] == "cust-99"
    assert user_data["lead_id"] == "1234567890123456"
    # And the one that IS hashed went out hashed, in Meta's list form.
    assert user_data["em"] == [hashlib.sha256(b"bob@example.com").hexdigest()]


def test_unknown_identifiers_are_dropped():
    """Meta ignores unrecognized user_data keys, so passing one through would read
    as a working integration that matches on less than the caller thinks."""
    user_data = meta_capi.build_user_data(email="bob@example.com", loyalty_tier="gold")

    assert "loyalty_tier" not in user_data
    assert set(user_data) == {"em"}


# ── Deduplication ────────────────────────────────────────────────────────────


def test_event_id_is_deterministic():
    args = dict(event_name="Purchase", identity="order-1", event_time=1_700_000_000)

    assert meta_capi.make_event_id(**args) == meta_capi.make_event_id(**args)


def test_event_id_tolerates_a_clock_skew_under_a_minute():
    """The browser fires on the confirmation page, the server when the order
    commits. Those are never the same second, so the id buckets to the minute."""
    base = 1_700_000_000  # :20 past the minute
    assert meta_capi.make_event_id(
        event_name="Purchase", identity="order-1", event_time=base
    ) == meta_capi.make_event_id(
        event_name="Purchase", identity="order-1", event_time=base + 30
    )


def test_event_id_separates_different_conversions():
    first = meta_capi.make_event_id(
        event_name="Purchase", identity="order-1", event_time=1_700_000_000
    )
    second = meta_capi.make_event_id(
        event_name="Purchase", identity="order-2", event_time=1_700_000_000
    )
    other_event = meta_capi.make_event_id(
        event_name="Lead", identity="order-1", event_time=1_700_000_000
    )

    assert first != second
    assert first != other_event


# ── Event construction ───────────────────────────────────────────────────────


def test_event_rejects_an_unknown_action_source():
    with pytest.raises(ValueError, match="action_source"):
        meta_capi.build_event(
            event_name="Purchase",
            user_data={"em": ["x"]},
            action_source="carrier_pigeon",
        )


def test_event_rejects_empty_user_data():
    with pytest.raises(ValueError, match="user_data"):
        meta_capi.build_event(event_name="Purchase", user_data={})


def test_event_rejects_events_older_than_metas_window():
    """Meta drops these with no error, which is indistinguishable from tracking
    never having been installed."""
    with pytest.raises(ValueError, match="7 days"):
        meta_capi.build_event(
            event_name="Purchase",
            user_data={"em": ["x"]},
            event_time=1,
        )


def test_limited_data_use_sets_all_three_fields():
    """Meta requires the country alongside the LDU flag; a lone flag is ignored."""
    event = meta_capi.build_event(
        event_name="Purchase", user_data={"em": ["x"]}, limited_data_use=True,
    )

    assert event["data_processing_options"] == ["LDU"]
    assert event["data_processing_options_country"] == 1
    assert event["data_processing_options_state"] == 0


# ── Batching ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sent(monkeypatch):
    """Record every payload ``send_events`` would put on the wire."""
    calls: list[dict] = []

    async def fake_request(method, endpoint, access_token, json_data=None, **kwargs):
        calls.append({"endpoint": endpoint, "payload": json_data})
        return {"events_received": len((json_data or {}).get("data") or [])}

    monkeypatch.setattr(meta_capi, "_request", fake_request)
    return calls


def _event(i: int) -> dict:
    return meta_capi.build_event(
        event_name="Purchase",
        user_data=meta_capi.build_user_data(external_id=f"cust-{i}"),
    )


@pytest.mark.asyncio
async def test_batches_are_capped_at_metas_limit(sent):
    """1500 events must go out as two requests — a single oversized batch is
    rejected whole, losing every event in it."""
    result = await meta_capi.send_events(
        "ds-1", [_event(i) for i in range(1500)], access_token="tok",
    )

    assert len(sent) == 2
    assert [len(c["payload"]["data"]) for c in sent] == [1000, 500]
    assert result["events_received"] == 1500
    assert result["errors"] == []
    assert sent[0]["endpoint"] == "ds-1/events"


@pytest.mark.asyncio
async def test_test_event_code_rides_on_the_request_not_the_event(sent):
    await meta_capi.send_events(
        "ds-1", [_event(0)], access_token="tok", test_event_code="TEST123",
    )

    assert sent[0]["payload"]["test_event_code"] == "TEST123"
    assert "test_event_code" not in sent[0]["payload"]["data"][0]


@pytest.mark.asyncio
async def test_one_bad_batch_does_not_discard_the_others(monkeypatch):
    """Partial success is the normal outcome at volume."""
    seen: list[int] = []

    async def flaky(method, endpoint, access_token, json_data=None, **kwargs):
        batch = (json_data or {}).get("data") or []
        seen.append(len(batch))
        if len(seen) == 1:
            raise meta_capi.MetaAdsError("GraphAPIError: transient")
        return {"events_received": len(batch)}

    monkeypatch.setattr(meta_capi, "_request", flaky)

    result = await meta_capi.send_events(
        "ds-1", [_event(i) for i in range(1200)], access_token="tok",
    )

    assert seen == [1000, 200]
    assert result["events_received"] == 200
    assert len(result["errors"]) == 1


@pytest.mark.asyncio
async def test_no_events_is_not_a_request(sent):
    result = await meta_capi.send_events("ds-1", [], access_token="tok")

    assert sent == []
    assert result == {"events_received": 0, "batches": 0, "errors": []}


# ── Event names ──────────────────────────────────────────────────────────────


def test_custom_event_type_maps_to_the_wire_name():
    """Meta spells one event two ways and nothing in Meta translates between them."""
    assert meta_capi.event_name_for("PURCHASE") == "Purchase"
    assert meta_capi.event_name_for("COMPLETE_REGISTRATION") == "CompleteRegistration"
    assert meta_capi.event_name_for("ADD_TO_WISHLIST") == "AddToWishlist"


def test_every_standard_event_round_trips():
    """The mapping is mechanical, so it has to hold for the whole set — one name
    it gets wrong is a snippet firing an event the ad set never learns from."""
    for name in meta_capi.STANDARD_EVENTS:
        enum_form = "".join(
            "_" + c if c.isupper() and i else c.upper()
            for i, c in enumerate(name)
        )
        assert meta_capi.event_name_for(enum_form) == name, enum_form


def test_every_offerable_conversion_event_has_a_wire_name():
    """The intake form offers PIXEL_EVENTS; the snippet has to be able to name
    each one on the wire. Imported here only — services must not depend on graph."""
    from app.graph.meta_spec.catalog import PIXEL_EVENTS

    for event_type in PIXEL_EVENTS:
        assert meta_capi.event_name_for(event_type) in meta_capi.STANDARD_EVENTS


def test_no_event_type_is_no_event_name():
    """An account optimizing for a custom conversion has no standard event, and
    "" must not become some default the caller then installs."""
    assert meta_capi.event_name_for("") == ""
    assert meta_capi.event_name_for(None) == ""
