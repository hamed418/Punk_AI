import asyncio
import uuid
from typing import Optional

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.database import AsyncSessionLocal
from app.db.models import CreativeGenerationJob
from app.modules.chat.models import Conversation
from app.services.creative_gen import generate_creatives
from app.services.media_store import persist_media_bytes
from app.services.storage import storage_service

def _merged_state_values(snap) -> dict:
    merged: dict = {}

    def _walk(s) -> None:
        if s is None:
            return
        for value in (getattr(s, "values", None) or {}).items():
            k, v = value
            if v:
                merged[k] = v
        for task in (getattr(s, "tasks", None) or ()):
            nested = getattr(task, "state", None)
            if nested is not None and not isinstance(nested, dict):
                _walk(nested)

    _walk(snap)
    return merged

async def _load_campaign_context(request: Request, thread_id: Optional[str]) -> dict:
    graph = getattr(request.app.state, "graph", None)
    if not (graph and thread_id):
        return {}
    try:
        snap = await graph.aget_state(
            {"configurable": {"thread_id": thread_id}}, subgraphs=True
        )
        values = _merged_state_values(snap)
    except Exception as exc:
        logger.warning("creatives: failed to load campaign context for %s: %s", thread_id, exc)
        return {}
    bs = values.get("campaign_builder_state") or {}
    return {
        "brief": bs.get("brief") or values.get("campaign_brief") or {},
        "user_info": values.get("user_info") or {},
        "geo": bs.get("geo_result") or values.get("geo_data") or {},
    }

async def _resolve_conversation_id(
    db: AsyncSession, thread_id: Optional[str], user_id
) -> Optional[uuid.UUID]:
    if not thread_id:
        return None
    res = await db.execute(
        select(Conversation).where(
            Conversation.thread_id == thread_id, Conversation.user_id == user_id
        )
    )
    conv = res.scalar_one_or_none()
    return conv.id if conv else None

async def _run_job(
    job_id, user_id, thread_id, media_type, variation_hint, context,
    reference_ref=None, aspect_ratio="1:1", variant_count=3,
) -> None:
    async with AsyncSessionLocal() as db:
        try:
            reference = None
            if reference_ref is not None:
                ref_path, ref_mime = reference_ref
                ref_bytes = await storage_service.download_file(ref_path)
                if not ref_bytes:
                    raise RuntimeError("Reference image could not be loaded from storage.")
                reference = (ref_bytes, ref_mime)
            variants = await generate_creatives(
                media_type, context, variation_hint, reference, aspect_ratio,
                variant_count,
            )
            conv_id = await _resolve_conversation_id(db, thread_id, user_id)
            medias = [
                await persist_media_bytes(
                    db,
                    file_bytes=data,
                    original_filename=filename,
                    content_type=content_type,
                    media_type=media_type,
                    user_id=user_id,
                    conversation_id=conv_id,
                )
                for data, content_type, filename, _prompt in variants
            ]
            job = await db.get(CreativeGenerationJob, job_id)
            if job:
                job.status = "ready"
                job.media_id = medias[0].id
                job.media_ids = [str(m.id) for m in medias]
                job.prompt = "\n\n---\n\n".join(v[3] for v in variants)
                await db.commit()
        except Exception as exc:
            logger.error("creatives: job %s failed: %s", job_id, exc)
            try:
                async with AsyncSessionLocal() as db2:
                    job = await db2.get(CreativeGenerationJob, job_id)
                    if job:
                        job.status = "failed"
                        job.error = str(exc)[:1000]
                        await db2.commit()
            except Exception:  # pragma: no cover
                logger.exception("creatives: could not mark job %s failed", job_id)
