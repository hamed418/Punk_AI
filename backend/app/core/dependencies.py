"""
app/core/dependencies.py
Reusable FastAPI dependency injectors:
  - get_db  -> async SQLAlchemy session
  - get_current_user -> JWT-validated user object
"""
from fastapi import Depends, HTTPException, status,Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from collections import defaultdict
import time
from app.core.security import decode_token
from app.db.database import AsyncSessionLocal 
from app.modules.user.models import User, UserSession
from app.modules.subscription.models import UserSubscription,Subscription
from app.shared.enums import SubscriptionStatus

bearer_scheme = HTTPBearer(auto_error=False)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not credentials:
        raise credentials_exception

    token = credentials.credentials

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise credentials_exception

    user_id: str = payload.get("sub")
    if not user_id:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception

    session_id = payload.get("session_id")
    if session_id:
        session_result = await db.execute(
            select(UserSession).where(UserSession.id == session_id)
        )
        user_session = session_result.scalar_one_or_none()
        if not user_session or not user_session.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="SESSION_REVOKED",
                headers={"WWW-Authenticate": "Bearer"},
            )
    else:
        # Legacy tokens without session_id are considered revoked
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SESSION_REVOKED",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user

async def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if not credentials:
        return None

    try:
        token = credentials.credentials
        payload = decode_token(token)
        if not payload or payload.get("type") != "access":
            return None

        user_id: str = payload.get("sub")
        if not user_id:
            return None

        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
    except Exception:
        return None


async def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """Allows both admin and super_admin roles."""
    from app.shared.enums import UserRole
    if current_user.role not in (UserRole.admin, UserRole.super_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


async def get_super_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """Allows only super_admin role."""
    from app.shared.enums import UserRole
    if current_user.role != UserRole.super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin privileges required",
        )
    return current_user

 
# Store: { ip: {"count": int, "window_start": float} }
login_attempts: dict = defaultdict(lambda: {"count": 0, "window_start": 0.0})

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 120  # 2 minutes

def check_rate_limit(request: Request):
    ip = request.client.host
    now = time.time()
    record = login_attempts[ip]

    # Reset window if 2 minutes have passed
    if now - record["window_start"] > WINDOW_SECONDS:
        record["count"] = 0
        record["window_start"] = now

    if record["count"] >= MAX_ATTEMPTS:
        retry_after = int(WINDOW_SECONDS - (now - record["window_start"]))
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Please wait.",
            headers={"Retry-After": str(retry_after)},
        )

    record["count"] += 1
    return True

 


async def check_subscription_active(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserSubscription | None:
    """
    Guard: Ensures user has active subscription + token limit check
    """
    from app.modules.subscription.service import TokenService
    
    balance = await TokenService.get_user_token_balance_internal(db, current_user.id)
    if balance["remaining_tokens"] <= 0:
        if current_user.isSubscriptionActive:
            current_user.isSubscriptionActive = False
            db.add(current_user)
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Token limit exceeded. Please upgrade your plan."
        )
        
    if not current_user.isSubscriptionActive:
        current_user.isSubscriptionActive = True
        db.add(current_user)
        await db.commit()

    # Find the most relevant active UserSubscription to return for backwards compatibility
    result = await db.execute(
        select(UserSubscription)
        .where(
            UserSubscription.user_id == current_user.id,
            UserSubscription.status == SubscriptionStatus.active
        )
    )
    return result.scalars().first()