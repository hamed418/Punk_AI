import api from './client';

export interface AnalyticsOverview {
  total_users: number;
  users_change: string;
  users_is_positive: boolean;
  active_campaigns: number;
  campaigns_change: string;
  campaigns_is_positive: boolean;
  ai_chats_today: number;
  chats_change: string;
  chats_is_positive: boolean;
  mrr: number;
  mrr_change: string;
  mrr_is_positive: boolean;
}

export interface VelocityDataPoint {
  name: string;
  campaigns: number;
  reach: number;
  conv: number;
  benchmark: number;
}

export interface VelocityResponse {
  timeframe: 'daily' | 'weekly' | 'monthly';
  data: VelocityDataPoint[];
}

export interface ActivityFeedItem {
  id: string;
  accent: string;
  title: string;
  desc: string;
  time: string;
  badge: string;
}

export interface RecentCampaignItem {
  id: string;
  name: string;
  platform: string;
  dateRange: string;
  manager: string;
  userEmail: string;
  userAvatar: string;
  ctr: string;
  spend: string;
  roas: string;
  status: string;
  daily_budget?: string;
  impressions?: number;
  clicks?: number;
  conversions?: number;
}

export const analyticsApi = {
  /**
   * High-level overview metrics for stat cards (Total Users, Active Campaigns, AI Chats, MRR).
   */
  getOverview: () => api.get<AnalyticsOverview>('/analytics/overview'),

  /**
   * Time-series performance velocity chart data (daily, weekly, monthly).
   */
  getVelocity: (timeframe: 'daily' | 'weekly' | 'monthly' = 'daily') =>
    api.get<VelocityResponse>(`/analytics/velocity?timeframe=${timeframe}`),

  /**
   * Live activity and event feed.
   */
  getActivityFeed: (limit: number = 10) =>
    api.get<{ items: ActivityFeedItem[] }>(`/analytics/activity-feed?limit=${limit}`),

  /**
   * Recent campaigns across all users with performance metrics.
   */
  getRecentCampaigns: (limit: number = 10, search?: string) => {
    const qs = new URLSearchParams();
    qs.set('limit', String(limit));
    if (search) qs.set('search', search);
    return api.get<{ campaigns: RecentCampaignItem[] }>(`/analytics/recent-campaigns?${qs.toString()}`);
  },
};

export default analyticsApi;
