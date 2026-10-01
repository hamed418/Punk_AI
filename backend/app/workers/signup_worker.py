from __future__ import annotations

import logging

from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
)
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService
from app.core.config import settings
import app.db.model_registry

logger = logging.getLogger(__name__)


engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
)

service = AuthService(AuthRepository())

async def process_signup(
    ctx: dict,
    signup_data: dict,
) -> dict:

    email = signup_data.get("email")

    logger.info(
        "========== SIGNUP WORKER STARTED =========="
    )
    logger.info("Processing signup for email=%s", email)

    try:
        async with SessionLocal() as db:
            logger.info(
                    "db ========================================="
                     
                )
            result = await service.process_signup(
                db=db,
                payload=signup_data,
            )

            logger.info(
                "Signup completed successfully. email=%s user_id=%s",
                email,
                result.id,
            )

            return {
                "status": "completed",
                "user_id": result.id,
            }

    except Exception:
        logger.exception(
            "Signup worker failed for email=%s",
            email,
        )
        raise


