import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.media.models import MediaFile
from app.modules.chat.models import Conversation

class MediaRepository:
    async def get_conversation(self, db: AsyncSession, thread_id: str, user_id: uuid.UUID) -> Optional[Conversation]:
        result = await db.execute(
            select(Conversation).where(
                Conversation.thread_id == thread_id,
                Conversation.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_media_file(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        conversation_internal_id: Optional[uuid.UUID],
        filename: str,
        content_type: str,
        media_type: str,
        file_size: int,
        file_path: str
    ) -> MediaFile:
        media = MediaFile(
            user_id=user_id,
            conversation_id=conversation_internal_id,
            original_filename=filename,
            content_type=content_type,
            media_type=media_type,
            file_size_bytes=file_size,
            file_path=file_path,
        )
        db.add(media)
        await db.commit() 
        await db.refresh(media)
        return media