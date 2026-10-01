import { useMutation, useQueryClient } from '@tanstack/react-query';
import { supportApi } from '../../lib/api/support';

export const useCreateSupportTicket = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: FormData) => {
      const result = await supportApi.createTicket(data);
      return result;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['support-tickets'] });
    },
  });
};
