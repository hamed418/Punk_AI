'use client';
import ActionButton from '@/components/ActionButton';
// import { BlobOverlay } from '@/components/MouseFollowBlob'
// import { useMouseFollowBlob } from '@/hooks/useMouseFollowBlob'
import WidgetHeaderV2 from '@/components/WidgetHeaderV2';
import type { LocationItem, PendingActionBlock } from '@/types/chat';
import { getWidgetHeader, getWidgetSubheader } from '@/utils';
import { Box, Text, Textarea } from '@mantine/core';
import { ArrowUp, ChevronDown, ChevronUp, Pencil } from 'lucide-react';
import { useState, useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import GetHeaderHelper from '@/utils/GetHeaderHelper';
// import WidgetLayout from './WidgetLayout'

interface WidgetOptionSelectionV2Props {
  content: PendingActionBlock['content'];
  onConfirm?: (value: string) => void;
  locations?: LocationItem[];
  showLogo?: boolean;
  isLatest?: boolean;
  userResponse?: string | null;
}

const WidgetOptionSelectionV2 = ({
  content,
  onConfirm,
  isLatest = true,
  //   showLogo = false,
  //   locations,
  userResponse = null,
}: WidgetOptionSelectionV2Props) => {
  const [activeOption, setActiveOption] = useState<number | null>(null);
  const [open, setOpen] = useState(isLatest);
  const [prevIsLatest, setPrevIsLatest] = useState(isLatest);

  if (isLatest !== prevIsLatest) {
    setPrevIsLatest(isLatest);
    if (!isLatest) {
      setOpen(false);
    }
  }
  const [customValue, setCustomValue] = useState('');
  const [prevUserResponse, setPrevUserResponse] = useState(userResponse);

  if (userResponse !== prevUserResponse) {
    setPrevUserResponse(userResponse);
    if (userResponse && content.options) {
      const parsedResponse = userResponse.includes('A:')
        ? userResponse.split('A:')[1].trim()
        : userResponse.trim();

      const found = content.options.find(
        (opt) => opt.trim() === parsedResponse
      );

      if (!found) {
        setCustomValue(parsedResponse);
      }
    }
  }

  const handleActiveOption = (idx: number | null) => {
    if (!isLatest) return;
    if (idx === activeOption) {
      setActiveOption(null);
    } else {
      setActiveOption(idx);
    }
  };
  const handleCustomValue = (value: string) => {
    if (activeOption !== null) {
      setActiveOption(null);
      setCustomValue(value);
    } else {
      setCustomValue(value);
    }
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Enter' && isLatest && onConfirm && activeOption !== null) {
        const option = content.options?.[activeOption];
        if (option) {
          e.preventDefault();
          // Send the WHOLE option, not just the label before the em dash: for a
          // disambiguation ask the description IS the discriminator (same venue
          // name, different addresses) and stripping it made every option
          // resolve to the first one server-side.
          onConfirm(`Q: ${content.prompt}\nA: ${option.trim()}`);
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [activeOption, isLatest, onConfirm, content.prompt, content.options]);

  // const { containerRef, blobX, blobY, opacity, handleMouseMove } =
  //   useMouseFollowBlob()
  return (
    // <WidgetLayout
    //   mode="single"
    //   showLogo={showLogo}
    //   className="pointer-events-auto w-full"
    // >
    <Box className="relative max-w-4xl rounded-[30px]">
      <Box
        // ref={containerRef}
        // onMouseMove={handleMouseMove}
        className="border-stroke-widget bg-primary-widget! shadow-widget! light:shadow-lg! w-full rounded-[30px] border"
        style={{
          backdropFilter: 'blur(75.9px)',
        }}
      >
        {/* mouse-following blob */}
        {/* <BlobOverlay blobX={blobX} blobY={blobY} opacity={opacity} /> */}
        {/* header */}
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className={`flex w-full cursor-pointer items-center justify-between px-4 sm:px-5 pt-4 sm:pt-5 pb-3 sm:pb-4 text-left ${open ? 'border-underline/15 border-b' : 'border-b border-transparent'}`}
        >
          <WidgetHeaderV2
            icon={GetHeaderHelper(content.field || '')}
            title={content.title || getWidgetHeader(content.field || '')}
            subtitle={
              userResponse
                ? userResponse.includes('A:')
                  ? userResponse.split('A:')[1].trim()
                  : userResponse.trim()
                : content.subtitle || getWidgetSubheader(content.field || '')
            }
          />
          {open ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </button>
        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2, ease: 'easeInOut' }}
              className="overflow-hidden"
            >
              {/* options */}
              <Box className="px-4 sm:px-5 py-1">
                {content.options
                  ?.filter((op) => op !== 'Enter a custom amount')
                  .map((op, idx) => {
                    const [label, description] = op.split('—');
                    return (
                      <Box
                        key={idx}
                        onMouseEnter={() => handleActiveOption(idx)}
                        onMouseLeave={() => handleActiveOption(null)}
                        onClick={() => {
                          if (isLatest && onConfirm) {
                            onConfirm(`Q: ${content.prompt}\nA: ${op.trim()}`);
                          }
                        }}
                        className={`border-t py-1 transition-all duration-200 first:border-0 ${
                          activeOption !== null
                            ? 'border-transparent'
                            : 'border-underline/15'
                        } ${isLatest ? 'cursor-pointer' : 'cursor-default'}`}
                      >
                        <Box
                          className={`flex items-center justify-between rounded-2xl sm:rounded-full p-1.5 sm:p-1 transition-all duration-200 ${activeOption === idx ? 'light:bg-[#15151512]! bg-white/10' : ''}`}
                        >
                          <Box className="flex items-start sm:items-center gap-2.5 sm:gap-3 flex-1 min-w-0">
                            <Box
                              className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full mt-0.5 sm:mt-0 ${activeOption === idx ? 'light:bg-secondary-widget! bg-transparent' : 'bg-[#1515150D]'}`}
                              style={
                                activeOption === idx
                                  ? {
                                      boxShadow: `
                                inset -3px -5px 2.5px -5px #FFFFFF,
                                inset 2.5px 3.5px 2px -3.5px #FFFFFF
                              `,
                                    }
                                  : undefined
                              }
                            >
                              <Text
                                fw={600}
                                fz={13}
                                className={`${activeOption === idx ? 'text-primary-text' : 'text-secondary-text/80'}`}
                              >
                                {idx + 1}
                              </Text>
                            </Box>
                            <Box className="flex flex-col sm:flex-row sm:items-baseline max-w-187.5 flex-1 min-w-0 gap-0.5 sm:gap-1.5">
                              <Text
                                fw={600}
                                fz={13}
                                className={`sm:shrink-0 ${activeOption === idx ? 'text-primary-text' : 'text-primary-text/80'}`}
                              >
                                {label.trim()}
                              </Text>
                              {description && (
                                <Text
                                  fw={400}
                                  fz={13}
                                  className={`flex-1 break-words leading-tight sm:leading-normal ${activeOption === idx ? 'text-primary-text/80' : 'text-secondary-text/80'}`}
                                >
                                  {description.trim()}
                                </Text>
                              )}
                            </Box>
                          </Box>
                          {activeOption === idx && (
                            <Box
                              className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ml-1.5 sm:ml-0 ${activeOption === idx ? 'light:bg-[#FAF9F5]! light:shadow-md! bg-transparent' : 'bg-primary-widget'}`}
                              style={
                                activeOption === idx
                                  ? {
                                      boxShadow: `
                                inset -3px -5px 2.5px -5px #FFFFFF,
                                inset 2.5px 3.5px 2px -3.5px #FFFFFF
                              `,
                                    }
                                  : undefined
                              }
                            >
                              <svg
                                width="13"
                                height="13"
                                viewBox="0 0 13 13"
                                fill="none"
                                className="text-primary-text"
                                xmlns="http://www.w3.org/2000/svg"
                              >
                                <path
                                  d="M4.87435 5.41699L2.16602 8.12533L4.87435 10.8337"
                                  stroke="currentColor"
                                  strokeWidth="0.975"
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                />
                                <path
                                  d="M10.8327 2.16699V5.95866C10.8327 6.53329 10.6044 7.0844 10.1981 7.49072C9.79175 7.89705 9.24065 8.12533 8.66602 8.12533H2.16602"
                                  stroke="currentColor"
                                  strokeWidth="0.975"
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                />
                              </svg>
                            </Box>
                          )}
                        </Box>
                      </Box>
                    );
                  })}
              </Box>
              {content.options?.includes('Enter a custom amount') && (
                <Box className="border-underline/15 flex items-center gap-1 border-t px-4 sm:px-5 py-3 transition-all duration-200">
                  <Box
                    className="bg-primary-widget flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
                    style={
                      customValue.length > 0
                        ? {
                            boxShadow: `
                                inset -3px -5px 2.5px -5px #FFFFFF,
                                inset 2.5px 3.5px 2px -3.5px #FFFFFF
                              `,
                          }
                        : undefined
                    }
                  >
                    <Pencil size={13} className="text-secondary-text" />
                  </Box>
                  <Textarea
                    variant="unstyled"
                    autosize
                    disabled={!isLatest}
                    value={customValue}
                    onChange={(e) => handleCustomValue(e.target.value)}
                    className="flex-1 focus:border-0 focus:ring-0 focus:outline-0 active:border-0 active:ring-0 active:outline-0"
                    placeholder="I want something else"
                    styles={{
                      input: {
                        padding: '8px 12px',
                      },
                    }}
                  />
                  {customValue.length > 0 && (
                    <Box>
                      {/* confirm button */}
                      <ActionButton
                        isActive={customValue.length > 0}
                        onClick={() => {
                          if (isLatest && onConfirm && customValue.trim()) {
                            onConfirm(
                              `Q: ${content.prompt}\nA: ${customValue.trim()}`
                            );
                          }
                        }}
                      >
                        <ArrowUp size={18} />
                      </ActionButton>
                    </Box>
                  )}
                </Box>
              )}

            </motion.div>
          )}
        </AnimatePresence>
      </Box>
    </Box>
    // </WidgetLayout>
  );
};

export default WidgetOptionSelectionV2;
