import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from .schemas import AuditLogRequest
from app.core.logging import logger
from .schemas import AuditLogRequest   
from .models import AuditLog

logger = logging.getLogger(__name__)


class AuditLogRepository:
    async def get_audit_logs(self, db: AsyncSession, skip: int, limit: int):
        total_result = await db.execute(select(func.count()).select_from(AuditLog))
        total = total_result.scalar()
        
        result = await db.execute(
            select(AuditLog)
            .order_by(AuditLog.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all(), total
    
    async def create_audit_logs(self, db: AsyncSession, payloadRequest:AuditLogRequest):
        try:
            audit_log = AuditLog(
                user_id=payloadRequest.user_id,
                action=payloadRequest.action,
                resource_type=payloadRequest.resource_type,
                resource_id=payloadRequest.resource_id,
                old_data=payloadRequest.old_data,
                new_data=payloadRequest.new_data,
                ip_address=payloadRequest.ip_address,
                user_agent=payloadRequest.user_agent
            )
            db.add(audit_log)
            await db.commit()
            return audit_log
        except Exception as e:
            logger.error(f"Error creating audit log: {str(e)}")
            return None
    
     