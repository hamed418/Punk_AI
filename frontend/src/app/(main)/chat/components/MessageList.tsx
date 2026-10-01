'use client';
import { Box } from '@mantine/core';
import { ChevronDown, ChevronUp } from 'lucide-react';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { awaitingReply, laterMessageCount, rewindableIds } from '@/lib/rewind';
import { useAuth } from '../../../../contexts/AuthContext';
import { useChat } from '../../../../contexts/ChatContext';
import { useSidebar } from '@/contexts/SidebarContext';
import { BlockRenderer } from './blocks/BlockRenderer';
import { AgentLogoStack } from './blocks/MessageBlockUI';
import { TextShimmer } from './thinking/TextShimmer';

interface MessageListProps {
  streaming: boolean;
  isNewChat?: boolean;
  onSendMessage?: (content: string) => void;
  isWidgetOpen?: boolean;
  activeWidgetHeight?: number;
  showEarlyAccessBanner?: boolean;
}

const isMapOrSplitView = (
  block: Record<string, unknown> | null | undefined
) => {
  if (!block) return false;
  const content = block.content;
  if (!content || typeof content !== 'object') return false;
  const actionType = (content as Record<string, unknown>).action_type;
  if (typeof actionType !== 'string') return false;
  const splitViewActions = [
    'maid_split_view',
    'radius_picker',
    'poi_radius_picker',
    'map_interaction',
    'radius_selection',
  ];
  return splitViewActions.includes(actionType);
};

const MessageList: React.FC<MessageListProps> = ({
  streaming,
  onSendMessage,
  isWidgetOpen = false,
  activeWidgetHeight = 0,
  showEarlyAccessBanner = true,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const topRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollParentRef = useRef<HTMLElement | Window | null>(null);
  const { user } = useAuth();
  const { conversation, sendMessage, currentStepLabel, activeThreadId } =
    useChat();
  const [atBottom, setAtBottom] = useState(true);
  const [windowWidth, setWindowWidth] = useState(0);

  useEffect(() => {
    const update = () => setWindowWidth(window.innerWidth);
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  const getWidgetButtonGap = (width: number) => {
    if (width < 640) return 80;
    if (width < 770) return 90;
    return 90;
  };

  const { isSidebarOpen } = useSidebar();
  const isLgScreen = windowWidth >= 1024 && windowWidth < 1280;
  const isSmOrMdScreen = windowWidth > 0 && windowWidth < 1024;

  const shouldMoveAboveWidget =
    isWidgetOpen && (isSmOrMdScreen || (isLgScreen && isSidebarOpen));

  const isSmallScreen = windowWidth > 0 && windowWidth < 770;

  const blocks = useMemo(() => conversation?.blocks || [], [conversation]);
  const lastUserBlockIdx = useMemo(() => {
    for (let i = blocks.length - 1; i >= 0; i--) {
      const b = blocks[i];
      if (b.type === 'message' && b.role === 'user') return i;
    }
    return -1;
  }, [blocks]);

  // Which user answers can be rewound — the rule mirrors the server's plan_rewind
  // (see lib/rewind.ts), so a button is only offered where the server will honour it.
  const rewindable = useMemo(() => rewindableIds(blocks), [blocks]);
  // The newest rewindable answer keeps its Edit / Change action visible; older ones
  // reveal it on hover. Without this the feature is invisible until you happen to
  // hover the right message — and never appears on touch screens.
  const newestRewindableId = useMemo(() => {
    for (let i = blocks.length - 1; i >= 0; i--) {
      const b = blocks[i];
      if (b.type === 'message' && b.role === 'user' && rewindable.has(b.id)) return b.id;
    }
    return null;
  }, [blocks, rewindable]);

  // Retry re-sends the answer that produced the last assistant turn — the same
  // "regenerate" affordance every assistant offers on its newest reply.
  const retrySource = useMemo(() => {
    if (lastUserBlockIdx === -1) return null;
    const b = blocks[lastUserBlockIdx];
    if (b.type !== 'message' || !rewindable.has(b.id)) return null;
    const isLastBlock = lastUserBlockIdx === blocks.length - 1;
    if (isLastBlock) return null; // nothing was answered yet
    return {
      id: b.id,
      content: b.content,
      laterCount: laterMessageCount(blocks, b.id),
    };
  }, [blocks, lastUserBlockIdx, rewindable]);
  const shouldScrollInstantlyRef = useRef(true);

  const doScrollToBottom = useCallback((instant = false) => {
    // Traverse live from containerRef each time — no stale ref issues after chat switch/refresh.
    const rootElement = containerRef.current;
    if (!rootElement) return;

    const behavior = instant ? 'auto' : 'smooth';

    let current: HTMLElement | null = rootElement.parentElement;
    while (current) {
      const { overflowY } = window.getComputedStyle(current);
      if (/(auto|scroll|overlay)/.test(overflowY)) {
        current.scrollTo({ top: current.scrollHeight, behavior });
        return;
      }
      current = current.parentElement;
    }
    window.scrollTo({
      top: document.documentElement.scrollHeight,
      behavior,
    });
  }, []);

  useEffect(() => {
    shouldScrollInstantlyRef.current = true;
  }, [activeThreadId]);

  useEffect(() => {
    if (blocks.length > 0) {
      const instant = shouldScrollInstantlyRef.current;
      doScrollToBottom(instant);
      if (shouldScrollInstantlyRef.current) {
        shouldScrollInstantlyRef.current = false;
      }
    }
  }, [blocks, streaming, doScrollToBottom]);

  useEffect(() => {
    if (isWidgetOpen) {
      doScrollToBottom(false);
    }
  }, [isWidgetOpen, doScrollToBottom]);

  const [isScrollable, setIsScrollable] = useState(false);

  const getScrollContainer = useCallback((): HTMLElement | Window => {
    const rootElement = containerRef.current;
    if (!rootElement) return window;

    // Check if any parent with overflow has scrollable content
    let current: HTMLElement | null = rootElement.parentElement;
    while (current) {
      const styles = window.getComputedStyle(current);
      if (
        /(auto|scroll|overlay)/.test(styles.overflowY) &&
        current.scrollHeight > current.clientHeight
      ) {
        return current;
      }
      current = current.parentElement;
    }

    // Check if window/document has scrollable content
    if (document.documentElement.scrollHeight > window.innerHeight) {
      return window;
    }

    // Fallback to nearest overflow container
    current = rootElement.parentElement;
    while (current) {
      const styles = window.getComputedStyle(current);
      if (/(auto|scroll|overlay)/.test(styles.overflowY)) {
        return current;
      }
      current = current.parentElement;
    }

    return window;
  }, []);

  const updateScrollState = useCallback(() => {
    const rootElement = containerRef.current;
    if (!rootElement) return;

    const scrollParent = getScrollContainer();
    scrollParentRef.current = scrollParent;

    let scrollTop = 0;
    let scrollHeight = 0;
    let clientHeight = 0;

    if (scrollParent === window) {
      scrollTop = window.scrollY || document.documentElement.scrollTop;
      scrollHeight = document.documentElement.scrollHeight;
      clientHeight = window.innerHeight;
    } else {
      const scrollElement = scrollParent as HTMLElement;
      scrollTop = scrollElement.scrollTop;
      scrollHeight = scrollElement.scrollHeight;
      clientHeight = scrollElement.clientHeight;
    }

    const maxScrollTop = scrollHeight - clientHeight;
    // Exactly matches whether a vertical scrollbar exists (content overflows container)
    const hasScrollbar = scrollHeight > clientHeight;

    setIsScrollable(hasScrollbar);
    setAtBottom(scrollTop >= Math.max(maxScrollTop - 30, 0));
  }, [getScrollContainer]);

  useEffect(() => {
    const rootElement = containerRef.current;

    if (!rootElement) {
      return;
    }

    const update = () => updateScrollState();
    update();

    const scrollParent = getScrollContainer();
    scrollParentRef.current = scrollParent;

    scrollParent.addEventListener('scroll', update, { passive: true });
    window.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update, { passive: true });

    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(() => {
        update();
      });
      ro.observe(rootElement);
      if (scrollParent !== window && scrollParent instanceof HTMLElement) {
        ro.observe(scrollParent);
      }
    }

    return () => {
      scrollParent.removeEventListener('scroll', update);
      window.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
      ro?.disconnect();
    };
  }, [getScrollContainer, updateScrollState]);

  useEffect(() => {
    updateScrollState();
    const t1 = setTimeout(updateScrollState, 50);
    const t2 = setTimeout(updateScrollState, 200);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [
    blocks,
    streaming,
    isWidgetOpen,
    activeWidgetHeight,
    activeThreadId,
    updateScrollState,
  ]);

  const lastScrolledBlockRef = useRef<string | null>(null);
  const scrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reset guard when the block list grows (new message arrived).
  useEffect(() => {
    lastScrolledBlockRef.current = null;
  }, [blocks.length]);

  // Scroll immediately AND after the CSS grid transition (duration-200 = 200ms) so
  // the copy-button row is fully in view regardless of animation timing.
  const scrollToBottomOnce = (blockId: string) => {
    if (lastScrolledBlockRef.current === blockId) return;
    lastScrolledBlockRef.current = blockId;
    if (scrollTimerRef.current) clearTimeout(scrollTimerRef.current);
    doScrollToBottom();
    scrollTimerRef.current = setTimeout(doScrollToBottom, 210);
  };

  const resetLastScrolledBlock = () => {
    lastScrolledBlockRef.current = null;
  };

  const handleToggleScroll = () => {
    const parent = scrollParentRef.current || getScrollContainer();

    if (atBottom) {
      setAtBottom(false);
      if (parent) {
        parent.scrollTo({ top: 0, behavior: 'smooth' });
      }
      topRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else {
      setAtBottom(true);
      doScrollToBottom(false);
    }
  };

  const handleQuickAction = (text: string) => {
    if (onSendMessage) {
      onSendMessage(text);
    } else {
      sendMessage(text);
    }
  };

  return (
    <Box ref={containerRef} className="font-body relative w-full">
      <Box ref={topRef} />
      <Box className="flex flex-col">
        {blocks.length === 0 ? (
          <Box className="animate-fade-in mx-auto flex w-full max-w-4xl flex-1 flex-col items-start justify-end pb-12 text-left">
            <Box className="mb-6 flex items-center gap-3 sm:gap-4">
              <Box className="h-8 w-8 transition-transform duration-500 hover:scale-110">
                <img src="/logo.svg" alt="Punk AI" className="h-full w-full" />
              </Box>
              <h2 className="font-display text-foreground text-3xl font-bold tracking-tight sm:text-4xl md:text-5xl">
                Welcome back,{' '}
                <span className="text-primary-600">
                  {user?.full_name?.split(' ')[0] || 'User'}
                </span>
              </h2>
            </Box>

            <p className="text-muted-foreground mb-8 max-w-xl text-[13px] font-medium sm:text-[14px]">
              How shall we optimize your advertising infrastructure today?
              Select a neural protocol below or initiate a custom query.
            </p>

            <Box className="flex w-full max-w-md flex-col gap-4">
              {[
                { text: 'Plan a high-conversion multi-channel campaign' },
                { text: 'Analyze my current ads for better performance' },
                { text: 'Identify my most profitable customer segments' },
                { text: 'Generate high-impact ad copy and headlines' },
              ].map((item, i) => (
                <button
                  type="button"
                  key={item.text}
                  onClick={() => handleQuickAction(item.text)}
                  style={{ animationDelay: `${i * 100}ms` }}
                  className="group btn-gradient- animate-popup flex items-center justify-between gap-4 rounded-xl border px-5 py-3 text-left transition-all active:scale-[0.98]"
                >
                  <Box className="flex flex-col">
                    <span className="text-foreground text-[12px] transition-colors md:text-[13px] lg:text-[14px]">
                      {item.text}
                    </span>
                  </Box>
                  <Box className="flex h-5 w-5 items-center justify-center rounded-full border opacity-0 transition-opacity group-hover:opacity-100">
                    <span className="text-muted-foreground group-hover:text-foreground text-[10px]">
                      →
                    </span>
                  </Box>
                </button>
              ))}
            </Box>
          </Box>
        ) : (
          <Box className="relative mx-auto w-full lg:px-2 xl:px-0">
            {blocks.map((block, index) => {
              const canRewind =
                block.type === 'message' && rewindable.has(block.id);
              // What changing this answer would discard — shown before it acts.
              const laterCount = canRewind
                ? laterMessageCount(blocks, block.id)
                : 0;
              // Only the newest assistant reply gets Retry.
              const retryFor =
                block.type === 'message' &&
                block.role !== 'user' &&
                index === blocks.length - 1
                  ? retrySource
                  : null;
              const isFirstAi =
                blocks.findIndex(
                  (b) => b.type !== 'message' || b.role !== 'user'
                ) === index;
              const isLatest =
                index === blocks.length - 1 || index === blocks.length - 2;
              const isStrictlyLatest = index === blocks.length - 1;

              const nextBlock = blocks[index + 1];
              // const prevBlock = blocks[index - 1]
              const userResponse =
                nextBlock?.type === 'message' && nextBlock.role === 'user'
                  ? nextBlock.content
                  : null;
              // Last AI message gets an onMouseEnter scroll so the copy
              // button row (which expands below) is always fully visible.
              const isLastAiMsg =
                isStrictlyLatest &&
                block.type === 'message' &&
                (block as { role?: string }).role !== 'user';

              return (
                <React.Fragment key={block.id}>
                  {isMapOrSplitView(block) && (
                    <React.Fragment>
                      {/* {prevBlock && !isMapOrSplitView(prevBlock) && (
                        <Box className="mx-auto mb-8 mt-8 w-full max-w-4xl px-2 opacity-40 lg:max-w-7xl">
                          <Box className="w-full border-t border-dotted border-[#50504C]" />
                        </Box>
                      )} */}
                      <Box className="group animate-fade-in font-body mx-auto mb-3 flex w-full max-w-4xl justify-start px-2">
                        <Box className="flex w-full min-w-0 flex-col gap-6">
                          <Box className="w-full">
                            {/* <Box className="chat-markdown max-w-none font-medium text-foreground/90 text-md leading-relaxed tracking-tight">
															User has been confirmed lookback window.
														</Box> */}
                          </Box>
                        </Box>
                      </Box>
                    </React.Fragment>
                  )}
                  <div
                    onMouseMove={
                      isLastAiMsg
                        ? () => scrollToBottomOnce(block.id)
                        : undefined
                    }
                    onMouseLeave={
                      isLastAiMsg ? resetLastScrolledBlock : undefined
                    }
                  >
                    <BlockRenderer
                      block={block}
                      isFirstAiMessage={isFirstAi}
                      isLatest={isLatest}
                      isStrictlyLatest={isStrictlyLatest}
                      canRewind={canRewind}
                      laterCount={laterCount}
                      emphasizeActions={block.id === newestRewindableId}
                      retryFor={retryFor}
                      userResponse={userResponse}
                    />
                  </div>
                  {/* {isMapOrSplitView(block) &&
                    nextBlock &&
                    !isMapOrSplitView(nextBlock) && (
                      <Box className="mx-auto mt-11 w-full max-w-4xl px-2 opacity-40 lg:max-w-7xl">
                        <Box className="w-full border-t border-dotted border-red-900!" />
                      </Box>
                    )} */}
                </React.Fragment>
              );
            })}

            {/* Icon at the bottom: static logo when done, or initial loading state before first AI block */}
            <Box className="mx-auto mt-2 w-full max-w-207.5">
              {/* {!streaming && (
                <AnimatedPunkSvgIcon className="w-12 cursor-pointer transition-transform duration-500 hover:scale-110" />
              )} */}
              {streaming && awaitingReply(blocks) && (
                  <div className="group animate-fade-in font-body mb-3 flex w-full justify-start">
                    <div className="flex w-full min-w-0 flex-col gap-6">
                      <div className="w-full">
                        <div
                          className="mt-2 mb-4 w-full overflow-hidden transition-all delay-0 duration-200 ease-in-out"
                          style={{ maxWidth: '56rem' }}
                        >
                          <button
                            type="button"
                            className="font-ocrx! flex w-max cursor-default items-center text-[16px]! leading-6! font-black tracking-[0.02em] uppercase transition-opacity"
                          >
                            <Box className="mr-2">
                              <AgentLogoStack
                                count={1}
                                animated={true}
                                scale={0.3}
                              />
                            </Box>
                            <TextShimmer className="font-black">
                              {currentStepLabel || 'thinking something'}
                            </TextShimmer>
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
            </Box>

            <Box
              ref={bottomRef}
              className={`${showEarlyAccessBanner ? 'h-22' : 'h-28'} transition-all duration-200`}
            />
          </Box>
        )}
      </Box>

      {isScrollable && (
        <button
          type="button"
          onClick={handleToggleScroll}
          aria-label={atBottom ? 'Scroll to top' : 'Scroll to bottom'}
          className={
            shouldMoveAboveWidget
              ? `fixed right-1.75 z-1001 flex cursor-pointer items-center justify-center rounded-full transition-transform duration-200 hover:scale-105 active:scale-95 md:right-2 ${
                  isSmallScreen ? 'h-8 w-8' : 'h-10 w-10'
                }`
              : `fixed right-1.75 bottom-20! z-1001 flex cursor-pointer items-center justify-center rounded-full transition-transform duration-200 hover:scale-105 active:scale-95 md:right-2 md:bottom-34 md:h-10 md:w-10 xl:right-10 xl:bottom-12 ${
                  isWidgetOpen && isSmallScreen ? 'h-8 w-8' : 'h-8 w-8'
                }`
          }
          style={{
            bottom:
              shouldMoveAboveWidget && windowWidth > 0
                ? `${activeWidgetHeight + getWidgetButtonGap(windowWidth)}px`
                : undefined,
            visibility: 'visible',
            background: '#FFFFFF03',
            backdropFilter: 'blur(75.9000015258789px)',
            boxShadow:
              '0px 8px 24px 0px #00000080, 0px -1px 0px 0px #00000066 inset, 0px 1px 0px 0px #FFFFFF1F inset',
          }}
        >
          <span
            className={`leading-none font-semibold ${shouldMoveAboveWidget && isSmallScreen ? 'pb-0.5 text-base' : 'text-lg'}`}
          >
            {atBottom ? <ChevronUp /> : <ChevronDown />}
          </span>
        </button>
      )}
    </Box>
  );
};

export default MessageList;
