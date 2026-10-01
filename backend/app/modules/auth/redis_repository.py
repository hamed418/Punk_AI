import hashlib
from typing import Optional

from redis.asyncio import Redis

from app.core.redis import get_client, key as rkey


class AuthRedisRepository:

    SESSION_TTL = 1800
    OTP_TTL = 300
    JOB_TTL = 3600

    def __init__(
        self,
        redis: Optional[Redis] = None,
    ) -> None:
        self.redis = redis or get_client()

    def _get_redis(self) -> Redis:
        if self.redis is None:
            raise RuntimeError("Redis is disabled or unavailable, which is required for signup.")
        return self.redis

    # -------------------------
    # Signup Session
    # -------------------------

    async def create_signup_session(
        self,
        signup_token: str,
        email: str,
    ) -> None:
        redis = self._get_redis()
        key = rkey("signup", "session", signup_token)

        await redis.hset(  # type: ignore
            key,
            mapping={
                "email": email,
                "email_verified": "false",
            },
        )

        await redis.expire(  # type: ignore
            key,
            self.SESSION_TTL,
        )

    async def get_signup_session(
        self,
        signup_token: str,
    ) -> dict[str, str]:
        redis = self._get_redis()
        key = rkey("signup", "session", signup_token)

        return await redis.hgetall(key)  # type: ignore

    async def mark_email_verified(
        self,
        signup_token: str,
    ) -> None:
        redis = self._get_redis()
        key = rkey("signup", "session", signup_token)

        await redis.hset(  # type: ignore
            key,
            mapping={"email_verified": "true"},
        )

    async def delete_signup_session(
        self,
        signup_token: str,
    ) -> None:
        redis = self._get_redis()
        key = rkey("signup", "session", signup_token)

        await redis.delete(key)

    # -------------------------
    # OTP
    # -------------------------

    async def save_otp(
        self,
        signup_token: str,
        otp: str,
    ) -> None:
        redis = self._get_redis()
        key = rkey("signup", "otp", signup_token)

        otp_hash = hashlib.sha256(
            otp.encode()
        ).hexdigest()

        await redis.set(
            key,
            otp_hash,
            ex=self.OTP_TTL,
        )

    async def get_otp_hash(
        self,
        signup_token: str,
    ) -> str | None:
        redis = self._get_redis()
        key = rkey("signup", "otp", signup_token)

        return await redis.get(key)

    async def delete_otp(
        self,
        signup_token: str,
    ) -> None:
        redis = self._get_redis()
        key = rkey("signup", "otp", signup_token)

        await redis.delete(key)

    # -------------------------
    # Login OTP
    # -------------------------

    async def create_login_otp(
        self,
        login_token: str,
        email: str,
        otp: str,
    ) -> None:
        redis = self._get_redis()
        key = rkey("login", "otp", login_token)

        otp_hash = hashlib.sha256(
            otp.encode()
        ).hexdigest()

        await redis.hset(
            key,
            mapping={
                "email": email,
                "otp_hash": otp_hash,
            },
        )
        await redis.expire(key, self.OTP_TTL)

    async def get_login_otp_data(
        self,
        login_token: str,
    ) -> dict | None:
        redis = self._get_redis()
        key = rkey("login", "otp", login_token)

        data = await redis.hgetall(key)
        return data if data else None

    async def delete_login_otp(
        self,
        login_token: str,
    ) -> None:
        redis = self._get_redis()
        key = rkey("login", "otp", login_token)

        await redis.delete(key)

    # -------------------------
    # Signup Job
    # -------------------------

    async def create_job(
        self,
        job_id: str,
    ) -> None:
        redis = self._get_redis()
        key = rkey("signup", "job", job_id)

        await redis.hset(  # type: ignore
            key,
            mapping={
                "status": "queued",
            },
        )

        await redis.expire(  # type: ignore
            key,
            self.JOB_TTL,
        )

    async def update_job(
        self,
        job_id: str,
        *,
        status: str,
        user_id: str | None = None,
        error: str | None = None,
    ) -> None:
        redis = self._get_redis()
        key = rkey("signup", "job", job_id)

        data: dict[str, str] = {
            "status": status,
        }

        if user_id is not None:
            data["user_id"] = str(user_id)

        if error is not None:
            data["error"] = error

        await redis.hset(  # type: ignore
            key,
            mapping=data,
        )

    async def get_job(
        self,
        job_id: str,
    ) -> dict[str, str]:
        redis = self._get_redis()
        key = rkey("signup", "job", job_id)

        return await redis.hgetall(key)  # type: ignore