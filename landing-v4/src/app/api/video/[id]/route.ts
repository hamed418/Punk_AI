import { NextRequest, NextResponse } from 'next/server';
import { getVideoBuffer } from '@/lib/videoAssets';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const buffer = getVideoBuffer(id);

  if (!buffer) {
    return new NextResponse('Video not found', { status: 404 });
  }

  const range = request.headers.get('range');
  const total = buffer.length;

  if (range) {
    const parts = range.replace(/bytes=/, '').split('-');
    const start = parseInt(parts[0], 10);
    const end = parts[1] ? parseInt(parts[1], 10) : total - 1;
    const chunk = buffer.subarray(start, end + 1);

    return new NextResponse(new Uint8Array(chunk) as BodyInit, {
      status: 206,
      headers: {
        'Content-Range': `bytes ${start}-${end}/${total}`,
        'Accept-Ranges': 'bytes',
        'Content-Length': String(chunk.length),
        'Content-Type': 'video/mp4',
      },
    });
  }

  return new NextResponse(new Uint8Array(buffer) as BodyInit, {
    status: 200,
    headers: {
      'Content-Length': String(total),
      'Content-Type': 'video/mp4',
      'Accept-Ranges': 'bytes',
    },
  });
}
