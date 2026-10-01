export interface FaqItem {
  id: string | number;
  question: string;
  answer: string;
  order?: number;
}

export interface SubscriptionPlan {
  id: string;
  name?: string;
  slug?: string;
  amount?: number | string;
  description?: string;
  interval?: string;
}

export interface EarlyAccessCheckoutPayload {
  email: string;
  success_url: string;
  cancel_url: string;
  subscription_id?: string;
}

export interface CheckoutResponse {
  url?: string;
  message?: string;
  detail?: unknown;
}

export interface CheckEmailResponse {
  exists: boolean;
  email: string;
  message: string;
}

export const getApiUrl = (): string => {
  return process.env.NEXT_PUBLIC_API_URL || "";
};

export const getApiKey = (): string => {
  return process.env.NEXT_PUBLIC_API_KEY || "";
};

export const formatErrorMessage = (detail: unknown): string => {
  if (!detail) return 'Failed to process request. Please try again.';
  if (typeof detail !== 'string') {
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0];
      return typeof first === 'object' && first?.msg
        ? String(first.msg)
        : 'Invalid submission details. Please try again.';
    }
    return 'Failed to process request. Please try again.';
  }
  if (detail.includes('valid UUID') || detail.toLowerCase().includes('uuid')) {
    return 'Invalid subscription plan. Please select a valid plan and try again.';
  }
  return detail;
};

/**
 * Fetch FAQs for landing page (GET /faq/landing-faq?limit=100)
 */
export async function fetchLandingFaqs(): Promise<FaqItem[]> {
  const apiUrl = getApiUrl();
  const apiKey = getApiKey();
  const res = await fetch(`${apiUrl}/faq/landing-faq?limit=100`, {
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': apiKey,
    },
    cache: 'no-store',
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch FAQs: ${res.statusText}`);
  }

  const json = await res.json();
  const items: FaqItem[] = Array.isArray(json) ? json : json?.data || [];
  return items;
}

/**
 * Fetch available subscription plans (GET /subscription/list)
 */
export async function fetchSubscriptionPlans(): Promise<SubscriptionPlan[]> {
  const apiUrl = getApiUrl();
  const apiKey = getApiKey();
  const res = await fetch(`${apiUrl}/subscription/list`, {
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': apiKey,
    },
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch subscriptions: ${res.statusText}`);
  }

  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

/**
 * Create Stripe Checkout Session for early access (POST /early-access/checkout)
 */
export async function createEarlyAccessCheckout(
  payload: EarlyAccessCheckoutPayload
): Promise<CheckoutResponse> {
  const apiUrl = getApiUrl();
  const apiKey = getApiKey();
  const res = await fetch(`${apiUrl}/early-access/checkout`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': apiKey,
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const errorData = (await res.json().catch(() => ({}))) as {
      detail?: unknown;
      message?: string;
    };
    throw new Error(formatErrorMessage(errorData.detail || errorData.message));
  }

  const data = (await res.json()) as CheckoutResponse;
  if (!data.url) {
    throw new Error('No checkout URL returned from server.');
  }
  return data;
}

/**
 * Verify Stripe Checkout Session completion (GET /subscription/success?session_id=...)
 */
export async function verifySubscriptionSuccess(sessionId: string): Promise<boolean> {
  const apiUrl = getApiUrl();
  const apiKey = getApiKey();
  const res = await fetch(`${apiUrl}/subscription/success?session_id=${encodeURIComponent(sessionId)}`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': apiKey,
    },
  });

  if (!res.ok) {
    const errorData = (await res.json().catch(() => null)) as {
      detail?: unknown;
      message?: string;
    } | null;
    throw new Error(
      errorData?.detail
        ? formatErrorMessage(errorData.detail)
        : errorData?.message || 'Failed to verify subscription payment.'
    );
  }

  return true;
}

/**
 * Check if a user already exists with this email (GET /auth/check-email?email=...)
 */
export async function checkEmailExists(email: string): Promise<CheckEmailResponse> {
  const apiUrl = getApiUrl();
  const apiKey = getApiKey();
  const cleanEmail = email.trim().toLowerCase();
  const res = await fetch(`${apiUrl}/auth/check-email?email=${encodeURIComponent(cleanEmail)}`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': apiKey,
    },
  });

  if (!res.ok) {
    return { exists: false, email: cleanEmail, message: 'Check unavailable' };
  }

  return res.json();
}
