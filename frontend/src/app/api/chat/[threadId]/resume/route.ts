import { NextRequest } from 'next/server';
import { getAuthToken } from '@/lib/cookies';
import { getForwardableHeaders } from '@/lib/headers';
import { getApiKey } from '@/lib/apiKey';

const BASE_URL = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function POST(req: NextRequest, { params }: { params: Promise<{ threadId: string }> }) {
  try {
    const resolvedParams = await params;
    const body = await req.text();
    const token = await getAuthToken();

    const headers = new Headers({
      'Content-Type': 'application/json',
      'X-API-Key': getApiKey(),
    });

    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    }

    const forwardableHeaders = await getForwardableHeaders();
    Object.entries(forwardableHeaders).forEach(([key, value]) => {
      if (!headers.has(key)) {
        headers.set(key, String(value));
      }
    });



    let backendResponse = await fetch(`${BASE_URL.replace(/\/$/, '')}/chat/${resolvedParams.threadId}/resume`, {
      method: 'POST',
      headers,
      body,
    });

    if (backendResponse.status === 401) {
      const { refreshAuthTokenAction } = await import('@/actions/auth.actions');
      const refreshResult = await refreshAuthTokenAction();
      if (refreshResult.success && refreshResult.accessToken) {
        headers.set('Authorization', `Bearer ${refreshResult.accessToken}`);
        backendResponse = await fetch(`${BASE_URL.replace(/\/$/, '')}/chat/${resolvedParams.threadId}/resume`, {
          method: 'POST',
          headers,
          body,
        });
      }
    }

    return new Response(backendResponse.body, {
      status: backendResponse.status,
      headers: {
        'Content-Type': backendResponse.headers.get('Content-Type') || 'text/event-stream',
      },
    });
  } catch (error: unknown) {
    return new Response(JSON.stringify({ error: error instanceof Error ? error.message : 'Unknown error' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}
