"use server";

import { couponApi } from '../lib/api/coupon';
import type {
  CouponValidateRequest,
  CouponValidateResponse,
  RedeemRequest,
  RedeemResponse,
} from '@/types/coupon';
import { extractErrorMessage } from '../lib/errorUtils';

export async function validateCouponAction(data: CouponValidateRequest): Promise<{
  success: boolean;
  data?: CouponValidateResponse;
  error?: string;
}> {
  try {
    const res = await couponApi.validateCoupon(data);
    return { success: true, data: res };
  } catch (error: unknown) {
    console.error('Failed to validate coupon:', error);
    return {
      success: false,
      error: extractErrorMessage(error, 'Failed to validate coupon.'),
    };
  }
}

export async function redeemCouponAction(data: RedeemRequest): Promise<{
  success: boolean;
  data?: RedeemResponse;
  error?: string;
}> {
  try {
    const res = await couponApi.redeemCoupon(data);
    return { success: true, data: res };
  } catch (error: unknown) {
    console.error('Failed to redeem coupon:', error);
    return {
      success: false,
      error: extractErrorMessage(error, 'Failed to redeem coupon.'),
    };
  }
}
