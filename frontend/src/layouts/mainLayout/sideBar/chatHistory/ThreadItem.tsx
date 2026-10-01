import { Menu as MantineMenu } from "@mantine/core";
import Link from "next/link";
import { ExternalLink, MoreHorizontal, Pencil, Star, Trash2 } from "lucide-react";

import type { ChatThread } from "@/types/chat.dto";
import { useQueryClient } from "@tanstack/react-query";
import { getHistoryAction } from "@/actions/chat.actions";

interface ThreadItemProps {
  thread: ChatThread;
  activeThreadId: string | null;
  isCollapsed: boolean;
  onSelect: (threadId: string) => void;
  onDelete: (e: React.MouseEvent, threadId: string) => void;
  onRename: (e: React.MouseEvent, threadId: string, currentTitle: string) => void;
  onToggleStar: (e: React.MouseEvent, threadId: string, currentStarred: boolean) => void;
}

export function ThreadItem({
  thread,
  activeThreadId,
  isCollapsed,
  onSelect,
  onDelete,
  onRename,
  onToggleStar,
}: ThreadItemProps) {
  const threadId = thread.thread_id || thread.id;
  const isActive = activeThreadId === threadId;
  const queryClient = useQueryClient();

  const handleMouseEnter = () => {
    if (!isActive) {
      queryClient.prefetchQuery({
        queryKey: ["chat-history", threadId],
        queryFn: async () => {
          const result = await getHistoryAction(threadId);
          if (!result.success) throw new Error(result.error);
          return result.data!;
        },
        staleTime: 5 * 60 * 1000,
      });
    }
  };

  return (
    <div
      className={`group/thread relative rounded-md transition-all duration-100 ${isActive ? "bg-navlink-bg" : "bg-transparent hover:bg-primary-button light:hover:bg-plus-minus-button-hover"}`}
      onMouseEnter={handleMouseEnter}
    >
      <Link
        href={`/chat/${threadId}`}
        onClick={() => onSelect(threadId)}
        className={`relative flex h-7 cursor-pointer items-center rounded-md pr-8 pl-2.5 transition-all duration-100 outline-hidden`}
      >
        {isCollapsed ? (
          <div
            className={`h-1.5 w-1.5 rounded-full transition-colors duration-200 ${isActive ? "bg-white" : "bg-transparent"}`}
          />
        ) : (
          <div className="flex min-w-0 flex-1 items-center justify-between gap-1.5">
            <span
              className={`block min-w-0 flex-1 truncate text-left text-[13px] font-medium transition-all duration-100 ease-out opacity-70 group-hover/thread:opacity-100 group-hover/thread:text-bw group-hover/thread:text-clip group-hover/thread:mask-[linear-gradient(to_right,#000_80%,transparent_100%)] group-hover/thread:mask-size-[100%_100%] ${isActive ? "text-bw opacity-100 text-clip mask-[linear-gradient(to_right,#000_80%,transparent_100%)] mask-size-[100%_100%]" : "text-primary-text/70"}`}
              title={thread.title || "Untitled Chat"}
            >
              {thread.title || "Untitled Chat"}
            </span>
          </div>
        )}
      </Link>

      {!isCollapsed && (
        <div className="absolute top-1/2 right-1 z-20 -translate-y-1/2">
          <MantineMenu position="bottom-end" withArrow shadow="sm" zIndex={4000}>
            <MantineMenu.Target>
              <button
                type="button"
                aria-label="Options"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                }}
                className={[
                  "flex h-5.5 w-5.5 items-center cursor-pointer justify-center rounded-md text-primary-text/70 opacity-100 lg:opacity-0 transition-all duration-100 lg:group-hover/thread:bg-black/20 lg:group-hover/thread:text-bw hover:shadow-sm lg:group-hover/thread:opacity-100 data-[state=open]:opacity-100 data-[state=open]:bg-background",
                  isActive ? "opacity-100 lg:opacity-100 text-bw" : "",
                ].join(" ")}
              >
                <MoreHorizontal size={14} className="shrink-0 rotate-90" />
              </button>
            </MantineMenu.Target>
            <MantineMenu.Dropdown className="min-w-40 rounded-xl border-border/50 bg-background/95 p-1 backdrop-blur-md">
              <MantineMenu.Item
                leftSection={
                  <Star
                    size={14}
                    className={thread.starred ? "text-yellow-500 fill-yellow-500" : ""}
                  />
                }
                className="text-[13px] font-medium transition-all duration-100 hover:bg-accent"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  onToggleStar(e as unknown as React.MouseEvent, threadId, thread.starred || false);
                }}
              >
                {thread.starred ? "Unstar" : "Star"}
              </MantineMenu.Item>
              <MantineMenu.Item
                leftSection={<Pencil size={14} />}
                className="text-[13px] font-medium transition-all duration-100 hover:bg-accent"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  onRename(e as unknown as React.MouseEvent, threadId, thread.title || "");
                }}
              >
                Rename
              </MantineMenu.Item>
              <MantineMenu.Item
                component="a"
                href={`/agent-track/${threadId}`}
                target="_blank"
                leftSection={<ExternalLink size={14} />}
                className="text-[13px] font-medium transition-all duration-100 hover:bg-accent"
              >
                Open in new tab
              </MantineMenu.Item>
              <MantineMenu.Divider />
              <MantineMenu.Item
                color="red"
                leftSection={<Trash2 size={14} />}
                className="text-[13px] font-medium hover:bg-destructive/10"
                onClick={(e) => onDelete(e as unknown as React.MouseEvent, threadId)}
              >
                Delete
              </MantineMenu.Item>
            </MantineMenu.Dropdown>
          </MantineMenu>
        </div>
      )}
    </div>
  );
}