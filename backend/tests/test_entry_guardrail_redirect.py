"""
tests/test_entry_guardrail_redirect.py
───────────────────────────────────────
Part B: a rule-level PS-OFFTOPIC REDIRECT (chat_stream, guardrails/rules.py)
is forwarded into the graph instead of a duplicate fixed sentence pre-graph.
entry_node's `guardrail_redirect_topic` bypass reuses its EXISTING off-topic
path (the guardrail_reject-tagged message chatbot_node already narrates with
full conversation context), mirroring the `awaiting_write_tool` bypass right
above it — no LLM call, same tag shape as the LLM-driven `decision.off_topic`
branch further down.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from app.graph import nodes


def _run_entry(state: dict):
    # tracked_ainvoke is patched to explode if called — the whole point of the
    # bypass is that entry's LLM calls never happen for this path.
    async def _must_not_be_called(*_a, **_kw):
        raise AssertionError("entry_node's LLM call ran; the bypass should have short-circuited first")

    with patch.object(nodes, "get_stream_writer", return_value=lambda _e: None), \
         patch.object(nodes, "tracked_ainvoke", side_effect=_must_not_be_called):
        return asyncio.run(nodes.entry_node(state))


def test_guardrail_redirect_topic_bypasses_the_llm_and_routes_to_chatbot() -> None:
    state = {
        "messages": [HumanMessage(content="write me a poem about spring")],
        "guardrail_redirect_topic": "something unrelated to Meta advertising",
    }

    out = _run_entry(state)

    assert out["next_nodes"] == ["chatbot"]
    assert out["pending_action"] is None
    assert len(out["messages"]) == 1
    tagged = out["messages"][0]
    assert isinstance(tagged, AIMessage)
    assert tagged.additional_kwargs.get("role") == "guardrail_reject"
    assert tagged.content == "something unrelated to Meta advertising"


def test_no_redirect_topic_does_not_bypass() -> None:
    # awaiting_write_tool is the sibling bypass right above the one under
    # test — reusing it here proves an absent/falsy guardrail_redirect_topic
    # falls through past THIS bypass to the next one, not that entry_node
    # fully executes (which would need the full LLM harness).
    state = {
        "messages": [HumanMessage(content="hello")],
        "guardrail_redirect_topic": None,
        "campaign_manager_state": {"awaiting_write_tool": True},
    }

    with patch.object(nodes, "get_stream_writer", return_value=lambda _e: None):
        out = asyncio.run(nodes.entry_node(state))

    assert out["next_nodes"] == ["campaign_manager"]
