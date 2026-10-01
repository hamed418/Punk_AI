from fastapi.encoders import jsonable_encoder
import uuid
import copy
import json
from fastapi import HTTPException,status,Request 
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from langchain_core.messages import HumanMessage
from typing import Any, Awaitable, Callable, AsyncGenerator, Optional
from datetime import datetime
from app.core.config import settings 
from app.db.database import AsyncSessionLocal
from langgraph.types import Command
from langchain_core.callbacks import get_usage_metadata_callback
from app.services.resume_preflight import run_preflight
from app.services.oauth import get_meta_credentials
from app.graph.wizard_helpers import parse_radius_float
from app.graph.usage import (
    aggregate_grounding_usage,
    api_call_callback,
    compute_cost,
    flush_usage_events,
    grounding_usage_callback,
    normalize_model_name,
    turn_identity,
)
from app.services.session_naming import update_conversation_title_from_context
from app.modules.user.models import User
from app.core.logging import logger
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver 
from .schemas import ResumeRequest,ChatRequest,UpdateThreadRequest,CancelOutcome,AudiencePreviewRequest
from .repository import ChatRepository
from .rewind_restore import plan_rewind, restore_from_anchor, with_question_text

# Graph state carries live third-party credentials (the user's Meta access token
# is written into user_info and media_wizard_state so publish nodes can reach it).
# Any endpoint that serializes state has to strip them first — a token is not
# safe to return even to the user it belongs to, because the browser is exactly
# where it must not end up.
_SECRET_KEY_MARKERS = ("access_token", "refresh_token", "secret", "password", "api_key")

_REDACTED = "***redacted***"


def _redact_secrets(value):
    """Recursively blank any dict key that names a credential.

    Matches on the key, not the value: a token has no reliable shape, but the
    keys that hold one are known and stable (``meta_access_token``,
    ``access_token``, ``refresh_token``).
    """
    if isinstance(value, dict):
        return {
            k: (
                _REDACTED
                if isinstance(k, str)
                and any(marker in k.lower() for marker in _SECRET_KEY_MARKERS)
                and value[k]
                else _redact_secrets(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_secrets(v) for v in value]
    return value


import asyncio
import contextlib
from types import SimpleNamespace

from app.modules.chat import runs
from app.modules.chat.runs import (
    _MAX_STORED_OBSERVATIONS,
    RunBusyError,
    TooManyRunsError,
    _slim_for_storage,
)
from app.services.resume_preflight import (
    maid_map_reemit_event,
    pending_interrupt_value,
)


class _TurnCapture:
    """What a turn will persist as its single assistant message.

    Kept separate from the emitting side because the resume path has to REWIND
    it: on a resume LangGraph replays the paused node top-to-bottom, so the
    pre-interrupt narration is re-emitted before any new work. ``reset_to`` drops
    the replayed duplicate without touching what already went out on the wire.
    """

    def __init__(self) -> None:
        self.assistant_text = ""
        self.thinking: list[str] = []
        self.metadata: dict = {}

    def baseline(self) -> tuple[str, list[str], dict]:
        return (self.assistant_text, list(self.thinking), dict(self.metadata))

    def reset_to(self, base: tuple[str, list[str], dict]) -> None:
        self.assistant_text = base[0]
        self.thinking = list(base[1])
        self.metadata = dict(base[2])

    def absorb(self, event: dict) -> None:
        etype = event.get("type")
        if etype == "assistant_message":
            self.assistant_text += event.get("content", "")
        elif etype == "campaign_plan":
            self.metadata["campaign_plan"] = event.get("content")
        elif etype == "thinking":
            if event.get("source") == "punk":
                self.thinking.append(f"Punk Reasoning:\n{event.get('content', '')}")
        elif etype in ("pending_action", "map_data"):
            self.metadata[etype] = _slim_for_storage(etype, event.get("content"))

    @property
    def is_empty(self) -> bool:
        return not (self.assistant_text.strip() or self.thinking or self.metadata)


class ChatService:
    def __init__(self, repository: ChatRepository):
        self.repository = repository

    def _sse(self, payload: dict, seq: int | None = None) -> str:
        """Format a dict as one SSE frame.

        The ``id:`` line carries the run's sequence number so a client that
        reconnects mid-turn can ask for everything after the last frame it saw
        (``?from_seq=``, or the browser's own ``Last-Event-ID`` header).
        """
        prefix = f"id: {seq}\n" if seq is not None else ""
        return f"{prefix}data: {json.dumps(payload)}\n\n"

    async def _iter_graph_events(
        self,
        graph,
        graph_input,
        config: dict,
        on_state_snapshot: Callable[[dict], Awaitable[None]] | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Consume ``graph.astream()`` and yield raw event dicts.

        Handles both "custom" events (thinking / map_data / assistant_message /
        campaign_plan) and "values" snapshots (pending_action extraction).

        Yields plain dicts rather than SSE strings because the run registry needs
        to buffer them for replay; SSE framing happens at the subscriber edge.
        """
        try:
            async for chunk in graph.astream(
                graph_input,
                config,
                stream_mode=["values", "custom"],
                subgraphs=True,
            ):
                # subgraphs=True -> (namespace_tuple, mode, data)
                # ns identifies which subgraph emitted the event; ignored here
                ns, mode, data = chunk

                if mode == "custom":
                    # Nodes emit dicts with "type" key via get_stream_writer()
                    if isinstance(data, dict):
                        yield data

                elif mode == "values":
                    # AgentState snapshot — surfaces pending_action only.
                    #
                    # There is no `marketing_plan` SSE event. It was documented
                    # and had consumer branches here, but nothing in the graph
                    # ever emitted one. The campaign plan reaches the client as
                    # the `campaign_plan` custom event (see builder_act), and the
                    # approved payload itself now rides on the pending_action's
                    # spec (the campaign editor).
                    if isinstance(data, dict):
                        if on_state_snapshot is not None:
                            await on_state_snapshot(data)
                        if data.get("pending_action"):
                            yield {"type": "pending_action", "content": data["pending_action"]}

            yield {"type": "done"}

        except Exception as exc:  # noqa: BLE001
            # CancelledError is a BaseException — it passes straight through, so
            # a stop request is never mistaken for a graph failure.
            yield {"type": "error", "content": str(exc)}

    async def _persist_confirmed_stepper_value(
        self,
        db: AsyncSession,
        conversation_id: uuid.UUID, 
        confirmed_value: str
    ) -> None:
        """After a user resumes an interrupt, backfill stepper.default in the last
        assistant message so the widget re-hydrates with the confirmed value on refresh."""

        last_assistant = await self.repository.get_latest_resume_assistant_message(db, conversation_id)

        if not last_assistant or not last_assistant.langchain_data:
            return

        pending_action = last_assistant.langchain_data.get("pending_action")
        if not pending_action or not pending_action.get("stepper"):
            return

        # confirmed_value is the raw resume payload, still wrapped as
        # "Q: <prompt>\nA: 2 km" — bare float() always raised on it, so this
        # never actually backfilled anything. parse_radius_float already knows
        # how to pull the number out of both the wrapper and the unit suffix.
        numeric = parse_radius_float(confirmed_value)
        if numeric is None:
            return

        updated = copy.deepcopy(last_assistant.langchain_data)
        updated["pending_action"]["stepper"]["default"] = numeric
        last_assistant.langchain_data = updated
        flag_modified(last_assistant, "langchain_data")
        await db.commit()

    async def _graph_is_interrupted(self,graph, config: dict) -> bool:
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
    async def _billing_ad_account(self, snap_values: dict, user_id) -> Optional[str]:
        """Which ad account this turn's tokens are billed to.

        This used to read ``active_ads_account_id`` / ``ad_account_id`` off the
        AgentState root. Neither key exists — nothing in the repo ever wrote
        them — so every deduction ran with ad_account_id=None, matched no
        per-account subscription, drained the free tier instead, then 402'd into
        a logger.error. Paid balances never moved. The real key is nested:
        ``user_info["meta_ad_account_id"]`` (graph/state.py).

        That key is empty for the first turns of a thread, before the builder
        resolves Meta — hence the DB fallback. ``get_meta_credentials`` opens
        its OWN session, which is what billing needs (see ``_commit_turn``: the
        deduction must not share a session with other writers), and it already
        resolves ``selected_account or ad_account_id``, so the fallback agrees
        with what publish targets. It returns None for an expired Meta token —
        that turn then bills unscoped, as it did before, rather than failing.
        """
        account = (snap_values.get("user_info") or {}).get("meta_ad_account_id")
        if account:
            return account
        return (await get_meta_credentials(str(user_id)) or {}).get("ad_account_id")

    # bill usage
    async def _bill_usage(self,graph, config: dict, usage_cb, subscription, stream_db, current_user,grounding_acc=None, api_acc=None) -> None:
        total_tokens = 0
        total_cost = 0.0

        # ── 1. Aggregate usage ─────────────────────────────
        for model, u in (usage_cb.usage_metadata or {}).items():
            model_key = normalize_model_name(model)
            inp = u.get("input_tokens", 0)
            out = u.get("output_tokens", 0)
            think = (u.get("output_token_details") or {}).get("reasoning", 0)

            total_tokens += u.get("total_tokens", inp + out)
            total_cost += compute_cost(inp, out, think, model_key)

        g_tokens, g_cost = aggregate_grounding_usage(grounding_acc)
        total_tokens += g_tokens
        total_cost += g_cost

        api_calls = {k: v for k, v in (api_acc or {}).items() if v}

        if total_tokens <= 0 and not api_calls:
            return

        thread_id = (config.get("configurable") or {}).get("thread_id", "")

        # ── 2. Handle AgentState update (safe) ────────────
        try:
            # One snapshot serves both branches: the carry (durable in AgentState,
            # not a process-local dict — survives restart / multi-worker) and,
            # on the non-interrupted branch, ad_account_id below.
            state_snap = await graph.aget_state(config)
            snap_values = state_snap.values if state_snap and state_snap.values else {}
            carried = snap_values.get("pending_usage") or {}
            carried_t = carried.get("tokens", 0)
            carried_c = carried.get("cost_usd", 0.0)
            carried_calls = carried.get("api_calls") or {}

            if await self._graph_is_interrupted(graph, config):
                # A bare aupdate_state (no as_node) while a subgraph interrupt is
                # pending RESETS the interrupted task — see _graph_is_interrupted's
                # docstring. Writing the pending_usage carry here was exactly that:
                # every resume silently restarted campaign_builder from START, so
                # the user's reply landed on the FIRST interrupt in the replay
                # (geo_location_confirmation) instead of the widget on screen.
                #
                # Bill THIS turn's usage immediately instead of carrying it — no
                # graph write at all while paused. Any pending_usage carry from
                # before this fix shipped is left untouched; it still flushes
                # correctly the next time a non-interrupted turn hits the branch
                # below, exactly as it did before.
                if total_tokens > 0:
                    from app.modules.subscription.service import TokenService

                    try:
                        ad_account_id = await self._billing_ad_account(snap_values, current_user.id)
                        await TokenService.deduct_tokens(
                            db=stream_db,
                            user_id=current_user.id,
                            amount=total_tokens,
                            ad_account_id=ad_account_id,
                            action="chat_message",
                            metadata={
                                "thread_id": thread_id,
                                "cost_usd": round(total_cost, 8),
                                "api_calls": api_calls,
                            },
                        )
                    except HTTPException as token_err:
                        logger.error(f"Token deduction failed for user {current_user.id}: {token_err.detail}")
                    except Exception as token_err:
                        logger.error(f"Unexpected token deduction error: {token_err}")
            else:
                billed_tokens = total_tokens + carried_t
                merged_calls = dict(carried_calls)
                for k, v in api_calls.items():
                    merged_calls[k] = merged_calls.get(k, 0) + v

                # Deduct tokens from active subscriptions / free tier
                from app.modules.subscription.service import TokenService

                if billed_tokens > 0:
                    try:
                        ad_account_id = await self._billing_ad_account(snap_values, current_user.id)
                        await TokenService.deduct_tokens(
                            db=stream_db,
                            user_id=current_user.id,
                            amount=billed_tokens,
                            ad_account_id=ad_account_id,
                            action="chat_message",
                            metadata={
                                "thread_id": thread_id,
                                "cost_usd": round(total_cost + carried_c, 8),
                                "api_calls": merged_calls,
                            },
                        )
                    except HTTPException as token_err:
                        logger.error(f"Token deduction failed for user {current_user.id}: {token_err.detail}")
                    except Exception as token_err:
                        logger.error(f"Unexpected token deduction error: {token_err}")

                await graph.aupdate_state(config, {
                    "total_tokens": billed_tokens,
                    "token_cost_usd": round(total_cost + carried_c, 8),
                    "google_api_calls": merged_calls,
                    "pending_usage": None,
                })

        except Exception as e:
            logger.warning(f"AgentState billing update failed: {e}")
#    chat message
    # ── Run plumbing ─────────────────────────────────────────────────────────

    def _require_graph(self, request: Request):
        graph = getattr(request.app.state, "graph", None)
        if graph is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent not initialised — the database may be unavailable.",
            )
        return graph

    async def _snapshot(self, graph, config: dict):
        """``StateSnapshot`` for a thread, or ``None`` if it can't be read.

        Always ``subgraphs=True``: ``campaign_builder`` is a compiled subgraph, so
        its interrupts surface only in ``tasks[].state.tasks[].interrupts`` — the
        parent-level ``tasks[].interrupts`` is empty and every interrupt check
        would come back false.
        """
        try:
            return await graph.aget_state(config, subgraphs=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("aget_state failed", session=config, error=str(exc))
            return None

    @staticmethod
    def _innermost_snapshot(snap):
        """The deepest nested-subgraph state under ``snap`` (``snap`` itself when
        nothing is nested). Needs a snapshot fetched with ``subgraphs=True``."""
        innermost = snap

        def _descend(node) -> None:
            nonlocal innermost
            for task in (getattr(node, "tasks", None) or ()):
                nested = getattr(task, "state", None)
                if nested is not None and not isinstance(nested, dict):
                    innermost = nested
                    _descend(nested)

        _descend(snap)
        return innermost

    async def _current_checkpoint_ref(
        self, graph, config: dict
    ) -> tuple[Optional[str], Optional[str]]:
        """Address of the checkpoint the thread is sitting on, as ``(ns, id)``.

        Stamped onto the assistant message so a rewind can fork back to it.

        The namespace is not optional. ``campaign_builder`` is a compiled subgraph,
        and while it is the pending parent task every one of its ``interrupt()``
        calls happens inside a SINGLE parent superstep — so the parent's
        checkpoint_id is identical for every builder step and cannot identify one.
        Forking it always replays to the subgraph's first interrupt, whichever
        answer the user actually meant. The per-step state lives under
        ``checkpoint_ns = "campaign_builder:<task_id>"``, so we descend to the
        innermost paused state and record ITS config.

        Returns ``("", id)`` when nothing is nested — a pause in the parent graph —
        and ``(None, None)`` when the state cannot be read. ``""`` is a real
        namespace, so callers must test ``is not None``, never truthiness.
        """
        try:
            snap = await graph.aget_state(config, subgraphs=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("checkpoint ref read failed", error=str(exc))
            return None, None
        if snap is None:
            return None, None

        cfg = (getattr(self._innermost_snapshot(snap), "config", None) or {}).get("configurable") or {}
        checkpoint_id = cfg.get("checkpoint_id")
        if checkpoint_id is None:
            return None, None
        return cfg.get("checkpoint_ns") or "", checkpoint_id

    async def _commit_turn(
        self,
        graph,
        config: dict,
        conv_id,
        capture: "_TurnCapture",
        question: Optional[str],
        usage_cb,
        grounding_cb,
        current_user,
        api_cb=None,
        source: str = "chat",
        stopped: bool = False,
        start_checkpoint_ref: tuple[Optional[str], Optional[str]] = (None, None),
    ) -> None:
        """Bill the turn and persist its assistant message.

        Always runs in its own task (see ``runs.track_persist``) so a stop request
        or a dropped connection can never skip it. Skipping this step — because
        the client went away mid-stream and took the response generator with it —
        is the exact bug the run registry exists to fix.

        ``stopped`` + ``start_checkpoint_ref`` catch a different failure: a stop
        that lands before the in-flight superstep commits. Billing still runs —
        tokens were really spent — but the assistant row is skipped, because the
        checkpoint (what the agent remembers) never advanced past where the turn
        started. Writing it anyway would show text AgentState has no memory of,
        which the next turn's replay would then re-emit as if it were new.
        """
        # Durable per-thread/per-user usage log. Deliberately BEFORE short_db is
        # opened and on its own session — see flush_usage_events' docstring for
        # why it must not share a session with TokenService.deduct_tokens (called
        # from _bill_usage below), and unconditional so it survives an interrupt
        # or a 402 that _bill_usage swallows.
        await flush_usage_events(
            user_id=str(current_user.id),
            thread_id=(config.get("configurable") or {}).get("thread_id"),
            usage_cb=usage_cb, grounding_acc=grounding_cb, api_acc=api_cb,
            source=source,
        )

        async with AsyncSessionLocal() as short_db:
            try:
                await self._bill_usage(
                    graph, config, usage_cb, None, short_db, current_user, grounding_cb, api_cb,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Token billing failed", error=str(exc))

            # Trim trailing whitespace — narrator emits text with trailing "\n\n"
            # as a between-emission separator; the final blob shouldn't end in it.
            capture.assistant_text = capture.assistant_text.rstrip()
            if capture.is_empty:
                return

            checkpoint_ns, checkpoint_id = await self._current_checkpoint_ref(graph, config)
            if (
                stopped
                and checkpoint_id is not None
                and (checkpoint_ns, checkpoint_id) == start_checkpoint_ref
            ):
                # checkpoint_id is not None guards a read failure on either side —
                # _current_checkpoint_ref returns (None, None) then, and two
                # failures must never compare equal to "nothing committed".
                return
            try:
                await self.repository.create_chat_message(short_db, {
                    "conversation_id": conv_id,
                    "role": "assistant",
                    "content": capture.assistant_text,
                    "question": question or None,
                    "thinking": "\n".join(capture.thinking),
                    "langchain_data": capture.metadata or None,
                    "checkpoint_id": checkpoint_id,
                    "checkpoint_ns": checkpoint_ns,
                })
            except Exception as exc:  # noqa: BLE001
                logger.error("Error saving assistant message------------>>", error=str(exc))

    def _subscription_response(self, session_id: str, from_seq: int = 0) -> StreamingResponse:
        """SSE response that follows a run: backlog from ``from_seq``, then live."""
        async def event_stream() -> AsyncGenerator[str, None]:
            async for seq, event in runs.subscribe(session_id, from_seq):
                yield self._sse(event, seq)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    async def _start_and_stream(self, session_id: str, producer) -> StreamingResponse:
        try:
            await runs.start_run(session_id, producer)
        except RunBusyError:
            # Structured like the pending_action 409 so the client can branch on it:
            # a busy thread means "attach to the run that exists", not "send failed".
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "run_busy",
                    "message": "This conversation already has a turn in progress.",
                },
            )
        except TooManyRunsError:
            raise HTTPException(
                status_code=429,
                detail="Too many active AI streams. Please try again later.",
            )
        return self._subscription_response(session_id, 0)

    # ── Endpoints ────────────────────────────────────────────────────────────

    @staticmethod
    def _turn_state(message: str, user_id) -> dict:
        """Per-turn graph input for a fresh (non-resume) user message.

        Shared by ``/chat`` and by ``/rewind`` when it edits a message the graph
        finished answering (no interrupt to resume) — an edit there IS a new turn.
        """
        return {
            "messages": [HumanMessage(content=message)],
            "user_id": str(user_id),
            "next_nodes": ["entry"],
            "pending_action": None,
            "thinking": [],
            "current_turn_tool_errors": None,
            # Freshness signal for the post-publish route; only ever true for the
            # turn the publish happened on. Reset here because the builder sets it
            # from several exits and no node reliably clears it.
            "just_published": None,
        }

    async def chat_stream(
        self,
        payload,
        request,
        current_user
    ) -> StreamingResponse:
        """
            Send a message to the AI agent and receive a streaming SSE response.

            Pass `session_id` to continue an existing conversation thread.
            Omit it (or pass null) to start a fresh session — a new UUID is
            generated and returned as the first SSE event:
            data: {"type": "session_id", "content": "<uuid>"}

            The graph run itself happens in a background task; this response is
            just a subscriber to it. Disconnecting does not stop the turn.
        """
        graph = self._require_graph(request)

        session_id = payload.session_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": session_id}}

        # A thread paused at an interrupt has to be answered through /resume.
        # astream()-ing fresh input here makes LangGraph drop the pending task and
        # restart the interrupted node, so the wizard silently loses its place.
        # Hand the client the live pending_action instead and let it re-render the
        # widget it was supposed to be showing.
        # FAIL CLOSED. `_snapshot` swallows a checkpointer error and returns None,
        # which used to read as "no interrupt pending" — so a transient DB blip let
        # this request astream a fresh HumanMessage over a LIVE interrupt, which in
        # LangGraph discards the pending task and restarts the interrupted node.
        # A 503 the client can retry is strictly better than silently destroying
        # the step the user was answering.
        _snap = await self._snapshot(graph, config)
        if _snap is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "Couldn't read the conversation state just now — try that again.",
                    "code": "state_unavailable",
                },
            )
        pending = pending_interrupt_value(_snap)
        if pending is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "This conversation is waiting on an answer to the current step.",
                    "pending_action": pending,
                },
            )

        async with AsyncSessionLocal() as short_db:
            conv = await self.repository.find_specific_user_chat(short_db, session_id, current_user.id)

            # If no existing chat found, create a new one
            if not conv:
                conv = await self.repository.create_conversation(short_db, {
                    "thread_id": session_id,
                    "user_id": current_user.id,
                    "title": payload.message[:50] or "New Chat"
                })

            await self.repository.create_chat_message(short_db, {
                "conversation_id": conv.id,
                "role": "user",
                "content": payload.message,
            })
            conv_id = conv.id

        # Per-turn fields only — keys with reducers (user_info, geo_data,
        # wizards_completed, etc.) preserve themselves across turns. Keys
        # without reducers (marketing_plan, wizard scratch, etc.) MUST NOT be
        # written here because LangGraph merges this dict into the checkpoint
        # and non-reducer keys overwrite — writing geo_data=None every turn
        # would silently wipe the geo result, causing maid_wizard to skip.
        _per_turn_state: dict = self._turn_state(payload.message, current_user.id)

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
                "google_api_calls": {},
                "pending_usage": None,
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
        # Where the checkpoint sits before this turn does any work — the baseline
        # a stop compares against to tell "the superstep committed" from "it
        # didn't" (see _commit_turn).
        start_checkpoint_ref = await self._current_checkpoint_ref(graph, config)

        async def producer(emit: runs.Emit) -> None:
            capture = _TurnCapture()
            stopped = False
            emit({"type": "session_id", "content": session_id})
            # Instant motion: the entry node is a blocking Pro LLM call (~300-800ms)
            # that emits nothing until it resolves, so the screen sits dead. Emit one
            # immediate reasoning beat so the UI shows activity <200ms. source != "punk"
            # → not captured into thinking, so it is never persisted.
            emit({"type": "thinking", "source": "system", "content": "Reading your message..."})

            async def rename_from_state(state_values: dict) -> None:
                async with AsyncSessionLocal() as short_db:
                    conv_in_db = await self.repository.find_specific_user_chat(
                        short_db, session_id, current_user.id
                    )
                    if conv_in_db:
                        await update_conversation_title_from_context(
                            short_db,
                            conv_in_db,
                            latest_user_text=payload.message,
                            state_values=state_values,
                        )

            # Capture token usage for EVERY LLM call in this turn (all nodes,
            # wizards, tools) via the contextvar-based callback — no per-node
            # plumbing. Totals are billed once after the stream completes.
            #
            # turn_identity is NOT usage capture: it tags vendor calls made deep
            # inside the graph (unacast_query.reconcile_call) with who they
            # belong to, at the moment the call happens rather than at billing
            # time — see app/graph/usage.py.
            with get_usage_metadata_callback() as usage_cb, \
                 grounding_usage_callback() as grounding_cb, \
                 api_call_callback() as api_cb, \
                 turn_identity(str(current_user.id), session_id):
                try:
                    async for event in self._iter_graph_events(
                        graph, initial_state, config, rename_from_state
                    ):
                        capture.absorb(event)
                        emit(event)
                except asyncio.CancelledError:
                    stopped = True
                    emit({"type": "cancelled"})
                    raise
                finally:
                    # Shielded + tracked: the persist must survive the cancellation
                    # that a stop request delivers to this task.
                    persist = runs.track_persist(self._commit_turn(
                        graph, config, conv_id, capture, payload.question,
                        usage_cb, grounding_cb, current_user, api_cb,
                        stopped=stopped, start_checkpoint_ref=start_checkpoint_ref,
                    ), session_id)
                    with contextlib.suppress(asyncio.CancelledError):
                        await asyncio.shield(persist)

        return await self._start_and_stream(session_id, producer)

    async def _stream_resume_turn(
        self,
        graph,
        config: dict,
        value: str,
        capture: "_TurnCapture",
        emit,
        on_state_snapshot=None,
    ) -> None:
        """Run one ``Command(resume=value)`` turn: preflight, replay gate, emit.

        Shared by ``/resume`` and by the resubmit half of ``/rewind`` — an edit IS
        a resume with a different value, so the two must not drift apart.
        """
        # Resume orchestration — intent re-extraction and MAID map re-emit live in
        # services/resume_preflight. Called here so its LLM calls land inside the
        # caller's usage callback.
        preflight = await run_preflight(graph, config, value)

        for ev in preflight.sse_events:
            capture.absorb(ev)
            emit(ev)

        # Events emitted by preflight (MAID map re-emit, etc.) precede any resume
        # boundary but are genuine resume-turn output, not the duplicate
        # pre-interrupt re-fire. The rewind below restores to this baseline, not to
        # empty, so they survive.
        baseline = capture.baseline()

        # Interrupt-replay stream gate: on a resume, LangGraph replays the paused
        # node top-to-bottom, re-emitting every already-answered interrupt's events
        # before the new work. `replay_boundary_skip` (= paused interrupt index + 1)
        # is how many replayed `resume_boundary` events precede the genuinely-new
        # content; suppress everything until then, then forward live. skip==0 (fresh
        # /chat, non-builder interrupt, or no stamp) → no gating.
        #
        # Suppressed events are never emitted at all, not merely withheld from this
        # response — the run buffers what it emits for replay, so anything emitted
        # here would resurface on a reconnect.
        skip = preflight.replay_boundary_skip
        boundaries_seen = 0

        async for event in self._iter_graph_events(
            graph, Command(resume=value), config, on_state_snapshot
        ):
            # Persist bookkeeping first, gating second — the DB copy is rewound by
            # resume_boundary rather than by the gate.
            #
            # The resumed step's pre-interrupt narration is re-emitted on replay
            # (the in-node `skip_emit` guard is inert on the builder path —
            # `pending_action` is never persisted to state with the active step_key,
            # so resume detection never fires). Reset the capture buckets on
            # `resume_boundary` — emitted by wizard_interrupt at the interrupt()
            # return, the structural resume point — so only genuinely-new events are
            # saved, without re-introducing the old gate's bug of dropping the
            # post-resume handoff / audience reveal. On multiple boundaries this
            # keeps the work after the LAST resume.
            if event.get("type") == "resume_boundary":
                capture.reset_to(baseline)
            else:
                capture.absorb(event)

            if skip > 0:
                if event.get("type") == "resume_boundary":
                    boundaries_seen += 1
                    continue  # internal marker; never forward on a gated resume
                if boundaries_seen < skip:
                    continue

            emit(event)

    async def resume_chat(
        self,
        session_id,
        payload,
        request,
        current_user
    ) -> StreamingResponse:
        """
        Resume a paused agent thread after the user answers an interrupt prompt.

        `value` is the raw string the user provided (option selection, free text,
        lat/lng JSON string, or "skip" for file-upload interrupts).
        """
        graph = self._require_graph(request)

        async with AsyncSessionLocal() as short_db:
            # Ensure conversation exists
            conv = await self.repository.find_specific_user_chat(short_db, session_id, current_user.id)
            if not conv:
                raise HTTPException(status_code=404, detail="Conversation not found")

            # Save user response to DB
            await self.repository.create_chat_message(short_db, {
                "conversation_id": conv.id,
                "role": "user",
                "content": payload.value,
                "question": payload.question or None,
            })

            await self._persist_confirmed_stepper_value(short_db, conv.id, payload.value)
            conv_id = conv.id

        config = {"configurable": {"thread_id": session_id}}
        # Baseline for the stop-vs-committed check in _commit_turn.
        start_checkpoint_ref = await self._current_checkpoint_ref(graph, config)

        # NOTE: no pre-stream title enrichment here. It previously required a
        # SYNCHRONOUS graph.get_state(config) — a blocking Redis read on the event
        # loop — purely to feed state_values into the title call. Title is already
        # re-derived in-stream via rename_from_state (on_state_snapshot), so both the
        # sync read and the blocking title call are dropped from time-to-first-byte.

        async def producer(emit: runs.Emit) -> None:
            capture = _TurnCapture()
            stopped = False
            # Instant motion before preflight (checkpoint reads + possible extraction
            # LLM) and the resumed node run. source != "punk" → never persisted.
            emit({"type": "thinking", "source": "system",
                  "content": "Got it, picking up where we left off..."})

            # Capture token usage for the whole resume turn — including the
            # preflight intent-extraction LLM calls — via the contextvar
            # callback. Totals are billed once after streaming completes.
            # turn_identity tags vendor calls with who they belong to — see the
            # chat producer above.
            with get_usage_metadata_callback() as usage_cb, \
                 grounding_usage_callback() as grounding_cb, \
                 api_call_callback() as api_cb, \
                 turn_identity(str(current_user.id), session_id):
                try:
                    async def rename_from_state(state_values: dict) -> None:
                        async with AsyncSessionLocal() as short_db:
                            conv_in_db = await self.repository.find_specific_user_chat(
                                short_db, session_id, current_user.id
                            )
                            if conv_in_db:
                                await update_conversation_title_from_context(
                                    short_db,
                                    conv_in_db,
                                    latest_user_text=payload.value,
                                    state_values=state_values,
                                )

                    await self._stream_resume_turn(
                        graph, config, payload.value, capture, emit, rename_from_state
                    )
                except asyncio.CancelledError:
                    stopped = True
                    emit({"type": "cancelled"})
                    raise
                finally:
                    persist = runs.track_persist(self._commit_turn(
                        graph, config, conv_id, capture, payload.question,
                        usage_cb, grounding_cb, current_user, api_cb,
                        stopped=stopped, start_checkpoint_ref=start_checkpoint_ref,
                    ), session_id)
                    with contextlib.suppress(asyncio.CancelledError):
                        await asyncio.shield(persist)

        return await self._start_and_stream(session_id, producer)

    async def attach_stream(
        self,
        session_id: str,
        request: Request,
        current_user: User,
        db: AsyncSession,
        from_seq: int = 0,
    ):
        """Re-attach to a turn already in flight (after a refresh or a thread switch).

        ``204`` means there is nothing running for this thread and the client should
        render from history + ``/status`` instead.
        """
        conv = await self.repository.find_specific_user_chat(db, session_id, current_user.id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        # describe(), not get_run(): the run may be live on ANOTHER instance, and
        # the local-only lookup reported that as "no run", so a reconnect got a
        # 204 and rendered an empty screen instead of attaching.
        if await runs.describe(session_id) is None:
            return Response(status_code=204)
        return self._subscription_response(session_id, max(0, from_seq))

    def _publish_locked(self, snapshot) -> bool:
        """True once a campaign is live on Meta.

        Rewinding past a publish would leave the checkpoint describing ad objects
        that already exist and are spending; nothing here can un-publish them.
        """
        if snapshot is None:
            return False
        values = getattr(snapshot, "values", None) or {}
        if values.get("meta_campaign_ids"):
            return True
        # ``publish`` writes the ids into the builder's scratch and only
        # builder_finalize copies them up — and the go_live_confirm gate pauses in
        # between. At that pause the campaign already exists on Meta (paused) while
        # the parent values still look unpublished, so a rewind there would let the
        # builder publish a SECOND campaign. Same gap edit_block_reason closes
        # for prose edits (field_owner_registry).
        inner_values = getattr(self._innermost_snapshot(snapshot), "values", None) or {}
        for vals in (values, inner_values):
            bs = vals.get("campaign_builder_state") if hasattr(vals, "get") else None
            if isinstance(bs, dict) and bs.get("meta_campaign_ids"):
                return True
        return False

    def _can_undo(self, snapshot, last_two, running: bool, ledger_locked: bool = False) -> bool:
        """Global 'is any rewind possible' flag for ``/status``.

        Per-message editability is decided on the client from each message's
        ``checkpoint_id``; this stays as the coarse kill-switch.

        ``ledger_locked`` is the publish-ledger half of the lock (Meta objects
        exist that state has not recorded yet) — it needs a DB read, so the async
        caller computes it and passes it in.
        """
        if running:
            return False
        if len(last_two) < 2 or not self._is_rewindable(last_two[1]):
            return False
        return not (ledger_locked or self._publish_locked(snapshot))

    async def _rewind_locked(self, conv, graph, config: dict, db: AsyncSession, user_id, snapshot=None) -> bool:
        """True when nothing before this point may be rewound: a campaign is live
        on Meta, or its objects are partly built (ledger) and not yet recorded."""
        snap = snapshot if snapshot is not None else await self._snapshot(graph, config)
        if self._publish_locked(snap):
            return True
        return await self._publish_in_flight(conv, graph, config, db, user_id)

    @staticmethod
    def _is_rewindable(message) -> bool:
        """True when this assistant message carries a usable fork address.

        Needs BOTH halves. ``checkpoint_ns is None`` marks a row written before the
        namespace was recorded, whose ``checkpoint_id`` is the ambiguous parent
        stamp shared by every builder step — forking it rewinds to the wrong step,
        so those rows are refused rather than trusted. ``""`` is a legitimate
        namespace (a pause in the parent graph), hence ``is not None``.
        """
        if message is None:
            return False
        return (
            getattr(message, "checkpoint_id", None) is not None
            and getattr(message, "checkpoint_ns", None) is not None
        )

    async def get_status(
        self,
        session_id: str,
        request: Request,
        current_user: User,
        db: AsyncSession,
    ) -> dict:
        """Where this thread stands right now — the client's single source of truth.

        The widget the UI should be showing comes from the checkpoint, not from
        scraping the last assistant message's ``langchain_data``: ``wizard_interrupt``
        passes the ``pending_action`` dict straight into ``interrupt()``, so
        ``tasks[].interrupts[].value`` IS that payload.
        """
        graph = self._require_graph(request)

        conv = await self.repository.find_specific_user_chat(db, session_id, current_user.id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        config = {"configurable": {"thread_id": session_id}}
        snapshot = await self._snapshot(graph, config)
        pending = pending_interrupt_value(snapshot)

        map_data = None
        if pending is not None:
            # Restores the MAID split-view for a client that refreshed while the
            # audience step was on screen. Reuses the resume-path re-emit, which
            # rebuilds from the maid_extractions row + checkpoint.
            event = await maid_map_reemit_event(graph, config, snapshot=snapshot)
            if event is not None:
                map_data = event.get("content")

        run = await runs.describe(session_id)
        last_two = await self.repository.get_last_assistant_messages(db, conv.id, limit=2)
        running = bool(run and run["running"])

        # The ledger half of the publish lock costs a DB read, so only pay it when
        # everything else already says a rewind is possible.
        ledger_locked = False
        if self._can_undo(snapshot, last_two, running):
            ledger_locked = await self._publish_in_flight(
                conv, graph, config, db, current_user.id
            )

        return {
            "session_id": session_id,
            "running": bool(run and run["running"]),
            "run_id": run["run_id"] if run else None,
            "last_seq": run["last_seq"] if run else -1,
            "interrupted": pending is not None,
            # State carries the caller's live Meta access token; never let one reach
            # a browser, not even its owner's.
            "pending_action": _redact_secrets(pending) if pending else None,
            "map_data": _redact_secrets(map_data) if map_data else None,
            # `running` is passed in rather than re-derived: it is one
            # cross-instance lookup per request, and having two places ask the
            # question is how they end up disagreeing.
            "can_undo": self._can_undo(snapshot, last_two, running, ledger_locked),
        }

    @staticmethod
    def _answered_step_key(messages: list) -> Optional[str]:
        """The step_key of the question the tail user message was answering.

        Read off the last assistant message's persisted ``pending_action`` rather
        than the graph, because that record is what the user was actually looking
        at when they submitted.
        """
        for m in messages:  # newest first
            if m.role != "assistant":
                continue
            data = m.langchain_data or {}
            return ((data.get("pending_action") or {}).get("step_key")) or None
        return None

    @staticmethod
    def _asking_message(messages: list):
        """The assistant message that posed the question the tail was answering."""
        for m in messages:  # newest first
            if m.role == "assistant":
                return m
        return None

    async def cancel_run(
        self,
        session_id: str,
        request: Request,
        current_user: User,
        db: AsyncSession,
    ) -> dict:
        """Stop button. Returns once the partial turn has been persisted.

        Also reconciles the transcript with the checkpoint. ``resume_chat`` writes
        the user's answer to the DB *before* starting the run, but
        ``Command(resume=...)`` only lands when the superstep commits — so whether
        that answer was actually consumed depends on when the stop arrived. Left
        alone, the transcript shows an answered question that the agent never saw
        and the same widget is re-offered beside it.

        So: if the graph is still sitting on the very step the tail user message was
        answering, that answer was never consumed. Drop it (and any partial reply
        from the aborted turn) and hand the text back, making stop mean "un-submit".
        If the graph moved on, the answer counted and the turn stays.
        """
        conv = await self.repository.find_specific_user_chat(db, session_id, current_user.id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        stopped = await runs.cancel(session_id)
        result = {
            "outcome": CancelOutcome.NOT_RUNNING,
            "restored_value": None,
        }
        if not stopped:
            return result

        # Something was cancelled, so the floor is KEPT: whatever the graph had
        # already taken stays, and the partial reply was persisted by the shielded
        # _commit_turn before runs.cancel returned.
        result["outcome"] = CancelOutcome.KEPT

        graph = getattr(request.app.state, "graph", None)
        if graph is None:
            return result

        config = {"configurable": {"thread_id": session_id}}
        if await self._publish_in_flight(conv, graph, config, db, current_user.id):
            result["outcome"] = CancelOutcome.PUBLISH_INTERRUPTED
            return result

        current_step = (pending_interrupt_value(await self._snapshot(graph, config)) or {}).get("step_key")
        if not current_step:
            return result

        current_ns, current_ckpt = await self._current_checkpoint_ref(graph, config)

        async with AsyncSessionLocal() as short_db:
            tail = await self.repository.get_last_messages(short_db, conv.id, limit=4)
            if not tail or tail[0].role != "user":
                return result
            if self._answered_step_key(tail) != current_step:
                # The graph moved on — the answer was consumed before the stop landed.
                return result

            # step_key alone cannot tell "never moved" from "consumed the answer and
            # re-asked the SAME step" — a validation retry produces the identical key,
            # and rolling back there deletes a message the graph has already acted on.
            # The checkpoint address can tell them apart: a committed superstep always
            # writes a new checkpoint_id. Compare against the stamp on the assistant
            # message that posed the question. Rows predating the stamp carry
            # checkpoint_id None, so they fall back to the step_key verdict above.
            asking = self._asking_message(tail)
            asked_ckpt = getattr(asking, "checkpoint_id", None) if asking else None
            if asked_ckpt is not None and current_ckpt is not None:
                asked_ns = getattr(asking, "checkpoint_ns", None)
                if (current_ckpt, current_ns) != (asked_ckpt, asked_ns):
                    # New checkpoint => a superstep committed => the answer counted.
                    return result

            orphan = tail[0]
            result["restored_value"] = orphan.content
            result["outcome"] = CancelOutcome.UNSENT
            await self.repository.delete_messages_from(short_db, conv.id, orphan.auto_id)

        return result

    async def _publish_in_flight(self, conv, graph, config: dict, db: AsyncSession, user_id) -> bool:
        """True when the cancel landed inside ``publish_campaign_to_meta``.

        The publish ledger commits after each individual Meta create, outside the
        LangGraph checkpoint; ``meta_campaign_ids`` only reaches state once the whole
        pipeline returns. Ledger populated + state empty therefore means objects exist
        on Meta that this turn never got to record. They are all PAUSED
        (``meta_ads.create_ad`` hard-pins it), so nothing is spending — but the next
        publish resumes from that ledger, and the user is owed that fact.
        """
        try:
            snapshot = await self._snapshot(graph, config)
            if snapshot is not None and (getattr(snapshot, "values", None) or {}).get("meta_campaign_ids"):
                return False  # publish completed; ids are committed
            from app.modules.campaigns.repository import CampaignsRepository

            draft = await CampaignsRepository().get_draft_for_conversation(
                db, user_id=user_id, conversation_id=conv.id
            )
            state = (draft.publish_state if draft else None) or {}
            # Any created id means the pipeline got past its first Meta call.
            return any(
                state.get(k)
                for k in ("campaign_id", "campaigns", "adsets", "ads",
                          "custom_audience_id", "lead_form_id")
            )
        except Exception as exc:  # noqa: BLE001 — never let this block a stop
            logger.warning("publish-in-flight check failed", error=str(exc))
            return False

    async def rewind(
        self,
        session_id: str,
        payload,
        request: Request,
        current_user: User,
    ) -> StreamingResponse:
        """Rewind to a previous answer — undo it, edit it, or retry it.

        ``message_id`` picks the user message to rewind to (default: the most
        recent one). ``value`` decides what happens once the graph is back there:

            {}                        undo   — re-ask the question, leave it open
            {message_id}              undo a specific answer
            {message_id, value}       edit   — re-ask silently, answer with `value`
            {message_id, value: same} retry

        Rewinding is a FORK, not a replay. Streaming straight from the anchor
        checkpoint id does NOT re-ask: the resume value the user already gave is
        recorded in that checkpoint's pending writes, so ``interrupt()`` returns it
        again and the graph marches forward past the step being undone (verified in
        tests/test_undo_rewind.py). ``aupdate_state`` writes a NEW checkpoint
        descending from the anchor; the pending writes belong to the anchor's id, so
        the fork starts clean and the node re-interrupts.
        """
        graph = self._require_graph(request)
        config = {"configurable": {"thread_id": session_id}}

        new_value = (getattr(payload, "value", None) or "").strip() or None
        resubmit = new_value is not None
        payload_question = getattr(payload, "question", None) or None

        # Ownership FIRST. Every later refusal (busy, published, not rewindable)
        # says something about the thread, so it must not be reachable by a caller
        # who does not own it.
        async with AsyncSessionLocal() as short_db:
            conv = await self.repository.find_specific_user_chat(short_db, session_id, current_user.id)
            if not conv:
                raise HTTPException(status_code=404, detail="Conversation not found")
            conv_id = conv.id

            # Fast, friendly refusal only. The claim in start_run is what actually
            # closes the race — this check and that claim are not atomic.
            if await runs.is_running_anywhere(session_id):
                raise HTTPException(
                    status_code=409,
                    detail="Stop the current turn before rewinding it.",
                )

            if await self._rewind_locked(conv, graph, config, short_db, current_user.id):
                raise HTTPException(
                    status_code=409,
                    detail="This campaign is already published — earlier steps can no longer be changed.",
                )

            message_id = getattr(payload, "message_id", None)
            if message_id:
                target = await self.repository.get_message_by_id(short_db, conv_id, message_id)
            else:
                target = await self.repository.get_last_user_message(short_db, conv_id)
            if target is None or target.role != "user":
                raise HTTPException(status_code=404, detail="No such message to rewind to.")

            anchor = await self.repository.get_assistant_message_before(
                short_db, conv_id, target.auto_id
            )
            if anchor is None or not self._is_rewindable(anchor):
                # The opening message has no preceding assistant turn to fork from,
                # and pre-namespace rows carry an ambiguous parent-only stamp.
                raise HTTPException(
                    status_code=409,
                    detail="This message can no longer be changed.",
                )

            # Interrupts inside ONE node run share a single checkpoint, so several
            # assistant rows can carry the same stamp (a "group"). The stamp cannot
            # tell those rows apart: a restart re-arms the node's FIRST interrupt, a
            # fork its SECOND (tests/test_rewind_restart.py, test_undo_rewind.py).
            # plan_rewind honours a grouped anchor only when the chosen mode will land
            # where the user pointed, and refuses otherwise — before anything is
            # changed. Doing it anyway answered the wrong question, or cut messages
            # the graph still remembered.
            group = await self.repository.get_assistants_with_checkpoint(
                short_db, conv_id, anchor.checkpoint_ns, anchor.checkpoint_id
            )
            rewind_plan = plan_rewind(
                anchor_ns=anchor.checkpoint_ns or "",
                anchor_id=anchor.id,
                group_ids=[g.id for g in group],
                restart_enabled=settings.REWIND_RESTART_ENABLED,
            )
            if rewind_plan.refusal:
                raise HTTPException(status_code=409, detail=rewind_plan.refusal)

            # What the anchor's checkpoint was doing: paused on a step, or idle (the
            # turn ran to END — a plain chat answer). Read from the checkpoint, not
            # from the row, for the same reason /status does. Fail closed: an aged
            # or unreadable anchor is refused, not guessed at.
            anchor_snap = await self._snapshot(graph, {
                "configurable": {
                    "thread_id": session_id,
                    "checkpoint_id": anchor.checkpoint_id,
                    "checkpoint_ns": anchor.checkpoint_ns,
                }
            })
            if anchor_snap is None:
                raise HTTPException(
                    status_code=409,
                    detail="This message can no longer be changed.",
                )
            idle_anchor = pending_interrupt_value(anchor_snap) is None
            # A builder step is RESTARTED from its saved state; an idle anchor (the turn
            # ran to END) has no step to re-arm and stays a fork to a new turn.
            restart = rewind_plan.mode == "restart" and not idle_anchor
            anchor_values = dict(getattr(anchor_snap, "values", None) or {})
            # The question's own text. A restart re-asks from saved state, where the
            # narrator has nothing buffered (the beats were added by the work that
            # PRECEDED the question), so the re-ask arrives as a widget with no words.
            anchor_text = (getattr(anchor, "content", None) or "").strip()
            # The step the user was actually looking at when they answered: read
            # from the row that posed it (cancel_run does the same), NOT from the
            # checkpoint — a shared checkpoint reports its FIRST interrupt, which is
            # a different step whenever the group has more than one row.
            expected_step = (
                ((anchor.langchain_data or {}).get("pending_action") or {}).get("step_key")
                or None
            )

            target_checkpoint = anchor.checkpoint_id
            target_ns = anchor.checkpoint_ns
            undone_text = target.content
            target_id = target.id
            if resubmit or idle_anchor:
                # An edit replaces the answer itself: the anchor's own row stays,
                # because the silent re-ask writes no new question row. With an idle
                # anchor there is no re-ask at all, so undo cuts from the answer too.
                delete_from, cut_id = target.auto_id, target.id
            else:
                # Undo on an armed anchor: the re-ask re-emits the question and
                # writes its own copy, so the anchor must go too or history shows it
                # twice.
                delete_from, cut_id = anchor.auto_id, anchor.id
            anchor_id = anchor.id
            # Everything after the answer being changed: shown to the user so "Change
            # answer" says what it will discard.
            discarded = len(await self.repository.get_messages_after(short_db, conv_id, target.auto_id))

        # Fork the checkpoint the anchor recorded — NAMESPACE INCLUDED. Passing
        # checkpoint_ns="" here instead would fork the parent graph, and since every
        # campaign_builder step shares one parent checkpoint that lands on the
        # subgraph's first interrupt no matter which answer was targeted.
        # ``checkpoint_ns`` is also required structurally: the checkpointer raises
        # KeyError without the key present at all.
        #
        # The fork and the cut run INSIDE the producer, i.e. after start_run has
        # claimed the thread. Done before the claim they raced any /resume, /chat or
        # second /rewind that landed in between, writing a checkpoint underneath a
        # live run.
        async def producer(emit: runs.Emit) -> None:
            capture = _TurnCapture()
            stopped = False
            emit({"type": "session_id", "content": session_id})

            # The claim is ours now, so re-check the one thing that can change
            # between the pre-check above and here: a publish that just landed.
            async with AsyncSessionLocal() as lock_db:
                still_locked = await self._rewind_locked(
                    SimpleNamespace(id=conv_id), graph, config, lock_db, current_user.id
                )
            if still_locked:
                emit({"type": "rewind_failed", "content": {
                    "message": "This campaign is already published — earlier steps can no longer be changed.",
                }})
                return

            # Fork FIRST, delete second. A failing aupdate_state (aged checkpoint_id,
            # checkpointer KeyError, pool error) must not have already deleted the
            # rows — that leaves the transcript truncated over an unforked
            # checkpoint, unrecoverable. Forking first means the worst a mid-op
            # failure leaves is extra rows over an already-rewound graph, which a
            # retry or a history refetch repairs. Still one shielded+tracked unit so
            # a disconnect can't orphan either half — the same mechanism
            # _commit_turn relies on.
            forked: dict = {}

            async def _cut_and_fork() -> None:
                try:
                    if restart:
                        # Resume from that point: put the step's saved state on the
                        # thread head and let the builder start fresh (see
                        # rewind_restore). Forking the step's checkpoint instead
                        # swallows the thread's last resume value and walks past it.
                        await restore_from_anchor(graph, config, anchor_values)
                        forked["config"] = config
                    else:
                        forked["config"] = await graph.aupdate_state(
                            {
                                "configurable": {
                                    "thread_id": session_id,
                                    "checkpoint_id": target_checkpoint,
                                    "checkpoint_ns": target_ns,
                                }
                            },
                            # Tokens carried for the discarded turn would otherwise be
                            # billed onto the next completed turn (_bill_usage's
                            # pending_usage carry).
                            {"pending_usage": None},
                        )
                except Exception as exc:  # noqa: BLE001
                    forked["error"] = str(exc)
                    return
                async with AsyncSessionLocal() as cut_db:
                    await self.repository.delete_messages_from(cut_db, conv_id, delete_from)

            # Detached and tracked, not merely shielded: shielding alone keeps the
            # inner coroutine alive but leaves nothing awaiting it, so a disconnect
            # orphans the fork half. track_persist puts it where drain_persists can
            # finish it.
            cut = runs.track_persist(_cut_and_fork(), session_id)
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(cut)
            fork_config = forked.get("config")
            if fork_config is None:
                emit({"type": "rewind_failed", "content": {
                    "message": (
                        f"Could not rewind: {forked['error']}" if "error" in forked
                        else "The rewind was interrupted. Reload the conversation."
                    ),
                }})
                return

            # The narrator's "already told" ring lives outside the checkpoint and
            # still holds lines from the branch that was just discarded.
            with contextlib.suppress(Exception):
                from app.graph.narrator import beats as _beats

                fork_snapshot = await self._snapshot(graph, config)
                await _beats.reset_history(
                    (getattr(fork_snapshot, "values", None) or {}) if fork_snapshot else {}
                )

            # Baseline for the stop-vs-committed check in _commit_turn: the checkpoint
            # now sits at the freshly forked address, since aupdate_state just wrote it.
            start_checkpoint_ref = await self._current_checkpoint_ref(graph, config)

            emit({"type": "rewind", "content": {
                "undone_text": undone_text,
                "resubmitting": resubmit,
                # What the user edited it TO, so the client can keep the edited bubble
                # on screen instead of waiting for the history refetch.
                "new_text": new_value,
                "discarded": discarded,
                "mode": "restart" if restart else "fork",
                "message_id": str(target_id),
                "anchor_id": str(anchor_id),
                # The server is the only side that knows the real cut point (it can
                # differ from both ids above); the client cuts its blocks here.
                "cut_id": str(cut_id),
            }})
            emit({"type": "thinking", "source": "system", "content": (
                "Resubmitting..." if resubmit else "Rewinding to your last answer..."
            )})
            # The re-open below is silent (no assistant text until it finishes): a
            # planner call, then the narrator. The `update` frame is what the UI shows
            # as the running step label, so say what is happening instead of leaving the
            # screen quiet right after the "later messages were removed" line.
            emit({"type": "update", "content": (
                "Re-opening that step…" if restart else "Going back to that step…"
            )})

            async def rename_from_state(state_values: dict) -> None:
                async with AsyncSessionLocal() as short_db:
                    conv_in_db = await self.repository.find_specific_user_chat(
                        short_db, session_id, current_user.id
                    )
                    if conv_in_db:
                        await update_conversation_title_from_context(
                            short_db,
                            conv_in_db,
                            latest_user_text=new_value,
                            state_values=state_values,
                        )

            # turn_identity tags vendor calls with who they belong to — see the
            # chat producer above.
            with get_usage_metadata_callback() as usage_cb, \
                 grounding_usage_callback() as grounding_cb, \
                 api_call_callback() as api_cb, \
                 turn_identity(str(current_user.id), session_id):
                try:
                    if idle_anchor:
                        # Nothing was waiting on an answer at the anchor: the turn
                        # ran to END (a plain chat reply). There is no interrupt to
                        # replay or re-arm — an undo is just the cut above, and an
                        # edit is a brand-new turn on the forked state, exactly what
                        # /chat does. Replaying here used to end in `rewind_degraded`
                        # and drop the edited text on the floor.
                        if not resubmit:
                            return
                        async with AsyncSessionLocal() as short_db:
                            await self.repository.create_chat_message(short_db, {
                                "conversation_id": conv_id,
                                "role": "user",
                                "content": new_value,
                                "question": payload_question,
                            })
                        async for event in self._iter_graph_events(
                            graph, self._turn_state(new_value, current_user.id),
                            config, rename_from_state,
                        ):
                            capture.absorb(event)
                            emit(event)
                        return

                    # Phase 1 — replay the forked checkpoint so the node re-fires its
                    # interrupt. On an edit this is bookkeeping the user should not
                    # have to watch: the question is still in history and they are
                    # about to answer it, so consume the events without emitting or
                    # capturing them.
                    replay: list[dict] = []
                    # An undo on a restart is held too, so the question's text can be
                    # put back in front of the widget (see _flush_replay).
                    hold_replay = resubmit or bool(restart and anchor_text)
                    async for event in self._iter_graph_events(graph, None, fork_config):
                        replay.append(event)
                        # An `error` frame is never bookkeeping — swallowing it on a
                        # resubmit is what turned a real graph failure into a bare
                        # "could not re-open that step" with no cause attached.
                        if hold_replay and event.get("type") != "error":
                            continue
                        capture.absorb(event)
                        emit(event)

                    def _flush_replay() -> None:
                        """Emit the held replay events (errors already went out live).

                        On an UNDO the old question row is deleted and the restart
                        re-arms the step without re-narrating it, so when the replay
                        carried no message of its own, re-emit the question's stored
                        text just before the widget — otherwise the user sees a widget
                        with nothing above it. An edit keeps the anchor row, so it needs
                        no such help."""
                        if not hold_replay:
                            return
                        out = with_question_text(replay, "" if resubmit else anchor_text)
                        for event in out:
                            capture.absorb(event)
                            emit(event)

                    # The replay must re-arm an interrupt on EITHER mode — an undo
                    # that doesn't re-arm is just as dead a conversation as an edit
                    # that doesn't. It must also be the SAME step: an edit answers
                    # whatever is asked next, so submitting it to a different step
                    # would silently put the user's words in the wrong field.
                    rearmed = pending_interrupt_value(await self._snapshot(graph, config))
                    wrong_step = (
                        rearmed is not None
                        and expected_step is not None
                        and rearmed.get("step_key") != expected_step
                    )
                    if rearmed is None or wrong_step:
                        # The restore already happened and the messages are already
                        # gone, so failing here would leave the transcript ahead of
                        # the graph — the exact mismatch this feature exists to stop.
                        logger.warning(
                            "rewind re-armed a different step",
                            session=session_id, expected=expected_step,
                            armed=(rearmed or {}).get("step_key"), mode="restart" if restart else "fork",
                        )
                        # A held replay (edit, or undo on a restart) is emitted now; a
                        # live one already went out above.
                        _flush_replay()
                        if rearmed is None:
                            # Nothing is waiting on an answer, so the edit cannot be
                            # sent. Hand the text back — the client puts it in the
                            # composer — instead of dropping it.
                            emit({"type": "rewind_degraded", "content": {
                                "undone_text": undone_text,
                                "new_text": new_value,
                                "message": (
                                    "Went back to that point, but Punk has no question open "
                                    "there, so your change wasn't sent. It's in the message "
                                    "box — send it to continue."
                                ),
                            }})
                            return
                        # Something else is open (the planner chose a different next
                        # step from the restored state). Say so, and — on an edit —
                        # still send the text: the resume router classifies it against
                        # whatever is open, so the user's change is applied, not lost.
                        emit({"type": "rewind_notice", "content": {
                            "step_key": rearmed.get("step_key"),
                            "message": (
                                "Punk picked up from a slightly different point than "
                                "before, so your change is being applied to the step below."
                                if resubmit else
                                "Went back, but Punk is asking a different question here "
                                "than before — answer the step shown."
                            ),
                        }})

                    if not resubmit:
                        _flush_replay()
                        return

                    # Phase 2 — answer the freshly-armed interrupt. Identical to a
                    # normal /resume turn, because that is exactly what it is.
                    emit({"type": "update", "content": "Applying your change…"})
                    async with AsyncSessionLocal() as short_db:
                        await self.repository.create_chat_message(short_db, {
                            "conversation_id": conv_id,
                            "role": "user",
                            "content": new_value,
                            "question": payload_question,
                        })

                    await self._stream_resume_turn(
                        graph, config, new_value, capture, emit, rename_from_state
                    )
                except asyncio.CancelledError:
                    stopped = True
                    emit({"type": "cancelled"})
                    raise
                finally:
                    persist = runs.track_persist(self._commit_turn(
                        graph, config, conv_id, capture, payload_question,
                        usage_cb, grounding_cb, current_user, api_cb,
                        source="rewind",
                        stopped=stopped, start_checkpoint_ref=start_checkpoint_ref,
                    ), session_id)
                    with contextlib.suppress(asyncio.CancelledError):
                        await asyncio.shield(persist)

        return await self._start_and_stream(session_id, producer)

    async def create_new_chat(self,current_user: User,db: AsyncSession):  
        data={
            "user_id":current_user.id,
            "title":f"New Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "thread_id":str(uuid.uuid4())
        }
        return await self.repository.create_conversation(db,data)
         
    async def find_specific_user_conversation(self,current_user:User,db:AsyncSession, skip: int = 0, limit: int = 10):
        return await self.repository.find_specific_user_all_chat(db,current_user.id, skip, limit)

    async def get_conversation_history(self,current_user:User,thread_id:str,db:AsyncSession):
        conversastion = await self.repository.find_specific_user_chat(db,thread_id,current_user.id)
        if not conversastion:
            raise HTTPException(status_code=404, detail="Conversation not found")
        history_result = await self.repository.find_fetch_specific_history(db,conversastion.id)
        return conversastion,history_result
        
    #  for public access
    async def get_public_conversation_history(self, thread_id: str, db: AsyncSession):
        conversation = await self.repository.find_chat_by_thread_id(db, thread_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        history_result = await self.repository.find_fetch_specific_history(db, conversation.id)
        return conversation, history_result
    
    async def delete_conversation(self,current_user:User,thread_id:str,db:AsyncSession):
        conv = await self.repository.find_specific_user_chat(db,thread_id,current_user.id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        try:
            # A live turn holds a task that will keep writing to this thread. Cancel
            # first: runs.cancel drains the detached persists, so a write already in
            # flight lands before the rows go, instead of after them against nothing.
            await runs.cancel(thread_id)
            async with AsyncPostgresSaver.from_conn_string(settings.CHECKPOINT_DB_URL) as checkpointer:
                await checkpointer.adelete_thread(thread_id)
            await self.repository.delete_conversation(db,conv.id)
            return {"message":"Conversation deleted successfully"}
        except Exception as e:
            logger.error("Error deleting conversation------------>>",error=str(e),e=e)
            return {"message":"Conversation deleted unsuccessfully"}
        
    async def delete_multiple_conversations(self, current_user: User, thread_ids: list[str], db: AsyncSession):
        convs = await self.repository.find_specific_user_chats(db, thread_ids, current_user.id)
        if not convs:
            raise HTTPException(status_code=404, detail="Conversations not found")
        
        conv_ids = [c.id for c in convs]
        valid_thread_ids = [c.thread_id for c in convs]

        try:
            # In parallel — each cancel waits up to 15s for its run to settle, so a
            # serial loop over a multi-select would stall the request for minutes.
            await asyncio.gather(*(runs.cancel(tid) for tid in valid_thread_ids))
            async with AsyncPostgresSaver.from_conn_string(settings.CHECKPOINT_DB_URL) as checkpointer:
                for tid in valid_thread_ids:
                    await checkpointer.adelete_thread(tid)
            await self.repository.delete_multiple_conversations(db, conv_ids)
            return {"message": f"{len(conv_ids)} conversation(s) deleted successfully"}
        except Exception as e:
            logger.error("Error deleting conversations------------>>", error=str(e), e=e)
            return {"message": "Conversations deleted unsuccessfully"}
        
    async def update_thread(self,current_user:User,thread_id:str,db:AsyncSession,payload:UpdateThreadRequest):
        try:
            conv = await self.repository.find_specific_user_chat(db,thread_id,current_user.id)
            if not conv:
                raise HTTPException(status_code=404, detail="Conversation not found")
            if payload.title is not None:
                conv.title = payload.title
            if payload.starred == True:
                conv.starred = True
            elif payload.starred == False:
                conv.starred = False
            update_data = await self.repository.update_thread(db,conv)
            return  {
                "thread_id": update_data.thread_id,
                "title": update_data.title,
                "starred": update_data.starred,
            }
        except Exception as e:
            logger.error("Error updating conversation------------>>",error=str(e),e=e)
            return {"message":"Conversation updated unsuccessfully"}
    
    async def get_starred_threads(self,current_user:User,db:AsyncSession):
        return await self.repository.get_starred_threads(db,current_user.id)
    
    async def preview_audience(
        self, session_id: str, payload: AudiencePreviewRequest,
        current_user: User, db: AsyncSession,
    ) -> dict:
        """What each candidate audience layer would leave, from the rows already
        persisted for this session. Read-only and free — no vendor call, nothing
        written, the chat state untouched — so the layer builder can recount on
        every change.

        Ownership-gated like ``get_agent_state``. A purged extraction (the raw
        device rows are cleared once a campaign publishes) is a 409, not a
        confident "0 people".
        """
        conv = await self.repository.find_specific_user_chat(db, session_id, current_user.id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        from app.services import maid_store

        extraction = await maid_store.fetch_maid_extraction_by_session(session_id)
        if not extraction:
            raise HTTPException(status_code=404, detail="No audience extracted for this conversation yet")
        if extraction.get("purged_at"):
            raise HTTPException(status_code=409, detail="This audience was already published; its visitor data is cleared")

        from app.graph.resume_router import sanitize_panel_patch

        stored = extraction.get("audience_filter")
        base = maid_store.public_audience_filter(stored)
        if base.get("any_of"):
            # An either/or filter can't be overlaid: the fold replaces it with a
            # fresh flat filter, so any count here would describe a different
            # audience than the one on screen.
            raise HTTPException(
                status_code=409,
                detail="This audience combines several either/or conditions; change it in chat.",
            )

        # Patches are cleaned by the same function the commit uses, and overlaid
        # on the same base by the same function — so a layer's count is exactly
        # what Apply will produce, every key the panel doesn't edit included.
        layers = maid_store.preview_audience_layers(
            extraction["observations"] or [],
            extraction["pois"] or [],
            [
                {"label": layer.label, "patches": [sanitize_panel_patch(p) for p in layer.patches]}
                for layer in payload.layers
            ],
            base=base,
            history_days_bought=(stored or {}).get("_history_days_bought"),
        )
        return {
            "total_devices": extraction["maid_count"],
            "min_deliverable": maid_store.MIN_DELIVERABLE_AUDIENCE,
            # What is in force but not the panel's to edit — included in every
            # count above, so the panel must say so (and can remove any of it).
            "carried": maid_store.carried_filter_parts(base),
            "layers": layers,
        }

    async def get_agent_state(self,session_id:str,request:Request,current_user:User,db:AsyncSession):
        """Full AgentState dump (minus ``messages``) for a thread the caller owns.

        Ownership-gated so one user cannot read another's session by guessing a
        session_id. Values are passed through ``jsonable_encoder`` with a ``str()``
        fallback so nested LangChain objects in scratch fields cannot 500 the route,
        then through ``_redact_secrets`` — the state carries the caller's live Meta
        access token, which must never reach a browser even for its own owner.
        """
        graph = getattr(request.app.state, "graph", None)

        if graph is None:
            raise HTTPException(
            status_code=503,
            detail="Graph not initialized"
            )

    # Verify ownership
        conv = await self.repository.find_specific_user_chat(db,session_id,current_user.id)

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
                serializable[k] = _redact_secrets(jsonable_encoder(v))
            except Exception:
                serializable[k] = str(v)

        return {
            "success": True,
            "session_id": session_id,
            "state": serializable
        }
