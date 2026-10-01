"""The extraction message surface (app/graph/nodes.py::_build_extraction_messages).

Both extraction callers — entry_node's `_extract()` and the resume path's
`extract_user_info_from_text` — build their messages here, so the framing this
pins applies to both.

The bug these guard: the previous assistant turn used to be appended as a bare
``AIMessage``, which the model read as if the user had said it. On a "yes, go
ahead" turn the assistant's own paraphrase ("those specific stores") came back
as ``poi_types=["beauty store"]`` and overwrote a correctly extracted
``competitor_brand`` angle with a category the user never typed.
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.graph.nodes import _build_extraction_messages


def test_previous_assistant_turn_is_never_an_ai_message():
    """As an AIMessage it reads as conversation to extract from; as a framed
    SystemMessage it reads as reference material for resolving pronouns."""
    msgs = _build_extraction_messages(
        "Yes, go ahead and build it.",
        {"location": ["NYC"]},
        "I can pinpoint people who have been to those specific stores.",
    )

    assert not any(isinstance(m, AIMessage) for m in msgs), (
        "the assistant's paraphrase must not be presented as a conversational turn"
    )
    carrier = [m for m in msgs if isinstance(m, SystemMessage)
               and "those specific stores" in m.content]
    assert len(carrier) == 1
    text = carrier[0].content
    assert "never take a field value from it" in text
    assert "NOT user input" in text


def test_user_message_stays_last_and_is_the_only_human_turn():
    """Whatever else is prepended, the thing being extracted FROM is the user's
    own message, and it is the final turn."""
    msgs = _build_extraction_messages("Target Ulta in Denver.", {}, "Some earlier reply.")

    humans = [m for m in msgs if isinstance(m, HumanMessage)]
    assert len(humans) == 1
    assert humans[0].content == "Target Ulta in Denver."
    assert msgs[-1] is humans[0]


def test_long_assistant_turn_is_still_clamped():
    """The 500-char clamp predates this change and must survive it — the whole
    assistant turn would otherwise crowd out the user's message."""
    msgs = _build_extraction_messages("ok", {}, "x" * 900)

    carrier = next(m for m in msgs if isinstance(m, SystemMessage) and "xxx" in m.content)
    assert "x" * 500 + "..." in carrier.content
    assert "x" * 501 not in carrier.content


def test_no_assistant_turn_leaves_the_shape_untouched():
    """First turn of a conversation: system prompt + the user, nothing else."""
    msgs = _build_extraction_messages("I run a gym in Dhaka.", {}, None)

    assert [type(m) for m in msgs] == [SystemMessage, HumanMessage]


def test_known_fields_ride_separately_from_the_assistant_turn():
    """Known context and assistant reference text are different things and must
    not be merged into one blob — only the latter carries the do-not-extract rule."""
    msgs = _build_extraction_messages("yes", {"business_name": "Punk Gym"}, "Earlier reply.")

    systems = [m.content for m in msgs if isinstance(m, SystemMessage)]
    known = [s for s in systems if s.startswith("Known user context")]
    assert len(known) == 1
    assert "Earlier reply." not in known[0]
