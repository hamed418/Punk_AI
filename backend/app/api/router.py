from fastapi import APIRouter

# ── Client & Core Application Routers ──────────────────────────────────────────
from app.modules.auth.router import router as auth_router
from app.modules.user.router import router as user_router
from app.modules.chat.router import router as chat_router
from app.modules.campaigns.router import router as campaigns_router
from app.modules.ads.router import router as ads_router
from app.modules.creatives.router import router as creatives_router
from app.modules.media.router import router as media_router
from app.modules.payment.router import router as payment_router
from app.modules.subscription.router import router as subscription_router
from app.modules.tracking.router import router as tracking_router
from app.modules.support.router import router as support_router
from app.modules.faq.router import router as faq_router
from app.modules.legals.router import router as legals_router
from app.modules.map.router import router as map_router
from app.modules.waitlist.router import router as waitlist_router
from app.modules.redeem.router import router as redeem_router
from app.modules.coupon.router import router as coupon_router

# ── Admin Panel Dedicated Routers ─────────────────────────────────────────────
from app.modules.analytics.router import router as analytics_router
from app.modules.auditLogs.router import router as audit_log_router
from app.modules.usage.router import router as usage_router

api_router = APIRouter()

# ── Client & Core Routes ──────────────────────────────────────────────────────
api_router.include_router(auth_router)
api_router.include_router(user_router)
api_router.include_router(chat_router)
api_router.include_router(campaigns_router)
api_router.include_router(ads_router)
api_router.include_router(creatives_router)
api_router.include_router(media_router)
api_router.include_router(payment_router)
api_router.include_router(subscription_router)  # Reloaded
api_router.include_router(tracking_router)

api_router.include_router(support_router)
api_router.include_router(faq_router)
api_router.include_router(legals_router)
api_router.include_router(map_router)
api_router.include_router(waitlist_router)
api_router.include_router(redeem_router)
api_router.include_router(coupon_router)


# ── Admin Panel Routes ────────────────────────────────────────────────────────
api_router.include_router(analytics_router)
api_router.include_router(audit_log_router)
api_router.include_router(usage_router)

