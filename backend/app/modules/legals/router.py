from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_db, get_admin_user
from app.modules.user.models import User
from .repository import LegalDocRepository
from .service import LegalDocService
from .schemas import (
    LegalDocumentCreate,
    LegalDocumentUpdate,
    LegalDocumentResponse,
    LegalDocumentPublicResponse,
    DocumentType,
    DocumentLanguage,
)

router = APIRouter(prefix="/legals", tags=["Legal Documents"])

repository = LegalDocRepository()
service = LegalDocService(repository)

# Public APIs

@router.get("", response_model=List[LegalDocumentPublicResponse])
async def get_public_legal_documents(
    doc_type: Optional[DocumentType] = Query(None, description="Document type filter"),
    language: Optional[DocumentLanguage] = Query(None, description="Document language filter"),
    version: Optional[str] = Query(None, description="Document version filter"),
    db: AsyncSession = Depends(get_db),
):
    """Get Legal Documents (Public)."""
    return await service.get_public_legal_documents(db, doc_type=doc_type, language=language, version=version)


# Admin APIs

@router.post("/admin", response_model=LegalDocumentResponse)
async def create_legal_document(
    payload: LegalDocumentCreate,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin: Create Legal Document."""
    return await service.create_legal_document(db, payload)


@router.get("/admin", response_model=List[LegalDocumentResponse])
async def admin_get_legal_documents(
    doc_type: Optional[DocumentType] = Query(None, description="Document type filter"),
    language: Optional[DocumentLanguage] = Query(None, description="Document language filter"),
    version: Optional[str] = Query(None, description="Document version filter"),
    is_active: Optional[bool] = Query(None, description="Document active status filter"),
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin: List all Legal Documents."""
    return await service.get_legal_documents(
        db, doc_type=doc_type, language=language, version=version, is_active=is_active
    )


@router.put("/admin/{doc_id}", response_model=LegalDocumentResponse)
async def update_legal_document(
    doc_id: UUID,
    payload: LegalDocumentUpdate,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin: Update Legal Document."""
    return await service.update_legal_document(db, doc_id, payload)


@router.delete("/admin/{doc_id}")
async def delete_legal_document(
    doc_id: UUID,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin: Delete Legal Document."""
    return await service.delete_legal_document(db, doc_id)

@router.get("/{doc_id}", response_model=LegalDocumentPublicResponse)
async def get_public_legal_document(
    doc_id: UUID = Path(...),
    db: AsyncSession = Depends(get_db),
):
    """Get single Legal Document (Public)."""
    return await service.get_public_legal_document(db, doc_id)
