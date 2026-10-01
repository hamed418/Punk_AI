import { APIError, NetworkError, UnauthorizedError, ValidationError } from './errors';
import { extractErrorMessage } from './errorUtils';
import { logger } from './logger';
import { getApiKey } from './apiKey';

type FetchOptions = RequestInit & {
  timeout?: number;
  retries?: number;
};

const DEFAULT_TIMEOUT = 60000;
const BASE_URL = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function apiFetch<T>(endpoint: string, options: FetchOptions = {}): Promise<T> {
  const { timeout = DEFAULT_TIMEOUT, retries = 0, ...customConfig } = options;

  const headers = new Headers(customConfig.headers || {});

  headers.set('X-API-Key', getApiKey());

  if (!headers.has('Content-Type') && customConfig.body && !(customConfig.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const isServer = typeof window === 'undefined';
  if (isServer) {
    const { getAuthToken } = await import('./cookies');
    const { getForwardableHeaders } = await import('./headers');

    const token = await getAuthToken();
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    }

    const forwardableHeaders = await getForwardableHeaders();
    Object.entries(forwardableHeaders).forEach(([key, value]) => {
      if (!headers.has(key)) {
        headers.set(key, String(value));
      }
    });
  }

  const config: RequestInit = {
    credentials: 'include',
    ...customConfig,
    headers,
  };

  const baseUrlClean = BASE_URL.replace(/\/$/, '');
  const endpointClean = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  const url = `${baseUrlClean}${endpointClean}`;

  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), timeout);

    try {
      const response = await fetch(url, { ...config, signal: controller.signal });
      clearTimeout(id);

      if (response.status === 204) {
        return {} as T;
      }

      let data: unknown = null;
      const contentType = response.headers.get('Content-Type');
      if (contentType && contentType.includes('application/json')) {
        data = await response.json();
      }

      if (response.ok) {
        return data as T;
      }

      const parsedMsg = extractErrorMessage(data, response.statusText || 'An error occurred');

      if (response.status === 401 && endpoint !== '/auth/refresh' && endpoint !== '/auth/login' && endpoint !== '/auth/google' && endpoint !== '/auth/logout') {
        try {
          const { refreshAuthTokenAction } = await import('../actions/auth.actions');
          const refreshResult = await refreshAuthTokenAction();
          if (refreshResult.success && refreshResult.accessToken) {
            headers.set('Authorization', `Bearer ${refreshResult.accessToken}`);
            const retryRes = await fetch(url, { ...config, headers, signal: controller.signal });

            if (retryRes.status === 204) return {} as T;

            let retryData: unknown = null;
            const retryContentType = retryRes.headers.get('Content-Type');
            if (retryContentType && retryContentType.includes('application/json')) {
              retryData = await retryRes.json();
            }

            if (retryRes.ok) return retryData as T;

            const retryMsg = extractErrorMessage(retryData, retryRes.statusText || 'An error occurred');
            if (retryRes.status === 400 || retryRes.status === 422) {
              throw new ValidationError(retryMsg, retryData);
            }
            if (retryRes.status === 401) {
              throw new UnauthorizedError(retryMsg);
            }
            throw new APIError(retryMsg, retryRes.status, retryData);
          }
        } catch (e) {
          if (e instanceof APIError || e instanceof UnauthorizedError || e instanceof ValidationError) {
            throw e;
          }
          logger.error('Failed to refresh token in apiFetch', e);
        }
        throw new UnauthorizedError(parsedMsg);
      }


      if (response.status === 400 || response.status === 422) {
        throw new ValidationError(parsedMsg, data);
      }

      throw new APIError(parsedMsg, response.status, data);

    } catch (error) {
      clearTimeout(id);

      if (error instanceof APIError) {
        logger.error(`API Error [${endpoint}]:`, error);
        throw error;
      }

      if (error instanceof Error && error.name === 'AbortError') {
        logger.error(`Request Timeout [${endpoint}]`);
        if (attempt === retries) throw new NetworkError('Request Timeout');
      } else {
        logger.error(`Network Error [${endpoint}]:`, error);
        if (attempt === retries) {
          const msg = error instanceof Error ? error.message : 'Network Error';
          throw new NetworkError(msg);
        }
      }

      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }

  throw new NetworkError('Request failed after retries');
}
