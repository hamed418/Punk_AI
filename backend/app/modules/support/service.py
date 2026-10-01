import os
import re
import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status, UploadFile
from app.shared.pagination import paginate
from app.core.config import settings
from app.services.storage import storage_service
from .repository import SupportRepository
from .schemas import SupportUpdate, SupportResponse

class SupportService:
    def __init__(self, repository: SupportRepository):
        self.repository = repository
        
        self.ALLOWED_MIME_TYPES = [
            "image/jpeg",
            "image/png",
            "image/webp",
            "image/gif",
            "application/pdf",
            "video/mp4",
            "video/webm",
            "video/quicktime",
            "video/x-msvideo",
            "video/mpeg",
            "video/ogg",
        ]
        self.MAX_ATTACHMENT_SIZE_MB = 10

    def _sanitize_filename(self, filename: str) -> str:
        name = os.path.basename(filename)
        name = re.sub(r"[^\w.\-]", "_", name)
        return name[:200]

    async def _handle_attachment(self, file: UploadFile, user_id: str) -> Optional[str]:
        content_type = file.content_type or ""
        
        # Fallback to extension check if content_type is missing or generic
        if not content_type or content_type in ["application/octet-stream", "binary/octet-stream"]:
            ext = os.path.splitext(file.filename or "")[1].lower()
            ext_map = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
                ".gif": "image/gif",
                ".pdf": "application/pdf",
                ".mp4": "video/mp4",
                ".webm": "video/webm",
                ".mov": "video/quicktime",
                ".avi": "video/x-msvideo",
            }
            if ext in ext_map:
                content_type = ext_map[ext]

        if content_type not in self.ALLOWED_MIME_TYPES and not content_type.startswith("video/"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type '{content_type}'. Allowed: {', '.join(self.ALLOWED_MIME_TYPES)}",
            )
            
        file_content = await file.read()
        file_size = len(file_content)
        
        max_bytes = self.MAX_ATTACHMENT_SIZE_MB * 1024 * 1024
        if file_size > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File too large ({file_size / 1024 / 1024:.1f} MB). Max allowed is {self.MAX_ATTACHMENT_SIZE_MB} MB.",
            )
            
        unique_name = f"{uuid.uuid4().hex[:12]}_{self._sanitize_filename(file.filename or 'upload')}"
        r2_url = await storage_service.upload_file(
            file_data=file_content,
            file_name=unique_name,
            content_type=content_type,
            prefix=f"support/{user_id}" if user_id else "support/guests"
        )
        
        if not r2_url:
            raise HTTPException(status_code=500, detail="Failed to upload attachment to storage.")
            
        return r2_url

    async def create_support(
        self, db: AsyncSession, data: dict, attachment: Optional[UploadFile] = None
    ) -> SupportResponse:
        
        # Verify category exists if provided
        if data.get("category_id"):
            from app.modules.faq.repository import FAQRepository
            faq_repo = FAQRepository()
            category = await faq_repo.get_category_by_id(db, str(data["category_id"]))
            if not category:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid category_id")

        if attachment:
            r2_url = await self._handle_attachment(attachment, str(data.get("user_id", "guest")))
            data["attachment"] = r2_url
            data["attachment_type"] = attachment.content_type

        support = await self.repository.create_support(db, data)
        return SupportResponse.model_validate(support)

    async def get_support(self, db: AsyncSession, support_id: str) -> SupportResponse:
        support = await self.repository.get_support_by_id(db, support_id)
        if not support:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found")
        return SupportResponse.model_validate(support)

    async def get_supports(
        self, db: AsyncSession, skip: int, limit: int, 
        search: str = None, category_id: str = None, user_id: str = None, 
        status_val: str = None, problem_type: str = None
    ):
        total, supports = await self.repository.get_supports(
            db, skip, limit, search, category_id, user_id, status_val, problem_type
        )
        data = [SupportResponse.model_validate(s) for s in supports]
        page = (skip // limit) + 1 if limit > 0 else 1
        return paginate(data=data, total=total, page=page, limit=limit)

    async def update_support(self, db: AsyncSession, support_id: str, payload: SupportUpdate) -> SupportResponse:
        support = await self.repository.get_support_by_id(db, support_id)
        if not support:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found")

        update_data = payload.model_dump(exclude_unset=True)
        if "category_id" in update_data and update_data["category_id"] is not None:
            from app.modules.faq.repository import FAQRepository
            faq_repo = FAQRepository()
            category = await faq_repo.get_category_by_id(db, str(update_data["category_id"]))
            if not category:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid category_id")
        
        for key, value in update_data.items():
            setattr(support, key, value)
        
        support = await self.repository.update_support(db, support)
        return SupportResponse.model_validate(support)

    async def delete_support(self, db: AsyncSession, support_id: str):
        support = await self.repository.get_support_by_id(db, support_id)
        if not support:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found")
        
        # Optionally delete attachment from R2
        if support.attachment:
            await storage_service.delete_file(support.attachment)
            
        await self.repository.delete_support(db, support)
        return {"success": True, "message": "Support ticket deleted successfully"}
