from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Path, Form, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import EmailStr
from app.core.dependencies import get_db, get_current_user, get_admin_user, get_optional_user
from app.shared.pagination import PaginatedResponse
from app.modules.user.models import User
from .repository import SupportRepository
from .service import SupportService
from .schemas import SupportUpdate, SupportResponse

router = APIRouter(prefix="/support", tags=["Support"])

repository = SupportRepository()
service = SupportService(repository)

# ── User APIs ───────────────────────────────────────────────────────────────

@router.post("/tickets", response_model=SupportResponse)
async def create_support_ticket(
    name: str = Form(...),
    email: EmailStr = Form(...),
    description: str = Form(...),
    category_id: Optional[str] = Form(None),
    problem_type: Optional[str] = Form(None),
    attachment: Optional[UploadFile] = File(None),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """User: Create a support ticket."""
    user_id = None
    if current_user:
        user_id = str(current_user.id)
    else:
        # Try to find user by email
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user:
            user_id = str(user.id)

    data = {
        "name": name,
        "email": email,
        "description": description,
        "category_id": category_id,
        "problem_type": problem_type,
        "user_id": user_id
    }
    return await service.create_support(db, data, attachment)

@router.get("/me", response_model=PaginatedResponse[SupportResponse])
async def get_my_supports(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """User: List my own support tickets."""
    skip = (page - 1) * limit
    return await service.get_supports(db, skip, limit, user_id=str(current_user.id), status_val=status)

@router.get("/me/{support_id}", response_model=SupportResponse)
async def get_my_support(
    support_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """User: Get single support ticket details."""
    support = await service.get_support(db, support_id)
    if str(support.user_id) != str(current_user.id):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Not authorized to view this ticket.")
    return support

# ── Admin APIs ──────────────────────────────────────────────────────────────

@router.get("/admin/tickets", response_model=PaginatedResponse[SupportResponse], tags=["Admin - Support"])
async def admin_get_tickets(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    category_id: Optional[str] = None,
    status: Optional[str] = None,
    problem_type: Optional[str] = None,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin: List all support tickets."""
    skip = (page - 1) * limit
    return await service.get_supports(
        db, skip, limit, search=search, category_id=category_id, 
        status_val=status, problem_type=problem_type
    )

@router.get("/admin/tickets/{support_id}", response_model=SupportResponse, tags=["Admin - Support"])
async def admin_get_ticket(
    support_id: str,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin: Get single support ticket."""
    return await service.get_support(db, support_id)

@router.patch("/admin/tickets/{support_id}", response_model=SupportResponse, tags=["Admin - Support"])
async def admin_update_ticket(
    support_id: str,
    payload: SupportUpdate,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin: Update support ticket status or category."""
    return await service.update_support(db, support_id, payload)

@router.delete("/admin/tickets/{support_id}", tags=["Admin - Support"])
async def admin_delete_ticket(
    support_id: str,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin: Delete support ticket."""
    return await service.delete_support(db, support_id)
