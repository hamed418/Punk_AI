"""
scripts/capture_maid_baseline.py
────────────────────────────────
Record what a MAID extraction actually produced, as a diffable JSON baseline.

**Why the old numbers cannot be reused.** The 2026-09-09 live test recorded
3,506 devices narrowing to 1,277 under ``2+ visits``. That figure is no longer a
pass/fail gate, because four shipped changes move it *deliberately*:

  * the signal-quality gate drops ~15% of devices (drive-by and pings whose
    accuracy band is wider than the ring)
  * folding on ``Feature.id`` instead of an H3 cell removes ~13.7% of visits
    that were hexagon-boundary artifacts
  * a visit is now a session rather than a distinct day, which moved repeat
    visitors from 17% to 40%
  * ``required_history_days`` widens the purchase for trend/cadence filters

Diffing a new run against 1,277 would read a correct result as a regression. So
the first run after this lands **establishes** the baseline, and every later run
diffs against that file instead.

Usage — the extraction has to have run first, in the same database:

    # after a chat_autopilot run, capture by session
    .venv/Scripts/python.exe scripts/capture_maid_baseline.py --session <session_id>

    # or just take the most recent extraction
    .venv/Scripts/python.exe scripts/capture_maid_baseline.py --latest

    # compare a later run against a recorded baseline
    .venv/Scripts/python.exe scripts/capture_maid_baseline.py --latest \\
        --compare docs/baselines/flagship.json

Writes to ``--out`` when given, otherwise prints. Read-only against the database
and never calls the vendor.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DEBUG", "false")

from sqlalchemy import text                                    # noqa: E402
from app.db.database import AsyncSessionLocal                  # noqa: E402

# Numbers that legitimately drift run to run (timestamps, ids) are excluded from
# the diff; everything else is expected to be stable for the same prompt.
_VOLATILE = {"captured_at", "session_id", "extraction_id", "ledger"}


async def _extraction(session_id: str | None, latest: bool) -> dict | None:
    where = "WHERE session_id = :sid" if session_id else ""
    sql = (
        "SELECT id, session_id, maid_count, filtered_maid_count, audience_filter, "
        "       lookback_days, search_radius_km, pois, purged_at, created_at "
        f"FROM maid_extractions {where} ORDER BY created_at DESC LIMIT 1"
    )
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(sql), {"sid": session_id} if session_id else {})).one_or_none()
    if row is None:
        return None
    return {
        "extraction_id": str(row[0]),
        "session_id": row[1],
        "maid_count": row[2],
        "filtered_maid_count": row[3],
        "audience_filter": row[4],
        "lookback_days": row[5],
        "search_radius_km": row[6],
        "poi_count": len(row[7] or []),
        "purged": row[8] is not None,
        "created_at": str(row[9]),
    }


async def _ledger() -> dict:
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT period, calls_made, requests_made, observations_used, "
            "       provisional_reserved FROM unacast_usage_ledger "
            "ORDER BY period DESC LIMIT 1"
        ))).one_or_none()
        cache = (await db.execute(text(
            "SELECT count(*), count(distinct poi_key), count(distinct maid) "
            "FROM unacast_raw_observations"
        ))).one()
        coverage = (await db.execute(text(
            "SELECT count(*) FROM unacast_fetch_coverage"
        ))).scalar_one()
    return {
        "period": row[0] if row else None,
        "calls_made": row[1] if row else 0,
        "requests_made": row[2] if row else 0,
        "observations_used": row[3] if row else 0,
        "provisional_reserved": row[4] if row else 0,
        "cached_observations": cache[0],
        "cached_pois": cache[1],
        "cached_devices": cache[2],
        "coverage_rows": coverage,
    }


def _flatten(prefix: str, value, out: dict) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}" if prefix else k, v, out)
    else:
        out[prefix] = value


def _diff(old: dict, new: dict) -> list[str]:
    a: dict = {}
    b: dict = {}
    _flatten("", {k: v for k, v in old.items() if k not in _VOLATILE}, a)
    _flatten("", {k: v for k, v in new.items() if k not in _VOLATILE}, b)

    lines: list[str] = []
    for key in sorted(set(a) | set(b)):
        was, now = a.get(key, "—"), b.get(key, "—")
        if was != now:
            lines.append(f"  {key:38s} {was!s:>18} -> {now!s}")
    return lines


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--session", help="capture the extraction for this session id")
    group.add_argument("--latest", action="store_true", help="capture the most recent extraction")
    parser.add_argument("--out", help="write the baseline JSON here")
    parser.add_argument("--compare", help="diff against a previously recorded baseline")
    args = parser.parse_args()

    extraction = await _extraction(args.session, args.latest)
    if extraction is None:
        print("No extraction found — run the autopilot first, against this database.")
        return 1

    baseline = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        **extraction,
        "ledger": await _ledger(),
    }

    print(json.dumps(baseline, indent=2, default=str))

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(baseline, fh, indent=2, default=str)
        print(f"\nBaseline written to {args.out}")

    if args.compare:
        with open(args.compare, encoding="utf-8") as fh:
            previous = json.load(fh)
        changes = _diff(previous, baseline)
        print(f"\n{'=' * 60}\nDIFF vs {args.compare}\n{'=' * 60}")
        if not changes:
            print("  identical")
        else:
            print("\n".join(changes))

        # The ledger is excluded from the diff above because it is cumulative
        # and would differ on every run. Its DELTA is the number that matters:
        # "a second identical run makes zero vendor calls" is the cache property
        # that has held since the first live test, and it is the definition of
        # done for a re-run.
        before = previous.get("ledger") or {}
        after = baseline["ledger"]
        spent = (after.get("calls_made") or 0) - (before.get("calls_made") or 0)
        reqs = (after.get("requests_made") or 0) - (before.get("requests_made") or 0)
        print(f"\n  vendor calls since that baseline : {spent}")
        print(f"  real HTTP requests               : {reqs}")
        if spent == 0:
            print("  -> fully served from cache, which is the re-run DoD.")
        elif reqs > spent:
            print("  -> some calls were retried (429/5xx) — see UnacastClient.")

        if changes:
            print(
                "\nA difference is not automatically a regression — several "
                "shipped changes move these numbers on purpose. Record WHY each "
                "delta happened in docs/maid_signal_quality_baseline.md."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
