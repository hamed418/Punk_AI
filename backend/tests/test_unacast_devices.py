"""
tests/test_unacast_devices.py
──────────────────────────────
The TEMPORARY areas/devices ID substitution at Meta-upload time
(app/graph/unacast_devices.py, executors/media.py._load_maids).

Our observations/geo/search entitlement currently returns Unacast's own
Pseudonymized Registration ID, not a real advertising ID, so a MADID upload
built from it matches nobody. Every stat, filter, map dot and dwell/frequency
number the user sees stays built from real observations — unchanged,
untouched by this file. The ONLY thing that changes is what gets uploaded to
Meta: at that one moment, the observation-derived (registration-ID) list is
silently replaced by a fresh, unfiltered fetch of real advertising IDs for the
same places over the same window. Each group below pins one way that swap
could go wrong: leaking into the display pipeline, firing when there is
nothing to publish, or losing to a fabricated "0% unconfirmed" instead of
"not applicable".
"""
from __future__ import annotations

import inspect
from datetime import date, datetime, timezone

import pytest

from app.graph import unacast_devices as ud
from app.graph.unacast_query import poi_key, purchase_radius_m

_RING = {"lat": 40.7500, "lng": -73.9893, "radius_km": 0.1}
_DAY = date(2026, 9, 1)


# ── response parsing ─────────────────────────────────────────────────────────

def test_one_row_per_device_at_the_ring_centre():
    key = poi_key(_RING)
    fid = f"{key}::{_DAY.isoformat()}"
    payload = {"features": [{
        "id": fid,
        "properties": {"deviceCount": 2, "devices": ["dev-1", "dev-2"], "deviceLimitHit": False},
    }]}
    rows, truncated = ud._parse_response(payload, {fid: (key, _DAY)}, {key: _RING})

    assert truncated == set()
    assert {r["maid"] for r in rows} == {"dev-1", "dev-2"}
    for r in rows:
        assert r["poi_key"] == key
        assert r["lat"] == _RING["lat"] and r["lng"] == _RING["lng"]
        assert r["observed_at"] == datetime(2026, 9, 1, tzinfo=timezone.utc)
        assert r["forensic_flags"] is None and r["hot"] is False


def test_device_limit_hit_marks_the_base_key_truncated():
    """deviceLimitHit is the 10k-device analogue of observationLimitHit — the
    day's device list is a non-random sample, and truncation_report must be
    able to say so from the BASE poi_key, not the per-day feature id."""
    key = poi_key(_RING)
    fid = f"{key}::{_DAY.isoformat()}"
    payload = {"features": [{
        "id": fid,
        "properties": {"devices": ["dev-1"], "deviceLimitHit": True},
    }]}
    ud._TRUNCATED_FEATURES.clear()
    try:
        rows, truncated = ud._parse_response(payload, {fid: (key, _DAY)}, {key: _RING})
        assert truncated == {key}
        assert key in ud._TRUNCATED_FEATURES
    finally:
        ud._TRUNCATED_FEATURES.clear()


def test_a_feature_id_outside_the_request_is_ignored():
    """A response echoing an id this call never sent must not crash or invent
    a row — defensive, matches parse_response's fid-must-resolve contract."""
    rows, truncated = ud._parse_response(
        {"features": [{"id": "unknown::2026-09-01", "properties": {"devices": ["x"]}}]},
        {}, {},
    )
    assert rows == [] and truncated == set()


def test_junk_device_ids_are_dropped():
    key = poi_key(_RING)
    fid = f"{key}::{_DAY.isoformat()}"
    payload = {"features": [{
        "id": fid,
        "properties": {"devices": ["dev-1", "", None, 42]},
    }]}
    rows, _t = ud._parse_response(payload, {fid: (key, _DAY)}, {key: _RING})
    assert [r["maid"] for r in rows] == ["dev-1"]


# ── feature/body shape ───────────────────────────────────────────────────────

def test_feature_carries_the_place_visit_exclude_preset_and_clamped_radius():
    from app.graph.maid_signal import PLACE_VISIT_EXCLUDE_MASK

    feat = ud._feature(_RING, "fid", _DAY)
    assert feat["properties"]["excludeFlags"] == PLACE_VISIT_EXCLUDE_MASK
    assert feat["properties"]["radiusInMeters"] == purchase_radius_m(_RING)
    assert feat["properties"]["deviceCountOnly"] is False
    assert feat["geometry"]["coordinates"] == [_RING["lng"], _RING["lat"]]
    # One calendar day, not the whole window — see the module docstring on
    # why this path never buys a multi-day feature.
    assert feat["properties"]["startDateTime"].startswith("2026-09-01")
    assert feat["properties"]["endDateTime"].startswith("2026-09-01")


def test_request_packs_at_twenty_features_not_ten():
    assert ud._MAX_FEATURES_PER_REQUEST == 20


# ── no pre-flight refusal ─────────────────────────────────────────────────────

def test_there_is_no_feature_count_ceiling():
    """A search is never refused up front for being large — removed alongside
    the observations-path equivalent (unacast_query.UnacastExtractionTooLarge).
    The real backstops are the shared monthly call budget, the circuit breaker
    and the concurrency gate, which _run_batch/_fetch_gaps still enforce; a
    large slot count just becomes more chunks."""
    assert not hasattr(ud, "_check_device_feature_ceiling")
    assert not hasattr(ud, "UnacastExtractionTooLarge")
    from app.core.config import settings

    assert not hasattr(settings, "UNACAST_MAX_DEVICE_FEATURES")


@pytest.mark.asyncio
async def test_a_large_slot_count_chunks_instead_of_refusing(monkeypatch):
    """6,000 location-days (a 200-POI, 30-day search — the shape the old
    ceiling refused outright) packs into 300 requests of 20 instead."""
    from datetime import timedelta

    chunks_seen: list[int] = []

    async def _fake_run_batch(self, chunk, key_to_poi, *, writer=None):
        chunks_seen.append(len(chunk))

    monkeypatch.setattr(ud.UnacastDevicesQuerier, "_run_batch", _fake_run_batch)
    monkeypatch.setattr(ud, "_extraction_limit", lambda: 8)

    querier = ud.UnacastDevicesQuerier(client=object())
    key_to_poi = {f"k{i}": {"lat": 40.0 + i * 0.01, "lng": -73.0, "radius_km": 0.1} for i in range(200)}
    gaps = {k: [_DAY + timedelta(days=n) for n in range(30)] for k in key_to_poi}

    await querier._fetch_gaps(key_to_poi, gaps)

    assert len(chunks_seen) == 300
    assert all(c <= 20 for c in chunks_seen)
    assert sum(chunks_seen) == 6000


# ── this backend never reaches the display pipeline ──────────────────────────

def test_get_maid_querier_is_always_observations(monkeypatch):
    """The whole point of the correction: areas/devices is called from
    exactly one place (fetch_area_advertising_ids, at publish time), never
    wired into the querier every stat/filter/map widget is built from."""
    from app.core import config
    from app.graph import maid_query as mq
    from app.graph.unacast_query import UnacastMAIDQuerier

    monkeypatch.setattr(config.settings, "UNACAST_API_TOKEN", "tok", raising=False)
    monkeypatch.setattr(config.settings, "UNACAST_ID_SOURCE", "areas_devices", raising=False)
    mq._querier = None
    try:
        assert isinstance(mq.get_maid_querier(), UnacastMAIDQuerier)
    finally:
        mq._querier = None


def test_fold_withholds_ping_meta_for_device_rows():
    """Defence in depth: IF a devices-sourced row were ever folded (it isn't,
    on the wired-up path — this module returns a flat maid list, never
    observation rows), it must not fabricate confirmed=False from no
    evidence. Kept even though nothing on the current call path exercises
    it, because _fold_row is shared code any future caller might reach."""
    from app.graph.builder.executors import maid as maid_exec

    assert 'row.get("src") != "devices"' in inspect.getsource(maid_exec._fold_row)


# ── no rebuy when already cached (watermark reuse) ───────────────────────────

@pytest.mark.asyncio
async def test_a_fully_covered_window_makes_no_call(monkeypatch):
    """The whole point of reusing covered_days_bulk/read_cached is that a
    second publish over an overlapping window costs nothing."""
    key = poi_key(_RING)
    called = []

    async def _all_covered(key_to_poi, *, src=None):
        assert src == "devices"
        return {k: {_DAY} for k in key_to_poi}

    async def _fake_read(key_to_poi, days, *, src=None):
        assert src == "devices"
        return [{"poi_key": key, "maid": "dev-1", "lat": 40.75, "lng": -73.98,
                  "ts": "2026-09-01T00:00:00+00:00", "forensic_flags": None, "hot": False}]

    async def _should_not_run(*a, **kw):
        called.append(True)

    monkeypatch.setattr(ud, "covered_days_bulk", _all_covered)
    monkeypatch.setattr(ud, "read_cached", _fake_read)
    querier = ud.UnacastDevicesQuerier(client=object())
    monkeypatch.setattr(querier, "_fetch_gaps", _should_not_run)

    rows = await querier.query_maids([_DAY.isoformat()], [_RING])

    assert called == []
    assert rows and rows[0]["src"] == "devices"


# ── provenance never mixes at the same centre ────────────────────────────────

def test_persist_rows_and_reads_thread_src_through_the_watermark():
    """covered_days_bulk/read_cached/cached_observation_count/persist_rows all
    fence by src so a devices-path buy can never be satisfied by, or delete,
    real observation pings at the same centre/day — and vice versa. Still
    load-bearing even though devices data no longer reaches any widget: a
    stray devices row would otherwise mis-size a real observations request
    (observed_daily_rate) or corrupt a real observations read. Asserted from
    source: the fake-DB test harness elsewhere in this suite ignores SQL
    WHERE clauses entirely, so it cannot distinguish a present filter from a
    missing one."""
    import app.graph.unacast_query as uq

    assert "src: str | None = None" in inspect.getsource(uq.covered_days_bulk)
    assert "src_clause" in inspect.getsource(uq.covered_days_bulk)
    assert "src IS NOT DISTINCT FROM :src" in inspect.getsource(uq.persist_rows)
    assert '"src": src' in inspect.getsource(uq.persist_rows)
    assert "src_clause" in inspect.getsource(uq._rings_join)


def test_no_density_math_exists_to_mis_size_from_devices_rows():
    """The density-atlas/rate-prediction machinery this used to guard against
    mixing devices rows into is gone entirely (unacast_query.py no longer
    predicts request size at all — see its module docstring) — nothing left
    to mis-size. The src fence stays on the functions that DO still exist
    (covered_days_bulk/read_cached/persist_rows), pinned elsewhere in this
    file (test_persist_rows_and_reads_thread_src_through_the_watermark)."""
    import app.graph.unacast_query as uq

    assert not hasattr(uq, "observed_daily_rate")
    assert not hasattr(uq, "planning_rates")
    assert not hasattr(uq, "density_priors")


# ── the publish-time swap (executors/media.py._load_maids) ──────────────────

def _extraction(**over):
    from types import SimpleNamespace

    base = dict(
        maids=["reg-1", "reg-2"],
        observations=[
            {"maid": "reg-1", "lat": 40.75, "lng": -73.98, "count": 1,
             "poi_key": poi_key(_RING), "poi_ids": ["category:gym"], "poi_uids": ["a"],
             "visits": [], "days": []},
            {"maid": "reg-2", "lat": 40.75, "lng": -73.98, "count": 1,
             "poi_key": poi_key(_RING), "poi_ids": ["category:gym"], "poi_uids": ["a"],
             "visits": [], "days": []},
        ],
        pois=[_RING], audience_filter=None, lookback_days=7, event_date_ranges=[],
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_publish_swaps_registration_ids_for_advertising_ids(monkeypatch):
    from app.core import config
    from app.graph.builder.executors import media

    monkeypatch.setattr(config.settings, "UNACAST_ID_SOURCE", "areas_devices", raising=False)

    async def _fake_fetch(pois, *, lookback_days, event_date_ranges=None, writer=None):
        assert pois == [_RING]
        assert lookback_days == 7
        return ["real-maid-1", "real-maid-2", "real-maid-3"]

    monkeypatch.setattr("app.graph.unacast_devices.fetch_area_advertising_ids", _fake_fetch)

    class _Result:
        def scalar_one_or_none(self_inner):
            return _extraction()

    class _Db:
        async def __aenter__(self_inner):
            return self_inner

        async def __aexit__(self_inner, *a):
            return False

        async def execute(self_inner, *a, **kw):
            return _Result()

    monkeypatch.setattr(media, "AsyncSessionLocal", lambda: _Db())

    maids = await media._load_maids({"maid_extraction_id": "11111111-1111-1111-1111-111111111111"})
    assert maids == ["real-maid-1", "real-maid-2", "real-maid-3"]


@pytest.mark.asyncio
async def test_publish_does_not_swap_on_the_observations_backend(monkeypatch):
    """Regression guard: the deletion-day flip (UNACAST_ID_SOURCE=observations)
    must restore a plain upload of the observation-derived list with no other
    code change."""
    from app.core import config
    from app.graph.builder.executors import media

    monkeypatch.setattr(config.settings, "UNACAST_ID_SOURCE", "observations", raising=False)

    async def _should_not_run(*a, **kw):
        raise AssertionError("areas/devices must not be called on the observations backend")

    monkeypatch.setattr("app.graph.unacast_devices.fetch_area_advertising_ids", _should_not_run)

    class _Result:
        def scalar_one_or_none(self_inner):
            return _extraction()

    class _Db:
        async def __aenter__(self_inner):
            return self_inner

        async def __aexit__(self_inner, *a):
            return False

        async def execute(self_inner, *a, **kw):
            return _Result()

    monkeypatch.setattr(media, "AsyncSessionLocal", lambda: _Db())

    maids = await media._load_maids({"maid_extraction_id": "11111111-1111-1111-1111-111111111111"})
    assert maids == ["reg-1", "reg-2"]


@pytest.mark.asyncio
async def test_a_filter_zeroed_audience_stays_zero_not_repopulated(monkeypatch):
    """The observation-side filter narrowing an audience to nobody is a real
    answer and must stay zero — substituting an unfiltered devices fetch here
    would silently publish an audience the user was told did not exist."""
    from app.core import config
    from app.graph.builder.executors import media

    monkeypatch.setattr(config.settings, "UNACAST_ID_SOURCE", "areas_devices", raising=False)

    async def _should_not_run(*a, **kw):
        raise AssertionError("must not fetch replacement IDs for a zeroed audience")

    monkeypatch.setattr("app.graph.unacast_devices.fetch_area_advertising_ids", _should_not_run)

    class _Result:
        def scalar_one_or_none(self_inner):
            return _extraction(audience_filter={"min_visits": 99})

    class _Db:
        async def __aenter__(self_inner):
            return self_inner

        async def __aexit__(self_inner, *a):
            return False

        async def execute(self_inner, *a, **kw):
            return _Result()

    monkeypatch.setattr(media, "AsyncSessionLocal", lambda: _Db())

    maids = await media._load_maids({"maid_extraction_id": "11111111-1111-1111-1111-111111111111"})
    assert maids == []


@pytest.mark.asyncio
async def test_an_empty_devices_fetch_uploads_nothing_not_the_unmatchable_list(monkeypatch):
    """If areas/devices comes back empty (budget/breaker/vendor failure —
    fetch_area_advertising_ids swallows those to []), uploading the
    observation-derived list anyway would silently ship IDs Meta can't match
    either. Failing to empty is the honest outcome."""
    from app.core import config
    from app.graph.builder.executors import media

    monkeypatch.setattr(config.settings, "UNACAST_ID_SOURCE", "areas_devices", raising=False)

    async def _empty(*a, **kw):
        return []

    monkeypatch.setattr("app.graph.unacast_devices.fetch_area_advertising_ids", _empty)

    class _Result:
        def scalar_one_or_none(self_inner):
            return _extraction()

    class _Db:
        async def __aenter__(self_inner):
            return self_inner

        async def __aexit__(self_inner, *a):
            return False

        async def execute(self_inner, *a, **kw):
            return _Result()

    monkeypatch.setattr(media, "AsyncSessionLocal", lambda: _Db())

    maids = await media._load_maids({"maid_extraction_id": "11111111-1111-1111-1111-111111111111"})
    assert maids == []


def test_publish_dates_use_the_event_ranges_when_present():
    dates = ud._publish_dates(lookback_days=7, event_date_ranges=["2026-07-25 -> 2026-07-27"])
    assert dates == ["2026-07-25", "2026-07-26", "2026-07-27"]


def test_publish_dates_fall_back_to_the_lookback_window():
    dates = ud._publish_dates(lookback_days=3, event_date_ranges=[])
    assert len(dates) == 3
