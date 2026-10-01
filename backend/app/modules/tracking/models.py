"""What Punk sent to a customer's dataset, and what Meta said about it.

Written on the way out of ``POST /tracking/events``. The reason it exists is the
support case: an advertiser says their conversions are not showing, and without
this there is nothing on our side to look at — ``send`` reported to Meta and
forgot, so "we never received it" and "Meta rejected it" were the same silence.

**No identifiers are stored here — not raw, not hashed.** ``meta_capi`` normalizes
and SHA-256s email, phone, name and address on the way out and nothing keeps a
copy; a log of who converted would be a second store of the customer's customers'
PII, reachable with an ingest key. What is kept is the shape of the event: which
dataset, which event name, the id used for deduplication, and Meta's verdict.
"""
import uuid

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.db.models import Base


class TrackingEvent(Base):
    """One conversion event Punk forwarded to Meta."""

    __tablename__ = "tracking_events"

    __table_args__ = (
        # Every read is "the latest N for this account", which is exactly this
        # index — without it the scan grows with every conversion the customer
        # ever made.
        Index("ix_tracking_events_account_created", "ads_account_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # The ad account whose ingest key carried the event. The tenant boundary: an
    # agency running three clients off one login must not see one another's rows.
    ads_account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ads_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_id = Column(String(100), nullable=False)
    event_name = Column(String(100), nullable=False)
    # The deduplication id sent to Meta, derived or supplied. Kept because it is
    # the only value that ties this row to the browser pixel's own report of the
    # same conversion — the thing to compare when a conversion counted twice.
    event_id = Column(String(100), nullable=True)
    action_source = Column(String(40), nullable=True)
    # Numeric, not Float: this is money, and it is reconciled against the
    # advertiser's own order totals.
    value = Column(Numeric(18, 4), nullable=True)
    currency = Column(String(3), nullable=True)
    # Meta's own count for the batch this event was in, not ours. 0 with an error
    # beside it is a rejected batch; 0 with no error is CAPI switched off here.
    events_received = Column(Integer, nullable=False, default=0)
    # Meta's rejection message for the batch, when there was one.
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
