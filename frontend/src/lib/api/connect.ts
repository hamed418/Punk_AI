import { apiFetch } from '../fetcher';
import type { MetaRemediation } from '@/types/chat';

export interface MetaConnectionResponse {
  authorization_url: string;
}

export interface MetaLeadForm {
  id: string;
  name: string | null;
  status: string | null;
  page_id: string;
  page_name: string;
}

export interface LeadDelivery {
  page_id: string;
  page_name: string;
  // Meta's own answer. null = Punk could not ask (e.g. pages_manage_metadata was not
  // granted) — never "off".
  subscribed: boolean | null;
  // Whether this is the Page the selected ad account receives leads for.
  routed: boolean;
  // Only set by a failed connect.
  remediation: MetaRemediation[];
}

export interface MetaLead {
  id: string;
  created_time: string | null;
  // Flat {question: answer}, as the backend flattens Meta's field_data.
  fields: Record<string, string | null>;
}

export interface AdPlatformStatus {
  platform: 'google' | 'meta';
  connected: boolean;
  account_id: string | null;
  account_name: string | null;
}

export const connectApi = {
  // `connected` is only true for a token the backend would actually accept
  // (valid + unexpired), so this is safe to poll as "did the OAuth land yet".
  adsStatus: () => {
    return apiFetch<AdPlatformStatus[]>('/ads/status', {
      method: 'GET',
      cache: 'no-store',
    });
  },

  // Everything the connected advertiser still has to do on a Meta screen, in the
  // order to do it. Live Graph reads — not for polling; `adsStatus` is that.
  readiness: () => {
    return apiFetch<MetaRemediation[]>('/ads/readiness', {
      method: 'GET',
      cache: 'no-store',
    });
  },

  // Instant forms on the Pages the user shared, each with its Page.
  leadForms: () => {
    return apiFetch<MetaLeadForm[]>('/ads/lead-forms', {
      method: 'GET',
      cache: 'no-store',
    });
  },

  // A permission failure is a 502 carrying the actionable wording — surfaced, never
  // degraded to an empty table, which would read as "no leads yet".
  formLeads: (formId: string, pageId: string) => {
    const query = new URLSearchParams({ form_id: formId, page_id: pageId });
    return apiFetch<{ results: MetaLead[] }>(`/ads/leads?${query.toString()}`, {
      method: 'GET',
      cache: 'no-store',
    });
  },

  // Per Page: is Meta pushing its leads at Punk, and to the selected ad account?
  leadDelivery: () => {
    return apiFetch<LeadDelivery[]>('/ads/lead-delivery', {
      method: 'GET',
      cache: 'no-store',
    });
  },

  // Subscribe Punk to a Page's leads and route them to the selected ad account.
  connectLeadDelivery: (pageId: string) => {
    return apiFetch<LeadDelivery>('/ads/lead-delivery', {
      method: 'POST',
      body: JSON.stringify({ page_id: pageId }),
      cache: 'no-store',
    });
  },

  metaAdsRegister: () => {
    return apiFetch<MetaConnectionResponse>('/ads/connect/meta', {
      method: 'POST',
      cache: 'no-store',
    });
  },

  metaAdsDisconnect: () => {
    return apiFetch<MetaConnectionResponse>('/ads/disconnect/meta', {
      method: 'DELETE',
      cache: 'no-store',
    });
  },

  metaAdsDisconnectConnection: (tokenId: string) => {
    return apiFetch<{status: string, message: string}>(`/ads/disconnect/connection/${tokenId}`, {
      method: 'DELETE',
      cache: 'no-store',
    });
  },

  removeMetaAdsAccount: (adAccountId: string) => {
    return apiFetch<{status: string, message: string}>(`/ads/accounts/meta/${adAccountId}`, {
      method: 'DELETE',
      cache: 'no-store',
    });
  }
};
