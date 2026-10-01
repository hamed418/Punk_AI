"""
graph/graph.py
──────────────
Entry point for the PunkAI LangGraph campaign-builder agent.

Defines the StateGraph, wires all nodes and edges, attaches AsyncPostgresSaver
for persistent checkpointing, and exposes get_graph() for FastAPI lifespan.

Graph topology:
    START ──► entry   (one Pro call: topic filter + extraction + routing)
    entry            ──► campaign_builder | knowledge_based | campaign_manager
                     ──► chatbot | END
    campaign_builder  ──► END (fresh publish — narrator already spoke) | chatbot
    knowledge_based   ──► chatbot
    campaign_managvbc   cvbc er  ──► chatbot
    chatbot           ──► END

campaign_builder is the single planner-driven build+publish path (geo → maid →
campaign brief → Meta JSON → creatives → publish). The legacy four-wizard chain
(geo/maid/campaign/media) was removed; its shared cores live in
``app/graph/builder/executors/``.

campaign_manager (on demand):
    ReAct agent — analytics, optimization suggestions, apply changes to live campaigns.
    Reached only through ``entry``, on a turn where the user actually asks about
    performance or wants a change — never as an automatic post-publish handoff.

chatbot_node is the single exit point for all user-visible responses.

Streaming usage (FastAPI route handler):
    async for chunk in graph.astream(input, config, stream_mode=["values", "custom"]):
        mode, data = chunk
        if mode == "custom":
            # {"type": "thinking", "content": "..."} — relay to frontend
        elif mode == "values":
            # AgentState snapshot — relay new messages / marketing_plan

Interrupt resume:
    from langgraph.types import Command
    async for chunk in graph.astream(Command(resume=value), config, stream_mode=["values", "custom"]):
        ...
"""

from __future__ import annotations

import logging
from typing import Optional

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import settings
from app.graph.builder.builder_node import build_campaign_builder
from app.graph.campaign_manager_node import campaign_manager_node
from app.graph.nodes import (
    chatbot_node,
    entry_node,
    knowledge_based_node,
)
from app.graph.state import AgentState

logger = logging.getLogger(__name__)

# Module-level sentinel — replaced by get_graph() during FastAPI lifespan.
# Allows `from app.graph.graph import graph` before startup.
graph: Optional[CompiledStateGraph] = None

# Long-lived psycopg3 pool backing the Postgres checkpointer. Opened in
# get_graph(); closed by close_checkpointer() during lifespan teardown.
_checkpointer_pool: Optional[AsyncConnectionPool] = None


# ── Routing functions ──────────────────────────────────────────────────────────

def _entry_route(state: AgentState) -> str:
    """
    Routing function for the entry conditional edge.

    Reads ``state["next_nodes"]`` (set by ``entry_node``) and returns the
    destination node name. Only single-destination routing is supported:
    multi-destination parallel ``Send`` dispatch and the matching
    ``data_aggregator`` fan-in node were removed because no node ever
    produced a multi-destination route — the unwired aggregator left
    parallel writes racing without a merge point.

    If parallel dispatch is ever needed again, restore the ``list[Send]``
    branch here AND wire ``data_aggregator`` as a fan-in node with the
    appropriate reducers on every state field that parallel branches
    might write.

    ``"end"`` is translated to the ``END`` sentinel.
    """
    # Alias: the entry LLM may emit the legacy "geo_agent" node name; it always
    # resolves to the planner-driven campaign_builder (the sole build path).
    _ALIASES = {"geo_agent": "campaign_builder"}

    destinations: list[str] = state.get("next_nodes") or ["chatbot"]
    dest = _ALIASES.get(destinations[0], destinations[0])
    return END if dest == "end" else dest


def _route_after_publish_pipeline(state: AgentState) -> str:
    """A fresh publish ends the turn; every other builder exit goes to chatbot.

    ``builder_finalize`` has already flushed the narrator's publish confirmation to
    the wire, so there is nothing left to say. Running chatbot (or campaign_manager)
    here only produced a second, contradictory message: the builder never writes to
    ``state["messages"]``, so both nodes saw a transcript still ending at the
    pre-build user turn and dutifully re-answered it.

    ``just_published`` is the freshness signal and is required — ``meta_campaign_ids``
    alone survives from an earlier campaign and would end later builder turns early.
    """
    if (
        state.get("just_published")
        and (state.get("meta_campaign_ids") or {}).get("campaign_id")
    ):
        return END
    return "chatbot"


# ── Path maps ──────────────────────────────────────────────────────────────────
# LangGraph 1.x validates all keys in path_map at compile time — every string
# that _entry_route() can return must appear here, or the graph will raise
# ValueError.

_ENTRY_PATH_MAP: dict[str, str] = {
    "geo_agent": "campaign_builder",
    "knowledge_based": "knowledge_based",
    "campaign_manager": "campaign_manager",
    "campaign_builder": "campaign_builder",
    "chatbot": "chatbot",
    END: END,
}


# ── Graph builder ──────────────────────────────────────────────────────────────

def _build_graph() -> StateGraph:
    """
    Construct and return an uncompiled StateGraph.

    Compilation (which attaches the checkpointer) is deferred to get_graph()
    so that the async Postgres saver is only instantiated inside a running
    event loop.
    """
    builder = StateGraph(AgentState)

    # ── Nodes ──────────────────────────────────────────────────────────────────
    # entry_node is the single per-turn gateway: topic filter + extraction +
    # routing in one Pro temp-0 structured call (replaces the old guardrail →
    # intent_extraction → supervisor pipeline of three serial LLM calls).
    builder.add_node("entry", entry_node)
    builder.add_node("knowledge_based", knowledge_based_node)
    builder.add_node("campaign_manager", campaign_manager_node)
    # Planner-driven campaign builder — the sole build+publish path. Each builder
    # sub-node is its own checkpoint boundary so interrupt replays stay flat.
    builder.add_node("campaign_builder", build_campaign_builder())
    builder.add_node("chatbot", chatbot_node)

    # ── Entry point ────────────────────────────────────────────────────────────
    builder.add_edge(START, "entry")

    # ── Entry: single-destination routing via next_nodes[0] ────────────────────
    # Multi-destination Send dispatch was removed — see _entry_route docstring
    # for the restore-conditions if it is ever needed again.
    builder.add_conditional_edges("entry", _entry_route, _ENTRY_PATH_MAP)

    # Off-flow paths route through chatbot directly.
    builder.add_edge("knowledge_based", "chatbot")
    builder.add_edge("campaign_manager", "chatbot")
    builder.add_conditional_edges(
        "campaign_builder",
        _route_after_publish_pipeline,
        {"chatbot": "chatbot", END: END},
    )

    builder.add_edge("chatbot", END)

    return builder


# ── Async factory ──────────────────────────────────────────────────────────────

async def get_graph() -> CompiledStateGraph:
    """
    Build, compile, and return the PunkAI campaign agent graph.

    Opens a psycopg3 connection pool, creates an AsyncPostgresSaver, calls
    setup() to initialise the checkpoint tables (idempotent), then compiles the
    StateGraph with the checkpointer attached.

    Must be called inside a running asyncio event loop (e.g. FastAPI lifespan),
    so the async pool and saver bind to the running loop.

    FastAPI lifespan example:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            from app.graph.graph import get_graph, close_checkpointer
            app.state.graph = await get_graph()
            yield
            await close_checkpointer()   # closes the psycopg pool

    Returns:
        A compiled CompiledStateGraph with Postgres checkpointing and interrupt support.

    Streaming (in route handlers — see app/api/chat.py for the production
    pattern with ``subgraphs=True``):
        config = {"configurable": {"thread_id": str(session_id)}}

        # First turn — only per-turn fields. AgentState reducers
        # (``_dict_merge_or_clear`` on user_info / geo_data, ``add_messages``
        # on messages, accumulators on total_tokens, etc.) preserve every
        # other key across turns, so do NOT re-init geo_data / user_info /
        # wizard scratch here.
        async for ns, mode, data in app.state.graph.astream(
            {
                "messages": [HumanMessage(content=user_text)],
                "user_id": str(current_user.id),
                "next_nodes": ["entry"],
                "pending_action": None,
                "thinking": [],
                "current_turn_tool_errors": None,
            },
            config,
            stream_mode=["values", "custom"],
            subgraphs=True,
        ):
            # ns is the subgraph namespace tuple (empty for parent graph)
            # mode == "custom"  -> thinking event  {"type": "thinking", "content": "..."}
            # mode == "values"  -> AgentState snapshot

        # Resume after interrupt:
        from langgraph.types import Command
        async for ns, mode, data in app.state.graph.astream(
            Command(resume=user_button_value),
            config,
            stream_mode=["values", "custom"],
            subgraphs=True,
        ):
            ...
    """
    global graph, _checkpointer_pool

    # Long-lived psycopg3 pool. autocommit + prepare_threshold=0 are required by
    # the async saver (and keep it compatible with transaction poolers such as
    # PgBouncer); dict_row is the row factory langgraph expects.
    _checkpointer_pool = AsyncConnectionPool(
        conninfo=settings.CHECKPOINT_DB_URL,
        max_size=20,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await _checkpointer_pool.open()

    checkpointer = AsyncPostgresSaver(_checkpointer_pool)
    await checkpointer.setup()   # idempotent: creates checkpoint tables + migration table
    logger.info("AsyncPostgresSaver initialised at %s:%s", settings.POSTGRES_HOST, settings.POSTGRES_PORT)

    builder = _build_graph()
    graph = builder.compile(checkpointer=checkpointer)

    logger.info("PunkAI LangGraph compiled successfully")
    return graph


async def close_checkpointer() -> None:
    """Close the checkpointer's psycopg pool. Call during lifespan teardown."""
    global _checkpointer_pool
    if _checkpointer_pool is not None:
        await _checkpointer_pool.close()
        _checkpointer_pool = None
        logger.info("Checkpointer connection pool closed")
