import uuid
from typing import Literal, Optional
from pydantic import BaseModel, Field
from app.modules.media.schemas import MediaFileResponse

class GenerateRequest(BaseModel):
    media_type: Literal["image"]
    thread_id: Optional[str] = None
    variation_hint: Optional[str] = None
    reference_media_id: Optional[uuid.UUID] = None
    aspect_ratio: Literal["1:1", "4:5", "1.91:1", "9:16"] = "1:1"
    variant_count: int = Field(default=3, ge=1, le=4)

class CreativeJobResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    medias: list[MediaFileResponse] = []
    media: Optional[MediaFileResponse] = None
    error: Optional[str] = None
