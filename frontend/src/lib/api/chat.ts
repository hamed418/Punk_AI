import { apiFetch } from '../fetcher';
import { ThreadsResponse, HistoryResponse, ChatThread, ChatStatus, CancelResult } from '../../types/chat.dto';
import type { AudienceLayerRequest, AudiencePreviewResponse } from '../../types/chat';

export const chatApi = {
  getThreads: async (page: number = 1, limit: number = 50) => {
    // /chat/threads returns PaginatedResponse ({ data }), not { threads }.
    const queryParams = new URLSearchParams({ page: page.toString(), limit: limit.toString() });
    const res = await apiFetch<{
      data: ChatThread[];
      total: number;
      page: number;
      limit: number;
      total_pages: number;
      has_next: boolean;
      has_previous: boolean;
    }>(`/chat/threads?${queryParams.toString()}`, {
      method: 'GET',
      cache: 'no-store'
    });
    return {
      threads: res.data ?? [],
      total: res.total ?? 0,
      page: res.page ?? page,
      limit: res.limit ?? limit,
      total_pages: res.total_pages ?? 0,
      has_next: res.has_next ?? false,
      has_previous: res.has_previous ?? false,
    } as ThreadsResponse;
  },

  getStarredThreads: () => {
    return apiFetch<ThreadsResponse>('/chat/thread/starred', {
      method: 'GET',
      cache: 'no-store'
    });
  },

  getHistory: (threadId: string) => {
    return apiFetch<HistoryResponse>(`/chat/history/${threadId}`, {
      method: 'GET',
      cache: 'no-store'
    });
  },

  createNewChat: () => {
    return apiFetch<{ thread_id: string }>('/chat/new', {
      method: 'POST',
      cache: 'no-store'
    });
  },

  deleteThread: (threadId: string) => {
    return apiFetch(`/chat/thread/${threadId}`, {
      method: 'DELETE',
      cache: 'no-store'
    });
  },

  updateThread: (threadId: string, payload: { title?: string; starred?: boolean }) => {
    return apiFetch<{ thread_id: string; title: string; starred: boolean }>(`/chat/thread/update/${threadId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
      cache: 'no-store'
    });
  },

  /**
   * Where a thread stands right now: is a turn running, is it paused at a
   * widget, and can the last answer still be undone.
   *
   * `pending_action` comes from the LangGraph checkpoint's live interrupt, which
   * is authoritative — the copy embedded in the last assistant message's
   * `langchain_data` is only a fallback for rows written before this existed.
   */
  getStatus: (sessionId: string) => {
    return apiFetch<ChatStatus>(`/chat/${sessionId}/status`, {
      method: 'GET',
      cache: 'no-store'
    });
  },

  cancelRun: (sessionId: string) => {
    return apiFetch<CancelResult>(`/chat/${sessionId}/cancel`, {
      method: 'POST',
      cache: 'no-store'
    });
  },

  /**
   * What each candidate audience layer would leave, from the rows already
   * stored for the session. Read-only and free (no vendor call), so the layer
   * builder can call it on every change.
   */
  previewAudience: (sessionId: string, layers: AudienceLayerRequest[]) => {
    return apiFetch<AudiencePreviewResponse>(`/chat/${sessionId}/audience/preview`, {
      method: 'POST',
      body: JSON.stringify({ layers }),
      cache: 'no-store'
    });
  },

  getState: (sessionId: string) => {
    return apiFetch<Record<string, unknown>>(`/chat/state/${sessionId}`, {
      method: 'GET',
      cache: 'no-store'
    });
  },

  getDebug: (sessionId: string) => {
    return apiFetch<Record<string, unknown>>(`/chat/debug/${sessionId}`, {
      method: 'GET',
      cache: 'no-store'
    });
  },

  uploadMedia: (formData: FormData) => {
    // Note: apiFetch will skip adding Content-Type if body is FormData
    // media_type ('image' | 'video') comes straight from MediaFileResponse. The
    // campaign editor records it on the creative so a video-only optimization
    // goal can be caught in the form rather than at publish.
    return apiFetch<{ id: string; file_path: string; media_type: string }>('/media/upload', {
      method: 'POST',
      body: formData,
      cache: 'no-store'
    });
  }
};
