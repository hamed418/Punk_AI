import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import usersApi, { type UserListParams, type UserRole } from '@/api/users';

// ── Query Keys ────────────────────────────────────────────────────────────
export const USERS_QUERY_KEY = {
  all: ['adminUsers'] as const,
  list: (params: UserListParams) => ['adminUsers', 'list', params] as const,
  stats: () => ['adminUsers', 'stats'] as const,
  details: (id: string) => ['adminUsers', 'details', id] as const,
};

// ── Hooks ─────────────────────────────────────────────────────────────────

/**
 * Paginated user list. Keeps previous data while fetching next page.
 */
export const useUsersList = (params: UserListParams = {}) => {
  return useQuery({
    queryKey: USERS_QUERY_KEY.list(params),
    queryFn: () => usersApi.list(params),
    placeholderData: keepPreviousData,
    staleTime: 30 * 1000, // 30s — fresh enough for a list
    retry: 1,
  });
};

/**
 * Overview card stats (total, active, new this month, suspended, plan breakdown).
 */
export const useUsersStats = () => {
  return useQuery({
    queryKey: USERS_QUERY_KEY.stats(),
    queryFn: usersApi.stats,
    staleTime: 60 * 1000, // 1 min — counts change slowly
    retry: 1,
  });
};

/**
 * Full user details for the drawer.
 */
export const useUserDetails = (userId: string | null) => {
  return useQuery({
    queryKey: USERS_QUERY_KEY.details(userId ?? ''),
    queryFn: () => usersApi.details(userId!),
    enabled: !!userId,
    staleTime: 30 * 1000,
    retry: 1,
  });
};

/**
 * Update user status (activate / deactivate).
 */
export const useUpdateUserStatus = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, is_active }: { userId: string; is_active: boolean }) =>
      usersApi.updateStatus(userId, is_active),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY.all });
    },
  });
};

/**
 * Update user role.
 */
export const useUpdateUserRole = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: UserRole }) =>
      usersApi.updateRole(userId, role),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY.all });
    },
  });
};

/**
 * Update user email verification status.
 */
export const useUpdateUserVerification = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, is_verified }: { userId: string; is_verified: boolean }) =>
      usersApi.updateVerification(userId, is_verified),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY.all });
    },
  });
};
