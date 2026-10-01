"""Every tool bound to Gemini must convert to a Gemini function schema.

`bind_tools` does not convert eagerly — the conversion happens at invoke time,
and the resume-router tests patch `tracked_ainvoke`, i.e. they run *past* it. A
typeless parameter (`value: Any`) therefore shipped green and crashed every
mid-turn reply in a live build. This test converts the real tool sets with no
network, LLM or DB.
"""
import pytest
from langchain_google_genai._function_utils import convert_to_genai_function_declarations

from app.graph.builder.interject_tools import HANDOFF_ALL_TOOLS
from app.graph.resume_router import _structural_tools

_TOOL_SETS = {"structural": _structural_tools(), "handoff": HANDOFF_ALL_TOOLS}


def _declaration_count(tools) -> int:
    return sum(len(t.function_declarations) for t in convert_to_genai_function_declarations(list(tools)))


@pytest.mark.parametrize("set_name", _TOOL_SETS)
def test_each_tool_converts_alone(set_name):
    # Per-tool so a failure names the offender instead of the whole batch.
    for t in _TOOL_SETS[set_name]:
        assert _declaration_count([t]) == 1, f"{set_name}.{t.name} did not convert"


@pytest.mark.parametrize("set_name", _TOOL_SETS)
def test_whole_set_converts_together(set_name):
    # bind_tools sends the set as one payload: one bad schema breaks every tool.
    tools = _TOOL_SETS[set_name]
    assert _declaration_count(tools) == len(tools)


def test_filter_audience_doc_teaches_value_formats():
    # Live Gemini answered "only weekends" with day NAMES because the tool doc
    # listed key names but not formats; the evaluator wants ints Mon=0..Sun=6.
    from app.graph.resume_router import filter_audience

    doc = filter_audience.description
    assert "Mon=0..Sun=6" in doc and "[5,6]" in doc
    # the shared block, not a copy: counting + role guards and `invert` come with it
    assert "COUNTING" in doc and "ROLE TARGETING" in doc and "invert" in doc
    assert "__" not in "".join(w for w in doc.split() if w.startswith("__"))  # no unspliced token
