'use client';
import { Divider, Popover, Text } from '@mantine/core';
import { DatePicker } from '@mantine/dates';
import { Calendar, ChevronDown, ChevronUp } from 'lucide-react';
import type React from 'react';
import { useMemo, useState } from 'react';
import type { PendingActionBlock } from '@/types/chat';
import WidgetLayout from './WidgetLayout';
import { motion, AnimatePresence } from 'framer-motion';
import dayjs from 'dayjs';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';
import WidgetHeaderV2 from '@/components/WidgetHeaderV2';

interface WidgetDateRangePickerProps {
  content: PendingActionBlock['content'];
  onConfirm?: (value: string) => void;
  aiText?: React.ReactNode;
  showLogo?: boolean;
  isLatest?: boolean;
  userResponse?: string | null;
}

export default function WidgetDateRangePickerV2({
  content,
  onConfirm,
  aiText,
  showLogo = false,
  isLatest = true,
  userResponse,
}: WidgetDateRangePickerProps) {
  const [open, setOpen] = useState(isLatest);
  const [prevIsLatest, setPrevIsLatest] = useState(isLatest);

  if (isLatest !== prevIsLatest) {
    setPrevIsLatest(isLatest);
    if (!isLatest) {
      setOpen(false);
    }
  }

  const prefill = content.prefill as unknown as
    { start?: string; end?: string } | undefined;

  // Parse dates from userResponse if available
  const parsedResponse = useMemo(() => {
    if (!userResponse) return null;
    const match = userResponse.match(
      /Campaign set from (\d{4}-\d{2}-\d{2}) to (ongoing|\d{4}-\d{2}-\d{2})/i
    );
    if (match) {
      return {
        start: match[1],
        end: match[2],
      };
    }
    return null;
  }, [userResponse]);

  const [startDate, setStartDate] = useState(() => {
    if (parsedResponse?.start) return parsedResponse.start;
    if (prefill?.start) return prefill.start;
    const d = new Date();
    return d.toISOString().split('T')[0];
  });

  const [endDate, setEndDate] = useState(() => {
    if (parsedResponse?.end && parsedResponse.end !== 'ongoing')
      return parsedResponse.end;
    if (prefill?.end && prefill.end !== 'ongoing') return prefill.end;
    const d = new Date();
    d.setDate(d.getDate() + 30);
    return d.toISOString().split('T')[0];
  });

  const [startMode, setStartMode] = useState<'today' | 'custom'>(() => {
    const todayStr = dayjs().format('YYYY-MM-DD');
    const initialStart = parsedResponse?.start || prefill?.start;
    if (initialStart && initialStart !== todayStr) return 'custom';
    return 'today';
  });

  const [endMode, setEndMode] = useState<'ongoing' | 'custom'>(() => {
    const initialEnd = parsedResponse?.end || prefill?.end;
    if (initialEnd === 'ongoing' || !initialEnd) return 'ongoing';
    return 'custom';
  });

  // Sync state when parsedResponse changes
  const [prevParsedResponse, setPrevParsedResponse] = useState(parsedResponse);

  if (parsedResponse !== prevParsedResponse) {
    setPrevParsedResponse(parsedResponse);
    if (parsedResponse) {
      setStartDate(parsedResponse.start);
      const todayStr = dayjs().format('YYYY-MM-DD');
      setStartMode(parsedResponse.start === todayStr ? 'today' : 'custom');
      if (parsedResponse.end === 'ongoing') {
        setEndMode('ongoing');
      } else {
        setEndMode('custom');
        setEndDate(parsedResponse.end);
      }
    }
  }

  const activeStartDate = useMemo(() => {
    if (startMode === 'today') {
      return dayjs().format('YYYY-MM-DD');
    }
    return startDate;
  }, [startMode, startDate]);

  const activeEndDate = useMemo(() => {
    if (endMode === 'ongoing') {
      return 'ongoing';
    }
    return endDate;
  }, [endMode, endDate]);

  const subtitle = useMemo(() => {
    const startText =
      startMode === 'today'
        ? 'Today'
        : dayjs(activeStartDate).format('MMM D, YYYY');
    const endText =
      endMode === 'ongoing'
        ? 'Ongoing'
        : dayjs(activeEndDate).format('MMM D, YYYY');
    return `${startText} → ${endText}`;
  }, [startMode, activeStartDate, endMode, activeEndDate]);

  const statusText = useMemo(() => {
    const formattedStart =
      startMode === 'today'
        ? 'today'
        : dayjs(activeStartDate).format('MMM D, YYYY');
    if (endMode === 'ongoing') {
      return (
        <Text fz={14} className="text-secondary-text">
          Runs{' '}
          <strong className="text-primary-text font-semibold">
            indefinitely
          </strong>
          , starting{' '}
          <strong className="text-primary-text font-semibold">
            {formattedStart}
          </strong>
          .
        </Text>
      );
    } else {
      const formattedEnd = dayjs(activeEndDate).format('MMM D, YYYY');
      return (
        <Text fz={14} className="text-secondary-text">
          Runs from{' '}
          <strong className="text-primary-text font-semibold">
            {formattedStart}
          </strong>{' '}
          to{' '}
          <strong className="text-primary-text font-semibold">
            {formattedEnd}
          </strong>
          .
        </Text>
      );
    }
  }, [startMode, activeStartDate, endMode, activeEndDate]);

  const handleConfirm = () => {
    if (!isLatest) return;
    const resultStr = `Q: Campaign Duration?\nA: Campaign set from ${activeStartDate} to ${endMode === 'ongoing' ? 'ongoing' : activeEndDate}`;
    onConfirm?.(resultStr);
  };

  // const { containerRef, blobX, blobY, opacity, handleMouseMove } =
  //   useMouseFollowBlob()

  return (
    <WidgetLayout mode="single" showLogo={showLogo} aiText={aiText}>
      <div className="mb-3 transition-opacity duration-300">
        <div
          // ref={containerRef}
          // onMouseMove={handleMouseMove}
          className="relative rounded-[30px]"
        >
          {/* Blob sits behind the card so backdrop-blur blurs it naturally */}
          {/* <BlobOverlay blobX={blobX} blobY={blobY} opacity={opacity} /> */}
          <motion.div
            layout
            transition={{
              type: 'spring',
              damping: 20,
              stiffness: 300,
              mass: 1,
            }}
            className="animate-fade-up border-stroke-widget! bg-primary-widget! shadow-widget! light:shadow-sm! relative z-10 flex flex-col overflow-hidden rounded-[30px] border! transition-opacity duration-300"
            style={{
              backdropFilter: 'blur(75.9px)',
            }}
          >
            {/* ── Header ── */}
            <button
              type="button"
              onClick={() => setOpen(!open)}
              className={`flex w-full cursor-pointer items-center justify-between px-5 pt-5 pb-4 text-left ${open ? 'border-underline/15 border-b' : 'border-b border-transparent'}`}
            >
              <WidgetHeaderV2
                icon={<Calendar size={15} className="text-primary-text" />}
                title="Choose start and end dates"
                subtitle={subtitle}
              />
              {open ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
            </button>

            {/* ── Body ── */}
            <AnimatePresence initial={false}>
              {open && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.2, ease: 'easeInOut' }}
                  className="overflow-hidden"
                >
                  <div className="flex flex-col gap-5 p-8">
                    <div className="flex flex-col items-start gap-4 sm:flex-row">
                      {/* Starts Column */}
                      <div className="flex flex-1 flex-col gap-2">
                        <Text
                          fw={600}
                          fz={12}
                          className="text-secondary-text/60 block pl-1 tracking-widest uppercase"
                        >
                          Starts
                        </Text>
                        <div className="border-plus-minus-button-border/60 bg-plus-minus-button-bg/30 flex w-fit items-center gap-1 rounded-full border p-1">
                          <button
                            type="button"
                            onClick={() => setStartMode('today')}
                            className={`cursor-pointer rounded-full px-4 py-1.5 text-[13px] font-semibold transition-all ${
                              startMode === 'today'
                                ? 'text-primary-text!'
                                : 'text-primary-text/40 hover:text-primary-text/70'
                            }`}
                            style={
                              startMode === 'today'
                                ? {
                                    background:
                                      'var(--color-plus-minus-button-bg)',
                                    borderTop:
                                      '1px solid var(--color-plus-minus-button-border)',
                                    boxShadow:
                                      'var(--shadow-plus-minus-button-shadow)',
                                  }
                                : {}
                            }
                          >
                            Today
                          </button>
                          <button
                            type="button"
                            onClick={() => setStartMode('custom')}
                            className={`cursor-pointer rounded-full px-4 py-1.5 text-[13px] font-semibold transition-all ${
                              startMode === 'custom'
                                ? 'text-primary-text!'
                                : 'text-primary-text/40 hover:text-primary-text/70'
                            }`}
                            style={
                              startMode === 'custom'
                                ? {
                                    background:
                                      'var(--color-plus-minus-button-bg)',
                                    borderTop:
                                      '1px solid var(--color-plus-minus-button-border)',
                                    boxShadow:
                                      'var(--shadow-plus-minus-button-shadow)',
                                  }
                                : {}
                            }
                          >
                            Pick a date
                          </button>
                        </div>

                        {/* Custom Date Input for STARTS */}
                        {startMode === 'custom' && (
                          <div className="mt-1">
                            <Popover
                              position="bottom"
                              width={300}
                              trapFocus
                              withArrow
                              shadow="md"
                              middlewares={{ shift: true, flip: true }}
                              zIndex={10000}
                            >
                              <Popover.Target>
                                <button
                                  type="button"
                                  className="border-plus-minus-button-border! bg-plus-minus-button-bg! text-primary-text! hover:bg-plus-minus-button-hover! flex w-full cursor-pointer items-center gap-2.5 rounded-[12px] border px-4 py-2.5 text-left transition-colors"
                                >
                                  <Calendar
                                    size={15}
                                    className="text-secondary-text/60"
                                  />
                                  <span className="text-primary-text text-[13px] font-semibold">
                                    {startDate
                                      ? dayjs(startDate).format('MMM D, YYYY')
                                      : 'Pick a date'}
                                  </span>
                                </button>
                              </Popover.Target>
                              <Popover.Dropdown
                                className="bg-primary-bg/70! border-stroke-widget! shadow-widget rounded-2xl backdrop-blur-md"
                                style={{
                                  zIndex: 10000,
                                }}
                              >
                                <DatePicker
                                  value={startDate ? new Date(startDate) : null}
                                  onChange={(date) => {
                                    if (date) {
                                      setStartDate(
                                        dayjs(date).format('YYYY-MM-DD')
                                      );
                                    }
                                  }}
                                />
                              </Popover.Dropdown>
                            </Popover>
                          </div>
                        )}
                      </div>

                      {/* Divider Line */}
                      <div className="bg-primary-text/10 mt-3 hidden w-px self-stretch sm:flex" />

                      {/* Ends Column */}
                      <div className="flex flex-1 flex-col gap-2">
                        <Text
                          fw={600}
                          fz={12}
                          className="text-secondary-text/60 block pl-1 tracking-widest uppercase"
                        >
                          Ends
                        </Text>
                        <div className="border-plus-minus-button-border/60 bg-plus-minus-button-bg/30 flex w-fit items-center gap-1 rounded-full border p-1">
                          <button
                            type="button"
                            onClick={() => setEndMode('ongoing')}
                            className={`cursor-pointer rounded-full px-4 py-1.5 text-[13px] font-semibold transition-all ${
                              endMode === 'ongoing'
                                ? 'text-primary-text!'
                                : 'text-primary-text/40 hover:text-primary-text/70'
                            }`}
                            style={
                              endMode === 'ongoing'
                                ? {
                                    background:
                                      'var(--color-plus-minus-button-bg)',
                                    borderTop:
                                      '1px solid var(--color-plus-minus-button-border)',
                                    boxShadow:
                                      'var(--shadow-plus-minus-button-shadow)',
                                  }
                                : {}
                            }
                          >
                            Ongoing
                          </button>
                          <button
                            type="button"
                            onClick={() => setEndMode('custom')}
                            className={`cursor-pointer rounded-full px-4 py-1.5 text-[13px] font-semibold transition-all ${
                              endMode === 'custom'
                                ? 'text-primary-text!'
                                : 'text-primary-text/40 hover:text-primary-text/70'
                            }`}
                            style={
                              endMode === 'custom'
                                ? {
                                    background:
                                      'var(--color-plus-minus-button-bg)',
                                    borderTop:
                                      '1px solid var(--color-plus-minus-button-border)',
                                    boxShadow:
                                      'var(--shadow-plus-minus-button-shadow)',
                                  }
                                : {}
                            }
                          >
                            Pick a date
                          </button>
                        </div>

                        {/* Custom Date Input for ENDS */}
                        {endMode === 'custom' && (
                          <div className="mt-1">
                            <Popover
                              position="bottom"
                              width={300}
                              trapFocus
                              withArrow
                              shadow="md"
                              middlewares={{ shift: true, flip: true }}
                              zIndex={10000}
                            >
                              <Popover.Target>
                                <button
                                  type="button"
                                  className="border-plus-minus-button-border! bg-plus-minus-button-bg! text-primary-text! hover:bg-plus-minus-button-hover! flex w-full cursor-pointer items-center gap-2.5 rounded-[12px] border px-4 py-2.5 text-left transition-colors"
                                >
                                  <Calendar
                                    size={15}
                                    className="text-secondary-text/60"
                                  />
                                  <span className="text-primary-text text-[13px] font-medium">
                                    {endDate
                                      ? dayjs(endDate).format('MMM D, YYYY')
                                      : 'Pick a date'}
                                  </span>
                                </button>
                              </Popover.Target>
                              <Popover.Dropdown
                                className="bg-primary-bg/70! border-stroke-widget! shadow-widget rounded-2xl backdrop-blur-md"
                                style={{
                                  zIndex: 10000,
                                }}
                              >
                                <DatePicker
                                  value={endDate ? new Date(endDate) : null}
                                  onChange={(date) => {
                                    if (date) {
                                      setEndDate(
                                        dayjs(date).format('YYYY-MM-DD')
                                      );
                                    }
                                  }}
                                />
                              </Popover.Dropdown>
                            </Popover>
                          </div>
                        )}
                      </div>
                    </div>

                    <Divider />

                    {/* Footer */}
                    <div className="mt-1 flex items-center justify-between">
                      <div className="pr-4">{statusText}</div>
                      <PrimaryGlassBtn
                        type="button"
                        onClick={handleConfirm}
                        disabled={!isLatest}
                        withArrow={true}
                      >
                        Schedule
                      </PrimaryGlassBtn>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        </div>
      </div>
    </WidgetLayout>
  );
}
