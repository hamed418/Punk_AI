from typing import Optional, Tuple, List, Union
from uuid import UUID
from datetime import datetime
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload

from app.modules.coupon.models import Coupons, CouponRedemptions
from app.modules.coupon.schemas import DiscountType, CouponStatus


class CouponRepository:

    async def admin_get_all_coupons(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 20,
        status: Optional[Union[CouponStatus, bool]] = None,
        discount_type: Optional[DiscountType] = None,
        valid_from: Optional[datetime] = None,
        valid_till: Optional[datetime] = None,
        created_by: Optional[UUID] = None,
        search: Optional[str] = None,
    ) -> Tuple[int, List[Coupons]]:
        query = select(Coupons)
        count_query = select(func.count(Coupons.id))

        if status is not None:
            if isinstance(status, bool):
                is_active = status
            elif status == CouponStatus.ACTIVE:
                is_active = True
            elif status == CouponStatus.INACTIVE:
                is_active = False
            else:
                is_active = None

            if is_active is not None:
                query = query.where(Coupons.is_active == is_active)
                count_query = count_query.where(Coupons.is_active == is_active)

        if discount_type is not None:
            query = query.where(Coupons.discount_type == discount_type)
            count_query = count_query.where(Coupons.discount_type == discount_type)

        if valid_from is not None:
            query = query.where(Coupons.valid_from >= valid_from)
            count_query = count_query.where(Coupons.valid_from >= valid_from)

        if valid_till is not None:
            query = query.where(Coupons.valid_till <= valid_till)
            count_query = count_query.where(Coupons.valid_till <= valid_till)

        if created_by is not None:
            query = query.where(Coupons.created_by == created_by)
            count_query = count_query.where(Coupons.created_by == created_by)

        if search:
            search_pattern = f"%{search.strip().lower()}%"
            query = query.where(func.lower(Coupons.code).like(search_pattern))
            count_query = count_query.where(func.lower(Coupons.code).like(search_pattern))

        total_coupons_res = await db.execute(count_query)
        total_coupons = total_coupons_res.scalar() or 0

        query = (
            query.options(selectinload(Coupons.redemptions))
            .order_by(desc(Coupons.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(query)
        coupons = result.scalars().all()

        return total_coupons, list(coupons)

    async def admin_get_coupon_by_id(self, db: AsyncSession, coupon_id: UUID) -> Optional[Coupons]:
        query = select(Coupons).options(selectinload(Coupons.redemptions)).where(Coupons.id == coupon_id)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    # Aliases
    get_coupon_by_id = admin_get_coupon_by_id
    get_by_id = admin_get_coupon_by_id

    async def admin_get_by_coupon_code(self, db: AsyncSession, coupon_code: str) -> Optional[Coupons]:
        query = select(Coupons).where(func.lower(Coupons.code) == coupon_code.strip().lower())
        result = await db.execute(query)
        return result.scalar_one_or_none()

    # Aliases
    get_by_code = admin_get_by_coupon_code
    get_coupon_by_code = admin_get_by_coupon_code

    async def admin_create_coupon(self, db: AsyncSession, coupon: Coupons) -> Coupons:
        db.add(coupon)
        await db.commit()
        await db.refresh(coupon)
        return coupon

    create_coupon = admin_create_coupon

    async def admin_delete_coupon(self, db: AsyncSession, coupon_id: UUID) -> bool:
        coupon = await self.admin_get_coupon_by_id(db, coupon_id)
        if not coupon:
            return False
        await db.delete(coupon)
        await db.commit()
        return True

    delete_coupon = admin_delete_coupon

    async def admin_update_coupon(self, db: AsyncSession, coupon: Coupons) -> Coupons:
        db.add(coupon)
        await db.commit()
        await db.refresh(coupon)
        return coupon

    update_coupon = admin_update_coupon

    async def admin_get_redemptions(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 20,
        user_id: Optional[UUID] = None,
        coupon_id: Optional[UUID] = None,
    ) -> Tuple[int, List[CouponRedemptions]]:
        query = select(CouponRedemptions)
        count_query = select(func.count(CouponRedemptions.id))

        if user_id is not None:
            query = query.where(CouponRedemptions.user_id == user_id)
            count_query = count_query.where(CouponRedemptions.user_id == user_id)

        if coupon_id is not None:
            query = query.where(CouponRedemptions.coupon_id == coupon_id)
            count_query = count_query.where(CouponRedemptions.coupon_id == coupon_id)

        total_redemptions_res = await db.execute(count_query)
        total_redemptions = total_redemptions_res.scalar() or 0

        query = query.order_by(desc(CouponRedemptions.redeemed_at)).offset(skip).limit(limit)
        result = await db.execute(query)
        redemptions = result.scalars().all()

        return total_redemptions, list(redemptions)

    async def user_make_redemption(self, db: AsyncSession, redemption: CouponRedemptions) -> CouponRedemptions:
        db.add(redemption)
        await db.commit()
        await db.refresh(redemption)
        return redemption

    create_redemption = user_make_redemption

    async def get_user_redemptions(
        self,
        db: AsyncSession,
        user_id: UUID,
        skip: int = 0,
        limit: int = 20,
    ) -> Tuple[int, List[CouponRedemptions]]:
        query = select(CouponRedemptions).where(CouponRedemptions.user_id == user_id)
        count_query = select(func.count(CouponRedemptions.id)).where(CouponRedemptions.user_id == user_id)

        total_redemptions_res = await db.execute(count_query)
        total_redemptions = total_redemptions_res.scalar() or 0

        query = query.order_by(desc(CouponRedemptions.redeemed_at)).offset(skip).limit(limit)
        result = await db.execute(query)
        redemptions = result.scalars().all()

        return total_redemptions, list(redemptions)

    async def get_user_coupon_redemptions_count(
        self,
        db: AsyncSession,
        user_id: UUID,
        coupon_id: UUID,
    ) -> int:
        query = (
            select(func.count(CouponRedemptions.id))
            .where(
                CouponRedemptions.user_id == user_id,
                CouponRedemptions.coupon_id == coupon_id,
            )
        )
        res = await db.execute(query)
        return res.scalar() or 0

    async def get_user_total_redemptions_count(
        self,
        db: AsyncSession,
        user_id: UUID,
    ) -> int:
        query = (
            select(func.count(CouponRedemptions.id))
            .where(CouponRedemptions.user_id == user_id)
        )
        res = await db.execute(query)
        return res.scalar() or 0