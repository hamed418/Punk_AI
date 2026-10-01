import httpx
from typing import Dict, Any, List, Optional
from fastapi import HTTPException
from app.core import config
from app.core.logging import logger

GOOGLE_API_KEY = config.settings.GOOGLE_MAPS_API_KEY
SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
NEARBY_SEARCH_URL = "https://places.googleapis.com/v1/places:searchNearby"


async def _count_api_call(session_id: Optional[str], api: str) -> None:
    """Record one Google request from a widget route. Never raises.

    These routes run outside any chat turn, so the usage.py contextvar (which
    needs an open turn) can't reach them — write straight to usage_events
    instead. No user_id: /map/* is unauthenticated; a per-user total is
    resolved at read time via ``conversations.thread_id`` (unique-indexed),
    not by adding auth to these routes.

    Replaces a former AgentState write (aget_state + aupdate_state per call)
    that had to skip counting entirely while a subgraph interrupt was pending
    — i.e. it silently undercounted exactly the editable confirm-location
    maps this widget serves. A plain insert has no such interrupt hazard.
    """
    if not session_id:
        return
    try:
        from app.db.database import AsyncSessionLocal
        from app.db.models import UsageEvent
        from app.graph.usage import _period

        async with AsyncSessionLocal() as db:
            db.add(UsageEvent(
                period=_period(), thread_id=session_id, user_id=None,
                kind="google_maps", api=api, quantity=1, source="map_widget",
            ))
            await db.commit()
    except Exception as exc:
        logger.warning("map widget api_call count failed: %s", exc)


class MapService:
    async def search_places(self, query: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": GOOGLE_API_KEY,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location,places.rating"
        }
        payload = {
            "textQuery": query,
            "maxResultCount": 20, 
        } 
        async with httpx.AsyncClient() as client:
            response = await client.post(SEARCH_URL, json=payload, headers=headers)
            await _count_api_call(session_id, "places_search")
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)
            return response.json()

    async def get_suggestions(self, input_text: str, session_id: Optional[str] = None) -> List[Any]:
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": GOOGLE_API_KEY
        }
        payload = {
            "input": input_text
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(AUTOCOMPLETE_URL, json=payload, headers=headers)
            await _count_api_call(session_id, "places_autocomplete")
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)
            data = response.json()
            return data.get("suggestions", [])

    async def search_all_places(self, query: str, next_token: Optional[str], session_id: Optional[str] = None) -> Dict[str, Any]:
        params = {
            "query": query,
            "key": GOOGLE_API_KEY,
        }
        if next_token:
            params["pagetoken"] = next_token

        async with httpx.AsyncClient() as client:
            response = await client.get(TEXT_SEARCH_URL, params=params)
            await _count_api_call(session_id, "places_text_search_legacy")
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail="Google API Error")
            data = response.json()
            
            results = []
            for place in data.get("results", []):
                results.append({
                    "place_id": place.get("place_id"),
                    "name": place.get("name"),
                    "address": place.get("formatted_address"),
                    "lat": place.get("geometry", {}).get("location", {}).get("lat"),
                    "lng": place.get("geometry", {}).get("location", {}).get("lng"),
                    "rating": place.get("rating"),
                    "user_ratings_total": place.get("user_ratings_total"),
                    "types": place.get("types"),
                    "price_level": place.get("price_level"),
                    "open_now": place.get("opening_hours", {}).get("open_now") if "opening_hours" in place else None,
                    "photo_reference": place.get("photos", [{}])[0].get("photo_reference") if "photos" in place else None
                })
                
            return {
                "total_results": len(results),
                "results": results,
                "next_page_token": data.get("next_page_token")  
            }

    async def nearby_search(
        self, lat: float, lng: float, radius: int, place_type: str, page_token: Optional[str],
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        headers = {
            "X-Goog-Api-Key": GOOGLE_API_KEY,
            "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.rating,places.userRatingCount,places.formattedAddress,places.types",
        }
        body = {
            "includedTypes": [place_type],
            "maxResultCount": 10,
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": lat,
                        "longitude": lng
                    },
                    "radius": radius
                }
            }
        }
        if page_token:
            body["pageToken"] = page_token

        async with httpx.AsyncClient() as client:
            response = await client.post(
                NEARBY_SEARCH_URL,
                headers=headers,
                json=body
            )
            await _count_api_call(session_id, "places_nearby")
            data = response.json()
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail=data)
            return data