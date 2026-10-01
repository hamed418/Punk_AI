from fastapi import APIRouter, Depends,Header,Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_db
from app.shared.pagination import PaginationParams, PaginatedResponse

from .service import WaitlistService
from .repository import WaitlistRepository
from .schemas import WaitListResponse,WaitListCreateRequest,WaitListUpdateRequest
from typing import Optional

router = APIRouter(
    prefix="/waitlist"
)

repository = WaitlistRepository()
service = WaitlistService(repository)

@router.get(
    "",
    response_model=PaginatedResponse[WaitListResponse],
    tags=["Admin - Waitlist"]
)
async def get_waitlist(
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends()
):
    return await service.get_all(db, pagination)

@router.post(
    "", 
    response_model=WaitListResponse,
    tags=["Waitlist"]
)
async def create_waitlist(
    request: Request,
    waitlist_data: WaitListCreateRequest,
    user_agent: Optional[str] = Header(None),
    accept_language: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    return await service.create(db,request, waitlist_data,user_agent,accept_language)

@router.get("/{id}", tags=["Admin - Waitlist"])
async def get_waitlist_by_id(
    id: str,
    db: AsyncSession = Depends(get_db)
):
    return await service.get_by_id(db,id)

@router.patch("/{id}", tags=["Admin - Waitlist"])
async def fill_waitlist(
    id: str,
    payload: WaitListUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    return await service.update(db,id,payload)

@router.delete("/{id}", tags=["Admin - Waitlist"])
async def delete_waitlist(
    id: str,
    db: AsyncSession = Depends(get_db)
):
    return await service.delete(db,id)
