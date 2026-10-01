"""
graph/builder/executors/maid.py
───────────────────────────────
MAID extraction cores.

  _query_maids_with_retry – the Unacast query with retry/backoff. Pure I/O —
                            returns rows plus a structured tool-log entry.
  run_maid_query          – full extraction pipeline: radius clamp,
                            event/lookback date grouping, session-cache check,
                            the vendor query, DB persistence, map emission. No
                            interrupts; callers own checkpointing and milestone
                            narration.
  query_pois_audience     – the same query for POIs added mid-build.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import defaultdict
from datetime import date as _date, timedelta as _timedelta
from typing import Any, Callable, Optional

from app.graph.maid_query import (
    DEFAULT_POI_RADIUS_KM,
    attribute_audience,
    build_date_list,
    build_date_range,
    build_maid_split_view,
    cluster_visits,
    compute_visit_stats,  # re-exported for callers importing from this module
    gap_minutes_for,
    get_maid_querier,
    is_dwell_only_role_spec,
    is_role_spec,
    role_confidence,
    visit_is_timed,
)
from app.graph.maid_signal import describe_gate
from app.graph.maid_history import required_history_days
from app.graph.narrator import narrate
from app.graph.narrator.types import Utterance
from app.services.maid_store import (
    AudienceFilterUnevaluable,
    apply_audience_filter,
    describe_audience_filter,
    fetch_maid_extraction_by_session,
    intersection_witness_stats,
    resolve_group_labels_verbose,
    role_signal_stats,
    scope_exclusion_to_named_groups,
    store_maid_extraction,
    unknown_filter_keys,
)

logger = logging.getLogger(__name__)


async def _query_maids_with_retry(
    querier: Any,
    *,
    dates: list,
    pois: list,
    max_attempts: int = 2,
    writer: Callable[[dict], None] | None = None,
    on_row: Callable[[dict], None] | None = None,
) -> tuple[list | None, dict]:
    """Retry a MAID query on transient failure. Returns (rows, log_entry).

    ``writer`` is threaded through to the querier so its concurrency gate can
    narrate a wait instead of leaving the SSE stream silent.

    ``on_row``, when given, streams instead of collecting: rows are handed to
    the callback one at a time (via the querier's ``iter_maids``, when it has
    one — the devices querier doesn't and falls back to its plain list) rather
    than materialised into a list first. Peak memory then stays the caller's
    fold size, not the raw ping count, which is what used to require the
    extraction-size ceiling this replaces. The returned ``rows`` is always
    ``None`` in this mode — everything already reached the callback — and
    ``log["streamed"]`` is ``True`` so the caller does not re-walk an empty
    list expecting to find them there.

    A ``NonRetryableMAIDQueryError`` (maid_query.py) breaks out immediately —
    retrying an exhausted monthly budget, a saturated concurrency pool, an open
    breaker or a non-allowlisted source IP cannot succeed, and most of them cost
    real, scarce vendor budget to re-attempt. ``error_kind`` carries the
    exception class name so callers can tell these apart from a generic outage.
    """
    from app.graph.maid_query import NonRetryableMAIDQueryError

    start = time.monotonic()
    last_exc: Exception | None = None
    attempts_used = 0
    args = {"dates_count": len(dates), "pois_count": len(pois)}
    for attempt in range(1, max_attempts + 1):
        attempts_used = attempt
        failures: dict = {}
        try:
            rows: list | None
            rows_seen = 0
            streamed = on_row is not None
            if streamed and hasattr(querier, "iter_maids"):
                async for row in querier.iter_maids(
                    dates=dates, pois=pois, writer=writer, failures=failures,
                ):
                    on_row(row)
                    rows_seen += 1
                rows = None
            elif streamed:
                for row in await querier.query_maids(
                    dates=dates, pois=pois, writer=writer, failures=failures,
                ):
                    on_row(row)
                    rows_seen += 1
                rows = None
            else:
                rows = await querier.query_maids(
                    dates=dates, pois=pois, writer=writer, failures=failures,
                )
                rows_seen = len(rows)
            error = failures.get("error")
            if error is None:
                return rows, {
                    "tool": "query_maids",
                    "args": args,
                    "status": "ok",
                    "error_msg": None,
                    "error_kind": None,
                    "attempts": attempt,
                    "duration_ms": round((time.monotonic() - start) * 1000, 1),
                    "node": "maid_execute",
                    "streamed": streamed,
                    "rows": rows_seen,
                }
            # Some spots came back and some did not. A transient error is worth
            # one more attempt — the watermark means it buys only what is still
            # missing. Otherwise keep what landed: it is already paid for, and
            # throwing it away used to turn 19 good batches of 20 into an
            # empty, failed audience.
            last_exc = error
            if not isinstance(error, NonRetryableMAIDQueryError) and attempt < max_attempts:
                logger.warning("MAID query partial on attempt %d/%d: %s", attempt, max_attempts, error)
                await asyncio.sleep(2.0 ** (attempt - 1))
                continue
            return rows, {
                "tool": "query_maids",
                "args": args,
                "status": "partial",
                "error_msg": str(error),
                "error_kind": type(error).__name__,
                "failed_keys": sorted(failures.get("failed_keys") or ()),
                "attempts": attempt,
                "duration_ms": round((time.monotonic() - start) * 1000, 1),
                "node": "maid_execute",
                "streamed": streamed,
                "rows": rows_seen,
            }
        except NonRetryableMAIDQueryError as exc:
            last_exc = exc
            logger.warning("MAID query not retryable (%s): %s", type(exc).__name__, exc)
            break
        except Exception as exc:
            last_exc = exc
            logger.warning("MAID query attempt %d/%d: %s", attempt, max_attempts, exc)
            if attempt < max_attempts:
                await asyncio.sleep(2.0 ** (attempt - 1))
    return None, {
        "tool": "query_maids",
        "args": args,
        "status": "error",
        "error_msg": str(last_exc),
        "error_kind": type(last_exc).__name__ if last_exc else None,
        "attempts": attempts_used,
        "duration_ms": round((time.monotonic() - start) * 1000, 1),
        "node": "maid_execute",
    }


_MAX_MAID_RADIUS_M = 5000


def _maid_failure_kind(kinds: set) -> str:
    """Which failure the narrator reports, from the exception class names.

    A budget/capacity refusal is a very different thing from an outage, and
    telling the user "the query failed" when the real answer is "we're out of
    monthly data quota" sends them debugging the wrong thing.
    """
    return (
        "budget" if "UnacastBudgetExhausted" in kinds
        else "capacity" if "UnacastConcurrencyTimeout" in kinds
        else "ip_not_allowlisted" if "UnacastIPNotAllowlisted" in kinds
        # An OPEN BREAKER is not an outage from the user's side — it is us
        # declining to spend more of the shared budget on a vendor that just
        # failed repeatedly. Without its own kind it fell through to
        # "vendor_error", which reads as "the query broke" and invites a retry
        # that the breaker will refuse.
        else "circuit_open" if "UnacastCircuitOpen" in kinds
        # Too heavy to answer even after being split down to one POI on one
        # day — the terminal case of unacast_query._split_request. Its own
        # kind so the narrator never suggests a LONGER lookback, which makes
        # it slower; there is no "too_large" any more (nothing is ever
        # refused for predicted size — see unacast_query.py's module
        # docstring), only this genuinely un-splittable case.
        else "timeout" if "UnacastRequestTimeout" in kinds
        # The key's daily request limit — resets 00:00 UTC, so "try again in
        # a few minutes" would be wrong advice.
        else "rate_limited" if "UnacastRateLimited" in kinds
        # The vendor refused this search itself (e.g. a place outside
        # coverage). Retrying the same search cannot help; changing it can.
        else "request_rejected" if "UnacastRequestRejected" in kinds
        else "vendor_error"
    )


def _eta_text(seconds: float) -> str:
    return "under a minute" if seconds < 60 else f"about {math.ceil(seconds / 60)} min"


def _truncation_facts(pois: list[dict]) -> dict:
    """Truncation disclosure for the funnel, best-effort.

    The vendor caps a DIRECT response at 100k observations PER FEATURE, and a
    truncated POI's frequency counts are floors rather than measurements. The
    flag was previously logged and nothing else — the user was never told their
    audience was a sample.

    Scoped to THIS extraction's POIs. The report reads a process-wide record of
    every truncated feature, so an unscoped call told one tenant their spots
    were sampled because of another tenant's busy ones.
    """
    try:
        from app.graph.unacast_query import poi_key, truncation_report

        return truncation_report([k for p in pois if (k := poi_key(p))])
    except Exception:  # noqa: BLE001 — disclosure must never break an extraction
        return {"truncated_poi_count": 0}


def _yesterday() -> _date:
    """The most recent day the vendor will actually serve.

    Observations for today are not returned (the API refuses a window ending in
    the future, and `unacast_query._dates_to_days` drops today for that reason),
    so a lookback anchored at today is always one day short of what the user
    asked for.
    """
    return _date.today() - _timedelta(days=1)


def _build_device_timelines(
    obs_ts: dict[tuple[str, Any], list[str]],
) -> dict[str, list]:
    """Per-device sorted ping times across EVERY place that device was seen at.

    ``obs_ts`` is keyed ``(maid, spot)``; this collapses the spot dimension so
    ``cluster_visits`` can bound a visit from above. The device left the place
    before its next ping ANYWHERE — a ping at a different POI is exactly as good
    a bound as one at the same POI, and is often the only one available.
    """
    from datetime import datetime as _dt

    out: dict[str, list] = defaultdict(list)
    for (maid, _spot), ts_list in obs_ts.items():
        for ts in ts_list:
            try:
                out[maid].append(_dt.fromisoformat(str(ts).replace("Z", "+00:00")))
            except ValueError:
                continue
    for maid in out:
        out[maid].sort()
    return out


def _spot_key(row: dict) -> str | None:
    """The "same place" token used to fold raw pings into visits: ``poi_key``.

    That is the response feature's id, i.e. the POI key we ourselves sent. The
    vendor geofenced the ping and nested it under that feature, so this is exact
    rather than inferred, and all of a device's pings at one place become one
    visit.

    It replaced a self-computed H3 cell id: a res-10 cell is ~132 m
    corner-to-corner while a 100 m ring spans several of them, so one continuous
    visit that drifted inside a single store split into two visits with half the
    dwell each. Measured on 287,000 real pings: 26.1% of device-POI pairs spanned
    more than one cell, inflating visit counts by 14.5% — enough that a single
    visit could satisfy ``min_visits: 2``. See docs/maid_signal_quality_baseline.md §3.
    """
    return row.get("poi_key") or None


def _category_by_key(pois: list[dict]) -> dict[str, str]:
    """poi_key -> the searched category/brand, so the visit-gap threshold can
    differ by place type: a forecourt stop and an afternoon at a mall are not the
    same shape, and the threshold swings visit counts by 2x.

    ``poi_key`` is coordinates + radius only, so the SAME physical place found
    under two search labels (e.g. "PetSmart" the brand and "pet store" the
    category) shares one key — a plain overwrite let whichever group was
    grouped last silently decide the threshold. When two categories share a
    key, the TIGHTER definition of "one visit" wins (the smaller
    ``gap_minutes_for``): applying the looser one to a shared-key POI would
    under-count its visits relative to what the stricter category asked for.
    """
    from app.graph.builder.executors.geo import group_pois_by_category
    from app.graph.unacast_query import poi_key

    out: dict[str, str] = {}
    for group in group_pois_by_category(pois):
        for p in group["pois"]:
            k = poi_key(p)
            if not k:
                continue
            existing = out.get(k)
            if existing is not None and existing != group["key"]:
                if gap_minutes_for(existing) <= gap_minutes_for(group["key"]):
                    logger.info(
                        "MAID: POI shared between categories %r and %r (same "
                        "coords+radius) — using %r's tighter visit-gap threshold",
                        existing, group["key"], existing,
                    )
                    continue
                logger.info(
                    "MAID: POI shared between categories %r and %r (same "
                    "coords+radius) — using %r's tighter visit-gap threshold",
                    existing, group["key"], group["key"],
                )
            out[k] = group["key"]
    return out


def _apply_ring_specs(pois: list[dict], specs: list[dict]) -> list[dict]:
    """A visit ring for a GROUP of spots ("100 m for the gyms"): stamp each
    matching POI's own ``radius_km`` (in place — every payload below reads it per
    POI), later specs winning. Returns what applied, for the narration:
    ``[{"match", "radius_m", "count"}]``. A group that matches nothing (its spots
    were trimmed away) is left out rather than reported as applied."""
    from app.graph.builder.executors.poi_selection import resolve_drop_predicate

    applied: list[dict] = []
    for spec in specs:
        metres = min(int(spec.get("radius_m") or 0), _MAX_MAID_RADIUS_M)
        hits = resolve_drop_predicate(pois, str(spec.get("match") or "")) if metres > 0 else []
        for poi in hits:
            poi["radius_km"] = metres / 1000.0
        if hits:
            applied.append({"match": spec["match"], "radius_m": metres, "count": len(hits)})
    return applied


def _maid_cache_still_valid(
    existing: dict | None, poi_radius_km: float, lookback_days: int,
    event_date_ranges: list[str], updated_pois: list[dict],
) -> bool:
    """Whether the session's last-persisted extraction (``existing``, from
    ``fetch_maid_extraction_by_session``) still answers THIS query — same
    radius, lookback window, date ranges, and POI set. A rollback that
    invalidates the "maid_query" unit (edits.invalidate_from) does so
    precisely because one of those inputs changed; restoring the extraction
    anyway silently ignores the edit (e.g. "change the radius to 100m" keeps
    showing the 60m-radius count). POI identity is coords+name via
    `dedup_key`, not radius_km — that's the very field a radius edit changes,
    and it lives on the POI dict, not the query params.
    """
    # purged_at not-None means maids/observations were already cleared (a
    # publish, or the abandoned-row sweep) — maid_count can still be a real,
    # nonzero HISTORICAL number on that row, so it alone is not enough to tell
    # a live cache hit from a purged one. Without this a purged row look like
    # a valid restore and hand the caller an empty maid list under a nonzero
    # maid_count.
    if not existing or not existing.get("maid_count") or existing.get("purged_at"):
        return False
    from app.graph.builder.executors.geo import dedup_key

    def _rings(pois: list[dict]) -> set:
        # Each spot's OWN ring: one group's ring changing must invalidate the
        # cache even though the default (scalar) ring did not.
        return {(dedup_key(p), round(float(p.get("radius_km") or 0), 4)) for p in pois}

    return (
        existing.get("search_radius_km") == poi_radius_km
        and existing.get("lookback_days") == lookback_days
        and (existing.get("event_date_ranges") or []) == event_date_ranges
        and {dedup_key(p) for p in (existing.get("pois") or [])}
            == {dedup_key(p) for p in updated_pois}
        and _rings(existing.get("pois") or []) == _rings(updated_pois)
    )


def _new_fold() -> dict:
    """The per-extraction accumulators ``_fold_row`` writes into."""
    return {
        "maids": set(),
        # (maid, poi_key) -> the ONE deduped row it produced, so the frequency
        # written back later lands on the same key it was counted under.
        "row_index": {},
        "rows": [],
        # Every raw ping timestamp per (maid, poi_key) — feeds cluster_visits
        # and, through it, every audience-filter time predicate.
        "ts": defaultdict(list),
        # Per-ping evidence keyed by ISO timestamp, so cluster_visits can judge
        # each visit's CONFIDENCE rather than merely count it. Keyed per
        # (device, place) because two devices can share a timestamp.
        "meta": defaultdict(dict),
        "radius": {},
    }


def _fold_row(fold: dict, row: dict) -> None:
    """Fold one raw ping into ``fold``, deduping to one row per device per POI."""
    spot = _spot_key(row)
    if spot is None:
        return
    m = row["maid"]
    key = (m, spot)
    fold["maids"].add(m)
    ts = row.get("ts")
    if ts:
        fold["ts"][key].append(ts)
        # A row from the temporary /areas/devices path (src="devices", see
        # unacast_devices.py) carries no position or accuracy evidence — it is
        # a presence marker, not a GPS fix. Passing it as ping_meta would stamp
        # every such visit `confirmed: False` (evidence looked at and found
        # wanting) instead of leaving `confirmed` ABSENT (no evidence supplied
        # at all) — the same distinction test_maid_visit_evidence.py pins for
        # legacy/demo-synth rows.
        if row.get("src") != "devices":
            fold["meta"][key][ts] = {
                "flags": row.get("forensic_flags"),
                "dist_m": row.get("dist_m"),
            }
    if row.get("radius_m"):
        fold["radius"][key] = float(row["radius_m"])
    r = fold["row_index"].get(key)
    if r is None:
        r = {"lat": float(row["lat"]), "lng": float(row["lng"]), "maid": m,
             "count": 0, "poi_key": spot}
        fold["row_index"][key] = r
        fold["rows"].append(r)
    r["count"] += 1


def _finish_fold(fold: dict, key_to_category: dict[str, str]) -> list[dict]:
    """Cluster each folded row's pings into visits and return the rows.

    ``device_timeline`` is that device's pings across EVERY place, which is what
    bounds each visit from above: the device left before its next ping anywhere,
    not merely before its next ping here.
    """
    timelines = _build_device_timelines(fold["ts"])
    for key, r in fold["row_index"].items():
        ts_list = fold["ts"].get(key)
        if ts_list:
            r["visits"] = cluster_visits(
                ts_list,
                gap_minutes=gap_minutes_for(key_to_category.get(key[1])),
                device_timeline=timelines.get(key[0]),
                ping_meta=fold["meta"].get(key),
                radius_m=fold["radius"].get(key),
            )
            r["days"] = sorted({t[:10] for t in ts_list})
    return fold["rows"]


async def run_maid_query(
    state: Any,
    ws: dict,
    geo: dict,
    writer: Callable[[dict], None],
    session_id: str,
) -> dict:
    """Run the full MAID extraction pipeline. Mutates ``ws``/``geo`` in place
    (callers pass fresh copies they then checkpoint) and returns the facts the
    caller needs for milestone narration::

        {"maid_tool_log": [...], "maid_count": int, "filtered_maid_count": int,
         "pois_found": int, "date_context": str, "lookback_days": int,
         "poi_radius_m": int|None, ...}

    ``state`` is read-only — used by the narrator for stage_open framing.
    """
    poi_radius_m = ws.get("poi_radius_m")
    is_event_based = bool(ws.get("is_event_based"))

    if poi_radius_m and poi_radius_m > _MAX_MAID_RADIUS_M:
        writer({"type": "thinking", "content": (
            f"MAID: clamping poi_radius {poi_radius_m}m -> {_MAX_MAID_RADIUS_M}m"
        )})
        poi_radius_m = _MAX_MAID_RADIUS_M
    poi_radius_km = (poi_radius_m / 1000.0) if poi_radius_m else DEFAULT_POI_RADIUS_KM
    if not poi_radius_m:
        writer({"type": "thinking", "content":
            f"MAID: poi_radius_m not set — defaulting to {DEFAULT_POI_RADIUS_KM * 1000:.0f} m"})

    updated_pois = [
        {**poi, "radius_km": poi_radius_km}
        for poi in geo.get("targetable_pois") or []
    ]
    geo["poi_ring_overrides"] = _apply_ring_specs(updated_pois, ws.get("poi_ring_specs") or [])

    # ── Derive date groupings ──────────────────────────────────────────────
    event_date_ranges: list[str] = []
    date_groups: dict[tuple[str, str], list[dict]] = defaultdict(list)

    if is_event_based:
        for poi in updated_pois:
            start = poi.get("event_start_date") or "TBD"
            end = poi.get("event_end_date") or "TBD"
            if start == "TBD":
                writer({"type": "thinking", "content": f"MAID: POI '{poi.get('name', '?')}' has no event date — skipping"})
                continue
            end_val = end if end != "TBD" else start
            date_groups[(start, end_val)].append(poi)

        for (start, end_val) in date_groups:
            label = f"{start} -> {end_val}" if start != end_val else start
            event_date_ranges.append(label)

        total_unique_days = len({
            d
            for (start, end_val) in date_groups
            for d in build_date_range(start, end_val)
        })
        lookback_days = total_unique_days or 1
        writer({"type": "thinking", "content": (
            f"MAID: event-based — {len(date_groups)} date group(s), "
            f"{lookback_days} unique day(s): {', '.join(event_date_ranges)}"
        )})
    else:
        lookback_days = ws.get("lookback_days") or 7

    geo["poi_radius_km"] = poi_radius_km
    geo["lookback_days"] = lookback_days
    geo["targetable_pois"] = updated_pois

    # ── User-facing narration: explain what the MAID query is about to do ──
    _poi_count = len(updated_pois)
    await narrate(
        Utterance(
            role="stage_open",
            facts={
                "stage": "maid_extract",
                "poi_count": _poi_count,
                "lookback_days": lookback_days,
                "is_event_based": is_event_based,
            },
            fallback=f"Extracting your audience from **{_poi_count} confirmed location(s)**.",
        ),
        state,
        writer,
    )

    # ── Query the audience data provider ───────────────────────────────────
    maid_tool_log: list[dict] = []
    all_maids: list[str] = []
    all_observations: list[dict] = []
    geocoded_locations = geo.get("locations") or []
    center = geocoded_locations[0] if geocoded_locations else {}

    session_cache_hit = False
    try:
        existing = await fetch_maid_extraction_by_session(session_id)
    except Exception as exc:  # cache probe only — degrade to a fresh query
        logger.warning("MAID session-cache probe failed, querying fresh: %s", exc)
        existing = None
    _cache_valid = _maid_cache_still_valid(
        existing, poi_radius_km, lookback_days, event_date_ranges, updated_pois,
    )
    if existing and existing.get("maid_count") and not _cache_valid:
        writer({"type": "thinking", "content": (
            "MAID: session cache present but radius/lookback/dates/POIs "
            "changed — querying fresh instead of restoring it"
        )})
    if _cache_valid:
        # Already queried and stored in a prior run of this node — no vendor query.
        session_cache_hit = True
        writer({"type": "update", "content": f"Restoring the previously extracted audience of {existing['maid_count']:,} visitor profiles..."})
        writer({"type": "thinking", "content": f"MAID: session cache hit (extraction_id={existing['id']}), skipping the vendor query"})
        all_maids = existing["maids"]
        all_observations = existing["observations"]
        geo["maid_count"] = existing["maid_count"]
        geo["maid_extraction_id"] = existing["id"]
        geo["maid_query_skipped"] = False
    else:
        querier = get_maid_querier()

        if querier is None:
            writer({"type": "update", "content": "Audience extraction is unavailable in this environment, so I am preparing an empty map result..."})
            writer({"type": "thinking", "content": "MAID querier not configured (UNACAST_API_TOKEN unset) — skipping the query"})
            geo["maid_query_skipped"] = True
            geo["maid_count"] = 0
        else:
            fold = _new_fold()
            key_to_category: dict[str, str] = {}

            if is_event_based:
                for (start, end_val), group_pois in date_groups.items():
                    group_dates = build_date_range(start, end_val)
                    pois_payload = [
                        {"lat": p["lat"], "lng": p["lng"], "radius_km": p.get("radius_km", poi_radius_km)}
                        for p in group_pois if p.get("lat") and p.get("lng")
                    ]
                    if not pois_payload:
                        continue
                    label = f"{start} -> {end_val}" if start != end_val else start
                    writer({"type": "update", "content": f"Extracting visitors from {len(pois_payload)} event place(s) for {label}..."})
                    writer({"type": "thinking", "content": f"MAID: querying {len(group_pois)} POI(s) for {label}..."})
                    rows, _log = await _query_maids_with_retry(
                        querier, dates=group_dates, pois=pois_payload, writer=writer,
                    )
                    maid_tool_log.append(_log)
                    if rows is not None:
                        for row in rows:
                            _fold_row(fold, row)
                        writer({"type": "thinking", "content": f"  {label} -> {len(rows)} rows"})
                    else:
                        writer({"type": "thinking", "content": f"  MAID query failed ({label}): {_log['error_msg']}"})

                # Combined angles: an event_based combo (e.g. event + named_places)
                # carries POIs WITHOUT event dates too. Those were skipped by the
                # date-group loop above, so query them here via a normal lookback
                # window and merge into the same audience — otherwise the non-event
                # venues would contribute nobody.
                # "TBD" counts as non-event, NOT as a dated event. `search_events`
                # now drops any event it cannot date (it never emits "TBD"), so this
                # only catches legacy/checkpointed POIs. A bare truthiness test would
                # leave a "TBD" one out of this list ("TBD" is truthy) and drop it
                # from the run silently. A place adopted by the event→place
                # cross-check has no event_start_date at all and lands here too.
                non_event_pois = [
                    p for p in updated_pois
                    if (p.get("event_start_date") or "").strip() in ("", "TBD")
                    and p.get("lat") and p.get("lng")
                ]
                if non_event_pois:
                    _lb = ws.get("lookback_days") or 7
                    # Anchored at yesterday for the same reason as the main
                    # lookback below: today is never served, so "7 days" from
                    # today buys 6.
                    lb_dates = build_date_list(_yesterday().isoformat(), _lb)
                    lb_payload = [
                        {"lat": p["lat"], "lng": p["lng"], "radius_km": p.get("radius_km", poi_radius_km)}
                        for p in non_event_pois
                    ]
                    writer({"type": "thinking", "content": (
                        f"MAID: combo — also querying {len(lb_payload)} non-event POI(s) "
                        f"over a {_lb}-day lookback"
                    )})
                    rows, _log = await _query_maids_with_retry(
                        querier, dates=lb_dates, pois=lb_payload, writer=writer,
                    )
                    maid_tool_log.append(_log)
                    if rows is not None:
                        for row in rows:
                            _fold_row(fold, row)
                        writer({"type": "thinking", "content": f"  lookback -> {len(rows)} rows"})
                    else:
                        writer({"type": "thinking", "content": f"  MAID lookback query failed: {_log['error_msg']}"})
            else:
                # How far back to actually BUY: the stated lookback, widened only
                # for predicates that read OUTSIDE it. Buying only the lookback did
                # not make `trend`/`cadence_days` strict — it made them
                # unevaluable: trend's older window fell entirely outside the
                # purchase, so "started" matched everyone and "lapsed" matched
                # nobody. Same for a `window_days` larger than the lookback, which
                # filtered a 7-day audience and called it 45. Every extra day is a
                # paid call, so nothing wider is bought by default. See
                # app/graph/maid_history.py.
                query_days = required_history_days(lookback_days, geo.get("audience_filter"))
                # Anchor at YESTERDAY, not today. `_dates_to_days` drops today
                # (the vendor rejects a window ending in the future), so a
                # stated "7 days" anchored at today bought only 6 and was
                # reported as 7. Anchoring one day back makes 7 mean 7.
                dates = build_date_list(_yesterday().isoformat(), query_days)
                geo["history_days_bought"] = query_days

                # ONE query for every POI, not one per category/brand group.
                #
                # Attribution and per-group accounting both come from the
                # response: every row carries `poi_key` (the feature id the
                # vendor matched it under), so a per-group loop only cost money —
                # it stopped the querier packing features across groups and
                # running requests concurrently. The querier sizes requests by
                # predicted observations (unacast_query.plan_requests), which
                # only works when it sees every POI at once.
                # Local import: executors.geo imports this module at load time.
                from app.graph.builder.executors.geo import group_pois_by_category
                from app.graph.unacast_query import poi_key as _poi_key_of

                _queryable = [p for p in updated_pois if p.get("lat") and p.get("lng")]
                _groups = group_pois_by_category(_queryable)
                _total_pois = len(_queryable)
                # poi_key -> group id(s), so the single response can still be
                # reported per group. Built from the SAME key function the
                # querier stamps on each row.
                #
                # MANY-valued on purpose: poi_key is coordinates + radius
                # only, so the same physical place found under two search
                # labels (e.g. "PetSmart" the brand and "pet store" the
                # category) shares one key. A plain overwrite here let
                # whichever group was built last silently win the row —
                # the other read every one of the vendor's real rows as
                # "empty", which an `op: intersection` then reported as
                # nobody qualifying even though the spot was answered.
                # attribute_audience's poi_ids stamping already credits a
                # shared-key row to every group it belongs to
                # (maid_query.py); this was the one place still assuming 1:1.
                _key_to_group: dict[str, list[str]] = {}
                for _g in _groups:
                    for _p in _g["pois"]:
                        _k = _poi_key_of(_p)
                        if not _k:
                            continue
                        _key_to_group.setdefault(_k, []).append(_g["id"])
                        # Same shared-key collision as _key_to_group above: when
                        # two categories share a key, the TIGHTER visit-gap
                        # definition wins (see _category_by_key's docstring).
                        _existing_cat = key_to_category.get(_k)
                        if _existing_cat is None or gap_minutes_for(_g["key"]) < gap_minutes_for(_existing_cat):
                            key_to_category[_k] = _g["key"]

                writer({"type": "update", "content": f"Extracting visitors from {_total_pois} confirmed place(s) over {lookback_days} day(s)..."})
                writer({"type": "thinking", "content": (
                    f"MAID: querying {_total_pois} POI(s) across {len(_groups)} group(s) "
                    f"({', '.join(g['key'] for g in _groups)}) in one request set, "
                    f"{query_days}-day window ({lookback_days}-day default filter)"
                )})
                writer({"type": "update", "content": "Querying observed visitors — this may take a few moments..."})

                _payload = [
                    {"lat": p["lat"], "lng": p["lng"], "radius_km": p.get("radius_km", poi_radius_km)}
                    for p in _queryable
                ]

                # Tell the user what this costs BEFORE the wait. Free — features
                # and calls are arithmetic over the watermark, not a probe.
                # A fully-cached re-run reports 0 calls, which is also the
                # cheapest possible confirmation that the cache is working.
                try:
                    from app.graph.unacast_query import estimate_cost

                    _est = await estimate_cost(dates, _payload)
                    geo["maid_spend_estimate"] = _est
                    writer({"type": "thinking", "content": (
                        f"MAID: {_est['calls']} vendor call(s) needed "
                        f"({_est['features']} location-window(s); "
                        f"{_est['cached_pois']}/{_est['pois']} POI(s) already cached "
                        f"for this window)"
                    )})
                    if _est["calls"]:
                        writer({"type": "update", "content": (
                            f"Pulling visitors for {_est['pois'] - _est['cached_pois']} "
                            f"spot(s) — {_eta_text(_est.get('eta_s') or 0)}..."
                        )})
                except Exception as _exc:  # noqa: BLE001 — an estimate must never block a query
                    logger.debug("MAID: spend estimate unavailable — %s", _exc)

                # Per-group accounting from the vendor's own attribution, folded
                # AS ROWS ARRIVE rather than after a full list is collected —
                # peak memory is then the fold's size, not the raw ping count,
                # which is what an unbounded (never-refused) search needs. A
                # group that returned nothing is NOT the same as a group whose
                # query failed, and the two must stay distinguishable — an
                # `op: intersection` over a group that failed to fetch would
                # otherwise return an empty set that reads as a real answer.
                # See geo["maid_group_status"].
                _rows_per_group: dict[str, int] = {g["id"]: 0 for g in _groups}

                def _on_row(row: dict, _rows_per_group=_rows_per_group) -> None:
                    _fold_row(fold, row)
                    for _gid in _key_to_group.get(row.get("poi_key") or "", ()):
                        _rows_per_group[_gid] += 1

                _rows, _log = await _query_maids_with_retry(
                    querier, dates=dates, pois=_payload, writer=writer, on_row=_on_row,
                )
                maid_tool_log.append(_log)
                if _log["status"] != "error":
                    # A group with any spot the querier could not pull is
                    # "partial": its audience is real but incomplete, which an
                    # intersection must not treat as a full side.
                    _partial_groups = {
                        gid for k in (_log.get("failed_keys") or ())
                        for gid in _key_to_group.get(k, ())
                    }
                    geo["maid_group_status"] = {
                        g["id"]: {
                            "status": (
                                "partial" if g["id"] in _partial_groups
                                else "ok" if _rows_per_group[g["id"]] else "empty"
                            ),
                            "pois_requested": len(g["pois"]),
                            "rows": _rows_per_group[g["id"]],
                        }
                        for g in _groups
                    }
                    writer({"type": "thinking", "content": (
                        "  " + ", ".join(
                            f"{g['key']}={_rows_per_group[g['id']]} rows" for g in _groups
                        ) or f"  {_log.get('rows', 0)} rows"
                    )})
                else:
                    geo["maid_group_status"] = {
                        g["id"]: {
                            "status": "failed",
                            "error_kind": _log.get("error_kind"),
                            "pois_requested": len(g["pois"]),
                            "rows": 0,
                        }
                        for g in _groups
                    }
                    writer({"type": "thinking", "content": f"  MAID query failed: {_log['error_msg']}"})

            # Some spots landed and some did not. The audience stays — it is real
            # for the spots that came back — but the user is told how much of
            # the search it covers, and the fact reaches the narrator.
            _partial_logs = [_l for _l in maid_tool_log if _l.get("status") == "partial"]
            if _partial_logs:
                _failed_keys = {k for _l in _partial_logs for k in (_l.get("failed_keys") or ())}
                _partial_kind = _maid_failure_kind({_l.get("error_kind") for _l in _partial_logs})
                geo["maid_partial_failure"] = {
                    "failed_pois": len(_failed_keys),
                    "total_pois": len(updated_pois),
                    "kind": _partial_kind,
                }
                writer({"type": "update", "content": (
                    f"I couldn't pull visitors for {len(_failed_keys)} of "
                    f"{len(updated_pois)} spot(s) ({_partial_kind.replace('_', ' ')}); "
                    f"the audience below covers the rest."
                )})

            all_maids = list(fold["maids"])
            all_observations = _finish_fold(fold, key_to_category)

            # A query that genuinely ran and found nobody looks IDENTICAL to one
            # that never ran at all once both come back as `all_maids == []` —
            # `_query_maids_with_retry` surfaces the real failure as
            # `status: "error"`, so this can tell the two apart and say so.
            _any_query_failed = any(_log.get("status") == "error" for _log in maid_tool_log)
            if not all_maids and _any_query_failed:
                # A budget/capacity refusal is a very different thing from an
                # outage, and telling the user "the query failed" when the real
                # answer is "we're out of monthly data quota" sends them
                # debugging the wrong thing.
                _kinds = {_log.get("error_kind") for _log in maid_tool_log}
                # Record WHICH failure on the state, not just in the stream.
                # The narrator composes the visible message from the fact pack,
                # and `maid_count == 0` alone reads as "nobody visited these
                # spots" — a confident claim about the world made when no query
                # ran at all. `_msg` below is only a stream `update`, which the
                # composer never sees. See narrator/grounding._build_maid and
                # the live-test report's open issue H.
                geo["maid_failure_kind"] = _maid_failure_kind(_kinds)
                if "UnacastBudgetExhausted" in _kinds:
                    _msg = (
                        "This month's shared audience-data budget is used up, so I "
                        "couldn't pull the visitors for these spots. It resets at the "
                        "start of next month."
                    )
                elif "UnacastConcurrencyTimeout" in _kinds:
                    _msg = (
                        "The audience data service was at capacity for too long, so I "
                        "couldn't pull the visitors for these spots. Worth retrying in "
                        "a few minutes."
                    )
                elif "UnacastIPNotAllowlisted" in _kinds:
                    _msg = (
                        "I couldn't reach the audience data provider — this environment "
                        "isn't calling from an approved network address. That's a "
                        "configuration problem on our side, not something you did."
                    )
                elif "UnacastCircuitOpen" in _kinds:
                    _msg = (
                        "The audience data provider failed several times in a row, so "
                        "I've paused requests to it for a few minutes rather than burn "
                        "through the shared data budget getting nothing back. Worth "
                        "trying again shortly."
                    )
                elif "UnacastRequestTimeout" in _kinds:
                    _msg = (
                        "The audience data provider timed out on some very busy spots, "
                        "even after I split the request up. Retrying, a shorter lookback, "
                        "or fewer/smaller rings will help — a longer lookback makes it slower."
                    )
                elif "UnacastRateLimited" in _kinds:
                    _msg = (
                        "The audience data provider's daily request limit is used up, so I "
                        "couldn't pull the visitors for these spots. It resets at midnight UTC."
                    )
                elif "UnacastRequestRejected" in _kinds:
                    _msg = (
                        "The audience data provider rejected this search — usually a spot "
                        "outside the US/Canada area it covers. Retrying the same search "
                        "won't help; removing or changing those spots will."
                    )
                else:
                    _msg = (
                        "The audience data provider query failed, so this isn't a "
                        "confirmed empty result — I couldn't verify who's actually "
                        "been to these spots."
                    )
                writer({"type": "update", "content": _msg})

            geo["maid_query_skipped"] = False
            writer({"type": "update", "content": f"Found {len(all_maids):,} unique visitor profile(s); preparing the audience map..."})
            writer({"type": "thinking", "content": (
                f"MAID extraction complete: {len(all_maids)} unique MAIDs, {len(all_observations)} unique observation points"
            )})

    # ── Attribute devices to POIs, then apply the active audience filter ────
    # Two passes over attribute_audience:
    #   1. On the raw superset — stamps `poi_ids` on every row (needed for
    #      group filters later) and drops rows whose POI is no longer in the set.
    #      This becomes the persisted superset — audience layering re-filters
    #      it later without re-querying. stamp_stats=False: the per-POI numbers
    #      this pass would compute are pre-filter and not what the map should
    #      show.
    #   2. On the FILTERED subset — stamps the per-POI audience_count/
    #      visit_stats the map/user actually see, so a POI's on-screen count
    #      always matches the headline total.
    _raw_total, all_observations = attribute_audience(
        all_observations, updated_pois, stamp_stats=False
    )
    all_maids = sorted({o["maid"] for o in all_observations if o.get("maid")}) or all_maids

    # Active filter: an explicit one on `geo` (mid-turn edit / Phase-2
    # extraction) wins; else a session-cache restore carries the extraction's
    # last filter; else default to the user's stated lookback. Event-based runs
    # get no default filter (the query window IS the event dates already).
    audience_filter_spec = geo.get("audience_filter")
    if audience_filter_spec is None:
        if session_cache_hit and (existing or {}).get("audience_filter") is not None:
            audience_filter_spec = existing["audience_filter"]
        elif not is_event_based:
            # System default, not a user narrowing — `_derived` tells
            # grounding.py to keep this out of `active_filter` and the funnel
            # block, so the composer never presents it as something the user
            # chose. It still governs the query window exactly as before.
            audience_filter_spec = {"window_days": lookback_days, "_derived": True}
    elif not audience_filter_spec.get("_resolved") and (
        audience_filter_spec.get("groups") or audience_filter_spec.get("exclude_groups")
        or audience_filter_spec.get("any_of")
    ):
        # A fresh (first-mention, Phase-2 extraction) filter names groups as
        # loose labels ("gym", "Starbucks") — resolve to real poi_group_id
        # values now that the POI search has actually run. A recompute-path
        # filter (mid-turn edit, session-cache restore) is already resolved
        # and flagged `_resolved` so it's never re-resolved against a
        # DIFFERENT (edited) POI set. `any_of` clauses each need the same
        # resolution applied individually — they carry their own groups.
        #
        # A label that resolves to nothing (e.g. "SneakerCon" named but no
        # such POI was found) used to be silently DROPPED — an "intersection
        # of X and Y" would quietly collapse into just Y's visitors with no
        # sign anything was missing. `_missing_groups`/`_missing_exclude_groups`
        # collect what didn't resolve so it can be narrated + shown as a map
        # chip below, instead — kept as TWO lists (not one shared
        # `_missing_labels`) because an unresolved EXCLUDE label means the
        # exclusion the user asked for was silently never applied, a
        # different (and worse) failure than a missing POSITIVE group; the
        # repair path (builder_node's unresolved-group narration) needs to
        # tell them apart.
        _missing_groups: list[str] = []
        _missing_exclude_groups: list[str] = []

        def _resolve(clause: dict) -> dict:
            clause = dict(clause)
            if clause.get("groups"):
                resolved, missing = resolve_group_labels_verbose(clause["groups"], updated_pois)
                clause["groups"] = resolved
                _missing_groups.extend(missing)
            if clause.get("exclude_groups"):
                resolved, missing = resolve_group_labels_verbose(clause["exclude_groups"], updated_pois)
                clause["exclude_groups"] = resolved
                _missing_exclude_groups.extend(missing)
            # A POI collected ONLY to be excluded (e.g. the user's own store,
            # pulled in solely so "my store" resolves) must not also count as
            # a positive targeting source — see `scope_exclusion_to_named_groups`.
            clause = scope_exclusion_to_named_groups(clause, updated_pois)
            return clause

        audience_filter_spec = _resolve(audience_filter_spec)
        if audience_filter_spec.get("any_of"):
            audience_filter_spec["any_of"] = [_resolve(c) for c in audience_filter_spec["any_of"]]
        audience_filter_spec["_resolved"] = True
        if _missing_groups:
            audience_filter_spec["_unresolved_groups"] = _missing_groups
            writer({"type": "thinking", "content": (
                f"MAID: audience_filter group(s) not found in the POI set: "
                f"{', '.join(_missing_groups)} — dropped from the filter, so "
                f"op={audience_filter_spec.get('op')!r} now runs over fewer "
                f"groups than the user asked for"
            )})
        if _missing_exclude_groups:
            audience_filter_spec["_unresolved_exclude_groups"] = _missing_exclude_groups
            writer({"type": "thinking", "content": (
                f"MAID: audience_filter exclude_groups not found in the POI set: "
                f"{', '.join(_missing_exclude_groups)} — that exclusion was NOT "
                f"applied, so those visitors are still in the audience"
            )})
        # A RESOLVED exclude group whose query came back "partial" (some of
        # its POI keys failed) is not raised by `_assert_groups_fetched` under
        # the default union op — nulling the whole filter over a
        # partially-fetched exclusion is worse than a slightly leaky one. Say
        # so instead, so "excluding my stores" is never silently presented as
        # complete when it wasn't.
        _group_status = geo.get("maid_group_status") or {}
        _exclude_ids: set[str] = set(audience_filter_spec.get("exclude_groups") or [])
        for _c in audience_filter_spec.get("any_of") or []:
            _exclude_ids.update(_c.get("exclude_groups") or [])
        _partial_excludes = sorted(
            gid for gid in _exclude_ids
            if (_group_status.get(gid) or {}).get("status") == "partial"
        )
        if _partial_excludes:
            audience_filter_spec["_partial_exclude_groups"] = _partial_excludes
            writer({"type": "thinking", "content": (
                f"MAID: exclusion group(s) only partially fetched: "
                f"{', '.join(g.split(':', 1)[-1] for g in _partial_excludes)} — "
                f"applying the exclusion anyway, but it may miss some visitors"
            )})
        # SAME leniency for POSITIVE groups (see _assert_groups_fetched's
        # docstring): a "partial" group under intersection/difference/
        # min_distinct_groups is NOT unevaluable — it's the DEFAULT outcome
        # for any city-scale category search (100k-observations-per-feature
        # split), and the filter still evaluates honestly against whatever
        # rows DID come back. Narrated so an intersection that under-counts
        # because of a split is never mistaken for a complete answer.
        _positive_ids: set[str] = set(audience_filter_spec.get("groups") or [])
        for _c in audience_filter_spec.get("any_of") or []:
            _positive_ids.update(_c.get("groups") or [])
        _partial_groups = sorted(
            gid for gid in _positive_ids
            if (_group_status.get(gid) or {}).get("status") == "partial"
        )
        if _partial_groups:
            audience_filter_spec["_partial_groups"] = _partial_groups
            writer({"type": "thinking", "content": (
                f"MAID: audience_filter group(s) only partially fetched: "
                f"{', '.join(g.split(':', 1)[-1] for g in _partial_groups)} — "
                f"applying the filter anyway over the data that did come back; "
                f"it may undercount"
            )})
    # Stamp what this extraction actually PURCHASED onto the filter itself.
    # Every later re-filter (a mid-turn edit, a session-cache restore, the
    # publish-time reload in executors/media.py) reads the stored spec and not
    # this checkpoint, so without it a `trend` clause added later cannot tell
    # whether its prior window was ever bought — and an unevaluable trend
    # returns everyone or nobody rather than failing. Underscore-prefixed to
    # match `_resolved` / `_unresolved_groups`: internal, not a user predicate.
    if audience_filter_spec is not None and geo.get("history_days_bought"):
        audience_filter_spec["_history_days_bought"] = geo["history_days_bought"]
    geo["audience_filter"] = audience_filter_spec

    try:
        _filtered_maid_set = set(
            apply_audience_filter(
                all_observations, audience_filter_spec, pois=updated_pois,
                group_status=geo.get("maid_group_status"),
            )
        )
    except AudienceFilterUnevaluable as exc:
        # The filter needs history this extraction never bought. Fall back to
        # the unfiltered superset and SAY SO — returning a silently-wrong
        # audience is the exact failure this exception exists to prevent.
        logger.warning("MAID: audience_filter unevaluable — %s", exc)
        geo["maid_filter_unevaluable"] = str(exc)
        _hint = (
            " — ask me to re-run it with a longer lookback and I'll pull the history it needs"
            if getattr(exc, "needed_days", 0) else ""
        )
        writer({"type": "update", "content": (
            f"I couldn't apply that audience filter: {exc}. "
            f"Showing everyone who visited instead{_hint}."
        )})
        _filtered_maid_set = {o["maid"] for o in all_observations if o.get("maid")}
        # Persist what was APPLIED, not what was asked. Publish and every edit
        # path re-apply the stored filter, and this one would fail there again;
        # the intent survives in maid_filter_unevaluable for the narrator.
        audience_filter_spec = None
        geo["audience_filter"] = None
    filtered_observations = [o for o in all_observations if o.get("maid") in _filtered_maid_set]
    # Snapshot immediately — same side-channel pattern as
    # intersection_witness_stats: written synchronously inside the
    # apply_audience_filter call just above, read here before anything else
    # can run. Empty (0) on the AudienceFilterUnevaluable path, which is
    # correct: audience_filter_spec becomes None there, so is_role_spec()
    # below already gates role_confidence out regardless of this value.
    _open_days_observed = role_signal_stats()["open_days_observed"]

    # A session-cache restore keeps the per-POI stats built when the audience
    # was really queried (`stamp_stats=False`), and the whole-audience summary
    # stays on the checkpoint. Same reasoning as the POI-removal recompute in
    # builder_node._apply_maid_poi_edits.
    attr_total, filtered_observations = attribute_audience(
        filtered_observations, updated_pois, stamp_stats=not session_cache_hit
    )
    # `maid_count` is the TRUE superset — `_raw_total` (above), before this
    # step's filter narrows it — and `filtered_maid_count` is what the filter
    # actually leaves. Anything shown to a user reads the filtered number via
    # maid_query.audience_headline_count; `maid_count` is only ever "narrowed
    # from N". Same zero-or-keep-prior-nonzero guard as before.
    if _raw_total or not geo.get("maid_count"):
        geo["maid_count"] = _raw_total
    geo["filtered_maid_count"] = attr_total

    # ── The funnel ─────────────────────────────────────────────────────────
    # Every number the user is shown must have a chain behind it. Without this,
    # "why is this 12 / why is this 111k / why is this zero" is unanswerable
    # after the fact — and each stage below can independently collapse an
    # audience for a reason nothing else records.
    _timed_visits = sum(
        1 for o in all_observations for v in (o.get("visits") or []) if visit_is_timed(v)
    )
    _all_visits = sum(len(o.get("visits") or []) for o in all_observations)
    geo["maid_funnel"] = {
        "signal_gate": describe_gate(),
        "history_days_bought": geo.get("history_days_bought"),
        "devices_attributed": _raw_total,
        "devices_after_filter": attr_total,
        "visits_total": _all_visits,
        "visits_dwell_measurable": _timed_visits,
        "dwell_measurable_pct": (
            round(_timed_visits / _all_visits * 100) if _all_visits else 0
        ),
        "unconfirmed_visit_pct": (
            round(
                sum(
                    1 for o in all_observations for v in (o.get("visits") or [])
                    if v.get("confirmed") is False
                ) / _all_visits * 100
            ) if _all_visits else 0
        ),
        "filter_chips": describe_audience_filter(audience_filter_spec),
        "filter_unevaluable": geo.get("maid_filter_unevaluable"),
        # An LLM-extracted key with no producer in _apply_clause (e.g. a typo'd
        # `min_dwell_minutes`) used to be silently ignored. apply_audience_filter
        # already logs this; stamped here too so it's visible without grepping
        # logs — the spec is already in scope, so no re-derivation needed.
        "unknown_filter_keys": unknown_filter_keys(audience_filter_spec),
        # An N-way intersection ("vet AND PetSmart AND dog park") silently
        # requires PAIRWISE NON-OVERLAPPING witness visits per device — correct
        # (co-located geofences can return one physical presence under two
        # groups otherwise), but a user has no way to know a same-afternoon
        # vet+PetSmart trip doesn't count. Read right after
        # apply_audience_filter ran, still synchronous — see
        # intersection_witness_stats's docstring. Zero/zero when the spec had
        # no intersection clause.
        **intersection_witness_stats(),
        **_truncation_facts(updated_pois),
    }
    _trunc = geo["maid_funnel"].get("truncated_poi_count") or 0
    if _trunc:
        writer({"type": "update", "content": (
            f"{_trunc} of these spots are busy enough that I could only sample "
            f"their visitors, so their visit counts are a floor rather than an "
            f"exact number."
        )})
    writer({"type": "thinking", "content": (
        f"MAID funnel: {_raw_total:,} device(s) attributed -> {attr_total:,} after filter; "
        f"{_timed_visits:,}/{_all_visits:,} visits have measurable dwell "
        f"({geo['maid_funnel']['dwell_measurable_pct']}%); "
        f"bought {geo.get('history_days_bought') or lookback_days} day(s) of history"
    )})

    # The audience_filter (default or user-stated) narrowed a real, nonzero
    # superset down to nobody — distinct from "no visitors at all" (raw==0).
    # Surfaced to the narrator (grounding._build_maid) so the reveal can name the
    # filter and offer to relax it instead of silently reporting the pre-filter
    # count.
    geo["maid_filter_zeroed"] = bool(attr_total == 0 and _raw_total)
    if geo["maid_filter_zeroed"]:
        writer({"type": "thinking", "content": (
            f"MAID: audience_filter "
            f"({', '.join(describe_audience_filter(audience_filter_spec)) or audience_filter_spec}) "
            f"matched 0 of {_raw_total} device(s) found"
        )})

    if session_cache_hit:
        # The checkpoint POIs normally still carry the stats from the run that
        # queried the vendor; refill from the stored extraction for any that
        # lost them (a session restored into a fresh process).
        from app.graph.builder.executors.geo import _poi_key
        _stored_stats = {}
        for _p in (existing["pois"] or []):
            _k = _poi_key(_p)
            if _k is not None and _p.get("visit_stats"):
                _stored_stats[_k] = _p["visit_stats"]
        for _p in updated_pois:
            if not _p.get("visit_stats"):
                _s = _stored_stats.get(_poi_key(_p))
                if _s:
                    _p["visit_stats"] = _s
    else:
        # Whole-audience summary for the short reveal line.
        geo["maid_visit_stats"] = compute_visit_stats(filtered_observations)["summary"]
    # Empty dict rather than None so the reveal-beat reads below stay total.
    visit_stats_summary = geo.get("maid_visit_stats") or compute_visit_stats([])["summary"]

    # Role-inference confidence — ONLY when the active filter actually reads
    # as a role predicate (min_weekly_hours or a presence-pattern field).
    # NEVER gates the returned audience (see role_confidence's own docstring
    # and AUDIENCE_FILTER_ROLE_GUARD — role targeting is never refused); this
    # only decides what the reveal/UI SAY about the audience they get.
    if is_role_spec(audience_filter_spec):
        _role_yield_pct = round(attr_total / _raw_total * 100, 1) if _raw_total else 0.0
        geo["maid_funnel"]["role_basis"] = (
            "dwell" if is_dwell_only_role_spec(audience_filter_spec) else "presence pattern"
        )
        geo["maid_funnel"]["role_yield_pct"] = _role_yield_pct
        geo["maid_funnel"]["open_days_observed"] = _open_days_observed
        geo["maid_funnel"]["dwell_measurable_device_pct"] = (
            visit_stats_summary.get("dwell_measurable_device_pct", 0)
        )
        geo["maid_funnel"]["role_confidence"] = role_confidence(
            _open_days_observed, _role_yield_pct,
            visit_stats_summary.get("dwell_measurable_device_pct", 0),
            audience_filter_spec,
        )

    # Full superset rows (lat,lng,maid,count,visits,days,poi_key,poi_ids) persist
    # as-is — maid is needed for POI-removal recompute, count/visits for
    # frequency/time layering (apply_audience_filter, compute_audience_set_op).
    # Nothing gets stripped until the SSE/public boundary (public_observations,
    # below), which ships only the FILTERED rows.

    # ── Persist bulk data to Postgres; keep only reference in checkpoint state ──
    # Skip on a session-cache hit (already stored in a prior run of this node).
    if not session_cache_hit:
        extraction_id = await store_maid_extraction(
            session_id=session_id,
            maids=all_maids,
            observations=all_observations,
            pois=updated_pois,
            center=center,
            search_radius_km=geo.get("search_radius_km"),
            lookback_days=lookback_days,
            event_date_ranges=event_date_ranges,
            audience_filter=audience_filter_spec,
            filtered_maid_count=attr_total,
        )
        geo["maid_extraction_id"] = extraction_id
        writer({"type": "update", "content": "Saving the extracted audience so this result can be reused later..."})
        writer({"type": "thinking", "content": f"MAID data persisted to DB (extraction_id={extraction_id})"})

    maid_count = geo.get("maid_count", 0)
    pois_found = geo.get("pois_found", 0)

    # ── Stream map to frontend ─────────────────────────────────────────────
    # build_maid_split_view is the single source of truth for this payload
    # shape (shared with builder_node._maid_confirm_map_event and
    # resume_preflight.maid_map_reemit_event) — it re-applies audience_filter_
    # spec over the RAW superset itself, so `maid_count` here is guaranteed to
    # equal `attr_total`/`geo["filtered_maid_count"]` above, not the pre-filter
    # `_raw_total`.
    if not ws.get("_maid_map_emitted"):
        writer({
            "type": "map_data",
            "content": build_maid_split_view(
                pois=updated_pois,
                observations=all_observations,
                audience_filter=audience_filter_spec,
                center=center,
                visit_stats=visit_stats_summary,
                search_radius_km=geo.get("search_radius_km"),
                lookback_days=lookback_days,
                event_date_ranges=event_date_ranges,
                stamp_stats=not session_cache_hit,
                editable=True,
                role_confidence_tier=geo["maid_funnel"].get("role_confidence"),
                role_basis=geo["maid_funnel"].get("role_basis"),
            ),
        })
        ws["_maid_map_emitted"] = True

    # `lookback_days` (the "how far back to search" slot) and
    # `audience_filter.window_days` (a stated recency NARROWING) are
    # different knobs that can both be live at once — when they diverge, the
    # filter's window is what's actually enforced on the shown audience, so
    # the reveal must say THAT number, not the unrelated search-depth slot
    # ("past 7 day(s)" while a 45-day filter is what's really keeping devices
    # out reads as Punk contradicting its own result).
    _shown_window = (audience_filter_spec or {}).get("window_days") or lookback_days
    date_context = (
        f"event dates: {', '.join(event_date_ranges)}"
        if event_date_ranges
        else f"past {_shown_window} day(s)"
    )

    return {
        "maid_tool_log": maid_tool_log,
        # The raw superset, for "narrowed from N" only — `builder_node.py`'s
        # reveal beat uses `filtered_maid_count` as the headline.
        "maid_count": maid_count,
        "filtered_maid_count": attr_total,
        "audience_filter_chips": describe_audience_filter(audience_filter_spec),
        "maid_filter_zeroed": geo["maid_filter_zeroed"],
        "maid_funnel": geo["maid_funnel"],
        "pois_found": pois_found,
        "date_context": date_context,
        "lookback_days": lookback_days,
        "poi_radius_m": poi_radius_m,
        # Per-device frequency (see compute_visit_stats). Consumed by the reveal
        # beat so Punk can mention the repeat crowd.
        "visit_basis": visit_stats_summary["basis"],
        "repeat_visitor_count": visit_stats_summary["repeat_visitor_count"],
        "repeat_visitor_pct": visit_stats_summary["repeat_visitor_pct"],
        "visit_buckets": visit_stats_summary["buckets"],
        "max_seen": visit_stats_summary["max_seen"],
        # Role-inference disclosure — only present when audience_filter reads
        # as a role predicate (is_role_spec). builder_node.py's reveal beat
        # reads these straight off the executor result, not funnel-only —
        # a funnel-only value never reaches the beat (see run_maid_query's
        # own return-dict docstring).
        "role_confidence": geo["maid_funnel"].get("role_confidence"),
        "role_basis": geo["maid_funnel"].get("role_basis"),
        "role_yield_pct": geo["maid_funnel"].get("role_yield_pct"),
        "dwell_measurable_device_pct": geo["maid_funnel"].get("dwell_measurable_device_pct"),
        # Set only when the query genuinely failed (budget/breaker/IP/an
        # un-splittable timeout) with nothing usable to show — never on a
        # real, honestly-empty audience. builder_node.py reads this to keep
        # the op OUT of ops_done instead of treating the failure as a
        # completed, confirmable extraction. See geo["maid_failure_kind"].
        "failure_kind": geo.get("maid_failure_kind"),
    }


async def query_pois_audience(
    geo: dict, pois: list[dict], *, writer: Callable[[dict], None]
) -> tuple[list[dict], Optional[str]]:
    """Query the audience for a SUBSET of POIs and return folded observation
    rows ``[{"lat","lng","maid","count","poi_key","visits","days"}]`` plus a
    failure kind (``_maid_failure_kind`` — "budget"/"capacity"/"circuit_open"/…,
    or None on success).

    Used when a POI is ADDED at the maid confirmation step: the vendor was never
    asked about the new spot, so without this the added POI would show 0
    audience. Sized and anchored exactly like ``run_maid_query``'s lookback
    path — yesterday back, widened by ``required_history_days`` for the active
    filter — so an added POI's history matches the rest of the audience. Uses the
    recent-lookback window even for event-based campaigns (the added POI carries
    no event dates). Rows are ``[]`` when the querier is not configured or the
    query fails; the POI then honestly shows no audience — but the CALLER now
    gets to say why, instead of a silent 0 indistinguishable from "genuinely no
    visitors" (see ``_apply_maid_poi_edits``, the only caller).
    """
    poi_radius_km = geo.get("poi_radius_km") or DEFAULT_POI_RADIUS_KM
    pois = [
        {**p, "radius_km": p.get("radius_km") or poi_radius_km}
        for p in pois if p.get("lat") and p.get("lng")
    ]
    if not pois:
        return [], None

    querier = get_maid_querier()
    if querier is None:
        return [], None

    lookback_days = geo.get("lookback_days") or 7
    query_days = required_history_days(lookback_days, geo.get("audience_filter"))
    dates = build_date_list(_yesterday().isoformat(), query_days)
    pois_payload = [
        {"lat": p["lat"], "lng": p["lng"], "radius_km": p["radius_km"]} for p in pois
    ]

    # Tell the user what this costs BEFORE the wait — same disclosure
    # run_maid_query gives the first-run query (above), missing here before:
    # a mid-build POI add could block for minutes and spend shared vendor
    # budget with no announcement a query even started. Free — arithmetic
    # over the watermark, not a probe.
    try:
        from app.graph.unacast_query import estimate_cost

        _est = await estimate_cost(dates, pois_payload)
        if _est["calls"]:
            writer({"type": "update", "content": (
                f"Pulling visitors for {_est['pois'] - _est['cached_pois']} "
                f"added spot(s) — {_eta_text(_est.get('eta_s') or 0)}..."
            )})
    except Exception as _exc:  # noqa: BLE001 — an estimate must never block a query
        logger.debug("MAID add: spend estimate unavailable — %s", _exc)

    writer({"type": "thinking", "content":
        f"MAID add: querying {len(pois_payload)} added POI(s), {query_days}-day window"})
    rows, _log = await _query_maids_with_retry(
        querier, dates=dates, pois=pois_payload, writer=writer,
    )
    if not rows:
        _kinds = {_log.get("error_kind")} if _log.get("error_kind") else set()
        failure_kind = _maid_failure_kind(_kinds) if _kinds else None
        return [], failure_kind

    fold = _new_fold()
    for row in rows:
        _fold_row(fold, row)
    return _finish_fold(fold, _category_by_key(pois)), None
