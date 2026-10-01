import { apiFetch } from '../fetcher';
import type {
  CouponValidateRequest,
  CouponValidateResponse,
  RedeemRequest,
  RedeemResponse,
} from '@/types/coupon';

export const couponApi = {
  validateCoupon: (data: CouponValidateRequest) => {
    return apiFetch<CouponValidateResponse>('/coupons/validate', {
      method: 'POST',
      body: JSON.stringify(data),
      cache: 'no-store',
    });
  },

  redeemCoupon: (data: RedeemRequest) => {
    return apiFetch<RedeemResponse>('/coupons/redeem', {
      method: 'POST',
      body: JSON.stringify(data),
      cache: 'no-store',
    });
  },
};
