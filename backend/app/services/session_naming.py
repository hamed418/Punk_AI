"""
Session naming helpers.

Conversation titles should come from user-provided context, not from campaign
publish lifecycle events or generated platform campaign names.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat.models import Conversation


_DEFAULT_TITLE_RE = re.compile(r"^new chat(?:\s+\d{4}-\d{2}-\d{2}.*)?$", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


def _clean(value: Any, max_len: int = 80) -> str:
    if value is None:
        return ""
    text = _WHITESPACE_RE.sub(" ", str(value)).strip(" \t\r\n-_:;,")
    return text[:max_len].strip()


def _title_case(value: str) -> str:
    value = _clean(value)
    if value.isupper():
        return value.title()
    return value


def _objective_label(value: Any) -> str:
    objective = _clean(value, 40).replace("_", " ").lower()
    labels = {
        "awareness": "Awareness",
        "traffic": "Traffic",
        "engagement": "Engagement",
        "leads": "Lead Gen",
        "sales": "Sales",
        "app promotion": "App Promotion",
    }
    return labels.get(objective, objective.title() if objective else "")


def _location_label(geo_data: dict[str, Any]) -> str:
    locations = geo_data.get("locations") or []
    if isinstance(locations, list) and locations:
        first = locations[0] or {}
        label = first.get("location_name") or first.get("formatted_address")
        if label:
            return _clean(label, 40)

    meta_targeting = geo_data.get("meta_targeting") or {}
    geo_locations = meta_targeting.get("geo_locations") or {}
    for key in ("cities", "regions", "countries"):
        values = geo_locations.get(key) or []
        if isinstance(values, list) and values:
            first = values[0]
            if isinstance(first, dict):
                return _clean(first.get("name") or first.get("key"), 40)
            return _clean(first, 40)
    return ""


def _fallback_from_text(text: str) -> str:
    text = _clean(text, 70)
    if not text:
        return ""

    text = re.sub(r"^(hi|hello|hey)[,!\s]+", "", text, flags=re.IGNORECASE)
    text = text.strip()
    if not text:
        return ""

    if len(text) > 55:
        text = text[:55].rsplit(" ", 1)[0].strip()
    return text[:1].upper() + text[1:]


def build_session_title(
    *,
    latest_user_text: str = "",
    user_info: dict[str, Any] | None = None,
    geo_data: dict[str, Any] | None = None,
) -> tuple[str, int]:
    """
    Return (title, confidence).

    Confidence allows callers to avoid replacing a meaningful title with a
    weak fallback from a short answer like "yes".
    """
    user_info = user_info or {}
    geo_data = geo_data or {}

    business = _clean(user_info.get("business_name"), 45)
    objective = _objective_label(user_info.get("campaign_objective"))
    offer = _clean(user_info.get("product_offer"), 45)
    audience = _clean(user_info.get("target_audience"), 45)
    industry = _title_case(_clean(user_info.get("industry"), 45))
    location = _location_label(geo_data)

    if business and objective and location:
        return f"{business} - {objective} in {location}"[:80], 100
    if business and objective:
        return f"{business} - {objective} Campaign"[:80], 95
    if business and offer:
        return f"{business} - {offer}"[:80], 90
    if business and location:
        return f"{business} in {location}"[:80], 85
    if business:
        return f"{business} Campaign"[:80], 80

    if industry and objective:
        return f"{industry} - {objective} Campaign"[:80], 70
    if audience and objective:
        return f"{audience} - {objective}"[:80], 65
    if offer:
        return f"{offer} Campaign"[:80], 60

    fallback = _fallback_from_text(latest_user_text)
    if fallback:
        return fallback, 25
    return "", 0


def _looks_default(title: str | None) -> bool:
    title = _clean(title)
    return not title or bool(_DEFAULT_TITLE_RE.match(title))


async def update_conversation_title_from_context(
    db: AsyncSession,
    conversation: Conversation,
    *,
    latest_user_text: str = "",
    state_values: dict[str, Any] | None = None,
) -> str | None:
    """
    Update the conversation title based on the current state.
    
    Ensures the conversation object is attached to the session before updating.
    """
    try:
        state_values = state_values or {}
        title, confidence = build_session_title(
            latest_user_text=latest_user_text,
            user_info=state_values.get("user_info") or {},
            geo_data=state_values.get("geo_data") or {},
        )

        if not title:
            return None

        # Ensure object is persistent in the provided session to avoid "not persistent within this Session" errors
        # during streaming where the original session might have closed.
        if conversation not in db:
            conversation = await db.merge(conversation, load=False)

        if title == conversation.title:
            return None

        # Weak fallbacks are useful for new/default threads only. Strong contextual
        # names may replace earlier first-message titles as the user gives details.
        if confidence < 60 and not _looks_default(conversation.title):
            return None

        conversation.title = title[:200]
        await db.commit()
        await db.refresh(conversation)
        return conversation.title
    except Exception as exc:
        from app.core.logging import logger
        logger.warning("Failed to update conversation title: %s", exc)
        return None
