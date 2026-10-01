
import uuid
from datetime import datetime
from typing import Optional,Dict,Any 
from pydantic import BaseModel,ConfigDict 

 
class AuditLogResponse(BaseModel):
    id: uuid.UUID
    user_id: Optional[str]
    action: str
    resource_type: Optional[str]
    resource_id: Optional[str]
    old_data: Optional[Dict[str, Any]]
    new_data: Optional[Dict[str, Any]]
    ip_address: Optional[str]
    user_agent: Optional[str]
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class AuditLogRequest(BaseModel):
    user_id: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None

    old_data: Optional[Dict[str, Any]] = None
    new_data: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None