"""
Runs each sampled input through the REAL pipeline node functions
(entry_node, chatbot_node, campaign_manager_node, builder_plan), inside an
eval-namespaced thread_id, with every write-capable path mocked.

Design notes / deliberate scope limits (flagged, not hidden):

1. Nodes are called directly as plain async functions rather than through a
   compiled LangGraph + AsyncPostgresSaver/MemorySaver + interrupt/Command
   resume loop. `_build_graph()` + `MemorySaver` would avoid any Postgres
   writes just as well, but `builder_ask` and parts of `campaign_manager`
   use LangGraph's `interrupt()`, which needs a real multi-turn
   Command(resume=...) driver to progress past the first pause. Building
   that safely (without ever letting a resume turn read as "yes, spend
   budget") is a separate, larger project. Direct node calls sidestep
   interrupts entirely and are sufficient for what Steps 2/3/5 actually
   need: the map/routing decision, the response text, the confirmation
   gate's *proposal* (never its execution), and the planner's next-action
   decision.
2. Each node still runs inside a real (but minimal) single-node LangGraph
   graph — `_single_node_graph()` below — compiled with an in-memory
   `MemorySaver`, because `get_stream_writer()` (used by entry_node/
   chatbot_node/campaign_manager_node) raises `RuntimeError` outside an
   actual graph run; it is not a safe no-op. Running through `.ainvoke()`
   this way means LangGraph applies the state's real reducers
   (`_dict_merge_or_clear`, `operator.add`, `add_messages`, etc. from
   app/graph/state.py) exactly as production does — this is NOT a
   simplified merge. Each stage gets its own single-node graph/thread_id
   under the shared eval checkpoint_ns; `MemorySaver` guarantees nothing
   persists past the process anyway.
3. campaign_manager_node's real tool acquisition
   (`app.services.meta_mcp.campaign_manager_tool_context`) fetches live Meta
   credentials and (per the earlier audit) has a call-signature bug
   (3 positional args against a 2-positional-arg signature) that would raise
   TypeError if hit for real. Both problems are moot here: it is
   monkeypatched to a mock async context manager for the whole eval run
   (see _mock_tool_context) that never touches real credentials and never
   executes a write tool — it only records what *would* have been called.
4. builder_plan's real "act" operations (geo_discover, maid_query, publish,
   ...) live in app/graph/builder/executors/ and are NOT invoked here —
   only the planner LLM call inside builder_plan is (it returns a
   PlannerAction decision: kind/slot/operation/reason). That decision is
   captured as the stage-4 "map"/meta-config output without ever running
   the operation it names.
"""
from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph.nodes import chatbot_node, entry_node
from app.graph.state import AgentState

from tests.eval.config import EVAL_THREAD_PREFIX

# get_stream_writer() (used by entry_node/chatbot_node/campaign_manager_node)
# raises RuntimeError unless called inside an actual LangGraph run — it is
# NOT a safe no-op outside one. So each node is wrapped in its own minimal
# single-node graph (no interrupts, no Postgres) compiled with an in-memory
# MemorySaver, purely to give it a valid runnable context. This is a
# different graph object per node, not the production graph — it never
# touches AsyncPostgresSaver, so it can never write to the checkpoints/
# checkpoint_writes/checkpoint_blobs tables.
_NODE_GRAPH_CACHE: dict[str, object] = {}


def _single_node_graph(name: str, node_fn):
    if name in _NODE_GRAPH_CACHE:
        return _NODE_GRAPH_CACHE[name]
    builder = StateGraph(AgentState)
    builder.add_node(name, node_fn)
    builder.add_edge(START, name)
    builder.add_edge(name, END)
    compiled = builder.compile(checkpointer=MemorySaver())
    _NODE_GRAPH_CACHE[name] = compiled
    return compiled


async def _invoke_node(name: str, node_fn, state: dict, checkpoint_ns: str) -> dict:
    graph = _single_node_graph(name, node_fn)
    config = {"configurable": {"thread_id": f"{checkpoint_ns}:{name}", "checkpoint_ns": checkpoint_ns}}
    result_state = await graph.ainvoke(state, config)
    # ainvoke returns the full merged state; diff against input to get the
    # "patch" this node contributed, matching what direct node calls returned.
    return {k: v for k, v in result_state.items() if state.get(k) is not v}


@dataclass
class MockWriteLog:
    calls: list[dict] = field(default_factory=list)

    def record(self, tool_name: str, tool_args: dict, description: str) -> None:
        self.calls.append({"tool_name": tool_name, "tool_args": tool_args, "description": description})


@dataclass
class StageCapture:
    example_id: str
    checkpoint_ns: str
    route: str | None = None
    map_output: dict | None = None          # entry_node's extraction/routing fields
    response_text: str | None = None        # chatbot_node's answer
    confirmation: dict | None = None        # campaign_manager proposal (never executed)
    builder_action: dict | None = None      # builder_plan's PlannerAction decision
    mocked_write_attempts: list[dict] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


def _initial_state(user_text: str) -> AgentState:
    return {
        "messages": [HumanMessage(content=user_text)],
        "user_id": "eval-synthetic-user",
        "user_info": {},
        "next_nodes": ["entry"],
        "pending_action": None,
        "thinking": [],
        "current_turn_tool_errors": None,
        "geo_data": None,
        "campaign_manager_state": {},
        "campaign_builder_state": None,
        "token_cost_usd": 0.0,
        "total_tokens": 0,
        "tool_calls_log": [],
        "wizard_milestone_cache": {},
        "narrator_history": [],
        "wizards_completed": set(),
    }


@contextlib.contextmanager
def _mock_campaign_manager_tools(write_log: MockWriteLog):
    """Patches campaign_manager_node's tool acquisition so no real Meta
    credentials are fetched and no write tool can ever execute — read tools
    return canned data, write tools are intercepted and logged only.
    """
    import app.graph.campaign_manager_node as cm_node_mod
    from app.services.meta_mcp import CampaignManagerToolSet

    async def _fake_read(**kwargs) -> dict:
        return {"mocked": True, "note": "eval run — no live Meta data fetched", "kwargs": kwargs}

    WRITE_TOOL_NAMES = frozenset({"apply_budget_change", "apply_status_change", "apply_bid_adjustment"})

    class _MockTool:
        def __init__(self, name: str, is_write: bool):
            self.name = name
            self._is_write = is_write

        async def ainvoke(self, args: dict) -> Any:
            if self._is_write:
                write_log.record(self.name, args, description=f"mocked write tool '{self.name}'")
                return {"mocked": True, "executed": False, "would_have_called": self.name, "args": args}
            return await _fake_read(**args)

    mock_tools = [
        _MockTool("list_user_campaigns", False),
        _MockTool("fetch_campaign_analytics", False),
        _MockTool("fetch_adset_breakdown", False),
        _MockTool("get_campaign_settings", False),
        _MockTool("apply_budget_change", True),
        _MockTool("apply_status_change", True),
        _MockTool("apply_bid_adjustment", True),
    ]
    mock_registry = {t.name: t for t in mock_tools}
    mock_toolset = CampaignManagerToolSet(
        tools=mock_tools, registry=mock_registry, write_tools=WRITE_TOOL_NAMES, uses_mcp=False,
    )

    @contextlib.asynccontextmanager
    async def _mock_ctx(*args, **kwargs):
        yield mock_toolset

    original = cm_node_mod.campaign_manager_tool_context
    cm_node_mod.campaign_manager_tool_context = _mock_ctx
    # Also patch credential resolution so no real OAuth token is read from the DB.
    original_resolve = getattr(cm_node_mod, "_resolve_credentials", None)

    async def _fake_resolve_credentials(state):
        return "mock-access-token", "act_mock_ad_account"

    if original_resolve is not None:
        cm_node_mod._resolve_credentials = _fake_resolve_credentials
    try:
        yield
    finally:
        cm_node_mod.campaign_manager_tool_context = original
        if original_resolve is not None:
            cm_node_mod._resolve_credentials = original_resolve


async def run_one(example: dict) -> StageCapture:
    example_id = example["id"]
    checkpoint_ns = f"{EVAL_THREAD_PREFIX}:{example.get('checkpoint_ns_prefix', 'root')}:{uuid.uuid4()}"
    capture = StageCapture(example_id=example_id, checkpoint_ns=checkpoint_ns)
    write_log = MockWriteLog()

    state = _initial_state(example["content"])

    # Stage 1 — intent/map extraction + routing.
    try:
        state = await _invoke_node("entry", entry_node, state, checkpoint_ns)
        capture.map_output = {
            "next_nodes": state.get("next_nodes"),
            "user_info": state.get("user_info"),
            "clarify_reason": state.get("clarify_reason"),
            "missing_signals": state.get("missing_signals"),
            "follow_ups": state.get("follow_ups"),
            "onboarding_active": state.get("onboarding_active"),
            "flow_blocked": state.get("flow_blocked"),
        }
        capture.route = (state.get("next_nodes") or ["chatbot"])[0]
    except Exception as exc:  # noqa: BLE001 — eval must not crash on one bad example
        capture.errors["entry_node"] = f"{type(exc).__name__}: {exc}"
        capture.route = "chatbot"

    route = capture.route

    # Stage 3/4 — confirmation or meta-config planning, depending on route.
    # geo_agent is the legacy alias for campaign_builder (see graph.py _entry_route).
    if route in ("campaign_manager",):
        try:
            with _mock_campaign_manager_tools(write_log):
                import app.graph.campaign_manager_node as cm_node_mod
                state = await _invoke_node("campaign_manager", cm_node_mod.campaign_manager_node, state, checkpoint_ns)
            capture.confirmation = {
                "awaiting_write_tool": (state.get("campaign_manager_state") or {}).get("awaiting_write_tool"),
                "last_ai_message": _last_ai_text(state.get("messages")),
            }
        except Exception as exc:  # noqa: BLE001
            capture.errors["campaign_manager_node"] = f"{type(exc).__name__}: {exc}"

    elif route in ("campaign_builder", "geo_agent"):
        try:
            from app.graph.builder.builder_node import builder_plan
            before_keys = set(state.keys())
            state = await _invoke_node("campaign_builder", builder_plan, state, checkpoint_ns)
            cb_state = state.get("campaign_builder_state") or {}
            capture.builder_action = {
                "next_action": cb_state.get("next_action") or cb_state.get("pending_action"),
                "iteration": cb_state.get("iteration"),
                "new_state_keys": sorted(set(state.keys()) - before_keys),
            }
            op = (capture.builder_action.get("next_action") or {}).get("operation") if isinstance(
                capture.builder_action.get("next_action"), dict
            ) else None
            if op:
                write_log.record(op, {}, description=f"builder planner selected operation '{op}' — NOT executed")
        except Exception as exc:  # noqa: BLE001
            capture.errors["builder_plan"] = f"{type(exc).__name__}: {exc}"

    # Stage 2 — response generation (single exit point for all user-visible text).
    try:
        state = await _invoke_node("chatbot", chatbot_node, state, checkpoint_ns)
        capture.response_text = _last_ai_text(state.get("messages"))
    except Exception as exc:  # noqa: BLE001
        capture.errors["chatbot_node"] = f"{type(exc).__name__}: {exc}"

    capture.mocked_write_attempts = write_log.calls
    return capture


def _last_ai_text(messages: list | None) -> str | None:
    if not messages:
        return None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str):
            return msg.content
    return None
