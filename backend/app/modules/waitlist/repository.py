from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from .models import WaitList


class WaitlistRepository:
    async def get_all(self, db: AsyncSession, skip: int, limit: int):
        total_result = await db.execute(select(func.count()).select_from(WaitList))
        total = total_result.scalar()
        
        result = await db.execute(
            select(WaitList)
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all(), total
    
    async def create(
        self,
        db: AsyncSession,
        data
    ):
        new_waitlist = WaitList(**data)
        db.add(new_waitlist)
        await db.commit()
        await db.refresh(new_waitlist)
        return new_waitlist 

    async def get_by_id(self,db,id):
        result = await db.execute(select(WaitList).where(WaitList.id == id))
        return result.scalar_one_or_none()
        
    async def update(self , db:AsyncSession,id,data): 
        await db.commit()
        await db.refresh(data)
        return data
    
    async def delete(self, db, wait_user):
        await db.delete(wait_user)
        await db.commit()
        return {"message": "Waitlist deleted successfully"}
 
    async def get_by_email(self,db,email):
        result = await db.execute(select(WaitList).where(WaitList.email == email))
        return result.scalar_one_or_none()

