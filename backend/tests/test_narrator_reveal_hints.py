"""Reveal guidance is conditional: a reveal only carries the clauses its facts
trigger, and the composer message is ordered background -> task."""
from __future__ import annotations

import pytest

from app.graph.narrator import beats
from app.graph.narrator.composer import _build_messages
from app.graph.narrator.grounding import build_pack
from app.graph.narrator.prompts import composer as cp


def _block(signals):
    return cp.beat_hint_block(["reveal"], signals)


def test_a_bare_reveal_carries_no_conditional_clause():
    block = _block({"poi_count": 12})
    assert "ALREADY landed" in block
    for _name, _keys, text in cp._REVEAL_CLAUSES:
        assert text not in block


@pytest.mark.parametrize("name,keys,text", cp._REVEAL_CLAUSES, ids=[c[0] for c in cp._REVEAL_CLAUSES])
def test_each_clause_renders_only_when_its_key_is_truthy(name, keys, text):
    assert text in _block({keys[0]: True})
    assert text not in _block({keys[0]: False})
    assert text not in _block({})


def test_no_signals_renders_every_clause():
    block = _block(None)
    assert all(text in block for _n, _k, text in cp._REVEAL_CLAUSES)


def test_zero_count_does_not_claim_a_detection_mechanism():
    # audience_count 0 means nobody was detected — the "devices were detected
    # on-site" clause must not fire.
    assert cp._REVEAL_CLAUSES[1][2] not in _block({"audience_count": 0})


def test_edit_hint_defers_to_the_change_ledger():
    hint = cp.BEAT_HINTS["edit"]
    assert "WHAT ACTUALLY CHANGED" in hint and "never as done" in hint


def _messages(kinds_facts, **state_extra):
    state = {"messages": [], **state_extra}
    beat_list = [beats.Beat(kind=k, facts=f) for k, f in kinds_facts]
    return _build_messages(beat_list, build_pack(state), [], 800)


def test_background_comes_before_the_task():
    _system, human = _messages([("reveal", {"poi_count": 12}), ("framing", {"stage": "x"})])
    text = human.content
    assert text.index("REFERENCE context") < text.index("Beats this turn") < text.index("Length:")


def test_length_is_given_in_words_and_characters():
    _system, human = _messages([("framing", {"stage": "x"})])
    assert "about 133 words, never more than 800 characters" in human.content


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["wizard_milestone_narrate", "wizard_handoff_narrate"])
async def test_no_caller_fallback_never_becomes_machine_text(monkeypatch, name):
    from langchain_core.messages import HumanMessage

    from app.core.config import settings
    from app.graph import wizard_helpers as wh

    fn = getattr(wh, name)
    state = {"messages": [HumanMessage(content="hi", id="m9")]}
    events: list = []
    await fn(events.append, state, "geo_pois_found", {"poi_count": 12})
    # The beat carries NO fallback, so a failed compose says the plain retry line
    # instead of "geo_pois_found: poi_count=12".
    assert [b.fallback for b in beats.peek(state)] == [None]
    beats.clear(state)
    monkeypatch.setattr(settings, "WIZARD_NARRATOR_ENABLED", False)
    await fn(events.append, state, "geo_pois_found", {"poi_count": 12})
    assert events == [] and beats.peek(state) == []


def test_product_facts_only_ride_along_with_an_answer_beat():
    with_answer, _ = _messages([("answer", {"question": "does Punk use interests?"})])
    without, _ = _messages([("framing", {"stage": "x"})])
    assert "PUNK PRODUCT FACTS" in with_answer.content
    assert "PUNK PRODUCT FACTS" not in without.content
