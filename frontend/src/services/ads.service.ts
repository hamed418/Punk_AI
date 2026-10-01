import { apiFetch } from '@/lib/fetcher';
import type {
  AdPreview,
  CampaignTreeAdSet,
  EditorAudience,
  LeadFormDraft,
  PageObject,
  PageObjectKind,
  TargetingSuggestion,
} from '@/types/chat';

export const adsService = {
  /**
   * Typeahead over Meta's detailed-targeting catalog (interests / behaviors)
   * for the campaign editor's flexible_spec field.
   */
  searchTargeting: async (
    q: string,
    kind: 'interests' | 'behaviors' = 'interests',
    limit = 25
  ): Promise<TargetingSuggestion[]> => {
    const params = new URLSearchParams({ q, kind, limit: String(limit) });
    const res = await apiFetch<{ results: TargetingSuggestion[] }>(
      `/ads/targeting-search?${params.toString()}`,
      { method: 'GET' }
    );
    return res.results || [];
  },

  /**
   * Autofill options for the same field — seeded by the interests already
   * picked, or by the session's business context when none are.
   */
  suggestTargeting: async (
    sessionId: string,
    seeds: string
  ): Promise<TargetingSuggestion[]> => {
    const params = new URLSearchParams({ session_id: sessionId, seeds });
    const res = await apiFetch<{ results: TargetingSuggestion[] }>(
      `/ads/targeting-suggest?${params.toString()}`,
      { method: 'GET' }
    );
    return res.results || [];
  },

  // Boostable Page objects for the campaign editor's post picker. Engagement's
  // "On your post / video / event" ads promote something that already exists on
  // the Page, so the user picks it rather than composing new copy.
  listPageObjects: async (
    pageId: string,
    kind: PageObjectKind = 'post',
    limit = 25
  ): Promise<PageObject[]> => {
    const params = new URLSearchParams({ page_id: pageId, kind, limit: String(limit) });
    const res = await apiFetch<{ results: PageObject[] }>(
      `/ads/page-objects?${params.toString()}`,
      { method: 'GET' }
    );
    return res.results || [];
  },

  // The posts behind ads this account already ran — the picker's "Past ads"
  // tab. Account scoped, so unlike listPageObjects there is no page to name.
  listAdPosts: async (limit = 25): Promise<PageObject[]> => {
    const res = await apiFetch<{ results: PageObject[] }>(
      `/ads/ad-posts?limit=${limit}`,
      { method: 'GET' }
    );
    return res.results || [];
  },

  // The ad sets and ads of one previous campaign, so "start from a previous
  // campaign" can copy part of it rather than all of it. The editor's catalog
  // only carries the campaign list, so the structure is read on demand.
  listCampaignTree: async (campaignId: string): Promise<CampaignTreeAdSet[]> => {
    const params = new URLSearchParams({ campaign_id: campaignId });
    const res = await apiFetch<{ adsets: CampaignTreeAdSet[] }>(
      `/ads/campaign-tree?${params.toString()}`,
      { method: 'GET' }
    );
    return res.adsets || [];
  },

  // Meta's own rendering of a published ad, one entry per placement. Read on
  // demand rather than shipped with the pending_action: the preview iframe URLs
  // Meta hands back are short-lived, and the Preview & Publish screen can sit on
  // a user's monitor for a while before they open it.
  listAdPreviews: async (adId: string): Promise<AdPreview[]> => {
    const params = new URLSearchParams({ ad_id: adId });
    const res = await apiFetch<{ previews: AdPreview[] }>(
      `/ads/ad-previews?${params.toString()}`,
      // One request here is seven Graph round-trips server-side, each with its
      // own retry — the 10s default aborts a call that was going to succeed, and
      // an abort is indistinguishable downstream from "Meta rendered nothing".
      { method: 'GET', timeout: 30000 }
    );
    return res.previews || [];
  },

  // Create an Instant Form on the Page now, rather than carrying it on the plan
  // as a lead_form_draft for publish to create. Same body either way.
  createLeadForm: async (
    pageId: string,
    form: LeadFormDraft
  ): Promise<{ id: string; name: string }> =>
    apiFetch<{ id: string; name: string }>('/ads/lead-forms', {
      method: 'POST',
      body: JSON.stringify({ page_id: pageId, form }),
    }),

  /**
   * The ad account's custom audiences, read live.
   *
   * The session catalog already carries a copy from connect time; this is for
   * after something changes it — a user who just built an audience here, or one
   * they made in Ads Manager with the editor still open.
   */
  listAudiences: async (): Promise<EditorAudience[]> =>
    apiFetch<EditorAudience[]>('/ads/audiences', { method: 'GET' }),

  /**
   * Build an audience from the people the advertiser's dataset has seen.
   *
   * `eventName` empty means everyone it saw; a name means the people who fired
   * that event, which is how the converters list worth excluding gets built.
   */
  createAudience: async (payload: {
    name: string;
    dataset_id: string;
    event_name?: string;
    retention_days?: number;
  }): Promise<EditorAudience> =>
    apiFetch<EditorAudience>('/ads/audiences', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /**
   * Add the advertiser's own customer list to an audience.
   *
   * Identifiers go up raw and are normalized and hashed server-side before they
   * reach Meta — the hashing rules are Meta's, and a digest built the wrong way
   * is accepted, matches nobody, and reports success.
   */
  addAudienceUsers: async (
    audienceId: string,
    schemaFields: string[],
    rows: string[][]
  ): Promise<{ uploaded: number }> =>
    apiFetch<{ uploaded: number }>(`/ads/audiences/${audienceId}/users`, {
      method: 'POST',
      body: JSON.stringify({ schema_fields: schemaFields, rows }),
    }),
};
