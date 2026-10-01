"""
scripts/live_publish_test.py
────────────────────────────
Publish a real campaign to a real ad account, verify it, and delete it.

The half of the audit that static analysis cannot do. It drives the actual
publish executor (``publish_campaign_to_meta``) rather than a reimplementation,
so what it proves is what users get.

Two runs:

  --positive   build a campaign, read it back from Meta, assert every object is
               PAUSED, then delete everything.
  --negative   submit a spec our own validation accepts and Meta rejects (a
               budget under the account's per-currency floor), then assert the ad
               account is left CLEAN — no orphan campaign. That is the rollback
               path, and it is the one thing only a live run can prove.

Safety, in three layers:

  1. ``META_PUBLISH_ACTIVATE=false`` in the environment keeps the final
     activation pass switched off, so nothing ever goes live. The script refuses
     to run without it.
  2. ``geo_data`` carries no ``maid_extraction_id``, so no custom audience and no
     lookalike is created. The MAIDs in this environment are demo data and
     uploading them could get the ad account banned.
  3. Every object created is deleted before the script exits, including on
     failure.

    .venv/Scripts/python.exe scripts/live_publish_test.py --user-id <uuid> --positive
    .venv/Scripts/python.exe scripts/live_publish_test.py --user-id <uuid> --negative
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.db import model_registry  # noqa: F401,E402  — registers every ORM model
from app.graph.builder.executors.media import (  # noqa: E402
    MetaPublishError,
    publish_campaign_to_meta,
)
from app.graph.meta_spec import CampaignSpec  # noqa: E402
from app.graph.meta_spec.enums import (  # noqa: E402
    BillingEvent,
    CallToAction,
    DestinationType,
    Objective,
    OptimizationGoal,
)
from app.graph.meta_spec.models import AdSetSpec, AdSpec, CreativeSpec, min_budget_cents  # noqa: E402
from app.services import meta_ads as _meta  # noqa: E402
from app.services.oauth import get_meta_credentials  # noqa: E402

# Traffic -> Website. Measured as accepted end to end (scripts/preflight_live_spec.py),
# needs no pixel, no app and no Page Terms of Service acceptance — so a failure
# here is our bug, not a missing prerequisite.
_OBJECTIVE = Objective.TRAFFIC


def _writer(event: dict) -> None:
    kind = event.get("type")
    if kind in ("update", "thinking"):
        print(f"   . {event.get('content')}")


async def _image_hash(ad_account_id: str, token: str) -> str:
    """A real uploaded image. Meta needs one before it will make a creative."""
    from PIL import Image

    path = Path(tempfile.gettempdir()) / "punk_live_publish_test.png"
    Image.new("RGB", (600, 600), (32, 32, 48)).save(path)
    return await _meta.upload_image(str(path), ad_account_id, token)


def _spec(*, daily_budget: int, image_hash: str, link: str) -> CampaignSpec:
    start = datetime.now(timezone.utc) + timedelta(days=1)
    return CampaignSpec(
        name=f"[punk live test] {datetime.now(timezone.utc):%Y-%m-%d %H:%M}",
        objective=_OBJECTIVE,
        special_ad_categories=[],
        adsets=[AdSetSpec(
            name="Live test ad set",
            optimization_goal=OptimizationGoal.LINK_CLICKS,
            billing_event=BillingEvent.IMPRESSIONS,
            destination_type=DestinationType.WEBSITE,
            daily_budget=daily_budget,
            targeting={"geo_locations": {"countries": ["US"]}},
            start_time=start,
            ads=[AdSpec(name="Live test ad", creative=CreativeSpec(
                title="Live publish test",
                body="Created by scripts/live_publish_test.py and deleted again.",
                call_to_action=CallToAction.LEARN_MORE,
                link=link,
                image_hash=image_hash,
            ))],
        )],
    )


async def _tree(campaign_id: str, token: str) -> dict:
    return await _meta.fetch_campaign_tree(campaign_id, token)


def _campaign_ids(ids: dict | None) -> list[str]:
    """Every campaign id the publish reported, from both keys it uses.

    ``campaign_ids`` is the full list (an app plan splits into one campaign per
    store) and ``campaign_id`` is the scalar primary. Reading only the wrong one
    is not theoretical — the first run of this script looked for ``campaigns``,
    found nothing, skipped cleanup, and left a real campaign in the ad account.
    """
    out = [str(c) for c in ((ids or {}).get("campaign_ids") or []) if c]
    primary = (ids or {}).get("campaign_id")
    if primary and str(primary) not in out:
        out.append(str(primary))
    return out


async def _cleanup(ids: dict | None, token: str) -> None:
    """Delete the campaigns this run created. Ad sets and ads go with them."""
    found = _campaign_ids(ids)
    if not found:
        print("   NOTHING TO CLEAN UP — check this, a publish that created "
              "objects must report their ids")
    for cid in found:
        print(f"   deleting campaign {cid}")
        await _meta.delete_campaign(cid, token)
    for key in ("custom_audience_id", "lookalike_audience_id"):
        if (ids or {}).get(key):
            print(f"   deleting {key} {ids[key]}")
            try:
                await _meta._request("DELETE", str(ids[key]), token)
            except _meta.MetaAdsError as exc:
                print(f"   could not delete {key}: {exc}")


async def _account_campaign_ids(ad_account_id: str, token: str) -> set[str]:
    rows = await _meta.list_account_campaigns(ad_account_id, token, limit=200)
    return {str(r.get("id")) for r in rows if r.get("id")}


async def _publish_state_for(name: str) -> dict | None:
    """The ledger as it was persisted, read straight back out of Postgres.

    Keyed by the campaign name this run generated (it carries a timestamp), so a
    stale row from an earlier run cannot make the assertion pass.
    """
    from sqlalchemy import text

    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            text("SELECT publish_state FROM campaigns WHERE name = :n"),
            {"n": name},
        )).scalar_one_or_none()
    if row is None:
        return None
    import json as _json
    return row if isinstance(row, dict) else _json.loads(row)


async def _drop_test_drafts(name: str) -> None:
    from sqlalchemy import text

    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM campaigns WHERE name = :n"), {"n": name})
        await db.commit()


async def positive(user_info: dict, token: str, account: str, user_id: str) -> int:
    print("\n== POSITIVE: publish, verify, delete")
    hash_ = await _image_hash(account, token)
    print(f"   image uploaded: {hash_}")
    floor = min_budget_cents(user_info)
    spec = _spec(daily_budget=floor * 2, image_hash=hash_,
                 link=user_info.get("website_url") or "https://example.com")

    ids = await publish_campaign_to_meta(
        user_info=user_info,
        geo_data={},                      # no maid_extraction_id -> no audience
        marketing_plan=spec.model_dump(mode="json"),
        campaign_brief={},
        writer=_writer,
        # A real user id and thread, so the publish creates a draft row and
        # persists the ledger to campaigns.publish_state — the column an
        # autogenerate migration silently dropped (restored in d9e4a17c85b3).
        # With user_id=None the ledger stays in memory and this test proves
        # nothing about the persistence the whole retry design rests on.
        user_id=user_id,
        thread_id=f"live-publish-test-{datetime.now(timezone.utc):%Y%m%d%H%M%S}",
        allow_without_audience=True,
    )
    if not ids:
        print("   FAIL: publish returned nothing")
        return 1

    failures = 0
    try:
        campaigns = _campaign_ids(ids)
        print(f"   published campaigns: {campaigns}")
        if not campaigns:
            print("   FAIL: publish created objects but reported no campaign id")
            failures += 1
        for cid in campaigns:
            tree = await _tree(str(cid), token)
            statuses = [(tree.get("campaign") or {}).get("status")]
            statuses += [a.get("status") for a in tree.get("adsets", [])]
            statuses += [
                ad.get("status")
                for a in tree.get("adsets", []) for ad in a.get("ads", [])
            ]
            print(f"   {cid}: {len(tree.get('adsets', []))} ad set(s), statuses={statuses}")
            if any(s != "PAUSED" for s in statuses if s):
                print("   FAIL: something is not PAUSED")
                failures += 1
        if ids.get("activated"):
            print("   FAIL: activation ran with META_PUBLISH_ACTIVATE=false")
            failures += 1

        # The ledger has to have reached Postgres, or a failure part-way through
        # the next publish orphans everything and the retry builds a second
        # campaign — the exact failure the column exists to prevent, and the one
        # that was live until d9e4a17c85b3.
        state = await _publish_state_for(spec.name)
        if not state:
            print("   FAIL: nothing in campaigns.publish_state")
            failures += 1
        else:
            missing = [k for k in ("campaign_id", "adsets", "ads") if not state.get(k)]
            print(f"   publish_state: campaign_id={state.get('campaign_id')} "
                  f"adsets={state.get('adsets')} ads={state.get('ads')}")
            if missing:
                print(f"   FAIL: publish_state is missing {missing}")
                failures += 1
            elif str(state.get("campaign_id")) not in _campaign_ids(ids):
                print("   FAIL: publish_state names a different campaign")
                failures += 1
    finally:
        await _cleanup(ids, token)
        await _drop_test_drafts(spec.name)
    print("   OK" if not failures else f"   {failures} problem(s)")
    return 1 if failures else 0


async def negative(user_info: dict, token: str, account: str) -> int:
    """A spec we accept and Meta does not. The account must be left clean."""
    print("\n== NEGATIVE: forced preflight rejection, assert no orphans")
    hash_ = await _image_hash(account, token)
    # Legal locally (AdSetSpec only enforces a USD-derived sanity floor) and far
    # under this account's real per-currency minimum, so Meta rejects it at
    # preflight — subcode 1885272.
    spec = _spec(daily_budget=100, image_hash=hash_, link="https://example.com")
    print(f"   daily_budget=100 vs account floor {min_budget_cents(user_info)}")

    before = await _account_campaign_ids(account, token)
    ids = None
    try:
        ids = await publish_campaign_to_meta(
            user_info=user_info,
            geo_data={},
            marketing_plan=spec.model_dump(mode="json"),
            campaign_brief={},
            writer=_writer,
            user_id=None,
            thread_id=None,
            allow_without_audience=True,
        )
        print("   FAIL: Meta accepted a budget under its own floor")
        await _cleanup(ids, token)
        return 1
    except MetaPublishError as exc:
        print(f"   rejected at step={exc.step!r}: {str(exc)[:140]}")

    after = await _account_campaign_ids(account, token)
    orphans = after - before
    if orphans:
        print(f"   FAIL: {len(orphans)} orphan campaign(s) left behind: {sorted(orphans)}")
        for cid in orphans:
            await _meta.delete_campaign(cid, token)
        return 1
    print("   OK: ad account is clean")
    return 0


async def main(user_id: str, run_positive: bool, run_negative: bool) -> int:
    if settings.META_PUBLISH_ACTIVATE:
        print(
            "REFUSING: META_PUBLISH_ACTIVATE is true, so this would activate real "
            "ads. Set it false in .env before running a live publish test.",
            file=sys.stderr,
        )
        return 2

    creds = await get_meta_credentials(user_id)
    if not creds:
        print(f"user {user_id} has no connected Meta account", file=sys.stderr)
        return 2
    token, account = creds["access_token"], creds["ad_account_id"]
    currency = await _meta.fetch_ad_account_currency(account, token)
    user_info = {
        "meta_access_token": token,
        "meta_ad_account_id": account,
        "meta_page_id": creds.get("page_id"),
        "page_id": creds.get("page_id"),
        "business_name": "Punk live test",
        **currency,
    }
    print(f"{account}  currency={currency.get('currency') or '?'}  "
          f"floor={min_budget_cents(user_info)}  page={creds.get('page_id')}")

    rc = 0
    if run_positive:
        rc |= await positive(user_info, token, account, user_id)
    if run_negative:
        rc |= await negative(user_info, token, account)
    return rc


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[3])
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--positive", action="store_true")
    parser.add_argument("--negative", action="store_true")
    args = parser.parse_args()
    if not (args.positive or args.negative):
        args.positive = args.negative = True
    raise SystemExit(asyncio.run(main(args.user_id, args.positive, args.negative)))
