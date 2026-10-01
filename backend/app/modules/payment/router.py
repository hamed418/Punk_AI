from fastapi import APIRouter, Depends, status, HTTPException, Request, Header, Body
 
from sqlalchemy.ext.asyncio import AsyncSession
 

from typing import Optional
from app.core.config import settings
from app.core.logging import logger
from app.core.security import skip_api_key
from app.core.dependencies import get_db, get_current_user, get_optional_user
from app.modules.user.models import User 
 

from app.modules.payment.schemas import (
    StripeCheckoutRequest,
    StripePortalRequest,
    StripeSessionResponse,
    EarlyAccessPayload,
)
from app.modules.subscription.schemas import AssignAdsAccountRequest
from app.modules.subscription.repository import SubscriptionRepository
from app.modules.payment.service import PaymentService


router = APIRouter(tags=["Payment"])

repository = SubscriptionRepository()
service = PaymentService(repository)

@router.post("/subscription/checkout", response_model=StripeSessionResponse, status_code=status.HTTP_200_OK)
async def create_checkout_session(
    payload: StripeCheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    url = await service.create_subscription_checkout(db, payload, current_user)
    return StripeSessionResponse(url=url)


@router.post("/subscription/portal", response_model=StripeSessionResponse, status_code=status.HTTP_200_OK)
async def create_portal_session(
    payload: StripePortalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    return_url = payload.return_url or f"{settings.FRONTEND_URL}/subscription"
    url = await service.create_portal_session(db, return_url, current_user)
    return StripeSessionResponse(url=url)


@router.get(
    "/subscription/success",
    summary="Sync Stripe Checkout Payment",
    description="Callback endpoint called by the frontend or landing page after a successful Stripe checkout session to confirm payment."
)
@skip_api_key
async def subscription_success(
    session_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception as e:
        logger.error(f"Stripe session retrieve failed for {session_id}: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sync failed")

    metadata = session.metadata.to_dict() if hasattr(session.metadata, "to_dict") else dict(session.metadata or {})
    user_id_in_meta = metadata.get("user_id")

    # If the checkout was created for a logged-in user, enforce ownership
    if user_id_in_meta:
        if not current_user or str(current_user.id) != user_id_in_meta:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your checkout session")
    elif metadata.get("early_access") != "true":
        # If neither user_id nor early_access flag is present, reject unauthenticated calls
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid checkout session metadata")

    if session.payment_status not in ("paid", "no_payment_required"):
        logger.warning(f"Session {session_id} not paid yet.")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment not completed")

    await service.process_checkout_session_completed(db, session)
    logger.info(f"Subscription success callback handled for session_id: {session_id}")

    clean_email = (
        metadata.get("email")
        or (session.customer_details and session.customer_details.email)
        or ""
    )
    return {
        "success": True,
        "message": "Subscription synced successfully",
        "email": clean_email,
        "early_access": metadata.get("early_access") == "true"
    }


@router.post(
    "/early-access/checkout",
    response_model=StripeSessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Create Early Access Stripe Checkout Session",
    description="Initiates a Stripe checkout session for a new user entering their email on the landing page."
)
@skip_api_key
async def create_early_access_checkout_session(
    payload: EarlyAccessPayload,
    db: AsyncSession = Depends(get_db)
):
    url = await service.create_early_access_checkout(db, payload)
    return StripeSessionResponse(url=url)


@router.post("/token-upgrade/checkout", response_model=StripeSessionResponse, status_code=status.HTTP_200_OK)
async def create_token_upgrade_checkout(
    payload: StripeCheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Creates a Stripe checkout session for a one-time token upgrade.
    """
    url = await service.create_token_upgrade_checkout(db, payload, current_user)
    return StripeSessionResponse(url=url)


@router.post(
    "/subscription/assign-ad-account",
    status_code=status.HTTP_200_OK
)
async def assign_ad_account(
    payload: AssignAdsAccountRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    If none of the user's subscriptions has an ad_account_id,
    assign the ad_account_id to the latest subscription.
    Then update user's select_meta_id.
    """
    return await service.assign_ad_account(db, payload, current_user)


@router.post("/subscription/cancel", status_code=status.HTTP_200_OK)
async def cancel_subscription(
    subscription_id: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Cancel an active subscription.
    """
    return await service.cancel_subscription(db, subscription_id, current_user)


@router.post("/subscription/resume", status_code=status.HTTP_200_OK)
async def resume_subscription(
    subscription_id: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Undo a scheduled cancellation while the subscription is still running.
    """
    return await service.resume_subscription(db, subscription_id, current_user)


@router.post("/webhook/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db)
):  
    """
    Production-ready Stripe webhook handler.
    """
    payload_body = await request.body()
    try:
        await service.handle_stripe_webhook(db, payload_body, stripe_signature)
    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}")
        
    return {"status": "success"}
