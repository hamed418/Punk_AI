import { apiFetch } from '@/lib/fetcher';

export type CreativeAspectRatio = '1:1' | '4:5' | '1.91:1' | '9:16';

export interface GenerateCreativeRequest {
  media_type: 'image' | 'video';
  thread_id?: string;
  variation_hint?: string;
  reference_media_id?: string;
  aspect_ratio?: CreativeAspectRatio;
  /** How many distinct concepts to render this round (backend caps at 4). */
  variant_count?: number;
}

export interface CreativeMedia {
  id: string;
  file_name: string;
  file_path: string;
  content_type: string;
  url?: string;
}

export interface CreativeJobResponse {
  job_id: string;
  status: 'running' | 'ready' | 'failed';
  /** Every variant of the round, in render order — what the picker shows. */
  medias?: CreativeMedia[];
  /** First variant. Kept for single-asset callers. */
  media?: CreativeMedia;
  error?: string;
}

export const creativeService = {
  /**
   * Starts a new creative generation job.
   */
  generateCreative: async (data: GenerateCreativeRequest): Promise<CreativeJobResponse> => {
    return apiFetch<CreativeJobResponse>('/creatives/generate', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /**
   * Polls the status of an existing creative generation job.
   */
  pollJobStatus: async (jobId: string): Promise<CreativeJobResponse> => {
    return apiFetch<CreativeJobResponse>(`/creatives/generate/${jobId}`, {
      method: 'GET',
    });
  },
};
