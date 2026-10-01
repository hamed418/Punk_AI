import DashboardLayout from '@/layouts/dashboardLayout/DashboardLayout'
import { createFileRoute, redirect } from '@tanstack/react-router'

/**
 * Lightweight client-side JWT decoder.
 * Does NOT verify the signature (that's the server's job).
 * We only use it to check exp + role so we can fast-redirect
 * stale or non-admin sessions before making any network call.
 */
function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const [, payloadB64] = token.split('.');
    const padded = payloadB64.replace(/-/g, '+').replace(/_/g, '/');
    const json = atob(padded);
    return JSON.parse(json);
  } catch {
    return null;
  }
}

export const Route = createFileRoute('/(dashboard)')({
  component: DashboardLayout,
  beforeLoad: () => {
    const token = localStorage.getItem('access_token');

    // 1. No token at all → straight to login
    if (!token) {
      throw redirect({ to: '/login' });
    }

    const payload = decodeJwtPayload(token);

    // 2. Malformed token → clear and redirect
    if (!payload) {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      throw redirect({ to: '/login' });
    }

    // 3. Expired access token → let the app load; the HTTP client will
    //    auto-refresh on the first API call. We only hard-redirect if there
    //    is also no refresh token, meaning the session is fully dead.
    const nowSec = Math.floor(Date.now() / 1000);
    const expSec = payload['exp'] as number | undefined;
    const refreshToken = localStorage.getItem('refresh_token');

    if (expSec && nowSec >= expSec && !refreshToken) {
      // Fully expired — no refresh token to recover with
      localStorage.removeItem('access_token');
      throw redirect({ to: '/login' });
    }

    // 4. Role check — must be admin or super_admin
    const role = payload['role'] as string | undefined;
    if (role && role !== 'admin' && role !== 'super_admin') {
      // Valid token but wrong role (e.g. regular user token somehow in storage)
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      throw redirect({ to: '/login' });
    }
  },
})
