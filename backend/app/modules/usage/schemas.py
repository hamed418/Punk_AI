import uuid
from typing import Optional

from pydantic import BaseModel


class UserUsageRow(BaseModel):
    """One user's rollup for a period (or all-time when ``period`` is omitted).

    ``tokens``/``cost_usd`` come from ``usage_events`` (kind='llm_tokens').
    ``maps_calls``/``grounding_calls`` come from ``usage_events`` too.
    ``unacast_requests`` comes from ``unacast_call_log`` — Unacast is never
    written into ``usage_events``, see UsageEvent's docstring.
    """
    user_id: Optional[uuid.UUID] = None
    email: Optional[str] = None
    tokens: int
    cost_usd: float
    maps_calls: int
    grounding_calls: int
    unacast_requests: int

    model_config = {"from_attributes": True}


class ThreadUsageRow(BaseModel):
    """Same rollup, grouped by chat thread instead of user."""
    thread_id: Optional[str] = None
    user_id: Optional[uuid.UUID] = None
    tokens: int
    cost_usd: float
    maps_calls: int
    grounding_calls: int
    unacast_requests: int

    model_config = {"from_attributes": True}
