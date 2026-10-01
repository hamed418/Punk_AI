import json
import uuid
from pydantic import BaseModel, EmailStr, model_validator
from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import datetime
from app.shared.enums import SubscriptionStatus, PurchaseType

class SubscriptionCreateRequest(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    price_id: Optional[str] = None
    description: Optional[str] = ""
    features: Optional[List[str]] = []
    amount: Decimal
    currency: str = "usd"
    interval: Optional[str] = "month"
    type: PurchaseType = PurchaseType.SUBSCRIPTION
    total_token_can_use: int = 0

class SubscriptionUpdateRequest(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    price_id: Optional[str] = None
    description: Optional[str] = None
    features: Optional[List[str]] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    interval: Optional[str] = None
    type: Optional[PurchaseType] = None
    total_token_can_use: Optional[int] = None

class SubscriptionResponse(BaseModel):
    id: uuid.UUID
    name: Optional[str] = None
    slug: Optional[str] = None
    price_id: Optional[str] = None
    description: Optional[str] = None
    features: List[str] = []
    amount: Decimal
    currency: str
    interval: Optional[str] = None
    type: PurchaseType = PurchaseType.SUBSCRIPTION
    total_token_can_use: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}



    @model_validator(mode="before")
    @classmethod
    def parse_features_and_description(cls, data: Any) -> Any:
        desc = getattr(data, "description", None) if not isinstance(data, dict) else data.get("description")
        feats = getattr(data, "features", None) if not isinstance(data, dict) else data.get("features")
        
        extracted_features = list(feats) if isinstance(feats, list) and len(feats) > 0 else []
        clean_description = desc or ""

        if desc and not extracted_features:
            try:
                parsed = json.loads(desc)
                if isinstance(parsed, dict):
                    if "features" in parsed and isinstance(parsed["features"], list):
                        extracted_features = [f.strip() for f in parsed["features"] if f and str(f).strip()]
                    if "shortDescription" in parsed:
                        clean_description = parsed["shortDescription"]
                    elif "description" in parsed:
                        clean_description = parsed["description"]
            except Exception:
                # Comma-separated or newline-separated fallback
                if "," in desc:
                    extracted_features = [f.strip() for f in desc.split(",") if f.strip()]
                    clean_description = ""
                elif "\n" in desc:
                    extracted_features = [f.strip() for f in desc.split("\n") if f.strip()]
                    clean_description = ""

        if isinstance(data, dict):
            data["description"] = clean_description
            data["features"] = extracted_features
            if data.get("type") is None:
                data["type"] = PurchaseType.SUBSCRIPTION
            return data

        return {
            "id": getattr(data, "id", None),
            "name": getattr(data, "name", None),
            "slug": getattr(data, "slug", None),
            "price_id": getattr(data, "price_id", None),
            "description": clean_description,
            "features": extracted_features,
            "amount": getattr(data, "amount", Decimal("0.0")),
            "currency": getattr(data, "currency", "usd"),
            "interval": getattr(data, "interval", "month"),
            "type": getattr(data, "type", None) or PurchaseType.SUBSCRIPTION,
            "total_token_can_use": getattr(data, "total_token_can_use", 0),
            "created_at": getattr(data, "created_at", None),
            "updated_at": getattr(data, "updated_at", None),
        }



class UserSubscriptionResponse(BaseModel):
    id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    email: Optional[str] = None
    status: SubscriptionStatus
    plan_id: Optional[uuid.UUID] = None
    ad_account_id: Optional[str] = None
    total_tokens: int = 0
    used_tokens: int = 0
    remaining_tokens: int = 0
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool
    created_at: datetime
    plan: Optional[SubscriptionResponse] = None

    model_config = {"from_attributes": True}

class UserSubscriptionCreateRequest(BaseModel):
    email: EmailStr
    plan_id: Optional[uuid.UUID] = None
    total_tokens: int = 0
    status: SubscriptionStatus = SubscriptionStatus.active
    current_period_end: Optional[datetime] = None

class UserSubscriptionUpdateRequest(BaseModel):
    status: Optional[SubscriptionStatus] = None
    total_tokens: Optional[int] = None
    remaining_tokens: Optional[int] = None
    current_period_end: Optional[datetime] = None

class AssignAdsAccountRequest(BaseModel):
    ads_account_id: str

class TokenBalanceResponse(BaseModel):
    remaining_tokens: int
    total_tokens: int
    used_tokens: int
    subscription_remaining: int
    subscription_total: int
    free_remaining: int
    free_total: int
    free_used: int

class TokenTransactionResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    subscription_id: Optional[uuid.UUID] = None
    type: str
    amount: int
    balance_before: int
    balance_after: int
    action: Optional[str] = None
    tx_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime

    model_config = {"from_attributes": True}