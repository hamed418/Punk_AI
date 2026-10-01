import asyncio
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import AsyncSessionLocal
import app.db.model_registry  # noqa: Ensure all models are imported before mappers are configured
from app.modules.user.models import User
from app.core.security import hash_password

logger = logging.getLogger(__name__)

async def seed_users(session: AsyncSession) -> None:
    """
    Seed default users.
    This function is idempotent:
    running it multiple times will not create duplicates.
    """

    admin_email = "admin@example.com"

    result = await session.execute(
        select(User).where(User.email == admin_email)
    )

    existing_admin = result.scalar_one_or_none()

    if existing_admin:
        logger.info("Admin user already exists. Skipping.")
        return

    admin = User(
        email=admin_email,
        password_hash=hash_password("Admin@123"),
        role="admin",
        full_name="Admin User",
    )
    session.add(admin)
    logger.info("Admin user created successfully.")


async def run_seed() -> None:
    async with AsyncSessionLocal() as session:
        try:
            await seed_users(session)

            await session.commit()

            logger.info("Database seeding completed successfully.")

        except Exception:
            await session.rollback()
            logger.exception("Database seeding failed.")
            raise


if __name__ == "__main__":
    asyncio.run(run_seed())