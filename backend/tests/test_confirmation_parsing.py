"""
tests/test_confirmation_parsing.py
───────────────────────────────────
Regression coverage for a tester report tracing three separately-reported
symptoms to one root cause: exact whole-string matching at every yes/no gate.
"Yes." (trailing punctuation), "yes please" / "yes, do it" (a tail), and
"approved" (a synonym never listed) all failed the old membership test — and
every caller then treated "didn't match" as a REJECTION, not as "ambiguous,
ask again". That produced three symptoms from one cause:

  1. a builder gate (poi_confirm / maid_confirm) silently re-asking forever
     instead of advancing on an approved answer;
  2. the campaign-manager money gate reporting "cancelled by user" for a
     write the user never rejected;
  3. a JSON-shaped answer bypassing confirmation entirely (`if edits:` never
     checked the payload was actually the map widget's delta shape), letting
     `{"poi_radius_m": -99999, "lookback_days": 100000}` close a gate outright.

Also covers the companion bug: an "also add X" append silently replacing an
existing list because `edit_base` was empty at the merge site — the same
"reported as applied, actually lost" failure shape as the JSON bypass.
"""
from __future__ import annotations

import pytest

from app.graph.builder.builder_node import _apply_confirm_semantics
from app.graph.campaign_manager_node import _write_resume_decision
from app.graph.resume_router import ResumeIntent
from app.graph.wizard_helpers import (
    _dispatch_edit_intent,
    _resolve_edit_base,
    confirmation_intent,
)


# ── confirmation_intent ─────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Yes.", "yes"),
    ("yes, do it", "yes"),
    ("Go ahead.", "yes"),
    ("Approved", "yes"),
    ("yes please", "yes"),
    ("YEP!", "yes"),
    ("", "yes"),  # by design — the two form-flow callers need this.
    ("no", "no"),
    ("nope", "no"),
    ("cancel that", "no"),
    ("no, cancel that", "no"),
    ("no.", "no"),
    ("no!", "no"),
    ("no,", "no"),
    ("Nope, stop", "no"),
    ("nothing", "unclear"),
    ("what's my budget?", "unclear"),
    ("yes but make it $500", "unclear"),
])
def test_confirmation_intent_table(raw, expected):
    assert confirmation_intent(raw) == expected


# ── builder gates: poi_confirm / maid_confirm ───────────────────────────────

_BAD_PAYLOAD = '{"poi_radius_m": -99999, "lookback_days": 100000}'


@pytest.mark.asyncio
async def test_poi_confirm_accepts_trailing_punctuation():
    bs = {"filled": {"poi_confirm": "Yes."}}
    note = await _apply_confirm_semantics(bs, {})
    assert note is None
    assert bs["filled"]["poi_confirm"] == "Yes."  # gate satisfied, not popped


@pytest.mark.asyncio
async def test_poi_confirm_rejects_non_delta_json_payload():
    """The JSON-means-confirm bypass: a JSON object that merely PARSES, but
    isn't the map widget's {confirm/added/removed} delta shape, must not be
    trusted as a confirmation."""
    bs = {"filled": {"poi_confirm": _BAD_PAYLOAD}}
    note = await _apply_confirm_semantics(bs, {})
    assert note == "POIs not confirmed — asking again"
    assert "poi_confirm" not in bs["filled"]


@pytest.mark.asyncio
async def test_maid_confirm_accepts_a_tail():
    bs = {"filled": {"maid_confirm": "yes, do it"}}
    note = await _apply_confirm_semantics(bs, {})
    assert note is None
    assert bs["filled"]["maid_confirm"] == "yes, do it"


@pytest.mark.asyncio
async def test_maid_confirm_rejects_non_delta_json_payload():
    bs = {"filled": {"maid_confirm": _BAD_PAYLOAD}}
    note = await _apply_confirm_semantics(bs, {})
    assert note == "audience not confirmed — asking again"
    assert "maid_confirm" not in bs["filled"]


@pytest.mark.asyncio
async def test_poi_confirm_unrelated_reply_reasks_not_cancels():
    bs = {"filled": {"poi_confirm": "what's a POI anyway?"}}
    note = await _apply_confirm_semantics(bs, {})
    assert note == "POIs not confirmed — asking again"
    assert "cancel" not in note.lower()


# ── money gate: campaign_manager write resume ───────────────────────────────

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402


def test_write_resume_decision_yes_with_punctuation():
    messages = [AIMessage(content="Apply this change?"), HumanMessage(content="Yes.")]
    assert _write_resume_decision(messages) == "yes"


def test_write_resume_decision_no():
    messages = [AIMessage(content="Apply this change?"), HumanMessage(content="no")]
    assert _write_resume_decision(messages) == "no"


def test_write_resume_decision_unclear_on_unrelated_reply():
    messages = [AIMessage(content="Apply this change?"),
                HumanMessage(content="what's my current budget?")]
    assert _write_resume_decision(messages) == "unclear"


def test_write_resume_decision_unclear_when_no_human_turn_found():
    """The fail-closed guard: no real conversational turn (or an empty one)
    must never read as "yes" — but it also must not be blamed on the user as
    a rejection any more. Both land on "unclear"."""
    assert _write_resume_decision([]) == "unclear"
    assert _write_resume_decision([AIMessage(content="Apply this change?")]) == "unclear"
    assert _write_resume_decision([HumanMessage(content="")]) == "unclear"


# ── edit_base default (append-as-replace root cause) ────────────────────────

def test_resolve_edit_base_fills_from_user_info():
    state = {"user_info": {"poi_types": ["cafe", "bakery", "bar"]}}
    bs = {"filled": {"poi_types": "cafe, bakery, bar", "det_type": "category"}}
    base = _resolve_edit_base(state, bs, None)
    assert base["poi_types"] == ["cafe", "bakery", "bar"]


def test_resolve_edit_base_caller_key_wins_but_other_fields_still_fill():
    """The partial-base hole: geo.py's two confirm sites only ever supplied
    their OWN field. A caller-supplied base for one field must not starve
    every other appendable field of a base to merge against."""
    state = {"user_info": {"poi_types": ["cafe", "bakery", "bar"]}}
    bs = {"filled": {"poi_types": "cafe, bakery, bar", "det_type": "category"}}
    base = _resolve_edit_base(state, bs, {"location": ["Somewhere Else"]})
    assert base["location"] == ["Somewhere Else"]       # caller value wins
    assert base["poi_types"] == ["cafe", "bakery", "bar"]  # gap still filled


@pytest.mark.asyncio
async def test_append_to_poi_types_keeps_all_existing_items():
    """The tester's reported bug, end to end: "also add X" to a 3-item list
    must produce 4 items, not 1. Reproduces the failure by resolving
    edit_base the way `wizard_interrupt` now does by default (an interrupt
    site that supplies NOTHING of its own, e.g. the OAuth ask)."""
    state = {
        "user_info": {"poi_types": ["cafe", "bakery", "bar"]},
        "campaign_builder_state": {"ops_done": ["geo_discover"]},
    }
    bs = {"filled": {"poi_types": "cafe, bakery, bar", "det_type": "category"}}
    edits: dict = {}
    base = _resolve_edit_base(state, bs, None)

    await _dispatch_edit_intent(
        intent=ResumeIntent(
            lane="edit", target_field="poi_types",
            new_value="vintage clothing store", is_append=True, confidence=0.95,
        ),
        state=state, writer=lambda _e: None, pending={"prefill": None},
        cfg={"field": "maid_poi_radius"}, edits=edits,
        edit_base=base,
    )
    assert edits["poi_types"] == ["cafe", "bakery", "bar", "vintage clothing store"]
