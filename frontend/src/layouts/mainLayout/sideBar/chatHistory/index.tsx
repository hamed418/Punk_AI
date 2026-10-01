import { useRouter } from 'next/navigation';
import { ChevronDown, MoreHorizontal } from 'lucide-react';
import { useState } from 'react';
import { Skeleton } from '@mantine/core';
import DeleteConfirmationModal from '@/components/DeleteConfirmationModal';
import RenameModal from '@/layouts/mainLayout/sideBar/chatHistory/RenameModal';
import { useChat } from '@/contexts/ChatContext';
import { ThreadItem } from './ThreadItem';

function ChatItemSkeleton({ width = '80%' }: { width?: string }) {
  return (
    <div className="relative flex h-7 w-full animate-pulse items-center rounded-md bg-navlink-bg pr-8 pl-2.5">
      <div className="flex min-w-0 flex-1 items-center">
        <Skeleton height={13} radius="sm" width={width} className="bg-primary-text/20" />
      </div>
      <div className="absolute top-1/2 right-1 flex h-5.5 w-5.5 -translate-y-1/2 items-center justify-center text-primary-text/70">
        <MoreHorizontal size={14} className="shrink-0 rotate-90" />
      </div>
    </div>
  );
}

interface ChatHistoryProps {
  isCollapsed: boolean;
  closeMobile: () => void;
}

export function ChatHistory({ isCollapsed, closeMobile }: ChatHistoryProps) {
  const {
    threads,
    threadsLoading,
    starredThreads,
    starredThreadsLoading,
    activeThreadId,
    setActiveThread,
    deleteThread,
    renameThread,
    updateThreadStar,
    fetchNextThreads,
    hasNextThreads,
    isFetchingNextThreads,
  } = useChat();
  const router = useRouter();

  const [isStarredCollapsed, setIsStarredCollapsed] = useState(false);
  const [isHistoryCollapsed, setIsHistoryCollapsed] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [threadToDelete, setThreadToDelete] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const [isRenameModalOpen, setIsRenameModalOpen] = useState(false);
  const [threadToRename, setThreadToRename] = useState<{
    id: string;
    title: string;
  } | null>(null);
  const [isRenaming, setIsRenaming] = useState(false);

  const [starringThreadIds, setStarringThreadIds] = useState<string[]>([]);
  const [unstarringThreadIds, setUnstarringThreadIds] = useState<string[]>([]);

  const handleSelectThread = (threadId: string) => {
    setActiveThread(threadId);
    router.push(`/chat/${threadId}`);
    closeMobile();
  };

  const handleDeleteThread = (e: React.MouseEvent, threadId: string) => {
    e.stopPropagation();
    setThreadToDelete(threadId);
    setIsDeleteModalOpen(true);
  };

  const handleRenameThread = (
    e: React.MouseEvent,
    threadId: string,
    currentTitle: string
  ) => {
    e.stopPropagation();
    setThreadToRename({ id: threadId, title: currentTitle });
    setIsRenameModalOpen(true);
  };

  const handleToggleStar = async (
    e: React.MouseEvent,
    threadId: string,
    currentStarred: boolean
  ) => {
    e.stopPropagation();
    const newStarred = !currentStarred;

    if (starringThreadIds.includes(threadId) || unstarringThreadIds.includes(threadId)) {
      return;
    }

    if (newStarred) {
      setStarringThreadIds((prev) => [...prev, threadId]);
      setIsStarredCollapsed(false);
    } else {
      setUnstarringThreadIds((prev) => [...prev, threadId]);
    }

    try {
      const minDelay = new Promise((resolve) => setTimeout(resolve, 800));
      await Promise.all([
        updateThreadStar(threadId, newStarred),
        minDelay,
      ]);
    } catch (error) {
      console.error('Failed to update thread star:', error);
    } finally {
      if (newStarred) {
        setStarringThreadIds((prev) => prev.filter((id) => id !== threadId));
      } else {
        setUnstarringThreadIds((prev) => prev.filter((id) => id !== threadId));
      }
    }
  };

  const confirmRename = async (newTitle: string) => {
    if (!threadToRename) return;

    setIsRenaming(true);
    try {
      await renameThread(threadToRename.id, newTitle);
      setIsRenameModalOpen(false);
    } catch (error) {
      console.error('Failed to rename thread:', error);
    } finally {
      setIsRenaming(false);
      setThreadToRename(null);
    }
  };

  const confirmDelete = async () => {
    if (!threadToDelete) return;

    setIsDeleting(true);
    try {
      await deleteThread(threadToDelete);
      if (activeThreadId === threadToDelete) {
        router.push('/chat');
      }
      setIsDeleteModalOpen(false);
    } catch (error) {
      console.error('Failed to delete thread:', error);
    } finally {
      setIsDeleting(false);
      setThreadToDelete(null);
    }
  };
  
  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const target = e.target as HTMLDivElement;
    if (
      target.scrollHeight - target.scrollTop <= target.clientHeight + 50 &&
      hasNextThreads &&
      !isFetchingNextThreads
    ) {
      fetchNextThreads();
    }
  };

  const hasStarredContent =
    starredThreads.length !== 0 ||
    starringThreadIds.length !== 0 ||
    unstarringThreadIds.length !== 0;

  const displayedStarredThreads = starredThreads.filter((t) => {
    const tId = t.thread_id || t.id;
    if (starringThreadIds.includes(tId)) return false;
    return t.starred !== false || unstarringThreadIds.includes(tId);
  });

  const recentThreads = threads.filter((t) => {
    const tId = t.thread_id || t.id;
    if (starringThreadIds.includes(tId)) return true;
    if (unstarringThreadIds.includes(tId)) return false;
    return !t.starred;
  });

  if (isCollapsed) {
    return null;
  }
  return (
    <div
      aria-hidden={isCollapsed}
      className={`flex min-h-0 flex-col overflow-hidden transition-all duration-300 ease-out ${isCollapsed ? 'pointer-events-none max-h-0 flex-none opacity-0' : 'max-h-screen flex-1 opacity-100'}`}
    >
      {hasStarredContent && (
        <button
          onClick={() => setIsStarredCollapsed(!isStarredCollapsed)}
          className="group hover:bg-secondary-bg mb-1 flex h-8 w-full cursor-pointer items-center justify-between rounded-md px-2 outline-hidden transition-all duration-100"
          type="button"
        >
          <h3 className="text-primary-text/60 group-hover:text-primary-text text-[11px] font-semibold tracking-wider transition-colors duration-200">
            Starred
          </h3>
          <ChevronDown
            size={14}
            className={`text-primary-text/60 group-hover:text-primary-text transition-transform duration-200 ease-in-out ${isStarredCollapsed ? '-rotate-90' : 'rotate-0'}`}
          />
        </button>
      )}

      {hasStarredContent && (
        <div
          className={`custom-scrollbar space-y-0.5 overflow-y-auto px-1 transition-all duration-300 ease-in-out ${isStarredCollapsed ? 'pointer-events-none max-h-0 opacity-0' : 'mb-2 max-h-52 opacity-100'}`}
        >
          {starredThreadsLoading ? (
            ['st-1', 'st-2'].map((skId) => (
              <ChatItemSkeleton key={skId} width="96%" />
            ))
          ) : (
            <>
              {displayedStarredThreads.map((thread) => {
                const tId = thread.thread_id || thread.id;
                if (unstarringThreadIds.includes(tId)) {
                  return (
                    <ChatItemSkeleton key={`unstarring-skeleton-${tId}`} width="95%" />
                  );
                }
                return (
                  <ThreadItem
                    key={tId}
                    thread={thread}
                    activeThreadId={activeThreadId}
                    isCollapsed={isCollapsed}
                    onSelect={handleSelectThread}
                    onDelete={handleDeleteThread}
                    onRename={handleRenameThread}
                    onToggleStar={handleToggleStar}
                  />
                );
              })}
              {unstarringThreadIds
                .filter((id) => !displayedStarredThreads.some((t) => (t.thread_id || t.id) === id))
                .map((id) => (
                  <ChatItemSkeleton key={`unstarring-skeleton-extra-${id}`} width="95%" />
                ))}
              {starringThreadIds.map((id) => (
                <ChatItemSkeleton key={`starring-skeleton-${id}`} width="95%" />
              ))}
            </>
          )}
        </div>
      )}

      <button
        onClick={() => setIsHistoryCollapsed(!isHistoryCollapsed)}
        className="group hover:bg-secondary-bg mb-1 flex h-8 w-full cursor-pointer items-center justify-between rounded-md px-2 outline-hidden transition-all duration-100"
        type="button"
      >
        <h3 className="text-primary-text/60 group-hover:text-primary-text text-[11px] font-semibold tracking-wider transition-colors duration-200">
          Recent Chats
        </h3>
        <ChevronDown
          size={14}
          className={`text-primary-text/60 group-hover:text-primary-text transition-transform duration-200 ease-in-out ${isHistoryCollapsed ? '-rotate-90' : 'rotate-0'}`}
        />
      </button>

      <div
        onScroll={handleScroll}
        className={`custom-scrollbar flex-1 space-y-0.5 overflow-y-auto px-1 transition-all duration-300 ease-in-out ${isHistoryCollapsed ? 'pointer-events-none max-h-0 opacity-0' : 'max-h-screen opacity-100'}`}
      >
        {threadsLoading ? (
          ['sk-1', 'sk-2', 'sk-3', 'sk-4', 'sk-5'].map((skId) => (
            <ChatItemSkeleton key={skId} width="95%" />
          ))
        ) : recentThreads.length === 0 && unstarringThreadIds.length === 0 ? (
          <p className="text-muted-foreground px-2 py-4 text-center text-[12px]">
            No conversations yet
          </p>
        ) : (
          <>
            {unstarringThreadIds.map((id) => (
              <ChatItemSkeleton key={`recent-unstarring-sk-${id}`} width="95%" />
            ))}
            {recentThreads.map((thread) => {
              const tId = thread.thread_id || thread.id;
              if (starringThreadIds.includes(tId)) {
                return (
                  <ChatItemSkeleton key={`recent-starring-sk-${tId}`} width="95%" />
                );
              }
              return (
                <ThreadItem
                  key={tId}
                  thread={thread}
                  activeThreadId={activeThreadId}
                  isCollapsed={isCollapsed}
                  onSelect={handleSelectThread}
                  onDelete={handleDeleteThread}
                  onRename={handleRenameThread}
                  onToggleStar={handleToggleStar}
                />
              );
            })}
          </>
        )}
        {isFetchingNextThreads && (
          <ChatItemSkeleton width="95%" />
        )}
      </div>

      <DeleteConfirmationModal
        isOpen={isDeleteModalOpen}
        onClose={() => !isDeleting && setIsDeleteModalOpen(false)}
        onConfirm={confirmDelete}
        isLoading={isDeleting}
        title="Delete Chat"
        message="Are you sure you want to delete this chat history? This action cannot be undone."
      />

      <RenameModal
        isOpen={isRenameModalOpen}
        onClose={() => !isRenaming && setIsRenameModalOpen(false)}
        onConfirm={confirmRename}
        currentTitle={threadToRename?.title || ''}
        isLoading={isRenaming}
      />
    </div>
  );
}
