"""Conversion tracking endpoints.

``POST /tracking/events``, ``/tracking/leads`` and ``/tracking/webhook`` are the
only routes in Punk that a machine outside Punk calls directly: the first two by
the advertiser's own website, server or CRM, the third by Meta. That makes all
three a trust boundary, so they are ``@skip_api_key`` (the platform key is Punk's,
not something to hand every customer's website) and authenticate on their own
credential instead, under a rate limit — the per-tenant ingest key for the first
two, an HMAC signature over the raw body for the webhook.

Everything else here is a normal authenticated read for the UI.
"""
import hashlib
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger

from app.core.dependencies import get_current_user, get_db
from app.core.limiter import limiter
from app.core.security import skip_api_key
from app.shared.pagination import PaginatedResponse, PaginationParams, paginate
from app.modules.ads.repository import AdsRepository
from app.modules.user.models import User
from app.modules.tracking.schemas import (
    CustomConversionRequest,
    CustomConversionResponse,
    TrackingDatasetRequest,
    TrackingDatasetsResponse,
    TrackingEventBatch,
    TrackingEventLogItem,
    TrackingMethodRequest,
    TrackingSystemTokenRequest,
    TrackingEventResponse,
    TrackingHealthResponse,
    TrackingSnippetResponse,
)
from app.modules.tracking.service import INGEST_KEY_HEADER, TrackingError, TrackingService

router = APIRouter(prefix="/tracking", tags=["Conversion Tracking"])

service = TrackingService(AdsRepository())


def _client_ip(request: Request) -> str:
    """The visitor's IP, not our load balancer's.

    ``x-forwarded-for`` is a comma-separated chain; the first entry is the client.
    Same handling as the waitlist module. It matters here because the IP is one of
    the identifiers Meta matches on.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


@router.post("/events", response_model=TrackingEventResponse)
@skip_api_key
@limiter.limit("600/minute")
async def ingest_events(
    request: Request,
    batch: TrackingEventBatch,
    tracking_key: str = Header("", alias=INGEST_KEY_HEADER),
    db: AsyncSession = Depends(get_db),
) -> TrackingEventResponse:
    """Report conversions to the advertiser's own Meta dataset.

    Called by their site or server, not by Punk's frontend. The browser pixel
    reports what the browser can; this reports what actually happened.
    """
    try:
        result = await service.send(
            db,
            ingest_key=tracking_key,
            batch=batch,
            client_ip=_client_ip(request),
            user_agent=request.headers.get("user-agent", ""),
        )
    except TrackingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return TrackingEventResponse(**result)


@router.post("/leads", response_model=TrackingEventResponse)
@skip_api_key
@limiter.limit("600/minute")
async def ingest_leads(
    request: Request,
    batch: TrackingEventBatch,
    tracking_key: str = Header("", alias=INGEST_KEY_HEADER),
    db: AsyncSession = Depends(get_db),
) -> TrackingEventResponse:
    """Send lead-stage events back for instant-form leads (CAPI for CRM).

    Same pipe as /events with one difference that carries the whole value: a lead
    that came from a Meta instant form is identified by its ``lead_id``, and
    reporting which of those leads the sales team actually qualified is what lets
    the Conversion Leads goal optimize for quality instead of volume.

    ``action_source`` defaults to ``system_generated`` here because a CRM stage
    change is not a website action.
    """
    for event in batch.events:
        if not event.lead_id:
            raise HTTPException(
                status_code=422,
                detail=(
                    "lead_id is required on /tracking/leads — it is what ties the "
                    "event to the instant-form lead Meta already knows about. Use "
                    "/tracking/events for website conversions."
                ),
            )
        if "action_source" not in event.model_fields_set:
            event.action_source = "system_generated"
    try:
        result = await service.send(
            db,
            ingest_key=tracking_key,
            batch=batch,
            client_ip=_client_ip(request),
            user_agent=request.headers.get("user-agent", ""),
        )
    except TrackingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return TrackingEventResponse(**result)


@router.get("/webhook", response_class=PlainTextResponse)
@skip_api_key
async def verify_webhook(
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
) -> PlainTextResponse:
    """Meta's one-time subscription handshake.

    The challenge has to come back as bare text — Meta compares the body against
    what it sent, and a JSON-quoted copy is not equal to it.

    An unset ``META_WEBHOOK_VERIFY_TOKEN`` refuses every handshake rather than
    accepting any token offered: a deployment that has not configured the webhook
    should not be subscribable by whoever asks first.
    """
    expected = settings.META_WEBHOOK_VERIFY_TOKEN
    if not expected:
        # Named out loud, because a missing setting and a wrong token were the
        # same silent 403 — and this handshake happens once per deployment, in
        # Meta's dashboard, where nobody is watching our logs at the time.
        logger.error(
            "tracking webhook: META_WEBHOOK_VERIFY_TOKEN is not set, so every "
            "subscription handshake is refused and no instant-form lead can ever "
            "be delivered. Set it here and in the Meta App dashboard's webhook "
            "config to the same value."
        )
    if mode != "subscribe" or not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="verification failed")
    return PlainTextResponse(challenge)


@router.post("/webhook")
@skip_api_key
@limiter.limit("600/minute")
async def receive_webhook(
    request: Request,
    signature: str = Header("", alias="X-Hub-Signature-256"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Instant-form leads, pushed by Meta as they are submitted.

    This endpoint is unauthenticated in every ordinary sense — no login, no API
    key, no ingest key — so the signature IS the authentication, and it is checked
    over the RAW body before anything is parsed out of it. Without it, anyone who
    learned the URL could report conversions into any tenant's dataset.

    The 200 is deliberately unconditional once the signature holds. Meta redelivers
    a non-200 and disables a subscription that keeps failing, so one unreadable
    lead must not cost the advertiser every later one — ``ingest_leadgen`` absorbs
    per-lead failures and reports how many actually went out.
    """
    raw = await request.body()
    secret = settings.META_APP_SECRET
    expected = "sha256=" + hmac.new(
        secret.encode(), raw, hashlib.sha256,
    ).hexdigest()
    if not (secret and signature and hmac.compare_digest(signature, expected)):
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = await request.json()
    if str(payload.get("object") or "") != "page":
        # Something else this app is subscribed to. Acknowledged, not acted on.
        return {"forwarded": 0}
    return await service.ingest_leadgen(db, payload.get("entry") or [])


@router.get("/events/log", response_model=PaginatedResponse[TrackingEventLogItem])
async def list_tracking_events(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(),
) -> PaginatedResponse[TrackingEventLogItem]:
    """What Punk forwarded to this account's dataset, newest first.

    A normal authenticated read, unlike the ingest routes above: it is the
    advertiser looking at their own account in Punk, not their website calling in.
    Declared before the ``/health`` route only for grouping — ``/events/log`` and
    the ``POST /events`` ingest are different methods on different paths and do
    not shadow each other.
    """
    try:
        rows, total = await service.recent_events(
            db, str(current_user.id), skip=pagination.skip, limit=pagination.limit,
        )
    except TrackingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return paginate(
        total=total,
        page=pagination.page,
        limit=pagination.limit,
        data=[
            TrackingEventLogItem.model_validate(
                {**row.__dict__, "id": str(row.id)}
            )
            for row in rows
        ],
    )


@router.get("/health", response_model=TrackingHealthResponse)
async def tracking_health(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrackingHealthResponse:
    """Whether this account's tracking is measuring anything, and how well.

    Read by the publish preview before offering to go live: a dataset that has
    never fired means the campaign is about to optimize toward an event that never
    arrives, and the user should know that before spending.
    """
    try:
        return TrackingHealthResponse(**await service.health(db, str(current_user.id)))
    except TrackingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/snippet", response_model=TrackingSnippetResponse)
async def tracking_snippet(
    # Empty means "the event this account's campaigns optimize toward". The card
    # only sends a name when the user picks a different one from the list the
    # response itself carries.
    event_name: str = Query("", max_length=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrackingSnippetResponse:
    """The install helper — pixel code, the event call, and the server example."""
    try:
        return TrackingSnippetResponse(
            **await service.snippet(db, str(current_user.id), event_name=event_name)
        )
    except TrackingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/datasets", response_model=TrackingDatasetsResponse)
async def list_datasets(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrackingDatasetsResponse:
    """Datasets this ad account can write to, for the picker.

    Read live from Meta rather than off the stored row: the user who opens this is
    usually the one who just created a Pixel in Events Manager, and a cached list
    is exactly the list without it.
    """
    try:
        return TrackingDatasetsResponse(
            **await service.datasets(db, str(current_user.id))
        )
    except TrackingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/dataset", response_model=dict)
async def set_dataset(
    payload: TrackingDatasetRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Attach a dataset by hand.

    The other half of the two error messages that told users to "pick a dataset in
    Punk" when nothing here could.
    """
    try:
        return {"dataset_id": await service.set_dataset(
            db, str(current_user.id), payload.dataset_id,
        )}
    except TrackingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/custom-conversion", response_model=CustomConversionResponse)
async def create_custom_conversion(
    payload: CustomConversionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CustomConversionResponse:
    """Turn a page URL into a conversion Meta can optimize toward.

    For the advertiser whose base pixel is installed and whose thank-you page has
    no event code: the PageViews are already arriving, and this is the rule that
    makes one of them count. No developer, no deploy, no change to their site.
    """
    try:
        return CustomConversionResponse(**await service.create_custom_conversion(
            db, str(current_user.id),
            name=payload.name,
            url_contains=payload.url_contains,
            custom_event_type=payload.custom_event_type,
        ))
    except TrackingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/method", response_model=dict)
async def set_method(
    payload: TrackingMethodRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Change how conversions reach Meta.

    Publish derives this from the shape of the campaign and an express Sales run
    lands on ``pixel_only`` — whose own instructions tell the advertiser to switch
    to server events when ad blockers start costing them conversions. This is that
    switch.
    """
    try:
        return {"method": await service.set_method(
            db, str(current_user.id), payload.method,
        )}
    except TrackingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/token", response_model=dict)
async def set_system_token(
    payload: TrackingSystemTokenRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Store a system user token for this account's server events, or clear it.

    Never echoed back — the response says whether one is set, nothing more. The
    token is the advertiser's own credential; Punk holds no platform Meta token.
    """
    try:
        return {"configured": await service.set_system_user_token(
            db, str(current_user.id), payload.token,
        )}
    except TrackingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/key/rotate", response_model=dict)
async def rotate_key(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Issue a new ingest key and invalidate the old one.

    Breaks whatever is currently posting conversions until the new key is
    installed — which is the point of a rotation, and why it is an explicit action
    rather than something Punk does on a schedule.
    """
    try:
        return {"ingest_key": await service.rotate_ingest_key(db, str(current_user.id))}
    except TrackingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
