"""
tests/test_unacast_request_sizing.py
────────────────────────────────────
Requests are packed by the vendor's own legality limits only (feature count,
MAX_RANGE_DAYS) — never a predicted size — and a request that times out is
split smaller and retried, recursively, rather than refused up front or
repeated as-is.

Thread 77e403d3: ten dense Midtown POIs over 30 days went out as one request,
never answered inside the 195 s timeout, and were re-sent four times — 13
minutes of a silent stream and an audience of zero. Threads 237aca1b/a10b211a:
a 24M/785K-observation PREDICTION refused two searches outright before a
single call was made — the prediction itself (learned from pre-truncation
response totals) was wrong, and the fix is to never predict at all.

No database and no network anywhere in this file.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx
import pytest

from app.core.config import settings
from app.graph import unacast_query as uq


@pytest.fixture(autouse=True)
def _clean_state():
    uq._breaker_reset()
    uq._reset_truncation()
    yield
    uq._breaker_reset()
    uq._reset_truncation()


def _days(n: int, end: date = date(2026, 9, 10)) -> list[date]:
    return [end - timedelta(days=i) for i in range(n)][::-1]


def _pois(n: int, radius_km: float = 0.04) -> dict[str, dict]:
    return {
        f"k{i}": {"lat": 40.75 + i * 0.001, "lng": -73.99, "radius_km": radius_km}
        for i in range(n)
    }


def _bought(plan) -> list:
    return sorted((s.key, d) for req in plan for s in req for d in s.days)


# ── the planner: legality limits only ────────────────────────────────────────

def test_ten_pois_pack_into_two_requests():
    """The endpoint's hard cap is 10 features/request — no volume estimate is
    consulted, only feature count."""
    pois = _pois(15)
    gaps = {k: _days(7) for k in pois}

    plan = uq.plan_requests(pois, gaps)

    assert [len(req) for req in plan] == [10, 5]
    assert _bought(plan) == sorted((k, d) for k, dd in gaps.items() for d in dd)


def test_a_30_day_gap_is_not_pre_split_by_volume():
    """The old planner cut a busy POI's window down using a predicted rate
    (max_days_per_feature). There is no such prediction any more: a single
    contiguous 30-day gap is ONE span (MAX_RANGE_DAYS is 90), whatever the POI's
    real density — an oversized request is handled reactively, by
    _split_request, on an actual timeout."""
    pois = _pois(1)
    gaps = {"k0": _days(30)}

    plan = uq.plan_requests(pois, gaps)

    assert len(plan) == 1
    assert len(plan[0]) == 1
    span = plan[0][0]
    assert (span.end - span.start).days + 1 == 30


def test_a_dense_237aca1b_shape_is_accepted_not_refused():
    """The exact thread that used to refuse outright: one POI whose real
    density (~502,744 obs/day) would have predicted 24,066,448 pings over the
    window. No prediction is made any more, so it is planned like any other
    POI — the vendor's own per-feature truncation (disclosed separately,
    truncation_report) is what actually happens to it, not a refusal."""
    pois = _pois(1)
    gaps = {"k0": _days(48)}   # the 24M-ping thread's window shape

    plan = uq.plan_requests(pois, gaps)

    assert plan   # planned, not refused
    assert sum(len(req) for req in plan) >= 1


def test_gap_runs_are_each_their_own_span_no_merging():
    """_merged_ranges (a rate-driven "is merging cheaper" decision) is gone.
    plan_requests calls _contiguous_ranges directly: every run is its own
    span, always."""
    pois = _pois(1)
    days = [date(2026, 7, 1) + timedelta(days=2 * n) for n in range(20)]  # 20 isolated gap days
    gaps = {"k0": days}

    plan = uq.plan_requests(pois, gaps)

    spans = [s for req in plan for s in req]
    assert len(spans) == 20
    assert all(len(s.days) == 1 for s in spans)


def test_plan_requests_signature_has_no_size_arguments():
    import inspect

    sig = inspect.signature(uq.plan_requests)
    assert set(sig.parameters) & {"rates", "target"} == set()


# ── _split_request: reactive halving, no prediction ──────────────────────────

def _span(key, start, end):
    days = [start + timedelta(days=n) for n in range((end - start).days + 1)]
    return uq._Span(key, start, end, days)


def test_ten_features_split_five_and_five():
    req = [_span(f"k{i}", date(2026, 9, 1), date(2026, 9, 1)) for i in range(10)]
    halves = uq._split_request(req)
    assert [len(h) for h in halves] == [5, 5]


def test_a_thirty_day_span_splits_fifteen_and_fifteen():
    req = [_span("k0", date(2026, 9, 1), date(2026, 9, 30))]
    halves = uq._split_request(req)
    assert len(halves) == 2
    (a,), (b,) = halves
    assert (a.end - a.start).days + 1 == 15
    assert (b.end - b.start).days + 1 == 15
    assert a.end + timedelta(days=1) == b.start
    # No gap, no overlap, no day lost.
    assert set(a.days) | set(b.days) == set(_span("k0", date(2026, 9, 1), date(2026, 9, 30)).days)


def test_a_further_timeout_halves_again_to_seven_and_eight():
    req = [_span("k0", date(2026, 9, 1), date(2026, 9, 15))]   # one of the 15-day halves above
    halves = uq._split_request(req)
    lengths = sorted((h[0].end - h[0].start).days + 1 for h in halves)
    assert lengths == [7, 8]


def test_a_single_day_single_feature_cannot_split_further():
    req = [_span("k0", date(2026, 9, 1), date(2026, 9, 1))]
    assert uq._split_request(req) == []


# ── the runner: reactive split on a real timeout, never a repeat ────────────

def _runner(monkeypatch, *, fail_when):
    """A querier whose batches fail by rule — no rates, no DB."""
    calls: list[int] = []

    async def _batch(features, key_to_poi, key_days, *, writer=None):
        calls.append(len(features))
        await asyncio.sleep(0.01)
        if fail_when(features):
            raise httpx.ReadTimeout("too heavy")

    querier = uq.UnacastMAIDQuerier(client=object())
    monkeypatch.setattr(querier, "_run_batch", _batch)
    return querier, calls


@pytest.mark.asyncio
async def test_a_timed_out_request_is_split_not_repeated(monkeypatch):
    pois = _pois(10)
    gaps = {k: [date(2026, 9, 1)] for k in pois}
    querier, calls = _runner(monkeypatch, fail_when=lambda f: len(f) == 10)

    await querier._fetch_gaps(pois, gaps)

    assert calls == [10, 5, 5]   # one big request, then two halves that both succeed


@pytest.mark.asyncio
async def test_repeated_timeouts_keep_halving_until_they_succeed(monkeypatch):
    pois = _pois(4)
    gaps = {k: [date(2026, 9, 1)] for k in pois}
    querier, calls = _runner(monkeypatch, fail_when=lambda f: len(f) > 1)

    await querier._fetch_gaps(pois, gaps)

    assert calls == [4, 2, 2, 1, 1, 1, 1]


@pytest.mark.asyncio
async def test_a_request_that_cannot_be_split_raises_request_timeout(monkeypatch):
    """One POI, one day: _split_request returns [] and the caller raises
    UnacastRequestTimeout instead of re-sending the identical body."""
    pois = _pois(1)
    querier, calls = _runner(monkeypatch, fail_when=lambda f: True)

    with pytest.raises(uq.UnacastRequestTimeout):
        await querier._fetch_gaps(pois, {"k0": [date(2026, 9, 1)]})

    assert calls == [1]
    from app.graph.maid_query import NonRetryableMAIDQueryError

    assert issubclass(uq.UnacastRequestTimeout, NonRetryableMAIDQueryError)


@pytest.mark.asyncio
async def test_a_long_extraction_keeps_talking(monkeypatch):
    pois = _pois(2)
    gaps = {k: [date(2026, 9, 1)] for k in pois}
    querier, _calls = _runner(monkeypatch, fail_when=lambda f: False)
    monkeypatch.setattr(uq, "_HEARTBEAT_S", 0.005)
    events: list[dict] = []

    await querier._fetch_gaps(pois, gaps, writer=events.append)

    updates = [e["content"] for e in events if e["type"] == "update"]
    assert updates and all("spot(s) done" in u for u in updates)


# ── unique Feature ids (thread 0aa5fa49: 400 "Duplicate Feature ID") ────────

def test_a_pois_two_gap_runs_get_distinct_feature_ids():
    """One POI whose uncached days form two runs is two spans with the same key,
    packed into ONE request by first-fit. Sending the bare key as the id made
    the vendor reject the whole request; ids must be unique per span."""
    pois = _pois(2)
    gaps = {
        "k0": [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 5)],   # two runs
        "k1": [date(2026, 9, 1)],
    }
    plan = uq.plan_requests(pois, gaps)
    assert len(plan) == 1 and len(plan[0]) == 3   # the collision shape

    features, k2p, _days_by_key = uq._batch_args(plan[0], pois)

    ids = [f["id"] for f in features]
    assert len(ids) == len(set(ids)), f"duplicate Feature ids: {ids}"
    assert set(k2p) == {"k0", "k1"}   # attribution still keyed by the POI


def test_parse_response_reads_the_poi_key_back_out_of_a_span_id():
    pois = _pois(1)
    plan = uq.plan_requests(pois, {"k0": [date(2026, 9, 1), date(2026, 9, 5)]})
    features, k2p, _d = uq._batch_args(plan[0], pois)
    obs = {"timestampEpochMS": 1_788_000_000_000, "latitude": 40.75, "longitude": -73.99}
    payload = {"features": [
        {"id": features[0]["id"], "properties": {"observationsPerDevice": [
            {"advertiserID": "dev-1", "observations": [obs]}]}},
        {"id": features[1]["id"], "properties": {
            "observationLimitHit": True, "observationCount": 1,
            "totalPossibleObservationCount": 9,
            "observationsPerDevice": [{"advertiserID": "dev-2", "observations": [obs]}]}},
    ]}

    rows, _total, truncated = uq.parse_response(payload, k2p)

    assert {r["poi_key"] for r in rows} == {"k0"}
    assert truncated == {"k0"}


# ── a half-open probe must not cost the batches that lost the claim ──────────
# (thread 23f83f99: the probe succeeded, 4 of 5 batches were dropped anyway)

@pytest.mark.asyncio
async def test_batches_that_lose_the_probe_claim_are_retried_once(monkeypatch):
    pois = _pois(30)   # 3 requests
    gaps = {k: [date(2026, 9, 1)] for k in pois}
    ran: list[int] = []
    probe_done = asyncio.Event()

    async def _batch(features, key_to_poi, key_days, *, writer=None):
        if not probe_done.is_set() and ran:          # everyone after the first loses
            raise uq.UnacastCircuitOpen("probe in flight")
        ran.append(len(features))
        await asyncio.sleep(0.01)
        probe_done.set()

    querier = uq.UnacastMAIDQuerier(client=object())
    monkeypatch.setattr(querier, "_run_batch", _batch)

    await querier._fetch_gaps(pois, gaps)

    assert sorted(ran) == [10, 10, 10]   # all three landed; none dropped


@pytest.mark.asyncio
async def test_a_breaker_that_stays_open_still_raises(monkeypatch):
    pois = _pois(1)

    async def _batch(features, key_to_poi, key_days, *, writer=None):
        raise uq.UnacastCircuitOpen("still open")

    querier = uq.UnacastMAIDQuerier(client=object())
    monkeypatch.setattr(querier, "_run_batch", _batch)

    with pytest.raises(uq.UnacastCircuitOpen):
        await querier._fetch_gaps(pois, {"k0": [date(2026, 9, 1)]})


# ── no extraction-size ceiling of any kind ───────────────────────────────────

def test_there_is_no_extraction_size_ceiling():
    """Deleted along with the density atlas that fed it — a search is never
    refused for being large; a request too big for the vendor to answer times
    out and is split (above), not pre-judged."""
    assert not hasattr(uq, "UnacastExtractionTooLarge")
    assert not hasattr(uq, "_check_extraction_size")
    assert not hasattr(settings, "UNACAST_MAX_EXTRACTION_OBS")
    assert not hasattr(settings, "UNACAST_MAX_EXTRACTION_ETA_S")


@pytest.mark.asyncio
async def test_a_huge_predicted_shape_is_never_refused(monkeypatch):
    """The exact numbers from the log threads this fix closes: 785,790 and
    24,066,448 predicted pings used to raise UnacastExtractionTooLarge before
    a single call was reserved. Nothing here predicts a volume at all any
    more, so a request this size is simply planned and sent."""
    pois = _pois(4)
    querier, calls = _runner(monkeypatch, fail_when=lambda f: False)

    await querier._fetch_gaps(pois, {k: _days(48) for k in pois})

    assert calls   # actually attempted, not refused


# ── a fetch that fails part-way keeps what landed ────────────────────────────

def _partial_querier(monkeypatch, *, fetched: set, error: Exception, rows: list):
    """query_maids with every DB path stubbed: the `fetched` keys land (their
    days become covered) and then the fetch raises `error`."""
    covered_now: dict[str, set] = {}

    async def _covered(key_to_poi):
        return {k: set(covered_now.get(k, ())) for k in key_to_poi}

    async def _read(key_to_poi, days):
        return list(rows)

    monkeypatch.setattr(uq, "covered_days_bulk", _covered)
    monkeypatch.setattr(uq, "read_cached", _read)
    querier = uq.UnacastMAIDQuerier(client=object())

    async def _fetch(key_to_poi, gaps, *, writer=None):
        for k in fetched:
            covered_now[k] = set(gaps[k])
        raise error

    monkeypatch.setattr(querier, "_fetch_gaps", _fetch)
    monkeypatch.setattr(querier, "_gate", lambda rows, key_to_poi, writer=None: rows)
    return querier


def _two_spots():
    from datetime import datetime, timezone

    day = (datetime.now(timezone.utc).date() - timedelta(days=2)).isoformat()
    a = {"lat": 40.75, "lng": -73.99, "radius_km": 0.1}
    b = {"lat": 40.76, "lng": -73.98, "radius_km": 0.1}
    return day, a, b


@pytest.mark.asyncio
async def test_a_part_failed_fetch_keeps_what_landed(monkeypatch):
    """The first error used to skip the cache read entirely, so 19 good batches
    of 20 became an empty, failed audience. What landed is paid for and kept,
    and the caller is told exactly which spots are still missing."""
    day, a, b = _two_spots()
    row = {"poi_key": uq.poi_key(a), "maid": "dev-1", "ts": f"{day}T12:00:00+00:00"}
    querier = _partial_querier(
        monkeypatch, fetched={uq.poi_key(a)},
        error=uq.UnacastConcurrencyTimeout("pool busy"), rows=[row],
    )
    failures: dict = {}

    rows = await querier.query_maids([day], [a, b], failures=failures)

    assert rows == [row]
    assert failures["failed_keys"] == {uq.poi_key(b)}
    assert isinstance(failures["error"], uq.UnacastConcurrencyTimeout)


@pytest.mark.asyncio
async def test_a_fetch_that_landed_nothing_is_still_a_failure(monkeypatch):
    """With nothing to show, a partial result would read as "nobody visited"."""
    day, a, b = _two_spots()
    querier = _partial_querier(
        monkeypatch, fetched=set(), error=uq.UnacastConcurrencyTimeout("pool busy"), rows=[],
    )
    with pytest.raises(uq.UnacastConcurrencyTimeout):
        await querier.query_maids([day], [a, b], failures={})


@pytest.mark.asyncio
async def test_without_a_failures_dict_the_error_still_raises(monkeypatch):
    day, a, b = _two_spots()
    row = {"poi_key": uq.poi_key(a), "maid": "dev-1", "ts": f"{day}T12:00:00+00:00"}
    querier = _partial_querier(
        monkeypatch, fetched={uq.poi_key(a)},
        error=uq.UnacastConcurrencyTimeout("pool busy"), rows=[row],
    )
    with pytest.raises(uq.UnacastConcurrencyTimeout):
        await querier.query_maids([day], [a, b])


@pytest.mark.asyncio
async def test_the_executor_marks_the_partial_run_and_keeps_its_rows():
    """_query_maids_with_retry turns the partial into rows plus a `partial` log
    entry naming the missing spots — not `status: error` with no rows."""
    from app.graph.builder.executors.maid import _query_maids_with_retry

    class _Partial:
        calls = 0

        async def query_maids(self, dates, pois, *, writer=None, failures=None):
            self.calls += 1
            failures.update(error=uq.UnacastConcurrencyTimeout("pool busy"), failed_keys={"kb"})
            return [{"maid": "dev-1"}]

    q = _Partial()
    rows, log = await _query_maids_with_retry(q, dates=["2026-09-01"], pois=[{}])

    assert q.calls == 1, "a non-retryable partial is kept, not retried"
    assert rows == [{"maid": "dev-1"}]
    assert log["status"] == "partial" and log["failed_keys"] == ["kb"]
    assert log["error_kind"] == "UnacastConcurrencyTimeout"
