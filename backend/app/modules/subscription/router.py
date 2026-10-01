from app.core.security import skip_api_key
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_
from sqlalchemy.orm import selectinload

from app.core.dependencies import get_db, get_current_user
from app.modules.user.models import User
from app.shared.enums import UserRole, PurchaseType
from app.modules.subscription.models import (
    Subscription,
    UserSubscription,
    TokenTransaction,
)
from app.modules.subscription.schemas import (
    SubscriptionResponse,
    SubscriptionCreateRequest,
    SubscriptionUpdateRequest,
    UserSubscriptionResponse,
    UserSubscriptionCreateRequest,
    UserSubscriptionUpdateRequest,
    AssignAdsAccountRequest,
    TokenBalanceResponse,
    TokenTransactionResponse,
)
from app.modules.subscription.repository import SubscriptionRepository
from app.modules.subscription.service import (
    SubscriptionService,
    SubscriptionLinkingService,
    TokenService,
)

router = APIRouter()

repository = SubscriptionRepository()
service = SubscriptionService(repository)


# ── General Subscription (Plans) CRUD ──────────────────────────────────────────

@router.post("/subscription/list", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED, tags=["Admin - Subscriptions"])
@skip_api_key
async def subscription_card_show(
    payload: SubscriptionCreateRequest,
    db: AsyncSession = Depends(get_db)
) -> SubscriptionResponse: 
    return await service.create_subscription(db, payload)
        

@router.patch("/subscription/update/{id}", response_model=SubscriptionResponse, status_code=status.HTTP_200_OK, tags=["Admin - Subscriptions"])
@skip_api_key
async def subscription_card_update(
    id: uuid.UUID,
    payload: SubscriptionUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    return await service.update_subscription(db, id, payload)

@router.get("/subscription/list", response_model=List[SubscriptionResponse], status_code=status.HTTP_200_OK, tags=["Admin - Subscriptions"])
@skip_api_key
async def subscription_card_show_all(
    type: str = Query("ALL", description="Filter by purchase type (SUBSCRIPTION, TOKEN_PACK, or ALL)"),
    db: AsyncSession = Depends(get_db)
):
    actual_type = None if type.upper() == "ALL" else type
    return await service.get_all_subscriptions(db, actual_type)

@router.get("/subscription/list/{id}", response_model=SubscriptionResponse, status_code=status.HTTP_200_OK, tags=["Admin - Subscriptions"])
@skip_api_key
async def subscription_card_show_single(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    return await service.get_subscription(db, id)

@router.delete("/subscription/delete/{id}", response_model=SubscriptionResponse, status_code=status.HTTP_200_OK, tags=["Admin - Subscriptions"])
@skip_api_key
async def subscription_card_delete(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    return await service.delete_subscription(db, id)




# ── Current User (/me) Operations ───────────────────────────────────────────

@router.get("/me/subscriptions", response_model=List[UserSubscriptionResponse], tags=["Subscriptions"])
async def get_my_subscriptions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserSubscription)
        .where(UserSubscription.user_id == current_user.id)
        .options(selectinload(UserSubscription.plan))
        .order_by(UserSubscription.created_at.desc())
    )
    return result.scalars().all()

@router.get("/me/token-balance", response_model=TokenBalanceResponse, tags=["Subscriptions"])
async def get_my_token_balance(
    ad_account_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await TokenService.get_user_token_balance_internal(db, current_user.id, ad_account_id)

@router.get("/me/token-history", response_model=List[TokenTransactionResponse], tags=["Subscriptions"])
async def get_my_token_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TokenTransaction)
        .where(TokenTransaction.user_id == current_user.id)
        .order_by(TokenTransaction.created_at.desc())
    )
    return result.scalars().all()
