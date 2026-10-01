import api from './client';

// ── Types ─────────────────────────────────────────────────────────────────

export type AdminRole = 'admin' | 'super_admin';

export interface AdminUser {
    id: string;
    email: string;
    full_name: string | null;
    role: AdminRole;
}

export interface AdminLoginResponse {
    access_token: string;
    refresh_token: string;
    token_type: string;
    expires_in: number;
    user: AdminUser;
}

export interface RefreshTokenResponse {
    access_token: string;
    refresh_token: string;
    token_type: string;
    expires_in: number;
}

// ── Auth API ──────────────────────────────────────────────────────────────

export const authApi = {
    /**
     * Admin-only login. Returns tokens + admin user info.
     * Rejects regular (non-admin) users with 403.
     */
    login: (email: string, password: string) =>
        api.post<AdminLoginResponse>('/auth/admin/login', { email, password }),

    /**
     * Get the current admin's profile (requires valid access token).
     */
    getMe: () =>
        api.get<AdminUser>('/auth/admin/me'),

    /**
     * Revoke current admin session.
     */
    logout: () =>
        api.post<{ message: string }>('/auth/admin/logout', {}),

    /**
     * Exchange a refresh token for a new access + refresh token pair.
     */
    refreshToken: (refresh_token: string) =>
        api.post<RefreshTokenResponse>('/auth/refresh', { refresh_token }),
};

export default authApi;
