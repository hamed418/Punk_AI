import React, { useMemo, useRef, useState, useEffect } from 'react';
import { Box, Flex, Menu, ScrollArea, SegmentedControl, Text, Tooltip } from '@mantine/core';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Check,
  ChevronDown,
  ChevronUp,
  ChevronLeft,
  ChevronRight,
  ListFilter,
  MapPin,
  Minus,
  Plus,
  ArrowDown,
  ArrowUp,
  InfoIcon,
  SlidersHorizontal,
} from 'lucide-react';
import type { MaidSplitViewData, PoiCategoryGroup } from '@/types/chat';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';
import PrimaryActionIcon from '@/components/PrimaryActionIcon';
import SecondaryActionIcon from '@/components/SecondaryActionIcon';
import WidgetHeaderV2 from '@/components/WidgetHeaderV2';
import type { Competitor, SortOption } from './types';
import { computeDynamicMetric } from './utils';
import { AudienceSummaryIcon, LocationsFoundIcon } from './MaidSplitViewIcons';
import MapWidgetGlassIconButton from '@/components/MapWidgetGlassIconButton';
import AudienceLayerBuilder from './AudienceLayerBuilder';
import type { AudiencePatch } from './audienceLayers';

interface MaidSplitViewSidePanelProps {
  content: MaidSplitViewData;
  // The audience layer builder (audience review only): recounts through this
  // session's stored rows and commits through the same chat edit path.
  sessionId?: string | null;
  onCommitAudience?: (patch: AudiencePatch) => void;
  isLatest: boolean;
  open: boolean;
  setOpen: (open: boolean) => void;
  isSearchExpanded: boolean;
  visibleCompetitors: Competitor[];
  sortBy: SortOption;
  setSortBy: (sortBy: SortOption) => void;
  stepperValue: number;
  setStepperValue: React.Dispatch<React.SetStateAction<number>>;
  onFocusCompetitor: (competitor: Competitor) => void;
  onRemoveCompetitor: (id: string) => void;
  onConfirmAction: () => void;
  onConfirmStepper: (value: number, unit?: string, prompt?: string) => void;
  // Category/brand tabs (poi_categories) — "All" is `null`. Absent/empty
  // categories means a single-angle search: no tabs to show.
  categories?: PoiCategoryGroup[];
  allCount?: number;
  activeCategoryId?: string | null;
  onSelectCategory?: (id: string | null) => void;
}

export default function MaidSplitViewSidePanel({
  content,
  sessionId = null,
  onCommitAudience,
  isLatest,
  open,
  setOpen,
  isSearchExpanded,
  visibleCompetitors,
  sortBy,
  setSortBy,
  stepperValue,
  setStepperValue,
  onFocusCompetitor,
  onRemoveCompetitor,
  onConfirmAction,
  onConfirmStepper,
  categories = [],
  allCount = 0,
  activeCategoryId = null,
  onSelectCategory,
}: MaidSplitViewSidePanelProps) {
  const isAudienceReview =
    (content.maid_count !== null && content.maid_count !== 0) ||
    !!content.visit_stats;
  const isEditable = !!content.editable;
  const pendingAction = content.pending_action;
  const [openWing, setOpenWing] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);
  const [isAscending, setIsAscending] = useState(false);

  const isDraggingRef = useRef(false);
  const startXRef = useRef(0);
  const scrollLeftStartRef = useRef(0);
  const hasDraggedRef = useRef(false);
  const velocityRef = useRef(0);
  const lastXRef = useRef(0);
  const lastTimeRef = useRef(0);
  const animationFrameRef = useRef<number | null>(null);

  const checkScroll = () => {
    if (scrollRef.current) {
      const { scrollLeft, scrollWidth, clientWidth } = scrollRef.current;
      const hasOverflow = scrollWidth > clientWidth + 2;
      const nextLeft = hasOverflow && scrollLeft > 2;
      const nextRight =
        hasOverflow && Math.ceil(scrollLeft) < scrollWidth - clientWidth - 2;
      setCanScrollLeft((prev) => (prev !== nextLeft ? nextLeft : prev));
      setCanScrollRight((prev) => (prev !== nextRight ? nextRight : prev));
    }
  };

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!scrollRef.current) return;
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
    }
    isDraggingRef.current = true;
    hasDraggedRef.current = false;
    startXRef.current = e.clientX;
    lastXRef.current = e.clientX;
    lastTimeRef.current = performance.now();
    scrollLeftStartRef.current = scrollRef.current.scrollLeft;
    velocityRef.current = 0;

    try {
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
    } catch {
      // ignore
    }
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!isDraggingRef.current || !scrollRef.current) return;
    const now = performance.now();
    const dt = now - lastTimeRef.current;
    const currentX = e.clientX;
    const dx = currentX - lastXRef.current;

    if (dt > 0) {
      velocityRef.current = 0.8 * (dx / dt) + 0.2 * velocityRef.current;
    }

    lastXRef.current = currentX;
    lastTimeRef.current = now;

    const totalDelta = currentX - startXRef.current;
    if (Math.abs(totalDelta) > 4) {
      hasDraggedRef.current = true;
    }

    scrollRef.current.scrollLeft = scrollLeftStartRef.current - totalDelta;
  };

  const handlePointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!isDraggingRef.current) return;
    isDraggingRef.current = false;

    try {
      (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      // ignore
    }

    if (!scrollRef.current) return;

    const timeSinceLastMove = performance.now() - lastTimeRef.current;
    if (timeSinceLastMove > 80) {
      velocityRef.current = 0;
      return;
    }

    let v = velocityRef.current * 16;
    if (Math.abs(v) > 0.3) {
      const friction = 0.94;
      const momentumStep = () => {
        if (!scrollRef.current || Math.abs(v) < 0.1 || isDraggingRef.current) {
          return;
        }
        scrollRef.current.scrollLeft -= v;
        v *= friction;
        animationFrameRef.current = requestAnimationFrame(momentumStep);
      };
      animationFrameRef.current = requestAnimationFrame(momentumStep);
    }
  };

  useEffect(() => {
    const timer = setTimeout(checkScroll, 200);
    checkScroll();
    window.addEventListener('resize', checkScroll);
    return () => {
      clearTimeout(timer);
      window.removeEventListener('resize', checkScroll);
    };
  }, [categories, open]);

  const scroll = (direction: 'left' | 'right') => {
    if (scrollRef.current) {
      const { clientWidth } = scrollRef.current;
      const scrollAmount =
        direction === 'left'
          ? -Math.min(200, Math.max(120, clientWidth * 0.6))
          : Math.min(200, Math.max(120, clientWidth * 0.6));
      scrollRef.current.scrollBy({ left: scrollAmount, behavior: 'smooth' });
    }
  };

  // Backend-computed aggregate only — see computeDynamicMetric's own comment
  // for why this must never be a client sum/mean over visibleCompetitors.
  // Per-POI numbers stay correct on the row list / marker labels / hover
  // card — only this whole-audience headline reads from `content` directly.
  const dynamicMetric = useMemo(
    () => computeDynamicMetric(content, sortBy),
    [sortBy, content]
  );

  const audienceSubtitle = useMemo(() => {
    if (!isAudienceReview) return '';
    const parts: string[] = [];

    if (
      typeof content.unfiltered_maid_count === 'number' &&
      content.unfiltered_maid_count > 0
    ) {
      parts.push(
        `From ${content.unfiltered_maid_count.toLocaleString()} devices`
      );
    } else if (
      typeof content.maid_count === 'number' &&
      content.maid_count > 0
    ) {
      parts.push(`From ${content.maid_count.toLocaleString()} devices`);
    }

    if (categories.length > 0) {
      parts.push(`${categories.length} of ${categories.length} brands`);
    }

    if (content.lookback_days) {
      parts.push(`last ${content.lookback_days} days`);
    } else {
      parts.push('last 30 days');
    }

    if (content.audience_filter_chips?.length) {
      parts.push(...content.audience_filter_chips);
    }

    return parts.join(' · ');
  }, [
    isAudienceReview,
    content.unfiltered_maid_count,
    content.maid_count,
    content.lookback_days,
    content.audience_filter_chips,
    categories.length,
  ]);

  const pendingActionButtons = useMemo(() => {
    if (!pendingAction) return null;
    return (
      <Box className="">
        <Box className="border-underline/50 mt-auto">
          <Box className="flex flex-col">
            <Box className="flex w-full items-center justify-between gap-2">
              <Box className="border-primary-text/10 flex w-full flex-wrap items-center justify-end gap-3 border-t px-4">
                {pendingAction.action_type === 'stepper_input' && (
                  <Flex align="center" justify="center" gap={8}>
                    <PrimaryActionIcon
                      disabled={!isLatest}
                      bg="transparent"
                      size="lg"
                      onClick={() => {
                        const s = pendingAction.stepper?.step || 1;
                        const m = pendingAction.stepper?.min || 0;
                        setStepperValue((v) =>
                          Number(Math.max(m, v - s).toFixed(2))
                        );
                      }}
                      className="hover:bg-transparent! active:bg-transparent!"
                      style={{
                        border: '1px solid rgba(255, 255, 255, 0.12)',
                        borderRadius: '14px',
                        boxShadow:
                          '0px 2px 12px 0px #00000040, 0px 1px 0px 0px #FFFFFF40 inset',
                      }}
                    >
                      <Minus size={16} />
                    </PrimaryActionIcon>
                    <PrimaryActionIcon
                      bg="transparent"
                      size="lg"
                      className="w-fit! cursor-default! bg-[#00000008] px-3! text-xs! font-normal! hover:bg-transparent! active:transform-none! active:bg-transparent!"
                      style={{
                        border: '1px solid rgba(255, 255, 255, 0.12)',
                        borderRadius: '14px',
                        boxShadow:
                          '0px 2px 12px 0px #00000040, 0px 1px 0px 0px #FFFFFF40 inset',
                        backdropFilter: 'blur(15px)',
                      }}
                      aria-readonly
                    >
                      {stepperValue} {pendingAction.stepper?.unit}
                    </PrimaryActionIcon>
                    <PrimaryActionIcon
                      disabled={!isLatest}
                      bg="transparent"
                      size="lg"
                      onClick={() => {
                        const s = pendingAction.stepper?.step || 1;
                        const mx = pendingAction.stepper?.max || 9999;
                        setStepperValue((v) =>
                          Number(Math.min(mx, v + s).toFixed(2))
                        );
                      }}
                      className="hover:bg-transparent! active:bg-transparent!"
                      style={{
                        border: '1px solid rgba(255, 255, 255, 0.12)',
                        borderRadius: '14px',
                        boxShadow:
                          '0px 2px 12px 0px #00000040, 0px 1px 0px 0px #FFFFFF40 inset',
                      }}
                    >
                      <Plus size={16} />
                    </PrimaryActionIcon>
                  </Flex>
                )}
                <Box
                  className={`flex w-full items-center justify-center pt-4 ${isAudienceReview ? 'pb-1' : 'pb-4'}`}
                >
                  <PrimaryGlassBtn
                    className="w-full!"
                    onClick={() => {
                      setOpen(false);
                      if (pendingAction.action_type === 'stepper_input') {
                        onConfirmStepper(
                          stepperValue,
                          pendingAction.stepper?.unit,
                          pendingAction.prompt
                        );
                      } else {
                        onConfirmAction();
                      }
                    }}
                    disabled={!isLatest}
                  >
                    {isAudienceReview
                      ? 'Confirm Audience'
                      : `Use these ${allCount || visibleCompetitors.length || 0} locations`}
                  </PrimaryGlassBtn>
                </Box>
              </Box>
            </Box>
          </Box>
        </Box>
      </Box>
    );
  }, [
    pendingAction,
    isLatest,
    stepperValue,
    setStepperValue,
    setOpen,
    isAudienceReview,
    allCount,
    visibleCompetitors.length,
    onConfirmStepper,
    onConfirmAction,
  ]);

  return (
    <>
      {/* Main Floating Widget */}
      <div className="pointer-events-none absolute top-2 right-2 z-1000 origin-top-right scale-72 md:scale-88 lg:scale-68 xl:scale-80 2xl:scale-92">
        <div className="relative w-97.25 shrink-0">
          <AnimatePresence mode="wait">
            {!isSearchExpanded && (
              <motion.div
                key="maid-main-floating-card"
                initial={{ opacity: 0, y: -10, scale: 0.96 }}
                animate={{
                  opacity: 1,
                  y: 0,
                  scale: 1,
                }}
                exit={{ opacity: 0, y: -10, scale: 0.96 }}
                transition={{
                  type: 'spring',
                  duration: 0.35,
                  bounce: 0,
                }}
                style={{
                  backdropFilter: 'blur(75.9px)',
                  WebkitBackdropFilter: 'blur(75.9px)',
                  pointerEvents: 'auto',
                }}
                className="bg-primary-bg/1! light:border-white/90! light:border! light:backdrop-blur-[57px] shadow-widget relative overflow-hidden rounded-[30px] dark:backdrop-blur-[75.9px]"
              >
                <button
                  type="button"
                  onClick={() => {
                    setOpen(!open);
                  }}
                  className="relative z-10 w-full text-left"
                >
                  <WidgetHeaderV2
                    className={`cursor-pointer border-b bg-transparent p-0 px-4 py-3.5 transition-colors duration-150 ease-out ${open ? 'border-primary-text/5' : 'border-transparent'}`}
                    icon={
                      isAudienceReview ? (
                        <AudienceSummaryIcon />
                      ) : (
                        <LocationsFoundIcon />
                      )
                    }
                    title={
                      isAudienceReview ? 'Audience Summary' : 'Locations Found'
                    }
                    iconSize={40}
                    rightContent={
                      <div className="text-secondary-text my-auto shrink-0">
                        {open ? (
                          <ChevronUp size={20} />
                        ) : (
                          <ChevronDown size={20} />
                        )}
                      </div>
                    }
                  />
                </button>

                <AnimatePresence initial={false}>
                  {open && (
                    <motion.div
                      key="maid-floating-widget-collapsible"
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{
                        height: { duration: 0.28, ease: [0.16, 1, 0.3, 1] },
                        opacity: { duration: 0.2, ease: 'easeOut' },
                      }}
                      className="relative z-10 overflow-hidden"
                    >
                      {isAudienceReview ? (
                        <div className="flex flex-col gap-4 p-4">
                          {/* Segmented Tab Pill: Places | Advanced */}
                          <SegmentedControl
                            fullWidth
                            radius="xl"
                            value={openWing ? 'advanced' : 'places'}
                            onChange={(val) => {
                              if (val === 'advanced') {
                                if (
                                  isLatest &&
                                  !!pendingAction &&
                                  !!onCommitAudience
                                ) {
                                  setOpenWing(true);
                                }
                              } else {
                                setOpenWing(false);
                              }
                            }}
                            data={[
                              {
                                label: 'Places',
                                value: 'places',
                              },
                              {
                                label: 'Advanced',
                                value: 'advanced',
                                disabled:
                                  !isLatest ||
                                  !pendingAction ||
                                  !onCommitAudience,
                              },
                            ]}
                            classNames={{
                              root: 'w-full! bg-[#0000004D]! light:bg-black/5! rounded-full! p-1! backdrop-blur-[15.2px]!',
                              indicator:
                                'bg-white/8! light:bg-white! rounded-full! border-t! border-t-white/12! border-b! border-b-white/8! light:border-black/5! shadow-[inset_0px_1px_0px_0px_#FFFFFF40,0px_2px_12px_0px_#00000040]!',
                              control: 'border-0!',
                              label:
                                'w-full! block! text-center! text-secondary-text! data-[active]:text-primary-text! data-[active]:font-semibold! text-sm! py-[6.5px]! font-medium! transition-colors! duration-150!',
                            }}
                          />

                          {openWing ? (
                            <AudienceLayerBuilder
                              sessionId={sessionId}
                              filter={content.audience_filter}
                              categories={categories}
                              unfilteredCount={content.unfiltered_maid_count}
                              initialCount={content.maid_count}
                              onCommit={onCommitAudience}
                              onConfirmAction={() => {
                                setOpen(false);
                                if (
                                  pendingAction?.action_type ===
                                  'stepper_input'
                                ) {
                                  onConfirmStepper(
                                    stepperValue,
                                    pendingAction.stepper?.unit,
                                    pendingAction.prompt
                                  );
                                } else {
                                  onConfirmAction();
                                }
                              }}
                              isLatest={isLatest}
                              disabled={!isLatest}
                            />
                          ) : (
                            <>

                          {/* Metric Card */}
                          <div
                            className="border-stroke-widget bg-[#0000004D] light:border-none relative overflow-hidden rounded-2xl! border px-3! pt-2! pb-4! backdrop-blur-[15.2px]! -mt-2!"
                            style={{
                              background: '#0000004D',
                            }}
                          >
                            <div className="flex items-center gap-4">
                              <Text
                                fz={36}
                                fw={700}
                                className="text-primary-text tracking-tight"
                              >
                                {dynamicMetric.value}
                              </Text>
                              <Text
                                fz={14}
                                fw={600}
                                className="text-primary-text"
                              >
                                {dynamicMetric.label}
                              </Text>
                            </div>
                            {audienceSubtitle && (
                              <Text
                                fz={11.5}
                                className="text-[#C8C8C4CC] leading-relaxed"
                              >
                                {audienceSubtitle}
                              </Text>
                            )}
                          </div>

                          {/* Filter Pills Carousel */}
                          {categories.length > 0 && (
                            <Box
                              className="group relative flex-1 overflow-hidden"
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                              }}
                            >
                              <style>{`
                            .hide-scroll::-webkit-scrollbar {
                              display: none;
                            }
                          `}</style>

                              {canScrollLeft && (
                                <Box className="pointer-events-none absolute left-0 z-10 flex h-full items-center justify-start pr-4 opacity-0 transition-opacity duration-200 group-hover:pointer-events-auto group-hover:opacity-100">
                                  <button
                                    onClick={() => scroll('left')}
                                    className="text-primary-text flex h-7 w-7 cursor-pointer items-center justify-center rounded-full border border-white/17 bg-gray-800 shadow-sm transition-colors hover:bg-gray-900"
                                  >
                                    <ChevronLeft size={16} />
                                  </button>
                                </Box>
                              )}

                              <div
                                ref={scrollRef}
                                onScroll={checkScroll}
                                onPointerDown={handlePointerDown}
                                onPointerMove={handlePointerMove}
                                onPointerUp={handlePointerUp}
                                onPointerCancel={handlePointerUp}
                                className="hide-scroll flex w-full cursor-grab touch-pan-y flex-nowrap items-center gap-1.5 overflow-x-auto bg-transparent select-none active:cursor-grabbing"
                                style={{
                                  scrollbarWidth: 'none',
                                  msOverflowStyle: 'none',
                                }}
                              >
                                <button
                                  type="button"
                                  onClick={() => {
                                    if (hasDraggedRef.current) return;
                                    onSelectCategory?.(null);
                                  }}
                                  className={`border-secondary-text/17 shrink-0 cursor-pointer rounded-full border px-3 py-1.5 text-xs! font-semibold! whitespace-nowrap transition-colors ${
                                    activeCategoryId === null
                                      ? 'text-primary-text bg-white/10!'
                                      : 'text-secondary-text light:hover:bg-black/5! hover:bg-white/5!'
                                  }`}
                                >
                                  All{' '}
                                  <span className="text-[11px]! opacity-50">
                                    {' '}
                                    {allCount}
                                  </span>
                                </button>
                                {categories.map((cat) => (
                                  <button
                                    key={cat.id}
                                    type="button"
                                    onClick={() => {
                                      if (hasDraggedRef.current) return;
                                      onSelectCategory?.(cat.id);
                                    }}
                                    title={cat.kind}
                                    className={`border-secondary-text/17 shrink-0 cursor-pointer rounded-full border px-3 py-1.5 text-xs! font-semibold! whitespace-nowrap capitalize! transition-colors ${
                                      activeCategoryId === cat.id
                                        ? 'text-primary-text bg-white/10!'
                                        : 'text-secondary-text light:hover:bg-black/5! hover:bg-white/5!'
                                    }`}
                                  >
                                    {cat.key}{' '}
                                    <span className="text-[11px]! opacity-50">
                                      {' '}
                                      {cat.count}
                                    </span>
                                  </button>
                                ))}
                              </div>

                              {canScrollRight && (
                                <Box className="pointer-events-none absolute right-0 z-10 flex h-full items-center justify-end pl-4 opacity-0 transition-opacity duration-200 group-hover:pointer-events-auto group-hover:opacity-100">
                                  <button
                                    onClick={() => scroll('right')}
                                    className="text-primary-text flex h-7 w-7 cursor-pointer items-center justify-center rounded-full border border-white/17 bg-gray-800 shadow-sm transition-colors hover:bg-gray-900"
                                  >
                                    <ChevronRight size={16} />
                                  </button>
                                </Box>
                              )}
                            </Box>
                          )}

                          {/* Section Header: Confirmed Locations count & Sort Menu */}
                          <div className="flex items-center justify-between">
                            <div className="flex items-center! gap-1.5">
                              <Text
                                fw={700}
                                fz={13}
                                className="text-secondary-text"
                              >
                                Confirmed Locations
                              </Text>
                              <span className="text-secondary-text/45! text-[13px]! font-semibold!">
                                {visibleCompetitors.length}
                              </span>
                            </div>

                            <div className="flex items-center gap-1">
                              <Menu
                                shadow="md"
                                width={170}
                                position="bottom-end"
                                zIndex={1000000}
                              >
                                <Menu.Target>
                                  <button
                                    type="button"
                                    className="text-secondary-text/40! font-medium! hover:text-primary-text flex cursor-pointer items-center text-[11px]! transition-colors"
                                  >
                                    <span>
                                      {sortBy === 'total_devices'
                                        ? 'Unique Visitors'
                                        : sortBy === 'repeat_visitor_count'
                                          ? 'Repeat Visitors'
                                          : sortBy === 'repeat_visitor_pct'
                                            ? 'Repeat %'
                                            : 'Max Frequency'}
                                    </span>
                                  </button>
                                </Menu.Target>
                                <Menu.Dropdown
                                style={{
                                  backdropFilter: 'blur(15px)',
                                  WebkitBackdropFilter: 'blur(15px)',
                                  background: '#0000004D',
                                }}
                                className="light:backdrop-blur-[7.7px] border-primary-text/10! backdrop-blur-[15px]"
                              >
                                <Menu.Item
                                  className={`text-xs ${sortBy === 'total_devices' ? 'text-primary-text bg-white/10!' : 'text-secondary-text hover:bg-white/5!'}`}
                                  onClick={() => {
                                    if (sortBy === 'total_devices')
                                      setIsAscending(!isAscending);
                                    else {
                                      setSortBy('total_devices');
                                      setIsAscending(false);
                                    }
                                  }}
                                  rightSection={
                                    sortBy === 'total_devices' && (
                                      <Check size={14} />
                                    )
                                  }
                                >
                                  Unique Visitors
                                </Menu.Item>
                                <Menu.Item
                                  className={`text-xs ${sortBy === 'repeat_visitor_count' ? 'text-primary-text bg-white/10!' : 'text-secondary-text hover:bg-white/5!'}`}
                                  onClick={() => {
                                    if (sortBy === 'repeat_visitor_count')
                                      setIsAscending(!isAscending);
                                    else {
                                      setSortBy('repeat_visitor_count');
                                      setIsAscending(false);
                                    }
                                  }}
                                  rightSection={
                                    sortBy === 'repeat_visitor_count' && (
                                      <Check size={14} />
                                    )
                                  }
                                >
                                  Repeat Visitors
                                </Menu.Item>
                                <Menu.Item
                                  className={`text-xs ${sortBy === 'repeat_visitor_pct' ? 'text-primary-text bg-white/10!' : 'text-secondary-text hover:bg-white/5!'}`}
                                  onClick={() => {
                                    if (sortBy === 'repeat_visitor_pct')
                                      setIsAscending(!isAscending);
                                    else {
                                      setSortBy('repeat_visitor_pct');
                                      setIsAscending(false);
                                    }
                                  }}
                                  rightSection={
                                    sortBy === 'repeat_visitor_pct' && (
                                      <Check size={14} />
                                    )
                                  }
                                >
                                  Repeat %
                                </Menu.Item>
                                <Menu.Item
                                  className={`text-xs ${sortBy === 'max_seen' ? 'text-primary-text bg-white/10!' : 'text-secondary-text hover:bg-white/5!'}`}
                                  onClick={() => {
                                    if (sortBy === 'max_seen')
                                      setIsAscending(!isAscending);
                                    else {
                                      setSortBy('max_seen');
                                      setIsAscending(false);
                                    }
                                  }}
                                  rightSection={
                                    sortBy === 'max_seen' && <Check size={14} />
                                  }
                                >
                                  Max Frequency
                                </Menu.Item>
                              </Menu.Dropdown>
                            </Menu>

                            <button
                              type="button"
                              onClick={() => setIsAscending(!isAscending)}
                              className="text-secondary-text! hover:text-primary-text flex cursor-pointer items-center transition-colors"
                            >
                              {isAscending ? (
                                <ArrowUp size={12} />
                              ) : (
                                <ArrowDown size={12} />
                              )}
                            </button>
                          </div>
                        </div>

                          <ScrollArea
                            scrollbars="y"
                            h={
                              visibleCompetitors.length <= 3
                                ? (156 / 3) * visibleCompetitors.length
                                : 156
                            }
                            type="auto"
                            scrollbarSize={2}
                            style={{
                              backdropFilter: 'blur(44.5px)',
                              background: '#00000018',
                            }}
                            className="overflow-hidden rounded-md"
                          >
                            {visibleCompetitors.length < 1 ? (
                              <div className="border-primary-text/10 flex items-center justify-between gap-3 border-b px-3 last:border-none">
                                <div className="justify-cente flex flex-col items-start py-2">
                                  <span className="text-secondary-text text-sm font-normal">
                                    No Locations Found
                                  </span>
                                </div>
                              </div>
                            ) : (
                              (isAscending
                                ? [...visibleCompetitors].reverse()
                                : visibleCompetitors
                              ).map((competitor) => (
                                <div
                                  key={competitor.id}
                                  className="border-primary-text/10 light:hover:bg-black/5! flex cursor-pointer items-center justify-between gap-3 border-b px-3 transition-colors last:border-none hover:bg-white/5! dark:hover:bg-white/5"
                                  onClick={() =>
                                    onFocusCompetitor(competitor)
                                  }
                                >
                                  <div className="flex items-center gap-2 py-2">
                                    {!isAudienceReview && (
                                      <MapPin
                                        size={12}
                                        className="text-primary-text shrink-0"
                                      />
                                    )}
                                    <div className="flex flex-col items-start">
                                      <Text
                                        fw={600}
                                        fz={12}
                                        className={`text-primary-text ${isEditable ? 'max-w-40' : 'max-w-43'} truncate!`}
                                        title={competitor.type}
                                      >
                                        {competitor.type}
                                      </Text>
                                      <Text
                                        className="text-secondary-text max-w-40 truncate!"
                                        fz={11}
                                        fw={400}
                                      >
                                        {competitor.content}
                                      </Text>
                                    </div>
                                  </div>
                                  <div className="flex items-center gap-3">
                                    {(() => {
                                      const val =
                                        sortBy === 'repeat_visitor_count'
                                          ? competitor.visit_stats
                                              ?.repeat_visitor_count
                                          : sortBy === 'repeat_visitor_pct'
                                            ? competitor.visit_stats
                                                ?.repeat_visitor_pct !==
                                              undefined
                                              ? `${competitor.visit_stats.repeat_visitor_pct}%`
                                              : undefined
                                            : sortBy === 'max_seen'
                                              ? competitor.visit_stats
                                                  ?.max_seen !== undefined
                                                ? `${competitor.visit_stats.max_seen}x`
                                                : undefined
                                              : (competitor.audience_count ??
                                                competitor.visit_stats
                                                  ?.total_devices);
                                      const label =
                                        sortBy === 'repeat_visitor_count'
                                          ? 'Repeat'
                                          : sortBy === 'repeat_visitor_pct'
                                            ? 'Repeat %'
                                            : sortBy === 'max_seen'
                                              ? 'Max Freq'
                                              : 'Visitors';

                                      if (val === undefined || val === null)
                                        return null;

                                      return (
                                        <div className="flex flex-col items-end">
                                          <span className="text-primary-text text-sm font-bold">
                                            {typeof val === 'number'
                                              ? val.toLocaleString()
                                              : val}
                                          </span>
                                          <span className="text-secondary-text text-[8.92px] font-medium tracking-wider uppercase">
                                            {label}
                                          </span>
                                        </div>
                                      );
                                    })()}
                                    {isEditable && (
                                      <SecondaryActionIcon
                                        size="xs"
                                        radius={4}
                                        disabled={!isLatest}
                                        onClick={(e: React.MouseEvent) => {
                                          e.stopPropagation();
                                          onRemoveCompetitor(competitor.id);
                                        }}
                                        className="bg-white/10! hover:bg-white/7! active:bg-white/7! disabled:bg-white/5!"
                                      >
                                        <Minus size={12} strokeWidth={3} />
                                      </SecondaryActionIcon>
                                    )}
                                  </div>
                                </div>
                              ))
                            )}
                          </ScrollArea>

                          {/* Stepper if stepper_input */}
                          {pendingAction?.action_type === 'stepper_input' && (
                            <Flex
                              align="center"
                              justify="center"
                              gap={8}
                              className="py-1"
                            >
                              <PrimaryActionIcon
                                disabled={!isLatest}
                                bg="transparent"
                                size="lg"
                                onClick={() => {
                                  const s = pendingAction.stepper?.step || 1;
                                  const m = pendingAction.stepper?.min || 0;
                                  setStepperValue((v) =>
                                    Number(Math.max(m, v - s).toFixed(2))
                                  );
                                }}
                                className="hover:bg-transparent! active:bg-transparent!"
                                style={{
                                  border:
                                    '1px solid rgba(255, 255, 255, 0.12)',
                                  borderRadius: '14px',
                                  boxShadow:
                                    '0px 2px 12px 0px #00000040, 0px 1px 0px 0px #FFFFFF40 inset',
                                }}
                              >
                                <Minus size={16} />
                              </PrimaryActionIcon>
                              <PrimaryActionIcon
                                bg="transparent"
                                size="lg"
                                className="w-fit! cursor-default! bg-[#00000008] px-3! text-xs! font-normal! hover:bg-transparent! active:transform-none! active:bg-transparent!"
                                style={{
                                  border:
                                    '1px solid rgba(255, 255, 255, 0.12)',
                                  borderRadius: '14px',
                                  boxShadow:
                                    '0px 2px 12px 0px #00000040, 0px 1px 0px 0px #FFFFFF40 inset',
                                  backdropFilter: 'blur(15px)',
                                }}
                                aria-readonly
                              >
                                {stepperValue} {pendingAction.stepper?.unit}
                              </PrimaryActionIcon>
                              <PrimaryActionIcon
                                disabled={!isLatest}
                                bg="transparent"
                                size="lg"
                                onClick={() => {
                                  const s = pendingAction.stepper?.step || 1;
                                  const mx = pendingAction.stepper?.max || 9999;
                                  setStepperValue((v) =>
                                    Number(Math.min(mx, v + s).toFixed(2))
                                  );
                                }}
                                className="hover:bg-transparent! active:bg-transparent!"
                                style={{
                                  border:
                                    '1px solid rgba(255, 255, 255, 0.12)',
                                  borderRadius: '14px',
                                  boxShadow:
                                    '0px 2px 12px 0px #00000040, 0px 1px 0px 0px #FFFFFF40 inset',
                                }}
                              >
                                <Plus size={16} />
                              </PrimaryActionIcon>
                            </Flex>
                          )}

                          <Box className='border-t! border-primary-text/10! -mx-4! -my-2' />

                          {/* Confirm Audience Button */}
                          <div className="pt-0.5">
                            <PrimaryGlassBtn
                              className="w-full!"
                              onClick={() => {
                                setOpen(false);
                                if (
                                  pendingAction?.action_type ===
                                  'stepper_input'
                                ) {
                                  onConfirmStepper(
                                    stepperValue,
                                    pendingAction.stepper?.unit,
                                    pendingAction.prompt
                                  );
                                } else {
                                  onConfirmAction();
                                }
                              }}
                              disabled={!isLatest}
                            >
                              Confirm Audience
                            </PrimaryGlassBtn>
                          </div>
                        </>
                      )}
                    </div>
                  ) : (
                        <Box className="flex flex-col py-0">
                        {/* Audience Metric Card — only when maid_count is present */}
                        <Box
                          className={` ${isAudienceReview ? 'border-primary-text/5 border-b' : ''} px-4`}
                        >
                          {isAudienceReview && (
                            <div
                              className="border-stroke-widget light:border-none relative mb-3.5 overflow-hidden rounded-md border p-3 backdrop-blur-[15.2px]!"
                              style={{
                                background: '#0000004D',
                              }}
                            >
                              <div className="flex items-start justify-between gap-2">
                                <div>
                                  <Flex
                                    align="center"
                                    justify={'start'}
                                    gap={16}
                                  >
                                    <Text
                                      fz={30}
                                      fw={700}
                                      className="text-primary-text"
                                    >
                                      {dynamicMetric.value}
                                    </Text>
                                    <Text
                                      fz={14}
                                      fw={600}
                                      className="text-primary-text pt-1!"
                                    >
                                      {dynamicMetric.label}
                                    </Text>
                                  </Flex>
                                  {isAudienceReview &&
                                    sortBy === 'total_devices' && (
                                      <Text
                                        fz={11}
                                        className="text-secondary-text/75 mt-1 leading-tight"
                                      >
                                        Pin counts may exceed this total because
                                        visitors to multiple spots are counted
                                        on each pin, but only once overall.
                                      </Text>
                                    )}
                                </div>

                                <div className="flex shrink-0 flex-col items-start justify-start gap-1.5 self-center">
                                  {isAudienceReview &&
                                    isLatest &&
                                    !!pendingAction &&
                                    !!onCommitAudience && (
                                      <Tooltip
                                        label={
                                          openWing
                                            ? 'Close audience builder'
                                            : 'Adjust audience'
                                        }
                                        position="bottom-end"
                                        offset={8}
                                        withArrow
                                      >
                                        <MapWidgetGlassIconButton
                                          pulse={false}
                                          title={
                                            openWing
                                              ? 'Close audience builder'
                                              : 'Adjust audience'
                                          }
                                          aria-label={
                                            openWing
                                              ? 'Close audience builder'
                                              : 'Adjust audience'
                                          }
                                          onClick={() => setOpenWing((o) => !o)}
                                          className={`relative! bottom-auto! left-auto! h-7 w-7 shrink-0 self-center rounded-lg! md:h-8 md:w-8 ${
                                            openWing
                                              ? 'bg-primary-text/25! text-primary-text'
                                              : ''
                                          }`}
                                        >
                                          <SlidersHorizontal className="size-3.5 md:size-4" />
                                        </MapWidgetGlassIconButton>
                                      </Tooltip>
                                    )}

                                  {!!content.audience_filter_chips?.length && (
                                    <Tooltip
                                      multiline
                                      withArrow
                                      interactive
                                      position="bottom-end"
                                      offset={8}
                                      zIndex={100000}
                                      transitionProps={{
                                        transition: 'fade',
                                        duration: 180,
                                      }}
                                      classNames={{
                                        tooltip:
                                          'light:border-white/90! light:border! light:backdrop-blur-[57px] dark:backdrop-blur-[75.9px]',
                                      }}
                                      styles={{
                                        tooltip: {
                                          backgroundColor:
                                            'var(--mantine-color-widget-inner-glass-bg)',
                                          backdropFilter: 'blur(75.9px)',
                                          WebkitBackdropFilter: 'blur(75.9px)',
                                          border:
                                            '1px solid var(--mantine-color-plus-minus-button-border)',
                                          borderRadius: '20px',
                                          padding: '12px 14px',
                                          maxWidth: '300px',
                                          boxShadow: 'var(--shadow-widget)',
                                        },
                                        arrow: {
                                          backgroundColor:
                                            'var(--mantine-color-widget-inner-glass-bg)',
                                          border:
                                            '1px solid var(--mantine-color-plus-minus-button-border)',
                                        },
                                      }}
                                      label={
                                        <div className="flex flex-col gap-2.5">
                                          <div className="border-primary-text/10 flex flex-col gap-1 border-b pb-2">
                                            <div className="flex items-center justify-between">
                                              <span className="text-primary-text text-xs font-semibold tracking-tight">
                                                Active Filters
                                              </span>
                                              <span className="text-secondary-text/60 text-[10px] font-medium tracking-wide uppercase">
                                                {
                                                  content.audience_filter_chips
                                                    .length
                                                }{' '}
                                                filter
                                                {content.audience_filter_chips
                                                  .length > 1
                                                  ? 's'
                                                  : ''}
                                              </span>
                                            </div>
                                            {sortBy === 'total_devices' &&
                                              typeof content.unfiltered_maid_count ===
                                                'number' &&
                                              content.unfiltered_maid_count !==
                                                content.maid_count && (
                                                <Text
                                                  fz={11}
                                                  fw={500}
                                                  className="text-secondary-text"
                                                >
                                                  narrowed from{' '}
                                                  <span className="text-primary-text font-semibold">
                                                    {content.unfiltered_maid_count.toLocaleString()}
                                                  </span>{' '}
                                                  total devices
                                                </Text>
                                              )}
                                          </div>

                                          <Flex
                                            align="center"
                                            wrap="wrap"
                                            gap={6}
                                          >
                                            {content.audience_filter_chips.map(
                                              (chip, i) => (
                                                <span
                                                  key={`${chip}-${i}`}
                                                  className="border-primary-text/15 bg-primary-text/6 text-primary-text rounded-full border px-2.5 py-1 text-xs! font-medium! whitespace-nowrap shadow-[0px_1px_0px_0px_rgba(255,255,255,0.08)_inset] backdrop-blur-[10px]"
                                                >
                                                  {chip}
                                                </span>
                                              )
                                            )}
                                          </Flex>

                                          {/* Role-inference disclosure — this filter reads as
                                          owners/staff/managers, not customers, inferred from
                                          visit pattern, never a staff list. Never affects which
                                          audience is returned; a caveat on the read, not a
                                          narrowing. Rides map_data (persisted), so it survives
                                          a reload unlike a transient status line. */}
                                          {content.role_confidence && (
                                            <Text
                                              fz={11}
                                              fw={500}
                                              className="text-secondary-text border-primary-text/10 border-t pt-2"
                                            >
                                              Role estimate (
                                              {content.role_basis === 'dwell'
                                                ? 'hours on-site'
                                                : 'visit pattern'}
                                              ) —{' '}
                                              <span className="text-primary-text font-semibold">
                                                {content.role_confidence ===
                                                'high'
                                                  ? 'high confidence'
                                                  : content.role_confidence ===
                                                      'medium'
                                                    ? 'medium confidence'
                                                    : 'low confidence — try a longer lookback'}
                                              </span>
                                            </Text>
                                          )}
                                        </div>
                                      }
                                    >
                                      <MapWidgetGlassIconButton
                                        pulse={false}
                                        title="Audience filter details"
                                        aria-label="Audience filter details"
                                        className="relative! bottom-auto! left-auto! h-7 w-7 shrink-0 self-center rounded-lg! md:h-8 md:w-8"
                                      >
                                        <InfoIcon className="size-3.5 md:size-4" />
                                      </MapWidgetGlassIconButton>
                                    </Tooltip>
                                  )}
                                </div>
                              </div>
                            </div>
                          )}
                        </Box>

                        <Box className="px-4 py-4">
                          <div>
                            {(() => {
                              const sectionHeaderRow = (
                                <div className="mb-2.5 flex items-end justify-between gap-3">
                                  <Text
                                    fw={600}
                                    fz={13}
                                    className="text-primary-text flex items-center gap-2"
                                  >
                                    {isAudienceReview ? (
                                      <>
                                        Confirmed Locations{' '}
                                        <span className="text-secondary-text text-xs! font-normal">
                                          {visibleCompetitors.length}
                                        </span>
                                      </>
                                    ) : (
                                      <span className="text-[12px]!">
                                        Keep the ones you want to use. Remove
                                        the rest.
                                      </span>
                                    )}
                                  </Text>
                                  {isAudienceReview && (
                                    <Text
                                      fz={11}
                                      onClick={() =>
                                        setIsAscending(!isAscending)
                                      }
                                      className="text-secondary-text hover:text-primary-text flex cursor-pointer items-center gap-1 transition-colors"
                                    >
                                      {sortBy === 'total_devices'
                                        ? 'Unique Visitors'
                                        : sortBy === 'repeat_visitor_count'
                                          ? 'Repeat Visitors'
                                          : sortBy === 'repeat_visitor_pct'
                                            ? 'Repeat %'
                                            : 'Max Frequency'}{' '}
                                      {isAscending ? (
                                        <ArrowDown size={14} />
                                      ) : (
                                        <ArrowUp size={14} />
                                      )}
                                    </Text>
                                  )}
                                </div>
                              );

                              const filterCarouselAndMenu = (
                                <Box className="mb-3 flex items-center justify-between gap-2">
                                  {categories.length > 0 ? (
                                    <Box
                                      className="group relative flex-1 overflow-hidden"
                                      style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                      }}
                                    >
                                      <style>{`
                                    .hide-scroll::-webkit-scrollbar {
                                      display: none;
                                    }
                                  `}</style>

                                      {canScrollLeft && (
                                        <Box className="pointer-events-none absolute left-0 z-10 flex h-full items-center justify-start pr-4 opacity-0 transition-opacity duration-200 group-hover:pointer-events-auto group-hover:opacity-100">
                                          <button
                                            onClick={() => scroll('left')}
                                            className="text-primary-text flex h-7 w-7 cursor-pointer items-center justify-center rounded-full border border-white/17 bg-gray-800 shadow-sm transition-colors hover:bg-gray-900"
                                          >
                                            <ChevronLeft size={16} />
                                          </button>
                                        </Box>
                                      )}

                                      <div
                                        ref={scrollRef}
                                        onScroll={checkScroll}
                                        onPointerDown={handlePointerDown}
                                        onPointerMove={handlePointerMove}
                                        onPointerUp={handlePointerUp}
                                        onPointerCancel={handlePointerUp}
                                        className="hide-scroll flex w-full cursor-grab touch-pan-y flex-nowrap items-center gap-1.5 overflow-x-auto bg-transparent select-none active:cursor-grabbing"
                                        style={{
                                          scrollbarWidth: 'none',
                                          msOverflowStyle: 'none',
                                        }}
                                      >
                                        <button
                                          type="button"
                                          onClick={() => {
                                            if (hasDraggedRef.current) return;
                                            onSelectCategory?.(null);
                                          }}
                                          className={`border-secondary-text/17 shrink-0 cursor-pointer rounded-full border px-3 py-1.5 text-xs! font-semibold! whitespace-nowrap transition-colors ${
                                            activeCategoryId === null
                                              ? 'text-primary-text bg-white/10!'
                                              : 'text-secondary-text light:hover:bg-black/5! hover:bg-white/5!'
                                          }`}
                                        >
                                          All{' '}
                                          <span className="text-[11px]! opacity-50">
                                            {' '}
                                            {allCount}
                                          </span>
                                        </button>
                                        {categories.map((cat) => (
                                          <button
                                            key={cat.id}
                                            type="button"
                                            onClick={() => {
                                              if (hasDraggedRef.current) return;
                                              onSelectCategory?.(cat.id);
                                            }}
                                            title={cat.kind}
                                            className={`border-secondary-text/17 shrink-0 cursor-pointer rounded-full border px-3 py-1.5 text-xs! font-semibold! whitespace-nowrap capitalize! transition-colors ${
                                              activeCategoryId === cat.id
                                                ? 'text-primary-text bg-white/10!'
                                                : 'text-secondary-text light:hover:bg-black/5! hover:bg-white/5!'
                                            }`}
                                          >
                                            {cat.key}{' '}
                                            <span className="text-[11px]! opacity-50">
                                              {' '}
                                              {cat.count}
                                            </span>
                                          </button>
                                        ))}
                                      </div>

                                      {canScrollRight && (
                                        <Box className="pointer-events-none absolute right-0 z-10 flex h-full items-center justify-end pl-4 opacity-0 transition-opacity duration-200 group-hover:pointer-events-auto group-hover:opacity-100">
                                          <button
                                            onClick={() => scroll('right')}
                                            className="text-primary-text flex h-7 w-7 cursor-pointer items-center justify-center rounded-full border border-white/17 bg-gray-800 shadow-sm transition-colors hover:bg-gray-900"
                                          >
                                            <ChevronRight size={16} />
                                          </button>
                                        </Box>
                                      )}
                                    </Box>
                                  ) : (
                                    <Box className="flex-1" />
                                  )}

                                  {isAudienceReview && (
                                    <Menu
                                      shadow="md"
                                      width={180}
                                      position="bottom-end"
                                      zIndex={1000000}
                                    >
                                      <Menu.Target>
                                        <button className="text-secondary-text hover:text-primary-text flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-full border border-white/10 bg-white/5 transition-colors">
                                          <ListFilter size={16} />
                                        </button>
                                      </Menu.Target>

                                      <Menu.Dropdown
                                        style={{
                                          backdropFilter: 'blur(15px)',
                                          WebkitBackdropFilter: 'blur(15px)',
                                          background: '#0000004D',
                                        }}
                                        className="light:backdrop-blur-[7.7px] border-primary-text/10! backdrop-blur-[15px]"
                                      >
                                        <Menu.Item
                                          className={`text-xs ${sortBy === 'total_devices' ? 'text-primary-text bg-white/10!' : 'text-secondary-text light:hover:bg-black/5! hover:bg-white/5! dark:hover:bg-white/5!'}`}
                                          onClick={() =>
                                            setSortBy('total_devices')
                                          }
                                          rightSection={
                                            sortBy === 'total_devices' && (
                                              <Check size={14} />
                                            )
                                          }
                                        >
                                          Unique Visitors
                                        </Menu.Item>
                                        <Menu.Item
                                          className={`text-xs ${sortBy === 'repeat_visitor_count' ? 'text-primary-text bg-white/10!' : 'text-secondary-text light:hover:bg-black/5! hover:bg-white/5! dark:hover:bg-white/5!'}`}
                                          onClick={() =>
                                            setSortBy('repeat_visitor_count')
                                          }
                                          rightSection={
                                            sortBy ===
                                              'repeat_visitor_count' && (
                                              <Check size={14} />
                                            )
                                          }
                                        >
                                          Repeat Visitors
                                        </Menu.Item>
                                        <Menu.Item
                                          className={`text-xs ${sortBy === 'repeat_visitor_pct' ? 'text-primary-text bg-white/10!' : 'text-secondary-text light:hover:bg-black/5! hover:bg-white/5! dark:hover:bg-white/5!'}`}
                                          onClick={() =>
                                            setSortBy('repeat_visitor_pct')
                                          }
                                          rightSection={
                                            sortBy === 'repeat_visitor_pct' && (
                                              <Check size={14} />
                                            )
                                          }
                                        >
                                          Repeat %
                                        </Menu.Item>
                                        <Menu.Item
                                          className={`text-xs ${sortBy === 'max_seen' ? 'text-primary-text bg-white/10!' : 'text-secondary-text light:hover:bg-black/5! hover:bg-white/5! dark:hover:bg-white/5!'}`}
                                          onClick={() => setSortBy('max_seen')}
                                          rightSection={
                                            sortBy === 'max_seen' && (
                                              <Check size={14} />
                                            )
                                          }
                                        >
                                          Max Frequency
                                        </Menu.Item>
                                      </Menu.Dropdown>
                                    </Menu>
                                  )}
                                </Box>
                              );

                              return isAudienceReview ? (
                                <>
                                  {filterCarouselAndMenu}
                                  {sectionHeaderRow}
                                </>
                              ) : (
                                <>
                                  {sectionHeaderRow}
                                  {filterCarouselAndMenu}
                                </>
                              );
                            })()}

                            <ScrollArea
                              scrollbars="y"
                              h={
                                visibleCompetitors.length <= 3
                                  ? (156 / 3) * visibleCompetitors.length
                                  : 156
                              }
                              type="auto"
                              scrollbarSize={2}
                              style={{
                                backdropFilter: 'blur(44.5px)',
                                background: '#00000018',
                              }}
                              className="overflow-hidden rounded-md"
                            >
                              {visibleCompetitors.length < 1 ? (
                                <div className="border-primary-text/10 flex items-center justify-between gap-3 border-b px-3 last:border-none">
                                  <div className="justify-cente flex flex-col items-start py-2">
                                    <span className="text-secondary-text text-sm font-normal">
                                      No Locations Found
                                    </span>
                                  </div>
                                </div>
                              ) : (
                                (isAscending
                                  ? [...visibleCompetitors].reverse()
                                  : visibleCompetitors
                                ).map((competitor) => (
                                  <div
                                    key={competitor.id}
                                    className="border-primary-text/10 light:hover:bg-black/5! flex cursor-pointer items-center justify-between gap-3 border-b px-3 transition-colors last:border-none hover:bg-white/5! dark:hover:bg-white/5"
                                    onClick={() =>
                                      onFocusCompetitor(competitor)
                                    }
                                  >
                                    <div className="flex items-center gap-2 py-2">
                                      {!isAudienceReview && (
                                        <MapPin
                                          size={12}
                                          className="text-primary-text shrink-0"
                                        />
                                      )}
                                      <div className="flex flex-col items-start">
                                        <Text
                                          fw={600}
                                          fz={12}
                                          className={`text-primary-text ${isEditable ? 'max-w-40' : 'max-w-43'} truncate!`}
                                          title={competitor.type}
                                        >
                                          {competitor.type}
                                        </Text>
                                        <Text
                                          className="text-secondary-text max-w-40 truncate!"
                                          fz={11}
                                          fw={400}
                                        >
                                          {competitor.content}
                                        </Text>
                                      </div>
                                    </div>
                                    <div className="flex items-center gap-3">
                                      {(() => {
                                        const val =
                                          sortBy === 'repeat_visitor_count'
                                            ? competitor.visit_stats
                                                ?.repeat_visitor_count
                                            : sortBy === 'repeat_visitor_pct'
                                              ? competitor.visit_stats
                                                  ?.repeat_visitor_pct !==
                                                undefined
                                                ? `${competitor.visit_stats.repeat_visitor_pct}%`
                                                : undefined
                                              : sortBy === 'max_seen'
                                                ? competitor.visit_stats
                                                    ?.max_seen !== undefined
                                                  ? `${competitor.visit_stats.max_seen}x`
                                                  : undefined
                                                : (competitor.audience_count ??
                                                  competitor.visit_stats
                                                    ?.total_devices);
                                        const label =
                                          sortBy === 'repeat_visitor_count'
                                            ? 'Repeat'
                                            : sortBy === 'repeat_visitor_pct'
                                              ? 'Repeat %'
                                              : sortBy === 'max_seen'
                                                ? 'Max Freq'
                                                : 'Visitors';

                                        if (val === undefined || val === null)
                                          return null;

                                        return (
                                          <div className="flex flex-col items-end">
                                            <span className="text-primary-text text-sm font-bold">
                                              {typeof val === 'number'
                                                ? val.toLocaleString()
                                                : val}
                                            </span>
                                            <span className="text-secondary-text text-[8.92px] font-medium tracking-wider uppercase">
                                              {label}
                                            </span>
                                          </div>
                                        );
                                      })()}
                                      {isEditable && (
                                        <SecondaryActionIcon
                                          size="xs"
                                          radius={4}
                                          disabled={!isLatest}
                                          onClick={(e: React.MouseEvent) => {
                                            e.stopPropagation();
                                            onRemoveCompetitor(competitor.id);
                                          }}
                                          className="bg-white/10! hover:bg-white/7! active:bg-white/7! disabled:bg-white/5!"
                                        >
                                          <Minus size={12} strokeWidth={3} />
                                        </SecondaryActionIcon>
                                      )}
                                    </div>
                                  </div>
                                ))
                              )}
                            </ScrollArea>
                          </div>
                        </Box>

                        {pendingActionButtons}

                        {!pendingAction && (
                          <div className="mt-auto px-4 pt-2">
                            <PrimaryGlassBtn
                              className="w-full"
                              onClick={() => {
                                if (isLatest) {
                                  setOpen(false);
                                  onConfirmAction();
                                }
                              }}
                              disabled={!isLatest}
                            >
                              Confirm & Proceed
                            </PrimaryGlassBtn>
                          </div>
                        )}
                      </Box>
                      )}
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </>
  );
}
