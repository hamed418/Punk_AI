"""
app/services/media_store.py
───────────────────────────
Shared persistence for advertising media — uploaded OR Punk-generated.

Both the upload endpoint (``POST /media/upload``) and the creative-generation job
(``POST /creatives/generate``) end the same way: push bytes to R2, insert a
``MediaFile`` row, return it. Centralizing that here keeps a generated asset
byte-for-byte identical to an uploaded one downstream — the graph's
``collect_creatives`` interrupt and the Meta publish path only ever see a
``MediaFile`` UUID and cannot tell the two apart.
"""
from app.modules.media.models import MediaFile
# from __future__ import annotations

import re
import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger 
from app.services.storage import storage_service
from app.modules.media.repository import MediaRepository

media_repository = MediaRepository()
def _sanitize_filename(filename: str) -> str:
    """Strip unsafe characters, keep extension, cap length (mirrors api/media.py)."""
    import os

    name = os.path.basename(filename or "upload")
    name = re.sub(r"[^\w.\-]", "_", name)
    return name[:200] or "upload"


async def persist_media_bytes(
    db: AsyncSession,
    *,
    file_bytes: bytes,
    original_filename: str,
    content_type: str,
    media_type: str,
    user_id,
    conversation_id=None,
    prefix: Optional[str] = None,
) -> MediaFile:
    """Upload bytes to R2 and insert a ``MediaFile`` row; return the persisted row.

    Raises ``RuntimeError`` when R2 is unavailable — the caller surfaces it as a
    500 (upload) or a failed job (generation). A ``MediaFile`` without a real
    ``file_path`` would break the publish path that fetches the asset for Meta,
    so a storage miss must fail loudly rather than persist a dangling row.
    """
    unique_name = f"{uuid.uuid4().hex[:12]}_{_sanitize_filename(original_filename)}"
    r2_url = await storage_service.upload_file(
        file_data=file_bytes,
        file_name=unique_name,
        content_type=content_type,
        prefix=prefix or f"media/{user_id}",
    )
    if not r2_url:
        raise RuntimeError("Failed to upload media to R2 storage.")
    media = await media_repository.create_media_file(
        db=db,
        user_id=user_id,
        conversation_internal_id=conversation_id,
        filename=original_filename or "upload",
        content_type=content_type,
        media_type=media_type,
        file_size=len(file_bytes),
        file_path=r2_url,
    )
    logger.info(
        "Media persisted",
        media_id=str(media.id),
        media_type=media_type,
        size_bytes=len(file_bytes),
        user_id=str(user_id),
    )
    return media