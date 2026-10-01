from datetime import datetime
from typing import Optional, Union
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Path, Body, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_current_user, get_admin_user
from app.shared.pagination import PaginatedResponse
from app.modules.user.models import User
from .repository import CouponRepository
from .service import CouponService
from .schemas import (
    CreateCoupon,
    UpdateCoupon,
    CouponDetailResponse,
    CouponRedemptionResponse,
    CouponValidateRequest,
    CouponValidateResponse,
    RedeemRequest,
    RedeemResponse,
    CouponDeleteResponse,
    CouponRevertResponse,
    DiscountType,
    CouponStatus,
)

router = APIRouter(prefix="/coupons", tags=["Coupon"])

repository = CouponRepository()
service = CouponService(repository)


# ── Coupon Management & Retrieval ──────────────────────────────────────────

@router.post(
    "",
    response_model=CouponDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Coupon",
    response_description="Coupon successfully created",
    responses={
        400: {"description": "Validation error (e.g. invalid date range or discount value)"},
        401: {"description": "Authentication required"},
        403: {"description": "Admin privileges required"},
        409: {"description": "Coupon code already exists"},
    },
)
async def admin_create_coupon(
    payload: CreateCoupon,
    current_admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new promotional or discount coupon.

    **Permissions**: Requires Admin or Super Admin role.

    - **code**: Unique alphanumeric promo code (case-insensitive, stored uppercase).
    - **discount_type**: `percentage`, `fixed_amount`, or `full_free`.
    - **discount_value**: Required if percentage (0-100) or fixed amount (>0).
    - **currency**: 3-letter currency code (default: USD).
    - **max_discount_amount**: Cap on total discount (applicable for percentage discounts).
    - **max_uses**: Total global redemption limit (optional).
    - **usage_limit_per_user**: Maximum times a single user can redeem (default: 1).
    - **valid_from** / **valid_till**: Optional datetime validity window.
    - **new_users_only**: When true, only users with no prior subscriptions or payments can redeem.
    """
    return await service.create_coupon(db, current_admin, payload)


@router.get(
    "",
    response_model=PaginatedResponse[CouponDetailResponse],
    status_code=status.HTTP_200_OK,
    summary="List All Coupons",
    response_description="Paginated list of coupons",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Admin privileges required"},
    },
)
async def admin_get_all_coupons(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(20, ge=1, le=100, description="Items per page (1-100)"),
    status_filter: Optional[Union[CouponStatus, bool]] = Query(
        None,
        alias="status",
        description="Filter by coupon status: 'active', 'inactive', 'revoked', or boolean true/false",
    ),
    discount_type: Optional[DiscountType] = Query(None, description="Filter by discount type"),
    valid_from: Optional[datetime] = Query(None, description="Filter coupons valid on or after this UTC datetime"),
    valid_till: Optional[datetime] = Query(None, description="Filter coupons valid on or before this UTC datetime"),
    created_by: Optional[UUID] = Query(None, description="Filter by creator admin user UUID"),
    search: Optional[str] = Query(None, description="Search term matching coupon code or description"),
    current_admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve all coupons with optional filtering, search, and pagination.

    **Permissions**: Requires Admin or Super Admin role.
    """
    skip = (page - 1) * limit
    return await service.get_all_coupons(
        db=db,
        user=current_admin,
        skip=skip,
        limit=limit,
        status_filter=status_filter,
        discount_type=discount_type,
        valid_from=valid_from,
        valid_till=valid_till,
        created_by=created_by,
        search=search,
    )


# ── Customer Validation & Redemption ───────────────────────────────────────

@router.post(
    "/validate",
    response_model=CouponValidateResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate Coupon Code",
    response_description="Coupon validation outcome and computed discount breakdown",
    responses={
        401: {"description": "Authentication required"},
    },
)
async def validate_coupon(
    payload: CouponValidateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Validate a coupon code and calculate the discount preview for an order amount without redeeming it.

    **Permissions**: Authenticated user.

    Returns whether the coupon is valid for this user and order amount, along with the computed
    `discount_amount` and `final_amount`. If invalid, returns `is_valid: false` with a clear explanation message.
    """
    return await service.validate_coupon(db, current_user, payload)


@router.post(
    "/redeem",
    response_model=RedeemResponse,
    status_code=status.HTTP_200_OK,
    summary="Redeem Coupon Code",
    response_description="Redemption confirmation and discount details",
    responses={
        400: {"description": "Coupon is invalid, expired, exhausted, or user exceeded limit"},
        401: {"description": "Authentication required"},
        404: {"description": "Coupon code not found"},
    },
)
async def redeem_coupon(
    payload: RedeemRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Redeem and apply a coupon code against a purchase or checkout.

    **Permissions**: Authenticated user.

    Records the redemption, increments the coupon's usage count, checks per-user and global usage limits,
    and returns the discount details along with the unique `redemption_id`.
    """
    return await service.redeem_coupon(db, current_user, payload)


@router.get(
    "/user/my-redemptions",
    response_model=PaginatedResponse[CouponRedemptionResponse],
    status_code=status.HTTP_200_OK,
    summary="Get My Redemptions History",
    response_description="Paginated list of user's personal coupon redemptions",
    responses={
        401: {"description": "Authentication required"},
    },
)
async def get_my_redemptions(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(20, ge=1, le=100, description="Items per page (1-100)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve the coupon redemption history for the currently logged-in user.

    **Permissions**: Authenticated user.
    """
    skip = (page - 1) * limit
    return await service.get_my_redemptions(db, current_user, skip, limit)


# ── Admin Redemptions Tracking & Audit ─────────────────────────────────────

@router.get(
    "/redemptions",
    response_model=PaginatedResponse[CouponRedemptionResponse],
    status_code=status.HTTP_200_OK,
    summary="List All Redemptions",
    response_description="Paginated list of all coupon redemptions across all users",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Admin privileges required"},
    },
)
async def admin_get_all_redemptions(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(20, ge=1, le=100, description="Items per page (1-100)"),
    user_id: Optional[UUID] = Query(None, description="Filter redemptions by user UUID"),
    coupon_id: Optional[UUID] = Query(None, description="Filter redemptions by coupon UUID"),
    current_admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve an audit log of all coupon redemptions across all users.

    **Permissions**: Requires Admin or Super Admin role.
    """
    skip = (page - 1) * limit
    return await service.get_all_redemptions(
        db=db,
        user=current_admin,
        skip=skip,
        limit=limit,
        user_id=user_id,
        coupon_id=coupon_id,
    )


@router.post(
    "/redemptions/{redemption_id}/revert",
    response_model=CouponRevertResponse,
    status_code=status.HTTP_200_OK,
    summary="Revert Coupon Redemption",
    response_description="Redemption successfully reverted and coupon usage count decremented",
    responses={
        400: {"description": "Redemption has already been reverted"},
        401: {"description": "Authentication required"},
        403: {"description": "Admin privileges required"},
        404: {"description": "Redemption ID not found"},
    },
)
async def admin_revert_redemption(
    redemption_id: UUID = Path(..., description="UUID of the redemption record to revert"),
    current_admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Revert a previously processed coupon redemption.

    **Permissions**: Requires Admin or Super Admin role.

    Marks the redemption record status as `reverted`, records `reverted_at`, decrements
    the coupon's `current_uses` counter, and re-activates the coupon if it was deactivated due to max uses.
    """
    return await service.revert_redemption(db, redemption_id, current_admin)


# ── Coupon Detail, Update, & Deletion ───────────────────────────────────────

@router.get(
    "/{coupon_id}",
    response_model=CouponDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Coupon by ID",
    response_description="Detailed coupon information",
    responses={
        401: {"description": "Authentication required"},
        404: {"description": "Coupon not found"},
    },
)
async def admin_get_coupon(
    coupon_id: UUID = Path(..., description="UUID of the coupon to retrieve"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve full configuration and status details of a coupon by its unique ID.

    **Permissions**: Authenticated user.
    """
    return await service.get_coupon_by_id(db, coupon_id, current_user)


@router.put(
    "/{coupon_id}",
    response_model=CouponDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Coupon",
    response_description="Updated coupon details",
    responses={
        400: {"description": "Validation error in updated parameters"},
        401: {"description": "Authentication required"},
        403: {"description": "Admin privileges required"},
        404: {"description": "Coupon not found"},
    },
)
async def admin_update_coupon(
    payload: UpdateCoupon,
    coupon_id: UUID = Path(..., description="UUID of the coupon to update"),
    current_admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update parameters of an existing coupon (description, limits, dates, status, discount amount).

    **Permissions**: Requires Admin or Super Admin role.
    """
    return await service.update_coupon(db, coupon_id, current_admin, payload)


@router.delete(
    "/{coupon_id}",
    response_model=CouponDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete Coupon",
    response_description="Confirmation of coupon deletion",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Admin privileges required"},
        404: {"description": "Coupon not found"},
    },
)
async def admin_delete_coupon(
    coupon_id: UUID = Path(..., description="UUID of the coupon to delete"),
    current_admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Permanently delete a coupon by its unique ID.

    **Permissions**: Requires Admin or Super Admin role.
    """
    return await service.delete_coupon(db, coupon_id, current_admin)