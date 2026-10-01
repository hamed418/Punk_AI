import api from './client';

export interface PaginatedResponse<T> {
  total: number;
  page: number;
  limit: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
  data: T[];
}

// ── Coupon APIs ─────────────────────────────────────────────────────────────

export type DiscountType = 'percentage' | 'fixed_amount' | 'full_free';
export type RedemptionStatus = 'applied' | 'reverted';
export type CouponStatus = 'active' | 'inactive' | 'revoked';

export interface CreateCouponPayload {
  code: string;
  description?: string;
  discount_type: DiscountType;
  discount_value?: number;
  currency?: string;
  max_discount_amount?: number;
  max_uses?: number;
  usage_limit_per_user?: number;
  is_active?: boolean;
  valid_from?: string;
  valid_till?: string;
  new_users_only?: boolean;
}

export interface UpdateCouponPayload {
  code?: string;
  description?: string;
  discount_type?: DiscountType;
  discount_value?: number;
  currency?: string;
  max_discount_amount?: number;
  max_uses?: number;
  usage_limit_per_user?: number;
  is_active?: boolean;
  valid_from?: string;
  valid_till?: string;
  new_users_only?: boolean;
}

export interface CouponDetailResponse {
  id: string;
  code: string;
  description?: string | null;
  discount_type: DiscountType;
  discount_value?: number | null;
  currency: string;
  max_discount_amount?: number | null;
  max_uses?: number | null;
  usage_limit_per_user?: number | null;
  current_uses: number;
  is_active: boolean;
  valid_from: string;
  valid_till?: string | null;
  new_users_only: boolean;
  created_by: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CouponRedemptionResponse {
  id: string;
  coupon_id: string;
  user_id: string;
  email?: string | null;
  original_amount: number;
  discounted_amount: number;
  final_amount: number;
  status: RedemptionStatus;
  redeemed_at: string;
  reverted_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CouponDeleteResponse {
  success: boolean;
  message: string;
}

export interface CouponRevertResponse {
  success: boolean;
  message: string;
  redemption: CouponRedemptionResponse;
}

export interface CouponListParams {
  page?: number;
  limit?: number;
  status?: CouponStatus | boolean | string;
  discount_type?: DiscountType;
  valid_from?: string;
  valid_till?: string;
  created_by?: string;
  search?: string;
}

export interface CouponRedemptionListParams {
  page?: number;
  limit?: number;
  user_id?: string;
  coupon_id?: string;
}

export const couponApi = {
  /**
   * Admin: List all coupons with filtering and pagination
   */
  getAll: (params?: CouponListParams) => {
    const qs = new URLSearchParams();
    if (params?.page) qs.append('page', String(params.page));
    if (params?.limit) qs.append('limit', String(params.limit));
    if (params?.status !== undefined) qs.append('status', String(params.status));
    if (params?.discount_type) qs.append('discount_type', params.discount_type);
    if (params?.valid_from) qs.append('valid_from', params.valid_from);
    if (params?.valid_till) qs.append('valid_till', params.valid_till);
    if (params?.created_by) qs.append('created_by', params.created_by);
    if (params?.search) qs.append('search', params.search);
    const query = qs.toString();
    return api.get<PaginatedResponse<CouponDetailResponse>>(`/coupons${query ? `?${query}` : ''}`);
  },

  /**
   * Admin: Create a new promotional/discount coupon
   */
  create: (payload: CreateCouponPayload) =>
    api.post<CouponDetailResponse>('/coupons', payload),

  /**
   * Admin: Get coupon by ID
   */
  getById: (couponId: string) =>
    api.get<CouponDetailResponse>(`/coupons/${couponId}`),

  /**
   * Admin: Update coupon
   */
  update: (couponId: string, payload: UpdateCouponPayload) =>
    api.put<CouponDetailResponse>(`/coupons/${couponId}`, payload),

  /**
   * Admin: Delete coupon
   */
  delete: (couponId: string) =>
    api.delete<CouponDeleteResponse>(`/coupons/${couponId}`),

  /**
   * Admin: List all coupon redemptions across all users
   */
  getRedemptions: (params?: CouponRedemptionListParams) => {
    const qs = new URLSearchParams();
    if (params?.page) qs.append('page', String(params.page));
    if (params?.limit) qs.append('limit', String(params.limit));
    if (params?.user_id) qs.append('user_id', params.user_id);
    if (params?.coupon_id) qs.append('coupon_id', params.coupon_id);
    const query = qs.toString();
    return api.get<PaginatedResponse<CouponRedemptionResponse>>(`/coupons/redemptions${query ? `?${query}` : ''}`);
  },

  /**
   * Admin: Revert coupon redemption
   */
  revertRedemption: (redemptionId: string) =>
    api.post<CouponRevertResponse>(`/coupons/redemptions/${redemptionId}/revert`),
};

// ── Code APIs ───────────────────────────────────────────────────────────────

export interface RedeemCodesCreate {
  is_active?: boolean;
  is_single?: boolean;
  max_redemptions?: number;
}

export interface RedeemCodesUpdate {
  is_active?: boolean;
  is_single?: boolean;
  max_redemptions?: number;
  expires_at?: string;
}

export interface RedeemCodesResponse {
  id: string;
  code: string;
  is_active: boolean;
  is_single: boolean;
  max_redemptions: number;
  redemption_count: number;
  created_by: string;
  created_at: string;
  expires_at?: string | null;
  updated_at: string;
}

export interface RedeemCodeRedemptionResponse {
  id: string;
  redeem_code_id: string;
  user_id: string;
  email?: string | null;
  redeemed_at: string;
  created_at: string;
  updated_at: string;
}

export interface RedeemCodeDetailResponse extends RedeemCodesResponse {
  redemptions: RedeemCodeRedemptionResponse[];
}

export interface RedeemCodesListParams {
  page?: number;
  limit?: number;
  search?: string;
  is_active?: boolean;
}

export const codeApi = {
  /**
   * Admin: List all redeem codes in the system
   */
  getAll: (params?: RedeemCodesListParams) => {
    const qs = new URLSearchParams();
    if (params?.page) qs.append('page', String(params.page));
    if (params?.limit) qs.append('limit', String(params.limit));
    if (params?.search) qs.append('search', params.search);
    if (params?.is_active !== undefined) qs.append('is_active', String(params.is_active));
    const query = qs.toString();
    return api.get<PaginatedResponse<RedeemCodesResponse>>(`/redeem/admin/all${query ? `?${query}` : ''}`);
  },

  /**
   * Admin: Get details of a specific redeem code
   */
  getById: (codeId: string) =>
    api.get<RedeemCodeDetailResponse>(`/redeem/${codeId}`),

  /**
   * Admin: Create a new redeem code
   */
  create: (payload?: RedeemCodesCreate) =>
    api.post<RedeemCodesResponse>('/redeem/create', payload || {}),

  /**
   * Admin: Update a redeem code
   */
  update: (codeId: string, payload: RedeemCodesUpdate) =>
    api.patch<RedeemCodesResponse>(`/redeem/${codeId}`, payload),

  /**
   * Admin: Delete a redeem code
   */
  delete: (codeId: string) =>
    api.delete<{ success: boolean; message: string }>(`/redeem/${codeId}`),
};

export const redeemApi = {
  coupon: couponApi,
  code: codeApi,
};

export default redeemApi;
