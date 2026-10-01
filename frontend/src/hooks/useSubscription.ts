import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { notifications } from "@mantine/notifications";
import type { CreateCheckoutSessionRequest } from "@/types/subscription";
import {
  getPlansAction,
  createCheckoutSessionAction,
  createPortalSessionAction,
  assignAdAccountAction,
  cancelSubscriptionAction,
  resumeSubscriptionAction
} from "../actions/subscription.actions";
import { trackEvent } from "@/lib/analytics";

export const usePlans = () => {
  return useQuery({
    queryKey: ["plans"],
    queryFn: async () => {
      const result = await getPlansAction();
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
  });
};

export const useCreateCheckoutSession = () => {
  return useMutation({
    mutationFn: async (data: CreateCheckoutSessionRequest) => {
      const result = await createCheckoutSessionAction(data);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
    onSuccess: (data) => {
      if (data.url) {
        window.location.href = data.url;
      }
    },
    onError: (error) => {
      console.error("Checkout Session Error:", error);
      notifications.show({
        title: "Subscription checkout failed",
        message: error.message,
        color: "red",
      });
    }
  });
};

// A subscription change moves what the Connections tab (`['user']` →
// user.subscriptions) and the Billing tab (`['user-subscriptions']`) both show.
// Nothing invalidated the second key anywhere, so the two drifted from the server
// until a hard reload.
const useInvalidateSubscriptions = () => {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["user-subscriptions"] }),
      queryClient.invalidateQueries({ queryKey: ["user"] }),
    ]);
};

export const useCreatePortalSession = () => {
  return useMutation({
    mutationFn: async (return_url?: string) => {
      const result = await createPortalSessionAction(return_url);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
    onSuccess: (data) => {
      if (data.url) {
        window.location.href = data.url;
      }
    },
  });
};

export const useAssignAdAccount = () => {
  const invalidate = useInvalidateSubscriptions();
  return useMutation({
    mutationFn: async (ads_account_id: string) => {
      const result = await assignAdAccountAction(ads_account_id);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
    onSuccess: invalidate,
  });
};

export const useCancelSubscription = () => {
  const invalidate = useInvalidateSubscriptions();
  return useMutation({
    mutationFn: async (subscription_id: string) => {
      const result = await cancelSubscriptionAction(subscription_id);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
    onSuccess: (_, subscription_id) => {
      invalidate();
      // Funnel Step 5: Subscription Cancelled
      trackEvent('Subscription Cancelled', {
        subscription_id,
        cancel_at_period_end: true,
      });
      trackEvent('subscription_cancelled', {
        subscription_id,
        cancel_at_period_end: true,
      });
    },
  });
};

export const useResumeSubscription = () => {
  const invalidate = useInvalidateSubscriptions();
  return useMutation({
    mutationFn: async (subscription_id: string) => {
      const result = await resumeSubscriptionAction(subscription_id);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
    onSuccess: invalidate,
  });
};

