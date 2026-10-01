from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_db, get_current_user, get_admin_user
from app.core.security import skip_api_key
from app.shared.pagination import PaginationParams, PaginatedResponse
from typing import Optional
from app.modules.user.models import User
from app.core.limiter import limiter
from .service import AuthService
from .repository import AuthRepository
from .schemas import (
    UserRegisterRequest,
    UserLoginRequest,
    SignupStartRequest,
    SignupStartResponse,
    SignupVerifyRequest,
    SignupVerifyResponse,
    SignupCompleteRequest,
    SignupCompleteResponse,
    TokenResponse,
    RefreshTokenRequest,
    GoogleLoginRequest,
    AppleAuthRequest,
    SocialAuthResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
    ResendVerificationRequest,
    SessionListResponse,
    CompleteLoginRequest,
    RevokePendingSessionRequest,
    EarlyAccessVerifyResponse,
    AdminLoginRequest,
    AdminTokenResponse,
    AdminUserInfo,
    SignupQueuedResponse,
    LoginOtpSendRequest,
    LoginOtpSendResponse,
    LoginOtpVerifyRequest,
)
from app.modules.user.schemas import UserResponse

router = APIRouter(
    prefix="/auth",
    tags=["Auth & Onboarding"]
)

repository = AuthRepository()
service = AuthService(repository)
#   early access 
@router.get(
    "/check-email",
    summary="Check if user exists and determine primary auth method",
    description="Returns whether an email is already registered and its primary auth method (email or google)."
)
@skip_api_key
async def check_email_exists(
    email: str,
    db: AsyncSession = Depends(get_db)
):
    clean_email = email.strip().lower() if email else ""
    if not clean_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is required.")
    user = await repository.get_user_by_email(db, clean_email)
    auth_method = None
    if user:
        # If user registered with Google and has not set a password, direct to Google Sign-In
        if not user.password_hash and (user.google_id or user.auth_provider == "google"):
            auth_method = "google"
        else:
            # Users with a password (or legacy social without password) log in with password
            auth_method = "email"

    return {
        "exists": user is not None,
        "email": clean_email,
        "auth_method": auth_method,
        "has_password": bool(user and user.password_hash),
        "message": f"Account linked to {auth_method}" if user else "User does not exist"
    }

@router.get(
    "/verify-early-access",
    response_model=EarlyAccessVerifyResponse,
    summary="Verify Early Access Payment Status",
    description="Validates whether an email address has completed early access payment on Stripe. Unlocks the 2-step onboarding and signup flow if paid."
)
@skip_api_key
async def verify_early_access_payment(
    email: str,
    db: AsyncSession = Depends(get_db)
):
    return await service.verify_early_access(db, email)

@router.post(
    "/register",
    response_model=SignupQueuedResponse,
    summary="Complete Early Access Registration & Onboarding",
    description="Registers or updates the user account with business info (name, type, why punk), hashes password, and activates the account if early access payment is confirmed."
)
async def user_register(
    payload: UserRegisterRequest,
    # db: AsyncSession = Depends(get_db),
):
    return await service.user_register( payload)

@router.post("/verify-email")
@limiter.limit("10/minute")
async def verify_email(
    request: Request,
    payload: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    return await service.verify_email(db, payload)

@router.post("/resend-verification")
@limiter.limit("5/minute")
async def resend_verification(
    request: Request,
    payload: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
):
    return await service.resend_verification(db, payload)

@router.post(
    "/login",
    response_model=TokenResponse,
    summary="User Login",
    description="Authenticates user with email and password, returning JWT access & refresh tokens."
)
@limiter.limit("200/minute")
async def user_login(
    request: Request,
    payload: UserLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    return await service.user_login(db, payload, request)

@router.post(
    "/login/otp/send",
    response_model=LoginOtpSendResponse,
    summary="Send Login OTP Code",
    description="Generates and emails a 6-digit OTP code to the user for login."
)
@skip_api_key
@limiter.limit("10/minute")
async def send_login_otp(
    request: Request,
    payload: LoginOtpSendRequest,
    db: AsyncSession = Depends(get_db),
):
    return await service.login_otp_send(db, payload)

@router.post(
    "/login/otp/verify",
    response_model=TokenResponse,
    summary="Verify Login OTP Code",
    description="Verifies the 6-digit login OTP and authenticates the user."
)
@skip_api_key
@limiter.limit("20/minute")
async def verify_login_otp(
    request: Request,
    payload: LoginOtpVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    return await service.login_otp_verify(db, payload, request)

@router.post(
    "/google",
    response_model=SocialAuthResponse,
    summary="Google OAuth Login & Signup",
    description="Authenticates or signs up a user using a Google OAuth access token or ID token."
)
@skip_api_key
@limiter.limit("50/minute")
async def user_login_google(
    request: Request,
    payload: GoogleLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    return await service.google_login(db, payload, request)

@router.post(
    "/apple",
    response_model=SocialAuthResponse,
    summary="Apple OAuth Login & Signup",
    description="Authenticates or registers a user using an Apple OAuth identity token with account linking."
)
@skip_api_key
@limiter.limit("50/minute")
async def user_login_apple(
    request: Request,
    payload: AppleAuthRequest,
    db: AsyncSession = Depends(get_db),
):
    return await service.apple_login(db, payload, request)

@router.post(
    "/forgot-password",
    summary="Request Password Reset OTP",
    description="Generates and emails a 5-digit password reset OTP to the user."
)
@limiter.limit("10/minute")
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    return await service.forgot_password(db, payload)

@router.post(
    "/reset-password",
    summary="Reset Password with OTP",
    description="Resets the user's password using the verified 5-digit OTP."
)
@limiter.limit("10/minute")
async def user_reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    return await service.user_reset_password(db, payload)

@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh Access Token",
    description="Issues a new JWT access token and refresh token using a valid refresh token.",
)
@skip_api_key
async def refresh_token_for_get_access_token(
    payload: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    return await service.user_refresh_token(db, payload)

@router.get(
    "/sessions",
    response_model=SessionListResponse,
    summary="List Active User Sessions",
    description="Retrieves all active device sessions for the authenticated user."
)
async def get_active_sessions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_active_sessions(db, current_user, request)

@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.revoke_session(db, current_user, session_id)

@router.post("/revoke-pending-session")
@limiter.limit("50/minute")
async def revoke_pending_session(
    request: Request,
    payload: RevokePendingSessionRequest,
    db: AsyncSession = Depends(get_db),
):
    return await service.revoke_pending_session(db, payload)

@router.post("/complete-login")
@limiter.limit("50/minute")
async def complete_login(
    request: Request,
    payload: CompleteLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    return await service.complete_login(db, payload, request)

@router.post("/logout")
async def user_logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.logout(db, request, current_user)

# verifyfication signup system 
@router.post("/signup/start", response_model=SignupStartResponse)
async def user_signup_start(
    request: Request,
    payload: SignupStartRequest,
    db: AsyncSession = Depends(get_db),
):
    return await service.signup_start(db, payload)

@router.post("/signup/verify", response_model=SignupVerifyResponse)
async def user_signup_verify(
    request: Request,
    payload: SignupVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    return await service.signup_verify(db, payload)

@router.post("/signup/complete", response_model=SignupCompleteResponse)
async def user_signup_complete(
    request: Request,
    payload: SignupCompleteRequest,
    db: AsyncSession = Depends(get_db),
):
    return await service.signup_complete(db, payload, request)

# ── Admin-Only Auth Endpoints ────────────────────────────────────────────────

@router.post(
    "/admin/login",
    response_model=AdminTokenResponse,
    tags=["Admin - Auth"],
    summary="Admin Panel Login",
    description=(
        "Authenticates admin or super admin accounts only. Regular users are rejected with 403. "
        "Returns JWT access & refresh tokens along with admin profile info."
    ),
)
@skip_api_key
@limiter.limit("20/minute")
async def admin_login(
    request: Request,
    payload: AdminLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    return await service.admin_login(db, payload, request)


@router.get(
    "/admin/me",
    response_model=AdminUserInfo,
    tags=["Admin - Auth"],
    summary="Get Admin Profile",
    description="Returns the authenticated admin's profile (role, email, name). Requires valid admin access token.",
)
async def admin_get_me(
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.admin_get_me(db, current_user)


@router.post(
    "/admin/logout",
    tags=["Admin - Auth"],
    summary="Admin Logout",
    description="Revokes the admin's current session and invalidates the access token.",
)
async def admin_logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    return await service.logout(db, request, current_user)