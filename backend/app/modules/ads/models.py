import uuid
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Boolean, JSON, UniqueConstraint, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.crypto import EncryptedString
from app.db.models import Base
from app.shared.enums import AdPlatform

class OAuthToken(Base):
    """
    Stores OAuth2 access and refresh tokens for various ad platforms.

    The token columns are ``EncryptedString`` — Fernet at rest, plaintext in
    Python. A Meta access token spends real money, so a DB dump must not be a
    full compromise of every connected ad account.
    """
    __tablename__ = "oauth_tokens"

    # One connection per user per platform. Every read uses
    # ``scalar_one_or_none()``, which *raises* on a second row — and
    # ``get_meta_credentials`` catches broadly, so a duplicate turned into a
    # silent, permanent "not connected" for that user. Two OAuth callbacks
    # racing (read-then-insert, no upsert) was enough to produce one.
    __table_args__ = (
        UniqueConstraint("user_id", "platform", name="uq_oauth_tokens_user_platform"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    platform = Column(SAEnum(AdPlatform), nullable=False)
    access_token = Column(EncryptedString, nullable=False)
    # 'user' (60-day person-bound token, the old consumer-login shape) or
    # 'system_user' (Business Integration System User token minted via Facebook
    # Login for Business — never expires). Default 'user' makes the backfill for
    # every pre-existing row a no-op.
    token_type = Column(String(20), nullable=False, default="user", server_default="user")
    meta_user_name = Column(String(255), nullable=True)
    meta_user_image = Column(Text, nullable=True)
    
    refresh_token = Column(EncryptedString, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    scopes = Column(JSON, nullable=True)
    
    # Selected account for this platform
    ad_account_id = Column(String(50), nullable=True)
    ad_account_name = Column(String(255), nullable=True)
    accessible_accounts = Column(JSON, nullable=True)  # List[Dict[id, name]]
    # selected ads account id in case user connect multi account

    selected_account = Column(String(50), nullable=True)
    page_id = Column(String(100), nullable=True)
    page_name = Column(String(255), nullable=True)
    is_valid = Column(Boolean, default=True, nullable=False)

    # billing setup here


    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship(
        "User",
        back_populates="oauth_tokens"
    )

    # passive_deletes=True on both: without it SQLAlchemy UPDATEs the
    # loaded collection to oauth_token_id/meta_ads_id = NULL before the
    # parent DELETE runs — ads_accounts.oauth_token_id is NOT NULL, so that
    # UPDATE fails outright, and it pre-empts the FK's own ON DELETE
    # behavior either way. ads_accounts is lazy="selectin", so
    # disconnect_account's own lookup always loads it — this bites on every
    # Meta disconnect, not just an edge case.
    meta_account_subscriptions = relationship(
        "UserSubscription", back_populates="meta_ads", lazy="select", passive_deletes=True
    )
    ads_accounts = relationship(
        "AdsAccount", back_populates="oauth_token", lazy="selectin", passive_deletes=True
    )
 
class AdsAccount(Base):
    __tablename__ = "ads_accounts"

    # get-or-create on the tracking path is the same read-then-insert race that
    # produced duplicate oauth_tokens rows. Let the database settle it.
    __table_args__ = (
        UniqueConstraint("oauth_token_id", "ad_account_id", name="uq_ads_accounts_token_account"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    oauth_token_id = Column(UUID(as_uuid=True), ForeignKey("oauth_tokens.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("user_subscriptions.id", ondelete="SET NULL"), nullable=True)

    ad_account_id = Column(String(50), nullable=True)
    ad_account_name = Column(String(255), nullable=True)

    # ── Conversion tracking (the user's own dataset, never Punk's) ─────────────
    #
    # On the ad account, not the login: one oauth_tokens row spans every account
    # in accessible_accounts, billing is per ad account, and a dataset belongs to
    # an ad account or a business. One key per login would let an agency's client
    # A write conversions into client B's dataset.
    #
    # Resolved once and remembered: without this the dataset was re-derived from
    # Graph on every session, so a dataset the user had already accepted could be
    # replaced by a different one the next time the list came back in another
    # order. The default for this account, not a limit of one — the campaign
    # picker (media_ws.pixel_candidates) still chooses per campaign.
    tracking_dataset_id = Column(String(100), nullable=True)
    # The business portfolio the dataset lives in, when the ad account has one.
    # Null means the dataset sits on the ad account itself (personal accounts).
    tracking_business_id = Column(String(100), nullable=True)
    # Shared secret for POST /tracking/events — the customer's site or CRM sends
    # conversions with it. Rotatable from the tracking card; not a Meta token.
    tracking_ingest_key = Column(String(64), nullable=True)
    # Optional. An agency that wants server events to outlive an OAuth token
    # generates a system user token in THEIR OWN Business Settings and pastes it.
    # Encrypted for the same reason as access_token: it spends and reads on their
    # account. Left null for everyone else, who ride the OAuth token. A token is
    # minted per business, so an advertiser whose accounts sit in one portfolio
    # pastes the same one per account — a cheap duplicate next to being wrong for
    # a login that reaches two businesses.
    tracking_system_user_token = Column(EncryptedString, nullable=True)
    # The conversion event this account's campaigns optimize toward, in Meta's
    # custom_event_type enum form ("LEAD"). Remembered so the tracking card can
    # hand out a snippet that fires the SAME event the ad set is learning from —
    # a snippet firing Purchase under a LEAD ad set is a dataset that receives
    # everything except the event being optimized for. See meta_capi.event_name_for.
    tracking_event_type = Column(String(50), nullable=True)
    # How this account reports conversions: pixel_and_server / pixel_only /
    # lead_forms / offline_crm. Decides whether the tracking card hands out an
    # install snippet, a server ingest key, or neither — and whether a dataset
    # that has never fired is worth warning about, because a CRM upload never
    # fires a browser event and that warning is permanent noise for it.
    tracking_method = Column(String(32), nullable=True)
    # The Page whose leadgen webhook this account is subscribed to. Written when
    # an instant-form campaign publishes, and the only thing that can route an
    # inbound lead back to an ad account: Meta's delivery names the Page and
    # nothing that identifies us. Not oauth_tokens.page_id, which is whichever
    # Page Meta listed first at connect time rather than the one that published.
    tracking_lead_page_id = Column(String(100), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="ads_accounts")
    oauth_token = relationship("OAuthToken", back_populates="ads_accounts")
    subscription = relationship("UserSubscription", back_populates="ads_accounts")
