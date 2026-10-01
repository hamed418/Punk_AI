import { useQuery, keepPreviousData } from '@tanstack/react-query';
import campaignsApi, { type CampaignListParams } from '@/api/campaigns';

// ── Query Keys ────────────────────────────────────────────────────────────
export const CAMPAIGNS_QUERY_KEY = {
  all: ['adminCampaigns'] as const,
  list: (params: CampaignListParams) => ['adminCampaigns', 'list', params] as const,
  stats: () => ['adminCampaigns', 'stats'] as const,
  details: (id: string) => ['adminCampaigns', 'details', id] as const,
};

// ── Hooks ─────────────────────────────────────────────────────────────────

/**
 * Paginated campaigns list. Keeps previous data while fetching next page or filter.
 */
export const useCampaignsList = (params: CampaignListParams = {}) => {
  return useQuery({
    queryKey: CAMPAIGNS_QUERY_KEY.list(params),
    queryFn: () => campaignsApi.list(params),
    placeholderData: keepPreviousData,
    staleTime: 30 * 1000,
    retry: 1,
  });
};

/**
 * Overview card stats (total, active, spend, CTR, ROAS, trends).
 */
export const useCampaignsStats = () => {
  return useQuery({
    queryKey: CAMPAIGNS_QUERY_KEY.stats(),
    queryFn: campaignsApi.stats,
    staleTime: 60 * 1000,
    retry: 1,
  });
};

/**
 * Single campaign details for the drawer.
 */
export const useCampaignDetails = (campaignId: string | null) => {
  return useQuery({
    queryKey: CAMPAIGNS_QUERY_KEY.details(campaignId ?? ''),
    queryFn: () => campaignsApi.details(campaignId!),
    enabled: !!campaignId,
    staleTime: 30 * 1000,
    retry: 1,
  });
};
