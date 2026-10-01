"""
scripts/measure_maid_signal_quality.py
──────────────────────────────────────
Read-only report over ``unacast_raw_observations`` answering the questions whose
answers would otherwise be config guesses:

  1. What is the signal quality of what we buy?     accuracy bands, fraud bits, hot
  2. What would each candidate quality gate cost?   pings / devices / visits kept
  3. Which POI-days look truncated?                 the 100k-per-feature ceiling

Nothing here writes, and nothing here calls the vendor.

    .venv/Scripts/python.exe scripts/measure_maid_signal_quality.py
    .venv/Scripts/python.exe scripts/measure_maid_signal_quality.py --json out.json

Flag bit meanings: ``Unacast documentation/unacast-forensic-flags.pdf``,
consolidated in UNACAST-API-REFERENCE.md section 6.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# DEBUG=true in .env turns on SQLAlchemy echo, which would log every one of
# several hundred thousand rows. Force it off before the engine is built.
os.environ["DEBUG"] = "false"

from sqlalchemy import text                                    # noqa: E402
from app.db.database import AsyncSessionLocal                  # noqa: E402


# ── Forensic flag bits (UNACAST-API-REFERENCE.md section 6) ──────────────────

FLAG_BITS: dict[str, int] = {
    "LAT_GRID_LOCATION": 7,
    "TOO_MANY_DEVICES_AT_LOCATION": 8,
    "SPOOF_LOCATION": 9,
    "RADIO_DERIVED": 10,
    "EU": 12,
    "OVER_CAPACITY_DEVICE": 13,
    "LIKELY_DRIVING": 14,
    "HIGH_ACCURACY": 15,
    "MODERATE_ACCURACY": 16,
    "LOW_ACCURACY": 17,
    "MOBILE_NETWORK": 19,
    "HYPERV_OUTSIDE_CLUSTER": 20,
    "HYPERV_WITHIN_CLUSTER": 21,
    "HYPERV_CLUSTER_INTERLEAVE": 22,
    "TIMESHIFT": 23,
    "US": 25,
    "IMPLAUSIBLE_MOVEMENT": 27,
    "APPROXIMATED_SIGNAL": 28,
    "DENSE_CIRCULAR_AREAS": 31,
    "IP_DERIVED": 32,
    "LOW_RECURRING_BEHAVIOR": 33,
    "MODERATE_RECURRING_BEHAVIOR": 34,
    "DENSE_CROSSES": 35,
}

# (LOW, MOD, HIGH) -> (label, lower_bound_m, upper_bound_m). Upper is None when
# unbounded. The two "pre-2024" rows are historical combos the vendor documents
# as still appearing in older data.
_ACCURACY: dict[tuple[int, int, int], tuple[str, float, float | None]] = {
    (0, 0, 0): ("unavailable / >10km", 10000.0, None),
    (1, 0, 0): ("250-10000m", 250.0, 10000.0),
    (1, 1, 0): ("220-250m", 220.0, 250.0),
    (0, 1, 0): ("50-220m", 50.0, 220.0),
    (0, 1, 1): ("35-50m", 35.0, 50.0),
    (0, 0, 1): ("0-35m", 0.0, 35.0),
    (1, 1, 1): ("35-50m (pre-2024)", 35.0, 50.0),
    (1, 0, 1): ("0-35m (pre-2024)", 0.0, 35.0),
}


def accuracy_band(flags: int | None) -> tuple[str, float, float | None]:
    """Decode bits 15/16/17 into (label, lower_bound_m, upper_bound_m).

    A ping with no flags at all is treated as the worst band — we genuinely do
    not know how accurate it is.
    """
    if flags is None:
        return ("no flags", 10000.0, None)
    high = (flags >> 15) & 1
    mod = (flags >> 16) & 1
    low = (flags >> 17) & 1
    return _ACCURACY[(low, mod, high)]


def set_flag_names(flags: int | None) -> list[str]:
    if not flags:
        return []
    return [name for name, bit in FLAG_BITS.items() if flags & (1 << bit)]


# The vendor's documented place-visit preset: spoofed, ad-fraud, grid-snapped
# and drive-by signals. See UNACAST-API-REFERENCE.md section 6.
_PLACE_VISIT_MASK = sum(
    1 << FLAG_BITS[name]
    for name in (
        "SPOOF_LOCATION",
        "OVER_CAPACITY_DEVICE",
        "LAT_GRID_LOCATION",
        "LIKELY_DRIVING",
    )
)
_FRAUD_ONLY_MASK = sum(
    1 << FLAG_BITS[name] for name in ("SPOOF_LOCATION", "OVER_CAPACITY_DEVICE")
)

# Candidate gates, cheapest-to-strictest. `acc` compares the decoded accuracy
# band against the POI radius: "permissive" keeps a ping whose accuracy LOWER
# bound is within the ring (it could have been inside); "positional" adds the
# ping's distance from the ring centre to that lower bound (even the smallest
# error must still land inside); "strict" requires the UPPER bound (it must have
# been inside).
GATES: list[dict] = [
    {"name": "none", "bad_mask": 0, "acc": None},
    {"name": "fraud only", "bad_mask": _FRAUD_ONLY_MASK, "acc": None},
    {"name": "place-visit preset", "bad_mask": _PLACE_VISIT_MASK, "acc": None},
    {"name": "preset + acc permissive", "bad_mask": _PLACE_VISIT_MASK, "acc": "permissive"},
    {"name": "preset + acc positional", "bad_mask": _PLACE_VISIT_MASK, "acc": "positional"},
    {"name": "preset + acc strict", "bad_mask": _PLACE_VISIT_MASK, "acc": "strict"},
]


def gate_admits(
    gate: dict, flags: int | None, radius_m: float, dist_m: float | None = None,
) -> bool:
    """``dist_m`` is only read by "positional", which falls back to "permissive"
    without it — exactly as the pipeline's gate does (maid_signal.ping_admitted)."""
    if gate["bad_mask"] and flags and (flags & gate["bad_mask"]):
        return False
    if gate["acc"] is None:
        return True
    _label, lower, upper = accuracy_band(flags)
    if gate["acc"] == "positional" and dist_m is not None:
        return dist_m + lower <= radius_m
    if gate["acc"] in ("permissive", "positional"):
        return lower <= radius_m
    return upper is not None and upper <= radius_m


def sessionize(timestamps: list, gap: timedelta) -> list[tuple]:
    """Split a SORTED timestamp list into (first, last, n_pings) sessions.

    Same greedy gap chain as ``maid_query.cluster_visits`` so the numbers this
    script reports are comparable to what the pipeline actually produces.
    """
    if not timestamps:
        return []
    out: list[tuple] = []
    start = prev = timestamps[0]
    n = 1
    for ts in timestamps[1:]:
        if ts - prev <= gap:
            prev = ts
            n += 1
        else:
            out.append((start, prev, n))
            start = prev = ts
            n = 1
    out.append((start, prev, n))
    return out


def pct(part: float, whole: float) -> str:
    return f"{(part / whole * 100):5.1f}%" if whole else "     -"


async def load_rows(limit: int | None) -> list:
    sql = (
        "SELECT poi_key, maid, observed_at, forensic_flags, hot, "
        "observed_at::date AS day, lat, lng, center_key "
        "FROM unacast_raw_observations "
        "ORDER BY maid, poi_key, observed_at"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(sql))
        return result.fetchall()


async def load_centres() -> dict[str, tuple[float, float]]:
    """Ring centres by ``center_key``, from the POIs saved on extractions.

    The raw cache records which centre a ping was bought for, not where that
    centre is. ``maid_extractions.pois`` keeps the coordinates and survives a
    purge (only device IDs are cleared). A ping whose centre is not found has no
    distance, and the positional gate falls back to permissive for it.
    """
    from app.graph.unacast_query import center_key

    centres: dict[str, tuple[float, float]] = {}
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("SELECT pois FROM maid_extractions"))
        for (pois,) in result.fetchall():
            for p in pois or []:
                if p.get("lat") is None or p.get("lng") is None:
                    continue
                c = center_key(p)
                if c:
                    centres.setdefault(c, (float(p["lat"]), float(p["lng"])))
    return centres


def ground_distance_m(lat: float, lng: float, clat: float, clng: float) -> float:
    """Equirectangular, the same approximation the pipeline's cache read uses."""
    import math

    dy = (lat - clat) * 111320.0
    dx = (lng - clng) * 111320.0 * math.cos(math.radians(clat))
    return math.hypot(dx, dy)


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure MAID signal quality and truncation (read-only)."
    )
    parser.add_argument(
        "--gap-minutes", type=int, default=20,
        help="visit sessionization gap; matches maid_query.VISIT_GAP_MINUTES (default 20)",
    )
    parser.add_argument(
        "--radius-m", type=float, default=100.0,
        help="POI radius the accuracy gates are judged against (default 100)",
    )
    parser.add_argument("--limit", type=int, default=None, help="cap rows for a quick pass")
    parser.add_argument("--json", metavar="PATH", help="also write the report as JSON")
    args = parser.parse_args()

    gap = timedelta(minutes=args.gap_minutes)
    print("Loading observations...", flush=True)
    rows = await load_rows(args.limit)
    total = len(rows)
    if not total:
        print("unacast_raw_observations is empty - nothing to measure.")
        return 1

    report: dict = {
        "total_pings": total,
        "gap_minutes": args.gap_minutes,
        "radius_m": args.radius_m,
    }

    # ── 1. Signal quality ────────────────────────────────────────────────────
    acc_counter: Counter = Counter()
    flag_counter: Counter = Counter()
    hot_count = 0
    no_flag_count = 0
    devices: set = set()
    poi_days: Counter = Counter()
    by_device_poi: dict[tuple, list] = defaultdict(list)

    centres = await load_centres()
    no_centre_count = 0
    for poi_key, maid, ts, flags, hot, day, lat, lng, c_key in rows:
        acc_counter[accuracy_band(flags)[0]] += 1
        if flags is None:
            no_flag_count += 1
        for name in set_flag_names(flags):
            flag_counter[name] += 1
        if hot:
            hot_count += 1
        devices.add(maid)
        poi_days[(poi_key, day)] += 1
        centre = centres.get(c_key) if c_key else None
        dist_m = ground_distance_m(float(lat), float(lng), *centre) if centre else None
        if dist_m is None:
            no_centre_count += 1
        by_device_poi[(maid, poi_key)].append((ts, flags, dist_m))

    bar = "=" * 72
    print(f"\n{bar}")
    print(f"1. SIGNAL QUALITY - {total:,} pings, {len(devices):,} devices")
    print(bar)
    print(f"  {'hot (provisional, <5 days old)':34s} {hot_count:>10,}  {pct(hot_count, total)}")
    print(f"  {'no forensic_flags at all':34s} {no_flag_count:>10,}  {pct(no_flag_count, total)}")
    print("\n  accuracy band (bits 15/16/17):")
    for band, n in sorted(acc_counter.items(), key=lambda kv: -kv[1]):
        print(f"    {band:32s} {n:>10,}  {pct(n, total)}")
    print("\n  flags set (any bit):")
    for name, n in sorted(flag_counter.items(), key=lambda kv: -kv[1]):
        print(f"    {name:32s} {n:>10,}  {pct(n, total)}")

    report["hot_pings"] = hot_count
    report["pings_without_flags"] = no_flag_count
    report["devices"] = len(devices)
    report["accuracy_bands"] = dict(acc_counter)
    report["flags"] = dict(flag_counter)

    # ── 2. Gate impact ───────────────────────────────────────────────────────
    print(f"\n{bar}")
    print(f"2. QUALITY GATE IMPACT (judged against a {args.radius_m:g} m ring)")
    print(bar)
    print(f"  {'gate':26s} {'pings':>11s} {'devices':>9s} {'visits':>9s} {'timed':>8s}")
    gate_rows = []
    for gate in GATES:
        kept_pings = 0
        kept_devices: set = set()
        visits = 0
        timed = 0
        for (maid, _poi_key), pings in by_device_poi.items():
            kept = [
                ts for ts, flags, dist_m in pings
                if gate_admits(gate, flags, args.radius_m, dist_m)
            ]
            if not kept:
                continue
            kept_pings += len(kept)
            kept_devices.add(maid)
            for _first, _last, n in sessionize(sorted(kept), gap):
                visits += 1
                if n >= 2:
                    timed += 1
        print(
            f"  {gate['name']:26s} {kept_pings:>11,} {len(kept_devices):>9,} "
            f"{visits:>9,} {pct(timed, visits)}"
        )
        gate_rows.append({
            "gate": gate["name"],
            "pings": kept_pings,
            "devices": len(kept_devices),
            "visits": visits,
            "timed_visits": timed,
        })
    print("\n  'timed' = visits with 2+ pings, i.e. the only ones where dwell is")
    print("  measurable at all. A single-ping visit has UNKNOWN dwell and cannot")
    print("  satisfy a dwell predicate.")
    report["gates"] = gate_rows

    # ── 3. Truncation suspects ───────────────────────────────────────────────
    # A fetch that hit the cap is recorded on `unacast_fetch_coverage.truncated`;
    # this infers it from volume instead, which also flags a POI-day that is
    # close to the ceiling without having hit it. A feature can span several
    # days, so this is a floor on the real count.
    print(f"\n{bar}")
    print("3. TRUNCATION SUSPECTS (100k observations per feature, DIRECT)")
    print(bar)
    suspects = [(key, n) for key, n in poi_days.items() if n >= 90_000]
    print(f"  POI-days observed                     {len(poi_days):>11,}")
    print(f"  POI-days at >=90k pings               {len(suspects):>11,}")
    for (poi_key, day), n in sorted(suspects, key=lambda kv: -kv[1])[:10]:
        print(f"    {poi_key[:16]}  {day}  {n:>10,}")
    busiest = sorted(poi_days.items(), key=lambda kv: -kv[1])[:5]
    print("\n  busiest POI-days:")
    for (poi_key, day), n in busiest:
        print(f"    {poi_key[:16]}  {day}  {n:>10,}")
    report["poi_days"] = len(poi_days)
    report["truncation_suspects"] = len(suspects)
    report["busiest_poi_days"] = [
        {"poi_key": key[0], "day": str(key[1]), "pings": n} for key, n in busiest
    ]

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, default=str)
        print(f"\nJSON written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
