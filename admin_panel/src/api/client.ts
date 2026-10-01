const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const API_KEY = import.meta.env.VITE_API_KEY || '';


export interface ApiError {
    message: string;
    status?: number;
    data?: any;
}

let refreshPromise: Promise<string> | null = null;

/**
 * Check if a JWT token is expired or expiring in the next bufferSeconds (default 30s).
 */
export function isTokenExpired(token: string | null, bufferSeconds = 30): boolean {
    if (!token) return true;
    try {
        const parts = token.split('.');
        if (parts.length !== 3) return true;
        const base64Url = parts[1];
        const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
        const jsonPayload = decodeURIComponent(
            atob(base64)
                .split('')
                .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
                .join('')
        );
        const payload = JSON.parse(jsonPayload);
        if (!payload.exp) return false;
        const expiryTime = payload.exp * 1000;
        return Date.now() >= expiryTime - bufferSeconds * 1000;
    } catch {
        return true;
    }
}

/**
 * Perform the actual token refresh call to /auth/refresh.
 * Deduplicates concurrent calls via refreshPromise.
 */
export async function refreshAccessToken(): Promise<string> {
    if (refreshPromise) {
        return refreshPromise;
    }

    refreshPromise = (async () => {
        const refreshToken = localStorage.getItem('refresh_token');
        if (!refreshToken) {
            throw new Error('No refresh token available');
        }

        const res = await fetch(`${BASE_URL.replace(/\/$/, '')}/auth/refresh`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(API_KEY ? { 'X-API-Key': API_KEY } : {}),
            },
            body: JSON.stringify({ refresh_token: refreshToken }),
        });

        if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            const err: ApiError = {
                message: body.detail || body.message || 'Failed to refresh access token',
                status: res.status,
                data: body,
            };
            throw err;
        }

        const data = await res.json();
        if (!data.access_token) {
            throw new Error('Invalid refresh response');
        }

        localStorage.setItem('access_token', data.access_token);
        if (data.refresh_token) {
            localStorage.setItem('refresh_token', data.refresh_token);
        }
        return data.access_token as string;
    })().finally(() => {
        refreshPromise = null;
    });

    return refreshPromise;
}

/**
 * Ensures a valid access token is available.
 * If expired and a refresh token exists, refreshes automatically.
 */
async function getValidAccessToken(): Promise<string | null> {
    const currentAccessToken = localStorage.getItem('access_token');
    const refreshToken = localStorage.getItem('refresh_token');

    // If there's an ongoing refresh in progress, always wait for it
    if (refreshPromise) {
        try {
            return await refreshPromise;
        } catch {
            return null;
        }
    }

    // If access token is missing or expired, attempt refresh if we have a refresh_token
    if (isTokenExpired(currentAccessToken) && refreshToken) {
        try {
            return await refreshAccessToken();
        } catch {
            return null;
        }
    }

    return currentAccessToken;
}

async function request<T>(
    endpoint: string,
    options: RequestInit = {},
    isStream = false
): Promise<T> {
    const baseUrlClean = BASE_URL.replace(/\/$/, '');
    const endpointClean = endpoint.replace(/^\//, '');
    const url = `${baseUrlClean}/${endpointClean}`;

    const isAuthEndpoint =
        endpoint.includes('/auth/refresh') ||
        endpoint.includes('/auth/admin/login') ||
        endpoint.includes('/auth/login') ||
        endpoint.includes('/auth/admin/logout');

    const makeRequest = async (token?: string | null) => {
        const isFormData = options.body instanceof FormData;
        const headers = new Headers(options.headers);

        const hasBody = !!options.body;
        if (hasBody && !isFormData && !headers.has('Content-Type')) {
            headers.set('Content-Type', 'application/json');
        }

        // Always send the API key so the backend gateway passes the request
        if (API_KEY) {
            headers.set('X-API-Key', API_KEY);
        }

        if (token) {
            headers.set('Authorization', `Bearer ${token}`);
        }

        return fetch(url, { ...options, headers });
    };

    // 1. For non-auth endpoints, get a valid access token (proactively refreshing if expired)
    let token: string | null = null;
    if (!isAuthEndpoint) {
        token = await getValidAccessToken();
    } else {
        token = localStorage.getItem('access_token');
    }
    let response = await makeRequest(token);

    // 2. Handle 401 Unauthorized (reactive fallback for clock skew, backend invalidation, etc.)
    if (response.status === 401) {
        if (isAuthEndpoint) {
            const errorData = await response.json().catch(() => ({}));
            throw {
                message: errorData.detail || errorData.message || 'Authentication failed',
                status: response.status,
                data: errorData,
            } as ApiError;
        }

        try {
            // Check if another request has already refreshed the token in localStorage
            const latestToken = localStorage.getItem('access_token');
            let newToken: string;

            if (latestToken && latestToken !== token && !isTokenExpired(latestToken, 5)) {
                newToken = latestToken;
            } else {
                newToken = await refreshAccessToken();
            }

            // Retry the original request with the fresh token
            response = await makeRequest(newToken);
        } catch (refreshErr) {
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            if (
                typeof window !== 'undefined' &&
                !window.location.pathname.includes('/login') &&
                !window.location.pathname.includes('/register')
            ) {
                window.location.href = '/login';
            }
            throw refreshErr;
        }
    }

    if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw {
            message: errorData.detail || errorData.message || 'API request failed',
            status: response.status,
            data: errorData,
        } as ApiError;
    }

    if (isStream) {
        return response as unknown as T;
    }

    if (response.status === 204) {
        return {} as T;
    }

    return response.json();
}

export const api = {
    get: <T>(endpoint: string, options?: RequestInit) =>
        request<T>(endpoint, { ...options, method: 'GET' }),

    post: <T>(endpoint: string, data?: any, options?: RequestInit) =>
        request<T>(endpoint, {
            ...options,
            method: 'POST',
            body: data && !(data instanceof FormData) ? JSON.stringify(data) : data
        }),

    put: <T>(endpoint: string, data?: any, options?: RequestInit) =>
        request<T>(endpoint, {
            ...options,
            method: 'PUT',
            body: data && !(data instanceof FormData) ? JSON.stringify(data) : data
        }),

    patch: <T>(endpoint: string, data?: any, options?: RequestInit) =>
        request<T>(endpoint, {
            ...options,
            method: 'PATCH',
            body: data && !(data instanceof FormData) ? JSON.stringify(data) : data
        }),

    delete: <T>(endpoint: string, options?: RequestInit) =>
        request<T>(endpoint, { ...options, method: 'DELETE' }),

    upload: <T>(endpoint: string, formData: FormData, options?: RequestInit) =>
        request<T>(endpoint, {
            ...options,
            method: 'POST',
            body: formData,
        }),

    stream: (endpoint: string, options?: RequestInit) =>
        request<Response>(endpoint, options, true),
};

export default api;