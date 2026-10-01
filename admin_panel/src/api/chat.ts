import api from './client';
// import type { Conversation } from '../types/chat';

export interface ChatThread {
    thread_id: string;
    title: string;
    status: string;
    created_at: string;
}

export interface ThreadsResponse {
    threads: ChatThread[];
}

export interface HistoryResponse {
    messages: any[];
}

export const chatApi = {
    getThreads: () =>
        api.get<ThreadsResponse>('/chat/threads'),

    getHistory: (threadId: string) =>
        api.get<HistoryResponse>(`/chat/history/${threadId}`),

    createNewChat: () =>
        api.post<{ thread_id: string }>('/chat/new'),

    deleteThread: (threadId: string) =>
        api.delete(`/chat/thread/${threadId}`),

    uploadMedia: (formData: FormData) =>
        api.upload<{ file_id: string; url: string }>('/media/upload', formData),
};
