from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone
from app.modules.analytics.repository import AnalyticsRepository
from app.modules.analytics.schemas import (
    AnalyticsOverviewResponse,
    VelocityResponse,
    VelocityDataPoint,
    ActivityFeedResponse,
    ActivityFeedItem,
    RecentCampaignsResponse,
    RecentCampaignItem,
)


class AnalyticsService:
    def __init__(self, repo: AnalyticsRepository):
        self.repo = repo

    async def get_analytics(self, db: AsyncSession) -> Dict[str, Any]:
        """Legacy analytics endpoint kept for backward compatibility."""
        rows = await self.repo.get_user_analytics_list(db)
        users_dict = {}
        total_subscribed_users = 0
        new_user_count = 0
        total_user = 0
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        for row in rows:
            user_id_str = str(row.id)
            if user_id_str not in users_dict:
                is_subscribed = row.isSubscriptionActive
                if row.created_at >= thirty_days_ago:
                    new_user_count += 1
                total_user += 1
                if is_subscribed:
                    total_subscribed_users += 1
                users_dict[user_id_str] = {
                    "user_id": user_id_str,
                    "email": row.email,
                    "full_name": row.full_name,
                    "is_subscribed": is_subscribed,
                    "total_conversations": 0,
                    "conversations": [],
                }
            if row.conversation_id:
                users_dict[user_id_str]["total_conversations"] += 1
                users_dict[user_id_str]["conversations"].append({
                    "conversation_id": str(row.conversation_id),
                    "title": row.conversation_title,
                    "total_chats": row.chat_count,
                })

        return {
            "total_user": total_user,
            "total_subscribed_users": total_subscribed_users,
            "users": list(users_dict.values()),
            "new_user": new_user_count,
        }

    async def get_overview(self, db: AsyncSession) -> AnalyticsOverviewResponse:
        data = await self.repo.get_overview_metrics(db)
        return AnalyticsOverviewResponse(**data)

    async def get_velocity(self, db: AsyncSession, timeframe: str = "daily") -> VelocityResponse:
        valid_tf = timeframe.lower() if timeframe.lower() in ("daily", "weekly", "monthly") else "daily"
        points = await self.repo.get_velocity_data(db, valid_tf)
        return VelocityResponse(
            timeframe=valid_tf,
            data=[VelocityDataPoint(**p) for p in points],
        )

    async def get_activity_feed(self, db: AsyncSession, limit: int = 10) -> ActivityFeedResponse:
        items = await self.repo.get_recent_activity_feed(db, limit=limit)
        return ActivityFeedResponse(
            items=[ActivityFeedItem(**item) for item in items]
        )

    async def get_recent_campaigns(
        self, db: AsyncSession, limit: int = 10, search: Optional[str] = None
    ) -> RecentCampaignsResponse:
        campaigns = await self.repo.get_recent_campaigns(db, limit=limit, search=search)
        return RecentCampaignsResponse(
            campaigns=[RecentCampaignItem(**c) for c in campaigns]
        )