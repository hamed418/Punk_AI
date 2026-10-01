from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_db
from app.modules.chat.service import ChatService
from app.modules.chat.repository import ChatRepository
from app.modules.chat.schemas import ThreadHistoryResponse, ChatMessageResponse

router = APIRouter(
    prefix="/public/chat",
    tags=["Public Chat"]
)

repository = ChatRepository()
service = ChatService(repository)

@router.get("/{thread_id}", response_model=ThreadHistoryResponse)
async def get_public_chat_data(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
) -> ThreadHistoryResponse:
    """Fetch chat data by thread_id without user authentication."""
    conversation, history_result = await service.get_public_conversation_history(thread_id, db)
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
                created_at=m.created_at,
            ) for m in history_result
        ]
    )
