export interface CampaignResponse {
  id: string;
  name: string;
  platform: string;
  status: string;
  campaign_plan?: Record<string, unknown> | null;
  daily_budget_usd?: number | null;
  monthly_budget_usd?: number | null;
  impressions: number;
  clicks: number;
  conversions: number;
  spend_usd?: number | null;
  roas?: number | null;
  cpa_usd?: number | null;
  approved_by_user: boolean;
  approved_at?: string | null;
  created_at: string;
  // Meta's id for the PRIMARY campaign. An app plan publishes one campaign per
  // store, so this is not all of them — the review read resolves the rest on the
  // server from Punk's own id.
  ext_campaign_id?: string | null;
}

export interface CampaignListResponse {
  results: CampaignResponse[];
  total: number;
  page: number;
  page_size: number;
}
