"""Stop must not leave the transcript claiming an answer the agent never saw.

``resume_chat`` writes the user's answer to the DB *before* starting the run, but
``Command(resume=...)`` only lands when the superstep commits. So after a stop the
row always exists, and whether it counted depends on when the button was pressed.
Left alone the UI shows an answered question sitting next to the same widget being
asked again.

``cancel_run`` settles it from the checkpoint: if the graph is still on the very
step the tail user message was answering, that answer was never consumed and the
whole aborted turn is dropped.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.modules.chat.repository import ChatRepository
from app.modules.chat.service import ChatService

SERVICE = ChatService(ChatRepository())


def _msg(role, step_key=None, content="x", auto_id=1):
    return SimpleNamespace(
        role=role,
        content=content,
        auto_id=auto_id,
        langchain_data=({"pending_action": {"step_key": step_key}} if step_key else None),
    )


# ── which question was the tail answering ────────────────────────────────────

def test_reads_step_key_from_the_latest_assistant_message():
    tail = [  # newest first, as get_last_messages returns
        _msg("user", content="500 Queen St W"),
        _msg("assistant", step_key="geo_collect_stores"),
        _msg("user", content="a coffee shop"),
    ]
    assert SERVICE._answered_step_key(tail) == "geo_collect_stores"


def test_no_step_key_when_the_assistant_turn_carried_no_widget():
    tail = [_msg("user"), _msg("assistant")]
    assert SERVICE._answered_step_key(tail) is None


def test_skips_user_rows_to_reach_the_assistant_one():
    tail = [_msg("user"), _msg("user"), _msg("assistant", step_key="maid_confirm_results")]
    assert SERVICE._answered_step_key(tail) == "maid_confirm_results"


def test_empty_tail_is_not_a_crash():
    assert SERVICE._answered_step_key([]) is None


# ── the rollback decision ────────────────────────────────────────────────────
#
# Mirrors the comparison cancel_run makes, so the branch is pinned independently
# of the DB and HTTP plumbing around it.

def _should_roll_back(tail, current_step) -> bool:
    if not current_step:
        return False
    if not tail or tail[0].role != "user":
        return False
    return SERVICE._answered_step_key(tail) == current_step


def test_rolls_back_when_the_graph_never_moved():
    tail = [_msg("user"), _msg("assistant", step_key="geo_collect_stores")]
    assert _should_roll_back(tail, "geo_collect_stores") is True


def test_keeps_the_answer_when_the_graph_advanced():
    """The stop landed after the superstep committed — the answer counted."""
    tail = [_msg("user"), _msg("assistant", step_key="geo_collect_stores")]
    assert _should_roll_back(tail, "geo_store_confirmation") is False


def test_no_rollback_when_the_tail_is_not_a_user_message():
    """A completed turn ends on an assistant message; nothing is orphaned."""
    tail = [_msg("assistant", step_key="geo_collect_stores"), _msg("user")]
    assert _should_roll_back(tail, "geo_collect_stores") is False


def test_no_rollback_when_the_graph_is_not_paused():
    """No pending interrupt means there is no step to compare against."""
    tail = [_msg("user"), _msg("assistant", step_key="geo_collect_stores")]
    assert _should_roll_back(tail, None) is False


# ── publish kill-switch ──────────────────────────────────────────────────────

def test_publish_locks_rewinding():
    published = SimpleNamespace(values={"meta_campaign_ids": {"campaign_id": "1203"}})
    assert SERVICE._publish_locked(published) is True
    assert SERVICE._publish_locked(SimpleNamespace(values={})) is False
    assert SERVICE._publish_locked(None) is False

# ── rewind eligibility ───────────────────────────────────────────────────────

def _stamp(checkpoint_id, checkpoint_ns):
    return SimpleNamespace(checkpoint_id=checkpoint_id, checkpoint_ns=checkpoint_ns)


def test_empty_namespace_is_rewindable():
    """"" is a real namespace — a pause in the parent graph, not a missing stamp.

    Testing truthiness here instead of `is not None` would silently refuse every
    non-subgraph rewind.
    """
    assert SERVICE._is_rewindable(_stamp("ck", "")) is True


def test_subgraph_namespace_is_rewindable():
    assert SERVICE._is_rewindable(_stamp("ck", "campaign_builder:abc")) is True


def test_missing_namespace_is_refused():
    """Pre-namespace row: its checkpoint_id is the ambiguous parent stamp."""
    assert SERVICE._is_rewindable(_stamp("ck", None)) is False


def test_missing_checkpoint_is_refused():
    assert SERVICE._is_rewindable(_stamp(None, "")) is False
    assert SERVICE._is_rewindable(None) is False
