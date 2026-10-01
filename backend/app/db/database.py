"""
app/db/database.py
Async SQLAlchemy engine and session factory.
"""
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from app.core.config import settings
from app.core.logging import logger

# ── Engine ───────────────────────────────────────────────────────────────────
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    pool_pre_ping=True,        # test liveness on checkout, discard dead conns
    pool_recycle=1800,          # drop conns older than 30 min, below server idle cutoff
    pool_size=15,
    max_overflow=15,
    connect_args={
        # asyncpg TCP keepalives: keep idle conns alive so server/proxy
        # (pgbouncer/RDS/Supabase) does not silently kill them mid-operation.
        "server_settings": {"tcp_keepalives_idle": "60"},
        "timeout": 30,             # connection acquire timeout (s)
    },
)

# ── Session factory ──────────────────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


_keepalive_task: asyncio.Task | None = None


async def _keepalive(interval: int = 120) -> None:
    """
    Touch the pool so user requests never pay the cold connect (~6s against a
    remote DB: asyncpg handshake plus the dialect's first-connect introspection).
    pool_recycle drops conns older than 280s, so an idle gap would otherwise put
    that cost on someone's login. Interval stays under the recycle window.
    """
    while True:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:  # network blip — retry next tick
            logger.warning("db keepalive failed", error=str(exc))
        await asyncio.sleep(interval)


async def init_db() -> None:
    """
    Import all models so Alembic can discover them.
    Called at startup to ensure tables exist (useful in dev).
    Production should use `alembic upgrade head`.
    """
    from app.db.models import Base  # noqa: F401

    global _keepalive_task
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))  # pay the cold connect at boot
    except Exception as exc:
        # DB down at boot: still start the keepalive so the pool warms up as
        # soon as it comes back.
        logger.warning("db warm-up failed", error=str(exc))
    _keepalive_task = asyncio.create_task(_keepalive())
    logger.info("Database engine initialized", url=settings.POSTGRES_HOST)


async def close_db() -> None:
    if _keepalive_task:
        _keepalive_task.cancel()
    await engine.dispose()
    logger.info("Database engine closed")
