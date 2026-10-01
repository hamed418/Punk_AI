"""
graph/maid_query.py
───────────────────
The audience seam, plus the pure helpers every stage after the vendor call uses.

    querier = get_maid_querier()   # None when UNACAST_API_TOKEN is unset
    rows = await querier.query_maids(dates=[...], pois=[{"lat", "lng", "radius_km"}])

``rows`` is one dict per raw Unacast ping (see
``unacast_query.UnacastMAIDQuerier``). Everything else here — visit clustering,
POI attribution, per-device frequency, the map payload — is pure, so it can be
tested without the vendor or a database.
"""

from __future__ import annotations

import logging
import math
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Optional

from app.graph.maid_signal import accuracy_upper_m

logger = logging.getLogger(__name__)


class NonRetryableMAIDQueryError(Exception):
    """A query failure that retrying cannot fix.

    Lives here, on the module that defines the querier seam, so
    ``_query_maids_with_retry`` (executors/maid.py) can recognise it without
    importing the querier. The Unacast querier raises subclasses for an
    exhausted monthly budget, a saturated concurrency pool, an open circuit
    breaker, and a source IP the vendor has not allowlisted — none of which a
    second attempt changes, and most of which cost real, scarce budget to
    re-attempt.
    """


DEFAULT_POI_RADIUS_KM = 0.1   # 100 m — fallback when caller provides no radius

# Consecutive pings at the same PLACE within this many minutes collapse into
# one visit. It is also what bounds dwell when a device has no neighbouring
# ping to bound it with (see cluster_visits' dwell_upper_s).
#
# The threshold is a hard cliff and worth knowing: two coffee stops 25 minutes
# apart are two visits; 18 minutes apart is one visit spanning the gap. The
# chain is also transitive, so pings at 0/19/38/57 minutes are one 57-minute
# visit — right for a continuous stay, wrong for a device drifting through
# repeatedly. `n_pings` plus `dwell_lower_s` let a reader tell those apart.
#
# ponytail: gap-based clustering is a heuristic — real vendor feeds ship dwell
# directly, swap this out when the feed does.
#
# Measured sensitivity (84,473 gated pings, 17,671 device-POI pairs): 5 min
# yields 46,137 visits, 20 min 30,791, 120 min 22,279 — a 2x swing, and
# `min_visits` reads straight off it. Overridable globally and per category via
# settings; see gap_minutes_for.
VISIT_GAP_MINUTES = 20


def gap_minutes_for(category: str | None = None) -> int:
    """Visit-gap threshold for a POI category, in minutes.

    A two-minute forecourt stop and an afternoon at a mall are not the same
    shape, so one global constant has to be wrong for one of them. Falls back to
    the global default, which is what every published baseline number was
    produced with.
    """
    from app.core.config import settings

    default = int(getattr(settings, "MAID_VISIT_GAP_MINUTES", VISIT_GAP_MINUTES)
                  or VISIT_GAP_MINUTES)
    raw = (getattr(settings, "MAID_VISIT_GAP_BY_CATEGORY", "") or "").strip()
    if not category or not raw:
        return default
    needle = str(category).strip().lower()
    for pair in raw.split(","):
        name, _, minutes = pair.partition(":")
        if name.strip().lower() and name.strip().lower() in needle:
            try:
                return max(1, int(minutes))
            except ValueError:
                logger.warning(
                    "MAID_VISIT_GAP_BY_CATEGORY entry %r has a non-integer value — ignored",
                    pair,
                )
    return default


def audience_headline_count(geo_data: dict | None) -> int | None:
    """The one audience number to show anyone: what the active filter leaves.

    ``filtered_maid_count`` when the extraction recorded one, else the raw
    ``maid_count`` superset, else None. Every summary and narration fact routes
    through this so one conversation cannot quote two different audiences — the
    Meta-connect turn once said "3,506" right after the reveal said the filter
    had narrowed that to 1,277, because it read the raw count directly.
    """
    geo_data = geo_data or {}
    count = geo_data.get("filtered_maid_count")
    return geo_data.get("maid_count") if count is None else count


def is_role_spec(spec: dict | None) -> bool:
    """True when ``spec`` (or any ``any_of`` branch) sets a role-inference
    field — ``min_weekly_hours`` or a presence-pattern field
    (``min_open_day_share``/``min_intraday_span_min``/``min_days_present``).
    Gates whether ``role_confidence`` is meaningful to compute or show at
    all — a plain frequency/day-of-week filter has no role reading."""
    if not spec:
        return False
    if spec.get("any_of"):
        return any(is_role_spec(c) for c in spec["any_of"])
    return bool(
        spec.get("min_weekly_hours") or spec.get("min_open_day_share")
        or spec.get("min_intraday_span_min") or spec.get("min_days_present")
    )


def is_dwell_only_role_spec(spec: dict | None) -> bool:
    """A role spec using ONLY ``min_weekly_hours``, no presence-pattern
    field — the shape most exposed to ping sparsity (see
    ``AUDIENCE_FILTER_ROLE_GUARD``: ~47% of visits are single-ping and
    ``min_weekly_hours`` sums only the measured ones). An ``any_of`` counts
    as dwell-only only when EVERY branch is — one presence-pattern branch is
    enough evidence-shape diversity to not warrant the extra caution.

    Public (not underscore-prefixed): also used outside ``role_confidence``
    to pick the ``role_basis`` narrated to the user ("dwell" vs "presence
    pattern") — see ``executors/maid.py``'s role-confidence block."""
    if not spec:
        return False
    if spec.get("any_of"):
        branches = spec["any_of"]
        return bool(branches) and all(is_dwell_only_role_spec(c) for c in branches)
    has_presence = bool(
        spec.get("min_open_day_share") or spec.get("min_intraday_span_min")
        or spec.get("min_days_present")
    )
    return bool(spec.get("min_weekly_hours")) and not has_presence


def role_confidence(
    open_days: int, yield_pct: float, device_dwell_measurable_pct: float,
    spec: dict | None,
) -> str:
    """How much to trust a role-inferred (owner/staff) READ on this audience
    — ``"high"``/``"medium"``/``"low"``. NEVER gates whether the audience is
    returned — that would be a refusal, and role targeting is never refused
    (see ``AUDIENCE_FILTER_ROLE_GUARD``'s product decision). This only
    decides what the narrator/UI SAY about a role-inferred audience.

    ``open_days`` — operating days observed for the active role predicate
        (``maid_store.role_signal_stats()["open_days_observed"]`` right after
        the same ``apply_audience_filter`` call this is scored from).
    ``yield_pct`` — ``filtered_devices / raw_devices * 100``. A role
        predicate that clears most of a POI's visitors is a sign the
        inference is too loose for that POI (a 3-chair barbershop cannot
        have hundreds of "staff"), not that everyone works there — see
        ``settings.MAID_ROLE_YIELD_CEILING_PCT``.
    ``device_dwell_measurable_pct`` — ``compute_visit_stats``'
        ``dwell_measurable_device_pct`` over the FILTERED (kept) devices.
    ``spec`` — the active ``AudienceFilter``, to weight a dwell-only spec
        (the shape most exposed to sparsity) more cautiously than a
        presence-pattern one at the same evidence depth.

    Three tiers, cheapest-to-fail first — not a scoring model, a ladder:
        low    — under a week of operating-day evidence, or the yield ceiling
                 tripped. Either way the read is not trustworthy.
        medium — 1-2 weeks of evidence, or a dwell-only spec whose kept
                 devices are under half measurably-dwelled (min_weekly_hours
                 read mostly off single-ping, unmeasured visits).
        high   — everything else: 2+ weeks of evidence, yield inside the
                 ceiling, and (for a dwell-only spec) solid dwell evidence.
    """
    from app.core.config import settings

    ceiling = float(getattr(settings, "MAID_ROLE_YIELD_CEILING_PCT", 15.0) or 15.0)
    if open_days < 7 or yield_pct > ceiling:
        return "low"
    if open_days < 14:
        return "medium"
    if is_dwell_only_role_spec(spec) and device_dwell_measurable_pct < 50:
        return "medium"
    return "high"


# ── Pure helpers ──────────────────────────────────────────────────────────────

def build_date_list(reference_date: str, lookback_days: int) -> list[str]:
    """
    ISO date strings from reference_date back lookback_days days (inclusive).

    build_date_list("2026-02-10", 3) -> ["2026-02-10", "2026-02-09", "2026-02-08"]
    """
    end = date.fromisoformat(reference_date)
    return [(end - timedelta(days=i)).isoformat() for i in range(lookback_days)]


def build_date_range(start_date: str, end_date: str) -> list[str]:
    """
    ISO date strings for every day from start_date to end_date inclusive.

    build_date_range("2026-07-25", "2026-07-27") -> ["2026-07-25", "2026-07-26", "2026-07-27"]
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    days = max(0, (end - start).days) + 1
    return [(start + timedelta(days=i)).isoformat() for i in range(days)]


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def visit_is_timed(visit: dict) -> bool:
    """Whether this visit's dwell was actually MEASURED rather than unknown.

    A visit built from a single ping has no measurable duration — the device was
    seen once and we know nothing about how long it stayed. Measured on 287,000
    real pings, **46.6% of visits are single-ping**
    (docs/maid_signal_quality_baseline.md §4). A visit that carries no
    ``n_pings`` has no evidence either way and is treated as unmeasured.
    """
    return int(visit.get("n_pings") or 0) >= 2


# A single ping confirms a visit only if it is precise enough AND comfortably
# inside the ring rather than on its edge — the vendor's geo search is fuzzy, so
# an observation can be returned from just outside the drawn area.
_CONFIRM_MAX_ACCURACY_M = 35.0
_CONFIRM_MAX_DIST_FRACTION = 0.8


def cluster_visits(
    timestamps: list[str],
    gap_minutes: int = VISIT_GAP_MINUTES,
    *,
    device_timeline: list[datetime] | None = None,
    ping_meta: dict[str, dict] | None = None,
    radius_m: float | None = None,
) -> list[dict]:
    """Collapse raw ping ISO timestamps at ONE place into discrete visits.

    Pings within ``gap_minutes`` of each other belong to the same visit. Returns
    ``[{"ts", "dwell_min", "dwell_lower_s", "dwell_upper_s", "n_pings"}, ...]``
    sorted earliest first — the shape ``apply_audience_filter`` (maid_store.py)
    evaluates hour/day-of-week/dwell/trend predicates against.

    Dwell is reported as an INTERVAL, not a point estimate, because that is what
    ping data supports:

      ``dwell_lower_s`` — the observed span, first ping to last. **Zero for a
          single-ping visit**, where the duration is genuinely unknown.
      ``dwell_upper_s`` — when the visit must have ended by. The device was here
          at its first and last in-visit ping; it arrived after its previous
          ping ANYWHERE and left before its next ping anywhere. Pass
          ``device_timeline`` (that device's full sorted ping times across every
          POI) to get the real bound; without it the gap threshold is used as a
          proxy.
      ``n_pings`` — the evidence count, and via ``visit_is_timed`` the gate on
          which predicates may read this visit's dwell at all.

    ``dwell_min`` is the observed span in whole minutes (so 0 when unmeasured).

    ``ping_meta`` (ISO timestamp -> ``{"flags", "dist_m"}``) and ``radius_m``
    add the EVIDENCE fields, which is what makes a visit judgeable rather than
    merely counted:

      ``confirmed``       — a legible rule, not a classifier: two or more pings,
          OR one high-accuracy ping comfortably inside the ring. Without it the
          ``min_confidence`` filter has no producer and silently does nothing.
      ``best_accuracy_m`` — the tightest accuracy band in the cluster.
      ``min_dist_m``      — closest approach to the ring centre.
      ``flags_or``        — OR of the cluster's forensicFlags, so a later filter
          can drop a visit whose evidence includes a driving or spoof ping
          without re-reading the pings.
    """
    if not timestamps:
        return []
    times = sorted(datetime.fromisoformat(t.replace("Z", "+00:00")) for t in timestamps)
    clusters: list[list[datetime]] = [[times[0]]]
    for t in times[1:]:
        if (t - clusters[-1][-1]).total_seconds() <= gap_minutes * 60:
            clusters[-1].append(t)
        else:
            clusters.append([t])

    gap = timedelta(minutes=gap_minutes)
    timeline = device_timeline or []
    out: list[dict] = []
    for cluster in clusters:
        first, last = cluster[0], cluster[-1]
        lower_s = int((last - first).total_seconds())

        # Nearest pings OUTSIDE this visit bound when it can have started and
        # ended. bisect over the device's own timeline; a ping at another POI is
        # exactly as good a bound as one at this POI.
        if timeline:
            i = bisect_left(timeline, first)
            prev_any = timeline[i - 1] if i > 0 else None
            j = bisect_right(timeline, last)
            next_any = timeline[j] if j < len(timeline) else None
        else:
            prev_any = next_any = None
        earliest = prev_any if prev_any is not None else first - gap
        latest = next_any if next_any is not None else last + gap
        upper_s = max(lower_s, int((latest - earliest).total_seconds()))

        visit = {
            "ts": first.isoformat(),
            "dwell_min": lower_s // 60,
            "dwell_lower_s": lower_s,
            "dwell_upper_s": upper_s,
            "n_pings": len(cluster),
            # What "one visit" MEANT for this row. The threshold swings visit
            # counts by 2x end to end and is now per-category, so a stored
            # extraction that does not record it cannot be compared with a later
            # one, or re-derived correctly.
            "gap_s": gap_minutes * 60,
        }

        if ping_meta:
            metas = [m for t in cluster if (m := ping_meta.get(t.isoformat()))]
            accs = [
                a for m in metas
                if (a := accuracy_upper_m(m.get("flags"))) is not None
            ]
            dists = [d for m in metas if (d := m.get("dist_m")) is not None]
            flags_or = 0
            for m in metas:
                flags_or |= int(m.get("flags") or 0)

            best_acc = min(accs) if accs else None
            min_dist = min(dists) if dists else None
            visit["best_accuracy_m"] = best_acc
            visit["min_dist_m"] = min_dist
            visit["flags_or"] = flags_or
            visit["confirmed"] = bool(
                len(cluster) >= 2
                or (
                    best_acc is not None
                    and best_acc <= _CONFIRM_MAX_ACCURACY_M
                    and min_dist is not None
                    and radius_m
                    and min_dist <= radius_m * _CONFIRM_MAX_DIST_FRACTION
                )
            )
        out.append(visit)
    return out


def attribute_audience(
    obs_rows: list[dict], pois: list[dict], *, stamp_stats: bool = True
) -> tuple[int, list[dict]]:
    """Attribute observed devices to the POI each row was bought under.

    Every row carries ``poi_key`` — the id of the request feature the vendor
    matched the ping under, which is the key of the POI we sent — so the POI is
    a dict lookup, never a geometric re-derivation. A row whose key resolves to
    no POI in ``pois`` is dropped: its POI was removed at the confirm gate, or it
    was bought at a different radius, and either way it is not evidence for
    this audience. POIs at the same coordinates and radius share a key (they are
    the same purchase), so such a row counts toward each of them.

    Mutates each POI dict in ``pois`` in place, stamping ``audience_count`` = the
    number of UNIQUE devices attributed to it — on EVERY call, regardless of
    ``stamp_stats`` — and, only when ``stamp_stats``, ``visit_stats`` too (a
    per-POI frequency report, ``compute_visit_stats`` over just that POI's
    rows, for the POI-hover popup). The two are deliberately split: a
    ``stamp_stats=False`` recompute pass (e.g. the raw-superset pass in
    ``executors/maid.py``) still needs the per-POI COUNT refreshed — a removed
    POI's group must stop showing its old total — it just must not clobber the
    already-persisted ``visit_stats`` from the run that actually queried the
    vendor with numbers computed over a differently-filtered subset. The
    SECOND, filtered-subset call in the same pipeline is what stamps the real
    ``visit_stats`` the user sees. Pass ``stamp_stats=False`` on any call whose
    inputs are not the audience being shown, or an unfiltered/stale/counterfeit
    per-POI stat silently overwrites a correct one.

    Per-POI counts may sum to more than the returned total, which is the deduped
    union ("unique visitors").

    Stamps ``poi_ids`` (the ``geo.poi_group_id()`` of the POI(s) — "which
    group") and ``poi_uids`` (the individual place as ``"lat,lng"`` — "which
    spot", what ``min_distinct_pois`` counts) on every kept row, so a stored
    observation can be traced back to a POI/category/brand later
    (``group_pois_by_category_with_audience``, ``maid_store.py``).

    Returns ``(total_unique_maids, kept_rows)``.
    """
    from app.graph.builder.executors.geo import _poi_key, poi_group_id
    from app.graph.unacast_query import poi_key

    poi_ids = [poi_group_id(p) for p in pois]
    # String, not the raw (lat,lng) tuple: observations persist through a JSON
    # column (db/models.py) where a tuple round-trips as a list — unhashable,
    # breaks every downstream set() use of this value.
    poi_uids = [
        (f"{k[0]},{k[1]}" if (k := _poi_key(p)) is not None else poi_ids[i])
        for i, p in enumerate(pois)
    ]
    key_to_indices: dict[str, list[int]] = defaultdict(list)
    for i, poi in enumerate(pois):
        k = poi_key(poi)
        if k is not None:
            key_to_indices[k].append(i)

    per_poi_maids: list[set] = [set() for _ in pois]
    per_poi_rows: list[list] = [[] for _ in pois]
    union: set = set()
    kept: list[dict] = []
    for row in obs_rows:
        matched = key_to_indices.get(row.get("poi_key") or "")
        if not matched:
            continue
        maid = row.get("maid")
        for i in matched:
            per_poi_rows[i].append(row)
            if maid is not None:
                per_poi_maids[i].add(maid)
        if maid is not None:
            union.add(maid)
        kept.append({
            **row,
            "poi_ids": list(dict.fromkeys(poi_ids[i] for i in matched)),
            "poi_uids": list(dict.fromkeys(poi_uids[i] for i in matched)),
        })
    for poi, mset, rows in zip(pois, per_poi_maids, per_poi_rows):
        poi["audience_count"] = len(mset)
        if stamp_stats:
            poi["visit_stats"] = compute_visit_stats(rows)["summary"]
    return len(union), kept


def compute_visit_stats(observations: list[dict]) -> dict:
    """Aggregate observation rows into a per-device frequency summary.

    ``observations`` are ``{maid, count, visits, days}`` rows, one row per
    ``(maid, poi_key)`` pair (see ``attribute_audience``). A device's value is
    the MOST visits it has at any ONE of its POIs, not the sum across every POI
    it happens to appear at — the same thing an UNGROUPED ``min_visits``
    counts (``maid_store._apply_clause``'s per-place branch), so the map's
    repeat-visitor chip and a plain "3+ visits" filter cannot disagree on one
    screen. Summing across POIs instead used to call a device that visited two
    DIFFERENT places once each a "repeat visitor" (2 "visits"), though it never
    returned to either one — with enough POIs in one search this produced a
    roughly constant, meaningless slice of any audience ("always ~20%"
    regardless of real behaviour). A call scoped to a single POI's own rows
    (``attribute_audience``'s per-POI ``stamp_stats`` pass) is unaffected
    either way — each device appears in at most one row there, so sum and max
    were always identical for it.

    A NAMED ``groups`` clause ("3+ times at Sephora") is the one place the two
    still legitimately differ: ``_apply_clause`` sums across that group's own
    places on purpose — three different Sephoras really is brand loyalty, not
    the cross-category noise a bare "3+ visits" used to sum across before it
    matched this function.

    Distinct days are reported as their own number (``total_distinct_days``)
    because several prompts are genuinely day-shaped ("every weekday", "3
    nights a week").

    Returns ``{"per_device": {maid: visits}, "summary": {...}}``. Only the small
    ``summary`` is stamped onto checkpoint state / narrated; ``per_device`` is
    derivable from the stored ``observations`` when needed.
    """
    per_device_visits: dict[str, int] = defaultdict(int)
    per_device_days: dict[str, set] = defaultdict(set)
    per_device_pings: dict[str, int] = defaultdict(int)
    # DEVICE-level measurability, not visit-level: a device with ANY 2+-ping
    # visit anywhere in its rows counts as measurable, even if most of its
    # OTHER visits are single-ping. This is deliberately a different number
    # from executors/maid.py's funnel `dwell_measurable_pct` (timed VISITS /
    # all visits, over the raw superset) — that one answers "how much of the
    # evidence is solid", this one answers "for how many PEOPLE do we have
    # at least one solid data point", which is what a role-confidence read on
    # THIS audience actually needs. See maid_query.visit_is_timed for what
    # "measurable" means (2+ pings — ~47% of real visits are single-ping and
    # have no measured duration at all, docs/maid_signal_quality_baseline.md §4).
    per_device_has_timed: dict[str, bool] = defaultdict(bool)
    for r in observations:
        m = r.get("maid")
        if m is None:
            continue
        per_device_pings[m] += int(r.get("count", 1) or 1)
        visits = r.get("visits") or []
        per_device_visits[m] = max(per_device_visits[m], len(visits))
        per_device_days[m].update(r.get("days") or [])
        if any(visit_is_timed(v) for v in visits):
            per_device_has_timed[m] = True

    per_device = {m: per_device_visits.get(m, 0) for m in per_device_pings}
    total = len(per_device)
    b1 = b2 = b35 = b6 = 0
    for n in per_device.values():
        if n <= 1:
            b1 += 1
        elif n == 2:
            b2 += 1
        elif n <= 5:
            b35 += 1
        else:
            b6 += 1
    repeat = total - b1
    devices_with_measurable_dwell = sum(1 for m in per_device if per_device_has_timed.get(m))
    summary = {
        "basis": "visits",
        "total_devices": total,
        "buckets": {"1x": b1, "2x": b2, "3_5x": b35, "6plus": b6},
        "total_pings": sum(per_device_pings.values()),
        "total_visits": sum(per_device.values()),
        "total_distinct_days": sum(len(d) for d in per_device_days.values()),
        "repeat_visitor_count": repeat,
        "repeat_visitor_pct": round(repeat / total * 100) if total else 0,
        "max_seen": max(per_device.values()) if per_device else 0,
        "devices_with_measurable_dwell": devices_with_measurable_dwell,
        "dwell_measurable_device_pct": (
            round(devices_with_measurable_dwell / total * 100) if total else 0
        ),
    }
    return {"per_device": per_device, "summary": summary}


def public_observations(observations: list[dict]) -> list[dict]:
    """Strip an observation list down to what's safe to put on the wire.

    Persisted/attributed rows carry ``{lat, lng, maid, count, visits, poi_ids}``
    — the ``maid`` (a raw device id — a personal-security exposure with no
    upside, the frontend only plots dots) and everything else are only ever
    needed server-side (POI-removal recompute, frequency layering, set ops).
    The SSE/frontend map only ever needs coordinates.
    """
    return [{"lat": o["lat"], "lng": o["lng"]} for o in observations]


def group_pois_by_category_with_audience(pois: list[dict], observations: list[dict]) -> list[dict]:
    """``geo.group_pois_by_category`` plus a redacted audience slice per group.

    Each group gets its own ``maid_observations`` (redacted dots, via
    ``public_observations``), ``maid_count`` (deduped devices) and ``visit_stats``
    (this group's own frequency summary — repeat-visitor count/pct, buckets,
    max_seen), all computed from the ``poi_ids`` ``attribute_audience`` stamped
    on each row — so the frontend can render one tab per category/brand (POIs +
    dots + count + repeat stats) straight off one SSE payload, no client-side
    recomputation or client-side re-aggregation of per-POI numbers. A device
    seen at two groups' venues counts in both (matches how per-POI
    ``audience_count`` already double-counts across overlapping geofences) —
    group counts are NOT expected to sum to the combined total, and neither is
    ``visit_stats`` (its own denominator is this group's own devices).
    """
    from app.graph.builder.executors.geo import group_pois_by_category

    groups = group_pois_by_category(pois)
    for g in groups:
        rows = [o for o in observations if g["id"] in (o.get("poi_ids") or [])]
        g["maid_observations"] = public_observations(rows)
        g["maid_count"] = len({o["maid"] for o in rows if o.get("maid") is not None})
        g["visit_stats"] = compute_visit_stats(rows)["summary"]
    return groups


def build_maid_split_view(
    *,
    pois: list[dict],
    observations: list[dict],
    audience_filter: dict | None,
    center: dict,
    visit_stats: dict | None,
    search_radius_km: float | None,
    lookback_days: int | None,
    event_date_ranges: list[str] | None,
    stamp_stats: bool = False,
    editable: bool = True,
    split: bool = False,
    role_confidence_tier: str | None = None,
    role_basis: str | None = None,
) -> dict:
    """Single source of truth for the ``maid_split_view`` map_data content.

    ``observations`` is the UNFILTERED superset (already attributed with
    ``poi_ids``/``poi_uids`` or not — either is fine, ``attribute_audience``
    re-derives them here). The active ``audience_filter`` is applied INSIDE this
    function, once, so ``maid_count``, the map dots, the per-POI
    ``audience_count``/``visit_stats``, and the category tabs can never disagree
    again — every caller used to apply the filter (or not) slightly differently
    and ship a different ``maid_count`` semantics. ``maid_count`` is always the
    FILTERED total (the actually-publishable audience); ``unfiltered_maid_count``
    is the raw superset, kept alongside so the UI/narrator can say "narrowed
    from N" instead of hiding it.

    ``role_confidence_tier``/``role_basis`` are precomputed by the caller
    (``executors/maid.py``'s ``role_confidence()`` call, right after the same
    ``apply_audience_filter`` this function re-runs) and passed through
    as-is, not recomputed here — this function only has the observations and
    filter, not the operating-days/yield evidence ``role_confidence`` needs.
    Carried into the returned payload so a RELOAD (map_data is persisted,
    unlike a ``"thinking"``/``"update"`` event) still shows the caveat, not
    just the turn that first said it out loud.
    """
    from app.services.maid_store import (
        AudienceFilterUnevaluable,
        apply_audience_filter,
        describe_audience_filter,
        public_audience_filter,
    )

    # `attributed` (not the raw `observations`) is what the filter runs
    # against: `groups`/`exclude_groups` (poi_ids) and `min_distinct_pois`
    # (poi_uids) both need the attribution stamp this first pass adds —
    # filtering the UNSTAMPED raw rows would silently no-op every group-based
    # and multi-location predicate.
    unfiltered_total, attributed = attribute_audience(list(observations), pois, stamp_stats=False)

    filtered_rows = attributed
    if audience_filter:
        try:
            keep = set(apply_audience_filter(attributed, audience_filter, pois=pois))
            filtered_rows = [o for o in attributed if o.get("maid") in keep]
        except AudienceFilterUnevaluable:
            # Shown unfiltered — the same fallback run_maid_query takes. A map
            # re-emit or a reconnect must not crash on a filter it cannot judge.
            pass

    maid_count, filtered_rows = attribute_audience(filtered_rows, pois, stamp_stats=stamp_stats)

    return {
        "action_type": "maid_split_view",
        "pois": pois,
        "poi_categories": group_pois_by_category_with_audience(pois, filtered_rows),
        "maid_observations": public_observations(filtered_rows),
        "center": center,
        "maid_count": maid_count,
        "unfiltered_maid_count": unfiltered_total,
        "visit_stats": visit_stats,
        "search_radius_km": search_radius_km,
        "lookback_days": lookback_days,
        "event_date_ranges": event_date_ranges or [],
        "split": split,
        "editable": editable,
        "audience_filter_chips": describe_audience_filter(audience_filter),
        # The structured spec behind the chips, so the layer builder can edit
        # it instead of reverse-engineering strings. Internal `_`-prefixed
        # bookkeeping (resolution flags, purchase depth) stays server-side.
        "audience_filter": public_audience_filter(audience_filter) or None,
        "role_confidence": role_confidence_tier,
        "role_basis": role_basis,
    }


# ── Module-level singleton ────────────────────────────────────────────────────

_querier: Optional[Any] = None


def get_maid_querier() -> Optional[Any]:
    """The Unacast querier (created once), or None when ``UNACAST_API_TOKEN`` is
    unset — callers check for None and set ``maid_query_skipped=True``.

    Always the observations/geo/search querier — every stat, filter, map dot
    and dwell/frequency number the user is shown is built from real pings, and
    stays that way. The separate ``UnacastDevicesQuerier``
    (app/graph/unacast_devices.py) is NOT wired in here: it is called only at
    the Meta-upload boundary (executors/media.py._load_maids) to fetch real
    advertising IDs for the confirmed places, because our observations
    entitlement currently returns Unacast's own pseudonym instead of one and
    Meta cannot match on that — see unacast_devices.py's module docstring.

    The import is function-local: unacast_query imports from this module, so a
    top-level import would be a cycle.
    """
    global _querier
    if _querier is not None:
        return _querier

    from app.core.config import settings

    if not settings.UNACAST_API_TOKEN:
        logger.warning(
            "UNACAST_API_TOKEN is unset — audience extraction disabled "
            "(callers will set maid_query_skipped=True)."
        )
        return None

    from app.graph.unacast_query import UnacastMAIDQuerier

    _querier = UnacastMAIDQuerier()
    logger.info("MAID querier: Unacast (%s)", settings.UNACAST_ENV)
    return _querier


async def close_maid_querier() -> None:
    """Close the querier's HTTP pool and drop it.

    ``UnacastMAIDQuerier`` lazily builds one ``httpx.AsyncClient`` and keeps it
    for the life of the process, so without this its connection pool is never
    closed. Called from the app lifespan's teardown, beside
    ``close_checkpointer`` and the Redis close; a no-op when no querier (or no
    client yet) exists.
    """
    global _querier
    if _querier is None:
        return
    aclose = getattr(getattr(_querier, "_client", None), "aclose", None)
    if aclose is not None:
        await aclose()
    _querier = None
