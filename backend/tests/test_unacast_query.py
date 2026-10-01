"""Tests for the Unacast MAID querier (app/graph/unacast_query.py) and the
executor code that folds its rows (executors/maid.py).

Pure-logic coverage only — no DB, no network. What's here is the logic that
would silently corrupt an audience if it broke:

  * the response translator (a shape change = silently wrong audiences)
  * the POI key (must match between the querier and the executor)
  * the poi_key fold (pings -> one row per device per POI)
  * gap-range collapsing (a wrong range = re-buying data or missing days)
  * identity extraction (advertiserID preferred over registrationID)
"""
from datetime import date, timedelta

import pytest

from app.graph.unacast_query import (
    _contiguous_ranges,
    _dates_to_days,
    _extract_maid,
    build_feature,
    parse_response,
    poi_key,
)


# ── querier lifecycle ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_closing_the_querier_closes_the_http_pool():
    """The querier caches one httpx.AsyncClient in get_maid_querier's module
    global, so its connection pool outlives every request. The app lifespan
    closes it beside the checkpointer and Redis."""
    from app.graph import maid_query as mq

    closed: list[bool] = []

    class _FakeClient:
        async def aclose(self):
            closed.append(True)

    class _FakeQuerier:
        def __init__(self):
            self._client = _FakeClient()

    mq._querier = _FakeQuerier()
    await mq.close_maid_querier()

    assert closed == [True]
    assert mq._querier is None, "a closed client must not be handed out again"


@pytest.mark.asyncio
async def test_closing_is_a_no_op_without_a_client():
    """A querier that never built its client has nothing to close, and shutdown
    must not raise on the way out."""
    from app.graph import maid_query as mq

    mq._querier = None
    await mq.close_maid_querier()          # must not raise

    class _NoClientYet:
        pass

    mq._querier = _NoClientYet()
    await mq.close_maid_querier()          # no _client attribute
    assert mq._querier is None


def test_no_token_means_no_querier(monkeypatch):
    """An unset token disables extraction — there is no second backend to fall
    back to, and callers report the step as skipped."""
    from app.core import config
    from app.graph import maid_query as mq

    monkeypatch.setattr(config.settings, "UNACAST_API_TOKEN", "", raising=False)
    mq._querier = None
    assert mq.get_maid_querier() is None


# ── identity ─────────────────────────────────────────────────────────────────

def test_extract_maid_prefers_advertiser_id():
    """advertiserID is the real MAID; registrationID is Unacast's pseudonym.
    When the vendor enables advertiserID mode this must switch with no code
    change — that's the whole point of the preference order."""
    assert _extract_maid({"advertiserID": "real-maid", "registrationID": "pseudo"}) == "real-maid"
    assert _extract_maid({"registrationID": "pseudo", "advertiserID": None}) == "pseudo"
    assert _extract_maid({"registrationID": "pseudo"}) == "pseudo"
    assert _extract_maid({}) is None


# ── POI identity ─────────────────────────────────────────────────────────────

def test_poi_key_is_geometry_and_radius_only():
    """The querier computes keys from stripped ``{lat, lng, radius_km}`` payloads
    and the executor from full POI dicts. Mixing the place name into the key made
    those two never match, so every group read as "empty" and attribution fell
    back to a geometric scan. The key must come out the same from either shape."""
    full = {"lat": 40.7608, "lng": -73.9733, "radius_km": 0.1, "name": "Times Square Cafe",
            "source_angle": "competitor_brand", "parent_poi_type": "Sephora"}
    stripped = {"lat": 40.7608, "lng": -73.9733, "radius_km": 0.1}

    assert poi_key(full) == poi_key(stripped)
    assert poi_key(full) != poi_key({**full, "radius_km": 0.5})
    assert poi_key(full) != poi_key({**full, "lat": 40.7700})
    assert poi_key({"name": "no coords"}) is None


# ── the fold key ─────────────────────────────────────────────────────────────

def test_spot_key_is_the_vendors_own_attribution():
    """`poi_key` is the response feature's id — the key we sent — so the vendor
    already told us which place this ping belongs to. Folding on it means all of
    a device's pings at one POI become ONE visit.

    Regression guard on the H3 fold this replaced: a res-10 cell is ~132 m
    across while a 100 m ring spans several, so a visit that drifted inside a
    single store split into two visits with half the dwell each. Measured at
    26.1% of device-POI pairs and +14.5% visit inflation on 287k real pings.
    """
    from app.graph.builder.executors.maid import _spot_key

    assert _spot_key({"poi_key": "abc123"}) == "abc123"
    assert _spot_key({"poi_key": "store1"}) != _spot_key({"poi_key": "store2"})
    assert _spot_key({}) is None


def test_the_fold_keeps_frequency_and_clusters_visits():
    """`run_maid_query` counts pings under (maid, poi_key) and must read the
    frequency back under the SAME key — a second index keyed on exact
    coordinates never matches jittered GPS pings, leaving every device at
    count=1 with no visits, which zeroes every time-based predicate."""
    from app.graph.builder.executors.maid import _finish_fold, _fold_row, _new_fold

    rows = [
        {"maid": "dev-1", "lat": 40.759400, "lng": -73.969800,
         "ts": "2026-09-01T12:00:00+00:00", "poi_key": "keyA"},
        {"maid": "dev-1", "lat": 40.759420, "lng": -73.969820,
         "ts": "2026-09-01T12:04:00+00:00", "poi_key": "keyA"},
        {"maid": "dev-1", "lat": 40.759380, "lng": -73.969790,
         "ts": "2026-09-03T18:00:00+00:00", "poi_key": "keyA"},
        # No attribution: not evidence for any POI, so it is not folded at all.
        {"maid": "dev-2", "lat": 40.0, "lng": -73.0, "ts": "2026-09-01T12:00:00+00:00"},
    ]
    fold = _new_fold()
    for row in rows:
        _fold_row(fold, row)
    out = _finish_fold(fold, {})

    assert len(out) == 1, "jittered pings at one POI must dedup to one row"
    dot = out[0]
    assert dot["maid"] == "dev-1" and dot["poi_key"] == "keyA"
    assert dot["count"] == 3, "frequency must survive the fold, not reset to 1"
    assert dot["days"] == ["2026-09-01", "2026-09-03"]
    assert len(dot["visits"]) == 2, "12:00 and 12:04 are one visit; the 3rd is another"
    assert fold["maids"] == {"dev-1"}


# ── watermark gap ranges ─────────────────────────────────────────────────────

def test_contiguous_ranges_collapses_runs():
    """A scattered gap must become a few ranges, not one feature per day —
    10 features per request is a hard API cap."""
    days = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3),
            date(2026, 9, 7),
            date(2026, 9, 9), date(2026, 9, 10)]
    assert _contiguous_ranges(days) == [
        (date(2026, 9, 1), date(2026, 9, 3)),
        (date(2026, 9, 7), date(2026, 9, 7)),
        (date(2026, 9, 9), date(2026, 9, 10)),
    ]
    assert _contiguous_ranges([]) == []


def test_dates_to_days_parses_and_sorts():
    assert _dates_to_days(["2026-09-03", "2026-09-01", "2026-09-01", "garbage"]) == [
        date(2026, 9, 1), date(2026, 9, 3),
    ]


def test_dates_to_days_drops_today_and_the_future():
    """build_feature stamps endDateTime at 23:59:59 of the last day, and the API
    rejects the whole request with "endDateTimeEpochMS ... cannot be in the
    future". Today is dropped, not clamped to now: a partially-fetched day marked
    in the watermark is never re-bought, so the rest of it would be lost for good.
    """
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date()
    days = [
        (today - timedelta(days=2)).isoformat(),
        (today - timedelta(days=1)).isoformat(),
        today.isoformat(),
        (today + timedelta(days=1)).isoformat(),
    ]
    assert _dates_to_days(days) == [today - timedelta(days=2), today - timedelta(days=1)]
    # A purely future window (an event that has not happened) buys nothing.
    assert _dates_to_days([(today + timedelta(days=5)).isoformat()]) == []


# ── request building ─────────────────────────────────────────────────────────

def test_build_feature_is_point_plus_radius():
    """Point + radiusInMeters, not a hand-built polygon box — and the POI's own
    stable key as the feature id so the response round-trips back to it."""
    poi = {"lat": 40.7608, "lng": -73.9733, "radius_km": 0.25}
    feat = build_feature(poi, "key123", date(2026, 9, 1), date(2026, 9, 3))

    assert feat["id"] == "key123"
    assert feat["geometry"]["type"] == "Point"
    # GeoJSON is [lng, lat] — getting this backwards puts the geofence in the
    # wrong hemisphere and returns a plausible-looking empty audience.
    assert feat["geometry"]["coordinates"] == [-73.9733, 40.7608]
    # radiusInMeters is a per-feature PROPERTY. As a sibling of `geometry` the
    # API does not see it and answers 400 — confirmed against the live endpoint.
    assert feat["properties"]["radiusInMeters"] == 250
    assert "radiusInMeters" not in feat
    assert feat["properties"]["startDateTime"].startswith("2026-09-01T00:00:00")
    assert feat["properties"]["endDateTime"].startswith("2026-09-03T23:59:59")


def test_build_feature_clamps_radius_to_area_cap():
    """observations/geo/search caps a single feature at 25 sq km; the upstream
    _MAX_MAID_RADIUS_M allows 5 km (78 sq km), which would 400 the whole batch."""
    feat = build_feature({"lat": 40.0, "lng": -73.0, "radius_km": 5.0}, "k", date(2026, 9, 1), date(2026, 9, 1))
    assert feat["properties"]["radiusInMeters"] == 2820


def test_contiguous_ranges_split_at_the_direct_day_cap():
    """DIRECT rejects a window longer than 90 days. One 200-day run must come
    back as chunks that each fit, not a single illegal span."""
    from app.graph.unacast_query import MAX_RANGE_DAYS
    days = [date(2026, 1, 1) + timedelta(days=n) for n in range(200)]
    ranges = _contiguous_ranges(days)
    assert len(ranges) == 3
    for start, end in ranges:
        assert (end - start).days + 1 <= MAX_RANGE_DAYS
    covered = [d for s, e in ranges for d in (s + timedelta(days=n) for n in range((e - s).days + 1))]
    assert covered == days


# ── response translation ─────────────────────────────────────────────────────

_SAMPLE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "id": "keyA",
            "properties": {
                "observationCount": 3,
                "observationsPerDevice": [
                    {
                        "registrationID": "dev-1",
                        "observationCount": 2,
                        "observations": [
                            {"timestampEpochMS": 1788643811000, "latitude": 40.7594,
                             "longitude": -73.9698, "forensicFlags": 30098358272, "hot": True},
                            {"timestampEpochMS": 1788643818000, "latitude": 40.75942,
                             "longitude": -73.96982, "forensicFlags": 30098882560, "hot": True},
                        ],
                    },
                    {
                        "advertiserID": "adv-2",
                        "observationCount": 1,
                        "observations": [
                            {"timestampEpochMS": 1788665280000, "latitude": 40.759998,
                             "longitude": -73.970001, "forensicFlags": 4295000064, "hot": False},
                        ],
                    },
                ],
            },
        }
    ],
}


def test_parse_response_flattens_to_per_ping_rows():
    rows, total, truncated = parse_response(_SAMPLE, {"keyA": {"lat": 40.76, "lng": -73.97}})
    assert truncated == set()

    assert total == 3
    assert len(rows) == 3
    assert {r["maid"] for r in rows} == {"dev-1", "adv-2"}
    assert all(r["poi_key"] == "keyA" for r in rows)
    assert all(r["observed_at"].tzinfo is not None for r in rows)
    assert rows[0]["forensic_flags"] == 30098358272
    assert rows[0]["hot"] is True
    assert "cell_id" not in rows[0]


def test_parse_response_skips_unknown_feature_ids():
    """We set the ids ourselves; an unrecognised one means a shape change.
    Attributing those pings to an arbitrary POI would be silently wrong."""
    rows, total, _truncated = parse_response(_SAMPLE, {"someOtherKey": {}})
    assert rows == [] and total == 0


def test_parse_response_tolerates_missing_fields():
    payload = {"features": [{"id": "k", "properties": {"observationsPerDevice": [
        {"registrationID": "d", "observations": [
            {"timestampEpochMS": None, "latitude": 1.0, "longitude": 2.0},
            {"timestampEpochMS": 123456789000, "latitude": None, "longitude": 2.0},
            {"timestampEpochMS": 123456789000, "latitude": 1.0, "longitude": 2.0},
        ]},
        {"observations": [{"timestampEpochMS": 1, "latitude": 1.0, "longitude": 2.0}]},  # no id
    ]}}]}
    rows, total, _truncated = parse_response(payload, {"k": {}})
    assert total == 1 and len(rows) == 1


def test_body_has_no_probe_variant():
    """The quota counts API calls, so a returnObservations=false sizing probe
    would cost exactly as much as the real request. _body must therefore take
    features and nothing else — no probe mode to accidentally spend a call on."""
    import inspect

    from app.graph.unacast_query import _body

    assert list(inspect.signature(_body).parameters) == ["features"]
    body = _body([build_feature({"lat": 40.0, "lng": -73.0}, "k", date(2026, 9, 1), date(2026, 9, 1))])
    assert body["crs"]["properties"]["responseType"] == "DIRECT"
    assert body["features"][0]["properties"]["returnObservations"] is True


# ── non-retryable failures must not be retried ───────────────────────────────

class _CountingQuerier:
    """Records how many times query_maids was invoked, and what writer it got."""

    def __init__(self, raises):
        self.raises = raises
        self.calls = 0
        self.writers = []

    async def query_maids(self, dates, pois, *, writer=None, failures=None):
        self.calls += 1
        self.writers.append(writer)
        if self.raises:
            raise self.raises
        return []


@pytest.mark.asyncio
async def test_budget_exhausted_is_not_retried():
    """Retrying an exhausted monthly budget cannot succeed and may cost real
    quota. Exactly one attempt."""
    from app.graph.builder.executors.maid import _query_maids_with_retry
    from app.graph.unacast_query import UnacastBudgetExhausted

    q = _CountingQuerier(UnacastBudgetExhausted("no budget left"))
    rows, log = await _query_maids_with_retry(q, dates=["2026-09-01"], pois=[{}])

    assert q.calls == 1, "a non-retryable failure must not be attempted twice"
    assert rows is None
    assert log["status"] == "error"
    assert log["error_kind"] == "UnacastBudgetExhausted"
    assert log["attempts"] == 1


@pytest.mark.asyncio
async def test_ip_not_allowlisted_is_not_retried():
    from app.graph.builder.executors.maid import _query_maids_with_retry
    from app.services.unacast_client import UnacastIPNotAllowlisted

    q = _CountingQuerier(
        UnacastIPNotAllowlisted(403, {"message": "Unauthorized IP address."}, "https://x/y")
    )
    rows, log = await _query_maids_with_retry(q, dates=["2026-09-01"], pois=[{}])

    assert q.calls == 1
    assert log["error_kind"] == "UnacastIPNotAllowlisted"
    # The message must name the NAT, or an on-call engineer has nothing to act on.
    assert "<NAT_IP>" in log["error_msg"]


@pytest.mark.asyncio
async def test_a_rejected_request_is_not_retried():
    """A 400/404/413/422 describes THIS search: the same body gets the same
    answer, and every re-send was another metered call."""
    from app.graph.builder.executors.maid import _query_maids_with_retry
    from app.services.unacast_client import UnacastRequestRejected

    q = _CountingQuerier(
        UnacastRequestRejected(400, {"message": "outside coverage"}, "https://x/y")
    )
    rows, log = await _query_maids_with_retry(q, dates=["2026-09-01"], pois=[{}])

    assert q.calls == 1
    assert log["error_kind"] == "UnacastRequestRejected"


@pytest.mark.asyncio
async def test_the_client_tells_a_bad_request_from_an_account_fault(monkeypatch):
    """Only a request-content status is a UnacastRequestRejected. An IP or
    credential rejection is about the shared account, and must stay something
    the platform-wide breaker counts."""
    import httpx

    from app.core.config import settings
    from app.services import unacast_client as uc

    monkeypatch.setattr(settings, "UNACAST_PROXY_URL", "", raising=False)

    async def _post(status: int, body: dict):
        client = uc.UnacastClient(token="t", base_url="https://example.invalid/")
        await client._client.aclose()
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body))
        )
        try:
            await client.post("observations/geo/search", {})
        finally:
            await client.aclose()

    with pytest.raises(uc.UnacastRequestRejected):
        await _post(400, {"message": "feature outside coverage"})
    with pytest.raises(uc.UnacastIPNotAllowlisted):
        await _post(403, {"message": "Unauthorized IP address."})
    with pytest.raises(uc.UnacastAPIError) as credential:
        await _post(401, {"message": "bad key"})
    assert not isinstance(credential.value, uc.UnacastRequestRejected)


def test_parse_response_reports_only_this_responses_truncation():
    """Coverage is flagged from what THIS response capped. The process-wide
    record also holds older truncations, and reading it marked a POI's later,
    narrower windows as samples."""
    from app.graph import unacast_query as uq

    payload = {"features": [
        {"id": "capped", "properties": {
            "observationLimitHit": True, "observationCount": 1,
            "totalPossibleObservationCount": 9,
        }},
        {"id": "whole", "properties": {"observationCount": 0}},
    ]}
    uq._reset_truncation()
    try:
        uq._TRUNCATED_FEATURES["whole"] = {"fraction": None}   # capped in an earlier response
        _rows, _total, truncated = parse_response(payload, {"capped": {}, "whole": {}})
        assert truncated == {"capped"}
    finally:
        uq._reset_truncation()


def test_the_truncation_disclosure_is_scoped_to_the_extraction():
    """The report reads a process-wide record, so an unscoped call told one
    tenant their spots were sampled because of another tenant's busy ones."""
    from app.graph import unacast_query as uq
    from app.graph.builder.executors.maid import _truncation_facts

    mine = {"lat": 40.70, "lng": -74.00, "radius_km": 0.1}
    theirs = {"lat": 40.758, "lng": -73.9855, "radius_km": 1.0}
    uq._reset_truncation()
    try:
        uq._TRUNCATED_FEATURES[uq.poi_key(theirs)] = {
            "returned": 100_000, "possible": 7_000_000, "fraction": 0.0143, "devices": (),
        }
        assert _truncation_facts([mine])["truncated_poi_count"] == 0
        assert _truncation_facts([theirs])["truncated_poi_count"] == 1
    finally:
        uq._reset_truncation()


@pytest.mark.asyncio
async def test_transient_failure_still_retries():
    """Ordinary outages must keep their retry."""
    from app.graph.builder.executors.maid import _query_maids_with_retry

    q = _CountingQuerier(RuntimeError("connection reset"))
    rows, log = await _query_maids_with_retry(
        q, dates=["2026-09-01"], pois=[{}], max_attempts=2
    )

    assert q.calls == 2, "a transient failure should still be retried"
    assert log["error_kind"] == "RuntimeError"


@pytest.mark.asyncio
async def test_writer_is_threaded_through_to_the_querier():
    """The concurrency gate narrates its capacity wait through `writer`. If the
    retry wrapper doesn't pass it, a queued user sees a silent stall."""
    from app.graph.builder.executors.maid import _query_maids_with_retry

    events = []
    q = _CountingQuerier(None)
    await _query_maids_with_retry(
        q, dates=["2026-09-01"], pois=[{}], writer=events.append
    )

    assert q.writers == [events.append], "writer must reach query_maids"


# ── production POI cap ───────────────────────────────────────────────────────

def _poi(name, angle, cat, rating, n):
    return {"name": name, "lat": 40.0, "lng": -73.0, "source_angle": angle,
            "parent_poi_type": cat, "rating": rating, "user_ratings_total": n}


def test_poi_cap_is_off_by_default():
    """Production must target EVERY location in a category. The vendor quota
    counts calls, not POIs — so the long tail is nearly free. The cap is a
    test-only knob and its default must never trim a real campaign."""
    from app.core.config import settings
    from app.graph.builder.executors.geo import _cap_pois_per_category

    assert settings.GEO_MAX_POIS_PER_CATEGORY == 0
    pois = [_poi(f"SEPHORA {i}", "competitor_brand", "Sephora", 4.0 + i / 100, 500 + i)
            for i in range(50)]
    assert _cap_pois_per_category(pois) == pois


def test_poi_cap_is_per_category_not_global():
    """20 Sephora + 3 Ulta under a global top-10 would drop Ulta entirely and
    silently answer a different question than the user asked."""
    from app.graph.builder.executors.geo import _cap_pois_per_category

    pois = (
        [_poi(f"SEPHORA {i}", "competitor_brand", "Sephora", 4.0 + i / 100, 500 + i) for i in range(20)]
        + [_poi(f"Ulta {i}", "competitor_brand", "Ulta", 4.0 + i / 100, 500 + i) for i in range(3)]
    )
    kept = _cap_pois_per_category(pois, cap=10)
    by_brand = {}
    for p in kept:
        by_brand.setdefault(p["parent_poi_type"], []).append(p)
    assert len(by_brand["Sephora"]) == 10
    assert len(by_brand["Ulta"]) == 3, "a smaller category must survive intact"
    assert "SEPHORA 19" in {p["name"] for p in kept}
    assert "SEPHORA 0" not in {p["name"] for p in kept}


def test_poi_cap_prefers_well_reviewed_over_thin_five_stars():
    """A 5.0 from 3 reviews is noise, not a busy store."""
    from app.graph.builder.executors.geo import _cap_pois_per_category

    pois = [_poi(f"thin {i}", "category", "gym", 5.0, 3) for i in range(10)]
    pois.append(_poi("busy", "category", "gym", 4.1, 1800))
    kept = {p["name"] for p in _cap_pois_per_category(pois, cap=10)}
    assert len(kept) == 10
    assert "busy" in kept


def test_poi_cap_preserves_input_order_and_is_a_noop_under_the_cap():
    """It only removes — the round-robin interleave upstream must survive."""
    from app.graph.builder.executors.geo import _cap_pois_per_category

    small = [_poi("a", "category", "gym", 4.5, 100), _poi("b", "category", "spa", 4.4, 100)]
    assert _cap_pois_per_category(small, cap=10) == small

    pois = [_poi(f"g{i}", "category", "gym", 4.0 + i / 100, 100 + i) for i in range(12)]
    kept = _cap_pois_per_category(pois, cap=10)
    assert [p["name"] for p in kept] == sorted(
        (p["name"] for p in kept), key=lambda n: int(n[1:])
    ), "surviving POIs must stay in their original relative order"


# ── _gate: per-POI drive-by override (B3) ────────────────────────────────────

def test_gate_keeps_driving_pings_only_for_the_drive_by_poi(monkeypatch):
    """Two POIs in one extraction: an ordinary store and a billboard. Only the
    billboard's pings keep LIKELY_DRIVING — the store's gate is untouched."""
    from app.core import config
    from app.graph.maid_signal import FLAG_BITS, mask_for
    from app.graph.unacast_query import UnacastMAIDQuerier, poi_key

    monkeypatch.setattr(config.settings, "MAID_ACCURACY_MODE", "off", raising=False)
    monkeypatch.setattr(config.settings, "MAID_EXCLUDE_FLAGS", "", raising=False)

    driving = mask_for("LIKELY_DRIVING")
    store = {"lat": 40.0, "lng": -73.0, "radius_km": 0.1}
    billboard = {"lat": 41.0, "lng": -74.0, "radius_km": 0.1, "targeting_intent": "drive_by"}
    store_key, billboard_key = poi_key(store), poi_key(billboard)

    rows = [
        {"poi_key": store_key, "maid": "a", "lat": 40.0, "lng": -73.0, "forensic_flags": driving},
        {"poi_key": billboard_key, "maid": "b", "lat": 41.0, "lng": -74.0, "forensic_flags": driving},
    ]
    kept = UnacastMAIDQuerier._gate(rows, {store_key: store, billboard_key: billboard})
    assert [r["maid"] for r in kept] == ["b"]


def test_gate_default_behaviour_is_unchanged_with_no_drive_by_poi(monkeypatch):
    from app.core import config
    from app.graph.maid_signal import mask_for
    from app.graph.unacast_query import UnacastMAIDQuerier, poi_key

    monkeypatch.setattr(config.settings, "MAID_ACCURACY_MODE", "off", raising=False)
    monkeypatch.setattr(config.settings, "MAID_EXCLUDE_FLAGS", "", raising=False)

    driving = mask_for("LIKELY_DRIVING")
    store = {"lat": 40.0, "lng": -73.0, "radius_km": 0.1}
    store_key = poi_key(store)
    rows = [{"poi_key": store_key, "maid": "a", "lat": 40.0, "lng": -73.0, "forensic_flags": driving}]

    kept = UnacastMAIDQuerier._gate(rows, {store_key: store})
    assert kept == []
