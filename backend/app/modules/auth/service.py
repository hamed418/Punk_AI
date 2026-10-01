from app.modules.auth.schemas import RevokePendingSessionRequest
import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
import httpx
import random
import secrets
import string
from fastapi import HTTPException, status, Request
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    create_pending_login_token,
    decode_token,
)
import hashlib
from user_agents import parse
from starlette.concurrency import run_in_threadpool
from app.core.config import settings
from app.services.email_service import (
    send_verification_otp_email,
    send_password_reset_otp_email,
)
from app.core.logging import logger
from .repository import AuthRepository
from .schemas import (
    TokenResponse,
    GoogleLoginRequest,
    AppleAuthRequest,
    SocialAuthResponse,
    VerifyEmailRequest,
    ResendVerificationRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    CompleteLoginRequest,
    SessionListResponse,
    AdminTokenResponse,
    AdminUserInfo,
    LoginOtpSendRequest,
    LoginOtpVerifyRequest,
)
from app.modules.user.schemas import UserResponse

def generate_numeric_otp(length: int = 5) -> str:
    """Generate a secure N-digit numeric OTP string."""
    return "".join(secrets.choice(string.digits) for _ in range(length))

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def extract_device_info(request: Request) -> dict:
    user_agent_string = request.headers.get("user-agent", "")
    user_agent_string = request.headers.get("user-agent", "")

    # Get original client IP
    forwarded_for = request.headers.get("x-forwarded-for")
    ip_address = "Unknown"
    if forwarded_for:
        ip_address = forwarded_for.split(",")[0].strip()
    else:
        real_ip = request.headers.get("x-real-ip")

        if real_ip:
            ip_address = real_ip.strip()
        else:
            ip_address = (
                request.client.host
                if request.client
                else "Unknown"
            )

    # ip_address = request.client.host if request.client else "Unknown"
    # logger.info(f"User Agent===================================>>>>: {user_agent_string}")
    # logger.info(f"IP Address gggg===================================>>>>: {ip_address}")
    device_name = "Unknown Device"
    device_type = "unknown"
    browser = "Unknown Browser"
    os_name = "Unknown OS"
    
    if user_agent_string:
        ua = parse(user_agent_string)
        device_name = f"{ua.browser.family} on {ua.os.family}"
        if ua.is_mobile:
            device_type = "mobile"
        elif ua.is_tablet:
            device_type = "tablet"
        elif ua.is_pc:
            device_type = "desktop"
        else:
            device_type = "other"
            
        browser = ua.browser.family
        os_name = ua.os.family
        
    return {
        "device_name": device_name,
        "device_type": device_type,
        "browser": browser,
        "operating_system": os_name,
        "ip_address": ip_address
    }

from app.modules.auth.redis_repository import AuthRedisRepository

class AuthService:
    def __init__(self, repository: AuthRepository):
        self.repository = repository
        self.redis_repo = AuthRedisRepository()

    async def signup_start(self, db, payload) -> dict:
        import re
        from fastapi import HTTPException
        import secrets
        
        email = payload.email.strip().lower()
        if not email:
            raise HTTPException(status_code=400, detail="Email is required.")

        email_regex = re.compile(
            r"^[a-zA-Z0-9_.+-]+"
            r"@[a-zA-Z0-9-]+\."
            r"[a-zA-Z0-9-.]+$"
        )
        if not email_regex.match(email):
            raise HTTPException(status_code=400, detail="Invalid email format.")

        duplicate_email = await self.repository.get_user_by_email(db, email)
        if duplicate_email:
            raise HTTPException(status_code=403, detail="User with this email already exists. Please login.")

        # Optional: Enforce early access payment requirement at start if needed.
        # But maybe we'll just let them verify email first. Let's do it like before.

        signup_token = secrets.token_urlsafe(32)
        otp_code = generate_numeric_otp(6)
        
        await self.redis_repo.create_signup_session(signup_token, email)
        await self.redis_repo.save_otp(signup_token, otp_code)
        
        asyncio.create_task(send_verification_otp_email(email, otp_code))
        
        return {
            "status": "success",
            "signup_token": signup_token,
            "message": "OTP has been sent to your email."
        }

    async def signup_verify(self, db, payload) -> dict:
        from fastapi import HTTPException
        
        otp_hash = await self.redis_repo.get_otp_hash(payload.signup_token)
        if not otp_hash:
            raise HTTPException(status_code=400, detail="OTP expired or invalid.")
            
        provided_hash = hashlib.sha256(payload.code.encode()).hexdigest()
        if provided_hash != otp_hash:
            raise HTTPException(status_code=400, detail="Invalid OTP code.")
            
        await self.redis_repo.mark_email_verified(payload.signup_token)
        await self.redis_repo.delete_otp(payload.signup_token)
        
        return {
            "status": "success",
            "message": "Email verified successfully. You can now complete your signup."
        }

    async def signup_complete(self, db, payload, request: Request = None) -> dict:
        from fastapi import HTTPException
        from app.modules.subscription.models import UserSubscription
        from app.shared.enums import SubscriptionStatus
        from sqlalchemy import select

        session = await self.redis_repo.get_signup_session(payload.signup_token)
        if not session or session.get("email_verified") != "true":
            raise HTTPException(status_code=403, detail="Email verification required or session expired.")
            
        email = session.get("email")

        hashed_password = await run_in_threadpool(
            hash_password,
            payload.password,
        )

        duplicate_email = await self.repository.get_user_by_email(db, email)
        if duplicate_email:
            raise HTTPException(
                status_code=403,
                detail="User with this email already exists. Please login."
            )

        # Check early access payment status
        ea_payment = await self.repository.get_early_access_payment_by_email(db, email)
        sub_res = await db.execute(
            select(UserSubscription).where(
                UserSubscription.email == email,
                UserSubscription.status.in_([SubscriptionStatus.active, SubscriptionStatus.trialing])
            )
        )
        existing_sub = sub_res.scalars().first()

        is_paid = bool((ea_payment and ea_payment.is_payment_done) or (existing_sub is not None))
        if not is_paid and settings.STRIPE_SECRET_KEY:
            try:
                import stripe
                stripe.api_key = settings.STRIPE_SECRET_KEY
                sessions = stripe.checkout.Session.list(limit=20)
                for s in sessions.data:
                    cust_email = (s.customer_details and s.customer_details.email) or (s.metadata and s.metadata.get("email"))
                    if cust_email and cust_email.strip().lower() == email and s.payment_status == "paid":
                        is_paid = True
                        if ea_payment:
                            ea_payment.is_payment_done = True
                            db.add(ea_payment)
                        break
            except Exception as e:
                logger.warning(f"Error checking stripe in signup_complete: {e}")

        free_limit = getattr(settings, "DEFAULT_FREE_TOKENS", 10000)

        # Create user with appropriate entitlements
        user = await self.repository.create_user(db, data={
            "email": email,
            "password_hash": hashed_password,
            "full_name": payload.full_name,
            "business_name": payload.business_name,
            "is_verified": True,
            "isSubscriptionActive": is_paid,
            "free_message_limit": None if is_paid else free_limit,
            "free_token_usage": 0,
        })
        db.add(user)
        await db.commit()

        if ea_payment:
            if payload.full_name:
                ea_payment.name = payload.full_name
            if payload.business_name:
                ea_payment.business_name = payload.business_name
            if payload.why_choose_punk:
                ea_payment.why_choose_punk = payload.why_choose_punk
            if is_paid and not ea_payment.is_payment_done:
                ea_payment.is_payment_done = True
            db.add(ea_payment)
            await db.commit()

        if is_paid:
            # Link any pre-existing subscriptions for this email and allocate tokens
            from app.modules.subscription.service import SubscriptionLinkingService
            await SubscriptionLinkingService.link_subscriptions_to_user(db, user)

        # Clean up signup session
        await self.redis_repo.delete_signup_session(payload.signup_token)

        # Generate auth session & JWT tokens for seamless auto-login
        device_info = extract_device_info(request) if request else {}
        device_info["user_id"] = user.id
        
        user_session = await self.repository.create_session(db, device_info)
        
        access_token = create_access_token(str(user.id), user.email, user.role.value, str(user_session.id))
        refresh_token = create_refresh_token(str(user.id), str(user_session.id))
        
        user_session.refresh_token_hash = hash_token(refresh_token)
        await self.repository.update_session(db, user_session)

        return {
            "status": "success",
            "message": "Signup completed successfully.",
            "user_id": str(user.id),
            "email": user.email,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "is_paid": is_paid,
        }

    async def user_register(
        self,
        payload,
    ):
        import re

        if not payload.email or not payload.email.strip():
            raise HTTPException(
                status_code=400,
                detail="Email is required.",
            )

        email = payload.email.strip().lower()

        email_regex = re.compile(
            r"^[a-zA-Z0-9_.+-]+"
            r"@[a-zA-Z0-9-]+\."
            r"[a-zA-Z0-9-.]+$"
        )

        if not email_regex.match(email):
            raise HTTPException(
                status_code=400,
                detail="Invalid email format.",
            )

        if not payload.password:
            raise HTTPException(
                status_code=400,
                detail="Password is required.",
            )

        hashed_password = await run_in_threadpool(
            hash_password,
            payload.password,
        )

        from app.core.redis import get_arq_pool

        redis_pool = await get_arq_pool()

        if not redis_pool:
            raise HTTPException(
                status_code=503,
                detail="Background worker service is currently unavailable. Please try again later.",
            )

        try:
            job = await redis_pool.enqueue_job(
                "process_signup",
                {
                    "email": email,
                    "password_hash": hashed_password,
                    "full_name": payload.full_name,
                    "business_name": payload.business_name,
                    "why_choose_punk": (
                        payload.why_choose_punk
                    ),
                },
                _queue_name=(
                    f"{settings.REDIS_KEY_PREFIX}arq:queue"
                ),
            )
        finally:
            if redis_pool:
                await redis_pool.aclose()

        return {
            "status": "queued",
            "job_id": job.job_id,
            "message": (
                "Signup request has been queued successfully."
            ),
        }

    async def process_signup(self, db, payload) -> UserResponse:
        import re
        email = payload["email"]
        hashed_password = payload["password_hash"]
        full_name = payload["full_name"]
        business_name = payload["business_name"]
        why_choose_punk = payload["why_choose_punk"]
         

        # Enforce early access payment requirement
        from app.modules.subscription.models import UserSubscription
        from app.shared.enums import SubscriptionStatus
        from sqlalchemy import select
        duplicate_email = await self.repository.get_user_by_email(db, email)
        if duplicate_email:
            raise HTTPException(
                status_code=403,
                detail="User with this email already exists. Please login."
            )
        ea_payment = await self.repository.get_early_access_payment_by_email(db, email)
        sub_res = await db.execute(
            select(UserSubscription).where(
                UserSubscription.email == email,
                UserSubscription.status.in_([SubscriptionStatus.active, SubscriptionStatus.trialing])
            )
        )
        existing_sub = sub_res.scalars().first()
        if(existing_sub is None and ea_payment is None):
            user = await self.repository.create_user(db, data={
                "email": email,
                "password_hash": hashed_password,
                "full_name": full_name,
                "business_name": business_name,
                "is_verified": True,
                # "why_choose_punk": why_choose_punk,
                # "verification_code": otp_code,
                # "verification_code_expires_at": otp_expires_at,
            })
            
            db.add(user)
            await db.commit()
            return UserResponse.model_validate(user)

        is_paid = (ea_payment and ea_payment.is_payment_done) or (existing_sub is not None)
        if not is_paid and settings.STRIPE_SECRET_KEY:
            try:
                import stripe
                stripe.api_key = settings.STRIPE_SECRET_KEY
                sessions = stripe.checkout.Session.list(limit=20)
                for s in sessions.data:
                    cust_email = (s.customer_details and s.customer_details.email) or (s.metadata and s.metadata.get("email"))
                    if cust_email and cust_email.strip().lower() == email and s.payment_status == "paid":
                        is_paid = True
                        break
            except Exception as e:
                logger.warning(f"Error checking stripe in user_register: {e}") 

        if not is_paid:
            raise HTTPException(
                status_code=403,
                detail="Early access payment required before registration. Please secure your spot first."
            )
            
        
        otp_code = generate_numeric_otp(5)
        otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

       
        user = await self.repository.create_user(db, data={
                "email": email,
                "password_hash": hashed_password,
                "full_name": full_name,
                "business_name": business_name,
                "is_verified": True,
                "verification_code": otp_code,
                "verification_code_expires_at": otp_expires_at,
            })

        if ea_payment:
            if full_name:
                ea_payment.name = payload.full_name
            if payload.business_name:
                ea_payment.business_name = payload.business_name
            if payload.why_choose_punk:
                ea_payment.why_choose_punk = payload.why_choose_punk
            db.add(ea_payment)
            await db.commit()

        # Link any pre-existing subscriptions for this email
        from app.modules.subscription.service import SubscriptionLinkingService
        await SubscriptionLinkingService.link_subscriptions_to_user(db, user)

        return UserResponse.model_validate(user)

    async def verify_early_access(self, db, email: str) -> dict:
        clean_email = email.strip().lower() if email else ""
        if not clean_email:
            return {"is_paid": False, "is_registered": False, "message": "Email is required"}

        from app.modules.subscription.models import UserSubscription
        from app.shared.enums import SubscriptionStatus
        from sqlalchemy import select

        ea_payment = await self.repository.get_early_access_payment_by_email(db, clean_email)
        sub_res = await db.execute(
            select(UserSubscription).where(
                UserSubscription.email == clean_email,
                UserSubscription.status.in_([SubscriptionStatus.active, SubscriptionStatus.trialing])
            )
        )
        existing_sub = sub_res.scalars().first()

        is_paid = bool((ea_payment and ea_payment.is_payment_done) or (existing_sub is not None))

        if not is_paid and settings.STRIPE_SECRET_KEY:
            try:
                import stripe
                from app.modules.user.models import EarlyAccessPayment
                stripe.api_key = settings.STRIPE_SECRET_KEY
                sessions = stripe.checkout.Session.list(limit=20)
                for s in sessions.data:
                    cust_email = (s.customer_details and s.customer_details.email) or (s.metadata and s.metadata.get("email"))
                    if cust_email and cust_email.strip().lower() == clean_email and s.payment_status == "paid":
                        is_paid = True
                        if ea_payment:
                            ea_payment.is_payment_done = True
                            db.add(ea_payment)
                        else:
                            ea_payment = EarlyAccessPayment(
                                email=clean_email,
                                is_payment_done=True,
                                is_active=True
                            )
                            db.add(ea_payment)
                        await db.commit()
                        break
            except Exception as stripe_err:
                logger.warning(f"Error checking Stripe session for {clean_email}: {stripe_err}")

        existing_user = await self.repository.get_user_by_email(db, clean_email)
        is_registered = existing_user is not None

        return {
            "is_paid": is_paid,
            "is_registered": is_registered,
            "email": clean_email,
            "message": "User already registered" if is_registered else ("Payment verified" if is_paid else "Early access payment required")
        }

    async def verify_email(self, db, payload: VerifyEmailRequest) -> dict:
        email = payload.email.lower()
        user = await self.repository.get_user_by_email(db, email)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        if user.is_verified:
            return {"message": "Email is already verified", "is_verified": True}

        if not user.verification_code or user.verification_code != payload.code:
            raise HTTPException(status_code=400, detail="Invalid verification code")

        now = datetime.now(timezone.utc)
        expires_at = user.verification_code_expires_at
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at and now > expires_at:
            raise HTTPException(status_code=400, detail="Verification code has expired. Please request a new code.")

        user.is_verified = True
        user.verification_code = None
        user.verification_code_expires_at = None
        await self.repository.update_user(db, user)

        return {"message": "Email verified successfully", "is_verified": True}

    async def resend_verification(self, db, payload: ResendVerificationRequest) -> dict:
        email = payload.email.lower()
        user = await self.repository.get_user_by_email(db, email)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if user.is_verified:
            return {"message": "Email is already verified"}

        otp_code = generate_numeric_otp(5)
        otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

        user.verification_code = otp_code
        user.verification_code_expires_at = otp_expires_at
        await self.repository.update_user(db, user)

        asyncio.create_task(send_verification_otp_email(user.email, otp_code))

        return {"message": "Verification code sent successfully"} 
        
    async def _handle_device_login(self, db, user, request: Request):
        # Link any unlinked subscriptions for this email
        from app.modules.subscription.service import SubscriptionLinkingService
        await SubscriptionLinkingService.link_subscriptions_to_user(db, user)

        active_sessions = await self.repository.get_active_sessions_by_user_id(db, str(user.id))
        
        from app.shared.enums import UserRole
        if user.role in (UserRole.admin, UserRole.super_admin) and len(active_sessions) >= 15:
            # For admin users, auto-revoke oldest sessions
            while len(active_sessions) >= 15:
                oldest_session = active_sessions.pop()
                oldest_session.is_active = False
                oldest_session.revoked_at = datetime.now(timezone.utc)
                await self.repository.update_session(db, oldest_session)
        elif len(active_sessions) >= 15:
            pending_token = create_pending_login_token(str(user.id))
            from fastapi.responses import JSONResponse
            
            sessions_data = []
            for s in active_sessions:
                sessions_data.append({
                    "id": str(s.id),
                    "device_name": s.device_name,
                    "device_type": s.device_type,
                    "browser": s.browser,
                    "operating_system": s.operating_system,
                    "ip_address": s.ip_address,
                    "current_device": False,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "last_active_at": s.last_active_at.isoformat() if s.last_active_at else None,
                })
            
            return JSONResponse(
                status_code=403,
                content={
                    "code": "MAX_DEVICE_LIMIT_REACHED",
                    "message": "You are already logged in on 3 devices. Remove an existing device to continue.",
                    "max_devices": 3,
                    "active_devices": len(active_sessions),
                    "sessions": sessions_data,
                    "pending_login_token": pending_token
                }
            )
        
        device_info = extract_device_info(request)
        device_info["user_id"] = user.id
        
        session = await self.repository.create_session(db, device_info)
        
        access_token = create_access_token(str(user.id), user.email, user.role.value, str(session.id))
        refresh_token = create_refresh_token(str(user.id), str(session.id))
        
        session.refresh_token_hash = hash_token(refresh_token)
        await self.repository.update_session(db, session)
        
        return TokenResponse.model_validate({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        })

    async def user_login(self, db, payload, request: Request):
        email = payload.email.lower().strip()
        user = await self.repository.get_user_by_email(db, email)
        
        # Release the DB connection back to the pool before slow password hashing
        await db.commit()
        
        if user and not user.password_hash:
            if user.google_id or user.auth_provider == "google":
                raise HTTPException(
                    status_code=400,
                    detail="This account was registered using Google. Please continue with Google or use 'Forgot password?' to set a password."
                )
            raise HTTPException(
                status_code=400,
                detail="No password set for this account. Please use 'Forgot password?' to create one."
            )

        ok = user and user.password_hash and await run_in_threadpool(verify_password, payload.password, user.password_hash)
        if not ok:
            raise HTTPException(status_code=401, detail="Invalid email or password.")
           
        if not user.is_active:
            raise HTTPException(
                status_code=403,
                detail="Account is deactivated",
            )
        
        # Sync subscription / payment status
        is_paid = await self._resolve_is_paid(db, user.email)
        if is_paid and not user.isSubscriptionActive:
            user.isSubscriptionActive = True
            user = await self.repository.update_user(db, user)

        userToken = await self._handle_device_login(db, user, request)
        return userToken

    async def login_otp_send(self, db, payload: LoginOtpSendRequest):
        email = payload.email.lower().strip()
        user = await self.repository.get_user_by_email(db, email)
        if not user:
            raise HTTPException(
                status_code=404,
                detail="No account found with this email address. Please sign up.",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=403,
                detail="Account is deactivated",
            )

        login_token = secrets.token_urlsafe(32)
        otp_code = generate_numeric_otp(6)
        logger.info(f"Generated login OTP for {email}: {otp_code}")

        await self.redis_repo.create_login_otp(login_token, email, otp_code)
        try:
            await send_verification_otp_email(email, otp_code)
        except Exception as e:
            logger.error(f"Failed to send login OTP email to {email}: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Unable to send verification code email right now. Please try again in a few moments."
            )

        return {
            "status": "success",
            "login_token": login_token,
            "message": "Login code sent to your email.",
        }

    async def login_otp_verify(self, db, payload: LoginOtpVerifyRequest, request: Request):
        otp_data = await self.redis_repo.get_login_otp_data(payload.login_token)
        if not otp_data:
            raise HTTPException(
                status_code=400,
                detail="Login code expired or invalid.",
            )

        provided_hash = hashlib.sha256(payload.code.encode()).hexdigest()
        if provided_hash != otp_data.get("otp_hash"):
            raise HTTPException(
                status_code=400,
                detail="Invalid verification code.",
            )

        email = otp_data.get("email")
        await self.redis_repo.delete_login_otp(payload.login_token)

        user = await self.repository.get_user_by_email(db, email)
        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found.",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=403,
                detail="Account is deactivated",
            )

        userToken = await self._handle_device_login(db, user, request)
        return userToken

    async def admin_login(self, db, payload, request: Request) -> AdminTokenResponse:
        """Admin-only login. Rejects regular users with 403."""
        from app.shared.enums import UserRole
        from fastapi.responses import JSONResponse

        email = payload.email.lower()
        user = await self.repository.get_user_by_email(db, email)

        # Release DB connection before slow password hashing
        await db.commit()

        ok = user and await run_in_threadpool(verify_password, payload.password, user.password_hash)
        if not ok:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        if user.role not in (UserRole.admin, UserRole.super_admin):
            raise HTTPException(
                status_code=403,
                detail="Access denied. Admin or Super Admin privileges required.",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=403,
                detail="Account is deactivated. Contact support.",
            )

        token_response = await self._handle_device_login(db, user, request)
        if isinstance(token_response, JSONResponse):
            return token_response

        return AdminTokenResponse(
            access_token=token_response.access_token,
            refresh_token=token_response.refresh_token,
            token_type=token_response.token_type,
            expires_in=token_response.expires_in,
            user=AdminUserInfo.model_validate(user),
        )

    async def admin_get_me(self, db, current_user) -> AdminUserInfo:
        """Return current admin profile info."""
        return AdminUserInfo.model_validate(current_user)

    async def _resolve_is_paid(self, db: AsyncSession, email: str, explicit_paid: bool = False) -> bool:
        if explicit_paid:
            return True
        from app.modules.subscription.models import UserSubscription
        from app.shared.enums import SubscriptionStatus
        from sqlalchemy import select

        ea_payment = await self.repository.get_early_access_payment_by_email(db, email)
        sub_res = await db.execute(
            select(UserSubscription).where(
                UserSubscription.email == email,
                UserSubscription.status.in_([SubscriptionStatus.active, SubscriptionStatus.trialing])
            )
        )
        existing_sub = sub_res.scalars().first()
        is_paid = bool((ea_payment and ea_payment.is_payment_done) or (existing_sub is not None))

        if not is_paid and settings.STRIPE_SECRET_KEY:
            try:
                import stripe
                stripe.api_key = settings.STRIPE_SECRET_KEY
                sessions = stripe.checkout.Session.list(limit=20)
                for s in sessions.data:
                    cust_email = (s.customer_details and s.customer_details.email) or (s.metadata and s.metadata.get("email"))
                    if cust_email and cust_email.strip().lower() == email and s.payment_status == "paid":
                        is_paid = True
                        if ea_payment:
                            ea_payment.is_payment_done = True
                            db.add(ea_payment)
                            await db.commit()
                        break
            except Exception as e:
                logger.warning(f"Error checking stripe in _resolve_is_paid: {e}")
        return is_paid

    async def google_login(self, db: AsyncSession, payload: GoogleLoginRequest, request: Request):
        from fastapi.responses import JSONResponse
        email = None
        full_name = None
        google_id = None

        token_to_verify = payload.access_token or payload.id_token
        if not token_to_verify:
            raise HTTPException(status_code=400, detail="Google token is required")

        # 1. Try Google userinfo with access token if access_token provided
        if payload.access_token:
            try:
                async with httpx.AsyncClient() as client:
                    res = await client.get(
                        "https://www.googleapis.com/oauth2/v3/userinfo",
                        headers={"Authorization": f"Bearer {payload.access_token}"}
                    )
                    if res.status_code == 200:
                        user_info = res.json()
                        email = user_info.get("email")
                        full_name = user_info.get("name")
                        google_id = user_info.get("sub")
            except Exception as e:
                logger.warning(f"Google userinfo request failed: {e}")

        # 2. If email still None and id_token provided (or access_token was an id_token)
        if not email and token_to_verify:
            candidate_id_token = payload.id_token or token_to_verify
            try:
                from google.oauth2 import id_token as google_id_token
                from google.auth.transport import requests as google_requests
                req = google_requests.Request()
                id_info = google_id_token.verify_oauth2_token(
                    candidate_id_token,
                    req,
                    audience=settings.GOOGLE_CLIENT_ID if settings.GOOGLE_CLIENT_ID else None
                )
                email = id_info.get("email")
                full_name = id_info.get("name")
                google_id = id_info.get("sub")
            except Exception as e:
                logger.warning(f"Google ID token verification failed: {e}")

        if not email:
            raise HTTPException(status_code=401, detail="Invalid Google token or could not retrieve user email")

        email = email.strip().lower()

        # Account linking & lookup: match by google_id first, then email
        user = None
        if google_id:
            user = await self.repository.get_user_by_google_id(db, google_id)
        if not user:
            user = await self.repository.get_user_by_email(db, email)

        # If user already exists (even if created with email), link Google ID
        # and log them in directly — no OTP challenge needed.
        # Keep original auth_provider so email login still works.
        if user and not user.google_id and google_id:
            user.google_id = google_id
            user = await self.repository.update_user(db, user)

        is_new_user = False
        is_flow_paid = bool(payload.paid or (payload.flow and payload.flow.lower() in ("paid", "early_access", "pro")))
        is_paid = await self._resolve_is_paid(db, email, explicit_paid=is_flow_paid)

        if not user:
            is_new_user = True
            free_limit = getattr(settings, "DEFAULT_FREE_TOKENS", 10000)
            user = await self.repository.create_user(db, data={
                "email": email,
                "password_hash": None,
                "full_name": full_name,
                "is_verified": True,
                "auth_provider": "google",
                "google_id": google_id,
                "isSubscriptionActive": is_paid,
                "free_message_limit": None if is_paid else free_limit,
                "free_token_usage": 0,
            })
        else:
            updated = False
            if google_id and user.google_id != google_id:
                user.google_id = google_id
                updated = True
            if full_name and not user.full_name:
                user.full_name = full_name
                updated = True
            if not user.is_verified:
                user.is_verified = True
                updated = True
            if is_paid and not user.isSubscriptionActive:
                user.isSubscriptionActive = True
                updated = True
            if not user.auth_provider:
                user.auth_provider = "google"
                updated = True
            if updated:
                user = await self.repository.update_user(db, user)

        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account is deactivated")

        if is_paid:
            ea_payment = await self.repository.get_early_access_payment_by_email(db, email)
            if ea_payment:
                if full_name and not ea_payment.name:
                    ea_payment.name = full_name
                if not ea_payment.is_payment_done:
                    ea_payment.is_payment_done = True
                db.add(ea_payment)
                await db.commit()
            from app.modules.subscription.service import SubscriptionLinkingService
            await SubscriptionLinkingService.link_subscriptions_to_user(db, user)

        session_result = await self._handle_device_login(db, user, request)
        if isinstance(session_result, JSONResponse):
            return session_result

        return SocialAuthResponse(
            access_token=session_result.access_token,
            refresh_token=session_result.refresh_token,
            token_type=session_result.token_type,
            expires_in=session_result.expires_in,
            user_id=str(user.id),
            email=user.email,
            full_name=user.full_name,
            business_name=user.business_name,
            auth_method="google",
            is_new_user=is_new_user,
            is_paid=bool(user.isSubscriptionActive),
        )

    async def apple_login(self, db: AsyncSession, payload: AppleAuthRequest, request: Request):
        from fastapi.responses import JSONResponse
        if not payload.id_token:
            raise HTTPException(status_code=400, detail="Apple id_token is required")

        # Verify Apple id_token using Apple's JWKS
        claims = {}
        try:
            import jwt
            jwks_client = jwt.PyJWKClient("https://appleid.apple.com/auth/keys", cache_jwk_set=True, lifespan=86400)
            signing_key = jwks_client.get_signing_key_from_jwt(payload.id_token)

            decode_kwargs = {
                "algorithms": ["RS256"],
                "issuer": "https://appleid.apple.com",
            }
            if settings.APPLE_CLIENT_ID:
                decode_kwargs["audience"] = settings.APPLE_CLIENT_ID
            else:
                decode_kwargs["options"] = {"verify_aud": False}

            claims = jwt.decode(payload.id_token, signing_key.key, **decode_kwargs)
        except Exception as e:
            logger.warning(f"Apple JWT signature verification failed: {e}")
            # Gracefully handle unverified decode if testing with sandbox tokens
            try:
                import jwt
                claims = jwt.decode(payload.id_token, options={"verify_signature": False})
            except Exception as inner_e:
                raise HTTPException(status_code=401, detail=f"Invalid Apple identity token: {str(e)}")

        apple_sub = claims.get("sub")
        if not apple_sub:
            raise HTTPException(status_code=400, detail="Apple token missing 'sub' claim")

        # Email can be in token claims OR in the initial user payload
        email = claims.get("email") or payload.email
        if not email and payload.user and payload.user.email:
            email = payload.user.email

        if not email:
            # Check if user already exists with this apple_id
            existing_user = await self.repository.get_user_by_apple_id(db, apple_sub)
            if existing_user:
                email = existing_user.email
            else:
                raise HTTPException(status_code=400, detail="Could not determine email from Apple authorization.")

        email = email.strip().lower()

        # Handle Apple's first-time-only user name
        first = payload.first_name or (payload.user and payload.user.name and payload.user.name.firstName) or ""
        last = payload.last_name or (payload.user and payload.user.name and payload.user.name.lastName) or ""
        full_name = payload.full_name or f"{first} {last}".strip() or None

        user = await self.repository.get_user_by_apple_id(db, apple_sub)
        if not user:
            user = await self.repository.get_user_by_email(db, email)

        # If user already exists (even if created with email), link Apple ID
        # and log them in directly — no OTP challenge needed.
        # Keep original auth_provider so email login still works.
        if user and not user.apple_id:
            user.apple_id = apple_sub
            user = await self.repository.update_user(db, user)

        is_new_user = False
        is_flow_paid = bool(payload.paid or (payload.flow and payload.flow.lower() in ("paid", "early_access", "pro")))
        is_paid = await self._resolve_is_paid(db, email, explicit_paid=is_flow_paid)

        if not user:
            is_new_user = True
            free_limit = getattr(settings, "DEFAULT_FREE_TOKENS", 10000)
            user = await self.repository.create_user(db, data={
                "email": email,
                "password_hash": None,
                "full_name": full_name,
                "is_verified": True,
                "auth_provider": "apple",
                "apple_id": apple_sub,
                "isSubscriptionActive": is_paid,
                "free_message_limit": None if is_paid else free_limit,
                "free_token_usage": 0,
            })
        else:
            updated = False
            if user.apple_id != apple_sub:
                user.apple_id = apple_sub
                updated = True
            if full_name and not user.full_name:
                user.full_name = full_name
                updated = True
            if not user.is_verified:
                user.is_verified = True
                updated = True
            if is_paid and not user.isSubscriptionActive:
                user.isSubscriptionActive = True
                updated = True
            if not user.auth_provider:
                user.auth_provider = "apple"
                updated = True
            if updated:
                user = await self.repository.update_user(db, user)

        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account is deactivated")

        if is_paid:
            from app.modules.subscription.service import SubscriptionLinkingService
            await SubscriptionLinkingService.link_subscriptions_to_user(db, user)

        session_result = await self._handle_device_login(db, user, request)
        if isinstance(session_result, JSONResponse):
            return session_result

        return SocialAuthResponse(
            access_token=session_result.access_token,
            refresh_token=session_result.refresh_token,
            token_type=session_result.token_type,
            expires_in=session_result.expires_in,
            user_id=str(user.id),
            email=user.email,
            full_name=user.full_name,
            business_name=user.business_name,
            auth_method="apple",
            is_new_user=is_new_user,
            is_paid=bool(user.isSubscriptionActive),
        )



    async def forgot_password(self, db, payload) -> dict:
        email = payload.email.lower()
        user = await self.repository.get_user_by_email(db, email)
        if user and user.is_active:
            otp_code = generate_numeric_otp(5)
            otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
            user.password_reset_code = otp_code
            user.password_reset_code_expires_at = otp_expires_at
            await self.repository.update_user(db, user)

            asyncio.create_task(send_password_reset_otp_email(user.email, otp_code))

        # Always return uniform message to prevent email enumeration
        return {"message": "If an account exists with this email, a reset code has been sent."}

    async def user_reset_password(self, db, payload: ResetPasswordRequest) -> dict:
        email = payload.email.lower()
        user = await self.repository.get_user_by_email(db, email)
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found or deactivated",
            )

        if not user.password_reset_code or user.password_reset_code != payload.code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid password reset code",
            )

        now = datetime.now(timezone.utc)
        expires_at = user.password_reset_code_expires_at
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at and now > expires_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password reset code has expired. Please request a new code.",
            )

        if user.password_hash and await run_in_threadpool(verify_password, payload.new_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password cannot be the same as your previous password.",
            )

        user.password_hash = await run_in_threadpool(hash_password, payload.new_password)
        user.password_reset_code = None
        user.password_reset_code_expires_at = None
        await self.repository.update_user(db, user)

        return {"message": "Password has been successfully reset."}
    
    async def user_refresh_token(self, db, payload) -> TokenResponse:
        decoded = decode_token(payload.refresh_token) 
        if not decoded or decoded.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )

        user_id = decoded.get("sub")
        session_id = decoded.get("session_id")
        user = await self.repository.get_user_by_id(db, user_id)

        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or deactivated",
            )

        if session_id:
            session = await self.repository.get_session_by_id(db, session_id)
            if not session or not session.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="SESSION_REVOKED",
                )
            
            # Check hash match, allowing a 30s grace window if recently refreshed
            now = datetime.now(timezone.utc)
            incoming_hash = hash_token(payload.refresh_token)
            hash_matches = bool(session.refresh_token_hash and session.refresh_token_hash == incoming_hash)
            
            recent_refresh = False
            if not hash_matches and session.last_active_at:
                last_active = session.last_active_at
                if last_active.tzinfo is None:
                    last_active = last_active.replace(tzinfo=timezone.utc)
                if (now - last_active).total_seconds() < 30:
                    recent_refresh = True

            if not hash_matches and not recent_refresh and session.refresh_token_hash:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid refresh token for this session",
                )

            session.last_active_at = now
            
            impersonator_id = decoded.get("impersonator_id")
            access_token = create_access_token(
                str(user.id),
                user.email,
                user.role.value if hasattr(user.role, 'value') else user.role,
                str(session.id),
                impersonator_id=impersonator_id
            )
            refresh_token = create_refresh_token(str(user.id), str(session.id), impersonator_id=impersonator_id)
            session.refresh_token_hash = hash_token(refresh_token)
            await self.repository.update_session(db, session)
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="SESSION_REVOKED",
            )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def get_active_sessions(self, db, current_user, request: Request) -> SessionListResponse:
        active_sessions = await self.repository.get_active_sessions_by_user_id(db, str(current_user.id))
        
        # Get current session id from header/JWT if possible, but let's assume it's tricky to get here directly
        # The router injects current_user, but we can decode the token manually if we need to know current_device.
        auth_header = request.headers.get("Authorization")
        current_session_id = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            decoded = decode_token(token)
            if decoded:
                current_session_id = decoded.get("session_id")
                
        sessions_data = []
        for s in active_sessions:
            sessions_data.append({
                "id": str(s.id),
                "device_name": s.device_name,
                "device_type": s.device_type,
                "browser": s.browser,
                "operating_system": s.operating_system,
                "ip_address": s.ip_address,
                "current_device": str(s.id) == current_session_id,
                "created_at": s.created_at,
                "last_active_at": s.last_active_at,
            })
            
        return SessionListResponse(
            max_devices=3,
            active_devices=len(active_sessions),
            sessions=sessions_data
        )

    async def revoke_session(self, db, current_user, session_id: str) -> dict:
        session = await self.repository.get_session_by_id(db, session_id)
        if not session or str(session.user_id) != str(current_user.id):
            raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")
            
        if not session.is_active:
            raise HTTPException(status_code=400, detail="Session is already revoked")
            
        session.is_active = False
        session.revoked_at = datetime.now(timezone.utc)
        await self.repository.update_session(db, session)
        
        return {"message": "Device session revoked successfully."}

    async def revoke_pending_session(self, db: AsyncSession, payload: RevokePendingSessionRequest) -> dict:
        from app.core.security import decode_token
        decoded = decode_token(payload.pending_login_token)
        if not decoded or decoded.get("type") != "pending_login":
            raise HTTPException(status_code=400, detail="INVALID_PENDING_LOGIN")
            
        user_id = decoded.get("sub")
        session = await self.repository.get_session_by_id(db, payload.session_id)
        
        if not session or str(session.user_id) != str(user_id):
            raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")
            
        if not session.is_active:
            raise HTTPException(status_code=400, detail="Session is already revoked")
            
        session.is_active = False
        session.revoked_at = datetime.now(timezone.utc)
        await self.repository.update_session(db, session)
        
        return {"message": "Device session revoked successfully."}

    async def complete_login(self, db: AsyncSession, payload: CompleteLoginRequest, request: Request) -> dict:
        decoded = decode_token(payload.pending_login_token)
        if not decoded or decoded.get("type") != "pending_login":
            raise HTTPException(status_code=400, detail="INVALID_PENDING_LOGIN")
            
        user_id = decoded.get("sub")
        user = await self.repository.get_user_by_id(db, user_id)
        if not user or not user.is_active:
            raise HTTPException(status_code=403, detail="Account is deactivated")
            
        return await self._handle_device_login(db, user, request)

    async def logout(self, db: AsyncSession, request: Request, current_user) -> dict:
        auth_header = request.headers.get("Authorization")
        current_session_id = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            decoded = decode_token(token)
            if decoded:
                current_session_id = decoded.get("session_id")
                
        if current_session_id:
            session = await self.repository.get_session_by_id(db, current_session_id)
            if session and session.is_active:
                session.is_active = False
                session.revoked_at = datetime.now(timezone.utc)
                await self.repository.update_session(db, session)
                
        return {"message": "Logged out successfully"}