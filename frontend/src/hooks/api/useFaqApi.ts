import { useQuery } from '@tanstack/react-query';
import { getFaqCategoriesAction, getFaqsAction } from '../../actions/faq.actions';
import { GetFaqsQuery } from '../../lib/api/faq';

export const useGetFaqCategories = (query?: GetFaqsQuery) => {
  return useQuery({
    queryKey: ['faq-categories', query],
    queryFn: async () => {
      const result = await getFaqCategoriesAction(query);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
  });
};

export const useGetFaqs = (query?: GetFaqsQuery) => {
  return useQuery({
    queryKey: ['faqs', query],
    queryFn: async () => {
      const result = await getFaqsAction(query);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
  });
};
