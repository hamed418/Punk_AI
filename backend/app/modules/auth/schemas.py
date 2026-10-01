
import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator
from app.core.security import validate_password_complexity
from app.shared.enums import UserRole
from app.modules.ads.schemas import OAuthTokenResponse 
from app.modules.subscription.schemas import UserSubscriptionResponse

# ════════════════════════════════════════════════════════════════
# Auth schemas
# ════════════════════════════════════════════════════════════════

class EarlyAccessVerifyResponse(BaseModel):
    is_paid: bool = Field(..., description="Whether early access payment has been completed for this email")
    is_registered: bool = Field(..., description="Whether user is already registered (false if user can complete signup)")
    email: Optional[str] = Field(None, description="Normalized email address")
    message: str = Field(..., description="Human-readable verification message")


class UserRegisterRequest(BaseModel):
    email: Optional[str] = Field(None, description="User email address (must match verified early access payment)")
    password: Optional[str] = Field(None, description="Password for the user account")
    full_name: Optional[str] = Field(None, description="Full name of the user")
    business_name: Optional[str] = Field(None, description="Name of the business or company")
    business_type: Optional[str] = Field(None, description="Type of business (e.g. E-Commerce, Local Service, Agency)")
    why_choose_punk: Optional[str] = Field(None, description="Why the user chose Punk AI")

    @field_validator("password")
    @classmethod
    def validate_register_password(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_password_complexity(v)
        return v


#otp related signup setup #################
class SignupStartRequest(BaseModel):
    email: EmailStr

class SignupStartResponse(BaseModel):
    status: str
    signup_token: str
    message: str

class SignupVerifyRequest(BaseModel):
    signup_token: str
    code: str = Field(min_length=6, max_length=6)

class SignupVerifyResponse(BaseModel):
    status: str
    message: str

class SignupCompleteRequest(BaseModel):
    signup_token: str

    password: str = Field(
        min_length=8,
        max_length=72,
    )

    @field_validator("password")
    @classmethod
    def validate_signup_password(cls, v: str) -> str:
        return validate_password_complexity(v)

    full_name: str = Field(
        min_length=1,
        max_length=255,
    )

    business_name: str | None = Field(
        default=None,
        max_length=255,
    )

    business_type: str | None = Field(
        default=None,
        max_length=255,
    )

    why_choose_punk: str | None = None


class SignupCompleteResponse(BaseModel):
    status: str
    message: str
    user_id: Optional[str] = None
    email: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: Optional[str] = "bearer"
    expires_in: Optional[int] = None
    is_paid: Optional[bool] = False

class SignupQueuedResponse(BaseModel):
    status: str
    job_id: str
    message: str


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=72)


class GoogleLoginRequest(BaseModel):
    access_token: Optional[str] = None
    id_token: Optional[str] = None
    flow: Optional[str] = None
    paid: Optional[bool] = False


class AppleUserName(BaseModel):
    firstName: Optional[str] = None
    lastName: Optional[str] = None


class AppleUserObj(BaseModel):
    name: Optional[AppleUserName] = None
    email: Optional[str] = None


class AppleAuthRequest(BaseModel):
    id_token: str
    code: Optional[str] = None
    user: Optional[AppleUserObj] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    flow: Optional[str] = None
    paid: Optional[bool] = False


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class SocialAuthResponse(TokenResponse):
    user_id: str
    email: str
    full_name: Optional[str] = None
    business_name: Optional[str] = None
    why_choose_punk: Optional[str] = None
    auth_method: str
    is_new_user: bool = False
    is_paid: bool = False


class LoginOtpSendRequest(BaseModel):
    email: EmailStr

class LoginOtpSendResponse(BaseModel):
    status: str
    login_token: str
    message: str

class LoginOtpVerifyRequest(BaseModel):
    login_token: str
    code: str = Field(..., min_length=6, max_length=6)

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=5, max_length=5)

class ResendVerificationRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=5, max_length=5)
    new_password: str = Field(..., min_length=8, max_length=72)

    @field_validator("new_password")
    @classmethod
    def validate_reset_new_password(cls, v: str) -> str:
        return validate_password_complexity(v)


class CompleteLoginRequest(BaseModel):
    pending_login_token: str

class RevokePendingSessionRequest(BaseModel):
    pending_login_token: str
    session_id: str

class SessionResponse(BaseModel):
    id: str
    device_name: Optional[str] = None
    device_type: Optional[str] = None
    browser: Optional[str] = None
    operating_system: Optional[str] = None
    ip_address: Optional[str] = None
    current_device: bool = False
    created_at: datetime
    last_active_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SessionListResponse(BaseModel):
    max_devices: int
    active_devices: int
    sessions: List[SessionResponse]


# ════════════════════════════════════════════════════════════════
# Admin Auth schemas
# ════════════════════════════════════════════════════════════════

class AdminLoginRequest(BaseModel):
    email: EmailStr = Field(..., description="Admin or Super Admin email address")
    password: str = Field(..., max_length=72, description="Account password")


class AdminUserInfo(BaseModel):
    id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    role: UserRole

    model_config = ConfigDict(from_attributes=True)


class AdminTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AdminUserInfo
