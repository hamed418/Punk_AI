from fastapi import HTTPException, status
from app.shared.pagination import paginate
from app.shared.enums import UserRole
from app.modules.user.models import User
from .repository import AuditLogRepository
from .schemas import AuditLogRequest  

class AuditLogService:
    def __init__(self, repository: AuditLogRepository):
        self.repository = repository

    async def get_audit_logs(self, db, pagination, current_user: User = None):
        if current_user is not None and current_user.role not in (UserRole.admin, UserRole.super_admin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin privileges required",
            )

        data, total = await self.repository.get_audit_logs(
            db=db,
            skip=pagination.skip,
            limit=pagination.limit,
        )

        return paginate(
            data=data,
            total=total,
            page=pagination.page,
            limit=pagination.limit,
        )

    # create a auditlog service
    async def create_audit_logs(self, db, payloadRequest: AuditLogRequest):
        return await self.repository.create_audit_logs(db, payloadRequest)
    