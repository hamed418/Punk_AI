import uuid 
from app.db.models import Base 
from sqlalchemy import (
    Column, String,    DateTime,   
     JSON
)
from sqlalchemy.dialects.postgresql import UUID,TIMESTAMP 
from sqlalchemy.sql import func
 
 
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(String, nullable=True, index=True)
    action = Column(String(100), nullable=False, index=True)

    resource_type = Column(String(100), nullable=True)
    resource_id = Column(String(100), nullable=True)

    old_data = Column(JSON, nullable=True)
    new_data = Column(JSON, nullable=True)

    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())