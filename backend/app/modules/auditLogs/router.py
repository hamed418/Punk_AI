from fastapi import APIRouter, Depends 
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_db, get_admin_user
from app.modules.user.models import User
from app.shared.pagination import PaginationParams, PaginatedResponse
from .service import AuditLogService
from .repository import AuditLogRepository 
from .schemas import AuditLogResponse  

router = APIRouter(
    prefix="/audit-logs",
    tags=["Admin - Audit Logs"]
)

repository = AuditLogRepository()
service = AuditLogService(repository)
 
@router.get("", response_model=PaginatedResponse[AuditLogResponse])
async def get_all_audit_logs(
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends()
):
    """
    Get all audit logs (Admin only).
    """
    return await service.get_audit_logs(db, pagination, current_user=admin_user)
    