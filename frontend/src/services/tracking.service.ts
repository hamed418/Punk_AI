import { apiFetch } from '@/lib/fetcher';
import type {
  TrackingDatasets,
  TrackingHealth,
  TrackingMethod,
  TrackingSnippet,
} from '@/types/chat';

/**
 * Conversion tracking for the connected Meta account.
 *
 * The dataset these read is the advertiser's own, in their own business — Punk
 * owns none. `health` is the honest answer to "is this measuring anything?", and
 * `snippet` is what they paste into their site.
 */
export const trackingService = {
  health: async (): Promise<TrackingHealth> =>
    apiFetch<TrackingHealth>('/tracking/health', { method: 'GET' }),

  // No event name means "the one this account's campaigns optimize for" — the
  // server knows it, and a fixed 'Purchase' here would override that with the
  // one event a Leads advertiser does not use.
  snippet: async (eventName = ''): Promise<TrackingSnippet> => {
    const query = eventName
      ? `?${new URLSearchParams({ event_name: eventName })}`
      : '';
    return apiFetch<TrackingSnippet>(`/tracking/snippet${query}`, {
      method: 'GET',
    });
  },

  // Read live from Meta, not off the stored row: whoever opens the picker is
  // usually the person who just made a Pixel in Events Manager, and a cached list
  // is exactly the list without it.
  datasets: async (): Promise<TrackingDatasets> =>
    apiFetch<TrackingDatasets>('/tracking/datasets', { method: 'GET' }),

  // Refused server-side unless the ad account can actually write to it — an id it
  // cannot reach publishes ad sets optimizing toward an event that never fires.
  setDataset: async (datasetId: string): Promise<{ dataset_id: string }> =>
    apiFetch<{ dataset_id: string }>('/tracking/dataset', {
      method: 'POST',
      body: JSON.stringify({ dataset_id: datasetId }),
    }),

  // How conversions reach Meta. Publish derives this and an express Sales run
  // lands on 'pixel_only', whose own instructions tell the advertiser to switch to
  // server events — this is that switch. The ingest key is NOT rotated by it.
  setMethod: async (method: TrackingMethod): Promise<{ method: string }> =>
    apiFetch<{ method: string }>('/tracking/method', {
      method: 'POST',
      body: JSON.stringify({ method }),
    }),

  // A system user token the advertiser generated in THEIR own Business Settings.
  // Optional: without one, server events ride the user's OAuth token, which
  // expires — the whole reason the tracking_token_expired fix-it card exists.
  // Sending an empty string clears it. Never echoed back.
  setSystemToken: async (token: string): Promise<{ configured: boolean }> =>
    apiFetch<{ configured: boolean }>('/tracking/token', {
      method: 'POST',
      body: JSON.stringify({ token }),
    }),

  // Issues a new ingest key and invalidates the old one — this BREAKS whatever is
  // currently posting conversions until the new key is installed, which is why it
  // is only ever called from an explicit user action.
  rotateKey: async (): Promise<{ ingest_key: string }> =>
    apiFetch<{ ingest_key: string }>('/tracking/key/rotate', { method: 'POST' }),

  // Define a conversion from a page URL instead of from event code.
  //
  // For the most common broken setup there is: base pixel installed site-wide,
  // no event code on the thank-you page, campaign optimizing toward an event
  // that will never fire. This turns the PageViews Meta already receives into
  // the conversion — no developer, no deploy.
  createCustomConversion: async (payload: {
    name: string;
    url_contains: string;
    custom_event_type: string;
  }): Promise<{ id: string; name: string; custom_event_type: string }> =>
    apiFetch<{ id: string; name: string; custom_event_type: string }>(
      '/tracking/custom-conversion',
      { method: 'POST', body: JSON.stringify(payload) }
    ),
};
