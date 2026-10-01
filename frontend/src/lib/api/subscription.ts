import { apiFetch } from '../fetcher';
import type { CreateCheckoutSessionRequest, Plan, StripeSessionResponse, UserSubscription } from "@/types/subscription";

// What cancel and resume answer with. `current_period_end` can be null: checkout
// does not record it, and Stripe's reply is the first place it shows up.
export interface SubscriptionChangeResponse {
  status?: string;
  message?: string;
  cancel_at_period_end?: boolean;
  current_period_end?: string | null;
}

export const subscriptionApi = {
  getPlans: () => {
    return apiFetch<Plan[]>('/subscription/list', {
      method: 'GET',
      next: { tags: ['subscription-plans'] },
    });
  },

  createCheckoutSession: (data: CreateCheckoutSessionRequest) => {
    return apiFetch<StripeSessionResponse>('/subscription/checkout', {
      method: 'POST',
      body: JSON.stringify(data),
      cache: 'no-store',
    });
  },

  createPortalSession: (return_url?: string) => {
    return apiFetch<StripeSessionResponse>('/subscription/portal', {
      method: 'POST',
      body: JSON.stringify({ return_url }),
      cache: 'no-store',
    });
  },

  getUserSubscriptions: () => {
    return apiFetch<(UserSubscription & { plan?: Plan })[]>('/me/subscriptions', {
      method: 'GET',
      cache: 'no-store',
    });
  },

  assignAdAccount: (ads_account_id: string) => {
    return apiFetch<{ status: string; message: string }>('/subscription/assign-ad-account', {
      method: 'POST',
      body: JSON.stringify({ ads_account_id }),
      cache: 'no-store',
    });
  },

  // The backend declares `subscription_id` as Body(..., embed=True). It used to be
  // sent as a query string with no body, which FastAPI rejects with a 422 on every
  // call — cancel never once worked from the UI.
  cancelSubscription: (subscription_id: string) => {
    return apiFetch<SubscriptionChangeResponse>('/subscription/cancel', {
      method: 'POST',
      body: JSON.stringify({ subscription_id }),
      cache: 'no-store',
    });
  },

  resumeSubscription: (subscription_id: string) => {
    return apiFetch<SubscriptionChangeResponse>('/subscription/resume', {
      method: 'POST',
      body: JSON.stringify({ subscription_id }),
      cache: 'no-store',
    });
  },

  syncCheckoutSession: (session_id: string) => {
    return apiFetch<{ success: boolean; message: string }>(
      `/subscription/success?session_id=${encodeURIComponent(session_id)}`,
      { method: 'GET', cache: 'no-store' }
    );
  },
};

