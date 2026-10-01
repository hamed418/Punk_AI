"""
scripts/sweep_unacast_raw_observations.py
─────────────────────────────────────────
Retention for the durable Unacast ping cache.

`maid_extractions` already has two paths that clear raw device identifiers: the
publish path (`maid_store.purge_maid_extraction`) and the abandoned-row sweep
(`sweep_abandoned_maid_extractions.py`).

`unacast_raw_observations` has neither, and it is the LARGER exposure of the
two: it is deliberately cross-campaign and never purged, so it accumulates real
advertiser IDs indefinitely and outlives every campaign that touched it. A
single two-POI test run put 287,000 rows and 39,023 devices in it.

    .venv/Scripts/python.exe scripts/sweep_unacast_raw_observations.py
    .venv/Scripts/python.exe scripts/sweep_unacast_raw_observations.py --confirm
    .venv/Scripts/python.exe scripts/sweep_unacast_raw_observations.py --days 90 --confirm

Dry run by default — prints what it would delete and touches nothing.

**Coverage rows are deleted in the SAME transaction as the observations they
cover.** Leaving the watermark behind would mark those POI-days as paid for while
their pings are gone, so a later extraction would read the day as covered, make
no call, and return an empty audience for a POI that actually has visitors —
silently, and permanently, because a covered day is never re-bought.

The default window matches the DIRECT endpoint's 90-day span cap, so nothing
still reachable in a single vendor request is deleted.

Scheduled in production by Cloud Scheduler calling
``POST /internal/maintenance/run`` — which invokes the SAME coroutine this CLI
does (``app.core.maintenance.sweep_raw_observations``), so there is one
implementation rather than a script and a service that can drift apart.

It is an endpoint rather than a background task because Cloud Run allocates CPU
only during a request (``cpu-throttling=true``) and tears down idle instances
(``minScale=0``), so a daily asyncio loop would not reliably fire.

This CLI stays the way to run it by hand, and is dry-run by default.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DEBUG", "false")


# Matches MAX_RANGE_DAYS in app/graph/unacast_query.py: the DIRECT endpoint
# cannot span more than 90 days in one request, so anything older cannot be
# part of a single live query anyway.
DEFAULT_RETENTION_DAYS = 90


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days", type=int, default=DEFAULT_RETENTION_DAYS,
        help=f"delete observations older than this many days (default {DEFAULT_RETENTION_DAYS})",
    )
    parser.add_argument(
        "--confirm", action="store_true",
        help="actually delete; without it this is a dry run",
    )
    args = parser.parse_args()

    if args.days < 1:
        print("--days must be at least 1 — refusing to delete the whole cache.")
        return 2

    # One implementation, shared with POST /internal/maintenance/run. The CLI is
    # a front end for it, not a second copy that can drift.
    from app.core.maintenance import sweep_raw_observations

    r = await sweep_raw_observations(days=args.days, confirm=args.confirm)

    print(f"retention window   : {r['days']} day(s), cutoff {r['cutoff']}")
    print(f"  older than cutoff: {r['observations_matched']:,} observation(s), "
          f"{r['devices_matched']:,} device(s)")
    print(f"coverage rows      : {r['coverage_matched']:,} older than cutoff")

    if not r["observations_matched"] and not r["coverage_matched"]:
        print("\nNothing to sweep.")
        return 0
    if not r["deleted"]:
        print("\nDry run — nothing deleted. Re-run with --confirm to apply.")
        return 0

    print(f"\nDeleted {r['observations_deleted']:,} observation(s) and "
          f"{r['coverage_deleted']:,} coverage row(s).")
    print("Those POI-days are now honestly re-buyable rather than covered-but-empty.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
