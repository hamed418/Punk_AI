from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from app.shared.pagination import paginate
from .repository import FAQRepository
from .schemas import (
    FAQCategoryCreate, FAQCategoryUpdate, FAQCreate, FAQUpdate, FAQCategoryResponse, FAQResponse,
    LandingFAQCreate, LandingFAQUpdate, LandingFAQResponse
)

class FAQService:
    def __init__(self, repository: FAQRepository):
        self.repository = repository

    # ── Category ────────────────────────────────────────────────────────

    async def create_category(self, db: AsyncSession, payload: FAQCategoryCreate) -> FAQCategoryResponse:
        category = await self.repository.create_category(db, payload.model_dump())
        return FAQCategoryResponse.model_validate(category)

    async def get_category(self, db: AsyncSession, category_id: str) -> FAQCategoryResponse:
        category = await self.repository.get_category_by_id(db, category_id)
        if not category:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FAQ Category not found")
        return FAQCategoryResponse.model_validate(category)

    async def get_categories(
        self, db: AsyncSession, skip: int, limit: int, 
        search: str = None, is_active: bool = None, type: str = None
    ):
        total, categories = await self.repository.get_categories(db, skip, limit, search, is_active, type)
        data = [FAQCategoryResponse.model_validate(c) for c in categories]
        page = (skip // limit) + 1 if limit > 0 else 1
        return paginate(data=data, total=total, page=page, limit=limit)

    async def update_category(self, db: AsyncSession, category_id: str, payload: FAQCategoryUpdate) -> FAQCategoryResponse:
        category = await self.repository.get_category_by_id(db, category_id)
        if not category:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FAQ Category not found")

        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(category, key, value)
        
        category = await self.repository.update_category(db, category)
        return FAQCategoryResponse.model_validate(category)

    async def delete_category(self, db: AsyncSession, category_id: str):
        category = await self.repository.get_category_by_id(db, category_id)
        if not category:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FAQ Category not found")
        
        await self.repository.delete_category(db, category)
        return {"success": True, "message": "Category deleted successfully"}

    # ── FAQ ─────────────────────────────────────────────────────────────

    async def create_faq(self, db: AsyncSession, payload: FAQCreate) -> FAQResponse:
        category = await self.repository.get_category_by_id(db, str(payload.category_id))
        if not category:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid category_id")
            
        faq = await self.repository.create_faq(db, payload.model_dump())
        return FAQResponse.model_validate(faq)

    async def get_faq(self, db: AsyncSession, faq_id: str) -> FAQResponse:
        faq = await self.repository.get_faq_by_id(db, faq_id)
        if not faq:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FAQ not found")
        return FAQResponse.model_validate(faq)

    async def get_faqs(
        self, db: AsyncSession, skip: int, limit: int, 
        search: str = None, category_id: str = None, is_active: bool = None
    ):
        total, faqs = await self.repository.get_faqs(db, skip, limit, search, category_id, is_active)
        data = [FAQResponse.model_validate(f) for f in faqs]
        page = (skip // limit) + 1 if limit > 0 else 1
        return paginate(data=data, total=total, page=page, limit=limit)

    async def update_faq(self, db: AsyncSession, faq_id: str, payload: FAQUpdate) -> FAQResponse:
        faq = await self.repository.get_faq_by_id(db, faq_id)
        if not faq:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FAQ not found")

        update_data = payload.model_dump(exclude_unset=True)
        if "category_id" in update_data and update_data["category_id"] is not None:
            category = await self.repository.get_category_by_id(db, str(update_data["category_id"]))
            if not category:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid category_id")
        
        for key, value in update_data.items():
            setattr(faq, key, value)
        
        faq = await self.repository.update_faq(db, faq)
        return FAQResponse.model_validate(faq)

    async def delete_faq(self, db: AsyncSession, faq_id: str):
        faq = await self.repository.get_faq_by_id(db, faq_id)
        if not faq:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FAQ not found")
        
        await self.repository.delete_faq(db, faq)
        return {"success": True, "message": "FAQ deleted successfully"}
    
    # ── Landing FAQ ─────────────────────────────────────────────────────

    async def create_landing_faq(self, db: AsyncSession, payload: LandingFAQCreate) -> LandingFAQResponse:
        faq = await self.repository.create_landing_faq(db, payload.model_dump())
        return LandingFAQResponse.model_validate(faq)

    async def get_landing_faq(self, db: AsyncSession, faq_id: str) -> LandingFAQResponse:
        faq = await self.repository.get_landing_faq_by_id(db, faq_id)
        if not faq:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Landing FAQ not found")
        return LandingFAQResponse.model_validate(faq)

    async def get_landing_faqs(
        self, db: AsyncSession, skip: int, limit: int, 
        search: str = None, is_active: bool = None
    ):
        total, faqs = await self.repository.get_landing_faqs(db, skip, limit, search, is_active)
        data = [LandingFAQResponse.model_validate(f) for f in faqs]
        page = (skip // limit) + 1 if limit > 0 else 1
        return paginate(data=data, total=total, page=page, limit=limit)

    async def update_landing_faq(self, db: AsyncSession, faq_id: str, payload: LandingFAQUpdate) -> LandingFAQResponse:
        faq = await self.repository.get_landing_faq_by_id(db, faq_id)
        if not faq:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Landing FAQ not found")

        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(faq, key, value)
        
        faq = await self.repository.update_landing_faq(db, faq)
        return LandingFAQResponse.model_validate(faq)

    async def delete_landing_faq(self, db: AsyncSession, faq_id: str):
        faq = await self.repository.get_landing_faq_by_id(db, faq_id)
        if not faq:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Landing FAQ not found")
        
        await self.repository.delete_landing_faq(db, faq)
        return {"success": True, "message": "Landing FAQ deleted successfully"}

