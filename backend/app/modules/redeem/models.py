import uuid
from sqlalchemy import (
    Column, String, DateTime, ForeignKey,
    Boolean, Integer
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.models import Base


class RedeemCode(Base):
    __tablename__ = "redeem_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(100), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_single = Column(Boolean, default=True, nullable=False)
    max_redemptions = Column(Integer, default=1, nullable=False)
    redemption_count = Column(Integer, default=0, nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ?Relationships
    creator = relationship("User", foreign_keys=[created_by], lazy="select")
    redemptions = relationship("RedeemCodeRedemption", back_populates="redeem_code", cascade="all, delete-orphan", lazy="selectin")


class RedeemCodeRedemption(Base):
    __tablename__ = "redeem_code_redemptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    redeem_code_id = Column(UUID(as_uuid=True), ForeignKey("redeem_codes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=True)
    redeemed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ?Relationships
    redeem_code = relationship("RedeemCode", back_populates="redemptions", lazy="select")
    user = relationship("User", foreign_keys=[user_id], lazy="select")
