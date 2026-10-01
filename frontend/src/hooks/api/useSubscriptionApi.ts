import { useQuery, useMutation } from '@tanstack/react-query';
import { subscriptionApi } from '../../lib/api/subscription';

export const useUserSubscriptions = () => {
  return useQuery({
    queryKey: ['user-subscriptions'],
    queryFn: async () => {
      const data = await subscriptionApi.getUserSubscriptions();
      return data;
    },
  });
};
