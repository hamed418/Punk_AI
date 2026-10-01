"""
services/meta_insights.py
─────────────────────────
Meta Graph API read + write functions for post-publish campaign management.

Supplements meta_ads.py with Insights API calls and update operations
used by the campaign_manager_node ReAct agent.

All functions return dicts or lists — never raise; errors are returned
as {"error": str} so the ReAct loop can handle them gracefully.
"""

from __future__ import annotations

import logging

from app.services.meta_ads import MetaAdsError, _act, _request

logger = logging.getLogger(__name__)

# What our `conversions` column counts. Meta reports one row per action type
# under `actions`, not a single "conversions" number — this is the same
# ambiguity `purchase_roas` has, just on the read side instead of the field
# name: pick the wrong set of action_types and "conversions" quietly means
# something else per objective.
_CONVERSION_ACTIONS = frozenset({
    "purchase", "omni_purchase", "offsite_conversion.fb_pixel_purchase",
    "lead", "onsite_conversion.lead_grouped", "complete_registration",
})

_SYNC_INSIGHT_FIELDS = "campaign_id,spend,impressions,clicks,actions,purchase_roas"

# ``purchase_roas``, not ``roas``. There is no bare ``roas`` field on Insights —
# Meta spells it purchase_roas / website_purchase_roas — and ONE unknown field
# fails the WHOLE read with code 100, the same trap documented on
# ``meta_ads.fetch_ad_account_currency``. Every caller here degrades to
# {"error": …}, so the bad name did not read as a broken field list; it read as an
# account with no data, forever.
_INSIGHT_FIELDS = ",".join([
    "impressions", "reach", "clicks", "ctr", "cpc", "cpm",
    "spend", "purchase_roas", "frequency", "actions",
])


# ── READ: insights ─────────────────────────────────────────────────────────────


async def get_campaign_insights(
    campaign_id: str,
    access_token: str,
    date_preset: str = "last_7d",
    fields: list[str] | None = None,
) -> dict:
    """Fetch performance metrics for a campaign from the Meta Insights API.

    date_preset values: last_7d, last_14d, last_30d, this_month, last_month, yesterday
    """
    field_str = ",".join(fields) if fields else _INSIGHT_FIELDS
    try:
        result = await _request(
            "GET",
            f"{campaign_id}/insights",
            access_token,
            json_data={"fields": field_str, "date_preset": date_preset},
        )
        data = result.get("data") or []
        return data[0] if data else {"note": "No insight data available for this period"}
    except MetaAdsError as exc:
        logger.warning("get_campaign_insights %s: %s", campaign_id, exc)
        return {"error": str(exc)}


async def get_adset_insights(
    adset_id: str,
    access_token: str,
    date_preset: str = "last_7d",
) -> dict:
    """Fetch performance metrics for a single ad set."""
    try:
        result = await _request(
            "GET",
            f"{adset_id}/insights",
            access_token,
            json_data={"fields": _INSIGHT_FIELDS, "date_preset": date_preset},
        )
        data = result.get("data") or []
        return data[0] if data else {"note": "No insight data available for this period"}
    except MetaAdsError as exc:
        logger.warning("get_adset_insights %s: %s", adset_id, exc)
        return {"error": str(exc)}


# ── READ: campaign structure ───────────────────────────────────────────────────


async def list_campaigns_for_account(
    ad_account_id: str,
    access_token: str,
) -> list[dict]:
    """List all campaigns for a Meta ad account with current config."""
    fields = "id,name,status,objective,daily_budget,lifetime_budget,created_time"
    try:
        result = await _request(
            "GET",
            f"{ad_account_id}/campaigns",
            access_token,
            json_data={"fields": fields},
        )
        return result.get("data") or []
    except MetaAdsError as exc:
        logger.warning("list_campaigns_for_account %s: %s", ad_account_id, exc)
        return []


async def get_account_campaign_insights(
    ad_account_id: str,
    access_token: str,
    date_preset: str = "maximum",
) -> dict[str, dict]:
    """Lifetime spend/impressions/clicks/conversions for every campaign on an
    account, in one paged call instead of one Insights call per campaign.

    Returns ``{campaign_id: row}``, empty on any failure — the sync this feeds
    must still write names/status even when metrics can't be fetched, same
    contract as every other function in this module.

    Query string, not a JSON body — a GET body silently drops fields and
    returns a different result set on this API (measured and documented on
    ``meta_ads.list_account_campaigns``), so this follows that endpoint's
    pattern rather than the ``json_data=`` one used elsewhere in this file.
    """
    query = f"fields={_SYNC_INSIGHT_FIELDS}&level=campaign&date_preset={date_preset}&limit=200"
    path = f"{_act(ad_account_id)}/insights?{query}"
    out: dict[str, dict] = {}
    for _ in range(50):
        try:
            result = await _request("GET", path, access_token)
        except MetaAdsError as exc:
            logger.warning("get_account_campaign_insights(%s): %s", ad_account_id, exc)
            break
        for row in result.get("data") or []:
            campaign_id = row.get("campaign_id")
            if campaign_id:
                out[str(campaign_id)] = row
        paging = result.get("paging") or {}
        after = (paging.get("cursors") or {}).get("after")
        if not after or not paging.get("next"):
            break
        path = f"{_act(ad_account_id)}/insights?{query}&after={after}"
    return out


async def get_campaign_details(
    campaign_id: str,
    access_token: str,
) -> dict:
    """Fetch current campaign configuration: status, budget, objective, spend cap."""
    fields = "id,name,status,objective,daily_budget,lifetime_budget,spend_cap"
    try:
        return await _request(
            "GET",
            campaign_id,
            access_token,
            json_data={"fields": fields},
        )
    except MetaAdsError as exc:
        logger.warning("get_campaign_details %s: %s", campaign_id, exc)
        return {"error": str(exc)}


async def get_campaign_adsets(
    campaign_id: str,
    access_token: str,
) -> list[dict]:
    """List all ad sets for a campaign with budget and optimization settings."""
    fields = "id,name,status,daily_budget,lifetime_budget,bid_amount,optimization_goal"
    try:
        result = await _request(
            "GET",
            f"{campaign_id}/adsets",
            access_token,
            json_data={"fields": fields},
        )
        return result.get("data") or []
    except MetaAdsError as exc:
        logger.warning("get_campaign_adsets %s: %s", campaign_id, exc)
        return []


# ── WRITE: campaign updates ────────────────────────────────────────────────────


async def update_campaign_budget(
    campaign_id: str,
    access_token: str,
    new_budget_cents: int,
    budget_type: str,
) -> bool:
    """Update campaign daily or lifetime budget. budget_type: 'daily' | 'lifetime'."""
    field = "daily_budget" if budget_type == "daily" else "lifetime_budget"
    try:
        await _request("POST", campaign_id, access_token, json_data={field: new_budget_cents})
        return True
    except MetaAdsError as exc:
        logger.error("update_campaign_budget %s: %s", campaign_id, exc)
        return False


async def update_campaign_status(
    campaign_id: str,
    access_token: str,
    status: str,
) -> bool:
    """Set campaign status. status: 'ACTIVE' | 'PAUSED' | 'ARCHIVED'."""
    try:
        await _request("POST", campaign_id, access_token, json_data={"status": status})
        return True
    except MetaAdsError as exc:
        logger.error("update_campaign_status %s: %s", campaign_id, exc)
        return False


async def update_adset_budget(
    adset_id: str,
    access_token: str,
    new_budget_minor: int,
    budget_type: str,
) -> bool:
    """Update ad set daily or lifetime budget. budget_type: 'daily' | 'lifetime'.

    The ad-set twin of ``update_campaign_budget``, and the reason it exists: the
    budget tool used to route ad sets to ``update_adset_bid``, so approving
    "change the daily budget" set a BID CAP and flipped the bid strategy to
    COST_CAP on a live ad set. Two different intents, two different writes.

    ``new_budget_minor`` is minor units of the AD ACCOUNT's currency, never USD
    cents — Meta reads every amount in the account's own currency.

    An ad set inside a campaign-budget (CBO) campaign has no budget of its own;
    Meta refuses the write and this returns False with the reason logged, like
    every other update here.
    """
    field = "daily_budget" if budget_type == "daily" else "lifetime_budget"
    try:
        await _request("POST", adset_id, access_token, json_data={field: new_budget_minor})
        return True
    except MetaAdsError as exc:
        logger.error("update_adset_budget %s: %s", adset_id, exc)
        return False


async def update_adset_status(
    adset_id: str,
    access_token: str,
    status: str,
) -> bool:
    """Set ad set status. status: 'ACTIVE' | 'PAUSED' | 'ARCHIVED'."""
    try:
        await _request("POST", adset_id, access_token, json_data={"status": status})
        return True
    except MetaAdsError as exc:
        logger.error("update_adset_status %s: %s", adset_id, exc)
        return False


async def update_adset_bid(
    adset_id: str,
    access_token: str,
    bid_cap_cents: int,
) -> bool:
    """Update ad set bid cap and switch strategy to COST_CAP."""
    try:
        await _request(
            "POST",
            adset_id,
            access_token,
            json_data={"bid_amount": bid_cap_cents, "bid_strategy": "COST_CAP"},
        )
        return True
    except MetaAdsError as exc:
        logger.error("update_adset_bid %s: %s", adset_id, exc)
        return False
