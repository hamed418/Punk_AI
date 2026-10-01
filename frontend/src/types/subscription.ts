export type SubscriptionStatus =
  | "active"
  | "trialing"
  | "past_due"
  | "canceled"
  | "unpaid"
  | "incomplete"
  | "incomplete_expired"
  | "paused";

export interface Plan {
  id: string;
  subscription_id?: string;
  name?: string;
  slug?: string;
  description: string;
  features?: string[];
  amount?: number;
  currency: string;
  created_at?: string;
  updated_at?: string;
  price_id?: string;
}

export interface UserSubscription {
  id: string;
  stripe_subscription_id: string | null;
  plan_id: string | null;
  status: SubscriptionStatus;
  // The Meta ad account this subscription is scoped to — null means
  // unscoped (not yet assigned to an account, or a guest/early-access row).
  ad_account_id: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  total_tokens?: number;
  used_tokens?: number;
  remaining_tokens?: number;
  created_at: string;
  updated_at: string;
}

export interface StripeSessionResponse {
  url: string;
}

export interface CreateCheckoutSessionRequest {
  subscription_id?: string;
  ads_account_id?: string;
  price_id?: string;
  success_url?: string;
  cancel_url?: string;
  coupon_code?: string;
  amount?: number;
}
