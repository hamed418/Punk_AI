import { NextResponse } from 'next/server';
import {
  getAuthToken,
  removeAuthToken,
  removeRefreshToken,
  clearImpersonation,
  getAdminPanelUrl,
} from '@/lib/cookies';
import { getApiKey } from '@/lib/apiKey';

export async function GET() {
  const token = await getAuthToken();
  const adminPanelUrl =
    (await getAdminPanelUrl()) ||
    process.env.NEXT_PUBLIC_ADMIN_PANEL_URL ||
    'http://localhost:5173';

  // Revoke the impersonation session on backend
  if (token) {
    try {
      const BASE_URL =
        process.env.API_URL ||
        process.env.NEXT_PUBLIC_API_URL ||
        'http://localhost:8000';
      const baseUrlClean = BASE_URL.replace(/\/$/, '');
      await fetch(`${baseUrlClean}/user/stop-impersonation`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'X-API-Key': getApiKey(),
        },
      });
    } catch {
      // Continue even if backend call fails to ensure cookies are cleared
    }
  }

  // Clear session cookies
  await removeAuthToken();
  await removeRefreshToken();
  await clearImpersonation();

  // Redirect back to admin panel
  return NextResponse.redirect(adminPanelUrl);
}

export async function POST() {
  return GET();
}
