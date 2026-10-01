"""Punk self-knowledge / grounding-scope regression tests.

Covers the fix for sessions where a question about Punk's own product
(e.g. "how do you know where people go?") got answered with grounded public
Meta Ads content instead of Punk's own facts. See:
  - app/graph/knowledge/punk_kb.md — Punk's own product facts
  - app/graph/tools.py: retrieve_marketing_knowledge — NONE scope rule
  - app/graph/nodes.py: _tagged_context_this_turn — stale-context scope fix
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.graph.knowledge import load_punk_kb
from app.graph.nodes import _tagged_context_this_turn
from app.graph.tools import retrieve_marketing_knowledge


def test_punk_kb_loads_and_names_real_visits_not_interests():
    """The exact fact that would have fixed session 48158c11 ("Meta builds an
    interest profile" — wrong for Punk) must actually be in the loaded KB."""
    kb = load_punk_kb()
    assert kb
    assert "interest" in kb.lower()
    assert "visit" in kb.lower()


@pytest.mark.asyncio
async def test_none_scope_answer_yields_empty_string():
    """When the grounded prompt decides a question is about Punk's own product
    (not public Meta facts), it returns NONE — the tool must surface that as ""
    so chatbot_node's Punk KB answers unopposed, never a real-looking but wrong
    grounded answer."""
    with patch(
        "app.graph.tools._gemini_grounded_text",
        new=AsyncMock(return_value=("NONE", [], 1.0)),
    ):
        result = await retrieve_marketing_knowledge.ainvoke(
            {"query": "how do you know where people go?", "context": "sunglasses | online"}
        )
    assert result == ""


@pytest.mark.asyncio
async def test_context_reaches_the_grounded_prompt():
    """The advertiser context (business/industry/market) must actually be
    interpolated into the prompt sent for grounding — without it retrieval is
    blind to who is asking, which is how a Montreal café question got answered
    with no locale awareness."""
    mock = AsyncMock(return_value=("some grounded answer", [], 1.0))
    with patch("app.graph.tools._gemini_grounded_text", new=mock):
        await retrieve_marketing_knowledge.ainvoke(
            {"query": "what's a good CPM?", "context": "sunglasses shop | targeting Miami"}
        )
    sent_prompt = mock.call_args.args[0]
    assert "sunglasses shop" in sent_prompt
    assert "targeting Miami" in sent_prompt


@pytest.mark.asyncio
async def test_poorly_supported_answer_is_dropped():
    """An answer the grounding metadata barely backs is model memory posing as a
    web answer — it must surface as "" rather than be injected as authoritative."""
    with patch(
        "app.graph.tools._gemini_grounded_text",
        new=AsyncMock(return_value=("confident but unsupported", ["u"], 0.05)),
    ):
        result = await retrieve_marketing_knowledge.ainvoke(
            {"query": "what's a good CPM?", "context": "x"}
        )
    assert result == ""


def test_tagged_context_scoped_to_current_turn():
    """A tagged context message (knowledge_context / guardrail_reject / ...)
    from a PRIOR turn must not leak into this turn — the exact bug that kept a
    stale 'OFF-TOPIC ALERT' telling the model to decline legitimate follow-ups."""
    state = {
        "messages": [
            AIMessage(content="stale knowledge blob", additional_kwargs={"role": "knowledge_context"}),
            HumanMessage(content="a real follow-up question"),
        ]
    }
    assert _tagged_context_this_turn(state, "knowledge_context") == ""


def test_tagged_context_found_within_current_turn():
    """The same tag, still ahead of the last HumanMessage, IS this turn's and
    must be returned — the fix must not blind the scan to the real case."""
    state = {
        "messages": [
            HumanMessage(content="how would you know where people go?"),
            AIMessage(content="fresh knowledge blob", additional_kwargs={"role": "knowledge_context"}),
        ]
    }
    assert _tagged_context_this_turn(state, "knowledge_context") == "fresh knowledge blob"
