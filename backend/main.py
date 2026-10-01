"""
main.py
FastAPI application factory with lifespan management.
"""
import asyncio
import os
import sys
from contextlib import asynccontextmanager

# Windows: psycopg's async mode refuses the default ProactorEventLoop, so the
# LangGraph Postgres checkpointer never connects — its pool retries forever and
# the lifespan below catches the failure as a WARNING. The result is a server
# that starts, passes /health, and has chat silently dead:
#
#     Psycopg cannot use the 'ProactorEventLoop' to run in async mode.
#
# This must run before uvicorn builds its loop, so it lives at import time
# rather than in the lifespan. No effect on Linux or Cloud Run.
if sys.platform == "win32":  # pragma: no cover - platform specific
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from typing import AsyncGenerator

from fastapi import FastAPI, Request, status,Depends
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.security import verify_api_key 
from app.core.logging import configure_logging, logger
from app.db.database import close_db, init_db 
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware
from app.core.limiter import limiter

# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    configure_logging()
    logger.info(
        "Starting AI Ad Consultant",
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
    )
    try:
        await init_db()
    except Exception as db_err:
        logger.warning("init_db at startup failed (continuing)", error=str(db_err))

    try:
        from app.graph.graph import get_graph
        app.state.graph = await get_graph()
        logger.info("LangGraph agent compiled and attached to app.state.graph")
    except Exception as graph_err:
        logger.warning("LangGraph init failed (chat disabled)", error=str(graph_err))
        app.state.graph = None

    # Redis is an optimisation of VISIBILITY across Cloud Run instances, never a
    # new way to fail — see app/core/redis.py. Ping it once so an unreachable
    # host is reported at startup rather than discovered per-request, and so the
    # unavailable flag starts in the right state.
    try:
        from app.core.redis import ping as redis_ping, redis_enabled

        app.state.redis_ok = await redis_ping() if redis_enabled() else False
        if not settings.REDIS_URL:
            logger.info(
                "Redis not configured - chat run state and rate limiting stay "
                "per-instance (fine for a single instance, not for maxScale>1)"
            )
    except Exception as redis_err:
        app.state.redis_ok = False
        logger.warning("Redis startup check failed (continuing)", error=str(redis_err))

    logger.info("Services initialized")
    yield
    # ── Teardown ──────────────────────────────────────────────────────────
    try:
        # Stop live agent runs first so each one's persist gets a chance to commit
        # while the checkpointer pool is still open.
        from app.modules.chat.runs import cancel_all
        await cancel_all()
    except Exception as run_err:
        logger.warning("Cancelling live chat runs failed", error=str(run_err))

    try:
        from app.graph.graph import close_checkpointer
        await close_checkpointer()
    except Exception as cp_err:
        logger.warning("Checkpointer pool close failed", error=str(cp_err))

    try:
        from app.core.redis import aclose as redis_close
        await redis_close()
    except Exception as redis_err:
        logger.warning("Redis close failed", error=str(redis_err))

    try:
        # The Unacast querier lazily builds one httpx.AsyncClient and caches it
        # in get_maid_querier's module global, so its connection pool outlives
        # every request. No-op when no querier (or no client yet) exists.
        from app.graph.maid_query import close_maid_querier
        await close_maid_querier()
    except Exception as maid_err:
        logger.warning("MAID querier close failed", error=str(maid_err))

    await close_db()
    logger.info("Application shutdown complete")


tags_metadata = [
    # ── Admin Panel APIs ──────────────────────────────────────────────────────────
    {
        "name": "Admin - Auth",
        "description": "Admin Panel: Authentication, session management, and admin profile for admin/super_admin accounts.",
    },
    {
        "name": "Admin - Analytics",
        "description": "Admin Panel: Overview statistics, performance metrics, and velocity charts.",
    },
    {
        "name": "Admin - Users",
        "description": "Admin Panel: User directory, details, role/status updates, verification, and impersonation.",
    },
    {
        "name": "Admin - Subscriptions",
        "description": "Admin Panel: Subscription plans management (Create, Read, Update, Delete plans).",
    },
    {
        "name": "Admin - Audit Logs",
        "description": "Admin Panel: System and user activity audit logging.",
    },
    {
        "name": "Admin - FAQ",
        "description": "Admin Panel: FAQ categories and questions management.",
    },
    {
        "name": "Admin - Support",
        "description": "Admin Panel: Support ticket triage, updates, and management.",
    },
    {
        "name": "Admin - Waitlist",
        "description": "Admin Panel: Waitlist leads management and pagination.",
    },
    # ── Client & Core Application APIs ───────────────────────────────────────────
    {
        "name": "Auth & Onboarding",
        "description": "User authentication, registration, password management, and sessions.",
    },
    {
        "name": "User Profile",
        "description": "Current user profile management and settings.",
    },
    {
        "name": "Chat",
        "description": "AI Agent ad consultant conversations and assistant tools.",
    },
    {
        "name": "Public Chat",
        "description": "Unauthenticated public shared chat conversation viewing.",
    },
    {
        "name": "Campaigns",
        "description": "Ad campaign creation, management, and Meta Ads synchronization.",
    },
    {
        "name": "Ad Platforms",
        "description": "Third-party ad platform integration and authentication.",
    },
    {
        "name": "Creatives",
        "description": "Ad creative generation, prompts, and copy.",
    },
    {
        "name": "Media",
        "description": "Media uploads and asset storage.",
    },
    {
        "name": "Payment",
        "description": "Stripe checkout sessions and payment webhooks.",
    },
    {
        "name": "Subscriptions",
        "description": "User subscription status, token balances, and transaction history.",
    },
    {
        "name": "Conversion Tracking",
        "description": "Conversion and event tracking API.",
    },
    {
        "name": "Support",
        "description": "User support ticket submission and history.",
    },
    {
        "name": "FAQ",
        "description": "Public knowledge base and frequently asked questions.",
    },
    {
        "name": "Map",
        "description": "Geographical mapping and location services.",
    },
    {
        "name": "Waitlist",
        "description": "Public waitlist registration.",
    },
    {
        "name": "Coupon",
        "description": "Coupon management, discount validation, redemptions, and audit tracking.",
    },
    {
        "name": "System",
        "description": "Health checks and system status endpoints.",
    },
]


# ── App factory ──────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "AI Advertising Consultant – multi-tenant SaaS powered by LangGraph. "
            "Generate, manage, and publish advertising campaigns for Google and Meta Ads."
        ),
        openapi_tags=tags_metadata,
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        lifespan=lifespan,
    )
 
    #  rate limiting added 
    app.state.limiter = limiter
    app.add_exception_handler(
        RateLimitExceeded,
        _rate_limit_exceeded_handler,
    )
    app.add_middleware(SlowAPIMiddleware)

    # ── CORS ──────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception handlers ────────────────────────────────────────────────

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        origin = request.headers.get("origin")
        headers = {}
        if origin and (origin in settings.ALLOWED_ORIGINS or "*" in settings.ALLOWED_ORIGINS):
            headers["Access-Control-Allow-Origin"] = origin
            headers["Access-Control-Allow-Credentials"] = "true"
        error = exc.errors()[0]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": error["msg"], "body": str(exc.body)},
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception", error=str(exc), path=str(request.url))
        
        error_message = str(exc)
        
        # Clean up database error messages for the frontend
        if "[SQL:" in error_message:
            error_message = error_message.split("[SQL:")[0]
            
        if ">:" in error_message:
            error_message = error_message.split(">:")[-1]
        elif "):" in error_message:
            error_message = error_message.split("):")[-1]
            
        error_message = error_message.strip()
        
        origin = request.headers.get("origin")
        headers = {}
        if origin and (origin in settings.ALLOWED_ORIGINS or "*" in settings.ALLOWED_ORIGINS):
            headers["Access-Control-Allow-Origin"] = origin
            headers["Access-Control-Allow-Credentials"] = "true"

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": error_message, 
                "details": error_message,
                "detail": error_message,
                "error_type": type(exc).__name__
            },
            headers=headers,
        )

    # ── Routers ───────────────────────────────────────────────────────────
    from app.api.router import api_router as api_router
    from app.modules.public.router import router as public_chat_router
    
    app.include_router(
        api_router,
        dependencies=[Depends(verify_api_key)]
    ) 

    app.include_router(public_chat_router) 


    @app.get("/", tags=["System"])
    async def root():
        return {
            "name": settings.APP_NAME,
            "status": "ok",
            "version": settings.APP_VERSION,
            "health": "/health",
        }

    # ── Health check ──────────────────────────────────────────────────────
    @app.get("/health", tags=["System"])
    async def health_check():
        return {
            "status": "healthy",
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
        }

    return app


# Reload trigger for subscription and faq modules
from app.modules.subscription import schemas as _sub_schemas
from app.modules.faq import schemas as _faq_schemas
app = create_app()





if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.APP_PORT,
        reload=settings.DEBUG,
        # log_level="debug" if settings.DEBUG else "info",
        log_level="warning",
    )
 