/**
 * UTM & Attribution tracking utilities for Frontend App
 */

export interface UtmParams {
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
  utm_term?: string;
  utm_content?: string;
  gclid?: string;
  fbclid?: string;
  ttclid?: string;
  ref?: string;
}

const STORAGE_KEY_INITIAL_UTM = 'punk_initial_utm';
const STORAGE_KEY_INITIAL_REFERRER = 'punk_initial_referrer';
const STORAGE_KEY_INITIAL_LANDING = 'punk_initial_landing';

export function getUtmParams(search?: string): UtmParams {
  if (typeof window === 'undefined') return {};

  const query = search !== undefined ? search : window.location.search;
  const params = new URLSearchParams(query);
  const result: UtmParams = {};

  const utmKeys: Array<keyof UtmParams> = [
    'utm_source',
    'utm_medium',
    'utm_campaign',
    'utm_term',
    'utm_content',
    'gclid',
    'fbclid',
    'ttclid',
    'ref',
  ];

  for (const key of utmKeys) {
    const value = params.get(key);
    if (value) {
      result[key] = value;
    }
  }

  return result;
}

export function persistAttributionData(): void {
  if (typeof window === 'undefined') return;

  try {
    const utms = getUtmParams();
    const hasUtms = Object.keys(utms).length > 0;

    if (!sessionStorage.getItem(STORAGE_KEY_INITIAL_LANDING)) {
      sessionStorage.setItem(STORAGE_KEY_INITIAL_LANDING, window.location.href);
    }

    if (!sessionStorage.getItem(STORAGE_KEY_INITIAL_REFERRER) && document.referrer) {
      sessionStorage.setItem(STORAGE_KEY_INITIAL_REFERRER, document.referrer);
    }

    if (hasUtms && !sessionStorage.getItem(STORAGE_KEY_INITIAL_UTM)) {
      sessionStorage.setItem(STORAGE_KEY_INITIAL_UTM, JSON.stringify(utms));
    }
  } catch {
    // Gracefully handle storage exceptions
  }
}

export function getStoredAttributionData(): {
  initial_landing_page?: string;
  initial_referrer?: string;
  initial_utm_params?: UtmParams;
} {
  if (typeof window === 'undefined') return {};

  try {
    const landing = sessionStorage.getItem(STORAGE_KEY_INITIAL_LANDING) || undefined;
    const referrer = sessionStorage.getItem(STORAGE_KEY_INITIAL_REFERRER) || undefined;
    const utmRaw = sessionStorage.getItem(STORAGE_KEY_INITIAL_UTM);
    const utmParams = utmRaw ? (JSON.parse(utmRaw) as UtmParams) : undefined;

    return {
      initial_landing_page: landing,
      initial_referrer: referrer,
      initial_utm_params: utmParams,
    };
  } catch {
    return {};
  }
}

export function sanitizeEmailDomain(email?: string): string | undefined {
  if (!email || !email.includes('@')) return undefined;
  const parts = email.split('@');
  return parts.length > 1 ? parts[1].toLowerCase() : undefined;
}
