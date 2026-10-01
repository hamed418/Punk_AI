"""
graph/usage.py
──────────────
Token usage tracking and cost estimation for all LangGraph LLM calls.

Provides tracked_ainvoke() as a drop-in replacement for llm.ainvoke() that:
  - Extracts usage_metadata from every Gemini response
  - Computes estimated USD cost (separating thinking vs non-thinking output tokens)
  - Returns a (response, record) tuple (record is debug-log only)

Whole-turn token accounting is handled OUTSIDE these wrappers: the chat
endpoints wrap each turn in LangChain's ``get_usage_metadata_callback()`` to
aggregate every LangChain LLM call (nodes, wizards, tools, preflight), then write
the totals into AgentState (``total_tokens`` / ``token_cost_usd`` reducers) and
the subscription meter. ``compute_cost()`` below is reused there for the USD figure.

That callback only sees calls made THROUGH LangChain. Gemini grounding
(``app.graph.grounding.grounded_text``) must use the raw google-genai SDK — the
google_search / google_maps tools are not reachable via ChatGoogleGenerativeAI —
so its tokens were billed by Google but invisible here. ``grounding_usage_callback``
below is the parallel accumulator for that path; the chat endpoints open both and
``_bill_usage`` sums them.

Pricing: MODEL_PRICING below, keyed by real model id (update it when Google revises
pricing or a model is added — an unknown model is charged at the priciest rate).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)

# ── Pricing ($ per 1M tokens), keyed by the REAL model id ────────────────────
# Vertex (Gemini Enterprise Agent Platform) standard tier, global endpoint,
# prompts <= 200k tokens — from Google's pricing page, checked 2026-09-24.
# Thinking (reasoning) tokens bill as output tokens, hence the equal rates.
# ponytail: the >200k-token context tier (2.5-pro out $15, 3.1-pro-preview
# in $4 / out $18) is not modelled — Punk prompts run ~20-40k. Add when a
# prompt can genuinely cross 200k.
# A model missing from this table is NOT priced as Flash: compute_cost logs an
# error and charges the priciest row, so a forgotten model over-reports.
def _price(inp: float, out: float) -> dict[str, float]:
    return {"input_per_million": inp, "output_per_million": out, "thinking_per_million": out}


MODEL_PRICING = {
    "gemini-2.5-flash":       _price(0.30, 2.50),
    "gemini-2.5-flash-lite":  _price(0.10, 0.40),
    "gemini-2.5-pro":         _price(1.25, 10.00),
    "gemini-3.5-flash":       _price(1.50, 9.00),
    "gemini-3.5-flash-lite":  _price(0.30, 2.50),
    "gemini-3.1-flash-lite":  _price(0.25, 1.50),
    "gemini-3.1-pro-preview": _price(2.00, 12.00),
}
_PRICIEST = max(MODEL_PRICING.values(), key=lambda p: p["output_per_million"])


def normalize_model_name(name: str | None) -> str:
    """Clean a model identifier to the bare id: drop any 'models/' or
    'publishers/<x>/models/' path and an '@version' suffix, lowercase.

    The result is the pricing key when the model is known, otherwise the cleaned
    id — it is never collapsed onto another model, so usage_events records the
    model that actually ran. ``None``/empty means "the default fast model".
    """
    if not name or not str(name).strip():
        from app.core.config import settings

        return settings.GEMINI_MODEL
    return str(name).strip().lower().rsplit("/", 1)[-1].split("@", 1)[0]


def _get_model_name(llm: Any) -> str:
    """Extract and normalize model name from LLM instance."""
    return normalize_model_name(getattr(llm, "model", None))


# ── Cost computation ──────────────────────────────────────────────────────────

def compute_cost(
    input_tokens: int,
    output_tokens: int,
    thinking_tokens: int = 0,
    model: str | None = None,
) -> float:
    """Estimate USD cost for one LLM call.

    thinking_tokens is a sub-count of output_tokens (reasoning-only).
    Non-thinking output = output_tokens - thinking_tokens, billed at the
    output rate; thinking tokens billed at the thinking rate (in Gemini,
    standard output rate).
    """
    model_key = normalize_model_name(model)
    pricing = MODEL_PRICING.get(model_key)
    if pricing is None:
        logger.error(
            "usage: no pricing for model %r — charging the priciest known rate. "
            "Add it to MODEL_PRICING.", model_key,
        )
        pricing = _PRICIEST
    non_thinking = max(output_tokens - thinking_tokens, 0)
    return (
        (input_tokens    / 1_000_000) * pricing["input_per_million"]
      + (non_thinking    / 1_000_000) * pricing["output_per_million"]
      + (thinking_tokens / 1_000_000) * pricing["thinking_per_million"]
    )


# ── Grounding usage (raw google-genai SDK) ────────────────────────────────────
# LangChain's usage callback cannot see raw-SDK calls, so grounding tokens were
# absent from AgentState entirely. This mirrors that callback for the grounding
# path: contextvar-scoped to one turn, opened by the chat endpoints.
#
# The accumulator is MUTATED, never reassigned. A ContextVar.set() inside a child
# task does not propagate back to the parent, but appending to a list the parent
# already put in the context does — which is what lets a tool call buried in a
# LangGraph node reach the endpoint's totals with no per-node plumbing.

_GROUNDING_USAGE: ContextVar[list | None] = ContextVar("grounding_usage", default=None)


@contextmanager
def grounding_usage_callback():
    """Collect raw-SDK grounding usage for the duration of one turn.

    Mirror of LangChain's ``get_usage_metadata_callback()`` for calls it cannot
    observe. Yields the accumulator; pass it to ``_bill_usage``.
    """
    acc: list[dict] = []
    token = _GROUNDING_USAGE.set(acc)
    try:
        yield acc
    finally:
        _GROUNDING_USAGE.reset(token)


def record_grounding_usage(model: str, usage_metadata: Any) -> None:
    """Record one grounded call's tokens into the active turn's accumulator.

    No-op when called outside a turn (tests, scripts, eval harnesses) — the
    contextvar is unset, so grounding tools stay usable standalone. Never raises:
    usage accounting must not be able to fail a user's turn.
    """
    acc = _GROUNDING_USAGE.get()
    if acc is None or usage_metadata is None:
        return
    try:
        def _n(attr: str) -> int:
            return int(getattr(usage_metadata, attr, 0) or 0)

        # google-genai field names AND semantics differ from LangChain's.
        #
        # tool_use_prompt is the search/maps tool's own prompt overhead — real
        # billed input, and the easy one to miss (absent from a non-grounded
        # response).
        #
        # thoughts_token_count is SEPARATE from candidates_token_count here,
        # whereas compute_cost (and LangChain's output_token_details.reasoning)
        # treats thinking as a SUB-COUNT of output. Verified on a live response:
        # prompt+tool_use=415, candidates=211, thoughts=206, total=832 = 415+211+206.
        # So fold thoughts into output to match compute_cost's contract — passing
        # candidates raw would price only (211-206)=5 tokens at the output rate.
        input_tokens = _n("prompt_token_count") + _n("tool_use_prompt_token_count")
        thinking_tokens = _n("thoughts_token_count")
        output_tokens = _n("candidates_token_count") + thinking_tokens
        # total_token_count is authoritative — Google may count parts our named
        # fields miss — but it omits tool_use_prompt on some responses, so take
        # whichever is larger rather than trusting either blindly.
        total_tokens = max(
            _n("total_token_count"), input_tokens + output_tokens,
        )

        acc.append({
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "thinking_tokens": thinking_tokens,
            "total_tokens": total_tokens,
        })
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("record_grounding_usage failed: %s", exc)


# ── API call counting (Google Places / Geocoding / grounding requests) ───────
# Same idiom as _GROUNDING_USAGE above — mutate-a-dict-the-parent-already-put-in-
# context, so a call buried in a @tool (no config access) still reaches the
# turn's totals with no per-call plumbing.

_API_CALLS: ContextVar[dict | None] = ContextVar("api_calls", default=None)


@contextmanager
def api_call_callback():
    """Collect Google API request counts for the duration of one turn.

    Yields the accumulator; pass it to ``_bill_usage``.
    """
    acc: dict[str, int] = {}
    token = _API_CALLS.set(acc)
    try:
        yield acc
    finally:
        _API_CALLS.reset(token)


def record_api_call(api: str, n: int = 1) -> None:
    """Record ``n`` billed requests to ``api`` in the active turn's accumulator.

    No-op when called outside a turn (tests, scripts, eval harnesses). Never
    raises: usage accounting must not be able to fail a user's turn.
    """
    acc = _API_CALLS.get()
    if acc is None:
        return
    try:
        acc[api] = acc.get(api, 0) + n
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("record_api_call failed: %s", exc)


# ── Who this turn belongs to ─────────────────────────────────────────────────
# Same idiom as the accumulators above, and as campaign_manager_tools._cm_user_id
# / meta_ads._ACTING_USER_ID: set once by the chat producer, read wherever it is
# needed, no per-call plumbing.
#
# This exists for VENDOR COST ATTRIBUTION (unacast_query.reconcile_call writes a
# UnacastCallLog row and needs to know who to bill it to). It cannot come from
# the billing path instead: `_bill_usage` runs at the END of a turn, only when
# tokens were spent, and skips its state write entirely while a subgraph
# interrupt is pending — which is how a MAID extraction almost always ends.
# Attribution has to be captured when the CALL happens.

_TURN_IDENTITY: ContextVar[tuple[str | None, str | None]] = ContextVar(
    "turn_identity", default=(None, None)
)


@contextmanager
def turn_identity(user_id: str | None, thread_id: str | None):
    """Scope ``(user_id, thread_id)`` to one turn."""
    token = _TURN_IDENTITY.set((user_id, thread_id))
    try:
        yield
    finally:
        _TURN_IDENTITY.reset(token)


def current_turn_identity() -> tuple[str | None, str | None]:
    """``(user_id, thread_id)`` for the turn in flight, or ``(None, None)``
    outside one — a script, the autopilot, a test.

    ``(None, None)`` is a real, recorded answer, not a failure: a call with no
    turn behind it still cost budget, and logging it unattributed is what lets
    "everything every user spent" be reconciled against "what the month cost".
    """
    return _TURN_IDENTITY.get()


def aggregate_grounding_usage(acc: Any) -> tuple[int, float]:
    """Sum an accumulator into ``(total_tokens, cost_usd)``.

    Reuses ``compute_cost`` so grounding is priced exactly like every other call.

    KNOWN GAP: Google bills Search grounding as a separate PER-REQUEST SKU on top
    of tokens. compute_cost only knows token pricing, so the USD here is a floor,
    not the true spend. Tokens are exact; cost is not. The request count itself
    IS tracked, though — see record_api_call / AgentState.google_api_calls —
    for whoever prices the SKU.
    """
    if not acc:
        return 0, 0.0
    total_tokens = 0
    total_cost = 0.0
    for rec in acc:
        total_tokens += rec.get("total_tokens", 0)
        total_cost += compute_cost(
            rec.get("input_tokens", 0),
            rec.get("output_tokens", 0),
            rec.get("thinking_tokens", 0),
            rec.get("model"),
        )
    return total_tokens, total_cost


# ── Tracked ainvoke ───────────────────────────────────────────────────────────

async def tracked_ainvoke(
    llm: Any,
    messages: list,
    *,
    node_name: str,
    writer: Any = None,
) -> tuple[Any, dict]:
    """Drop-in replacement for ``await llm.ainvoke(messages)``.

    Handles two response shapes:
      - AIMessage         — standard LLM call
      - {"raw": AIMessage, "parsed": Schema}
                          — structured output with include_raw=True

    Returns:
        (response, record)
        response — AIMessage or parsed Pydantic model (identical to plain ainvoke)
        record   — dict with token counts and cost for this call
    """
    result = await llm.ainvoke(messages)

    # Structured output: extract raw AIMessage for metadata, return parsed object
    is_structured = isinstance(result, dict) and "raw" in result and "parsed" in result
    raw_msg = result["raw"] if is_structured else result
    response = result["parsed"] if is_structured else result

    # A structured call that fails to parse returns parsed=None with NO exception —
    # silently swallowing it here let entry_node's extraction call return None,
    # merge zero fields, and never surface a log line (see the wholesale-coffee
    # thread: turn 1's business_description/target_audience/location all vanished
    # this way). Every include_raw=True call site already tolerates a raised
    # exception (try/except or asyncio.gather(..., return_exceptions=True)), so
    # raise instead of returning a silent None.
    if is_structured and response is None:
        logger.error(
            "tracked_ainvoke: structured output failed to parse (node=%s): %s",
            node_name, result.get("parsing_error"),
        )
        raise ValueError(f"{node_name}: structured output parse failed: {result.get('parsing_error')}")

    meta = getattr(raw_msg, "usage_metadata", None) or {}
    model = _get_model_name(llm)

    input_tokens    = meta.get("input_tokens", 0)
    output_tokens   = meta.get("output_tokens", 0)
    thinking_tokens = (meta.get("output_token_details") or {}).get("reasoning", 0)
    cost_usd        = compute_cost(input_tokens, output_tokens, thinking_tokens, model)

    record: dict = {
        "node":            node_name,
        "input_tokens":    input_tokens,
        "output_tokens":   output_tokens,
        "thinking_tokens": thinking_tokens,
        "cost_usd":        round(cost_usd, 8),
        "model":           model,
    }

    # NOTE: whole-turn usage is aggregated by the LangChain usage callback in
    # the chat endpoints; this record is debug-log only and NOT emitted as a
    # stream event.
    logger.debug("token_usage %s", record)

    return response, record


def _split_stream_content(content: Any) -> tuple[str, str]:
    """Return ``(thinking_text, answer_text)`` from a streamed Gemini chunk."""
    if isinstance(content, str):
        return "", content

    thinking_parts: list[str] = []
    text_parts: list[str] = []

    if isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                text_parts.append(block)
                continue
            if not isinstance(block, dict):
                text_parts.append(str(block))
                continue

            block_type = block.get("type", "")
            if block_type == "thinking":
                thinking_parts.append(block.get("thinking", ""))
            else:
                text_parts.append(block.get("text", ""))

    return "".join(thinking_parts), "".join(text_parts)


def _build_streamed_message(thinking_text: str, answer_text: str, usage_metadata: dict) -> AIMessage:
    """Create a normal AIMessage from streamed Gemini chunks."""
    if thinking_text:
        content: Any = [
            {"type": "thinking", "thinking": thinking_text},
            {"type": "text", "text": answer_text},
        ]
    else:
        content = answer_text

    try:
        return AIMessage(content=content, usage_metadata=usage_metadata)
    except Exception:
        # Older/langchain-compatible fallback if usage_metadata validation changes.
        msg = AIMessage(content=content)
        try:
            msg.usage_metadata = usage_metadata
        except Exception:
            pass
        return msg


async def tracked_astream(
    llm: Any,
    messages: list,
    *,
    node_name: str,
    writer: Any = None,
    emit_assistant: bool = False,
    emit_thinking: bool = False,
    thinking_source: str = "gemini",
) -> tuple[AIMessage, dict]:
    """Tracked streaming variant for user-visible LLM calls.

    Emits incremental SSE-compatible events through ``writer`` while preserving
    the old return shape: ``(AIMessage, usage_record)``. Structured output calls
    should keep using ``tracked_ainvoke`` because schema parsing is not streamed.
    """
    thinking_parts: list[str] = []
    answer_parts: list[str] = []
    usage_metadata: dict = {}
    model = _get_model_name(llm)

    async for chunk in llm.astream(messages):
        meta = getattr(chunk, "usage_metadata", None) or {}
        if meta:
            usage_metadata = meta

        thinking_text, answer_text = _split_stream_content(getattr(chunk, "content", ""))

        if thinking_text:
            thinking_parts.append(thinking_text)
            if writer is not None and emit_thinking:
                writer({
                    "type": "thinking",
                    "source": thinking_source,
                    "content": thinking_text,
                })

        if answer_text:
            answer_parts.append(answer_text)
            if writer is not None and emit_assistant:
                writer({"type": "assistant_message", "content": answer_text})

    thinking_text = "".join(thinking_parts)
    answer_text = "".join(answer_parts)
    response = _build_streamed_message(thinking_text, answer_text, usage_metadata)

    input_tokens    = usage_metadata.get("input_tokens", 0)
    output_tokens   = usage_metadata.get("output_tokens", 0)
    thinking_tokens = (usage_metadata.get("output_token_details") or {}).get("reasoning", 0)
    cost_usd        = compute_cost(input_tokens, output_tokens, thinking_tokens, model)

    record: dict = {
        "node":            node_name,
        "input_tokens":    input_tokens,
        "output_tokens":   output_tokens,
        "thinking_tokens": thinking_tokens,
        "cost_usd":        round(cost_usd, 8),
        "model":           model,
    }

    # See note in tracked_ainvoke — usage lands in AgentState, not the stream.
    logger.debug("token_usage %s", record)

    return response, record


# ── Durable per-thread / per-user usage log ──────────────────────────────────
# usage_events is the SQL-queryable record _bill_usage cannot provide: it skips
# its AgentState write entirely while a subgraph interrupt is pending (a MAID
# extraction almost always ends at one), and token_transactions is only
# written when the user HAD balance. flush_usage_events writes unconditionally
# and never raises — it is telemetry, not billing, and must never be able to
# fail a turn. Unacast is NOT written here; unacast_call_log already records
# it transactionally with the budget ledger (unacast_query.reconcile_call).

def _period(when: Any = None) -> str:
    from datetime import datetime, timezone
    dt = when or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m")


async def flush_usage_events(
    *,
    user_id: str | None,
    thread_id: str | None,
    usage_cb: Any = None,
    grounding_acc: Any = None,
    api_acc: Any = None,
    source: str = "chat",
) -> None:
    """Write this turn's tokens and API-call counts to ``usage_events``.

    Deliberately independent of ``_bill_usage``: does not care whether the
    turn ended at an interrupt, whether tokens were > 0, or whether
    ``TokenService.deduct_tokens`` 402'd. Telemetry must not inherit billing's
    branches — call this unconditionally, once per turn.

    Opens its OWN session. Must not reuse a session ``TokenService.deduct_tokens``
    may have touched: that call ``db.add()``s partial deductions in a loop
    before it can raise 402, ahead of its own commit — sharing a session here
    would risk committing that dirty partial state as a side effect of writing
    telemetry.

    Never raises.
    """
    import uuid as _uuid

    from app.db.database import AsyncSessionLocal
    from app.db.models import UsageEvent

    period = _period()
    rows: list[UsageEvent] = []

    # ── token rows, one per model, merging LangChain + raw-SDK grounding ────
    per_model: dict[str, dict[str, int]] = {}
    for model, u in (getattr(usage_cb, "usage_metadata", None) or {}).items():
        model_key = normalize_model_name(model)
        entry = per_model.setdefault(model_key, {"input": 0, "output": 0, "thinking": 0})
        entry["input"] += u.get("input_tokens", 0)
        entry["output"] += u.get("output_tokens", 0)
        entry["thinking"] += (u.get("output_token_details") or {}).get("reasoning", 0)

    for rec in (grounding_acc or []):
        model_key = normalize_model_name(rec.get("model"))
        entry = per_model.setdefault(model_key, {"input": 0, "output": 0, "thinking": 0})
        entry["input"] += rec.get("input_tokens", 0)
        entry["output"] += rec.get("output_tokens", 0)
        entry["thinking"] += rec.get("thinking_tokens", 0)

    for model_key, entry in per_model.items():
        total = entry["input"] + entry["output"]
        if total <= 0:
            continue
        cost = compute_cost(entry["input"], entry["output"], entry["thinking"], model_key)
        rows.append(UsageEvent(
            period=period, thread_id=thread_id, kind="llm_tokens", api=model_key,
            quantity=total, cost_usd=round(cost, 8), source=source,
            detail={"in": entry["input"], "out": entry["output"], "think": entry["thinking"]},
        ))

    # ── API-call rows — unacast_* is owned by unacast_call_log, skip it ─────
    for api, n in (api_acc or {}).items():
        if not n or api.startswith("unacast"):
            continue
        kind = "grounding" if api.startswith("grounding_") else "google_maps"
        rows.append(UsageEvent(
            period=period, thread_id=thread_id, kind=kind, api=api,
            quantity=n, source=source,
        ))

    if not rows:
        return

    try:
        user_uuid = _uuid.UUID(user_id) if user_id else None
    except (ValueError, AttributeError, TypeError):
        user_uuid = None
    for row in rows:
        row.user_id = user_uuid

    try:
        async with AsyncSessionLocal() as db:
            db.add_all(rows)
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — telemetry must never fail a turn
        logger.error("flush_usage_events failed: %s", exc)
