'use client';

import {
  WidgetDateRangePicker,
  WidgetLocationMap,
  WidgetMapInteraction,
  WidgetOauthConnect,
  WidgetRadiusPickerV2,
  WidgetMaidSplitViewV2,
  WidgetPoiRadiusPickerV2,
  WidgetOptionSelectionV2,
  WidgetDateRangePickerV2,
  WidgetFileUploadV2,
} from '../../chat/components';
import type {
  ConfirmLocationsData,
  MaidSplitViewData,
  PoiRadiusPickerData,
  RadiusPickerData,
} from '@/types/chat';
import {
  dummyAssistantMessage,
  dummyAssistantMessageWithThinking,
  dummyConfirmLocations,
  dummyDateRangePicker,
  dummyFileUpload,
  dummyMaidSplitViewCategorized,
  dummyMaidSplitViewEmpty,
  dummyMaidSplitViewPopulated,
  dummyMapInteraction,
  dummyOauthConnect,
  dummyOptionSelection,
  dummyOptionSelectionWithProgress,
  dummyPoiRadiusPicker,
  dummyRadiusPicker,
  dummyUserMessage,
} from '../data/DummyData';
import WidgetGlassMorphism from './WidgetGlassMorphism';
import MapWidgetSkeleton from '../../../../components/MapWidgetSkeleton';
import { Box } from '@mantine/core';
import { MessageBlockUI } from '../../chat/components/blocks/MessageBlockUI';
import UploadCampaignContentUI from '../../chat/components/creative';
import { AiSkeleton } from '@/components/AISkeleton';
import SingleWidgetSkeleton from '@/components/SingleWidgetSkeleton';
import Loading from '@/app/loading';
import BlackDiamondMonkey from '@/components/BlackDiamondMonkey';
import WhiteDiamondMonkey from '@/components/WhiteDiamondMonkey';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const noop = (val: string | number) => {
  console.log('[TestChat] onConfirm:', val);
};

/** Thin labelled section wrapping each widget for easy visual separation. */
function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-12">
      <div className="mb-3 flex items-center gap-3">
        <span className="border-stroke-widget bg-secondary-widget text-secondary-text rounded-full border px-3 py-1 font-mono text-xs font-bold tracking-widest uppercase">
          {label}
        </span>
        <div className="border-stroke-widget flex-1 border-t border-dashed" />
      </div>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const TestChat = () => {
  return (
    <div className="bg-primary-bg font-inter! text-secondary-text h-full w-full overflow-y-auto">
      {/* Sticky header */}
      <div className="border-stroke-widget bg-primary-bg/90 sticky top-0 z-50 border-b px-6 py-3 backdrop-blur-md">
        <p className="text-secondary-text font-mono text-xs font-bold tracking-widest uppercase">
          🧪 Test Chat — Widget Playground
        </p>
        <p className="text-secondary-text/50 mt-0.5 text-xs">
          All widgets rendered with dummy data for isolated debugging
        </p>
      </div>

      <div className="mx-auto max-w-5xl px-4 py-10">
        {/* ----------------------------------------------------------------
            MESSAGE BLOCKS
        ---------------------------------------------------------------- */}
        <Section label="MessageBlock — user">
          <MessageBlockUI block={dummyUserMessage} />
        </Section>

        <Section label="MessageBlock — assistant">
          <MessageBlockUI block={dummyAssistantMessage} />
        </Section>

        <Section label="MessageBlock — assistant with thinking">
          <MessageBlockUI block={dummyAssistantMessageWithThinking} />
        </Section>

        {/* ----------------------------------------------------------------
            PENDING ACTION — simple inputs
        ---------------------------------------------------------------- */}
        <Section label="WidgetOptionSelection (no progress, isLatest)">
          <WidgetOptionSelectionV2
            content={dummyOptionSelection.content}
            onConfirm={noop}
            showLogo
            isLatest
          />
        </Section>

        <Section label="WidgetOptionSelection (with progress, not latest)">
          <WidgetOptionSelectionV2
            content={dummyOptionSelectionWithProgress.content}
            onConfirm={noop}
            showLogo={false}
            isLatest={false}
            userResponse="Q: Which targeting method?\nA: Deterministic"
          />
        </Section>
        <Section label="WidgetFileUpload">
          <WidgetFileUploadV2
            content={dummyFileUpload.content}
            onConfirm={noop}
            showLogo
            isLatest
          />
        </Section>

        <Section label="WidgetOauthConnect">
          <WidgetOauthConnect
            content={dummyOauthConnect.content}
            onConfirm={noop}
            isLatest
          />
        </Section>

        <Section label="WidgetDateRangePicker">
          <WidgetDateRangePicker
            content={dummyDateRangePicker.content}
            onConfirm={noop}
            showLogo
            isLatest
          />
        </Section>

        {/* ----------------------------------------------------------------
            MAP / MAP_DATA blocks
        ---------------------------------------------------------------- */}
        <Section label="WidgetMapInteraction (map_interaction pending_action)">
          <WidgetMapInteraction
            content={dummyMapInteraction.content}
            onConfirm={noop}
            isLatest
          />
        </Section>

        <Section label="SingleWidgetSkeleton">
          <SingleWidgetSkeleton />
        </Section>

        <Section label="WidgetSkeleton (showLogo)">
          <AiSkeleton />
        </Section>

        <Section label="WidgetSkeleton (no logo)">
          <AiSkeleton />
        </Section>

        <Section label="WidgetLocationMap — skeleton (loading state)">
          <MapWidgetSkeleton />
        </Section>

        <Section label="WidgetLocationMap — confirm_locations (2 cities)">
          <WidgetLocationMap
            content={dummyConfirmLocations.content as ConfirmLocationsData}
            onConfirm={noop}
            isLatest
          />
        </Section>

        <Section label="WidgetRadiusPicker — radius_picker">
          <WidgetRadiusPickerV2
            content={dummyRadiusPicker.content as RadiusPickerData}
            onConfirm={noop}
            isLatest
          />
        </Section>

        <Section label="WidgetMaidSplitView — maid_split_view (empty, no MAIDs yet)">
          <WidgetMaidSplitViewV2
            content={dummyMaidSplitViewEmpty.content as MaidSplitViewData}
            onConfirm={noop}
            isLatest
          />
        </Section>

        <Section label="WidgetMaidSplitView — maid_split_view (populated with MAIDs)">
          <WidgetMaidSplitViewV2
            content={dummyMaidSplitViewPopulated.content as MaidSplitViewData}
            onConfirm={noop}
            isLatest
          />
        </Section>

        <Section label="WidgetMaidSplitView — maid_split_view (poi_categories: Sephora / Ulta tabs)">
          <WidgetMaidSplitViewV2
            content={dummyMaidSplitViewCategorized.content as MaidSplitViewData}
            onConfirm={noop}
            isLatest
          />
        </Section>

        <Section label="WidgetPoiRadiusPicker — poi_radius_picker">
          <WidgetPoiRadiusPickerV2
            content={dummyPoiRadiusPicker.content as PoiRadiusPickerData}
            onConfirm={noop}
            isLatest
          />
        </Section>

        <Section label="WidgetFileUpload">
          <WidgetFileUploadV2
            content={dummyFileUpload.content}
            onConfirm={noop}
            isLatest
          />
        </Section>

        <Section label="WidgetDateRangePicker">
          <WidgetDateRangePickerV2
            content={dummyDateRangePicker.content}
            onConfirm={noop}
            isLatest
          />
        </Section>

        <Section label="WidgetGlassMorphism (isLatest)">
          <WidgetGlassMorphism
            content={dummyConfirmLocations.content as ConfirmLocationsData}
            onConfirm={noop}
            isLatest
          />
        </Section>

        <Section label="widget version 2">
          <Box className="mb-10">
            <WidgetOptionSelectionV2
              content={dummyOptionSelection.content}
              onConfirm={noop}
              showLogo
              isLatest
            />
          </Box>
          <WidgetOptionSelectionV2
            content={dummyOptionSelectionWithProgress.content}
            onConfirm={noop}
            showLogo={false}
            isLatest={false}
            userResponse="Q: Which targeting method?\nA: Deterministic"
          />
        </Section>

        <Section label="creative">
          <Box className="relative">
            <UploadCampaignContentUI />
          </Box>
        </Section>

        <Section label="loader">
          <Loading />
        </Section>

        <Section label="punk diamond monkey">
          <Box className="h-100 scale-25">
            <BlackDiamondMonkey />
          </Box>
          <Box className="h-100 scale-25">
            <WhiteDiamondMonkey />
          </Box>
        </Section>
      </div>
    </div>
  );
};

export default TestChat;
