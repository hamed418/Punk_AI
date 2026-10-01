'use client';

import React, { useEffect, useState, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { verifySubscriptionSuccess } from '@/lib/api';
import { trackEvent, identifyUser } from '@/lib/analytics';
import { PixelButton } from '@/components/PixelButton';

function SubscriptionSuccessContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const sessionId = searchParams.get('session_id');
  const email = searchParams.get('email') || '';

  const [status, setStatus] = useState<'loading' | 'success' | 'error'>(
    sessionId ? 'loading' : 'error'
  );
  const [errorMessage, setErrorMessage] = useState(
    sessionId ? '' : 'Missing session ID from Stripe.'
  );

  useEffect(() => {
    if (!sessionId) return;

    const verify = async () => {
      try {
        await verifySubscriptionSuccess(sessionId);
        setStatus('success');

        trackEvent('payment_succeeded', {
          session_id: sessionId,
          source: 'stripe_redirect_page',
          plan_name: 'pro',
        });

        if (email) {
          identifyUser(email, {
            email,
            is_paid_member: true,
          });
        }

        // Redirect to landing page with payment-success parameter to show access modal
        setTimeout(() => {
          const params = new URLSearchParams();
          params.set('payment-success', 'true');
          if (email) params.set('email', email);
          if (sessionId) params.set('session_id', sessionId);
          router.push(`/?${params.toString()}`);
        }, 1200);
      } catch (err) {
        setStatus('error');
        setErrorMessage(
          err instanceof Error ? err.message : 'Failed to verify subscription payment.'
        );
      }
    };

    verify();
  }, [sessionId, email, router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#FAF9F5] px-4 py-12">
      <div className="w-full max-w-md rounded-2xl border border-[#1515151A] bg-white p-8 text-center shadow-[0_8px_30px_rgb(0,0,0,0.06)]">
        {status === 'loading' && (
          <div className="flex flex-col items-center">
            <svg
              className="h-10 w-10 animate-spin text-[#F02D8A]"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="3"
              ></circle>
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              ></path>
            </svg>
            <h2 className="mt-4 font-display text-xl font-medium tracking-tight text-[#151515]">
              Verifying Payment
            </h2>
            <p className="mt-2 text-sm text-[#15151599]">
              Please wait while we confirm your subscription details...
            </p>
          </div>
        )}

        {status === 'success' && (
          <div className="flex flex-col items-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[#F02D8A]/10 text-[#F02D8A]">
              <svg viewBox="0 0 7 7" className="h-6 w-6" shapeRendering="crispEdges" fill="currentColor">
                <rect x="0" y="3" width="1" height="2" />
                <rect x="1" y="4" width="1" height="2" />
                <rect x="2" y="5" width="1" height="2" />
                <rect x="3" y="4" width="1" height="2" />
                <rect x="4" y="3" width="1" height="2" />
                <rect x="5" y="2" width="1" height="2" />
                <rect x="6" y="1" width="1" height="2" />
              </svg>
            </div>
            <h2 className="mt-4 font-display text-xl font-medium tracking-tight text-[#151515]">
              Payment Successful!
            </h2>
            <p className="mt-2 text-sm text-[#15151599]">
              Your early access spot is confirmed. Redirecting you to punk...
            </p>
            <div className="mt-6 w-full">
              <PixelButton
                href={`/?payment-success=true${email ? `&email=${encodeURIComponent(email)}` : ''}${sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : ''}`}
                className="pk-btn--primary pk-btn--md w-full"
                variant="primary"
              >
                Go to punk
              </PixelButton>
            </div>
          </div>
        )}

        {status === 'error' && (
          <div className="flex flex-col items-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-red-100 text-red-600">
              <svg
                viewBox="0 0 24 24"
                className="h-6 w-6"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <circle cx="12" cy="12" r="10" />
                <line x1="15" y1="9" x2="9" y2="15" />
                <line x1="9" y1="9" x2="15" y2="15" />
              </svg>
            </div>
            <h2 className="mt-4 font-display text-xl font-medium tracking-tight text-[#151515]">
              Verification Issue
            </h2>
            <p className="mt-2 text-sm text-red-600">{errorMessage}</p>
            <div className="mt-6 w-full">
              <PixelButton
                href="/"
                className="pk-btn--secondary pk-btn--md w-full"
                variant="secondary"
              >
                Return to home
              </PixelButton>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function SubscriptionSuccessPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-[#FAF9F5]">
          <div className="text-sm font-medium text-[#15151599]">Loading...</div>
        </div>
      }
    >
      <SubscriptionSuccessContent />
    </Suspense>
  );
}
