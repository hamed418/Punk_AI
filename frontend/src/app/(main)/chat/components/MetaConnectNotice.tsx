'use client';

import { useEffect, useRef } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { notifications } from '@mantine/notifications';

// What the OAuth callback (`GET /ads/callback/meta`) sends back when Meta will not
// complete a connection: a short reason, never a token and never internal error
// text. The popup lands on this page, so this is where the reason has to be said.
const MESSAGES: Record<string, string> = {
  denied:
    "Meta didn't complete the connection. If you're an early user, make sure you've accepted the invite to test Punk on Meta — otherwise contact us and we'll get you in.",
  expired: 'That connection link expired. Close this window and start again from the Connect button.',
  failed: 'Something went wrong finishing the connection. Close this window and try again in a moment.',
};

/**
 * Says why a Meta connection failed, once, then clears the params.
 *
 * Renders nothing. Without it a refusal from Meta showed a raw JSON error in the
 * popup — the most likely failure while the Meta app is still invite-only.
 */
export default function MetaConnectNotice() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const shown = useRef(false);

  useEffect(() => {
    const reason = searchParams.get('meta_error');
    if (!reason || shown.current) return;
    shown.current = true;

    const detail = searchParams.get('meta_error_detail');
    notifications.show({
      title: 'Meta connection',
      message: [MESSAGES[reason] ?? MESSAGES.failed, detail].filter(Boolean).join(' — '),
      color: 'red',
      autoClose: false,
    });

    const next = new URLSearchParams(Array.from(searchParams.entries()));
    next.delete('meta_error');
    next.delete('meta_error_detail');
    const search = next.toString();
    router.replace(search ? `${pathname}?${search}` : pathname);
  }, [searchParams, router, pathname]);

  return null;
}
