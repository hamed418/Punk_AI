from datetime import datetime
import enum
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class DiscountType(str, enum.Enum):
    PERCENTAGE = "percentage"
    FIXED_AMOUNT = "fixed_amount"
    FULL_FREE = "full_free"
    # Backward compatibility alias
    PERCENT = "percentage"


# Alias for compatibility
DiscoutType = DiscountType


class RedemptionStatus(str, enum.Enum):
    APPLIED = "applied"
    REVERTED = "reverted"


class CouponStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    REVOKED = "revoked"


class CreateCoupon(BaseModel):
    code: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    discount_type: DiscountType
    discount_value: Optional[float] = Field(None, ge=0)
    currency: str = Field("USD", min_length=3, max_length=3)
    max_discount_amount: Optional[float] = Field(None, ge=0)
    max_uses: Optional[int] = Field(None, ge=1)
    usage_limit_per_user: Optional[int] = Field(1, ge=1)
    is_active: bool = True
    valid_from: Optional[datetime] = None
    valid_till: Optional[datetime] = None
    new_users_only: bool = False


# Alias if needed
CouponCreate = CreateCoupon


class UpdateCoupon(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    discount_type: Optional[DiscountType] = None
    discount_value: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    max_discount_amount: Optional[float] = Field(None, ge=0)
    max_uses: Optional[int] = Field(None, ge=1)
    usage_limit_per_user: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None
    valid_from: Optional[datetime] = None
    valid_till: Optional[datetime] = None
    new_users_only: Optional[bool] = None


class CouponDetailResponse(BaseModel):
    id: UUID
    code: str
    description: Optional[str] = None
    discount_type: DiscountType
    discount_value: Optional[float] = None
    currency: str = "USD"
    max_discount_amount: Optional[float] = None
    max_uses: Optional[int] = None
    usage_limit_per_user: Optional[int] = 1
    current_uses: int = 0
    is_active: bool
    valid_from: datetime
    valid_till: Optional[datetime] = None
    new_users_only: bool
    created_by: UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CouponRedemptionResponse(BaseModel):
    id: UUID
    coupon_id: UUID
    user_id: UUID
    email: Optional[str] = None
    original_amount: float
    discounted_amount: float
    final_amount: float
    status: RedemptionStatus
    redeemed_at: datetime
    reverted_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# Keep Redeem model for compatibility
class Redeem(BaseModel):
    coupon_id: UUID
    user_id: UUID
    email: Optional[str] = None
    original_amount: float
    discounted_amount: float
    final_amount: float
    status: RedemptionStatus
    redeemed_at: datetime
    reverted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CouponValidateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=100)
    original_amount: float = Field(..., ge=0)


class CouponValidateResponse(BaseModel):
    is_valid: bool
    message: str
    coupon_id: Optional[UUID] = None
    code: str
    discount_type: Optional[DiscountType] = None
    discount_value: Optional[float] = None
    original_amount: float
    discount_amount: float
    final_amount: float


class RedeemRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=100)
    original_amount: float = Field(..., ge=0)
    email: Optional[str] = None


class RedeemResponse(BaseModel):
    success: bool
    message: str
    coupon_code: str
    original_amount: float
    discounted_amount: float
    final_amount: float
    redemption_id: UUID
    redeemed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CouponDeleteResponse(BaseModel):
    success: bool = Field(..., description="Indicates if the deletion was successful")
    message: str = Field(..., description="Confirmation message")


class CouponRevertResponse(BaseModel):
    success: bool = Field(..., description="Indicates if the reversion was successful")
    message: str = Field(..., description="Confirmation message")
    redemption: CouponRedemptionResponse = Field(..., description="Reverted redemption details")