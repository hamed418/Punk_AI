from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from app.shared.enums import FAQCategoryType

class FAQCategoryBase(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    type: FAQCategoryType = FAQCategoryType.both
    is_active: bool = True

class FAQCategoryCreate(FAQCategoryBase):
    pass

class FAQCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    type: Optional[FAQCategoryType] = None
    is_active: Optional[bool] = None

class FAQCategoryResponse(FAQCategoryBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class FAQBase(BaseModel):
    category_id: UUID
    question: str
    answer: str
    is_active: bool = True

class FAQCreate(FAQBase):
    pass

class FAQUpdate(BaseModel):
    category_id: Optional[UUID] = None
    question: Optional[str] = None
    answer: Optional[str] = None
    is_active: Optional[bool] = None

class FAQResponse(FAQBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    category: Optional[FAQCategoryResponse] = None
    
    class Config:
        from_attributes = True

class LandingFAQBase(BaseModel):
    question: str
    answer: str
    is_active: bool = True

class LandingFAQCreate(LandingFAQBase):
    pass

class LandingFAQUpdate(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    is_active: Optional[bool] = None

class LandingFAQResponse(LandingFAQBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True
