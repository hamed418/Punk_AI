"""
scripts/preflight_live_spec.py
──────────────────────────────
Put a real, fully-populated CampaignSpec past Meta's own validator.

This is the narrow half of the live publish test — the half that answers "can our
parameter list be one Meta refuses". It runs the exact two-stage preflight the
publish executor runs (``validate_campaign_payload`` then
``validate_adset_payload`` for every ad set), against a real connected account.

What it creates: one PAUSED, budget-less campaign, needed because ``/adsets``
validation requires a real parent id — deleted in a ``finally``. The ad sets are
never created; ``execution_options: ["validate_only"]`` means Meta checks the
payload and discards it. Nothing can spend.

What it does NOT cover: media upload, audience creation, the Instant Form, and
activation. Those need the chat flow and a real publish.

    .venv/Scripts/python.exe scripts/preflight_live_spec.py --user-id <uuid>
    .venv/Scripts/python.exe scripts/preflight_live_spec.py --user-id <uuid> \
        --objective OUTCOME_TRAFFIC
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Registers every ORM model. Without it SQLAlchemy cannot resolve the
# CreativeGenerationJob -> MediaFile relationship, mapper configuration raises,
# and get_meta_credentials swallows it and reports "not connected".
from app.db import model_registry  # noqa: F401,E402
from app.graph.meta_spec import CampaignSpec  # noqa: E402
from app.graph.meta_spec.enums import Objective  # noqa: E402
from app.graph.meta_spec.models import (  # noqa: E402
    AdSetSpec,
    AdSpec,
    CreativeSpec,
    min_budget_cents,
)
from app.graph.meta_spec.objective_matrix import matrix_for  # noqa: E402
from app.services import meta_ads as _meta  # noqa: E402
from app.services.oauth import get_meta_credentials  # noqa: E402


def _spec(objective: Objective, *, floor: int, page_id: str | None) -> CampaignSpec:
    """The richest spec the matrix allows for this objective.

    Deliberately not a minimal one: the whole question is whether a *detailed*
    plan — schedule, frequency cap, attribution, placements, several ad sets —
    survives, and a bare payload proves nothing about that.
    """
    rules = matrix_for(objective)
    dest = rules.default_destination
    goal = dest.default_optimization_goal
    start = datetime.now(timezone.utc) + timedelta(days=1)

    def creative() -> CreativeSpec:
        return CreativeSpec(
            title="Preflight headline",
            body="Body copy that a real plan would carry.",
            call_to_action=dest.default_call_to_action,
            link="https://example.com",
        )

    def adset(name: str, budget: int) -> AdSetSpec:
        return AdSetSpec(
            name=name,
            optimization_goal=goal,
            billing_event=dest.default_billing_event,
            destination_type=dest.destination_type,
            bid_strategy=rules.bid_strategies[0],
            daily_budget=budget,
            targeting={
                "geo_locations": {"countries": ["US"]},
                # Placements are the field this audit added a destination rule
                # for, so the live check should carry one.
                "publisher_platforms": ["facebook", "instagram"],
            },
            start_time=start,
            ads=[AdSpec(name=f"{name} ad", creative=creative())],
            promoted_object=(
                {"page_id": page_id}
                if page_id and dest.promoted_object_kind(goal) == "page"
                else None
            ),
        )

    return CampaignSpec(
        name=f"[punk preflight] {objective.value}",
        objective=objective,
        special_ad_categories=[],
        adsets=[adset("Seed", floor * 2), adset("Prospecting", floor * 3)],
    )


async def main(user_id: str, objectives: list[str]) -> int:
    creds = await get_meta_credentials(user_id)
    if not creds:
        print(f"user {user_id} has no connected Meta account", file=sys.stderr)
        return 2
    token = creds["access_token"]
    account = creds["ad_account_id"]
    page_id = creds.get("page_id")

    currency = await _meta.fetch_ad_account_currency(account, token)
    floor = min_budget_cents(currency)
    print(f"{account}  currency={currency.get('currency') or '?'}  "
          f"min daily budget={floor} (minor units)\n")

    failures = 0
    for name in objectives:
        objective = Objective(name)
        # ASCII: this prints through the console codepage (cp1252 on Windows).
        print(f"== {objective.value}")
        try:
            spec = _spec(objective, floor=floor, page_id=page_id)
        except Exception as exc:  # noqa: BLE001 — our own validation is the test
            print(f"   SPEC REJECTED LOCALLY: {exc}\n")
            failures += 1
            continue

        campaign_id = None
        try:
            await _meta.validate_campaign_payload(
                spec, ad_account_id=account, access_token=token
            )
            print("   campaign payload   OK")
            # A real parent id is required before Meta will look at an ad set.
            campaign_id = await _meta.create_campaign_from_spec(
                spec, ad_account_id=account, access_token=token
            )
            for idx, adset in enumerate(spec.adsets):
                await _meta.validate_adset_payload(
                    adset,
                    campaign_id=campaign_id,
                    ad_account_id=account,
                    access_token=token,
                    campaign_has_budget=spec.daily_budget is not None,
                )
                print(f"   adset[{idx}] payload  OK  ({adset.name})")
        except _meta.MetaAdsError as exc:
            print(f"   META REJECTED: {exc}")
            failures += 1
        finally:
            if campaign_id:
                await _meta.delete_campaign(campaign_id, token)
        print()

    print("all payloads accepted" if not failures else f"{failures} objective(s) rejected")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the real two-stage preflight against a live ad account."
    )
    parser.add_argument("--user-id", required=True)
    parser.add_argument(
        "--objective", action="append", dest="objectives",
        help="repeatable; defaults to every objective in the matrix",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(
        args.user_id, args.objectives or [o.value for o in Objective]
    )))
