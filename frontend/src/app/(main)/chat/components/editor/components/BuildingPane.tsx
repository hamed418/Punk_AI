'use client';

/**
 * BuildingPane — the in-shell spinner shown while the backend is between
 * pauses (intake submitted but no plan yet, plan submitted but no preview
 * yet, or — for guide mode, which skips the intake form — nothing at all yet
 * after the publish-mode pick). Same content-pane wrapper geometry as the
 * form/tree/preview it will be replaced by, so swapping it out causes no
 * layout shift. `label` is normally `currentStepLabel` from `useChat()` —
 * the `update` SSE text the backend already streams during a build.
 */
import { Text } from '@mantine/core';
import { Loader2 } from 'lucide-react';

export default function BuildingPane({ label }: { label?: string | null }) {
  return (
    <div className="custom-scrollbar flex min-h-0 w-full md:w-198.5 flex-1 flex-col gap-4 overflow-y-auto p-4 md:p-5">
      <div className="flex flex-1 flex-col items-center justify-center gap-3 py-20">
        <Loader2 className="text-primary-text/50 h-6 w-6 animate-spin" />
        <Text className="text-secondary-text/60 text-[13px]">
          {label || 'Building your plan…'}
        </Text>
      </div>
    </div>
  );
}
