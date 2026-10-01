import { NextRequest, NextResponse } from 'next/server';
import { setAuthToken, setRefreshToken, setIsImpersonating } from '@/lib/cookies';

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const token = searchParams.get('token');
  const refreshToken = searchParams.get('refresh_token');
  const adminUrl = searchParams.get('admin_url') || '';
  const redirectPath = searchParams.get('redirect') || '/chat';

  if (!token) {
    return NextResponse.json({ error: 'Missing token' }, { status: 400 });
  }

  // Set auth cookies for the user session
  await setAuthToken(token);
  if (refreshToken) {
    await setRefreshToken(refreshToken);
  }

  // Set impersonation tracking cookie
  await setIsImpersonating(adminUrl);

  const destination = new URL(redirectPath, request.url);
  return NextResponse.redirect(destination);
}
