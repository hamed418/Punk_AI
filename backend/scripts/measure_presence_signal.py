"""
scripts/measure_presence_signal.py
───────────────────────────────────
Per-category distributions for the presence-pattern role predicates
(``min_open_day_share``, ``min_intraday_span_min``, ``min_days_present`` —
see the role-inference plan) plus ``min_weekly_hours`` computed the SAME way
the evaluator computes it, over the real cached pings.

Runs the REAL production pipeline, not a local re-implementation: gate
(``maid_signal.apply_gate``), fold and per-category gap-clustering
(``executors/maid._new_fold``/``_fold_row``/``_finish_fold``, which is what
``run_maid_query`` itself calls) so this script cannot drift from what the
product actually does. ``measure_maid_signal_quality.py`` re-implements the
gate and the clustering locally for exactly this reason — don't repeat that
mistake here.

Category recovery: raw cache rows carry no category, only an opaque
``poi_key``/``center_key``. ``maid_extractions.pois`` (JSON, survives
``purge_maid_extraction``) is the durable source; ``_category_by_key`` already
resolves the shared-key collision (same coords+radius found under two search
labels) by keeping the tighter category's visit-gap threshold.

Output is in the filter's own units so a number here is directly
copy-pasteable into an ``AudienceFilter`` spec. Valley detection is 20 fixed
bins + a largest-gap split — no sklearn, no new dependency.

Usage:

    .venv/Scripts/python.exe scripts/measure_presence_signal.py
    .venv/Scripts/python.exe scripts/measure_presence_signal.py --days 30 --min-devices 10
    .venv/Scripts/python.exe scripts/measure_presence_signal.py --json out.json

Read-only against the database and the coverage cache. Never calls the vendor.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import date as _date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DEBUG", "false")

from sqlalchemy import text                                          # noqa: E402
from app.core.config import settings                                  # noqa: E402
from app.db.database import AsyncSessionLocal                         # noqa: E402
from app.graph.maid_query import gap_minutes_for, visit_is_timed      # noqa: E402
from app.graph.maid_signal import apply_gate                          # noqa: E402
from app.graph.unacast_query import poi_key, purchase_radius_m, read_cached  # noqa: E402
from app.graph.builder.executors.maid import (                        # noqa: E402
    _category_by_key, _finish_fold, _fold_row, _new_fold,
)
from app.services.maid_store import _local_shift                      # noqa: E402

_MIN_BIN_DEVICES = 20   # below this, a histogram is noise, not signal
_N_BINS = 20


def pct(part: int, whole: int) -> str:
    return f"{part / whole * 100:5.1f}%" if whole else "  0.0%"


async def _load_all_pois() -> list[dict]:
    """Every POI dict ever persisted on a ``maid_extractions`` row.

    Deliberately unscoped (not the latest session) and un-deduped going into
    category grouping — ``_category_by_key`` needs every (angle, label) a
    coordinate set was ever searched under to resolve collisions correctly.
    Purged rows still carry ``pois`` (``purge_maid_extraction`` clears
    ``maids``/``observations`` only), so this reaches every category a POI
    was ever bought under, not just live extractions.
    """
    async with AsyncSessionLocal() as db:
        rows = await db.execute(text("SELECT pois FROM maid_extractions"))
        out: list[dict] = []
        for (pois,) in rows:
            out.extend(pois or [])
    return out


def _valley(counts: list[int]) -> dict:
    """Two highest-count bins, the bin between them, and how deep the dip is.

    ``depth_ratio`` = valley bin / smaller of the two modes. <=0.6 is called a
    clear valley (matches the plan's stated cutoff); modes adjacent (no bin
    between them) means there's nothing to report a valley AT.
    """
    n = len(counts)
    top2 = sorted(range(n), key=lambda i: -counts[i])[:2]
    lo, hi = sorted(top2)
    if hi - lo < 2:
        return {"clear_valley": False, "reason": "the two densest bins are adjacent"}
    valley_bin = min(range(lo + 1, hi), key=lambda i: counts[i])
    valley_count = counts[valley_bin]
    smaller_mode = min(counts[lo], counts[hi])
    depth_ratio = valley_count / smaller_mode if smaller_mode else 1.0
    return {
        "clear_valley": depth_ratio <= 0.6,
        "mode_bins": [lo, hi],
        "valley_bin": valley_bin,
        "valley_threshold": round(valley_bin / n, 3),
        "depth_ratio": round(depth_ratio, 3),
    }


def _deciles(values: list[float]) -> dict | None:
    if len(values) < 10:
        return None
    qs = statistics.quantiles(values, n=10)
    return {
        "p10": round(qs[0], 2), "p50": round(qs[4], 2), "p90": round(qs[8], 2),
        "max": round(max(values), 2), "n": len(values),
    }


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=None,
                     help="lookback window in days (default: UNACAST_RAW_RETENTION_DAYS)")
    ap.add_argument("--min-devices", type=int, default=_MIN_BIN_DEVICES,
                     help="skip a category's histogram below this many devices")
    ap.add_argument("--json", dest="json_path", help="also write the report as JSON")
    args = ap.parse_args()

    all_pois = await _load_all_pois()
    if not all_pois:
        print("No maid_extractions.pois found — run an extraction first.")
        return 1

    key_to_poi: dict[str, dict] = {}
    for p in all_pois:
        k = poi_key(p)
        if k and k not in key_to_poi:
            key_to_poi[k] = p
    category_by_key = _category_by_key(all_pois)

    n_days = args.days or int(getattr(settings, "UNACAST_RAW_RETENTION_DAYS", 90) or 90)
    today = _date.today()
    # Ascending, oldest first: read_cached/_rings_join use days[0]/days[-1] as
    # the start/end of the query window directly (no internal sort, unlike
    # _dates_to_days) — a descending list silently inverts start > end and
    # matches nothing.
    days = sorted(today - timedelta(days=i) for i in range(1, n_days + 1))  # today dropped

    print(f"Loaded {len(key_to_poi)} distinct POI(s) across {len(set(category_by_key.values()))} "
          f"categor(y/ies); reading {n_days} day(s) of cache...\n")

    rows = await read_cached(key_to_poi, days)
    if not rows:
        print("Cache is empty for this window — nothing to measure.")
        return 1

    # Gate + fold: the exact real-pipeline sequence unacast_query/_fetch_gaps
    # and executors/maid.run_maid_query use — see this module's docstring.
    by_poi: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_poi[r["poi_key"]].append(r)

    fold = _new_fold()
    gate_kept = gate_total = 0
    for k, poi_rows in by_poi.items():
        poi = key_to_poi.get(k) or {}
        radius_m = float(purchase_radius_m(poi))
        kept, _stats = apply_gate(poi_rows, radius_m)
        gate_total += len(poi_rows)
        gate_kept += len(kept)
        for row in kept:
            row["radius_m"] = radius_m
            _fold_row(fold, row)

    fold_rows = _finish_fold(fold, category_by_key)
    print(f"Signal gate: kept {gate_kept:,} of {gate_total:,} ping(s) ({pct(gate_kept, gate_total)})\n")

    # Per-category, per-device accumulation.
    by_category: dict[str, list[dict]] = defaultdict(list)
    for r in fold_rows:
        cat = category_by_key.get(r["poi_key"])
        if cat:
            by_category[cat].append(r)

    report: dict = {"days": n_days, "gate_kept": gate_kept, "gate_total": gate_total, "categories": {}}
    weeks = max(n_days, 1) / 7.0

    for cat, cat_rows in sorted(by_category.items()):
        device_days: dict[str, set] = defaultdict(set)
        device_day_span: dict[str, dict] = defaultdict(dict)
        device_timed_hours: dict[str, float] = defaultdict(float)
        open_days_all: set = set()

        for r in cat_rows:
            poi = key_to_poi.get(r["poi_key"])
            poi_arg = [poi] if poi else None
            m = r["maid"]
            for v in r.get("visits") or []:
                try:
                    ts = datetime.fromisoformat(str(v["ts"]).replace("Z", "+00:00"))
                except (KeyError, ValueError):
                    continue
                local_ts = _local_shift(ts, poi_arg)
                day = local_ts.date()
                dwell_s = v.get("dwell_lower_s") or 0
                end_local = local_ts + timedelta(seconds=dwell_s)

                device_days[m].add(day)
                open_days_all.add(day)
                cur = device_day_span[m].get(day)
                device_day_span[m][day] = (
                    (min(cur[0], local_ts), max(cur[1], end_local)) if cur
                    else (local_ts, end_local)
                )
                if visit_is_timed(v):
                    device_timed_hours[m] += dwell_s / 3600.0

        n_open_days = len(open_days_all) or 1
        open_day_share: list[float] = []
        intraday_span_min: list[float] = []
        weekly_hours: list[float] = []
        days_present: list[float] = []

        for m, days_set in device_days.items():
            days_present.append(len(days_set))
            open_day_share.append(len(days_set) / n_open_days)
            spans = device_day_span[m].values()
            intraday_span_min.append(max(((e - s).total_seconds() / 60.0 for s, e in spans), default=0.0))
            weekly_hours.append(device_timed_hours[m] / weeks)

        n_devices = len(device_days)
        cat_report: dict = {"n_devices": n_devices, "operating_days_observed": n_open_days}

        if n_devices < args.min_devices:
            cat_report["insufficient_data"] = True
            print(f"── {cat} — {n_devices} device(s), below --min-devices {args.min_devices}, skipped ──\n")
            report["categories"][cat] = cat_report
            continue

        print(f"── {cat} — {n_devices} device(s), {n_open_days} operating day(s) observed ──")
        for label, values in (
            ("open_day_share", open_day_share),
            ("intraday_span_min", intraday_span_min),
            ("weekly_hours", weekly_hours),
            ("days_present", days_present),
        ):
            d = _deciles(values)
            cat_report[label] = d
            if d:
                print(f"  {label:20s} p10={d['p10']:>7}  p50={d['p50']:>7}  p90={d['p90']:>7}  max={d['max']:>7}")

        counts = [0] * _N_BINS
        for share in open_day_share:
            counts[min(_N_BINS - 1, int(share * _N_BINS))] += 1
        valley = _valley(counts)
        cat_report["open_day_share_valley"] = valley
        if valley["clear_valley"]:
            print(f"  open_day_share valley at {valley['valley_threshold']}  "
                  f"(depth_ratio={valley['depth_ratio']}) -> candidate min_open_day_share threshold")
        else:
            print(f"  no clear open_day_share valley ({valley.get('reason', 'depth_ratio too shallow')})")
        print()
        report["categories"][cat] = cat_report

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"Wrote {args.json_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
