import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { authApi } from '../../api/auth';
import type { AdminUser } from '../../api/auth';

// ── Query Keys ────────────────────────────────────────────────────────────
export const AUTH_QUERY_KEY = ['adminUser'] as const;

// ── Hooks ─────────────────────────────────────────────────────────────────

/**
 * Fetches the current admin profile from the API.
 * Enabled only when an access token is present.
 */
export const useUser = () => {
    const token = localStorage.getItem('access_token');
    return useQuery<AdminUser>({
        queryKey: AUTH_QUERY_KEY,
        queryFn: authApi.getMe,
        enabled: !!token,
        retry: false,
        staleTime: 5 * 60 * 1000,      // treat data as fresh for 5 min
        gcTime: 10 * 60 * 1000,        // keep in cache for 10 min after unmount
        refetchOnWindowFocus: false,    // don't ping /me every time user switches tabs
        refetchOnMount: 'always',       // always re-validate on browser refresh / remount
    });
};

/**
 * Admin login mutation.
 * On success: stores tokens, sets user query data, navigates to /analytics.
 */
export const useLogin = () => {
    const queryClient = useQueryClient();
    const navigate = useNavigate();

    return useMutation({
        mutationFn: ({ email, password }: { email: string; password: string }) =>
            authApi.login(email, password),
        onSuccess: (data) => {
            localStorage.setItem('access_token', data.access_token);
            localStorage.setItem('refresh_token', data.refresh_token);
            // Immediately seed user data to avoid a redundant /auth/admin/me call
            queryClient.setQueryData(AUTH_QUERY_KEY, data.user);
            navigate({ to: '/analytics' });
        },
    });
};

/**
 * Admin logout mutation.
 * Calls server logout, clears local storage, purges all cached queries,
 * and redirects to /login.
 */
export const useLogout = () => {
    const queryClient = useQueryClient();
    const navigate = useNavigate();

    return useMutation({
        mutationFn: async () => {
            try {
                await authApi.logout();
            } catch {
                // Even if the server call fails, always clear local state
            }
        },
        onSettled: () => {
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            queryClient.clear();
            navigate({ to: '/login' });
        },
    });
};

// Legacy aliases kept for backwards compat with existing contexts
export const useRegister = () => {
    return useMutation({
        mutationFn: (_: any) => Promise.reject(new Error('Register not available in admin panel')),
    });
};

export const useUpdateProfile = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (_data: any) => Promise.resolve({} as AdminUser),
        onSuccess: (data) => {
            queryClient.setQueryData(AUTH_QUERY_KEY, data);
        },
    });
};
