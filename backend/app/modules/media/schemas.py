import uuid
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm", "video/mpeg"}
ALLOWED_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_VIDEO_TYPES

class MediaFileResponse(BaseModel):
    id: uuid.UUID
    original_filename: str
    content_type: str
    media_type: str
    file_size_bytes: int
    file_path: str
    conversation_id: Optional[uuid.UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}