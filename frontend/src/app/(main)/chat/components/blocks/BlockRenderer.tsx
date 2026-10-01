'use client';
import type React from 'react';
import { Box } from '@mantine/core';
import { useChat } from '@/contexts/ChatContext';
import type { Block } from '@/types/chat';
import MapWidgetSkeleton from '@/components/MapWidgetSkeleton';
import {
  WidgetCampaignPlan,
  WidgetLocationMap,
  WidgetMapInteraction,
} from '../widgets';
import { MessageBlockUI } from './MessageBlockUI';
import WidgetRadiusPicker from '../widgets/WidgetRadiusPicker';
import WidgetMaidSplitView from '../widgets/WidgetMaidSplitView';
import WidgetPoiRadiusPicker from '../widgets/WidgetPoiRadiusPicker';
import SingleWidgetSkeleton from '@/components/SingleWidgetSkeleton';

interface BlockRendererProps {
  block: Block;
  isFirstAiMessage: boolean;
  isLatest: boolean;
  isStrictlyLatest?: boolean;
  /** An assistant turn before this answer carries a checkpoint, so it can be rewound. */
  canRewind?: boolean;
  /** Messages after this answer — what changing it will discard. */
  laterCount?: number;
  /** Keep the Edit / Change action visible instead of revealing it on hover. */
  emphasizeActions?: boolean;
  /** On the newest assistant reply: the answer Redo should re-send. */
  retryFor?: { id: string; content: string; laterCount?: number } | null;
  userResponse?: string | null;
}

export const BlockRenderer: React.FC<BlockRendererProps> = ({
  block,
  isFirstAiMessage,
  isLatest,
  isStrictlyLatest = false,
  canRewind = false,
  laterCount = 0,
  emphasizeActions = false,
  retryFor = null,
  userResponse,
}) => {
  const { sendMessage, streaming } = useChat();

  const handleConfirm = (value: string | number) => {
    sendMessage(value.toString(), true);
  };

  if (
    block.type === 'pending_action' &&
    block.content.action_type === 'text_input'
  ) {
    return null;
  }

  // Interactive widgets are owned by ActiveWidgetRenderer (rendered once, pinned
  // below the transcript by ChatPage) — the transcript must not render a second
  // live copy of them. Everything listed here is handled there instead.
  const isSingleWidget =
    block.type === 'pending_action' &&
    [
      'option_selection',
      'permission',
      'file_upload',
      'oauth_connect',
      'stepper_input',
      'date_range_picker',
      'campaign_intake_form',
      'campaign_plan_editor',
      'campaign_preview',
    ].includes(block.content?.action_type);

  if (isSingleWidget) {
    return null;
  }

  if (
    block.type !== 'message' &&
    isStrictlyLatest &&
    streaming &&
    !userResponse
  ) {
    if (
      block.type === 'map_data' ||
      (block.type === 'pending_action' &&
        streaming &&
        block.content?.action_type === 'map_interaction')
    ) {
      return (
        <Box className="my-5 flex w-full justify-center">
          <MapWidgetSkeleton />
        </Box>
      );
    }
    return <SingleWidgetSkeleton />;
  }

  switch (block.type) {
    case 'message':
      return (
        <MessageBlockUI
          key={block.id}
          block={block}
          canRewind={canRewind}
          laterCount={laterCount}
          emphasizeActions={emphasizeActions}
          retryFor={retryFor}
        />
      );
    case 'pending_action': {
      // map_interaction is the only pending action the transcript still renders
      // itself — it belongs inline with the message it answers. Everything else
      // returned null above.
      const { action_type } = block.content;
      switch (action_type) {
        case 'map_interaction':
          return (
            <WidgetMapInteraction
              key={block.id}
              content={block.content}
              onConfirm={handleConfirm}
              isLatest={isLatest}
              userResponse={userResponse}
            />
          );
        default:
          return (
            <div className="text-center" key={block.id}>
              Unknown action type: {action_type}
            </div>
          );
      }
    }

    case 'map_data': {
      const { action_type } = block.content;
      switch (action_type) {
        case 'radius_picker':
          return (
            <WidgetRadiusPicker
              key={block.id}
              content={block.content}
              onConfirm={handleConfirm}
              isLatest={isLatest}
              userResponse={userResponse}
            />
          );
        case 'confirm_locations':
          return (
            <WidgetLocationMap
              key={block.id}
              content={block.content}
              onConfirm={(val) => handleConfirm(val)}
              isLatest={isLatest}
              userResponse={userResponse}
            />
          );
        case 'maid_split_view':
          return (
            <WidgetMaidSplitView
              key={block.id}
              content={block.content}
              onConfirm={handleConfirm}
              isLatest={isLatest}
              userResponse={userResponse}
            />
          );
        case 'poi_radius_picker':
          return (
            <WidgetPoiRadiusPicker
              key={block.id}
              content={block.content}
              onConfirm={handleConfirm}
              isLatest={isLatest}
              userResponse={userResponse}
              widgetId={block.id}
            />
          );
        default:
          return (
            <div className="text-center" key={block.id}>
              Unknown map data type: {action_type}
            </div>
          );
      }
    }

    case 'campaign_plan':
      return (
        <WidgetCampaignPlan
          key={block.id}
          content={block.content}
          showLogo={isFirstAiMessage}
          isLatest={isLatest}
        />
      );

    default:
      return null;
  }
};
