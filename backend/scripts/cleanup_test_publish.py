"""
scripts/cleanup_test_publish.py
───────────────────────────────
Delete everything one publish created in a real Meta ad account.

A test publish leaves objects in five places — campaigns and ad sets and ads in
Ads Manager, the custom audience and its lookalike in Audiences, the Instant Form
on the Page. Deleting them by hand means three UIs and is how a demo MAID
audience survives a cleanup and later gets used for real.

``PublishLedger`` already records every id it created, and the ledger is
persisted to ``campaigns.publish_state``. This reads it back and deletes what it
names, in the reverse of creation order.

Dry run by default — it prints what it would delete and touches nothing::

    .venv/Scripts/python.exe scripts/cleanup_test_publish.py --user-id <uuid> --session <id>

Add ``--confirm`` to actually delete::

    .venv/Scripts/python.exe scripts/cleanup_test_publish.py --user-id <uuid> --session <id> --confirm

Deleting the campaign removes its ad sets and ads with it, so those are listed
for the record rather than deleted individually. Audiences and the Instant Form
are separate objects and are deleted explicitly.

This is a **test-cleanup** tool. It is not wired into the app and never runs
against a user's session automatically.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.database import AsyncSessionLocal  # noqa: E402
from app.services import meta_ads as _meta  # noqa: E402
from app.services.oauth import get_meta_credentials  # noqa: E402


async def _load_publish_state(session_id: str) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                # conversation_id, not session_id — the chat session id is stored
                # under the conversation column. Compared as text so a session id
                # that is not a well-formed uuid returns no rows instead of
                # raising InvalidTextRepresentation.
                text(
                    "SELECT publish_state FROM campaigns "
                    "WHERE conversation_id::text = :sid AND publish_state IS NOT NULL "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"sid": session_id},
            )
        ).scalar_one_or_none()
    if not row:
        return None
    return row if isinstance(row, dict) else json.loads(row)


async def _delete(kind: str, obj_id: str, token: str, *, confirm: bool) -> None:
    if not confirm:
        print(f"  would delete {kind:<18} {obj_id}")
        return
    try:
        await _meta._request("DELETE", obj_id, token)
        print(f"  deleted {kind:<18} {obj_id}")
    except _meta.MetaAdsError as exc:
        # Best effort, like _rollback_campaigns: an object already gone, or one
        # Meta refuses to delete, must not stop the rest of the cleanup.
        print(f"  FAILED  {kind:<18} {obj_id}: {exc}", file=sys.stderr)


async def main(user_id: str, session_id: str, *, confirm: bool) -> int:
    state = await _load_publish_state(session_id)
    if not state:
        print(f"no publish_state for session {session_id}", file=sys.stderr)
        return 1

    creds = await get_meta_credentials(user_id)
    if not creds:
        print(f"user {user_id} has no connected Meta account", file=sys.stderr)
        return 2
    token = creds["access_token"]

    # "campaigns" is the full map; "campaign_id" is the single-campaign shorthand
    # every older reader uses. An app-promotion split writes two, and cleaning up
    # only the first is how the second one survives.
    campaigns = list((state.get("campaigns") or {}).values())
    if not campaigns and state.get("campaign_id"):
        campaigns = [state["campaign_id"]]

    adsets = list((state.get("adsets") or {}).values())
    ads = list((state.get("ads") or {}).values())
    print(f"{'DRY RUN — ' if not confirm else ''}session {session_id}")
    print(f"  {len(ads)} ads and {len(adsets)} ad sets go with the campaigns")

    # Reverse of creation order. Campaigns first: deleting one takes its ad sets
    # and ads with it, so the audiences an ad set still references are free by the
    # time we reach them.
    for cid in campaigns:
        await _delete("campaign", str(cid), token, confirm=confirm)
    for key in ("lookalike_audience_id", "custom_audience_id", "lead_form_id"):
        if state.get(key):
            await _delete(key.removesuffix("_id"), str(state[key]), token, confirm=confirm)

    if not confirm:
        print("\nnothing was deleted — re-run with --confirm")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Delete everything one publish created in a real ad account."
    )
    parser.add_argument("--user-id", required=True, help="the publishing user's uuid")
    parser.add_argument("--session", required=True, help="chat session id")
    parser.add_argument(
        "--confirm", action="store_true",
        help="actually delete; without this the run only prints what it would do",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.user_id, args.session, confirm=args.confirm)))
