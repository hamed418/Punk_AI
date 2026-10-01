"use server";

import { chatApi } from '../lib/api/chat';
import { revalidateTag } from 'next/cache';
import { APIError, UnauthorizedError } from '../lib/errors';
import type { AudienceLayerRequest } from '../types/chat';

export async function getThreadsAction(page: number = 1, limit: number = 50) {
  try {
    const data = await chatApi.getThreads(page, limit);
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to get threads:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred' };
  }
}

export async function getStarredThreadsAction() {
  try {
    const data = await chatApi.getStarredThreads();
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to get starred threads:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred' };
  }
}

export async function getHistoryAction(threadId: string) {
  try {
    const data = await chatApi.getHistory(threadId);
    return { success: true, data };
  } catch (error: unknown) {
    console.error(`Failed to get history for thread ${threadId}:`, error);
    const isUnauthorized = error instanceof UnauthorizedError || (error instanceof APIError && error.status === 401);
    return { 
      success: false, 
      error: error instanceof Error ? error.message : 'Unknown error occurred',
      isUnauthorized
    };
  }
}

export async function getChatStatusAction(threadId: string) {
  try {
    const data = await chatApi.getStatus(threadId);
    return { success: true, data };
  } catch (error: unknown) {
    console.error(`Failed to get status for thread ${threadId}:`, error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred' };
  }
}

export async function cancelChatRunAction(threadId: string) {
  try {
    const data = await chatApi.cancelRun(threadId);
    return { success: true, data };
  } catch (error: unknown) {
    console.error(`Failed to cancel run for thread ${threadId}:`, error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred' };
  }
}

export async function createNewChatAction() {
  try {
    const data = await chatApi.createNewChat();
    // @ts-expect-error: Next.js revalidateTag
    revalidateTag('chat-threads');
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to create new chat:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred' };
  }
}

export async function deleteThreadAction(threadId: string) {
  try {
    const data = await chatApi.deleteThread(threadId);
    // @ts-expect-error: Next.js revalidateTag
    revalidateTag('chat-threads');
    // @ts-expect-error: Next.js revalidateTag
    revalidateTag('chat-threads-starred');
    return { success: true, data };
  } catch (error: unknown) {
    console.error(`Failed to delete thread ${threadId}:`, error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred' };
  }
}

export async function updateThreadAction(threadId: string, payload: { title?: string; starred?: boolean }) {
  try {
    const data = await chatApi.updateThread(threadId, payload);
    // @ts-expect-error: Next.js revalidateTag
    revalidateTag('chat-threads');
    // @ts-expect-error: Next.js revalidateTag
    revalidateTag('chat-threads-starred');
    return { success: true, data };
  } catch (error: unknown) {
    console.error(`Failed to update thread ${threadId}:`, error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred' };
  }
}

export async function uploadMediaAction(formData: FormData) {
  try {
    const data = await chatApi.uploadMedia(formData);
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to upload media:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred' };
  }
}

export async function previewAudienceAction(sessionId: string, layers: AudienceLayerRequest[]) {
  try {
    const data = await chatApi.previewAudience(sessionId, layers);
    return { success: true as const, data };
  } catch (error: unknown) {
    console.error('Failed to preview audience:', error);
    // A 409 (published/purged) or 404 (nothing extracted) carries the reason.
    return { success: false as const, error: error instanceof Error ? error.message : 'Unknown error occurred' };
  }
}

export async function getStateAction(sessionId: string) {
  try {
    const data = await chatApi.getState(sessionId);
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to get state:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred' };
  }
}

export async function getDebugAction(sessionId: string) {
  try {
    const data = await chatApi.getDebug(sessionId);
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to get debug:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred' };
  }
}
