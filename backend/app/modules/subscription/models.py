from app.shared.enums import SubscriptionPaymentStatus, PurchaseType
import uuid
from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey, Enum as SAEnum, Integer, Boolean, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.models import Base
from app.shared.enums import SubscriptionStatus

class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    price_id = Column(String, nullable=True)
    name = Column(
        String(100),
        nullable=True,
    )
    slug = Column(
        String(100),
        unique=True,
        nullable=True,
    )
    description = Column(String)
    amount = Column(Numeric(10, 2))
    currency = Column(String(3), default="usd")
    interval = Column(
        String(20),
        nullable=True,
        default="month",
    )
    type = Column(SAEnum(PurchaseType), default=PurchaseType.SUBSCRIPTION)
    total_token_can_use = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    user_subscriptions = relationship("UserSubscription", back_populates="plan")

class UserSubscription(Base):
    __tablename__ = "user_subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "ad_account_id", name="uq_user_ad_account_sub"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    email = Column(String(255), nullable=True)
    normalized_email = Column(String(255), nullable=True, index=True)
    
    total_tokens = Column(Integer, default=0, nullable=False)
    used_tokens = Column(Integer, default=0, nullable=False)
    remaining_tokens = Column(Integer, default=0, nullable=False)
    
    # SET NULL, not CASCADE: this row carries the Stripe linkage
    # (stripe_customer_id/stripe_subscription_id). Under CASCADE, deleting the
    # Meta connection — a plain disconnect, or Meta's own deletion callback —
    # deleted the user's paid subscription along with it.
    meta_ads_id = Column(UUID(as_uuid=True), ForeignKey("oauth_tokens.id", ondelete="SET NULL"), nullable=True)
    ad_account_id = Column(String(50), nullable=True, index=True)
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, unique=True, index=True, nullable=True)  
    status = Column(SAEnum(SubscriptionStatus), default=SubscriptionStatus.incomplete)
    payment_status = Column(SAEnum(SubscriptionPaymentStatus), default=SubscriptionPaymentStatus.unpaid)
    
    plan_id = Column(UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True) 
    
    usage_token = Column(Integer, default=0)
    current_period_start = Column(DateTime(timezone=True), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    auto_renewal = Column(Boolean, default=True, nullable=False)
    cancel_at_period_end = Column(Boolean, default=False, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="subscriptions")
    meta_ads = relationship("OAuthToken", back_populates="meta_account_subscriptions")
    ads_accounts = relationship("AdsAccount", back_populates="subscription", lazy="select")
    plan = relationship("Subscription", back_populates="user_subscriptions")

class SubscriptionTokenAllocation(Base):
    __tablename__ = "subscription_token_allocations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("user_subscriptions.id", ondelete="CASCADE"), unique=True, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    allocated_at = Column(DateTime(timezone=True), server_default=func.now())

class TokenTransaction(Base):
    __tablename__ = "token_transactions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("user_subscriptions.id", ondelete="SET NULL"), nullable=True)
    type = Column(String(50), nullable=False)  # ALLOCATION, USAGE, REFUND, ADJUSTMENT
    amount = Column(Integer, nullable=False)
    balance_before = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)
    action = Column(String(255), nullable=True)
    tx_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())