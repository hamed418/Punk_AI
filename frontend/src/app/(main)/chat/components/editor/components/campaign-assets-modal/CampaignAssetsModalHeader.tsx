import React from 'react';
import { Box, Text } from '@mantine/core';
import { ChevronLeft, ChevronRight, Image as ImageIcon, X } from 'lucide-react';
import type { CampaignAssetsModalHeaderProps } from './types';

export default function CampaignAssetsModalHeader({
  title,
  subtitle,
  currentAd,
  currentAdSet,
  dIdx,
  flattenedAdsCount,
  activeFlatAdIndex,
  onPrevAd,
  onNextAd,
  onClose,
}: CampaignAssetsModalHeaderProps) {
  return (
    <>
      {/* ── Top Header ────────────────────────────────────────────────────── */}
      <Box className="border-primary-bg/50! flex! shrink-0! items-center! justify-between! gap-2.5 border-b! px-3.5! py-2.5! sm:gap-3! sm:px-5! sm:py-3.5!">
        <Box className="flex! min-w-0! flex-1! items-center! gap-2 sm:gap-2.5!">
          <Box className="flex! h-7.5! w-7.5! shrink-0! items-center! justify-center! rounded-full! bg-[#3D3D3A33]! text-white! sm:h-8! sm:w-8!">
            <ImageIcon size={17} />
          </Box>
          <Box className="flex! min-w-0! flex-1! flex-col!">
            <Text
              fz={{ base: 14, sm: 16 }}
              fw={600}
              className="text-primary-text! truncate! tracking-tight"
            >
              {title || 'Campaign Assets'}
            </Text>
            <Text
              fz={{ base: 11, sm: 12.5 }}
              className="text-primary-text/80! truncate! sm:line-clamp-none"
            >
              {subtitle ||
                'Upload your creative and write copy for each ad placement.'}
            </Text>
          </Box>
        </Box>

        <Box className="flex! shrink-0! items-center! gap-2 sm:gap-2.5!">
          {flattenedAdsCount > 1 && (
            <Box className="flex shrink-0 items-center gap-0.5 sm:gap-1">
              <button
                type="button"
                disabled={activeFlatAdIndex <= 0}
                onClick={onPrevAd}
                className="text-primary-text/60 hover:text-primary-text flex h-6 w-6 items-center justify-center rounded-full transition-colors hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-30"
                title="Previous ad"
              >
                <ChevronLeft size={14} />
              </button>
              <Text
                fz={11}
                className="text-primary-text/60 px-0.5 font-medium tabular-nums"
              >
                {activeFlatAdIndex + 1}/{flattenedAdsCount}
              </Text>
              <button
                type="button"
                disabled={activeFlatAdIndex >= flattenedAdsCount - 1}
                onClick={onNextAd}
                className="text-primary-text/60 hover:text-primary-text flex h-6 w-6 items-center justify-center rounded-full transition-colors hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-30"
                title="Next ad"
              >
                <ChevronRight size={14} />
              </button>
            </Box>
          )}

          <button
            type="button"
            onClick={onClose}
            className="flex h-7.5 w-7.5 cursor-pointer items-center justify-center rounded-full text-zinc-400 transition-colors hover:bg-white/10 hover:text-white sm:h-8 sm:w-8"
          >
            <X size={17} />
          </button>
        </Box>
      </Box>

      {/* ── Sub-header: Ad Name & Single/Carousel Toggle ──────────────────── */}
      <Box className="border-primary-bg/50! bg-primary-bg/1! flex! shrink-0! flex-nowrap! items-center! justify-between! gap-2 border-b! px-3.5! py-2! sm:gap-3! sm:px-5! sm:py-2.5!">
        <Box className="flex! min-w-0! flex-1! items-center! gap-1.5 sm:gap-2!">
          <Box className="flex! min-w-0! flex-1! flex-col! gap-0.5 sm:flex-row! sm:items-center! sm:gap-1.5!">
            <Text
              fz={{ base: 12, sm: 13 }}
              fw={700}
              className="text-primary-text! truncate! leading-tight"
            >
              {currentAd?.name ||
                `${currentAdSet?.name || 'Custom Audience'} Ad ${dIdx + 1}`}
            </Text>
            {currentAdSet?.name && currentAd?.name && (
              <Box className="flex! min-w-0! items-center! gap-1.5!">
                <Text
                  fz={13}
                  className="text-primary-text/80! hidden sm:inline!"
                >
                  ·
                </Text>
                <Text
                  fz={{ base: 11, sm: 13 }}
                  className="text-primary-text/70! truncate! leading-tight"
                >
                  {currentAdSet.name}
                </Text>
              </Box>
            )}
          </Box>
        </Box>
      </Box>
    </>
  );
}
