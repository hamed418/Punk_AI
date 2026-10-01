import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.models import Base

class MediaFile(Base):
    """Uploaded image or video files for advertising content (demo)."""
    __tablename__ = "media_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)

    original_filename = Column(String(500), nullable=False)
    content_type = Column(String(100), nullable=False)
    media_type = Column(String(10), nullable=False)  # "image" or "video"
    file_size_bytes = Column(Integer, nullable=False)
    file_path = Column(String(1000), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User")
    conversation = relationship("Conversation")
