"""The campaign manager's write tools — what the user approved is what happens.

These three tools are the only place in Punk where an LLM moves money on a live
campaign, and nothing covered them. Two defects lived here:

  * ``apply_budget_change`` routed an AD SET to ``update_adset_bid``, so
    approving "change the daily budget to 75" wrote a 75 bid cap and flipped the
    bid strategy to COST_CAP — a different write from the one the permission
    prompt described.
  * every amount was converted as ``* 100`` under the name ``new_budget_usd``,
    while Meta reads the AD ACCOUNT's own currency.

No network: ``meta_insights._request`` is the seam, the same way
``test_tracking_ingest`` fakes the CAPI sender.
"""
import pytest

from app.graph import campaign_manager_tools as cmt
from app.graph.campaign_manager_node import _format_write_action
from app.services import meta_insights


@pytest.fixture
def graph(monkeypatch):
    """Capture what would be POSTed to Meta."""
    calls: list[dict] = []

    async def fake_request(method, endpoint, access_token, json_data=None, **kwargs):
        calls.append({
            "method": method,
            "endpoint": endpoint,
            "access_token": access_token,
            "json": json_data or {},
        })
        return {"success": True}

    monkeypatch.setattr(meta_insights, "_request", fake_request)

    cmt._cm_access_token.set("token-1")
    cmt._cm_ad_account_id.set("act_123")
    cmt._cm_currency.set("CAD")
    return calls


# ── an ad set budget is a budget ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_adset_budget_change_writes_a_budget_not_a_bid_cap(graph):
    """The regression this file exists for. A bid cap and a budget are different
    buttons in Ads Manager and different money in the auction."""
    result = await cmt.apply_budget_change.ainvoke({
        "target_id": "6789",
        "new_budget": 75.0,
        "budget_type": "daily",
        "target_type": "adset",
    })

    assert result["success"]
    assert graph[0]["endpoint"] == "6789"
    assert graph[0]["json"] == {"daily_budget": 7500}
    # The two fields that used to be written instead.
    assert "bid_amount" not in graph[0]["json"]
    assert "bid_strategy" not in graph[0]["json"]


@pytest.mark.asyncio
async def test_a_lifetime_budget_names_the_lifetime_field(graph):
    await cmt.apply_budget_change.ainvoke({
        "target_id": "6789",
        "new_budget": 900.0,
        "budget_type": "lifetime",
        "target_type": "adset",
    })

    assert graph[0]["json"] == {"lifetime_budget": 90000}


@pytest.mark.asyncio
async def test_a_campaign_budget_still_goes_to_the_campaign(graph):
    await cmt.apply_budget_change.ainvoke({
        "target_id": "1111",
        "new_budget": 50.0,
        "budget_type": "daily",
        "target_type": "campaign",
    })

    assert graph[0]["endpoint"] == "1111"
    assert graph[0]["json"] == {"daily_budget": 5000}


@pytest.mark.asyncio
async def test_the_bid_tool_still_writes_a_bid_cap(graph):
    """Fixing the budget path must not take the bid path with it — a bid cap
    genuinely does set bid_amount and COST_CAP."""
    await cmt.apply_bid_adjustment.ainvoke({"adset_id": "6789", "new_bid_cap": 2.5})

    assert graph[0]["json"] == {"bid_amount": 250, "bid_strategy": "COST_CAP"}


# ── money is in the account's currency ───────────────────────────────────────


@pytest.mark.asyncio
async def test_the_result_names_the_currency_it_spent_in(graph):
    result = await cmt.apply_budget_change.ainvoke({
        "target_id": "6789",
        "new_budget": 75.0,
        "budget_type": "daily",
        "target_type": "adset",
    })

    assert result["currency"] == "CAD"
    assert result["new_budget"] == 75.0


@pytest.mark.asyncio
async def test_an_unknown_currency_is_read_not_assumed(graph, monkeypatch):
    """Empty for anyone who never built in this session — the returning
    advertiser managing an old campaign. Defaulting to USD there prices a BDT
    budget in the wrong money."""
    cmt._cm_currency.set("")

    async def currency(ad_account_id, access_token):
        assert ad_account_id == "act_123"
        return {"currency": "BDT"}

    from app.services import meta_ads

    monkeypatch.setattr(meta_ads, "fetch_ad_account_currency", currency)

    result = await cmt.apply_budget_change.ainvoke({
        "target_id": "6789",
        "new_budget": 1200.0,
        "budget_type": "daily",
        "target_type": "adset",
    })

    assert result["currency"] == "BDT"


def test_the_permission_prompt_never_shows_a_bare_dollar_sign():
    """This string IS the approval. It has to describe the write that follows."""
    description = _format_write_action(
        "apply_budget_change",
        {"target_id": "6789", "new_budget": 75.0, "budget_type": "daily",
         "target_type": "adset"},
        "CAD",
    )

    assert "75.00 CAD" in description
    assert "$" not in description


# ── the insights field list ──────────────────────────────────────────────────


def test_insights_asks_meta_for_fields_that_exist():
    """There is no bare ``roas`` field. One unknown name fails the WHOLE read
    with code 100, and every caller degrades to {"error": …} — so the bad list
    read as an account with no data rather than as a broken request."""
    fields = meta_insights._INSIGHT_FIELDS.split(",")

    assert "purchase_roas" in fields
    assert "roas" not in fields
