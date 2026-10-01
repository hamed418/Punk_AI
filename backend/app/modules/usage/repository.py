from typing import Optional, Sequence

from sqlalchemy import Numeric, func, literal, select, text, union_all
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.model_registry  # noqa: F401 — ensure all models are imported before mappers are configured

from app.db.models import UnacastCallLog, UsageEvent
from app.modules.chat.models import Conversation
from app.modules.user.models import User


def _usage_union():
    """One row per (user/thread, period, kind, quantity) across both sources.

    ``usage_events`` never holds Unacast rows (see ``UsageEvent``'s docstring —
    ``unacast_call_log`` already records those transactionally with the budget
    ledger), so this UNION is what gives a caller "everything this
    user/thread spent" in one query without a second writer anywhere.

    ``usage_events.user_id`` is NULL for map-widget rows (those routes are
    unauthenticated); resolved here via ``conversations.thread_id``, which is
    unique-indexed, rather than by touching the widget routes' auth.
    """
    ev = select(
        func.coalesce(UsageEvent.user_id, Conversation.user_id).label("user_id"),
        UsageEvent.thread_id.label("thread_id"),
        UsageEvent.period.label("period"),
        UsageEvent.kind.label("kind"),
        UsageEvent.quantity.label("quantity"),
        UsageEvent.cost_usd.label("cost_usd"),
    ).outerjoin(Conversation, Conversation.thread_id == UsageEvent.thread_id)

    unacast = select(
        UnacastCallLog.user_id.label("user_id"),
        UnacastCallLog.thread_id.label("thread_id"),
        UnacastCallLog.period.label("period"),
        literal("unacast").label("kind"),
        UnacastCallLog.requests.label("quantity"),
        literal(None, type_=Numeric(12, 8)).label("cost_usd"),
    )

    return union_all(ev, unacast).subquery("ev")


def _sum(ev, kind: str, col=None):
    """SUM(col) FILTER (WHERE kind = ...), 0 if nothing matched.

    Never SUM ``quantity`` unqualified — it means tokens for kind='llm_tokens'
    and request counts for every other kind (see UsageEvent's docstring).
    """
    col = col if col is not None else ev.c.quantity
    return func.coalesce(func.sum(col).filter(ev.c.kind == kind), 0)


class UsageRepository:
    async def get_user_usage(
        self, db: AsyncSession, *, period: Optional[str], skip: int, limit: int,
    ) -> tuple[Sequence, int]:
        ev = _usage_union()
        stmt = (
            select(
                ev.c.user_id,
                User.email,
                _sum(ev, "llm_tokens").label("tokens"),
                _sum(ev, "llm_tokens", ev.c.cost_usd).label("cost_usd"),
                _sum(ev, "google_maps").label("maps_calls"),
                _sum(ev, "grounding").label("grounding_calls"),
                _sum(ev, "unacast").label("unacast_requests"),
            )
            .outerjoin(User, User.id == ev.c.user_id)
            .group_by(ev.c.user_id, User.email)
        )
        if period:
            stmt = stmt.where(ev.c.period == period)

        total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = (
            await db.execute(stmt.order_by(text("tokens DESC")).offset(skip).limit(limit))
        ).all()
        return rows, total or 0

    async def get_thread_usage(
        self, db: AsyncSession, *,
        user_id: Optional[str], period: Optional[str], skip: int, limit: int,
    ) -> tuple[Sequence, int]:
        ev = _usage_union()
        stmt = (
            select(
                ev.c.thread_id,
                ev.c.user_id,
                _sum(ev, "llm_tokens").label("tokens"),
                _sum(ev, "llm_tokens", ev.c.cost_usd).label("cost_usd"),
                _sum(ev, "google_maps").label("maps_calls"),
                _sum(ev, "grounding").label("grounding_calls"),
                _sum(ev, "unacast").label("unacast_requests"),
            )
            .group_by(ev.c.thread_id, ev.c.user_id)
        )
        if period:
            stmt = stmt.where(ev.c.period == period)
        if user_id:
            stmt = stmt.where(ev.c.user_id == user_id)

        total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = (
            await db.execute(stmt.order_by(text("tokens DESC")).offset(skip).limit(limit))
        ).all()
        return rows, total or 0
