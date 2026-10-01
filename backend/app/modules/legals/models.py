import uuid
from app.db.models import Base
from sqlalchemy import Column, String, DateTime, Text, Enum as SAEnum, UniqueConstraint, Boolean, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from .schemas import DocumentType, DocumentLanguage

class LegalDocument(Base):
    __tablename__ = "legal_documents"
    __table_args__ = (
        UniqueConstraint("version", name="uq_legal_document_version"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_type = Column(SAEnum(DocumentType), nullable=False)
    content = Column(Text, nullable=False)
    version = Column(String(50), nullable=False)
    language = Column(SAEnum(DocumentLanguage), nullable=False)
    is_active = Column(Boolean, nullable=False, server_default=text("true"), default=True)
    updated_by = Column(String(255), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())