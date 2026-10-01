# app/db/model_registry.py
from app.modules.media.models import MediaFile
from app.db.models import (
    MaidExtraction,
    CreativeGenerationJob,
)

from app.modules.ads.models import (OAuthToken, AdsAccount)
from app.modules.auditLogs.models import AuditLog
from app.modules.user.models import User, UserSession ,EarlyAccessPayment
from app.modules.subscription.models import (
    UserSubscription,
    Subscription,
    SubscriptionTokenAllocation,
    TokenTransaction,
) 
from app.modules.campaigns.models import Campaign 
from app.modules.chat.models import (Conversation,ChatMessage)
from app.modules.waitlist.models import WaitList
from app.modules.tracking.models import TrackingEvent
from app.modules.tracking.models import TrackingEvent
from app.modules.faq.models import FAQ, FAQCategory, LandingFAQ
from app.modules.support.models import Support
from app.modules.legals.models import LegalDocument
from app.modules.redeem.models import RedeemCode, RedeemCodeRedemption
from app.modules.coupon.models import Coupons, CouponRedemptions
