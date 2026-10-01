import posthog from 'posthog-js';
import { EventRegistry, AnalyticsEventName } from './events';
import { getUtmParams, persistAttributionData, getStoredAttributionData } from './utm';

let isInitialized = false;

export const POSTHOG_KEY = process.env.NEXT_PUBLIC_POSTHOG_KEY || '';
export const POSTHOG_HOST = process.env.NEXT_PUBLIC_POSTHOG_HOST || 'https://us.i.posthog.com';
export const ROOT_DOMAIN = process.env.NEXT_PUBLIC_ROOT_DOMAIN || '';
export const CONSENT_REQUIRED = process.env.NEXT_PUBLIC_CONSENT_REQUIRED === 'true';

/**
 * Initializes the PostHog client singleton with best practices.
 */
export function initPostHog(): void {
  if (typeof window === 'undefined' || isInitialized) return;

  if (!POSTHOG_KEY) {
    if (process.env.NODE_ENV !== 'production') {
      console.warn('[PostHog] NEXT_PUBLIC_POSTHOG_KEY is not defined. Analytics tracking is running in mock mode.');
    }
    return;
  }

  try {
    persistAttributionData();

    posthog.init(POSTHOG_KEY, {
      api_host: POSTHOG_HOST,
      capture_pageview: false, // Handled explicitly in PostHogPageView to support Next.js App Router
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
          app_name: 'punk_landing',
          app_version: '4.0.0',
        };

        ph.register(superProps);
      },
    });

    isInitialized = true;
  } catch (error) {
    console.error('[PostHog] Failed to initialize PostHog:', error);
  }
}

/**
 * Type-safe event tracking helper.
 */
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

  if (process.env.NODE_ENV !== 'production') {
    console.log(`[PostHog Track] ${eventName}:`, enrichedProps);
  }

  if (POSTHOG_KEY) {
    try {
      posthog.capture(eventName, enrichedProps);
    } catch (err) {
      console.error(`[PostHog] Error capturing ${eventName}:`, err);
    }
  }
}

/**
 * Identifies a user when an email or identifier is supplied.
 */
export function identifyUser(distinctId: string, traits?: Record<string, unknown>): void {
  if (typeof window === 'undefined' || !distinctId) return;

  if (process.env.NODE_ENV !== 'production') {
    console.log(`[PostHog Identify] ${distinctId}`, traits);
  }

  if (POSTHOG_KEY) {
    try {
      posthog.identify(distinctId, traits);
    } catch (err) {
      console.error('[PostHog] Error identifying user:', err);
    }
  }
}

/**
 * Resets user identification on logout or session reset.
 */
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

/**
 * Sets user / person properties.
 */
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

export { posthog };
