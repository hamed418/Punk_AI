import React from 'react';
import { Skeleton } from '@mantine/core';
import {
  UserCheck,
  Bot,
  Target,
  Megaphone,
  CreditCard,
  TrendingDown,
  Filter,
} from 'lucide-react';
import type { FunnelStage, LifecycleStatus } from '@/api/posthog';

interface JourneyFunnelSectionProps {
  stages: FunnelStage[];
  isLoading?: boolean;
  activeStatusFilter?: LifecycleStatus;
  onFilterByStatus?: (status: LifecycleStatus) => void;
  timeFilterLabel?: string;
}

const STAGE_ICON_MAP: Record<string, React.ElementType> = {
  signup: UserCheck,
  chat: Bot,
  audience: Target,
  publish: Megaphone,
  payment: CreditCard,
};

const STAGE_TO_LIFECYCLE_MAP: Record<string, LifecycleStatus> = {
  signup: 'signed_up',
  chat: 'chat_completed',
  audience: 'audience_generated',
  publish: 'campaign_published',
  payment: 'payment_done',
};

export const JourneyFunnelSection: React.FC<JourneyFunnelSectionProps> = ({
  stages,
  isLoading = false,
  activeStatusFilter = 'all',
  onFilterByStatus,
  timeFilterLabel,
}) => {
  if (isLoading && stages.length === 0) {
    return (
      <div className="rounded-12 border border-border-default bg-surface-card p-5 shadow-xs space-y-4">
        <div className="flex items-center justify-between">
          <Skeleton height={20} width={220} radius="xs" />
          <Skeleton height={20} width={120} radius="xs" />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          {Array.from({ length: 5 }).map((_, idx) => (
            <Skeleton key={idx} height={130} radius="md" />
          ))}
        </div>
      </div>
    );
  }

  const overallConversion = stages.length > 0 ? stages[stages.length - 1].percentage : 28;
  const overallDropOff = 100 - overallConversion;

  return (
    <div className="rounded-12 border border-border-default bg-surface-card p-4 sm:p-5 shadow-xs space-y-4">
      {/* Top Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-border-default">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-bold text-text-dark tracking-tight">
              User Journey & Funnel Drop-off Analysis
            </h2>
            <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-highlight-teal/10 text-highlight-teal">
              End-to-End Lifecycle
            </span>
            {timeFilterLabel && timeFilterLabel !== 'All Time' && (
              <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-surface-primary border border-border-default text-text-dark">
                {timeFilterLabel}
              </span>
            )}
          </div>
          <p className="text-xs text-text-muted mt-0.5">
            Progression from user registration through AI interaction, audience generation, and campaign publishing.
          </p>
        </div>

        {/* Aggregate Conversion & Drop-off Pills */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-[8px] bg-surface-primary border border-border-default text-xs">
            <span className="text-text-muted">Conversion:</span>
            <span className="font-bold text-highlight-teal">{overallConversion}%</span>
          </div>
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-[8px] bg-surface-primary border border-border-default text-xs">
            <TrendingDown size={13} className="text-state-warning" />
            <span className="text-text-muted">Total Drop-off:</span>
            <span className="font-bold text-state-warning">{overallDropOff}%</span>
          </div>
        </div>
      </div>

      {/* Funnel Stage Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        {stages.map((stage, idx) => {
          const Icon = STAGE_ICON_MAP[stage.id] || UserCheck;
          const mappedStatus = STAGE_TO_LIFECYCLE_MAP[stage.id] || 'all';
          const isSelected = activeStatusFilter === mappedStatus;
          const hasDropOff = stage.dropOffRate > 0 && idx < stages.length - 1;

          return (
            <div
              key={stage.id}
              onClick={() => onFilterByStatus?.(isSelected ? 'all' : mappedStatus)}
              className={`rounded-10 border p-3.5 flex flex-col justify-between transition-all cursor-pointer relative group ${
                isSelected
                  ? 'border-text-dark bg-surface-primary shadow-xs ring-1 ring-text-dark'
                  : 'border-border-default bg-surface-card hover:bg-surface-primary/50 hover:border-text-muted'
              }`}
            >
              {/* Header: Step Number, Icon, Conversion % */}
              <div className="flex items-center justify-between gap-1 mb-2">
                <div className="flex items-center gap-1.5 min-w-0">
                  <div
                    className="w-6 h-6 rounded-[6px] flex items-center justify-center shrink-0"
                    style={{
                      backgroundColor: `${stage.color}18`,
                      color: stage.color,
                    }}
                  >
                    <Icon size={13} />
                  </div>
                  <span className="text-xs font-bold text-text-dark truncate">
                    {stage.shortLabel}
                  </span>
                </div>

                <span
                  className="text-[11px] font-bold px-1.5 py-0.2 rounded shrink-0"
                  style={{
                    color: stage.color,
                    backgroundColor: `${stage.color}14`,
                  }}
                >
                  {stage.percentage}%
                </span>
              </div>

              {/* Metric Counts */}
              <div className="my-2">
                <div className="flex items-baseline gap-1.5">
                  <span className="text-xl font-bold text-text-dark tracking-tight">
                    {stage.count.toLocaleString()}
                  </span>
                  <span className="text-[11px] text-text-muted font-normal">users</span>
                </div>
                <p className="text-[11px] text-text-muted mt-1 line-clamp-2 leading-tight">
                  {stage.description}
                </p>
              </div>

              {/* Progress Bar */}
              <div className="w-full bg-border-default rounded-full h-1.5 my-2 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${stage.percentage}%`,
                    backgroundColor: stage.color,
                  }}
                />
              </div>

              {/* Drop-off Callout Footer */}
              <div className="pt-2 border-t border-border-default flex items-center justify-between text-[10px]">
                {hasDropOff ? (
                  <div className="flex items-center gap-1 text-text-muted">
                    <span className="text-state-warning font-semibold">
                      -{stage.dropOffRate}% drop
                    </span>
                    <span>({stage.dropOffCount} dropped)</span>
                  </div>
                ) : (
                  <span className="text-highlight-teal font-semibold">
                    {idx === stages.length - 1 ? 'End conversion' : 'Full retention'}
                  </span>
                )}

                <span className="text-text-muted group-hover:text-text-dark transition-colors flex items-center gap-0.5">
                  <Filter size={10} />
                  <span>Filter</span>
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Helper Footer notice */}
      <div className="flex items-center justify-between text-xs text-text-muted pt-1">
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-highlight-teal" />
          <span>Click any stage card above to instantly filter the activity feed to that cohort.</span>
        </div>
        {activeStatusFilter !== 'all' && (
          <button
            type="button"
            onClick={() => onFilterByStatus?.('all')}
            className="text-xs font-medium text-highlight-teal hover:underline cursor-pointer"
          >
            Reset Filter
          </button>
        )}
      </div>
    </div>
  );
};

export default JourneyFunnelSection;
