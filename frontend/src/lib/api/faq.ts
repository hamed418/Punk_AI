import { apiFetch } from '../fetcher';
import { FAQCategory, FAQItem, PaginatedResponse } from '../../types/faq.types';

export interface GetFaqsQuery {
  page?: number;
  limit?: number;
  search?: string;
  category_id?: string;
  type?: string;
}

export const faqApi = {
  getCategories: (query?: GetFaqsQuery) => {
    const params = new URLSearchParams();
    if (query?.page) params.append('page', query.page.toString());
    params.append('limit', query?.limit ? query.limit.toString() : '100');
    if (query?.search) params.append('search', query.search);
    if (query?.type) params.append('type', query.type);

    return apiFetch<PaginatedResponse<FAQCategory>>(`/faq/categories?${params.toString()}`, {
      method: 'GET',
      cache: 'no-store',
    });
  },

  getFaqs: (query?: GetFaqsQuery) => {
    const params = new URLSearchParams();
    if (query?.page) params.append('page', query.page.toString());
    params.append('limit', query?.limit ? query.limit.toString() : '100');
    if (query?.search) params.append('search', query.search);
    if (query?.category_id) params.append('category_id', query.category_id);

    return apiFetch<PaginatedResponse<FAQItem>>(`/faq/faqs?${params.toString()}`, {
      method: 'GET',
      cache: 'no-store',
    });
  },
};
