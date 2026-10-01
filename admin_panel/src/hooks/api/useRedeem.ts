import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import {
  couponApi,
  codeApi,
  type CreateCouponPayload,
  type UpdateCouponPayload,
  type CouponListParams,
  type CouponRedemptionListParams,
  type RedeemCodesCreate,
  type RedeemCodesUpdate,
  type RedeemCodesListParams,
} from '@/api/redeem';

// ── Coupon APIs ─────────────────────────────────────────────────────────────

export const COUPON_QUERY_KEYS = {
  all: ['coupons'] as const,
  list: (params?: CouponListParams) => ['coupons', 'list', params] as const,
  details: (id: string) => ['coupons', 'details', id] as const,
  redemptions: (params?: CouponRedemptionListParams) => ['coupons', 'redemptions', params] as const,
};

/**
 * List all coupons (Admin)
 */
export const useCoupons = (params?: CouponListParams) => {
  return useQuery({
    queryKey: COUPON_QUERY_KEYS.list(params),
    queryFn: () => couponApi.getAll(params),
    placeholderData: keepPreviousData,
    staleTime: 1000 * 60 * 2, // 2 minutes
    refetchOnWindowFocus: false,
  });
};

/**
 * Get coupon details by ID (Admin)
 */
export const useCoupon = (couponId: string | null | undefined) => {
  return useQuery({
    queryKey: COUPON_QUERY_KEYS.details(couponId ?? ''),
    queryFn: () => couponApi.getById(couponId!),
    enabled: !!couponId,
    staleTime: 1000 * 60 * 2,
    refetchOnWindowFocus: false,
  });
};

/**
 * Create a new coupon (Admin)
 */
export const useCreateCoupon = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateCouponPayload) => couponApi.create(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: COUPON_QUERY_KEYS.all });
    },
  });
};

/**
 * Update an existing coupon (Admin)
 */
export const useUpdateCoupon = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ couponId, payload }: { couponId: string; payload: UpdateCouponPayload }) =>
      couponApi.update(couponId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: COUPON_QUERY_KEYS.all });
    },
  });
};

/**
 * Delete a coupon (Admin)
 */
export const useDeleteCoupon = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (couponId: string) => couponApi.delete(couponId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: COUPON_QUERY_KEYS.all });
    },
  });
};

/**
 * List all coupon redemptions (Admin)
 */
export const useCouponRedemptions = (
  params?: CouponRedemptionListParams,
  options?: { enabled?: boolean }
) => {
  return useQuery({
    queryKey: COUPON_QUERY_KEYS.redemptions(params),
    queryFn: () => couponApi.getRedemptions(params),
    placeholderData: keepPreviousData,
    staleTime: 1000 * 60 * 2,
    refetchOnWindowFocus: false,
    enabled: options?.enabled,
  });
};

/**
 * Revert a coupon redemption (Admin)
 */
export const useRevertCouponRedemption = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (redemptionId: string) => couponApi.revertRedemption(redemptionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: COUPON_QUERY_KEYS.all });
    },
  });
};

// ── Code APIs ───────────────────────────────────────────────────────────────

export const CODE_QUERY_KEYS = {
  all: ['redeemCodes'] as const,
  list: (params?: RedeemCodesListParams) => ['redeemCodes', 'list', params] as const,
  details: (id: string) => ['redeemCodes', 'details', id] as const,
};

/**
 * List all redeem codes (Admin)
 */
export const useRedeemCodes = (params?: RedeemCodesListParams) => {
  return useQuery({
    queryKey: CODE_QUERY_KEYS.list(params),
    queryFn: () => codeApi.getAll(params),
    placeholderData: keepPreviousData,
    staleTime: 1000 * 60 * 2,
    refetchOnWindowFocus: false,
  });
};

/**
 * Get redeem code details by ID (Admin)
 */
export const useRedeemCode = (
  codeId: string | null | undefined,
  options?: { enabled?: boolean }
) => {
  return useQuery({
    queryKey: CODE_QUERY_KEYS.details(codeId ?? ''),
    queryFn: () => codeApi.getById(codeId!),
    enabled: (options?.enabled ?? true) && !!codeId,
    staleTime: 1000 * 60 * 2,
    refetchOnWindowFocus: false,
  });
};

/**
 * Create a new redeem code (Admin)
 */
export const useCreateRedeemCode = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload?: RedeemCodesCreate) => codeApi.create(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: CODE_QUERY_KEYS.all });
    },
  });
};

/**
 * Update an existing redeem code (Admin)
 */
export const useUpdateRedeemCode = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ codeId, payload }: { codeId: string; payload: RedeemCodesUpdate }) =>
      codeApi.update(codeId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: CODE_QUERY_KEYS.all });
    },
  });
};

/**
 * Delete a redeem code (Admin)
 */
export const useDeleteRedeemCode = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (codeId: string) => codeApi.delete(codeId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: CODE_QUERY_KEYS.all });
    },
  });
};
