"""
graph/campaign_manager_tools.py
────────────────────────────────
LangGraph @tool definitions for the campaign manager ReAct agent.

Credentials are injected via contextvars.ContextVar by campaign_manager_node
before the ReAct loop — never passed as tool arguments so they stay out of
the LLM-visible tool schema and out of logs.

READ tools: list_user_campaigns, fetch_campaign_analytics,
            fetch_adset_breakdown, get_campaign_settings

WRITE tools (permission gate enforced by campaign_manager_node, not here):
            apply_budget_change, apply_status_change, apply_bid_adjustment
"""

from __future__ import annotations

import contextvars
import logging
from typing import Any

from langchain_core.tools import tool
from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.graph.tools import retrieve_marketing_knowledge
from app.modules.campaigns.models import Campaign
from app.services.meta_insights import (
    get_adset_insights,
    get_campaign_adsets,
    get_campaign_details,
    get_campaign_insights,
    list_campaigns_for_account,
    update_adset_bid,
    update_adset_budget,
    update_adset_status,
    update_campaign_budget,
    update_campaign_status,
)

logger = logging.getLogger(__name__)

# ── Context variables — injected by campaign_manager_node before ReAct loop ────

_cm_access_token: contextvars.ContextVar[str] = contextvars.ContextVar(
    "cm_access_token", default=""
)
_cm_ad_account_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "cm_ad_account_id", default=""
)
_cm_user_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "cm_user_id", default=""
)
# The currency Meta reads this account's amounts in. Every budget and bid below
# used to be converted as though it were USD, which is simply a different number
# on a CAD or BDT account — and prompts.py already tells the model never to assume
# a USD account while the tools it calls did exactly that.
_cm_currency: contextvars.ContextVar[str] = contextvars.ContextVar(
    "cm_currency", default=""
)


async def _account_currency(access_token: str) -> str:
    """The ad account's currency — from the session, or read live.

    The contextvar is set from ``user_info["ad_account_currency"]``, which the
    media wizard resolves during a build. It is empty for someone who never built
    in this session — the returning advertiser managing an old campaign, which is
    most of this agent's traffic — so that case reads it rather than guessing.
    One Graph call, on a write the user has already approved.
    """
    cached = _cm_currency.get()
    if cached:
        return cached

    from app.services.meta_ads import fetch_ad_account_currency

    account = await fetch_ad_account_currency(_cm_ad_account_id.get(), access_token)
    currency = str(account.get("currency") or "")
    if currency:
        _cm_currency.set(currency)
    return currency


def _minor_units(amount: float) -> int:
    """An amount in the account currency → the minor units Meta wants.

    ponytail: ×100 is right for USD, CAD, BDT and every other two-decimal
    currency, and 100× wrong for a zero-decimal one (JPY, KRW). AdAccount does not
    expose ``currency_offset`` in v25 — see meta_ads.fetch_ad_account_currency —
    so the upgrade path is a small offset map keyed by currency, added the day a
    customer lands in one.
    """
    return int(round(amount * 100))


# ── READ tools ─────────────────────────────────────────────────────────────────


@tool
async def list_user_campaigns() -> list[dict]:
    """
    List all Meta ad campaigns for the user's connected ad account.

    Returns campaign names, IDs, statuses, objectives, and budget info.
    Call this first when the user has not specified a campaign, or to
    discover which campaigns exist (including from previous sessions).
    """
    access_token = _cm_access_token.get()
    ad_account_id = _cm_ad_account_id.get()
    user_id = _cm_user_id.get()

    # Meta API — authoritative, always cross-session
    meta_campaigns: list[dict] = []
    if access_token and ad_account_id:
        meta_campaigns = await list_campaigns_for_account(ad_account_id, access_token)

    # Local DB — enriches with PunkAI metadata (creation context, platform)
    db_by_ext_id: dict[str, dict] = {}
    if user_id:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Campaign).where(Campaign.user_id == user_id)
                )
                for row in result.scalars().all():
                    meta = {
                        "punk_id": str(row.id),
                        "punk_status": row.status,
                        "platform": str(row.platform),
                    }
                    # ext_campaign_id holds only the PRIMARY campaign. One draft
                    # can publish several — an app plan becomes one campaign per
                    # store — and the rest live in the publish ledger, so read
                    # both or the extra campaigns list from Meta unenriched.
                    ids = {row.ext_campaign_id} | set(
                        ((row.publish_state or {}).get("campaigns") or {}).values()
                    )
                    for ext_id in ids:
                        if ext_id:
                            db_by_ext_id[str(ext_id)] = meta
        except Exception as exc:
            logger.warning("list_user_campaigns DB query failed: %s", exc)

    # Merge: attach DB metadata where IDs match
    merged: list[dict] = []
    seen_ids: set[str] = set()
    for mc in meta_campaigns:
        cid = mc.get("id", "")
        seen_ids.add(cid)
        enriched = dict(mc)
        if cid in db_by_ext_id:
            enriched["punk_metadata"] = db_by_ext_id[cid]
        merged.append(enriched)

    # Include DB-only entries (old sessions not returned by Meta's list endpoint)
    for ext_id, meta in db_by_ext_id.items():
        if ext_id not in seen_ids:
            merged.append({"id": ext_id, **meta})

    return merged


@tool
async def fetch_campaign_analytics(
    campaign_id: str,
    date_range: str = "last_7d",
) -> dict:
    """
    Fetch performance metrics for a Meta campaign.

    Args:
        campaign_id: Meta campaign ID (e.g. "120213...")
        date_range: One of: last_7d, last_14d, last_30d, this_month, last_month, yesterday

    Returns: impressions, reach, clicks, CTR, CPC, CPM, spend, ROAS, frequency.
    """
    access_token = _cm_access_token.get()
    return await get_campaign_insights(campaign_id, access_token, date_preset=date_range)


@tool
async def fetch_adset_breakdown(
    campaign_id: str,
    date_range: str = "last_7d",
) -> list[dict]:
    """
    Fetch per-ad-set performance breakdown for a campaign.

    Use when diagnosing which ad set is underperforming or comparing
    performance across different audience segments.

    Args:
        campaign_id: Meta campaign ID — ad set IDs are resolved automatically
        date_range: Same presets as fetch_campaign_analytics
    """
    access_token = _cm_access_token.get()

    adsets = await get_campaign_adsets(campaign_id, access_token)
    if not adsets:
        return []

    results: list[dict] = []
    for adset in adsets[:10]:  # cap to avoid token bloat
        adset_id = adset.get("id", "")
        insights = await get_adset_insights(adset_id, access_token, date_preset=date_range)
        results.append({
            "adset_id": adset_id,
            "adset_name": adset.get("name", ""),
            "status": adset.get("status", ""),
            "insights": insights,
        })
    return results


@tool
async def get_campaign_settings(campaign_id: str) -> dict:
    """
    Fetch current campaign configuration: status, budget, objective, ad sets.

    Call this before suggesting changes so you know the current baseline.

    Args:
        campaign_id: Meta campaign ID
    """
    access_token = _cm_access_token.get()
    details = await get_campaign_details(campaign_id, access_token)
    adsets = await get_campaign_adsets(campaign_id, access_token)
    return {"campaign": details, "adsets": adsets}


# ── WRITE tools ────────────────────────────────────────────────────────────────
# Permission gate is enforced by campaign_manager_node BEFORE calling these.
# The docstrings flag them as write operations so the LLM knows to propose
# them explicitly rather than calling them silently.


@tool
async def apply_budget_change(
    target_id: str,
    new_budget: float,
    budget_type: str,
    target_type: str = "campaign",
) -> dict:
    """
    [WRITE OPERATION — do not call without user approval]
    Update the budget for a campaign or ad set.

    Args:
        target_id: Campaign or ad set ID
        new_budget: New budget in the AD ACCOUNT's own currency (e.g. 75.0 for
            75 per day). Never convert to USD — Meta reads the account's currency.
        budget_type: "daily" or "lifetime"
        target_type: "campaign" or "adset"
    """
    access_token = _cm_access_token.get()
    currency = await _account_currency(access_token)
    amount_minor = _minor_units(new_budget)

    # An ad set budget is a BUDGET. This used to call update_adset_bid, so a user
    # approving "change the daily budget to 75" got a 75 bid cap and a bid
    # strategy silently flipped to COST_CAP on a live ad set — a different write
    # from the one the permission prompt described.
    if target_type == "adset":
        success = await update_adset_budget(
            target_id, access_token, amount_minor, budget_type
        )
    else:
        success = await update_campaign_budget(
            target_id, access_token, amount_minor, budget_type
        )

    return {
        "success": success,
        "target_id": target_id,
        "target_type": target_type,
        "new_budget": new_budget,
        "currency": currency,
        "budget_type": budget_type,
    }


@tool
async def apply_status_change(
    target_id: str,
    new_status: str,
    target_type: str = "campaign",
) -> dict:
    """
    [WRITE OPERATION — do not call without user approval]
    Pause, activate, or archive a campaign or ad set.

    Args:
        target_id: Campaign or ad set ID
        new_status: "ACTIVE", "PAUSED", or "ARCHIVED"
        target_type: "campaign" or "adset"
    """
    access_token = _cm_access_token.get()

    if target_type == "adset":
        success = await update_adset_status(target_id, access_token, new_status)
    else:
        success = await update_campaign_status(target_id, access_token, new_status)

    return {
        "success": success,
        "target_id": target_id,
        "target_type": target_type,
        "new_status": new_status,
    }


@tool
async def apply_bid_adjustment(
    adset_id: str,
    new_bid_cap: float,
) -> dict:
    """
    [WRITE OPERATION — do not call without user approval]
    Update the bid cap on an ad set to control cost per result.

    Args:
        adset_id: Ad set ID
        new_bid_cap: New bid cap in the AD ACCOUNT's own currency (e.g. 2.50 for
            2.50 per result). Never convert to USD.
    """
    access_token = _cm_access_token.get()
    currency = await _account_currency(access_token)
    success = await update_adset_bid(
        adset_id, access_token, _minor_units(new_bid_cap)
    )
    return {
        "success": success,
        "adset_id": adset_id,
        "new_bid_cap": new_bid_cap,
        "currency": currency,
    }


# ── Planning (deep-agent scratchpad — no campaign side effects) ─────────────────
# A no-op tool the agent calls to record/track its plan before acting. Kept OUT
# of ALL_TOOLS / WRITE_TOOLS / TOOL_REGISTRY: it is bound conditionally (behind
# CAMPAIGN_MANAGER_PLANNING_ENABLED) and intercepted in campaign_manager_node
# BEFORE the registry dispatch, so it never needs a registry entry.


@tool
async def write_todos(todos: list[dict]) -> str:
    """
    Record or update your plan BEFORE acting, and after each milestone.
    Each todo: {"content": str, "status": "pending"|"in_progress"|"done"}.
    Call this FIRST on any multi-step task (diagnose -> analyze -> propose).
    Skip it only for a single trivial lookup. Does not change any campaign.
    """
    return "Plan updated."


# ── Registry (used by campaign_manager_node) ────────────────────────────────────

LEGACY_TOOLS: list[Any] = [
    list_user_campaigns,
    fetch_campaign_analytics,
    fetch_adset_breakdown,
    get_campaign_settings,
    apply_budget_change,
    apply_status_change,
    apply_bid_adjustment,
    # Grounded Meta Ads knowledge (policy changes, rejection reasons, product
    # questions) — same tool knowledge_based_node uses, bound here so the
    # campaign-manager ReAct agent can call it mid-analysis instead of
    # answering policy/product questions from its own (possibly stale) memory.
    retrieve_marketing_knowledge,
]

LEGACY_WRITE_TOOLS: frozenset[str] = frozenset({
    "apply_budget_change",
    "apply_status_change",
    "apply_bid_adjustment",
})

# Back-compat aliases for tests and imports.
ALL_TOOLS = LEGACY_TOOLS
WRITE_TOOLS = LEGACY_WRITE_TOOLS
TOOL_REGISTRY = LEGACY_TOOL_REGISTRY = {t.name: t for t in LEGACY_TOOLS}

# Bound conditionally by campaign_manager_node when planning is enabled.
PLANNING_TOOLS: list[Any] = [write_todos]
