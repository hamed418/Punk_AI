import api from './client';

export interface MediaUploadResponse {
    id: string;
    original_filename: string;
    content_type: string;
    media_type: 'image' | 'video';
    file_size_bytes: number;
    file_path: string;
    created_at: string;
}

export const mediaApi = {
    upload: (file: File, threadId?: string) => {
        const formData = new FormData();
        formData.append('file', file);
        if (threadId) {
            formData.append('thread_id', threadId);
        }
        return api.upload<MediaUploadResponse>('/media/upload', formData);
    },
};
