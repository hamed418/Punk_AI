import re

file_path = r"d:\dos_malek\dos\Punk_AI\backend\app\modules\chat\service.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Replace Semaphore definition with Slot Counter
sem_def = "_STREAM_SEMAPHORE = asyncio.Semaphore(300)"
slot_logic = '''_MAX_CONCURRENT_STREAMS = getattr(settings, "MAX_CONCURRENT_CHAT_STREAMS", 300)
_active_streams = 0
_stream_count_lock = asyncio.Lock()

async def _try_acquire_stream_slot() -> bool:
    global _active_streams
    async with _stream_count_lock:
        if _active_streams >= _MAX_CONCURRENT_STREAMS:
            return False
        _active_streams += 1
        return True

def _release_stream_slot() -> None:
    global _active_streams
    _active_streams = max(0, _active_streams - 1)'''

content = content.replace(sem_def, slot_logic)

# 2. Replace fail-fast checks
old_check = '''        if _STREAM_SEMAPHORE.locked():
            raise HTTPException(status_code=429, detail="Too many active AI streams. Please try again later.")'''
new_check = '''        if not await _try_acquire_stream_slot():
            raise HTTPException(status_code=429, detail="Too many active AI streams. Please try again later.")'''
content = content.replace(old_check, new_check)

# 3. Fix chat_stream acquire and release
content = content.replace("await _STREAM_SEMAPHORE.acquire()", "")
content = content.replace("_STREAM_SEMAPHORE.release()", "_release_stream_slot()")

# 4. Fix short_circuit block in resume_chat
old_short_circuit = '''                        async with AsyncSessionLocal() as short_db:
                            if assistant_text or metadata:
                                conv_in_db = await short_db.merge(conv, load=False)
                                assistant_msg = await self.repository.create_chat_message(short_db,
                                {"conversation_id": conv_in_db.id,'''

new_short_circuit = '''                        async with AsyncSessionLocal() as short_db:
                            if assistant_text or metadata:
                                assistant_msg = await self.repository.create_chat_message(short_db,
                                {"conversation_id": conv_id,'''

content = content.replace(old_short_circuit, new_short_circuit)

# 5. Fix rename_from_state inside resume_chat
old_rename = '''                    async def rename_from_state(state_values: dict) -> None:
                        async with AsyncSessionLocal() as short_db:
                            conv_in_db = await short_db.merge(conv, load=False)
                            await update_conversation_title_from_context(
                                short_db,
                                conv_in_db,
                                latest_user_text=payload.value,
                                state_values=state_values,
                            )'''

new_rename = '''                    async def rename_from_state(state_values: dict) -> None:
                        async with AsyncSessionLocal() as short_db:
                            conv_in_db = await self.repository.find_specific_user_chat(short_db, session_id, current_user.id)
                            if conv_in_db:
                                await update_conversation_title_from_context(
                                    short_db,
                                    conv_in_db,
                                    latest_user_text=payload.value,
                                    state_values=state_values,
                                )'''

content = content.replace(old_rename, new_rename)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Replacement successful")
