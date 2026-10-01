import secrets
import string
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.user.models import User
from app.shared.enums import UserRole
from app.shared.pagination import paginate, PaginatedResponse
from .repository import RedeemRepository
from .schemas import (
    RedeemCodesCreate,
    RedeemCodesUpdate,
    RedeemCodesResponse,
    RedeemCodeDetailResponse,
    RedeemCodeRedemptionResponse,
    RedeemUseRequest,
    RedeemUseResponse,
)


def generate_unique_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class RedeemService:
    def __init__(self, repository: RedeemRepository):
        self.repository = repository

    async def create_redeem_code(
        self,
        db: AsyncSession,
        user: User,
        payload: Optional[RedeemCodesCreate] = None
    ) -> RedeemCodesResponse:
        if payload is None:
            payload = RedeemCodesCreate()

        # Auto-generate a unique 8-character code
        code_str = None
        for _ in range(10):
            candidate = generate_unique_code(8)
            existing = await self.repository.get_by_code(db, candidate)
            if not existing:
                code_str = candidate
                break

        if not code_str:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate a unique redeem code. Please try again."
            )

        max_redemptions = payload.max_redemptions
        if payload.is_single:
            max_redemptions = 1

        expires_at = datetime.now(timezone.utc) + timedelta(days=15)

        data = {
            "code": code_str,
            "is_active": payload.is_active,
            "is_single": payload.is_single,
            "max_redemptions": max_redemptions,
            "redemption_count": 0,
            "created_by": user.id,
            "expires_at": expires_at,
        }

        created = await self.repository.create_code(db, data)
        return RedeemCodesResponse.model_validate(created)

    async def use_redeem_code(
        self,
        db: AsyncSession,
        user: User,
        payload: RedeemUseRequest
    ) -> RedeemUseResponse:
        code_str = payload.code.strip()
        if not code_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Redeem code cannot be empty."
            )

        redeem_code = await self.repository.get_by_code(db, code_str)
        if not redeem_code:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Redeem code not found."
            )

        # Validation: Creator cannot redeem own code
        if str(redeem_code.created_by) == str(user.id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot redeem a code created by yourself."
            )

        # Validation: Is active
        if not redeem_code.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This redeem code is inactive or no longer available."
            )

        # Validation: Expiration
        if redeem_code.expires_at:
            now = datetime.now(timezone.utc)
            expires_at = redeem_code.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < now:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="This redeem code has expired."
                )

        # Validation: Duplicate redemption by same user
        existing_redemption = await self.repository.get_redemption(db, redeem_code.id, user.id)
        if existing_redemption:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You have already redeemed this code."
            )

        # Validation: Max redemptions reached
        if redeem_code.redemption_count >= redeem_code.max_redemptions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This redeem code has reached its maximum redemptions limit."
            )

        # Record redemption
        redemption_data = {
            "redeem_code_id": redeem_code.id,
            "user_id": user.id,
            "email": user.email,
        }
        redemption = await self.repository.create_redemption(db, redemption_data)

        # Update redeem code
        redeem_code.redemption_count += 1
        if redeem_code.is_single or redeem_code.redemption_count >= redeem_code.max_redemptions:
            redeem_code.is_active = False

        updated_code = await self.repository.update_code(db, redeem_code)

        return RedeemUseResponse(
            success=True,
            message=f"Redeem code '{updated_code.code}' claimed successfully!",
            redeem_code=RedeemCodesResponse.model_validate(updated_code),
            redemption=RedeemCodeRedemptionResponse.model_validate(redemption)
        )

    async def get_my_codes(
        self,
        db: AsyncSession,
        user_id: UUID | str,
        skip: int,
        limit: int,
        is_active: Optional[bool] = None
    ) -> PaginatedResponse[RedeemCodesResponse]:
        total, codes = await self.repository.get_user_codes(db, user_id, skip, limit, is_active)
        data = [RedeemCodesResponse.model_validate(c) for c in codes]
        page = (skip // limit) + 1 if limit > 0 else 1
        return paginate(data=data, total=total, page=page, limit=limit)

    async def get_my_redemptions(
        self,
        db: AsyncSession,
        user_id: UUID | str,
        skip: int,
        limit: int
    ) -> PaginatedResponse[RedeemCodeRedemptionResponse]:
        total, redemptions = await self.repository.get_user_redemptions(db, user_id, skip, limit)
        data = [RedeemCodeRedemptionResponse.model_validate(r) for r in redemptions]
        page = (skip // limit) + 1 if limit > 0 else 1
        return paginate(data=data, total=total, page=page, limit=limit)

    async def get_code_by_id(
        self,
        db: AsyncSession,
        code_id: UUID | str,
        user: User
    ) -> RedeemCodeDetailResponse:
        redeem_code = await self.repository.get_by_id(db, code_id)
        if not redeem_code:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Redeem code not found."
            )

        is_admin = getattr(user, "role", None) in [UserRole.admin, UserRole.super_admin]
        if str(redeem_code.created_by) != str(user.id) and not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to view this redeem code details."
            )

        return RedeemCodeDetailResponse.model_validate(redeem_code)

    async def update_code(
        self,
        db: AsyncSession,
        code_id: UUID | str,
        user: User,
        payload: RedeemCodesUpdate
    ) -> RedeemCodesResponse:
        redeem_code = await self.repository.get_by_id(db, code_id)
        if not redeem_code:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Redeem code not found."
            )

        is_admin = getattr(user, "role", None) in [UserRole.admin, UserRole.super_admin]
        if str(redeem_code.created_by) != str(user.id) and not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to update this redeem code."
            )

        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(redeem_code, key, value)

        updated = await self.repository.update_code(db, redeem_code)
        return RedeemCodesResponse.model_validate(updated)

    async def delete_code(
        self,
        db: AsyncSession,
        code_id: UUID | str,
        user: User
    ):
        redeem_code = await self.repository.get_by_id(db, code_id)
        if not redeem_code:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Redeem code not found."
            )

        is_admin = getattr(user, "role", None) in [UserRole.admin, UserRole.super_admin]
        if str(redeem_code.created_by) != str(user.id) and not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to delete this redeem code."
            )

        await self.repository.delete_code(db, redeem_code)
        return {"success": True, "message": "Redeem code deleted successfully."}

    async def get_all_codes_admin(
        self,
        db: AsyncSession,
        skip: int,
        limit: int,
        search: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> PaginatedResponse[RedeemCodesResponse]:
        total, codes = await self.repository.get_all_codes(db, skip, limit, search, is_active)
        data = [RedeemCodesResponse.model_validate(c) for c in codes]
        page = (skip // limit) + 1 if limit > 0 else 1
        return paginate(data=data, total=total, page=page, limit=limit)
