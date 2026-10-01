"""
app/api/chat.py
───────────────
Streaming chat endpoints for the PunkAI LangGraph agent.

Two endpoints:
  POST /chat              – start (or continue) a conversation thread
  POST /chat/{session_id}/resume – resume after an interrupt with user input

Both stream Server-Sent Events (SSE) back to the client:
  data: {"type": "thinking",          "content": "..."}
  data: {"type": "assistant_message", "content": "..."}
  data: {"type": "map_data",          "content": {...}}
  data: {"type": "pending_action",    "content": {...}}
  data: {"type": "marketing_plan",    "content": {...}}
  data: {"type": "campaign_plan",     "content": "<html>"}
  data: {"type": "done"}
  data: {"type": "error",             "content": "..."}
""" 
import json
import uuid
from datetime import datetime
from app.db.schemas import ChatMessageResponse, ThreadHistoryResponse, ThreadListResponse, ThreadResponse
from sqlalchemy import select
from app.modules.chat.models import Conversation, ChatMessage
from app.modules.user.models import User
from app.modules.payment.models import UserSubscription, Subscription
from app.shared.enums import SubscriptionStatus
 
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import AsyncSessionLocal
# from __future__ import annotations
from typing import Awaitable, Callable, AsyncGenerator, Optional
from app.core.logging import logger
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langchain_core.callbacks import get_usage_metadata_callback
from langgraph.types import Command
from app.graph.usage import aggregate_grounding_usage, compute_cost, grounding_usage_callback
from pydantic import BaseModel
from app.core.dependencies import get_current_user
from app.services.resume_preflight import run_preflight
from app.core.dependencies import get_current_user,get_db,check_subscription_active
from app.services.maid_store import fetch_maid_extraction
from app.services.session_naming import update_conversation_title_from_context
from app.services.chat_service import delete_checkpoint_data
from app.core.config import settings

router = APIRouter(prefix="/chat", tags=["Chat"])


# ── Request / response schemas ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    question: Optional[str] = None
    session_id: Optional[str] = None  # omit to start a new session



class ResumeRequest(BaseModel):
    value: str  # the user's answer to the pending interrupt
    question: Optional[str] = None

class UpdateThreadRequest(BaseModel):
    title: Optional[str] = None
    starred: Optional[bool] = None
# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse(payload: dict) -> str:
    """Format a dict as a single SSE data line."""
    return f"data: {json.dumps(payload)}\n\n"


# Per-thread carry of token totals that could NOT be written to AgentState
# because the graph was paused at an interrupt (see _bill_usage). Flushed into
# the next safe aupdate_state. Best-effort display accounting only — the billing
# source of truth is the DB subscription meter, which is always updated.
_TOKEN_CARRY: dict[str, tuple[int, float]] = {}


async def _graph_is_interrupted(graph, config: dict) -> bool:
    """True when the graph (or a subgraph) is paused at an interrupt.

    A bare ``aupdate_state`` (no ``as_node``) while an interrupt is pending
    RESETS the interrupted task and makes the next invocation replay the
    interrupted node — for a wizard SUBGRAPH that means a restart-from-START,
    which consumes the next resume value at the wrong interrupt (the geo
    plan-review loop). ``StateSnapshot.next`` is the canonical "work still
    pending" signal and surfaces a subgraph interrupt at the parent; we also
    check ``tasks[].interrupts`` as a belt-and-suspenders.
    """
    try:
        snap = await graph.aget_state(config)
    except Exception as exc:
        logger.warning("interrupt check aget_state failed: %s", exc)
        return False
    if not snap:
        return False
    if getattr(snap, "next", None):
        return True
    return any(getattr(t, "interrupts", ()) for t in (getattr(snap, "tasks", None) or ()))


# async def _bill_usage(graph, config: dict, usage_cb, subscription, stream_db, user) -> None:
#     """Aggregate this turn's token usage from the callback and persist it.

#     ``usage_cb.usage_metadata`` is a per-model dict produced by LangChain's
#     ``get_usage_metadata_callback`` covering EVERY LLM call in the turn (all
#     nodes, wizards, tools, and resume preflight). We sum total tokens across
#     models, compute USD via the existing pricing table, write the running
#     totals into AgentState (operator.add reducers), and add the total tokens
#     to the per-user subscription meter.

#     CRITICAL: the AgentState write is SKIPPED while the graph is paused at an
#     interrupt — a bare ``aupdate_state`` there restarts the interrupted wizard
#     subgraph from START and breaks resume routing. Skipped totals are carried
#     forward (``_TOKEN_CARRY``) and flushed on the next non-interrupted turn.
#     The DB meter is always updated, so billing is never skipped.
#     """
#     total_tokens = 0
#     total_cost = 0.0
#     for model, u in (usage_cb.usage_metadata or {}).items():
#         inp = u.get("input_tokens", 0)
#         out = u.get("output_tokens", 0)
#         think = (u.get("output_token_details") or {}).get("reasoning", 0)
#         total_tokens += u.get("total_tokens", inp + out)
#         total_cost += compute_cost(inp, out, think, model)

#     if not total_tokens:
#         return

#     # Persist running totals into AgentState (checkpointed; accumulates) ONLY
#     # when the graph is NOT paused at an interrupt. Otherwise carry forward.
#     thread_id = (config.get("configurable") or {}).get("thread_id", "")
#     if await _graph_is_interrupted(graph, config):
#         carried_t, carried_c = _TOKEN_CARRY.get(thread_id, (0, 0.0))
#         _TOKEN_CARRY[thread_id] = (carried_t + total_tokens, carried_c + total_cost)
#         logger.info(
#             "token usage: graph interrupted — deferring AgentState write "
#             "(carry=%s tokens) thread=%s",
#             _TOKEN_CARRY[thread_id][0], thread_id,
#         )
#     else:
#         carried_t, carried_c = _TOKEN_CARRY.pop(thread_id, (0, 0.0))
#         try:
#             await graph.aupdate_state(config, {
#                 "total_tokens": total_tokens + carried_t,
#                 "token_cost_usd": round(total_cost + carried_c, 8),
#             })
#         except Exception as e:
#             logger.warning("token usage aupdate_state failed: %s", e)
#             # Restore carry so the increment is not lost.
#             if carried_t or carried_c:
#                 _TOKEN_CARRY[thread_id] = (carried_t, carried_c)
#     print(f"TOKEN USAGE  for me : {total_tokens}","==================>>>>>")
#     # Update the per-user usage meter.
#     try:
#         db_user = await stream_db.merge(user, load=False)
#         db_user.free_token_usage = (db_user.free_token_usage or 0) + total_tokens
#         print(f"TOKEN USAGE : {db_user.free_token_usage}","==================>>>>>")
        
#         if subscription:
#             sub = await stream_db.merge(subscription, load=False)
#             sub.usage_token = (sub.usage_token or 0) + total_tokens

#         await stream_db.commit()
#     except Exception as e:
#         logger.error(f"error in token update : {e}")
#         await stream_db.rollback()


async def _bill_usage(
    graph, config: dict, usage_cb, subscription, stream_db, current_user,
    grounding_acc=None,
) -> None:
    total_tokens = 0
    total_cost = 0.0

    # ── 1. Aggregate usage ─────────────────────────────
    for model, u in (usage_cb.usage_metadata or {}).items():
        inp = u.get("input_tokens", 0)
        out = u.get("output_tokens", 0)
        think = (u.get("output_token_details") or {}).get("reasoning", 0)

        total_tokens += u.get("total_tokens", inp + out)
        total_cost += compute_cost(inp, out, think, model)

    # Gemini grounding rides the raw google-genai SDK, which `usage_cb` cannot
    # observe (see graph/usage.py) — its tokens are billed by Google but would
    # otherwise reach AgentState as zero. Added BEFORE the guard below so a turn
    # whose only LLM spend was grounding still bills.
    # `grounding_acc` is defaulted so an un-updated caller degrades to the old
    # behavior instead of raising mid-turn.
    g_tokens, g_cost = aggregate_grounding_usage(grounding_acc)
    total_tokens += g_tokens
    total_cost += g_cost

    if total_tokens <= 0:
        return

    thread_id = (config.get("configurable") or {}).get("thread_id", "")

    # ── 2. Handle AgentState update (safe) ────────────
    try:
        if await _graph_is_interrupted(graph, config):
            carried_t, carried_c = _TOKEN_CARRY.get(thread_id, (0, 0.0))
            _TOKEN_CARRY[thread_id] = (
                carried_t + total_tokens,
                carried_c + total_cost,
            )
        else:
            carried_t, carried_c = _TOKEN_CARRY.pop(thread_id, (0, 0.0))

            await graph.aupdate_state(config, {
                "total_tokens": total_tokens + carried_t,
                "token_cost_usd": round(total_cost + carried_c, 8),
            })

    except Exception as e:
        logger.warning(f"AgentState billing update failed: {e}")

    # ── 3. SAFE DB UPDATE (NO merge, NO stale objects) ────────────
    # try:
        # 🔥 always fetch fresh row
        # db_user = await stream_db.get(User, current_user.id)

        # if not db_user:
        #     logger.error("User not found in billing update")
        #     return
     
        # db_user.free_token_usage = (db_user.free_token_usage or 0) + total_tokens
        
        # if subscription is not True:
        #     if subscription:
        #         db_sub = await stream_db.get(UserSubscription, subscription.id)
        #         if db_sub:
        #             db_sub.usage_token = (db_sub.usage_token or 0) + total_tokens

        # await stream_db.flush()
        # await stream_db.commit()
        # await stream_db.refresh(db_user)
    #     logger.info(
    #         f"Token billed: user={current_user.id} tokens={total_tokens} cost={total_cost}"
    #     )

    # except Exception as e:
    #     print("------------------------------------------------------------------------------------>>>>>>>>>>>>>>>>>>>>>>>>====================")
    #     logger.error(f"error in token update : {e}")
        # await stream_db.rollback()


async def _stream_graph(
    request: Request,
    graph,
    graph_input,
    config: dict,
    db: AsyncSession | None = None,
    current_user: User | None = None,
    on_state_snapshot: Callable[[dict], Awaitable[None]] | None = None,
) -> AsyncGenerator[str, None]:
    """
    Consume graph.astream() and yield SSE-formatted strings.

    Handles both "custom" events (thinking / map_data / assistant_message)
    and "values" snapshots (pending_action, marketing_plan extraction).
    """
    try:
        async for chunk in graph.astream(
            graph_input,
            config,
            stream_mode=["values", "custom"],
            subgraphs=True,
        ):
            # subgraphs=True → (namespace_tuple, mode, data)
            # ns identifies which subgraph emitted the event; ignored here
            ns, mode, data = chunk

            if mode == "custom":
                # Nodes emit dicts with "type" key via get_stream_writer()
                if isinstance(data, dict):
                    yield _sse(data)

            elif mode == "values":
                # AgentState snapshot — surface pending_action and marketing_plan
                if isinstance(data, dict):
                    if on_state_snapshot is not None:
                        await on_state_snapshot(data)
                    if data.get("pending_action"):
                        yield _sse({"type": "pending_action", "content": data["pending_action"]})
                    # NOTE: marketing_plan is NOT emitted from the values snapshot.
                    # campaign_publish writes it to state then the graph flows
                    # straight into the media creative-upload interrupt in the same
                    # astream turn, which would surface the plan card alongside the
                    # upload prompt. The plan is emitted explicitly by
                    # media_collect_creatives after creatives are collected so it
                    # lands on the turn AFTER the upload ask.

        yield _sse({"type": "done"})

    except Exception as exc:  # noqa: BLE001
        yield _sse({"type": "error", "content": str(exc)})


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("")
async def chat(
    payload: ChatRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    # subscription: UserSubscription = Depends(check_subscription_active)
) -> StreamingResponse:
    """
    Send a message to the AI agent and receive a streaming SSE response.

    Pass `session_id` to continue an existing conversation thread.
    Omit it (or pass null) to start a fresh session — a new UUID is
    generated and returned as the first SSE event:
        data: {"type": "session_id", "content": "<uuid>"}
    """

     
    subscription = None
    print(settings.ALLOWED_ORIGINS,"welcome to home---------------------------------------------------->>>>>>>>>>>>>>>>>>>>>>")

    graph = getattr(request.app.state, "graph", None)
    if graph is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent not initialised — the database may be unavailable.",
        )
    session_id = payload.session_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}
    # ─────────────────────────────────────────
    # 2. CONVERSATION ENSURE
    # ─────────────────────────────────────────
    result = await db.execute(
        select(Conversation).where(
            Conversation.thread_id == session_id,
            Conversation.user_id == current_user.id,
        )
    )
    conv = result.scalar_one_or_none()

    if not conv:
        conv = Conversation(
            user_id=current_user.id,
            thread_id=session_id,
            title=payload.message[:50] or "New Chat",
        )
        db.add(conv)
        # flush (not commit) assigns conv.id so the user message can FK to it
        # in a single commit below — one DB round-trip instead of two.
        await db.flush()
    # NOTE: title enrichment is NOT done here — it runs in-stream via
    # rename_from_state (on_state_snapshot) on every values snapshot, so a
    # pre-stream call only adds a blocking commit to time-to-first-byte.
    user_msg = ChatMessage(
        conversation_id=conv.id,
        role="user",
        content=payload.message,
    )
    db.add(user_msg)
    await db.commit()

    # Per-turn fields only — keys with reducers (user_info, geo_data,
    # wizards_completed, etc.) preserve themselves across turns. Keys
    # without reducers (marketing_plan, wizard scratch, etc.) MUST NOT be
    # written here because LangGraph merges this dict into the checkpoint
    # and non-reducer keys overwrite — writing geo_data=None every turn
    # would silently wipe the geo result, causing maid_wizard to skip.
    _per_turn_state: dict = {
        "messages": [HumanMessage(content=payload.message)],
        "user_id": str(current_user.id),
        "next_nodes": ["entry"],
        "pending_action": None,
        "thinking": [],
        "current_turn_tool_errors": None,
    }

    # For brand-new sessions (no checkpoint yet) also supply the initial defaults
    # that accumulator reducers (operator.add) need to start from zero, plus all
    # the optional state keys so they don't start as undefined.
    _is_new_session = not payload.session_id  # session_id=None means fresh UUID above
    if not _is_new_session:
        # Check whether a real checkpoint exists for this thread
        try:
            _existing = await graph.aget_state(config)
            _is_new_session = _existing is None or not _existing.values
        except Exception:
            _is_new_session = True

    if _is_new_session:
        _per_turn_state.update({
            "user_info": {},
            "marketing_plan": None,
            "campaign_brief": None,
            "meta_campaign_ids": None,
            "geo_data": None,
            "token_cost_usd": 0.0,
            "total_tokens": 0,
            "tool_calls_log": [],
            "geo_wizard_state": None,
            "maid_wizard_state": None,
            "campaign_wizard_state": None,
            "media_wizard_state": None,
            "active_campaign_id": None,
            "campaign_manager_state": None,
            "wizard_failure": None,
        })

    initial_state = _per_turn_state

    assistant_text = ""
    thinking_data = []
    metadata = {}

    async def event_stream() -> AsyncGenerator[str, None]:
        nonlocal assistant_text, thinking_data, metadata
        yield _sse({"type": "session_id", "content": session_id})
        # Instant motion: the entry node is a blocking Pro LLM call (~300-800ms)
        # that emits nothing until it resolves, so the screen sits dead. Emit one
        # immediate reasoning beat so the UI shows activity <200ms. source != "punk"
        # → not captured into thinking_data, so it is never persisted.
        yield _sse({"type": "thinking", "source": "system", "content": "Reading your message..."})

        # Use a fresh session for the duration of the stream to ensure it remains
        # open while yielding events. The dependency 'db' may close early.
        async with AsyncSessionLocal() as stream_db:
            # Re-attach objects to the current session
            stream_conv = await stream_db.merge(conv, load=False)
            stream_user = await stream_db.merge(current_user, load=False)

            async def rename_from_state(state_values: dict) -> None:
                await update_conversation_title_from_context(
                    stream_db,
                    stream_conv,
                    latest_user_text=payload.message,
                    state_values=state_values,
                )

            # Capture token usage for EVERY LLM call in this turn (all nodes,
            # wizards, tools) via the contextvar-based callbacks — no per-node
            # plumbing. Two are needed: LangChain's covers calls made through
            # ChatGoogleGenerativeAI, `grounding_usage_callback` covers the raw
            # google-genai grounding calls LangChain cannot see. Totals are
            # billed once after the stream completes.
            with get_usage_metadata_callback() as usage_cb, \
                 grounding_usage_callback() as grounding_cb:
                async for chunk in _stream_graph(
                    request,
                    graph,
                    initial_state,
                    config,
                    db=stream_db,
                    current_user=stream_user,
                    on_state_snapshot=rename_from_state,
                ):
                    try:
                        # Remove SSE prefix to parse JSON
                        raw_data = chunk.replace("data: ", "").strip()
                        if not raw_data:
                            continue
                        data = json.loads(raw_data)

                        # Collect assistant output and thinking events
                        if data.get("type") == "assistant_message":
                            assistant_text += data.get("content", "")
                        elif data.get("type") == "campaign_plan":
                            metadata["campaign_plan"] = data.get("content")
                        elif data.get("type") == "thinking":
                            if data.get("source") == "punk":
                                thinking_data.append(f"Punk Reasoning:\n{data.get('content', '')}")
                        elif data.get("type") in ["pending_action", "map_data", "marketing_plan"]:
                            metadata[data.get("type")] = data.get("content")
                    except Exception:
                        # Fallback for non-JSON or malformed chunks
                        pass

                    yield chunk

            await _bill_usage(graph, config, usage_cb, subscription, stream_db,
                              current_user, grounding_cb)

            # After streaming completes, save the assistant message to the database
            # Trim trailing whitespace — narrator emits text with trailing "\n\n"
            # as a between-emission separator; the final blob shouldn't end in it.
            assistant_text = assistant_text.rstrip()
            if assistant_text or thinking_data or metadata:
                assistant_msg = ChatMessage(
                    conversation_id=stream_conv.id,
                    role="assistant",
                    content=assistant_text,
                    question=payload.question or None,
                    thinking="\n".join(thinking_data),
                    langchain_data=metadata if metadata else None
                )
                stream_db.add(assistant_msg)
                await stream_db.commit()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )

async def _persist_confirmed_stepper_value(
    db: AsyncSession, conversation_id: uuid.UUID, confirmed_value: str
) -> None:
    """After a user resumes an interrupt, backfill stepper.default in the last
    assistant message so the widget re-hydrates with the confirmed value on refresh."""
    from sqlalchemy.orm.attributes import flag_modified
    import copy

    result = await db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.role == "assistant",
        )
        .order_by(ChatMessage.auto_id.desc())
        .limit(1)
    )
    last_assistant = result.scalar_one_or_none()

    if not last_assistant or not last_assistant.langchain_data:
        return

    pending_action = last_assistant.langchain_data.get("pending_action")
    if not pending_action or not pending_action.get("stepper"):
        return

    try:
        numeric = float(confirmed_value)
    except (ValueError, TypeError):
        return

    updated = copy.deepcopy(last_assistant.langchain_data)
    updated["pending_action"]["stepper"]["default"] = numeric
    last_assistant.langchain_data = updated
    flag_modified(last_assistant, "langchain_data")
    await db.commit()


@router.post("/{session_id}/resume")
async def resume_chat(
    session_id: str,
    payload: ResumeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    # subscription: UserSubscription = Depends(check_subscription_active)
) -> StreamingResponse:
    """
    Resume a paused agent thread after the user answers an interrupt prompt.

    `value` is the raw string the user provided (option selection, free text,
    lat/lng JSON string, or "skip" for file-upload interrupts).
    """
    print("welcome to male is bac----------------------------")
    subscription = None
    graph = getattr(request.app.state, "graph", None)
    if graph is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent not initialised — the database may be unavailable.",
        )

    # Ensure conversation exists
    result = await db.execute(
        select(Conversation).where(
            Conversation.thread_id == session_id,
            Conversation.user_id == current_user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Save user response to DB
    user_msg = ChatMessage(
        conversation_id=conv.id,
        role="user",
        content=payload.value,
        question=payload.question or None,
    )
    db.add(user_msg)
    await db.commit()
    await _persist_confirmed_stepper_value(db, conv.id, payload.value)

    config = {"configurable": {"thread_id": session_id}}

    # NOTE: no pre-stream title enrichment here. It previously required a
    # SYNCHRONOUS graph.get_state(config) — a blocking checkpointer read on the
    # event loop — purely to feed state_values into the title call. Title is already
    # re-derived in-stream via rename_from_state (on_state_snapshot), so both the
    # sync read and the blocking title call are dropped from time-to-first-byte.

    resume_command = Command(resume=payload.value)

    assistant_text = ""
    thinking_data = []
    metadata = {}

    async def event_stream() -> AsyncGenerator[str, None]:
        nonlocal assistant_text, thinking_data, metadata
        # Instant motion before preflight (checkpointer reads + possible extraction LLM)
        # and the resumed node run. source != "punk" → never persisted.
        yield _sse({"type": "thinking", "source": "system", "content": "Got it, picking up where we left off..."})

        # Use a fresh session for the duration of the stream to ensure it remains
        # open while yielding events. The dependency 'db' may close early.
        async with AsyncSessionLocal() as stream_db:
            # Re-attach objects to the current session
            stream_conv = await stream_db.merge(conv, load=False)
            stream_user = await stream_db.merge(current_user, load=False)

            # Capture token usage for the whole resume turn — including the
            # preflight intent-extraction LLM calls — via the contextvar
            # callbacks (LangChain's, plus grounding's for the raw-SDK calls it
            # cannot see). Totals are billed once after streaming completes.
            with get_usage_metadata_callback() as usage_cb, \
                 grounding_usage_callback() as grounding_cb:
                # Resume orchestration — intent re-extraction, MAID map re-emit,
                # and backtrack / locked-refusal short-circuits live in
                # services/resume_preflight. Run it here so its LLM calls are
                # counted under the callback.
                preflight = await run_preflight(graph, config, payload.value)

                # Emit any preflight events (MAID map, backtrack rewind notice,
                # locked-refusal summary). Capture into metadata for DB persistence
                # the same way graph events are captured below.
                for ev in preflight.sse_events:
                    if ev.get("type") in ("pending_action", "map_data", "marketing_plan"):
                        metadata[ev["type"]] = ev.get("content")
                    elif ev.get("type") == "assistant_message":
                        assistant_text += ev.get("content", "")
                    elif ev.get("type") == "campaign_plan":
                        metadata["campaign_plan"] = ev.get("content")
                    yield _sse(ev)

                if preflight.short_circuit:
                    # Backtrack / locked-refusal already handled — do NOT call
                    # astream, the resume value was consumed by the preflight.
                    if assistant_text or metadata:
                        assistant_msg = ChatMessage(
                            conversation_id=stream_conv.id,
                            role="assistant",
                            content=assistant_text,
                            thinking="",
                            langchain_data=metadata if metadata else None,
                        )
                        stream_db.add(assistant_msg)
                        await stream_db.commit()
                    await _bill_usage(graph, config, usage_cb, subscription, stream_db,
                                      current_user, grounding_cb)
                    yield _sse({"type": "done"})
                    return

                async def rename_from_state(state_values: dict) -> None:
                    await update_conversation_title_from_context(
                        stream_db,
                        stream_conv,
                        latest_user_text=payload.value,
                        state_values=state_values,
                    )

                # Events emitted by preflight (MAID map re-emit, etc.) precede
                # any "Resumed " marker but are genuine resume-turn output, not
                # the duplicate pre-interrupt re-fire. The marker reset below
                # restores to this baseline, not empty, so they survive.
                _base_assistant_text = assistant_text
                _base_thinking = list(thinking_data)
                _base_metadata = dict(metadata)

                # Interrupt-replay stream gate: on a resume, LangGraph replays the
                # paused node top-to-bottom, re-emitting every already-answered
                # interrupt's events before the new work. `replay_boundary_skip`
                # (= paused interrupt index + 1) is how many replayed `resume_boundary`
                # events precede the genuinely-new content; suppress everything until
                # then, then forward live. skip==0 (fresh /chat, non-builder interrupt,
                # or no stamp) → no gating, current behavior.
                _skip = preflight.replay_boundary_skip
                _boundaries_seen = 0

                async for chunk in _stream_graph(
                    request,
                    graph,
                    resume_command,
                    config,
                    db=stream_db,
                    current_user=stream_user,
                    on_state_snapshot=rename_from_state,
                ):
                    data: dict = {}
                    try:
                        raw_data = chunk.replace("data: ", "").strip()
                        if not raw_data:
                            continue
                        data = json.loads(raw_data)
                        # Collect assistant output + thinking for DB persistence.
                        # The resumed step's pre-interrupt narration is re-emitted
                        # on replay (the in-node `skip_emit` guard is inert in the
                        # builder path — `pending_action` is never persisted to
                        # state with the active step_key, so resume detection never
                        # fires). We therefore reset the capture buckets on the
                        # `resume_boundary` event (emitted by wizard_interrupt at
                        # the interrupt() return — the structural resume point) so
                        # only the genuinely-new events that follow it are saved,
                        # without re-introducing the old gate's bug of dropping the
                        # post-resume handoff / audience reveal.
                        if data.get("type") == "resume_boundary":
                            # The resumed node re-emits its pre-interrupt narration
                            # (a duplicate) BEFORE this boundary, then the new work
                            # runs AFTER it. Drop everything captured so far across
                            # content, thinking AND langchain_data back to the
                            # post-preflight baseline — keep only post-resume events
                            # plus the preflight re-emit. On multiple boundaries this
                            # keeps work after the LAST resume. Live stream untouched
                            # (yield still runs below).
                            assistant_text = _base_assistant_text
                            thinking_data = list(_base_thinking)
                            metadata = dict(_base_metadata)
                        elif data.get("type") == "assistant_message":
                            assistant_text += data.get("content", "")
                        elif data.get("type") == "campaign_plan":
                            metadata["campaign_plan"] = data.get("content")
                        elif data.get("type") == "thinking":
                            _tc = data.get("content", "")
                            if data.get("source") == "punk":
                                thinking_data.append(f"Punk Reasoning:\n{_tc}")
                        elif data.get("type") in ["pending_action", "map_data", "marketing_plan"]:
                            metadata[data.get("type")] = data.get("content")
                    except Exception:
                        pass

                    # ── interrupt-replay stream gate ──────────────────────────────
                    # Suppress replayed events until past the last replay boundary,
                    # so the wire carries only genuinely-new content. Persist
                    # bookkeeping above already ran (DB stays correct); this only
                    # affects what is yielded to the client.
                    if _skip > 0:
                        if data.get("type") == "resume_boundary":
                            _boundaries_seen += 1
                            continue  # internal marker; never forward on a gated resume
                        if _boundaries_seen < _skip:
                            continue  # still replaying → keep it off the wire
                    yield chunk

            await _bill_usage(graph, config, usage_cb, subscription, stream_db,
                              current_user, grounding_cb)

            # Save assistant response after streaming
            if assistant_text or thinking_data or metadata:
                assistant_msg = ChatMessage(
                    conversation_id=stream_conv.id,
                    role="assistant",
                    content=assistant_text,
                    thinking="\n".join(thinking_data),
                    langchain_data=metadata if metadata else None
                )
                stream_db.add(assistant_msg)
                await stream_db.commit()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )




@router.post("/new", response_model=ThreadResponse)
async def create_new_chat(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Explicitly create a new chat session."""
    thread_id = str(uuid.uuid4())
    conv = Conversation(
        user_id=current_user.id,
        thread_id=thread_id,
        title=f"New Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


@router.get("/threads", response_model=ThreadListResponse)
async def list_user_threads(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ThreadListResponse:
    """List all chat sessions for the current user."""
    from sqlalchemy import desc
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(desc(Conversation.created_at))
    )
    threads = result.scalars().all()
    return ThreadListResponse(
        threads=threads,
        total=len(threads)
    )


@router.get("/history/{thread_id}", response_model=ThreadHistoryResponse)
async def get_conversation_history(
    thread_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ThreadHistoryResponse:
    """Retrieve the conversation history (metadata + messages) for a thread."""
    from sqlalchemy import asc
    # 1. Fetch metadata
    result = await db.execute(
        select(Conversation).where(
            Conversation.thread_id == thread_id,
            Conversation.user_id == current_user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # 2. Fetch messages
    msg_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conv.id)
        .order_by(asc(ChatMessage.auto_id))
    )
    messages = msg_result.scalars().all()

    # 3. Combine
    return ThreadHistoryResponse(
        id=conv.id,
        thread_id=conv.thread_id,
        title=conv.title,
        status=conv.status.value,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[
            ChatMessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                question=m.question,
                thinking=m.thinking,
                langchain_data=m.langchain_data,
                created_at=m.created_at,
            )
            for m in messages
        ]
    )


@router.delete("/thread/{thread_id}", response_model=dict)
async def delete_thread(
    thread_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a chat session and all its messages."""
    from sqlalchemy import delete
    # Verify ownership and get conversation
    result = await db.execute(
        select(Conversation).where(
            Conversation.thread_id == thread_id,
            Conversation.user_id == current_user.id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Clear checkpoint data first so a partial failure does not leave a
    # zombie checkpoint pointing at a deleted DB row.
    try:
        await delete_checkpoint_data(thread_id)
    except Exception as cp_exc:
        logger.error("Failed to clear checkpoints during deletion", thread_id=thread_id, error=str(cp_exc))

    await db.execute(delete(Conversation).where(Conversation.id == conv.id))
    await db.commit()

    return {"status": "success", "message": f"Thread {thread_id} deleted."}


@router.put("/thread/update/{id}")
async def update_thread(
    id: str,
    payload: UpdateThreadRequest, 
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update thread metadata."""
    from sqlalchemy import update
    
    # Verify conversation ownership
    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.thread_id == id,
            Conversation.user_id == current_user.id,
        )
    )
    conv = conv_result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Update thread metadata
    if payload.title is not None:
        conv.title = payload.title
    if payload.starred == True:
        conv.starred = True
    elif payload.starred == False:
        conv.starred = False
        
    await db.commit()
    await db.refresh(conv)

    return {
        "thread_id": conv.thread_id,
        "title": conv.title,
        "starred": conv.starred,
    }

# stared list show api 
@router.get("/thread/starred", response_model=ThreadListResponse)
async def get_starred_threads(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ThreadListResponse:
    """Get all starred threads for a user."""
    from sqlalchemy import select, desc
    result = await db.execute(
        select(Conversation)
        .where(
            Conversation.user_id == current_user.id,
            Conversation.starred == True,
        )
        .order_by(desc(Conversation.created_at))
    )
    threads = result.scalars().all()
    return ThreadListResponse(
        threads=threads,
        total=len(threads)
    )


#   poi save user wise user remove or update system 
@router.post("/set/poi")
async def set_poi(
    thread_id: str,
    pois: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Set POI for a specific thread."""
    from app.graph.graph import get_compiled_graph
    #  "pois": [
    #   { "name": "Starbucks – Peel St",      "lat": 45.4993, "lng": -73.5716, "radius_km": null, "parent_location": "Montreal", "types": ["cafe"], "brand": "Starbucks", "event_start_date": null, "event_end_date": null },
    #   { "name": "Starbucks – McGill College","lat": 45.5021, "lng": -73.5707, "radius_km": null, "parent_location": "Montreal", "types": ["cafe"], "brand": "Starbucks", "event_start_date": null, "event_end_date": null }
    # ],
    # Verify conversation ownership
    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.thread_id == thread_id,
            Conversation.user_id == current_user.id,
        )
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if conv.final_poi:
        # Ensure SQLAlchemy tracks changes to JSON columns by re-assigning
        current_poi = list(conv.final_poi) if isinstance(conv.final_poi, list) else [conv.final_poi]
        current_poi.append(pois)
        conv.final_poi = current_poi
    else:
        conv.final_poi = pois

    conv.is_final_poi_set = True
    await db.commit()
    await db.refresh(conv)

    return {
        "thread_id": thread_id,
        "agent_state": conv.final_poi,
    }


# debug state
# AGENT_STATE_STORE: dict[str, AgentState] = {}

@router.get("/state/{session_id}")
async def get_agent_state(
    session_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full AgentState dump (minus ``messages``) for a thread the caller owns.

    Ownership-gated so one user cannot read another's session by guessing a
    session_id. Values are passed through ``jsonable_encoder`` with a ``str()``
    fallback so nested LangChain objects in scratch fields cannot 500 the route.
    """
    graph = getattr(request.app.state, "graph", None)

    if graph is None:
        raise HTTPException(
            status_code=503,
            detail="Graph not initialized"
        )

    # Verify ownership
    result = await db.execute(
        select(Conversation).where(
            Conversation.thread_id == session_id,
            Conversation.user_id == current_user.id,
        )
    )

    conv = result.scalar_one_or_none()

    if not conv:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found"
        )

    config = {
        "configurable": {
            "thread_id": session_id
        }
    }

    state = await graph.aget_state(config)

    values = state.values if state and getattr(state, "values", None) else {}
    if not values:
        raise HTTPException(
            status_code=404,
            detail="Agent state not found"
        )

    # Strip messages; encode the rest defensively so a nested LangChain object
    # in scratch state can't raise during JSON serialization.
    serializable = {}
    for k, v in values.items():
        if k == "messages":
            continue
        try:
            serializable[k] = jsonable_encoder(v)
        except Exception:
            serializable[k] = str(v)

    return {
        "success": True,
        "session_id": session_id,
        "state": serializable
    }