'use client';

import { usePathname, useSearchParams } from 'next/navigation';
import { useEffect, useRef, Suspense } from 'react';
import { trackEvent } from '@/lib/analytics/posthog';
import { getUtmParams } from '@/lib/analytics/utm';

function PostHogPageViewContent() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const lastTrackedUrl = useRef<string | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    const url = window.location.href;
    if (lastTrackedUrl.current === url) return;
    lastTrackedUrl.current = url;

    const utms = getUtmParams(searchParams ? `?${searchParams.toString()}` : '');

    trackEvent('page_viewed', {
      page_title: typeof document !== 'undefined' ? document.title : 'punk',
      pathname: pathname || '/',
      url,
      referrer: typeof document !== 'undefined' ? document.referrer : '',
      ...utms,
    });
  }, [pathname, searchParams]);

  return null;
}

export default function PostHogPageView() {
  return (
    <Suspense fallback={null}>
      <PostHogPageViewContent />
    </Suspense>
  );
}
