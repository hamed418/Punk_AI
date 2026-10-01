"""
app/graph/unacast_devices.py
─────────────────────────────
TEMPORARY. Buys device IDs from ``POST areas/devices`` instead of raw pings
from ``observations/geo/search`` (app/graph/unacast_query.py).

WHY THIS FILE EXISTS: our observations/geo/search entitlement currently
returns Unacast's own Pseudonymized Registration ID — a UUIDv4 pseudonym —
not a real advertising ID (GAID/IDFA). Meta's MADID custom-audience upload
only matches on real advertising IDs, so an audience built from that feed
uploads into Meta and matches nobody (silently — Meta accepts the upload;
see unacast_query._extract_maid's ``advertiserID or registrationID``
fallback and services/meta_ads.py's raw, unhashed MADID upload).
``areas/devices`` returns advertising IDs on this SAME key today
(UNACAST-API-REFERENCE.md §4: "selected by registration ID sort, EVEN FOR
advertiserID mode").

SCOPE — narrower than a first cut of this file attempted. The observations
querier (unacast_query.UnacastMAIDQuerier) stays the ONLY thing that powers
what the user sees: every stat, filter, map dot, dwell/frequency number and
the confirm-screen count are built from real pings, exactly as before this
file existed (``maid_query.get_maid_querier()`` is unchanged — it always
returns the observations querier). ``UnacastDevicesQuerier`` here is called
from exactly ONE place, ``executors/media.py._load_maids``, at the moment an
audience is about to be uploaded to Meta: it fetches real advertising IDs for
the confirmed places over the same window, and that list SILENTLY REPLACES
the observation-derived (registration-ID) list in the upload payload only.
No crosswalk between the two ID spaces exists, so the uploaded population is
an approximation of the displayed one, not the exact filtered set — accepted
on purpose, because the alternative is a MADID upload Meta cannot match at
all. See ``fetch_area_advertising_ids`` below, the actual entry point.

DELETE THIS FILE the day the vendor confirms advertiserID mode on the
observations entitlement:
  1. Flip ``UNACAST_ID_SOURCE`` to ``"observations"`` (core/config.py) —
     ``_load_maids`` stops calling this module and uploads the observation
     list directly again.
  2. Delete this module, the ``UNACAST_ID_SOURCE`` setting, and the
     ``fetch_area_advertising_ids`` call site in
     ``executors/media.py._load_maids``.
  3. Delete the ``src`` fences in unacast_query.py (covered_days_bulk/
     read_cached/iter_cached/cached_observation_count/persist_rows)
     and the ``src`` columns on both tables (migration:
     ``DELETE FROM unacast_raw_observations WHERE src = 'devices'`` and the
     matching coverage rows, then drop both columns).
  4. Consider removing the ``advertiserID or registrationID`` fallback in
     ``_extract_maid`` so a future entitlement regression fails loudly
     instead of silently re-uploading pseudonyms again.

THE ONE IDEA: a device present in a (POI, day) is written as ONE SYNTHETIC
ROW at the ring's CENTRE, in exactly the persisted shape observations rows
take — ``{poi_key, maid, lat, lng, observed_at, forensic_flags: None,
hot: False}`` — tagged ``src="devices"``. It goes through the SAME
``unacast_raw_observations``/``unacast_fetch_coverage`` tables, the SAME
centre-keyed watermark, retention sweep, call ledger, circuit breaker and
concurrency lease as the observations querier (see unacast_query.py) — every
function reused here takes the ``src`` kwarg added for this so a devices-path
read/write never mixes with a real-ping one at the same centre/day — this path
no longer feeds any widget, so a stray device row mixed into the real cache
would corrupt an audience for no reason at all.

ALWAYS ONE FEATURE PER (POI, DAY) — never a whole-window feature. A device
list has no per-ping timestamp, so a device seen in a 30-day feature could be
dated to any day in it. Buying strictly by day keeps every stored row's date
exact — moot for filtering now (this path is never filtered; see below), but
it is what lets a repeat publish of the same POIs over an overlapping window
reuse the watermark instead of re-buying. The cost is more requests than the
observations querier's planner would use for the same window, but NOT refused
for being large: a search is never turned away up front here either (same
decision as unacast_query.py — see its module docstring). The shared monthly
call budget, the circuit breaker and the concurrency gate are what bound cost;
a chunk that times out is retried, and only the outer caller's attempt budget
(executors/maid.py._query_maids_with_retry) gives up on it. Packed 20 features/
request — this endpoint's cap,
double observations' 10.

NO FILTERING IS APPLIED to what this path buys or returns — every device
seen at ANY of the confirmed places over the window is in the upload list.
Replicating the observation-side audience_filter (min_visits, dwell, trend,
groups, ...) against presence-only data would be answering it with evidence
it doesn't have; the uploaded population is deliberately just "who showed up
here," an accepted approximation of the filtered count the user was shown.

NOT run through app.graph.maid_signal.apply_gate: that gate judges a ping's
accuracy band and distance from the ring centre, evidence a device list has
none of — every device in the response is already inside the vendor's own
geofence. NOT folded through maid.py's `_fold_row`/`cluster_visits` at all — this module returns a
flat MAID list, not observation rows, so there is nothing for the map, the
funnel or the audience filter to see.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date as _date, datetime, timezone

import httpx

from app.core.config import settings
from app.graph.maid_signal import PLACE_VISIT_EXCLUDE_MASK
from app.graph.unacast_query import (
    UnacastBudgetExhausted,
    UnacastConcurrencyTimeout,
    _TRUNCATED_FEATURES,
    _breaker_check,
    _breaker_record,
    _dates_to_days,
    _extraction_limit,
    _settle,
    covered_days_bulk,
    persist_rows,
    poi_key,
    purchase_radius_m,
    read_cached,
    reconcile_call,
    release_concurrency_slot,
    reserve_call,
    wait_for_slot,
)

logger = logging.getLogger(__name__)

_ENDPOINT = "areas/devices"

# The endpoint's hard cap (UNACAST-API-REFERENCE.md §4) — double observations'
# 10, because a device-list feature carries no per-ping payload.
_MAX_FEATURES_PER_REQUEST = 20


def _feature(poi: dict, fid: str, day: _date) -> dict:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    end = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc)
    return {
        "type": "Feature",
        "id": fid,
        "properties": {
            "startDateTime": start.isoformat(),
            "endDateTime": end.isoformat(),
            "radiusInMeters": purchase_radius_m(poi),
            "deviceCountOnly": False,
            "excludeFlags": PLACE_VISIT_EXCLUDE_MASK,
        },
        "geometry": {"type": "Point", "coordinates": [float(poi["lng"]), float(poi["lat"])]},
    }


def _body(features: list[dict]) -> dict:
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"responseType": "DIRECT"}},
        "features": features,
    }


def _parse_response(
    payload: dict,
    day_by_feature: dict[str, tuple[str, _date]],
    key_to_poi: dict[str, dict],
) -> tuple[list[dict], set[str]]:
    """One persist-shape row per device per feature, at the ring's centre.
    Returns ``(rows, truncated_keys)`` — ``truncated_keys`` are base poi_keys
    (not the per-day feature id) whose day hit the 10k device-list cap.
    """
    rows: list[dict] = []
    truncated: set[str] = set()
    for feat in payload.get("features") or []:
        fid = feat.get("id")
        loc = day_by_feature.get(fid) if fid else None
        if loc is None:
            continue
        key, day = loc
        poi = key_to_poi.get(key)
        if poi is None:
            continue
        props = feat.get("properties") or {}
        devices = props.get("devices") or []
        observed_at = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        lat, lng = float(poi["lat"]), float(poi["lng"])
        for device_id in devices:
            if not device_id or not isinstance(device_id, str):
                continue
            rows.append({
                "poi_key": key, "maid": device_id, "lat": lat, "lng": lng,
                "observed_at": observed_at, "forensic_flags": None, "hot": False,
            })
        if props.get("deviceLimitHit"):
            truncated.add(key)
            # No per-device detail available for this cap (unlike
            # observationLimitHit's totalPossibleObservationCountPerDevice) —
            # the vendor's device-list response carries no such breakdown.
            _TRUNCATED_FEATURES.setdefault(key, {
                "returned": len(devices), "possible": None,
                "fraction": None, "devices": (),
            })
    return rows, truncated


class UnacastDevicesQuerier:
    """Same ``query_maids(dates, pois, *, writer=None, failures=None)``
    interface as ``unacast_query.UnacastMAIDQuerier`` — see
    ``maid_query.get_maid_querier``. TEMPORARY, see module docstring.
    """

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
        days = _dates_to_days(dates)
        if not days or not pois:
            return []

        keyed: list[tuple[str, dict]] = []
        for p in pois:
            k = poi_key(p)
            if k and p.get("lat") is not None and p.get("lng") is not None:
                keyed.append((k, p))
        if not keyed:
            logger.warning("Unacast devices: no POIs with usable coordinates — nothing to query")
            return []
        key_to_poi = dict(keyed)

        covered = await covered_days_bulk(key_to_poi, src="devices")
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
            logger.info("Unacast devices: full window already cached for %d POI(s) — no API call", len(keyed))
            if writer:
                writer({"type": "thinking", "content": (
                    f"MAID: all {len(keyed)} location(s) already cached for this window — "
                    f"no Unacast request needed"
                )})

        rows = await read_cached(key_to_poi, days, src="devices")
        for row in rows:
            # read_cached's SELECT doesn't carry src — stamped here so
            # _fold_row (maid.py) can withhold ping_meta for these rows.
            row["src"] = "devices"

        if fetch_error is not None:
            still = await covered_days_bulk({k: key_to_poi[k] for k in gaps}, src="devices")
            failed = {
                k for k, gap in gaps.items()
                if any(d not in still.get(k, set()) for d in gap)
            }
            if failed:
                if not rows:
                    raise fetch_error
                failures.update(error=fetch_error, failed_keys=failed)
        return rows

    async def _fetch_gaps(
        self, key_to_poi: dict[str, dict], gaps: dict[str, list[_date]], *, writer=None,
    ) -> None:
        slots = [(k, d) for k, days in gaps.items() for d in days]
        if not slots:
            return

        limit = _extraction_limit()
        sem = asyncio.Semaphore(limit)
        chunks = [
            slots[i:i + _MAX_FEATURES_PER_REQUEST]
            for i in range(0, len(slots), _MAX_FEATURES_PER_REQUEST)
        ]
        logger.info(
            "Unacast devices: %d location-day(s) -> %d request(s), up to %d at a time",
            len(slots), len(chunks), limit,
        )
        if writer:
            writer({"type": "thinking", "content": (
                f"MAID (temporary device-list path): {len(slots)} location-day(s) -> "
                f"{len(chunks)} request(s), up to {limit} at a time"
            )})

        async def _run(chunk: list[tuple[str, _date]]) -> None:
            async with sem:
                await self._run_batch(chunk, key_to_poi, writer=writer)

        await _settle([_run(c) for c in chunks])

    async def _run_batch(
        self, chunk: list[tuple[str, _date]], key_to_poi: dict[str, dict], *, writer=None,
    ) -> None:
        """Fire ONE areas/devices request for this chunk and persist what
        comes back. Admission/accounting mirrors
        UnacastMAIDQuerier._run_batch exactly — same breaker, same shared
        monthly call budget, same concurrency lease — because it is the same
        vendor account and the same shared limits."""
        from app.services.unacast_client import (
            REQUESTS_MADE,
            UnacastAPIError,
            UnacastNoContact,
            UnacastRequestRejected,
        )

        await _breaker_check()

        if not await reserve_call():
            raise UnacastBudgetExhausted(
                f"the shared monthly Unacast budget "
                f"({settings.UNACAST_MONTHLY_CALL_BUDGET:,} API calls) is exhausted. "
                f"It resets at the start of next month."
            )

        lease = None
        actual = 0
        requests = 0
        REQUESTS_MADE.set(0)

        features: list[dict] = []
        day_by_feature: dict[str, tuple[str, _date]] = {}
        key_days: dict[str, dict[_date, int]] = {}
        for key, day in chunk:
            poi = key_to_poi[key]
            fid = f"{key}::{day.isoformat()}"
            features.append(_feature(poi, fid, day))
            day_by_feature[fid] = (key, day)
            # window_days=1: every feature here is exactly one day, so a
            # truncated day has no narrower window to repair with — it stays
            # covered and disclosed, the same rule covered_days_bulk already
            # applies to a truncated 1-day observations feature.
            key_days.setdefault(key, {})[day] = 1

        try:
            lease = await wait_for_slot(writer=writer)
            if writer:
                writer({"type": "thinking", "content": (
                    f"MAID: querying Unacast (devices) for {len(features)} location-day(s)"
                )})
            payload = await self.client.post(_ENDPOINT, _body(features))
            await _breaker_record(success=True)
            rows, truncated = _parse_response(payload, day_by_feature, key_to_poi)
            actual = len(rows)
            await persist_rows(rows, key_days, truncated, key_to_poi=key_to_poi, src="devices")
            logger.info(
                "Unacast devices: %d device presence row(s) across %d feature(s) persisted",
                actual, len(features),
            )
        except UnacastConcurrencyTimeout:
            raise
        except httpx.ReadTimeout:
            # No adaptive split here (unlike the observations querier): a
            # device-list feature is far lighter than a 100k-observation one,
            # and the per-extraction ceiling above already bounds the worst
            # case. One chunk timing out fails that chunk; _settle lets the
            # rest persist and query_maids' partial-result path (failures=)
            # keeps what landed.
            raise
        except (UnacastNoContact, httpx.TransportError):
            await _breaker_record(success=False)
            raise
        except UnacastRequestRejected:
            raise
        except UnacastAPIError:
            await _breaker_record(success=False)
            raise
        finally:
            requests = int(REQUESTS_MADE.get() or 0)
            await reconcile_call(
                fired=requests > 0, observations=actual, requests=requests, src="devices",
            )
            if lease is not None:
                await release_concurrency_slot(lease)

    async def health_check(self) -> bool:
        try:
            return bool(self.client)
        except Exception as exc:  # noqa: BLE001 — a config error is a health failure
            logger.warning("Unacast devices health check failed: %s", exc)
            return False


def _publish_dates(*, lookback_days: int | None, event_date_ranges: list[str] | None) -> list[str]:
    """The window to buy advertising IDs over — same shape run_maid_query used
    to buy the observation-side audience, so the uploaded population covers
    the same places over the same span the user was shown (see the module
    docstring: no attempt is made to match the FILTERED count, only the
    window and the places)."""
    from datetime import timedelta as _td

    ranges = event_date_ranges or []
    if ranges:
        from app.graph.maid_query import build_date_range

        dates: set[str] = set()
        for label in ranges:
            parts = [s.strip() for s in str(label).split("->")]
            if len(parts) != 2:
                continue
            try:
                dates.update(build_date_range(parts[0], parts[1]))
            except ValueError:
                continue
        if dates:
            return sorted(dates)

    from app.graph.maid_query import build_date_list

    yesterday = (_date.today() - _td(days=1)).isoformat()
    return build_date_list(yesterday, int(lookback_days or 7))


async def fetch_area_advertising_ids(
    pois: list[dict], *, lookback_days: int | None, event_date_ranges: list[str] | None = None,
    writer=None,
) -> list[str]:
    """Real advertising IDs for the confirmed places, for the Meta upload
    ONLY — see the module docstring. Every device seen at any of ``pois`` over
    the window is included; nothing here is filtered. Returns ``[]`` on any
    failure (budget exhausted, breaker open, ceiling exceeded, vendor error)
    rather than raising — the caller's existing "nothing to upload" handling
    is the right response, not a partially-wrong audience.
    """
    dates = _publish_dates(lookback_days=lookback_days, event_date_ranges=event_date_ranges)
    if not dates or not pois:
        return []
    try:
        rows = await UnacastDevicesQuerier().query_maids(dates, pois, writer=writer)
    except Exception as exc:  # noqa: BLE001 — see docstring: fail to empty, not to a wrong list
        logger.warning("Unacast devices: publish-time ID fetch failed — %s", exc)
        return []
    return sorted({r["maid"] for r in rows if r.get("maid")})
