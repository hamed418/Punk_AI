import uuid
import urllib.parse
import asyncio
from typing import Optional, List
from datetime import datetime, timezone
import stripe
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.config import settings
from app.core.logging import logger
from app.shared.enums import SubscriptionStatus, SubscriptionPaymentStatus
from app.modules.subscription.repository import SubscriptionRepository
from app.modules.subscription.models import Subscription, UserSubscription, TokenTransaction
from app.modules.user.models import User, EarlyAccessPayment
from app.services.email_service import send_early_access_access_link_email

class PaymentService:
    def __init__(self, repository: SubscriptionRepository):
        self.repository = repository
        stripe.api_key = settings.STRIPE_SECRET_KEY

    async def create_subscription_checkout(self, db: AsyncSession, payload, current_user: User) -> str:
        from app.services.stripe_logic import StripeService
        # Punk sells per ad account now — a logged-in checkout with no
        # account would otherwise fall back to an unscoped subscription that
        # ad_account_is_paid() treats as authorizing nothing, i.e. money for
        # a subscription that can never gate anything.
        if not payload.ads_account_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ads_account_id is required to subscribe.",
            )

        plan = await self.repository.get_subscription(db, payload.subscription_id)
        if not plan:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription plan not found")

        existing_user_sub = await self.repository.get_user_subscription_by_ad_account(
            db, current_user.id, payload.ads_account_id
        )

        if not existing_user_sub:
            new_user_sub = UserSubscription(
                user_id=current_user.id,
                ad_account_id=payload.ads_account_id,
                status=SubscriptionStatus.incomplete,
                plan_id=plan.id
            )
            await self.repository.update_user_subscription(db, new_user_sub)
            user_sub = new_user_sub
        elif existing_user_sub.status in (SubscriptionStatus.active, SubscriptionStatus.trialing):
            # Already paying — a second checkout on the same account must not
            # silently reuse or duplicate it (uq_user_ad_account_sub allows
            # only one row per (user, ad account) anyway).
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This ad account already has a subscription."
            )
        else:
            # incomplete, canceled, past_due, incomplete_expired, unpaid,
            # paused — none of these are currently authorizing anything
            # (ad_account_is_paid only allows active/trialing), and the
            # unique constraint means this row IS the only slot this ad
            # account will ever get. Re-subscribing must reuse it, not
            # refuse forever because it was once canceled.
            existing_user_sub.plan_id = plan.id
            existing_user_sub.status = SubscriptionStatus.incomplete
            existing_user_sub.payment_status = SubscriptionPaymentStatus.unpaid
            await self.repository.update_user_subscription(db, existing_user_sub)
            user_sub = existing_user_sub

        charge_amount = float(plan.amount)
        if payload.coupon_code:
            from app.modules.coupon.repository import CouponRepository
            from app.modules.coupon.service import CouponService
            coupon_service = CouponService(CouponRepository())
            code_clean = payload.coupon_code.strip().upper()
            coupon = await coupon_service.coupon_repository.admin_get_by_coupon_code(db, code_clean)
            if coupon and coupon.is_active:
                _, final_amt = coupon_service.calculate_discount(coupon, charge_amount)
                charge_amount = final_amt
        elif payload.amount is not None and payload.amount >= 0:
            charge_amount = float(payload.amount)

        return await StripeService.create_checkout_session(
            db=db,
            user=current_user,
            amount=charge_amount,
            # Stripe's product name — what the customer sees on the portal, invoices
            # and receipts. plan.description is a serialized JSON blob for
            # admin-created plans, and every account's line read the same; name the
            # plan and the ad account it is for.
            plan_name=f"{plan.name or 'Punk AI Plan'} — {payload.ads_account_id}",
            user_subscription_id=str(user_sub.id),
            ad_account_id=payload.ads_account_id,
            coupon_code=payload.coupon_code,
        )

    async def create_early_access_checkout(self, db: AsyncSession, payload) -> str:
        from app.services.stripe_logic import StripeService
        plan = None
        if payload.subscription_id:
            plan = await self.repository.get_subscription(db, payload.subscription_id)
        
        if not plan:
            plan = await self.repository.get_cheapest_paid_plan(db)
        if not plan:
            plan = await self.repository.get_any_plan(db)
        if not plan:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription plan not found")

        existing_user_sub = await self.repository.get_user_subscription_by_email(db, payload.email)
        
        if not existing_user_sub:
            new_user_sub = UserSubscription(
                email=payload.email,
                status=SubscriptionStatus.incomplete,
                plan_id=plan.id
            )
            await self.repository.update_user_subscription(db, new_user_sub)
            user_sub = new_user_sub
        else:
            if existing_user_sub.status == SubscriptionStatus.incomplete:
                existing_user_sub.plan_id = plan.id
                await self.repository.update_user_subscription(db, existing_user_sub)
            user_sub = existing_user_sub
        
        user_info = EarlyAccessPayment(
            email=payload.email,
            name=payload.name,
            business_name=payload.business_name,
            why_choose_punk=payload.why_choose_punk
        )
        await self.repository.create_early_access_payment(db, user_info)

        return await StripeService.create_checkout_session_with_early_access(
            db=db,
            email=payload.email,
            amount=float(plan.amount),
            plan_name=plan.description or "Punk AI Plan",
            subscription_id=str(user_sub.id),
            success_url=payload.success_url,
            cancel_url=payload.cancel_url,
        )

    async def create_token_upgrade_checkout(self, db: AsyncSession, payload, current_user: User) -> str:
        from app.services.stripe_logic import StripeService
        active_subs = await self.repository.get_active_subscriptions_by_user(db, current_user.id)
        if not active_subs:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="You need an active subscription to purchase tokens."
            )

        plan = await self.repository.get_subscription(db, payload.subscription_id)
        if not plan:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription plan not found")
            
        return await StripeService.create_token_upgrade_session(
            db=db,
            user=current_user,
            amount=plan.amount,
            token_amount=plan.total_token_can_use
        )

    async def assign_ad_account(self, db: AsyncSession, payload, current_user: User) -> dict:
        from app.modules.ads.repository import AdsRepository
        from app.services.entitlement import ad_account_is_paid

        # Select first, through the one writer that keeps oauth_tokens.selected_account
        # and users.select_meta_id in step. This used to write select_meta_id alone,
        # so a user could pay for B while Punk kept publishing into A (and then hit
        # _require_paid_account on A). It also runs BEFORE binding the sub: the
        # membership check inside rejects an account this Meta connection never
        # granted, and a paid slot must not be spent on an account nobody can use.
        if not await AdsRepository().update_selected_account(
            db, current_user.id, payload.ads_account_id
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="That Meta ad account is not connected",
            )

        if not await ad_account_is_paid(current_user.id, payload.ads_account_id, db):
            # Only an unscoped (ad_account_id IS NULL) subscription can be
            # assigned — get_latest_user_subscription used to grab whichever
            # row was newest, which could steal a sub already bound to a
            # DIFFERENT ad account.
            user_sub = await self.repository.get_user_subscription(db, current_user.id)
            if not user_sub:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No subscription found. Please subscribe first."
                )

            user_sub.ad_account_id = payload.ads_account_id
            await self.repository.update_user_subscription(db, user_sub)

        return {
            "status": "success",
            "message": "Ad account assigned and selected successfully"
        }

    async def create_portal_session(self, db: AsyncSession, return_url: str, current_user: User) -> str:
        from app.services.stripe_logic import StripeService
        return await StripeService.create_portal_session(
            db=db,
            user=current_user,
            return_url=return_url
        )

    async def cancel_subscription(self, db: AsyncSession, subscription_id: str, current_user: User) -> dict:
        from app.services.stripe_logic import StripeService
        result = await StripeService.cancel_subscription(
            db=db,
            user=current_user,
            subscription_id=subscription_id
        )
        return {
            "status": "success",
            # Access continues to the end of the paid period — this used to say
            # "has been canceled", which is not what happens.
            "message": "Subscription will end at the end of the billing period.",
            **result,
        }

    async def resume_subscription(self, db: AsyncSession, subscription_id: str, current_user: User) -> dict:
        from app.services.stripe_logic import StripeService
        result = await StripeService.resume_subscription(
            db=db,
            user=current_user,
            subscription_id=subscription_id
        )
        return {
            "status": "success",
            "message": "Subscription resumed.",
            **result,
        }

    async def handle_stripe_webhook(self, db: AsyncSession, payload: bytes, signature: str):
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")

        await self.process_stripe_event(db, event)

    async def process_stripe_event(self, db: AsyncSession, event: stripe.Event):
        """Process Stripe webhook events and sync database safely."""
        data_object = event.data.object
        
        try:
            if event.type == "checkout.session.completed":
                await self.process_checkout_session_completed(db, data_object)
            
            elif event.type == "invoice.paid":
                await self.process_invoice_paid(db, data_object)
                
            elif event.type in ["customer.subscription.updated", "customer.subscription.deleted", "invoice.payment_failed"]:
                # Sometimes invoice.payment_failed carries the subscription ID too, we can sync status
                sub_id = data_object.subscription if hasattr(data_object, "subscription") else data_object.id
                if type(sub_id) == str:
                    # Make sure we get the full subscription object if it's just an ID from an invoice
                    if event.type == "invoice.payment_failed":
                        stripe_sub = stripe.Subscription.retrieve(sub_id)
                    else:
                        stripe_sub = data_object
                    await self.sync_subscription_status(db, stripe_sub)
        except Exception as e:
            logger.exception(f"Error processing webhook event {event.type}: {e}")
            raise

    async def process_checkout_session_completed(self, db: AsyncSession, session: stripe.checkout.Session):
        if session.payment_status not in ("paid", "no_payment_required"):
            logger.warning(f"Checkout session {session.id} is not paid. Ignoring.")
            return

        metadata = session.metadata.to_dict() if hasattr(session.metadata, "to_dict") else (session.metadata or {})
        user_id_str = metadata.get("user_id")
        
        # 1. Token Purchase Flow
        if metadata.get("token_upgrade") == "true":
            await self._handle_token_upgrade(db, session, metadata, user_id_str)
            return

        # 2. Subscription Purchase Flow
        await self._handle_subscription_checkout(db, session, metadata, user_id_str)

    async def _handle_token_upgrade(self, db: AsyncSession, session, metadata: dict, user_id_str: str):
        if not user_id_str:
            logger.error("Token upgrade failed: Missing user_id in metadata")
            return
            
        user_id = uuid.UUID(user_id_str)
        token_amount = int(metadata.get("token_amount", "0"))
        
        if token_amount <= 0:
            return

        try:
            # Idempotency check: Have we processed this session?
            existing_tx = await db.execute(
                select(TokenTransaction).where(
                    TokenTransaction.tx_metadata.op("->>")("stripe_session_id") == session.id
                )
            )
            if existing_tx.scalar_one_or_none():
                logger.info(f"Token upgrade for session {session.id} already processed.")
                return

            # Proceed with allocation
            user_result = await db.execute(select(User).where(User.id == user_id).with_for_update())
            user = user_result.scalar_one_or_none()
            if not user:
                logger.error(f"Token upgrade failed: User {user_id} not found")
                return

            current_balance = user.free_message_limit or 0
            user.free_message_limit = current_balance + token_amount
            db.add(user)

            # Record transaction for idempotency and audit
            tx = TokenTransaction(
                user_id=user.id,
                type="ALLOCATION",
                amount=token_amount,
                balance_before=current_balance,
                balance_after=current_balance + token_amount,
                action="token_purchase",
                tx_metadata={"stripe_session_id": session.id, "payment_intent": session.payment_intent}
            )
            db.add(tx)
            
            await db.commit()
            logger.info(f"Successfully processed token upgrade of {token_amount} for user {user_id}")
            
        except Exception as e:
            await db.rollback()
            raise e

    async def _handle_subscription_checkout(self, db: AsyncSession, session, metadata: dict, user_id_str: str):
        subscription_id = metadata.get("subscription_id")
        cust_details = session.customer_details.to_dict() if (hasattr(session, "customer_details") and hasattr(session.customer_details, "to_dict")) else {}
        email = metadata.get("email") or cust_details.get("email") or getattr(session.customer_details, "email", None)
        
        stripe_sub_id = session.subscription
        stripe_sub_status = "active"
        if stripe_sub_id:
            try:
                stripe_sub = stripe.Subscription.retrieve(stripe_sub_id)
                stripe_sub_status = stripe_sub.status
            except Exception as e:
                logger.warning(f"Failed to retrieve Stripe sub: {e}")

        try:
            if not user_id_str:
                # Flow 2: Guest / Unregistered User
                clean_email = email.strip().lower() if email else ""
                if not clean_email:
                    logger.error("Guest checkout missing email")
                    return

                # Mark Early Access as Paid
                ea_res = await db.execute(select(EarlyAccessPayment).where(func.lower(EarlyAccessPayment.email) == clean_email))
                ea_records = ea_res.scalars().all()
                already_ea_paid = any(ep.is_payment_done for ep in ea_records)
                for ep in ea_records:
                    ep.is_payment_done = True
                    db.add(ep)
                if not ea_records:
                    db.add(EarlyAccessPayment(email=clean_email, is_payment_done=True, is_active=True))

                # Activate UserSubscription with row lock to serialize concurrent webhook & callback
                if subscription_id:
                    sub_res = await db.execute(select(UserSubscription).where(UserSubscription.id == subscription_id).with_for_update())
                else:
                    sub_res = await db.execute(
                        select(UserSubscription).where(func.lower(UserSubscription.email) == clean_email)
                        .order_by(UserSubscription.created_at.desc()).with_for_update()
                    )
                sub = sub_res.scalars().first()

                already_sub_paid = False
                if sub:
                    if sub.payment_status == SubscriptionPaymentStatus.paid and sub.status in [SubscriptionStatus.active, SubscriptionStatus.trialing]:
                        already_sub_paid = True

                    sub.status = SubscriptionStatus(stripe_sub_status) if stripe_sub_status in [e.value for e in SubscriptionStatus] else SubscriptionStatus.active
                    sub.payment_status = SubscriptionPaymentStatus.paid
                    if stripe_sub_id:
                        sub.stripe_subscription_id = stripe_sub_id

                    if sub.plan_id:
                        plan = await self.repository.get_subscription(db, sub.plan_id)
                        if plan:
                            sub.total_tokens = plan.total_token_can_use
                    
                    db.add(sub)
                
                await db.commit()

                # Async send link only if not already paid/processed
                if already_sub_paid or already_ea_paid:
                    logger.info(f"Early access checkout for {clean_email} already processed as paid. Skipping duplicate access link email.")
                else:
                    registration_link = f"{settings.FRONTEND_URL}/signup?email={urllib.parse.quote(clean_email)}"
                    asyncio.create_task(send_early_access_access_link_email(clean_email, registration_link))
                
            else:
                # Flow 1 & 4: Registered User Subscription / Ad Account Subscription
                user_id = uuid.UUID(user_id_str)
                user = await self.repository.get_user(db, user_id)
                if not user:
                    logger.error("Registered checkout missing user")
                    return

                if subscription_id:
                    sub = await self.repository.get_user_subscription_by_id(db, subscription_id)
                else:
                    sub = None

                if not sub:
                    # Fallback (Should rarely happen as checkout creates it first).
                    # Money changed hands, so the row is kept — but scoped to the
                    # account the checkout was for. Unscoped (NULL) it would
                    # authorize nothing, ever (ad_account_is_paid), with no way
                    # back to which account was paid for.
                    fallback_account = metadata.get("ad_account_id")
                    if not fallback_account:
                        logger.error(
                            f"Checkout fallback for session {session.id} has no ad_account_id "
                            "in metadata — this subscription authorizes nothing until it is "
                            "assigned to an account by hand."
                        )
                    sub = UserSubscription(
                        user_id=user_id,
                        email=user.email,
                        ad_account_id=fallback_account,
                        stripe_subscription_id=stripe_sub_id,
                        status=SubscriptionStatus(stripe_sub_status) if stripe_sub_status in [e.value for e in SubscriptionStatus] else SubscriptionStatus.active,
                        payment_status=SubscriptionPaymentStatus.paid
                    )
                    db.add(sub)
                else:
                    sub.status = SubscriptionStatus(stripe_sub_status) if stripe_sub_status in [e.value for e in SubscriptionStatus] else SubscriptionStatus.active
                    sub.payment_status = SubscriptionPaymentStatus.paid
                    if stripe_sub_id:
                        sub.stripe_subscription_id = stripe_sub_id
                    
                    if sub.plan_id:
                        plan = await self.repository.get_subscription(db, sub.plan_id)
                        if plan:
                            sub.total_tokens = plan.total_token_can_use
                    
                    db.add(sub)

                await db.commit()
                
                # Explicitly allocate tokens idempotently
                if sub.status in [SubscriptionStatus.active]:
                    from app.modules.subscription.service import SubscriptionLinkingService
                    await SubscriptionLinkingService.allocate_subscription_tokens(db, sub, user)

                # Paying for an account is what makes it the account Punk publishes
                # into — otherwise the user pays for B while Punk keeps targeting A
                # and _require_paid_account blocks the publish. Best-effort, NOT
                # fatal: this is the Stripe webhook, and a raise here means Stripe
                # retries forever over a selection nicety. False just means no live
                # Meta connection grants that account (yet).
                if sub.ad_account_id:
                    try:
                        from app.modules.ads.repository import AdsRepository
                        if not await AdsRepository().update_selected_account(
                            db, user_id, sub.ad_account_id
                        ):
                            logger.warning(
                                f"Paid ad account {sub.ad_account_id} not selectable for user "
                                f"{user_id} — no Meta connection grants it"
                            )
                    except Exception as sel_err:  # noqa: BLE001
                        logger.warning(f"Could not select paid ad account {sub.ad_account_id}: {sel_err}")

        except Exception as e:
            await db.rollback()
            raise e

    async def process_invoice_paid(self, db: AsyncSession, invoice: stripe.Invoice):
        # We only care about recurring billing cycles for tokens
        if invoice.billing_reason == "subscription_create":
            # First month is handled by checkout session completed
            return

        if invoice.billing_reason != "subscription_cycle":
            return

        stripe_sub_id = invoice.subscription
        if not stripe_sub_id:
            return

        try:
            # Idempotency check
            existing_tx = await db.execute(
                select(TokenTransaction).where(
                    TokenTransaction.tx_metadata.op("->>")("stripe_invoice_id") == invoice.id
                )
            )
            if existing_tx.scalar_one_or_none():
                logger.info(f"Recurring tokens for invoice {invoice.id} already allocated.")
                return

            result = await db.execute(select(UserSubscription).where(UserSubscription.stripe_subscription_id == stripe_sub_id).with_for_update())
            sub = result.scalar_one_or_none()
            
            if not sub or not sub.user_id:
                logger.error(f"Could not allocate recurring tokens. Sub {stripe_sub_id} not found or no user_id.")
                return

            if sub.total_tokens > 0:
                # Renewal tops the SUBSCRIPTION's own balance back up, not the
                # user's shared wallet — quota is per ad account.
                current_bal = sub.remaining_tokens or 0
                sub.remaining_tokens = sub.total_tokens
                sub.used_tokens = 0
                db.add(sub)

                tx = TokenTransaction(
                    user_id=sub.user_id,
                    subscription_id=sub.id,
                    type="ALLOCATION",
                    amount=sub.total_tokens,
                    balance_before=current_bal,
                    balance_after=sub.total_tokens,
                    action="monthly_recurring_allocation",
                    tx_metadata={"stripe_invoice_id": invoice.id, "stripe_subscription_id": stripe_sub_id}
                )
                db.add(tx)
                
            # Also update the current period end safely
            if invoice.lines and invoice.lines.data:
                line = invoice.lines.data[0]
                period_end = line.period.end if hasattr(line, "period") else None
                if period_end:
                    sub.current_period_end = datetime.fromtimestamp(period_end, tz=timezone.utc)
                    
            sub.payment_status = SubscriptionPaymentStatus.paid
            db.add(sub)
            await db.commit()
            
        except Exception as e:
            await db.rollback()
            raise e

    async def sync_subscription_status(self, db: AsyncSession, stripe_sub: stripe.Subscription):
        try:
            # Locked like _handle_subscription_checkout and process_invoice_paid: the
            # Stripe webhook and the /subscription/success callback race each other
            # on exactly this row.
            result = await db.execute(
                select(UserSubscription)
                .where(UserSubscription.stripe_subscription_id == stripe_sub.id)
                .with_for_update()
            )
            sub = result.scalar_one_or_none()

            if not sub:
                logger.warning(f"Cannot sync status for unknown stripe_sub {stripe_sub.id}")
                return

            sub.status = SubscriptionStatus(stripe_sub.status) if stripe_sub.status in [e.value for e in SubscriptionStatus] else SubscriptionStatus.canceled
            
            stripe_sub_dict = stripe_sub.to_dict()
            
            # Period start/end
            item = stripe_sub_dict["items"]["data"][0] if stripe_sub_dict.get("items") and stripe_sub_dict["items"].get("data") else None
            
            period_start = None
            period_end = None
            
            if item:
                period_start = item.get("current_period_start") or stripe_sub_dict.get("current_period_start") or stripe_sub_dict.get("start_date") or stripe_sub_dict.get("created")
                period_end = item.get("current_period_end") or stripe_sub_dict.get("current_period_end") or stripe_sub_dict.get("start_date") or stripe_sub_dict.get("created")
            else:
                period_start = stripe_sub_dict.get("current_period_start") or stripe_sub_dict.get("start_date") or stripe_sub_dict.get("created")
                period_end = stripe_sub_dict.get("current_period_end") or stripe_sub_dict.get("start_date") or stripe_sub_dict.get("created")

            sub.current_period_start = datetime.fromtimestamp(period_start, tz=timezone.utc) if period_start else None
            sub.current_period_end = datetime.fromtimestamp(period_end, tz=timezone.utc) if period_end else None
            sub.cancel_at_period_end = stripe_sub_dict.get("cancel_at_period_end", False)

            db.add(sub)
            await db.commit()
        except Exception as e:
            await db.rollback()
            raise e
