from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Path, Body, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_db, get_current_user, get_admin_user
from app.shared.pagination import PaginatedResponse
from app.modules.user.models import User
from .repository import RedeemRepository
from .service import RedeemService
from .schemas import (
    RedeemCodesCreate,
    RedeemCodesUpdate,
    RedeemCodesResponse,
    RedeemCodeDetailResponse,
    RedeemCodeRedemptionResponse,
    RedeemUseRequest,
    RedeemUseResponse,
)

router = APIRouter(prefix="/redeem", tags=["Redeem"])

repository = RedeemRepository()
service = RedeemService(repository)


# ── User APIs ───────────────────────────────────────────────────────────────

@router.post("/create", response_model=RedeemCodesResponse, status_code=status.HTTP_201_CREATED)
async def create_redeem_code(
    payload: Optional[RedeemCodesCreate] = Body(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Authenticated user creates a new redeem code."""
    return await service.create_redeem_code(db, current_user, payload)


@router.post("/use", response_model=RedeemUseResponse)
async def use_redeem_code(
    payload: RedeemUseRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Authenticated user uses/claims a redeem code."""
    return await service.use_redeem_code(db, current_user, payload)


@router.get("/my-codes", response_model=PaginatedResponse[RedeemCodesResponse])
async def get_my_redeem_codes(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    is_active: Optional[bool] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List redeem codes created by the current user."""
    skip = (page - 1) * limit
    return await service.get_my_codes(db, current_user.id, skip, limit, is_active=is_active)


@router.get("/my-redemptions", response_model=PaginatedResponse[RedeemCodeRedemptionResponse])
async def get_my_redemptions(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List codes redeemed by the current user."""
    skip = (page - 1) * limit
    return await service.get_my_redemptions(db, current_user.id, skip, limit)


@router.get("/{code_id}", response_model=RedeemCodeDetailResponse)
async def get_redeem_code(
    code_id: UUID = Path(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get details of a specific redeem code (admin only)."""
    return await service.get_code_by_id(db, code_id, current_user)


@router.patch("/{code_id}", response_model=RedeemCodesResponse)
async def update_redeem_code(
    code_id: UUID = Path(...),
    payload: RedeemCodesUpdate = ...,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a redeem code"""
    return await service.update_code(db, code_id, current_user, payload)


@router.delete("/{code_id}")
async def delete_redeem_code(
    code_id: UUID = Path(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a redeem code"""
    return await service.delete_code(db, code_id, current_user)


# ── Admin APIs ──────────────────────────────────────────────────────────────

@router.get("/admin/all", response_model=PaginatedResponse[RedeemCodesResponse])
async def admin_get_all_redeem_codes(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin: List all redeem codes in the system."""
    skip = (page - 1) * limit
    return await service.get_all_codes_admin(db, skip, limit, search=search, is_active=is_active)
