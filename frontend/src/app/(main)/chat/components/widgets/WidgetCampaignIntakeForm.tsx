'use client';

import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { Box } from '@mantine/core';
import type { PendingActionBlock } from '@/types/chat';
import WidgetLayout from './WidgetLayout';
import WidgetHeaderV2 from '@/components/WidgetHeaderV2';
import GetHeaderHelper from '@/utils/GetHeaderHelper';
import { getWidgetHeader, getWidgetSubheader } from '@/utils';
import DynamicForm from '../forms/DynamicForm';

interface Props {
  content: PendingActionBlock['content'];
  onConfirm: (value: string) => void;
  showLogo?: boolean;
  isLatest?: boolean;
  userResponse?: string | null;
}

export default function WidgetCampaignIntakeForm({
  content,
  onConfirm,
  showLogo = false,
  isLatest = true,
  userResponse = null,
}: Props) {
  const [open, setOpen] = useState(isLatest);
  const [prevIsLatest, setPrevIsLatest] = useState(isLatest);

  if (isLatest !== prevIsLatest) {
    setPrevIsLatest(isLatest);
    if (!isLatest) {
      setOpen(false);
    }
  }

  const schema = content.form_schema;
  if (!schema) return null;

  const handleSubmit = (action: string, values: Record<string, unknown>) => {
    if (action === 'back') {
      setOpen(false);
      return;
    }
    if (!isLatest) return;
    const promptText =
      content.prompt ||
      content.title ||
      getWidgetHeader(content.field || '') ||
      'Campaign Setup';
    onConfirm(`Q: ${promptText}\nA: ${JSON.stringify({ values })}`);
  };

  const getDisplaySubtitle = () => {
    if (!userResponse) {
      return (
        content.subtitle ||
        getWidgetSubheader(content.field || '') ||
        content.prompt
      );
    }

    const parsedResponse = userResponse.includes('A:')
      ? userResponse.split('A:')[1].trim()
      : userResponse.trim();

    try {
      if (parsedResponse.startsWith('{')) {
        const data = JSON.parse(parsedResponse);
        if (data.values && typeof data.values === 'object') {
          const val = data.values as Record<string, unknown>;
          return (
            (val.business_name as string) ||
            (val.business_context as string) ||
            Object.values(val).filter(Boolean).join(' • ') ||
            parsedResponse
          );
        }
      }
    } catch {
      // Ignore JSON parse error
    }

    return parsedResponse;
  };

  return (
    <WidgetLayout mode="full" showLogo={showLogo}>
      <Box className="relative max-w-4xl rounded-[30px]">
        <Box
          className="border-stroke-widget w-full rounded-[30px] border bg-white/1"
          style={{
            boxShadow: `
              0px -1px 0px 0px #00000066 inset,
              0px 1px 0px 0px #FFFFFF1F inset,
              0px 8px 24px 0px #00000080
            `,
            backdropFilter: 'blur(75.9000015258789px)',
          }}
        >
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className={`flex w-full cursor-pointer items-center justify-between px-5 pt-5 pb-4 text-left ${open ? 'border-underline/15 border-b' : 'border-b border-transparent'}`}
          >
            <WidgetHeaderV2
              icon={GetHeaderHelper(content.field || '')}
              title={
                content.title ||
                getWidgetHeader(content.field || '') ||
                'Campaign Setup'
              }
              subtitle={getDisplaySubtitle()}
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
                <DynamicForm
                  schema={schema}
                  initialValues={content.values}
                  errors={content.errors ?? schema.errors}
                  submitMode="full"
                  submitActions={[
                    { label: 'Back', action: 'back', variant: 'ghost' },
                    { label: 'To Campaign Setup', action: 'generate' },
                  ]}
                  onSubmit={handleSubmit}
                />
              </motion.div>
            )}
          </AnimatePresence>
        </Box>
      </Box>
    </WidgetLayout>
  );
}
