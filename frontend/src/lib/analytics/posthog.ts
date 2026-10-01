import posthog from 'posthog-js';
import { EventRegistry, AnalyticsEventName } from './events';
import { getUtmParams, persistAttributionData, getStoredAttributionData } from './utm';

let isInitialized = false;

export const POSTHOG_KEY = process.env.NEXT_PUBLIC_POSTHOG_KEY || '';
export const POSTHOG_HOST = process.env.NEXT_PUBLIC_POSTHOG_HOST || '';
export const ROOT_DOMAIN = process.env.NEXT_PUBLIC_ROOT_DOMAIN || '';
export const CONSENT_REQUIRED = process.env.NEXT_PUBLIC_CONSENT_REQUIRED === 'true';

export function initPostHog(): void {
  if (typeof window === 'undefined' || isInitialized) return;

  if (!POSTHOG_KEY) return;

  try {
    persistAttributionData();

    posthog.init(POSTHOG_KEY, {
      api_host: POSTHOG_HOST,
      capture_pageview: false, // Handled by PostHogPageView on App Router transitions
      capture_pageleave: true,
      autocapture: {
        css_selector_allowlist: ['[data-ph-capture]'],
      },
      cross_subdomain_cookie: Boolean(ROOT_DOMAIN),
      opt_out_capturing_by_default: CONSENT_REQUIRED,
      session_recording: {
        maskAllInputs: true,
        maskTextSelector: '.ph-no-capture, [data-ph-mask]',
        recordCrossOriginIframes: false,
      },
      persistence: 'localStorage+cookie',
      loaded: (ph) => {
        const storedAttribution = getStoredAttributionData();
        const currentUtms = getUtmParams();

        const superProps = {
          ...storedAttribution.initial_utm_params,
          ...currentUtms,
          app_name: 'punk_main_app',
        };

        ph.register(superProps);
      },
    });

    isInitialized = true;
  } catch (error) {
    console.error('[PostHog Frontend] Failed to initialize PostHog:', error);
  }
}

export function trackEvent<E extends AnalyticsEventName>(
  eventName: E,
  properties: EventRegistry[E]
): void {
  if (typeof window === 'undefined') return;

  const enrichedProps = {
    ...getUtmParams(),
    url: typeof window !== 'undefined' ? window.location.href : undefined,
    pathname: typeof window !== 'undefined' ? window.location.pathname : undefined,
    timestamp: new Date().toISOString(),
    ...properties,
  };

  if (POSTHOG_KEY) {
    try {
      posthog.capture(eventName, enrichedProps);
    } catch (err) {
      console.error(`[PostHog] Error capturing ${eventName}:`, err);
    }
  }
}

export function identifyUser(distinctId: string, traits?: Record<string, unknown>): void {
  if (typeof window === 'undefined' || !distinctId) return;

  if (POSTHOG_KEY) {
    try {
      posthog.identify(distinctId, traits);
    } catch (err) {
      console.error('[PostHog] Error identifying user:', err);
    }
  }
}

export function resetUser(): void {
  if (typeof window === 'undefined') return;

  if (POSTHOG_KEY) {
    try {
      posthog.reset();
    } catch (err) {
      console.error('[PostHog] Error resetting user:', err);
    }
  }
}

export function setPersonProperties(properties: Record<string, unknown>): void {
  if (typeof window === 'undefined') return;

  if (POSTHOG_KEY) {
    try {
      posthog.setPersonProperties(properties);
    } catch (err) {
      console.error('[PostHog] Error setting person properties:', err);
    }
  }
}

export function optInTracking(): void {
  if (typeof window === 'undefined' || !POSTHOG_KEY) return;
  try {
    posthog.opt_in_capturing();
  } catch (err) {
    console.error('[PostHog] Error opting in:', err);
  }
}

export function optOutTracking(): void {
  if (typeof window === 'undefined' || !POSTHOG_KEY) return;
  try {
    posthog.opt_out_capturing();
  } catch (err) {
    console.error('[PostHog] Error opting out:', err);
  }
}

export function hasConsented(): boolean {
  if (typeof window === 'undefined' || !POSTHOG_KEY) return true;
  return posthog.has_opted_in_capturing();
}

export { posthog };
