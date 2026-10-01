export type SubscriptionStatus =
    | 'active'
    | 'trialing'
    | 'past_due'
    | 'canceled'
    | 'unpaid'
    | 'incomplete'
    | 'incomplete_expired'
    | 'paused';

export interface Plan {
    id: string;
    name?: string | null;
    slug?: string | null;
    price_id?: string | null;
    description: string;
    features?: string[];
    amount: number | string;
    currency: string;
    interval?: string | null;
    type?: 'SUBSCRIPTION' | 'TOKEN_PACK';
    total_token_can_use: number;
    created_at: string;
    updated_at?: string;
}

export interface SubscriptionCreatePayload {
    name?: string;
    slug?: string;
    price_id?: string;
    description?: string;
    features?: string[];
    amount: number;
    currency?: string;
    interval?: string;
    type?: 'SUBSCRIPTION' | 'TOKEN_PACK';
    total_token_can_use: number;
}

export interface SubscriptionUpdatePayload {
    name?: string;
    slug?: string;
    price_id?: string;
    description?: string;
    features?: string[];
    amount?: number;
    currency?: string;
    interval?: string;
    type?: 'SUBSCRIPTION' | 'TOKEN_PACK';
    total_token_can_use?: number;
}


export interface UserSubscription {
    id: string;
    user_id?: string | null;
    email?: string | null;
    stripe_subscription_id: string | null;
    ad_account_id?: string | null;
    plan_id: string | null;
    status: SubscriptionStatus;
    total_tokens?: number;
    used_tokens?: number;
    remaining_tokens?: number;
    current_period_start?: string | null;
    current_period_end: string | null;
    cancel_at_period_end: boolean;
    created_at: string;
    updated_at?: string;
    plan?: Plan | null;
}

export interface StripeSessionResponse {
    url: string;
}

export interface CreateCheckoutSessionRequest {
    subscription_id: string;
    ads_account_id?: string;
    success_url?: string;
    cancel_url?: string;
    price_id?: string;
}

