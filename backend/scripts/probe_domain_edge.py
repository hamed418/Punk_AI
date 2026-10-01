"""
scripts/probe_domain_edge.py
────────────────────────────
Find out how to read a business's VERIFIED DOMAINS on the current Graph version.

``fetch_verified_domains`` calls ``GET /{business_id}/owned_domains``, which
answers ``(#100) Tried accessing nonexisting field (owned_domains)`` on v25.0
with a token carrying ``business_management``. That leaves the whole
``domain_not_verified`` remediation unreachable: Meta never errors on an
unverified domain, it just attributes fewer conversions, so this read is the only
way to know.

Two hypotheses, and the output tells them apart:

  1. **The edge was renamed or removed.** Then every candidate below fails, and
     the ones that do not exist at all fail differently — ``Unknown path
     components`` (code 2500) rather than ``nonexisting field`` (code 100).
     Meta uses "nonexisting field" for an edge it knows about but will not show
     you, which is why ``owned_domains`` failing that way is the interesting case.
  2. **The app lacks business asset access.** Then the same call starts working
     once the app is added to the business in Business settings → Apps, with no
     code change. Run this again after doing that; if ``owned_domains`` flips to
     OK, the fix is onboarding, not a new edge.

Read-only. Nothing is created, and every failure is printed rather than raised.

    .venv/Scripts/python.exe scripts/probe_domain_edge.py --user-id <uuid>
    .venv/Scripts/python.exe scripts/probe_domain_edge.py --user-id <uuid> \
        --business-id 1569319880963006
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import model_registry  # noqa: F401,E402  — registers every ORM model
from app.services import meta_ads as _meta  # noqa: E402
from app.services.oauth import get_meta_credentials  # noqa: E402

# Every spelling worth trying, plus one control. The control matters: a business
# node that answers NOTHING means the token cannot see the business at all, and
# then no result below says anything about the domains edge.
CONTROL = ("business node (control)", "", {"fields": "id,name,verification_status"})
EDGES = (
    "owned_domains",
    "domains",
    "verified_domains",
    "business_domains",
    "owned_domain",
    "pending_owned_domains",
    "agency_business_domains",
)


async def _try(label: str, endpoint: str, token: str, params: dict | None = None) -> bool:
    try:
        result = await _meta._request(
            "GET", endpoint, token, json_data=params or {}, retries=1,
        )
    except _meta.MetaAdsError as exc:
        print(f"  {label:<32} FAIL  {exc}")
        return False
    print(f"  {label:<32} OK    {json.dumps(result, default=str)[:300]}")
    return True


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-id", required=True)
    ap.add_argument(
        "--business-id",
        default="",
        help="defaults to the business behind the connected ad account",
    )
    args = ap.parse_args()

    creds = await get_meta_credentials(args.user_id)
    if not creds:
        print("No live Meta connection for that user.")
        return 1
    token = creds["access_token"]

    business_id = args.business_id
    with _meta.acting_user(args.user_id):
        if not business_id:
            account = creds.get("ad_account_id") or creds.get("selected_account") or ""
            business = await _meta.fetch_ad_account_business(account, token)
            business_id = str((business or {}).get("id") or "")
            if not business_id:
                print(f"Ad account {account} is not in a business portfolio — "
                      "there is no business to read domains from.")
                return 1

        scopes = await _meta.fetch_token_scopes(token)
        print(f"business  {business_id}")
        print(f"scopes    {', '.join(scopes) or 'unknown'}")
        print(f"graph     {_meta._BASE}")
        print("\nprobing:")

        label, suffix, params = CONTROL
        await _try(label, f"{business_id}{suffix}", token, params)
        found = []
        for edge in EDGES:
            if await _try(f"/{edge}", f"{business_id}/{edge}", token):
                found.append(edge)

    print()
    if found:
        print(f"USABLE: {', '.join(found)} — point fetch_verified_domains at the first one.")
        return 0
    print(
        "Nothing answered. If the control line above was OK, the token can see the\n"
        "business and the domains edge is genuinely closed to this app — add the app\n"
        "to the business (Business settings -> Apps) and run this again before\n"
        "concluding the edge is gone."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
