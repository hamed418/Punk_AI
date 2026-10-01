import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator, model_validator
from app.core.security import validate_password_complexity
from app.shared.enums import UserRole
from app.modules.ads.schemas import OAuthTokenResponse 
from app.modules.subscription.schemas import UserSubscriptionResponse

class UserUpdateRequest(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=8, max_length=72)
    full_name: Optional[str] = None
    phone: Optional[str] = None
    select_meta_id: Optional[str] = None
    business_name: Optional[str] = None
    business_type: Optional[str] = None
    why_choose_punk: Optional[str] = None

    @field_validator("password")
    @classmethod
    def validate_update_password(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_password_complexity(v)
        return v

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=72)

    @field_validator("new_password")
    @classmethod
    def validate_change_new_password(cls, v: str) -> str:
        return validate_password_complexity(v)

    @model_validator(mode="after")
    def verify_different_passwords(self):
        if self.current_password and self.new_password and self.current_password == self.new_password:
            raise ValueError("New password cannot be the same as your current password.")
        return self

class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: Optional[str]
    business_name: Optional[str] = None
    phone: Optional[str] = None
    role: UserRole
    is_active: bool
    is_verified: bool = False
    created_at: datetime
    oauth_tokens: List[OAuthTokenResponse] = []
    subscriptions: List[UserSubscriptionResponse] = []
    free_message_limit: Optional[int] = None 
    free_token_usage: Optional[int] = None
    isSubscriptionActive: Optional[bool] = None
    select_meta_id: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

class UserListResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: Optional[str]
    role: UserRole
    is_active: bool
    is_verified: bool = False
    created_at: datetime
    # Enriched fields for the admin users table
    subscription_plan: Optional[str] = None     # name of active plan ("Pro", "Basic", etc.)
    campaigns_count: int = 0
    conversations_count: int = 0
    last_active_at: Optional[datetime] = None   # most recent session activity
    
    model_config = ConfigDict(from_attributes=True)


class UserStatsResponse(BaseModel):
    total_users: int
    active_users: int          # users with a session in the last 30 days
    new_this_month: int
    suspended_users: int
    paying_users: int = 0      # distinct users with an active subscription
    plan_breakdown: dict[str, int]  # {"PRO": 12, "Basic": 40, ...}

class AdsAccountSummary(BaseModel):
    id: uuid.UUID
    ad_account_id: Optional[str] = None
    ad_account_name: Optional[str] = None
    is_subscribed: bool = False
    
    model_config = ConfigDict(from_attributes=True)

class UserDetailsResponse(UserResponse):
    active_devices_count: int = 0
    inactive_devices_count: int = 0
    login_count: int = 0
    subscriptions_count: int = 0
    meta_accounts_count: int = 0
    ads_accounts_count: int = 0
    active_ads_accounts: List[AdsAccountSummary] = []
    
    model_config = ConfigDict(from_attributes=True)

class AdminRoleUpdateRequest(BaseModel):
    role: UserRole

class AdminStatusUpdateRequest(BaseModel):
    is_active: bool

class AdminVerificationUpdateRequest(BaseModel):
    is_verified: bool

class ImpersonateResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse

class StopImpersonationResponse(BaseModel):
    message: str
    admin_id: Optional[str] = None
    target_user_id: Optional[str] = None
