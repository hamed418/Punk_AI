from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List, Tuple, Union
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy import select

from app.modules.user.models import User
from app.shared.enums import UserRole
from app.shared.pagination import paginate, PaginatedResponse
from app.modules.coupon.models import Coupons, CouponRedemptions
from app.modules.coupon.repository import CouponRepository
from app.modules.coupon.schemas import (
    CreateCoupon,
    UpdateCoupon,
    CouponDetailResponse,
    CouponRedemptionResponse,
    CouponValidateRequest,
    CouponValidateResponse,
    RedeemRequest,
    RedeemResponse,
    DiscountType,
    RedemptionStatus,
    CouponStatus,
)


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Helper to ensure datetime is timezone-aware in UTC for safe comparisons."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class CouponService:

    def __init__(self, coupon_repository: Optional[CouponRepository] = None):
        self.coupon_repository = coupon_repository or CouponRepository()
        self.repository = self.coupon_repository

    def _check_admin(self, user: User) -> None:
        user_role = getattr(user, "role", None)
        if user_role not in [UserRole.admin, UserRole.super_admin, "admin", "super_admin"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin privileges are required to perform this action.",
            )

    # ---------------------------------------------------------
    # Admin Coupon Management: Create, Read, Update, Delete
    # ---------------------------------------------------------

    async def create_coupon(
        self,
        db: AsyncSession,
        user: User,
        payload: CreateCoupon,
    ) -> CouponDetailResponse:
        self._check_admin(user)

        code_clean = payload.code.strip().upper()
        if not code_clean:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Coupon code cannot be empty.",
            )

        # Ensure coupon code uniqueness
        existing = await self.coupon_repository.admin_get_by_coupon_code(db, code_clean)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A coupon with code '{code_clean}' already exists.",
            )

        # Validate discount rules
        if payload.discount_type in (DiscountType.PERCENTAGE, DiscountType.PERCENT):
            if payload.discount_value is None or payload.discount_value <= 0 or payload.discount_value > 100:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Percentage discount must be greater than 0 and less than or equal to 100.",
                )
        elif payload.discount_type == DiscountType.FIXED_AMOUNT:
            if payload.discount_value is None or payload.discount_value <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Fixed amount discount must be greater than 0.",
                )
        elif payload.discount_type == DiscountType.FULL_FREE:
            # Full free coupons cover 100% discount
            pass

        # Validate date ranges
        valid_from = payload.valid_from or datetime.now(timezone.utc)
        valid_till = payload.valid_till
        if valid_till is not None and _ensure_utc(valid_till) < _ensure_utc(valid_from):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The expiration date (valid_till) cannot be earlier than valid_from.",
            )

        coupon = Coupons(
            code=code_clean,
            description=payload.description,
            discount_type=payload.discount_type,
            discount_value=Decimal(str(payload.discount_value)) if payload.discount_value is not None else None,
            currency=payload.currency.upper() if payload.currency else "USD",
            max_discount_amount=Decimal(str(payload.max_discount_amount)) if payload.max_discount_amount is not None else None,
            max_uses=payload.max_uses,
            usage_limit_per_user=payload.usage_limit_per_user or 1,
            current_uses=0,
            is_active=payload.is_active,
            valid_from=valid_from,
            valid_till=valid_till,
            new_users_only=payload.new_users_only,
            created_by=user.id,
        )

        saved = await self.coupon_repository.admin_create_coupon(db, coupon)
        return CouponDetailResponse.model_validate(saved)

    async def update_coupon(
        self,
        db: AsyncSession,
        coupon_id: UUID,
        user: User,
        payload: UpdateCoupon,
    ) -> CouponDetailResponse:
        self._check_admin(user)

        coupon = await self.coupon_repository.admin_get_coupon_by_id(db, coupon_id)
        if not coupon:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Coupon with id '{coupon_id}' was not found.",
            )

        update_data = payload.model_dump(exclude_unset=True)

        # Check code uniqueness if updated
        if "code" in update_data and update_data["code"]:
            new_code = update_data["code"].strip().upper()
            if new_code != coupon.code:
                existing = await self.coupon_repository.admin_get_by_coupon_code(db, new_code)
                if existing and existing.id != coupon.id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"A coupon with code '{new_code}' already exists.",
                    )
                coupon.code = new_code

        # Discount type and value validation
        new_discount_type = update_data.get("discount_type", coupon.discount_type)
        new_discount_value = update_data.get("discount_value", coupon.discount_value)

        if new_discount_type in (DiscountType.PERCENTAGE, DiscountType.PERCENT):
            if new_discount_value is None or float(new_discount_value) <= 0 or float(new_discount_value) > 100:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Percentage discount must be between 1 and 100.",
                )
        elif new_discount_type == DiscountType.FIXED_AMOUNT:
            if new_discount_value is None or float(new_discount_value) <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Fixed amount discount must be greater than 0.",
                )

        # Date range validation
        new_valid_from = update_data.get("valid_from", coupon.valid_from)
        new_valid_till = update_data.get("valid_till", coupon.valid_till)
        if new_valid_till is not None and new_valid_from is not None:
            if _ensure_utc(new_valid_till) < _ensure_utc(new_valid_from):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="The expiration date (valid_till) cannot be earlier than valid_from.",
                )

        # Apply updates
        for field, value in update_data.items():
            if field == "code":
                continue
            if field in ("discount_value", "max_discount_amount") and value is not None:
                setattr(coupon, field, Decimal(str(value)))
            elif field == "currency" and value:
                setattr(coupon, field, str(value).upper())
            else:
                setattr(coupon, field, value)

        updated = await self.coupon_repository.admin_update_coupon(db, coupon)
        return CouponDetailResponse.model_validate(updated)

    async def delete_coupon(
        self,
        db: AsyncSession,
        coupon_id: UUID,
        user: User,
    ) -> dict:
        self._check_admin(user)

        coupon = await self.coupon_repository.admin_get_coupon_by_id(db, coupon_id)
        if not coupon:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Coupon with id '{coupon_id}' was not found.",
            )

        success = await self.coupon_repository.admin_delete_coupon(db, coupon_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete coupon.",
            )

        return {"success": True, "message": f"Coupon '{coupon.code}' deleted successfully."}

    async def get_coupon_by_id(
        self,
        db: AsyncSession,
        coupon_id: UUID,
        user: User,
    ) -> CouponDetailResponse:
        coupon = await self.coupon_repository.admin_get_coupon_by_id(db, coupon_id)
        if not coupon:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Coupon with id '{coupon_id}' was not found.",
            )
        return CouponDetailResponse.model_validate(coupon)

    async def get_all_coupons(
        self,
        db: AsyncSession,
        user: User,
        skip: int = 0,
        limit: int = 20,
        status_filter: Optional[Union[CouponStatus, bool]] = None,
        discount_type: Optional[DiscountType] = None,
        valid_from: Optional[datetime] = None,
        valid_till: Optional[datetime] = None,
        created_by: Optional[UUID] = None,
        search: Optional[str] = None,
    ) -> PaginatedResponse[CouponDetailResponse]:
        self._check_admin(user)

        total, coupons = await self.coupon_repository.admin_get_all_coupons(
            db=db,
            skip=skip,
            limit=limit,
            status=status_filter,
            discount_type=discount_type,
            valid_from=valid_from,
            valid_till=valid_till,
            created_by=created_by,
            search=search,
        )

        data = [CouponDetailResponse.model_validate(c) for c in coupons]
        page = (skip // limit) + 1 if limit > 0 else 1
        return paginate(data=data, total=total, page=page, limit=limit)

    # ---------------------------------------------------------
    # Admin Redemption Tracking
    # ---------------------------------------------------------

    async def get_all_redemptions(
        self,
        db: AsyncSession,
        user: User,
        skip: int = 0,
        limit: int = 20,
        user_id: Optional[UUID] = None,
        coupon_id: Optional[UUID] = None,
    ) -> PaginatedResponse[CouponRedemptionResponse]:
        self._check_admin(user)

        total, redemptions = await self.coupon_repository.admin_get_redemptions(
            db=db,
            skip=skip,
            limit=limit,
            user_id=user_id,
            coupon_id=coupon_id,
        )

        data = [CouponRedemptionResponse.model_validate(r) for r in redemptions]
        page = (skip // limit) + 1 if limit > 0 else 1
        return paginate(data=data, total=total, page=page, limit=limit)

    async def revert_redemption(
        self,
        db: AsyncSession,
        redemption_id: UUID,
        user: User,
    ) -> dict:
        self._check_admin(user)

        # Query redemption directly
        res = await db.execute(select(CouponRedemptions).where(CouponRedemptions.id == redemption_id))
        redemption = res.scalar_one_or_none()
        if not redemption:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Redemption '{redemption_id}' was not found.",
            )

        if redemption.status == RedemptionStatus.REVERTED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This redemption has already been reverted.",
            )

        redemption.status = RedemptionStatus.REVERTED
        redemption.reverted_at = datetime.now(timezone.utc)

        # Decrement current_uses on coupon
        coupon = await self.coupon_repository.admin_get_coupon_by_id(db, redemption.coupon_id)
        if coupon and coupon.current_uses > 0:
            coupon.current_uses -= 1
            if not coupon.is_active:
                # Re-activate coupon if it was only deactivated due to max_uses
                coupon.is_active = True
            await self.coupon_repository.admin_update_coupon(db, coupon)

        db.add(redemption)
        await db.commit()
        await db.refresh(redemption)

        return {
            "success": True,
            "message": f"Redemption '{redemption_id}' was successfully reverted.",
            "redemption": CouponRedemptionResponse.model_validate(redemption),
        }

    # ---------------------------------------------------------
    # User Coupon Validation & Redemption
    # ---------------------------------------------------------

    def calculate_discount(
        self,
        coupon: Coupons,
        original_amount: float,
    ) -> Tuple[float, float]:
        """Calculates (discount_amount, final_amount) based on coupon terms."""
        if original_amount <= 0:
            return 0.0, 0.0

        orig = Decimal(str(original_amount))
        discount = Decimal("0.0")

        if coupon.discount_type == DiscountType.FULL_FREE:
            discount = orig
        elif coupon.discount_type in (DiscountType.PERCENTAGE, DiscountType.PERCENT):
            pct = Decimal(str(coupon.discount_value or 0))
            discount = (orig * pct) / Decimal("100")
            if coupon.max_discount_amount is not None and coupon.max_discount_amount > 0:
                discount = min(discount, Decimal(str(coupon.max_discount_amount)))
        elif coupon.discount_type == DiscountType.FIXED_AMOUNT:
            val = Decimal(str(coupon.discount_value or 0))
            discount = min(val, orig)

        # Cap discount so it cannot exceed original amount
        discount = min(discount, orig)
        final_amt = max(Decimal("0.0"), orig - discount)

        return float(round(discount, 2)), float(round(final_amt, 2))

    async def _validate_coupon_eligibility(
        self,
        db: AsyncSession,
        coupon: Coupons,
        user: User,
        original_amount: float,
    ) -> None:
        """Runs all business validation checks on coupon usability for a user."""
        if not coupon.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This coupon is inactive or has been disabled.",
            )

        now = datetime.now(timezone.utc)

        # Check start date
        if coupon.valid_from and _ensure_utc(coupon.valid_from) > now:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This coupon is not active yet.",
            )

        # Check expiration date
        if coupon.valid_till and _ensure_utc(coupon.valid_till) < now:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This coupon has expired.",
            )

        # Check global usage limit
        if coupon.max_uses is not None and coupon.current_uses >= coupon.max_uses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This coupon has reached its maximum total redemptions limit.",
            )

        # Check user-specific usage limit
        if coupon.usage_limit_per_user is not None and coupon.usage_limit_per_user > 0:
            user_redemptions_count = await self.coupon_repository.get_user_coupon_redemptions_count(
                db, user.id, coupon.id
            )
            if user_redemptions_count >= coupon.usage_limit_per_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"You have reached the maximum redemption limit ({coupon.usage_limit_per_user}) for this coupon.",
                )

        # Check new users only requirement
        if coupon.new_users_only:
            total_user_redemptions = await self.coupon_repository.get_user_total_redemptions_count(
                db, user.id
            )
            if total_user_redemptions > 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="This coupon is only valid for new users who have not redeemed any coupons before.",
                )

    async def validate_coupon(
        self,
        db: AsyncSession,
        user: User,
        payload: CouponValidateRequest,
    ) -> CouponValidateResponse:
        code_clean = payload.code.strip().upper()
        if not code_clean:
            return CouponValidateResponse(
                is_valid=False,
                message="Coupon code cannot be empty.",
                code=payload.code,
                original_amount=payload.original_amount,
                discount_amount=0.0,
                final_amount=payload.original_amount,
            )

        coupon = await self.coupon_repository.admin_get_by_coupon_code(db, code_clean)
        if not coupon:
            return CouponValidateResponse(
                is_valid=False,
                message=f"Coupon code '{code_clean}' not found.",
                code=code_clean,
                original_amount=payload.original_amount,
                discount_amount=0.0,
                final_amount=payload.original_amount,
            )

        try:
            await self._validate_coupon_eligibility(db, coupon, user, payload.original_amount)
        except HTTPException as exc:
            return CouponValidateResponse(
                is_valid=False,
                message=exc.detail,
                coupon_id=coupon.id,
                code=coupon.code,
                discount_type=coupon.discount_type,
                discount_value=float(coupon.discount_value) if coupon.discount_value is not None else None,
                original_amount=payload.original_amount,
                discount_amount=0.0,
                final_amount=payload.original_amount,
            )

        discount_amount, final_amount = self.calculate_discount(coupon, payload.original_amount)

        return CouponValidateResponse(
            is_valid=True,
            message="Coupon is valid and applicable.",
            coupon_id=coupon.id,
            code=coupon.code,
            discount_type=coupon.discount_type,
            discount_value=float(coupon.discount_value) if coupon.discount_value is not None else None,
            original_amount=payload.original_amount,
            discount_amount=discount_amount,
            final_amount=final_amount,
        )

    async def redeem_coupon(
        self,
        db: AsyncSession,
        user: User,
        payload: RedeemRequest,
    ) -> RedeemResponse:
        code_clean = payload.code.strip().upper()
        if not code_clean:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Coupon code cannot be empty.",
            )

        coupon = await self.coupon_repository.admin_get_by_coupon_code(db, code_clean)
        if not coupon:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Coupon with code '{code_clean}' was not found.",
            )

        # Validate eligibility (raises HTTPException if ineligible)
        await self._validate_coupon_eligibility(db, coupon, user, payload.original_amount)

        # Calculate discount
        discount_amount, final_amount = self.calculate_discount(coupon, payload.original_amount)

        user_email = payload.email or getattr(user, "email", None)

        # Create redemption record
        redemption = CouponRedemptions(
            coupon_id=coupon.id,
            user_id=user.id,
            email=user_email,
            original_amount=Decimal(str(payload.original_amount)),
            discounted_amount=Decimal(str(discount_amount)),
            final_amount=Decimal(str(final_amount)),
            status=RedemptionStatus.APPLIED,
            redeemed_at=datetime.now(timezone.utc),
        )

        saved_redemption = await self.coupon_repository.user_make_redemption(db, redemption)

        # Increment uses on coupon
        coupon.current_uses += 1
        if coupon.max_uses is not None and coupon.current_uses >= coupon.max_uses:
            coupon.is_active = False

        await self.coupon_repository.admin_update_coupon(db, coupon)

        return RedeemResponse(
            success=True,
            message=f"Coupon '{coupon.code}' successfully redeemed! You saved {coupon.currency} {discount_amount:.2f}.",
            coupon_code=coupon.code,
            original_amount=payload.original_amount,
            discounted_amount=discount_amount,
            final_amount=final_amount,
            redemption_id=saved_redemption.id,
            redeemed_at=saved_redemption.redeemed_at,
        )

    async def get_my_redemptions(
        self,
        db: AsyncSession,
        user: User,
        skip: int = 0,
        limit: int = 20,
    ) -> PaginatedResponse[CouponRedemptionResponse]:
        total, redemptions = await self.coupon_repository.get_user_redemptions(
            db=db,
            user_id=user.id,
            skip=skip,
            limit=limit,
        )

        data = [CouponRedemptionResponse.model_validate(r) for r in redemptions]
        page = (skip // limit) + 1 if limit > 0 else 1
        return paginate(data=data, total=total, page=page, limit=limit)