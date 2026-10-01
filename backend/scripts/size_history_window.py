"""
scripts/size_history_window.py
───────────────────────────────
What a longer MAID lookback window would actually cost, in shared Unacast
budget calls — answered BEFORE any default window is raised, not after.

Reuses ``unacast_query.estimate_cost`` rather than re-deriving the arithmetic:
it already plans through the SAME ``plan_requests``/``_contiguous_ranges`` the
real fetch uses, reading only the coverage watermark. Zero vendor calls, zero
new logic to drift from the real planner.

Expected shape of the answer (see ``_contiguous_ranges``, ``MAX_RANGE_DAYS =
90``, and ``plan_requests``, ``MAX_FEATURES_PER_REQUEST = 10``,
unacast_query.py): a contiguous run <=90 days is ONE feature per POI whether
it covers 7 days or 90, so calls are a step function in 90-day blocks, not
linear in days. This script exists to confirm that on the real POI set and
watermark rather than assume it.

Usage:

    .venv/Scripts/python.exe scripts/size_history_window.py
    .venv/Scripts/python.exe scripts/size_history_window.py --session <id>
    .venv/Scripts/python.exe scripts/size_history_window.py --windows 7,30,90,180

Read-only against the database and the coverage watermark. Never calls the
vendor — same guarantee ``estimate_cost`` itself makes.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DEBUG", "false")

from sqlalchemy import text                                     # noqa: E402
from app.db.database import AsyncSessionLocal                   # noqa: E402
from app.graph.maid_query import build_date_list                # noqa: E402
from app.graph.unacast_query import estimate_cost                # noqa: E402

_DEFAULT_WINDOWS = (7, 30, 60, 90, 180)


async def _load_pois(session_id: str | None) -> tuple[str | None, list[dict]]:
    """The newest extraction's POIs (or a named session's), or (None, [])."""
    where = "WHERE session_id = :sid" if session_id else ""
    sql = (
        f"SELECT session_id, pois FROM maid_extractions {where} "
        "ORDER BY created_at DESC LIMIT 1"
    )
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(text(sql), {"sid": session_id} if session_id else {})
        ).first()
    if row is None:
        return None, []
    return row[0], list(row[1] or [])


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--session", help="score a specific session's POIs instead of the newest extraction")
    ap.add_argument(
        "--windows", default=",".join(str(w) for w in _DEFAULT_WINDOWS),
        help="comma-separated lookback-day windows to price, e.g. 7,30,90,180",
    )
    args = ap.parse_args()

    windows = sorted({int(w) for w in args.windows.split(",") if w.strip()})

    session_id, pois = await _load_pois(args.session)
    if not pois:
        print("No maid_extractions row with POIs found — run an extraction first.")
        return 1

    today = date.today().isoformat()
    print(f"Pricing {len(pois)} POI(s) from session {session_id!r} against today={today}\n")
    print(f"{'window (days)':>14}  {'calls':>6}  {'features':>9}  {'cached_pois':>11}  {'eta_s':>7}")

    prev_calls: int | None = None
    for n in windows:
        dates = build_date_list(today, n)
        cost = await estimate_cost(dates, pois)
        note = ""
        if prev_calls is not None and cost["calls"] == prev_calls:
            note = "  (same as previous window — still inside one 90-day block)"
        print(
            f"{n:>14}  {cost['calls']:>6}  {cost['features']:>9}  "
            f"{cost['cached_pois']:>11}  {cost['eta_s']:>7}{note}"
        )
        prev_calls = cost["calls"]

    print(
        "\ncalls is a step function in 90-day blocks (MAX_RANGE_DAYS), not linear "
        "in days — a flat 'calls' column across several window sizes above means "
        "widening the lookback there is free in budget terms; the real cost of a "
        "longer window is the 100k-per-feature truncation ceiling and wall time, "
        "not the shared call budget."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
