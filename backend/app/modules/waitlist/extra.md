<!-- # import re
# import httpx
# from fastapi import APIRouter, HTTPException, Query, Depends,Header,Request
# from typing import Optional
# from sqlalchemy import select, func
# from pydantic import BaseModel
# from sqlalchemy.ext.asyncio import AsyncSession
# from app.core import config
# from app.core.logging import logger
# from app.db.schemas import WaitListCreateRequest, WaitListResponse,WaitListUpdateRequest
# from app.db.models import WaitList
# from app.core.dependencies import get_db
# from user_agents import parse

# router = APIRouter(prefix="/wait-list", tags=["Wait List"])

 
# @router.get("")
# async def get_waitlist(
#     page: int = Query(1, ge=1, description="Page number"),
#     page_size: int = Query(10, ge=1, le=100, description="Items per page"),
#     db: AsyncSession = Depends(get_db)
# ):
#     """
#     Get waitlist with pagination
#     """

#     # Calculate offset
#     offset = (page - 1) * page_size

#     # Get total count
#     total_result = await db.execute(
#         select(func.count()).select_from(WaitList)
#     )
#     total = total_result.scalar()

#     # Get paginated data
#     result = await db.execute(
#         select(WaitList)
#         .offset(offset)
#         .limit(page_size)
#     )

#     waitlist = result.scalars().all()

#     return {
#         "data": waitlist,
#         "pagination": {
#             "page": page,
#             "page_size": page_size,
#             "total_items": total,
#             "total_pages": (total + page_size - 1) // page_size,
#             "has_next": page * page_size < total,
#             "has_previous": page > 1,
#         }
#     }

# # how many list only count api create here 
# @router.get("/list-count")
# async def waitlist_count(
#     db: AsyncSession = Depends(get_db)
# ):
#     result = await db.execute(
#         select(func.count()).select_from(WaitList)
#     )

#     count = result.scalar()

#     return {
#         "count": count + 1000 if count < 1000 else count
#     }

# @router.get("/{id}")
# async def get_waitlist_user(
#     id: str,
#     db: AsyncSession = Depends(get_db)
# ):
#     """
#     Get single waitlist user
#     """

#     result = await db.execute(
#         select(WaitList).where(WaitList.id == id)
#     )

#     wait_user = result.scalar_one_or_none()

#     if not wait_user:
#         raise HTTPException(
#             status_code=404,
#             detail="Waitlist user not found"
#         )

#     return wait_user

# @router.post("/join")
# async def join_waitlist(
#     payload:WaitListCreateRequest,
#     db: AsyncSession = Depends(get_db)
# ):
#     """
#     Add user to waitlist
#     """ 
#     # validate email 
#     if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", payload.email):
#         raise HTTPException(status_code=400, detail="Invalid email address")
#     # check if user is already in waitlist
#     result = await db.execute(select(WaitList).where(WaitList.email == payload.email))
#     if result.scalar_one_or_none():
#         raise HTTPException(status_code=400, detail="Email already registered in waitlist")
#     # creaet waitlist 
#     waitList = WaitList(
#         email=payload.email,
#     )
#     db.add(waitList)
#     await db.commit()
#     await db.refresh(waitList)
#     return waitList

# @router.patch("/join/{id}")
# async def fill_waitlist(
#     id: str,
#     payload: WaitListUpdateRequest,
#     db: AsyncSession = Depends(get_db)
# ):
#     """
#     Approve waitlist
#     """
#     result = await db.execute(select(WaitList).where(WaitList.id == id))
#     wait_user = result.scalar_one_or_none()
#     if not wait_user:
#         raise HTTPException(status_code=404, detail="Waitlist not found")
#     update_data = payload.model_dump(exclude_unset=True) # Use .dict(exclude_unset=True) if using Pydantic v1
#     for key, value in update_data.items():
#         setattr(wait_user, key, value)
        
#     await db.commit()
#     await db.refresh(wait_user)
    
#     return wait_user

# @router.get("/detect-device/get")
# async def get_device_info(
#     request: Request,
#     user_agent: Optional[str] = Header(None),
#     accept_language: Optional[str] = Header(None),
#     db: AsyncSession = Depends(get_db)
# ):
#     if not user_agent:
#         return {"device_type": "unknown", "message": "No User-Agent header found"}
#     client_language = accept_language.split(",")[0] if accept_language else "en"
#     # Parse the user agent string
#     ua = parse(user_agent)

#     # Determine the device category
#     if ua.is_mobile:
#         device_type = "mobile"
#     elif ua.is_tablet:
#         device_type = "tablet"
#     elif ua.is_pc:
#         device_type = "laptop/desktop"
#     elif ua.is_bot:
#         device_type = "bot/crawler"
#     else:
#         device_type = "other"
#     ip_address = request.headers.get("x-forwarded-for")
#     if ip_address:
#         # x-forwarded-for can be a comma-separated list; take the first one
#         ip_address = ip_address.split(",")[0].strip()
#     else:
#         ip_address = request.client.host if request.client else "127.0.0.1"

#     # Default structure in case the lookup fails
#     geo_data = {
#         "ip_address": ip_address,
#         "country": None,
#         "region": None,
#         "city": None,
#         "timezone": None,
#         "isp": None
#     }

#     # Avoid looking up local/internal IPs on live APIs
#     # if ip_address in ("127.0.0.1", "localhost", "::1") or ip_address.startswith("192.168."):
#     #     return geo_data

#     # 2. Query an external Geolocation API (Using ip-api.com as an example)
#     try:
#         async with httpx.AsyncClient() as client:
#             response = await client.get(f"http://ip-api.com/json/{ip_address}?fields=status,country,regionName,city,timezone,isp")
#             if response.status_code == 200:
#                 data = response.json()
#                 if data.get("status") == "success":
#                     geo_data["country"] = data.get("country")
#                     geo_data["region"] = data.get("regionName")
#                     geo_data["city"] = data.get("city")
#                     geo_data["timezone"] = data.get("timezone")
#                     geo_data["isp"] = data.get("isp")
#     except Exception as e:
#         # Log your error here so your endpoint doesn't crash if the geo-API goes down
#         print(f"Failed to fetch geo data: {e}")
#     return {
#         "device_type": device_type,
#         "browser": ua.browser.family,       # e.g., Chrome, Safari
#         "os": ua.os.family,                 # e.g., iOS, Windows, Android
#         "device_model": ua.device.model,     
#         "device_brand": ua.device.brand,   
#         "is_mobile": ua.is_mobile,
#         "is_tablet": ua.is_tablet,
#         "is_pc": ua.is_pc,
#         "is_bot": ua.is_bot,
#         "client_language":client_language,
#         "geo_data":geo_data
#     }

# @router.delete("/{id}")
# async def delete_waitlist_user(
#     id: str,
#     db: AsyncSession = Depends(get_db)
# ):
#     """
#     Delete waitlist user
#     """

#     result = await db.execute(
#         select(WaitList).where(WaitList.id == id)
#     )

#     wait_user = result.scalar_one_or_none()

#     if not wait_user:
#         raise HTTPException(
#             status_code=404,
#             detail="Waitlist user not found"
#         )

#     await db.delete(wait_user)
#     await db.commit()

#     return {
#         "message": "Waitlist user deleted successfully"
#     } -->