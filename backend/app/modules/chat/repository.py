from sqlalchemy import select, func,desc,asc,delete
from sqlalchemy.ext.asyncio import AsyncSession
 
from .models import Conversation,ChatMessage


class ChatRepository:
    async def get_all(self, db: AsyncSession, skip: int, limit: int):
        total_result = await db.execute(select(func.count()).select_from(Conversation))
        total = total_result.scalar()
        result = await db.execute(
            select(Conversation)
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all(), total
        
    async def find_specific_user_all_chat(self, db:AsyncSession, user_id:str, skip: int = 0, limit: int = 10):
        total_result = await db.execute(select(func.count()).select_from(Conversation).where(Conversation.user_id == user_id))
        total = total_result.scalar()
        
        result = await db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(desc(Conversation.created_at))
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all(), total

    async def find_specific_user_chat(self, db: AsyncSession, session_id: str, user_id:str ):
        result = await db.execute(
            select(Conversation)
            .where(
                Conversation.thread_id==session_id,
                Conversation.user_id == user_id
            )
        )
        return result.scalars().first()

    async def find_chat_by_thread_id(self, db: AsyncSession, thread_id: str):
        result = await db.execute(
            select(Conversation)
            .where(
                Conversation.thread_id == thread_id
            )
        )
        return result.scalars().first()

    async def find_specific_user_chats(self, db: AsyncSession, session_ids: list[str], user_id: str):
        result = await db.execute(
            select(Conversation)
            .where(
                Conversation.thread_id.in_(session_ids),
                Conversation.user_id == user_id
            )
        )
        return result.scalars().all()

    async def find_fetch_specific_history(self,db:AsyncSession,conv_id:str):
        msg_result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conv_id)
            .order_by(asc(ChatMessage.auto_id))
        ) 
        return msg_result.scalars().all()
         
    
    async def create_conversation(self, db: AsyncSession, data: dict):
        new_conversation = Conversation(**data)
        db.add(new_conversation)
        await db.commit()
        await db.refresh(new_conversation)
        return new_conversation
    
    async def create_chat_message(self, db: AsyncSession, data: dict):
        new_chat_message = ChatMessage(**data)
        db.add(new_chat_message)
        await db.commit()
        await db.refresh(new_chat_message) 
        return new_chat_message
    
    async def get_latest_assistant_message(self,db:AsyncSession,conversation_id:str):
        result = await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.role == "assistant",
            )
            .order_by(ChatMessage.auto_id.desc())
            .limit(1)
        )
        return result.scalars().all()

    async def get_latest_resume_assistant_message(self,db:AsyncSession,conversation_id:str):
        result = await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.role == "assistant",
            )
            .order_by(ChatMessage.auto_id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_last_assistant_messages(self, db: AsyncSession, conversation_id: str, limit: int = 2):
        """The N most recent assistant messages, newest first.

        Undo needs two: the message that closed the last turn, and the one before
        it — whose ``checkpoint_id`` is the state the graph was in *before* the
        user's last answer (i.e. paused at the interrupt they then answered).
        """
        result = await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.role == "assistant",
            )
            .order_by(ChatMessage.auto_id.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_last_messages(self, db: AsyncSession, conversation_id: str, limit: int = 3):
        """The N most recent messages of any role, newest first.

        Stop reconciliation needs the tail as written, not just the assistant side:
        the thing it has to recognise is a trailing USER message whose answer the
        graph never consumed.
        """
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.auto_id.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_message_by_id(self, db: AsyncSession, conversation_id: str, message_id: str):
        result = await db.execute(
            select(ChatMessage).where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.id == message_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_last_user_message(self, db: AsyncSession, conversation_id: str):
        result = await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.role == "user",
            )
            .order_by(ChatMessage.auto_id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_assistant_message_before(self, db: AsyncSession, conversation_id: str, auto_id: int):
        """The assistant message immediately preceding ``auto_id``.

        This is the rewind ANCHOR: its ``checkpoint_id`` is the state the graph was
        in when it asked the question, so forking there re-asks it. A user message
        with no such predecessor (the opening message) cannot be rewound.
        """
        result = await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.role == "assistant",
                ChatMessage.auto_id < auto_id,
            )
            .order_by(ChatMessage.auto_id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_assistants_with_checkpoint(
        self, db: AsyncSession, conversation_id: str, checkpoint_ns: str, checkpoint_id: str
    ):
        """Every assistant message stamped with this checkpoint address, oldest first.

        Interrupts inside one node run share a single checkpoint, so several
        assistant rows can carry the same stamp (a "group"). A fork of that stamp
        cannot tell them apart, which is why /rewind needs the whole group to decide
        whether it can honour the request at all.
        """
        result = await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.role == "assistant",
                ChatMessage.checkpoint_id == checkpoint_id,
                ChatMessage.checkpoint_ns == checkpoint_ns,
            )
            .order_by(ChatMessage.auto_id.asc())
        )
        return list(result.scalars().all())

    async def get_messages_after(self, db: AsyncSession, conversation_id: str, auto_id: int):
        result = await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.auto_id > auto_id,
            )
            .order_by(asc(ChatMessage.auto_id))
        )
        return result.scalars().all()

    async def delete_messages_from(self, db: AsyncSession, conversation_id: str, auto_id: int):
        """Delete this message and everything after it.

        Undo uses this rather than ``delete_messages_after``: the anchor assistant
        message is the question being re-asked, and the undo turn writes its own
        copy of it. Keeping the old row would show the same question twice in
        history and leave ``can_undo`` true with nothing left to undo.
        """
        await db.execute(
            delete(ChatMessage).where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.auto_id >= auto_id,
            )
        )
        return await db.commit()

    async def delete_messages_after(self, db: AsyncSession, conversation_id: str, auto_id: int):
        await db.execute(
            delete(ChatMessage).where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.auto_id > auto_id,
            )
        )
        return await db.commit()

    async def delete_conversation(self, db: AsyncSession, conv_id: str):
        await db.execute(delete(Conversation).where(Conversation.id == conv_id))
        return await db.commit()
    
    async def delete_multiple_conversations(self, db: AsyncSession, conv_ids: list[str]):
        await db.execute(delete(Conversation).where(Conversation.id.in_(conv_ids)))
        return await db.commit()
    
    async def update_thread(self,db:AsyncSession,conv):
        await db.commit()
        await db.refresh(conv)
        return conv
     
    async def get_starred_threads(self,db:AsyncSession,user_id:str):
        result = await db.execute(
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.starred == True,
            )
            .order_by(desc(Conversation.created_at))
        )
        return result.scalars().all()