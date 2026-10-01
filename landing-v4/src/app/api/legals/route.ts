import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL ?? 'http://localhost:8000';
const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? '';

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const query = searchParams.toString();
  const url = `${BACKEND_URL}/legals${query ? `?${query}` : ''}`;

  try {
    const res = await fetch(url, {
      headers: {
        'X-API-Key': API_KEY,
        'Content-Type': 'application/json',
      },
      // Cache for 60 seconds — legal docs rarely change
      next: { revalidate: 60 },
    });

    const data = await res.json();

    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error('[/api/legals] upstream fetch error', err);
    return NextResponse.json(
      { detail: 'Failed to reach legal document service.' },
      { status: 502 }
    );
  }
}
