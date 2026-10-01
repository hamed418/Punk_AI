import asyncio
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from app.core.security import hash_password, verify_password, decode_token
from starlette.concurrency import run_in_threadpool
from app.shared.enums import AdPlatform, UserRole
from app.core.security import create_access_token, create_refresh_token
from app.modules.user.models import UserSession
from app.modules.auditLogs.repository import AuditLogRepository
from app.modules.auditLogs.schemas import AuditLogRequest
from .repository import UserRepository
from .schemas import (
    UserResponse, UserListResponse, UserDetailsResponse, AdsAccountSummary,
    ImpersonateResponse, StopImpersonationResponse, AdminRoleUpdateRequest, AdminStatusUpdateRequest,
    AdminVerificationUpdateRequest, UserStatsResponse,
)

class UserService:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    async def user_me(self, db, current_user) -> UserResponse:
        user = await self.repository.get_user_by_id(db, current_user.id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return UserResponse.model_validate(user)
    
    async def user_update(self, db, current_user, payload) -> UserResponse:
        """Update current user's profile."""
        user = await self.repository.get_user_by_id(db, current_user.id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # if payload.password:
        #     user.password_hash = await run_in_threadpool(hash_password, payload.password)
        
        if payload.email:
            user.email = payload.email.lower()
        if payload.full_name is not None:
            user.full_name = payload.full_name
        if payload.phone is not None:
            user.phone = payload.phone
        if payload.business_name is not None:
            user.business_name = payload.business_name
        elif payload.business_type is not None:
            user.business_name = payload.business_type

        if payload.why_choose_punk is not None or payload.business_name is not None or payload.business_type is not None:
            from app.modules.user.models import EarlyAccessPayment
            from sqlalchemy import select, func
            stmt = (
                select(EarlyAccessPayment)
                .where(func.lower(EarlyAccessPayment.email) == user.email.lower())
                .order_by(EarlyAccessPayment.is_payment_done.desc(), EarlyAccessPayment.created_at.desc())
            )
            result = await db.execute(stmt)
            ea_records = result.scalars().all()
            if ea_records:
                for ea_payment in ea_records:
                    if payload.why_choose_punk:
                        ea_payment.why_choose_punk = payload.why_choose_punk
                    if payload.business_name or payload.business_type:
                        ea_payment.business_name = payload.business_name or payload.business_type
                    if payload.full_name:
                        ea_payment.name = payload.full_name
                    db.add(ea_payment)
            elif payload.why_choose_punk or payload.business_name or payload.business_type:
                ea_payment = EarlyAccessPayment(
                    email=user.email.lower(),
                    name=payload.full_name or user.full_name,
                    business_name=payload.business_name or payload.business_type or user.business_name,
                    why_choose_punk=payload.why_choose_punk,
                    is_active=True,
                    is_payment_done=bool(user.isSubscriptionActive),
                )
                db.add(ea_payment)

        if payload.select_meta_id is not None:
            # Switching accounts must move oauth_tokens.selected_account too —
            # that's the column publish and the campaign list actually read.
            # A bare `user.select_meta_id = ...` here left that column stuck
            # on whichever account was selected first, so switching in the UI
            # never changed which account Punk published into.
            from app.modules.ads.repository import AdsRepository
            if not await AdsRepository().update_selected_account(
                db, current_user.id, payload.select_meta_id
            ):
                raise HTTPException(
                    status_code=400, detail="That Meta ad account is not connected"
                )
            # update_selected_account already wrote users.select_meta_id (one
            # commit with selected_account). This line only keeps the loaded row
            # honest: sessions run expire_on_commit=False, so without it the
            # response below could carry the previous account.
            user.select_meta_id = payload.select_meta_id

        user = await self.repository.update_user(db, user)
        return UserResponse.model_validate(user)

    async def change_password(self, db, current_user, payload) -> dict:
        user = await self.repository.get_user_by_id(db, current_user.id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        is_valid = await run_in_threadpool(verify_password, payload.current_password, user.password_hash)
        if not is_valid:
            raise HTTPException(status_code=400, detail="Invalid current password")
        
        is_same = await run_in_threadpool(verify_password, payload.new_password, user.password_hash)
        if is_same:
            raise HTTPException(
                status_code=400,
                detail="New password cannot be the same as your current password.",
            )
        
        user.password_hash = await run_in_threadpool(hash_password, payload.new_password)
        await self.repository.update_user(db, user)
        return {"message": "Password updated successfully"}

    async def list_users(
        self,
        db,
        skip: int = 0,
        limit: int = 100,
        search: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
        date: str | None = None,
        plan: str | None = None,
    ):
        from app.shared.pagination import paginate

        total, users = await self.repository.get_users(
            db, skip=skip, limit=limit, search=search, role=role, is_active=is_active, date=date, plan=plan
        )

        data = []
        for u in users:
            row = UserListResponse.model_validate(u)

            # Active subscription plan name (use same status list as repository)
            active_sub = next(
                (s for s in u.subscriptions if getattr(s, "status", None) in ("active", "trialing", "paid")),
                None
            )
            row.subscription_plan = active_sub.plan.name if active_sub and active_sub.plan else None

            # Counts from loaded relationships
            row.campaigns_count = len(u.campaigns) if u.campaigns else 0
            row.conversations_count = len(u.conversations) if u.conversations else 0

            # Last active: most recent session last_active_at
            if u.sessions:
                row.last_active_at = max(
                    (s.last_active_at for s in u.sessions if s.last_active_at),
                    default=None
                )

            data.append(row)

        page = (skip // limit) + 1 if limit > 0 else 1
        return paginate(data=data, total=total, page=page, limit=limit)

    async def user_stats(self, db) -> UserStatsResponse:
        stats = await self.repository.get_user_stats(db)
        return UserStatsResponse(**stats)


    async def get_user_details(self, db, user_id: str) -> UserDetailsResponse:
        user = await self.repository.get_user_details_with_stats(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        active_devices = sum(1 for s in user.sessions if s.is_active)
        inactive_devices = sum(1 for s in user.sessions if not s.is_active)
        login_count = len(user.sessions)
        subscriptions_count = len(user.subscriptions)
        meta_accounts_count = sum(1 for t in user.oauth_tokens if getattr(t, "platform", None) == AdPlatform.meta)
        ads_accounts_count = len(user.ads_accounts)
        
        active_ads_accounts = []
        for acc in user.ads_accounts:
            is_sub = acc.subscription_id is not None
            if is_sub:
                active_ads_accounts.append(
                    AdsAccountSummary(
                        id=acc.id,
                        ad_account_id=acc.ad_account_id,
                        ad_account_name=acc.ad_account_name,
                        is_subscribed=True
                    )
                )

        response = UserDetailsResponse.model_validate(user)
        response.active_devices_count = active_devices
        response.inactive_devices_count = inactive_devices
        response.login_count = login_count
        response.subscriptions_count = subscriptions_count
        response.meta_accounts_count = meta_accounts_count
        response.ads_accounts_count = ads_accounts_count
        response.active_ads_accounts = active_ads_accounts
        
        return response

    async def admin_update_role(self, db, user_id: str, payload: AdminRoleUpdateRequest) -> UserResponse:
        user = await self.repository.get_user_by_id(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        user.role = payload.role
        user = await self.repository.update_user(db, user)
        return UserResponse.model_validate(user)

    async def admin_update_status(self, db, user_id: str, payload: AdminStatusUpdateRequest) -> UserResponse:
        user = await self.repository.get_user_by_id(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        user.is_active = payload.is_active
        user = await self.repository.update_user(db, user)
        return UserResponse.model_validate(user)

    async def admin_update_verification(self, db, user_id: str, payload: AdminVerificationUpdateRequest) -> UserResponse:
        user = await self.repository.get_user_by_id(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        user.is_verified = payload.is_verified
        user = await self.repository.update_user(db, user)
        return UserResponse.model_validate(user)

    async def impersonate_user(self, db, request, user_id: str, admin_user) -> ImpersonateResponse:
        user = await self.repository.get_user_by_id(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Security: Prevent self-impersonation
        if str(user.id) == str(admin_user.id):
            raise HTTPException(status_code=400, detail="Cannot impersonate yourself")

        # Security: Prevent impersonating deactivated or suspended users
        if not user.is_active:
            raise HTTPException(status_code=400, detail="Cannot impersonate a deactivated or suspended user")

        # Security: Prevent regular admins from impersonating other admins or super_admin
        if user.role in (UserRole.admin, UserRole.super_admin) and admin_user.role != UserRole.super_admin:
            raise HTTPException(status_code=403, detail="Cannot impersonate administrative accounts")

        # Security: Super admin accounts cannot be impersonated
        if user.role == UserRole.super_admin:
            raise HTTPException(status_code=403, detail="Cannot impersonate a super administrator")

        # Create a new session for the impersonated user
        client_host = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "Unknown")
        
        session = UserSession(
            user_id=user.id,
            device_name=f"Impersonated by {admin_user.email if admin_user else 'Admin'}",
            device_type="System",
            browser="Unknown",
            operating_system="Unknown",
            ip_address=client_host
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        
        access_token = create_access_token(
            user_id=str(user.id),
            email=user.email,
            role=user.role.value if hasattr(user.role, 'value') else user.role,
            session_id=str(session.id),
            impersonator_id=str(admin_user.id) if admin_user else "admin"
        )
        refresh_token = create_refresh_token(
            user_id=str(user.id),
            session_id=str(session.id),
            impersonator_id=str(admin_user.id) if admin_user else "admin"
        )
        
        session.refresh_token_hash = hash_password(refresh_token)
        await db.commit()

        # Audit log creation for starting impersonation
        try:
            await AuditLogRepository().create_audit_logs(
                db,
                AuditLogRequest(
                    user_id=str(admin_user.id),
                    action="user.impersonation.started",
                    resource_type="user",
                    resource_id=str(user.id),
                    new_data={
                        "admin_email": admin_user.email,
                        "target_email": user.email,
                        "target_user_id": str(user.id),
                        "session_id": str(session.id),
                    },
                    ip_address=client_host,
                    user_agent=user_agent[:500] if user_agent else None
                )
            )
        except Exception:
            pass
        
        return ImpersonateResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=UserResponse.model_validate(user)
        )

    async def stop_impersonation(self, db, request, current_user) -> StopImpersonationResponse:
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing authorization header")
        token = auth_header[7:].strip()
        payload = decode_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid token")

        impersonator_id = payload.get("impersonator_id")
        session_id = payload.get("session_id")
        if not impersonator_id:
            raise HTTPException(status_code=400, detail="Current session is not an impersonated session")

        # Deactivate the impersonation session in DB
        if session_id:
            res = await db.execute(select(UserSession).where(UserSession.id == session_id))
            session = res.scalar_one_or_none()
            if session:
                session.is_active = False
                session.revoked_at = datetime.now(timezone.utc)
                db.add(session)
                await db.commit()

        client_host = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "Unknown")

        # Audit log creation for stopping impersonation
        try:
            await AuditLogRepository().create_audit_logs(
                db,
                AuditLogRequest(
                    user_id=str(impersonator_id),
                    action="user.impersonation.stopped",
                    resource_type="user",
                    resource_id=str(current_user.id),
                    new_data={
                        "target_email": current_user.email,
                        "target_user_id": str(current_user.id),
                        "session_id": str(session_id) if session_id else None,
                    },
                    ip_address=client_host,
                    user_agent=user_agent[:500] if user_agent else None
                )
            )
        except Exception:
            pass

        return StopImpersonationResponse(
            message="Impersonation session ended successfully",
            admin_id=str(impersonator_id),
            target_user_id=str(current_user.id)
        )

