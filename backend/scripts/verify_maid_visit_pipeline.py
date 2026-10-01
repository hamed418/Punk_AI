"""
scripts/verify_maid_visit_pipeline.py
─────────────────────────────────────
End-to-end check of the post-API path against REAL cached observations.

Runs the actual production functions — the signal gate -> the ``poi_key`` fold ->
``cluster_visits`` -> ``compute_visit_stats`` — over whatever is already in
``unacast_raw_observations``, and prints the funnel. No vendor calls, no writes.

    .venv/Scripts/python.exe scripts/verify_maid_visit_pipeline.py
    .venv/Scripts/python.exe scripts/verify_maid_visit_pipeline.py --radius-m 100

Companion to scripts/measure_maid_signal_quality.py, which reports the raw
signal; this one reports what the pipeline builds out of it.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DEBUG"] = "false"

from sqlalchemy import text                                    # noqa: E402
from app.db.database import AsyncSessionLocal                  # noqa: E402
from app.graph.maid_query import (                             # noqa: E402
    cluster_visits,
    compute_visit_stats,
    visit_is_timed,
)
from app.graph.maid_signal import apply_gate, describe_gate    # noqa: E402


async def load(limit: int | None) -> list:
    sql = (
        "SELECT poi_key, maid, observed_at, forensic_flags "
        "FROM unacast_raw_observations ORDER BY maid, poi_key, observed_at"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    async with AsyncSessionLocal() as db:
        return (await db.execute(text(sql))).fetchall()


def build_visits(rows: list[dict]) -> dict:
    """Fold pings into visits on ``poi_key``, exactly as executors/maid.py does."""
    obs_ts: dict[tuple, list[str]] = defaultdict(list)
    row_index: dict[tuple, dict] = {}
    for row in rows:
        key = (row["maid"], row["poi_key"])
        obs_ts[key].append(row["ts"])
        if key not in row_index:
            row_index[key] = {"maid": row["maid"], "poi_key": row["poi_key"], "count": 0}
        row_index[key]["count"] += 1

    from datetime import datetime as _dt
    timelines: dict[str, list] = defaultdict(list)
    for (maid, _spot), ts_list in obs_ts.items():
        timelines[maid].extend(_dt.fromisoformat(t) for t in ts_list)
    for maid in timelines:
        timelines[maid].sort()

    for key, r in row_index.items():
        r["visits"] = cluster_visits(obs_ts[key], device_timeline=timelines.get(key[0]))
        r["days"] = sorted({t[:10] for t in obs_ts[key]})
    return row_index


def pct(a: float, b: float) -> str:
    return f"{(a / b * 100):5.1f}%" if b else "     -"


async def main() -> int:
    ap = argparse.ArgumentParser(description="Verify the MAID visit pipeline on real data.")
    ap.add_argument("--radius-m", type=float, default=100.0)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    print("Loading cached observations...", flush=True)
    raw = await load(args.limit)
    if not raw:
        print("unacast_raw_observations is empty — nothing to verify.")
        return 1

    # Shape it the way read_cached returns it.
    rows = [
        {
            "poi_key": poi_key, "maid": maid,
            "lat": 0.0, "lng": 0.0,
            "ts": ts.isoformat(), "forensic_flags": flags,
        }
        for poi_key, maid, ts, flags in raw
    ]

    bar = "=" * 68
    gate = describe_gate()
    print(f"\n{bar}\nFUNNEL — radius {args.radius_m:g} m\n{bar}")
    print(f"  gate: accuracy={gate['accuracy_mode']}, "
          f"excluding {', '.join(gate['excluded_flags']) or 'nothing'}")
    print(f"\n  pings fetched                {len(rows):>10,}")

    kept, stats = apply_gate(rows, args.radius_m)
    print(f"  pings after quality gate     {len(kept):>10,}  {pct(len(kept), len(rows))}")
    print(f"    - dropped by flags         {stats['dropped_flags']:>10,}")
    print(f"    - dropped by accuracy      {stats['dropped_accuracy']:>10,}")

    devices_in = len({r["maid"] for r in rows})
    devices_out = len({r["maid"] for r in kept})
    print(f"\n  devices before gate          {devices_in:>10,}")
    print(f"  devices after gate           {devices_out:>10,}  {pct(devices_out, devices_in)}")

    index = build_visits(kept)
    visits = sum(len(r["visits"]) for r in index.values())
    print(f"\n  visits                       {visits:>10,}")

    timed = sum(1 for r in index.values() for v in r["visits"] if visit_is_timed(v))
    print(f"  visits with measurable dwell {timed:>10,}  {pct(timed, visits)}")
    print("  (the rest are single-ping: dwell unknown)")

    measured = [v for r in index.values() for v in r["visits"] if visit_is_timed(v)]
    if measured:
        lower = sorted(v["dwell_lower_s"] for v in measured)
        widths = [
            v["dwell_upper_s"] - v["dwell_lower_s"]
            for v in measured if v.get("dwell_upper_s") is not None
        ]
        mid = lower[len(lower) // 2]
        print(f"\n  median measured dwell        {mid // 60:>7,} min")
        print(f"  max measured dwell           {lower[-1] // 60:>7,} min")
        if widths:
            widths.sort()
            print(f"  median dwell uncertainty     {widths[len(widths) // 2] // 60:>7,} min "
                  f"(upper minus lower bound)")

    summary = compute_visit_stats(list(index.values()))["summary"]
    print(f"\n  devices                      {summary['total_devices']:>10,}")
    print(f"  repeat visitors              {summary['repeat_visitor_count']:>10,}  "
          f"({summary['repeat_visitor_pct']}%)")
    print(f"  buckets                      {summary['buckets']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
