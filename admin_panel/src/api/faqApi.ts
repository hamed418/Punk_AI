import api from './client';

export interface FAQCategoryItem {
  id: string;
  name: string;
  description?: string | null;
  type: 'faq' | 'support' | 'both';
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface FAQItem {
  id: string;
  category_id: string;
  question: string;
  answer: string;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
  category?: FAQCategoryItem | null;
}

export interface PaginatedResponse<T> {
  total: number;
  page: number;
  limit: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
  data: T[];
}

export interface CreateFAQCategoryPayload {
  name: string;
  description?: string;
  type?: 'faq' | 'support' | 'both';
  is_active?: boolean;
}

export interface UpdateFAQCategoryPayload {
  name?: string;
  description?: string;
  type?: 'faq' | 'support' | 'both';
  is_active?: boolean;
}

export interface CreateFAQPayload {
  category_id: string;
  question: string;
  answer: string;
  is_active?: boolean;
}

export interface UpdateFAQPayload {
  category_id?: string;
  question?: string;
  answer?: string;
  is_active?: boolean;
}

export interface LandingFAQItem {
  id: string;
  question: string;
  answer: string;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface CreateLandingFAQPayload {
  question: string;
  answer: string;
  is_active?: boolean;
}

export interface UpdateLandingFAQPayload {
  question?: string;
  answer?: string;
  is_active?: boolean;
}

export const faqApi = {
  // Categories
  getCategories: async (params?: { page?: number; limit?: number; search?: string; type?: string; is_active?: boolean }) => {
    const query = new URLSearchParams();
    if (params?.page) query.append('page', String(params.page));
    if (params?.limit) query.append('limit', String(params.limit));
    if (params?.search) query.append('search', params.search);
    if (params?.type) query.append('type', params.type);
    if (params?.is_active !== undefined) query.append('is_active', String(params.is_active));
    const qs = query.toString();
    return api.get<PaginatedResponse<FAQCategoryItem>>(`/faq/admin/categories${qs ? `?${qs}` : ''}`);
  },

  createCategory: async (payload: CreateFAQCategoryPayload) => {
    return api.post<FAQCategoryItem>('/faq/admin/categories', payload);
  },

  updateCategory: async (id: string, payload: UpdateFAQCategoryPayload) => {
    return api.put<FAQCategoryItem>(`/faq/admin/categories/${id}`, payload);
  },

  deleteCategory: async (id: string) => {
    return api.delete<{ success?: boolean }>(`/faq/admin/categories/${id}`);
  },

  // FAQs (App / Support)
  getFaqs: async (params?: { page?: number; limit?: number; search?: string; category_id?: string; is_active?: boolean }) => {
    const query = new URLSearchParams();
    if (params?.page) query.append('page', String(params.page));
    if (params?.limit) query.append('limit', String(params.limit));
    if (params?.search) query.append('search', params.search);
    if (params?.category_id) query.append('category_id', params.category_id);
    if (params?.is_active !== undefined) query.append('is_active', String(params.is_active));
    const qs = query.toString();
    return api.get<PaginatedResponse<FAQItem>>(`/faq/admin/faqs${qs ? `?${qs}` : ''}`);
  },

  createFaq: async (payload: CreateFAQPayload) => {
    return api.post<FAQItem>('/faq/admin/faqs', payload);
  },

  updateFaq: async (id: string, payload: UpdateFAQPayload) => {
    return api.put<FAQItem>(`/faq/admin/faqs/${id}`, payload);
  },

  deleteFaq: async (id: string) => {
    return api.delete<{ success?: boolean }>(`/faq/admin/faqs/${id}`);
  },

  // Landing FAQs
  getLandingFaqs: async (params?: { page?: number; limit?: number; search?: string; is_active?: boolean }) => {
    const query = new URLSearchParams();
    if (params?.page) query.append('page', String(params.page));
    if (params?.limit) query.append('limit', String(params.limit));
    if (params?.search) query.append('search', params.search);
    if (params?.is_active !== undefined) query.append('is_active', String(params.is_active));
    const qs = query.toString();
    return api.get<PaginatedResponse<LandingFAQItem>>(`/faq/admin/landing-faq${qs ? `?${qs}` : ''}`);
  },

  createLandingFaq: async (payload: CreateLandingFAQPayload) => {
    return api.post<LandingFAQItem>('/faq/admin/landing-faq', payload);
  },

  updateLandingFaq: async (id: string, payload: UpdateLandingFAQPayload) => {
    return api.put<LandingFAQItem>(`/faq/admin/landing-faq/${id}`, payload);
  },

  deleteLandingFaq: async (id: string) => {
    return api.delete<{ success?: boolean }>(`/faq/admin/landing-faq/${id}`);
  },
};

