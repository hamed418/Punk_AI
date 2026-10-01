import uuid
from sqlalchemy import (
    Column, Text, String, DateTime, Integer, Numeric, Boolean,
    ForeignKey, Enum as SAEnum, CheckConstraint, UniqueConstraint, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.models import Base
from app.modules.coupon.schemas import DiscountType, RedemptionStatus


class Coupons(Base):
    __tablename__ = "coupons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)

    discount_type = Column(
        SAEnum(DiscountType, values_callable=lambda x: [e.value for e in x], name="discounttype"),
        nullable=False,
    )
    discount_value = Column(Numeric(10, 2), nullable=True) 
    currency = Column(String(3), default="USD")
    max_discount_amount = Column(Numeric(10, 2), nullable=True)

    max_uses = Column(Integer, nullable=True) 
    usage_limit_per_user = Column(Integer, default=1, nullable=True)
    current_uses = Column(Integer, default=0, nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)
    valid_from = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    valid_till = Column(DateTime(timezone=True), nullable=True)

    new_users_only = Column(Boolean, default=False, nullable=False)

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ?relations
    redemptions = relationship(
        "CouponRedemptions",
        back_populates="coupon",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )

    # !validation for security
    __table_args__ = (
        CheckConstraint(
            "(discount_type = 'percentage' AND discount_value > 0 AND discount_value <= 100) OR "
            "(discount_type = 'fixed_amount' AND discount_value > 0) OR "
            "(discount_type = 'full_free')",
            name="ck_valid_discount_value_for_type"
        ),
    )


class CouponRedemptions(Base):
    __tablename__ = "coupon_redemptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    coupon_id = Column(UUID(as_uuid=True), ForeignKey("coupons.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    email = Column(String(255), nullable=True) 
    original_amount = Column(Numeric(10, 2), nullable=False)
    discounted_amount = Column(Numeric(10, 2), nullable=False)
    final_amount = Column(Numeric(10, 2), nullable=False)
    status = Column(
        SAEnum(RedemptionStatus, values_callable=lambda x: [e.value for e in x], name="redemptionstatus"),
        default=RedemptionStatus.APPLIED,
        nullable=False,
    )
    redeemed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reverted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ?relation
    coupon = relationship("Coupons", back_populates="redemptions", lazy="select")