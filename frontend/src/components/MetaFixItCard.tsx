'use client';

import { Box, Button, Text } from '@mantine/core';
import { CircleAlert, ExternalLink, Info, RefreshCw, TriangleAlert } from 'lucide-react';
import type { MetaRemediation } from '@/types/chat';

/**
 * One thing the user has to go do in Meta themselves.
 *
 * Punk cannot accept a Terms of Service, add a payment method, verify a domain or
 * link an Instagram account — Meta exposes no API for any of it, on purpose,
 * because they are consent and identity. So the only honest response is the
 * steps, on the screen where the user hit the wall.
 *
 * The `effect` line is the one nobody should have to ask for: whether anything is
 * built, whether it is spending, and what Punk did instead. A failure message
 * that leaves someone wondering if their card is being charged is worse than no
 * message.
 *
 * `onRetry` is whatever re-runs the thing that failed — usually resubmitting the
 * current gate. Omit it where there is nothing to retry from.
 */

const TONE = {
  blocks: {
    Icon: CircleAlert,
    text: 'text-red-300',
    border: 'border-red-400/25',
    label: 'Needs you',
  },
  degrades: {
    Icon: TriangleAlert,
    text: 'text-amber-300',
    border: 'border-amber-400/25',
    label: 'Publishing with less',
  },
  warns: {
    Icon: Info,
    text: 'text-sky-300',
    border: 'border-sky-400/25',
    label: 'Worth fixing',
  },
} as const;

export function MetaFixItCard({
  fix,
  onRetry,
  retrying,
}: {
  fix: MetaRemediation;
  onRetry?: () => void;
  retrying?: boolean;
}) {
  const tone = TONE[fix.severity] ?? TONE.warns;
  const { Icon } = tone;
  // Something Meta gives Punk no way to check. Say so, and say what to do: it is
  // still a to-do for a new advertiser, and silence is what sends them through the
  // same failure once per prerequisite. No "I've done it" — there is nothing for
  // Punk to re-check, so the button would look broken.
  const label = fix.unverified ? 'Confirm this yourself' : tone.label;

  return (
    <Box className={`flex flex-col gap-2 rounded-xl border ${tone.border} px-3 py-2.5`}>
      <Box className="flex items-start gap-2">
        <Icon size={14} className={`mt-0.5 shrink-0 ${tone.text}`} />
        <Box className="flex flex-col">
          <Text fz={10} fw={700} className={`tracking-wider ${tone.text}`}>
            {label.toUpperCase()}
          </Text>
          <Text fz={13} fw={500} className="text-primary-text leading-tight">
            {fix.title}
          </Text>
        </Box>
      </Box>

      <Text fz={12} className="text-[#FAF9F54D]">
        {fix.cause}
      </Text>
      {fix.unverified && (
        <Text fz={11} className="text-[#FAF9F54D] italic">
          Meta doesn&apos;t let Punk check this from here. If you&apos;ve already done it,
          you can ignore this.
        </Text>
      )}

      <ol className="flex list-decimal flex-col gap-1 pl-4">
        {fix.steps.map((step) => (
          <li key={step} className="text-[12px] text-[#FAF9F54D]">
            {step}
          </li>
        ))}
      </ol>

      <Box className="flex flex-wrap items-center gap-2">
        {/* No button without a link: the backend sends "" rather than a URL with
            an unfilled placeholder in it, and a dead link is worse than none. */}
        {fix.url && (
          <Button
            component="a"
            href={fix.url}
            target="_blank"
            rel="noreferrer"
            variant="light"
            size="compact-xs"
            rightSection={<ExternalLink size={11} />}
          >
            Open in Meta
          </Button>
        )}
        {onRetry && !fix.unverified && (
          <Button
            variant="subtle"
            size="compact-xs"
            loading={retrying}
            leftSection={<RefreshCw size={12} />}
            onClick={onRetry}
          >
            I&apos;ve done it
          </Button>
        )}
      </Box>

      {fix.effect && (
        <Text fz={11} className="text-[#FAF9F54D] italic">
          {fix.effect}
        </Text>
      )}
    </Box>
  );
}

/** The list form. Renders nothing when there is nothing to fix. */
export function MetaFixItList({
  fixes,
  onRetry,
  retrying,
}: {
  fixes?: MetaRemediation[] | null;
  onRetry?: () => void;
  retrying?: boolean;
}) {
  if (!fixes?.length) return null;
  return (
    <Box className="flex flex-col gap-2">
      {fixes.map((fix) => (
        <MetaFixItCard
          key={fix.key}
          fix={fix}
          onRetry={onRetry}
          retrying={retrying}
        />
      ))}
    </Box>
  );
}

export default MetaFixItCard;
