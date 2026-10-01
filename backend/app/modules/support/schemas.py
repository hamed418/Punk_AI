from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from app.shared.enums import SupportStatus
from app.modules.faq.schemas import FAQCategoryResponse

class UserSummary(BaseModel):
    id: UUID
    full_name: Optional[str] = None
    email: str

    class Config:
        from_attributes = True

class SupportBase(BaseModel):
    category_id: Optional[UUID] = None
    name: str = Field(..., max_length=255)
    email: EmailStr
    problem_type: Optional[str] = None
    description: str
    status: SupportStatus = SupportStatus.OPEN

class SupportUpdate(BaseModel):
    status: Optional[SupportStatus] = None
    category_id: Optional[UUID] = None
    problem_type: Optional[str] = None
    description: Optional[str] = None

class SupportResponse(SupportBase):
    id: UUID
    user_id: Optional[UUID] = None
    attachment: Optional[str] = None
    attachment_type: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    category: Optional[FAQCategoryResponse] = None
    user: Optional[UserSummary] = None

    class Config:
        from_attributes = True
