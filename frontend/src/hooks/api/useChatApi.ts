import { InfiniteData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getThreadsAction,
  getStarredThreadsAction,
  getHistoryAction,
  createNewChatAction,
  deleteThreadAction,
  updateThreadAction,
  uploadMediaAction,
} from "../../actions/chat.actions";
import { ThreadsResponse } from "../../types/chat.dto";

export const useThreads = (enabled = true) => {
  return useInfiniteQuery({
    queryKey: ["threads"],
    queryFn: async ({ pageParam = 1 }) => {
      const result = await getThreadsAction(pageParam, 50);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
    initialPageParam: 1,
    getNextPageParam: (lastPage) => lastPage.has_next ? lastPage.page + 1 : undefined,
    enabled,
    staleTime: 5 * 60 * 1000,
  });
};

export const useStarredThreads = (enabled = true) => {
  return useQuery({
    queryKey: ["starred-threads"],
    queryFn: async () => {
      const result = await getStarredThreadsAction();
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
    enabled,
    staleTime: 5 * 60 * 1000,
  });
};

export const useChatHistory = (threadId: string | null, enabled = true) => {
  return useQuery({
    queryKey: ["chat-history", threadId],
    queryFn: async () => {
      if (!threadId) throw new Error("Thread ID is required");
      const result = await getHistoryAction(threadId);
      if (!result.success) {
        const err = new Error(result.error) as Error & { isUnauthorized?: boolean };
        if (result.isUnauthorized) {
          err.isUnauthorized = true;
        }
        throw err;
      }
      
      if (process.env.NODE_ENV === 'development') {
        window.dispatchEvent(new CustomEvent('dev-log', { detail: { eventType: 'HISTORY_DATA', threadId, data: result.data } }));
      }
      
      return result.data!;
    },
    enabled: !!threadId && enabled,
    staleTime: 5 * 60 * 1000,
    retry: (failureCount, error) => {
      const err = error as Error & { isUnauthorized?: boolean };
      if (err?.isUnauthorized && failureCount < 2) return true;
      return false;
    },
  });
};

export const useCreateChat = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const result = await createNewChatAction();
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["threads"] });
      queryClient.invalidateQueries({ queryKey: ["starred-threads"] });
    },
  });
};

export const useDeleteThread = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (threadId: string) => {
      const result = await deleteThreadAction(threadId);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
    onMutate: async (threadId: string) => {
      await queryClient.cancelQueries({ queryKey: ["threads"] });
      await queryClient.cancelQueries({ queryKey: ["starred-threads"] });

      const prevThreads = queryClient.getQueryData<InfiniteData<ThreadsResponse>>(["threads"]);
      const prevStarred = queryClient.getQueryData<ThreadsResponse>(["starred-threads"]);

      if (prevThreads) {
        queryClient.setQueryData<InfiniteData<ThreadsResponse>>(["threads"], {
          ...prevThreads,
          pages: prevThreads.pages.map((page) => ({
            ...page,
            threads: page.threads.filter(
              (t) => t.thread_id !== threadId && t.id !== threadId
            ),
          })),
        });
      }

      if (prevStarred) {
        queryClient.setQueryData<ThreadsResponse>(["starred-threads"], {
          ...prevStarred,
          threads: prevStarred.threads.filter(
            (t) => t.thread_id !== threadId && t.id !== threadId
          ),
        });
      }

      return { prevThreads, prevStarred };
    },
    onError: (_err, _vars, context) => {
      if (context?.prevThreads) {
        queryClient.setQueryData(["threads"], context.prevThreads);
      }
      if (context?.prevStarred) {
        queryClient.setQueryData(["starred-threads"], context.prevStarred);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["threads"] });
      queryClient.invalidateQueries({ queryKey: ["starred-threads"] });
    },
  });
};

export const useUploadMedia = () => {
  return useMutation({
    mutationFn: async ({ file, threadId }: { file: File; threadId?: string }) => {
      const formData = new FormData();
      formData.append("file", file);
      if (threadId) {
        formData.append("thread_id", threadId);
      }
      const result = await uploadMediaAction(formData);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
  });
};

export const useUpdateThread = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      threadId,
      payload,
    }: {
      threadId: string;
      payload: { title?: string; starred?: boolean };
    }) => {
      const result = await updateThreadAction(threadId, payload);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
    onMutate: async ({ threadId, payload }) => {
      await queryClient.cancelQueries({ queryKey: ["threads"] });
      await queryClient.cancelQueries({ queryKey: ["starred-threads"] });

      const prevThreads = queryClient.getQueryData<InfiniteData<ThreadsResponse>>(["threads"]);
      const prevStarred = queryClient.getQueryData<ThreadsResponse>(["starred-threads"]);

      if (prevThreads) {
        queryClient.setQueryData<InfiniteData<ThreadsResponse>>(["threads"], {
          ...prevThreads,
          pages: prevThreads.pages.map((page) => ({
            ...page,
            threads: page.threads.map((t) =>
              t.thread_id === threadId || t.id === threadId
                ? { ...t, ...payload }
                : t
            ),
          })),
        });
      }

      if (prevStarred) {
        queryClient.setQueryData<ThreadsResponse>(["starred-threads"], {
          ...prevStarred,
          threads: prevStarred.threads.map((t) =>
            t.thread_id === threadId || t.id === threadId
              ? { ...t, ...payload }
              : t
          ),
        });
      }

      return { prevThreads, prevStarred };
    },
    onError: (_err, _vars, context) => {
      if (context?.prevThreads) {
        queryClient.setQueryData(["threads"], context.prevThreads);
      }
      if (context?.prevStarred) {
        queryClient.setQueryData(["starred-threads"], context.prevStarred);
      }
    },
    onSettled: () => {
      return Promise.all([
        queryClient.invalidateQueries({ queryKey: ["threads"] }),
        queryClient.invalidateQueries({ queryKey: ["starred-threads"] }),
      ]);
    },
  });
};
