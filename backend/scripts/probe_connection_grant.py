"""
scripts/probe_connection_grant.py
─────────────────────────────────
Find out what a connected Meta token can ACTUALLY do, before guessing at why a
publish was refused.

What a connection carries is decided by the login configuration in the App
Dashboard (Facebook Login for Business → Configurations), not by the ``scope=``
Punk sends, and what the APP may do with those permissions is decided by its
access level (Standard vs Advanced). Neither is visible from the code. Both fail
the same way at publish time — a ``(#200)``, ``(#10)`` or ``(#3)`` — and need
opposite fixes, so this prints the evidence instead:

  1. the grant       — scopes vs ``REQUIRED_SCOPES``. A non-empty "missing" line is
                       the whole bug; everything below is downstream of it.
  2. granular assets — which Pages / ad accounts each permission was granted on.
  3. page tokens     — ``me/accounts`` vs the ``granular_scopes`` fallback, the only
                       way a system-user token gets a Page token and never yet
                       verified against a real one.
  4. lead forms      — ``leadgen_forms`` with the user token vs the Page token. A
                       ``(#190) ... Page Access Token`` on the first line proves
                       ``create_lead_form`` needed the trade.
  5. custom audience terms — which field, if any, reports whether the ad account
                       has accepted them. Decides whether the check can happen at
                       connect or must stay a "confirm it yourself" card.
  6. lead match quality — for a dataset that has received ``Lead`` events.
  7. Page readiness  — ``is_published`` / ``tasks`` on the Page, so page_unpublished and
                       page_role_missing could be raised before publish, not after.
                       (4b, plus 5b for the ad account's ``spend_cap`` / ``user_tasks``.)
  8. app webhooks    — with the APP token, whether ``page`` → ``leadgen`` is subscribed
                       at the app level and points at ``/tracking/webhook``. Without it
                       no lead ever arrives, whatever Punk does per Page.
  9. ad review       — for ``--ad-id``: the raw ``effective_status`` and
                       ``ad_review_feedback`` Meta returns, so the disapproval card is
                       written from a real payload.

Run it for TWO people — the app admin and a Tester — and compare. While the app is in
Development mode only people with an app role can connect at all; if the admin's output is
clean and the Tester's is not, the difference is the login configuration or a missing role on
the ad account / Page, which is what a publish ``(#200)`` / ``(#10)`` means for them.

Read-only. Nothing is created, and every failure is printed rather than raised.

**``acting_user`` is deliberately NOT bound.** Punk marks a connection dead on a
code-190 response for the bound user, and section 4 is expected to produce one —
binding it would log the account you are testing out.

    .venv/Scripts/python.exe scripts/probe_connection_grant.py --user-id <uuid>
    .venv/Scripts/python.exe scripts/probe_connection_grant.py --user-id <uuid> \
        --page-id 123 --form-id 456 --dataset-id 789
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import model_registry  # noqa: F401,E402  — registers every ORM model
from app.modules.ads.service import REQUIRED_SCOPES  # noqa: E402
from app.services import meta_ads as _meta  # noqa: E402
from app.services.oauth import get_meta_credentials  # noqa: E402

# One rung per attempt: asking for a field the account will not answer fails the
# WHOLE read, so a bad guess must not hide a good one.
TOS_RUNGS = (
    "tos_accepted",
    "tos_accepted,offsite_pixels_tos_accepted",
    "user_tos_accepted",
)


def _redact(text: str) -> str:
    """``me/accounts`` returns each Page's access_token, which acts as the Page — a
    probe transcript gets pasted into chats and PRs, so it must not carry them."""
    return re.sub(r'("access_token":\s*")[^"]+', r"\1<redacted>", text)


async def _try(label: str, endpoint: str, token: str, params: dict | None = None):
    try:
        result = await _meta._request(
            "GET", endpoint, token, json_data=params or {}, retries=1,
        )
    except _meta.MetaAdsError as exc:
        print(f"  {label:<34} FAIL  code={exc.code} subcode={exc.subcode}  {exc}")
        return None
    print(f"  {label:<34} OK    {_redact(json.dumps(result, default=str))[:300]}")
    return result


def _heading(text: str) -> None:
    print(f"\n── {text} " + "─" * max(0, 66 - len(text)))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-id", required=True)
    ap.add_argument("--page-id", default="", help="defaults to the connected Page")
    ap.add_argument("--form-id", default="", help="an existing instant form, for section 4")
    ap.add_argument("--dataset-id", default="", help="a dataset that has received Lead events")
    ap.add_argument("--ad-id", default="", help="a published ad, for section 9")
    args = ap.parse_args()

    creds = await get_meta_credentials(args.user_id)
    if not creds:
        print("No live Meta connection for that user.")
        return 1
    token = creds["access_token"]
    account = creds.get("ad_account_id") or ""
    page_id = args.page_id or str(creds.get("page_id") or "")
    print(f"graph     {_meta._BASE}")
    print(f"account   {account or 'none selected'}")
    print(f"page      {page_id or 'none'}")

    _heading("1. the grant")
    info = await _meta.fetch_token_info(token)
    granted = set(info["scopes"])
    print(f"  token type  {info['type'] or 'unknown'}   expires_at  {info['expires_at']}")
    if not granted:
        print("  scopes      UNKNOWN — debug_token failed; nothing below about scopes is proof")
    else:
        missing = [s for s in REQUIRED_SCOPES if s not in granted]
        print(f"  granted     {', '.join(sorted(granted))}")
        print(f"  MISSING     {', '.join(missing) or 'none'}")
        if missing:
            print("  → the login configuration is short. Fix it in the App Dashboard; "
                  "a reconnect changes nothing until it is fixed.")

    _heading("2. granular assets")
    for entry in info["granular_scopes"]:
        targets = entry.get("target_ids") or []
        print(f"  {entry.get('scope', '?'):<26} {len(targets)} asset(s)  {targets[:5]}")
    if not info["granular_scopes"]:
        print("  none reported")

    # Assets the token was GRANTED vs assets it can REACH. A Page or ad account ticked at
    # consent shows up in granular_scopes; one created afterwards (or unticked) does not —
    # which decides whether "I made one, now what" needs a reconnect (U1).
    def _targets(*scopes: str) -> set[str]:
        return {
            str(t) for e in info["granular_scopes"] if e.get("scope") in scopes
            for t in (e.get("target_ids") or [])
        }

    granted_pages = _targets("pages_show_list", "pages_manage_ads", "pages_manage_metadata")
    granted_accounts = {a.removeprefix("act_") for a in _targets("ads_management", "ads_read")}
    reachable_accounts = {
        str(a.get("id", "")).removeprefix("act_") for a in (creds.get("accessible_accounts") or [])
    }
    print(f"  granted Pages         {sorted(granted_pages) or 'none'}")
    print(f"  granted ad accounts   {sorted(granted_accounts) or 'none'}")
    print(f"  reachable ad accounts {sorted(reachable_accounts) or 'none'}")
    if granted_accounts and reachable_accounts - granted_accounts:
        print("  → accounts Punk can list but the token was never granted — a publish to "
              "one will fail on permissions.")

    _heading("3. page tokens")
    raw = await _try("me/accounts", "me/accounts", token, {"fields": "id,access_token", "limit": 5})
    via_accounts = bool(raw and raw.get("data"))
    pages = await _meta.list_page_tokens(token)
    branch = "me/accounts" if via_accounts else "granular_scopes fallback"
    print(f"  list_page_tokens  {len(pages)} page token(s), via {branch if pages else 'NEITHER'}")
    if not pages:
        print("  → no Page token obtainable: no leadgen subscription, no form list, "
              "no form creation.")
    page_token = pages.get(page_id, "")

    _heading("4. lead forms — user token vs page token")
    if not page_id:
        print("  no Page to probe (pass --page-id)")
    else:
        await _try("leadgen_forms · user token", f"{page_id}/leadgen_forms", token,
                   {"fields": "id,name,status", "limit": 3})
        if page_token:
            await _try("leadgen_forms · page token", f"{page_id}/leadgen_forms", page_token,
                       {"fields": "id,name,status", "limit": 3})
        else:
            print("  leadgen_forms · page token         (no Page token to try)")
        if args.form_id:
            await _try("form leads · user token", f"{args.form_id}/leads", token, {"limit": 1})
            if page_token:
                await _try("form leads · page token", f"{args.form_id}/leads", page_token,
                           {"limit": 1})

    _heading("4b. page readiness (is_published / tasks)")
    # The edge Punk actually reads (``list_meta_pages``): me/accounts with the USER
    # token. A rung ladder for the same reason as everywhere else — one refused
    # field fails the whole read. The first OK line names what a new rung in
    # ``_PAGE_FIELD_LADDER`` could carry; if every rung fails but the single-Page
    # line below answers, the read has to move to a per-Page call.
    for fields in (
        f"id,name,is_published,tasks,{_meta._IG_FIELDS},{_meta._WHATSAPP_FIELDS}",
        "id,name,is_published,tasks",
        "id,name,is_published",
        "id,name,tasks",
    ):
        await _try("me/accounts · user token", "me/accounts", token,
                   {"fields": fields, "limit": 5})
    if not page_id:
        print("  no Page to probe")
    else:
        await _try("page fields · page token", page_id, page_token or token,
                   {"fields": "id,name,is_published,tasks"})

    _heading("5. custom audience terms")
    if not account:
        print("  no ad account selected")
    else:
        for fields in TOS_RUNGS:
            await _try(f"fields={fields}", _meta._act(account), token, {"fields": fields})
        print("  → the first OK line names a readable field. If every rung fails, the terms "
              "cannot be checked ahead of time and stay a 'confirm it yourself' card.")

    _heading("5b. account readiness (spend cap / role)")
    # spend_cap "0" means NO cap; amount_spent is a minor-unit string. user_tasks has
    # no precedent in Punk, so its shape is the point of this section.
    if not account:
        print("  no ad account selected")
    else:
        for fields in ("spend_cap,amount_spent,user_tasks", "spend_cap,amount_spent", "user_tasks"):
            await _try(f"fields={fields}", _meta._act(account), token, {"fields": fields})
        print("  → spend_cap/amount_spent answering is enough for the spend-limit card. "
              "Only wire a role check if user_tasks answers AND its values are understood.")

    _heading("6. lead match quality")
    if not args.dataset_id:
        print("  pass --dataset-id to read Event Match Quality for Lead")
    else:
        emq = await _meta.fetch_event_match_quality(args.dataset_id, token, event_name="Lead")
        print(f"  EMQ for Lead  {emq}")
        print("  → near 0 means a lead_id-only event teaches delivery nothing.")

    _heading("7. app-level webhook subscription")
    from app.core.config import settings

    app_token = f"{settings.META_APP_ID}|{settings.META_APP_SECRET}"
    subs = await _try("app subscriptions", f"{settings.META_APP_ID}/subscriptions", app_token)
    expect = f"{settings.BACKEND_PUBLIC_URL.rstrip('/')}/tracking/webhook"
    rows = (subs or {}).get("data") or []
    page_row = next((r for r in rows if r.get("object") == "page"), None)
    if page_row is None:
        print("  → NO `page` subscription: no leadgen event will ever arrive. Add it under "
              "App Dashboard → Webhooks.")
    else:
        fields = [f.get("name") for f in page_row.get("fields") or []]
        print(f"  page fields   {fields}")
        print(f"  callback      {page_row.get('callback_url')}")
        print(f"  expected      {expect}")
        if "leadgen" not in fields:
            print("  → `leadgen` is not subscribed on the page object.")
        if page_row.get("callback_url") != expect:
            print("  → callback URL differs from this deployment's /tracking/webhook.")

    _heading("9. ad review")
    if not args.ad_id:
        print("  pass --ad-id to read effective_status / ad_review_feedback")
    else:
        await _try("ad review", args.ad_id, token,
                   {"fields": "id,name,effective_status,ad_review_feedback"})

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
