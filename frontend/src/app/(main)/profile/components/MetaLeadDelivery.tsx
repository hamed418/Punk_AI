'use client';

import { useEffect, useState } from 'react';
import { Box, Button, Loader, Text } from '@mantine/core';
import { connectLeadDeliveryAction, leadDeliveryAction } from '@/actions/connect.actions';
import { MetaFixItList } from '@/components/MetaFixItCard';
import type { LeadDelivery } from '@/lib/api/connect';

/**
 * Whether each Facebook Page's leads are reaching Punk — and a way to fix it.
 *
 * Meta pushes a Page's new leads to Punk only after Punk subscribes to that Page, and
 * routes them to whichever ad account the Page is saved against. Publish does both
 * silently for a lead campaign, which left a user with no way to see why leads were
 * not arriving, or to repair it. Reading the subscription and creating it are what
 * the `pages_manage_metadata` permission is for, so this is also where it is visibly
 * used.
 *
 * An unreadable state is said as unreadable — never shown as "not connected".
 */

type Status = { label: string; tone: string };

function statusOf(row: LeadDelivery): Status {
  if (row.subscribed === null) return { label: "Can't check", tone: 'text-amber-300' };
  if (row.subscribed && row.routed) return { label: 'Connected', tone: 'text-green-300' };
  if (row.subscribed) return { label: 'Subscribed, not routed here', tone: 'text-amber-300' };
  return { label: 'Not connected', tone: 'text-[#FAF9F54D]' };
}

export default function MetaLeadDelivery() {
  const [rows, setRows] = useState<LeadDelivery[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [failed, setFailed] = useState<Record<string, LeadDelivery['remediation']>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    leadDeliveryAction().then((result) => {
      if (live) setRows(result.success && result.data ? result.data : []);
    });
    return () => {
      live = false;
    };
  }, []);

  const connect = async (pageId: string) => {
    setBusy(pageId);
    setError(null);
    try {
      const result = await connectLeadDeliveryAction(pageId);
      if (!result.success || !result.data) {
        setError(result.error ?? 'Failed to connect lead delivery.');
        return;
      }
      setFailed((prev) => ({ ...prev, [pageId]: result.data.remediation }));
      // Routing is per ad account, so connecting one Page can change another's row.
      const fresh = await leadDeliveryAction();
      if (fresh.success && fresh.data) setRows(fresh.data);
    } finally {
      setBusy(null);
    }
  };

  if (!rows) {
    return (
      <Box className="flex items-center justify-center py-8 gap-2 text-sm text-[#FAF9F599]">
        <Loader size="xs" /> Checking lead delivery subscriptions...
      </Box>
    );
  }

  if (!rows.length) {
    return (
      <Box className="flex flex-col items-center justify-center py-8 text-center gap-2">
        <Text fz={14} fw={600} className="text-primary-text">
          No Facebook Pages Found
        </Text>
        <Text fz={12} className="text-[#FAF9F580] max-w-sm">
          No Facebook Pages were found for this connection. Connect a Page with instant lead forms to configure lead delivery.
        </Text>
      </Box>
    );
  }

  const anotherIsRouted = rows.some((r) => r.routed);

  return (
    <Box className="flex flex-col gap-2">
      <Text fz={13} fw={600} className="text-primary-text">
        Lead delivery
      </Text>
      <Text fz={12} className="text-[#FAF9F54D]">
        Meta sends a Page&apos;s new leads to Punk once Punk is subscribed to that Page. One Page
        can be routed to an ad account at a time.
      </Text>
      {rows.map((row) => {
        const status = statusOf(row);
        const done = row.subscribed === true && row.routed;
        return (
          <Box key={row.page_id} className="flex flex-col gap-1">
            <Box className="flex items-center justify-between gap-2">
              <Box className="flex flex-col">
                <Text fz={13} className="text-primary-text">
                  {row.page_name || row.page_id}
                </Text>
                <Text fz={11} className={status.tone}>
                  {status.label}
                </Text>
              </Box>
              {!done && (
                <Button
                  variant="light"
                  size="compact-xs"
                  loading={busy === row.page_id}
                  disabled={busy !== null}
                  onClick={() => connect(row.page_id)}
                >
                  {anotherIsRouted && !row.routed ? 'Move lead delivery here' : 'Connect'}
                </Button>
              )}
            </Box>
            {row.subscribed === null && (
              <Text fz={11} className="text-[#FAF9F54D] italic">
                Punk couldn&apos;t read this Page&apos;s subscription. That needs the Manage Page
                metadata permission — reconnect Meta and accept every permission.
              </Text>
            )}
            <MetaFixItList fixes={failed[row.page_id]} />
          </Box>
        );
      })}
      {error && (
        <Text fz={12} className="text-red-300">
          {error}
        </Text>
      )}
    </Box>
  );
}
