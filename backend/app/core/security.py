"""
app/core/security.py
JWT creation/verification and password hashing utilities.
"""
import re
import secrets
from fastapi import Security,HTTPException,status,Request
from datetime import  datetime, timedelta, timezone
from typing import Optional, Union
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi.security import APIKeyHeader
from app.core.config import settings
from app.core.logging import logger

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Password helpers ────────────────────────────────────────────────────────

def validate_password_complexity(password: str) -> str:
    """
    Enforce security complexity rules and bcrypt boundary limits:
    - Minimum 8 characters
    - Maximum 72 bytes (Bcrypt boundary limit to prevent silent truncation)
    - At least one uppercase letter (A-Z)
    - At least one lowercase letter (a-z)
    - At least one digit (0-9)
    - At least one special symbol
    """
    if not password:
        raise ValueError("Password is required.")

    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")

    if len(password.encode("utf-8")) > 72:
        raise ValueError("Password cannot exceed 72 bytes.")

    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter (A-Z).")

    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter (a-z).")

    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one number (0-9).")

    if not re.search(r"[^A-Za-z0-9]", password):
        raise ValueError("Password must contain at least one special character.")

    return password


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ── Token helpers ───────────────────────────────────────────────────────────

def _create_token(data: dict, expires_delta: timedelta) -> str:
    payload = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    payload.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(user_id: str, email: str, role: str, session_id: str, impersonator_id: Optional[str] = None) -> str:
    payload = {"sub": user_id, "email": email, "role": role, "session_id": session_id, "type": "access"}
    if impersonator_id:
        payload["impersonator_id"] = impersonator_id
    
    return _create_token(
        data=payload,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(user_id: str, session_id: str, impersonator_id: Optional[str] = None) -> str:
    payload = {"sub": user_id, "session_id": session_id, "type": "refresh"}
    if impersonator_id:
        payload["impersonator_id"] = impersonator_id
    return _create_token(
        data=payload,
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def create_pending_login_token(user_id: str) -> str:
    return _create_token(
        data={"sub": user_id, "type": "pending_login"},
        expires_delta=timedelta(minutes=5),
    )


def create_password_reset_token(email: str) -> str:
    return _create_token(
        data={"sub": email, "type": "reset"},
        expires_delta=timedelta(minutes=10),
    )


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None


api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
)

def skip_api_key(func):
    """
    Mark an endpoint as not requiring the API key.
    """
    func.skip_api_key = True
    return func

async def verify_api_key(
    request: Request,
    api_key: str = Security(api_key_header),
):
    
    route_endpoint = request.scope.get("endpoint")
    if getattr(route_endpoint, "skip_api_key", False):
        return None

    # Fail closed when unconfigured. The key used to have a hardcoded default in
    # committed source; now that it must come from the environment, a missing
    # value has to reject every caller rather than let an empty header match an
    # empty setting.
    expected = settings.API_KEY
    if not expected:
        logger.error("verify_api_key: API_KEY is not configured — rejecting request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
        )

    if not api_key or not secrets.compare_digest(str(api_key), expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
        )

    return api_key

 
