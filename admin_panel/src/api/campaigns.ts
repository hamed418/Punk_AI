import api from './client';

export type CampaignStatus = 'draft' | 'pending_approval' | 'approved' | 'published' | 'archived';
export type AdPlatform = 'meta' | 'google' | 'both';

export interface AdminCampaignListItem {
  id: string;
  name: string;
  platform: AdPlatform;
  status: CampaignStatus;
  user_id: string;
  user_email: string | null;
  user_name: string | null;
  daily_budget_usd: number | null;
  monthly_budget_usd: number | null;
  spend_usd: number;
  impressions: number;
  clicks: number;
  conversions: number;
  ctr: number;
  roas: number | null;
  cpa_usd: number | null;
  start_date: string | null;
  end_date: string | null;
  created_at: string;
  updated_at: string | null;
  campaign_plan: Record<string, any> | null;
}

export interface PaginatedCampaigns {
  total: number;
  page: number;
  limit: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
  data: AdminCampaignListItem[];
}

export interface CampaignStats {
  total_campaigns: number;
  active_campaigns: number;
  avg_ctr: number;
  total_spend: number;
  avg_roas: number;
  new_this_week: number;
  status_breakdown: Record<string, number>;
  platform_breakdown: Record<string, number>;
}

export interface CampaignListParams {
  page?: number;
  limit?: number;
  search?: string;
  status?: string;
  platform?: string;
}

export const campaignsApi = {
  /**
   * Paginated admin campaigns list with joined user info and performance metrics.
   */
  list: (params: CampaignListParams = {}) => {
    const qs = new URLSearchParams();
    if (params.page) qs.set('page', String(params.page));
    if (params.limit) qs.set('limit', String(params.limit));
    if (params.search) qs.set('search', params.search);
    if (params.status && params.status !== 'all') qs.set('status', params.status);
    if (params.platform && params.platform !== 'all') qs.set('platform', params.platform);
    return api.get<PaginatedCampaigns>(`/campaigns/admin/list?${qs.toString()}`);
  },

  /**
   * Aggregate statistics for overview cards (total, active, spend, CTR, ROAS, trends).
   */
  stats: () => api.get<CampaignStats>('/campaigns/admin/stats'),

  /**
   * Single campaign full details for drawer.
   */
  details: (campaignId: string) =>
    api.get<AdminCampaignListItem>(`/campaigns/admin/${campaignId}`),
};

export default campaignsApi;