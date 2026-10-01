import os
import re
import uuid
from typing import Optional
from fastapi import HTTPException, UploadFile, status

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.logging import logger

from app.modules.media.repository import MediaRepository
from app.modules.media.models import MediaFile
from app.modules.media.schemas import ALLOWED_TYPES, ALLOWED_IMAGE_TYPES
from app.services.media_store import persist_media_bytes
class MediaService:
    def __init__(self, repository: MediaRepository):
        self.repository = repository

    def _sanitize_filename(self, filename: str) -> str:
        name = os.path.basename(filename)
        name = re.sub(r"[^\w.\-]", "_", name)
        return name[:200]

    async def process_upload(
        self,
        db: AsyncSession,
        file: UploadFile,
        thread_id: Optional[str],
        user_id: uuid.UUID
    ) -> MediaFile:
        
        logger.info(f"File type: {file.content_type}")
         
        content_type = file.content_type or ""
        if content_type not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type '{content_type}'. Allowed: {sorted(ALLOWED_TYPES)}",
            )

        media_type = "image" if content_type in ALLOWED_IMAGE_TYPES else "video"
        max_bytes = (
            settings.MAX_IMAGE_SIZE_MB * 1024 * 1024
            if media_type == "image"
            else settings.MAX_VIDEO_SIZE_MB * 1024 * 1024
        )

        file_content = await file.read()
        file_size = len(file_content)
        logger.info(f"File size: {file_size}")
        if file_size > max_bytes:
            limit_mb = settings.MAX_IMAGE_SIZE_MB if media_type == "image" else settings.MAX_VIDEO_SIZE_MB
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File too large ({file_size / 1024 / 1024:.1f} MB). Max for {media_type}: {limit_mb} MB.",
            )

        conversation_internal_id = None
        if thread_id is not None:
            conv = await self.repository.get_conversation(db, thread_id, user_id)
            if conv is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Conversation not found.",
                )
            conversation_internal_id = conv.id
        try:
            media = await persist_media_bytes(
                db,
                file_bytes=file_content,
                original_filename=file.filename or "upload",
                content_type=content_type,
                media_type=media_type,
                user_id=user_id,
                conversation_id=conversation_internal_id,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return media