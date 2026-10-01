"""
Regression test for the campaign-manager write-resume approval gate
(`campaign_manager_node._write_resume_decision`).

`confirmation_intent("")` is `"yes"` by design in wizard_helpers.py's form-flow
callers (empty reply = accept the prefill). That is NOT safe at this gate: if
no real conversational `HumanMessage` is found — or one is found with empty
content — the scan must not read as approval. Both land on `"unclear"`,
never `"yes"`, so a pending live budget/status/bid write can never execute
with no user turn behind it, and an ambiguous reply is never blamed on the
user as a cancellation either (see test_confirmation_parsing.py for the
full three-symptom writeup this gate is one third of).
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.graph.campaign_manager_node import _write_resume_decision


def test_no_conversational_message_at_all_is_unclear():
    """The bug: an empty scan result must NOT read as approval — but it must
    also not be reported as the user cancelling. Both land on "unclear"."""
    assert _write_resume_decision([]) == "unclear"
    assert _write_resume_decision([AIMessage(content="Apply this change?")]) == "unclear"
    assert _write_resume_decision([ToolMessage(content="x", tool_call_id="1")]) == "unclear"


def test_real_yes_confirms():
    messages = [AIMessage(content="Apply this change?"), HumanMessage(content="yes")]
    assert _write_resume_decision(messages) == "yes"


def test_real_no_rejects():
    messages = [AIMessage(content="Apply this change?"), HumanMessage(content="no")]
    assert _write_resume_decision(messages) == "no"


def test_a_clear_yes_with_trailing_words_still_confirms():
    """"yes please" IS a clear yes — the old exact-membership gate read it as
    a rejection, which is the same root-cause bug as the builder gates
    (see test_confirmation_parsing.py)."""
    messages = [AIMessage(content="Apply this change?"), HumanMessage(content="yes please")]
    assert _write_resume_decision(messages) == "yes"


def test_a_qualified_yes_is_unclear_not_a_silent_yes_or_no():
    """"yes but change the budget" must not fire the write as a clean yes —
    the qualifier means the reply isn't settled yet. Re-ask, don't guess."""
    messages = [AIMessage(content="Apply this change?"),
                HumanMessage(content="yes but change the budget")]
    assert _write_resume_decision(messages) == "unclear"


def test_empty_human_reply_is_unclear():
    """An actual HumanMessage with empty content is the same hazard as
    finding none — still must not confirm a money write."""
    messages = [AIMessage(content="Apply this change?"), HumanMessage(content="")]
    assert _write_resume_decision(messages) == "unclear"


def test_only_a_non_conversational_human_message_is_unclear():
    """A structured/non-conversational-shaped reply (a resume payload that
    doesn't read as yes or no either way) must not stand in for a real
    answer."""
    messages = [HumanMessage(content='{"confirm": true}')]
    assert _write_resume_decision(messages) == "unclear"


def test_scans_backward_to_the_nearest_real_human_turn():
    messages = [
        HumanMessage(content="no"),
        AIMessage(content="Apply this change?"),
        HumanMessage(content="yes"),
    ]
    assert _write_resume_decision(messages) == "yes"


def test_system_message_never_confirms():
    assert _write_resume_decision([SystemMessage(content="yes")]) == "unclear"
