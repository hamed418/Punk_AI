"""
app/graph/unacast_query.py
──────────────────────────
Live MAID querying against the Unacast/Gravy Analytics ``observations/geo/search``
endpoint — the only audience data source.

    await querier.query_maids(dates, pois) -> [{"poi_key","maid","lat","lng","ts", ...}]

one dict per RAW PING. ``poi_key`` names a purchase — the ring's centre AND radius
— and is the request feature's id, so POI attribution is exact and free:
``_spot_key`` folds on it (one visit per device per place) and
``attribute_audience`` resolves the POI by dict lookup. Pings are STORED under the
centre alone (``center_key``) and read back per requested ring by distance,
stamped with that ring's ``poi_key`` — so a smaller ring is served from a larger
purchase at the same place instead of being bought again. ``forensic_flags``
drives the signal-quality gate in app/graph/maid_signal.py.

The mechanism, in the order a request meets it:

  * DIRECT only (no EXPORT access on this account). Each feature is a Point +
    radiusInMeters with its own date window, packed by LEGALITY LIMITS ONLY
    (``plan_requests``): a request carries ≤10 features (the endpoint's hard
    cap), and no feature's window exceeds 90 days (``_contiguous_ranges``).
    No size is predicted and no request is ever refused up front — a search
    is never too big to try, only too big for ONE call to answer.
  * A request that times out is split in half — by feature count if it holds
    more than one, else by day-window — and the halves retried, recursively,
    until each request is small enough to answer or is a single POI on a
    single day (``_split_request``). Never re-sent as-is: the vendor could not
    answer that exact body.
  * A watermark so a (ring, day) already answerable — bought at this centre, at
    this radius or larger, untruncated — is never re-bought. Except once when it
    was bought while the vendor's data was still HOT, and when it was truncated
    inside a multi-day window that a narrower one can repair.
  * The vendor's own per-feature cap (100,000 observations) truncates a response
    rather than refusing it; a truncated POI's audience is disclosed as a
    partial sample (``truncation_report``), never hidden and never a reason to
    refuse the rest of the search.
  * Admission: a circuit breaker, a shared FIRST-COME-FIRST-SERVED monthly budget
    counted in API CALLS, and an 8-slot concurrent-call gate — all platform-wide
    (one shared API key) and all in Postgres, so every Cloud Run instance sees
    the same state. These — not a size prediction — are what bound cost.
  * ``inMin`` is not used: every POI's observations are bought independently and
    the audience filter runs locally over the stored superset.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import time
import uuid
from dataclasses import dataclass
from datetime import date as _date, datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import delete, func, select, text

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.graph.maid_query import NonRetryableMAIDQueryError
from app.db.models import (
    UnacastCallLog,
    UnacastCircuit,
    UnacastConcurrencyLease,
    UnacastFetchCoverage,
    UnacastRawObservation,
    UnacastUsageLedger,
)
from app.graph.usage import current_turn_identity, record_api_call

logger = logging.getLogger(__name__)

_ENDPOINT = "observations/geo/search"

# The endpoint's hard cap (confirmed by a real 400 from the API when violated).
MAX_FEATURES_PER_REQUEST = 10

# DIRECT responses are capped at a 90-day window per request (the waiver applies
# only to observations/registrationID/search, which this backend does not use).
# _contiguous_ranges splits anything longer rather than letting it 400.
MAX_RANGE_DAYS = 90

# Per-feature area cap: a Point is buffered into a circle by radiusInMeters, and
# the resulting disc must stay under 25 sq km. sqrt(25/pi) km ~= 2.82 km.
MAX_FEATURE_RADIUS_M = 2820

# Timestamps outside this range are rejected as malformed (see parse_response).
# Upper bound is 2100-01-01; the API itself refuses a future window, so anything
# beyond it is corruption, not data.
_MAX_PLAUSIBLE_TS_MS = 4_102_444_800_000

# Rows per bulk INSERT. Large enough that the round trips stop mattering, small
# enough that one statement's parameter list stays sane.
_PERSIST_CHUNK = 5_000

# The DIRECT response cap. A feature that hits it is silently truncated — the
# vendor returns 100k of however many exist and sets observationLimitHit — so
# it is disclosed (truncation_report), never predicted or refused for.
OBSERVATIONS_PER_FEATURE_CAP = 100_000

# How often a running extraction tells the user it is still working.
_HEARTBEAT_S = 15.0

# Advisory-lock key serializing concurrency-slot acquisition. Arbitrary but
# must be stable and not collide with any other pg_advisory lock in the app.
_GATE_LOCK_KEY = 8_417_233_901

# How long to keep retrying for a concurrency slot before giving up. DIRECT
# calls run 20-130s in practice, so a queued request can legitimately wait a
# while; past this it's better to fail loudly than hang an SSE stream forever.
_SLOT_WAIT_TIMEOUT_S = 240.0
_SLOT_POLL_INTERVAL_S = 2.0


# ── Circuit breaker ──────────────────────────────────────────────────────────
# `fired = True` is set before the request and committed in `finally`, which is
# correct — a request that reaches the vendor and then errors did consume quota.
# But with no breaker, a vendor outage means every extraction reserves, fires,
# fails and commits, across every tenant, against a shared FCFS monthly budget.
# The outage drains the month while returning nothing.
#
# State lives in the `unacast_circuit` table, not module globals. In-process
# state stopped only the acute single-worker case: Cloud Run runs this service at
# maxScale=5, so an open breaker in one worker did nothing about the other four,
# which kept reserving, firing and paying throughout the same outage.
#
# `opened_at` is a UTC timestamp rather than time.monotonic() precisely because
# it now has to mean the same thing in every worker — monotonic clocks are
# per-process and not comparable across them.
_BREAKER_ROW_ID = "unacast"


class _PgBreakerStore:
    """The shared breaker row. One row, upserted."""

    async def load(self) -> tuple[int, datetime | None]:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    select(
                        UnacastCircuit.consecutive_failures,
                        UnacastCircuit.opened_at,
                    ).where(UnacastCircuit.id == _BREAKER_ROW_ID)
                )
            ).first()
        return (int(row[0] or 0), row[1]) if row else (0, None)

    async def save(self, failures: int, opened_at: datetime | None) -> None:
        from sqlalchemy.dialects.postgresql import insert as _pg_insert

        async with AsyncSessionLocal() as db:
            async with db.begin():
                await db.execute(
                    _pg_insert(UnacastCircuit.__table__)
                    .values(
                        id=_BREAKER_ROW_ID,
                        consecutive_failures=failures,
                        opened_at=opened_at,
                    )
                    .on_conflict_do_update(
                        index_elements=["id"],
                        set_={
                            "consecutive_failures": failures,
                            "opened_at": opened_at,
                        },
                    )
                )

    async def claim_probe(self, seen: datetime, until: datetime, failures: int) -> bool:
        """Compare-and-set: move ``opened_at`` from ``seen`` to ``until`` only
        if no other worker has moved it first. The one UPDATE that matches is
        the one probe."""
        from sqlalchemy import update

        table = UnacastCircuit.__table__
        async with AsyncSessionLocal() as db:
            async with db.begin():
                result = await db.execute(
                    update(table)
                    .where(table.c.id == _BREAKER_ROW_ID, table.c.opened_at == seen)
                    .values(opened_at=until, consecutive_failures=failures)
                )
        return bool(result.rowcount)


class _MemoryBreakerStore:
    """Process-local fallback, and what the unit tests run against.

    The breaker's decision logic is worth testing without a database — the cost
    tests deliberately stub every DB path for exactly that reason — so the store
    is a seam rather than a hard dependency.
    """

    def __init__(self) -> None:
        self.failures = 0
        self.opened_at: datetime | None = None

    async def load(self) -> tuple[int, datetime | None]:
        return (self.failures, self.opened_at)

    async def save(self, failures: int, opened_at: datetime | None) -> None:
        self.failures = failures
        self.opened_at = opened_at

    async def claim_probe(self, seen: datetime, until: datetime, failures: int) -> bool:
        if self.opened_at != seen:
            return False
        self.opened_at, self.failures = until, failures
        return True


_BREAKER_STORE: Any = _PgBreakerStore()


class UnacastCircuitOpen(NonRetryableMAIDQueryError):
    """Too many consecutive vendor failures — refusing to spend more budget.

    Raised BEFORE any reservation, so an open breaker costs nothing at all.
    """


async def _breaker_check() -> None:
    _failures, opened_at = await _BREAKER_STORE.load()
    if opened_at is None:
        return
    waited = (datetime.now(timezone.utc) - opened_at).total_seconds()
    cooldown = float(settings.UNACAST_BREAKER_COOLDOWN_S)
    if waited < cooldown:
        raise UnacastCircuitOpen(
            f"the audience data provider has failed "
            f"{settings.UNACAST_BREAKER_THRESHOLD} times in a row, so I stopped "
            f"sending requests to avoid burning the shared data budget. "
            f"Retrying in {int(cooldown - waited)}s."
        )
    # Half-open: admit exactly ONE probe. The claim is a compare-and-set on the
    # opened_at this worker just read, so when several workers see the cooldown
    # elapse at once only one wins. The winner also moves opened_at forward by
    # as long as a request can take, so the breaker stays shut to everyone else
    # until the probe's outcome (_breaker_record) closes or re-opens it. The old
    # load-then-save let every worker that read the elapsed cooldown through.
    until = (
        datetime.now(timezone.utc)
        - timedelta(seconds=cooldown)
        + timedelta(seconds=float(settings.UNACAST_REQUEST_TIMEOUT_S) + 15.0)
    )
    if not await _BREAKER_STORE.claim_probe(
        opened_at, until, int(settings.UNACAST_BREAKER_THRESHOLD) - 1
    ):
        raise UnacastCircuitOpen(
            "the audience data provider failed several times in a row, and another "
            "request is already checking whether it has recovered. Retry shortly."
        )
    logger.info("Unacast breaker: cooldown elapsed after %.0fs — probing", waited)


async def _breaker_record(*, success: bool) -> None:
    failures, opened_at = await _BREAKER_STORE.load()
    if success:
        if failures or opened_at is not None:
            logger.info("Unacast breaker: vendor responded — closing")
        await _BREAKER_STORE.save(0, None)
        return
    failures += 1
    if failures >= int(settings.UNACAST_BREAKER_THRESHOLD):
        await _BREAKER_STORE.save(failures, datetime.now(timezone.utc))
        logger.error(
            "Unacast breaker OPEN after %d consecutive failures — refusing calls "
            "for %ss to protect the shared budget",
            failures, settings.UNACAST_BREAKER_COOLDOWN_S,
        )
        return
    await _BREAKER_STORE.save(failures, opened_at)


def _breaker_reset() -> None:
    """Test hook — swap in a clean in-memory store so no state, and no database,
    leaks between tests. Stays synchronous so the autouse fixture does not have
    to become async."""
    global _BREAKER_STORE
    _BREAKER_STORE = _MemoryBreakerStore()


class UnacastBudgetExhausted(NonRetryableMAIDQueryError):
    """The shared monthly observation budget cannot cover this call.

    Raised, never swallowed into an empty result: an empty list is
    indistinguishable from "this geofence really has nobody in it", which is
    exactly the confusion maid_query.py's own re-raise rule exists to prevent.

    Non-retryable on purpose — a retry re-runs the pre-flight probe against a
    budget that is, by definition, still exhausted.
    """


class UnacastConcurrencyTimeout(NonRetryableMAIDQueryError):
    """Waited out _SLOT_WAIT_TIMEOUT_S without getting one of the shared
    concurrent-call slots.

    Non-retryable: the caller already waited the full timeout: retrying just
    starts another full wait on a pool that was saturated moments ago.
    """


class UnacastRequestTimeout(NonRetryableMAIDQueryError):
    """The vendor could not answer a request in time even after it was split.

    Non-retryable: the same body cannot succeed on a re-send, and each attempt
    is a full timeout of the user staring at a silent stream. Thread 77e403d3
    re-sent one oversized request four times — 13 minutes — for nothing.
    """


# ── Pure helpers ─────────────────────────────────────────────────────────────

def poi_key(poi: dict) -> str | None:
    """Stable identity for the cache, the watermark and attribution: WHAT DID WE
    PAY FOR.

    Geometry only — the coordinates rounded to ~1 m (``geo._poi_key``) plus the
    ring radius, which is exactly what one request feature buys. So the same key
    comes out whether it is computed from the stripped ``{lat, lng, radius_km}``
    payload the querier receives or from the full POI dict the executor and
    ``attribute_audience`` hold.

    It used to hash ``geo.dedup_key``, which also includes the place NAME. The
    querier's stripped dicts therefore hashed with an empty name and the
    executor's full dicts with the real one, the two keys never matched, every
    POI group read as "empty", the per-category visit gap never applied, and
    attribution quietly fell back to a geometric scan.

    The radius is in the key because a different radius is a different purchase:
    ``read_cached`` filters on ``poi_key`` and time with no spatial predicate, so
    without it a day bought at 100 m satisfied a later 500 m request from cache
    and served the narrower audience as the wider one — across tenants, since
    the cache is global.
    """
    from app.graph.builder.executors.geo import _poi_key

    coords = _poi_key(poi)
    if coords is None:
        return None
    radius_m = int(round(float(poi.get("radius_km") or 0.1) * 1000))
    return hashlib.sha256(repr((coords, radius_m)).encode("utf-8")).hexdigest()[:32]


def center_key(poi: dict) -> str | None:
    """Where a ring is, without how big: the same rounded coordinates as
    ``poi_key``, no radius. What pings are STORED and read back under.

    ``poi_key`` has to keep the radius — it names a purchase, and a 100 m one
    once satisfied a 500 m request. But every ping inside a 100 m ring is also
    inside a 500 m ring at the same centre, so storing by centre lets
    ``covered_days_bulk`` serve the smaller ring from the larger purchase and
    ``read_cached`` cut it back out by distance, instead of buying it again.
    """
    from app.graph.builder.executors.geo import _poi_key

    coords = _poi_key(poi)
    if coords is None:
        return None
    return hashlib.sha256(repr(coords).encode("utf-8")).hexdigest()[:32]


def purchase_radius_m(poi: dict) -> int:
    """The radius the vendor actually answers for — the requested ring, clamped
    to the per-feature area cap exactly as ``build_feature`` sends it."""
    return min(int(round(float(poi.get("radius_km") or 0.1) * 1000)), MAX_FEATURE_RADIUS_M)


def _extract_maid(entry: dict) -> str | None:
    """advertiserID when the account emits it (a real MAID), else
    registrationID (Unacast's pseudonym, treated as the MAID for now — a
    confirmed product decision, see the integration plan §5).

    Written preference-first so the day the vendor enables advertiserID mode
    on this endpoint, nothing here changes: the values just become real
    device IDs. The API populates exactly one of the two.
    """
    return entry.get("advertiserID") or entry.get("registrationID")


def _period(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def _iso_utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _dates_to_days(dates: list[str]) -> list[_date]:
    """Parse a day list, dropping today and anything later.

    build_feature stamps endDateTime at 23:59:59 UTC of the last day, and the
    API rejects the whole request with "Value of endDateTimeEpochMS ... cannot
    be in the future" — so a caller's window that runs up to today (the default
    for any lookback) 400s every time.

    Today is dropped rather than clamped to `now` so the watermark stays
    honest: a partial day recorded as covered is never re-bought, which would
    permanently lose the rest of it. A future-dated event range simply yields
    no days, and so no call — there are no observations from the future.
    """
    cutoff = datetime.now(timezone.utc).date()
    out: list[_date] = []
    for d in dates or []:
        try:
            parsed = _date.fromisoformat(str(d)[:10])
        except ValueError:
            continue
        if parsed < cutoff:
            out.append(parsed)
    return sorted(set(out))


def _contiguous_ranges(days: list[_date]) -> list[tuple[_date, _date]]:
    """Collapse a sorted day list into contiguous [start, end] runs, so a gap
    of 40 scattered days becomes a handful of ranges rather than 40 features
    (which would blow the 10-feature cap instantly).

    No run is longer than MAX_RANGE_DAYS: the DIRECT endpoint rejects a
    request whose window exceeds that, and this is the one seam every caller
    (lookback and event-based alike) routes through, so the guard belongs
    here rather than at each call site."""
    if not days:
        return []
    ranges: list[tuple[_date, _date]] = []
    start = prev = days[0]
    for d in days[1:]:
        if (d - prev).days == 1 and (d - start).days + 1 <= MAX_RANGE_DAYS:
            prev = d
            continue
        ranges.append((start, prev))
        start = prev = d
    ranges.append((start, prev))
    return ranges


# ponytail: no fragmented-gap merging. `_contiguous_ranges` used to be wrapped
# in `_merged_ranges`, which collapsed scattered gap days into one re-buying
# span when that was estimated to cost fewer CALLS than the runs alone — an
# estimate that needed a predicted rate. Without prediction there is nothing
# to compare, so every contiguous run is just its own span; a search left with
# many small fragmented gaps (a rare partial-failure aftermath) makes more,
# smaller requests instead of one that guesses at being cheaper. Upgrade path:
# if this is ever measured to matter, merge purely on RUN COUNT (no rate) once
# a POI has more than _MAX_GAP_RANGES runs.


_FID_SEP = "::"


def _span_fid(span: "_Span") -> str:
    """Request-unique Feature id for one span: the POI key plus its start day."""
    return f"{span.key}{_FID_SEP}{span.start.isoformat()}"


def build_feature(
    poi: dict, key: str, start: _date, end: _date, *, feature_id: str | None = None,
) -> dict:
    """One GeoJSON Feature: a Point + radiusInMeters (the API buffers it into
    a circle itself — no hand-built polygon box), carrying its OWN date window
    in properties.

    Per-feature date windows are what let one request mix POIs with different
    ranges — used here for watermark gaps, and by the event-based path for
    genuinely different event dates. Same mechanism, two reasons.
    """
    radius_km = float(poi.get("radius_km") or 0.1)
    return {
        "type": "Feature",
        "id": feature_id or key,
        "properties": {
            "startDateTime": datetime(
                start.year, start.month, start.day, tzinfo=timezone.utc
            ).isoformat(),
            "endDateTime": datetime(
                end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc
            ).isoformat(),
            "returnObservations": True,
            # Point geometry REQUIRES this — the API buffers the point into a
            # polygon with it. It is a per-feature PROPERTY; placed as a
            # sibling of `geometry` the API does not see it and answers
            # 400 "radiusInMeters is required if feature is a Point or
            # LineString". Clamped because the buffered disc must stay under
            # the 25 sq km per-feature cap (_MAX_MAID_RADIUS_M upstream allows
            # 5 km, which is 78 sq km).
            "radiusInMeters": min(
                int(round(radius_km * 1000)), MAX_FEATURE_RADIUS_M
            ),
        },
        "geometry": {
            "type": "Point",
            "coordinates": [float(poi["lng"]), float(poi["lat"])],
        },
    }


def _body(features: list[dict]) -> dict:
    """FeatureCollection body. `inMin` is deliberately absent — see module
    docstring. crs.properties is the (non-standard) home the API gives
    non-feature-specific params.

    There is no returnObservations=false variant any more: the quota counts
    calls, so a sizing probe would cost exactly as much as the real request.
    """
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"responseType": "DIRECT"}},
        "features": features,
    }


def _observation_row(fid: str, maid: str, obs: dict) -> dict | None:
    """One validated per-ping row, or None if the observation is unusable.

    Validation is not paranoia. ``httpx``'s ``.json()`` uses ``json.loads``,
    which accepts bare ``NaN``/``Infinity`` by default, so a NaN latitude sails
    past a plain ``is None`` check and then blows up on the first arithmetic or
    ``datetime`` construction downstream. That exception used to escape
    ``_run_batch``'s try block and discard **the whole batch — up to 10 POIs —
    after the vendor call was already paid for**. One malformed observation may
    never cost a batch, so every row is validated here and rejects are counted.
    """
    ts_ms = obs.get("timestampEpochMS")
    lat, lng = obs.get("latitude"), obs.get("longitude")
    if ts_ms is None or lat is None or lng is None:
        return None
    try:
        ts_ms = int(ts_ms)
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError, OverflowError):
        return None
    # NaN fails every comparison, so the range checks below reject it without a
    # separate isnan() call; Infinity is rejected the same way.
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        return None
    if not (0 < ts_ms < _MAX_PLAUSIBLE_TS_MS):
        return None
    return {
        "poi_key": fid,
        "maid": maid,
        "lat": lat,
        "lng": lng,
        "observed_at": datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc),
        "forensic_flags": obs.get("forensicFlags"),
        "hot": obs.get("hot"),
    }


# Feature ids whose last fetch came back truncated, and each affected device's
# TRUE observation count.
#
# Still a process-local dict, but no longer the only record: `persist_rows`
# writes the fact to `unacast_fetch_coverage.truncated`, and `covered_days_bulk`
# rehydrates this dict from that column at the start of every query. So a
# CACHE-ONLY re-run — no API call, the common case once the watermark is warm —
# now discloses truncation it never observed itself, which it previously could
# not: the dict was empty and the user was told a sampled audience was complete.
#
# The dict stays because it also holds the per-device detail
# (`totalPossibleObservationCountPerDevice`), which is only available in the
# response body and is not worth a column.
_TRUNCATED_FEATURES: dict[str, dict] = {}


def truncation_report(keys: list[str] | None = None) -> dict:
    """What is known about truncated features, for the extraction funnel.

    ``/observations/geo/search`` DIRECT caps at 100k observations PER FEATURE.
    The trial measured a dense 1 km2 feature returning 100k of 10,479,989
    possible — 1.4% — with ``observationLimitHit: true``. Truncation is not
    random with respect to devices, so a frequency predicate over a truncated
    POI systematically under-counts, and the user was never told.
    """
    keys = list(keys) if keys is not None else list(_TRUNCATED_FEATURES)
    hits = {k: _TRUNCATED_FEATURES[k] for k in keys if k in _TRUNCATED_FEATURES}
    return {
        "truncated_poi_count": len(hits),
        "truncated_pois": sorted(hits),
        # Entries rehydrated from the coverage column know THAT a fetch
        # truncated but not by how much — the ratio lived only in the response
        # body. Those carry fraction=None, and mixing None into min() raises
        # TypeError rather than sorting last, so they are filtered out. The
        # count above still reports them, which is the part that matters.
        "worst_sampled_fraction": min(
            (
                h["fraction"] for h in hits.values()
                if h.get("fraction") is not None
            ),
            default=None,
        ),
        "under_sampled_devices": sorted(
            {d for h in hits.values() for d in h.get("devices", ())}
        ),
    }


def _reset_truncation() -> None:
    """Test hook — module state must not leak between tests."""
    _TRUNCATED_FEATURES.clear()


def parse_response(
    payload: dict, key_to_poi: dict[str, dict]
) -> tuple[list[dict], int, set[str]]:
    """Flatten an observations/geo/search response into per-ping rows.

    Returns ``(rows, observation_count, truncated_keys)`` where each row is
    ``{poi_key, maid, lat, lng, observed_at, forensic_flags, hot}`` and
    ``truncated_keys`` are the feature ids THIS response capped. The coverage
    flag must come from that set, not from ``_TRUNCATED_FEATURES``: the global
    remembers every truncation this process ever saw, so reading it marked a
    POI's later, narrower windows truncated too.

    ``poi_key`` is the response feature's own id — which is the POI key WE set
    on the request — so POI attribution here is exact and free: the vendor
    geofenced the ping and grouped it under that feature. Nothing downstream
    needs to re-derive it from coordinates.

    Features whose id isn't recognised are skipped rather than guessed at — the
    id is ours, so an unknown one means a shape change worth noticing in the
    logs, not pings silently attributed to the wrong POI.
    """
    rows: list[dict] = []
    total = 0
    rejected = 0
    truncated: set[str] = set()
    for feat in payload.get("features") or []:
        props = feat.get("properties") or {}
        fid = feat.get("id") or props.get("id")
        if isinstance(fid, str):
            fid = fid.split(_FID_SEP, 1)[0]  # back to the POI key (see _batch_args)
        if fid not in key_to_poi:
            logger.warning("Unacast: response feature id %r not in request set — skipped", fid)
            continue
        if props.get("observationLimitHit"):
            truncated.add(fid)
            returned = props.get("observationCount") or 0
            possible = props.get("totalPossibleObservationCount") or 0
            # `totalPossibleObservationCountPerDevice` gives each device's TRUE
            # count even though the response was truncated — so a device whose
            # returned observations fall short of its true count has a visit
            # count that is a FLOOR, not a measurement. That is exactly what a
            # frequency predicate must not silently treat as fact.
            per_device = props.get("totalPossibleObservationCountPerDevice") or {}
            returned_per_device: dict[str, int] = {}
            for entry in props.get("observationsPerDevice") or []:
                _m = _extract_maid(entry)
                if _m:
                    returned_per_device[_m] = len(entry.get("observations") or [])
            under_sampled = [
                m for m, true_count in per_device.items()
                if returned_per_device.get(m, 0) < int(true_count or 0)
            ]
            _TRUNCATED_FEATURES[fid] = {
                "returned": returned,
                "possible": possible,
                "fraction": (returned / possible) if possible else None,
                "devices": under_sampled,
            }
            logger.warning(
                "Unacast: observation limit hit for feature %s (returned %s of %s possible, "
                "%.1f%%) — this POI's audience is a partial sample, %d device(s) "
                "under-sampled",
                fid, returned, possible,
                (returned / possible * 100) if possible else 0.0,
                len(under_sampled),
            )
        for entry in props.get("observationsPerDevice") or []:
            maid = _extract_maid(entry)
            if not maid:
                continue
            for obs in entry.get("observations") or []:
                row = _observation_row(fid, maid, obs)
                if row is None:
                    rejected += 1
                    continue
                total += 1
                rows.append(row)
    if rejected:
        logger.warning(
            "Unacast: rejected %d malformed observation(s) of %d — kept the rest of the batch",
            rejected, rejected + total,
        )
    return rows, total, truncated


# ── Request planning: legality limits only, no size prediction ──────────────

@dataclass
class _Span:
    """One feature to buy: a POI over one date span, and the gap days it pays
    for. No predicted volume — a request too big for the vendor to answer
    times out and is split by ``_split_request``, rather than being sized in
    advance from a guess."""
    key: str
    start: _date
    end: _date
    days: list[_date]


def plan_requests(
    key_to_poi: dict[str, dict],
    gaps: dict[str, list[_date]],
    *,
    max_features: int = MAX_FEATURES_PER_REQUEST,
) -> list[list[_Span]]:
    """Cut each POI's gap into features and pack them into requests, using only
    the vendor's own legality limits — never a predicted size. Pure: no I/O.

    One span per contiguous gap-run per POI: ``_contiguous_ranges`` already
    caps every run at MAX_RANGE_DAYS (a real "the API 400s past this" limit),
    so nothing here re-splits a window further. A request that turns out too
    big for the vendor to answer times out and is split by ``_split_request``
    in ``_fetch_gaps`` instead of being pre-judged here — this used to predict
    observation VOLUME from a density atlas seeded by pre-truncation response
    totals (up to 14x what a request could ever return) and refuse before
    buying anything; that guess is gone, along with the refusal.

    First-fit, ``max_features`` per request (the endpoint's hard cap, 10):
    there is nothing left to sort by without a size estimate, so spans pack in
    the order their POIs were seen.
    """
    spans: list[_Span] = []
    for key, gap_days in gaps.items():
        gap_set = set(gap_days)
        for start, end in _contiguous_ranges(gap_days):
            window = [start + timedelta(days=n) for n in range((end - start).days + 1)]
            spans.append(_Span(key, start, end, [d for d in window if d in gap_set]))

    requests: list[list[_Span]] = []
    for span in spans:
        if requests and len(requests[-1]) < max_features:
            requests[-1].append(span)
        else:
            requests.append([span])
    return requests


def _split_request(req: list["_Span"]) -> list[list["_Span"]]:
    """One deterministic halving step for a request that timed out — no
    prediction consulted, just cut the concrete thing that was too big.

    ``>1 span``        -> two requests, the span list cut in half by count
                           (10 features -> 5 + 5).
    ``1 span, >1 day``  -> two requests, that one span's date range cut in
                           half (30 days -> 15 + 15; a further timeout on one
                           half -> 7 + 8).
    ``1 span, 1 day``   -> ``[]``: cannot split further, the caller's
                           terminal case.
    """
    if len(req) > 1:
        mid = len(req) // 2
        return [req[:mid], req[mid:]]
    span = req[0]
    n_days = (span.end - span.start).days + 1
    if n_days <= 1:
        return []
    mid = span.start + timedelta(days=n_days // 2)
    day_set = set(span.days)
    first_end = mid - timedelta(days=1)
    halves = [(span.start, first_end), (mid, span.end)]
    return [
        [_Span(span.key, s, e, [d for d in day_set if s <= d <= e])]
        for s, e in halves
    ]


def _extraction_limit() -> int:
    """Concurrent requests ONE extraction may run."""
    return max(1, min(
        int(settings.UNACAST_MAX_CONCURRENT_PER_EXTRACTION),
        int(settings.UNACAST_MAX_CONCURRENT_CALLS),
    ))


def _batch_args(
    req: list[_Span], key_to_poi: dict[str, dict]
) -> tuple[list[dict], dict[str, dict], dict[str, dict[_date, int]]]:
    """``_run_batch`` arguments for one planned request. Each span carries the
    days ITS OWN window covers, not the POI's whole gap list: persist_rows marks
    coverage from what it is handed, and a marked day is never re-bought. Each
    day also carries its span's length, so a truncated day records whether a
    narrower window could still repair it."""
    features: list[dict] = []
    k2p: dict[str, dict] = {}
    key_days: dict[str, dict[_date, int]] = {}
    for s in req:
        poi = key_to_poi[s.key]
        # The vendor 400s a whole request on a repeated Feature id, and one POI
        # with two gap runs is two spans sharing s.key that first-fit packing
        # puts side by side (thread 0aa5fa49: 61 features for 57 POIs, 26
        # lost). (key, start) is unique per span, split halves included;
        # parse_response strips the suffix so attribution still reads the key.
        features.append(build_feature(poi, s.key, s.start, s.end, feature_id=_span_fid(s)))
        k2p[s.key] = poi
        window = (s.end - s.start).days + 1
        key_days.setdefault(s.key, {}).update({d: window for d in s.days})
    return features, k2p, key_days


async def _settle(coros: list) -> None:
    """Run every request to completion, THEN re-raise the first error.

    return_exceptions so one failing request cannot cancel its siblings
    mid-flight — each has already paid for itself, and a cancelled one would
    lose data the budget was spent on.
    """
    results = await asyncio.gather(*coros, return_exceptions=True)
    errors = [r for r in results if isinstance(r, BaseException)]
    if errors:
        logger.warning(
            "Unacast: %d of %d request(s) failed — the rest persisted",
            len(errors), len(results),
        )
        raise errors[0]


# ── Budget ledger: reserve, then reconcile ───────────────────────────────────

async def reserve_call(*, period: str | None = None) -> bool:
    """Atomically reserve ONE call against this month's shared budget. Returns
    False when there is none left (caller must not fire the request).

    The quota is counted in calls, not observations: the vendor charges the same
    for a request that returns three observations as for one that returns the
    per-feature maximum. So the size of a batch is irrelevant here — only that
    a request is about to happen. This is why there is no pre-flight probe: an
    extra round trip to size a request would itself cost a call, doubling
    consumption to measure something admission does not use.

    The row lock is the whole point: up to UNACAST_MAX_CONCURRENT_CALLS calls
    can be in flight at once, each taking up to ~130s. A plain
    "check, fire, increment when done" would let every concurrent admission
    check see the same stale "budget available" before any of them commits.
    The reservation is visible to the others immediately; reconcile_call turns
    it into a committed call once the request has actually been made.
    """
    period = period or _period()
    cap = int(settings.UNACAST_MONTHLY_CALL_BUDGET)
    async with AsyncSessionLocal() as db:
        async with db.begin():
            row = (
                await db.execute(
                    select(UnacastUsageLedger)
                    .where(UnacastUsageLedger.period == period)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                row = UnacastUsageLedger(
                    period=period, observations_used=0, provisional_reserved=0, calls_made=0
                )
                db.add(row)
                await db.flush()
            committed = (row.calls_made or 0) + (row.provisional_reserved or 0)
            if committed + 1 > cap:
                logger.warning(
                    "Unacast budget refused: %d call(s) made + %d reserved + 1 > %d cap (%s)",
                    row.calls_made or 0, row.provisional_reserved or 0, cap, period,
                )
                return False
            row.provisional_reserved = (row.provisional_reserved or 0) + 1
    return True


async def reconcile_call(
    *, fired: bool, observations: int = 0, requests: int = 0,
    period: str | None = None, src: str | None = None,
) -> None:
    """Release the reservation and commit the call if one was actually made.

    ``fired`` is set immediately BEFORE the request goes out, not after it
    returns: a request that reached the vendor and then failed still consumed
    quota, so it must be counted. A reservation released without ever firing
    (refused a concurrency slot, say) commits nothing.

    ``observations`` is recorded as telemetry only — it is what the call
    returned, and it feeds capacity planning and the per-feature truncation
    question, but it never gates admission.

    ``src`` names the path that spent the budget (``None`` = observations/geo/
    search, ``"devices"`` = the Meta-upload path), so cost can be split by what
    it was spent ON, not just by who spent it.

    Two things are written, in ONE transaction:
      * the month's ledger row — the platform-wide budget guard;
      * one ``UnacastCallLog`` row — the per-user / per-thread attribution.
    Same transaction and the same ``fired`` condition, so a per-user report can
    never disagree with the month's total.

    Must run on the failure path too, or reservations leak and the budget reads
    as exhausted while nothing was spent.

    The whole body is wrapped in try/except: this always runs from a bare
    ``finally:`` ahead of ``release_concurrency_slot(lease)`` (see
    unacast_query.py's own caller and unacast_devices.py). An unguarded DB
    error here used to propagate, replace any in-flight exception from the
    caller's try body, AND skip that release call — leaking a concurrency
    slot from the shared FCFS pool on top of losing the reservation. Safe to
    swallow: the reservation being released lives in this same database, so
    if this write can't land, nothing else here could have either.
    """
    if fired:
        # Convenience view only: puts the call count on the same
        # token_transactions row as that turn's token cost, which is the
        # at-a-glance question. UnacastCallLog below is the source of truth —
        # this accumulator is a no-op outside a turn and is dropped entirely
        # when a turn spends no tokens.
        record_api_call("unacast_calls")
        record_api_call("unacast_requests", max(1, int(requests or 1)))

    period = period or _period()
    try:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                row = (
                    await db.execute(
                        select(UnacastUsageLedger)
                        .where(UnacastUsageLedger.period == period)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if row is None:
                    return
                row.provisional_reserved = max(0, (row.provisional_reserved or 0) - 1)
                if fired:
                    _requests = max(1, int(requests or 1))
                    row.calls_made = (row.calls_made or 0) + 1
                    # Real HTTP requests, which is what the vendor's DAILY limit
                    # counts. Retries happen inside UnacastClient, so this is >=
                    # calls_made and is the number that actually matters for the
                    # rate limit; calls_made stays the batch count for the monthly
                    # budget's own arithmetic.
                    row.requests_made = (row.requests_made or 0) + _requests
                    if observations:
                        row.observations_used = (row.observations_used or 0) + int(observations)

                    # The attribution half. Same transaction as the budget half
                    # above and gated on the same `fired`, which is what keeps
                    # SUM(UnacastCallLog.calls) == UnacastUsageLedger.calls_made.
                    # A call with no turn behind it (a script, the autopilot) is
                    # still logged, with NULL user/thread — that is the reconciling
                    # remainder, not a row to drop.
                    _user_id, _thread_id = current_turn_identity()
                    try:
                        _user_uuid = uuid.UUID(_user_id) if _user_id else None
                    except (ValueError, AttributeError, TypeError):
                        # Cost accounting must never be able to fail a paid call
                        # that already happened.
                        _user_uuid = None
                    db.add(UnacastCallLog(
                        period=period,
                        user_id=_user_uuid,
                        thread_id=_thread_id,
                        calls=1,
                        requests=_requests,
                        observations=int(observations or 0),
                        src=src,
                    ))
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.error("reconcile_call failed: %s", exc)


# ── Concurrency gate: shared, FCFS, Postgres-backed ──────────────────────────

async def acquire_concurrency_slot() -> uuid.UUID | None:
    """Take one of the shared concurrent-call slots, or None if all are busy.

    Serialized with a transaction-scoped advisory lock rather than
    SELECT ... FOR UPDATE: the check is "how many leases exist", and row locks
    can't guard against a concurrent INSERT of a row that doesn't exist yet.
    The advisory lock releases automatically at transaction end, so a crash
    mid-transaction can't wedge the gate.

    Leases older than UNACAST_LEASE_STALE_AFTER_S are reaped as abandoned (a
    process that died before releasing) — without this, one crash would
    permanently cost the platform a slot.
    """
    limit = int(settings.UNACAST_MAX_CONCURRENT_CALLS)
    stale_after = int(settings.UNACAST_LEASE_STALE_AFTER_S)
    lease_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        async with db.begin():
            await db.execute(select(func.pg_advisory_xact_lock(_GATE_LOCK_KEY)))
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after)
            reaped = await db.execute(
                delete(UnacastConcurrencyLease).where(UnacastConcurrencyLease.acquired_at < cutoff)
            )
            if reaped.rowcount:
                logger.warning("Unacast gate: reaped %d stale lease(s)", reaped.rowcount)
            held = (
                await db.execute(select(func.count()).select_from(UnacastConcurrencyLease))
            ).scalar_one()
            if held >= limit:
                return None
            db.add(UnacastConcurrencyLease(lease_id=lease_id, acquired_at=datetime.now(timezone.utc)))
    return lease_id


async def release_concurrency_slot(lease_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        async with db.begin():
            await db.execute(
                delete(UnacastConcurrencyLease).where(UnacastConcurrencyLease.lease_id == lease_id)
            )


async def wait_for_slot(writer=None) -> uuid.UUID:
    """Block until a slot frees up, narrating the wait so a queued interactive
    extraction doesn't look like a stalled stream.

    # ponytail: approximate FCFS via polling — under contention a later
    # arrival can occasionally win a slot before an earlier one. True FIFO
    # would need a LISTEN/NOTIFY wakeup queue; not worth it until the 8-slot
    # pool is actually observed to be a bottleneck.
    """
    deadline = time.monotonic() + _SLOT_WAIT_TIMEOUT_S
    announced = False
    while True:
        lease = await acquire_concurrency_slot()
        if lease is not None:
            return lease
        if time.monotonic() > deadline:
            raise UnacastConcurrencyTimeout(
                f"no Unacast slot free after {_SLOT_WAIT_TIMEOUT_S:.0f}s "
                f"(limit={settings.UNACAST_MAX_CONCURRENT_CALLS}, shared platform-wide)"
            )
        if writer and not announced:
            announced = True
            writer({"type": "thinking", "content": (
                "MAID: all shared Unacast request slots are busy — queued, waiting for capacity..."
            )})
        await asyncio.sleep(_SLOT_POLL_INTERVAL_S)


# ── Watermark + raw cache ────────────────────────────────────────────────────

# The vendor loads new observations daily as HOT, then de-duplicates and merges
# them into final COLD form about five days later (UNACAST-API-REFERENCE.md
# section 5): "expect duplicate/shifting HOT observations in the most recent 4-5
# days; COLD observations are stable and won't change further."
#
# Measured on the real cache, 85.4% of our pings are hot
# (docs/maid_signal_quality_baseline.md section 1) — because the default prompt
# is a 7-day lookback, so almost every extraction buys data that is still
# provisional. The watermark marked those days covered PERMANENTLY and never
# re-bought, which locks known-duplicated pings into the audience forever.
HOT_WINDOW_DAYS = 5


def _is_provisional(day: _date, fetched_at: datetime | None) -> bool:
    """Was this (POI, day) bought while the vendor's data for it was still HOT?

    Derived from ``fetched_at`` rather than a stored flag: a day fetched fewer
    than HOT_WINDOW_DAYS after it happened was provisional at purchase time.
    That is exactly the information a dedicated column would carry, and it is
    already on the row.
    """
    if fetched_at is None:
        return False
    return (fetched_at.date() - day).days < HOT_WINDOW_DAYS


def _has_gone_cold(day: _date, today: _date | None = None) -> bool:
    """Is the vendor's data for this day now final (past the HOT window)?"""
    today = today or datetime.now(timezone.utc).date()
    return (today - day).days >= HOT_WINDOW_DAYS


async def covered_days_bulk(
    key_to_poi: dict[str, dict], *, src: str | None = None,
) -> dict[str, set[_date]]:
    """Days the cache can already answer, per requested ring, EXCLUDING any that
    need re-buying.

    One query for every ring rather than a session and a round trip per POI —
    a 50-POI extraction was making 50 of each just to read the watermark.

    A day is covered when some purchase at the SAME CENTRE bought it at a radius
    at least this ring's: every ping inside a smaller ring is inside the larger
    one, and ``read_cached`` cuts it back out by distance. A radius edit from
    500 m down to 100 m therefore costs no call. A day is NOT covered when:

      * it was bought while the vendor's data was still HOT and has since gone
        COLD — re-bought once with the de-duplicated values, then final;
      * the only purchase that could serve it was truncated at a LARGER radius —
        a capped disc is a non-random sample, not a superset of the smaller ring;
      * it was truncated at this ring's own radius inside a multi-day window —
        re-bought with a narrower one. A truncated one-day window has no finer
        split left, so it stays covered and disclosed;
      * its coverage row predates centres (no ``center_key``) — re-bought once.

    Truncation is decided by radius+day's MOST RECENTLY BOUGHT covering row,
    not any covering row: ``persist_rows`` deletes and rewrites the WHOLE disc
    of whatever radius it just bought, and each distinct radius keeps its own
    coverage row (radius is part of ``poi_key``) forever, side by side. So an
    older row that still says ``truncated=False`` for radius 100 m can lie —
    if a later 500 m purchase at the same centre/day came back truncated, its
    delete+rewrite covered the 100 m disc too, and the 500 m row is what
    actually describes what's on disk there now. Picking the newest covering
    row rather than OR-ing every row's flag also keeps re-buying bounded: a
    smaller ring re-bought fresh AFTER a poisoning purchase produces its own,
    newer, clean row, which then governs again.

    ``src`` scopes the watermark to one provenance: ``None`` (real pings from
    observations/geo/search) never counts a ``"devices"`` day as covered, and
    vice versa — see ``UnacastRawObservation.src``. Two provenances at the same
    centre/day would otherwise satisfy each other's watermark and one path
    would silently start serving the other's rows.
    """
    out: dict[str, set[_date]] = {k: set() for k in key_to_poi}
    wanted = {
        k: (c, purchase_radius_m(p))
        for k, p in key_to_poi.items()
        if (c := center_key(p)) is not None
    }
    if not wanted:
        return out
    by_center: dict[str, list[tuple]] = {}
    async with AsyncSessionLocal() as db:
        # Core columns, not ORM attributes: this is a pure single-table read
        # and needs no mapper configuration, which keeps it callable from a
        # standalone script (the measure/verify tooling) as well as the app.
        _cov = UnacastFetchCoverage.__table__.c
        src_clause = _cov.src.is_(None) if src is None else _cov.src == src
        rows = await db.execute(
            select(
                _cov.center_key, _cov.radius_m, _cov.date, _cov.fetched_at,
                _cov.truncated, _cov.window_days,
            ).where(
                _cov.center_key.in_(sorted({c for c, _r in wanted.values()})),
                src_clause,
            )
        )
        for row in rows.all():
            by_center.setdefault(row[0], []).append(tuple(row[1:]))

    stale = 0
    for key, (center, radius) in wanted.items():
        by_day: dict[_date, list[tuple]] = {}
        for bought_radius, day, fetched_at, truncated, window_days in by_center.get(center, ()):
            if bought_radius is None or bought_radius < radius:
                continue
            by_day.setdefault(day, []).append(
                (fetched_at, bought_radius, truncated, window_days)
            )
        for day, rows in by_day.items():
            # The most recently bought covering purchase governs — see the
            # docstring above. Ties (same fetched_at) can't happen: fetched_at
            # is stamped per persist_rows call, one call per batch.
            fetched_at, bought_radius, truncated, window_days = max(rows, key=lambda r: r[0])
            if _is_provisional(day, fetched_at) and _has_gone_cold(day):
                stale += 1
                continue
            if truncated:
                if bought_radius > radius:
                    continue
                # Rehydrate the partial-sample disclosure from the durable
                # column. _TRUNCATED_FEATURES is only populated by
                # parse_response, i.e. by an actual API call — so a CACHE-ONLY
                # run (the common case once the watermark is warm) used to
                # report nothing truncated and present a sampled audience as
                # complete. The per-device detail is not recoverable here (it
                # lived only in the response body), so this records the fact
                # without inventing the breakdown. Set for a day about to be
                # repaired too: it is also what halves the repair's window.
                _TRUNCATED_FEATURES.setdefault(key, {
                    "returned": None, "possible": None,
                    "fraction": None, "devices": (),
                })
                if (window_days or 1) > 1:
                    continue
            out[key].add(day)
    if stale:
        logger.info(
            "Unacast: %d (ring, day) pair(s) were bought while the vendor's data was "
            "still HOT and have since gone COLD — re-buying once for the "
            "de-duplicated values", stale,
        )
    return out


def _dist2_sql(lat: str, lng: str, clat: str, clng: str) -> str:
    """SQL for the squared ground distance in metres between a ping and a ring
    centre. Equirectangular — under 0.1% off at the 2.8 km radius cap — and
    compared against a squared radius, so no sqrt runs per row."""
    return (
        f"(power(({lat} - {clat}) * 111320.0, 2) "
        f"+ power(({lng} - {clng}) * 111320.0 * cos(radians({clat})), 2))"
    )


async def persist_rows(
    rows: list[dict],
    key_days: dict[str, dict[_date, int]],
    truncated_keys: set[str] | frozenset = frozenset(),
    *,
    key_to_poi: dict[str, dict] | None = None,
    src: str | None = None,
) -> None:
    """Append fetched pings to the durable cache and mark their days covered.

    Coverage is marked for the days that were REQUESTED, not the days that
    happened to return data — a quiet POI with genuinely zero visitors on a
    day must not be re-queried forever just because it returned nothing.

    ``key_days`` maps each purchased key to ``{day: window_days}``, the length
    of the feature window that day was bought inside. ``truncated_keys`` are the
    features THIS response capped. ``key_to_poi`` gives each key its centre and
    purchased radius; anything written without them carries no centre and is
    never served to a different radius.
    """
    from sqlalchemy.dialects.postgresql import insert as _pg_insert

    purchases = {
        key: (center_key(poi), purchase_radius_m(poi), float(poi["lat"]), float(poi["lng"]))
        for key, poi in (key_to_poi or {}).items()
        if poi.get("lat") is not None and poi.get("lng") is not None
    }
    for row in rows:
        p = purchases.get(row.get("poi_key"))
        row["center_key"] = p[0] if p else None
        row["src"] = src

    async with AsyncSessionLocal() as db:
        async with db.begin():
            # Replace, don't append, what this batch re-bought. A covered day
            # comes back through the watermark when it was bought HOT and has
            # since gone COLD, or was truncated inside a window that can now be
            # narrower — and either way the old rows are what must go. An insert
            # that skips on conflict kept every stale HOT copy and added the
            # vendor's shifted ones, paying for a correction that never landed.
            # Scoped to the centre, this batch's own days and this purchase's
            # disc: pings a larger, still-stale purchase holds outside it stay
            # until that one is re-bought. Same transaction as the insert, so a
            # reader sees the old set or the new one, never neither.
            for key, days in key_days.items():
                p = purchases.get(key)
                if not p or not days:
                    continue
                c_key, radius_m, clat, clng = p
                for start, end in _contiguous_ranges(sorted(days)):
                    await db.execute(
                        text(
                            "DELETE FROM unacast_raw_observations "
                            "WHERE observed_at >= :start AND observed_at < :stop "
                            # Scoped to this batch's OWN provenance: a devices-path
                            # re-buy must never delete real observation pings at
                            # the same centre/day, or vice versa (see
                            # UnacastRawObservation.src).
                            "AND src IS NOT DISTINCT FROM :src AND ("
                            f"(center_key = :c AND {_dist2_sql('lat', 'lng', ':clat', ':clng')} <= :r2) "
                            # A row from before centres existed carries only its
                            # purchase key. Left in place it would block the
                            # re-bought copy on the older unique index, and the
                            # centre-keyed read would then find neither.
                            "OR (center_key IS NULL AND poi_key = :k))"
                        ),
                        {
                            "c": c_key, "k": key, "clat": clat, "clng": clng,
                            "r2": float(radius_m) ** 2, "src": src,
                            "start": datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
                            "stop": datetime(end.year, end.month, end.day, tzinfo=timezone.utc)
                                    + timedelta(days=1),
                        },
                    )

            # Bulk, chunked. This used to be one ORM object per ping — 21,924
            # individual INSERTs on the live test — plus a SELECT per (key, day)
            # to test existence. That matters beyond speed: persist_rows runs
            # INSIDE _run_batch's try, BEFORE the finally that releases the
            # concurrency lease, and the margin between
            # UNACAST_REQUEST_TIMEOUT_S and UNACAST_LEASE_STALE_AFTER_S is
            # small — a slow persist gets its own lease reaped mid-call and the
            # gate over-admits.
            #
            # ON CONFLICT DO NOTHING, untargeted, because more than one unique
            # index can fire: one ping per device-second per CENTRE (a 500 m
            # purchase re-returns a 100 m one's pings), and the older
            # per-purchase index, which a re-bought legacy row still trips. The
            # vendor also returns the same device at the same second more than
            # once in ONE response (seen live 2026-09-11 at Denver Union
            # Station). A plain INSERT raised on any of these and lost an
            # already-billed call. The first copy wins.
            raw_insert = _pg_insert(UnacastRawObservation.__table__).on_conflict_do_nothing()
            for i in range(0, len(rows), _PERSIST_CHUNK):
                chunk = rows[i:i + _PERSIST_CHUNK]
                if chunk:
                    await db.execute(raw_insert, chunk)

            # Coverage as a single upsert. `ON CONFLICT DO NOTHING` on the
            # (poi_key, date) primary key also closes the read-then-write race
            # between two sessions extracting the same POI-day at once, which
            # the previous db.get/db.add pair could not.
            #
            # `fetched_at` is stamped explicitly rather than left to the server
            # default: a re-bought HOT day must carry the NEW timestamp, or
            # _is_provisional would keep reporting it stale forever.
            # `truncated` is the durable half of the partial-sample disclosure:
            # the vendor capped this feature in THIS response, so its frequency
            # counts are floors. Written here rather than left in memory because
            # a later CACHE-ONLY read makes no call and would otherwise have no
            # idea. `center_key`/`radius_m` say what the day can serve — any ring
            # up to this radius at this centre — and `window_days` whether a
            # truncated day could still be repaired by a narrower window.
            _now = datetime.now(timezone.utc)
            coverage = [
                {
                    "poi_key": key,
                    "date": d,
                    "fetched_at": _now,
                    "truncated": key in truncated_keys,
                    "center_key": purchases[key][0] if key in purchases else None,
                    "radius_m": purchases[key][1] if key in purchases else None,
                    "window_days": window,
                    "src": src,
                }
                for key, days in key_days.items()
                for d, window in days.items()
            ]
            if coverage:
                upsert = _pg_insert(UnacastFetchCoverage.__table__).values(coverage)
                await db.execute(
                    upsert.on_conflict_do_update(
                        index_elements=["poi_key", "date"],
                        set_={
                            "fetched_at": _now,
                            "truncated": upsert.excluded.truncated,
                            "center_key": upsert.excluded.center_key,
                            "radius_m": upsert.excluded.radius_m,
                            "window_days": upsert.excluded.window_days,
                            "src": upsert.excluded.src,
                        },
                    )
                )


def _rings_join(
    key_to_poi: dict[str, dict], days: list[_date], *, src: str | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """The FROM/WHERE ``read_cached`` and ``cached_observation_count`` share:
    cached pings joined to each requested ring by centre, cut to the window and
    to that ring's own radius. None when there is nothing to read.

    ``src`` scopes the read to one provenance (see ``covered_days_bulk``) so a
    devices-path read never mixes in real observation pings at the same centre
    or vice versa."""
    rings = [
        (k, c, float(p["lat"]), float(p["lng"]), float(purchase_radius_m(p)) ** 2)
        for k, p in key_to_poi.items()
        if (c := center_key(p)) is not None
    ]
    if not rings or not days:
        return None
    params: dict[str, Any] = {
        "start": datetime(days[0].year, days[0].month, days[0].day, tzinfo=timezone.utc),
        "end": datetime(days[-1].year, days[-1].month, days[-1].day, 23, 59, 59, tzinfo=timezone.utc),
    }
    values: list[str] = []
    for i, (k, c, lat, lng, r2) in enumerate(rings):
        values.append(
            f"(CAST(:k{i} AS text), CAST(:c{i} AS text), CAST(:la{i} AS float8), "
            f"CAST(:ln{i} AS float8), CAST(:r{i} AS float8))"
        )
        params.update({f"k{i}": k, f"c{i}": c, f"la{i}": lat, f"ln{i}": lng, f"r{i}": r2})
    src_clause = "o.src IS NULL" if src is None else "o.src = :src"
    sql = (
        "FROM unacast_raw_observations o "
        f"JOIN (VALUES {', '.join(values)}) AS q(poi_key, center_key, clat, clng, r2) "
        "ON o.center_key = q.center_key "
        "WHERE o.observed_at >= :start AND o.observed_at <= :end "
        f"AND {_dist2_sql('o.lat', 'o.lng', 'q.clat', 'q.clng')} <= q.r2 "
        f"AND {src_clause}"
    )
    if src is not None:
        params["src"] = src
    return sql, params


async def cached_observation_count(
    key_to_poi: dict[str, dict], days: list[_date], *, src: str | None = None,
) -> int:
    """How many pings ``read_cached``/``iter_cached`` would return, without
    reading them."""
    joined = _rings_join(key_to_poi, days, src=src)
    if joined is None:
        return 0
    sql, params = joined
    async with AsyncSessionLocal() as db:
        return int((await db.execute(text(f"SELECT count(*) {sql}"), params)).scalar_one())


def _cached_row(poi_key: str, m: str, lat, lng, ts, flags, hot, dist_m) -> dict:
    """One cached ping in the shape ``query_maids`` returns — shared by
    ``read_cached`` and ``iter_cached`` so the two can never drift."""
    return {
        # The REQUESTED ring's key: what folds pings into visits downstream
        # (_spot_key) and attributes them. It once was dropped in favour of a
        # self-computed H3 cell, which split one visit across hexagon
        # boundaries for 26.1% of device-POI pairs and inflated visit counts
        # by 14.5% (docs/maid_signal_quality_baseline.md).
        "poi_key": poi_key,
        "maid": m,
        "lat": float(lat),
        "lng": float(lng),
        "ts": ts.astimezone(timezone.utc).isoformat(),
        "forensic_flags": flags,
        "hot": hot,
        "dist_m": float(dist_m),
    }


async def iter_cached(
    key_to_poi: dict[str, dict], days: list[_date], *, src: str | None = None,
    batch: int = 20_000,
):
    """``read_cached``, streamed via a server-side cursor.

    Nothing downstream needs the whole ping list in memory at once: the
    signal-quality gate and the fold (``executors/maid.py``) are both per-row.
    Materialising every ping first (~2.5 KB each, measured) was the only reason
    an extraction's size ever needed a ceiling; this is what makes peak memory
    the FOLD's size instead of the raw ping count, now that no search is
    refused for being large.
    """
    joined = _rings_join(key_to_poi, days, src=src)
    if joined is None:
        return
    sql, params = joined
    dist2 = _dist2_sql("o.lat", "o.lng", "q.clat", "q.clng")
    async with AsyncSessionLocal() as db:
        result = await db.stream(
            text(
                "SELECT q.poi_key, o.maid, o.lat, o.lng, o.observed_at, "
                f"o.forensic_flags, o.hot, sqrt({dist2}) AS dist_m {sql}"
            ),
            params,
        )
        result = result.yield_per(batch)
        async for poi_key, m, lat, lng, ts, flags, hot, dist_m in result:
            yield _cached_row(poi_key, m, lat, lng, ts, flags, hot, dist_m)


async def read_cached(
    key_to_poi: dict[str, dict], days: list[_date], *, src: str | None = None,
) -> list[dict]:
    """Read the full requested window back out of the cache (old + just-fetched)
    in the per-ping shape query_maids returns — one row per ping per requested
    ring.

    By centre and distance, not by purchase key: a 100 m ring's pings may have
    been bought under a 500 m purchase at the same centre (see
    ``covered_days_bulk``). The distance cut runs in Postgres, so a small ring
    never pulls a large disc into Python, and it applies to direct purchases
    too, so an audience does not depend on which purchase happened to serve it
    — it trims only the vendor's ~1% geohash padding past the ring's edge.

    Collects ``iter_cached`` into a list — kept for callers (``query_pois_audience``,
    tests) that want everything at once; ``query_maids``'s main path streams
    instead (see ``UnacastMAIDQuerier._iter_query_maids``).
    """
    return [row async for row in iter_cached(key_to_poi, days, src=src)]


# ── The querier ──────────────────────────────────────────────────────────────

async def estimate_cost(dates: list[str], pois: list[dict]) -> dict:
    """What this extraction would cost, WITHOUT calling the vendor.

    Features and calls are pure arithmetic over the watermark: which POI-days
    are still unpaid for, collapsed into ranges, packed to the request cap. So
    there is no probe, no round trip, and no reason not to show it before the
    user commits.

    Returns ``{"features", "calls", "pois", "days", "cached_pois", "eta_s"}``.
    ``calls`` comes from the SAME planner the fetch runs (``plan_requests``),
    so ``0`` means fully cached and a non-zero count is what admission will
    actually consume. ``eta_s`` is a flat bound — every request retried by
    ``_split_request`` costs at most one more ``UNACAST_REQUEST_TIMEOUT_S``, not
    a volume-derived guess (that guess is what used to under/over-predict wall
    time; see ``_split_request``'s docstring in the querier below).
    """
    days = _dates_to_days(dates)
    keyed = [
        (k, p) for p in pois
        if (k := poi_key(p)) and p.get("lat") is not None and p.get("lng") is not None
    ]
    if not days or not keyed:
        return {"features": 0, "calls": 0, "pois": len(pois), "days": len(days),
                "cached_pois": 0, "eta_s": 0}

    key_to_poi = dict(keyed)
    covered = await covered_days_bulk(key_to_poi)
    gaps: dict[str, list[_date]] = {}
    for k, _p in keyed:
        gap = [d for d in days if d not in covered.get(k, set())]
        if gap:
            gaps[k] = gap

    plan: list[list[_Span]] = []
    if gaps:
        gap_pois = {k: p for k, p in keyed if k in gaps}
        plan = plan_requests(gap_pois, gaps)
    limit = _extraction_limit()
    return {
        "features": sum(len(req) for req in plan),
        "calls": len(plan),
        "pois": len(keyed),
        "days": len(days),
        "cached_pois": len(keyed) - len(gaps),
        "eta_s": round(math.ceil(len(plan) / max(1, limit)) * float(settings.UNACAST_REQUEST_TIMEOUT_S)),
    }


class UnacastMAIDQuerier:
    """Buys, caches and gates Unacast observations behind ``query_maids``."""

    def __init__(self, client=None) -> None:
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from app.services.unacast_client import UnacastClient

            self._client = UnacastClient()
        return self._client

    async def query_maids(
        self, dates: list[str], pois: list[dict], *, writer=None,
        failures: dict | None = None,
    ) -> list[dict]:
        """Return device observations for the POIs over ``dates``, one dict per
        RAW PING — ``{poi_key, maid, lat, lng, ts, forensic_flags, hot, dist_m,
        radius_m}`` — already through the signal-quality gate.

        ``failures``, when given, turns a fetch that failed part-way into a
        partial result: what landed is returned, and ``failures`` receives the
        error and the ``failed_keys`` whose days are still unbought. Without it,
        or when nothing at all can be read back, the error is raised as before —
        a query that never ran is never mistaken for an empty audience.
        """
        days = _dates_to_days(dates)
        if not days or not pois:
            return []

        keyed: list[tuple[str, dict]] = []
        for p in pois:
            k = poi_key(p)
            if k and p.get("lat") is not None and p.get("lng") is not None:
                keyed.append((k, p))
        if not keyed:
            logger.warning("Unacast: no POIs with usable coordinates — nothing to query")
            return []
        key_to_poi = dict(keyed)

        # Per POI: only the days no purchase can already answer.
        covered = await covered_days_bulk(key_to_poi)
        gaps: dict[str, list[_date]] = {}
        for k in key_to_poi:
            gap = [d for d in days if d not in covered.get(k, set())]
            if gap:
                gaps[k] = gap

        fetch_error: Exception | None = None
        if gaps:
            try:
                await self._fetch_gaps(key_to_poi, gaps, writer=writer)
            except Exception as exc:  # noqa: BLE001 — re-raised below unless partial is wanted
                if failures is None:
                    raise
                fetch_error = exc
        else:
            logger.info("Unacast: full window already cached for %d POI(s) — no API call", len(keyed))
            if writer:
                writer({"type": "thinking", "content": (
                    f"MAID: all {len(keyed)} location(s) already cached for this window — "
                    f"no Unacast request needed"
                )})

        rows = await read_cached(key_to_poi, days)
        if fetch_error is not None:
            # Which spots are still missing is what the watermark says now:
            # every batch that landed marked its days before the error surfaced.
            still = await covered_days_bulk({k: key_to_poi[k] for k in gaps})
            failed = {
                k for k, gap in gaps.items()
                if any(d not in still.get(k, set()) for d in gap)
            }
            if failed:
                if not rows:
                    raise fetch_error
                failures.update(error=fetch_error, failed_keys=failed)
        return self._gate(rows, key_to_poi, writer=writer)

    async def iter_maids(
        self, dates: list[str], pois: list[dict], *, writer=None,
        failures: dict | None = None,
    ):
        """``query_maids``, streamed: same orchestration (fetch the gaps, same
        partial-failure detection), but read back and gated via
        ``iter_cached``/``_gate_row`` one ping at a time instead of collected
        into a list first. For a caller that folds as it goes
        (``executors/maid.py``'s ``_query_maids_with_retry``), so peak memory
        is the fold's size, not the raw ping count — the reason the extraction
        size ceiling used to exist. ``query_maids`` is now a thin wrapper over
        this that collects into a list, for callers that want everything at
        once.
        """
        days = _dates_to_days(dates)
        if not days or not pois:
            return

        keyed: list[tuple[str, dict]] = []
        for p in pois:
            k = poi_key(p)
            if k and p.get("lat") is not None and p.get("lng") is not None:
                keyed.append((k, p))
        if not keyed:
            logger.warning("Unacast: no POIs with usable coordinates — nothing to query")
            return
        key_to_poi = dict(keyed)

        covered = await covered_days_bulk(key_to_poi)
        gaps: dict[str, list[_date]] = {}
        for k in key_to_poi:
            gap = [d for d in days if d not in covered.get(k, set())]
            if gap:
                gaps[k] = gap

        fetch_error: Exception | None = None
        if gaps:
            try:
                await self._fetch_gaps(key_to_poi, gaps, writer=writer)
            except Exception as exc:  # noqa: BLE001 — re-raised below unless partial is wanted
                if failures is None:
                    raise
                fetch_error = exc
        else:
            logger.info("Unacast: full window already cached for %d POI(s) — no API call", len(keyed))
            if writer:
                writer({"type": "thinking", "content": (
                    f"MAID: all {len(keyed)} location(s) already cached for this window — "
                    f"no Unacast request needed"
                )})

        any_row = False
        async for row in self._iter_gated(key_to_poi, days, writer=writer):
            any_row = True
            yield row

        if fetch_error is not None:
            still = await covered_days_bulk({k: key_to_poi[k] for k in gaps})
            failed = {
                k for k, gap in gaps.items()
                if any(d not in still.get(k, set()) for d in gap)
            }
            if failed:
                if not any_row:
                    raise fetch_error
                failures.update(error=fetch_error, failed_keys=failed)

    @staticmethod
    async def _iter_gated(key_to_poi: dict[str, dict], days: list[_date], *, writer=None):
        """``iter_cached`` filtered through the signal-quality gate, row by row.

        Same rule as ``_gate`` (grouped stats aside — the per-row admission
        test is identical: ``maid_signal.ping_admitted``), so a stricter/looser
        accuracy mode re-derives an existing extraction identically whichever
        path reads it back.
        """
        from app.graph.maid_signal import describe_gate, gate_settings, ping_admitted
        from app.graph.maid_query import _haversine_km

        exclude_mask, mode = gate_settings()
        kept = 0
        dropped = 0
        async for row in iter_cached(key_to_poi, days):
            poi = key_to_poi.get(row.get("poi_key") or "") or {}
            radius_m = float(purchase_radius_m(poi))
            plat, plng = poi.get("lat"), poi.get("lng")
            if row.get("dist_m") is None and plat is not None and plng is not None:
                try:
                    row["dist_m"] = _haversine_km(
                        float(row["lat"]), float(row["lng"]), float(plat), float(plng),
                    ) * 1000.0
                except (KeyError, TypeError, ValueError):
                    pass
            row["radius_m"] = radius_m
            flags = int(row.get("forensic_flags") or 0)
            if exclude_mask and (flags & exclude_mask):
                dropped += 1
                continue
            if not ping_admitted(
                flags, radius_m, exclude_mask=0, accuracy_mode=mode, dist_m=row.get("dist_m"),
            ):
                dropped += 1
                continue
            kept += 1
            yield row

        if dropped and writer:
            gate = describe_gate()
            writer({"type": "thinking", "content": (
                f"MAID: signal gate dropped {dropped:,} of {kept + dropped:,} ping(s) "
                f"(accuracy={gate['accuracy_mode']}, excluding "
                f"{', '.join(gate['excluded_flags']) or 'nothing'})"
            )})

    @staticmethod
    def _gate(rows: list[dict], key_to_poi: dict[str, dict], *, writer=None) -> list[dict]:
        """Drop pings that cannot evidence presence inside their own POI's ring.

        Applied on the way OUT of the cache, not as an ``excludeFlags`` query
        param, so the gate is retunable and an existing extraction can be
        re-derived under a stricter rule without re-buying anything. Grouped by
        POI because the accuracy test is relative to that POI's radius — a
        50-220 m ping is usable evidence for a 500 m ring and useless for a
        60 m one. See app/graph/maid_signal.py for the measured impact.
        """
        from app.graph.maid_signal import DRIVE_BY_EXCLUDE_MASK, apply_gate, describe_gate

        if not rows:
            return rows
        by_poi: dict[str, list[dict]] = {}
        for row in rows:
            by_poi.setdefault(row.get("poi_key") or "", []).append(row)

        from app.graph.maid_query import _haversine_km

        kept: list[dict] = []
        dropped = 0
        for poi_key, poi_rows in by_poi.items():
            poi = key_to_poi.get(poi_key) or {}
            radius_m = float(purchase_radius_m(poi))

            # Distance from the ring centre, once per ping. read_cached already
            # computed it in SQL (it is also the cut that serves a smaller ring
            # from a larger purchase); a row from any other path gets it here.
            # Set BEFORE the gate, because the "positional" accuracy mode reads
            # it, and it is what lets a single-ping visit be judged confident or
            # not — see cluster_visits.
            plat, plng = poi.get("lat"), poi.get("lng")
            for row in poi_rows:
                if row.get("dist_m") is None and plat is not None and plng is not None:
                    try:
                        row["dist_m"] = _haversine_km(
                            float(row["lat"]), float(row["lng"]),
                            float(plat), float(plng),
                        ) * 1000.0
                    except (KeyError, TypeError, ValueError):
                        pass
                row["radius_m"] = radius_m
            # A POI whose whole point is drive-by traffic (a billboard: "target
            # everyone who drives past it daily") wants the pings the default
            # preset throws away as noise. Per-POI, not per-request: this loop
            # already groups by POI, so a request that mixes a billboard with
            # an ordinary walk-in store keeps each gated correctly.
            exclude_mask = (
                DRIVE_BY_EXCLUDE_MASK if poi.get("targeting_intent") == "drive_by" else None
            )
            poi_kept, stats = apply_gate(poi_rows, radius_m, exclude_mask=exclude_mask)

            kept.extend(poi_kept)
            dropped += stats["dropped_flags"] + stats["dropped_accuracy"]

        if dropped and writer:
            gate = describe_gate()
            writer({"type": "thinking", "content": (
                f"MAID: signal gate dropped {dropped:,} of {len(rows):,} ping(s) "
                f"(accuracy={gate['accuracy_mode']}, excluding "
                f"{', '.join(gate['excluded_flags']) or 'nothing'})"
            )})
        return kept

    async def _fetch_gaps(
        self, key_to_poi: dict[str, dict], gaps: dict[str, list[_date]], *, writer=None,
    ) -> None:
        """Fetch only the uncached days. Requests are packed by ``plan_requests``
        using ONLY the vendor's legality limits (feature count, day-window) —
        never a predicted size, and never refused up front. Attribution is per
        feature (``Feature.id`` is the POI key), so packing across POIs and POI
        groups loses nothing.

        Concurrency: requests run bounded. They used to run one after another,
        so 50 POIs meant five sequential DIRECT calls while the 8-slot gate sat
        idle. That gate is for fairness ACROSS users; the per-extraction bound
        keeps one extraction from starving the others.

        Recovery: a request that times out is halved by ``_split_request`` —
        by feature count if it holds more than one, else by day-window — and
        the halves retried, recursively. It is NOT re-sent as-is: the vendor
        could not answer that exact body. A request already down to one POI on
        one day that still times out cannot be split further and raises
        ``UnacastRequestTimeout``, which the outer retry does not repeat.
        """
        plan = plan_requests(key_to_poi, gaps)
        if not plan:
            return

        limit = _extraction_limit()
        sem = asyncio.Semaphore(limit)
        logger.info(
            "Unacast: %d POI(s) -> %d request(s), up to %d at a time",
            len(gaps), len(plan), limit,
        )
        if writer:
            writer({"type": "thinking", "content": (
                f"MAID: {len(plan)} Unacast request(s), running up to {limit} at a time"
            )})

        # Spans still owed per POI, for the progress line. A split swaps the
        # timed-out request's spans for its halves'.
        pending: dict[str, int] = {}
        for req in plan:
            for s in req:
                pending[s.key] = pending.get(s.key, 0) + 1

        # A half-open breaker admits ONE probe; the extraction's other batches,
        # fired in the same instant, all hit UnacastCircuitOpen against a vendor
        # that is in fact fine (thread 23f83f99: the probe succeeded and the 4
        # batches that lost the claim were dropped — 40 of 50 POIs). Park them
        # and retry once the first pass, probe included, has settled.
        # ponytail: ONE retry, and only for a probe this extraction ran itself;
        # a batch that lost to another tenant's still-running probe fails fast
        # as before. Upgrade path: poll the breaker row for the probe's verdict.
        deferred: list[list[_Span]] = []
        defer_open = True

        async def _run(req: list[_Span]) -> None:
            try:
                async with sem:
                    await self._run_batch(*_batch_args(req, key_to_poi), writer=writer)
            except UnacastCircuitOpen:
                if not defer_open:
                    raise
                deferred.append(req)
                return
            except httpx.ReadTimeout:
                keys = {s.key for s in req}
                halves = _split_request(req)
                if not halves:
                    raise UnacastRequestTimeout(
                        f"the audience data provider timed out on {len(keys)} very busy "
                        f"location(s) even at the smallest possible request"
                    ) from None
                for s in req:
                    pending[s.key] -= 1
                for r in halves:
                    for s in r:
                        pending[s.key] = pending.get(s.key, 0) + 1
                logger.warning(
                    "Unacast: request of %d feature(s) timed out — split into %d "
                    "smaller request(s)",
                    len(req), len(halves),
                )
                if writer:
                    writer({"type": "thinking", "content": (
                        f"MAID: a request over {len(keys)} busy location(s) timed out — "
                        f"splitting it into {len(halves)} smaller request(s)"
                    )})
                await _settle([_run(r) for r in halves])
                return
            for s in req:
                pending[s.key] -= 1

        started = time.monotonic()

        async def _heartbeat() -> None:
            # A DIRECT call is silent until it returns; without this a long
            # extraction looks exactly like a hung one (thread 77e403d3).
            while True:
                await asyncio.sleep(_HEARTBEAT_S)
                done = sum(1 for k in gaps if pending.get(k, 0) <= 0)
                elapsed = int(time.monotonic() - started)
                writer({"type": "update", "content": (
                    f"Pulling visitors… {done}/{len(gaps)} spot(s) done · "
                    f"{elapsed // 60}:{elapsed % 60:02d}"
                )})

        beat = asyncio.create_task(_heartbeat()) if writer else None
        try:
            first_error: BaseException | None = None
            try:
                await _settle([_run(req) for req in plan])
            except Exception as exc:  # noqa: BLE001 — re-raised below, after the retry
                first_error = exc
            if deferred:
                defer_open = False
                if writer:
                    writer({"type": "thinking", "content": (
                        f"MAID: {len(deferred)} request(s) waited out the vendor "
                        f"recovery check — retrying them"
                    )})
                await _settle([_run(req) for req in list(deferred)])
            if first_error is not None:
                raise first_error
        finally:
            if beat is not None:
                beat.cancel()

    async def _run_batch(
        self,
        features: list[dict],
        key_to_poi: dict[str, dict],
        key_days: dict[str, list[_date]],
        *,
        writer=None,
    ) -> None:
        """Fire ONE request for this batch and persist what comes back.

        **Retry lives in the transport, not here.** ``UnacastClient`` runs a
        lease-aware retry budget: it will not start a new attempt that cannot
        finish inside the concurrency lease this batch holds
        (``_retry_budget_s``), it honours the vendor's ``Retry-After``, and it
        jitters backoff because up to ``UNACAST_MAX_CONCURRENT_CALLS`` workers
        share one API key and a plain exponential makes them retry in lockstep.
        Duplicating that loop here would fight it.

        What this level owns is **admission and accounting**: the circuit
        breaker, the shared monthly budget, the concurrency lease, and reporting
        how many requests were actually metered.
        """
        from app.services.unacast_client import (
            REQUESTS_MADE,
            UnacastAPIError,
            UnacastNoContact,
            UnacastRequestRejected,
        )

        # 0. Circuit breaker, BEFORE the reservation. During a vendor outage
        #    every batch used to reserve, fire, fail and commit a call — so an
        #    outage drained the shared monthly budget while returning nothing.
        await _breaker_check()

        # 1. Budget admission — FCFS against the shared monthly CALL cap. No
        #    pre-flight sizing probe: the quota counts calls, so a probe would
        #    spend a second call to measure something admission never reads.
        #    Batch size is free — pack to MAX_FEATURES_PER_REQUEST.
        if not await reserve_call():
            raise UnacastBudgetExhausted(
                f"the shared monthly Unacast budget "
                f"({settings.UNACAST_MONTHLY_CALL_BUDGET:,} API calls) is exhausted. "
                f"It resets at the start of next month."
            )

        # 2. Concurrency admission, then the call. The reservation and the slot
        #    must be released on EVERY path, including failure.
        lease = None
        actual = 0
        requests = 0
        # Reset BEFORE anything that can fail. `finally` reads this to decide
        # whether a call was metered, and a ContextVar keeps whatever an earlier
        # call in the same task — or the parent a gathered batch was copied
        # from — left behind. A slot timeout used to read that stale count and
        # charge the monthly budget for a request that never went out.
        REQUESTS_MADE.set(0)
        try:
            lease = await wait_for_slot(writer=writer)
            if writer:
                writer({"type": "thinking", "content": (
                    f"MAID: querying Unacast for {len(features)} location-window(s)"
                )})
            payload = await self.client.post(_ENDPOINT, _body(features))
            # The vendor answered, so it is healthy. Recorded before our own
            # parse/persist: a database error on our side says nothing about the
            # provider and must not extend a failure streak against it.
            await _breaker_record(success=True)
            rows, actual, truncated = parse_response(payload, key_to_poi)
            await persist_rows(rows, key_days, truncated, key_to_poi=key_to_poi)
            logger.info(
                "Unacast: %d observation(s) across %d feature(s) persisted",
                actual, len(features),
            )
        # The breaker is platform-wide, so only a failure that says the VENDOR
        # (or our shared account with it) is unhealthy may count. It used to
        # count every exception, so one tenant's out-of-coverage search, a
        # dense-ring timeout or our own persist error paused audiences for all.
        except UnacastConcurrencyTimeout:
            # Our own shared slot pool was busy; the vendor was never asked.
            raise
        except httpx.ReadTimeout:
            # Too heavy to answer in time: a sizing miss that `_fetch_gaps`
            # handles by splitting the request, not an unhealthy vendor.
            raise
        except (UnacastNoContact, httpx.TransportError):
            # Never reached the vendor, or the connection broke. (NoContact is
            # also not metered — `fired` below is derived from real requests.)
            await _breaker_record(success=False)
            raise
        except UnacastRequestRejected:
            # The vendor refused THIS request's content. Says nothing about it.
            raise
        except UnacastAPIError:
            # 5xx, the daily 429, an IP or credential rejection: account- or
            # vendor-wide, so every tenant is affected and the breaker counts.
            await _breaker_record(success=False)
            raise
        finally:
            # `requests` is what the transport ACTUALLY sent, not one per batch.
            # Retries happen inside the client, so a single reservation could
            # cover several real HTTP requests — and the vendor's own limit is a
            # daily REQUEST limit per key, so counting batches made the ledger
            # read low and we believed we had budget we did not.
            requests = int(REQUESTS_MADE.get() or 0)
            await reconcile_call(
                fired=requests > 0, observations=actual, requests=requests
            )
            if lease is not None:
                await release_concurrency_slot(lease)

    async def health_check(self) -> bool:
        """Whether the querier is usable. Deliberately does NOT
        call the vendor — every real call costs shared, scarce budget, and a
        health probe is not worth a slice of the monthly cap. Reports only
        whether this backend is configured well enough to try."""
        try:
            return bool(self.client)
        except Exception as exc:  # noqa: BLE001 — a config error is a health failure
            logger.warning("Unacast health check failed: %s", exc)
            return False
