import React, { useState } from 'react';
import { Drawer, Skeleton, Tooltip } from '@mantine/core';
import {
  UserCheck,
  Bot,
  Target,
  Megaphone,
  CreditCard,
  AlertTriangle,
  Star,
  CheckCircle2,
  Clock,
  ExternalLink,
  Copy,
  Check,
  ChevronDown,
  ChevronUp,
  Play,
  Share2,
  Layers,
  Sparkles,
} from 'lucide-react';
import { usePostHogUserJourney } from '@/hooks/api/usePostHogApi';
import type { UserJourneyStep } from '@/api/posthog';

interface UserJourneyDrawerProps {
  distinctId: string | null;
  isOpen: boolean;
  onClose: () => void;
}

const STEP_ICON_MAP: Record<string, React.ElementType> = {
  signup: UserCheck,
  chat_start: Bot,
  chat_end: CheckCircle2,
  audience: Target,
  meta_connect: Share2,
  campaign_publish: Megaphone,
  payment: CreditCard,
  cancel: AlertTriangle,
  feedback: Star,
  other: Layers,
};

export const UserJourneyDrawer: React.FC<UserJourneyDrawerProps> = ({
  distinctId,
  isOpen,
  onClose,
}) => {
  const { data: profile, isLoading } = usePostHogUserJourney(isOpen ? distinctId : null);
  const [copied, setCopied] = useState(false);
  const [expandedStepId, setExpandedStepId] = useState<string | null>(null);

  const handleCopyId = () => {
    if (!distinctId) return;
    navigator.clipboard.writeText(distinctId);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  const toggleExpand = (stepId: string) => {
    setExpandedStepId((prev) => (prev === stepId ? null : stepId));
  };

  return (
    <Drawer
      opened={isOpen}
      onClose={onClose}
      position="right"
      size="xl"
      padding="lg"
      title={
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-[8px] bg-text-dark flex items-center justify-center text-surface-card shrink-0">
            <Sparkles size={16} />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-text-dark tracking-tight truncate max-w-72">
                {profile?.name || distinctId || 'User Journey Timeline'}
              </h3>
              {profile?.currentLifecycleStatus && (
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-surface-primary border border-border-default text-text-dark uppercase tracking-wider">
                  {profile.currentLifecycleStatus.replace('_', ' ')}
                </span>
              )}
            </div>
            <p className="text-[11px] text-text-muted truncate max-w-72">
              {profile?.email || distinctId}
            </p>
          </div>
        </div>
      }
      styles={{
        header: {
          borderBottom: '1px solid var(--border-primary)',
          paddingBottom: '14px',
        },
        body: {
          paddingTop: '16px',
        },
      }}
    >
      {isLoading ? (
        <div className="space-y-4 py-2">
          <Skeleton height={110} radius="md" />
          <Skeleton height={50} radius="md" />
          <div className="space-y-3 pt-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} height={85} radius="md" />
            ))}
          </div>
        </div>
      ) : !profile ? (
        <div className="py-12 text-center text-xs text-text-muted space-y-2">
          <p>No journey records found for this user.</p>
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded-[8px] border border-border-default text-text-dark hover:bg-surface-primary cursor-pointer text-xs"
          >
            Close Timeline
          </button>
        </div>
      ) : (
        <div className="space-y-5 pb-6">
          {/* User Overview Profile Card */}
          <div className="rounded-12 border border-border-default bg-surface-card p-4 space-y-3.5 shadow-xs">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-full bg-surface-primary border border-border-default flex items-center justify-center text-sm font-bold text-text-dark uppercase shrink-0">
                  {profile.name.charAt(0) || 'U'}
                </div>
                <div>
                  <h4 className="text-sm font-bold text-text-dark leading-tight">
                    {profile.businessName}
                  </h4>
                  <p className="text-xs text-text-muted mt-0.5">
                    {profile.businessType || 'General Account'}
                  </p>
                  <div className="flex items-center gap-1.5 mt-1 text-[11px] font-mono text-text-dark">
                    <span className="truncate max-w-64">{profile.distinctId}</span>
                    <button
                      type="button"
                      onClick={handleCopyId}
                      className="p-1 text-text-muted hover:text-text-dark transition-colors cursor-pointer"
                      title="Copy Distinct ID"
                    >
                      {copied ? <Check size={12} className="text-state-success" /> : <Copy size={12} />}
                    </button>
                  </div>
                </div>
              </div>

              {/* Session Replay Action Link */}
              {profile.replayUrl ? (
                <Tooltip label="Opens this user's recorded session directly in PostHog Cloud" withArrow>
                  <a
                    href={profile.replayUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-2 px-3.5 py-2 rounded-[8px] bg-text-dark hover:opacity-90 text-surface-card text-xs font-semibold shadow-xs transition-all no-underline shrink-0"
                  >
                    <Play size={13} className="fill-current text-highlight-teal" />
                    <span>View Session Replay</span>
                    <ExternalLink size={12} className="opacity-80" />
                  </a>
                </Tooltip>
              ) : (
                <div className="text-[11px] text-text-muted px-2.5 py-1.5 rounded bg-surface-primary border border-border-default">
                  No active session recording
                </div>
              )}
            </div>

            {/* Attribution & Context Info Pills */}
            <div className="pt-2 border-t border-border-default flex flex-wrap items-center gap-2 text-[11px]">
              <div className="px-2.5 py-1 rounded-[6px] bg-surface-primary border border-border-default text-text-muted">
                First Seen:{' '}
                <span className="text-text-dark font-medium">
                  {new Date(profile.firstSeen).toLocaleDateString()}
                </span>
              </div>
              <div className="px-2.5 py-1 rounded-[6px] bg-surface-primary border border-border-default text-text-muted">
                Last Activity:{' '}
                <span className="text-text-dark font-medium">
                  {new Date(profile.lastSeen).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
              {profile.attribution.source && (
                <div className="px-2.5 py-1 rounded-[6px] bg-surface-primary border border-border-default text-text-muted">
                  Source:{' '}
                  <span className="text-text-dark font-medium">
                    {profile.attribution.source}
                    {profile.attribution.medium ? ` / ${profile.attribution.medium}` : ''}
                  </span>
                </div>
              )}
              {profile.latestSessionId && (
                <div className="px-2.5 py-1 rounded-[6px] bg-highlight-teal/5 border border-highlight-teal/20 text-highlight-teal font-mono">
                  Session: {profile.latestSessionId.substring(0, 8)}...
                </div>
              )}
            </div>
          </div>

          {/* Journey Funnel Breadcrumb Progression */}
          <div className="rounded-12 border border-border-default bg-surface-primary p-3">
            <div className="text-[11px] font-bold text-text-muted uppercase tracking-wider mb-2">
              Lifecycle Stage Progress
            </div>
            <div className="grid grid-cols-5 gap-1.5 text-center text-[10px] font-semibold">
              {[
                { label: 'Signup', completed: profile.completedStages.signedUp },
                { label: 'Chat', completed: profile.completedStages.chatStarted },
                { label: 'Audience', completed: profile.completedStages.audienceGenerated },
                { label: 'Publish', completed: profile.completedStages.campaignPublished },
                { label: 'Payment', completed: profile.completedStages.paymentDone },
              ].map((stage, i) => (
                <div
                  key={i}
                  className={`py-1.5 px-1 rounded-[6px] border flex items-center justify-center gap-1 transition-all ${
                    stage.completed
                      ? 'bg-surface-card border-highlight-teal/40 text-highlight-teal font-bold shadow-2xs'
                      : 'bg-surface-primary border-border-default text-text-muted opacity-60'
                  }`}
                >
                  {stage.completed && <Check size={11} strokeWidth={3} />}
                  <span>{stage.label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Humanized Steps Timeline */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-bold text-text-dark uppercase tracking-wider">
                Activity Timeline ({profile.steps.length} Steps)
              </h4>
              <span className="text-[11px] text-text-muted">Chronological order (Newest first)</span>
            </div>

            <div className="relative pl-6 space-y-4 before:content-[''] before:absolute before:left-2.5 before:top-3 before:bottom-3 before:w-0.5 before:bg-border-default">
              {profile.steps.map((step: UserJourneyStep) => {
                const Icon = STEP_ICON_MAP[step.stepType] || Layers;
                const isExpanded = expandedStepId === step.id;

                return (
                  <div key={step.id} className="relative group">
                    {/* Node Dot */}
                    <div
                      className="absolute -left-6 top-3 w-5 h-5 rounded-full border border-border-default bg-surface-card flex items-center justify-center text-text-dark shadow-2xs group-hover:scale-110 transition-transform"
                      style={{ color: step.badge.color }}
                    >
                      <Icon size={11} />
                    </div>

                    {/* Step Card */}
                    <div className="rounded-10 border border-border-default bg-surface-card p-3.5 hover:border-text-muted transition-all shadow-xs space-y-2">
                      {/* Step Header */}
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1.5">
                        <div className="flex items-center gap-2">
                          <h5 className="text-xs font-bold text-text-dark">{step.title}</h5>
                          <span
                            className="text-[10px] font-bold px-1.5 py-0.2 rounded"
                            style={{
                              color: step.badge.color,
                              backgroundColor: step.badge.bg,
                            }}
                          >
                            {step.badge.label}
                          </span>
                        </div>

                        <div className="flex items-center gap-2 text-[11px] text-text-muted">
                          <div className="flex items-center gap-1">
                            <Clock size={11} />
                            <span>{step.relativeTime}</span>
                          </div>
                          <span className="text-border-default">•</span>
                          <span>
                            {new Date(step.timestamp).toLocaleTimeString([], {
                              hour: '2-digit',
                              minute: '2-digit',
                              second: '2-digit',
                            })}
                          </span>
                        </div>
                      </div>

                      {/* Humanized Narrative */}
                      <p className="text-xs text-text-dark/90 leading-relaxed font-normal">
                        {step.description}
                      </p>

                      {/* Key Metrics Pills */}
                      {step.metrics && step.metrics.length > 0 && (
                        <div className="flex flex-wrap items-center gap-1.5 pt-1">
                          {step.metrics.map((m, idx) => (
                            <div
                              key={idx}
                              className="px-2 py-0.5 rounded-[4px] bg-surface-primary border border-border-default text-[10px] flex items-center gap-1"
                            >
                              <span className="text-text-muted">{m.label}:</span>
                              <span className="font-semibold text-text-dark">{m.value}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Step Action Bar & Raw Properties Toggle */}
                      <div className="pt-2 border-t border-border-default flex items-center justify-between text-[11px]">
                        {step.replayUrl ? (
                          <a
                            href={step.replayUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-text-dark hover:text-highlight-teal font-medium no-underline transition-colors"
                          >
                            <Play size={10} className="fill-current text-highlight-teal" />
                            <span>Replay at this event</span>
                            <ExternalLink size={10} />
                          </a>
                        ) : (
                          <span className="text-text-muted font-mono text-[10px]">
                            {step.rawEvent}
                          </span>
                        )}

                        <button
                          type="button"
                          onClick={() => toggleExpand(step.id)}
                          className="flex items-center gap-1 text-text-muted hover:text-text-dark transition-colors cursor-pointer"
                        >
                          <span>{isExpanded ? 'Hide Raw Details' : 'Raw Details'}</span>
                          {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                        </button>
                      </div>

                      {/* Collapsible Raw Properties */}
                      {isExpanded && (
                        <div className="mt-2 p-2.5 rounded-[6px] bg-[#141414] text-[#E5E5E5] text-[11px] font-mono overflow-x-auto max-h-48 custom-scrollbar">
                          <pre>{JSON.stringify(step.properties, null, 2)}</pre>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </Drawer>
  );
};

export default UserJourneyDrawer;
