from sqlalchemy.ext.asyncio import AsyncSession 
from sqlalchemy import select, desc
from .models import LegalDocument
from .schemas import DocumentType, DocumentLanguage
from typing import List, Optional
from uuid import UUID

class LegalDocRepository:
    async def get_legal_document_by_id(self, db: AsyncSession, doc_id: UUID):
        result = await db.execute(select(LegalDocument).where(LegalDocument.id == doc_id))
        return result.scalar_one_or_none()
    
    async def get_legal_document_by_version(self, db: AsyncSession, version: str) -> Optional[LegalDocument]:
        result = await db.execute(select(LegalDocument).where(LegalDocument.version == version))
        return result.scalar_one_or_none()

    async def get_legal_documents(
        self, db: AsyncSession,
        doc_type: Optional[DocumentType] = None,
        language: Optional[DocumentLanguage] = None,
        version: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> List[LegalDocument]:
        query = select(LegalDocument)
        if doc_type:
            query = query.where(LegalDocument.doc_type == doc_type)
        if language:
            query = query.where(LegalDocument.language == language)
        if version:
            query = query.where(LegalDocument.version == version)
        if is_active is not None:
            query = query.where(LegalDocument.is_active == is_active)
        
        query = query.order_by(desc(LegalDocument.updated_at))
        result = await db.execute(query)
        documents = result.scalars().all()
        
        return list(documents)

    async def create_legal_document(self, db: AsyncSession, data: dict) -> LegalDocument:
        document = LegalDocument(**data)
        db.add(document)
        await db.commit()
        await db.refresh(document)
        return document

    async def update_legal_document(self, db: AsyncSession, document: LegalDocument) -> LegalDocument:
        db.add(document)
        await db.commit()
        await db.refresh(document)
        return document

    async def delete_legal_document(self, db: AsyncSession, document: LegalDocument) -> None:
        await db.delete(document)
        await db.commit()