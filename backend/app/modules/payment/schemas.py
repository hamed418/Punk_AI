import uuid
from pydantic import BaseModel
from typing import Optional, Union
from decimal import Decimal
from datetime import datetime
from app.shared.enums import SubscriptionStatus



class StripeCheckoutRequest(BaseModel):
    subscription_id: uuid.UUID
    ads_account_id: Optional[str] = None
    coupon_code: Optional[str] = None
    amount: Optional[float] = None
class EarlyAccessPayload(BaseModel):
    subscription_id: Optional[Union[uuid.UUID, str]] = None
    email: str
    name: Optional[str] = None
    business_name: Optional[str] = None
    why_choose_punk: Optional[str] = None
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None
    
    
    
class StripePortalRequest(BaseModel):
    return_url: str

class StripeSessionResponse(BaseModel):
    url: str