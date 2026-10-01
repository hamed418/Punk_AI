import pytest
import pytest_asyncio
import uuid
from datetime import datetime, timedelta
from sqlalchemy import select

import app.db.model_registry
from app.db.database import AsyncSessionLocal, engine
from app.modules.user.models import User
from app.modules.subscription.models import UserSubscription, SubscriptionTokenAllocation, TokenTransaction
from app.modules.subscription.service import SubscriptionLinkingService, TokenService
from app.shared.enums import SubscriptionStatus, SubscriptionPaymentStatus, UserRole

@pytest_asyncio.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        # Yield the session and rollback after test run to keep DB clean
        yield session
        await session.rollback()
    await engine.dispose()

@pytest.mark.asyncio
async def test_email_based_subscription_linking(db_session):
    # 1. Create a UserSubscription with a specific email but no user_id (unlinked)
    test_email = f"test_{uuid.uuid4()}@example.com"
    sub = UserSubscription(
        email=test_email,
        normalized_email=test_email.lower(),
        user_id=None,
        total_tokens=50000,
        status=SubscriptionStatus.active,
        payment_status=SubscriptionPaymentStatus.paid,
        current_period_end=datetime.utcnow() + timedelta(days=30)
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    
    # Assert subscription is unlinked
    assert sub.user_id is None
    
    # 2. Create a User with the matching email (simulating registration)
    user = User(
        email=test_email.upper(),  # Test case-insensitivity
        password_hash="fakehash",
        full_name="Test User",
        role=UserRole.user,
        is_verified=True,
        isSubscriptionActive=False
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    
    # 3. Call the linking service
    await SubscriptionLinkingService.link_subscriptions_to_user(db_session, user)
    
    # Refresh objects from DB
    await db_session.refresh(sub)
    await db_session.refresh(user)
    
    # Verify linking succeeded
    assert sub.user_id == user.id
    assert user.isSubscriptionActive is True
    
    # Verify idempotent token allocation unique record is created
    alloc_res = await db_session.execute(
        select(SubscriptionTokenAllocation).where(SubscriptionTokenAllocation.subscription_id == sub.id)
    )
    alloc = alloc_res.scalar_one_or_none()
    assert alloc is not None
    assert alloc.user_id == user.id
    
    # Verify token balance is allocated
    assert sub.remaining_tokens == 50000
    assert sub.used_tokens == 0
    
    # Verify allocation transaction is logged
    tx_res = await db_session.execute(
        select(TokenTransaction).where(TokenTransaction.subscription_id == sub.id)
    )
    txs = list(tx_res.scalars().all())
    assert len(txs) == 1
    assert txs[0].type == "ALLOCATION"
    assert txs[0].amount == 50000
    
    # 4. Test idempotence: Running link again does not create duplicate allocations
    await SubscriptionLinkingService.link_subscriptions_to_user(db_session, user)
    
    alloc_res_2 = await db_session.execute(
        select(SubscriptionTokenAllocation).where(SubscriptionTokenAllocation.subscription_id == sub.id)
    )
    allocs = list(alloc_res_2.scalars().all())
    assert len(allocs) == 1  # Still exactly 1 allocation record!
    
    # Clean up test rows
    await db_session.delete(txs[0])
    await db_session.delete(alloc)
    await db_session.delete(sub)
    await db_session.delete(user)
    await db_session.commit()

@pytest.mark.asyncio
async def test_token_deduction_and_concurrency(db_session):
    test_email = f"test_{uuid.uuid4()}@example.com"
    user = User(
        email=test_email,
        password_hash="fakehash",
        full_name="Test User",
        role=UserRole.user,
        is_verified=True,
        free_token_usage=0,
        free_message_limit=1000
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    sub = UserSubscription(
        email=test_email,
        normalized_email=test_email,
        user_id=user.id,
        total_tokens=10000,
        remaining_tokens=10000,
        used_tokens=0,
        status=SubscriptionStatus.active
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    
    # Deduct 4000 tokens
    await TokenService.deduct_tokens(db_session, user.id, 4000, action="test_action")
    
    await db_session.refresh(sub)
    assert sub.remaining_tokens == 6000
    assert sub.used_tokens == 4000
    
    # Deduct 8000 tokens (this exceeds 6000 subscription tokens, but user has 1000 free tokens)
    # Total available: 6000 subscription + 1000 free = 7000. Deducting 8000 should raise Exception.
    with pytest.raises(Exception) as exc_info:
        await TokenService.deduct_tokens(db_session, user.id, 8000)
    
    # Deduct 7000 tokens (should succeed: consumes 6000 from subscription and 1000 from free limit)
    await TokenService.deduct_tokens(db_session, user.id, 7000)
    
    await db_session.refresh(sub)
    await db_session.refresh(user)
    
    assert sub.remaining_tokens == 0
    assert sub.used_tokens == 10000
    assert user.free_token_usage == 1000
    
    # Clean up test rows
    tx_res = await db_session.execute(
        select(TokenTransaction).where(TokenTransaction.user_id == user.id)
    )
    for tx in tx_res.scalars().all():
        await db_session.delete(tx)
    await db_session.delete(sub)
    await db_session.delete(user)
    await db_session.commit()
