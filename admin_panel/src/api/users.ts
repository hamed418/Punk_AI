import api from './client';

// ── Types ─────────────────────────────────────────────────────────────────

export type UserRole = 'user' | 'admin' | 'super_admin';

export interface UserListItem {
  id: string;
  email: string;
  full_name: string | null;
  role: UserRole;
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
  subscription_plan: string | null;
  campaigns_count: number;
  conversations_count: number;
  last_active_at: string | null;
}

export interface PaginatedUsers {
  data: UserListItem[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface UserStats {
  total_users: number;
  active_users: number;       // users with a session in last 30 days
  new_this_month: number;
  suspended_users: number;
  paying_users: number;       // distinct users with active subscription
  plan_breakdown: Record<string, number>;
}

export interface UserDetails extends UserListItem {
  phone: string | null;
  free_message_limit: number | null;
  free_token_usage: number | null;
  isSubscriptionActive: boolean | null;
  active_devices_count: number;
  inactive_devices_count: number;
  login_count: number;
  subscriptions_count: number;
  meta_accounts_count: number;
  ads_accounts_count: number;
  active_ads_accounts: Array<{
    id: string;
    ad_account_id: string | null;
    ad_account_name: string | null;
    is_subscribed: boolean;
  }>;
}

export interface UserListParams {
  page?: number;
  limit?: number;
  search?: string;   // matches name OR email
  role?: string;
  is_active?: boolean;
  plan?: string;     // server-side subscription plan filter
}

// ── Users API ─────────────────────────────────────────────────────────────

export const usersApi = {
  /**
   * Paginated admin user list with enriched fields (plan, counts, last active).
   */
  list: (params: UserListParams = {}) => {
    const qs = new URLSearchParams();
    if (params.page) qs.set('page', String(params.page));
    if (params.limit) qs.set('limit', String(params.limit));
    if (params.search) qs.set('search', params.search);
    if (params.role) qs.set('role', params.role);
    if (params.plan) qs.set('plan', params.plan);
    if (params.is_active !== undefined) qs.set('is_active', String(params.is_active));
    return api.get<PaginatedUsers>(`/user/list?${qs.toString()}`);
  },

  /**
   * Aggregate stats for overview cards.
   */
  stats: () => api.get<UserStats>('/user/stats'),

  /**
   * Detailed user profile (devices, sessions, subscriptions, ads accounts).
   */
  details: (userId: string) =>
    api.get<UserDetails>(`/user/${userId}/details`),

  /**
   * Update user role.
   */
  updateRole: (userId: string, role: UserRole) =>
    api.patch(`/user/${userId}/role`, { role }),

  /**
   * Activate / deactivate a user.
   */
  updateStatus: (userId: string, is_active: boolean) =>
    api.patch(`/user/${userId}/status`, { is_active }),

  /**
   * Manually verify / unverify a user.
   */
  updateVerification: (userId: string, is_verified: boolean) =>
    api.patch(`/user/${userId}/verification`, { is_verified }),

  /**
   * Start impersonating a target user.
   */
  impersonate: (userId: string) =>
    api.post<ImpersonateResponse>(`/user/${userId}/impersonate`),

  /**
   * Stop impersonating the current user and revoke the impersonated session.
   */
  stopImpersonation: () =>
    api.post<StopImpersonationResponse>('/user/stop-impersonation'),
};

export interface ImpersonateResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: {
    id: string;
    email: string;
    full_name: string | null;
    role: UserRole;
    is_active: boolean;
    is_verified: boolean;
    [key: string]: unknown;
  };
}

export interface StopImpersonationResponse {
  message: string;
  admin_id?: string;
  target_user_id?: string;
}

export default usersApi;
