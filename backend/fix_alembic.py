import asyncio
from app.db.database import engine
from sqlalchemy import text

async def fix():
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE alembic_version SET version_num = '8439fc8b0a7a'"))
        print('Fixed alembic version')

asyncio.run(fix())
