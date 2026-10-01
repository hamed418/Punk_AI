"""DB access for the conversion event log."""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tracking.models import TrackingEvent


class TrackingRepository:
    async def log_batch(
        self,
        db: AsyncSession,
        *,
        ads_account_id: Any,
        dataset_id: str,
        payloads: list,
        event_ids: list[str],
        events_received: int,
        errors: list[str],
    ) -> None:
        """Record one row per event forwarded. Commits.

        ``events_received`` is Meta's count for the whole call, so it is stamped on
        every row rather than apportioned — Meta does not say WHICH events it
        accepted, and inventing a per-event verdict would make the log lie.
        """
        error = "; ".join(errors)[:2000] or None
        db.add_all([
            TrackingEvent(
                ads_account_id=ads_account_id,
                dataset_id=dataset_id,
                event_name=payload.event_name,
                event_id=event_id,
                action_source=payload.action_source,
                value=payload.value,
                currency=(payload.currency or "").upper() or None,
                events_received=events_received,
                error=error,
            )
            for payload, event_id in zip(payloads, event_ids)
        ])
        await db.commit()

    async def count(self, db: AsyncSession, ads_account_id: Any) -> int:
        """How many events Punk has forwarded for this account, ever.

        The honest answer to "is the server half live?" — an ingest key exists as
        soon as it is minted and the pixel's ``last_fired_time`` belongs to the
        browser tag, so neither one says anything about the server.
        """
        return int(await db.scalar(
            select(func.count())
            .select_from(TrackingEvent)
            .where(TrackingEvent.ads_account_id == ads_account_id)
        ) or 0)

    async def recent(
        self, db: AsyncSession, ads_account_id: Any, *, skip: int = 0, limit: int = 10
    ) -> tuple[list[TrackingEvent], int]:
        """Newest first, plus the total — the shape ``app.shared.pagination`` wants."""
        total = await db.scalar(
            select(func.count())
            .select_from(TrackingEvent)
            .where(TrackingEvent.ads_account_id == ads_account_id)
        )
        rows = (
            await db.execute(
                select(TrackingEvent)
                .where(TrackingEvent.ads_account_id == ads_account_id)
                .order_by(TrackingEvent.created_at.desc())
                .offset(skip)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), int(total or 0)
