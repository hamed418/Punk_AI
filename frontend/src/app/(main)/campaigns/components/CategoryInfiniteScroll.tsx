'use client';

import React, { useRef, useEffect, useState, useCallback } from 'react';
import { Box, Flex, Text, useMantineColorScheme } from '@mantine/core';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { Campaign } from './dummyData';
import AwarnessCard from './cards/AwarnessCard';
import TrafficCard from './cards/TrafficCard';
import EngagementCard from './cards/EngagementCard';
import LeadsCard from './cards/LeadsCard';
import AppCard from './cards/AppCard';
import SalesCard from './cards/SalesCard';

interface CategoryHorizontalScrollProps {
  label: string;
  campaigns: Campaign[];
  sectionSpend: string;
}

const renderCard = (campaign: Campaign) => {
  switch (campaign.campaignType) {
    case 'Awareness':
      return <AwarnessCard campaign={campaign} />;
    case 'Traffic':
      return <TrafficCard campaign={campaign} />;
    case 'Engagement':
      return <EngagementCard campaign={campaign} />;
    case 'LeadGeneration':
      return <LeadsCard campaign={campaign} />;
    case 'AppPromotion':
      return <AppCard campaign={campaign} />;
    case 'SalesConversion':
      return <SalesCard campaign={campaign} />;
    default:
      return null;
  }
};

export const CategoryInfiniteScroll: React.FC<CategoryHorizontalScrollProps> = ({
  label,
  campaigns,
  sectionSpend,
}) => {
  const { colorScheme } = useMantineColorScheme();
  const isLight = colorScheme === 'light';

  const containerRef = useRef<HTMLDivElement>(null);
  const isInteractingRef = useRef<boolean>(false);
  const hasDraggedRef = useRef<boolean>(false);
  const startXRef = useRef<number>(0);
  const startScrollLeftRef = useRef<number>(0);

  const [canScrollLeft, setCanScrollLeft] = useState<boolean>(false);
  const [canScrollRight, setCanScrollRight] = useState<boolean>(false);
  const [hasOverflow, setHasOverflow] = useState<boolean>(false);

  const checkScrollState = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;

    const { scrollLeft, scrollWidth, clientWidth } = el;
    // Allow a small tolerance for fractional pixel subpixel rendering
    const overflow = scrollWidth > clientWidth + 4;
    setHasOverflow(overflow);
    setCanScrollLeft(overflow && scrollLeft > 4);
    setCanScrollRight(overflow && scrollLeft < scrollWidth - clientWidth - 4);
  }, []);

  useEffect(() => {
    checkScrollState();
    const el = containerRef.current;
    if (!el) return;

    const resizeObserver = new ResizeObserver(() => {
      checkScrollState();
    });
    resizeObserver.observe(el);

    window.addEventListener('resize', checkScrollState);
    const timer1 = setTimeout(checkScrollState, 50);
    const timer2 = setTimeout(checkScrollState, 250);

    return () => {
      resizeObserver.disconnect();
      window.removeEventListener('resize', checkScrollState);
      clearTimeout(timer1);
      clearTimeout(timer2);
    };
  }, [checkScrollState, campaigns]);

  const handleScroll = () => {
    checkScrollState();
  };

  const handlePointerDown = (e: React.PointerEvent) => {
    if (!hasOverflow) return;
    if (e.button !== 0 && e.pointerType === 'mouse') return;
    const el = containerRef.current;
    if (!el) return;

    isInteractingRef.current = true;
    hasDraggedRef.current = false;
    startXRef.current = e.clientX;
    startScrollLeftRef.current = el.scrollLeft;
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!hasOverflow || !isInteractingRef.current) return;
    const el = containerRef.current;
    if (!el) return;

    const dx = e.clientX - startXRef.current;
    if (Math.abs(dx) > 6) {
      hasDraggedRef.current = true;
    }

    el.scrollLeft = startScrollLeftRef.current - dx;
    checkScrollState();
  };

  const handlePointerUp = () => {
    isInteractingRef.current = false;
  };

  const handleClickCapture = (e: React.MouseEvent) => {
    if (hasDraggedRef.current) {
      e.stopPropagation();
      e.preventDefault();
      hasDraggedRef.current = false;
    }
  };

  // 336px card width + 24px gap = 360px per step
  const scrollPrev = () => {
    const el = containerRef.current;
    if (!el) return;
    const step = Math.min(360, el.clientWidth - 32);
    el.scrollBy({ left: -step, behavior: 'smooth' });
  };

  const scrollNext = () => {
    const el = containerRef.current;
    if (!el) return;
    const step = Math.min(360, el.clientWidth - 32);
    el.scrollBy({ left: step, behavior: 'smooth' });
  };

  if (!campaigns.length) return null;

  const maskImageStyle = hasOverflow
    ? `linear-gradient(to right, ${canScrollLeft ? 'transparent' : 'black'} 0%, black 28px, black calc(100% - 28px), ${canScrollRight ? 'transparent' : 'black'} 100%)`
    : undefined;

  return (
    <Box className="flex w-full flex-col">
      {/* Section Header */}
      <Flex align="center" justify="space-between" className="mb-4">
        <Flex align="center" gap={8}>
          <span className="text-primary-text text-lg leading-none font-bold">
            •
          </span>
          <Text fw={600} fz={14} className="text-primary-text leading-none">
            {label}
          </Text>
          <Text fw={400} fz={13} className="text-secondary-text/50 leading-none">
            {campaigns.length}{' '}
            {campaigns.length === 1 ? 'campaign' : 'campaigns'}
          </Text>
        </Flex>

        <Flex align="center" gap={12}>
          <Text fw={500} fz={13} className="text-secondary-text/50 leading-none">
            {`$${sectionSpend} spend`}
          </Text>

          {/* Navigation chevrons only when items overflow */}
          {hasOverflow && (
            <Flex align="center" gap={6}>
              <button
                type="button"
                onClick={scrollPrev}
                disabled={!canScrollLeft}
                title="Scroll previous"
                aria-label="Scroll previous"
                className={`flex h-7 w-7 items-center justify-center rounded-full border transition-all duration-150 ${
                  !canScrollLeft
                    ? 'opacity-30 cursor-not-allowed border-transparent'
                    : 'cursor-pointer active:scale-90 hover:opacity-100'
                } ${
                  isLight
                    ? 'border-black/8 bg-black/4 text-neutral-700 hover:bg-black/8 hover:text-black'
                    : 'border-white/10 bg-white/5 text-white/70 hover:bg-white/10 hover:text-white'
                }`}
              >
                <ChevronLeft size={14} />
              </button>

              <button
                type="button"
                onClick={scrollNext}
                disabled={!canScrollRight}
                title="Scroll next"
                aria-label="Scroll next"
                className={`flex h-7 w-7 items-center justify-center rounded-full border transition-all duration-150 ${
                  !canScrollRight
                    ? 'opacity-30 cursor-not-allowed border-transparent'
                    : 'cursor-pointer active:scale-90 hover:opacity-100'
                } ${
                  isLight
                    ? 'border-black/8 bg-black/4 text-neutral-700 hover:bg-black/8 hover:text-black'
                    : 'border-white/10 bg-white/5 text-white/70 hover:bg-white/10 hover:text-white'
                }`}
              >
                <ChevronRight size={14} />
              </button>
            </Flex>
          )}
        </Flex>
      </Flex>

      {/* Cards Row */}
      <Box
        className={`relative ${
          hasOverflow
            ? '-mx-4 md:-mx-8 overflow-hidden px-4 md:px-8'
            : 'w-full'
        }`}
      >
        <div
          ref={containerRef}
          onScroll={handleScroll}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
          onClickCapture={handleClickCapture}
          className={`custom-scrollbar flex w-full flex-nowrap items-stretch gap-6 py-2 select-none overflow-x-auto ${
            hasOverflow
              ? 'cursor-grab touch-pan-x'
              : 'cursor-default'
          }`}
          style={{
            scrollbarWidth: 'none',
            msOverflowStyle: 'none',
            WebkitMaskImage: maskImageStyle,
            maskImage: maskImageStyle,
          }}
        >
          {campaigns.length > 0 ? (
            campaigns.map((camp) => (
              <div
                key={camp.id}
                className="w-84 h-114 shrink-0 flex flex-col "
              >
                {renderCard(camp)}
              </div>
            ))
          ) : (
            <div className="flex h-60 w-full items-center justify-center text-sm text-secondary-text/50">
              No data found
            </div>
          )}
        </div>
      </Box>
    </Box>
  );
};

export default CategoryInfiniteScroll;
