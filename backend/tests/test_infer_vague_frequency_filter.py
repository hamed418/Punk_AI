"""
tests/test_infer_vague_frequency_filter.py
────────────────────────────────────────────
`nodes._infer_vague_frequency_filter` — the deterministic backstop for a
real-but-unquantified frequency claim ("frequent dog parks", "regulars").

The regression this guards: never-invent correctly refuses to guess a number
for "frequent"/"regulars" phrasing, but the result was NO filter at all —
an audience with real, stated frequency language and zero narrowing. Pure
function, no LLM.
"""
from __future__ import annotations

from app.graph.nodes import _infer_vague_frequency_filter


def test_frequent_sets_min_visits_two():
    result = _infer_vague_frequency_filter(
        "target people that frequent dog parks", {"audience_filter": {"groups": ["dog park"]}}
    )
    assert result == {"groups": ["dog park"], "min_visits": 2}


def test_regulars_sets_min_visits_two_with_no_prior_filter():
    result = _infer_vague_frequency_filter("target the regulars at my gym", {})
    assert result == {"min_visits": 2}


def test_keeps_coming_back_triggers():
    result = _infer_vague_frequency_filter("people who keep coming back to the mall", {})
    assert result == {"min_visits": 2}


def test_does_not_override_explicit_min_visits():
    extracted = {"audience_filter": {"min_visits": 5}}
    assert _infer_vague_frequency_filter("our regulars", extracted) is None


def test_does_not_override_cadence_days():
    extracted = {"audience_filter": {"cadence_days": 14}}
    assert _infer_vague_frequency_filter("regulars who come every payday", extracted) is None


def test_does_not_override_trend():
    extracted = {"audience_filter": {"trend": "lapsed"}}
    assert _infer_vague_frequency_filter("regulars who stopped coming", extracted) is None


def test_no_vague_phrase_does_nothing():
    assert _infer_vague_frequency_filter("people who visited once", {}) is None


def test_no_text_does_nothing():
    assert _infer_vague_frequency_filter(None, {}) is None


def test_a_while_does_not_trigger():
    # "a while"/"a long time" names no repeatable behavior — must NOT match.
    assert _infer_vague_frequency_filter("people who spent a while there", {}) is None
