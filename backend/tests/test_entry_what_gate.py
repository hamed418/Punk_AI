"""
tests/test_entry_what_gate.py
──────────────────────────────
The entry build gate's WHAT signal (`nodes._gate_signals`).

The regression this guards: `product_offer` ("50% off this week", "grand
opening Friday" — a promotional detail) used to count as WHAT alongside
`business_description` ("what the business sells"). That let a promo-only
message satisfy the gate with business_description still empty — the build
started, the dynamic place mapper ran with nothing to build POI context from
(it reads business_description only), and the real "what do you sell"
question only ever surfaced later, after the POI search had already run.
"""
from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import AIMessage

from app.graph.nodes import _GATE_FOLLOW_UPS, _gate_signals, _validate_extracted_field
from app.graph.usage import tracked_ainvoke


def test_product_offer_alone_does_not_satisfy_what():
    """The exact regression: a promo/launch mention with no business
    description must NOT open the gate."""
    where, who, what = _gate_signals({
        "location": ["Austin"],
        "target_audience": "gym-goers",
        "product_offer": "50% off this week",
    })
    assert where is True
    assert who is True
    assert what is False


def test_business_description_satisfies_what():
    where, who, what = _gate_signals({
        "location": ["Austin"],
        "target_audience": "gym-goers",
        "business_description": "a crossfit gym",
    })
    assert (where, who, what) == (True, True, True)


def test_business_description_and_product_offer_together_still_satisfies_what():
    """product_offer riding alongside a real description is fine — it's only
    a *substitute* for business_description that's the bug."""
    where, who, what = _gate_signals({
        "location": ["Austin"],
        "target_audience": "gym-goers",
        "business_description": "a crossfit gym",
        "product_offer": "50% off this week",
    })
    assert what is True


def test_nothing_present_fails_all_three():
    assert _gate_signals({}) == (False, False, False)


def test_store_anchored_angle_satisfies_where_without_a_named_market():
    """store_set / competitor_nearby anchor the search on the user's own
    store, collected later — see _store_anchored. WHAT is still required
    (no exemption)."""
    where, _who, what = _gate_signals({"deterministic_subtype": "store_set"})
    assert where is True
    assert what is False


# ── The wholesale-coffee-thread regression ──────────────────────────────────
# Thread 7b4f5bbc-2b7b-4047-b4b0-e18610976bf2: turn-1 extraction silently
# returned nothing (a structured-output parse failure tracked_ainvoke used to
# swallow), business_description was never recovered, and the code build gate
# — which is the ONLY thing that ever set missing_signals=['what'] — carried
# no follow_ups (the routing LLM emits [] for wizard routes), so the chatbot
# fell into the fallback CLARIFY branch, whose prose explicitly banned asking
# for WHAT. The session looped for 7 turns and never reached campaign_builder.


class _FakeStructuredLLM:
    """Stub matching the {"raw": AIMessage, "parsed": ...} shape tracked_ainvoke
    expects from with_structured_output(..., include_raw=True)."""

    def __init__(self, result: dict):
        self._result = result

    async def ainvoke(self, messages):
        return self._result


def test_tracked_ainvoke_raises_on_unparsed_structured_output():
    """A parse failure must surface as an exception, not a silent None —
    every include_raw=True call site already tolerates a raise (try/except or
    asyncio.gather(..., return_exceptions=True)); returning None let it merge
    zero fields with no log line (RC-1 of the regression)."""
    llm = _FakeStructuredLLM({
        "raw": AIMessage(content=""),
        "parsed": None,
        "parsing_error": "boom",
    })

    async def _run():
        return await tracked_ainvoke(llm, [], node_name="test_node")

    with pytest.raises(ValueError):
        asyncio.run(_run())


def test_gate_follow_ups_cover_every_signal_gate_signals_can_report():
    """_GATE_FOLLOW_UPS is keyed by exactly the signals _gate_signals can name
    missing — if the gate ever blocks on a signal with no entry here, the
    turn falls back to the unguided CLARIFY branch again (the deadlock)."""
    assert set(_GATE_FOLLOW_UPS) == {"where", "who", "what"}
    for spec in _GATE_FOLLOW_UPS.values():
        assert spec.get("ask")


def test_list_field_entries_are_stripped_and_blanks_dropped():
    """Thread 73a89409: user_info.poi_types ended up as ["caf\\n\\n"] — a
    truncated/garbled structured-output entry that passed the old bare
    isinstance(value, list) check straight into state. Whitespace/newlines
    must be stripped and blank-after-strip entries dropped."""
    assert _validate_extracted_field("poi_types", ["caf\n\n", "  ", "bar"]) == ["caf", "bar"]


def test_list_field_all_blank_returns_none():
    assert _validate_extracted_field("poi_types", ["  ", "\n"]) is None


def test_fallback_clarify_prose_no_longer_bans_the_what_question():
    """Pins the nodes.py fix: the fallback CLARIFY branch must not tell the
    LLM to withhold the one question that unblocks the WHAT gate."""
    import inspect

    from app.graph import nodes

    src = inspect.getsource(nodes.chatbot_node)
    assert "Do NOT ask what the business sells" not in src


# ── Thread a90cc17c: a "resume" with no paused build must still hit the gates ──
# Turn 2 ("yes") was routed `campaign_builder` with nothing to resume. The old
# guard ran AFTER the onboarding / build gates and fell straight to chatbot when a
# signal was missing — no recovery extraction, no follow_ups — so the chatbot got
# an empty brief and invented a budget question.


def _run_entry(*, recovered: dict):
    from unittest.mock import MagicMock, patch

    from langchain_core.messages import HumanMessage

    from app.graph import nodes

    async def fake_tracked(_llm, _messages, *, node_name, writer=None):
        if node_name == "entry_routing":
            return nodes.EntryRouting(route="campaign_builder", reasoning="yes = resume", off_topic=False, detected_topic=""), {}
        if node_name == "entry_extraction":
            return nodes.ExtractedUserInfo(), {}
        return nodes.ExtractedUserInfo(**recovered), {}

    state = {
        "messages": [
            HumanMessage(content="I sell custom dog gear online. Target vet clinic visitors in Denver."),
            AIMessage(content="Ready to roll?"),
            HumanMessage(content="yes"),
        ],
        "user_info": {
            "location": ["Denver"],
            "target_audience": "dog owners",
            "poi_types": ["vet clinic"],
            "product_offer": "custom dog gear",
            "wizard_steps_done": ["onboarding_started"],
        },
    }
    with patch.object(nodes, "get_stream_writer", return_value=lambda _e: None), \
         patch.object(nodes, "_make_llm", return_value=MagicMock()), \
         patch.object(nodes, "tracked_ainvoke", side_effect=fake_tracked):
        return asyncio.run(nodes.entry_node(state))


def test_resume_without_paused_build_goes_to_geo_once_what_is_recovered():
    out = _run_entry(recovered={"business_description": "custom dog gear online"})
    assert out["next_nodes"] == ["geo_agent"]  # graph.py aliases geo_agent -> campaign_builder


def test_resume_without_paused_build_asks_what_not_budget_when_what_is_missing():
    out = _run_entry(recovered={})
    assert out["next_nodes"] == ["chatbot"]
    assert out["missing_signals"] == ["what"]
    assert [f["ask"] for f in out["follow_ups"]] == [_GATE_FOLLOW_UPS["what"]["ask"]]
