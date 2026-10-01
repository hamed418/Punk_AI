from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_db, get_admin_user
from app.core.security import skip_api_key
from app.shared.pagination import PaginatedResponse
from app.modules.user.models import User
from .repository import FAQRepository
from .service import FAQService
from .schemas import (
    FAQCategoryCreate, FAQCategoryUpdate, FAQCategoryResponse,
    FAQCreate, FAQUpdate, FAQResponse,
    LandingFAQCreate, LandingFAQUpdate, LandingFAQResponse
)

router = APIRouter(prefix="/faq", tags=["FAQ"])

repository = FAQRepository()
service = FAQService(repository)

# ── Public APIs ─────────────────────────────────────────────────────────────

@router.get("/categories", response_model=PaginatedResponse[FAQCategoryResponse])
@skip_api_key
async def get_public_categories(
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=100),
    search: Optional[str] = None,
    type: Optional[str] = Query(None, description="faq, support, or both"),
    db: AsyncSession = Depends(get_db)
):
    """Get active FAQ Categories (Public)."""
    skip = (page - 1) * limit
    return await service.get_categories(db, skip, limit, search, is_active=True, type=type)

@router.get("/faqs", response_model=PaginatedResponse[FAQResponse])
@skip_api_key
async def get_public_faqs(
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=100),
    search: Optional[str] = None,
    category_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Get active FAQs (Public)."""
    skip = (page - 1) * limit
    return await service.get_faqs(db, skip, limit, search, category_id, is_active=True)

@router.get("/faqs/{faq_id}", response_model=FAQResponse)
@skip_api_key
async def get_public_faq(
    faq_id: str = Path(...),
    db: AsyncSession = Depends(get_db)
):
    """Get single FAQ (Public)."""
    return await service.get_faq(db, faq_id)

@router.get("/landing-faq", response_model=PaginatedResponse[LandingFAQResponse])
@skip_api_key
async def get_public_landing_faqs(
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=100),
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Get active Landing FAQs (Public)."""
    skip = (page - 1) * limit
    return await service.get_landing_faqs(db, skip, limit, search, is_active=True)

@router.get("/landing-faq/{faq_id}", response_model=LandingFAQResponse)
@skip_api_key
async def get_public_landing_faq(
    faq_id: str = Path(...),
    db: AsyncSession = Depends(get_db)
):
    """Get single Landing FAQ (Public)."""
    return await service.get_landing_faq(db, faq_id)

# ── Admin APIs: Categories ──────────────────────────────────────────────────

@router.post("/admin/categories", response_model=FAQCategoryResponse, tags=["Admin - FAQ"])
@skip_api_key
async def create_category(
    payload: FAQCategoryCreate,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin: Create FAQ Category."""
    return await service.create_category(db, payload)

@router.get("/admin/categories", response_model=PaginatedResponse[FAQCategoryResponse], tags=["Admin - FAQ"])
@skip_api_key
async def admin_get_categories(
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=100),
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    type: Optional[str] = None,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin: List all FAQ Categories."""
    skip = (page - 1) * limit
    return await service.get_categories(db, skip, limit, search, is_active, type)

@router.put("/admin/categories/{category_id}", response_model=FAQCategoryResponse, tags=["Admin - FAQ"])
@skip_api_key
async def update_category(
    category_id: str,
    payload: FAQCategoryUpdate,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin: Update FAQ Category."""
    return await service.update_category(db, category_id, payload)

@router.delete("/admin/categories/{category_id}", tags=["Admin - FAQ"])
@skip_api_key
async def delete_category(
    category_id: str,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin: Delete FAQ Category."""
    return await service.delete_category(db, category_id)

# ── Admin APIs: FAQs ────────────────────────────────────────────────────────

@router.post("/admin/faqs", response_model=FAQResponse, tags=["Admin - FAQ"])
@skip_api_key
async def create_faq(
    payload: FAQCreate,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin: Create FAQ."""
    return await service.create_faq(db, payload)

@router.get("/admin/faqs", response_model=PaginatedResponse[FAQResponse], tags=["Admin - FAQ"])
@skip_api_key
async def admin_get_faqs(
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=100),
    search: Optional[str] = None,
    category_id: Optional[str] = None,
    is_active: Optional[bool] = None,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin: List all FAQs."""
    skip = (page - 1) * limit
    return await service.get_faqs(db, skip, limit, search, category_id, is_active)

@router.put("/admin/faqs/{faq_id}", response_model=FAQResponse, tags=["Admin - FAQ"])
@skip_api_key
async def update_faq(
    faq_id: str,
    payload: FAQUpdate,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin: Update FAQ."""
    return await service.update_faq(db, faq_id, payload)

@router.delete("/admin/faqs/{faq_id}", tags=["Admin - FAQ"])
@skip_api_key
async def delete_faq(
    faq_id: str,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin: Delete FAQ."""
    return await service.delete_faq(db, faq_id)

# ── Admin APIs: Landing FAQs ────────────────────────────────────────────────

@router.post("/admin/landing-faq", response_model=LandingFAQResponse, tags=["Admin - FAQ"])
@skip_api_key
async def create_landing_faq(
    payload: LandingFAQCreate,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin: Create Landing FAQ."""
    return await service.create_landing_faq(db, payload)

@router.get("/admin/landing-faq", response_model=PaginatedResponse[LandingFAQResponse], tags=["Admin - FAQ"])
@skip_api_key
async def admin_get_landing_faqs(
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=100),
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin: List all Landing FAQs."""
    skip = (page - 1) * limit
    return await service.get_landing_faqs(db, skip, limit, search, is_active)

@router.put("/admin/landing-faq/{faq_id}", response_model=LandingFAQResponse, tags=["Admin - FAQ"])
@skip_api_key
async def update_landing_faq(
    faq_id: str,
    payload: LandingFAQUpdate,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin: Update Landing FAQ."""
    return await service.update_landing_faq(db, faq_id, payload)

@router.delete("/admin/landing-faq/{faq_id}", tags=["Admin - FAQ"])
@skip_api_key
async def delete_landing_faq(
    faq_id: str,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin: Delete Landing FAQ."""
    return await service.delete_landing_faq(db, faq_id)


