import { apiFetch } from '../fetcher';
import { SupportTicket } from '../../types/support.types';
import { PaginatedResponse } from '../../types/faq.types';

export const supportApi = {
  createTicket: (data: FormData) => {
    return apiFetch<SupportTicket>('/support/tickets', {
      method: 'POST',
      body: data,
      cache: 'no-store',
    });
  },

  getMyTickets: (page: number = 1, limit: number = 20, status?: string) => {
    const params = new URLSearchParams();
    params.append('page', page.toString());
    params.append('limit', limit.toString());
    if (status) params.append('status', status);

    return apiFetch<PaginatedResponse<SupportTicket>>(`/support/me?${params.toString()}`, {
      method: 'GET',
      cache: 'no-store',
    });
  },
};
