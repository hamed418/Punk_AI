import uuid 
from app.db.models import Base 
from sqlalchemy import (
    Column, String, Text, DateTime, ForeignKey,
    Numeric, JSON, Boolean, Integer, Enum as SAEnum, Float,   Identity
)
from sqlalchemy.dialects.postgresql import UUID,TIMESTAMP
from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.sql import func
import enum
from app.shared.enums import UserRole,ConversationStatus

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    thread_id = Column(String(255), unique=True, nullable=False, index=True)
    title = Column(String(500), nullable=True)
    starred = Column(Boolean, default=False)
    status = Column(SAEnum(ConversationStatus), default=ConversationStatus.active)
    # LangGraph checkpoint state lives in Postgres via AsyncPostgresSaver
    # (app/graph/graph.py); we store metadata here
    current_step = Column(String(100), nullable=True)
    # Summary buffer (after summarizer_node runs)
    summary_buffer = Column(Text, nullable=True)
    is_final_poi_set = Column(Boolean, default=False)
    final_poi = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="conversations")
    campaigns = relationship("Campaign", back_populates="conversation", lazy="select")
    messages = relationship("ChatMessage", back_populates="conversation", cascade="all, delete-orphan")

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    auto_id = Column(Integer, Identity(start=1, cycle=False), nullable=False)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(50), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    question = Column(Text, nullable=True)
    thinking = Column(Text, nullable=True)     # Internal reasoning (hidden from history)
    langchain_data = Column(JSON, nullable=True) # Full LangChain Message serialization
    # Address of the LangGraph checkpoint this turn ended on. Rewinding forks the
    # checkpoint stamped on the PREVIOUS assistant message — the state before the
    # answer being changed.
    #
    # BOTH halves are required. campaign_builder is a compiled subgraph, and while
    # it is the pending parent task every one of its interrupts happens inside a
    # single parent superstep — so the parent checkpoint_id is IDENTICAL for every
    # builder step and cannot identify one. The per-step state lives under
    # checkpoint_ns "campaign_builder:<task_id>".
    #
    # checkpoint_ns NULL means the row predates this pair and its checkpoint_id is
    # the old ambiguous parent stamp: not rewindable. "" is a real value (a pause
    # in the parent graph), so tests must be `is not None`, never truthiness.
    checkpoint_id = Column(String(255), nullable=True)
    checkpoint_ns = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")