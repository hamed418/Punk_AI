from uuid import UUID
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from .repository import LegalDocRepository
from .schemas import (
    LegalDocumentCreate,
    LegalDocumentUpdate,
    LegalDocumentResponse,
    LegalDocumentPublicResponse,
    DocumentType,
    DocumentLanguage,
)

class LegalDocService:
    def __init__(self, repository: LegalDocRepository):
        self.repository = repository

    async def create_legal_document(self, db: AsyncSession, payload: LegalDocumentCreate) -> LegalDocumentResponse:
        existing = await self.repository.get_legal_document_by_version(db, version=payload.version)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A legal document with version '{payload.version}' already exists.",
            )
        document = await self.repository.create_legal_document(db, payload.model_dump())
        return LegalDocumentResponse.model_validate(document)

    async def get_public_legal_document(self, db: AsyncSession, doc_id: UUID) -> LegalDocumentPublicResponse:
        document = await self.repository.get_legal_document_by_id(db, doc_id)
        if not document or not document.is_active:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Legal document not found")
        return LegalDocumentPublicResponse.model_validate(document)

    async def get_public_legal_documents(
        self,
        db: AsyncSession,
        doc_type: Optional[DocumentType] = None,
        language: Optional[DocumentLanguage] = None,
        version: Optional[str] = None,
    ) -> List[LegalDocumentPublicResponse]:
        documents = await self.repository.get_legal_documents(
            db, doc_type=doc_type, language=language, version=version, is_active=True
        )
        return [LegalDocumentPublicResponse.model_validate(doc) for doc in documents]

    async def get_legal_document(self, db: AsyncSession, doc_id: UUID) -> LegalDocumentResponse:
        document = await self.repository.get_legal_document_by_id(db, doc_id)
        if not document:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Legal document not found")
        return LegalDocumentResponse.model_validate(document)

    async def get_legal_documents(
        self,
        db: AsyncSession,
        doc_type: Optional[DocumentType] = None,
        language: Optional[DocumentLanguage] = None,
        version: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> List[LegalDocumentResponse]:
        documents = await self.repository.get_legal_documents(
            db, doc_type=doc_type, language=language, version=version, is_active=is_active
        )
        return [LegalDocumentResponse.model_validate(doc) for doc in documents]

    async def update_legal_document(
        self, db: AsyncSession, doc_id: UUID, payload: LegalDocumentUpdate
    ) -> LegalDocumentResponse:
        document = await self.repository.get_legal_document_by_id(db, doc_id)
        if not document:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Legal document not found")

        if payload.version is not None and payload.version != document.version:
            existing = await self.repository.get_legal_document_by_version(db, version=payload.version)
            if existing and existing.id != doc_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"A legal document with version '{payload.version}' already exists.",
                )

        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(document, key, value)

        document = await self.repository.update_legal_document(db, document)
        return LegalDocumentResponse.model_validate(document)

    async def delete_legal_document(self, db: AsyncSession, doc_id: UUID):
        document = await self.repository.get_legal_document_by_id(db, doc_id)
        if not document:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Legal document not found")

        await self.repository.delete_legal_document(db, document)
        return {"success": True, "message": "Legal document deleted successfully"}
