"""Tests for the builder transcript ledger.

The builder collects every answer through ``interrupt()`` and speaks over the
stream, so before the ledger a whole build left NOTHING in ``state["messages"]``
and every downstream LLM saw a conversation frozen at the pre-build turn.

Covers:
- record_qa / drain_ledger: roles, contents, step_key, per-session isolation
- wizard_interrupt records exactly one Q/A pair per RESOLVED interrupt
- _with_ledger commits on return and DROPS on interrupt (no replay duplicates)
- reader policy: who sees ledger records and who must not
- _turn_index (and therefore the compose cache key) is invariant under ledger
  records — the regression this suite exists to prevent
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphInterrupt

from app.graph import wizard_helpers as wh
from app.graph.narrator import composer as _composer
from app.graph.prompts_registry import STEP_PROMPTS
from app.graph.state import is_conversational, is_internal

STEP = "geo_wizard_plan_review"
STEP_PROMPT = STEP_PROMPTS[STEP]["prompt"]


def _state(messages=None, **extra):
    """Minimal state; the human id keys the process-local ledger bucket."""
    base = {"messages": messages if messages is not None else [HumanMessage(content="hi", id="m1")]}
    base.update(extra)
    return base


def _ledger_pair(step=STEP, question="Q?", answer="A"):
    return [
        AIMessage(content=question, additional_kwargs={"role": "wizard_step", "step_key": step}),
        HumanMessage(content=answer, additional_kwargs={"role": "wizard_answer", "step_key": step}),
    ]


@pytest.fixture(autouse=True)
def _clear_ledger():
    wh._LEDGER.clear()
    yield
    wh._LEDGER.clear()


@pytest.fixture()
def _interrupt_env():
    """Silence the writer and the pre-interrupt emission machinery.

    Also pins RESUME_ROUTER_TOOLCALLING False: these tests mock
    classify_resume_intent (the lane-JSON backend) directly, and a local
    .env can flip the ambient setting to the tool-calling backend, which
    then runs unmocked, errors, and re-prompts for an interrupt() call the
    test never queued a value for — a failure with nothing to do with what
    the test is actually exercising.
    """
    with patch("app.graph.wizard_helpers.get_stream_writer", return_value=MagicMock()), \
         patch("app.graph.wizard_helpers.wizard_ask", new=AsyncMock(return_value=None)), \
         patch("app.graph.wizard_helpers.generate_chips", new=AsyncMock(return_value=[])), \
         patch("app.graph.wizard_helpers.flush_narration", new=AsyncMock(return_value=("", {}))), \
         patch("app.graph.wizard_helpers.narrate", new=AsyncMock(return_value=None)), \
         patch("app.graph.wizard_helpers.settings.RESUME_ROUTER_TOOLCALLING", False):
        yield


# ── buffer primitives ─────────────────────────────────────────────────────────

def test_record_qa_shape_and_drain_empties():
    st = _state()
    wh.record_qa(st, STEP, "Which locations?", "Brooklyn")

    records = wh.drain_ledger(st)
    assert [type(m) for m in records] == [AIMessage, HumanMessage]
    assert records[0].content == "Which locations?"
    assert records[0].additional_kwargs == {"role": "wizard_step", "step_key": STEP}
    assert records[1].content == "Brooklyn"
    assert records[1].additional_kwargs == {"role": "wizard_answer", "step_key": STEP}

    assert wh.drain_ledger(st) == []


def test_ledger_buckets_are_per_session():
    a = _state([HumanMessage(content="hi", id="a1")])
    b = _state([HumanMessage(content="hi", id="b1")])
    wh.record_qa(a, STEP, "Q", "answer-a")
    wh.record_qa(b, STEP, "Q", "answer-b")

    assert [m.content for m in wh.drain_ledger(a)] == ["Q", "answer-a"]
    assert [m.content for m in wh.drain_ledger(b)] == ["Q", "answer-b"]


def test_record_qa_skips_empty_answer():
    st = _state()
    wh.record_qa(st, STEP, "Q", "")
    assert [type(m) for m in wh.drain_ledger(st)] == [AIMessage]


# ── JSON widget payloads never reach the transcript verbatim ──────────────────
# plan_confirm answers with the whole edited campaign tree and poi_confirm with
# add/remove deltas. Recorded raw they become truncated machine JSON sitting in
# every later prompt as if the user had typed it.

def test_plan_confirm_payload_records_the_action_not_the_spec():
    payload = json.dumps({
        "action": "publish",
        "spec": {
            "campaign": {"name": "Bay Metro Hall"},
            "adsets": [{"name": "A", "creatives": [{"image_url": "https://cdn/secret.jpg"}]}],
        },
    })
    out = wh._ledger_answer(payload, payload)
    assert out == "(submitted the form — publish)"
    assert "secret.jpg" not in out and "{" not in out


def test_poi_confirm_delta_records_confirmed_or_declined():
    confirmed = json.dumps({"confirm": True, "added": [{"name": "Regal"}], "removed": []})
    declined = json.dumps({"confirm": False, "added": [], "removed": []})
    assert wh._ledger_answer(confirmed, confirmed) == "(confirmed)"
    assert wh._ledger_answer(declined, declined) == "(declined)"


def test_list_payload_records_the_selection():
    payload = json.dumps(["Manhattan", "Brooklyn"])
    assert wh._ledger_answer(payload, payload) == "Manhattan, Brooklyn"


def test_unparseable_payload_falls_back_to_a_marker():
    broken = '{"action": "publish", "spec": {truncated'
    assert wh._ledger_answer(broken, broken) == "(submitted the form)"


def test_plain_answers_are_recorded_verbatim():
    assert wh._ledger_answer("Brooklyn", "Brooklyn") == "Brooklyn"
    assert wh._ledger_answer("yes", "yes") == "yes"


def test_resolved_value_wins_over_the_raw_reply():
    """Confirming a suggested 50 must record "50", not "yes" — later turns need
    the number, and the recall path depends on it."""
    assert wh._ledger_answer("yes", "50") == "50"


def test_no_json_reaches_the_buffer_for_a_form_step():
    st = _state()
    payload = json.dumps({"action": "publish", "spec": {"adsets": [{"x": 1}]}})
    wh.record_qa(st, "plan_confirm", "Review your campaign", wh._ledger_answer(payload, payload))
    records = wh.drain_ledger(st)
    assert all("{" not in str(m.content) for m in records)
    assert records[1].content == "(submitted the form — publish)"


# ── wizard_interrupt: one pair per RESOLVED interrupt ─────────────────────────

def test_interrupt_records_question_and_answer(_interrupt_env):
    st = _state()
    with patch("app.graph.wizard_helpers.interrupt", return_value="yes"), \
         patch("app.graph.wizard_helpers.classify_resume_intent",
               new=AsyncMock(return_value=MagicMock(lane="confirm", target_field=None,
                                                    is_append=False, confidence=0.9))):
        result = asyncio.run(wh.wizard_interrupt(MagicMock(), STEP, "ctx", state=st))

    assert str(result) == "yes"
    records = wh.drain_ledger(st)
    # The AI side is the step's DETERMINISTIC prompt, not the composed narration —
    # the narration is unrecoverable on replay, this recomputes identically.
    assert records[0].content == STEP_PROMPT
    assert records[1].content == "yes"


def test_offpath_reask_still_records_one_pair(_interrupt_env):
    """A reject then a confirm is ONE resolved interrupt, so one pair.

    Both replies must be non-sentinel — a bare "no" IS a widget answer
    (``is_sentinel_resume``) and short-circuits before the classifier.
    """
    st = _state()
    lanes = [
        MagicMock(lane="reject", target_field=None, is_append=False, confidence=0.9),
        MagicMock(lane="confirm", target_field=None, is_append=False, confidence=0.9),
    ]
    with patch("app.graph.wizard_helpers.interrupt", side_effect=["hmm not sure", "Brooklyn"]), \
         patch("app.graph.wizard_helpers.classify_resume_intent",
               new=AsyncMock(side_effect=lanes)):
        asyncio.run(wh.wizard_interrupt(MagicMock(), STEP, "ctx", state=st))

    records = wh.drain_ledger(st)
    assert len(records) == 2
    assert records[1].content == "Brooklyn"


def test_sentinel_answer_records_the_reply(_interrupt_env):
    """A bare widget yes/no resolves via the sentinel lane and is still recorded."""
    st = _state()
    with patch("app.graph.wizard_helpers.interrupt", return_value="no"):
        result = asyncio.run(wh.wizard_interrupt(MagicMock(), STEP, "ctx", state=st))

    assert str(result) == "no"
    records = wh.drain_ledger(st)
    assert [m.content for m in records] == [STEP_PROMPT, "no"]


def test_widget_payload_records_resolved_value(_interrupt_env):
    """A sentinel/JSON payload is machine chatter — record what it resolved to."""
    st = _state()
    with patch("app.graph.wizard_helpers.interrupt", return_value='{"confirm":true}'), \
         patch("app.graph.wizard_helpers.is_sentinel_resume", return_value=True), \
         patch("app.graph.wizard_helpers._is_confirmation", return_value=True):
        result = asyncio.run(
            wh.wizard_interrupt(MagicMock(), STEP, "ctx", state=st, prefill="50")
        )

    assert str(result) == "50"
    records = wh.drain_ledger(st)
    assert records[1].content == "50"
    assert "{" not in records[1].content


def test_auto_advance_records_nothing(_interrupt_env):
    """No interrupt fired → no question was shown and no user turn happened."""
    st = _state()
    with patch("app.graph.wizard_helpers.interrupt") as it:
        asyncio.run(wh.wizard_interrupt(
            MagicMock(), STEP, "ctx", state=st,
            prefill="Brooklyn", prefill_confidence=0.99,
        ))
        it.assert_not_called()

    assert wh.drain_ledger(st) == []


# ── _with_ledger: commit on return, drop on interrupt ─────────────────────────

def test_with_ledger_commits_after_existing_messages():
    from app.graph.builder.builder_node import _with_ledger

    existing = AIMessage(content="already here")

    @_with_ledger
    async def node(state):
        wh.record_qa(state, STEP, "Q", "A")
        return {"campaign_builder_state": {}, "messages": [existing]}

    st = _state()
    update = asyncio.run(node(st))

    assert [m.content for m in update["messages"]] == ["already here", "Q", "A"]
    assert update["campaign_builder_state"] == {}
    assert wh.drain_ledger(st) == []


def test_with_ledger_noop_without_records():
    from app.graph.builder.builder_node import _with_ledger

    @_with_ledger
    async def node(state):
        return {"campaign_builder_state": {}}

    update = asyncio.run(node(_state()))
    assert "messages" not in update


def test_with_ledger_drops_records_on_interrupt():
    """The node's writes are discarded on interrupt and the replay re-derives the
    records. A buffer that survived would double them."""
    from app.graph.builder.builder_node import _with_ledger

    @_with_ledger
    async def node(state):
        wh.record_qa(state, STEP, "Q", "A")
        raise GraphInterrupt(())

    st = _state()
    with pytest.raises(GraphInterrupt):
        asyncio.run(node(st))

    assert wh.drain_ledger(st) == []


# ── the cache-key invariant ───────────────────────────────────────────────────

def test_turn_index_ignores_ledger_records():
    real_only = _state([HumanMessage(content="hi", id="m1")])
    with_ledger = _state([HumanMessage(content="hi", id="m1"), *_ledger_pair(), *_ledger_pair()])

    assert _composer._turn_index(real_only) == 1
    assert _composer._turn_index(with_ledger) == 1


def test_compose_cache_key_invariant_under_ledger():
    """Built without stubbing cache.lookup, so the KEY itself is exercised.

    If _turn_index counted ledger records the key would move on every build step
    and a replayed screen would regenerate at full price instead of replaying free.
    """
    from app.graph.narrator import cache
    from app.graph.narrator.grounding import build_pack

    def _key(st):
        return "compose:" + cache.stable_fingerprint({
            "beats": [{"k": "reveal", "f": {"poi_count": 12}}],
            "g": build_pack(st).as_prompt_dict(),
            "t": _composer._turn_index(st),
        })

    before = _state([HumanMessage(content="hi", id="m1")])
    after = _state([HumanMessage(content="hi", id="m1"), *_ledger_pair()])
    assert _key(before) == _key(after)


# ── reader policy ─────────────────────────────────────────────────────────────

def test_recent_transcript_includes_ledger_excludes_internal():
    st = _state([
        HumanMessage(content="build me a campaign", id="m1"),
        AIMessage(content="INTERNAL BLOB", additional_kwargs={"role": "knowledge_context"}),
        *_ledger_pair(question="Which locations?", answer="Brooklyn"),
    ])
    lines = _composer._recent_transcript(st)

    assert any("Brooklyn" in line for line in lines)
    assert any("Which locations?" in line for line in lines)
    assert not any("INTERNAL BLOB" in line for line in lines)


def test_last_turn_extractors_skip_ledger():
    from app.graph.nodes import _extract_last_ai_text, _extract_last_human_text

    st = _state([
        HumanMessage(content="real question"),
        AIMessage(content="real answer"),
        *_ledger_pair(question="Which locations?", answer="Brooklyn"),
    ])

    assert _extract_last_human_text(st) == "real question"
    assert _extract_last_ai_text(st) == "real answer"


def test_entry_window_filters_before_slicing():
    """Ledger records must not evict the real conversation from the 6-msg window."""
    msgs = [HumanMessage(content="real ask", id="m1"), AIMessage(content="real reply")]
    for i in range(6):
        msgs.extend(_ledger_pair(question=f"Q{i}", answer=f"A{i}"))

    window = [m for m in msgs if is_conversational(m)][-6:]
    contents = [m.content for m in window]
    assert "real ask" in contents and "real reply" in contents


def test_role_predicates():
    assert is_conversational(HumanMessage(content="hi"))
    assert not is_conversational(_ledger_pair()[0])
    assert not is_conversational(_ledger_pair()[1])
    assert not is_internal(_ledger_pair()[0])  # ledger records are NOT internal —
    assert is_internal(                        # chatbot/campaign_manager must see them
        AIMessage(content="x", additional_kwargs={"role": "campaign_manager_context"})
    )
