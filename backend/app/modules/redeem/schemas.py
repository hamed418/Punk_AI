from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field

class RedeemCodesBase(BaseModel):
    id: UUID
    code: str
    is_active: bool
    is_single: bool
    max_redemptions: int
    redemption_count: int
    created_by: UUID
    created_at: datetime
    expires_at: Optional[datetime] = None
    updated_at: datetime


class RedeemedBy(BaseModel):
    user_id: UUID
    redeemed_at: datetime
    email: Optional[str] = None


class RedeemCodeRedemptionBase(BaseModel):
    id: UUID
    redeem_code_id: UUID
    user_id: UUID
    email: Optional[str] = None
    redeemed_at: datetime
    created_at: datetime
    updated_at: datetime


class RedeemCodeRedemptionResponse(RedeemCodeRedemptionBase):
    class Config:
        from_attributes = True


class RedeemCodesCreate(BaseModel):
    is_active: bool = True
    is_single: bool = True
    max_redemptions: int = Field(1, ge=1, description="Maximum number of times this code can be redeemed")


class RedeemCodesUpdate(BaseModel):
    is_active: Optional[bool] = None
    is_single: Optional[bool] = None
    max_redemptions: Optional[int] = Field(None, ge=1)
    expires_at: Optional[datetime] = None


class RedeemCodesResponse(BaseModel):
    id: UUID
    code: str
    is_active: bool
    is_single: bool
    max_redemptions: int
    redemption_count: int
    created_by: UUID
    created_at: datetime
    expires_at: Optional[datetime] = None
    updated_at: datetime

    class Config:
        from_attributes = True


class RedeemCodeDetailResponse(RedeemCodesResponse):
    redemptions: List[RedeemCodeRedemptionResponse] = []

    class Config:
        from_attributes = True


class RedeemUseRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=100, description="The redeem code string to claim")


class RedeemUseResponse(BaseModel):
    success: bool = True
    message: str
    redeem_code: RedeemCodesResponse
    redemption: RedeemCodeRedemptionResponse