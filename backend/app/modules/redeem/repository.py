from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, desc
from sqlalchemy.orm import selectinload
from .models import RedeemCode, RedeemCodeRedemption


class RedeemRepository:

    async def get_by_id(self, db: AsyncSession, code_id: UUID | str) -> Optional[RedeemCode]:
        query = (
            select(RedeemCode)
            .options(selectinload(RedeemCode.redemptions))
            .where(RedeemCode.id == code_id)
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def get_by_code(self, db: AsyncSession, code: str) -> Optional[RedeemCode]:
        query = (
            select(RedeemCode)
            .options(selectinload(RedeemCode.redemptions))
            .where(func.lower(RedeemCode.code) == code.strip().lower())
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def get_user_codes(
        self,
        db: AsyncSession,
        user_id: UUID | str,
        skip: int = 0,
        limit: int = 20,
        is_active: Optional[bool] = None
    ) -> Tuple[int, List[RedeemCode]]:
        query = select(RedeemCode).where(RedeemCode.created_by == user_id)
        count_query = select(func.count(RedeemCode.id)).where(RedeemCode.created_by == user_id)

        if is_active is not None:
            query = query.where(RedeemCode.is_active == is_active)
            count_query = count_query.where(RedeemCode.is_active == is_active)

        total_res = await db.execute(count_query)
        total = total_res.scalar() or 0

        query = query.order_by(desc(RedeemCode.created_at)).offset(skip).limit(limit)
        result = await db.execute(query)
        codes = result.scalars().all()

        return total, list(codes)

    async def get_all_codes(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 20,
        search: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> Tuple[int, List[RedeemCode]]:
        query = select(RedeemCode)
        count_query = select(func.count(RedeemCode.id))

        if search:
            filter_expr = RedeemCode.code.ilike(f"%{search}%")
            query = query.where(filter_expr)
            count_query = count_query.where(filter_expr)

        if is_active is not None:
            query = query.where(RedeemCode.is_active == is_active)
            count_query = count_query.where(RedeemCode.is_active == is_active)

        total_res = await db.execute(count_query)
        total = total_res.scalar() or 0

        query = query.order_by(desc(RedeemCode.created_at)).offset(skip).limit(limit)
        result = await db.execute(query)
        codes = result.scalars().all()

        return total, list(codes)

    async def create_code(self, db: AsyncSession, data: dict) -> RedeemCode:
        redeem_code = RedeemCode(**data)
        db.add(redeem_code)
        await db.commit()
        await db.refresh(redeem_code)
        return redeem_code

    async def update_code(self, db: AsyncSession, redeem_code: RedeemCode) -> RedeemCode:
        db.add(redeem_code)
        await db.commit()
        await db.refresh(redeem_code)
        return redeem_code

    async def delete_code(self, db: AsyncSession, redeem_code: RedeemCode) -> None:
        await db.delete(redeem_code)
        await db.commit()

    async def get_redemption(
        self,
        db: AsyncSession,
        redeem_code_id: UUID | str,
        user_id: UUID | str
    ) -> Optional[RedeemCodeRedemption]:
        query = select(RedeemCodeRedemption).where(
            RedeemCodeRedemption.redeem_code_id == redeem_code_id,
            RedeemCodeRedemption.user_id == user_id
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def create_redemption(self, db: AsyncSession, data: dict) -> RedeemCodeRedemption:
        redemption = RedeemCodeRedemption(**data)
        db.add(redemption)
        await db.commit()
        await db.refresh(redemption)
        return redemption

    async def get_user_redemptions(
        self,
        db: AsyncSession,
        user_id: UUID | str,
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[int, List[RedeemCodeRedemption]]:
        query = select(RedeemCodeRedemption).where(RedeemCodeRedemption.user_id == user_id)
        count_query = select(func.count(RedeemCodeRedemption.id)).where(RedeemCodeRedemption.user_id == user_id)

        total_res = await db.execute(count_query)
        total = total_res.scalar() or 0

        query = query.order_by(desc(RedeemCodeRedemption.redeemed_at)).offset(skip).limit(limit)
        result = await db.execute(query)
        redemptions = result.scalars().all()

        return total, list(redemptions)
