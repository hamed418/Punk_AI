'use server';

import { adsService } from '@/services/ads.service';
import type {
  AdPreview,
  CampaignTreeAdSet,
  EditorAudience,
  LeadFormDraft,
  PageObject,
  PageObjectKind,
  TargetingSuggestion,
} from '@/types/chat';

export async function listAdPreviewsAction(adId: string): Promise<AdPreview[]> {
  if (!adId) return [];
  try {
    return await adsService.listAdPreviews(adId);
  } catch (err) {
    console.error('ad preview lookup failed:', err);
    return [];
  }
}

export async function listPageObjectsAction(
  pageId: string,
  kind: PageObjectKind = 'post'
): Promise<PageObject[]> {
  if (!pageId) return [];
  try {
    return await adsService.listPageObjects(pageId, kind);
  } catch (err) {
    console.error('page objects lookup failed:', err);
    return [];
  }
}

export async function listAdPostsAction(): Promise<PageObject[]> {
  try {
    return await adsService.listAdPosts();
  } catch (err) {
    console.error('ad posts lookup failed:', err);
    return [];
  }
}

export async function searchTargetingAction(
  q: string,
  kind: 'interests' | 'behaviors' = 'interests'
): Promise<TargetingSuggestion[]> {
  const query = (q || '').trim();
  if (!query) return [];
  try {
    return await adsService.searchTargeting(query, kind);
  } catch (err) {
    console.error('targeting search failed:', err);
    return [];
  }
}

export async function suggestTargetingAction(
  sessionId: string,
  seeds: string
): Promise<TargetingSuggestion[]> {
  try {
    return await adsService.suggestTargeting(sessionId || '', seeds || '');
  } catch (err) {
    console.error('targeting suggest failed:', err);
    return [];
  }
}

export async function listCampaignTreeAction(
  campaignId: string
): Promise<CampaignTreeAdSet[]> {
  if (!campaignId) return [];
  try {
    return await adsService.listCampaignTree(campaignId);
  } catch (err) {
    console.error('campaign tree lookup failed:', err);
    return [];
  }
}

/**
 * Create an Instant Form on the user's Page.
 *
 * The lookups above swallow their errors because an empty picker beats a broken
 * editor. This one must not: a form the user believes exists but does not takes
 * the whole campaign down at publish, so the failure is returned for display.
 */
export async function createLeadFormAction(
  pageId: string,
  form: LeadFormDraft
): Promise<{ id: string; name: string } | { error: string }> {
  if (!pageId) return { error: 'No Facebook Page is connected to this campaign.' };
  try {
    return await adsService.createLeadForm(pageId, form);
  } catch (err) {
    console.error('lead form creation failed:', err);
    return {
      error: err instanceof Error ? err.message : 'Could not create the form on Meta.',
    };
  }
}

/**
 * The ad account's custom audiences, for the editor's include/exclude pickers.
 *
 * Swallows its error like the other lookups: an empty picker is a state the
 * editor already handles, and the catalog copy from connect time is still there.
 */
export async function listAudiencesAction(): Promise<EditorAudience[]> {
  try {
    return await adsService.listAudiences();
  } catch (err) {
    console.error('audience lookup failed:', err);
    return [];
  }
}

/**
 * Build an audience from a dataset the ad account can already write to.
 *
 * Does not swallow: an audience the user believes exists but does not shows up
 * as an ad set delivering to nobody, days later.
 */
export async function createAudienceAction(payload: {
  name: string;
  dataset_id: string;
  event_name?: string;
  retention_days?: number;
}): Promise<EditorAudience | { error: string }> {
  if (!payload.dataset_id) {
    return { error: 'Pick a dataset first — an audience is built from its events.' };
  }
  try {
    return await adsService.createAudience(payload);
  } catch (err) {
    console.error('audience creation failed:', err);
    return {
      error: err instanceof Error ? err.message : 'Could not create the audience on Meta.',
    };
  }
}

/** Upload a customer list into an audience. Same no-swallow rule as above. */
export async function addAudienceUsersAction(
  audienceId: string,
  schemaFields: string[],
  rows: string[][]
): Promise<{ uploaded: number } | { error: string }> {
  if (!rows.length) return { error: 'Nothing to upload.' };
  try {
    return await adsService.addAudienceUsers(audienceId, schemaFields, rows);
  } catch (err) {
    console.error('audience upload failed:', err);
    return {
      error: err instanceof Error ? err.message : 'Could not upload the list to Meta.',
    };
  }
}
