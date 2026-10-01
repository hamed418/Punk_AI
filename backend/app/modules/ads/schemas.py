from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.shared.enums import AdPlatform
from app.graph.meta_spec.models import LeadFormSpec
from app.modules.subscription.schemas import UserSubscriptionResponse
from uuid import UUID
class OAuthConnectResponse(BaseModel):
    authorization_url: str
    state: str  # CSRF token

class OAuthCallbackRequest(BaseModel):
    code: str
    state: str

class AdAccountConnectStatus(BaseModel):
    id:Optional[UUID]
    platform: AdPlatform
    connected: bool
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    accessible_accounts: Optional[List[Dict[str, Any]]] = None
    # Permissions this connection was never granted, and the card telling the
    # user to reconnect. Empty for a complete connection and for one minted
    # before Punk recorded scopes at all — see ads.service.missing_scopes.
    missing_scopes: List[str] = []
    remediation: List[Dict[str, Any]] = []

class LeadFormCreateRequest(BaseModel):
    """Create an Instant Form on a Page, now, from the campaign editor.

    The body IS a ``LeadFormSpec`` — the same model the plan carries for a form
    created at publish — so the editor's form builder has one shape to produce
    whichever button the user presses.
    """

    page_id: str = Field(min_length=1)
    form: LeadFormSpec


class LeadFormCreateResponse(BaseModel):
    id: str
    name: str


class AudienceItem(BaseModel):
    """One custom audience, as both the picker and the catalog show it."""

    id: str
    name: str
    subtype: str = ""
    size: Optional[int] = None
    # Meta's own delivery verdict. False means an ad set pointed at this audience
    # will not deliver — too small, still building, or expired — which is only
    # knowable by asking, and was the thing nothing in Punk ever asked.
    usable: bool = True
    status: str = ""


class LeadFormItem(BaseModel):
    """One instant form, with the Page it lives on."""

    id: str
    name: str | None = None
    status: str | None = None
    page_id: str
    page_name: str = ""


class ReadinessItem(BaseModel):
    """One thing the advertiser still has to do on a Meta screen.

    The wire shape of ``meta_remediation.render`` — see ``MetaRemediation`` in the
    frontend types. ``unverified`` means Punk cannot read the answer, so the user
    is asked to confirm it themselves rather than told it is missing.
    """

    key: str
    title: str
    cause: str
    steps: List[str]
    url: str = ""
    effect: str = ""
    severity: str = "warns"
    scope: str = ""
    unverified: bool = False


class LeadDeliveryItem(BaseModel):
    """Whether one Page's leads are reaching Punk.

    ``subscribed`` is Meta's own answer (the ``subscribed_apps`` read-back) and is
    ``None`` when Punk could not ask — which is what a missing ``pages_manage_metadata``
    looks like, and must never read as "off". ``routed`` is whether this Page is the
    one the selected ad account receives leads for: one Page per ad account, so
    routing a second Page moves it. ``remediation`` is only set by a failed connect.
    """

    page_id: str
    page_name: str = ""
    subscribed: Optional[bool] = None
    routed: bool = False
    remediation: List[ReadinessItem] = Field(default_factory=list)


class LeadDeliveryConnectRequest(BaseModel):
    page_id: str = Field(min_length=1)


class AudienceCreateRequest(BaseModel):
    """Build a website audience from a dataset the ad account can already write to."""

    name: str = Field(min_length=1, max_length=255)
    dataset_id: str = Field(min_length=1)
    # Empty means everyone the dataset has seen. A standard event name (or a
    # custom one) means the people who fired it — which is how the audience worth
    # EXCLUDING from prospecting gets built.
    event_name: str = Field(default="", max_length=100)
    retention_days: int = Field(default=180, ge=1, le=365)


class AudienceUsersRequest(BaseModel):
    """Add people to an audience from the advertiser's own customer list.

    Raw identifiers are normalized and SHA-256'd server-side before they reach
    Meta (``meta_capi.hash_user_field``) and are never stored — the same contract
    as ``POST /tracking/events``, which already accepts a raw email and phone.
    """

    # Parallel to ``rows``: schema ["EMAIL","PHONE"] means each row is
    # [email, phone]. Named rather than inferred so a column the caller thought
    # was a phone is never uploaded as an email digest.
    schema_fields: List[str] = Field(min_length=1)
    rows: List[List[str]] = Field(min_length=1, max_length=100_000)


class AudienceUsersResponse(BaseModel):
    uploaded: int


class AdsAccountResponse(BaseModel):
    subscription_id: Optional[UUID] = None
    subscription: Optional["UserSubscriptionResponse"] = None
    ad_account_id: Optional[str] = None
    ad_account_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

class OAuthTokenResponse(BaseModel):
    id: UUID
    platform: AdPlatform
    ad_account_id: Optional[str]
    ad_account_name: Optional[str]
    expires_at: Optional[datetime]
    is_valid: bool
    page_id: Optional[str]
    page_name: Optional[str]
    selected_account: Optional[str]
    scopes: Optional[List[str]]
    access_token: Optional[str]
    refresh_token: Optional[str]
    accessible_accounts: Optional[List[Dict[str, Any]]]
    meta_user_name: Optional[str]
    meta_user_image: Optional[str]
    ads_accounts: List[AdsAccountResponse] = []
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}