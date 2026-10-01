from fastapi import APIRouter, Depends,Header,Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_db,get_current_user
from app.core.logging import logger
from typing import Optional
from app.modules.user.models import User
from app.shared.pagination import PaginationParams, PaginatedResponse, paginate
from .service import ChatService
from .repository import ChatRepository
from .schemas import AudiencePreviewRequest,ChatRequest,ResumeRequest,RewindRequest,ThreadResponse,ThreadListResponse,ThreadHistoryResponse,ChatMessageResponse,UpdateThreadRequest,DeleteMultipleThreadsRequest,CancelResponse

router = APIRouter(
    prefix="/chat",
    tags=["Chat"]
)

repository = ChatRepository()
service = ChatService(repository)

@router.post(
    "", 
)
async def chat_stream(
    payload: ChatRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return await service.chat_stream(
        payload,
        request,
        current_user
    )

@router.post(
    "/{session_id}/resume", 
)
async def resume_chat(
    session_id: str,
    payload: ResumeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return await service.resume_chat(
        session_id,
        payload,
        request,
        current_user
    )

@router.get("/{session_id}/stream")
async def attach_stream(
    session_id: str,
    request: Request,
    from_seq: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-attach to a turn already in flight (after a refresh or a thread switch).

    204 = nothing running; render from history + /status instead.
    """
    return await service.attach_stream(session_id, request, current_user, db, from_seq)


@router.get("/{session_id}/status")
async def get_chat_status(
    session_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Where this thread stands: running / paused-at-widget / idle, and can_undo."""
    return await service.get_status(session_id, request, current_user, db)


@router.post("/{session_id}/cancel", response_model=CancelResponse)
async def cancel_chat(
    session_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stop button. Also un-submits an answer the graph never consumed."""
    return await service.cancel_run(session_id, request, current_user, db)


@router.post("/{session_id}/rewind")
async def rewind(
    session_id: str,
    payload: RewindRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Undo, edit or retry a previous answer. See ChatService.rewind."""
    return await service.rewind(session_id, payload, request, current_user)


@router.post("/new", response_model=ThreadResponse)
async def create_new_chat(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Explicitly create a new chat session."""
    return await service.create_new_chat(current_user,db)

@router.get("/threads", response_model=PaginatedResponse[ThreadResponse])
async def list_user_threads(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends()
) -> PaginatedResponse[ThreadResponse]:
    """List all chat sessions for the current user."""
    threads, total = await service.find_specific_user_conversation(current_user,db, pagination.skip, pagination.limit)
    return paginate(
        total=total,
        page=pagination.page,
        limit=pagination.limit,
        data=threads
    )

@router.get("/history/{thread_id}", response_model=ThreadHistoryResponse)
async def get_conversation_history(
    thread_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ThreadHistoryResponse:
    conversation,history_result = await service.get_conversation_history(current_user,thread_id,db)
    return ThreadHistoryResponse(
        id=conversation.id,
        thread_id=conversation.thread_id,
        title=conversation.title,
        status=conversation.status.value,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[
            ChatMessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                question=m.question,
                thinking=m.thinking,
                langchain_data=m.langchain_data,
                checkpoint_id=m.checkpoint_id,
                checkpoint_ns=m.checkpoint_ns,
                created_at=m.created_at,
            ) for m in history_result]
    )

@router.delete("/thread/{thread_id}", response_model=dict)
async def delete_conversation(
    thread_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Explicitly create a new chat session."""
    return await service.delete_conversation(current_user,thread_id,db)

@router.delete("/threads/multiple", response_model=dict)
async def delete_multiple_conversations(
    payload: DeleteMultipleThreadsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete multiple chat sessions."""
    return await service.delete_multiple_conversations(current_user, payload.thread_ids, db)

@router.put("/thread/update/{thread_id}")
async def update_thread(
    thread_id: str,
    payload: UpdateThreadRequest, 
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await service.update_thread(current_user,thread_id,db,payload)
 
@router.get("/thread/starred", response_model=ThreadListResponse)
async def get_starred_threads(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ThreadListResponse:
    thread_data = await service.get_starred_threads(current_user,db)
    return ThreadListResponse(
        threads=thread_data,
        total=len(thread_data)
    )

@router.post("/{session_id}/audience/preview")
async def preview_audience(
    session_id: str,
    payload: AudiencePreviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Live recount for the audience layer builder — see ChatService.preview_audience."""
    return await service.preview_audience(session_id, payload, current_user, db)


@router.get("/state/{session_id}")
async def get_agent_state(
    session_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_agent_state(session_id,request,current_user,db)