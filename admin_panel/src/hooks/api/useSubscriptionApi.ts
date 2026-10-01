import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import subscriptionApi from '@/api/subscriptionApi';
import type {
  SubscriptionCreatePayload,
  SubscriptionUpdatePayload,
  CreateCheckoutSessionRequest,
} from '@/types/subscription';

// ── Query Keys ────────────────────────────────────────────────────────────
export const SUBSCRIPTION_QUERY_KEY = {
  all: ['subscriptions'] as const,
  plans: () => ['subscriptions', 'plans'] as const,
  plan: (id: string) => ['subscriptions', 'plan', id] as const,
};

// ── Hooks ─────────────────────────────────────────────────────────────────

/**
 * Fetch all subscription plans
 */
export const usePlans = () => {
  return useQuery({
    queryKey: SUBSCRIPTION_QUERY_KEY.plans(),
    queryFn: subscriptionApi.getPlans,
    staleTime: 30 * 1000,
    retry: 1,
  });
};

/**
 * Fetch a single plan by ID
 */
export const usePlanDetails = (planId: string | null) => {
  return useQuery({
    queryKey: SUBSCRIPTION_QUERY_KEY.plan(planId ?? ''),
    queryFn: () => subscriptionApi.getPlanById(planId!),
    enabled: !!planId,
    staleTime: 30 * 1000,
    retry: 1,
  });
};

/**
 * Create a new subscription plan
 */
export const useCreatePlan = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: SubscriptionCreatePayload) => subscriptionApi.createPlan(data),
    onSuccess: (newPlan) => {
      queryClient.setQueryData(SUBSCRIPTION_QUERY_KEY.plans(), (old: Plan[] | undefined) => {
        if (!old) return [newPlan];
        return [...old, newPlan];
      });
      queryClient.invalidateQueries({ queryKey: SUBSCRIPTION_QUERY_KEY.all });
    },
  });
};

/**
 * Update an existing subscription plan
 */
export const useUpdatePlan = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: SubscriptionUpdatePayload }) =>
      subscriptionApi.updatePlan(id, data),
    onSuccess: (updatedPlan) => {
      queryClient.setQueryData(SUBSCRIPTION_QUERY_KEY.plans(), (old: Plan[] | undefined) => {
        if (!old) return [updatedPlan];
        return old.map((p) => (p.id === updatedPlan.id ? updatedPlan : p));
      });
      queryClient.invalidateQueries({ queryKey: SUBSCRIPTION_QUERY_KEY.all });
    },
  });
};

/**
 * Delete a subscription plan
 */
export const useDeletePlan = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => subscriptionApi.deletePlan(id),
    onSuccess: (_, deletedId) => {
      queryClient.setQueryData(SUBSCRIPTION_QUERY_KEY.plans(), (old: Plan[] | undefined) => {
        if (!old) return [];
        return old.filter((p) => p.id !== deletedId);
      });
      queryClient.invalidateQueries({ queryKey: SUBSCRIPTION_QUERY_KEY.all });
    },
  });
};


/**
 * Create Stripe Checkout Session
 */
export const useCreateCheckoutSession = () => {
  return useMutation({
    mutationFn: (data: CreateCheckoutSessionRequest) =>
      subscriptionApi.createCheckoutSession(data),
    onSuccess: (data) => {
      if (data?.url) {
        window.location.href = data.url;
      }
    },
  });
};

/**
 * Create Stripe Portal Session
 */
export const useCreatePortalSession = () => {
  return useMutation({
    mutationFn: (return_url?: string) =>
      subscriptionApi.createPortalSession(return_url),
    onSuccess: (data) => {
      if (data?.url) {
        window.location.href = data.url;
      }
    },
  });
};
