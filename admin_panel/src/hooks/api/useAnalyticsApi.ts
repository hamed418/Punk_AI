import { useQuery, keepPreviousData } from '@tanstack/react-query';
import analyticsApi from '@/api/analytics';

// ── Query Keys ────────────────────────────────────────────────────────────
export const ANALYTICS_QUERY_KEY = {
  all: ['adminAnalytics'] as const,
  overview: () => ['adminAnalytics', 'overview'] as const,
  velocity: (timeframe: string) => ['adminAnalytics', 'velocity', timeframe] as const,
  activityFeed: () => ['adminAnalytics', 'activityFeed'] as const,
  recentCampaigns: (search?: string) => ['adminAnalytics', 'recentCampaigns', search] as const,
};

// ── Hooks ─────────────────────────────────────────────────────────────────

/**
 * High-level overview KPI metrics for the analytics cards.
 */
export const useAnalyticsOverview = () => {
  return useQuery({
    queryKey: ANALYTICS_QUERY_KEY.overview(),
    queryFn: analyticsApi.getOverview,
    staleTime: 60 * 1000,
    retry: 1,
  });
};

/**
 * Performance velocity chart data (daily, weekly, monthly).
 */
export const useAnalyticsVelocity = (timeframe: 'daily' | 'weekly' | 'monthly' = 'daily') => {
  return useQuery({
    queryKey: ANALYTICS_QUERY_KEY.velocity(timeframe),
    queryFn: () => analyticsApi.getVelocity(timeframe),
    placeholderData: keepPreviousData,
    staleTime: 60 * 1000,
    retry: 1,
  });
};

/**
 * Live activity and event feed.
 */
export const useAnalyticsActivityFeed = (limit: number = 10) => {
  return useQuery({
    queryKey: ANALYTICS_QUERY_KEY.activityFeed(),
    queryFn: () => analyticsApi.getActivityFeed(limit),
    staleTime: 30 * 1000,
    refetchInterval: 30 * 1000, // auto-refresh feed every 30s
    retry: 1,
  });
};

/**
 * Recent campaigns list across all users.
 */
export const useAnalyticsRecentCampaigns = (search?: string) => {
  return useQuery({
    queryKey: ANALYTICS_QUERY_KEY.recentCampaigns(search),
    queryFn: () => analyticsApi.getRecentCampaigns(10, search),
    placeholderData: keepPreviousData,
    staleTime: 30 * 1000,
    retry: 1,
  });
};
