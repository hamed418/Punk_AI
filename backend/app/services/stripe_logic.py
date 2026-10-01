from app.shared.enums import SubscriptionPaymentStatus
import stripe
import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException, status
from app.core.logging import logger
from app.core.config import settings
# from app.modules.user.models import User
# from app.modules.payment.models import UserSubscription
from app.modules.user.models import User
from app.modules.subscription.models import UserSubscription
from app.shared.enums import SubscriptionStatus

stripe.api_key = settings.STRIPE_SECRET_KEY
FRONTEND_URL = settings.FRONTEND_URL


def _period_end(stripe_sub) -> Optional[datetime]:
    """The end of the current billing period on a Stripe subscription, or None.

    Newer API versions carry it on the item, older ones at the top level. Missing
    is None on purpose — NOT sync_subscription_status's fallback to start_date /
    created: that yields a date in the PAST, and a past current_period_end makes
    ad_account_is_paid() reject a paid account. None means "unknown", which the UI
    words as "the end of the billing period".
    """
    data = stripe_sub.to_dict() if hasattr(stripe_sub, "to_dict") else dict(stripe_sub or {})
    item = ((data.get("items") or {}).get("data") or [None])[0] or {}
    ts = item.get("current_period_end") or data.get("current_period_end")
    return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None


class StripeService:
    @staticmethod
    async def get_or_create_customer(db: AsyncSession, user: User) -> str:
        """Get existing Stripe customer ID or create a new one."""
        if user.stripe_customer_id:
            return user.stripe_customer_id

        try:
            customer = stripe.Customer.create(
                email=user.email,
                name=user.full_name,
                metadata={"user_id": str(user.id)}
            )
            user.stripe_customer_id = customer.id
            db.add(user)
            await db.commit()
            return customer.id
        except stripe.error.StripeError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Stripe error: {str(e)}"
            )

    @staticmethod
    async def create_checkout_session(
        db: AsyncSession, 
        user: User, 
        amount: float,
        plan_name: str,
        user_subscription_id: str,
        ad_account_id: str,
        coupon_code: Optional[str] = None,
    ) -> str:
        """Generate a Stripe Checkout Session URL using a dynamic amount."""
        from app.modules.ads.models import AdsAccount

        # 2. Check if an active subscription already exists for this ad_account_id
        # query = select(UserSubscription).where(UserSubscription.user_id == user.id)
        # if ad_account_id:
        #     query = query.where(UserSubscription.ad_account_id == ad_account_id)
        # else:
        #     query = query.where(UserSubscription.ad_account_id.is_(None))
            
        # sub_res = await db.execute(query)
        # existing_sub = sub_res.scalars().first()
        # if existing_sub and existing_sub.status in [SubscriptionStatus.active, SubscriptionStatus.trialing]:
        #     if not existing_sub.current_period_end or existing_sub.current_period_end.replace(tzinfo=None) > datetime.utcnow():
        #         raise HTTPException(
        #             status_code=status.HTTP_400_BAD_REQUEST,
        #             detail="SUBSCRIPTION_ALREADY_ACTIVE"
        #         )

        customer_id = await StripeService.get_or_create_customer(db, user)

        try:
            # ad_account_id rides along so the checkout.session.completed fallback
            # (payment/service._handle_subscription_checkout) can build a SCOPED
            # subscription. Without it that fallback minted ad_account_id=NULL,
            # which ad_account_is_paid() rejects forever — a paid subscription
            # that authorizes nothing, with nothing left to recover it from.
            metadata = {
                "user_id": str(user.id),
                "subscription_id": user_subscription_id,
                "ad_account_id": ad_account_id,
            }
            if coupon_code:
                metadata["coupon_code"] = coupon_code
            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": plan_name,
                        },
                        "unit_amount": int(round(amount * 100)),
                        "recurring": {"interval": "month"}
                    },
                    "quantity": 1
                }],
                mode="subscription",
                success_url=f"{FRONTEND_URL}/subscription/success?session_id={{CHECKOUT_SESSION_ID}}&subscription_id={user_subscription_id}",
                cancel_url=f"{FRONTEND_URL}/subscription/cancel?session_id={{CHECKOUT_SESSION_ID}}",
                client_reference_id=str(user.id),
                metadata=metadata,
                subscription_data={
                    "metadata": metadata
                }
            )
            return session.url
        except stripe.error.InvalidRequestError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Stripe error: {str(e)}"
            )
        except stripe.error.StripeError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Stripe error: {str(e)}"
            )
    @staticmethod
    async def create_checkout_session_with_early_access(
        db: AsyncSession, 
        email: str, 
        amount: float,
        plan_name: str,
        subscription_id: str,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
    ) -> str:
        """Generate a Stripe Checkout Session URL using a dynamic amount for early access."""
        from app.modules.ads.models import AdsAccount
      
        # Check if an active subscription already exists for this email
        sub_res = await db.execute(
            select(UserSubscription).where(
                UserSubscription.email == email,  
            )
        )
        existing_sub = sub_res.scalar_one_or_none()
        if existing_sub and existing_sub.status in [SubscriptionStatus.active]:
            if not existing_sub.current_period_end or existing_sub.current_period_end.replace(tzinfo=None) > datetime.utcnow():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Early access subscription already active"
                )

        if not settings.STRIPE_SECRET_KEY:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="STRIPE_SECRET_KEY is not configured in backend .env."
            )

        final_success_url = success_url or f"{FRONTEND_URL}/subscription/success?success=true&session_id={{CHECKOUT_SESSION_ID}}&subscription_id={subscription_id}&email={email}"
        final_cancel_url = cancel_url or f"{FRONTEND_URL}/subscription/cancel?success=true&session_id={{CHECKOUT_SESSION_ID}}&subscription_id={subscription_id}&email={email}"

        try:
            customer = stripe.Customer.create(
                email=email,
                name=email
            )
            customer_id = customer.id

            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": plan_name,
                        },
                        "unit_amount": int(amount * 100),
                        "recurring": {"interval": "month"}
                    },
                    "quantity": 1
                }],
                mode="subscription",
                success_url=final_success_url,
                cancel_url=final_cancel_url,
                metadata={"email": str(email), "subscription_id": subscription_id, "early_access": "true"},
                subscription_data={
                    "metadata": {"email": str(email), "subscription_id": subscription_id, "early_access": "true"}
                }
            )
              
            return session.url
        except stripe.error.InvalidRequestError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Stripe error: {str(e)}"
            )
        except stripe.error.StripeError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Stripe error: {str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Stripe checkout creation failed: {str(e)}"
            )
    @staticmethod
    async def create_portal_session(db: AsyncSession, user: User, return_url: str) -> str:
        """Generate a Stripe Customer Portal URL."""
        customer_id = await StripeService.get_or_create_customer(db, user)

        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url
            )
            return session.url
        except stripe.error.StripeError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Stripe error: {str(e)}"
            )



    @staticmethod
    async def create_token_upgrade_session(
        db: AsyncSession, 
        user: User, 
        amount: float,
        token_amount: int
    ) -> str:
        """Generate a Stripe Checkout Session for a one-time token upgrade."""
        customer_id = await StripeService.get_or_create_customer(db, user)

        try:
            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": f"Token Upgrade ({token_amount} tokens)",
                        },
                        "unit_amount": int(amount * 100),
                    },
                    "quantity": 1
                }],
                mode="payment",
                success_url=f"{FRONTEND_URL}/subscription/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{FRONTEND_URL}/subscription/cancel?session_id={{CHECKOUT_SESSION_ID}}",
                client_reference_id=str(user.id),
                metadata={"user_id": str(user.id), "token_upgrade": "true", "token_amount": str(token_amount)}
            )
            return session.url
        except stripe.error.StripeError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Stripe error: {str(e)}"
            )

    @staticmethod
    async def _owned_subscription(db: AsyncSession, user: User, subscription_id) -> UserSubscription:
        """This user's UserSubscription with a Stripe subscription behind it, else 404."""
        from sqlalchemy import select

        try:
            # A non-UUID id used to reach the query and raise a DataError (a 500) on Postgres.
            sub_id = uuid.UUID(str(subscription_id))
        except ValueError:
            raise HTTPException(status_code=404, detail="Active subscription not found")

        result = await db.execute(select(UserSubscription).where(
            UserSubscription.id == sub_id,
            UserSubscription.user_id == user.id
        ))
        user_sub = result.scalar_one_or_none()
        if not user_sub or not user_sub.stripe_subscription_id:
            raise HTTPException(status_code=404, detail="Active subscription not found")
        return user_sub

    @staticmethod
    async def cancel_subscription(db: AsyncSession, user: User, subscription_id: str) -> dict:
        """Cancel a subscription at the END of the period the user has paid for."""
        user_sub = await StripeService._owned_subscription(db, user, subscription_id)

        if user_sub.status not in (SubscriptionStatus.active, SubscriptionStatus.trialing):
            raise HTTPException(status_code=409, detail="This subscription has already ended.")
        if user_sub.cancel_at_period_end:
            # Already scheduled: a double-click or a second tab is a no-op, not a
            # second Stripe call.
            return {"cancel_at_period_end": True, "current_period_end": user_sub.current_period_end}

        try:
            stripe_sub = stripe.Subscription.modify(
                user_sub.stripe_subscription_id,
                cancel_at_period_end=True
            )
        except stripe.error.StripeError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Only the flag. status/payment_status used to flip to canceled here,
        # but this is cancel-AT-PERIOD-END: the user has paid through
        # current_period_end and ad_account_is_paid() keys off status, so
        # flipping it cut access immediately. Stripe's subscription.updated /
        # .deleted webhooks (sync_subscription_status) move status when it is true.
        user_sub.cancel_at_period_end = True
        # Checkout never writes current_period_end, so a fresh subscription can
        # have none until a later webhook. Stripe's reply has it, and the UI needs
        # a date to say when access ends.
        period_end = _period_end(stripe_sub)
        if period_end:
            user_sub.current_period_end = period_end
        db.add(user_sub)
        await db.commit()
        return {"cancel_at_period_end": True, "current_period_end": user_sub.current_period_end}

    @staticmethod
    async def resume_subscription(db: AsyncSession, user: User, subscription_id: str) -> dict:
        """Undo a scheduled cancel while the subscription is still running."""
        user_sub = await StripeService._owned_subscription(db, user, subscription_id)

        if user_sub.status not in (SubscriptionStatus.active, SubscriptionStatus.trialing):
            raise HTTPException(
                status_code=409,
                detail="This subscription has already ended — subscribe again to restore access.",
            )
        if not user_sub.cancel_at_period_end:
            raise HTTPException(status_code=409, detail="This subscription is not scheduled to cancel.")

        try:
            stripe_sub = stripe.Subscription.modify(
                user_sub.stripe_subscription_id,
                cancel_at_period_end=False
            )
        except stripe.error.StripeError as e:
            raise HTTPException(status_code=400, detail=str(e))

        user_sub.cancel_at_period_end = False
        period_end = _period_end(stripe_sub)
        if period_end:
            user_sub.current_period_end = period_end
        db.add(user_sub)
        await db.commit()
        return {"cancel_at_period_end": False, "current_period_end": user_sub.current_period_end}


