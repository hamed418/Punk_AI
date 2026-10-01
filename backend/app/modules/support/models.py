import uuid
from app.db.models import Base
from sqlalchemy import (
    Column, String, DateTime, ForeignKey, Text, Enum as SAEnum
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.shared.enums import SupportStatus

class Support(Base):
    __tablename__ = "supports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    category_id = Column(UUID(as_uuid=True), ForeignKey("faq_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    problem_type = Column(String(255), nullable=True)
    description = Column(Text, nullable=False)
    status = Column(SAEnum(SupportStatus), default=SupportStatus.OPEN, nullable=False)
    
    attachment = Column(String(1024), nullable=True)
    attachment_type = Column(String(255), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", backref="supports", lazy="selectin")
    category = relationship("FAQCategory", back_populates="supports", lazy="selectin")
