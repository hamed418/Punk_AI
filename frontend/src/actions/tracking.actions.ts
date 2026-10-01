'use server';

import { trackingService } from '@/services/tracking.service';
import type {
  TrackingDatasets,
  TrackingHealth,
  TrackingMethod,
  TrackingSnippet,
} from '@/types/chat';

// Same degrade-to-empty contract as the ads read actions: a diagnostic that
// cannot be read must not break the settings page it sits on.
export async function trackingHealthAction(): Promise<TrackingHealth | null> {
  try {
    return await trackingService.health();
  } catch (err) {
    console.error('tracking health lookup failed:', err);
    return null;
  }
}

export async function trackingSnippetAction(
  // Empty means "whatever this account optimizes for" — see tracking.service.
  eventName = ''
): Promise<TrackingSnippet | null> {
  try {
    return await trackingService.snippet(eventName);
  } catch (err) {
    console.error('tracking snippet lookup failed:', err);
    return null;
  }
}

// A write the user asked for, so a failure is surfaced rather than swallowed:
// silently keeping the old credential would leave them believing the long-lived
// token is in place when it is not.
export async function setTrackingTokenAction(token: string): Promise<boolean> {
  const res = await trackingService.setSystemToken(token);
  return res.configured;
}

// Rotation is a write the user asked for, so a failure is surfaced rather than
// swallowed — silently keeping the old key would leave them installing one that
// does not work.
export async function rotateTrackingKeyAction(): Promise<string> {
  const res = await trackingService.rotateKey();
  return res.ingest_key;
}

// A read, so it degrades — an unreachable dataset list must not break the settings
// page, it only costs the user the picker.
export async function trackingDatasetsAction(): Promise<TrackingDatasets | null> {
  try {
    return await trackingService.datasets();
  } catch (err) {
    console.error('tracking dataset lookup failed:', err);
    return null;
  }
}

// Writes the user asked for, so failures surface. Silently keeping the old value
// would leave them believing a dataset is attached, or that server events are on,
// when neither is true.
export async function setTrackingDatasetAction(
  datasetId: string
): Promise<string> {
  const res = await trackingService.setDataset(datasetId);
  return res.dataset_id;
}

export async function setTrackingMethodAction(
  method: TrackingMethod
): Promise<string> {
  const res = await trackingService.setMethod(method);
  return res.method;
}

/**
 * Turn a page URL into a conversion Meta can optimize toward.
 *
 * Does not swallow its error, unlike the reads above: a conversion the user
 * believes exists but does not leaves the campaign optimizing against nothing.
 */
export async function createCustomConversionAction(payload: {
  name: string;
  url_contains: string;
  custom_event_type: string;
}): Promise<{ id: string; name: string } | { error: string }> {
  try {
    return await trackingService.createCustomConversion(payload);
  } catch (err) {
    console.error('custom conversion creation failed:', err);
    return {
      error:
        err instanceof Error
          ? err.message
          : 'Could not create the conversion on Meta.',
    };
  }
}
