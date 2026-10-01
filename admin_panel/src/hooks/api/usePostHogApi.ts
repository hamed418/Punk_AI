import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import postHogApi, {
  getPostHogConfig,
  savePostHogConfig,
} from '@/api/posthog';
import type { PostHogFilterParams, PostHogConfig, PostHogApiTestParams } from '@/api/posthog';

export const POSTHOG_QUERY_KEYS = {
  events: (params?: PostHogFilterParams) => ['posthog', 'events', params] as const,
  stats: (params?: { date_from?: string; date_to?: string }) => ['posthog', 'stats', params] as const,
  funnel: (params?: { date_from?: string; date_to?: string }) => ['posthog', 'funnel', params] as const,
  users: (params?: { date_from?: string; date_to?: string }) => ['posthog', 'identified-users', params] as const,
  dashboards: () => ['posthog', 'dashboards'] as const,
  userJourney: (distinctId: string | null) => ['posthog', 'user-journey', distinctId] as const,
  config: () => ['posthog', 'config'] as const,
};

/**
 * Fetch PostHog events with API-side pagination and optional auto-refresh interval
 */
export function usePostHogEvents(
  params: PostHogFilterParams = {},
  options?: { refetchInterval?: number | false }
) {
  return useQuery({
    queryKey: POSTHOG_QUERY_KEYS.events(params),
    queryFn: () => postHogApi.getEvents(params),
    staleTime: 1000 * 5, // 5 seconds
    refetchInterval: options?.refetchInterval ?? 10000,
  });
}

/**
 * Fetch aggregate PostHog stats (total count, active users, top events) filtered by time
 */
export function usePostHogStats(params: { date_from?: string; date_to?: string } = {}) {
  return useQuery({
    queryKey: POSTHOG_QUERY_KEYS.stats(params),
    queryFn: () => postHogApi.getStats(params),
    staleTime: 1000 * 15, // 15 seconds
  });
}

/**
 * Fetch 5-stage user journey funnel & drop-off metrics filtered by time
 */
export function usePostHogFunnel(params: { date_from?: string; date_to?: string } = {}) {
  return useQuery({
    queryKey: POSTHOG_QUERY_KEYS.funnel(params),
    queryFn: () => postHogApi.getFunnelMetrics(params),
    staleTime: 1000 * 15, // 15 seconds
  });
}

/**
 * Fetch all unique identified users active within the given time period
 */
export function usePostHogUsers(params: { date_from?: string; date_to?: string } = {}) {
  return useQuery({
    queryKey: POSTHOG_QUERY_KEYS.users(params),
    queryFn: () => postHogApi.getIdentifiedUsers(params),
    staleTime: 1000 * 15, // 15 seconds
  });
}

/**
 * Fetch project dashboards from PostHog Cloud (https://posthog.com/docs/api/dashboards)
 */
export function usePostHogDashboards() {
  return useQuery({
    queryKey: POSTHOG_QUERY_KEYS.dashboards(),
    queryFn: () => postHogApi.getDashboards(),
    staleTime: 1000 * 60, // 1 minute
  });
}

/**
 * Lazy-load complete humanized user journey timeline for an individual user
 */
export function usePostHogUserJourney(distinctId: string | null) {
  return useQuery({
    queryKey: POSTHOG_QUERY_KEYS.userJourney(distinctId),
    queryFn: () => (distinctId ? postHogApi.getUserJourney(distinctId) : null),
    enabled: Boolean(distinctId),
    staleTime: 1000 * 15, // 15 seconds
  });
}

/**
 * Hook to retrieve active PostHog configuration
 */
export function usePostHogConfig() {
  return useQuery({
    queryKey: POSTHOG_QUERY_KEYS.config(),
    queryFn: () => getPostHogConfig(),
    staleTime: Infinity,
  });
}

/**
 * Mutation to update PostHog configuration and invalidate queries
 */
export function useUpdatePostHogConfig() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (config: Partial<PostHogConfig>) => {
      const updated = savePostHogConfig(config);
      return updated;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['posthog'] });
    },
  });
}

/**
 * Mutation to execute an arbitrary PostHog API test endpoint
 */
export function usePostHogApiTest() {
  return useMutation({
    mutationFn: (params: PostHogApiTestParams) => postHogApi.executeQueryEndpoint(params),
  });
}

