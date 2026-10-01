import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.modules.payment.models import Subscription
from app.db.models import Base
from app.core.config import settings
import uuid

# Define the plans
PLANS = [
    {
        "price_id": "free_tier",
        "description": "5 Campaigns/mo, Basic Analytics, Email Support, Single Platform",
        "amount": 0,
        "currency": "usd"
    },
    {
        "price_id": "pro_tier",
        "description": "Unlimited Campaigns, Advanced AI Targeting, Priority Support, Multi-Platform Ads, Real-time ROI Tracking",
        "amount": 29,
        "currency": "usd"
    },
    {
        "price_id": "enterprise_tier",
        "description": "Custom Solutions, Dedicated Account Manager, API Access, White-label Reports, Custom LLM Training",
        "amount": 99,
        "currency": "usd"
    }
]

async def seed_plans():
    engine = create_async_engine(settings.DATABASE_URL, echo=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        async with session.begin():
            # Clear existing plans first if you want a clean start
            # from sqlalchemy import delete
            # await session.execute(delete(Subscription))
            
            for plan_data in PLANS:
                plan = Subscription(
                    price_id=plan_data["price_id"],
                    description=plan_data["description"],
                    amount=plan_data["amount"],
                    currency=plan_data["currency"]
                )
                session.add(plan)
        
        await session.commit()
    print("Plans seeded successfully!")

if __name__ == "__main__":
    asyncio.run(seed_plans())
