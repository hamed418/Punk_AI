import uuid
import json
import stripe
from decimal import Decimal
from datetime import datetime
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import logger
from app.shared.enums import SubscriptionStatus, PurchaseType

from app.modules.subscription.repository import SubscriptionRepository
from app.modules.subscription.models import (
    Subscription,
    UserSubscription,
    SubscriptionTokenAllocation,
    TokenTransaction,
)
from app.modules.user.models import User
from app.modules.subscription.schemas import (
    SubscriptionCreateRequest,
    SubscriptionUpdateRequest,
    SubscriptionResponse,
)

from app.services.stripe_logic import StripeService

class SubscriptionService:
    def __init__(self, repository: SubscriptionRepository):
        self.repository = repository

    def _build_subscription_response(self, sub: Subscription) -> SubscriptionResponse:
        desc = sub.description or ""
        features = []
        short_desc = desc
        if desc:
            try:
                parsed = json.loads(desc)
                if isinstance(parsed, dict):
                    if "features" in parsed and isinstance(parsed["features"], list):
                        features = [f.strip() for f in parsed["features"] if f and str(f).strip()]
                    if "shortDescription" in parsed:
                        short_desc = parsed["shortDescription"]
                    elif "description" in parsed:
                        short_desc = parsed["description"]
            except Exception:
                if "," in desc:
                    features = [f.strip() for f in desc.split(",") if f.strip()]
                    short_desc = ""
                elif "\n" in desc:
                    features = [f.strip() for f in desc.split("\n") if f.strip()]
                    short_desc = ""

        return SubscriptionResponse(
            id=sub.id,
            name=sub.name,
            slug=sub.slug,
            price_id=sub.price_id,
            description=short_desc,
            features=features,
            amount=sub.amount or Decimal("0.0"),
            currency=sub.currency or "usd",
            interval=sub.interval,
            type=sub.type or PurchaseType.SUBSCRIPTION,
            total_token_can_use=sub.total_token_can_use or 0,
            created_at=sub.created_at,
            updated_at=sub.updated_at,
        )

    async def create_subscription(self, db: AsyncSession, payload: SubscriptionCreateRequest) -> SubscriptionResponse:
        if not payload.amount:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount is required")
        if not payload.currency:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Currency is required")
        
        features_list = payload.features if payload.features is not None else []
        desc_str = json.dumps({
            "shortDescription": payload.description or "",
            "features": features_list,
            "name": payload.name or ""
        })
        
        subscription = Subscription(
            name=payload.name,
            slug=payload.slug,
            price_id=payload.price_id,
            interval=payload.interval,
            type=payload.type,
            description=desc_str,
            amount=payload.amount,
            currency=payload.currency,
            total_token_can_use=payload.total_token_can_use
        )
        saved = await self.repository.create_subscription(db, subscription)
        return self._build_subscription_response(saved)

    async def get_all_subscriptions(self, db: AsyncSession, type: Optional[str] = None) -> List[SubscriptionResponse]:
        subs = await self.repository.get_all_subscriptions(db, type)
        return [self._build_subscription_response(s) for s in subs]

    async def get_subscription(self, db: AsyncSession, id: uuid.UUID) -> SubscriptionResponse:
        sub = await self.repository.get_subscription(db, id)
        if not sub:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
        return self._build_subscription_response(sub)

    async def update_subscription(self, db: AsyncSession, id: uuid.UUID, payload: SubscriptionUpdateRequest) -> SubscriptionResponse:
        sub = await self.repository.get_subscription(db, id)
        if not sub:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
        
        if payload.name is not None:
            sub.name = payload.name
        if payload.slug is not None:
            sub.slug = payload.slug
        if payload.price_id is not None:
            sub.price_id = payload.price_id
        if payload.interval is not None:
            sub.interval = payload.interval
        if payload.type is not None:
            sub.type = payload.type
        if payload.amount is not None:
            sub.amount = payload.amount
        if payload.currency is not None:
            sub.currency = payload.currency
        if payload.total_token_can_use is not None:
            sub.total_token_can_use = payload.total_token_can_use
            
        if payload.features is not None or payload.description is not None:
            existing_desc = sub.description or ""
            existing_features = []
            existing_short_desc = existing_desc
            try:
                parsed = json.loads(existing_desc)
                if isinstance(parsed, dict):
                    existing_features = parsed.get("features", [])
                    existing_short_desc = parsed.get("shortDescription", existing_desc)
            except Exception:
                if "," in existing_desc:
                    existing_features = [f.strip() for f in existing_desc.split(",") if f.strip()]
                    existing_short_desc = ""

            new_features = payload.features if payload.features is not None else existing_features
            new_desc = payload.description if payload.description is not None else existing_short_desc

            sub.description = json.dumps({
                "shortDescription": new_desc,
                "features": new_features,
                "name": payload.name if payload.name is not None else sub.name
            })
            
        saved = await self.repository.update_subscription(db, sub)
        return self._build_subscription_response(saved)

    async def delete_subscription(self, db: AsyncSession, id: uuid.UUID) -> SubscriptionResponse:
        sub = await self.repository.get_subscription(db, id)
        if not sub:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
        await self.repository.delete_subscription(db, sub)
        return self._build_subscription_response(sub)



class SubscriptionLinkingService:
    @staticmethod
    async def link_subscriptions_to_user(db: AsyncSession, user: User) -> None:
         
        repository = SubscriptionRepository()
        
        # 1. Lock and retrieve all unlinked subscriptions with matching email
        unlinked_subs = await repository.get_unlinked_subscriptions_by_email(db, user.email)
        
        for sub in unlinked_subs:
            sub.user_id = user.id
            if sub.status in [SubscriptionStatus.active, SubscriptionStatus.trialing]:
                if (sub.total_tokens or 0) > 0:
                    sub.remaining_tokens = sub.total_tokens
                    sub.used_tokens = 0
                db.add(sub)
                await SubscriptionLinkingService.allocate_subscription_tokens(db, sub, user)
            else:
                db.add(sub)

        await db.commit()

    @staticmethod
    async def allocate_subscription_tokens(db: AsyncSession, sub: UserSubscription, user: User) -> None:
        # Check if already allocated
        alloc_check = await db.execute(
            select(SubscriptionTokenAllocation).where(SubscriptionTokenAllocation.subscription_id == sub.id)
        )
        if alloc_check.scalar_one_or_none() is not None:
            return  # Idempotent: already allocated!
            
        # Create allocation unique record
        allocation = SubscriptionTokenAllocation(
            subscription_id=sub.id,
            user_id=user.id
        )
        db.add(allocation)

        # Fund the subscription's own balance — quota is per ad account, not
        # a shared user wallet.
        current_remaining = sub.remaining_tokens or 0
        sub.remaining_tokens = sub.total_tokens
        sub.used_tokens = 0
        db.add(sub)

        # Log Transaction
        transaction = TokenTransaction(
            user_id=user.id,
            subscription_id=sub.id,
            type="ALLOCATION",
            amount=sub.total_tokens,
            balance_before=current_remaining,
            balance_after=sub.total_tokens,
            action="subscription_token_allocation",
            tx_metadata={"email": sub.email, "subscription_id": str(sub.id)}
        )
        db.add(transaction)
        
        # Update user's isSubscriptionActive flag
        user.isSubscriptionActive = True
        db.add(user)

        # Commit HERE, not in the caller. get_db() never commits, and the one
        # production caller (payment/service._handle_subscription_checkout)
        # already committed BEFORE calling this — so everything above was
        # in-memory state that died with the session: no allocation row,
        # remaining_tokens stuck at 0, isSubscriptionActive never set, for the
        # whole first billing period. Renewals (process_invoice_paid) commit
        # themselves, which is why month 2+ worked and month 1 did not.
        await db.commit()

class TokenService:
    @staticmethod
    async def get_user_token_balance_internal(
        db: AsyncSession, user_id: uuid.UUID, ad_account_id: Optional[str] = None
    ) -> dict:
        # 1. Sum up active subscriptions — scoped to one ad account when given,
        # since quota is per account, not a pool shared across every account
        # the user happens to have.
        repository = SubscriptionRepository()
        active_subs = await repository.get_active_subscriptions_by_user(db, user_id)
        if ad_account_id:
            active_subs = [s for s in active_subs if s.ad_account_id == ad_account_id]

        total_sub_tokens = sum(s.total_tokens for s in active_subs)
        used_sub_tokens = sum(s.used_tokens for s in active_subs)
        remaining_sub_tokens = sum(s.remaining_tokens for s in active_subs)
        
        # 2. Get user's free limits
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        free_limit = user.free_message_limit if user else 10000
        free_used = user.free_token_usage if user else 0
        free_remaining = max(0, free_limit - free_used)
        
        return {
            "remaining_tokens": remaining_sub_tokens + free_remaining,
            "total_tokens": total_sub_tokens + free_limit,
            "used_tokens": used_sub_tokens + free_used,
            "subscription_remaining": remaining_sub_tokens,
            "subscription_total": total_sub_tokens,
            "free_remaining": free_remaining,
            "free_total": free_limit,
            "free_used": free_used
        }

    @staticmethod
    async def deduct_tokens(
        db: AsyncSession,
        user_id: uuid.UUID,
        amount: int,
        ad_account_id: Optional[str] = None,
        action: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> None:
        if amount <= 0:
            return
            
        # Get overall balance before deduction to fail fast
        balance = await TokenService.get_user_token_balance_internal(db, user_id, ad_account_id)
        if balance["remaining_tokens"] < amount:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Insufficient tokens. Please upgrade your plan."
            )
            
        remaining_to_deduct = amount
        repository = SubscriptionRepository()
        
        # Fetch user
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
            
        # Fetch active subscriptions
        active_subs = await repository.get_active_subscriptions_by_user(db, user_id)

        # Consumption Strategy (no join table — sub.ad_account_id is the only
        # real binding; SubscriptionAdsAccount is dead, nothing ever wrote it):
        # 1. Subs bound to the current ad_account_id
        # 2. Unscoped subs (no ad_account_id)
        # 3. Oldest/earliest expiration first within each group
        ad_account_subs = [s for s in active_subs if ad_account_id and s.ad_account_id == ad_account_id]
        general_subs = [s for s in active_subs if not s.ad_account_id]

        # Sort each group (expiration ASC, created_at ASC)
        ad_account_subs.sort(key=lambda s: (s.current_period_end or datetime.max, s.created_at))
        general_subs.sort(key=lambda s: (s.current_period_end or datetime.max, s.created_at))
        
        subs_to_consume = ad_account_subs + general_subs
        
        for sub in subs_to_consume:
            if remaining_to_deduct <= 0:
                break
                
            lock_res = await db.execute(
                select(UserSubscription)
                .where(UserSubscription.id == sub.id)
                .with_for_update()
            )
            locked_sub = lock_res.scalar_one_or_none()
            if not locked_sub or locked_sub.remaining_tokens <= 0:
                continue
                
            deduction = min(locked_sub.remaining_tokens, remaining_to_deduct)
            locked_sub.remaining_tokens -= deduction
            locked_sub.used_tokens += deduction
            db.add(locked_sub)
            
            # Log Transaction
            current_bal_details = await TokenService.get_user_token_balance_internal(db, user_id)
            current_bal = current_bal_details["remaining_tokens"]
            
            tx = TokenTransaction(
                user_id=user_id,
                subscription_id=locked_sub.id,
                type="USAGE",
                amount=deduction,
                balance_before=current_bal + deduction,
                balance_after=current_bal,
                action=action or "token_consumption",
                tx_metadata={
                    **(metadata or {}),
                    "ad_account_id": ad_account_id,
                    "subscription_id": str(locked_sub.id)
                }
            )
            db.add(tx)
            
            remaining_to_deduct -= deduction

        # If we still need to deduct tokens and user has free usage remaining
        if remaining_to_deduct > 0:
            free_limit = user.free_message_limit
            free_used = user.free_token_usage
            free_remaining = max(0, free_limit - free_used)
            
            if free_remaining > 0:
                deduction = min(free_remaining, remaining_to_deduct)
                user.free_token_usage += deduction
                db.add(user)
                
                current_bal_details = await TokenService.get_user_token_balance_internal(db, user_id)
                current_bal = current_bal_details["remaining_tokens"]
                
                tx = TokenTransaction(
                    user_id=user_id,
                    subscription_id=None,
                    type="USAGE",
                    amount=deduction,
                    balance_before=current_bal + deduction,
                    balance_after=current_bal,
                    action=action or "free_token_consumption",
                    tx_metadata={
                        **(metadata or {}),
                        "ad_account_id": ad_account_id,
                        "type": "free_tier"
                    }
                )
                db.add(tx)
                remaining_to_deduct -= deduction
                
        if remaining_to_deduct > 0:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Insufficient tokens. Please upgrade your plan."
            )
            
        await db.commit()
