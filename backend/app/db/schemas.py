"""
app/db/schemas.py
Pydantic v2 schemas for API request/response serialization.
Kept separate from ORM models to maintain clean separation of concerns.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_serializer

from app.shared.enums import AdPlatform, CampaignStatus, UserRole

# ── Allowed media types ────────────────────────────────────────
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm", "video/mpeg"}


# ════════════════════════════════════════════════════════════════
# Auth schemas
# ════════════════════════════════════════════════════════════════

# class UserRegisterRequest(BaseModel):
#     email: EmailStr
#     password: str = Field(..., min_length=8, max_length=72)
#     full_name: Optional[str] = None


# class UserUpdateRequest(BaseModel):
#     email: Optional[EmailStr] = None
#     password: Optional[str] = Field(None, min_length=8, max_length=72)
#     full_name: Optional[str] = None


# class UserLoginRequest(BaseModel):
#     email: EmailStr
#     password: str = Field(..., max_length=72)


# class TokenResponse(BaseModel):
#     access_token: str
#     refresh_token: str
#     token_type: str = "bearer"
#     expires_in: int  # seconds


# class UserResponse(BaseModel):
#     id: uuid.UUID
#     email: str
#     full_name: Optional[str]
#     role: UserRole
#     is_active: bool
#     created_at: datetime
#     oauth_tokens: List[OAuthTokenResponse] = []
#     subscription: Optional[UserSubscriptionResponse] = None
#     free_message_limit: Optional[int] = None
#     free_token_usage: Optional[int] = None
#     isSubscriptionActive: Optional[bool] = None

#     # model_config = {"from_attributes": True}
#     model_config = ConfigDict(from_attributes=True)


# class RefreshTokenRequest(BaseModel):
#     refresh_token: str


# class ForgotPasswordRequest(BaseModel):
#     email: EmailStr


# class ResetPasswordRequest(BaseModel):
#     token: str
#     new_password: str = Field(..., min_length=8, max_length=72)


# ════════════════════════════════════════════════════════════════
# Chat / Message schemas
# ════════════════════════════════════════════════════════════════

class MessageRequest(BaseModel):
    thread_id: str = Field(..., description="LangGraph thread ID. Create a new UUID for new conversations.")
    message: str = Field(..., min_length=1, max_length=8000)


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    question:Optional[str] = None
    thinking: Optional[str] = None
    langchain_data: Optional[Any] = None
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


# ════════════════════════════════════════════════════════════════
# Campaign response schemas
# ════════════════════════════════════════════════════════════════

# class CampaignResponse(BaseModel):
#     id: uuid.UUID
#     name: str
#     platform: AdPlatform
#     status: CampaignStatus
#     campaign_plan: Optional[Dict[str, Any]] = None
#     daily_budget_usd: Optional[Decimal] = None
#     monthly_budget_usd: Optional[Decimal] = None
#     impressions: int = 0
#     clicks: int = 0
#     conversions: int = 0
#     spend_usd: Optional[Decimal] = None
#     roas: Optional[Decimal] = None
#     cpa_usd: Optional[Decimal] = None
#     approved_by_user: bool
#     approved_at: Optional[datetime] = None
#     created_at: datetime
# 
#     model_config = {"from_attributes": True}
# 
# 
# class CampaignListResponse(BaseModel):
#     results: List[CampaignResponse]
#     total: int
#     page: int
#     page_size: int


# ════════════════════════════════════════════════════════════════
# Ads OAuth schemas
# ════════════════════════════════════════════════════════════════

# class OAuthConnectResponse(BaseModel):
#     authorization_url: str
#     state: str  # CSRF token
# 
# 
# class OAuthCallbackRequest(BaseModel):
#     code: str
#     state: str
# 
# 
# class AdAccountConnectStatus(BaseModel):
#     platform: AdPlatform
#     connected: bool
#     account_id: Optional[str] = None
#     account_name: Optional[str] = None
#     accessible_accounts: Optional[List[Dict[str, Any]]] = None


# ════════════════════════════════════════════════════════════════
# Media schemas
# ════════════════════════════════════════════════════════════════

# class MediaFileResponse(BaseModel):
#     id: uuid.UUID
#     original_filename: str
#     content_type: str
#     media_type: str
#     file_size_bytes: int
#     file_path: str
#     conversation_id: Optional[uuid.UUID] = None
#     created_at: datetime
# 
#     model_config = {"from_attributes": True}


# ════════════════════════════════════════════════════════════════
# Subscription schemas
# ════════════════════════════════════════════════════════════════

# class UserSubscriptionResponse(BaseModel):
#     id: uuid.UUID
#     stripe_subscription_id: Optional[str]
#     plan_id: Optional[str]
#     usage_token: Optional[int]
#     status: str
#     current_period_end: Optional[datetime]
#     cancel_at_period_end: bool
#     created_at: datetime
#     updated_at: datetime
# 
#     model_config = {"from_attributes": True}
# 
# class StripeCheckoutRequest(BaseModel):
#     subscription_id: str
#     success_url: Optional[str] = None
#     cancel_url: Optional[str] = None
# 
# class StripePortalRequest(BaseModel):
#     return_url: Optional[str] = None
# 
# class StripeSessionResponse(BaseModel):
#     url: str
# 
# class SubscriptionCreateRequest(BaseModel):
#     price_id: str
#     description: str
#     amount: int
#     currency: str
#     total_token_can_use:int
# 
# class SubscriptionUpdateRequest(BaseModel):
#     price_id: Optional[str] = None
#     description: Optional[str] = None
#     amount: Optional[int] = None
#     currency: Optional[str] = None
#     total_token_can_use:Optional[int]=None
# 
# class SubscriptionResponse(BaseModel):
#     id: uuid.UUID
#     price_id: str
#     description: str
#     amount: Decimal
#     @field_serializer("amount")
#     def serialize_amount(self, value: Decimal):
#         return float(value)
#     currency: str
#     total_token_can_use: int
#     created_at: datetime
#     updated_at: datetime
# 
#     model_config = {"from_attributes": True}
# 
# class OAuthTokenResponse(BaseModel):
#     platform: AdPlatform
#     ad_account_id: Optional[str]
#     ad_account_name: Optional[str]
#     expires_at: Optional[datetime]
#     is_valid: bool
# 
#     model_config = {"from_attributes": True}
 