from fastapi import APIRouter, Query
from app.modules.map.service import MapService

router = APIRouter(prefix="/map", tags=["Map"])
service = MapService()

@router.get("/search")
async def search_places(
    q: str = Query(..., examples="Coffee shop in New York"),
    session_id: str | None = None,
):
    """
    Standard Text Search: Use this to get the list of coffee shops for markers.
    """
    return await service.search_places(q, session_id=session_id)

@router.get("/suggestions")
async def get_suggestions(
    input_text: str = Query(..., examples="coff"),
    session_id: str | None = None,
):
    """
    Autocomplete: Use this for the dropdown suggestions as the user types.
    """
    return await service.get_suggestions(input_text, session_id=session_id)

@router.get("/search-all")
async def search_all_places(
    q: str = Query(..., examples="Coffee shop in Dhaka"),
    next_token: str = None,
    session_id: str | None = None,
):
    return await service.search_all_places(q, next_token, session_id=session_id)

@router.get("/nearby")
async def nearby_search(
    lat: float,
    lng: float,
    radius: int = 2000,
    place_type: str = "restaurant",
    page_token: str | None = Query(None, alias="pageToken"),
    session_id: str | None = None,
):
    return await service.nearby_search(
        lat, lng, radius, place_type, page_token, session_id=session_id,
    )
