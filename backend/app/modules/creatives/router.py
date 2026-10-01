"""
app/modules/creatives/router.py
───────────────────────────────
FUTURE WORK (Post-Version 1):
AI Image creative generation is excluded in Version 1 and scheduled for a future release.
The endpoint remains cleanly mounted with 503 disabled status so clients fail gracefully.
"""
import asyncio
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db
from app.db.models import CreativeGenerationJob
from app.modules.user.models import User
from app.modules.media.models import MediaFile
from app.modules.media.schemas import MediaFileResponse
from app.modules.creatives.schemas import GenerateRequest, CreativeJobResponse
from app.modules.creatives.service import _load_campaign_context, _run_job

router = APIRouter(prefix="/creatives", tags=["Creatives"])

@router.post(
    "/generate",
    response_model=CreativeJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_generation(
    req: GenerateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CreativeJobResponse:
    """Start an async creative-generation job (Future work: disabled in V1)."""
    if not settings.CREATIVE_GEN_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI image creative generation is disabled in Version 1. Please upload media assets or pick existing Page posts.",
        )

    reference_ref = None
    if req.reference_media_id:
        ref = await db.get(MediaFile, req.reference_media_id)
        if ref is None or ref.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Reference image not found.")
        reference_ref = (ref.file_path, ref.content_type)

    context = await _load_campaign_context(request, req.thread_id)

    job = CreativeGenerationJob(
        user_id=current_user.id,
        thread_id=req.thread_id,
        media_type=req.media_type,
        status="running",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    asyncio.create_task(
        _run_job(
            job.id, current_user.id, req.thread_id, req.media_type,
            req.variation_hint, context, reference_ref, req.aspect_ratio,
            req.variant_count,
        )
    )
    return CreativeJobResponse(job_id=job.id, status="running")

@router.get("/generate/{job_id}", response_model=CreativeJobResponse)
async def poll_generation(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CreativeJobResponse:
    job = await db.get(CreativeGenerationJob, job_id)
    if job is None or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found.")

    medias: list[MediaFile] = []
    if job.status == "ready":
        ids = [uuid.UUID(i) for i in (job.media_ids or [])] or (
            [job.media_id] if job.media_id else []
        )
        if ids:
            rows = (
                await db.execute(select(MediaFile).where(MediaFile.id.in_(ids)))
            ).scalars().all()
            by_id = {m.id: m for m in rows}
            medias = [by_id[i] for i in ids if i in by_id]

    return CreativeJobResponse(
        job_id=job.id,
        status=job.status,
        medias=[MediaFileResponse.model_validate(m) for m in medias],
        media=MediaFileResponse.model_validate(medias[0]) if medias else None,
        error=job.error,
    )
