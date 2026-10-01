'use client';

import { useQueryClient } from '@tanstack/react-query';
import { usePathname, useRouter } from 'next/navigation';
import React, {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { CancelOutcome, ChatMessage, ChatStatus, ChatThread } from '../types/chat.dto';

import {
  cancelChatRunAction,
  getChatStatusAction,
} from '../actions/chat.actions';
import {
  useChatHistory,
  useCreateChat,
  useDeleteThread,
  useStarredThreads,
  useThreads,
  useUpdateThread,
} from '../hooks/api/useChatApi';
import { trackEvent } from '@/lib/analytics';
import { rewindMarker } from '@/lib/rewind';
import type {
  Block,
  Conversation,
  MapDataBlock,
  MessageBlock,
} from '../types/chat';
import { upsertPendingAction } from '../lib/pendingActionBlocks';
import { useAuth } from './AuthContext';

export type PlaceItem = {
  id?: string;
  location?: { latitude?: number; longitude?: number };

  displayName?: { text?: string };
  formattedAddress?: string;
  rating?: number;
  userRatingCount?: number;
  types?: string[];
};

export type Place = {
  id: string;
  type: string;
  content: string;
  lat: number;
  lng: number;
};
interface ChatContextType {
  threads: ChatThread[];
  starredThreads: ChatThread[];
  conversation: Conversation | undefined;
  activeThreadId: string | null;
  loading: boolean;
  streaming: boolean;
  currentStepLabel: string | null;
  updateBlock: (blockId: string, updater: (b: Block) => Block) => void;
  sendMessage: (content: string, isResume?: boolean) => Promise<string | null>;
  /**
   * A free-text message typed while Punk is still working. Held here and sent
   * the moment the run ends (to the pending question if there is one, else as a
   * normal message). One at a time: a newer one replaces it.
   */
  queuedMessage: string | null;
  cancelQueuedMessage: () => void;
  createNewChat: () => Promise<string>;
  setActiveThread: (threadId: string) => Promise<void>;
  deleteThread: (threadId: string) => Promise<boolean>;
  renameThread: (threadId: string, title: string) => Promise<boolean>;
  updateThreadStar: (threadId: string, starred: boolean) => Promise<boolean>;
  refreshThreads: () => Promise<void>;
  refreshStarredThreads: () => Promise<void>;
  resetChat: () => void;
  chatDisable: boolean;
  threadsLoading: boolean;
  starredThreadsLoading: boolean;
  inputMode: 'chat' | 'widget';
  selectedPoiAddress: PlaceItem[];
  setSelectedPoiAddress: React.Dispatch<React.SetStateAction<PlaceItem[]>>;
  fetchNextThreads: () => void;
  hasNextThreads: boolean;
  isFetchingNextThreads: boolean;
  isHistoryError: boolean;
  historyError: Error | null;
  /** Stop the turn currently generating. The partial answer is still saved. */
  stopGeneration: () => Promise<void>;
  /**
   * Rewind to a previous answer.
   *
   * No args      -> undo the last answer, re-asking the step.
   * messageId    -> undo that specific answer.
   * + value      -> edit: resubmit that answer with new text (retry = same text).
   */
  rewindTo: (messageId?: string, value?: string) => Promise<void>;
  /** Whether the last answer is still rewindable (false once published to Meta). */
  canUndo: boolean;
  /** Text of an undone free-text message, for the composer to pick up. */
  composerPrefill: string | null;
  clearComposerPrefill: () => void;
  /**
   * Set after a stop that un-sent the answer. Without it the message just
   * vanishes and nothing explains why. Carries the payload so a widget answer
   * (map pin, filled form) can be resent in one click instead of redone.
   */
  stopNotice: {
    value: string;
    isWidget: boolean;
    // 'pending' while the stop request is in flight; 'error' if it failed —
    // both client-only, never sent by the server.
    outcome: CancelOutcome | 'pending' | 'error';
  } | null;
  dismissStopNotice: () => void;
  resendStopped: () => Promise<void>;
  /**
   * Re-send a user message the server never accepted (status 'failed').
   *
   * Not a rewind: nothing was persisted, so there is no checkpoint to fork. The
   * block is dropped and the text goes back through the normal send path.
   */
  retrySend: (blockId: string) => Promise<void>;
}

const ChatContext = createContext<ChatContextType | undefined>(undefined);

/** Blocks for a message's langchain_data / status payload.
 *
 * A map that carries its own pending_action renders as ONE block (the widget
 * lives inside the map), everything else renders as siblings. History and the
 * status-based repair path both go through here so they can never disagree. */
const buildWidgetBlocks = (
  baseId: string,
  mapData: unknown,
  pendingAction: unknown,
  campaignPlan?: unknown
): Block[] => {
  const blocks: Block[] = [];

  if (mapData && pendingAction) {
    blocks.push({
      id: `map-${baseId}`,
      type: 'map_data',
      content: {
        ...(mapData as object),
        pending_action: pendingAction,
      },
    } as Block);
    return blocks;
  }

  if (campaignPlan) {
    blocks.push({
      id: `campaign-plan-${baseId}`,
      type: 'campaign_plan',
      content: campaignPlan,
    } as Block);
  }
  if (mapData) {
    blocks.push({
      id: `map-${baseId}`,
      type: 'map_data',
      content: mapData,
    } as Block);
  }
  if (pendingAction) {
    blocks.push({
      id: `action-${baseId}`,
      type: 'pending_action',
      content: pendingAction,
    } as Block);
  }
  return blocks;
};

/** True when the conversation tail is waiting on a widget answer.
 *
 * Walks backwards and stops at the user's last message: anything before that has
 * already been answered. */
const hasTrailingWidget = (blocks: Block[]): boolean => {
  for (let i = blocks.length - 1; i >= 0; i--) {
    const b = blocks[i];
    if (b.type === 'message' && b.role === 'user') return false;
    if (
      b.type === 'pending_action' ||
      (b.type === 'map_data' && b.content?.pending_action) ||
      (b.type === 'campaign_plan' && b.content?.pending_action)
    ) {
      return true;
    }
  }
  return false;
};

/** Widgets wire their answer as "Q: <prompt>\nA: <answer>", where the answer half
 * may be JSON, a date range or a map pin. Those are not editable as text — undo
 * re-renders the widget instead — so only a plain typed message prefills.
 * Exported: ChatPage's activeWidgetBlock uses the same test to decide whether
 * a user message mid-stream is a widget's own submission (keep the widget up)
 * or a typed follow-up (retire it as usual).
 *
 * A raw `{...}`/`[...]` also counts: CampaignEditor sends its plan/preview
 * submission bare, with no Q:/A: wrapper at all (see its file-header JSDoc) —
 * same rule the backend uses to route a submission past the resume classifier,
 * resume_router.is_sentinel_resume. Without this, ChatPage's activeWidgetBlock
 * scan (below) treats a Publish click as an ordinary user message and drops
 * the editor mid-turn instead of keeping it mounted through the build. */
export const isWidgetAnswer = (text: string): boolean => {
  const t = text.trimStart();
  return (
    (text.startsWith('Q:') && text.includes('\nA:')) ||
    t.startsWith('{') ||
    t.startsWith('[')
  );
};

export const ChatProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const { user, loading: authLoading } = useAuth();
  const queryClient = useQueryClient();
  // Thread id whose post-stream history refetch is still settling, or null.
  // Scoped to a thread so a refetch on thread A cannot freeze thread B's render.
  const postStreamLockRef = useRef<string | null>(null);
  const {
    data: threadsData,
    refetch: refreshThreads,
    isLoading: threadsLoading,
    fetchNextPage: fetchNextThreads,
    hasNextPage: hasNextThreads,
    isFetchingNextPage: isFetchingNextThreads,
  } = useThreads(!!user);

  const {
    data: starredThreadsData,
    refetch: refreshStarredThreads,
    isLoading: starredThreadsLoading,
  } = useStarredThreads(!!user);

  const pathname = usePathname() || '';
  const router = useRouter();

  const [activeThreadId, setActiveThreadId] = useState<string | null>(() => {
    const match = pathname.match(/^\/chat\/([^/]+)/);
    return match ? match[1] : null;
  });
  const {
    data: historyData,
    isLoading: historyLoading,
    isError: isHistoryError,
    error: historyError,
  } = useChatHistory(activeThreadId, !!user);

  const createChatMutation = useCreateChat();
  const deleteThreadMutation = useDeleteThread();
  const updateThreadMutation = useUpdateThread();

  const [conversation, setConversation] = useState<Conversation | undefined>(
    undefined
  );
  const [streaming, setStreaming] = useState(false);
  // A message typed while a run is active (see ChatContextType.queuedMessage).
  // The ref is what the drain reads — state is only for the UI chip — and it
  // remembers WHICH thread it was typed in, so switching threads drops it
  // instead of sending it to the wrong conversation.
  const queuedRef = useRef<{ content: string; threadId: string | null } | null>(null);
  const [queuedMessage, setQueuedMessage] = useState<string | null>(null);
  const setQueued = useCallback(
    (next: { content: string; threadId: string | null } | null) => {
      queuedRef.current = next;
      setQueuedMessage(next ? next.content : null);
    },
    []
  );
  const drainQueuedRef = useRef<() => void>(() => {});
  const [currentStepLabel, setCurrentStepLabel] = useState<string | null>(null);
  const [chatDisable, setChatDisable] = useState<boolean>(false);
  const [inputMode, setInputMode] = useState<'chat' | 'widget'>('chat');
  const [canUndo, setCanUndo] = useState(false);
  const [composerPrefill, setComposerPrefill] = useState<string | null>(null);
  const [stopNotice, setStopNotice] = useState<
    { value: string; isWidget: boolean; outcome: CancelOutcome | 'pending' | 'error' } | null
  >(null);
  const [statusData, setStatusData] = useState<ChatStatus | null>(null);
  const sendingRef = useRef(false);
  const clearingRef = useRef(false);
  const [selectedPoiAddress, setSelectedPoiAddress] = useState<PlaceItem[]>([]);

  // The SSE reader currently attached, and which thread it belongs to. The run
  // itself lives on the server and outlives this connection, so aborting only
  // detaches this client — it never cancels the turn.
  const streamAbortRef = useRef<AbortController | null>(null);
  const streamThreadIdRef = useRef<string | null>(null);

  const [prevActiveThreadId, setPrevActiveThreadId] = useState(activeThreadId);
  if (activeThreadId !== prevActiveThreadId) {
    setPrevActiveThreadId(activeThreadId);
    if (selectedPoiAddress.length > 0) {
      setSelectedPoiAddress([]);
    }
  }

  const activeThreadIdRef = useRef(activeThreadId);
  useEffect(() => {
    activeThreadIdRef.current = activeThreadId;
  }, [activeThreadId]);

  useEffect(() => {
    const match = pathname.match(/^\/chat\/([^/]+)/);
    if (match) {
      const routeThreadId = match[1];
      if (clearingRef.current) return;
      if (routeThreadId !== activeThreadIdRef.current) {
        setTimeout(() => {
          setActiveThreadId(routeThreadId);
          setConversation(undefined);
          setInputMode('chat');
          setChatDisable(false);
        }, 0);
      }
    } else {
      clearingRef.current = false;
      if (activeThreadIdRef.current && !sendingRef.current && !streaming) {
        setActiveThreadId(null);
        setConversation(undefined);
        setInputMode('chat');
        setChatDisable(false);
      }
    }
  }, [pathname, streaming]);

  const threads = useMemo(() => {
    if (!threadsData) return [];
    return threadsData.pages.flatMap((page) => page.threads);
  }, [threadsData]);
  const starredThreads = useMemo(
    () => starredThreadsData?.threads || [],
    [starredThreadsData]
  );

  useEffect(() => {
    // Only a stream belonging to THIS thread should hold off the history sync.
    // Gating on a global `streaming` flag is what left a freshly-opened thread
    // blank while another thread's turn was still running.
    const busyOnThisThread =
      (sendingRef.current || streaming) &&
      streamThreadIdRef.current === activeThreadId;
    if (busyOnThisThread || postStreamLockRef.current === activeThreadId) return;
    if (!historyData || !activeThreadId) return;

    const messagesWithData = historyData.messages.flatMap(
      (m: ChatMessage, index: number) => {
        const blocks: Block[] = [];
        const baseId = m.id || `msg-${index}`;
        if (m.content || m.thinking) {
          blocks.push({
            ...m,
            id: baseId,
            type: 'message',
            role: (m.role === 'assistant' ? 'assistant_message' : m.role) as
              'user' | 'assistant' | 'system' | 'assistant_message',
            status: 'complete',
          });
        }

        if (
          m.langchain_data &&
          typeof m.langchain_data === 'object' &&
          !Array.isArray(m.langchain_data)
        ) {
          blocks.push(
            ...buildWidgetBlocks(
              baseId,
              m.langchain_data.map_data,
              m.langchain_data.pending_action,
              m.langchain_data.campaign_plan
            )
          );
        }
        return blocks;
      }
    );

    setTimeout(() => {
      setConversation((prev) => {
        if (!prev || prev.id !== activeThreadId) {
          return { id: activeThreadId, blocks: messagesWithData };
        }

// Check if content actually changed to avoid unnecessary re-renders/flickers
        const isIdentical =
          prev.blocks.length === messagesWithData.length &&
          prev.blocks.every((b, i) => {
            const sb = messagesWithData[i];
            if (b.type !== sb.type) return false;
            if (b.type === 'message' && sb.type === 'message') {
              return b.content === sb.content;
            }
            return JSON.stringify(b.content) === JSON.stringify(sb.content);
          });

        if (isIdentical) return prev;

        return { id: activeThreadId, blocks: messagesWithData };
      });
    }, 0);
  }, [historyData, activeThreadId, streaming]);

  useEffect(() => {
    setTimeout(() => {
      if (!authLoading && !user) {
        setConversation(undefined);
        setActiveThreadId(null);
        setStreaming(false);
        setCurrentStepLabel(null);
        sendingRef.current = false;
      }
    }, 0);
  }, [user, authLoading]);

  useEffect(() => {
    if (!conversation) {
      setTimeout(() => {
        setChatDisable(false);
        setInputMode('chat');
      }, 0);

      return;
    }

    const blocks = conversation.blocks;
    if (blocks.length === 0) {
      setTimeout(() => {
        setChatDisable(false);
        setInputMode('chat');
      }, 0);

      return;
    }

    if (hasTrailingWidget(blocks)) {
      setTimeout(() => {
        setChatDisable(true);
        setInputMode('widget');
      }, 0);
    } else {
      setTimeout(() => {
        setChatDisable(false);
        setInputMode('chat');
      }, 0);
    }
  }, [conversation]);

  // ── SSE consumption ────────────────────────────────────────────────────────

  /**
   * Read one SSE body and fold its events into the conversation.
   *
   * Shared by sending, resuming, re-attaching to a run already in flight, and
   * undo — all four speak the same wire format, so they must all interpret it
   * the same way.
   *
   * Every state write is scoped to `threadId`: the run is server-side and keeps
   * going after the user navigates away, so an unscoped write would paint one
   * thread's tokens into another thread's transcript.
   */
  const consumeStream = useCallback(
    async (response: Response, threadId: string): Promise<void> => {
      const reader = response.body?.getReader();
      if (!reader) throw new Error('No reader available');

      const decoder = new TextDecoder();
      let buffer = '';

      let currentTurnMapBlockId: string | null = null;
      let currentTurnCampaignPlanBlockId: string | null = null;
      let hasLiveGeminiThinking = false;
      let hasLivePunkThinking = false;

      const patch = (fn: (prev: Conversation) => Conversation) =>
        setConversation((prev) =>
          prev && prev.id === threadId ? fn(prev) : prev
        );

      const isActive = () => activeThreadIdRef.current === threadId;

      const replaceOrAddMapBlock = (block: Block) => {
        patch((prev) => {
          const blocks = [...prev.blocks];
          if (currentTurnMapBlockId) {
            const idx = blocks.findIndex((b) => b.id === currentTurnMapBlockId);
            if (idx !== -1) {
              blocks[idx] = block;
              return { ...prev, blocks };
            }
          }
          // If not found or not created yet, push it
          currentTurnMapBlockId = block.id;
          blocks.push(block);
          return { ...prev, blocks };
        });
      };

      const replaceOrAddCampaignPlanBlock = (block: Block) => {
        patch((prev) => {
          const blocks = [...prev.blocks];
          if (currentTurnCampaignPlanBlockId) {
            const idx = blocks.findIndex(
              (b) => b.id === currentTurnCampaignPlanBlockId
            );
            if (idx !== -1) {
              blocks[idx] = block;
              return { ...prev, blocks };
            }
          }
          currentTurnCampaignPlanBlockId = block.id;
          blocks.push(block);
          return { ...prev, blocks };
        });
      };

      const appendAssistantThinking = (thinking: string) => {
        patch((prev) => {
          const blocks = [...prev.blocks];
          const lastBlock = blocks[blocks.length - 1];

          if (
            lastBlock &&
            lastBlock.type === 'message' &&
            lastBlock.role === 'assistant'
          ) {
            blocks[blocks.length - 1] = {
              ...lastBlock,
              thinking: (lastBlock.thinking || '') + thinking,
              status: 'streaming',
            };
          } else {
            blocks.push({
              id: crypto.randomUUID(),
              type: 'message',
              role: 'assistant',
              content: '',
              thinking,
              status: 'streaming',
              createdAt: new Date().toISOString(),
            });
          }
          return { ...prev, blocks };
        });
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmedLine = line.trim();
          // `id:` lines carry the run's sequence number for reconnects; the
          // reader does not need them, the browser tracks Last-Event-ID itself.
          if (!trimmedLine?.startsWith('data: ')) continue;

          const dataStr = trimmedLine.slice(6).trim();
          if (!dataStr) continue;

          try {
            const data = JSON.parse(dataStr);
            if (process.env.NODE_ENV === 'development') {
              window.dispatchEvent(new CustomEvent('dev-log', { detail: { eventType: 'SSE_STREAM', data } }));
            }
            if (data.type === 'input_mode') {
              if (isActive()) {
                setInputMode(data.mode);
                setChatDisable(data.mode === 'widget');
              }
            } else if (data.type === 'update') {
              const updateContent =
                typeof data.content === 'string' ? data.content.trim() : '';
              if (updateContent && isActive()) {
                setCurrentStepLabel(updateContent);
              }
            } else if (data.type === 'rewind') {
              // The server deletes from a DIFFERENT row depending on mode: the
              // target answer on an edit (its silent re-ask writes no new
              // question row), the preceding ANCHOR question on an undo (the
              // re-ask re-emits it, so the old copy must go too or it shows
              // twice). Cutting at message_id on both, like before, left the
              // anchor's question and widget on screen under a duplicate.
              const resubmitting: boolean = !!data.content?.resubmitting;
              // `cut_id` is the server's own cut point (the first row it deletes) —
              // the only side that knows it once shared-checkpoint re-asks and idle
              // anchors are in play. The older keys stay as a fallback.
              const cutId: string | undefined =
                data.content?.cut_id ??
                (resubmitting
                  ? data.content?.message_id
                  : data.content?.anchor_id ?? data.content?.message_id);
              // What the user changed it TO. The cut below removes their old bubble; without
              // putting the new one straight back it vanished until the history refetch,
              // ~1s after the stream ended, and the reply streamed under nothing.
              const newText: string =
                typeof data.content?.new_text === 'string' ? data.content.new_text : '';
              const discarded: number =
                typeof data.content?.discarded === 'number' ? data.content.discarded : 0;
              patch((prev) => {
                const blocks = [...prev.blocks];
                // Blocks built from history carry the DB message id. Fall back to
                // the last user message when the id isn't on screen (locally
                // streamed blocks use generated ids).
                const byId = cutId ? blocks.findIndex((b) => b.id === cutId) : -1;
                if (byId !== -1) {
                  blocks.length = byId;
                } else {
                  for (let i = blocks.length - 1; i >= 0; i--) {
                    const b = blocks[i];
                    if (b.type === 'message' && b.role === 'user') {
                      blocks.length = i;
                      break;
                    }
                  }
                }
                const stamp = Date.now();
                if (resubmitting && newText) {
                  blocks.push({
                    id: `rewind-edited-${stamp}`,
                    type: 'message',
                    role: 'user',
                    content: newText,
                    status: 'complete',
                    edited: true,
                    createdAt: new Date().toISOString(),
                  });
                }
                // Say what just happened, so the cut never looks like a glitch.
                blocks.push({
                  id: `rewind-marker-${stamp}`,
                  type: 'message',
                  role: 'system',
                  kind: 'rewind_marker',
                  content: rewindMarker(resubmitting, discarded),
                  status: 'complete',
                });
                return { ...prev, blocks };
              });
              // On an edit the new answer is already on its way, so the old text
              // must not also land in the composer.
              const undoneText: string = data.content?.undone_text || '';
              if (undoneText && !resubmitting && !isWidgetAnswer(undoneText) && isActive()) {
                setComposerPrefill(undoneText);
              }
            } else if (data.type === 'rewind_failed') {
              // The server refused before touching anything (published campaign,
              // fork error) — nothing was cut, so keep the transcript as it is and
              // say why instead of leaving the button looking dead.
              if (isActive()) {
                setCurrentStepLabel(null);
                setChatDisable(false);
              }
              const failMessage =
                typeof data.content?.message === 'string'
                  ? data.content.message
                  : 'Could not change that answer. Nothing was lost.';
              patch((prev) => ({
                ...prev,
                blocks: [
                  ...prev.blocks,
                  {
                    id: `rewind-failed-${Date.now()}`,
                    type: 'message',
                    role: 'system',
                    content: failMessage,
                    status: 'complete',
                  },
                ],
              }));
            } else if (data.type === 'rewind_notice') {
              // The server re-armed a different step than the one edited and applied the
              // change there — say so, the step on screen is not the one they clicked.
              const noticeMessage =
                typeof data.content?.message === 'string' ? data.content.message : '';
              if (noticeMessage) {
                patch((prev) => ({
                  ...prev,
                  blocks: [
                    ...prev.blocks,
                    {
                      id: `rewind-notice-${Date.now()}`,
                      type: 'message',
                      role: 'system',
                      kind: 'rewind_marker',
                      content: noticeMessage,
                      status: 'complete',
                    },
                  ],
                }));
              }
            } else if (data.type === 'rewind_degraded') {
              // Nothing is open to answer, so the edit could not be sent. The server
              // hands the text back: put it in the composer instead of losing it.
              if (isActive()) {
                setCurrentStepLabel(null);
                setChatDisable(false);
              }
              const keptText: string =
                (typeof data.content?.new_text === 'string' && data.content.new_text) ||
                (typeof data.content?.undone_text === 'string' && data.content.undone_text) ||
                '';
              if (keptText && !isWidgetAnswer(keptText) && isActive()) {
                setComposerPrefill(keptText);
              }
              const message =
                typeof data.content?.message === 'string'
                  ? data.content.message
                  : 'Went back, but your change could not be sent. Try again.';
              patch((prev) => ({
                ...prev,
                blocks: [
                  ...prev.blocks,
                  {
                    id: `rewind-degraded-${Date.now()}`,
                    type: 'message',
                    role: 'system',
                    content: message,
                    status: 'complete',
                  },
                ],
              }));
            } else if (data.type === 'cancelled') {
              if (isActive()) setCurrentStepLabel(null);
            } else if (data.type === 'error') {
              // Previously unhandled: the frame was parsed, logged to the dev
              // console, and dropped. A backend exception therefore looked like
              // the stream simply stopping — no message, no retry affordance,
              // nothing to report. Surface it as an assistant turn instead.
              if (isActive()) {
                setCurrentStepLabel(null);
                setChatDisable(false);
              }
              const errText =
                typeof data.content === 'string'
                  ? data.content
                  : (data.content as { message?: string })?.message ||
                    'Something went wrong on our side. Nothing was lost — try that again.';
              patch((prev) => ({
                ...prev,
                blocks: [
                  ...prev.blocks,
                  {
                    id: crypto.randomUUID(),
                    type: 'message',
                    role: 'assistant',
                    content: errText,
                  } as Block,
                ],
              }));
            } else if (data.type === 'map_data') {
              if (isActive()) setChatDisable(true);
              const block: Block = {
                id: currentTurnMapBlockId || crypto.randomUUID(),
                type: 'map_data',
                content: data.content,
              };
              replaceOrAddMapBlock(block);
            } else if (data.type === 'campaign_plan') {
              if (isActive()) setChatDisable(true);
              patch((prev) => {
                if (currentTurnCampaignPlanBlockId) return prev;

                const blocks = prev.blocks.filter(
                  (b) =>
                    !(
                      b.type === 'message' &&
                      b.role === 'assistant' &&
                      b.status === 'streaming'
                    )
                );
                return { ...prev, blocks };
              });

              const block: Block = {
                id: currentTurnCampaignPlanBlockId || crypto.randomUUID(),
                type: 'campaign_plan',
                content: data.content,
              };
              replaceOrAddCampaignPlanBlock(block);
            } else if (data.type === 'pending_action') {
              if (isActive()) setChatDisable(true);
              const pendingContent = {
                ...data.content,
                options: data.content.options ?? [],
                prefill: data.content.prefill ?? null,
                stepper: data.content.stepper ?? null,
                progress: data.content.progress ?? null,
                suggestions: data.content.suggestions ?? null,
                escape_menu: data.content.escape_menu ?? null,
                step_key: data.content.step_key ?? null,
              };

              patch((prev) => {
                const blocks = [...prev.blocks];

                // Same step already on screen? Replace it in place so the widget
                // does not remount and lose what the user typed. See
                // lib/pendingActionBlocks for the full reasoning.
                const upserted = upsertPendingAction(
                  blocks,
                  pendingContent,
                  () => crypto.randomUUID()
                );
                if (upserted !== blocks && upserted.length === blocks.length) {
                  return { ...prev, blocks: upserted };
                }

                // Try to find a campaign plan block
                const lastCampaignPlanIdx = currentTurnCampaignPlanBlockId
                  ? blocks.findIndex(
                      (b) => b.id === currentTurnCampaignPlanBlockId
                    )
                  : -1;

                if (lastCampaignPlanIdx !== -1) {
                  // Campaign plan block currently does not embed pending_action inside its content,
                  // it just relies on the sequential blocks. So we just push it sequentially.
                  blocks.push({
                    id: crypto.randomUUID(),
                    type: 'pending_action',
                    content: pendingContent,
                  });
                  return { ...prev, blocks };
                }

                const lastMapIdx = currentTurnMapBlockId
                  ? blocks.findIndex((b) => b.id === currentTurnMapBlockId)
                  : -1;

                if (lastMapIdx !== -1) {
                  const mapBlock = blocks[lastMapIdx] as MapDataBlock;
                  blocks[lastMapIdx] = {
                    ...mapBlock,
                    content: {
                      ...mapBlock.content,
                      pending_action: pendingContent,
                    },
                  } as MapDataBlock;
                  return { ...prev, blocks };
                } else {
                  blocks.push({
                    id: crypto.randomUUID(),
                    type: 'pending_action',
                    content: pendingContent,
                  });
                  return { ...prev, blocks };
                }
              });
            } else if (data.type === 'assistant_message') {
              patch((prev) => {
                const blocks = [...prev.blocks];

                // Search backwards for the last assistant message in the current turn (stop at user's message)
                let foundIdx = -1;
                for (let i = blocks.length - 1; i >= 0; i--) {
                  const b = blocks[i];
                  if (b.type === 'message' && b.role === 'user') {
                    break;
                  }
                  if (b.type === 'message' && b.role === 'assistant') {
                    foundIdx = i;
                    break;
                  }
                }

                if (foundIdx !== -1) {
                  const targetBlock = blocks[foundIdx] as MessageBlock;
                  blocks[foundIdx] = {
                    ...targetBlock,
                    content: targetBlock.content + data.content,
                    status: 'streaming',
                  };
                } else {
                  // Find the last user message index to know where the current turn starts.
                  let lastUserIdx = -1;
                  for (let i = blocks.length - 1; i >= 0; i--) {
                    const b = blocks[i];
                    if (b.type === 'message' && b.role === 'user') {
                      lastUserIdx = i;
                      break;
                    }
                  }

                  // Find the first widget block in this turn (after lastUserIdx)
                  let insertIdx = -1;
                  if (lastUserIdx !== -1) {
                    for (let i = lastUserIdx + 1; i < blocks.length; i++) {
                      if (blocks[i].type !== 'message') {
                        insertIdx = i;
                        break;
                      }
                    }
                  }

                  const newMsgBlock: Block = {
                    id: crypto.randomUUID(),
                    type: 'message',
                    role: 'assistant',
                    content: data.content,
                    status: 'streaming',
                    createdAt: new Date().toISOString(),
                  };

                  if (insertIdx !== -1) {
                    // Insert before the first widget of the current turn
                    blocks.splice(insertIdx, 0, newMsgBlock);
                  } else {
                    // No widget block yet, just push to the end
                    blocks.push(newMsgBlock);
                  }
                }
                return { ...prev, blocks };
              });
            } else if (data.type === 'thinking') {
              const thinkingContent =
                typeof data.content === 'string' ? data.content : '';
              const isLiveGeminiThinking =
                data.source === 'gemini' && thinkingContent;
              const isLivePunkThinking =
                data.source === 'punk' && thinkingContent;
              const isLegacyUserFacingThinking =
                thinkingContent.startsWith('Punk Reasoning:') ||
                thinkingContent.startsWith('Chatbot reasoning:');

              if (isLiveGeminiThinking) {
                const prefix = hasLiveGeminiThinking
                  ? ''
                  : 'Gemini reasoning:\n';
                hasLiveGeminiThinking = true;
                appendAssistantThinking(prefix + thinkingContent);
              } else if (isLivePunkThinking) {
                const prefix = hasLivePunkThinking
                  ? ''
                  : `${hasLiveGeminiThinking ? '\n\n' : ''}Punk reasoning:\n`;
                hasLivePunkThinking = true;
                appendAssistantThinking(prefix + thinkingContent);
              } else if (isLegacyUserFacingThinking) {
                appendAssistantThinking(
                  (hasLiveGeminiThinking ? '\n\n' : '') + thinkingContent
                );
              }
            }
          } catch (error) {
            console.error('Error parsing stream JSON:', error);
            queryClient.invalidateQueries({ queryKey: ['user'] });
          }
        }
      }
    },
    [queryClient]
  );

  const refreshStatus = useCallback(async (threadId: string) => {
    const result = await getChatStatusAction(threadId);
    if (!result.success || !result.data) return null;
    if (activeThreadIdRef.current !== threadId) return result.data;
    setStatusData(result.data);
    setCanUndo(result.data.can_undo);
    return result.data;
  }, []);

  /** Mark the turn finished and let the server-side history take over again. */
  const finishStream = useCallback(
    (threadId: string) => {
      setCurrentStepLabel(null);
      setStreaming(false);
      streamAbortRef.current = null;
      streamThreadIdRef.current = null;

      setConversation((prev) => {
        if (!prev || prev.id !== threadId) return prev;
        return {
          ...prev,
          blocks: prev.blocks.map((b) =>
            b.type === 'message' ? { ...b, status: 'complete' } : b
          ),
        };
      });

      // postStreamLock stays set until AFTER the invalidation resolves so the
      // historyData effect cannot overwrite the locally-streamed blocks with
      // server data that has not caught up yet.
      postStreamLockRef.current = threadId;
      setTimeout(() => {
        sendingRef.current = false;
        // The run is over: send anything the user typed while it was working.
        drainQueuedRef.current();
        queryClient.invalidateQueries({
          queryKey: ['chat-history', threadId],
        });
        queryClient.invalidateQueries({ queryKey: ['threads'] });
        queryClient.invalidateQueries({ queryKey: ['user'] });
        setTimeout(() => {
          if (postStreamLockRef.current === threadId) {
            postStreamLockRef.current = null;
          }
        }, 1500);
      }, 800);

      void refreshStatus(threadId);
    },
    [queryClient, refreshStatus]
  );

  // ── Re-attach ──────────────────────────────────────────────────────────────

  /**
   * Follow a turn that is already running on the server.
   *
   * This is what makes a refresh or a thread switch survivable: the run is a
   * background task, not this connection, so re-subscribing from seq 0 replays
   * everything the client missed and then goes live.
   */
  const attachToRun = useCallback(
    async (threadId: string) => {
      if (streamThreadIdRef.current === threadId) return;

      const controller = new AbortController();
      streamAbortRef.current = controller;
      streamThreadIdRef.current = threadId;
      setStreaming(true);
      setCurrentStepLabel('Reconnecting');

      try {
        const response = await fetch(
          `/api/chat/${threadId}/stream?from_seq=0`,
          { signal: controller.signal }
        );
        if (response.status === 204 || !response.ok) {
          setStreaming(false);
          streamThreadIdRef.current = null;
          streamAbortRef.current = null;
          return;
        }
        await consumeStream(response, threadId);
        finishStream(threadId);
      } catch (error) {
        if ((error as Error)?.name !== 'AbortError') {
          console.error('Failed to attach to run:', error);
        }
        setStreaming(false);
        if (streamThreadIdRef.current === threadId) {
          streamThreadIdRef.current = null;
          streamAbortRef.current = null;
        }
      }
    },
    [consumeStream, finishStream]
  );

  // On mount and on every thread switch, ask the server where the thread stands.
  useEffect(() => {
    if (!activeThreadId || !user) {
      setTimeout(() => {
        setStatusData(null);
        setCanUndo(false);
      }, 0);
      return;
    }
    let cancelled = false;
    void (async () => {
      const status = await refreshStatus(activeThreadId);
      if (cancelled || !status) return;
      if (activeThreadIdRef.current !== activeThreadId) return;
      if (status.running) {
        void attachToRun(activeThreadId);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeThreadId, user, refreshStatus, attachToRun]);

  // Detach when the user leaves the thread. The run keeps going server-side;
  // coming back re-attaches through the effect above.
  useEffect(() => {
    const streamingThread = streamThreadIdRef.current;
    if (streamingThread && streamingThread !== activeThreadId) {
      streamAbortRef.current?.abort();
      streamAbortRef.current = null;
      streamThreadIdRef.current = null;
      setStreaming(false);
      sendingRef.current = false;
      setCurrentStepLabel(null);
      setStopNotice(null);
    }
  }, [activeThreadId]);

  useEffect(() => () => streamAbortRef.current?.abort(), []);

  /**
   * The checkpoint says the graph is paused but no widget is on screen.
   *
   * Happens when the turn's assistant message never landed (a crash mid-write)
   * or when the widget rode on a message that is no longer the tail. The
   * checkpoint's live interrupt is authoritative, so trust it and re-render.
   */
  useEffect(() => {
    if (!statusData || !activeThreadId) return;
    if (statusData.session_id !== activeThreadId) return;
    if (!statusData.interrupted || statusData.running) return;
    if (streaming || sendingRef.current) return;
    if (!conversation || conversation.id !== activeThreadId) return;
    if (hasTrailingWidget(conversation.blocks)) return;

    const repaired = buildWidgetBlocks(
      `status-${statusData.run_id ?? activeThreadId}`,
      statusData.map_data,
      statusData.pending_action
    );
    if (repaired.length === 0) return;

    setTimeout(() => {
      setConversation((prev) =>
        prev && prev.id === activeThreadId
          ? { ...prev, blocks: [...prev.blocks, ...repaired] }
          : prev
      );
    }, 0);
  }, [statusData, conversation, activeThreadId, streaming]);

  // ── Actions ────────────────────────────────────────────────────────────────

  const setActiveThread = useCallback(
    async (threadId: string) => {
      if (threadId === activeThreadId) return;
      setActiveThreadId(threadId);
      setConversation(undefined);
      setInputMode('chat');
      setChatDisable(false);
    },
    [activeThreadId]
  );

  const createNewChat = useCallback(async (): Promise<string> => {
    try {
      const { thread_id } = await createChatMutation.mutateAsync();
      setActiveThreadId(thread_id);
      setConversation({ id: thread_id, blocks: [] });
      setInputMode('chat');
      setChatDisable(false);
      router.push(`/chat/${thread_id}`);
      return thread_id;
    } catch (error) {
      console.error('Failed to create new chat', error);
      throw error;
    }
  }, [createChatMutation, router]);

  const resetChat = useCallback(() => {
    clearingRef.current = true;
    setActiveThreadId(null);
    setConversation(undefined);
    setCurrentStepLabel(null);
    setInputMode('chat');
    setChatDisable(false);
  }, []);

  const deleteThread = useCallback(
    async (threadId: string): Promise<boolean> => {
      try {
        await deleteThreadMutation.mutateAsync(threadId);
        if (activeThreadId === threadId) {
          clearingRef.current = true;
          setConversation(undefined);
          setActiveThreadId(null);
        }
        return true;
      } catch (error) {
        console.error('Failed to delete thread', error);
        return false;
      }
    },
    [deleteThreadMutation, activeThreadId]
  );

  const renameThread = useCallback(
    async (threadId: string, title: string): Promise<boolean> => {
      try {
        await updateThreadMutation.mutateAsync({
          threadId,
          payload: { title },
        });
        return true;
      } catch (error) {
        console.error('Failed to rename thread', error);
        return false;
      }
    },
    [updateThreadMutation]
  );

  const updateThreadStar = useCallback(
    async (threadId: string, starred: boolean): Promise<boolean> => {
      try {
        await updateThreadMutation.mutateAsync({
          threadId,
          payload: { starred },
        });
        return true;
      } catch (error) {
        console.error('Failed to update thread star', error);
        return false;
      }
    },
    [updateThreadMutation]
  );

  const updateBlock = useCallback(
    (blockId: string, updater: (b: Block) => Block) => {
      setConversation((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          blocks: prev.blocks.map((b) => (b.id === blockId ? updater(b) : b)),
        };
      });
    },
    []
  );

  const clearComposerPrefill = useCallback(() => setComposerPrefill(null), []);
  const dismissStopNotice = useCallback(() => setStopNotice(null), []);

  const markFailed = useCallback((blockId: string, threadId: string | null) => {
    if (!threadId) return;
    setConversation((prev) =>
      prev && prev.id === threadId
        ? {
            ...prev,
            blocks: prev.blocks.map((b) =>
              b.id === blockId && b.type === 'message'
                ? { ...b, status: 'failed' as const }
                : b
            ),
          }
        : prev
    );
  }, []);

  const stopGeneration = useCallback(async () => {
    const threadId = streamThreadIdRef.current || activeThreadIdRef.current;
    if (!threadId) return;

    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
    streamThreadIdRef.current = null;
    setStreaming(false);
    sendingRef.current = false;
    setCurrentStepLabel(null);
    // Stopping means "not this" — a message queued behind it goes too.
    setQueued(null);
    // The POST below can take a few seconds (it awaits the server's own
    // persist-drain) — show something immediately rather than leaving the UI
    // looking inert until it resolves.
    setStopNotice({ value: '', isWidget: false, outcome: 'pending' });

    // Returns only once the server has committed the partial answer, so the
    // history refetch below is guaranteed to see it.
    const result = await cancelChatRunAction(threadId);

    if (!result.success || !result.data) {
      setStopNotice({ value: '', isWidget: false, outcome: 'error' });
      trackEvent('chat_run_stopped', { thread_id: threadId, outcome: 'error' });
      void refreshStatus(threadId);
      return;
    }

    const outcome = result.data.outcome;
    trackEvent('chat_run_stopped', { thread_id: threadId, outcome });

    // 'unsent' means the graph never consumed the answer, so stop meant
    // "un-submit". Mirror that locally instead of leaving the message sitting
    // above a widget that is asking the same question again.
    if (outcome === 'unsent') {
      setConversation((prev) => {
        if (!prev || prev.id !== threadId) return prev;
        const blocks = [...prev.blocks];
        for (let i = blocks.length - 1; i >= 0; i--) {
          const b = blocks[i];
          if (b.type === 'message' && b.role === 'user') {
            blocks.length = i;
            break;
          }
        }
        return { ...prev, blocks };
      });
      const restored = result.data.restored_value || '';
      if (restored) {
        const widget = isWidgetAnswer(restored);
        if (!widget) setComposerPrefill(restored);
        setStopNotice({ value: restored, isWidget: widget, outcome });
      } else {
        setStopNotice(null);
      }
    } else if (outcome === 'kept' || outcome === 'publish_interrupted') {
      // Nothing to un-send, but the user still pressed Stop and deserves to know
      // what it left behind — especially for publish, where PAUSED Meta objects
      // now exist that the next publish will resume from.
      setStopNotice({ value: '', isWidget: false, outcome });
    } else {
      // 'not_running' — the pending notice set above has nothing to resolve to.
      setStopNotice(null);
    }

    queryClient.invalidateQueries({ queryKey: ['chat-history', threadId] });
    void refreshStatus(threadId);
  }, [queryClient, refreshStatus, setQueued]);

  const rewindTo = useCallback(async (messageId?: string, value?: string) => {
    const threadId = activeThreadIdRef.current;
    if (!threadId || streaming || sendingRef.current) return;

    sendingRef.current = true;
    setCanUndo(false);
    setStreaming(true);
    setCurrentStepLabel(value ? 'Re-running from your change' : 'Going back to that step');
    setComposerPrefill(null);
    setStopNotice(null);

    const controller = new AbortController();
    streamAbortRef.current = controller;
    streamThreadIdRef.current = threadId;

    try {
      const response = await fetch(`/api/chat/${threadId}/rewind`, {
        method: 'POST',
        body: JSON.stringify({
          message_id: messageId ?? null,
          value: value ?? null,
        }),
        signal: controller.signal,
      });
      if (!response.ok) {
        const errorData = await response
          .json()
          .catch(() => ({ detail: 'Failed to rewind' }));
        // detail is a string for most refusals but an object ({code, message})
        // for run_busy — reading it as a string turned that into "Failed to rewind".
        throw new Error(
          typeof errorData.detail === 'string'
            ? errorData.detail
            : typeof errorData.detail?.message === 'string'
              ? errorData.detail.message
              : 'Failed to rewind'
        );
      }
      await consumeStream(response, threadId);
      finishStream(threadId);
    } catch (error) {
      const aborted = (error as Error)?.name === 'AbortError';
      if (!aborted) {
        console.error('Failed to rewind:', error);
        // Every backend guard (busy run, published campaign, un-rewindable
        // message, interrupted fork) used to land here and vanish — the button
        // looked like it did nothing. Surface the real reason instead.
        const message =
          error instanceof Error && error.message
            ? error.message
            : 'Failed to rewind.';
        setStopNotice({ value: message, isWidget: false, outcome: 'error' });
      }
      setStreaming(false);
      sendingRef.current = false;
      setCurrentStepLabel(null);
      streamAbortRef.current = null;
      streamThreadIdRef.current = null;
      // refreshStatus re-derives can_undo from the server — it was left false
      // (set at the top of this function) and a failed rewind must not leave
      // the button permanently dead.
      void refreshStatus(threadId);
    }
  }, [consumeStream, finishStream, refreshStatus, streaming]);

  const sendMessage = useCallback(
    async (
      content: string,
      isResume: boolean = false
    ): Promise<string | null> => {
      if (!content.trim()) return null;
      if (streaming || sendingRef.current) {
        // Free text typed while Punk is working is HELD, not dropped. Widget
        // answers are never held: a double-click would answer the NEXT question.
        if (!isResume && inputMode !== 'widget') {
          setQueued({ content, threadId: activeThreadIdRef.current });
        }
        return null;
      }

      setChatDisable(false);
      setCurrentStepLabel('Analyzing request');
      setComposerPrefill(null);
      setStopNotice(null);
      setCanUndo(false);

      sendingRef.current = true;

      let currentThreadId = activeThreadId;

      const userBlockId = crypto.randomUUID();
      const userMsg: Block = {
        id: userBlockId,
        type: 'message',
        role: 'user',
        content,
        status: 'complete',
        createdAt: new Date().toISOString(),
      };

      trackEvent('Chat Message Sent', {
        thread_id: currentThreadId || undefined,
        message_length: content.length,
        is_first_message: !currentThreadId,
      });
      trackEvent('chat_message_sent', {
        thread_id: currentThreadId || undefined,
        message_length: content.length,
        is_first_message: !currentThreadId,
      });

      setConversation((prev) => {
        if (!prev) {
          return { id: currentThreadId || 'pending', blocks: [userMsg] };
        }
        return { ...prev, blocks: [...prev.blocks, userMsg] };
      });

      setStreaming(true);

      if (!currentThreadId) {
        try {
          const { thread_id } = await createChatMutation.mutateAsync();

          currentThreadId = thread_id;

          setActiveThreadId(thread_id);

          setConversation((prev) => (prev ? { ...prev, id: thread_id } : prev));
          router.replace(`/chat/${thread_id}`);
          if (typeof window !== 'undefined') {
            window.history.replaceState(null, '', `/chat/${thread_id}`);
          }
        } catch (error) {
          console.error('Failed to auto-create thread', error);
          setStreaming(false);
          sendingRef.current = false;
          return null;
        }
      }

      const controller = new AbortController();
      streamAbortRef.current = controller;
      streamThreadIdRef.current = currentThreadId;

      // Whether any part of the answer reached the screen. A failure before this
      // means the turn never started and the message can be marked failed; after
      // it, the transcript is real and must be left alone.
      let opened = false;

      try {
        let response: Response;
        const useResume = isResume || inputMode === 'widget';
        if (useResume) {
          response = await fetch(`/api/chat/${currentThreadId}/resume`, {
            method: 'POST',
            body: JSON.stringify({ value: content }),
            signal: controller.signal,
          });
        } else {
          response = await fetch('/api/chat', {
            method: 'POST',
            body: JSON.stringify({
              session_id: currentThreadId,
              message: content,
            }),
            signal: controller.signal,
          });
        }

        if (process.env.NODE_ENV === 'development') {
          window.dispatchEvent(new CustomEvent('dev-log', { detail: { eventType: 'API_FETCH', endpoint: useResume ? 'resume' : 'new', threadId: currentThreadId } }));
        }

        if (!response.ok) {
          const errorData = await response
            .json()
            .catch(() => ({ detail: 'Failed to send message' }));

          // 409 from /chat means the thread is paused at a widget the client
          // was not showing. The server hands back the live pending_action so
          // the UI can re-render it instead of corrupting the thread.
          const pendingAction =
            response.status === 409 && typeof errorData.detail === 'object'
              ? errorData.detail?.pending_action
              : null;
          if (pendingAction) {
            const threadIdForWidget = currentThreadId;
            setConversation((prev) =>
              prev && prev.id === threadIdForWidget
                ? {
                    ...prev,
                    blocks: [
                      ...prev.blocks.filter((b) => b.id !== userBlockId),
                      ...buildWidgetBlocks(
                        `conflict-${Date.now()}`,
                        null,
                        pendingAction
                      ),
                    ],
                  }
                : prev
            );
            setStreaming(false);
            sendingRef.current = false;
            setCurrentStepLabel(null);
            streamAbortRef.current = null;
            streamThreadIdRef.current = null;
            return currentThreadId;
          }

          // 409 run_busy: a turn for this thread is ALREADY running (a second tab,
          // a double-submit that beat the local guard). The message was not lost —
          // the run owns it. Drop the optimistic block and join the live stream
          // instead of reporting a failure the user cannot act on.
          if (
            response.status === 409 &&
            typeof errorData.detail === 'object' &&
            errorData.detail?.code === 'run_busy'
          ) {
            const busyThreadId = currentThreadId;
            setConversation((prev) =>
              prev && prev.id === busyThreadId
                ? { ...prev, blocks: prev.blocks.filter((b) => b.id !== userBlockId) }
                : prev
            );
            streamAbortRef.current = null;
            streamThreadIdRef.current = null;
            sendingRef.current = false;
            setStreaming(false);
            void attachToRun(busyThreadId);
            return busyThreadId;
          }

          const errorMessage = typeof errorData.detail === 'string' ? errorData.detail : (errorData.detail?.message || 'Failed to send message');
          throw new Error(errorMessage);
        }

        opened = true;
        await consumeStream(response, currentThreadId);
      } catch (error: unknown) {
        // AbortError just means this client detached — the run continues on the
        // server and the attach effect picks it up when the user returns.
        if ((error as Error)?.name !== 'AbortError') {
          console.error('Error sending message:', error);
          queryClient.invalidateQueries({ queryKey: ['user'] });
          // The server never took the message. Left as-is it sits in the
          // transcript forever waiting for a reply that will never come.
          if (!opened) markFailed(userBlockId, currentThreadId);
        }
        setCurrentStepLabel(null);
        setStreaming(false);
        sendingRef.current = false;
        if (streamThreadIdRef.current === currentThreadId) {
          streamAbortRef.current = null;
          streamThreadIdRef.current = null;
        }
        return null;
      }

      finishStream(currentThreadId);

      if (!currentThreadId) {
        throw new Error('Thread ID was not initialized');
      }

      return currentThreadId;
    },
    [
      activeThreadId,
      createChatMutation,
      queryClient,
      inputMode,
      streaming,
      router,
      consumeStream,
      finishStream,
      markFailed,
      attachToRun,
      setQueued,
    ]
  );

  // What runs when a run ends (see finishStream): send the held message — unless
  // the user has since switched to another conversation, in which case it was
  // never meant for this one.
  useEffect(() => {
    drainQueuedRef.current = () => {
      const held = queuedRef.current;
      if (!held) return;
      setQueued(null);
      if (held.threadId !== activeThreadIdRef.current) return;
      void sendMessage(held.content);
    };
  }, [sendMessage, setQueued]);

  const cancelQueuedMessage = useCallback(() => setQueued(null), [setQueued]);

  /**
   * Re-send the answer a stop threw away, byte for byte.
   *
   * Matters most for widget answers: a map pin or a filled campaign form is not
   * something anyone wants to redo by hand, and the composer can't hold it. The
   * step is still waiting, so this is an ordinary resume.
   */
  const resendStopped = useCallback(async () => {
    const pendingValue = stopNotice?.value;
    if (!pendingValue) return;
    setStopNotice(null);
    await sendMessage(pendingValue, true);
  }, [stopNotice, sendMessage]);

  const retrySend = useCallback(
    async (blockId: string) => {
      const block = conversation?.blocks.find((b) => b.id === blockId);
      if (!block || block.type !== 'message' || !block.content) return;
      setConversation((prev) =>
        prev
          ? { ...prev, blocks: prev.blocks.filter((b) => b.id !== blockId) }
          : prev
      );
      // inputMode still reflects whether a widget is pending, so sendMessage
      // picks /resume or /chat on its own — same as the original attempt.
      await sendMessage(block.content);
    },
    [conversation, sendMessage]
  );

  const value = useMemo(
    () => ({
      threads,
      starredThreads,
      conversation,
      activeThreadId,
      loading:
        historyLoading ||
        createChatMutation.isPending ||
        deleteThreadMutation.isPending,
      streaming,
      currentStepLabel,
      updateBlock,
      sendMessage,
      queuedMessage,
      cancelQueuedMessage,
      createNewChat,
      setActiveThread,
      deleteThread,
      renameThread,
      updateThreadStar,
      refreshThreads: async () => {
        await refreshThreads();
      },
      refreshStarredThreads: async () => {
        await refreshStarredThreads();
      },
      resetChat,
      chatDisable,
      threadsLoading: threadsLoading || (!!user && !threadsData),
      starredThreadsLoading:
        starredThreadsLoading || (!!user && !starredThreadsData),
      inputMode,
      selectedPoiAddress,
      setSelectedPoiAddress,
      fetchNextThreads,
      hasNextThreads,
      isFetchingNextThreads,
      isHistoryError,
      historyError: (historyError as Error) || null,
      stopGeneration,
      rewindTo,
      canUndo,
      composerPrefill,
      clearComposerPrefill,
      stopNotice,
      dismissStopNotice,
      resendStopped,
      retrySend,
    }),
    [
      threads,
      starredThreads,
      conversation,
      activeThreadId,
      historyLoading,
      isHistoryError,
      historyError,
      createChatMutation.isPending,
      deleteThreadMutation.isPending,
      streaming,
      currentStepLabel,
      updateBlock,
      sendMessage,
      queuedMessage,
      cancelQueuedMessage,
      createNewChat,
      setActiveThread,
      deleteThread,
      renameThread,
      updateThreadStar,
      refreshThreads,
      refreshStarredThreads,
      resetChat,
      chatDisable,
      threadsLoading,
      starredThreadsLoading,
      threadsData,
      starredThreadsData,
      user,
      inputMode,
      selectedPoiAddress,
      setSelectedPoiAddress,
      fetchNextThreads,
      hasNextThreads,
      isFetchingNextThreads,
      stopGeneration,
      rewindTo,
      canUndo,
      composerPrefill,
      clearComposerPrefill,
      stopNotice,
      dismissStopNotice,
      resendStopped,
      retrySend,
    ]
  );

  return (
    <ChatContext.Provider value={value}>
      {children}
    </ChatContext.Provider>
  );
};

export const useChat = () => {
  const context = useContext(ChatContext);
  if (context === undefined) {
    throw new Error('useChat must be used within a ChatProvider');
  }
  return context;
};
