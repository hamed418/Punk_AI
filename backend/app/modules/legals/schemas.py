from typing import Optional
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field
import enum

class DocumentType(str, enum.Enum):
    TERMS_OF_SERVICE = "Terms of Service"
    PRIVACY_POLICY = "Privacy Policy"

class DocumentLanguage(str, enum.Enum):
    ENGLISH = "English"
    FRANCE = "French"
    
class LegalDocumentPublicResponse(BaseModel):
    id: UUID
    doc_type: DocumentType
    content: str
    version: str
    language: DocumentLanguage
    created_at: datetime

    class Config:
        from_attributes = True

class LegalDocumentResponse(LegalDocumentPublicResponse):
    is_active: bool
    updated_by: str
    updated_at: datetime

    class Config:
        from_attributes = True

class LegalDocumentCreate(BaseModel):
    doc_type: DocumentType
    content: str
    version: str
    language: DocumentLanguage
    is_active: bool = True
    updated_by: str
    
class LegalDocumentUpdate(BaseModel):
    content: Optional[str] = None
    version: Optional[str] = None
    language: Optional[DocumentLanguage] = None
    is_active: Optional[bool] = None
    updated_by: Optional[str] = None
    