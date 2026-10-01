from app.shared.enums import SubscriptionStatus, SubscriptionPaymentStatus
import uuid
from typing import List, Optional
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.subscription.models import (
    Subscription,
    UserSubscription,
    SubscriptionTokenAllocation,
    TokenTransaction,
)
from app.modules.user.models import User

class SubscriptionRepository:
    async def create_subscription(self, db: AsyncSession, subscription: Subscription) -> Subscription:
        db.add(subscription)
        await db.commit()
        await db.refresh(subscription)
        return subscription

    async def get_all_subscriptions(self, db: AsyncSession, type: Optional[str] = None) -> List[Subscription]:
        query = select(Subscription)
        if type:
            query = query.where(Subscription.type == type)
        result = await db.execute(query.order_by(Subscription.created_at.asc()))
        return list(result.scalars().all())


    async def get_subscription(self, db: AsyncSession, id: uuid.UUID | str) -> Optional[Subscription]:
        if isinstance(id, uuid.UUID):
            result = await db.execute(select(Subscription).where(Subscription.id == id))
            return result.scalars().first()

        if isinstance(id, str) and id.strip():
            id_str = id.strip()
            try:
                parsed_uuid = uuid.UUID(id_str)
                result = await db.execute(select(Subscription).where(Subscription.id == parsed_uuid))
                sub = result.scalars().first()
                if sub:
                    return sub
            except (ValueError, AttributeError):
                pass

            result = await db.execute(
                select(Subscription).where(
                    or_(
                        func.lower(Subscription.slug) == id_str.lower(),
                        func.lower(Subscription.name) == id_str.lower(),
                    )
                )
            )
            return result.scalars().first()

        return None

    async def update_subscription(self, db: AsyncSession, subscription: Subscription) -> Subscription:
        db.add(subscription)
        await db.commit()
        await db.refresh(subscription)
        return subscription

    async def delete_subscription(self, db: AsyncSession, subscription: Subscription):
        await db.delete(subscription)
        await db.commit()
        
    async def get_user(self, db: AsyncSession, user_id: uuid.UUID) -> Optional[User]:
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalars().first()

    async def update_user(self, db: AsyncSession, user: User):
        db.add(user)
        await db.commit()
        await db.refresh(user)
        
    async def get_user_subscription(self, db: AsyncSession, user_id: uuid.UUID) -> Optional[UserSubscription]:
        result = await db.execute(
            select(UserSubscription).where(
                UserSubscription.user_id == user_id,
                UserSubscription.ad_account_id.is_(None)
            ).order_by(UserSubscription.created_at.desc())
        )
        return result.scalars().first()

    async def get_user_subscription_by_id(self, db: AsyncSession, id: uuid.UUID) -> Optional[UserSubscription]:
        result = await db.execute(
            select(UserSubscription).where(
                UserSubscription.id == id
            ).order_by(UserSubscription.created_at.desc())
        )
        return result.scalars().first()

    async def get_user_subscription_by_ad_account(self, db: AsyncSession, user_id: uuid.UUID, ad_account_id: str) -> Optional[UserSubscription]:
        result = await db.execute(
            select(UserSubscription).where(
                UserSubscription.user_id == user_id, 
                UserSubscription.ad_account_id == ad_account_id
            ).order_by(UserSubscription.created_at.desc())
        )
        return result.scalars().first()

    async def update_user_subscription(self, db: AsyncSession, user_subscription: UserSubscription):
        db.add(user_subscription)
        await db.commit()
        await db.refresh(user_subscription)

    async def get_unlinked_subscriptions_by_email(self, db: AsyncSession, email: str) -> List[UserSubscription]:
        normalized = email.strip().lower()
        result = await db.execute(
            select(UserSubscription)
            .where(
                func.lower(UserSubscription.email) == normalized,
                UserSubscription.user_id.is_(None),
                UserSubscription.payment_status == SubscriptionPaymentStatus.paid,
                UserSubscription.status == SubscriptionStatus.active,
                UserSubscription.ad_account_id.is_(None)
            )
            .with_for_update()
        )
        return list(result.scalars().all())

    async def get_active_subscriptions_by_user(self, db: AsyncSession, user_id: uuid.UUID) -> List[UserSubscription]:
        from datetime import datetime
        now = datetime.utcnow()
        result = await db.execute(
            select(UserSubscription)
            .where(
                UserSubscription.user_id == user_id,
                UserSubscription.status.in_([SubscriptionStatus.active, SubscriptionStatus.trialing])
            )
            .order_by(UserSubscription.current_period_end.asc(), UserSubscription.created_at.asc())
        )
        subs = []
        for s in result.scalars().all():
            if not s.current_period_end or s.current_period_end.replace(tzinfo=None) > now:
                subs.append(s)
        return subs

    async def get_cheapest_paid_plan(self, db: AsyncSession) -> Optional[Subscription]:
        result = await db.execute(
            select(Subscription)
            .where(Subscription.amount > 0)
            .order_by(Subscription.amount.asc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_any_plan(self, db: AsyncSession) -> Optional[Subscription]:
        result = await db.execute(select(Subscription).limit(1))
        return result.scalars().first()

    async def get_user_subscription_by_email(self, db: AsyncSession, email: str) -> Optional[UserSubscription]:
        normalized = email.strip().lower()
        result = await db.execute(
            select(UserSubscription)
            .where(UserSubscription.email == normalized)
            .order_by(UserSubscription.created_at.desc())
        )
        return result.scalars().first()

    async def create_early_access_payment(self, db: AsyncSession, ea_payment) -> None:
        db.add(ea_payment)
        await db.commit()
        await db.refresh(ea_payment)