import React, { useState } from 'react';
import { Drawer, Tabs, Badge } from '@mantine/core';
import {
  Copy,
  Check,
  Clock,
  User,
  Globe,
  Monitor,
  Tag,
  Code2,
  ExternalLink,
  ShieldCheck,
} from 'lucide-react';
import type { PostHogEvent } from '@/api/posthog';
import { JsonViewer } from '@/components/shared/JsonViewer';

interface PostHogEventDrawerProps {
  event: PostHogEvent | null;
  isOpen: boolean;
  onClose: () => void;
}

export const PostHogEventDrawer: React.FC<PostHogEventDrawerProps> = ({
  event,
  isOpen,
  onClose,
}) => {
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  if (!event) return null;

  const handleCopy = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 1800);
  };

  const props = event.properties || {};

  // Separate UTM and standard PostHog props from custom payload
  const utmKeys = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', '$referrer', '$initial_referrer'];
  const systemKeys = [
    '$current_url',
    '$pathname',
    '$browser',
    '$browser_version',
    '$os',
    '$device',
    '$ip',
    '$geoip_country_name',
    '$geoip_city_name',
    '$lib',
    '$lib_version',
    'app_name',
  ];

  const customKeys = Object.keys(props).filter(
    (k) => !systemKeys.includes(k) && !utmKeys.includes(k) && !k.startsWith('$')
  );

  const formatTime = (iso: string) => {
    try {
      const d = new Date(iso);
      return {
        formatted: d.toLocaleString(),
        utc: d.toUTCString(),
      };
    } catch {
      return { formatted: iso, utc: iso };
    }
  };

  const time = formatTime(event.timestamp);

  return (
    <Drawer
      opened={isOpen}
      onClose={onClose}
      position="right"
      size="xl"
      title={
        <div className="flex items-center gap-2.5">
          <span
            className="w-2.5 h-2.5 rounded-full shrink-0"
            style={{ backgroundColor: event.category_color }}
          />
          <div className="flex items-center gap-2">
            <h3 className="text-base font-bold text-text-dark tracking-tight">
              {event.event}
            </h3>
            <Badge
              size="sm"
              variant="light"
              style={{
                backgroundColor: `${event.category_color}18`,
                color: event.category_color,
                border: `1px solid ${event.category_color}30`,
              }}
            >
              {event.category_label}
            </Badge>
          </div>
        </div>
      }
      classNames={{
        content: 'bg-surface-card text-text-dark border-l border-border-default',
        header: 'bg-surface-card border-b border-border-default px-6 py-4',
        body: 'p-0',
      }}
    >
      <div className="flex flex-col h-full">
        {/* Quick Context Strip */}
        <div className="bg-surface-primary border-b border-border-default px-6 py-3.5 flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-2 min-w-0">
            <User size={14} className="text-text-muted shrink-0" />
            <span className="text-text-muted">Distinct ID:</span>
            <span className="font-semibold text-text-dark font-mono truncate max-w-64" title={event.distinct_id}>
              {event.distinct_id}
            </span>
            <button
              type="button"
              onClick={() => handleCopy(event.distinct_id, 'distinct_id')}
              className="p-1 text-text-muted hover:text-text-dark rounded transition-colors cursor-pointer"
              title="Copy Distinct ID"
            >
              {copiedKey === 'distinct_id' ? (
                <Check size={12} className="text-state-success" />
              ) : (
                <Copy size={12} />
              )}
            </button>
          </div>

          <div className="flex items-center gap-2 text-text-muted shrink-0">
            <Clock size={14} />
            <span>{time.formatted}</span>
          </div>
        </div>

        {/* Tabbed Content */}
        <Tabs defaultValue="overview" className="flex-1 flex flex-col">
          <Tabs.List className="px-6 border-b border-border-default pt-2 bg-surface-card">
            <Tabs.Tab value="overview" leftSection={<Globe size={14} />}>
              Overview
            </Tabs.Tab>
            <Tabs.Tab
              value="properties"
              leftSection={<Tag size={14} />}
              rightSection={
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-surface-primary border border-border-default font-mono">
                  {customKeys.length}
                </span>
              }
            >
              Properties
            </Tabs.Tab>
            <Tabs.Tab value="attribution" leftSection={<ShieldCheck size={14} />}>
              Attribution & UTM
            </Tabs.Tab>
            <Tabs.Tab value="raw" leftSection={<Code2 size={14} />}>
              Raw JSON
            </Tabs.Tab>
          </Tabs.List>

          {/* TAB 1: OVERVIEW */}
          <Tabs.Panel value="overview" className="p-6 space-y-6 overflow-y-auto">
            {/* Core Event Metrics */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
              <div className="p-3.5 rounded-10 border border-border-default bg-surface-primary">
                <p className="text-[11px] font-medium text-text-muted uppercase tracking-wider mb-1">
                  Event UUID
                </p>
                <div className="flex items-center justify-between">
                  <p className="text-xs font-mono font-medium text-text-dark truncate mr-2" title={event.id}>
                    {event.id}
                  </p>
                  <button
                    type="button"
                    onClick={() => handleCopy(event.id, 'event_id')}
                    className="p-1 text-text-muted hover:text-text-dark rounded transition-colors"
                  >
                    {copiedKey === 'event_id' ? (
                      <Check size={12} className="text-state-success" />
                    ) : (
                      <Copy size={12} />
                    )}
                  </button>
                </div>
              </div>

              <div className="p-3.5 rounded-10 border border-border-default bg-surface-primary">
                <p className="text-[11px] font-medium text-text-muted uppercase tracking-wider mb-1">
                  UTC Timestamp
                </p>
                <p className="text-xs font-mono font-medium text-text-dark truncate">
                  {time.utc}
                </p>
              </div>
            </div>

            {/* Location & Client Environment */}
            <div>
              <h4 className="text-xs font-bold text-text-dark uppercase tracking-wider mb-3 flex items-center gap-1.5">
                <Monitor size={14} className="text-text-muted" />
                Client & Device Environment
              </h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 border border-border-default rounded-10 p-4 bg-surface-primary">
                <div>
                  <span className="text-xs text-text-muted">Browser:</span>
                  <p className="text-xs font-semibold text-text-dark mt-0.5">
                    {props.$browser || '—'} {props.$browser_version || ''}
                  </p>
                </div>

                <div>
                  <span className="text-xs text-text-muted">Operating System:</span>
                  <p className="text-xs font-semibold text-text-dark mt-0.5">
                    {props.$os || '—'}
                  </p>
                </div>

                <div>
                  <span className="text-xs text-text-muted">Device Type:</span>
                  <p className="text-xs font-semibold text-text-dark mt-0.5">
                    {props.$device || 'Desktop'}
                  </p>
                </div>

                <div>
                  <span className="text-xs text-text-muted">Client IP:</span>
                  <p className="text-xs font-mono font-semibold text-text-dark mt-0.5">
                    {props.$ip || '—'}
                  </p>
                </div>

                <div>
                  <span className="text-xs text-text-muted">Geo Location:</span>
                  <p className="text-xs font-semibold text-text-dark mt-0.5">
                    {props.$geoip_city_name
                      ? `${props.$geoip_city_name}, ${props.$geoip_country_name}`
                      : props.$geoip_country_name || '—'}
                  </p>
                </div>

                <div>
                  <span className="text-xs text-text-muted">App Name:</span>
                  <p className="text-xs font-semibold text-text-dark mt-0.5">
                    {props.app_name || 'punk_main_app'}
                  </p>
                </div>
              </div>
            </div>

            {/* Page Context */}
            <div>
              <h4 className="text-xs font-bold text-text-dark uppercase tracking-wider mb-3 flex items-center gap-1.5">
                <Globe size={14} className="text-text-muted" />
                Page & Route Context
              </h4>
              <div className="border border-border-default rounded-10 p-4 bg-surface-primary space-y-3">
                <div>
                  <span className="text-xs text-text-muted">Pathname:</span>
                  <p className="text-xs font-mono font-medium text-text-dark mt-0.5">
                    {props.$pathname || '—'}
                  </p>
                </div>

                <div>
                  <span className="text-xs text-text-muted">Current URL:</span>
                  <div className="flex items-center gap-2 mt-0.5">
                    <p className="text-xs font-mono font-medium text-text-dark truncate flex-1" title={props.$current_url}>
                      {props.$current_url || '—'}
                    </p>
                    {props.$current_url && (
                      <a
                        href={props.$current_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-text-muted hover:text-text-dark transition-colors"
                      >
                        <ExternalLink size={13} />
                      </a>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </Tabs.Panel>

          {/* TAB 2: CUSTOM EVENT PROPERTIES */}
          <Tabs.Panel value="properties" className="p-6 overflow-y-auto">
            {customKeys.length === 0 ? (
              <div className="text-center py-12 text-xs text-text-muted">
                No custom event properties attached to this event.
              </div>
            ) : (
              <div className="border border-border-default rounded-10 overflow-hidden">
                <table className="w-full text-left text-xs border-collapse">
                  <thead>
                    <tr className="bg-surface-primary border-b border-border-default text-text-muted">
                      <th className="py-2.5 px-4 font-medium">Property Name</th>
                      <th className="py-2.5 px-4 font-medium">Value</th>
                      <th className="py-2.5 px-4 font-medium w-16 text-right">Type</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-default bg-surface-card">
                    {customKeys.map((key) => {
                      const val = props[key];
                      const valType = Array.isArray(val) ? 'array' : typeof val;
                      const displayVal =
                        typeof val === 'object' && val !== null
                          ? JSON.stringify(val)
                          : String(val);

                      return (
                        <tr key={key} className="hover:bg-surface-primary/50 transition-colors">
                          <td className="py-2.5 px-4 font-mono font-semibold text-text-dark">
                            {key}
                          </td>
                          <td className="py-2.5 px-4 font-mono text-text-dark break-all">
                            {displayVal}
                          </td>
                          <td className="py-2.5 px-4 text-right text-[11px] text-text-muted capitalize">
                            {valType}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Tabs.Panel>

          {/* TAB 3: ATTRIBUTION & UTM */}
          <Tabs.Panel value="attribution" className="p-6 space-y-4 overflow-y-auto">
            <div className="border border-border-default rounded-10 p-4 bg-surface-primary space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <span className="text-xs text-text-muted">utm_source:</span>
                  <p className="text-xs font-semibold text-text-dark font-mono mt-0.5">
                    {props.utm_source || '—'}
                  </p>
                </div>
                <div>
                  <span className="text-xs text-text-muted">utm_medium:</span>
                  <p className="text-xs font-semibold text-text-dark font-mono mt-0.5">
                    {props.utm_medium || '—'}
                  </p>
                </div>
                <div>
                  <span className="text-xs text-text-muted">utm_campaign:</span>
                  <p className="text-xs font-semibold text-text-dark font-mono mt-0.5">
                    {props.utm_campaign || '—'}
                  </p>
                </div>
                <div>
                  <span className="text-xs text-text-muted">utm_term:</span>
                  <p className="text-xs font-semibold text-text-dark font-mono mt-0.5">
                    {props.utm_term || '—'}
                  </p>
                </div>
                <div>
                  <span className="text-xs text-text-muted">utm_content:</span>
                  <p className="text-xs font-semibold text-text-dark font-mono mt-0.5">
                    {props.utm_content || '—'}
                  </p>
                </div>
                <div>
                  <span className="text-xs text-text-muted">Referrer:</span>
                  <p className="text-xs font-semibold text-text-dark font-mono mt-0.5 truncate" title={props.$referrer || props.referrer}>
                    {props.$referrer || props.referrer || 'Direct / Organic'}
                  </p>
                </div>
              </div>
            </div>
          </Tabs.Panel>

          {/* TAB 4: RAW JSON */}
          <Tabs.Panel value="raw" className="p-6 overflow-y-auto flex-1 flex flex-col">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-text-muted font-mono">Full Event Payload</span>
              <button
                type="button"
                onClick={() => handleCopy(JSON.stringify(event, null, 2), 'raw_json')}
                className="px-2.5 py-1 text-xs rounded border border-border-default bg-surface-primary hover:bg-border-default text-text-dark flex items-center gap-1.5 transition-colors cursor-pointer"
              >
                {copiedKey === 'raw_json' ? (
                  <>
                    <Check size={12} className="text-state-success" />
                    <span>Copied!</span>
                  </>
                ) : (
                  <>
                    <Copy size={12} />
                    <span>Copy JSON</span>
                  </>
                )}
              </button>
            </div>

            <div className="p-4 rounded-10 border border-border-default bg-[#0d1117] text-white overflow-x-auto max-h-[500px] custom-scrollbar">
              <JsonViewer data={event} />
            </div>
          </Tabs.Panel>
        </Tabs>
      </div>
    </Drawer>
  );
};

export default PostHogEventDrawer;
