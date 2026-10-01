from typing import Optional
from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.modules.user.models import User

from app.modules.media.repository import MediaRepository
from app.modules.media.service import MediaService
from app.modules.media.schemas import MediaFileResponse

router = APIRouter(prefix="/media", tags=["Media"])

repository = MediaRepository()
service = MediaService(repository)

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
    return await service.process_upload(db, file, thread_id, current_user.id)
