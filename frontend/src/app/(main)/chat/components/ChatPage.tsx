'use client';

import AnimatedPunkSvgIcon from '@/components/AnimatedPunkLogo';
import { getColorIndex, onPunkColorChange } from '@/utils/handleLogoClick';
import { useChat, isWidgetAnswer } from '@/contexts/ChatContext';
import { useSidebar } from '@/contexts/SidebarContext';
import { Box, Button, Flex, ScrollArea, Skeleton, Text } from '@mantine/core';
import { useElementSize } from '@mantine/hooks';
import { useParams, notFound } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import ChatInput from './ChatInput';
import MessageList from './MessageList';
import { ActiveWidgetRenderer } from './widgets';
import WidgetAssistRow from './widgets/WidgetAssistRow';
import EditorShell from './editor/components/EditorShell';
import EditorNav from './editor/components/EditorNav';
import BuildingPane from './editor/components/BuildingPane';
import type { PendingActionBlock } from '@/types/chat';

let chatPageHasMounted = false;

const SINGLE_ACTION_TYPES = [
  'option_selection',
  'permission',
  'file_upload',
  'oauth_connect',
  'stepper_input',
  'date_range_picker',
  'campaign_intake_form',
  'campaign_plan_editor',
  'campaign_preview',
];

const ChatPage = () => {
  const params = useParams();
  const paramsThreadId = params?.threadId as string | undefined;
  const {
    conversation,
    loading,
    streaming,
    sendMessage,
    isHistoryError,
    historyError,
    stopNotice,
    dismissStopNotice,
    resendStopped,
    currentStepLabel,
  } = useChat();
  const { isSidebarOpen } = useSidebar();

  const [mounted, setMounted] = useState(chatPageHasMounted);
  const [isNewChat, setIsNewChat] = useState(!paramsThreadId);
  // True while we are switching from one existing thread to another
  const [isTransitioning, setIsTransitioning] = useState(false);
  const [logoColorIndex, setLogoColorIndex] = useState<number>(getColorIndex);

  useEffect(() => {
    return onPunkColorChange(() => {
      setLogoColorIndex(getColorIndex());
    });
  }, []);

  const lastParamsThreadId = useRef<string | undefined>(paramsThreadId);

  const { ref: widgetRef, height: widgetHeight } = useElementSize();

  // The assist row (chips + escape menu) must reach EVERY step, not just the ones
  // with a widget. activeWidgetBlock below is restricted to the types
  // ActiveWidgetRenderer can draw, so a `text_input` step — which has no widget at
  // all — would otherwise never show a way out of an off-path loop.
  //
  // Deliberately keeps the plain `streaming` bail that activeWidgetBlock below
  // no longer has: chips and the escape menu should not be live while the
  // campaign editor is mid-build, even though the editor itself stays mounted.
  // The two memos are allowed to differ here — see the SINGLE_ACTION_TYPES
  // comment below for why.
  const activeAssistContent = useMemo(() => {
    if (!conversation?.blocks || streaming) return null;
    const blocks = conversation.blocks;
    for (let i = blocks.length - 1; i >= 0; i--) {
      const block = blocks[i];
      if (block.type === 'message' && block.role === 'user') break;
      if (block.type === 'pending_action') return block.content;
      if (block.type === 'map_data') {
        const embedded = (block.content as { pending_action?: unknown })
          ?.pending_action;
        if (embedded) return embedded as PendingActionBlock['content'];
      }
    }
    return null;
  }, [conversation, streaming]);

  const activeWidgetBlock = useMemo(() => {
    if (!conversation?.blocks) return null;
    const blocks = conversation.blocks;

    // Search backwards for the last pending_action of single type
    for (let i = blocks.length - 1; i >= 0; i--) {
      const block = blocks[i];

      // If we see a user response after it, it's not active anymore — UNLESS
      // a turn is streaming and that response is a widget's own submission
      // (Q:/A:-wrapped). The campaign editor sends its intake submission that
      // way specifically so it can stay mounted and show its own build
      // progress instead of unmounting at the moment it is clicked (see
      // CampaignEditor's build state). Bounded to one crossing: anything
      // older than that single user message is history, same as before.
      if (block.type === 'message' && block.role === 'user') {
        if (streaming && isWidgetAnswer(block.content || '')) continue;
        break;
      }

      if (block.type === 'pending_action') {
        const actionType = block.content?.action_type;
        // Only the campaign editor draws its own in-place build state; every
        // other widget still disappears for the duration of its turn.
        if (streaming && actionType !== 'campaign_plan_editor') return null;
        if (SINGLE_ACTION_TYPES.includes(actionType)) {
          return block;
        }
      }
    }
    return null;
  }, [conversation, streaming]);

  // Guide mode ("Set up campaign manually in Punk") has no intake form — the
  // builder subgraph goes straight from the publish_mode pick to generating
  // the plan (see slots.py's campaign_intake `not_when=(... "guide")`), so
  // without this there is a streaming gap with nothing in the widget slot at
  // all: express already covers itself, because its intake form *is* the
  // shell from the very first question. True only for that one gap — once
  // any pending_action lands (intake for express, or the plan itself for
  // guide), activeWidgetBlock above takes over and this goes false.
  const builderBuilding = useMemo(() => {
    if (!conversation?.blocks || !streaming || activeWidgetBlock) return false;
    const blocks = conversation.blocks;
    // Whether the loop actually skipped a widget-answer message on the way
    // in. Reaching the campaign_publish_mode pending_action WITHOUT having
    // skipped one first means it's still the unanswered question itself —
    // its own streaming tail (activeWidgetBlock stays null for a moment
    // after the pending_action event lands, until `streaming` clears) — and
    // that has to render as the normal option_selection widget once
    // streaming ends, not this shell. Only "past the pick" (skipped the
    // answer to reach it) means the user already chose and the next real
    // widget is what's being built.
    let pastThePick = false;
    for (let i = blocks.length - 1; i >= 0; i--) {
      const block = blocks[i];
      // Same one-crossing exception as activeWidgetBlock above: the mode pick
      // itself is the widget answer that started this streaming turn, so skip
      // past it to reach the question it answered instead of stopping on it.
      if (block.type === 'message' && block.role === 'user') {
        if (isWidgetAnswer(block.content || '')) {
          pastThePick = true;
          continue;
        }
        break;
      }
      if (block.type === 'pending_action') {
        return pastThePick && block.content?.field === 'campaign_publish_mode';
      }
    }
    return false;
  }, [conversation, streaming, activeWidgetBlock]);

  // What actually occupies the pinned widget slot below the transcript —
  // either the real widget, or (guide mode's pre-intake gap) the shell alone.
  const showWidgetSlot = !!activeWidgetBlock || builderBuilding;

  const isFirstAi = useMemo(() => {
    if (!conversation?.blocks || !activeWidgetBlock) return false;
    const index = conversation.blocks.findIndex(
      (b) => b.id === activeWidgetBlock.id
    );
    const firstAiIndex = conversation.blocks.findIndex(
      (b) => b.type !== 'message' || b.role !== 'user'
    );
    return firstAiIndex === index;
  }, [conversation, activeWidgetBlock]);

  const handleConfirm = useCallback(
    (value: string | number) => {
      sendMessage(value.toString(), true);
    },
    [sendMessage]
  );

  useEffect(() => {
    setTimeout(() => {
      setMounted(true);
    }, 0);

    chatPageHasMounted = true;
    if (paramsThreadId) {
      setTimeout(() => {
        setIsNewChat(false);
      }, 0);

      if (paramsThreadId !== lastParamsThreadId.current) {
        // Navigating to a different thread — show loader immediately
        setIsTransitioning(true);
      }
    } else if (!streaming) {
      setTimeout(() => {
        setIsNewChat(true);
      }, 0);
    }
    lastParamsThreadId.current = paramsThreadId;
  }, [paramsThreadId, streaming]);

  // Clear the transition loader once the conversation for the new thread has arrived
  useEffect(() => {
    if (isTransitioning && conversation?.id === paramsThreadId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setIsTransitioning(false);
    }
  }, [isTransitioning, conversation, paramsThreadId]);

  // Removed the useEffect that does router.replace when activeThreadId !== paramsThreadId
  // because it was causing render loops when users navigated between chats.
  // URL is now the single source of truth for the thread context, and ChatContext
  // handles routing on new chat creations explicitly.

  const handleSendMessage = (content: string) => {
    if (!content.trim()) return;
    setIsNewChat(false);
    sendMessage(content);
  };

  const hasMessages = conversation?.blocks && conversation.blocks.length > 0;

  // Show loader whenever we have a thread URL but its conversation hasn't loaded yet
  const isWaitingForConversation =
    !!paramsThreadId && conversation?.id !== paramsThreadId;
  const textSelectionColor = [
    `selection:text-[#f54397]!`,
    `selection:text-[#26A2C1]!`,
    `selection:text-[#83EF39]!`,
    `selection:text-[#ED134F]!`,
    `selection:text-[#8C8C8C]!`,
  ];

  const [isPromptMenuOpen, setIsPromptMenuOpen] = useState(false);
  const [showEarlyAccessBanner, setShowEarlyAccessBanner] = useState(true);
  const scrollViewportRef = useRef<HTMLDivElement>(null);
  const prevWidgetSpacerHeight = useRef<number>(0);
  const prevActiveWidgetBlock =
    useRef<typeof activeWidgetBlock>(activeWidgetBlock);

  // When the widget closes, scroll to the very bottom so the chat is fully visible
  useEffect(() => {
    const wasOpen = !!prevActiveWidgetBlock.current;
    const isNowOpen = !!activeWidgetBlock;
    prevActiveWidgetBlock.current = activeWidgetBlock;

    if (wasOpen && !isNowOpen && scrollViewportRef.current) {
      // Small delay to let framer-motion begin the exit animation before we scroll
      const el = scrollViewportRef.current;
      const raf = requestAnimationFrame(() => {
        el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
      });
      return () => cancelAnimationFrame(raf);
    }
  }, [activeWidgetBlock]);

  // On chat switch, widgetHeight starts at 0 and is measured after the widget mounts.
  // Re-scroll to bottom once the height settles so messages don't hide behind the widget.
  const prevParamsThreadId = useRef(paramsThreadId);
  useEffect(() => {
    if (prevParamsThreadId.current !== paramsThreadId) {
      prevParamsThreadId.current = paramsThreadId;
      // Reset the spacer ref so onUpdate delta is correct for the new thread
      prevWidgetSpacerHeight.current = 0;
    }

    if (activeWidgetBlock && widgetHeight > 0 && scrollViewportRef.current) {
      const el = scrollViewportRef.current;
      el.scrollTo({ top: el.scrollHeight, behavior: 'auto' });
    }
  }, [widgetHeight, paramsThreadId, activeWidgetBlock]);

  // Whenever the page or thread loads with messages, ensure we scroll down to the bottom
  useEffect(() => {
    if (!hasMessages || isWaitingForConversation || isTransitioning) return;

    const el = scrollViewportRef.current;
    if (!el) return;

    let isUserScrolling = false;
    const onUserScroll = () => {
      // If user deliberately scrolled away from the bottom by more than 80px, don't hijack their scroll
      if (el.scrollHeight - el.scrollTop - el.clientHeight > 80) {
        isUserScrolling = true;
      }
    };

    el.addEventListener('wheel', onUserScroll, { passive: true });
    el.addEventListener('touchmove', onUserScroll, { passive: true });

    const scrollToBottom = () => {
      if (!isUserScrolling && scrollViewportRef.current) {
        scrollViewportRef.current.scrollTop =
          scrollViewportRef.current.scrollHeight;
      }
    };

    // Immediate scroll on load
    scrollToBottom();

    // Sequential frames and timers to keep pinned to bottom as child components, fonts, and images render
    const rafId = requestAnimationFrame(scrollToBottom);
    const timers = [
      setTimeout(scrollToBottom, 50),
      setTimeout(scrollToBottom, 150),
      setTimeout(scrollToBottom, 300),
      setTimeout(scrollToBottom, 600),
      setTimeout(scrollToBottom, 1000),
    ];

    // Observe size changes of the scroll content to keep pinned to bottom during initial layout
    const contentEl = el.firstElementChild;
    let observer: ResizeObserver | null = null;
    if (contentEl && typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => {
        scrollToBottom();
      });
      observer.observe(contentEl);
    }

    const cleanupTimer = setTimeout(() => {
      observer?.disconnect();
    }, 1500);

    return () => {
      cancelAnimationFrame(rafId);
      timers.forEach(clearTimeout);
      clearTimeout(cleanupTimer);
      observer?.disconnect();
      el.removeEventListener('wheel', onUserScroll);
      el.removeEventListener('touchmove', onUserScroll);
    };
  }, [
    conversation?.id,
    hasMessages,
    isWaitingForConversation,
    isTransitioning,
    paramsThreadId,
  ]);

  const historyErr = historyError as (Error & { isUnauthorized?: boolean }) | null;
  const isUnauthorizedError =
    historyErr?.isUnauthorized ||
    historyErr?.message?.includes('Unauthorized') ||
    historyErr?.message?.includes('401');

  if (paramsThreadId && isHistoryError && !isUnauthorizedError) {
    notFound();
  }

  return (
    <Box
      className={`font-inter! text-secondary-text relative flex h-full w-full overflow-x-hidden transition-opacity duration-700 ${mounted ? 'opacity-100' : 'opacity-0'}`}
    >
      <Box className="relative flex w-full flex-1 flex-col overflow-y-auto">
        <Box className="relative flex w-full flex-1 flex-col overflow-hidden">
          <Box className="fixed top-5 right-5 z-90 hidden lg:block"></Box>

          {(loading && !streaming) ||
            isTransitioning ||
            isWaitingForConversation ? (
            <Box className="flex flex-1 items-center justify-center">
              <Box className="animate-fade-in flex flex-col items-center gap-4">
                <Loader2 className="text-muted-foreground h-8 w-8 animate-spin" />
              </Box>
            </Box>
          ) : !hasMessages ? (
            <Box className="custom-scrollbar relative flex min-h-0 flex-1 flex-col items-center overflow-y-auto px-4 py-6 sm:px-6">
              <Box
                className={`absolute top-52 flex w-auto items-center justify-center gap-1.5 transition-opacity duration-200 ${isPromptMenuOpen
                    ? 'pointer-events-none opacity-0'
                    : 'opacity-100 delay-200!'
                  }`}
              >
              </Box>
              <Box className="my-auto flex w-full max-w-4xl flex-col items-center justify-center gap-4">
                <Box className="flex w-full max-w-4xl flex-col">
                  <Box className="mx-auto -mb-1.75 flex w-full flex-col items-center justify-center sm:-mb-3.25 lg:-mb-3.25 lg:scale-90 xl:-mb-4.75">
                    <Flex
                      w="100%"
                      maw={818}
                      gap={0}
                      align="center"
                    >
                      <AnimatedPunkSvgIcon
                        className={`ml-1 aspect-square w-15 sm:-mb-px sm:ml-2 sm:w-30 lg:-mb-2 lg:w-30 xl:mb-0 xl:ml-1.5 xl:w-30 ${
                          isSidebarOpen ? 'lg:-ml-7' : 'lg:ml-3'
                        }`}
                      />
                      {/* <PunkTargetTitle /> */}
                      <Text
                        fw={400}
                        className={`font-ocrx! text-primary-text! mt-2.5! scale-y-90! text-[20px]! md:text-[44px]! lg:text-[49px]! xl:text-[54px]! ${textSelectionColor[logoColorIndex % textSelectionColor.length]}`}
                      >
                        Find buyers from real-life behavior
                      </Text>
                    </Flex>
                  </Box>

                  <Box className="w-full">
                    <ChatInput
                      onSendMessage={handleSendMessage}
                      disabled={streaming}
                      isChatting={false}
                      onMenuToggle={setIsPromptMenuOpen}
                    />
                  </Box>
                </Box>
              </Box>
            </Box>
          ) : (
            <Box className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
              <ScrollArea
                viewportRef={scrollViewportRef}
                scrollbarSize={7}
                type="hover"
                className="custom-scrollbar absolute inset-0 overflow-y-auto px-3 lg:px-0"
              >
                <MessageList
                  streaming={streaming}
                  isNewChat={isNewChat}
                  onSendMessage={handleSendMessage}
                  isWidgetOpen={showWidgetSlot}
                  activeWidgetHeight={widgetHeight}
                  showEarlyAccessBanner={showEarlyAccessBanner}
                />
                <motion.div
                  animate={{ height: showWidgetSlot ? widgetHeight : 0 }}
                  transition={{
                    type: 'spring',
                    damping: 25,
                    stiffness: 350,
                  }}
                  style={{
                    flexShrink: 0,
                  }}
                  onUpdate={(latest) => {
                    const currentHeight =
                      typeof latest.height === 'number'
                        ? latest.height
                        : parseFloat(String(latest.height)) || 0;
                    const delta =
                      currentHeight - prevWidgetSpacerHeight.current;
                    prevWidgetSpacerHeight.current = currentHeight;

                    if (scrollViewportRef.current && delta > 0.01) {
                      scrollViewportRef.current.scrollTop += delta;
                    }
                  }}
                />
              </ScrollArea>

              <Box className="pointer-events-none absolute right-0 bottom-0 left-0 z-1000 flex flex-col bg-transparent px-2 pt-10 pb-2 lg:px-0">
                <Box className="pointer-events-auto w-full">
                  {/* Active Widget Rendered Inline Above ChatInput. Guide mode's
                      pre-intake build gap (builderBuilding) renders the same
                      editor shell here too, with no block to hand
                      ActiveWidgetRenderer — see builderBuilding above. */}
                  <AnimatePresence>
                    {showWidgetSlot && (
                      <motion.div
                        ref={widgetRef}
                        initial={{ height: 0, opacity: 0 }}
                        animate={{
                          height: 'auto',
                          opacity: 1,
                          transitionEnd: { overflow: 'visible' },
                        }}
                        exit={{ height: 0, opacity: 0, overflow: 'hidden' }}
                        transition={{
                          type: 'spring',
                          damping: 25,
                          stiffness: 350,
                        }}
                        className={`mx-auto w-full px-0 pb-3 xl:px-0 ${
                          activeWidgetBlock?.content?.action_type === 'campaign_plan_editor' ||
                          (!activeWidgetBlock && builderBuilding)
                            ? 'max-w-256.75'
                            : 'max-w-207.5'
                        } ${isSidebarOpen ? 'lg:px-1.75' : 'lg:px-0'}`}
                      >
                        {activeWidgetBlock ? (
                          <ActiveWidgetRenderer
                            block={activeWidgetBlock}
                            onConfirm={handleConfirm}
                            isFirstAiMessage={isFirstAi}
                          />
                        ) : (
                          <EditorShell
                            headerRight={
                              <div className="flex flex-col items-start leading-tight">
                                <span className="text-primary-text/32 text-[10px] font-bold tracking-[0.8px] uppercase">
                                  CAMPAIGN
                                </span>
                                <span className="text-primary-text max-w-105 truncate text-[17px] font-semibold tracking-[-0.2px]">
                                  Campaign Basics
                                </span>
                              </div>
                            }
                            nav={
                              <EditorNav
                                phase="intake"
                                building
                                errors={{}}
                                locks={{ geo: true, audience: true }}
                                unlocked={false}
                                adsOnly={false}
                                selected="campaign"
                                onSelect={() => {}}
                                onAddAdSet={() => {}}
                                onAddAd={() => {}}
                              />
                            }
                            footer={
                              <div className="flex w-full items-center justify-end">
                                <div className="flex items-center gap-2.5">
                                  <Skeleton height={32} width={68} radius="xl" />
                                  <Skeleton height={32} width={120} radius="xl" />
                                </div>
                              </div>
                            }
                          >
                            <BuildingPane label={currentStepLabel} />
                          </EditorShell>
                        )}
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {/* Escape-menu row disabled on the frontend for now (design pass
                      pending) — backend still computes/sends escape_menu, only the
                      button UI is hidden. Uncomment to re-enable. */}
                  {false && activeAssistContent && (
                    <WidgetAssistRow
                      content={activeAssistContent!}
                      onConfirm={handleConfirm}
                      disabled={streaming}
                    />
                  )}

                  {/* A stop that un-sends the answer removes the message, which on
                      its own just looks like it vanished. Say what happened, and
                      hold the payload so a widget answer is one click to resend. */}
                  {stopNotice && !streaming && (
                    <Box className="border-stroke-widget bg-primary-widget/60 mx-auto mb-2 flex w-full max-w-207.5 items-center gap-3 rounded-xl border px-4 py-2.5">
                      <Text fz={13} className="text-secondary-text flex-1">
                        {stopNotice.outcome === 'pending'
                          ? 'Stopping…'
                          : stopNotice.outcome === 'error'
                            ? (stopNotice.value || 'Failed to stop. Try again.')
                            : stopNotice.outcome === 'unsent'
                              ? 'Stopped — your answer wasn’t sent.'
                              : stopNotice.outcome === 'publish_interrupted'
                                ? 'Stopped during publish. Some campaign objects were created and are paused — nothing is spending, and the next publish picks up where this left off.'
                                : 'Stopped. Your answer was saved and the reply was cut short.'}
                      </Text>
                      {stopNotice.outcome === 'unsent' && (
                        <Button
                          unstyled
                          onClick={() => void resendStopped()}
                          className="text-primary-text hover:bg-primary-bg/10 cursor-pointer! rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors"
                        >
                          Resend
                        </Button>
                      )}
                      <Button
                        unstyled
                        onClick={dismissStopNotice}
                        className="text-secondary-text hover:text-primary-text cursor-pointer! rounded-lg px-2 py-1.5 text-[13px] transition-colors"
                        aria-label="Dismiss"
                      >
                        Dismiss
                      </Button>
                    </Box>
                  )}

                  {/* Not disabled while Punk works: what is typed is queued and
                      sent when the run ends (see ChatContext.queuedMessage). */}
                  <ChatInput
                    onSendMessage={handleSendMessage}
                    disabled={false}
                    isChatting={true}
                    showEarlyAccessBanner={showEarlyAccessBanner}
                    onCloseBanner={() => setShowEarlyAccessBanner(false)}
                  />
                </Box>
              </Box>
            </Box>
          )}
        </Box>
      </Box>
    </Box>
  );
};

export default ChatPage;
