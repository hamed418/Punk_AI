export interface FAQCategory {
  id: string;
  name: string;
  description?: string;
  type: 'faq' | 'support' | 'both';
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface FAQItem {
  id: string;
  category_id: string;
  question: string;
  answer: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  category?: FAQCategory;
}

export interface PaginatedResponse<T> {
  data: T[];
  meta: {
    total: number;
    page: number;
    limit: number;
    has_next: boolean;
    has_prev: boolean;
  };
}
