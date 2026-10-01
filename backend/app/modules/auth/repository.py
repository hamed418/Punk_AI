from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.modules.user.models import User,EarlyAccessPayment
from app.modules.ads.models import OAuthToken, AdsAccount
from typing import Optional


from app.modules.subscription.models import UserSubscription

class AuthRepository:
    async def get_user_by_id(self, db: AsyncSession, user_id: str) -> Optional[User]:
        result = await db.execute(
            select(User)
            .where(User.id == user_id)
            .options(
                selectinload(User.oauth_tokens).selectinload(OAuthToken.ads_accounts).selectinload(AdsAccount.subscription),
                selectinload(User.subscriptions).selectinload(UserSubscription.plan),
                selectinload(User.ads_accounts).selectinload(AdsAccount.subscription)
            )
        )
        return result.scalar_one_or_none()
    
    async def get_user_by_email(self, db: AsyncSession, email: str) -> Optional[User]:
        clean_email = email.strip().lower() if email else ""
        result = await db.execute(
            select(User)
            .where(func.lower(User.email) == clean_email)
            .options(
                selectinload(User.oauth_tokens).selectinload(OAuthToken.ads_accounts).selectinload(AdsAccount.subscription),
                selectinload(User.subscriptions).selectinload(UserSubscription.plan),
                selectinload(User.ads_accounts).selectinload(AdsAccount.subscription)
            )
            .order_by(User.created_at.desc())
        )
        return result.scalars().first()

    async def get_user_by_google_id(self, db: AsyncSession, google_id: str) -> Optional[User]:
        if not google_id:
            return None
        result = await db.execute(
            select(User)
            .where(User.google_id == google_id)
            .options(
                selectinload(User.oauth_tokens).selectinload(OAuthToken.ads_accounts).selectinload(AdsAccount.subscription),
                selectinload(User.subscriptions).selectinload(UserSubscription.plan),
                selectinload(User.ads_accounts).selectinload(AdsAccount.subscription)
            )
        )
        return result.scalars().first()

    async def get_user_by_apple_id(self, db: AsyncSession, apple_id: str) -> Optional[User]:
        if not apple_id:
            return None
        result = await db.execute(
            select(User)
            .where(User.apple_id == apple_id)
            .options(
                selectinload(User.oauth_tokens).selectinload(OAuthToken.ads_accounts).selectinload(AdsAccount.subscription),
                selectinload(User.subscriptions).selectinload(UserSubscription.plan),
                selectinload(User.ads_accounts).selectinload(AdsAccount.subscription)
            )
        )
        return result.scalars().first()

    async def create_user(self, db: AsyncSession, data: dict):
        user = User(**data)
        db.add(user)
        await db.commit()
        return await self.get_user_by_id(db, str(user.id))
    
    async def update_user(self, db: AsyncSession, user: User):
        db.add(user)
        await db.commit()
        return await self.get_user_by_id(db, str(user.id))

    # early access token method 
    async def get_early_access_payment_by_email(self, db: AsyncSession, email: str):
        clean_email = email.strip().lower() if email else ""
        result = await db.execute(
            select(EarlyAccessPayment)
            .where(func.lower(EarlyAccessPayment.email) == clean_email)
            .order_by(EarlyAccessPayment.is_payment_done.desc(), EarlyAccessPayment.created_at.desc())
        )
        return result.scalars().first()


    # ── Session Methods ────────────────────────────────────────────────────────

    async def get_active_sessions_by_user_id(self, db: AsyncSession, user_id: str) -> list:
        from app.modules.user.models import UserSession
        result = await db.execute(
            select(UserSession)
            .where(UserSession.user_id == user_id, UserSession.is_active == True)
            .order_by(UserSession.last_active_at.desc())
        )
        return result.scalars().all()
    
    async def get_session_by_id(self, db: AsyncSession, session_id: str):
        from app.modules.user.models import UserSession
        result = await db.execute(
            select(UserSession).where(UserSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def create_session(self, db: AsyncSession, data: dict):
        from app.modules.user.models import UserSession
        session = UserSession(**data)
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session

    async def update_session(self, db: AsyncSession, session):
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session
