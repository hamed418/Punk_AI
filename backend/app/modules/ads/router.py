import secrets
from urllib.parse import urlencode

from app.core.config import settings
from app.core.limiter import limiter
from app.core.security import skip_api_key
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_current_user, get_db
from app.core.logging import logger

from app.modules.ads.repository import AdsRepository
from app.modules.ads.service import AdsService, parse_meta_signed_request
from app.modules.ads.schemas import (
    AdAccountConnectStatus,
    AudienceCreateRequest,
    AudienceItem,
    AudienceUsersRequest,
    AudienceUsersResponse,
    LeadFormCreateRequest,
    LeadDeliveryConnectRequest,
    LeadDeliveryItem,
    LeadFormCreateResponse,
    LeadFormItem,
    OAuthConnectResponse,
    ReadinessItem,
)
from app.services.meta_ads import MetaAdsError

# Assuming User model is moved to auth or imported correctly
from app.modules.user.models import User

router = APIRouter(prefix="/ads", tags=["Ad Platforms"])

repository = AdsRepository()
service = AdsService(repository)

# "/verify" was never a real frontend route (only "/verify-email" exists) —
# every OAuth callback 404'd on landing. "/chat" is the actual app root
# (frontend/src/app/page.tsx redirects there); the connection state itself
# comes from GET /ads/status once the user is back in the app, not from this
# URL, so landing on the app root is enough.
FRONTEND_URL = settings.FRONTEND_URL + "/chat"

@router.post("/connect/meta", response_model=OAuthConnectResponse)
async def connect_meta(
    current_user: User = Depends(get_current_user),
) -> OAuthConnectResponse:
    result = service.build_meta_auth_url(str(current_user.id))
    return OAuthConnectResponse(
        authorization_url=result["authorization_url"],
        state=result["state"],
    )

def _meta_error_redirect(reason: str, detail: str = "") -> RedirectResponse:
    """Send the OAuth popup back to the app with a reason, not a raw JSON page.

    ``reason`` is one of a few short codes the frontend words itself (``denied``,
    ``expired``, ``failed``). ``detail`` is Meta's own ``error_description`` — safe
    prose about the user's own action — capped and URL-encoded. Internal exception
    text is never passed: it used to be echoed into a 500 body.
    """
    query = {"meta_error": reason}
    if detail:
        query["meta_error_detail"] = detail[:200]
    return RedirectResponse(url=f"{FRONTEND_URL}?{urlencode(query)}")


@router.get("/callback/meta")
@skip_api_key
async def meta_callback(
    # All optional: when Meta refuses (an account it has not opened the app to, a
    # cancelled consent screen, a misconfigured login) it redirects here with
    # ``error`` and NO ``code``. Required params turned that into a raw 422 in the
    # popup — the most likely failure of a private beta, worded worst.
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    if error or not (code and state):
        logger.warning(
            "Meta OAuth refused", error=error or "no code", detail=(error_description or "")[:200],
        )
        return _meta_error_redirect("denied", error_description or "")
    try:
        await service.exchange_meta_code(db, code, state)
        # Never put the access token in the redirect. It is a 60-day
        # ads_management credential, and a query string lands in browser
        # history, the Referer header of every subsequent request, and any
        # proxy/CDN access log. The token is already stored (encrypted) against
        # the user; the frontend reads connection state from GET /ads/status.
        redirect_url = f"{FRONTEND_URL}?connected=meta"
        return RedirectResponse(url=redirect_url)
    except ValueError as exc:
        logger.warning("Meta OAuth callback rejected", error=str(exc))
        return _meta_error_redirect("expired" if "state" in str(exc).lower() else "failed")
    except Exception as exc:
        logger.error("Meta OAuth callback failed", error=str(exc))
        return _meta_error_redirect("failed")

@router.get("/status", response_model=list[AdAccountConnectStatus])
async def get_connection_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AdAccountConnectStatus]:
    status_list = await service.get_connection_status(db, str(current_user.id))
    return [AdAccountConnectStatus(**s) for s in status_list]

@router.get("/targeting-search")
async def targeting_search(
    q: str = Query(..., min_length=1, description="Interest/behavior search text"),
    kind: str = Query("interests", pattern="^(interests|behaviors)$"),
    limit: int = Query(25, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Typeahead for the campaign editor's detailed-targeting (flexible_spec) field.

    Returns ``{"results": [{id, name, audience_size?, path?, flex_field}]}``.
    Degrades to an empty list when Meta is not connected or the search fails, so
    the editor never breaks on a lookup.
    """
    results = await service.search_meta_targeting(
        db, str(current_user.id), q, kind, limit
    )
    return {"results": results}


@router.get("/targeting-suggest")
async def targeting_suggest(
    session_id: str = Query("", description="Chat session — source of business context"),
    seeds: str = Query("", description="Comma-separated interest names already picked"),
    limit: int = Query(12, ge=1, le=25),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Autofill options for the editor's detailed-targeting field.

    With ``seeds`` it returns Meta's "more like this" for what the user already
    picked; without them it derives options from the session's business context.
    Same shape and same degrade-to-[] contract as /targeting-search.
    """
    results = await service.suggest_meta_targeting(
        db, str(current_user.id), session_id or None, seeds, limit
    )
    return {"results": results}


@router.get("/page-objects")
async def page_objects(
    page_id: str = Query(..., min_length=1, description="Facebook Page id"),
    kind: str = Query("post", pattern="^(post|video|event|instagram)$"),
    limit: int = Query(25, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Boostable Page objects for the campaign editor's post picker.

    Engagement's "On your post / video / event" conversion locations promote
    something that already exists on the Page, so the editor has to let the user
    choose it — and so does any ad whose creative source is "use an existing post".
    ``kind="instagram"`` lists the Page's linked Instagram media instead.

    Returns ``{"results": [{id, label, image, created_time, permalink}]}``
    and degrades to an empty list, like /targeting-search.
    """
    results = await service.list_page_objects(
        db, str(current_user.id), page_id, kind, limit
    )
    return {"results": results}


@router.get("/ad-posts")
async def ad_posts(
    limit: int = Query(25, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The posts behind this account's previous ads, for the same picker.

    "Reuse a post from an older ad" on the intake form: the new ad promotes the
    post an earlier ad ran, so its reactions and comments carry over. Account
    scoped rather than Page scoped — an inline unpublished post is not on the
    Page — so there is no page_id to pass.

    Returns ``{"results": [{id, label, image, created_time, permalink, source}]}``
    where ``id`` is the post and ``source`` says which creative field it lands on.
    Degrades to an empty list like /page-objects.
    """
    results = await service.list_previous_ad_posts(db, str(current_user.id), limit)
    return {"results": results}


@router.get("/campaign-tree")
async def campaign_tree(
    campaign_id: str = Query(..., min_length=1, description="Previous campaign id"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One previous campaign's ad sets + ads, for the editor's "what to copy" picker.

    Returns ``{"adsets": [{id, name, ads: [{id, name}]}]}`` and degrades to an
    empty list, like /page-objects — the editor then falls back to copying the
    whole campaign.
    """
    adsets = await service.list_campaign_structure(
        db, str(current_user.id), campaign_id
    )
    return {"adsets": adsets}


@router.get("/ad-previews")
async def ad_previews(
    ad_id: str = Query(..., min_length=1, description="Published ad id"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Meta's own rendering of a published ad, one entry per placement.

    Returns ``{"previews": [{format, label, src}]}`` where ``src`` is the Graph
    preview iframe URL. Fetched here rather than baked into the graph's
    pending_action because those URLs are short-lived — the client asks when it
    opens the preview, not when the step was emitted. Degrades to [].
    """
    previews = await service.list_ad_previews(db, str(current_user.id), ad_id)
    return {"previews": previews}


@router.get("/leads")
async def form_leads(
    form_id: str = Query(..., min_length=1, description="Instant form id"),
    page_id: str = Query("", description="The form's Page — lets the read use its Page token"),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Leads collected by one instant form.

    Returns ``{"results": [{id, created_time, fields}]}`` — ``fields`` is
    ``{question: answer}``, flat, because that is what a table or a CSV export
    wants. Degrades to an empty list, EXCEPT on a missing permission: an empty
    table reads as "no leads yet", which is the one wrong answer here.
    """
    try:
        results = await service.list_form_leads(
            db, str(current_user.id), form_id, limit, page_id
        )
    except MetaAdsError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, exc.user_msg or str(exc)
        ) from exc
    return {"results": results}


@router.get("/lead-forms", response_model=list[LeadFormItem])
async def list_lead_forms(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LeadFormItem]:
    """Every instant form on the Pages the user shared, for the leads table.

    Degrades to an empty list like the other reads behind a picker.
    """
    return [
        LeadFormItem(**row)
        for row in await service.list_lead_form_choices(db, str(current_user.id))
    ]


@router.post("/lead-forms", response_model=LeadFormCreateResponse)
async def create_lead_form(
    payload: LeadFormCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadFormCreateResponse:
    """Create an Instant Form on the user's Page from the campaign editor.

    The editor's other option is to carry the same form as a ``lead_form_draft``
    on the plan and let publish create it. This endpoint is the "I want it now"
    path: the form exists on the Page immediately, so the user can preview it in
    Meta and reuse it across campaigns.

    Unlike the read endpoints above this does NOT degrade — a form the user
    thinks exists but does not is worse than an error.
    """
    try:
        created = await service.create_page_lead_form(
            db, str(current_user.id), payload.page_id, payload.form
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except MetaAdsError as exc:
        # user_msg carries the actionable wording (e.g. the missing-permission
        # hint); str(exc) is the raw Graph error.
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, exc.user_msg or str(exc)
        ) from exc
    return LeadFormCreateResponse(**created)


@router.get("/lead-delivery", response_model=list[LeadDeliveryItem])
async def lead_delivery(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LeadDeliveryItem]:
    """Per Page: is Meta pushing its leads at Punk, and to the selected ad account?"""
    return [
        LeadDeliveryItem(**row)
        for row in await service.list_lead_delivery(db, str(current_user.id))
    ]


@router.post("/lead-delivery", response_model=LeadDeliveryItem)
async def connect_lead_delivery(
    payload: LeadDeliveryConnectRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadDeliveryItem:
    """Subscribe Punk to a Page's leads and route them to the selected ad account."""
    try:
        row = await service.connect_lead_delivery(db, str(current_user.id), payload.page_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return LeadDeliveryItem(**row)


@router.get("/readiness", response_model=list[ReadinessItem])
async def meta_readiness(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ReadinessItem]:
    """Everything the connected advertiser still has to do on a Meta screen.

    Meant to be read right after connecting, so a new user sees the whole list at
    once instead of meeting each item as a separate publish failure. Empty when
    nothing is outstanding or Meta is not connected.
    """
    return [
        ReadinessItem(**card)
        for card in await service.get_readiness(db, str(current_user.id))
    ]


@router.get("/audiences", response_model=list[AudienceItem])
async def list_audiences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AudienceItem]:
    """The ad account's custom audiences, for the plan editor's pickers.

    Degrades to an empty list like the other reads behind a picker — an empty
    dropdown is a state the editor already handles, a 500 is not.
    """
    return [
        AudienceItem(**row)
        for row in await service.list_audiences(db, str(current_user.id))
    ]


@router.post("/audiences", response_model=AudienceItem)
async def create_audience(
    payload: AudienceCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AudienceItem:
    """Build an audience from the people the advertiser's dataset has seen.

    The other end of conversion tracking. The pixel and the Conversions API fill
    a dataset; this is what lets the advertiser advertise to the people in it —
    or, with an event name, build the converters list worth excluding from
    prospecting.

    Does NOT degrade, for the same reason ``/lead-forms`` does not: an audience
    the user believes exists but does not shows up as an ad set delivering to
    nobody.
    """
    try:
        created = await service.create_website_audience(
            db, str(current_user.id),
            name=payload.name,
            dataset_id=payload.dataset_id,
            event_name=payload.event_name,
            retention_days=payload.retention_days,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except MetaAdsError as exc:
        # The likeliest rejection here is one only the user can clear — the
        # Custom Audience Terms, which Meta will not let an API accept on their
        # behalf. A raw Graph string tells them nothing, so the catalog's own
        # wording is used when it recognizes the error.
        from app.services import meta_remediation

        fix = meta_remediation.resolve(exc, step="custom_audience", scope="audience")
        detail = exc.user_msg or str(exc)
        if fix:
            detail = f"{fix.title}. {fix.steps[0]}" if fix.steps else fix.title
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail) from exc
    return AudienceItem(**created)


@router.post("/audiences/{audience_id}/users", response_model=AudienceUsersResponse)
async def add_audience_users(
    audience_id: str,
    payload: AudienceUsersRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AudienceUsersResponse:
    """Add the advertiser's own customer list to an audience.

    Identifiers arrive raw and are normalized and hashed before they leave the
    process; nothing here is stored. Same contract as ``POST /tracking/events``,
    which already accepts a raw email and phone for exactly this reason — the
    hashing rules are Meta's and getting them wrong produces a digest that is
    accepted, matches nobody, and reports success.
    """
    try:
        uploaded = await service.add_audience_users(
            db, str(current_user.id), audience_id,
            schema_fields=payload.schema_fields,
            rows=payload.rows,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except MetaAdsError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, exc.user_msg or str(exc)
        ) from exc
    return AudienceUsersResponse(uploaded=uploaded)


@router.delete("/disconnect/meta")
async def disconnect_meta(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    success = await service.disconnect_meta(db, str(current_user.id))
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No connected Meta Ads account found."
        )
    return {"status": "success", "message": "Meta Ads account disconnected successfully."}

@router.delete("/disconnect/connection/{token_id}")
async def disconnect_meta_connection(
    token_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    success = await service.disconnect_connection_by_id(db, str(current_user.id), token_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No connection found with this ID."
        )
    return {"status": "success", "message": "Connection disconnected successfully."}


@router.delete("/accounts/meta/{ad_account_id}")
async def remove_meta_ads_account(
    ad_account_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    outcome = await service.remove_ads_account(db, str(current_user.id), ad_account_id)
    if outcome == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No such ad account on this Meta connection.",
        )
    if outcome == "paid":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cancel the subscription for this ad account before removing it.",
        )
    return {"status": "success", "message": "Ad account removed successfully."}


# The two Meta callbacks that hand a person a confirmation code (Data
# Deletion Request + Deauthorize). Recorded the same way in audit_logs, keyed
# by that code in `resource_id` (String(100), plenty of room for
# token_hex(12)) so the status endpoint finds the row on the indexed `action`
# column instead of scanning a JSON blob.
META_SIGNED_REQUEST_ACTIONS = ("meta.data_deletion_processed", "meta.deauthorized")


async def _record_meta_signed_request(request: Request, action: str) -> dict:
    """Verify Meta's signed_request, record it durably, answer Meta's required
    ``{url, confirmation_code}`` shape.

    Deletes nothing. Under Facebook Login for Business the token minted is a
    Business Integration System User token, so the person's app-scoped id —
    the only id this payload ever carries — is unobtainable at connect time
    (``/me`` on that token returns the system user, not the person) and
    cannot be matched to a Punk account. There was a ``users.select_meta_id``
    lookup here; it was matching an ASID against a column that, on every
    write path in this codebase, actually holds a *selected ad account id*
    (``act_...`` — see ``app/modules/payment/service.py`` and
    ``app/modules/user/service.py``), so it could only ever miss or, worse,
    match the wrong person.

    That is fine to admit, because Punk holds no person-scoped Meta data to
    delete in the first place: ``tracking_events`` stores no identifiers
    (``app/modules/tracking/models.py``), leadgen leads are hashed and
    forwarded without being stored, and the OAuth connection's own
    ``meta_user_name`` is a business name, not a person's. What is owed is a
    truthful, durable record — this writes one.

    Always answers 200 once the signature verifies (Meta redelivers on
    anything else, same reasoning as the leadgen webhook), even when the
    audit write itself fails — the confirmation code is still handed back so
    the status URL resolves, and the failure is logged for a human to notice.
    """
    form = await request.form()
    signed_request = str(form.get("signed_request") or "")
    payload = parse_meta_signed_request(signed_request, settings.META_APP_SECRET)
    if payload is None:
        raise HTTPException(status_code=401, detail="invalid signed_request")

    confirmation_code = secrets.token_hex(12)
    try:
        from app.db.database import AsyncSessionLocal
        from app.modules.auditLogs.repository import AuditLogRepository
        from app.modules.auditLogs.schemas import AuditLogRequest

        async with AsyncSessionLocal() as audit_db:
            row = await AuditLogRepository().create_audit_logs(
                audit_db,
                AuditLogRequest(
                    action=action,
                    resource_type="meta_signed_request",
                    resource_id=confirmation_code,
                    new_data={
                        "meta_user_id": str(payload.get("user_id") or "") or None,
                        "connection_deleted": False,
                    },
                ),
            )
        # create_audit_logs swallows its own failures and returns None on one —
        # the one way to notice the record we just promised Meta did not land.
        if row is None:
            raise RuntimeError("audit log write returned None")
    except Exception as exc:  # noqa: BLE001 — a 200 is still owed; Meta redelivers otherwise
        logger.error(
            "meta %s: confirmation_code=%s was NOT recorded — %s",
            action, confirmation_code, exc,
        )

    status_url = f"{settings.BACKEND_PUBLIC_URL}/ads/data-deletion/meta/status?code={confirmation_code}"
    return {"url": status_url, "confirmation_code": confirmation_code}


@router.post("/data-deletion/meta")
@skip_api_key
@limiter.limit("60/minute")
async def meta_data_deletion_callback(request: Request) -> dict:
    """Meta's Data Deletion Request Callback — fired when a person removes
    Punk from their Meta account (or otherwise asks Meta to have Punk delete
    their data), independently of whether they are logged into Punk.
    Unauthenticated in every ordinary sense — no login, no API key —
    ``signed_request`` (form-encoded, HMAC-SHA256 over the app secret) IS the
    authentication. See ``_record_meta_signed_request`` for what this does
    and does not delete."""
    return await _record_meta_signed_request(request, "meta.data_deletion_processed")


@router.post("/deauthorize/meta")
@skip_api_key
@limiter.limit("60/minute")
async def meta_deauthorize_callback(request: Request) -> dict:
    """Meta's Deauthorize Callback — fired when a person removes Punk's
    access from their Meta account. Separate App Dashboard field from the
    Data Deletion Request URL above; same ``signed_request`` verification,
    same durable record, different action label."""
    return await _record_meta_signed_request(request, "meta.deauthorized")


@router.get("/data-deletion/meta/status")
@skip_api_key
@limiter.limit("60/minute")
async def meta_data_deletion_status(
    request: Request,
    code: str = Query(""),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The page Meta's UI links a person to after a deletion or deauthorize
    request — reports what the callback above actually recorded, keyed by
    the confirmation code in its URL. An unrecognized code (never issued, or
    the audit write that would have recorded it failed) answers
    ``status: "unknown"`` rather than a hardcoded "completed" — this page is
    what a regulator or the person themselves may check."""
    from app.modules.auditLogs.models import AuditLog

    result = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.action.in_(META_SIGNED_REQUEST_ACTIONS),
            AuditLog.resource_id == code,
        )
        .limit(1)
    )
    # .first(), not scalar_one_or_none(): resource_id is not a unique column,
    # and a person waiting on this page should never see a 500 over it.
    row = result.scalars().first()
    if row is None:
        return {
            "confirmation_code": code,
            "status": "unknown",
            "detail": "No request with this confirmation code was received.",
        }
    deleted = bool((row.new_data or {}).get("connection_deleted"))
    return {
        "confirmation_code": code,
        "status": "completed",
        "received_at": row.created_at.isoformat() if row.created_at else None,
        "detail": (
            "The Meta connection and everything derived from it was deleted."
            if deleted else
            "Request received and recorded. Punk holds no personal data from "
            "your Meta account — the connection here is to a business ad "
            "account, and nothing person-scoped is stored — so there was "
            "nothing further to delete."
        ),
    }


@router.post("/connect/google", response_model=OAuthConnectResponse)
async def connect_google(
    current_user: User = Depends(get_current_user),
) -> OAuthConnectResponse:
    result = service.build_google_auth_url(str(current_user.id))
    return OAuthConnectResponse(
        authorization_url=result["authorization_url"],
        state=result["state"],
    )

@router.get("/callback/google")
async def google_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    try:
        await service.exchange_google_code(db, code, state)
        # Same reasoning as the Meta callback above — no token in the URL.
        redirect_url = f"{FRONTEND_URL}?connected=google"
        return RedirectResponse(url=redirect_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Google OAuth callback failed", error=str(exc))
        raise HTTPException(
            status_code=500, 
            detail=f"OAuth exchange failed: {str(exc)}"
        )

@router.delete("/disconnect/google")
async def disconnect_google(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    success = await service.disconnect_google(db, str(current_user.id))
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No connected Google Ads account found."
        )
    return {"status": "success", "message": "Google Ads account disconnected successfully."}
