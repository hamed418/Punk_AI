'use client';
import {
  ActionIcon,
  Box,
  Flex,
  Group,
  Loader,
  Text,
  Textarea,
} from '@mantine/core';
import { motion } from 'framer-motion';
import { PROMPT_CATEGORIES } from './prompts';
import { ArrowUp, ImageIcon, Square, X } from 'lucide-react';
import type React from 'react';
import { useRef, useState, useEffect, useMemo } from 'react';
import { useChat } from '../../../../contexts/ChatContext';
import { useUploadMedia } from '../../../../hooks/api/useChatApi';
import EarlyAccessModal from './early-access-modal';
import { useSidebar } from '@/contexts/SidebarContext';

interface ChatInputProps {
  onSendMessage: (message: string) => void;
  disabled: boolean;
  isChatting?: boolean;
  onMenuToggle?: (isOpen: boolean) => void;
  showEarlyAccessBanner?: boolean;
  onCloseBanner?: () => void;
}

const ChatInput: React.FC<ChatInputProps> = ({
  onSendMessage,
  disabled,
  isChatting = false,
  onMenuToggle,
}) => {
  const [message, setMessage] = useState('');
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [openEarlyAccessModal, setOpenEarlyAccessModal] = useState(false);

  useEffect(() => {
    onMenuToggle?.(Boolean(selectedCategory));
  }, [selectedCategory, onMenuToggle]);
  const [hoveredPromptIndex, setHoveredPromptIndex] = useState<number | null>(
    null
  );
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [lastCategory, setLastCategory] = useState<string | null>(null);

  const {
    streaming,
    stopGeneration,
    composerPrefill,
    clearComposerPrefill,
    queuedMessage,
    cancelQueuedMessage,
  } = useChat();

  const uploadMediaMutation = useUploadMedia();

  // Undo returns the text of a rewound free-text message so the user can fix the
  // typo instead of retyping it. Widget answers never arrive here — their widget
  // is re-rendered instead (see isWidgetAnswer in ChatContext).
  useEffect(() => {
    if (composerPrefill === null) return;
    setTimeout(() => {
      setMessage(composerPrefill);
      clearComposerPrefill();
      textareaRef.current?.focus();
    }, 0);
  }, [composerPrefill, clearComposerPrefill]);

  const allPrompts = useMemo(
    () => PROMPT_CATEGORIES.flatMap((c) => c.prompts.map((p) => p.text)),
    []
  );

  const [placeholderIndex, setPlaceholderIndex] = useState(0);
  const [placeholderText, setPlaceholderText] = useState('');
  const [isFadingOut, setIsFadingOut] = useState(false);
  const [isFocused, setIsFocused] = useState(false);
  const { isSidebarOpen } = useSidebar();
  const currentCategory = useMemo(() => {
    if (message.trim()) {
      return (
        PROMPT_CATEGORIES.find((cat) =>
          cat.prompts.some((p) => p.text.trim() === message.trim())
        )?.label || null
      );
    }

    if (isFocused) return null;

    const currentPrompt = allPrompts[placeholderIndex];
    if (!currentPrompt) return null;
    return (
      PROMPT_CATEGORIES.find((cat) =>
        cat.prompts.some((p) => p.text === currentPrompt)
      )?.label || null
    );
  }, [isFocused, message, placeholderIndex, allPrompts]);

  const activePorpmtPill = Boolean(currentCategory);

  useEffect(() => {
    if (isFocused || message.trim()) {
      const timeout = setTimeout(() => {
        setPlaceholderText('');
        setIsFadingOut(false);
        setPlaceholderIndex(Math.floor(Math.random() * allPrompts.length));
      }, 0);
      return () => clearTimeout(timeout);
    }

    const currentPrompt = allPrompts[placeholderIndex];
    if (!currentPrompt) return;

    if (isFadingOut) {
      const timeout = setTimeout(() => {
        setPlaceholderText('');
        setIsFadingOut(false);
        setPlaceholderIndex(Math.floor(Math.random() * allPrompts.length));
      }, 1500);
      return () => clearTimeout(timeout);
    }

    if (placeholderText === currentPrompt) {
      const timeout = setTimeout(() => setIsFadingOut(true), 3000);
      return () => clearTimeout(timeout);
    }

    const typingSpeed = 30;
    const timeout = setTimeout(() => {
      setPlaceholderText((prev) => currentPrompt.substring(0, prev.length + 1));
    }, typingSpeed);

    return () => clearTimeout(timeout);
  }, [
    placeholderText,
    isFadingOut,
    placeholderIndex,
    allPrompts,
    isFocused,
    message,
  ]);

  const fadeStyles = (
    <style>{`
      .fade-placeholder::placeholder {
        color: var(--color-primary-text, var(--mantine-color-text-primary)) !important;
        opacity: 1 !important;
        transition: color 0.5s ease-out, opacity 0.5s ease-out;
      }
      .fade-placeholder:not(.fade-out)::placeholder {
        color: var(--color-primary-text, var(--mantine-color-text-primary)) !important;
        opacity: 1 !important;
        transition: none;
      }
      .fade-out::placeholder {
        color: transparent !important;
        opacity: 0 !important;
      }
    `}</style>
  );

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (message.trim() && !disabled) {
      onSendMessage(message);
      setMessage('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleRemoveFile = () => {
    setUploadedFile(null);
  };

  if (isChatting) {
    const isMultiLine = message.includes('\n') || message.length > 95;

    const spring = { type: 'spring' as const, stiffness: 340, damping: 36 };

    return (
      <Box
        className={`font-inter! mx-auto mb-4 w-full max-w-207.5 xl:px-0 ${isSidebarOpen ? 'lg:px-2' : ''}`}
      >
        <EarlyAccessModal
          opened={openEarlyAccessModal}
          onClose={() => setOpenEarlyAccessModal(false)}
        />
        {fadeStyles}
        <motion.div
          layout
          transition={spring}
          className={`light:backdrop-blur-[57px] flex w-full flex-col rounded-[28px] backdrop-blur-[75.9000015258789px] ${
            isMultiLine
              ? 'rounded-2xl pt-2 pr-4 pb-3 pl-5 focus-within:bg-white/1 focus-within:shadow-md'
              : 'rounded-4xl px-4 py-2 focus-within:bg-white/1 focus-within:shadow-md'
          }`}
          style={{
            // backdropFilter: 'blur(75.9000015258789px)',

            boxShadow: 'var(--shadow-chat-input)',
          }}
        >
          {/* A message typed while Punk is working: held, sent when it's done. */}
          {queuedMessage && (
            <Group
              gap={6}
              wrap="nowrap"
              className="bg-muted text-secondary-text mb-3 self-start rounded-full px-3 py-1"
              role="status"
            >
              <Text size="sm" className="text-secondary-text max-w-80 truncate">
                Queued — sends when Punk finishes: {queuedMessage}
              </Text>
              <ActionIcon
                variant="transparent"
                size="xs"
                onClick={cancelQueuedMessage}
                className="text-secondary-text hover:text-foreground ml-0.5"
                style={{ cursor: 'pointer' }}
                aria-label="Cancel queued message"
              >
                <X size={12} />
              </ActionIcon>
            </Group>
          )}

          {/* File chip */}
          {uploadedFile && (
            <Group
              gap={6}
              className="bg-muted text-secondary-text mb-3 self-start rounded-full px-3 py-1"
            >
              <ImageIcon size={13} />
              <Text size="sm" className="text-secondary-text max-w-30 truncate">
                {uploadedFile.name}
              </Text>
              <ActionIcon
                variant="transparent"
                size="xs"
                onClick={handleRemoveFile}
                className="text-secondary-text hover:text-foreground ml-0.5"
                style={{ cursor: 'pointer' }}
              >
                <X size={12} />
              </ActionIcon>
            </Group>
          )}

          {/* Wrapper container */}
          <Flex wrap="wrap" align="center" className="w-full">
            {/* 1. Textarea */}
            <motion.div
              layout
              transition={spring}
              className={`text-primary-text bg-transparent text-base ${
                isMultiLine ? 'order-1 w-full' : 'order-2 mx-2 flex-1'
              }`}
            >
              <Textarea
                ref={textareaRef}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                onKeyDown={handleKeyDown}
                onFocus={() => setIsFocused(true)}
                onBlur={() => setIsFocused(false)}
                placeholder={isFocused ? '' : 'Type a message...'}
                disabled={disabled}
                autosize
                minRows={1}
                maxRows={8}
                variant="unstyled"
                classNames={{
                  input: `fade-placeholder bg-transparent! disabled:bg-transparent! border-0 p-0 w-full text-primary-text custom-textarea-scrollbar placeholder:text-secondary-text/50! focus:ring-0 focus:outline-none focus:border-0 min-h-[24px] outline-none disabled:opacity-100 overflow-hidden`,
                }}
              />
            </motion.div>

            {/* 3. Actions */}
            <motion.div
              layout
              transition={spring}
              className={`flex shrink-0 items-center gap-2.5 ${
                isMultiLine ? 'order-3 mt-3 -mr-1 ml-auto' : 'order-3 -mr-1.25'
              }`}
            >
              {uploadMediaMutation.isPending && (
                <Loader size={16} className="text-secondary-text mr-1" />
              )}
              {/* <ActionIcon
                variant="transparent"
                size="lg"
                className="text-primary-text! hover:text-primary-text/70!"
                title="Settings"
                style={{ cursor: 'pointer' }}
              >
                <Settings size={20} />
              </ActionIcon> */}
              {streaming ? (
                <ActionIcon
                  onClick={() => void stopGeneration()}
                  size={34}
                  radius="xl"
                  variant="filled"
                  className="bg-primary-bg/6! text-primary-text! hover:text-primary-text/70!"
                  style={{
                    cursor: 'pointer',
                    border: '0.5px solid #FFFFFF29',
                    boxShadow: 'var(--shadow-chat-input-icon)',
                  }}
                  title="Stop generating"
                >
                  <Square size={14} fill="currentColor" />
                </ActionIcon>
              ) : (
                <ActionIcon
                  onClick={
                    message.trim() && !disabled ? handleSubmit : undefined
                  }
                  disabled={disabled || uploadMediaMutation.isPending}
                  size={34}
                  radius="xl"
                  variant="filled"
                  className="bg-primary-bg/6! text-primary-text! hover:text-primary-text/70!"
                  style={{
                    cursor:
                      uploadMediaMutation.isPending ||
                      disabled ||
                      !message.trim()
                        ? 'not-allowed'
                        : 'pointer',
                    border: '0.5px solid #FFFFFF29',
                    boxShadow: 'var(--shadow-chat-input-icon)',
                    opacity: message.trim() && !disabled ? 1 : 0.45,
                  }}
                  title="Send message"
                >
                  <ArrowUp size={18} />
                </ActionIcon>
              )}
            </motion.div>
          </Flex>
        </motion.div>
      </Box>
    );
  }

  // ── Homepage layout ──────────────────────────────────────────────────────────
  return (
    <Box className="font-inter! mb-4">
      {fadeStyles}
      <Box
        className="chat-input-container light:bg-[#15151505]! light:backdrop-blur-[57px]! mx-auto mb-5 w-full max-w-184.5 rounded-tl-[23px] rounded-tr-[23px] rounded-br-[27px] rounded-bl-[27px] bg-white/1! p-3.5 backdrop-blur-[58.400001525878906px]! transition-all focus-within:shadow-md"

        style={{
          boxShadow: 'var(--shadow-new-chat-input)',
          border: '1px solid',
          borderImageSource:
            'linear-gradient(136.45deg, rgba(255, 255, 255, 0.68) 2.69%, rgba(255, 255, 255, 0) 12.32%, rgba(255, 255, 255, 0.08) 86.05%, rgba(255, 255, 255, 0.4) 99.28%)',
        }}
      >
        {/* Textarea — top section */}
        <Textarea
          ref={textareaRef}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          placeholder={isFocused ? '' : placeholderText}
          disabled={disabled}
          autosize
          minRows={2}
          maxRows={6}
          variant="unstyled"
          classNames={{
            input: `fade-placeholder ${isFadingOut && !isFocused ? 'fade-out' : ''} custom-scrollbar text-primary-text! placeholder:opacity-100! placeholder:text-secondary-text/70! w-full resize-none border-none bg-transparent! disabled:bg-transparent! disabled:opacity-100 py-0 pr-0 pl-2! text-base leading-relaxed focus:ring-0 focus:outline-none overflow-hidden`,
          }}
        />

        {/* Bottom toolbar */}
        <Group gap={10} className="mt-1 w-full">
          {/* A message typed while Punk is working: held, sent when it's done. */}
          {queuedMessage && (
            <Group
              gap={6}
              wrap="nowrap"
              className="bg-muted text-secondary-text mb-3 self-start rounded-full px-3 py-1"
              role="status"
            >
              <Text size="sm" className="text-secondary-text max-w-80 truncate">
                Queued — sends when Punk finishes: {queuedMessage}
              </Text>
              <ActionIcon
                variant="transparent"
                size="xs"
                onClick={cancelQueuedMessage}
                className="text-secondary-text hover:text-foreground ml-0.5"
                style={{ cursor: 'pointer' }}
                aria-label="Cancel queued message"
              >
                <X size={12} />
              </ActionIcon>
            </Group>
          )}

          {/* File chip */}
          {uploadedFile && (
            <Group
              gap={6}
              className="bg-muted text-secondary-text rounded-full px-3 py-1"
            >
              <ImageIcon size={13} />
              <Text size="sm" className="text-secondary-text max-w-30 truncate">
                {uploadedFile.name}
              </Text>
              <ActionIcon
                variant="transparent"
                size="xs"
                onClick={handleRemoveFile}
                className="text-secondary-text hover:text-foreground ml-0.5"
                style={{ cursor: 'pointer' }}
              >
                <X size={12} />
              </ActionIcon>
            </Group>
          )}

          {/* Spacer */}
          <Box className="flex-1" />

          {/* Right icons */}
          {uploadMediaMutation.isPending && (
            <Loader size={16} className="text-secondary-text" />
          )}
          {streaming ? (
            <ActionIcon
              onClick={() => void stopGeneration()}
              size={32}
              radius="xl"
              className="text-primary-text! hover:text-primary-text/70! bg-primary-bg/6! light:bg-[#FAF9F5]!"
              style={{
                border: '0.5px solid #FFFFFF29',
                boxShadow:
                  '0px 1.5px 0px 0px #FFFFFF59 inset, 0px 2px 6px 0px #00000033',
                cursor: 'pointer',
              }}
              title="Stop generating"
            >
              <Square size={15} fill="currentColor" />
            </ActionIcon>
          ) : (
            <ActionIcon
              onClick={handleSubmit}
              disabled={!message.trim() || uploadMediaMutation.isPending}
              size={32}
              radius="xl"
              className={
                message.trim() && !uploadMediaMutation.isPending
                  ? 'text-primary-text! hover:text-primary-text/70! bg-primary-bg/6! light:bg-[#FAF9F5]!'
                  : 'shadow-md hover:opacity-90'
              }
              style={{
                border: '0.5px solid #FFFFFF29',
                boxShadow:
                  '0px 1.5px 0px 0px #FFFFFF59 inset, 0px 2px 6px 0px #00000033',
                cursor:
                  message.trim() && !uploadMediaMutation.isPending
                    ? 'pointer'
                    : 'not-allowed',
              }}
              title="Send message"
            >
              <ArrowUp size={20} />
            </ActionIcon>
          )}
        </Group>
      </Box>

      <Box className="relative w-full">
        {/* Menu Container */}
        <div
          className={`mx-auto overflow-hidden transition-all ease-in-out ${
            selectedCategory
              ? 'border-stroke-widget bg-primary-widget! shadow-widget! light:shadow-lg! w-full max-w-full rounded-[30px] border delay-150 duration-200 sm:max-w-184.5'
              : 'w-full max-w-2xl rounded-[30px] border-transparent delay-150 duration-200'
          }`}
          style={
            selectedCategory
              ? {
                  backdropFilter: 'blur(75.9px)',
                }
              : {
                  background: 'transparent',
                  backdropFilter: 'none',
                  boxShadow: 'none',
                }
          }
        >
          <div
            className={`grid transition-all ease-in-out ${
              selectedCategory
                ? 'grid-rows-[1fr] delay-150 duration-200'
                : 'grid-rows-[0fr] delay-150 duration-200'
            }`}
          >
            <div className="overflow-hidden">
              <div
                className={`transition-opacity ${
                  selectedCategory
                    ? 'opacity-100 delay-350 duration-200'
                    : 'opacity-0 delay-0 duration-150'
                }`}
              >
                {(() => {
                  const categoryData = PROMPT_CATEGORIES.find(
                    (c) => c.label === (selectedCategory || lastCategory)
                  );
                  if (!categoryData) return null;
                  const Icon = categoryData.icon;
                  return (
                    <Box className="text-primary-text flex flex-col">
                      <Flex
                        align="center"
                        justify="space-between"
                        className="border-underline/15 border-b p-3 sm:p-4"
                      >
                        <Group gap={8}>
                          <Box className="border-primary-text/10 bg-primary-text/5 flex h-7 w-7 items-center justify-center rounded-full border sm:h-8 sm:w-8">
                            <Icon size={15} className="text-primary-text/80" />
                          </Box>
                          <Text
                            size="sm"
                            fw={500}
                            className="text-primary-text/90 text-sm!"
                          >
                            {categoryData.label}
                          </Text>
                        </Group>
                        <ActionIcon
                          variant="transparent"
                          onClick={() => setSelectedCategory(null)}
                          className="text-primary-text/50! hover:text-primary-text/80! transition-colors"
                        >
                          <X size={16} />
                        </ActionIcon>
                      </Flex>

                      <Box className="custom-scrollbar flex max-h-75 flex-col overflow-y-auto py-1">
                        {categoryData.prompts.map((p, idx) => (
                          <Box
                            key={idx}
                            onMouseEnter={() => {
                              if (!selectedCategory) return;
                              setHoveredPromptIndex(idx);
                              setMessage(p.text);
                            }}
                            onMouseLeave={() => {
                              if (!selectedCategory) return;
                              setHoveredPromptIndex(null);
                            }}
                            onClick={() => {
                              setMessage(p.text);
                              textareaRef.current?.focus();
                              setSelectedCategory(null);
                              setHoveredPromptIndex(null);
                            }}
                            className={`cursor-pointer border-b transition-all duration-200 last:border-none ${hoveredPromptIndex === idx || hoveredPromptIndex === idx + 1 ? 'border-transparent' : 'border-underline/15'}`}
                          >
                            <Box
                              className={`mx-1 flex items-center justify-between rounded-full py-1 pr-1 pl-3 sm:pl-4 ${hoveredPromptIndex === idx ? 'light:bg-[#15151512]! bg-white/10' : ''}`}
                            >
                              <Box className="flex min-w-0 flex-1 items-center gap-2 sm:gap-3">
                                <Box className="flex h-auto min-h-10 min-w-0 flex-1 items-center justify-between gap-1.5">
                                  <Text
                                    size="xs"
                                    fw={500}
                                    className={`truncate text-[11px]! sm:text-xs! ${
                                      hoveredPromptIndex === idx
                                        ? 'text-primary-text'
                                        : 'text-primary-text/80'
                                    }`}
                                  >
                                    {p.title}
                                  </Text>
                                </Box>
                              </Box>
                              {hoveredPromptIndex === idx && (
                                <Box
                                  className="light:bg-[#FAF9F5]! light:shadow-md! flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-transparent sm:h-10 sm:w-10"
                                  style={{
                                    boxShadow: `
                                      inset -3px -5px 2.5px -5px #FFFFFF,
                                      inset 2.5px 3.5px 2px -3.5px #FFFFFF
                                    `,
                                  }}
                                >
                                  <ArrowUp
                                    size={16}
                                    className="text-primary-text/80 light:text-primary-text"
                                  />
                                </Box>
                              )}
                            </Box>
                          </Box>
                        ))}
                      </Box>
                    </Box>
                  );
                })()}
              </div>
            </div>
          </div>
        </div>

        {/* Tags Container */}
        <div
          className={`grid ease-in-out ${
            !selectedCategory
              ? 'grid-rows-[1fr] delay-150 duration-200'
              : 'grid-rows-[0fr] delay-150 duration-200'
          }`}
        >
          <div>
            <div
              className={`transition-opacity ${
                !selectedCategory
                  ? 'opacity-100 delay-350 duration-200'
                  : 'opacity-0 delay-0 duration-150'
              }`}
            >
              <div className="mx-auto flex w-full max-w-xl flex-wrap items-center justify-center gap-1.5 px-2 sm:gap-2 sm:px-0 md:gap-2.5">
                {PROMPT_CATEGORIES.map((tag) => {
                  const Icon = tag.icon;
                  const isActive =
                    activePorpmtPill && tag.label === currentCategory;
                  return (
                    <button
                      key={tag.label}
                      type="button"
                      onClick={() => {
                        setSelectedCategory(tag.label);
                        setLastCategory(tag.label);
                      }}
                      className={`light:bg-[#EEEEEC]! light:border! group light:border-[#D9D9D9]! ${
                        isActive
                          ? 'text-primary-text/80'
                          : 'text-primary-text/50'
                      } hover:bg-primary-bg/2 hover:text-primary-text/80 light:backdrop-blur-2xl! prompt-tag-button! flex shrink-0 cursor-pointer items-center gap-1.5 rounded-[36px]! bg-white/1! px-2.5 py-1 text-[11px]! shadow-none! backdrop-blur-[12.7px]! transition-all sm:gap-2 sm:px-3.5 sm:text-xs! md:px-4`}
                      style={{
                        boxShadow: 'var(--shadow-new-chat-chip) !important',
                      }}
                    >
                      <Icon
                        size={12}
                        className={`stroke-1.5 shrink-0 ${
                          isActive
                            ? 'text-primary-text/80'
                            : 'text-primary-text/50'
                        } group-hover:text-primary-text/80`}
                      />
                      <span className="text-[11px]! whitespace-nowrap md:text-xs!">
                        {tag.label}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      </Box>
    </Box>
  );
};

export default ChatInput;
