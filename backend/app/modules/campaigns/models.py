import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, JSON, Numeric, Integer, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.models import Base
from app.shared.enums import AdPlatform, CampaignStatus

class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)

    name = Column(String(500), nullable=False)
    platform = Column(SAEnum(AdPlatform), nullable=False)
    status = Column(SAEnum(CampaignStatus), default=CampaignStatus.draft, nullable=False)
    meta_ads_id = Column(String(255), nullable=True, index=True) 
    # The full structured campaign plan (JSON from Pydantic model)
    campaign_plan = Column(JSON, nullable=True)

    # External platform tracking (populated by media buyer after publishing)
    ext_campaign_id = Column(String(255), nullable=True, index=True)   # Google or Meta campaign ID
    ext_budget_id = Column(String(255), nullable=True)                  # Google shared budget ID
    ext_ad_group_ids = Column(JSON, nullable=True)                      # List of AdGroup / AdSet IDs

    # Per-object publish ledger, written as each Meta object is created:
    #   {"campaign_id", "custom_audience_id", "lookalike_audience_id",
    #    "media": {"<adset_idx>": hash}, "creatives": {...}, "adsets": {...},
    #    "ads": {...}, "activated": bool}
    #
    # This is what makes a retry idempotent. Publish is a multi-step remote
    # transaction with no rollback past the campaign; before this ledger existed,
    # a failure at ad set 3 orphaned everything before it AND a retry created a
    # second campaign, because nothing recorded what already succeeded.
    publish_state = Column(JSON, nullable=True)

    # Budget
    daily_budget_usd = Column(Numeric(10, 2), nullable=True)
    monthly_budget_usd = Column(Numeric(10, 2), nullable=True)

    # Performance metrics (updated by sync jobs)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    spend_usd = Column(Numeric(12, 2), default=0)
    roas = Column(Numeric(6, 2), nullable=True)
    cpa_usd = Column(Numeric(10, 2), nullable=True)  

    # Approval tracking (human-in-the-loop)
    approved_by_user = Column(Boolean, default=False)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="campaigns")
    conversation = relationship("Conversation", back_populates="campaigns")