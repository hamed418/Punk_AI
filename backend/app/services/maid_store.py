"""
app/services/maid_store.py
──────────────────────────
Persist and retrieve MAID extraction results in Postgres.

LangGraph checkpoint state only holds `maid_extraction_id` — a UUID reference.
The actual device IDs, observation coordinates, and map rebuild data live here,
preventing oversized checkpoint state when device counts reach tens of thousands.
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from functools import lru_cache
from zoneinfo import ZoneInfo
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.db.models import MaidExtraction, SuppressedMaid
from app.graph.maid_query import visit_is_timed

logger = logging.getLogger(__name__)

# Default span (days) for the two-window trend compare when the spec gives no
# window_days — "started"/"lapsed" need a "recent" window to be meaningful
# even when the caller isn't also filtering on recency.
_DEFAULT_TREND_WINDOW_DAYS = 30


def _dwell_seconds(visit: dict, bound: str = "lower") -> int:
    """Observed dwell for one visit, in seconds.

    ``bound="lower"`` (default, unchanged behaviour): ``cluster_visits``'
    ``dwell_lower_s`` — first ping to last, zero for a single-ping visit.
    That is a genuine LOWER bound, not the true dwell — a device that pinged
    twice 10 minutes apart but stayed 3 hours reads as a 10-minute visit.

    ``bound="upper"``: ``dwell_upper_s`` — the real bound ``cluster_visits``
    already computes from the device's own ping timeline (arrived after its
    previous ping ANYWHERE, left before its next one), and which nothing read
    until this parameter existed. Opt-in only: switching every caller's
    default would silently resize every existing dwell-based audience.
    """
    key = "dwell_upper_s" if bound == "upper" else "dwell_lower_s"
    return int(visit.get(key) or 0)


def _dwell_at_least(visit: dict, min_dwell_min: int, *, bound: str = "lower") -> bool:
    """Whether this visit's MEASURED dwell clears ``min_dwell_min`` minutes.

    A visit with a single ping has unknown duration and can never clear a dwell
    floor — see ``visit_is_timed``. That is not a new restriction in effect (an
    unmeasured visit's fabricated 1 minute failed any realistic threshold too),
    but it is now explicit, so callers can report how much of the audience dwell
    was measurable instead of silently dropping half of it.
    """
    return visit_is_timed(visit) and _dwell_seconds(visit, bound=bound) >= min_dwell_min * 60


def _visit_started_at(visit: dict) -> datetime | None:
    """Parse a visit's ``ts`` once, tolerating the same malformed/missing cases
    ``_visit_qualifies`` already tolerates inline — shared so the presence-
    pattern aggregates (``min_open_day_share`` &c.) can't drift from what
    per-visit scoping treats as unparseable."""
    ts = visit.get("ts")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


@lru_cache(maxsize=512)
def _zone_at(lat_r: float, lng_r: float) -> str | None:
    """IANA timezone name for a rounded coordinate, or None.

    Cached on coordinates rounded to ~1 km: every POI in one metro resolves to
    the same zone, so this is a handful of lookups per extraction. The
    TimezoneFinder instance is built lazily and kept — construction loads the
    boundary data and is the expensive part, not the query.
    """
    global _TZ_FINDER
    try:
        if _TZ_FINDER is None:
            from timezonefinder import TimezoneFinder

            _TZ_FINDER = TimezoneFinder()
        return _TZ_FINDER.timezone_at(lat=lat_r, lng=lng_r)
    except Exception as exc:  # noqa: BLE001 — a tz lookup must never break a filter
        logger.warning("maid_store: timezone lookup failed for (%s, %s) — %s", lat_r, lng_r, exc)
        return None


_TZ_FINDER = None


def _local_shift(dt: datetime, pois: list[dict] | None) -> datetime:
    """Shift a stored UTC timestamp into the POI set's LOCAL time.

    ``hours``/``days_of_week`` are stated by the user in local time; every
    stored ``ts`` is UTC. This used to be ``round(lng / 15)`` — a fixed offset
    with no DST and no timezone database, so "before 9am" in Denver evaluated as
    "before 8am" for the eight months a year MDT is in effect, and a campaign
    spanning two zones got one offset for all of it.

    Resolved per POI set (they cluster in one metro) against the real IANA
    zone. Falls back to the old longitude estimate if the lookup fails, because
    a wrong-by-an-hour filter is still better than a wrong-by-five-hours one.
    """
    zone = _zone_for(pois)
    if zone is not None:
        try:
            return dt.astimezone(zone)
        except Exception:  # noqa: BLE001
            pass
    return dt + timedelta(hours=_tz_offset_hours(pois))


def _zone_for(pois: list[dict] | None):
    """First resolvable IANA zone among ``pois``' coordinates.

    Tries every POI, not just the first with usable coordinates —
    ``timezonefinder``'s ``timezone_at`` returns ``None`` for a coordinate
    outside any land timezone polygon (a documented library limitation for
    ocean/coastal points), which a waterfront business or a slightly-off
    geocode can genuinely produce. Giving up on the whole set after one
    such POI used to silently drop hours/days_of_week evaluation back to the
    DST-ignorant longitude estimate for every device in the audience, even
    when the 2nd POI in the exact same list would have resolved cleanly.
    """
    for p in pois or []:
        lat, lng = p.get("lat"), p.get("lng")
        if lat is None or lng is None:
            continue
        name = _zone_at(round(float(lat), 2), round(float(lng), 2))
        if not name:
            continue
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 — unknown zone name, try the next POI
            continue
    return None


def _tz_offset_hours(pois: list[dict] | None) -> int:
    """Longitude-derived local-time offset — the FALLBACK for ``_local_shift``.

    No DST and no timezone database, so it is off by an hour wherever DST is in
    effect. Retained only for when the real lookup fails, and for callers that
    pass no POIs at all (tests fixed to a known UTC time).
    """
    for p in pois or []:
        lng = p.get("lng")
        if lng is not None:
            return round(float(lng) / 15.0)
    return 0


async def store_maid_extraction(
    *,
    session_id: str,
    maids: list[str],
    observations: list[dict],
    pois: list[dict],
    center: dict,
    search_radius_km: float | None,
    lookback_days: int | None,
    event_date_ranges: list[str],
    audience_filter: dict | None = None,
    filtered_maid_count: int | None = None,
) -> str:
    """Persist extraction results; return the new extraction UUID.

    ``observations`` are ``{lat, lng, maid, count, visits?, days?, poi_ids}``
    rows — the full attributed rows, not stripped. Frequency CAN be
    recomputed from a stored row (``maid_query.compute_visit_stats``);
    `pois[].visit_stats` (per POI) and the checkpoint's `geo["maid_visit_stats"]`
    (whole audience) are just the pre-computed summaries so callers don't have
    to.

    ``maids``/``observations`` are the UNFILTERED superset — everything bought
    for the extraction's POIs and window, which is wider than the stated
    lookback when a filter needs older history (``maid_history``).
    ``audience_filter`` is the active
    ``AudienceFilter`` spec (``apply_audience_filter``) and
    ``filtered_maid_count`` its result count — this is the headline number
    shown to the user; ``maid_count`` (the superset size) is not.
    """
    async with AsyncSessionLocal() as db:
        row = MaidExtraction(
            session_id=session_id,
            maid_count=len(maids),
            maids=maids,
            observations=observations,
            pois=pois,
            center=center,
            search_radius_km=search_radius_km,
            lookback_days=lookback_days,
            event_date_ranges=event_date_ranges or [],
            audience_filter=audience_filter,
            filtered_maid_count=filtered_maid_count,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        extraction_id = str(row.id)
        logger.info(
            "MAID extraction stored",
            extra={"session_id": session_id, "extraction_id": extraction_id, "maid_count": len(maids)},
        )
        return extraction_id


async def update_maid_extraction(
    extraction_id: str,
    *,
    maids: list[str],
    observations: list[dict],
    pois: list[dict],
    maid_count: int,
    audience_filter: dict | None = None,
    filtered_maid_count: int | None = None,
    _clear_filter: bool = False,
) -> bool:
    """Rewrite an existing extraction row in place after a POI removal or an
    audience-filter edit.

    Reuses the SAME row (UUID) so ``geo["maid_extraction_id"]`` stays valid.
    ``audience_filter``/``filtered_maid_count`` are left untouched unless
    passed (a POI-removal edit doesn't change the active filter); pass
    ``_clear_filter=True`` to explicitly reset them to null.
    Returns True when a row was updated, False when the id was not found.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(MaidExtraction).where(MaidExtraction.id == extraction_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return False
        row.maids = maids
        row.observations = observations
        row.pois = pois
        row.maid_count = maid_count
        if _clear_filter:
            row.audience_filter = None
            row.filtered_maid_count = None
        elif audience_filter is not None or filtered_maid_count is not None:
            row.audience_filter = audience_filter
            row.filtered_maid_count = filtered_maid_count
        await db.commit()
        logger.info(
            "MAID extraction updated",
            extra={"extraction_id": extraction_id, "maid_count": maid_count},
        )
        return True


async def fetch_maid_extraction_by_session(session_id: str) -> dict[str, Any] | None:
    """Return the most recent extraction for a session, or None if none exist."""
    from sqlalchemy import desc
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(MaidExtraction)
            .where(MaidExtraction.session_id == session_id)
            .order_by(desc(MaidExtraction.created_at))
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return {
            "id": str(row.id),
            "maid_count": row.maid_count,
            "maids": row.maids,
            "observations": row.observations,
            "pois": row.pois,
            "center": row.center,
            "search_radius_km": row.search_radius_km,
            "lookback_days": row.lookback_days,
            "event_date_ranges": row.event_date_ranges or [],
            "audience_filter": row.audience_filter,
            "filtered_maid_count": row.filtered_maid_count,
            # None = raw maids/observations above are intact. Non-None = they
            # were cleared (publish, or the abandoned-row sweep) and this dict's
            # "maids"/"observations" are empty regardless of maid_count — a
            # caller that only checks maid_count will read a purged row as a
            # real one. See _maid_cache_still_valid for why that matters.
            "purged_at": row.purged_at,
        }


async def fetch_maid_extraction(extraction_id: str) -> dict[str, Any] | None:
    """Return extraction data dict or None if not found."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(MaidExtraction).where(MaidExtraction.id == extraction_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return {
            "maid_count": row.maid_count,
            "maids": row.maids,
            "observations": row.observations,
            "pois": row.pois,
            "center": row.center,
            "search_radius_km": row.search_radius_km,
            "lookback_days": row.lookback_days,
            "event_date_ranges": row.event_date_ranges or [],
            "audience_filter": row.audience_filter,
            "filtered_maid_count": row.filtered_maid_count,
            "purged_at": row.purged_at,
        }


async def purge_maid_extraction(extraction_id: str, *, reason: str = "") -> bool:
    """Clear the raw device-ID superset (`maids`, `observations`) from a stored
    extraction. Everything else on the row — counts, pois, center, the filter
    spec — is left alone: reporting and campaign-template reuse need them,
    only the raw identifiers are the retention-sensitive part.

    Called from two places: the publish path, once a publish succeeds (the
    identifiers are in Meta by then), and the abandoned-row sweep script, for
    rows nobody came back to. Idempotent — purging an already-purged row is a
    no-op that still returns True.

    Best-effort by design, same as every other cleanup call on the publish
    path: a failure here must never turn a successful publish into an error.
    Callers on the publish path should wrap this in their own try/except
    rather than let it propagate.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(MaidExtraction).where(MaidExtraction.id == extraction_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return False
        if row.purged_at is not None:
            return True
        row.maids = []
        row.observations = []
        row.purged_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info(
            "maid_store.purge_maid_extraction: cleared raw MAIDs for %s%s",
            extraction_id, f" ({reason})" if reason else "",
        )
        return True


async def suppress(maids: list[str]) -> list[str]:
    """Drop any MAID on the suppression list before it reaches Meta.

    The seam for a supplier opt-out/deletion feed that does not exist yet —
    ``suppressed_maids`` is empty in every deployment today. Built now rather
    than after the feed is answered so the one call site that MUST check it
    (``meta_ads.upload_maids_to_audience``) exists, is wired, and is tested
    before there is real data to feed it; wiring the feed later is an
    ingester writing rows to ``suppressed_maids``, nothing about the upload
    path changes.

    Fails open (returns ``maids`` unfiltered) on a DB error, loudly logged —
    the same call-must-never-block-a-publish rule every other diagnostic read
    in this pipeline follows (see ``_seed_supports_lookalike``). An empty
    table makes this the overwhelmingly common path regardless.
    """
    if not maids:
        return maids
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(SuppressedMaid.maid).where(SuppressedMaid.maid.in_(maids))
            )
            blocked = {row[0] for row in result.all()}
    except Exception as exc:  # noqa: BLE001 — a suppression-list outage must not block a publish
        logger.warning("maid_store.suppress: lookup failed, uploading unfiltered — %s", exc)
        return maids
    if not blocked:
        return maids
    logger.info("maid_store.suppress: %d of %d MAIDs suppressed", len(blocked), len(maids))
    return [m for m in maids if m not in blocked]


async def compute_audience_set_op(
    extraction_id: str,
    category_ids: list[str],
    op: Literal["union", "intersection", "difference"],
    *,
    min_visits_per_week: float | None = None,
) -> dict[str, Any]:
    """Union/intersect/subtract the audiences of two or more POI category groups.

    ``category_ids`` are ``group["id"]`` values from
    ``geo.group_pois_by_category`` (e.g. ``"category:gym"``,
    ``"competitor_brand:Starbucks"``) — "people who go to both the gym crowd
    AND the coffee-shop crowd" is ``op="intersection"`` over those two ids.

    ``min_visits_per_week`` (optional) restricts each group's audience to
    devices visiting at that rate or higher — "gym-goers who show up twice a
    week" — *before* the set operation runs. Needs the extraction's
    ``lookback_days`` to convert a weekly rate into an absolute visit-count
    threshold over the actual window queried.

    Returns ``{"maids": [...], "maid_count": N, "visit_basis": "visits"|
    "sightings", ...}`` on success (``maids`` for internal/Meta-audience use
    only — never put this on an SSE event), or ``{"error": "..."}`` when the
    extraction or a category id doesn't exist.
    """
    from app.graph.builder.executors.geo import group_pois_by_category
    from app.graph.maid_query import compute_visit_stats

    extraction = await fetch_maid_extraction(extraction_id)
    if extraction is None:
        return {"error": f"no extraction found for id {extraction_id}"}
    if extraction.get("purged_at"):
        # observations is empty on a purged row (published, or swept as
        # abandoned) — computing a set op against it would silently report a
        # 0-person result instead of the honest "this audience is gone".
        return {"error": f"extraction {extraction_id} was already published and its raw data cleared"}

    groups = {g["id"]: g for g in group_pois_by_category(extraction["pois"] or [])}
    missing = [cid for cid in category_ids if cid not in groups]
    if missing:
        return {"error": f"unknown category id(s): {missing}"}

    observations = extraction["observations"] or []
    weeks = max(extraction.get("lookback_days") or 7, 1) / 7
    threshold = min_visits_per_week * weeks if min_visits_per_week is not None else None
    visit_basis = "sightings"

    per_group_sets: list[set[str]] = []
    for cid in category_ids:
        rows = [o for o in observations if cid in (o.get("poi_ids") or [])]
        stats = compute_visit_stats(rows)
        if stats["summary"]["basis"] == "visits":
            visit_basis = "visits"
        per_device = stats["per_device"]
        if threshold is not None:
            per_group_sets.append({m for m, v in per_device.items() if v >= threshold})
        else:
            per_group_sets.append(set(per_device.keys()))

    if op == "union":
        result = set().union(*per_group_sets) if per_group_sets else set()
    elif op == "intersection":
        result = set.intersection(*per_group_sets) if per_group_sets else set()
    elif op == "difference":
        result = per_group_sets[0].difference(*per_group_sets[1:]) if per_group_sets else set()
    else:
        return {"error": f"unknown op: {op}"}

    return {
        "op": op,
        "category_ids": category_ids,
        "min_visits_per_week": min_visits_per_week,
        "visit_basis": visit_basis,
        "maid_count": len(result),
        "maids": sorted(result),
    }


# ── Audience layering: one flat filter spec, one evaluator ─────────────────
#
# AudienceFilter is a plain dict (not a class — every field optional, `None`/
# absent = no constraint). All fields:
#
#   groups            list[str]   poi_group_id() values ("category:gym",
#                                  "competitor_brand:Starbucks"); empty/absent
#                                  = every POI in scope
#   op                "union" | "intersection" | "difference"  (default union)
#   exclude_groups    list[str]   drop any device seen at any of these groups
#   window_days       int         recency filter — only visits in the last N
#                                  days count (independent of how wide the
#                                  extraction over-fetched)
#   min_visits        int         "at least twice", "3+ times"
#   min_distinct_pois int         distinct PLACES, not categories — "2 different
#                                  courses", "multiple locations of the same chain"
#   days_of_week      list[int]   Mon=0..Sun=6 — "weekdays" = [0,1,2,3,4]
#   hours             [lo, hi)    local hour range, e.g. [6, 9) = before 9am
#   min_dwell_min     int         "3+ hours at a bar" -> 180
#   min_weekly_hours  float       total dwell/week -> "inside 40+ hrs/week"
#                                 (owner/staff, not a customer)
#   trend             "started" | "lapsed"   two-window compare, see below
#   cadence_days      int         target recurring interval — "every payday"
#   cadence_tolerance_days int    +/- window around cadence_days (default 20%)
#   any_of            list[AudienceFilter]   OR of independent clauses, each
#                                 the shape above (2-level DNF — see
#                                 _apply_clause). Mutually exclusive with the
#                                 flat fields on the SAME object: a clause
#                                 either sets any_of, or sets the flat fields,
#                                 never both.
#   invert            bool        flip a SELECT into an EXCLUDE over the same
#                                 otherwise-eligible pool — every other field
#                                 above is a minimum/membership test with no
#                                 negated counterpart, so this is how "drop
#                                 the staff" pairs with min_weekly_hours, or
#                                 "not the regulars" with min_visits.
#   min_visits_per_group int      per-group floor — "3+ times at the gym AND
#                                 3+ at the coffee shop". `min_visits` is a
#                                 TOTAL across the clause and cannot say this.
#   min_distinct_groups int       "3 of the 5 place types" — at least N of the
#                                 clause's `groups` (every group in the build
#                                 when `groups` is empty), each backed by a
#                                 witness visit, the witnesses pairwise
#                                 non-overlapping in time (same rule as
#                                 `intersection`, which is the N = len(groups)
#                                 case). `min_distinct_pois` cannot say this: it
#                                 counts PLACES, so five Starbucks satisfy it.
#   min_share_in_scope float      0..1, the share of a device's own visits that
#                                 must fall inside this clause's scope. This is
#                                 how "ONLY on weekdays" is expressed — every
#                                 other field is "at least one", so exclusivity
#                                 had no representation at all.
#   min_confidence    "confirmed" drop visits whose evidence is a single
#                                 low-accuracy ping (see cluster_visits).
#   exclude_window_days int       scope for `exclude_groups`, in days. Absent =
#                                 inherit the selection's scope ("gym in the
#                                 last 7 days but not my store" means no store
#                                 visit in those 7 days). 0 = "ever".
#   trend_recent_days / trend_prior_days int
#                                 asymmetric trend windows. "Suddenly started
#                                 going after never going before" wants a SHORT
#                                 recent window and a LONG prior one; the
#                                 symmetric default answers a different question.
#   _history_days_bought int      INTERNAL. Days the extraction actually
#                                 purchased, stamped by run_maid_query so a
#                                 later re-filter can tell whether a trend
#                                 clause's prior window was ever bought — see
#                                 assert_filter_evaluable.
#   min_open_day_share float 0..1 PRESENCE-PATTERN signal, not dwell: distinct
#                                 local days a device was seen at the scope's
#                                 POIs, divided by the scope's own OBSERVED
#                                 operating days (distinct local days ANY
#                                 device was seen there — an empirical
#                                 operating window derived from pings already
#                                 bought, no Places lookup). One ping a day
#                                 qualifies — unlike min_weekly_hours this does
#                                 NOT need a measured dwell, so it survives the
#                                 ~47% of visits that are single-ping (see
#                                 docs/maid_signal_quality_baseline.md §4).
#                                 "owner/staff, not a customer" when high.
#   min_intraday_span_min int    minutes between a device's FIRST and LAST
#                                 ping on its longest single local day at the
#                                 scope's POIs (max across days) — the arrival-
#                                 to-departure envelope, not summed dwell.
#                                 Immune to VISIT_GAP_MINUTES fragmentation: a
#                                 quiet-phone stay that gap-clustering splits
#                                 into several short visits still spans the
#                                 same envelope. "spends all day inside" ->
#                                 large value here even when min_dwell_min
#                                 reads near zero on the fragments.
#   min_days_present  int         absolute floor on distinct local presence-
#                                 days, alongside min_open_day_share — stops a
#                                 thin-evidence POI ("2 of 3 observed days")
#                                 from clearing a share threshold on almost no
#                                 evidence.
#
# min_open_day_share/min_intraday_span_min/min_days_present are PER-DEVICE
# AGGREGATES over the whole clause scope, computed once per _apply_clause call
# — NOT per-visit tests. They do not belong in _visit_qualifies and must never
# be added to _membership_scoped (that flag narrows which VISITS count toward
# a frequency total; these three read every visit in scope regardless). See
# the aggregate block after min_weekly_hours below.
#
# An empty/absent spec returns the full union — identical to today's
# behaviour (no regression for the 12 prompts that need no layering).
AudienceFilter = dict


def has_time_predicate(spec: dict | None) -> bool:
    """True if ``spec`` (or any ``any_of`` branch) needs visit timestamps to
    evaluate — the ``window_days``/``days_of_week``/``hours``/``min_dwell_min``/
    ``min_weekly_hours``/``trend``/``cadence_days``/presence-pattern family.
    Callers use this to tell "the filter matched nobody" apart from "this data
    has no timestamps to filter on at all" (see ``_apply_clause``'s
    ``has_visit_data`` guard).
    """
    if not spec:
        return False
    if spec.get("any_of"):
        return any(has_time_predicate(c) for c in spec["any_of"])
    return bool(
        spec.get("window_days") or spec.get("days_of_week") or spec.get("hours")
        or spec.get("min_dwell_min") or spec.get("min_weekly_hours")
        or spec.get("trend") or spec.get("cadence_days")
        or spec.get("min_open_day_share") or spec.get("min_intraday_span_min")
        or spec.get("min_days_present")
    )


_DAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def describe_audience_filter(spec: dict | None) -> list[str]:
    """Short human-readable chips summarizing the active ``AudienceFilter`` —
    what the frontend shows on the maid_split_view map so a layering request
    the user made ("only weekends", "3+ visits") stays visible after the
    reply narrates it once, rather than living only in headline-count math.
    Best-effort: omits ``groups``/``exclude_groups`` (already shown via the
    POI tabs) and never raises on an odd/legacy spec shape.
    """
    if not spec:
        return []
    if spec.get("any_of"):
        branches = [" + ".join(describe_audience_filter(c)) or "any" for c in spec["any_of"]]
        return [" OR ".join(branches)] if branches else []

    chips: list[str] = []
    if spec.get("min_visits"):
        chips.append(f"{spec['min_visits']}+ visits")
    if spec.get("window_days"):
        chips.append(f"last {spec['window_days']}d")
    days = spec.get("days_of_week")
    if days:
        dset = sorted(set(int(d) for d in days if 0 <= int(d) <= 6))
        if dset == [5, 6]:
            chips.append("weekends")
        elif dset == [0, 1, 2, 3, 4]:
            chips.append("weekdays")
        elif dset:
            chips.append("/".join(_DAY_ABBR[d] for d in dset))
    hours = spec.get("hours")
    if hours and len(hours) == 2:
        chips.append(f"{hours[0]}:00–{hours[1]}:00")
    if spec.get("min_dwell_min"):
        chips.append(f"{spec['min_dwell_min']}+ min on-site")
    if spec.get("min_weekly_hours"):
        chips.append(f"{spec['min_weekly_hours']:g}+ hrs/week")
    if spec.get("min_distinct_pois"):
        chips.append(f"{spec['min_distinct_pois']}+ locations")
    if spec.get("min_distinct_groups"):
        chips.append(f"any {spec['min_distinct_groups']}+ of these groups")
    if spec.get("min_visits_per_group"):
        chips.append(f"{spec['min_visits_per_group']}+ visits each")
    if spec.get("min_share_in_scope"):
        chips.append(f"{round(float(spec['min_share_in_scope']) * 100)}%+ of visits")
    if spec.get("min_open_day_share"):
        chips.append(f"{round(float(spec['min_open_day_share']) * 100)}%+ of open days")
    if spec.get("min_intraday_span_min"):
        chips.append(f"{spec['min_intraday_span_min']}+ min span/day")
    if spec.get("min_days_present"):
        chips.append(f"{spec['min_days_present']}+ days present")
    if spec.get("min_confidence") == "confirmed":
        chips.append("high-confidence visits")
    if spec.get("trend") == "started":
        chips.append("just started")
    elif spec.get("trend") == "lapsed":
        chips.append("lapsed / win-back")
    if spec.get("cadence_days"):
        chips.append(f"every ~{spec['cadence_days']}d")
    if spec.get("op") == "intersection":
        chips.append("all groups")
    elif spec.get("op") == "difference":
        chips.append("first group only")
    if spec.get("exclude_groups"):
        # State the real window rather than a bare "excluding some spots" —
        # `exclude_window_days` never widens the history purchase (see
        # `maid_history._clause_history_days`), so "excluding people who've
        # EVER been" (exclude_window_days=0) is only ever true within the
        # days actually bought, and the chip must not overclaim "never".
        _excl_window = spec.get("exclude_window_days")
        if _excl_window == 0:
            chips.append("excluding past visitors (within data bought)")
        elif _excl_window:
            chips.append(f"excluding visitors from the last {_excl_window}d")
        elif spec.get("window_days"):
            chips.append(f"excluding visitors from the last {spec['window_days']}d")
        else:
            chips.append("excluding past visitors")
    if spec.get("_unresolved_groups"):
        chips.extend(f"{g}: not found" for g in spec["_unresolved_groups"])
    if spec.get("_unresolved_exclude_groups"):
        chips.extend(f"{g}: exclusion not applied" for g in spec["_unresolved_exclude_groups"])

    if spec.get("invert"):
        return (["excluding:"] + chips) if chips else ["excluded"]
    return chips


def fold_audience_filter_specs(specs: list[dict]) -> dict:
    """Fold an ORDERED list of RESOLVED audience-filter patches (each already
    ran through `resolve_group_labels` for its `groups`/`exclude_groups`) into
    the one merged filter to evaluate — the exact merge algebra
    `_apply_maid_audience_filter_edit` (builder_node.py) always used, pulled
    out here so it is pure and directly testable. It previously lived inline
    and was completely untested, including the sharpest edge: `any_of`
    replaces the WHOLE filter rather than merging into it.

    Same reasoning as `poi_selection.apply_specs` folding from the ORIGINAL
    superset every time rather than the previous result: the caller persists
    `specs` (`bs["_audience_filter_specs"]`), not the merged output, so
    "3+ visits" then "actually just 1+" replays as the full patch history
    from empty and correctly ends up at `min_visits: 1` — a shallow merge
    of only the LATEST patch onto a stale merged dict could not express that
    kind of correction cleanly, and gave `undo()` nothing to replay from.

    Rules, in order applied:
      - a patch introducing `any_of` REPLACES the whole filter — there is no
        sane way to merge "the 2nd OR-branch" from a flat later patch, and
        `any_of` can't coexist with flat fields on the same filter object.
      - once the filter IS an `any_of`, a later flat patch has no single
        clause to land on, so it starts a FRESH flat filter rather than
        guessing which branch to patch.
      - otherwise: shallow merge, key-by-key, patch overwrites; a key set to
        `None` in the patch CLEARS it (this is how "actually, no visit
        minimum" widens the filter back out).
    """
    merged: dict = {}
    for patch in specs:
        patch = dict(patch)
        patch.pop("unsupported", None)  # not a filter key — see AudienceFilterReport
        if "any_of" in patch:
            merged = {"any_of": patch["any_of"]} if patch["any_of"] is not None else {}
        elif merged.get("any_of"):
            merged = {k: v for k, v in patch.items() if v is not None}
        else:
            for k, v in patch.items():
                if v is None:
                    merged.pop(k, None)
                else:
                    merged[k] = v
        # A sidecar is meaningless without its owner. "Drop the trend" clears
        # `trend` alone, and the windows left behind would silently re-attach to
        # the next "lapsed" someone asks for.
        if not merged.get("any_of"):
            if not merged.get("trend"):
                merged.pop("trend_recent_days", None)
                merged.pop("trend_prior_days", None)
            if not merged.get("cadence_days"):
                merged.pop("cadence_tolerance_days", None)
    if specs:
        # Marks the groups/exclude_groups on `merged` as already-resolved
        # poi_group_id values (the caller resolved each patch before folding)
        # — see the flag's other setter, executors/maid.py, for why a
        # re-resolve against a possibly-different POI set would be wrong.
        merged["_resolved"] = True
    return merged


@dataclass
class AudienceFilterReport:
    """What one audience-filter edit actually did — mirrors
    `poi_selection.ExecutionReport`'s job: the fact base `beats.record_change`
    / the outcome beat draw from, so the composer can only ever claim what
    `applied` reports."""

    filter: dict = field(default_factory=dict)
    before_count: int = 0
    after_count: int = 0
    applied: list[str] = field(default_factory=list)
    deviations: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)


def _label_words(s: str) -> set[str]:
    """Lowercase alphanumeric tokens of a label/group key, for whole-word
    containment — never a bare substring test (see ``resolve_group_labels_verbose``)."""
    return set(re.findall(r"[a-z0-9]+", s.lower()))


# A possessive self-reference to the user's OWN business ("my store", "our
# shops", "one of my locations") — matched only as a LAST RESORT in
# ``resolve_group_labels_verbose``, after a real venue could have claimed the
# label by name. Deliberately narrow: requires my/our + a business-premises
# noun, so it never catches a bare category ("gyms") or a third-party venue
# named literally "Store" / "The Shop".
_SELF_REFERENCE_RE = re.compile(
    r"^(?:(?:my|our)\s+(?:own\s+)?|one\s+of\s+(?:my|our)\s+)"
    r"(?:stores?|shops?|locations?|business(?:es)?|places?|outlets?|branches?)$"
)


def is_self_reference_label(label: str) -> bool:
    """True for a label like "my store"/"our shops" — the public form of the
    ``_SELF_REFERENCE_RE`` check, for callers outside this module (the
    unresolved-group repair path in ``builder_node.py``) that need to tell
    "this exclude label named the user's own business" apart from "this
    exclude label named some other missing place"."""
    return bool(_SELF_REFERENCE_RE.match(str(label or "").strip().lower()))


def resolve_group_labels_verbose(labels: list[str], pois: list[dict]) -> tuple[list[str], list[str]]:
    """Map loose group labels a user/classifier typed ("gym", "starbucks") to
    the real ``poi_group_id()`` values present in ``pois`` (``"category:gym"``,
    ``"competitor_brand:Starbucks"``) — what ``groups``/``exclude_groups`` in
    an ``AudienceFilter`` actually need to match against ``poi_ids``.

    Case-insensitive; prefers an exact label match, falls back to WHOLE-WORD
    containment either direction ("coffee" -> "coffee shop"; "coffee shop" ->
    "coffee shop chain"). Not a bare substring test: that let "bar" resolve to
    "barbershop" and "gym" resolve to "gymnastics studio" with no exact "bar"/
    "gym" group in scope — silently the WRONG category, not merely a loose
    one, and because it "resolved" to something, `missing` stayed empty and
    the caller's own "group not found" narration never fired.

    A label that matches nothing is DROPPED, never guessed — a group predicate
    that resolves to no groups is a no-op filter, not a silent "match
    everything" — but unlike ``resolve_group_labels`` it is also returned (as
    ``missing``) so a caller can say so out loud instead of narrowing (e.g. an
    "intersection of X and Y" quietly collapsing to just Y when X never
    resolved). A label matching MORE THAN ONE group (e.g. "gym" against both
    "category:gym" and "category:boutique gym") resolves to all of them —
    every consumer already treats `groups`/`exclude_groups` as a list of ids
    to match ANY of, so this is strictly more complete, not a new shape.

    Returns ``(resolved_ids, missing_labels)``.
    """
    from app.graph.builder.executors.geo import group_pois_by_category

    groups = group_pois_by_category(pois)
    known_ids = {g["id"] for g in groups}
    resolved: list[str] = []
    missing: list[str] = []
    for label in labels or []:
        needle = str(label or "").strip().lower()
        if not needle:
            continue
        # An already-resolved group id ("category:gym") is unambiguous — a
        # structured caller (the layer-builder panel) sends these back verbatim.
        if isinstance(label, str) and label in known_ids:
            resolved.append(label)
            continue
        exact = [g for g in groups if g["key"].lower() == needle]
        if exact:
            resolved.extend(g["id"] for g in exact)
            continue
        needle_words = _label_words(needle)
        partial = [
            g for g in groups
            if needle_words and (
                needle_words <= _label_words(g["key"])
                or _label_words(g["key"]) <= needle_words
            )
        ]
        if partial:
            resolved.extend(g["id"] for g in partial)
            continue
        # Last resort, never first: a real venue named "My Place" or "The
        # Shop" already had first crack at this label via the exact/partial
        # passes above. Only a label nothing else claimed falls through to
        # "the user means their own store(s)" — keyed on `source_angle`
        # rather than the display `key` so it survives a relabel of the
        # store_set group (see `executors/geo.py`'s `parent_poi_type` stamp).
        if _SELF_REFERENCE_RE.match(needle):
            own_stores = [g for g in groups if g["source_angle"] == "store_set"]
            if own_stores:
                resolved.extend(g["id"] for g in own_stores)
                continue
        missing.append(label)
    # De-dup, preserving first-seen order: a label matching several groups, or
    # several labels matching the same group, must not double an id in the
    # `groups`/`exclude_groups` list a caller stores.
    seen: set[str] = set()
    return [g for g in resolved if not (g in seen or seen.add(g))], missing


def resolve_group_labels(labels: list[str], pois: list[dict]) -> list[str]:
    """Thin wrapper over ``resolve_group_labels_verbose`` for callers that
    only need the resolved ids, not which labels missed."""
    return resolve_group_labels_verbose(labels, pois)[0]


def resolve_audience_filter_specs(
    specs: list[dict], pois: list[dict],
) -> tuple[dict, int, int]:
    """Resolve every patch's group labels against ``pois`` and fold them into
    the one filter to evaluate. Returns ``(merged, labels_named, labels_matched)``
    — the gap between the last two is how a caller says "a named group didn't
    exist on screen" instead of silently narrowing to nothing.

    The single implementation behind the mid-build edit
    (``builder_node._recompute_audience_filter``) and the read-only layer
    preview, so the two can never resolve a label differently.
    """
    named = matched = 0

    def _resolve_clause(clause: dict) -> dict:
        nonlocal named, matched
        clause = dict(clause)
        for key in ("groups", "exclude_groups"):
            if clause.get(key):
                named += len(clause[key])
                clause[key] = resolve_group_labels(clause[key], pois)
                matched += len(clause[key])
        return clause

    resolved: list[dict] = []
    for raw in specs:
        raw = dict(raw)
        if raw.get("any_of"):
            raw["any_of"] = [_resolve_clause(c) for c in raw["any_of"]]
        else:
            raw = _resolve_clause(raw)
        resolved.append(raw)
    return fold_audience_filter_specs(resolved), named, matched


# The keys the audience layer builder edits — it may SET, CHANGE or CLEAR these.
# Sidecar keys travel with their owner (the trend windows with `trend`, the
# tolerance with `cadence_days`) so the panel never leaves one orphaned.
# Everything else a stored filter carries (role signals, hours, anything added
# later) is NOT the panel's to set: it rides through every preview and commit
# untouched because both are OVERLAYS on the session's effective filter, never a
# rebuild of it. Those keys can only be REMOVED (see `CLEARABLE_FILTER_KEYS`).
# Mirrored by `PANEL_KEYS` in the frontend's `audienceLayers.ts`; a test pins
# the two together.
LAYER_BUILDER_KEYS: frozenset[str] = frozenset({
    "groups", "op", "min_distinct_groups", "exclude_groups", "exclude_window_days",
    "window_days", "min_visits", "min_visits_per_group", "days_of_week",
    "min_dwell_min", "trend", "trend_recent_days", "trend_prior_days",
    "cadence_days", "cadence_tolerance_days",
})


def public_audience_filter(spec: dict | None) -> dict:
    """The user-meaningful part of a stored filter: no ``_``-prefixed internal
    bookkeeping (resolution flags, purchase depth), and nothing at all for the
    system-derived default window (``_derived`` — not something the user chose,
    and kept out of every user-facing surface for that reason)."""
    if not spec or spec.get("_derived"):
        return {}
    return {k: v for k, v in spec.items() if not str(k).startswith("_")}


def overlay_audience_filter(
    base: dict | None, patches: list[dict], pois: list[dict],
) -> tuple[dict, int, int]:
    """``base`` (a session's effective filter) with ``patches`` applied on top —
    ``(merged, labels_named, labels_matched)``.

    The ONE function both the layer builder's preview and its commit go through,
    so what the panel shows and what Apply produces cannot diverge: same base,
    same fold, same resolver. Keys the patches don't mention come from ``base``.
    """
    seed = public_audience_filter(base)
    return resolve_audience_filter_specs(([seed] if seed else []) + list(patches), pois)


def reconcile_audience_history(
    history: list[dict], effective: dict | None, pois: list[dict],
) -> list[dict]:
    """A patch history that reproduces ``effective`` — the filter the audience
    actually carries (what publish reads) — safe to append a new patch to.

    The history is what an edit is folded from, but it only records EDITS. A
    filter stated in the user's first message is applied at extraction and never
    enters it, so folding ``[first_edit]`` from empty silently erased that
    original filter. When the history already reproduces the effective filter
    it is returned unchanged (undo keeps its granularity); when it does not, it
    is rebased to a single spec holding the effective filter. A false mismatch
    therefore costs only undo granularity, never correctness.
    """
    base = public_audience_filter(effective)
    folded = (
        public_audience_filter(resolve_audience_filter_specs(history, pois)[0]) if history else {}
    )
    same = json.dumps(folded, sort_keys=True, default=str) == json.dumps(base, sort_keys=True, default=str)
    if same:
        return list(history)
    return [base] if base else []


# Below this a custom audience still uploads and Meta still serves it, but reach
# is thin enough to warn about (a soft floor, not a block). The one definition:
# `executors/media.py` imports it as `_MIN_META_AUDIENCE` for its publish-time
# warning, and the layer builder's preview uses it to say "too few to run well".
MIN_DELIVERABLE_AUDIENCE = 1000

# Layers one preview call will evaluate. Each is a full pass over the stored
# rows on the event loop, so this is a cost cap, not a product limit.
MAX_PREVIEW_LAYERS = 8


def preview_audience_layers(
    observations: list[dict],
    pois: list[dict],
    layers: list[dict],
    *,
    base: dict | None = None,
    history_days_bought: int | None = None,
) -> list[dict]:
    """Evaluate each layer over the persisted rows and return what it would
    leave — read-only, no vendor call, nothing written.

    ``layers`` is ``[{"label": str, "patches": [patch, ...]}]``. Each layer's
    patches are OVERLAID on ``base`` (the session's effective filter, via
    ``overlay_audience_filter``) — the same overlay a commit applies — so a
    layer's count is exactly what committing it would headline, including every
    key the panel does not edit. The count goes through ``attribute_audience``
    like every other user-facing audience number.

    A layer the evaluator refuses (``AudienceFilterUnevaluable``) reports
    ``count: None`` with the reason, rather than a confident zero.

    ponytail: one full evaluation per layer on the calling thread (the witness
    side-channels forbid a worker thread); ``MAX_PREVIEW_LAYERS`` bounds it.
    """
    from app.graph.maid_query import attribute_audience

    out: list[dict] = []
    for layer in layers[:MAX_PREVIEW_LAYERS]:
        merged, named, matched = overlay_audience_filter(base, layer.get("patches") or [], pois)
        if history_days_bought:
            merged["_history_days_bought"] = history_days_bought
        entry: dict = {
            "label": layer.get("label") or "",
            "filter": {k: v for k, v in merged.items() if not str(k).startswith("_")},
            "chips": describe_audience_filter(merged),
            "count": None,
            "deviations": [],
            "unevaluable": None,
        }
        if named and matched < named:
            miss = named - matched
            entry["deviations"].append(
                f"{miss} named group{'s' if miss != 1 else ''} didn't match any category on screen"
            )
        try:
            keep = set(apply_audience_filter(observations, merged, pois=pois))
        except AudienceFilterUnevaluable as exc:
            entry["unevaluable"] = str(exc)
            out.append(entry)
            continue
        kept_rows = [o for o in observations if o.get("maid") in keep]
        entry["count"], _ = attribute_audience(kept_rows, pois, stamp_stats=False)
        out.append(entry)
    return out


def scope_exclusion_to_named_groups(clause: dict, pois: list[dict]) -> dict:
    """When a clause names ``exclude_groups`` but leaves ``groups`` unset,
    pin ``groups`` to every OTHER group in the pool.

    ``_apply_clause`` treats an unset/empty ``groups`` as "match every device
    in the pool" (see its docstring), so a POI collected ONLY to be excluded —
    the user's own store, added so "my store" resolves at all — would
    otherwise also count as a POSITIVE targeting source: its visitors would
    be pulled into the audience before being subtracted back out, and its
    visits would inflate ``min_visits``/``min_distinct_pois`` (which silently
    ignore ``min_visits_per_group`` entirely while ``groups`` is empty).

    Only fires for the default ``union`` op (or when ``op`` is absent, which
    means union). An ``intersection``/``difference`` with no ``groups`` is a
    malformed spec that already degrades to union in ``_apply_clause`` — this
    function must not paper over that by inventing a real intersection across
    every group in the pool, which would almost certainly match nobody.

    Callers pass already-RESOLVED ``exclude_groups`` (real ``poi_group_id()``
    values, not loose labels) — resolution must happen first. A no-op (spec
    already has ``groups``, or no pool to scope against) returns ``clause``
    unchanged.
    """
    if not clause.get("exclude_groups") or clause.get("groups"):
        return clause
    if clause.get("op") not in (None, "union"):
        return clause
    from app.graph.builder.executors.geo import group_pois_by_category

    excluded = set(clause["exclude_groups"])
    positive = [g["id"] for g in group_pois_by_category(pois) if g["id"] not in excluded]
    if not positive:
        return clause
    return {**clause, "groups": positive}


# Every key `_apply_clause` (or its callers) actually reads, plus the
# underscore-prefixed internal ones the pipeline itself stamps (`_resolved`,
# `_unresolved_groups`, `_history_days_bought` — see the field comment above
# `AudienceFilter`). A key extracted by the LLM but not in this set has NO
# producer anywhere: it silently does nothing, and nothing before this warned
# that it was ignored rather than applied.
_KNOWN_FILTER_KEYS: frozenset[str] = frozenset({
    "groups", "op", "exclude_groups", "window_days", "min_visits",
    "min_distinct_pois", "min_distinct_groups", "days_of_week", "hours", "min_dwell_min",
    "min_weekly_hours", "trend", "cadence_days", "cadence_tolerance_days",
    "any_of", "invert", "min_visits_per_group", "min_share_in_scope",
    "min_confidence", "exclude_window_days", "trend_recent_days",
    "trend_prior_days", "exclude_flags", "dwell_bound",
    "min_open_day_share", "min_intraday_span_min", "min_days_present",
    "_resolved", "_unresolved_groups", "_unresolved_exclude_groups",
    "_partial_exclude_groups", "_partial_groups", "_history_days_bought",
})


# What the layer builder panel may REMOVE: any user-facing filter key. It may
# only SET the ones in ``LAYER_BUILDER_KEYS`` — a removal needs no value, so it
# cannot smuggle one in, and it is how the panel drops a setting it shows as a
# chip but has no control for. ``any_of`` is excluded (it replaces the whole
# filter, which is not a removal) and so is every ``_`` internal.
CLEARABLE_FILTER_KEYS: frozenset[str] = frozenset(
    k for k in _KNOWN_FILTER_KEYS if not k.startswith("_") and k != "any_of"
)

# Chip text for carried keys ``describe_audience_filter`` has no chip for (or
# words badly when the key stands alone). Every carried key MUST read as
# something — a setting in force that the user cannot see cannot be removed.
_CARRIED_LABELS: dict[str, str] = {
    "invert": "flipped — excludes the people who match",
    "exclude_flags": "low-quality visits ignored",
}


def carried_filter_parts(spec: dict | None) -> list[dict]:
    """The settings in force on ``spec`` that the layer builder does not edit,
    one ``{"key", "label"}`` per key, in the filter's own order.

    They are in every count the panel shows, so the panel lists them; each is
    one key so "remove" means exactly that key (``CLEARABLE_FILTER_KEYS``). A key
    nothing can evaluate (``_KNOWN_FILTER_KEYS`` doesn't list it) is skipped —
    it does nothing, and the panel could not clear it.
    """
    parts: list[dict] = []
    for key, value in public_audience_filter(spec).items():
        if key in LAYER_BUILDER_KEYS or key not in CLEARABLE_FILTER_KEYS:
            continue
        if key == "dwell_bound":
            label = f"dwell counted at its {value} bound"
        else:
            label = _CARRIED_LABELS.get(key) or " · ".join(describe_audience_filter({key: value}))
        parts.append({"key": key, "label": label or key.replace("_", " ")})
    return parts


def unknown_filter_keys(spec: dict | None) -> list[str]:
    """Keys on ``spec`` (or, for an ``any_of``, any of its clauses) that
    ``_apply_clause`` has no producer for — sorted, deduped, empty when clean.

    Public (not underscore-prefixed): ``executors/maid.py`` calls this a
    second time to stamp ``maid_funnel["unknown_filter_keys"]`` — the spec is
    already in scope there, so no side-channel is needed, unlike
    ``_TRUNCATED_FEATURES``'s problem shape where the fact is discovered
    inside a call the caller cannot re-run cheaply.
    """
    if not spec:
        return []
    clauses = spec.get("any_of") or [spec]
    unknown: set[str] = set()
    for clause in clauses:
        unknown |= set((clause or {}).keys()) - _KNOWN_FILTER_KEYS
    return sorted(unknown)


# An N-way intersection silently requires PAIRWISE NON-OVERLAPPING witness
# visits (see `_has_disjoint_witnesses`'s docstring below) — correct, but a
# user asking for "vet AND PetSmart AND dog park in 45 days" has no way to know
# a same-afternoon vet+PetSmart trip does not count. `apply_audience_filter`
# has no return-shape room for this (its `list[str]` is depended on by every
# caller), so it's a side-channel like `_TRUNCATED_FEATURES` in
# unacast_query.py: written during the synchronous call, read by the caller
# immediately after — no `await` happens between the two, so no other asyncio
# task's code can interleave and race it, same as that module's pattern.
# `apply_audience_filter` resets it at the top of every call.
_INTERSECTION_WITNESS_STATS: dict[str, int] = {"intersection_raw": 0, "intersection_after_witness_test": 0}


def intersection_witness_stats() -> dict[str, int]:
    """Snapshot of the last ``apply_audience_filter`` call's intersection
    witness-test counts. Zero/zero when the spec had no intersection clause —
    not None, so a caller can always render it without a null check."""
    return dict(_INTERSECTION_WITNESS_STATS)


# Same side-channel pattern as _INTERSECTION_WITNESS_STATS above: written
# during the synchronous apply_audience_filter call, read by the caller
# immediately after — no `await` between the two, so nothing else can race it.
# `apply_audience_filter` resets it at the top of every call. The MAX across
# any_of branches, not a sum: it answers "how much operating-day evidence did
# the widest-evidenced branch have", not a double-count of the same days seen
# from two clauses.
_ROLE_SIGNAL_STATS: dict[str, int] = {"open_days_observed": 0}


def role_signal_stats() -> dict[str, int]:
    """Snapshot of the last ``apply_audience_filter`` call's role-signal
    evidence — currently just ``open_days_observed``, the distinct local days
    any device was seen at the clause's in-scope POIs, for whichever
    role-signal field (presence-pattern or ``min_weekly_hours``) was active.
    Zero when no role-signal field was in the spec at all."""
    return dict(_ROLE_SIGNAL_STATS)


def apply_audience_filter(
    observations: list[dict],
    spec: dict | None,
    pois: list[dict] | None = None,
    *,
    group_status: dict | None = None,
) -> list[str]:
    """Evaluate an ``AudienceFilter`` spec over persisted observation rows.

    Dispatches on ``any_of``: present -> union of ``_apply_clause`` over each
    entry (2-level DNF — see the ``AudienceFilter`` comment above); absent ->
    ``spec`` itself is evaluated as a single clause, exactly as before
    ``any_of`` existed. Every one of the 43 prompts that don't need `any_of`
    take this second path unchanged.

    ``pois`` (optional) locates the audience for the ``days_of_week``/``hours``
    predicates, which are stated in local time — see ``_tz_offset_hours``.
    Omitting it evaluates those predicates in UTC (fine for tests fixed to a
    known UTC time; every real caller passes the extraction's POIs).

    Pure function, no DB access — a thin async wrapper persists the result
    (see ``builder_node``'s maid-edit recompute path). Returns a sorted list
    of matching MAIDs.
    """
    _INTERSECTION_WITNESS_STATS["intersection_raw"] = 0
    _INTERSECTION_WITNESS_STATS["intersection_after_witness_test"] = 0
    _ROLE_SIGNAL_STATS["open_days_observed"] = 0
    _unknown = unknown_filter_keys(spec)
    if _unknown:
        # Log-only: an LLM-hallucinated key (`min_dwell_minutes` instead of
        # `min_dwell_min`) used to be silently ignored — the filter just did
        # less than asked, with no signal anywhere. Not raised: a spec this
        # pipeline builds itself (`_history_days_bought`, etc.) must keep
        # evaluating even if a future field is added to one side before the
        # other — see `unknown_filter_keys` for where the funnel gets this too.
        logger.warning(
            "MAID: audience_filter has unrecognized key(s) %s — ignored, filter "
            "runs without them", _unknown,
        )
    assert_filter_evaluable(observations, spec, group_status=group_status)
    if spec and spec.get("any_of"):
        result: set[str] = set()
        for clause in spec["any_of"]:
            result |= set(_apply_clause(observations, clause, pois=pois))
        return sorted(result)
    return _apply_clause(observations, spec, pois=pois)


class AudienceFilterUnevaluable(Exception):
    """The extraction does not contain the history this filter needs.

    Raised INSTEAD of returning a set, because the two failure shapes a caller
    would otherwise see are both confident lies:

      * ``trend: "started"`` means "visited recently, and NOT before". If the
        prior window was never bought, no device can have a prior visit, so the
        predicate matches EVERY device with a recent visit.
      * ``trend: "lapsed"`` means the reverse and matches NOBODY, ever.

    Neither is distinguishable from a real answer at the call site. A predicate
    that cannot be evaluated must fail loudly. See app/graph/maid_history.py for
    the sizing rule that prevents this happening on a fresh extraction.
    """

    def __init__(self, message: str, *, needed_days: int = 0, have_days: int = 0):
        super().__init__(message)
        self.needed_days = needed_days
        self.have_days = have_days


def _visit_intervals(row: dict) -> list[tuple[datetime, datetime]]:
    """(start, end) for every visit on a row, skipping unparseable timestamps."""
    out: list[tuple[datetime, datetime]] = []
    for v in row.get("visits") or []:
        ts = v.get("ts")
        if not ts:
            continue
        try:
            start = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            continue
        span = int(v.get("dwell_lower_s") or 0)
        out.append((start, start + timedelta(seconds=max(0, span))))
    return out


def _has_disjoint_witnesses(
    maid: str,
    per_group_rows: list[list[dict]],
    window,
    need: int | None = None,
) -> bool:
    """Can this device's visits supply ONE witness per group, no two overlapping
    in time?

    The question an intersection is really asking is "did this device visit all
    N kinds of place", and a device cannot be in two places at once. Overlapping
    geofences return one physical presence under several features, which is what
    this rejects.

    ``need`` is how many of the groups must be seated: ``None`` = all of them
    (an intersection), ``N`` = "any N of these" (``min_distinct_groups``). One
    search serves both, so the two operators cannot disagree on the same rows.
    """
    per_group = [
        [
            iv
            for row in rows if row.get("maid") == maid
            for iv in _visit_intervals(row)
            if window(iv[0])
        ]
        for rows in per_group_rows
    ]
    return _seat_groups(per_group, len(per_group) if need is None else need)


# Nodes the witness search may expand for ONE device before giving up. A
# device has a handful of visits per group, so real inputs finish in a few
# dozen nodes; the cap only exists so a pathological one cannot stall a request.
_WITNESS_SEARCH_BUDGET = 20_000


def _seat_groups(per_group: list[list[tuple[datetime, datetime]]], need: int) -> bool:
    """True when at least ``need`` of the groups can each be given ONE witness
    interval, no two of the chosen intervals overlapping in time.

    Two intervals conflict when they share ANY instant — touching counts.
    A single-ping visit is a zero-length interval ``(t, t)``, and one physical
    ping returned under two overlapping geofences carries the SAME ``t`` on
    both; an "ends at or before the other starts" test called those disjoint
    and credited one presence to two groups, which is the failure this exists
    to stop.

    Exact backtracking (choosing which groups to seat is a job-interval
    selection problem, so a greedy pass can wrongly reject). Groups with no
    witness at all can never be seated; the most constrained go first.
    ``need == len(per_group)`` collapses to the all-groups intersection test
    because the skip branch is pruned at once.

    ponytail: exponential in groups, bounded by ``_WITNESS_SEARCH_BUDGET``;
    an exhausted budget answers False (drops a device, never admits one).
    Upgrade to a real matching only if devices with many visits per group
    show up.
    """
    if need <= 0:
        return True
    seatable = sorted((sorted(set(ivs), key=lambda iv: iv[1]) for ivs in per_group if ivs), key=len)
    if len(seatable) < need:
        return False

    chosen: list[tuple[datetime, datetime]] = []
    steps = 0

    def go(i: int, seated: int) -> bool:
        nonlocal steps
        if seated >= need:
            return True
        steps += 1
        if steps > _WITNESS_SEARCH_BUDGET or seated + (len(seatable) - i) < need:
            return False
        for iv in seatable[i]:
            if all(iv[1] < c[0] or iv[0] > c[1] for c in chosen):
                chosen.append(iv)
                ok = go(i + 1, seated + 1)
                chosen.pop()
                if ok:
                    return True
        return go(i + 1, seated)

    return go(0, 0)


def _hour_in_range(hour: int, hours: list) -> bool:
    """``hours`` is ``[lo, hi)`` in local time, and MAY WRAP MIDNIGHT.

    "Friday night" is ``[22, 2]``, which is not ``22 <= h < 2`` — that is empty
    for every hour, so an overnight range silently matched nobody. A wrapped
    range means "at or after lo, OR before hi".
    """
    if not hours or len(hours) != 2:
        return True
    lo, hi = int(hours[0]), int(hours[1])
    if lo < hi:
        return lo <= hour < hi
    if lo == hi:
        return True          # a full-day range, not an empty one
    return hour >= lo or hour < hi


def _observed_span_days(visits: list[tuple]) -> int:
    """Days between a device's first and last visit — the honest denominator
    when nothing else says how wide the analysed window was."""
    if not visits:
        return 0
    times = [v[0] for v in visits]
    return max(1, (max(times) - min(times)).days)


def _oldest_visit(observations: list[dict]) -> datetime | None:
    oldest: datetime | None = None
    for row in observations or []:
        for visit in row.get("visits") or []:
            ts = visit.get("ts")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except ValueError:
                continue
            if oldest is None or dt < oldest:
                oldest = dt
    return oldest


def _trend_windows(spec: dict) -> tuple[int, int]:
    """``(recent_days, prior_days)`` for a trend clause.

    Explicit asymmetric windows win when both are given — "suddenly started
    after never going before" wants a SHORT recent window and a LONG prior one,
    which the symmetric default cannot express.
    """
    window = int(spec.get("window_days") or 0) or _DEFAULT_TREND_WINDOW_DAYS
    recent = int(spec.get("trend_recent_days") or 0) or window
    prior = int(spec.get("trend_prior_days") or 0) or recent
    return recent, prior


def _assert_groups_fetched(spec: dict | None, group_status: dict | None) -> None:
    """Refuse a filter that leans on a group whose query FAILED.

    Two distinct sharp cases, both "plausible but false":

    1. **intersection/difference over a named group that FAILED.** If one
       side fetched nothing because the call errored, its device set is
       empty, the intersection is empty, and the user is told nobody
       qualifies across those places — a confident answer to a question we
       never actually asked the vendor. A group that fetched successfully
       and genuinely returned nobody is a REAL finding and passes through
       untouched; only "failed" raises here.

       A "partial" group — some of its POI keys split/truncated under the
       vendor's per-feature observation cap, but real rows came back — is
       deliberately NOT raised here, same asymmetry as the exclude_groups
       case below: a big-city category search is "partial" essentially by
       DEFAULT (see CLAUDE.md's 100k-observations-per-feature note), so
       treating it as unevaluable made every real-world market-scale
       intersection (SneakerCon+Flight Club in NYC, vet+PetSmart+dog park in
       Denver) silently collapse to the full unfiltered union with no
       narration the user was likely to see. The intersection still finds
       real matches from the data that DID come back — an honest undercount,
       not a confident lie — and the caller (`executors/maid.py`) narrates
       the partial coverage instead of failing hard, mirroring how it already
       handles a partial exclude group.

    2. **a FAILED exclude_groups member, under ANY op (including the default
       union).** A union degrades honestly for a POSITIVE group (a smaller
       audience) and needs no guard. A failed EXCLUDE group is the opposite
       of honest: "nobody visited my store" (because the query errored, not
       because it's true) means nobody gets excluded — ads ship to exactly
       the people the user asked to leave out. A "partial" exclude group is
       NOT raised here either — nulling the whole filter over a
       partially-fetched exclusion is a worse outcome than a slightly leaky
       one; the caller (`executors/maid.py`) narrates that case instead of
       failing hard.
    """
    if not spec or not group_status:
        return
    for clause in (spec.get("any_of") or [spec]):
        if not clause:
            continue
        op = clause.get("op")
        groups = list(clause.get("groups") or [])
        exclude_groups = list(clause.get("exclude_groups") or [])
        # "At least N of these groups" (`min_distinct_groups`) is the same
        # question as an intersection with a weaker threshold: a group that
        # fetched nothing because the call errored silently lowers everyone's
        # count. Only NAMED groups are checked — with `groups` empty the
        # candidates are the whole build and it degrades like a union does.
        if op in ("intersection", "difference") or (groups and clause.get("min_distinct_groups")):
            named = groups + exclude_groups
            broken = [
                g for g in named
                if (group_status.get(g) or {}).get("status") == "failed"
            ]
            if broken:
                raise AudienceFilterUnevaluable(
                    "I couldn't pull the visitor data for "
                    f"{', '.join(g.split(':', 1)[-1] for g in broken)}, so I can't "
                    f"answer a '{op or 'at-least-N-of'}' across those places yet — the "
                    f"result would look like nobody qualified when really one side "
                    f"is missing. Worth retrying, or drop it from the filter."
                )
            continue
        failed_excludes = [
            g for g in exclude_groups
            if (group_status.get(g) or {}).get("status") == "failed"
        ]
        if failed_excludes:
            raise AudienceFilterUnevaluable(
                "I couldn't pull the visitor data for "
                f"{', '.join(g.split(':', 1)[-1] for g in failed_excludes)}, so I can't "
                "confirm who to exclude — showing everyone who matched instead of "
                "risking ads to the people you asked me to leave out."
            )


def assert_filter_evaluable(
    observations: list[dict],
    spec: dict | None,
    *,
    history_days_bought: int | None = None,
    group_status: dict | None = None,
) -> None:
    """Raise ``AudienceFilterUnevaluable`` if ``spec`` needs history this
    extraction never bought.

    Two signals, preferring the reliable one. ``history_days_bought`` (stamped
    on the filter by the extraction) says exactly what was purchased. Without it
    — a legacy extraction — fall back to the data: if a ``trend`` clause's prior
    window contains no observation at all, it cannot be evaluated.

    The data-derived fallback is deliberately conservative. A genuinely quiet
    POI can have no old visits by chance, and refusing to answer then would be
    its own kind of wrong; so it only fires when the ENTIRE dataset stops short
    of the prior window, which is a property of the purchase, not the POI.
    """
    if not spec:
        return

    _assert_groups_fetched(spec, group_status)

    clauses = spec.get("any_of") or [spec]
    trend_clauses = [c for c in clauses if c and c.get("trend")]
    # A cadence needs several on-cadence gaps to observe, so it depends on the
    # purchased span exactly as a trend does. Over too short a purchase it does
    # not fail — it just finds nobody, which reads as a real "no one repeats".
    cadence_clauses = [c for c in clauses if c and c.get("cadence_days")]
    if not trend_clauses and not cadence_clauses:
        return

    bought = history_days_bought
    if bought is None:
        bought = spec.get("_history_days_bought")
    if bought is not None:
        from app.graph.maid_history import history_shortfall

        shortfall = history_shortfall(spec, int(bought))
        if shortfall:
            needed = int(bought) + shortfall
            what = "a visit trend" if trend_clauses else "a repeating visit pattern"
            raise AudienceFilterUnevaluable(
                f"this audience covers {int(bought)} day(s) of history but the filter "
                f"needs {needed} to judge {what}",
                needed_days=needed, have_days=int(bought),
            )
        return

    if not trend_clauses:
        return  # legacy row with no stamp: only a trend has a data-derived check

    oldest = _oldest_visit(observations)
    if oldest is None:
        return  # no visit data at all — a different failure, handled downstream

    now = datetime.now(timezone.utc)
    for clause in trend_clauses:
        recent, _prior = _trend_windows(clause)
        if oldest >= now - timedelta(days=recent):
            span = max(0, (now - oldest).days)
            raise AudienceFilterUnevaluable(
                f"judging a visit trend needs history from before the last "
                f"{recent} day(s), but this audience only goes back {span}",
                needed_days=recent * 2, have_days=span,
            )


def _apply_clause(
    observations: list[dict],
    spec: dict | None,
    *,
    pois: list[dict] | None = None,
) -> list[str]:
    """Evaluate ONE flat ``AudienceFilter`` clause (no ``any_of``) over
    persisted observation rows.

    ``observations`` are the full attributed rows persisted by
    ``store_maid_extraction`` — ``{lat, lng, maid, count, visits, days,
    poi_key, poi_ids, poi_uids}``. ``poi_ids`` = category/brand group(s);
    ``poi_uids`` = individual place(s) — what ``min_distinct_pois`` below
    actually counts. ``visits`` (from ``maid_query.cluster_visits``) is what the
    time-based predicates (``window_days``, ``days_of_week``, ``hours``,
    ``min_dwell_min``, ``min_weekly_hours``, ``trend``, ``cadence_days``)
    evaluate against.

    ``pois`` locates the audience for ``days_of_week``/``hours``, which are
    stated in local time (see ``_local_shift``); without it those two predicates
    are evaluated in UTC. Every other predicate is duration-based and needs no
    shift.

    ``invert`` (on ``spec``) flips a SELECT into an EXCLUDE over the same
    otherwise-eligible pool ("drop the staff" = the ``min_weekly_hours``
    clause that would select them, plus ``invert: true``) — every other
    predicate stays a plain minimum/membership test.
    """
    if not spec:
        return sorted({o["maid"] for o in observations if o.get("maid")})

    groups: list[str] = spec.get("groups") or []
    op = spec.get("op") or "union"
    exclude_groups = set(spec.get("exclude_groups") or [])

    def _hits(row: dict, gset) -> bool:
        ids = row.get("poi_ids") or []
        return any(g in ids for g in gset)

    rows_in_scope = [o for o in observations if not groups or _hits(o, groups)]

    # Time-predicate params, parsed up front (used to be parsed after
    # `eligible` was already decided) so GROUP MEMBERSHIP — not just the
    # final per-device frequency count below — can be scoped to the window
    # the user actually stated. Without this, "vet clinic AND PetSmart AND
    # dog park, all within the last 45 days" evaluated as "all three ever,
    # AND at least one visit somewhere in 45 days" — a device with a
    # 170-day-old vet visit and a yesterday dog-park visit passed.
    window_days = spec.get("window_days")
    days_of_week = spec.get("days_of_week")
    hours = spec.get("hours")
    min_dwell = spec.get("min_dwell_min")
    dwell_bound = spec.get("dwell_bound") or "lower"
    min_visits = spec.get("min_visits")
    min_distinct_pois = spec.get("min_distinct_pois")
    min_distinct_groups = spec.get("min_distinct_groups")
    min_weekly_hours = spec.get("min_weekly_hours")
    min_visits_per_group = spec.get("min_visits_per_group")
    min_share_in_scope = spec.get("min_share_in_scope")
    min_confidence = spec.get("min_confidence")
    exclude_window_days = spec.get("exclude_window_days")
    exclude_flags = spec.get("exclude_flags")
    trend = spec.get("trend")
    cadence_days = spec.get("cadence_days")
    cadence_tolerance = spec.get("cadence_tolerance_days")
    min_open_day_share = spec.get("min_open_day_share")
    min_intraday_span_min = spec.get("min_intraday_span_min")
    min_days_present = spec.get("min_days_present")

    time_predicate_active = bool(
        window_days or days_of_week or hours or min_dwell or min_weekly_hours
        or trend or cadence_days
        or min_open_day_share or min_intraday_span_min or min_days_present
    )
    now = datetime.now(timezone.utc)
    # `trend` and a recency `cutoff` are contradictory when combined naively:
    # "lapsed" MEANS no recent visit, so a hard cutoff requiring one would
    # exclude every match. `trend`'s own two-window compare already encodes
    # the relevant recency — window_days there sizes the two windows, not an
    # additional "must have visited recently" requirement on top.
    cutoff = now - timedelta(days=window_days) if (window_days and not trend) else None
    trend_w = timedelta(days=(window_days or _DEFAULT_TREND_WINDOW_DAYS))

    def _local(dt: datetime) -> datetime:
        """A stored UTC timestamp in the POI set's real local time (the true
        IANA zone, so DST is handled), or UTC when no POIs were given."""
        return _local_shift(dt, pois) if pois else dt

    # Recency/day/hour/dwell narrow WHICH VISIT counts; trend/cadence compare
    # shapes over the device's full history by design (see their own blocks
    # below) and must not also gate group membership — a "lapsed" device is
    # defined by having NO recent visit, so scoping membership to "recent"
    # would make it impossible to ever match.
    _membership_scoped = bool(
        cutoff is not None or days_of_week or hours or min_dwell is not None
        or min_confidence or exclude_flags
    )

    _dow_set = set(days_of_week) if days_of_week else None

    def _visit_qualifies(visit: dict, started_at: datetime | None = None) -> bool:
        """Does ONE visit fall inside this clause's scope?

        The single implementation of the recency / day-of-week / hour / dwell /
        confidence / flag tests. It used to exist twice — once per row for group
        membership, once per device for frequency scoping — with the two copies
        drifting apart in exactly the ways that produce a wrong count nobody can
        see: one gained the dwell-measurability gate, the other the confidence
        gate.

        ``started_at`` lets the per-device pass, which has already parsed the
        timestamp, skip re-parsing it.
        """
        if started_at is None:
            ts = visit.get("ts")
            if not ts:
                return False
            try:
                started_at = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except ValueError:
                return False
        if cutoff is not None and started_at < cutoff:
            return False
        if _dow_set is not None and _local(started_at).weekday() not in _dow_set:
            return False
        if hours and not _hour_in_range(_local(started_at).hour, hours):
            return False
        if min_dwell is not None and not _dwell_at_least(visit, min_dwell, bound=dwell_bound):
            return False
        # `is False` rather than falsy: a visit from a backend that supplies no
        # evidence has no `confirmed` key at all, and must not be reclassified
        # as unconfirmed.
        if min_confidence == "confirmed" and visit.get("confirmed") is False:
            return False
        if exclude_flags and (int(visit.get("flags_or") or 0) & int(exclude_flags)):
            return False
        return True

    # The empirical "operating days" denominator for min_open_day_share: every
    # distinct LOCAL day any device was seen at the clause's in-scope POIs —
    # derived entirely from pings already bought, no Places lookup. Computed
    # once here (not per-device) so every device in this clause shares the
    # same denominator. Empty when the scope has no visit data at all;
    # min_open_day_share's own guard (below) skips the test rather than
    # dividing by zero — never drops a device for a scope-wide data gap.
    #
    # Computed for ANY role-signal clause (not just min_open_day_share) —
    # role_confidence() reads its size via _role_signal_stats() regardless of
    # which role field the spec actually used, including a dwell-only
    # min_weekly_hours clause with no presence-pattern field at all.
    #
    # Placed AFTER _visit_qualifies (not before, where this used to live) so
    # the denominator can be scoped by the SAME time predicate the numerator
    # (`_days_present`, built from `_presence_pool = scoped if
    # _membership_scoped else visits`, below) already is. Before this fix the
    # denominator counted every open day across the extraction's whole bought
    # history while the numerator was capped to `window_days`/`cutoff` — a
    # spec combining the two ("present most days over the last 2 weeks") could
    # cap the numerator at 14 while the denominator ran to 60+, making the
    # share mathematically unsatisfiable by any device, including a literal
    # every-day presence, and reporting an honest-looking "no one qualifies".
    _role_signal_active = bool(
        min_open_day_share is not None or min_intraday_span_min is not None
        or min_days_present is not None or min_weekly_hours is not None
    )
    open_days: set = {
        _local(v_ts).date()
        for row in rows_in_scope
        for v in (row.get("visits") or [])
        if (v_ts := _visit_started_at(v)) is not None
        and (not _membership_scoped or _visit_qualifies(v, started_at=v_ts))
    } if _role_signal_active else set()
    if _role_signal_active:
        _ROLE_SIGNAL_STATS["open_days_observed"] = max(
            _ROLE_SIGNAL_STATS["open_days_observed"], len(open_days)
        )

    def _row_time_ok(row: dict) -> bool:
        """True if `row` carries at least one qualifying visit.

        A row with no visit timestamps cannot be scoped and is excluded once
        scoping is active, so "visited group G within N days" means what it says.
        """
        return any(_visit_qualifies(v) for v in (row.get("visits") or []))

    def _visit_window(start: datetime) -> bool:
        """Whether a visit start falls inside the clause's recency scope —
        used by the intersection witness test so "visited all three within 45
        days" schedules only visits from those 45 days."""
        return cutoff is None or start >= cutoff

    if groups and op in ("intersection", "difference"):
        def _group_rows(g: str) -> list[dict]:
            rows = [o for o in observations if o.get("maid") and g in (o.get("poi_ids") or [])]
            return [r for r in rows if _row_time_ok(r)] if _membership_scoped else rows

        per_group_rows: list[list[dict]] = [_group_rows(g) for g in groups]
        per_group: list[set] = [{r["maid"] for r in rows} for rows in per_group_rows]
        eligible = (
            set.intersection(*per_group) if op == "intersection"
            else per_group[0].difference(*per_group[1:])
        ) if per_group else set()

        if op == "intersection" and eligible and len(groups) > 1:
            # Co-located geofences: two DIFFERENT groups' POIs can sit close
            # enough that ONE physical presence is returned under both — the
            # vendor evaluates each feature independently — so a device that
            # only ever stood in one spot could satisfy an N-way intersection.
            #
            # The old guard counted DISTINCT PLACES (`poi_uids`) and required as
            # many as there were groups. That does not catch this case: the two
            # POIs genuinely ARE distinct places, so the count passes while the
            # device was only ever in one location at one time.
            #
            # Visits carry timestamps now, so test the thing we actually mean:
            # require a set of witness visits, one per group, that are PAIRWISE
            # NON-OVERLAPPING IN TIME. Being in two places at once is exactly
            # what we are excluding, and that is directly checkable.
            _INTERSECTION_WITNESS_STATS["intersection_raw"] += len(eligible)
            eligible = {
                m for m in eligible
                if _has_disjoint_witnesses(m, per_group_rows, _visit_window)
            }
            _INTERSECTION_WITNESS_STATS["intersection_after_witness_test"] += len(eligible)
    elif op not in ("union", "intersection", "difference"):
        raise ValueError(f"unknown audience_filter op: {op!r}")
    else:
        eligible = {o["maid"] for o in rows_in_scope if o.get("maid")}

    if exclude_groups:
        # WHICH visits does an exclusion look at? "Went to a gym in the last 7
        # days but not to my store" almost always means no STORE visit in those
        # same 7 days, so by default the exclusion inherits the selection's
        # scope. `exclude_window_days` overrides it for the cases that mean
        # something else ("...and has never been to my store"): pass a larger
        # window, or 0 for "ever". Previously this was decided implicitly by
        # whichever predicates happened to be active.
        _excl_rows = [o for o in observations if o.get("maid") and _hits(o, exclude_groups)]
        if exclude_window_days is not None:
            _excl_cutoff = (
                now - timedelta(days=int(exclude_window_days))
                if int(exclude_window_days) > 0 else None
            )
            _excl_rows = [
                r for r in _excl_rows
                if _excl_cutoff is None or any(
                    start >= _excl_cutoff for start, _end in _visit_intervals(r)
                ) or not (r.get("visits") or [])
            ]
        elif _membership_scoped:
            _excl_rows = [r for r in _excl_rows if _row_time_ok(r)]
        eligible -= {o["maid"] for o in _excl_rows}
    if not eligible:
        return []

    by_device: dict[str, list[dict]] = defaultdict(list)
    for row in rows_in_scope:
        m = row.get("maid")
        if m in eligible:
            by_device[m].append(row)

    # The M in "N of M": the groups the clause named, else every group in the
    # build. Sorted for a deterministic search.
    _mdg_candidates: list[str] = (
        sorted(set(groups)) if groups
        else sorted({g for o in observations for g in (o.get("poi_ids") or [])})
    ) if min_distinct_groups is not None else []

    result: list[str] = []
    for maid, rows in by_device.items():
        visits: list[tuple[datetime, int, list[str]]] = []
        has_visit_data = False
        for row in rows:
            for v in (row.get("visits") or []):
                ts = v.get("ts")
                if not ts:
                    continue
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                except ValueError:
                    continue
                has_visit_data = True
                visits.append((
                    dt,
                    _dwell_seconds(v, bound=dwell_bound),
                    row.get("poi_ids") or [],
                    visit_is_timed(v),
                    v,
                    # Individual place(s) this visit belongs to — what the
                    # per-place min_visits count below groups by. Falls back to
                    # poi_ids (category/brand group) for rows persisted before
                    # poi_uids existed, same fallback min_distinct_pois already
                    # uses a few lines down; falls back further to the row's
                    # own poi_key (the request-feature id — one purchase, one
                    # physical place, present on every row regardless of
                    # whether attribute_audience has ever stamped it) so a row
                    # that was never run through attribution still groups by
                    # place instead of not grouping at all.
                    row.get("poi_uids") or row.get("poi_ids")
                    or ([row["poi_key"]] if row.get("poi_key") else []),
                ))

        if time_predicate_active and not has_visit_data:
            continue  # can't evaluate a time predicate with no timestamps

        if trend:
            # Asymmetric by design when the caller says so. "Suddenly started
            # going after never going before" needs a SHORT recent window and a
            # LONG prior one; a symmetric 2x window cannot express it and
            # answers a different question.
            _recent_d, _prior_d = _trend_windows(spec)
            _recent_start = now - timedelta(days=_recent_d)
            _prior_start = _recent_start - timedelta(days=_prior_d)
            recent = [v for v in visits if _recent_start <= v[0] <= now]
            older = [v for v in visits if _prior_start <= v[0] < _recent_start]
            # "started" needs only ONE recent visit; "lapsed" needs TWO older
            # ones — a single historic visit is not a habit worth winning back.
            if trend == "started" and not (len(recent) >= 1 and len(older) == 0):
                continue
            if trend == "lapsed" and not (len(older) >= 2 and len(recent) == 0):
                continue

        if cadence_days:
            # Recurring-interval check ("every payday"): consecutive gaps
            # between distinct visit DAYS (not raw pings — several same-day
            # visits shouldn't count as a near-zero gap), over the device's
            # full visit history (not `scoped` — cadence is its own
            # predicate, independent of window/day/hour narrowing, same as
            # `trend` above). Tolerance defaults to 20% of the target
            # interval when the caller doesn't give one.
            tol = cadence_tolerance if cadence_tolerance is not None else max(1, round(cadence_days * 0.2))
            # Local date, not UTC — every other day-bucketing predicate in
            # this function (open_days, the presence-pattern day envelopes)
            # already shifts to local time before taking `.date()`; this one
            # didn't. A visit at 23:58 Pacific (07:58 UTC the NEXT calendar
            # day) bucketed by raw UTC date could jump a device's "every
            # Friday" pattern onto Saturday for one week and read as a
            # spurious 6- or 8-day gap instead of the consistent local 7,
            # pushing a genuinely on-cadence device under `min_occurrences`.
            visit_days = sorted({_local(v[0]).date() for v in visits})
            gaps = [(b - a).days for a, b in zip(visit_days, visit_days[1:])]
            good_gaps = sum(1 for g in gaps if (cadence_days - tol) <= g <= (cadence_days + tol))
            # Occurrence floor: reuse min_visits (the device's own "at least
            # N occurrences of the cadence") when stated, else 2 consecutive
            # on-cadence gaps is the minimum evidence of a real recurrence.
            min_occurrences = max(1, (min_visits or 3) - 1)
            if good_gaps < min_occurrences:
                continue

        # Same qualifier as group membership above — one implementation, so the
        # two can no longer disagree about what "inside the scope" means.
        scoped = [v for v in visits if _visit_qualifies(v[4], started_at=v[0])]

        if time_predicate_active and not scoped and not visits:
            continue

        # Frequency counts are VISITS — the ones inside the clause's scope once
        # any per-visit predicate narrowed it, else all of them. A raw ping count
        # is not a visit count and is never used as one.
        #
        # `_membership_scoped` (not a hand-listed subset) so a predicate added
        # to `_visit_qualifies` later cannot be forgotten here — this used to
        # list only cutoff/days_of_week/hours/min_dwell, so `min_confidence`
        # and `exclude_flags` never narrowed the COUNT: a device with 3
        # unconfirmed single-ping visits and 0 confirmed ones satisfied
        # `{"min_visits": 3, "min_confidence": "confirmed"}`.
        target_visits = scoped if _membership_scoped else visits

        if groups:
            # A NAMED group ("3+ times at Sephora") is a real single scope —
            # `rows_in_scope` already restricted `visits` to that group's own
            # rows, so summing across it is "3 different Sephoras" brand
            # loyalty, not cross-category noise. Unchanged from before.
            n_visits = len(target_visits)
        else:
            # No named group is the common case — every POI in the build is in
            # scope. Summing across ALL of them used to let a device seen once
            # at a gym, once at a coffee shop and once at a barber satisfy
            # "3+ visits" and be called a regular, while maid_query.compute_
            # visit_stats (the map's repeat-visitor stat, and its own
            # docstring's claim of matching this) takes the device's BEST
            # single-location count and correctly calls that same device a
            # one-timer. Match the map: the count is the most this device
            # visited any ONE place, not the sum across every place it ever
            # appeared. `poi_uids` (index 5) is the individual place; several
            # duplicate-coordinate POI entries sharing one purchase resolve to
            # the same alias set, so crediting a visit to each doesn't inflate
            # the max.
            per_place: dict[str, int] = defaultdict(int)
            for v in target_visits:
                for uid in (v[5] or ()):
                    per_place[uid] += 1
            n_visits = max(per_place.values()) if per_place else 0

        if min_visits is not None and n_visits < min_visits:
            continue

        if min_distinct_pois is not None:
            # poi_uids = individual places (what "2 different locations" means);
            # poi_ids (category/brand group) is a fallback for rows persisted
            # before poi_uids existed — coarser, but better than refusing to
            # evaluate the predicate at all on old data. Window-scoped like
            # group membership above — "2 different locations in the last 7
            # days" must not silently mean "2 different locations, ever".
            _mdp_rows = [r for r in rows if _row_time_ok(r)] if _membership_scoped else rows
            distinct: set = set()
            for r in _mdp_rows:
                distinct.update(r.get("poi_uids") or r.get("poi_ids") or [])
            if len(distinct) < min_distinct_pois:
                continue

        if min_distinct_groups is not None:
            # "3 of the 5 place types". Counts GROUPS, scoped to the M the
            # clause named — a device's rows also carry every OTHER group that
            # shares a `poi_key`, and those must not earn credit. Each counted
            # group needs a witness visit and the witnesses must not overlap in
            # time, so one presence under two co-located geofences is one group,
            # exactly as `intersection` already requires.
            _mdg_rows = [r for r in rows if _row_time_ok(r)] if _membership_scoped else rows
            if not _has_disjoint_witnesses(
                maid,
                [[r for r in _mdg_rows if g in (r.get("poi_ids") or [])] for g in _mdg_candidates],
                _visit_window,
                need=int(min_distinct_groups),
            ):
                continue

        if min_visits_per_group is not None and groups:
            # "3+ times at the gym AND 3+ times at the coffee shop" — a
            # per-group floor, which `min_visits` (a total across the clause)
            # cannot express: 5 gym visits and 1 coffee visit passes
            # min_visits: 6 but is not what was asked.
            #
            # Reuses `target_visits` (already correctly time/qualifier-scoped
            # a few lines up), filtered per VISIT by group membership — not
            # the old row-level `_row_time_ok` check, which only required ONE
            # qualifying visit per row and then counted that row's ENTIRE
            # visit list regardless of how many of them actually qualified.
            # A row with 10 total visits, only 1 inside `window_days: 7`,
            # used to count as "10 gym visits in the last week" the moment
            # any single one of the 10 fell inside the window.
            _per_group_ok = True
            for g in groups:
                g_visits = sum(1 for v in target_visits if g in (v[2] or ()))
                if g_visits < min_visits_per_group:
                    _per_group_ok = False
                    break
            if not _per_group_ok:
                continue

        if min_share_in_scope is not None:
            # "ONLY on weekdays" — every other predicate is a minimum or a
            # membership test, so "at least one weekday visit" was the closest
            # they could get. This is the share of the device's OWN visits that
            # fall inside the clause's scope, which is what exclusivity means.
            _all_visits = sum(len(r.get("visits") or []) for r in rows)
            if _all_visits:
                if (len(scoped) / _all_visits) < float(min_share_in_scope):
                    continue
            elif float(min_share_in_scope) > 0:
                continue

        if min_weekly_hours is not None:
            # The denominator must be the span actually ANALYSED, never a
            # constant. An event-based run gets no default filter, so
            # `window_days` is unset and this used to fall back to 30 days:
            # a two-day event's dwell divided by 4.29 weeks needed 171 hours to
            # clear a 40 hrs/week threshold. It excluded everyone, silently, and
            # looked exactly like a real empty result.
            span_days = (
                window_days
                or spec.get("_history_days_bought")
                or _observed_span_days(visits)
                or _DEFAULT_TREND_WINDOW_DAYS
            )
            weeks = max(span_days, 1) / 7.0
            dwell_pool = scoped if _membership_scoped else visits
            # Measured visits only. Summing a fabricated minute for each of the
            # ~47% of visits that are single-ping put invented time into a
            # threshold the user stated in real hours.
            total_hours = sum(v[1] for v in dwell_pool if v[3]) / 3600.0
            if total_hours / weeks < min_weekly_hours:
                continue

        if min_open_day_share is not None or min_intraday_span_min is not None \
                or min_days_present is not None:
            # PRESENCE-PATTERN aggregates: per-device, per-LOCAL-DAY envelopes
            # over the same pool min_weekly_hours reads (scoped once any
            # per-visit predicate narrowed it, else every visit) — but unlike
            # min_weekly_hours these do NOT require visit_is_timed(): a single
            # ping still marks a day present and still anchors one end of that
            # day's envelope. That is the entire point (see the AudienceFilter
            # docblock) — a device whose stay was gap-fragmented into several
            # unmeasured-dwell visits still shows up here.
            _presence_pool = scoped if _membership_scoped else visits
            _day_span: dict = {}
            for v in _presence_pool:
                local_start = _local(v[0])
                day = local_start.date()
                local_end = local_start + timedelta(seconds=v[1])
                cur = _day_span.get(day)
                _day_span[day] = (
                    (min(cur[0], local_start), max(cur[1], local_end)) if cur
                    else (local_start, local_end)
                )

            _days_present = len(_day_span)
            if min_days_present is not None and _days_present < min_days_present:
                continue
            if min_open_day_share is not None and open_days:
                if (_days_present / len(open_days)) < float(min_open_day_share):
                    continue
            if min_intraday_span_min is not None:
                _span_min = max(
                    ((e - s).total_seconds() / 60.0 for s, e in _day_span.values()),
                    default=0.0,
                )
                if _span_min < min_intraday_span_min:
                    continue

        # ANY per-visit predicate, with no frequency aggregate to carry it,
        # still needs at least one qualifying visit to keep the device.
        #
        # `_membership_scoped` rather than a hand-listed tuple of
        # cutoff/day/hour/dwell: that list silently omitted `min_confidence`
        # and `exclude_flags`, so a clause carrying ONLY one of those filtered
        # nothing at all — the extractor could emit it and the evaluator kept
        # every device. Deriving the guard from the same flag the qualifier
        # uses means a predicate added later cannot be forgotten here.
        if _membership_scoped and not scoped \
                and min_visits is None and min_distinct_pois is None and min_weekly_hours is None \
                and min_distinct_groups is None \
                and min_open_day_share is None and min_intraday_span_min is None \
                and min_days_present is None:
            continue

        result.append(maid)

    if spec.get("invert"):
        return sorted(eligible - set(result))
    return sorted(result)
