import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { supportApi } from '@/api/supportApi';
import type {
  SupportTicketItem,
  SupportListParams,
  SupportUpdatePayload,
} from '@/api/supportApi';
import type { PaginatedResponse } from '@/api/faqApi';

export const SUPPORT_QUERY_KEYS = {
  all: ['adminSupport'] as const,
  tickets: (params?: SupportListParams) => ['adminSupport', 'tickets', params] as const,
  ticket: (id: string) => ['adminSupport', 'ticket', id] as const,
};

export const useAdminSupportTickets = (params?: SupportListParams) => {
  return useQuery({
    queryKey: SUPPORT_QUERY_KEYS.tickets(params),
    queryFn: () => supportApi.getTickets(params),
    placeholderData: keepPreviousData,
    staleTime: 1000 * 30, // 30 seconds
    refetchOnWindowFocus: false,
  });
};

export const useAdminSupportTicket = (id: string | null) => {
  return useQuery({
    queryKey: SUPPORT_QUERY_KEYS.ticket(id ?? ''),
    queryFn: () => supportApi.getTicket(id!),
    enabled: !!id,
    staleTime: 1000 * 30,
    refetchOnWindowFocus: false,
  });
};

export const useAdminUpdateTicket = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: SupportUpdatePayload }) =>
      supportApi.updateTicket(id, payload),
    onSuccess: (updatedTicket: SupportTicketItem) => {
      // Update in queries cache
      queryClient.setQueriesData<PaginatedResponse<SupportTicketItem>>(
        { queryKey: ['adminSupport', 'tickets'] },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            data: old.data.map((item) =>
              item.id === updatedTicket.id ? updatedTicket : item
            ),
          };
        }
      );
      queryClient.invalidateQueries({ queryKey: SUPPORT_QUERY_KEYS.all });
    },
  });
};

export const useAdminDeleteTicket = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => supportApi.deleteTicket(id),
    onSuccess: (_, deletedId) => {
      queryClient.setQueriesData<PaginatedResponse<SupportTicketItem>>(
        { queryKey: ['adminSupport', 'tickets'] },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            total: Math.max(0, old.total - 1),
            data: old.data.filter((item) => item.id !== deletedId),
          };
        }
      );
      queryClient.invalidateQueries({ queryKey: SUPPORT_QUERY_KEYS.all });
    },
  });
};
