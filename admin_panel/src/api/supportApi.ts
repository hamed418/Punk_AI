import api from './client';
import type { FAQCategoryItem, PaginatedResponse } from './faqApi';

export type SupportStatus = 'OPEN' | 'IN_PROGRESS' | 'RESOLVED' | 'CLOSED';

export interface UserSummary {
  id: string;
  full_name?: string | null;
  email: string;
}

export interface SupportTicketItem {
  id: string;
  user_id?: string | null;
  category_id?: string | null;
  name: string;
  email: string;
  problem_type?: string | null;
  description: string;
  status: SupportStatus;
  attachment?: string | null;
  attachment_type?: string | null;
  created_at: string;
  updated_at: string;
  category?: FAQCategoryItem | null;
  user?: UserSummary | null;
}

export interface SupportListParams {
  page?: number;
  limit?: number;
  search?: string;
  category_id?: string;
  status?: string;
  problem_type?: string;
}

export interface SupportUpdatePayload {
  status?: SupportStatus;
  category_id?: string | null;
  problem_type?: string | null;
  description?: string | null;
}

export const supportApi = {
  // Admin: List all tickets
  getTickets: async (params?: SupportListParams) => {
    const query = new URLSearchParams();
    if (params?.page) query.append('page', String(params.page));
    if (params?.limit) query.append('limit', String(params.limit));
    if (params?.search) query.append('search', params.search);
    if (params?.category_id) query.append('category_id', params.category_id);
    if (params?.status) query.append('status', params.status);
    if (params?.problem_type) query.append('problem_type', params.problem_type);
    const qs = query.toString();
    return api.get<PaginatedResponse<SupportTicketItem>>(`/support/admin/tickets${qs ? `?${qs}` : ''}`);
  },

  // Admin: Get single ticket
  getTicket: async (supportId: string) => {
    return api.get<SupportTicketItem>(`/support/admin/tickets/${supportId}`);
  },

  // Admin: Update ticket
  updateTicket: async (supportId: string, payload: SupportUpdatePayload) => {
    return api.patch<SupportTicketItem>(`/support/admin/tickets/${supportId}`, payload);
  },

  // Admin: Delete ticket
  deleteTicket: async (supportId: string) => {
    return api.delete<{ success: boolean; message: string }>(`/support/admin/tickets/${supportId}`);
  },
};
