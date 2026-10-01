import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { faqApi } from '@/api/faqApi';
import type {
  CreateFAQCategoryPayload,
  UpdateFAQCategoryPayload,
  CreateFAQPayload,
  UpdateFAQPayload,
  CreateLandingFAQPayload,
  UpdateLandingFAQPayload,
  FAQCategoryItem,
  FAQItem,
  LandingFAQItem,
  PaginatedResponse,
} from '@/api/faqApi';

export interface FaqCategoriesParams {
  search?: string;
  type?: string;
  is_active?: boolean;
  page?: number;
  limit?: number;
}

export interface FaqsParams {
  search?: string;
  category_id?: string;
  is_active?: boolean;
  page?: number;
  limit?: number;
}

export interface LandingFaqsParams {
  search?: string;
  is_active?: boolean;
  page?: number;
  limit?: number;
}

export const FAQ_QUERY_KEYS = {
  all: ['faq'] as const,
  categories: (params?: FaqCategoriesParams) => ['faq', 'categories', params] as const,
  faqs: (params?: FaqsParams) => ['faq', 'items', params] as const,
  landingFaqs: (params?: LandingFaqsParams) => ['faq', 'landing-items', params] as const,
};

// ── Categories Hooks ─────────────────────────────────────────────────────────

export const useFaqCategories = (params?: FaqCategoriesParams) => {
  return useQuery({
    queryKey: FAQ_QUERY_KEYS.categories(params),
    queryFn: () => faqApi.getCategories(params),
    staleTime: 1000 * 60 * 10, // 10 minutes
    refetchOnWindowFocus: false,
  });
};

export const useCreateFaqCategory = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateFAQCategoryPayload) => faqApi.createCategory(payload),
    onSuccess: (newCat: FAQCategoryItem) => {
      queryClient.setQueriesData<PaginatedResponse<FAQCategoryItem>>(
        { queryKey: ['faq', 'categories'] },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            total: old.total + 1,
            data: [...old.data, newCat],
          };
        }
      );
      queryClient.invalidateQueries({ queryKey: FAQ_QUERY_KEYS.all });
    },
  });
};

export const useUpdateFaqCategory = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateFAQCategoryPayload }) =>
      faqApi.updateCategory(id, payload),
    onSuccess: (updatedCat: FAQCategoryItem) => {
      queryClient.setQueriesData<PaginatedResponse<FAQCategoryItem>>(
        { queryKey: ['faq', 'categories'] },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            data: old.data.map((c) => (c.id === updatedCat.id ? updatedCat : c)),
          };
        }
      );
      queryClient.invalidateQueries({ queryKey: FAQ_QUERY_KEYS.all });
    },
  });
};

export const useDeleteFaqCategory = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => faqApi.deleteCategory(id),
    onMutate: async (deletedId: string) => {
      await queryClient.cancelQueries({ queryKey: FAQ_QUERY_KEYS.all });
      const previousCategories = queryClient.getQueriesData<PaginatedResponse<FAQCategoryItem>>({ queryKey: ['faq', 'categories'] });

      queryClient.setQueriesData<PaginatedResponse<FAQCategoryItem>>(
        { queryKey: ['faq', 'categories'] },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            total: Math.max(0, old.total - 1),
            data: old.data.filter((c) => c.id !== deletedId),
          };
        }
      );

      return { previousCategories };
    },
    onError: (_err, _deletedId, context) => {
      if (context?.previousCategories) {
        context.previousCategories.forEach(([key, val]) => queryClient.setQueryData(key, val));
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: FAQ_QUERY_KEYS.all });
    },
  });
};

// ── FAQ Items Hooks ─────────────────────────────────────────────────────────

export const useFaqs = (params?: FaqsParams) => {
  return useQuery({
    queryKey: FAQ_QUERY_KEYS.faqs(params),
    queryFn: () => faqApi.getFaqs(params),
    staleTime: 1000 * 60 * 10, // 10 minutes
    refetchOnWindowFocus: false,
  });
};

export const useCreateFaq = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateFAQPayload) => faqApi.createFaq(payload),
    onSuccess: (newFaq: FAQItem) => {
      queryClient.setQueriesData<PaginatedResponse<FAQItem>>(
        { queryKey: ['faq', 'items'] },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            total: old.total + 1,
            data: [...old.data, newFaq],
          };
        }
      );
      queryClient.invalidateQueries({ queryKey: FAQ_QUERY_KEYS.all });
    },
  });
};

export const useUpdateFaq = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateFAQPayload }) =>
      faqApi.updateFaq(id, payload),
    onSuccess: (updatedFaq: FAQItem) => {
      queryClient.setQueriesData<PaginatedResponse<FAQItem>>(
        { queryKey: ['faq', 'items'] },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            data: old.data.map((f) => (f.id === updatedFaq.id ? updatedFaq : f)),
          };
        }
      );
      queryClient.invalidateQueries({ queryKey: FAQ_QUERY_KEYS.all });
    },
  });
};

export const useDeleteFaq = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => faqApi.deleteFaq(id),
    onMutate: async (deletedId: string) => {
      await queryClient.cancelQueries({ queryKey: FAQ_QUERY_KEYS.all });
      const previousFaqs = queryClient.getQueriesData<PaginatedResponse<FAQItem>>({ queryKey: ['faq', 'items'] });

      queryClient.setQueriesData<PaginatedResponse<FAQItem>>(
        { queryKey: ['faq', 'items'] },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            total: Math.max(0, old.total - 1),
            data: old.data.filter((f) => f.id !== deletedId),
          };
        }
      );

      return { previousFaqs };
    },
    onError: (_err, _deletedId, context) => {
      if (context?.previousFaqs) {
        context.previousFaqs.forEach(([key, val]) => queryClient.setQueryData(key, val));
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: FAQ_QUERY_KEYS.all });
    },
  });
};

// ── Landing FAQ Hooks ───────────────────────────────────────────────────────

export const useLandingFaqs = (params?: LandingFaqsParams) => {
  return useQuery({
    queryKey: FAQ_QUERY_KEYS.landingFaqs(params),
    queryFn: () => faqApi.getLandingFaqs(params),
    staleTime: 1000 * 60 * 10, // 10 minutes
    refetchOnWindowFocus: false,
  });
};

export const useCreateLandingFaq = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateLandingFAQPayload) => faqApi.createLandingFaq(payload),
    onSuccess: (newLandingFaq: LandingFAQItem) => {
      queryClient.setQueriesData<PaginatedResponse<LandingFAQItem>>(
        { queryKey: ['faq', 'landing-items'] },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            total: old.total + 1,
            data: [...old.data, newLandingFaq],
          };
        }
      );
      queryClient.invalidateQueries({ queryKey: FAQ_QUERY_KEYS.all });
    },
  });
};

export const useUpdateLandingFaq = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateLandingFAQPayload }) =>
      faqApi.updateLandingFaq(id, payload),
    onSuccess: (updatedFaq: LandingFAQItem) => {
      queryClient.setQueriesData<PaginatedResponse<LandingFAQItem>>(
        { queryKey: ['faq', 'landing-items'] },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            data: old.data.map((f) => (f.id === updatedFaq.id ? updatedFaq : f)),
          };
        }
      );
      queryClient.invalidateQueries({ queryKey: FAQ_QUERY_KEYS.all });
    },
  });
};

export const useDeleteLandingFaq = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => faqApi.deleteLandingFaq(id),
    onMutate: async (deletedId: string) => {
      await queryClient.cancelQueries({ queryKey: FAQ_QUERY_KEYS.all });
      const previousLandingFaqs = queryClient.getQueriesData<PaginatedResponse<LandingFAQItem>>({ queryKey: ['faq', 'landing-items'] });

      queryClient.setQueriesData<PaginatedResponse<LandingFAQItem>>(
        { queryKey: ['faq', 'landing-items'] },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            total: Math.max(0, old.total - 1),
            data: old.data.filter((f) => f.id !== deletedId),
          };
        }
      );

      return { previousLandingFaqs };
    },
    onError: (_err, _deletedId, context) => {
      if (context?.previousLandingFaqs) {
        context.previousLandingFaqs.forEach(([key, val]) => queryClient.setQueryData(key, val));
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: FAQ_QUERY_KEYS.all });
    },
  });
};
