import React, { useMemo, useState } from 'react';
import { Box, Flex, RangeSlider, Text } from '@mantine/core';
import { motion, AnimatePresence } from 'framer-motion';
import { Trash, X } from 'lucide-react';
import type { PoiVisitStatsCardProps } from './types';
import { getRangeText } from './utils';

export default function PoiVisitStatsCard({
  competitor,
  onClose,
  isEditable = true,
  isLatest = true,
  onRemoveCompetitor,
}: PoiVisitStatsCardProps) {
  const [isConfirmingRemove, setIsConfirmingRemove] = useState(false);
  const [rangeValue, setRangeValue] = useState<[number, number]>([0, 2]);
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const [clickedIdx, setClickedIdx] = useState<number | null>(null);

  const groups = useMemo(() => {
    if (!competitor.visit_stats?.buckets) return [];

    let val1 = 0;
    let val2 = 0;
    let val3_5 = 0;
    let val6Plus = 0;

    Object.entries(competitor.visit_stats.buckets).forEach(([key, val]) => {
      const cleanKey = key.toLowerCase().replace('x', '').trim();
      const num = parseInt(cleanKey, 10);
      if (!isNaN(num)) {
        if (num === 1) val1 += val ?? 0;
        else if (num === 2) val2 += val ?? 0;
        else if (num >= 3 && num <= 5) val3_5 += val ?? 0;
        else if (num >= 6) val6Plus += val ?? 0;
      } else {
        if (cleanKey.includes('+') || cleanKey.includes('more')) {
          val6Plus += val ?? 0;
        } else if (cleanKey === '1') {
          val1 += val ?? 0;
        } else if (cleanKey === '2') {
          val2 += val ?? 0;
        }
      }
    });

    return [
      { label: '1', value: val1 },
      { label: '2', value: val2 },
      { label: '3-5', value: val3_5 },
      { label: '6+', value: val6Plus },
    ];
  }, [competitor.visit_stats]);

  const sum = useMemo(() => {
    return groups
      .slice(rangeValue[0], rangeValue[1] + 1)
      .reduce((acc, g) => acc + g.value, 0);
  }, [groups, rangeValue]);

  const maxVal = useMemo(() => {
    return Math.max(...groups.map((g) => g.value), 1);
  }, [groups]);

  if (!competitor.visit_stats) return null;

  return (
    <Box
      className="bg-primary-bg/1! relative flex max-w-76.5! flex-col overflow-hidden rounded-[18px] text-left font-sans backdrop-blur-[75.9px]! select-none"
      style={{ width: 306, minWidth: 306, maxWidth: 306 }}
      onClick={() => setClickedIdx(null)}
    >
      <Box px={16} pt={12} pb={12} className="flex items-center">
        <AnimatePresence mode="wait" initial={false}>
          {!isConfirmingRemove ? (
            <motion.div
              key="normal-header"
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 4 }}
              transition={{ duration: 0.16, ease: 'easeOut' }}
              className="w-full"
            >
              <Flex align="center" justify="space-between" gap={10} className="w-full">
                <Flex align="center" gap={12} className="min-w-0 flex-1">
                  <a
                    href={`https://www.google.com/maps?q=${competitor.lat},${competitor.lng}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    title="Open in Google Maps"
                    className="text-primary-text! flex! h-9! w-9! shrink-0 cursor-pointer items-center! justify-center! rounded-[10px] bg-[#7979791F] transition-colors hover:bg-white/10 m-0! p-0!"
                    style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', margin: 0 }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <svg
                      width="18"
                      height="18"
                      viewBox="0 0 18 18"
                      fill="none"
                      xmlns="http://www.w3.org/2000/svg"
                      className="shrink-0 block"
                    >
                      <path
                        d="M9 15.75C9 15.75 14.25 11.1 14.25 7.5C14.25 6.81056 14.1142 6.12787 13.8504 5.49091C13.5865 4.85395 13.1998 4.2752 12.7123 3.78769C12.2248 3.30018 11.646 2.91347 11.0091 2.64963C10.3721 2.3858 9.68944 2.25 9 2.25C8.31056 2.25 7.62787 2.3858 6.99091 2.64963C6.35395 2.91347 5.7752 3.30018 5.28769 3.78769C4.80018 4.2752 4.41347 4.85395 4.14963 5.49091C3.8858 6.12787 3.75 6.81056 3.75 7.5C3.75 11.1 9 15.75 9 15.75Z"
                        fill="#FAF9F5"
                      />
                      <path
                        d="M8.9998 9.4498C10.0768 9.4498 10.9498 8.57676 10.9498 7.4998C10.9498 6.42285 10.0768 5.5498 8.9998 5.5498C7.92285 5.5498 7.0498 6.42285 7.0498 7.4998C7.0498 8.57676 7.92285 9.4498 8.9998 9.4498Z"
                        fill="#0B0F14"
                      />
                    </svg>
                  </a>

                  <div className="flex min-w-0 flex-1 flex-col justify-center overflow-hidden">
                    <Text
                      fz={15}
                      fw={600}
                      truncate="end"
                      className="text-primary-text! block max-w-full truncate whitespace-nowrap leading-[18.75px]! tracking-[-0.09px]!"
                      title={competitor.type}
                    >
                      {competitor.type}
                    </Text>
                    {competitor.content && (
                      <Text
                        fz={13}
                        fw={400}
                        truncate="end"
                        className="text-secondary-text/70! block max-w-full truncate whitespace-nowrap leading-[16.25px]!"
                        title={competitor.content}
                      >
                        {competitor.content}
                      </Text>
                    )}
                  </div>
                </Flex>

                {/* Right: Actions */}
                <Flex align="center" gap={10} className="shrink-0">
                  {isEditable && (
                    <>
                      <button
                        type="button"
                        disabled={!isLatest}
                        onClick={(e: React.MouseEvent) => {
                          e.stopPropagation();
                          setIsConfirmingRemove(true);
                        }}
                        title="Remove"
                        className="trash-hover-btn text-primary-text/60! hover:text-red-400! group flex items-center justify-center cursor-pointer transition-colors disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        <Trash size={15} className="group-hover:stroke-red-400! transition-colors" />
                      </button>
                      <div className="bg-primary-text/15 h-3.5 w-px shrink-0 self-center" />
                    </>
                  )}
                  <button
                    type="button"
                    onClick={onClose}
                    title="Close"
                    className="text-primary-text/60 hover:text-primary-text flex items-center justify-center cursor-pointer transition-colors"
                  >
                    <X size={16} />
                  </button>
                </Flex>
              </Flex>
            </motion.div>
          ) : (
            <motion.div
              key="confirm-header"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.16, ease: 'easeOut' }}
              className="w-full"
            >
              <Flex align="center" justify="space-between" gap={10} className="w-full">
                <div className="flex min-w-0 flex-1 flex-col justify-center overflow-hidden">
                  <Text
                    fz={13}
                    fw={600}
                    className="text-primary-text! leading-[16.25px]!"
                  >
                    Remove this widget?
                  </Text>
                  <Text
                    fz={10}
                    className="text-[#C8C8C4]! leading-[13.75px]!"
                  >
                    It leaves the map for this session.
                  </Text>
                </div>

                <Flex align="center" gap={8} className="shrink-0">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setIsConfirmingRemove(false);
                    }}
                    className="text-[#C8C8C4]! hover:text-primary-text cursor-pointer px-2 py-1 text-xs! font-medium! transition-colors"
                  >
                    Keep
                  </button>
                  <button
                    type="button"
                    disabled={!isLatest}
                    onClick={(e: React.MouseEvent) => {
                      e.stopPropagation();
                      onRemoveCompetitor?.(competitor.id);
                      onClose?.();
                    }}
                    className="bg-[#FF6B6B1F]! hover:bg-[#FF6B6B33]! text-[#FF6B6B]! flex cursor-pointer items-center justify-center rounded-full px-3.5 py-1.5 text-xs! font-semibold! transition-colors disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    Remove
                  </button>
                </Flex>
              </Flex>
            </motion.div>
          )}
        </AnimatePresence>
      </Box>

      <Box pb={13} className="border-primary-text/10 border-t!" />

      {/* Main Stat & Range Label */}
      <Flex align="baseline" gap={7.5} mb={10} px={16}>
        <Text fz={24} fw={700} className="text-primary-text!">
          {sum.toLocaleString()}
        </Text>
        <Text fz={10} fw={600} tt="uppercase" className="text-primary-text/70!">
          {getRangeText(
            rangeValue[0],
            rangeValue[1],
            competitor.visit_stats.basis
          )}
        </Text>
      </Flex>

      {/* Bar Chart */}
      <Flex
        justify="space-between"
        align="end"
        h={90}
        mb={20}
        mt={-8}
        className="relative w-full"
      >
        {groups.map((group, idx) => {
          const isActive = idx >= rangeValue[0] && idx <= rangeValue[1];
          const isHovered = hoveredIdx === idx;
          const isClicked = clickedIdx === idx;
          const isTooltipVisible = isHovered || isClicked;
          const heightPercent = `${(group.value / maxVal) * 100}%`;

          return (
            <Flex
              key={group.label}
              direction="column"
              align="center"
              justify="end"
              className="h-full! flex-1! cursor-pointer"
              onMouseEnter={() => setHoveredIdx(idx)}
              onMouseLeave={() => setHoveredIdx(null)}
              onClick={(e) => {
                e.stopPropagation();
                setClickedIdx((prev) => (prev === idx ? null : idx));
              }}
            >
              {/* Bar */}
              <Box
                className="bg-widget-inner-glass-bg! light:bg-black/10! relative backdrop-blur-[15.2px]! transition-all duration-200"
                style={{
                  width: 42,
                  height: heightPercent,
                  opacity: isClicked ? 1 : isHovered ? 1 : isActive ? 0.6 : 0.4,
                }}
              >
                {/* Hover Value Tooltip */}
                <AnimatePresence>
                  {isTooltipVisible && (
                    <div
                      style={{
                        position: 'absolute',
                        top: '50%',
                        left: idx === groups.length - 1 ? undefined : '100%',
                        right: idx === groups.length - 1 ? '100%' : undefined,
                        transform: 'translateY(-50%)',
                        marginLeft: idx === groups.length - 1 ? undefined : 6,
                        marginRight: idx === groups.length - 1 ? 6 : undefined,
                        zIndex: 10,
                        pointerEvents: 'none',
                      }}
                    >
                      <motion.div
                        initial={{
                          opacity: 0,
                          x: idx === groups.length - 1 ? 5 : -5,
                          scale: 0.9,
                        }}
                        animate={{ opacity: 1, x: 0, scale: 1 }}
                        exit={{
                          opacity: 0,
                          x: idx === groups.length - 1 ? 5 : -5,
                          scale: 0.9,
                        }}
                        transition={{ duration: 0.15 }}
                        style={{ whiteSpace: 'nowrap' }}
                      >
                        <Box
                          className="bg-sidebar! light:bg-widget-inner-glass-bg! light:border-black/10! rounded-sm! border! border-white/10! backdrop-blur-[15.2px]!"
                          style={{
                            padding: '4px 8px',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            minHeight: '20px',
                          }}
                        >
                          <Text
                            fz={10}
                            fw={700}
                            className="text-primary-text!"
                            style={{
                              lineHeight: 1,
                            }}
                          >
                            {group.value.toLocaleString()}
                          </Text>
                        </Box>
                      </motion.div>
                    </div>
                  )}
                </AnimatePresence>

                {isActive && (
                  <Box
                    style={{
                      position: 'absolute',
                      bottom: 0,
                      left: 0,
                      right: 0,
                      height: 4,
                    }}
                  />
                )}
              </Box>

              {/* Label */}
              <Text
                className="text-primary-text!"
                fz={11}
                fw={600}
                mt={9}
                opacity={isActive ? 1 : isTooltipVisible ? 0.7 : 0.4}
              >
                {group.label}
              </Text>
            </Flex>
          );
        })}
      </Flex>

      {/* Slider */}
      <Box mb={10} px={16} className="w-full">
        <RangeSlider
          min={0}
          max={3}
          step={1}
          minRange={0}
          value={rangeValue}
          onChange={setRangeValue}
          label={null}
          styles={{
            track: {
              backgroundColor: '#3C3C432E',
              height: 1,
            },
            bar: {
              backgroundColor: '#FFFFFF',
              height: 1,
            },
            thumb: {
              backgroundColor: '#FFFFFF33',
              border: 'none',
              borderImageSource:
                'linear-gradient(0deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.08)),linear-gradient(0deg, rgba(255, 255, 255, 0.12), rgba(255, 255, 255, 0.12))',
              boxShadow: `0px 2.91px 6.31px 0px #0000001F, 0px 0.24px 1.94px 0px #0000001F, 0px 2px 12px 0px #00000040, 0px 1px 0px 0px #FFFFFF40 inset`,
              backdropFilter: 'blur(17.5px)',
            },
          }}
        />
      </Box>

      {/* Divider */}
      <Box pb={12} className="border-primary-text/10 border-t!" />

      {/* Footer Stats */}
      <Flex justify="space-between" align="center" px={16}>
        <Text fz={11} fw={500} className="text-primary-text!">
          Highest Frequency: {competitor.visit_stats.max_seen}
        </Text>
        <Text fz={10} fw={500} className="text-primary-text/74!">
          {competitor.visit_stats.total_devices.toLocaleString()} devices
          {competitor.visit_stats.total_visits !== undefined &&
            ` · ${competitor.visit_stats.total_visits.toLocaleString()} ${
              competitor.visit_stats.basis === 'visits' ? 'visits' : 'sightings'
            }`}
        </Text>
      </Flex>
    </Box>
  );
}
