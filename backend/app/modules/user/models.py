import uuid 
from app.db.models import Base 
from sqlalchemy import (
    Column, String,   DateTime, 
     Boolean, Integer, Enum as SAEnum, ForeignKey
)
from sqlalchemy.dialects.postgresql import UUID,TIMESTAMP
from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.sql import func
import enum
from app.shared.enums import UserRole
from app.modules.chat.models import Conversation 
from app.modules.campaigns.models import Campaign
from app.modules.subscription.models import UserSubscription

class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    device_name = Column(String(255), nullable=True)
    device_type = Column(String(50), nullable=True)
    browser = Column(String(100), nullable=True)
    operating_system = Column(String(100), nullable=True)
    ip_address = Column(String(45), nullable=True)
    refresh_token_hash = Column(String(255), nullable=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_active_at = Column(DateTime(timezone=True), server_default=func.now())
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="sessions", lazy="select")
 
class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)
    auth_provider = Column(String(50), nullable=True, default="email")
    google_id = Column(String(255), unique=True, nullable=True, index=True)
    apple_id = Column(String(255), unique=True, nullable=True, index=True)
    full_name = Column(String(255), nullable=True)
    business_name = Column(String(255), nullable=True) 
    phone = Column(String(20), nullable=True)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.user)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    verification_code = Column(String(10), nullable=True)
    verification_code_expires_at = Column(DateTime(timezone=True), nullable=True)
    password_reset_code = Column(String(10), nullable=True)
    password_reset_code_expires_at = Column(DateTime(timezone=True), nullable=True)
    # Misnamed: every writer (app/modules/payment/service.py assign_ad_account,
    # the profile PATCH in app/modules/user/service.py) puts a *selected ad
    # account id* (act_...) here, not a Meta person id. Not a Meta-identity
    # column — nothing in this codebase can obtain one under Facebook Login
    # for Business (see app/modules/ads/repository.py, save_user_oauth_tokens).
    select_meta_id=Column(String(255), nullable=True)
    stripe_customer_id = Column(String(255), nullable=True)
    free_message_limit = Column(Integer, default=10000)
    free_token_usage = Column(Integer, default=0)
    isSubscriptionActive = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    conversations = relationship("Conversation", back_populates="user", lazy="select")
    campaigns = relationship("Campaign", back_populates="user", lazy="select")
    subscriptions = relationship("UserSubscription", back_populates="user", lazy="select")
    sessions = relationship("UserSession", back_populates="user", lazy="select")
    oauth_tokens = relationship(
        "OAuthToken",
        back_populates="user",
        lazy="selectin"
    )
    ads_accounts = relationship("AdsAccount", back_populates="user", lazy="selectin")

class EarlyAccessPayment(Base):
    __tablename__ = "early_access_payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), nullable=False, index=True)
    name = Column(String(255), nullable=True) 
    business_name = Column(String(255), nullable=True) 
    is_active = Column(Boolean, default=True, nullable=False)
    is_payment_done = Column(Boolean, default=False, nullable=True)
    why_choose_punk = Column(String(5000), nullable=True)  
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    
