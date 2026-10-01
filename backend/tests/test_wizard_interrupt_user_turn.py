"""wizard_interrupt must refresh state["user_turn"] for EACH reply, not just
the final one.

Before this fix, `user_turn` (phrase/embedded_ask/mood/engagement — what the
composer's "RESPOND TO THE USER FIRST" instruction is built from, see
composer.py) was written only once, by builder_ask, AFTER wizard_interrupt
returns. A mid-turn edit reply never returns immediately — the loop dispatches
the edit and re-interrupts on the SAME widget — so the flush at the top of the
NEXT iteration composed against the PREVIOUS reply's user_turn. This test
drives that exact two-reply loop and asserts the in-loop flush sees the fresh
reply each time.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from app.graph import wizard_helpers as wh

STEP = "geo_wizard_plan_review"


def _state():
    # A distinct message id, NOT "m1" — narrator/beats' process-local buffers
    # (_CHANGES, _HISTORY) are keyed by session (first HumanMessage id) and
    # module-level across the whole test process; sharing an id with another
    # test file's fixture leaks a `heard` ledger entry across files and
    # corrupts an UNRELATED test's cache-key invariant (test_wizard_ledger.py
    # uses "m1" too — this collided with it).
    return {
        "messages": [HumanMessage(content="hi", id="wizard-interrupt-user-turn-m1")],
        "campaign_builder_state": {"filled": {}},
    }


@pytest.fixture()
def _interrupt_env():
    with patch("app.graph.wizard_helpers.get_stream_writer", return_value=MagicMock()), \
         patch("app.graph.wizard_helpers.wizard_ask", new=AsyncMock(return_value=None)), \
         patch("app.graph.wizard_helpers.generate_chips", new=AsyncMock(return_value=[])), \
         patch("app.graph.wizard_helpers.narrate", new=AsyncMock(return_value=None)), \
         patch("app.graph.wizard_helpers.settings.RESUME_ROUTER_TOOLCALLING", False):
        yield


def test_user_turn_is_fresh_on_the_flush_that_precedes_each_reply(_interrupt_env):
    st = _state()
    seen_phrases: list = []

    async def _fake_flush(state, writer):
        # The flush a mid-turn edit's re-interrupt runs BEFORE showing the
        # same widget again — this is exactly what the composer's user_turn
        # block reads from.
        seen_phrases.append((state.get("user_turn") or {}).get("phrase"))
        return "", {}

    edit_intent = MagicMock(
        lane="edit", target_field="business_name", new_value="Laval Gym Co",
        is_append=False, confidence=0.95, question_text=None, answer_value=None,
        extra_edits=None,
    )
    confirm_intent = MagicMock(
        lane="confirm", target_field=None, is_append=False, confidence=0.9,
    )

    with patch("app.graph.wizard_helpers.interrupt",
               side_effect=["drop the Laval gyms", "yes"]), \
         patch("app.graph.wizard_helpers.classify_resume_intent",
               new=AsyncMock(side_effect=[edit_intent, confirm_intent])), \
         patch("app.graph.wizard_helpers.flush_narration", new=_fake_flush):
        asyncio.run(wh.wizard_interrupt(MagicMock(), STEP, "ctx", state=st))

    # iteration 0's flush precedes the FIRST interrupt, before any reply
    # exists yet — no phrase. iteration 1's flush is the one this bug hit:
    # it must already reflect the first reply, not still be empty/stale.
    assert seen_phrases[0] is None
    assert seen_phrases[1] == "drop the Laval gyms"
