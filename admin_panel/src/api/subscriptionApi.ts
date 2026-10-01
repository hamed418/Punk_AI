import api from './client';
import type {
  Plan,
  SubscriptionCreatePayload,
  SubscriptionUpdatePayload,
  CreateCheckoutSessionRequest,
  StripeSessionResponse,
} from '@/types/subscription';

export const subscriptionApi = {
  /**
   * Fetch all subscription plans configured in the backend
   */
  getPlans: () => api.get<Plan[]>('/subscription/list'),

  /**
   * Fetch a single plan by ID
   */
  getPlanById: (id: string) => api.get<Plan>(`/subscription/list/${id}`),

  /**
   * Create a new subscription plan
   */
  createPlan: (data: SubscriptionCreatePayload) =>
    api.post<Plan>('/subscription/list', data),

  /**
   * Update an existing subscription plan
   */
  updatePlan: (id: string, data: SubscriptionUpdatePayload) =>
    api.patch<Plan>(`/subscription/update/${id}`, data),

  /**
   * Delete a subscription plan
   */
  deletePlan: (id: string) =>
    api.delete<Plan>(`/subscription/delete/${id}`),

  /**
   * Create Stripe checkout session
   */
  createCheckoutSession: (data: CreateCheckoutSessionRequest) =>
    api.post<StripeSessionResponse>('/billing/create-checkout-session', data),

  /**
   * Create Stripe customer portal session
   */
  createPortalSession: (return_url?: string) =>
    api.post<StripeSessionResponse>('/billing/create-portal-session', { return_url }),
};

export default subscriptionApi;

