from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func, desc
from sqlalchemy.orm import selectinload
from typing import Tuple, List, Optional
from .models import FAQCategory, FAQ, LandingFAQ

class FAQRepository:
    
    # ── Category ────────────────────────────────────────────────────────
    
    async def get_category_by_id(self, db: AsyncSession, category_id: str) -> Optional[FAQCategory]:
        result = await db.execute(
            select(FAQCategory).where(FAQCategory.id == category_id)
        )
        return result.scalar_one_or_none()

    async def get_categories(
        self, db: AsyncSession, skip: int = 0, limit: int = 100, 
        search: Optional[str] = None, is_active: Optional[bool] = None, type: Optional[str] = None
    ) -> Tuple[int, List[FAQCategory]]:
        query = select(FAQCategory)
        
        if search:
            query = query.where(
                or_(
                    FAQCategory.name.ilike(f"%{search}%"),
                    FAQCategory.description.ilike(f"%{search}%")
                )
            )
        if is_active is not None:
            query = query.where(FAQCategory.is_active == is_active)
        if type:
            query = query.where(FAQCategory.type == type)

        count_query = select(func.count(FAQCategory.id))
        if search:
            count_query = count_query.where(
                or_(
                    FAQCategory.name.ilike(f"%{search}%"),
                    FAQCategory.description.ilike(f"%{search}%")
                )
            )
        if is_active is not None:
            count_query = count_query.where(FAQCategory.is_active == is_active)
        if type:
            count_query = count_query.where(FAQCategory.type == type)

        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        query = query.order_by(FAQCategory.created_at.asc()).offset(skip).limit(limit)
        result = await db.execute(query)
        categories = result.scalars().all()
        
        return total, list(categories)

    async def create_category(self, db: AsyncSession, data: dict) -> FAQCategory:
        category = FAQCategory(**data)
        db.add(category)
        await db.commit()
        await db.refresh(category)
        return category

    async def update_category(self, db: AsyncSession, category: FAQCategory) -> FAQCategory:
        db.add(category)
        await db.commit()
        await db.refresh(category)
        return category

    async def delete_category(self, db: AsyncSession, category: FAQCategory) -> None:
        await db.delete(category)
        await db.commit()

    # ── FAQ ─────────────────────────────────────────────────────────────

    async def get_faq_by_id(self, db: AsyncSession, faq_id: str) -> Optional[FAQ]:
        result = await db.execute(
            select(FAQ).options(selectinload(FAQ.category)).where(FAQ.id == faq_id)
        )
        return result.scalar_one_or_none()

    async def get_faqs(
        self, db: AsyncSession, skip: int = 0, limit: int = 100, 
        search: Optional[str] = None, category_id: Optional[str] = None, is_active: Optional[bool] = None
    ) -> Tuple[int, List[FAQ]]:
        query = select(FAQ).options(selectinload(FAQ.category))
        count_query = select(func.count(FAQ.id))
        
        if search:
            filter_expr = or_(
                FAQ.question.ilike(f"%{search}%"),
                FAQ.answer.ilike(f"%{search}%")
            )
            query = query.where(filter_expr)
            count_query = count_query.where(filter_expr)
        if category_id:
            query = query.where(FAQ.category_id == category_id)
            count_query = count_query.where(FAQ.category_id == category_id)
        if is_active is not None:
            query = query.where(FAQ.is_active == is_active)
            count_query = count_query.where(FAQ.is_active == is_active)

        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        query = query.order_by(FAQ.created_at.asc()).offset(skip).limit(limit)
        result = await db.execute(query)
        faqs = result.scalars().all()
        
        return total, list(faqs)


    async def create_faq(self, db: AsyncSession, data: dict) -> FAQ:
        faq = FAQ(**data)
        db.add(faq)
        await db.commit()
        await db.refresh(faq)
        # Load relationships
        result = await db.execute(
            select(FAQ).options(selectinload(FAQ.category)).where(FAQ.id == faq.id)
        )
        return result.scalar_one()

    async def update_faq(self, db: AsyncSession, faq: FAQ) -> FAQ:
        db.add(faq)
        await db.commit()
        await db.refresh(faq)
        # Load relationships
        result = await db.execute(
            select(FAQ).options(selectinload(FAQ.category)).where(FAQ.id == faq.id)
        )
        return result.scalar_one()

    async def delete_faq(self, db: AsyncSession, faq: FAQ) -> None:
        await db.delete(faq)
        await db.commit()

    # ── Landing FAQ ─────────────────────────────────────────────────────

    async def get_landing_faq_by_id(self, db: AsyncSession, faq_id: str) -> Optional[LandingFAQ]:
        result = await db.execute(
            select(LandingFAQ).where(LandingFAQ.id == faq_id)
        )
        return result.scalar_one_or_none()

    async def get_landing_faqs(
        self, db: AsyncSession, skip: int = 0, limit: int = 100, 
        search: Optional[str] = None, is_active: Optional[bool] = None
    ) -> Tuple[int, List[LandingFAQ]]:
        query = select(LandingFAQ)
        count_query = select(func.count(LandingFAQ.id))
        
        if search:
            filter_expr = or_(
                LandingFAQ.question.ilike(f"%{search}%"),
                LandingFAQ.answer.ilike(f"%{search}%")
            )
            query = query.where(filter_expr)
            count_query = count_query.where(filter_expr)
        if is_active is not None:
            query = query.where(LandingFAQ.is_active == is_active)
            count_query = count_query.where(LandingFAQ.is_active == is_active)

        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        query = query.order_by(LandingFAQ.created_at.asc()).offset(skip).limit(limit)
        result = await db.execute(query)
        faqs = result.scalars().all()
        
        return total, list(faqs)

    async def create_landing_faq(self, db: AsyncSession, data: dict) -> LandingFAQ:
        faq = LandingFAQ(**data)
        db.add(faq)
        await db.commit()
        await db.refresh(faq)
        return faq

    async def update_landing_faq(self, db: AsyncSession, faq: LandingFAQ) -> LandingFAQ:
        db.add(faq)
        await db.commit()
        await db.refresh(faq)
        return faq

    async def delete_landing_faq(self, db: AsyncSession, faq: LandingFAQ) -> None:
        await db.delete(faq)
        await db.commit()


