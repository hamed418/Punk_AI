from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func, desc
from sqlalchemy.orm import selectinload
from typing import Tuple, List, Optional
from .models import Support
from app.modules.faq.models import FAQCategory

class SupportRepository:
    async def get_support_by_id(self, db: AsyncSession, support_id: str) -> Optional[Support]:
        result = await db.execute(
            select(Support)
            .options(selectinload(Support.category), selectinload(Support.user))
            .where(Support.id == support_id)
        )
        return result.scalar_one_or_none()

    async def get_supports(
        self, db: AsyncSession, skip: int = 0, limit: int = 100, 
        search: Optional[str] = None, category_id: Optional[str] = None, 
        user_id: Optional[str] = None, status: Optional[str] = None,
        problem_type: Optional[str] = None
    ) -> Tuple[int, List[Support]]:
        query = select(Support).options(selectinload(Support.category), selectinload(Support.user))
        
        if search:
            query = query.where(
                or_(
                    Support.name.ilike(f"%{search}%"),
                    Support.email.ilike(f"%{search}%"),
                    Support.description.ilike(f"%{search}%"),
                    Support.problem_type.ilike(f"%{search}%")
                )
            )
        if category_id:
            query = query.where(Support.category_id == category_id)
        if user_id:
            query = query.where(Support.user_id == user_id)
        if status:
            query = query.where(Support.status == status)
        if problem_type:
            query = query.where(Support.problem_type == problem_type)

        total_result = await db.execute(select(func.count()).select_from(query.subquery()))
        total = total_result.scalar() or 0

        query = query.order_by(desc(Support.created_at)).offset(skip).limit(limit)
        result = await db.execute(query)
        supports = result.scalars().all()
        
        return total, list(supports)

    async def create_support(self, db: AsyncSession, data: dict) -> Support:
        support = Support(**data)
        db.add(support)
        await db.commit()
        await db.refresh(support)
        
        result = await db.execute(
            select(Support)
            .options(selectinload(Support.category), selectinload(Support.user))
            .where(Support.id == support.id)
        )
        return result.scalar_one()

    async def update_support(self, db: AsyncSession, support: Support) -> Support:
        db.add(support)
        await db.commit()
        await db.refresh(support)
        
        result = await db.execute(
            select(Support)
            .options(selectinload(Support.category), selectinload(Support.user))
            .where(Support.id == support.id)
        )
        return result.scalar_one()

    async def delete_support(self, db: AsyncSession, support: Support) -> None:
        await db.delete(support)
        await db.commit()
