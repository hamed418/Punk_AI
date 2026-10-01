export type DiscountType = 'percentage' | 'fixed_amount' | 'full_free';

export interface CouponValidateRequest {
  code: string;
  original_amount: number;
}

export interface CouponValidateResponse {
  is_valid: boolean;
  message: string;
  coupon_id?: string | null;
  code: string;
  discount_type?: DiscountType | null;
  discount_value?: number | null;
  original_amount: number;
  discount_amount: number;
  final_amount: number;
}

export interface RedeemRequest {
  code: string;
  original_amount: number;
  email?: string | null;
}

export interface RedeemResponse {
  success: boolean;
  message: string;
  coupon_code: string;
  original_amount: number;
  discounted_amount: number;
  final_amount: number;
  redemption_id: string;
  redeemed_at: string;
}
