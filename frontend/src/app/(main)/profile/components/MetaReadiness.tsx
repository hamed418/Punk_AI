'use client';

import { useEffect, useState } from 'react';
import { Box, Loader, Text } from '@mantine/core';
import { metaReadinessAction } from '@/actions/connect.actions';
import { MetaFixItList } from '@/components/MetaFixItCard';
import type { MetaRemediation } from '@/types/chat';

/**
 * Everything a new advertiser still has to do on a Meta screen, in one place.
 *
 * A brand-new Meta account has almost nothing configured, and each missing piece
 * used to surface only when it blocked something — one failed publish per
 * prerequisite. This reads them all up front, in the order to work down them.
 * Live Graph reads, so it loads on its own rather than riding the status poll.
 *
 * A failed read renders nothing: an unknown must never look like a problem, and
 * every item here is also raised by the place that would actually hit it.
 */
export default function MetaReadiness() {
  const [fixes, setFixes] = useState<MetaRemediation[] | null>(null);
  const [rechecking, setRechecking] = useState(false);

  useEffect(() => {
    let live = true;
    metaReadinessAction().then((result) => {
      if (live) setFixes(result.success && result.data ? result.data : []);
    });
    return () => {
      live = false;
    };
  }, []);

  // "I've done it" — re-reads live, so a fixed item drops off the list.
  const recheck = async () => {
    setRechecking(true);
    try {
      const result = await metaReadinessAction();
      if (result.success && result.data) setFixes(result.data);
    } finally {
      setRechecking(false);
    }
  };

  if (!fixes) {
    return (
      <Box className="flex items-center justify-center py-8 gap-2 text-sm text-[#FAF9F599]">
        <Loader size="xs" /> Checking account readiness...
      </Box>
    );
  }

  if (!fixes.length) {
    return (
      <Box className="flex flex-col items-center justify-center py-8 text-center gap-2.5">
        <div className="flex h-11 w-11 items-center justify-center rounded-full bg-emerald-500/10 text-emerald-400">
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
            <polyline points="22 4 12 14.01 9 11.01" />
          </svg>
        </div>
        <Text fz={14} fw={600} className="text-primary-text">
          All Prerequisites Met
        </Text>
        <Text fz={12} className="text-[#FAF9F580] max-w-sm">
          Your Meta account is fully ready for campaigns. No outstanding prerequisites or action items required.
        </Text>
      </Box>
    );
  }

  return (
    <Box className="flex flex-col gap-2">
      <Text fz={13} fw={600} className="text-primary-text">
        Before your first campaign
      </Text>
      <Text fz={12} className="text-[#FAF9F54D]">
        A few things only you can do on Meta&apos;s side. Work down the list.
      </Text>
      <MetaFixItList fixes={fixes} onRetry={recheck} retrying={rechecking} />
    </Box>
  );
}
