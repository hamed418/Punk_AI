from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_admin_user, get_db
from app.modules.user.models import User
from app.shared.pagination import PaginatedResponse, PaginationParams, paginate

from .repository import UsageRepository
from .schemas import ThreadUsageRow, UserUsageRow

router = APIRouter(prefix="/usage", tags=["Admin - Usage"])
repository = UsageRepository()


@router.get("/users", response_model=PaginatedResponse[UserUsageRow])
async def get_usage_by_user(
    period: str | None = Query(None, description="YYYY-MM; omit for all-time"),
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(),
):
    """Tokens, Google Maps calls, grounding calls and Unacast requests per user."""
    rows, total = await repository.get_user_usage(
        db, period=period, skip=pagination.skip, limit=pagination.limit,
    )
    return paginate(
        data=[UserUsageRow.model_validate(r) for r in rows],
        total=total, page=pagination.page, limit=pagination.limit,
    )


@router.get("/threads", response_model=PaginatedResponse[ThreadUsageRow])
async def get_usage_by_thread(
    user_id: str | None = Query(None),
    period: str | None = Query(None, description="YYYY-MM; omit for all-time"),
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(),
):
    """Same rollup as /usage/users, grouped by chat thread instead."""
    rows, total = await repository.get_thread_usage(
        db, user_id=user_id, period=period, skip=pagination.skip, limit=pagination.limit,
    )
    return paginate(
        data=[ThreadUsageRow.model_validate(r) for r in rows],
        total=total, page=pagination.page, limit=pagination.limit,
    )
