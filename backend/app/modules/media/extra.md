"""
app/api/media.py
Media upload endpoint for advertising content (demo — local file storage).
  POST /media/upload  -> upload an image or video
"""
import os
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db
from app.core.logging import logger
from app.db.models import Conversation, MediaFile, User
from app.db.schemas import (
    ALLOWED_IMAGE_TYPES,
    ALLOWED_VIDEO_TYPES,
    MediaFileResponse,
)
from app.services.media_store import persist_media_bytes

router = APIRouter(prefix="/media", tags=["Media"])

ALLOWED_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_VIDEO_TYPES


def _sanitize_filename(filename: str) -> str:
    """Remove unsafe characters from filename, keep extension."""
    name = os.path.basename(filename)
    name = re.sub(r"[^\w.\-]", "_", name)
    return name[:200]  # cap length


@router.post("/upload", response_model=MediaFileResponse, status_code=status.HTTP_201_CREATED)
async def upload_media(
    file: UploadFile = File(...),
    thread_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MediaFileResponse:
    """
    Upload an image or video file for advertising content.

    Accepted image types: JPEG, PNG, GIF, WebP (max 10 MB).
    Accepted video types: MP4, QuickTime, WebM, MPEG (max 100 MB).
    """
    # ── Validate content type ──────────────────────────────────────
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

    # ── Read file and enforce size limit ───────────────────────────
    file_content = await file.read()
    file_size = len(file_content)
    logger.info(f"File size: {file_size}")
    if file_size > max_bytes:
        limit_mb = settings.MAX_IMAGE_SIZE_MB if media_type == "image" else settings.MAX_VIDEO_SIZE_MB
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large ({file_size / 1024 / 1024:.1f} MB). Max for {media_type}: {limit_mb} MB.",
        )

    # ── Verify conversation ownership (if provided) ────────────────
    conversation_internal_id = None
    if thread_id is not None:
        result = await db.execute(
            select(Conversation).where(
                Conversation.thread_id == thread_id,
                Conversation.user_id == current_user.id,
            )
        )
        conv = result.scalar_one_or_none()
        if conv is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found.",
            )
        conversation_internal_id = conv.id

    # ── Persist to R2 + DB (shared path with creative generation) ───────
    try:
        media = await persist_media_bytes(
            db,
            file_bytes=file_content,
            original_filename=file.filename or "upload",
            content_type=content_type,
            media_type=media_type,
            user_id=current_user.id,
            conversation_id=conversation_internal_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return media
