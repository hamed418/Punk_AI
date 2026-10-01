
import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Optional,List ,Any
from pydantic import BaseModel, BeforeValidator, Field
from app.services.maid_store import MAX_PREVIEW_LAYERS

# Postgres text/varchar (and JSONB in the checkpointer) reject 0x00 outright, which
# surfaced as a bare 500 with no reply. Strip it before length checks run, so a
# NUL-only message fails as a clean 422 instead.
def _strip_nul(v):
    return v.replace("\x00", "") if isinstance(v, str) else v

NoNulStr = Annotated[str, BeforeValidator(_strip_nul)]

# Cap on a resume / rewind answer. Far above ChatRequest's 20000 because a widget
# answer can carry a whole campaign spec as JSON (campaign editor publish), but
# bounded so a single request cannot push an unbounded string into the graph.
MAX_ANSWER_CHARS = 200_000

class MessageRequest(BaseModel):
    thread_id: str = Field(..., description="LangGraph thread ID. Create a new UUID for new conversations.")
    message: NoNulStr = Field(..., min_length=1, max_length=8000)

class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    question:Optional[str] = None
    thinking: Optional[str] = None
    langchain_data: Optional[Any] = None
    # Address of the checkpoint this turn ended on. The client uses the stamp on
    # the assistant message BEFORE a user message to decide whether that answer can
    # be rewound. checkpoint_ns null = pre-namespace row, not rewindable; "" is a
    # real value (parent-graph pause), so the client must test for null, not
    # falsiness.
    checkpoint_id: Optional[str] = None
    checkpoint_ns: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}

class ThreadResponse(BaseModel):
    id: uuid.UUID
    thread_id: str
    title: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime
    starred: bool = False

    model_config = {"from_attributes": True}

class ThreadHistoryResponse(ThreadResponse):
    messages: List[ChatMessageResponse] = Field(default_factory=list)

class ThreadListResponse(BaseModel):
    threads: List[ThreadResponse]
    total: int

class ChatRequest(BaseModel):
    message: NoNulStr = Field(..., min_length=1, max_length=20000)
    question: Optional[NoNulStr] = None
    session_id: Optional[str] = None  # omit to start a new session

class RewindRequest(BaseModel):
    # Which user message to rewind to. Omit for the most recent one.
    message_id: Optional[uuid.UUID] = None
    # Omit to re-ask the question and leave it open (undo). Provide to answer it
    # again straight away (edit, or retry with the same text).
    value: Optional[NoNulStr] = Field(None, max_length=MAX_ANSWER_CHARS)
    # The widget question text `value` answers, same as ResumeRequest.question —
    # stamped onto the new rows so an edit's history entry carries it like a
    # normal resume does. Optional: older clients that don't send it just get
    # `question=None`, same as before this field existed.
    question: Optional[NoNulStr] = None


class ResumeRequest(BaseModel):
    value: NoNulStr = Field(..., max_length=MAX_ANSWER_CHARS)  # the user's answer to the pending interrupt
    question: Optional[NoNulStr] = None


class CancelOutcome(str, Enum):
    """What pressing Stop actually did.

    The client used to infer this from a (stopped, rolled_back) pair, which could
    not express the publish case at all. Naming the outcome keeps the banner copy
    and the transcript repair in one place.
    """

    NOT_RUNNING = "not_running"
    """Nothing was in flight. The button was a no-op."""

    UNSENT = "unsent"
    """The graph never consumed the answer, so it was withdrawn. ``restored_value``
    carries it back for the composer (or a one-click resend, for a widget answer)."""

    KEPT = "kept"
    """The answer counted. The partial reply was persisted before the stop returned."""

    PUBLISH_INTERRUPTED = "publish_interrupted"
    """The stop landed inside the Meta publish pipeline. Objects were created and
    are PAUSED — nothing is spending — but they exist, and the next publish resumes
    from the ledger rather than starting clean."""


class CancelResponse(BaseModel):
    outcome: CancelOutcome
    restored_value: Optional[str] = None  # set only for UNSENT

class AudienceLayer(BaseModel):
    """One row of the layer builder: the ordered filter patches that reproduce
    it (the same list the chat edit path stores), so its count is exactly what
    committing it would headline."""
    label: str = Field("", max_length=120)
    patches: List[dict] = Field(default_factory=list, max_length=12)


class AudiencePreviewRequest(BaseModel):
    layers: List[AudienceLayer] = Field(..., min_length=1, max_length=MAX_PREVIEW_LAYERS)


class UpdateThreadRequest(BaseModel):
    title: Optional[NoNulStr] = None
    starred: Optional[bool] = None

class DeleteMultipleThreadsRequest(BaseModel):
    thread_ids: List[str]