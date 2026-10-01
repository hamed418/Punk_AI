"""
tests/test_meta_maid_upload.py
──────────────────────────────
The MAID custom-audience payload. MADIDs must reach Meta **unhashed** — the
``MADID`` schema takes the raw mobile advertiser ID, and the SHA256 digests we
used to send matched zero devices. This is the check that keeps hashing from
creeping back in.
"""
from __future__ import annotations

import pytest

from app.services import meta_ads


@pytest.mark.asyncio
async def test_maid_upload_sends_raw_lowercased_ids(monkeypatch):
    calls: list[dict] = []

    async def _fake_request(method, path, access_token, **kwargs):
        calls.append({"method": method, "path": path, **kwargs})
        return {}

    monkeypatch.setattr(meta_ads, "_request", _fake_request)

    total = await meta_ads.upload_maids_to_audience(
        audience_id="120200000000000",
        maids=["ABC-123", " def-456 ", "", "   "],
        access_token="tok",
    )

    assert total == 2
    assert len(calls) == 1
    assert calls[0]["path"] == "120200000000000/users"
    assert calls[0]["json_data"] == {
        "payload": {"schema": ["MADID"], "data": [["abc-123"], ["def-456"]]}
    }

    # Belt and braces: nothing in the payload looks like a SHA256 digest.
    sent = [row[0] for row in calls[0]["json_data"]["payload"]["data"]]
    assert not any(len(v) == 64 and all(c in "0123456789abcdef" for c in v) for v in sent)


@pytest.mark.asyncio
async def test_load_maids_never_raises_on_an_unevaluable_stored_filter(monkeypatch):
    """Publish relies on _load_maids never raising. A stored trend filter whose
    history was never bought used to raise straight through it. It now uploads
    nothing, so the no-audience gate asks the user instead of publishing a
    different audience than the headline promised."""
    from types import SimpleNamespace

    from app.graph.builder.executors import media as media_exec

    row = SimpleNamespace(
        maids=["a", "b"],
        observations=[{"maid": "a", "poi_ids": [], "visits": [
            {"ts": "2026-09-10T12:00:00+00:00", "dwell_lower_s": 600, "n_pings": 2},
        ]}],
        audience_filter={"trend": "lapsed", "window_days": 30, "_history_days_bought": 7},
        pois=[{"lat": 40.0, "lng": -73.0}],
    )

    class _Result:
        def scalar_one_or_none(self):
            return row

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def execute(self, *_a, **_k):
            return _Result()

    monkeypatch.setattr(media_exec, "AsyncSessionLocal", lambda: _Session())

    maids = await media_exec._load_maids(
        {"maid_extraction_id": "00000000-0000-0000-0000-000000000001"}
    )
    assert maids == []


# ── the standalone audience export ("publish it myself") ─────────────────────


_USER = {
    "meta_access_token": "tok",
    "meta_ad_account_id": "act_1",
    "business_name": "Autopaws",
}


@pytest.mark.asyncio
async def test_export_audience_only_creates_then_uploads(monkeypatch):
    """The self-publish route builds the audience and nothing else — no campaign,
    no ad set, no ad, no lookalike."""
    from app.graph.builder.executors import media as media_exec

    calls: list[str] = []

    async def _create(*, name, description, ad_account_id, access_token):
        calls.append(f"create:{name}")
        return "aud-1"

    async def _upload(*, audience_id, maids, access_token):
        calls.append(f"upload:{audience_id}:{len(maids)}")
        return len(maids)

    async def _no_campaign(*a, **k):
        raise AssertionError("the export route must not touch campaigns")

    monkeypatch.setattr(media_exec, "_load_maids", _ret(["a", "b", "c"]))
    monkeypatch.setattr(meta_ads, "create_custom_audience", _create)
    monkeypatch.setattr(meta_ads, "upload_maids_to_audience", _upload)
    monkeypatch.setattr(meta_ads, "create_lookalike_audience", _no_campaign)
    monkeypatch.setattr(meta_ads, "create_campaign_from_spec", _no_campaign)

    out = await media_exec.export_audience_only(_USER, {"maid_extraction_id": "x"}, lambda _e: None)

    assert calls == ["create:Autopaws — Custom Audience", "upload:aud-1:3"]
    assert out == {
        "audience_id": "aud-1",
        "audience_name": "Autopaws — Custom Audience",
        "uploaded": 3,
        "ad_account_id": "act_1",
    }


@pytest.mark.asyncio
async def test_export_audience_only_reuses_the_audience_it_already_created(monkeypatch):
    """A failed upload must not orphan the audience. The id is recorded the moment
    Meta returns it, so the retry uploads into that audience instead of creating a
    second one in the user's account."""
    from app.graph.builder.executors import media as media_exec

    creates: list[str] = []
    uploads: list[str] = []

    async def _create(*, name, description, ad_account_id, access_token):
        creates.append(name)
        return "aud-1"

    async def _upload_then_ok(*, audience_id, maids, access_token):
        uploads.append(audience_id)
        if len(uploads) == 1:
            raise meta_ads.MetaAdsError("transient upload failure")
        return len(maids)

    monkeypatch.setattr(media_exec, "_load_maids", _ret(["a", "b"]))
    monkeypatch.setattr(meta_ads, "create_custom_audience", _create)
    monkeypatch.setattr(meta_ads, "upload_maids_to_audience", _upload_then_ok)

    ledger: dict = {}
    with pytest.raises(media_exec.MetaPublishError):
        await media_exec.export_audience_only(
            _USER, {"maid_extraction_id": "x"}, lambda _e: None, export_state=ledger,
        )
    assert ledger == {"audience_id": "aud-1", "audience_name": "Autopaws — Custom Audience"}

    # The retry. A renamed business must not rename the audience mid-flight either.
    out = await media_exec.export_audience_only(
        {**_USER, "business_name": "Renamed"},
        {"maid_extraction_id": "x"}, lambda _e: None, export_state=ledger,
    )

    assert creates == ["Autopaws — Custom Audience"]      # created ONCE
    assert uploads == ["aud-1", "aud-1"]
    assert out["audience_id"] == "aud-1"
    assert out["audience_name"] == "Autopaws — Custom Audience"


@pytest.mark.asyncio
async def test_export_audience_only_records_nothing_when_the_create_fails(monkeypatch):
    """Nothing was created, so nothing may be recorded — a stale id here would make
    the retry upload into an audience that does not exist."""
    from app.graph.builder.executors import media as media_exec

    async def _refuse(**k):
        raise meta_ads.MetaAdsError("audience not allowed", subcode=1870050)

    monkeypatch.setattr(media_exec, "_load_maids", _ret(["a"]))
    monkeypatch.setattr(meta_ads, "create_custom_audience", _refuse)

    ledger: dict = {}
    with pytest.raises(media_exec.MetaPublishError):
        await media_exec.export_audience_only(
            _USER, {"maid_extraction_id": "x"}, lambda _e: None, export_state=ledger,
        )
    assert ledger == {}


@pytest.mark.asyncio
async def test_export_audience_only_refuses_an_empty_extraction(monkeypatch):
    """The audience IS the deliverable here, so an empty one is a failure, not a
    quietly-created empty audience in someone's ad account."""
    from app.graph.builder.executors import media as media_exec

    monkeypatch.setattr(media_exec, "_load_maids", _ret([]))
    monkeypatch.setattr(
        meta_ads, "create_custom_audience",
        _boom("an empty extraction must not create an audience"),
    )

    with pytest.raises(media_exec.MetaPublishError) as exc:
        await media_exec.export_audience_only(_USER, {}, lambda _e: None)
    assert exc.value.step == "custom_audience"


@pytest.mark.asyncio
async def test_export_audience_only_surfaces_a_meta_refusal(monkeypatch):
    """An ad account outside a Business cannot hold a customer-list audience.
    That has to reach the user, not be logged and swallowed.

    What reaches them is the REMEDIATION, not Meta's raw string: subcode 1870050
    has a known manual fix, so ``meta_remediation`` renders the cause and the steps
    to take in Business settings. The raw error is still attached for support to
    read. This test used to assert Meta's own wording, which was the contract
    before that layer existed.
    """
    from app.graph.builder.executors import media as media_exec

    async def _refuse(**k):
        raise meta_ads.MetaAdsError("audience not allowed", subcode=1870050)

    monkeypatch.setattr(media_exec, "_load_maids", _ret(["a"]))
    monkeypatch.setattr(meta_ads, "create_custom_audience", _refuse)

    with pytest.raises(media_exec.MetaPublishError) as exc:
        await media_exec.export_audience_only(_USER, {"maid_extraction_id": "x"}, lambda _e: None)
    assert exc.value.step == "custom_audience"
    # Names the real problem and what it costs, rather than an API code.
    assert "Meta Business" in exc.value.user_message
    assert "without the audience" in exc.value.user_message
    # And it is machine-readable, so the widget can render the steps.
    assert exc.value.remediation
    assert exc.value.remediation["key"] == "audience_needs_business"


def _ret(value):
    async def _inner(*a, **k):
        return value
    return _inner


def _boom(message):
    async def _inner(*a, **k):
        raise AssertionError(message)
    return _inner
