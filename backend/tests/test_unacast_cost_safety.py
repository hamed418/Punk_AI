"""
tests/test_unacast_cost_safety.py
─────────────────────────────────
Phases 3 and 5: the cache and the budget.

Every failure pinned here spent real, shared, first-come-first-served money or
served data the caller did not pay for. None of them raised.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.graph import unacast_query as uq
from app.graph.unacast_query import (
    HOT_WINDOW_DAYS,
    MAX_RANGE_DAYS,
    UnacastCircuitOpen,
    _breaker_check,
    _breaker_record,
    _breaker_reset,
    _contiguous_ranges,
    _has_gone_cold,
    _is_provisional,
    poi_key,
)


@pytest.fixture(autouse=True)
def _clean_breaker():
    _breaker_reset()
    yield
    _breaker_reset()


# ── radius belongs in the cache key ──────────────────────────────────────────

def _poi(radius_km: float) -> dict:
    return {"lat": 40.7500, "lng": -73.9893, "radius_km": radius_km}


def test_the_same_place_at_a_different_radius_is_a_different_purchase():
    """The live bug this closes: buying a POI at 100 m marked its days covered,
    so a later 500 m request found the watermark satisfied, made NO API call,
    and got the 100 m rows back presented as a 500 m audience. The cache is
    global, so one tenant's narrow fetch degraded every later tenant's wider
    one at the same location."""
    assert poi_key(_poi(0.1)) != poi_key(_poi(0.5))


def test_the_same_place_at_the_same_radius_is_one_purchase():
    assert poi_key(_poi(0.1)) == poi_key(_poi(0.1))


def test_a_poi_without_coordinates_has_no_key():
    assert poi_key({"radius_km": 0.1}) is None


# ── the HOT window ───────────────────────────────────────────────────────────

def test_a_day_bought_while_hot_is_provisional():
    """The vendor loads observations as HOT and de-duplicates them into final
    COLD form ~5 days later. 85.4% of our cached pings are hot, because the
    default prompt is a 7-day lookback."""
    day = date(2026, 9, 8)
    fetched_next_morning = datetime(2026, 9, 9, 6, 0, tzinfo=timezone.utc)
    assert _is_provisional(day, fetched_next_morning) is True


def test_a_day_bought_after_it_went_cold_is_final():
    day = date(2026, 9, 1)
    fetched_much_later = datetime(2026, 9, 20, 6, 0, tzinfo=timezone.utc)
    assert _is_provisional(day, fetched_much_later) is False


def test_a_row_with_no_fetched_at_is_treated_as_final():
    """Missing provenance must not trigger an unbounded re-buy loop."""
    assert _is_provisional(date(2026, 9, 8), None) is False


def test_gone_cold_matches_the_hot_window():
    today = date(2026, 9, 20)
    assert _has_gone_cold(today - timedelta(days=HOT_WINDOW_DAYS), today) is True
    assert _has_gone_cold(today - timedelta(days=HOT_WINDOW_DAYS - 1), today) is False


def test_only_provisional_and_now_cold_days_are_re_bought():
    """A day must be re-bought exactly once: it was provisional when bought AND
    the vendor has since finalised it. Any other combination is already
    correct and re-buying it would just spend budget."""
    today = date(2026, 9, 20)
    # Bought while hot, now cold -> re-buy.
    day_a = date(2026, 9, 10)
    assert _is_provisional(day_a, datetime(2026, 9, 11, tzinfo=timezone.utc))
    assert _has_gone_cold(day_a, today)
    # Bought while hot, STILL hot -> leave alone, nothing better exists yet.
    day_b = today - timedelta(days=1)
    assert _is_provisional(day_b, datetime(2026, 9, 20, tzinfo=timezone.utc))
    assert not _has_gone_cold(day_b, today)


# ── gap ranges: legality-only, no merging ────────────────────────────────────
#
# _merged_ranges (a rate-driven "is merging fragmented gaps cheaper" decision)
# is gone along with the size prediction it depended on — see unacast_query.py's
# module docstring. _contiguous_ranges alone (no rate, no cost comparison) is
# what plan_requests now calls directly: every contiguous run is its own span,
# capped at MAX_RANGE_DAYS (a vendor legality limit, not a cost one).

def test_runs_stay_separate_no_merging():
    days = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 10)]
    assert len(_contiguous_ranges(days)) == 2


def test_fragmented_gaps_are_not_merged_into_one_span():
    """45 alternating gap days is 45 separate runs now — no rate-based
    "merging is cheaper" comparison is made any more, since there is no rate
    to compare with. More, smaller requests are the accepted trade for never
    guessing at cost."""
    days = [date(2026, 7, 1) + timedelta(days=2 * n) for n in range(20)]
    assert len(_contiguous_ranges(days)) == 20


def test_a_run_still_respects_the_direct_day_cap():
    days = [date(2026, 1, 1) + timedelta(days=n) for n in range(200)]
    ranges = _contiguous_ranges(days)
    assert all((end - start).days + 1 <= MAX_RANGE_DAYS for start, end in ranges)
    assert sum((end - start).days + 1 for start, end in ranges) == 200


# ── serving a ring from any purchase at its centre ───────────────────────────

_DAY = date(2026, 8, 1)
_SETTLED = datetime(2026, 9, 1, tzinfo=timezone.utc)   # fetched long after: final, not HOT


def _ring(radius_km: float) -> dict:
    return {"lat": 40.7500, "lng": -73.9893, "radius_km": radius_km}


def _coverage_db(rows: list[tuple]):
    """Coverage rows as covered_days_bulk selects them:
    (center_key, radius_m, date, fetched_at, truncated, window_days)."""

    class _Rows:
        def all(self):
            return rows

    class _DB:
        async def execute(self, stmt, params=None):
            return _Rows()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

    return lambda: _DB()


async def _covered(monkeypatch, request: dict, rows: list[tuple]) -> set:
    monkeypatch.setattr(uq, "AsyncSessionLocal", _coverage_db(rows))
    key = poi_key(request)
    return (await uq.covered_days_bulk({key: request}))[key]


@pytest.mark.asyncio
async def test_a_smaller_ring_is_served_by_a_larger_purchase(monkeypatch):
    """Every ping inside a 100 m ring is inside the 500 m ring at the same
    centre. Re-buying it on a radius edit cost calls and minutes for data
    already held."""
    center = uq.center_key(_ring(0.5))
    assert await _covered(
        monkeypatch, _ring(0.1), [(center, 500, _DAY, _SETTLED, False, 7)],
    ) == {_DAY}


@pytest.mark.asyncio
async def test_a_larger_ring_is_never_served_by_a_smaller_purchase(monkeypatch):
    """The live bug the radius in poi_key exists for: a 100 m purchase answering
    a 500 m question, across tenants."""
    center = uq.center_key(_ring(0.1))
    assert await _covered(
        monkeypatch, _ring(0.5), [(center, 100, _DAY, _SETTLED, False, 7)],
    ) == set()


@pytest.mark.asyncio
async def test_a_truncated_larger_purchase_does_not_serve_a_smaller_ring(monkeypatch):
    """A capped disc is a non-random sample, not a superset of the ring inside."""
    center = uq.center_key(_ring(0.5))
    uq._reset_truncation()
    try:
        assert await _covered(
            monkeypatch, _ring(0.1), [(center, 500, _DAY, _SETTLED, True, 1)],
        ) == set()
    finally:
        uq._reset_truncation()


@pytest.mark.asyncio
async def test_a_stale_hot_purchase_does_not_serve_a_smaller_ring(monkeypatch):
    center = uq.center_key(_ring(0.5))
    bought_hot = datetime(2026, 8, 2, tzinfo=timezone.utc)
    assert await _covered(
        monkeypatch, _ring(0.1), [(center, 500, _DAY, bought_hot, False, 7)],
    ) == set()


@pytest.mark.asyncio
async def test_coverage_from_before_centres_is_not_reused(monkeypatch):
    """A row with no recorded radius cannot say what it covers — re-bought once."""
    center = uq.center_key(_ring(0.1))
    assert await _covered(
        monkeypatch, _ring(0.1), [(center, None, _DAY, _SETTLED, False, None)],
    ) == set()


@pytest.mark.asyncio
async def test_a_day_truncated_inside_a_multi_day_window_is_repaired(monkeypatch):
    """Marked paid, a truncated day used to stay a partial sample forever. Bought
    inside a 7-day window, a narrower one can still get all of it — so it is a
    gap again, and the disclosure is set so the repair's window is halved."""
    ring = _ring(0.1)
    center = uq.center_key(ring)
    uq._reset_truncation()
    try:
        assert await _covered(
            monkeypatch, ring, [(center, 100, _DAY, _SETTLED, True, 7)],
        ) == set()
        assert poi_key(ring) in uq._TRUNCATED_FEATURES
    finally:
        uq._reset_truncation()


@pytest.mark.asyncio
@pytest.mark.parametrize("window_days", [1, None])
async def test_a_day_truncated_in_a_one_day_window_stays_covered(monkeypatch, window_days):
    """No finer split exists, so re-buying could not help. It stays covered and
    disclosed — and a legacy row that never recorded its window is not looped."""
    ring = _ring(0.1)
    center = uq.center_key(ring)
    uq._reset_truncation()
    try:
        assert await _covered(
            monkeypatch, ring, [(center, 100, _DAY, _SETTLED, True, window_days)],
        ) == {_DAY}
    finally:
        uq._reset_truncation()


@pytest.mark.asyncio
async def test_a_later_truncated_purchase_overrides_an_older_clean_row(monkeypatch):
    """persist_rows deletes+rewrites the WHOLE disc of whatever radius it just
    bought. A later, larger purchase that comes back truncated overwrote an
    older, smaller radius's pings with its partial sample too — even though
    that smaller radius's own coverage row still (falsely) says clean."""
    center = uq.center_key(_ring(0.5))
    later = _SETTLED + timedelta(days=1)
    uq._reset_truncation()
    try:
        assert await _covered(
            monkeypatch, _ring(0.03), [
                (center, 100, _DAY, _SETTLED, False, 7),
                (center, 500, _DAY, later, True, 7),
            ],
        ) == set()
    finally:
        uq._reset_truncation()


@pytest.mark.asyncio
async def test_a_later_clean_rebuy_overrides_an_older_truncated_row(monkeypatch):
    """The bound on spend: once the smaller ring is re-bought fresh, its own
    newer clean row governs again — the day does not stay poisoned forever."""
    center = uq.center_key(_ring(0.5))
    later = _SETTLED + timedelta(days=1)
    assert await _covered(
        monkeypatch, _ring(0.03), [
            (center, 500, _DAY, _SETTLED, True, 7),
            (center, 100, _DAY, later, False, 7),
        ],
    ) == {_DAY}


def test_a_radius_edit_down_costs_no_call_and_up_costs_one(monkeypatch):
    """The whole point, end to end through estimate_cost: 500 m bought, then
    100 m asked -> 0 calls; 100 m bought, then 500 m asked -> 1 call."""
    import asyncio

    day = date.today() - timedelta(days=10)
    fetched = datetime.now(timezone.utc)

    center = uq.center_key(_ring(0.5))
    monkeypatch.setattr(uq, "AsyncSessionLocal", _coverage_db([(center, 500, day, fetched, False, 1)]))
    assert asyncio.run(uq.estimate_cost([day.isoformat()], [_ring(0.1)]))["calls"] == 0

    monkeypatch.setattr(uq, "AsyncSessionLocal", _coverage_db([(center, 100, day, fetched, False, 1)]))
    assert asyncio.run(uq.estimate_cost([day.isoformat()], [_ring(0.5)]))["calls"] == 1


# ── the circuit breaker ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_breaker_opens_after_consecutive_failures(monkeypatch):
    """A call is committed to the ledger before the request returns, so during
    an outage every attempt reserved, fired, failed and paid — draining the
    shared monthly budget while returning nothing."""
    from app.core import config

    monkeypatch.setattr(config.settings, "UNACAST_BREAKER_THRESHOLD", 3, raising=False)
    monkeypatch.setattr(config.settings, "UNACAST_BREAKER_COOLDOWN_S", 300, raising=False)

    for _ in range(2):
        await _breaker_record(success=False)
    await _breaker_check()          # still closed

    await _breaker_record(success=False)
    with pytest.raises(UnacastCircuitOpen):
        await _breaker_check()


@pytest.mark.asyncio
async def test_breaker_state_is_shared_not_per_worker(monkeypatch):
    """The reason this moved out of module globals: Cloud Run runs the service
    at maxScale=5, so an open breaker in ONE worker did nothing about the other
    four, which kept reserving, firing and paying through the same outage.

    State now goes through a store the workers share. `opened_at` must be a wall
    clock, not time.monotonic() — monotonic clocks are per-process and would not
    be comparable between them.
    """
    from datetime import datetime, timezone

    from app.core import config

    monkeypatch.setattr(config.settings, "UNACAST_BREAKER_THRESHOLD", 1, raising=False)
    monkeypatch.setattr(config.settings, "UNACAST_BREAKER_COOLDOWN_S", 300, raising=False)

    await _breaker_record(success=False)

    failures, opened_at = await uq._BREAKER_STORE.load()
    assert failures == 1
    assert isinstance(opened_at, datetime), "must be a timestamp, not a monotonic float"
    assert opened_at.tzinfo is not None, "and timezone-aware, or workers cannot compare it"

    # A second "worker" reading the same store refuses too.
    with pytest.raises(UnacastCircuitOpen):
        await _breaker_check()

    assert (datetime.now(timezone.utc) - opened_at).total_seconds() < 60


def test_the_breaker_refuses_before_spending_anything():
    """The raise must happen ahead of reserve_call, or an open breaker still
    costs budget on every attempt."""
    import inspect

    src = inspect.getsource(uq.UnacastMAIDQuerier._run_batch)
    assert src.index("_breaker_check()") < src.index("reserve_call()")


@pytest.mark.asyncio
async def test_one_success_closes_the_breaker(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "UNACAST_BREAKER_THRESHOLD", 2, raising=False)
    await _breaker_record(success=False)
    await _breaker_record(success=False)
    with pytest.raises(UnacastCircuitOpen):
        await _breaker_check()

    await _breaker_record(success=True)
    await _breaker_check()          # closed again


@pytest.mark.asyncio
async def test_the_cooldown_half_opens_for_a_single_probe(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "UNACAST_BREAKER_THRESHOLD", 2, raising=False)
    monkeypatch.setattr(config.settings, "UNACAST_BREAKER_COOLDOWN_S", 0, raising=False)
    await _breaker_record(success=False)
    await _breaker_record(success=False)

    await _breaker_check()          # cooldown elapsed -> probe allowed
    # One more failure re-opens immediately rather than needing the full count.
    await _breaker_record(success=False)
    monkeypatch.setattr(config.settings, "UNACAST_BREAKER_COOLDOWN_S", 300, raising=False)
    with pytest.raises(UnacastCircuitOpen):
        await _breaker_check()


# ── truncation survives the process that observed it ─────────────────────────

def test_truncation_is_written_to_the_watermark():
    """`observationLimitHit` means this POI's pings are a partial, non-random
    sample and its frequency counts are FLOORS. That was recorded only in an
    in-process dict, so it died with the worker.

    Written from THIS response's truncated set: the process-wide record remembers
    every truncation ever seen, so reading it marked a POI's later, narrower
    windows truncated too."""
    import inspect

    src = inspect.getsource(uq.persist_rows)
    assert '"truncated": key in truncated_keys' in src
    assert "_TRUNCATED_FEATURES" not in src


def test_duplicate_pings_do_not_abort_the_persist():
    """The vendor returns the same (device, second) more than once in ONE
    response — seen live at Denver Union Station. A plain INSERT raised on
    uq_unacast_raw_poi_maid_ts and threw away an already-billed call."""
    from sqlalchemy.dialects import postgresql

    captured = {}

    class _Db:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def begin(self):
            return self

        async def execute(self, stmt, params=None):
            captured.setdefault("sql", []).append(str(stmt.compile(dialect=postgresql.dialect())))

    import asyncio

    orig = uq.AsyncSessionLocal
    uq.AsyncSessionLocal = lambda: _Db()
    try:
        row = {"poi_key": "k", "maid": "m", "lat": 1.0, "lng": 2.0,
               "observed_at": "2026-09-06T00:05:58+00:00", "forensic_flags": 0, "hot": True}
        asyncio.run(uq.persist_rows([row, dict(row, lat=1.1)], {}))
    finally:
        uq.AsyncSessionLocal = orig

    raw = [s for s in captured["sql"] if "INSERT INTO unacast_raw_observations" in s]
    # Untargeted: the per-centre index and the older per-purchase one can both fire.
    assert raw and "ON CONFLICT DO NOTHING" in raw[0]


def test_a_rehydrated_entry_does_not_crash_the_report():
    """A rehydrated entry knows THAT a fetch truncated but not by how much, so
    it carries fraction=None. Mixed with a real entry's float, min() raises
    TypeError rather than sorting None last — which would take down the whole
    extraction funnel at the moment it tried to disclose the truncation."""
    uq._reset_truncation()
    try:
        uq._TRUNCATED_FEATURES["measured"] = {
            "returned": 100_000, "possible": 7_000_000,
            "fraction": 0.0143, "devices": ("dev-1",),
        }
        uq._TRUNCATED_FEATURES["rehydrated"] = {
            "returned": None, "possible": None, "fraction": None, "devices": (),
        }

        report = uq.truncation_report()

        assert report["truncated_poi_count"] == 2, "both are still disclosed"
        assert report["worst_sampled_fraction"] == 0.0143
        assert report["under_sampled_devices"] == ["dev-1"]
    finally:
        uq._reset_truncation()


def test_truncation_is_rehydrated_for_a_cache_only_run():
    """The case the in-process dict could never cover: a warm watermark means NO
    API call, so parse_response never runs, so nothing populates the dict — and
    the user was told a sampled audience was complete. The watermark read is the
    one thing that always happens, so the disclosure is restored there."""
    import inspect

    src = inspect.getsource(uq.covered_days_bulk)
    assert "_cov.truncated" in src, "the watermark read must select the column"
    assert "_TRUNCATED_FEATURES" in src, "and repopulate the disclosure from it"


# ── retry accounting ─────────────────────────────────────────────────────────

def test_the_ledger_counts_real_requests_not_batches():
    """Retry lives in the transport and is lease-aware, so ONE reservation can
    cover several real HTTP requests. The vendor's other limit is a DAILY
    request limit per key, so counting batches made the ledger read low and we
    believed we had headroom we did not.

    `contacted` in UnacastClient._attempt already knew the true number — "a
    response of any status proves the request reached the vendor and was
    therefore metered". REQUESTS_MADE just publishes it.
    """
    import inspect

    from app.services.unacast_client import REQUESTS_MADE

    assert REQUESTS_MADE.get() == 0, "defaults to zero outside a request"

    src = inspect.getsource(uq.UnacastMAIDQuerier._run_batch)
    assert "REQUESTS_MADE.get()" in src, "the batch must report what was metered"
    assert "requests=requests" in src, "and pass it to the ledger"


def test_retry_is_not_duplicated_at_the_batch_level():
    """The transport owns retry, with a budget that will not start an attempt
    which cannot finish inside the concurrency lease this batch holds
    (unacast_client._retry_budget_s). A second loop here would fight it."""
    import inspect

    src = inspect.getsource(uq.UnacastMAIDQuerier._run_batch)
    assert "for attempt in range" not in src


def test_a_request_that_never_reached_the_vendor_is_not_charged():
    """UnacastNoContact means no response of any status came back, so nothing
    was metered — charging the shared monthly budget for it would be wrong."""
    import inspect

    from app.services.unacast_client import UnacastNoContact  # noqa: F401

    src = inspect.getsource(uq.UnacastMAIDQuerier._run_batch)
    # `fired` is derived from what was actually metered, not set blindly before
    # the request goes out.
    assert "fired=requests > 0" in src
    assert "fired = True" not in src


# ── lease margin ─────────────────────────────────────────────────────────────

def test_the_lease_outlives_the_whole_critical_section():
    """The lease is held across the HTTP call AND parse AND persist. When the
    margin over the request timeout was 45s, a large persist could eat it and
    the lease would be reaped as abandoned mid-call, over-admitting the gate."""
    from app.core.config import settings

    margin = settings.UNACAST_LEASE_STALE_AFTER_S - settings.UNACAST_REQUEST_TIMEOUT_S
    assert margin >= 120, f"only {margin}s for parse + persist"


# ── spend estimate ───────────────────────────────────────────────────────────

def _estimate(dates, pois, covered=None, monkeypatch=None, rate=0.0, cached=0):
    """Run estimate_cost with the watermark stubbed.

    The arithmetic is the thing under test, not the database. Reaching the real
    one also makes these tests order-dependent: the shared async engine binds
    its pool to whichever event loop created it, and pytest-asyncio gives each
    test a fresh loop. ``rate``/``cached`` are unused now that estimate_cost
    predicts nothing — kept as no-op parameters so existing call sites below
    don't need to change.
    """
    import asyncio as _asyncio

    from app.graph import unacast_query as _uq

    async def _fake(key_to_poi):
        return {k: set(covered or []) for k in key_to_poi}

    real = _uq.covered_days_bulk
    _uq.covered_days_bulk = _fake
    try:
        return _asyncio.run(_uq.estimate_cost(dates, pois))
    finally:
        _uq.covered_days_bulk = real


def test_the_estimate_packs_features_to_the_request_cap():
    """Free arithmetic over the watermark — no probe, no round trip. 12 fresh
    POIs is 12 features and therefore 2 calls, which is also the packing win:
    the old per-group loop would have made one call PER GROUP."""
    from app.graph.maid_query import build_date_list

    dates = build_date_list((date.today() - timedelta(days=1)).isoformat(), 7)
    pois = [
        {"lat": 40.0 + i * 0.01, "lng": -73.0 - i * 0.01, "radius_km": 0.1}
        for i in range(12)
    ]
    est = _estimate(dates, pois)
    assert est["features"] == 12
    assert est["calls"] == 2
    assert est["cached_pois"] == 0


def test_a_fully_cached_window_estimates_zero_calls():
    """Which is also the cheapest possible confirmation that the cache works."""
    from app.graph.maid_query import build_date_list

    dates = build_date_list((date.today() - timedelta(days=1)).isoformat(), 7)
    pois = [{"lat": 40.0, "lng": -73.0, "radius_km": 0.1}]
    covered = [date.fromisoformat(d) for d in dates]
    est = _estimate(dates, pois, covered=covered)
    assert est["calls"] == 0
    assert est["cached_pois"] == 1


def test_the_estimate_is_zero_with_nothing_to_buy():
    assert _estimate([], [{"lat": 1.0, "lng": 2.0, "radius_km": 0.1}])["calls"] == 0
    assert _estimate(["2026-09-01"], [])["calls"] == 0


# ── intersection over a failed group ─────────────────────────────────────────

def test_an_intersection_over_a_failed_group_raises():
    """The sharpest plausible-but-false case: one group's call errored, so its
    device set is empty, so the intersection is empty, so the user is told
    nobody visited both places — a confident answer to a question we never
    asked the vendor."""
    from app.services.maid_store import AudienceFilterUnevaluable, apply_audience_filter

    obs = [{
        "maid": "dev-1", "lat": 40.0, "lng": -73.0, "count": 1,
        "poi_ids": ["category:gym"], "poi_uids": ["a"],
        "visits": [{"ts": datetime.now(timezone.utc).isoformat(),
                    "dwell_lower_s": 600, "n_pings": 3}],
    }]
    status = {
        "category:gym": {"status": "ok"},
        "category:cafe": {"status": "failed", "error_kind": "UnacastBudgetExhausted"},
    }
    with pytest.raises(AudienceFilterUnevaluable):
        apply_audience_filter(
            obs,
            {"groups": ["category:gym", "category:cafe"], "op": "intersection"},
            pois=[{"lat": 40.0, "lng": -73.0}],
            group_status=status,
        )


def test_a_group_that_fetched_and_found_nobody_is_a_real_answer():
    """"Empty" and "failed" must stay distinguishable — an honest zero is a
    finding, and refusing to report it would be its own kind of wrong."""
    from app.services.maid_store import apply_audience_filter

    obs = [{
        "maid": "dev-1", "lat": 40.0, "lng": -73.0, "count": 1,
        "poi_ids": ["category:gym"], "poi_uids": ["a"], "visits": [],
    }]
    status = {
        "category:gym": {"status": "ok"},
        "category:cafe": {"status": "empty"},
    }
    assert apply_audience_filter(
        obs,
        {"groups": ["category:gym", "category:cafe"], "op": "intersection"},
        pois=[{"lat": 40.0, "lng": -73.0}],
        group_status=status,
    ) == []


def test_a_union_does_not_raise_on_a_failed_group():
    """A union degrades honestly — fewer groups, smaller audience — and needs
    the partial badge, not a refusal."""
    from app.services.maid_store import apply_audience_filter

    obs = [{
        "maid": "dev-1", "lat": 40.0, "lng": -73.0, "count": 1,
        "poi_ids": ["category:gym"], "poi_uids": ["a"],
        "visits": [{"ts": datetime.now(timezone.utc).isoformat(),
                    "dwell_lower_s": 600, "n_pings": 3}],
    }]
    status = {"category:cafe": {"status": "failed"}}
    assert apply_audience_filter(
        obs,
        {"groups": ["category:gym", "category:cafe"]},
        pois=[{"lat": 40.0, "lng": -73.0}],
        group_status=status,
    ) == ["dev-1"]


def test_failed_exclude_group_raises_even_under_union():
    """A failed POSITIVE group under union just narrows the audience — no
    guard needed (see the test above). A failed EXCLUDE group is the opposite
    of honest: "nobody visited my store" (because the query errored, not
    because it's true) means nobody gets excluded, so ads would ship to
    exactly the people the user asked to leave out. This must raise even
    though `op` is the default union."""
    from app.services.maid_store import AudienceFilterUnevaluable, apply_audience_filter

    obs = [{
        "maid": "dev-1", "lat": 40.0, "lng": -73.0, "count": 1,
        "poi_ids": ["category:gym"], "poi_uids": ["a"],
        "visits": [{"ts": datetime.now(timezone.utc).isoformat(),
                    "dwell_lower_s": 600, "n_pings": 3}],
    }]
    status = {
        "category:gym": {"status": "ok"},
        "store_set:my stores": {"status": "failed", "error_kind": "UnacastBudgetExhausted"},
    }
    with pytest.raises(AudienceFilterUnevaluable):
        apply_audience_filter(
            obs,
            {"groups": ["category:gym"], "exclude_groups": ["store_set:my stores"]},
            pois=[{"lat": 40.0, "lng": -73.0}],
            group_status=status,
        )


def test_partial_exclude_group_does_not_raise_under_union():
    """A PARTIAL exclude group (some of the store's POI keys failed) must not
    raise — nulling the whole filter over a partially-fetched exclusion is a
    worse outcome than a slightly leaky one. The caller (executors/maid.py)
    narrates the partial exclusion separately; this layer just keeps
    evaluating."""
    from app.services.maid_store import apply_audience_filter

    obs = [
        {"maid": "dev-1", "lat": 40.0, "lng": -73.0, "count": 1,
         "poi_ids": ["category:gym"], "poi_uids": ["a"],
         "visits": [{"ts": datetime.now(timezone.utc).isoformat(),
                     "dwell_lower_s": 600, "n_pings": 3}]},
        {"maid": "dev-2", "lat": 40.0, "lng": -73.0, "count": 1,
         "poi_ids": ["category:gym", "store_set:my stores"], "poi_uids": ["b"],
         "visits": [{"ts": datetime.now(timezone.utc).isoformat(),
                     "dwell_lower_s": 600, "n_pings": 3}]},
    ]
    status = {
        "category:gym": {"status": "ok"},
        "store_set:my stores": {"status": "partial"},
    }
    result = apply_audience_filter(
        obs,
        {"groups": ["category:gym"], "exclude_groups": ["store_set:my stores"]},
        pois=[{"lat": 40.0, "lng": -73.0}],
        group_status=status,
    )
    assert result == ["dev-1"]  # dev-2 still excluded — partial != ignored, just not fatal


def test_intersection_with_a_partial_group_no_longer_raises():
    """INTENTIONAL behavior change (thread 76e8a789, the CEO's dog-gear
    prompt: "vet clinic, PetSmart, and a dog park all within 45 days in
    Denver"): a "partial" group is the DEFAULT outcome for any city-scale
    category search (the vendor's 100k-observations-per-feature cap splits
    it), not a failure — the real thread's group_status showed all three
    groups "partial" with 10k-75k real rows each, and the old
    "partial raises, same as failed" rule nulled the ENTIRE intersection
    filter, silently falling back to the raw unfiltered union
    (17,250 == 17,250) with the explanation easy to miss in the stream. Only
    a genuinely FAILED group (zero rows) may still raise — see
    test_assert_groups_fetched.py for the full matrix (any_of, difference,
    min_distinct_groups, failed still raises)."""
    from app.services.maid_store import apply_audience_filter

    obs = [{
        "maid": "dev-1", "lat": 40.0, "lng": -73.0, "count": 1,
        "poi_ids": ["category:gym"], "poi_uids": ["a"],
        "visits": [{"ts": datetime.now(timezone.utc).isoformat(),
                    "dwell_lower_s": 600, "n_pings": 3}],
    }]
    status = {
        "category:gym": {"status": "ok"},
        "store_set:my stores": {"status": "partial"},
    }
    result = apply_audience_filter(
        obs,
        {"groups": ["category:gym"], "exclude_groups": ["store_set:my stores"],
         "op": "intersection"},
        pois=[{"lat": 40.0, "lng": -73.0}],
        group_status=status,
    )
    assert result == ["dev-1"]  # evaluates honestly instead of refusing outright


# ── reactive splitting on a real timeout, no prediction ──────────────────────
#
# max_days_per_feature/_split_range (rate-driven pre-sizing) are gone with the
# density atlas they were fed by. What replaces them is _split_request: a
# request is never sized down in advance, only halved AFTER an actual vendor
# timeout. See tests/test_unacast_query.py for _split_request itself.

def _days_between(a: date, b: date) -> list[date]:
    return [a + timedelta(days=n) for n in range((b - a).days + 1)]


def test_plan_requests_needs_no_rate_argument():
    """plan_requests packs by legality limits (feature count, MAX_RANGE_DAYS)
    only — no predicted-volume argument exists to pass any more."""
    import inspect

    sig = inspect.signature(uq.plan_requests)
    assert "rates" not in sig.parameters
    assert "target" not in sig.parameters


# ── visit-gap threshold ──────────────────────────────────────────────────────

def test_the_gap_is_recorded_on_every_visit():
    """The threshold swings visit counts by 2x end to end (5 min -> 46,137
    visits, 120 min -> 22,279 on real data), so a stored extraction that does
    not record which one it used cannot be compared or re-derived."""
    from app.graph.maid_query import cluster_visits

    v = cluster_visits(["2026-09-01T12:00:00+00:00"], gap_minutes=45)[0]
    assert v["gap_s"] == 45 * 60


def test_the_gap_can_differ_by_category(monkeypatch):
    """A forecourt stop and an afternoon at a mall are not the same shape, and
    one global constant has to be wrong for one of them."""
    from app.core import config
    from app.graph.maid_query import gap_minutes_for

    monkeypatch.setattr(
        config.settings, "MAID_VISIT_GAP_BY_CATEGORY",
        "gas station:10,shopping mall:45", raising=False,
    )
    assert gap_minutes_for("gas station") == 10
    assert gap_minutes_for("shopping mall") == 45
    assert gap_minutes_for("gym") == 20          # unlisted -> global default
    assert gap_minutes_for(None) == 20


def test_a_malformed_category_override_falls_back(monkeypatch):
    from app.core import config
    from app.graph.maid_query import gap_minutes_for

    monkeypatch.setattr(
        config.settings, "MAID_VISIT_GAP_BY_CATEGORY", "gym:not-a-number", raising=False,
    )
    assert gap_minutes_for("gym") == 20


# ── density atlas / rate prediction: gone entirely ───────────────────────────

def test_no_rate_prediction_survives():
    """observed_daily_rate/planning_rates/the density atlas are deleted along
    with the size prediction they fed — unacast_query.py sizes nothing from
    history any more, only from the vendor's own legality limits."""
    assert not hasattr(uq, "observed_daily_rate")
    assert not hasattr(uq, "planning_rates")
    assert not hasattr(uq, "density_priors")
    assert not hasattr(uq, "prior_density")
    assert not hasattr(uq, "learn_densities")
    assert not hasattr(uq, "record_densities")
    assert not hasattr(uq, "raise_densities")


# ── a busy slot pool is not the vendor's fault, and costs nothing ────────────

@pytest.mark.asyncio
async def test_a_slot_timeout_is_not_billed_and_does_not_trip_the_breaker(monkeypatch):
    """Two bugs in one path.

    `REQUESTS_MADE` is a ContextVar, and it used to be reset only AFTER a
    concurrency slot was acquired. A slot timeout then read whatever an earlier
    call in the same task left behind, reported `fired=True`, and charged the
    shared monthly budget for a request that never went out.

    The same timeout was also recorded as a vendor failure, so a few congested
    minutes on our own pool opened the breaker against a healthy API.
    """
    from app.services import unacast_client as uc

    reconciled: dict = {}

    async def _reserve(**_kw):
        return True

    async def _reconcile(*, fired, observations=0, requests=0, period=None):
        reconciled.update(fired=fired, requests=requests)

    async def _no_slot(writer=None):
        raise uq.UnacastConcurrencyTimeout("pool busy")

    monkeypatch.setattr(uq, "reserve_call", _reserve)
    monkeypatch.setattr(uq, "reconcile_call", _reconcile)
    monkeypatch.setattr(uq, "wait_for_slot", _no_slot)

    uc.REQUESTS_MADE.set(3)          # left behind by an earlier call in this task
    querier = uq.UnacastMAIDQuerier(client=object())
    with pytest.raises(uq.UnacastConcurrencyTimeout):
        await querier._run_batch([], {}, {})

    assert reconciled == {"fired": False, "requests": 0}
    failures, opened_at = await uq._BREAKER_STORE.load()
    assert failures == 0 and opened_at is None


# ── only vendor-health failures count toward the platform-wide breaker ───────

def _batch_querier(monkeypatch, client):
    """A querier whose admission paths all succeed, so only `client` decides."""

    async def _reserve(**_kw):
        return True

    async def _reconcile(**_kw):
        return None

    async def _slot(writer=None):
        return "lease"

    async def _release(_lease):
        return None

    monkeypatch.setattr(uq, "reserve_call", _reserve)
    monkeypatch.setattr(uq, "reconcile_call", _reconcile)
    monkeypatch.setattr(uq, "wait_for_slot", _slot)
    monkeypatch.setattr(uq, "release_concurrency_slot", _release)
    return uq.UnacastMAIDQuerier(client=client)


def _failure(name: str) -> Exception:
    import httpx

    from app.services import unacast_client as uc

    return {
        "rejected_400": uc.UnacastRequestRejected(400, {"message": "outside coverage"}, "u"),
        "server_503": uc.UnacastAPIError(503, "unavailable", "u"),
        "daily_429": uc.UnacastRateLimited(429, "daily limit", "u"),
        "ip_403": uc.UnacastIPNotAllowlisted(403, {"message": "Unauthorized IP address."}, "u"),
        "read_timeout": httpx.ReadTimeout("too heavy to answer"),
        "connection_reset": httpx.ConnectError("reset"),
        "our_own_bug": RuntimeError("something on our side"),
    }[name]


@pytest.mark.asyncio
@pytest.mark.parametrize("name, counts", [
    ("rejected_400", False),
    ("server_503", True),
    ("daily_429", True),
    ("ip_403", True),
    ("read_timeout", False),
    ("connection_reset", True),
    ("our_own_bug", False),
])
async def test_only_vendor_health_failures_count_toward_the_breaker(monkeypatch, name, counts):
    """The breaker is shared by every tenant. It used to count any exception, so
    one tenant's out-of-coverage search, a dense-ring timeout or a bug on our
    side paused audiences for everyone."""
    exc = _failure(name)

    class _Client:
        async def post(self, *_a, **_k):
            raise exc

    querier = _batch_querier(monkeypatch, _Client())
    with pytest.raises(type(exc)):
        await querier._run_batch([], {}, {})

    failures, _opened = await uq._BREAKER_STORE.load()
    assert failures == (1 if counts else 0)


@pytest.mark.asyncio
async def test_a_vendor_that_answered_is_healthy_even_if_our_persist_fails(monkeypatch):
    class _Client:
        async def post(self, *_a, **_k):
            return {"features": []}

    async def _broken_persist(*_a, **_k):
        raise RuntimeError("database unavailable")

    querier = _batch_querier(monkeypatch, _Client())
    monkeypatch.setattr(uq, "persist_rows", _broken_persist)
    await _breaker_record(success=False)
    await _breaker_record(success=False)

    with pytest.raises(RuntimeError):
        await querier._run_batch([], {}, {})

    failures, _opened = await uq._BREAKER_STORE.load()
    assert failures == 0


@pytest.mark.asyncio
async def test_only_one_worker_probes_when_the_cooldown_ends(monkeypatch):
    """The half-open probe was a load then a save, so every worker that read the
    elapsed cooldown went through at once. Now the first check claims the probe
    and the next still sees the breaker shut while that probe runs."""
    from app.core import config

    monkeypatch.setattr(config.settings, "UNACAST_BREAKER_THRESHOLD", 1, raising=False)
    monkeypatch.setattr(config.settings, "UNACAST_BREAKER_COOLDOWN_S", 300, raising=False)
    await _breaker_record(success=False)
    failures, _opened = await uq._BREAKER_STORE.load()
    await uq._BREAKER_STORE.save(failures, datetime.now(timezone.utc) - timedelta(seconds=301))

    await _breaker_check()                      # this worker claims the probe
    with pytest.raises(UnacastCircuitOpen):
        await _breaker_check()                  # the next one does not


@pytest.mark.asyncio
async def test_a_probe_claim_loses_to_one_that_moved_first():
    """Two workers that read the same opened_at: only one compare-and-set wins."""
    seen = datetime.now(timezone.utc) - timedelta(seconds=301)
    await uq._BREAKER_STORE.save(1, seen)
    until = datetime.now(timezone.utc)

    assert await uq._BREAKER_STORE.claim_probe(seen, until, 0) is True
    assert await uq._BREAKER_STORE.claim_probe(seen, until, 0) is False


# ── a re-bought day replaces its rows ────────────────────────────────────────

def test_a_rebought_day_replaces_its_old_rows(monkeypatch):
    """A HOT day re-bought after it went COLD was inserted with skip-on-conflict
    beside its stale copies, so the correction that was paid for never landed.
    The batch's own days are deleted first, in the same transaction, scoped to
    the centre and the purchased disc — and legacy rows of the same purchase."""
    import asyncio

    from sqlalchemy.dialects import postgresql

    statements: list[tuple[str, dict | None]] = []

    class _Db:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        def begin(self):
            return self

        async def execute(self, stmt, params=None):
            statements.append((str(stmt.compile(dialect=postgresql.dialect())), params))

    monkeypatch.setattr(uq, "AsyncSessionLocal", lambda: _Db())
    poi = _ring(0.1)
    key = poi_key(poi)
    bought = {date(2026, 9, 1): 3, date(2026, 9, 2): 3, date(2026, 9, 5): 1}
    row = {"poi_key": key, "maid": "m", "lat": poi["lat"], "lng": poi["lng"],
           "observed_at": datetime(2026, 9, 1, 12, tzinfo=timezone.utc),
           "forensic_flags": 0, "hot": False}

    asyncio.run(uq.persist_rows([row], {key: bought}, set(), key_to_poi={key: poi}))

    deletes = [i for i, (sql, _p) in enumerate(statements) if sql.startswith("DELETE")]
    insert = next(i for i, (sql, _p) in enumerate(statements)
                  if sql.startswith("INSERT INTO unacast_raw_observations"))
    assert len(deletes) == 2, "one per contiguous run: Sep 1-2 and Sep 5"
    assert all(i < insert for i in deletes)
    params = statements[deletes[0]][1]
    assert params["c"] == uq.center_key(poi) and params["k"] == key
    assert params["start"] == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert params["stop"] == datetime(2026, 9, 3, tzinfo=timezone.utc)
    assert params["r2"] == pytest.approx(100.0 ** 2)
    assert row["center_key"] == uq.center_key(poi)
    coverage = next(sql for sql, _p in statements if "unacast_fetch_coverage" in sql)
    assert "center_key" in coverage and "radius_m" in coverage and "window_days" in coverage
