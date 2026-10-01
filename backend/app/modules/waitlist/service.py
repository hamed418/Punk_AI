from fastapi import HTTPException
from .repository import WaitlistRepository
from app.shared.pagination import paginate
from sqlalchemy import select 
from .models import WaitList

class WaitlistService:
    def __init__(self, repository: WaitlistRepository):
        self.repository = repository

    async def get_all(self, db, pagination):
        data, total = await self.repository.get_all(
            db=db,
            skip=pagination.skip,
            limit=pagination.limit,
        )

        return paginate(
            total=total,
            page=pagination.page,
            limit=pagination.limit,
            data=data
        )
    
    async def create(self, db,request, waitlist_data,user_agent,accept_language):
        data = waitlist_data if isinstance(waitlist_data, dict) else waitlist_data.model_dump()
        ip_address = request.headers.get("x-forwarded-for")
        if ip_address:
            # x-forwarded-for can be a comma-separated list; take the first one
            ip_address = ip_address.split(",")[0].strip()
        else:
            ip_address = request.client.host if request.client else "127.0.0.1"
        data["ip_address"] = ip_address
        # Parse user-agent string
        user_agent_str = user_agent or request.headers.get("user-agent", "")
        data["user_agent"] = user_agent_str

        # Basic browser & OS detection (you can use a library like user-agents for production)
        if "Firefox" in user_agent_str: data["browser"] = "Firefox"
        elif "Chrome" in user_agent_str and "Chromium" not in user_agent_str: data["browser"] = "Chrome"
        elif "Safari" in user_agent_str and "Chrome" not in user_agent_str: data["browser"] = "Safari"
        elif "Edg" in user_agent_str: data["browser"] = "Edge"
        elif "MSIE" in user_agent_str or "Trident" in user_agent_str: data["browser"] = "IE"
        
        if "Windows" in user_agent_str: data["operating_system"] = "Windows"
        elif "Macintosh" in user_agent_str or "Mac OS X" in user_agent_str: data["operating_system"] = "macOS"
        elif "Linux" in user_agent_str: data["operating_system"] = "Linux"
        elif "Android" in user_agent_str: data["operating_system"] = "Android"
        elif "iPhone" in user_agent_str or "iPad" in user_agent_str: data["operating_system"] = "iOS"

        # Extract language from Accept-Language header
        if accept_language:
            # e.g., "en-US,en;q=0.9,fr;q=0.8" -> "en-US"
            primary_lang = accept_language.split(",")[0].strip()
            data["language"] = primary_lang

        # Determine device type
        if "Mobile" in user_agent_str or "Android" in user_agent_str or "iPhone" in user_agent_str or "iPad" in user_agent_str:
            data["device_type"] = "Mobile"
        elif "Tablet" in user_agent_str:
            data["device_type"] = "Tablet"
        else:
            data["device_type"] = "Desktop"
        return await self.repository.create(db, data)
    
    async def get_by_id(self,db,id):
        wait_user = await self.repository.get_by_id(db,id)
        if not wait_user:
            raise HTTPException(status_code=404, detail="Waitlist not found")
        return wait_user

    async def update(self,db,id,payload):
        wait_user = await db.execute(select(WaitList).where(WaitList.id == id))
        wait_user = wait_user.scalar_one_or_none()
        if not wait_user:
            raise HTTPException(status_code=404, detail="Waitlist not found")
        update_data = payload.model_dump(exclude_unset=True)  
        for key, value in update_data.items():
            setattr(wait_user, key, value)
        return await self.repository.update(db, id, wait_user)
    
    # delete waitlist 
    async def delete(self,db,id):
        wait_user = await self.repository.get_by_id(db,id)
        if not wait_user:
            raise HTTPException(status_code=404, detail="Waitlist not found")
        return await self.repository.delete(db, wait_user)
