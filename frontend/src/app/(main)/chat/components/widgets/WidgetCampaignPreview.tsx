'use client';

/**
 * WidgetCampaignPreview — the standalone Preview & Publish card.
 *
 * The backend no longer emits `action_type: "campaign_preview"` (see
 * builder_node.py's `go_live_confirm` branch) — the live path renders this
 * same content as CampaignEditor's `phase: "preview"` pane instead, so the
 * shell never drops between the plan editor and the Meta previews. This
 * component is kept only so a thread checkpointed on the old interrupt (or a
 * transcript persisted with it) still renders. See ActiveWidgetRenderer's
 * `campaign_preview` case and `PreviewPanes` (the body content, shared by
 * both this widget and the editor's preview phase).
 */
import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { ChevronDown, ChevronUp, Rocket } from 'lucide-react';
import { Box, ScrollArea } from '@mantine/core';
import type { PendingActionBlock } from '@/types/chat';
import WidgetLayout from './WidgetLayout';
import WidgetHeaderV2 from '@/components/WidgetHeaderV2';
import GetHeaderHelper from '@/utils/GetHeaderHelper';
import { getWidgetHeader, getWidgetSubheader } from '@/utils';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';
import SecondaryBtn from '@/components/secondaryBtn';
import PreviewPanes, {
  SET_LIVE,
  STAY_PAUSED,
} from '../editor/components/PreviewPanes';

interface Props {
  content: PendingActionBlock['content'];
  onConfirm: (value: string) => void;
  showLogo?: boolean;
  isLatest?: boolean;
}

export default function WidgetCampaignPreview({
  content,
  onConfirm,
  showLogo = false,
  isLatest = true,
}: Props) {
  const [open, setOpen] = useState(isLatest);
  const [selectedAdId, setSelectedAdId] = useState<string | null>(
    content.ads?.[0]?.ad_id ?? null
  );

  const ads = content.ads ?? [];
  const selectedAdIndex = Math.max(
    0,
    ads.findIndex((ad) => ad.ad_id === (selectedAdId ?? ads[0]?.ad_id))
  );
  const selectedAdCountLabel = `${ads.length === 0 ? 0 : selectedAdIndex + 1}/${ads.length}`;

  const selectAdAtIndex = (nextIndex: number) => {
    if (ads.length === 0) return;
    const safeIndex = Math.max(0, Math.min(nextIndex, ads.length - 1));
    setSelectedAdId(ads[safeIndex].ad_id);
  };

  const answer = (option: string) => {
    if (!isLatest) return;
    const promptText =
      content.prompt ||
      content.title ||
      getWidgetHeader(content.field || '') ||
      'Preview & Publish';
    onConfirm(`Q: ${promptText}\nA: ${option}`);
  };

  return (
    <WidgetLayout mode="full" showLogo={showLogo} className="max-w-4xl">
      <Box className="relative max-w-4xl rounded-[26px]">
        <Box
          className="border-stroke-widget bg-primary-widget! shadow-widget! light:shadow-lg! w-full rounded-[26px] border"
          style={{ backdropFilter: 'blur(75.9px)' }}
        >
          <div
            className={`flex w-full items-center gap-3 px-4 pt-4 pb-3 ${open ? 'border-underline/15 border-b' : 'border-b border-transparent'}`}
          >
            <button
              type="button"
              onClick={() => setOpen(!open)}
              className="flex min-w-0 flex-1 items-center gap-3 text-left cursor-pointer!"
            >
              <WidgetHeaderV2
                icon={GetHeaderHelper(content.field || '')}
                title={
                  content.title ||
                  getWidgetHeader(content.field || '') ||
                  'Preview & Publish'
                }
                subtitle={
                  content.subtitle ||
                  getWidgetSubheader(content.field || '') ||
                  content.prompt
                }
              />
            </button>

            <div className="flex items-center gap-2">
              <div className="flex items-center gap-2 px-2 py-1">
                <button
                  type="button"
                  onClick={() => selectAdAtIndex(selectedAdIndex - 1)}
                  disabled={ads.length === 0 || selectedAdIndex <= 0}
                  className="text-secondary-text flex h-7 w-7 items-center justify-center rounded-full transition-colors hover:bg-white/8 disabled:cursor-not-allowed disabled:opacity-40"
                  aria-label="Previous ad"
                >
                  <ChevronUp size={13} className="-rotate-90" />
                </button>
                <div className="text-secondary-text/80 rounded-full py-1 text-[11px]">
                  {selectedAdCountLabel}
                </div>
                <button
                  type="button"
                  onClick={() => selectAdAtIndex(selectedAdIndex + 1)}
                  disabled={
                    ads.length === 0 || selectedAdIndex >= ads.length - 1
                  }
                  className="text-secondary-text flex h-7 w-7 items-center justify-center rounded-full transition-colors hover:bg-white/8 disabled:cursor-not-allowed disabled:opacity-40"
                  aria-label="Next ad"
                >
                  <ChevronDown size={13} className="-rotate-90" />
                </button>
              </div>

              <button
                type="button"
                onClick={() => setOpen(!open)}
                className="cursor-pointer!"
              >
                {open ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
              </button>
            </div>
          </div>

          <AnimatePresence initial={false}>
            {open && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2, ease: 'easeInOut' }}
                className="overflow-hidden"
              >
                <ScrollArea h={'62vh'} scrollbarSize={7} type="always">
                  <PreviewPanes content={content} selectedAdId={selectedAdId} />
                </ScrollArea>
                <div className="border-underline/15 flex items-center justify-end gap-3 border-t px-4 py-3.5">
                  <SecondaryBtn
                    radius="xl"
                    size="sm"
                    onClick={() => answer(STAY_PAUSED)}
                    className="text-primary-text/80! border-primary-text/15! border! bg-transparent! text-[13px]!"
                  >
                    Back
                  </SecondaryBtn>
                  <PrimaryGlassBtn
                    radius="xl"
                    leftSection={<Rocket size={14} />}
                    onClick={() => answer(SET_LIVE)}
                    className="bg-primary-text/10! border-primary-text/16! border! text-[13px]! shadow-[0px_8px_32px_0px_#00000059,0px_2px_6px_0px_#00000033,0px_1.5px_0px_0px_#FFFFFF59_inset]"
                  >
                    Set Up My Campaign
                  </PrimaryGlassBtn>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </Box>
      </Box>
    </WidgetLayout>
  );
}
