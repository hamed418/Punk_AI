import { apiFetch } from '../fetcher';
import { CampaignListResponse, CampaignResponse } from '../../types/campaigns.dto';
import type { MetaRemediation } from '../../types/chat';

export const campaignsApi = {
  getCampaigns: () => {
    return apiFetch<CampaignListResponse>('/campaigns', {
      method: 'GET',
      next: { tags: ['campaigns-list'] },
    });
  },
  getCampaign: (id: string) => {
    return apiFetch<CampaignResponse>(`/campaigns/${id}`, {
      method: 'GET',
    });
  },
  // What Meta's ad review has done to the campaign's ads — in review, or rejected
  // and why. Keyed on Punk's id; the server resolves every Meta campaign id.
  getCampaignReview: (id: string) => {
    return apiFetch<MetaRemediation[]>(`/campaigns/${id}/review`, {
      method: 'GET',
      cache: 'no-store',
    });
  },
  syncMetaCampaigns: () => {
    return apiFetch('/campaigns/meta/list', {
      method: 'GET',
    });
  },
};
