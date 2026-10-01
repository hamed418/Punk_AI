"""A 0x00 byte in user text used to reach a Postgres text column and 500 the request."""
import pytest
from pydantic import ValidationError

from app.modules.chat.schemas import ChatRequest, ResumeRequest, RewindRequest, UpdateThreadRequest


def test_nul_stripped_everywhere():
    assert ChatRequest(message="he\x00llo", question="q\x00").message == "hello"
    assert ChatRequest(message="a", question="q\x00").question == "q"
    assert ResumeRequest(value="\x00yes").value == "yes"
    assert RewindRequest(value="n\x00o").value == "no"
    assert UpdateThreadRequest(title="t\x00").title == "t"


def test_control_char_and_replacement_char_untouched():
    assert ChatRequest(message="a\x01b�").message == "a\x01b�"


def test_nul_only_message_is_clean_422_not_500():
    with pytest.raises(ValidationError):
        ChatRequest(message="\x00\x00")
