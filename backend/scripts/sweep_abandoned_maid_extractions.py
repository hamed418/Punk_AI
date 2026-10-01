"""
scripts/sweep_abandoned_maid_extractions.py
────────────────────────────────────────────
Purge raw MAID identifiers from extractions nobody came back to.

The publish path already purges an extraction's raw `maids`/`observations` the
moment its audience is uploaded to Meta and the campaign publish succeeds — see
`maid_store.purge_maid_extraction`, called from
`graph/builder/executors/media.py`. That covers everything that gets used.

This covers everything that DOESN'T: a user who extracts an audience, looks at
the map, and never comes back. Nothing else purges that row — it would sit in
Postgres holding real device IDs indefinitely. `updated_at` is the signal: it
bumps on every store/update write (a live editing session keeps re-touching its
row), so a row that has been quiet for the age window is either published
already (and this is a no-op — `purge_maid_extraction` is idempotent) or truly
abandoned.

Dry run by default — prints what it would purge and touches nothing::

    .venv/Scripts/python.exe scripts/sweep_abandoned_maid_extractions.py

Add ``--confirm`` to actually purge::

    .venv/Scripts/python.exe scripts/sweep_abandoned_maid_extractions.py --confirm

``--days N`` overrides the default age window (7 days).

Meant to run on a schedule (daily is plenty — this is a low-volume cleanup,
not a hard real-time deletion SLA). No scheduler is wired up in this codebase
today (`arq` is a dependency but nothing registers a periodic job with it) —
run this from cron, a systemd timer, or whatever schedules `ingest_maids_to_
postgres.py`'s counterpart on the ingestion side.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

# Registers every ORM model before any query runs. Without this, a standalone
# script that only imports MaidExtraction hits SQLAlchemy's mapper
# configuration lazily on the first query, in whatever partial state THIS
# process's imports left the relationship graph in — some other model's
# relationship() referencing a class name never imported here fails to
# resolve, and MaidExtraction (which references nothing exotic itself) pays
# for it. Same failure class documented in services/oauth.py's error path;
# cleanup_test_publish.py avoids it by using raw SQL instead of the ORM.
import app.api.router  # noqa: F401,E402

from app.db.database import AsyncSessionLocal  # noqa: E402
from app.db.models import MaidExtraction  # noqa: E402
from app.services.maid_store import purge_maid_extraction  # noqa: E402

_DEFAULT_AGE_DAYS = 7


async def _find_abandoned(cutoff: datetime) -> list[dict]:
    """Rows not yet purged and not touched since before ``cutoff``."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(MaidExtraction).where(
                MaidExtraction.purged_at.is_(None),
                MaidExtraction.updated_at < cutoff,
            )
        )
        rows = result.scalars().all()
        return [
            {
                "id": str(r.id),
                "session_id": r.session_id,
                "maid_count": r.maid_count,
                "updated_at": r.updated_at,
            }
            for r in rows
        ]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=_DEFAULT_AGE_DAYS, help="age window in days (default 7)")
    parser.add_argument("--confirm", action="store_true", help="actually purge (default: dry run)")
    args = parser.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    abandoned = await _find_abandoned(cutoff)

    if not abandoned:
        print(f"Nothing to sweep — no un-purged extraction untouched since before {cutoff.isoformat()}.")
        return

    print(f"{len(abandoned)} extraction(s) untouched since before {cutoff.isoformat()}:")
    for row in abandoned:
        print(f"  {row['id']}  session={row['session_id']}  maid_count={row['maid_count']}  updated_at={row['updated_at']}")

    if not args.confirm:
        print("\nDry run — nothing purged. Re-run with --confirm to actually clear these.")
        return

    cleared = 0
    for row in abandoned:
        if await purge_maid_extraction(row["id"], reason="abandoned-row sweep"):
            cleared += 1
    print(f"\nPurged raw MAIDs from {cleared}/{len(abandoned)} extraction(s).")


if __name__ == "__main__":
    asyncio.run(main())
