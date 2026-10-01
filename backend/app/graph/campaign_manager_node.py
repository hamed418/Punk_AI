"""
graph/campaign_manager_node.py
───────────────────────────────
ReAct-style agentic node for post-publish campaign management.

Design principles:
  - No directed pipeline — LLM decides which tools to call based on context
  - No interrupt() inside loop — turn-based permission gate avoids state-loss
    on checkpoint (local messages list would be lost on interrupt resume)
  - Credentials via contextvars — never in tool schemas or logs

Permission flow for WRITE operations:
  1. LLM proposes a write tool call
  2. Node exits loop early, writes cm_state["awaiting_write_tool"] to state
  3. Returns pending_action → chatbot presents it → user responds via /resume
  4. entry_node detects awaiting_write_tool → bypasses LLM → routes here
  5. Node checks last human message: confirmed → executes; rejected → cancels

Data flow to chatbot:
  Appends AIMessage(role="campaign_manager_context") to messages.
  chatbot_node extracts this tagged message and uses it as grounding context.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.config import get_stream_writer

from app.core.config import settings
from app.graph.campaign_manager_tools import (
    _cm_access_token,
    _cm_currency,
    _cm_ad_account_id,
    _cm_user_id,
)
from app.graph.prompts import (
    CAMPAIGN_MANAGER_PLANNING_CLAUSE,
    CAMPAIGN_MANAGER_SYSTEM_PROMPT,
    CAMPAIGN_MANAGER_MCP_CLAUSE,
)
from app.graph.state import (
    MAX_LLM_HISTORY,
    AgentState,
    PendingAction,
    is_conversational,
    is_internal,
)
from app.graph.usage import tracked_ainvoke
from app.graph.wizard_helpers import confirmation_intent
from app.services.entitlement import ad_account_is_paid
from app.services.meta_mcp import CampaignManagerToolSet, campaign_manager_tool_context
from app.services.oauth import get_meta_credentials


# ── LLM factories (mirrors nodes.py — duplicated to avoid import cycle) ────────

def _make_thinking_llm(budget: int = 8000, model: str | None = None) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=model or settings.GEMINI_MODEL_PRO,
        **settings.llm_auth,
        temperature=settings.GEMINI_TEMPERATURE,
        thinking_budget=budget,
        include_thoughts=True,
    )


def _split_gemini_thinking(content: Any) -> tuple[str, str]:
    if isinstance(content, str):
        return "", content
    thinking_parts: list[str] = []
    answer_parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            answer_parts.append(str(block))
            continue
        if block.get("type") == "thinking":
            thinking_parts.append(block.get("thinking", ""))
        else:
            answer_parts.append(block.get("text", ""))
    return "\n".join(thinking_parts), "\n".join(answer_parts)

logger = logging.getLogger(__name__)

# Planning calls (write_todos) consume loop iterations; budget accounts for
# 1-2 plan/update calls on top of real tool work.
_MAX_REACT_ITERATIONS = 10

# ── Credential resolution ──────────────────────────────────────────────────────


async def _resolve_credentials(state: AgentState) -> tuple[str, str]:
    """Return (access_token, ad_account_id), preferring the live DB row.

    ad_account_id is cached into user_info once (media.py, at account pick)
    and the session then reuses it forever since access_token alone doesn't
    go stale. If the user switches accounts later (PUT /me select_meta_id →
    AdsRepository.update_selected_account), that cached value goes stale while the
    DB's selected_account is current — so this always re-reads the DB when
    a user_id is available, and only falls back to the cached state value if
    that lookup comes back empty (DB down, or no user_id to key on).
    """
    user_info = dict(state.get("user_info") or {})
    access_token = user_info.get("meta_access_token") or ""
    ad_account_id = user_info.get("meta_ad_account_id") or ""

    user_id = state.get("user_id") or ""
    if user_id:
        creds = await get_meta_credentials(user_id)
        if creds:
            access_token = creds.get("access_token") or access_token
            ad_account_id = creds.get("ad_account_id") or ad_account_id

    return access_token, ad_account_id


# ── System context builder ─────────────────────────────────────────────────────


def _build_system_context(state: AgentState, active_campaign_id: str | None) -> str:
    lines: list[str] = []
    user_info = state.get("user_info") or {}
    ad_account_id = user_info.get("meta_ad_account_id") or ""
    if ad_account_id:
        lines.append(f"Connected Meta ad account ID: {ad_account_id}")
    meta_ids = state.get("meta_campaign_ids") or {}
    if meta_ids.get("campaign_id"):
        lines.append(f"Recently published campaign ID: {meta_ids['campaign_id']}")
        if meta_ids.get("adset_ids"):
            lines.append(f"Ad set IDs: {', '.join(meta_ids['adset_ids'])}")
    if active_campaign_id:
        lines.append(f"Currently active campaign focus: {active_campaign_id}")
    if user_info.get("business_name"):
        lines.append(f"Business: {user_info['business_name']}")
    return "\n".join(lines) if lines else "No campaign context available yet."


# ── Write action description ───────────────────────────────────────────────────


def _format_todos(todos: list[dict]) -> str:
    """Render a todo list as status-marked lines for the thinking stream."""
    mark = {"done": "[x]", "in_progress": "[~]", "pending": "[ ]"}
    return "\n".join(
        f"{mark.get(t.get('status'), '[ ]')} {t.get('content', '')}" for t in todos
    )


def _account_currency(state: AgentState) -> str:
    """The ad account's currency, as this session already resolved it.

    Written by the media wizard during a build. Empty for a session that never
    built anything, which the tools handle with a live read — this is only the
    cheap path, and the one the permission prompt can use before any tool runs.
    """
    return str((state.get("user_info") or {}).get("ad_account_currency") or "")


def _money(amount: float, currency: str) -> str:
    """An amount as the user must read it: never a bare "$".

    A hardcoded dollar sign on a CAD or BDT account describes a change the user
    is not making — and this string IS the permission prompt, so it has to name
    the same write that is about to happen. Same rule prompts.py already gives
    the model.
    """
    return f"{amount:.2f} {currency}".strip()


def _format_write_action(tool_name: str, tool_args: dict, currency: str = "") -> str:
    if tool_name == "apply_budget_change":
        budget_type = tool_args.get("budget_type", "daily")
        amount = tool_args.get("new_budget", 0)
        target_type = tool_args.get("target_type", "campaign")
        return (
            f"Change {budget_type} budget to **{_money(amount, currency)}** "
            f"for {target_type} `{tool_args.get('target_id', '')}`"
        )
    if tool_name == "apply_status_change":
        status = tool_args.get("new_status", "")
        target_type = tool_args.get("target_type", "campaign")
        return f"Set {target_type} `{tool_args.get('target_id', '')}` status to **{status}**"
    if tool_name == "apply_bid_adjustment":
        amount = tool_args.get("new_bid_cap", 0)
        return (
            f"Set bid cap to **{_money(amount, currency)}** "
            f"for ad set `{tool_args.get('adset_id', '')}`"
        )
    return f"Execute **{tool_name}** with: {json.dumps(tool_args, default=str)}"


def _tool_failure(prefix: str, exc: Exception) -> str:
    """A failed tool call, with the manual fix appended when there is one.

    Managing a live campaign hits the same walls publishing does — a disabled ad
    account, a spending limit, a permission the connected session never had — and
    none of them are things the agent can retry its way out of. Handing the model
    "Tool error: (#100) …" makes it apologise; handing it the steps makes it say
    what the user has to go do.
    """
    from app.services import meta_remediation
    from app.services.meta_ads import MetaAdsError

    # Only Meta's own refusals are worth asking the catalog about. A KeyError in
    # our own code is not a thing the user can go fix in Business Manager, and
    # asking would log a "no entry" line for every ordinary bug.
    found = (
        meta_remediation.resolve(exc, scope="manage")
        if isinstance(exc, MetaAdsError) else None
    )
    if not found:
        return f"{prefix}: {exc}"
    steps = " ".join(f"{i}. {s}" for i, s in enumerate(found.steps, 1))
    link = f" Link: {found.url}" if found.url and "{" not in found.url else ""
    return (
        f"{prefix}: {exc}\n\nThis is not retryable — the user has to do it in Meta. "
        f"{found.title}. {found.cause} Tell them: {steps}{link}"
    )


# ── Main node ──────────────────────────────────────────────────────────────────


async def campaign_manager_node(state: AgentState) -> dict[str, Any]:
    """
    ReAct campaign management agent. Decides its own tool-call path based on
    conversation context. Requires user confirmation before any write operation.
    """
    writer = get_stream_writer()
    writer({"type": "thinking", "content": "Campaign manager: starting..."})

    cm_state = dict(state.get("campaign_manager_state") or {})
    active_campaign_id: str | None = state.get("active_campaign_id")
    if not active_campaign_id:
        meta_ids = state.get("meta_campaign_ids") or {}
        active_campaign_id = meta_ids.get("campaign_id")

    # ── Resume path: pending write awaiting confirmation ───────────────────────
    if cm_state.get("awaiting_write_tool"):
        access_token, ad_account_id = await _resolve_credentials(state)
        if not access_token:
            return {
                "messages": [AIMessage(
                    content="No Meta Ads account connected. Please connect your Meta account first.",
                    additional_kwargs={"role": "campaign_manager_context"},
                )],
                "campaign_manager_state": {},
                "next_nodes": ["entry"],
            }
        _cm_access_token.set(access_token)
        _cm_ad_account_id.set(ad_account_id)
        _cm_user_id.set(state.get("user_id") or "")
        _cm_currency.set(_account_currency(state))
        planning_on = settings.CAMPAIGN_MANAGER_PLANNING_ENABLED
        # The MCP tool context spawns a stdio subprocess (~2-5s) before the
        # block body runs — emit a motion beat first so the wait shows activity.
        if settings.META_MCP_ENABLED:
            writer({"type": "thinking", "content": "Connecting to Meta Ads..."})
        async with campaign_manager_tool_context(
            access_token, ad_account_id, planning_enabled=planning_on,
        ) as tool_set:
            return await _handle_write_resume(
                state, cm_state, active_campaign_id, writer, tool_set,
            )

    # ── Fresh path: resolve credentials ───────────────────────────────────────
    access_token, ad_account_id = await _resolve_credentials(state)

    if not access_token:
        writer({"type": "thinking", "content": "Campaign manager: no Meta credentials found"})
        return {
            "messages": [AIMessage(
                content="No Meta Ads account connected. Please connect your Meta account first.",
                additional_kwargs={"role": "campaign_manager_context"},
            )],
            "campaign_manager_state": {},
            "next_nodes": ["entry"],
        }

    # Inject credentials into context vars for Punk-native tool functions
    _cm_access_token.set(access_token)
    _cm_ad_account_id.set(ad_account_id)
    _cm_user_id.set(state.get("user_id") or "")
    _cm_currency.set(_account_currency(state))

    # Also persist resolved credentials back to user_info for this session
    user_info = dict(state.get("user_info") or {})
    user_info["meta_access_token"] = access_token
    user_info["meta_ad_account_id"] = ad_account_id

    planning_on = settings.CAMPAIGN_MANAGER_PLANNING_ENABLED
    # MCP tool context spawns a stdio subprocess (~2-5s) before the block body
    # runs — emit a motion beat first so the wait shows activity.
    if settings.META_MCP_ENABLED:
        writer({"type": "thinking", "content": "Connecting to Meta Ads..."})
    async with campaign_manager_tool_context(
        access_token, ad_account_id, planning_enabled=planning_on,
    ) as tool_set:
        if tool_set.uses_mcp:
            writer({"type": "thinking", "content": "Campaign manager: Meta Ads MCP connected"})
        return await _run_react_loop(
            state=state,
            cm_state=cm_state,
            active_campaign_id=active_campaign_id,
            user_info=user_info,
            tool_set=tool_set,
            writer=writer,
            planning_on=planning_on,
        )


async def _run_react_loop(
    *,
    state: AgentState,
    cm_state: dict,
    active_campaign_id: str | None,
    user_info: dict,
    tool_set: CampaignManagerToolSet,
    writer: Any,
    planning_on: bool,
) -> dict[str, Any]:
    """ReAct loop for campaign manager using the provided tool set."""
    tool_calls_log: list[dict] = []

    # ── Build clean message list (filter internal-role messages) ──────────────
    # Ledger records stay: they are the build conversation, and this node reaching
    # a stale transcript is exactly what made it re-answer a resolved question.
    clean_history = [msg for msg in state.get("messages", []) if not is_internal(msg)]
    # Bounded — this list is re-sent on every one of up to _MAX_REACT_ITERATIONS
    # LLM calls. Safe to slice: every messages write here is an AIMessage and no
    # ToolMessage reaches state, so a cut cannot orphan a tool call.
    if len(clean_history) > MAX_LLM_HISTORY:
        clean_history = clean_history[:2] + clean_history[-MAX_LLM_HISTORY:]

    system_prompt = CAMPAIGN_MANAGER_SYSTEM_PROMPT
    if tool_set.uses_mcp:
        system_prompt += CAMPAIGN_MANAGER_MCP_CLAUSE
    if planning_on:
        system_prompt += CAMPAIGN_MANAGER_PLANNING_CLAUSE

    system_context = _build_system_context(state, active_campaign_id)
    messages: list = [
        SystemMessage(
            content=f"{system_prompt}\n\n--- Session Context ---\n{system_context}"
        ),
        *clean_history,
    ]

    llm = _make_thinking_llm(budget=10000)
    llm_with_tools = llm.bind_tools(tool_set.tools)

    for iteration in range(_MAX_REACT_ITERATIONS):
        writer({"type": "thinking", "content": f"Campaign manager: LLM iteration {iteration + 1}"})

        try:
            response, _usage = await tracked_ainvoke(
                llm_with_tools, messages,
                node_name="campaign_manager",
                writer=writer,
            )
        except Exception as exc:
            logger.error("campaign_manager_node LLM call failed: %s", exc)
            break

        thinking_text, _ = _split_gemini_thinking(response.content)
        if thinking_text:
            writer({"type": "thinking", "content": f"Campaign manager reasoning:\n{thinking_text}"})

        messages.append(response)

        if not response.tool_calls:
            writer({"type": "thinking", "content": "Campaign manager: no tool calls — loop complete"})
            break

        for tc in response.tool_calls:
            tool_name: str = tc["name"]
            tool_args: dict = tc["args"]
            tool_id: str = tc["id"]

            writer({"type": "thinking", "content": f"Campaign manager: tool -> {tool_name}"})

            if tool_name == "write_todos":
                todos = tool_args.get("todos", [])
                cm_state["todos"] = todos
                writer({"type": "thinking", "content": "Plan:\n" + _format_todos(todos)})
                messages.append(ToolMessage(
                    content="Plan recorded.", tool_call_id=tool_id, name=tool_name,
                ))
                continue

            if tool_name in tool_set.write_tools:
                if not await ad_account_is_paid(state.get("user_id"), user_info.get("meta_ad_account_id")):
                    pending = _subscription_required_pending()
                    writer({"type": "assistant_message", "content": pending["prompt"]})
                    writer({"type": "pending_action", "content": pending})
                    messages.append(ToolMessage(
                        content="Blocked: this ad account has no active Punk subscription. Reads still work.",
                        tool_call_id=tool_id, name=tool_name,
                    ))
                    return {
                        "messages": [AIMessage(
                            content=pending["prompt"],
                            additional_kwargs={"role": "campaign_manager_context"},
                        )],
                        "user_info": user_info,
                        "active_campaign_id": active_campaign_id,
                        "campaign_manager_state": cm_state,
                        "pending_action": pending,
                        "next_nodes": ["entry"],
                        "tool_calls_log": tool_calls_log,
                    }

                description = _format_write_action(
                    tool_name, tool_args, _account_currency(state),
                )
                pending = _write_permission_pending(tool_name, description)
                cm_state["awaiting_write_tool"] = {
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "description": description,
                    "todos": cm_state.get("todos", []),
                    "uses_mcp": tool_set.uses_mcp,
                }
                writer({"type": "assistant_message", "content": (
                    f"I'd like to make this change:\n\n{description}\n\n"
                    "Please confirm to apply it, or let me know if you'd prefer something different."
                )})
                writer({"type": "pending_action", "content": pending})

                return {
                    "messages": [AIMessage(
                        content=description,
                        additional_kwargs={"role": "campaign_manager_context"},
                    )],
                    "user_info": user_info,
                    "active_campaign_id": active_campaign_id,
                    "campaign_manager_state": cm_state,
                    "pending_action": pending,
                    "next_nodes": ["entry"],
                    "tool_calls_log": tool_calls_log,
                }

            tool_fn = tool_set.registry.get(tool_name)
            if tool_fn is None:
                result_str = f"Unknown tool: {tool_name}"
                log_status = "unknown_tool"
            else:
                try:
                    result = await tool_fn.ainvoke(tool_args)
                    result_str = json.dumps(result, default=str) if not isinstance(result, str) else result
                    log_status = "success"
                except Exception as exc:
                    result_str = _tool_failure("Tool error", exc)
                    log_status = "error"
                    logger.warning("campaign_manager tool %s failed: %s", tool_name, exc)

            tool_calls_log.append({
                "tool": tool_name,
                "args": tool_args,
                "status": log_status,
                "node": "campaign_manager",
            })
            messages.append(ToolMessage(
                content=result_str,
                tool_call_id=tool_id,
                name=tool_name,
            ))

            if tool_name in ("fetch_campaign_analytics", "get_insights") and tool_args.get("campaign_id"):
                active_campaign_id = tool_args["campaign_id"]
            elif tool_name == "get_insights" and tool_args.get("object_id"):
                active_campaign_id = tool_args["object_id"]
    else:
        logger.warning("campaign_manager_node: hit MAX_REACT_ITERATIONS (%d)", _MAX_REACT_ITERATIONS)
        writer({"type": "thinking", "content": "Campaign manager: iteration limit reached"})

    final_content = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            _, text = _split_gemini_thinking(msg.content)
            final_content = text.strip()
            if final_content:
                break

    if not final_content:
        final_content = "Campaign analysis complete — see details above."

    return {
        "messages": [AIMessage(
            content=final_content,
            additional_kwargs={"role": "campaign_manager_context"},
        )],
        "user_info": user_info,
        "active_campaign_id": active_campaign_id,
        "campaign_manager_state": {},
        "pending_action": None,
        "next_nodes": ["entry"],
        "tool_calls_log": tool_calls_log,
    }


# ── Write resume handler ───────────────────────────────────────────────────────

# Bounds how many unclear replies in a row keep a pending write alive before
# it's dropped outright — an off-topic reply must not resurrect a stale write
# forever, but it also must not be read as a rejection on the first miss.
_MAX_WRITE_REASKS = 2


def _subscription_required_pending() -> PendingAction:
    """The paywall shown when a write tool is proposed on an ad account with
    no active Punk subscription. Reads are unaffected — this only ever
    fires from inside the `write_tools` branch."""
    return {
        "action_type": "option_selection",
        "options": ["I've subscribed — try again", "Not now"],
        "prompt": (
            "This ad account doesn't have an active Punk subscription, so I "
            "can't make live changes to it — I can still read its campaigns "
            "and analytics. Subscribe it from Billing, then try again."
        ),
        "field": "subscription_required",
        "prefill": None,
        "stepper": None,
        "progress": None,
    }


def _write_permission_pending(tool_name: str, description: str) -> PendingAction:
    """The `permission` widget shown for a proposed write — shared by the
    initial ask and by a re-ask after an unclear resume reply, so the two
    can't drift apart."""
    return {
        "action_type": "permission",
        "options": [],
        "prompt": f"Apply this change?\n\n{description}",
        "field": f"cm_permission_{tool_name}",
        "prefill": None,
        "stepper": None,
        "progress": None,
    }


def _write_resume_decision(messages: list) -> str:
    """Classify the user's LAST real turn against a pending live
    budget/status/bid write: ``"yes"``, ``"no"``, or ``"unclear"``. Pulled out
    of `_handle_write_resume` as a pure function specifically so this money
    gate is unit-testable without standing up credentials/tool execution.

    A wizard answer must never be read as approval of a live write, so only a
    real conversational `HumanMessage` counts — `reversed(messages)` scans
    back to the nearest one and ignores everything else (tool messages,
    non-conversational system turns).

    `confirmation_intent("")` is `"yes"` BY DESIGN elsewhere — wizard_helpers.py's
    two form-flow callers use an empty reply to mean "accept the prefill",
    which is correct there. It is NOT correct here: if the scan finds no real
    conversational message at all, or finds one with empty content, this must
    NOT read as `"yes"` — a live write firing with no user turn behind it
    at all is the exact hazard this gate exists to close. Both cases return
    `"unclear"` (never `"yes"`), which only ever leaves the write pending or
    drops it honestly — it can never execute or silently cancel on its own.
    """
    last_human = ""
    for msg in reversed(messages or []):
        if isinstance(msg, HumanMessage) and isinstance(msg.content, str) and is_conversational(msg):
            last_human = msg.content
            break
    if not last_human.strip():
        return "unclear"
    return confirmation_intent(last_human)


async def _handle_write_resume(
    state: AgentState,
    cm_state: dict,
    active_campaign_id: str | None,
    writer: Any,
    tool_set: CampaignManagerToolSet,
) -> dict[str, Any]:
    """Execute, cancel, or re-ask a pending write operation based on the
    user's latest message.

    Reads `awaiting_write_tool` WITHOUT popping it — an "unclear" decision
    (an unrelated question, a reply the parser can't place either way) must
    leave the pending write standing so a later "yes" can still apply it.
    Popping unconditionally used to mean any off-topic reply destroyed the
    pending write and reported it back as "cancelled by user" — a
    cancellation the user never asked for.
    """
    pending_write = cm_state["awaiting_write_tool"]
    tool_name = pending_write["tool_name"]
    tool_args = pending_write["tool_args"]
    description = pending_write["description"]

    # Resolve credentials (needed for write tools)
    access_token, ad_account_id = await _resolve_credentials(state)
    _cm_access_token.set(access_token)
    _cm_ad_account_id.set(ad_account_id)
    _cm_user_id.set(state.get("user_id") or "")
    _cm_currency.set(_account_currency(state))

    decision = _write_resume_decision(state.get("messages", []))
    writer({"type": "thinking", "content": f"Campaign manager write resume: decision={decision}"})

    tool_calls_log: list[dict] = []

    if decision == "unclear":
        reasks = int(pending_write.get("reasks") or 0) + 1
        if reasks <= _MAX_WRITE_REASKS:
            cm_state["awaiting_write_tool"] = {**pending_write, "reasks": reasks}
            pending = _write_permission_pending(tool_name, description)
            writer({"type": "assistant_message", "content": (
                "I didn't catch a clear yes or no on that — still waiting to "
                f"hear on this:\n\n{description}\n\n"
                "Please confirm to apply it, or let me know if you'd prefer something different."
            )})
            writer({"type": "pending_action", "content": pending})
            return {
                "messages": [AIMessage(
                    content=f"Awaiting confirmation (unclear reply): {description}",
                    additional_kwargs={"role": "campaign_manager_context"},
                )],
                "campaign_manager_state": cm_state,
                "active_campaign_id": active_campaign_id,
                "pending_action": pending,
                "next_nodes": ["entry"],
                "tool_calls_log": tool_calls_log,
            }
        # Re-ask budget spent — drop it, honestly. Nothing ran and the user
        # never said no, so this must not read as "you cancelled this".
        context_content = (
            f"I haven't made this change yet — let me know when you'd like "
            f"me to apply it: {description}"
        )
        writer({"type": "thinking", "content": (
            "Campaign manager: write re-ask budget exhausted — dropping pending write"
        )})
        return {
            "messages": [AIMessage(
                content=context_content,
                additional_kwargs={"role": "campaign_manager_context"},
            )],
            "campaign_manager_state": {"todos": pending_write.get("todos", [])},
            "active_campaign_id": active_campaign_id,
            "pending_action": None,
            "next_nodes": ["entry"],
            "tool_calls_log": tool_calls_log,
        }

    if decision == "yes":
        # Re-checked here, not just when the write was first proposed — the
        # subscription can lapse in the time it takes the user to reply "yes".
        if not await ad_account_is_paid(state.get("user_id"), ad_account_id):
            pending = _subscription_required_pending()
            writer({"type": "assistant_message", "content": pending["prompt"]})
            writer({"type": "pending_action", "content": pending})
            return {
                "messages": [AIMessage(
                    content=pending["prompt"],
                    additional_kwargs={"role": "campaign_manager_context"},
                )],
                "campaign_manager_state": {"todos": pending_write.get("todos", [])},
                "active_campaign_id": active_campaign_id,
                "pending_action": pending,
                "next_nodes": ["entry"],
                "tool_calls_log": tool_calls_log,
            }

        tool_fn = tool_set.registry.get(tool_name)
        result_content = "Action cancelled — tool not found."
        if tool_fn:
            try:
                result = await tool_fn.ainvoke(tool_args)
                result_content = json.dumps(result, default=str) if not isinstance(result, str) else result
                log_status = "success"
            except Exception as exc:
                result_content = _tool_failure("Action failed", exc)
                log_status = "error"
                logger.error("campaign_manager write resume tool %s failed: %s", tool_name, exc)
            tool_calls_log.append({
                "tool": tool_name,
                "args": tool_args,
                "status": log_status,
                "node": "campaign_manager/write_resume",
            })
        context_content = f"Applied: {description}\n\nResult: {result_content}"
        writer({"type": "thinking", "content": f"Campaign manager: write applied — {tool_name}"})
    else:  # "no" — the only case this attributes a cancellation to the user.
        context_content = f"Action cancelled by user: {description}"
        writer({"type": "thinking", "content": "Campaign manager: write rejected by user"})

    return {
        "messages": [AIMessage(
            content=context_content,
            additional_kwargs={"role": "campaign_manager_context"},
        )],
        # Preserve the plan across the write round-trip; drop the resolved
        # awaiting_write_tool.
        "campaign_manager_state": {"todos": pending_write.get("todos", [])},
        "active_campaign_id": active_campaign_id,
        "pending_action": None,
        "next_nodes": ["entry"],
        "tool_calls_log": tool_calls_log,
    }
