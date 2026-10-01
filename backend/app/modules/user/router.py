from typing import   Optional
from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_db, get_current_user, get_admin_user
from app.core.limiter import limiter
from app.shared.pagination import PaginatedResponse
from .models import User
from .service import UserService
from .repository import UserRepository
from .schemas import (
    UserUpdateRequest,
    UserResponse,
    ChangePasswordRequest,
    UserListResponse,
    UserDetailsResponse,
    AdminRoleUpdateRequest,
    AdminStatusUpdateRequest,
    AdminVerificationUpdateRequest,
    ImpersonateResponse,
    StopImpersonationResponse,
    UserStatsResponse,
)

router = APIRouter(
    prefix="/user",
    tags=["User Profile"]
)

repository = UserRepository()
service = UserService(repository)

@router.get(
    "/stats",
    response_model=UserStatsResponse,
    tags=["Admin - Users"],
    summary="User Overview Stats",
    description="Returns aggregate user statistics for the admin dashboard overview cards (total, active, new this month, suspended, plan breakdown)."
)
async def get_user_stats(
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin only: aggregated user stats for overview cards."""
    return await service.user_stats(db)


@router.get(
    "/list",
    response_model=PaginatedResponse[UserListResponse],
    tags=["Admin - Users"],
    summary="List Users",
    description="Paginated user list. search= matches name OR email. plan= filters by active subscription plan name.",
)

async def list_users(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=1000, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by name or email"),
    role: Optional[str] = Query(None, description="Filter by role"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    date: Optional[str] = Query(None, description="Filter by creation date (YYYY-MM-DD)"),
    plan: Optional[str] = Query(None, description="Filter by subscription plan name (e.g. 'PRO', 'Starter')"),
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a list of all users."""
    skip = (page - 1) * limit
    return await service.list_users(db, skip, limit, search, role, is_active, date, plan)

@router.get(
    "/{user_id}/details",
    response_model=UserDetailsResponse,
    tags=["Admin - Users"]
)
async def get_user_details(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed analytics for a specific user."""
    return await service.get_user_details(db, user_id)

@router.get(
    "/me",
    response_model=UserResponse
)
async def user_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    return await service.user_me(db, current_user)

@router.patch("/me", response_model=UserResponse)
async def update_me(
    payload: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Update current user's profile."""
    return await service.user_update(db, current_user, payload)

@router.post("/change-password")
@limiter.limit("10/minute")
async def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.change_password(db, current_user, payload)

# ── Admin Endpoints ─────────────────────────────────────────────────────────
 
@router.patch("/{user_id}/role", response_model=UserResponse, tags=["Admin - Users"])
async def update_user_role(
    user_id: str,
    payload: AdminRoleUpdateRequest,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin only: Change a user's role."""
    return await service.admin_update_role(db, user_id, payload)

@router.patch("/{user_id}/status", response_model=UserResponse, tags=["Admin - Users"])
async def update_user_status(
    user_id: str,
    payload: AdminStatusUpdateRequest,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin only: Activate or deactivate a user."""
    return await service.admin_update_status(db, user_id, payload)

@router.patch("/{user_id}/verification", response_model=UserResponse, tags=["Admin - Users"])
async def update_user_verification(
    user_id: str,
    payload: AdminVerificationUpdateRequest,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin only: Manually verify or unverify a user."""
    return await service.admin_update_verification(db, user_id, payload)

@router.post("/stop-impersonation", response_model=StopImpersonationResponse, tags=["Admin - Users"])
async def stop_impersonation(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Stop impersonating the current user and revoke the impersonation session."""
    return await service.stop_impersonation(db, request, current_user)

@router.post("/{user_id}/impersonate", response_model=ImpersonateResponse, tags=["Admin - Users"])
async def impersonate_user(
    request: Request,
    user_id: str,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin only: Generate an access token to login as another user."""
    return await service.impersonate_user(db, request, user_id, admin_user)

