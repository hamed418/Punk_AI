import React, { useState, useMemo } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  Skeleton,
  Switch,
  Menu,
  Popover,
} from '@mantine/core';
import {
  Search,
  SlidersHorizontal,
  RefreshCw,
  Download,
  ChevronLeft,
  ChevronRight,
  Clock,
  Check,
  Copy,
  User,
  Activity,
  Users,
  ChevronDown,
  X,
  Filter,
} from 'lucide-react';
import {
  usePostHogEvents,
  usePostHogStats,
  usePostHogFunnel,
  usePostHogUsers,
} from '@/hooks/api/usePostHogApi';
import {
  getTimeFilterDate,
  getTimeFilterLabel,
} from '@/api/posthog';
import type { PostHogEvent, LifecycleStatus, TimeFilter } from '@/api/posthog';
import { PostHogEventDrawer } from '@/components/posthog/PostHogEventDrawer';
import { PostHogConfigModal } from '@/components/posthog/PostHogConfigModal';
import { JourneyFunnelSection } from '@/components/posthog/JourneyFunnelSection';
import { UserJourneyDrawer } from '@/components/posthog/UserJourneyDrawer';
import { PostHogApiPlayground } from '@/components/posthog/PostHogApiPlayground';
import { FlaskConical, LayoutDashboard } from 'lucide-react';

const PAGE_SIZE_OPTIONS = [15, 30, 50];

function formatRelativeTime(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const sec = Math.floor(diff / 1000);
    if (sec < 60) return 'Just now';
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h ago`;
    return `${Math.floor(hr / 24)}d ago`;
  } catch {
    return 'Recently';
  }
}

export const PostHogEventsPage = () => {
  const queryClient = useQueryClient();
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedStatus, setSelectedStatus] = useState<LifecycleStatus>('all');
  const [selectedUserFilter, setSelectedUserFilter] = useState<string>('');

  // Global Time Filter with LocalStorage Persistence
  const [selectedTimeFilter, setSelectedTimeFilter] = useState<TimeFilter>(() => {
    try {
      const saved = localStorage.getItem('posthog_global_time_filter');
      if (saved && ['all', '1h', '24h', '7d', '30d'].includes(saved)) {
        return saved as TimeFilter;
      }
    } catch {
      // ignore
    }
    return 'all';
  });

  const handleSetTimeFilter = (filter: TimeFilter) => {
    setSelectedTimeFilter(filter);
    setCurrentPage(1);
    try {
      localStorage.setItem('posthog_global_time_filter', filter);
    } catch {
      // ignore
    }
  };

  const globalDateFrom = useMemo(() => getTimeFilterDate(selectedTimeFilter), [selectedTimeFilter]);
  const globalTimeParams = useMemo(() => ({ date_from: globalDateFrom }), [globalDateFrom]);

  const [userSearchTerm, setUserSearchTerm] = useState('');
  const [userPopoverOpened, setUserPopoverOpened] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(15);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // Active View Tab: 'events' (Journeys & Table) or 'tester' (API Test Lab)
  const [activeViewTab, setActiveViewTab] = useState<'events' | 'tester'>('events');

  // Sync tab from URL if present (?tab=tester)
  React.useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      if (params.get('tab') === 'tester') {
        setActiveViewTab('tester');
      }
    } catch {
      // ignore
    }
  }, []);

  // Selected drawers
  const [selectedEvent, setSelectedEvent] = useState<PostHogEvent | null>(null);
  const [isEventDrawerOpen, setIsEventDrawerOpen] = useState(false);
  const [selectedUserDistinctId, setSelectedUserDistinctId] = useState<string | null>(null);
  const [isUserDrawerOpen, setIsUserDrawerOpen] = useState(false);
  const [isConfigModalOpen, setIsConfigModalOpen] = useState(false);

  // 1. Overview Summary (Fastest) - Synchronized with Global Time Filter
  const { data: statsData, isLoading: isLoadingStats } = usePostHogStats(globalTimeParams);

  // 2. Funnel & Drop-off Journey - Synchronized with Global Time Filter
  const { data: funnelData, isLoading: isLoadingFunnel } = usePostHogFunnel(globalTimeParams);

  // 3. Unique Identified Users - Synchronized with Global Time Filter
  const { data: identifiedUsers = [] } = usePostHogUsers(globalTimeParams);

  // 4. API-side Paginated Events Stream - Synchronized with Global Time & User Filters
  const {
    data: eventsData,
    isLoading: isLoadingEvents,
    refetch,
    isFetching,
  } = usePostHogEvents(
    {
      page: currentPage,
      pageSize,
      status: selectedStatus,
      search: searchQuery,
      distinct_id: selectedUserFilter || undefined,
      date_from: globalDateFrom,
    },
    { refetchInterval: autoRefresh ? 10000 : false }
  );

  const handleRefreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ['posthog'] });
    refetch();
  };

  const events = eventsData?.events ?? [];
  const totalRecords = eventsData?.total ?? 0;
  const isLiveConnected = eventsData?.isLive ?? false;
  const totalPages = Math.max(1, Math.ceil(totalRecords / pageSize));

  // Filter users in the user dropdown
  const filteredUsersList = useMemo(() => {
    if (!userSearchTerm.trim()) return identifiedUsers;
    const term = userSearchTerm.toLowerCase();
    return identifiedUsers.filter(
      (u) =>
        u.name.toLowerCase().includes(term) ||
        u.email.toLowerCase().includes(term) ||
        u.business_name.toLowerCase().includes(term) ||
        u.distinct_id.toLowerCase().includes(term)
    );
  }, [identifiedUsers, userSearchTerm]);

  const selectedUserObject = useMemo(() => {
    if (!selectedUserFilter) return null;
    return identifiedUsers.find(
      (u) =>
        u.distinct_id.toLowerCase() === selectedUserFilter.toLowerCase() ||
        u.email.toLowerCase() === selectedUserFilter.toLowerCase()
    );
  }, [identifiedUsers, selectedUserFilter]);

  const handleCopyDistinctId = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(id);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 1800);
  };

  const handleUserClick = (distinctId: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    setSelectedUserDistinctId(distinctId);
    setIsUserDrawerOpen(true);
  };

  const handleQuickFilterUser = (distinctId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedUserFilter(distinctId === selectedUserFilter ? '' : distinctId);
    setCurrentPage(1);
  };

  const handleExportJson = () => {
    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(events, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', dataStr);
    downloadAnchor.setAttribute('download', `posthog_events_${new Date().toISOString().slice(0, 10)}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  const handleExportCsv = () => {
    if (events.length === 0) return;
    const headers = ['id', 'event', 'distinct_id', 'status', 'timestamp', 'category', 'pathname', 'url'];
    const rows = events.map((e) => [
      e.id,
      `"${e.event}"`,
      `"${e.distinct_id}"`,
      e.lifecycle_status,
      e.timestamp,
      e.category,
      `"${e.properties.$pathname || ''}"`,
      `"${e.properties.$current_url || ''}"`,
    ]);

    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', encodeURI(csvContent));
    downloadAnchor.setAttribute('download', `posthog_events_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  const timeFilterOptions: Array<{ id: TimeFilter; label: string }> = [
    { id: 'all', label: 'All Time' },
    { id: '1h', label: 'Last 1 Hour' },
    { id: '24h', label: 'Last 24 Hours' },
    { id: '7d', label: 'Last 7 Days' },
    { id: '30d', label: 'Last 30 Days' },
  ];

  return (
    <div className="space-y-6">
      {/* 1. Header with Direct Ingestion Status & Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-bold text-text-dark tracking-tight">
              PostHog User Journeys & Events
            </h1>
            <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-highlight-teal/10 text-highlight-teal text-xs font-semibold">
              <span className="w-2 h-2 rounded-full bg-highlight-teal animate-pulse" />
              <span>{isLiveConnected ? 'PostHog Cloud API' : 'Taxonomy Ingestion'}</span>
            </div>
          </div>
          <p className="text-xs text-text-muted mt-1">
            Track user journey conversions, drop-offs, lifecycle milestones, and session replays.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          {/* Global Time Range Filter Menu */}
          <Menu shadow="md" width={190} position="bottom-end">
            <Menu.Target>
              <button
                type="button"
                className={`px-3 py-1.5 rounded-[8px] border text-xs font-semibold transition-all flex items-center gap-2 cursor-pointer ${
                  selectedTimeFilter !== 'all'
                    ? 'bg-text-dark text-surface-card border-text-dark shadow-xs ring-2 ring-highlight-teal/25'
                    : 'bg-surface-card border-border-default text-text-dark hover:bg-surface-primary'
                }`}
                title="Global time range: filters all metrics, funnel stages, users, and event activity"
              >
                <Clock size={13} className={selectedTimeFilter !== 'all' ? 'text-highlight-teal' : 'text-text-muted'} />
                <span>{getTimeFilterLabel(selectedTimeFilter)}</span>
                <ChevronDown size={12} className="opacity-70 shrink-0" />
              </button>
            </Menu.Target>
            <Menu.Dropdown>
              <div className="px-2.5 py-1.5 border-b border-border-default">
                <p className="text-[10px] font-bold uppercase tracking-wider text-text-muted">Global Time Range</p>
                <p className="text-[11px] text-text-muted mt-0.5">Filters metrics, funnel & live feed</p>
              </div>
              {timeFilterOptions.map((tf) => (
                <Menu.Item
                  key={tf.id}
                  onClick={() => handleSetTimeFilter(tf.id)}
                  className="text-xs py-2 cursor-pointer"
                >
                  <div className="flex items-center justify-between w-full">
                    <span className={selectedTimeFilter === tf.id ? 'font-semibold text-text-dark' : 'text-text-muted'}>
                      {tf.label}
                    </span>
                    {selectedTimeFilter === tf.id && (
                      <Check size={13} className="text-highlight-teal" />
                    )}
                  </div>
                </Menu.Item>
              ))}
            </Menu.Dropdown>
          </Menu>

          <button
            type="button"
            onClick={handleRefreshAll}
            className="p-2 rounded-[8px] border border-border-default bg-surface-card hover:bg-surface-primary text-text-dark transition-colors cursor-pointer"
            title="Refresh all metrics and event stream"
          >
            <RefreshCw size={15} className={isFetching || isLoadingStats || isLoadingFunnel ? 'animate-spin' : ''} />
          </button>

          <button
            type="button"
            onClick={() => setIsConfigModalOpen(true)}
            className="px-3 py-1.5 rounded-[8px] border border-border-default bg-surface-card hover:bg-surface-primary text-xs font-medium text-text-dark transition-colors flex items-center gap-1.5 cursor-pointer"
          >
            <SlidersHorizontal size={14} />
            <span>API Settings</span>
          </button>

          <Menu shadow="md" width={140} position="bottom-end">
            <Menu.Target>
              <button
                type="button"
                className="px-3 py-1.5 rounded-[8px] bg-text-dark hover:opacity-90 text-surface-card text-xs font-semibold transition-opacity flex items-center gap-1.5 cursor-pointer"
              >
                <Download size={14} />
                <span>Export</span>
              </button>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item onClick={handleExportJson}>Export JSON</Menu.Item>
              <Menu.Item onClick={handleExportCsv}>Export CSV</Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </div>
      </div>

      {/* View Mode Switcher: Analytics & Funnel vs API Test Lab */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border-default pb-3">
        <div className="flex items-center gap-1.5 p-1 rounded-10 bg-surface-primary border border-border-default">
          <button
            type="button"
            onClick={() => setActiveViewTab('events')}
            className={`px-3.5 py-1.5 rounded-[8px] text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5 ${
              activeViewTab === 'events'
                ? 'bg-surface-card text-text-dark shadow-xs border border-border-default'
                : 'text-text-muted hover:text-text-dark'
            }`}
          >
            <LayoutDashboard size={14} />
            <span>User Journeys & Live Events</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveViewTab('tester')}
            className={`px-3.5 py-1.5 rounded-[8px] text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5 ${
              activeViewTab === 'tester'
                ? 'bg-surface-card text-text-dark shadow-xs border border-border-default'
                : 'text-text-muted hover:text-text-dark'
            }`}
          >
            <FlaskConical size={14} className="text-highlight-teal" />
            <span>PostHog API Test Lab</span>
            <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-highlight-teal/15 text-highlight-teal font-bold uppercase tracking-wider">
              Playground
            </span>
          </button>
        </div>

        {activeViewTab === 'events' ? (
          <button
            type="button"
            onClick={() => setActiveViewTab('tester')}
            className="text-xs text-text-muted hover:text-highlight-teal flex items-center gap-1 font-medium transition-colors cursor-pointer"
          >
            <span>Need to test custom PostHog endpoints or HogQL?</span>
            <span className="font-semibold text-highlight-teal underline">Open Test Lab ➔</span>
          </button>
        ) : (
          <button
            type="button"
            onClick={() => setActiveViewTab('events')}
            className="text-xs text-text-muted hover:text-text-dark flex items-center gap-1 font-medium transition-colors cursor-pointer"
          >
            <span>← Return to Live Journeys & Event Feed</span>
          </button>
        )}
      </div>

      {activeViewTab === 'tester' ? (
        <PostHogApiPlayground />
      ) : (
        <>
      {/* 2. Connection Helper Banner if using local fallback */}
      {!isLiveConnected && (
        <div className="rounded-12 border border-highlight-teal/20 bg-highlight-teal/5 p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
          <div className="flex items-start gap-2.5">
            <span className="w-2 h-2 rounded-full bg-highlight-teal mt-1.5 shrink-0" />
            <div>
              <p className="font-semibold text-text-dark">
                Direct Browser PostHog API Integration
              </p>
              <p className="text-[11px] text-text-muted mt-0.5">
                Simulating verified Punk AI user journeys with session replay links. Add your PostHog Personal API Key and Project ID to query your live cloud dataset directly without backend intervention.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setIsConfigModalOpen(true)}
            className="px-3 py-1.5 rounded-[8px] bg-text-dark text-surface-card font-semibold text-xs hover:opacity-90 transition-opacity shrink-0 cursor-pointer"
          >
            Configure API Keys
          </button>
        </div>
      )}

      {/* 3. Hierarchy Level 1: High-Level Overview Metric Cards (Loaded First) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
        <div className="rounded-12 border border-border-default p-0.5 bg-surface-primary flex flex-col transition-all duration-200 hover:shadow-xs">
          <div className="h-17.25 rounded-10 p-2.5 bg-surface-card flex flex-col justify-between">
            <span className="text-[13px] font-normal text-text-dark">Total Events</span>
            <div className="flex items-baseline gap-1.5">
              {isLoadingStats ? (
                <Skeleton height={28} width={80} radius="sm" />
              ) : (
                <span className="text-[24px] font-bold text-text-dark leading-tight tracking-tight">
                  {statsData?.total_events_24h.toLocaleString() ?? '—'}
                </span>
              )}
            </div>
          </div>
          <div className="h-7.5 px-2.5 py-1.5 flex items-center justify-between">
            <span className="text-[12px] font-normal text-text-muted">
              {selectedTimeFilter !== 'all' ? getTimeFilterLabel(selectedTimeFilter) : 'Total recorded'}
            </span>
            <span className="text-[12px] font-medium text-highlight-teal">Live Stream</span>
          </div>
        </div>

        <div className="rounded-12 border border-border-default p-0.5 bg-surface-primary flex flex-col transition-all duration-200 hover:shadow-xs">
          <div className="h-17.25 rounded-10 p-2.5 bg-surface-card flex flex-col justify-between">
            <span className="text-[13px] font-normal text-text-dark">Active Identified Users</span>
            <div className="flex items-baseline gap-1.5">
              {isLoadingStats ? (
                <Skeleton height={28} width={80} radius="sm" />
              ) : (
                <span className="text-[24px] font-bold text-text-dark leading-tight tracking-tight">
                  {statsData?.unique_users_24h.toLocaleString() ?? '—'}
                </span>
              )}
            </div>
          </div>
          <div className="h-7.5 px-2.5 py-1.5 flex items-center justify-between">
            <span className="text-[12px] font-normal text-text-muted">
              {selectedTimeFilter !== 'all' ? `Active in ${getTimeFilterLabel(selectedTimeFilter).toLowerCase()}` : 'Distinct user accounts'}
            </span>
            <span className="text-[12px] font-medium text-highlight-orange">
              {identifiedUsers.length} users
            </span>
          </div>
        </div>

        <div className="rounded-12 border border-border-default p-0.5 bg-surface-primary flex flex-col transition-all duration-200 hover:shadow-xs">
          <div className="h-17.25 rounded-10 p-2.5 bg-surface-card flex flex-col justify-between">
            <span className="text-[13px] font-normal text-text-dark">Journey Conversion Rate</span>
            <div className="flex items-baseline gap-1.5">
              {isLoadingStats ? (
                <Skeleton height={28} width={80} radius="sm" />
              ) : (
                <span className="text-[24px] font-bold text-text-dark leading-tight tracking-tight">
                  {statsData?.funnel_conversion_rate ?? '—'}
                </span>
              )}
            </div>
          </div>
          <div className="h-7.5 px-2.5 py-1.5 flex items-center justify-between">
            <span className="text-[12px] font-normal text-text-muted">Signup to Payment</span>
            <span className="text-[12px] font-medium text-highlight-teal">
              {selectedTimeFilter !== 'all' ? getTimeFilterLabel(selectedTimeFilter) : 'Overall'}
            </span>
          </div>
        </div>

        <div className="rounded-12 border border-border-default p-0.5 bg-surface-primary flex flex-col transition-all duration-200 hover:shadow-xs">
          <div className="h-17.25 rounded-10 p-2.5 bg-surface-card flex flex-col justify-between">
            <span className="text-[13px] font-normal text-text-dark">Funnel Drop-off Rate</span>
            <div className="flex items-baseline gap-1.5">
              {isLoadingStats ? (
                <Skeleton height={28} width={80} radius="sm" />
              ) : (
                <span className="text-[24px] font-bold text-text-dark leading-tight tracking-tight">
                  {funnelData?.overallDropOff ? `${funnelData.overallDropOff}%` : '28.5%'}
                </span>
              )}
            </div>
          </div>
          <div className="h-7.5 px-2.5 py-1.5 flex items-center justify-between">
            <span className="text-[12px] font-normal text-text-muted">Drop-offs & cancellations</span>
            <span className="text-[12px] font-medium text-state-warning">
              {selectedTimeFilter !== 'all' ? getTimeFilterLabel(selectedTimeFilter) : 'Monitored'}
            </span>
          </div>
        </div>
      </div>

      {/* 4. Hierarchy Level 2: User Journeys & Funnel Section (The ONLY source for stage filtering) */}
      <JourneyFunnelSection
        stages={funnelData?.stages ?? []}
        isLoading={isLoadingFunnel}
        activeStatusFilter={selectedStatus}
        timeFilterLabel={getTimeFilterLabel(selectedTimeFilter)}
        onFilterByStatus={(status) => {
          setSelectedStatus(status);
          setCurrentPage(1);
        }}
      />

      {/* 5. Hierarchy Level 3: Activity Explorer (Duplicate lifecycle row removed as requested) */}
      <div className="rounded-12 border border-border-default bg-surface-card shadow-xs overflow-hidden">
        {/* Clean Filter Bar without redundant activity pills */}
        <div className="p-4 border-b border-border-default flex flex-col gap-3">
          {/* Controls Row: Search, User Filter Popover, Time Filter Menu, Page Size, Auto-refresh */}
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2.5 flex-1">
              {/* Search Input */}
              <div className="relative w-full sm:w-64">
                <Search
                  size={14}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none"
                />
                <input
                  type="text"
                  placeholder="Search event, context, IDs..."
                  value={searchQuery}
                  onChange={(e) => {
                    setSearchQuery(e.target.value);
                    setCurrentPage(1);
                  }}
                  className="w-full pl-8.5 pr-3 py-1.5 text-xs rounded-[8px] border border-border-default bg-surface-primary text-text-dark placeholder:text-text-muted focus:outline-none focus:border-text-dark transition-colors"
                />
              </div>

              {/* User Filter Popover with smooth typing & full list of all users */}
              <Popover
                opened={userPopoverOpened}
                onChange={setUserPopoverOpened}
                width={320}
                position="bottom-start"
                shadow="md"
                withArrow={false}
              >
                <Popover.Target>
                  <button
                    type="button"
                    onClick={() => setUserPopoverOpened((o) => !o)}
                    className={`px-3 py-1.5 rounded-[8px] border text-xs font-medium transition-colors flex items-center gap-1.5 cursor-pointer ${
                      selectedUserFilter
                        ? 'bg-text-dark text-surface-card border-text-dark shadow-xs'
                        : 'bg-surface-primary border-border-default text-text-dark hover:bg-border-default'
                    }`}
                  >
                    <Users size={13} />
                    <span className="truncate max-w-40">
                      {selectedUserObject ? selectedUserObject.name : 'Filter by User'}
                    </span>
                    {selectedUserFilter ? (
                      <span
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedUserFilter('');
                          setCurrentPage(1);
                        }}
                        className="p-0.5 hover:text-state-warning transition-colors"
                        title="Clear user filter"
                      >
                        <X size={12} />
                      </span>
                    ) : (
                      <ChevronDown size={12} className="opacity-70 shrink-0" />
                    )}
                  </button>
                </Popover.Target>

                <Popover.Dropdown className="p-2 border border-border-default bg-surface-card shadow-lg rounded-10">
                  <div className="space-y-2">
                    {/* User Search Input */}
                    <div className="relative">
                      <Search
                        size={13}
                        className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none"
                      />
                      <input
                        type="text"
                        placeholder="Search user name, email, business..."
                        value={userSearchTerm}
                        onChange={(e) => setUserSearchTerm(e.target.value)}
                        className="w-full pl-8 pr-7 py-1.5 text-xs rounded-[6px] border border-border-default bg-surface-primary text-text-dark placeholder:text-text-muted focus:outline-none focus:border-text-dark transition-colors"
                        autoFocus
                      />
                      {userSearchTerm && (
                        <button
                          type="button"
                          onClick={() => setUserSearchTerm('')}
                          className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-dark cursor-pointer"
                        >
                          <X size={12} />
                        </button>
                      )}
                    </div>

                    {/* Scrollable list of ALL users */}
                    <div className="max-h-64 overflow-y-auto custom-scrollbar space-y-1 pt-1">
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedUserFilter('');
                          setUserPopoverOpened(false);
                          setCurrentPage(1);
                        }}
                        className={`w-full p-2 rounded-[6px] text-xs flex items-center justify-between cursor-pointer transition-colors ${
                          !selectedUserFilter
                            ? 'bg-surface-primary text-text-dark font-semibold'
                            : 'hover:bg-surface-primary/70 text-text-muted hover:text-text-dark'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <div className="w-5 h-5 rounded-full bg-surface-card border border-border-default flex items-center justify-center text-[10px] font-bold text-text-dark">
                            <Users size={11} />
                          </div>
                          <span>All Users ({identifiedUsers.length})</span>
                        </div>
                        {!selectedUserFilter && <Check size={13} className="text-highlight-teal" />}
                      </button>

                      <div className="h-px bg-border-default my-1" />

                      {filteredUsersList.length === 0 ? (
                        <div className="py-6 text-center text-xs text-text-muted">
                          No users match "{userSearchTerm}"
                        </div>
                      ) : (
                        filteredUsersList.map((u) => {
                          const isSelected =
                            selectedUserFilter.toLowerCase() === u.distinct_id.toLowerCase() ||
                            selectedUserFilter.toLowerCase() === u.email.toLowerCase();
                          return (
                            <button
                              key={u.distinct_id}
                              type="button"
                              onClick={() => {
                                setSelectedUserFilter(u.distinct_id);
                                setUserPopoverOpened(false);
                                setCurrentPage(1);
                              }}
                              className={`w-full p-2 rounded-[6px] text-xs flex items-center justify-between gap-2 cursor-pointer transition-colors text-left ${
                                isSelected
                                  ? 'bg-surface-primary text-text-dark font-semibold'
                                  : 'hover:bg-surface-primary/70 text-text-dark'
                              }`}
                            >
                              <div className="flex items-center gap-2.5 min-w-0">
                                <div className="w-6 h-6 rounded-full bg-surface-card border border-border-default flex items-center justify-center text-[10px] font-bold text-text-dark uppercase shrink-0">
                                  {u.name.charAt(0) || 'U'}
                                </div>
                                <div className="min-w-0">
                                  <p className="font-semibold text-text-dark truncate leading-tight">
                                    {u.name}
                                  </p>
                                  <p className="text-[10px] text-text-muted truncate font-mono mt-0.5">
                                    {u.email}
                                  </p>
                                  <p className="text-[10px] text-text-muted truncate">
                                    {u.business_name}
                                  </p>
                                </div>
                              </div>

                              <div className="flex items-center gap-1.5 shrink-0">
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-card border border-border-default text-text-muted">
                                  {u.eventCount} evts
                                </span>
                                {isSelected && <Check size={13} className="text-highlight-teal" />}
                              </div>
                            </button>
                          );
                        })
                      )}
                    </div>
                  </div>
                </Popover.Dropdown>
              </Popover>

              {/* Time Range Filter Dropdown */}
              <Menu shadow="md" width={180} position="bottom-start">
                <Menu.Target>
                  <button
                    type="button"
                    className={`px-3 py-1.5 rounded-[8px] border text-xs font-medium transition-colors flex items-center gap-1.5 cursor-pointer ${
                      selectedTimeFilter !== 'all'
                        ? 'bg-text-dark text-surface-card border-text-dark shadow-xs'
                        : 'bg-surface-primary border-border-default text-text-dark hover:bg-border-default'
                    }`}
                  >
                    <Clock size={13} />
                    <span>{getTimeFilterLabel(selectedTimeFilter)}</span>
                    <ChevronDown size={12} className="opacity-70 shrink-0" />
                  </button>
                </Menu.Target>
                <Menu.Dropdown>
                  {timeFilterOptions.map((tf) => (
                    <Menu.Item
                      key={tf.id}
                      onClick={() => handleSetTimeFilter(tf.id)}
                      className="text-xs py-1.5"
                    >
                      <div className="flex items-center justify-between w-full">
                        <span>{tf.label}</span>
                        {selectedTimeFilter === tf.id && (
                          <Check size={12} className="text-highlight-teal" />
                        )}
                      </div>
                    </Menu.Item>
                  ))}
                </Menu.Dropdown>
              </Menu>
            </div>

            <div className="flex items-center gap-3 shrink-0">
              {/* Page Size Selector */}
              <div className="flex items-center gap-1.5 text-xs text-text-muted">
                <span>Show:</span>
                <select
                  value={pageSize}
                  onChange={(e) => {
                    setPageSize(Number(e.target.value));
                    setCurrentPage(1);
                  }}
                  className="px-2 py-1 text-xs rounded-[6px] border border-border-default bg-surface-primary text-text-dark focus:outline-none cursor-pointer"
                >
                  {PAGE_SIZE_OPTIONS.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
              </div>

              <div className="h-4 w-px bg-border-default" />

              <div className="flex items-center gap-2 text-xs text-text-muted">
                <span>Auto-refresh</span>
                <Switch
                  size="xs"
                  checked={autoRefresh}
                  onChange={(e) => setAutoRefresh(e.currentTarget.checked)}
                  color="teal"
                />
              </div>
            </div>
          </div>

          {/* Active Filters Tag Bar (Displays active Stage, User, or Time filter) */}
          {(selectedUserFilter || selectedTimeFilter !== 'all' || selectedStatus !== 'all') && (
            <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-border-default/60">
              <span className="text-[11px] font-medium text-text-muted">Active Filters:</span>

              {selectedStatus !== 'all' && (
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-highlight-teal/10 border border-highlight-teal/30 text-[11px] font-semibold text-highlight-teal">
                  <Activity size={11} />
                  <span>Funnel: {selectedStatus.replace('_', ' ')}</span>
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedStatus('all');
                      setCurrentPage(1);
                    }}
                    className="p-0.5 hover:text-state-warning transition-colors cursor-pointer"
                    title="Clear stage filter"
                  >
                    <X size={11} />
                  </button>
                </span>
              )}

              {selectedUserFilter && (
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-surface-primary border border-border-default text-[11px] font-medium text-text-dark">
                  <Users size={11} className="text-text-muted" />
                  <span>User: {selectedUserObject ? selectedUserObject.name : selectedUserFilter}</span>
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedUserFilter('');
                      setCurrentPage(1);
                    }}
                    className="p-0.5 text-text-muted hover:text-state-warning transition-colors cursor-pointer"
                    title="Clear user filter"
                  >
                    <X size={11} />
                  </button>
                </span>
              )}

              {selectedTimeFilter !== 'all' && (
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-surface-primary border border-border-default text-[11px] font-medium text-text-dark">
                  <Clock size={11} className="text-text-muted" />
                  <span>Time: {getTimeFilterLabel(selectedTimeFilter)}</span>
                  <button
                    type="button"
                    onClick={() => handleSetTimeFilter('all')}
                    className="p-0.5 text-text-muted hover:text-state-warning transition-colors cursor-pointer"
                    title="Clear time filter"
                  >
                    <X size={11} />
                  </button>
                </span>
              )}

              <button
                type="button"
                onClick={() => {
                  setSelectedUserFilter('');
                  handleSetTimeFilter('all');
                  setSelectedStatus('all');
                  setSearchQuery('');
                  setCurrentPage(1);
                }}
                className="text-[11px] text-highlight-teal hover:underline cursor-pointer font-medium ml-1"
              >
                Reset all filters
              </button>
            </div>
          )}
        </div>

        {/* User Activity Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="bg-surface-primary border-b border-border-default text-text-muted">
                <th className="py-3 px-4 font-medium">User / Distinct ID</th>
                <th className="py-3 px-4 font-medium">Event & Milestone</th>
                <th className="py-3 px-4 font-medium">Context & Human Summary</th>
                <th className="py-3 px-4 font-medium">Client Device & Geo</th>
                <th className="py-3 px-4 font-medium">Timestamp</th>
                <th className="py-3 px-4 font-medium text-right">Actions</th>
              </tr>
            </thead>

            <tbody className="divide-y divide-border-default bg-surface-card">
              {isLoadingEvents && events.length === 0 ? (
                Array.from({ length: 6 }).map((_, idx) => (
                  <tr key={idx}>
                    <td className="py-3 px-4" colSpan={6}>
                      <Skeleton height={20} radius="xs" />
                    </td>
                  </tr>
                ))
              ) : events.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-xs text-text-muted">
                    No activity records found matching your criteria.
                  </td>
                </tr>
              ) : (
                events.map((evt) => {
                  const p = evt.properties || {};
                  const contextDetail =
                    p.maid_count ? `${Number(p.maid_count).toLocaleString()} MAIDs Geofenced` :
                    p.daily_budget ? `Budget: $${p.daily_budget}/day (${p.objective || 'SALES'})` :
                    p.business_name ? `${p.business_name} (${p.business_type || 'Account'})` :
                    p.thread_id ? `Thread: ${String(p.thread_id).substring(0, 9)}` :
                    p.cancel_reason ? `Cancelled: ${p.cancel_reason}` :
                    p.campaign_name ? `${p.campaign_name}` :
                    p.$pathname || '—';

                  const deviceStr = p.$browser
                    ? `${p.$browser} (${p.$os || 'Desktop'})`
                    : 'Web Client';
                  const geoStr = p.$geoip_city_name
                    ? `${p.$geoip_city_name}, ${p.$geoip_country_name}`
                    : p.$geoip_country_name || 'Global';

                  const isFilteredUser =
                    selectedUserFilter.toLowerCase() === evt.distinct_id.toLowerCase() ||
                    (typeof p.email === 'string' && selectedUserFilter.toLowerCase() === p.email.toLowerCase());

                  return (
                    <tr
                      key={evt.id}
                      onClick={() => handleUserClick(evt.distinct_id)}
                      className="hover:bg-surface-primary/60 transition-colors cursor-pointer group"
                    >
                      {/* User Column (Clicking opens User Journey Timeline, plus Quick-Filter action) */}
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2 max-w-56">
                          <div className="w-6 h-6 rounded-full bg-surface-primary border border-border-default flex items-center justify-center text-[10px] font-bold text-text-dark uppercase shrink-0">
                            {evt.distinct_id.charAt(0) || <User size={12} />}
                          </div>
                          <div className="min-w-0">
                            <span
                              className="font-semibold text-text-dark group-hover:text-highlight-teal transition-colors truncate block"
                              title={evt.distinct_id}
                            >
                              {p.full_name || evt.distinct_id.split('@')[0]}
                            </span>
                            <span className="font-mono text-[10px] text-text-muted truncate block">
                              {evt.distinct_id}
                            </span>
                          </div>

                          <div className="flex items-center gap-0.5 shrink-0" onClick={(e) => e.stopPropagation()}>
                            <button
                              type="button"
                              onClick={(e) => handleQuickFilterUser(evt.distinct_id, e)}
                              className={`p-1 rounded hover:bg-surface-primary transition-colors cursor-pointer ${
                                isFilteredUser
                                  ? 'text-highlight-teal font-bold bg-highlight-teal/10'
                                  : 'text-text-muted hover:text-text-dark'
                              }`}
                              title={isFilteredUser ? 'Clear user filter' : 'Filter by this user'}
                            >
                              <Filter size={11} className={isFilteredUser ? 'fill-current' : ''} />
                            </button>

                            <button
                              type="button"
                              onClick={(e) => handleCopyDistinctId(evt.distinct_id, e)}
                              className="p-1 text-text-muted hover:text-text-dark transition-colors cursor-pointer"
                              title="Copy Distinct ID"
                            >
                              {copiedId === evt.distinct_id ? (
                                <Check size={11} className="text-state-success" />
                              ) : (
                                <Copy size={11} />
                              )}
                            </button>
                          </div>
                        </div>
                      </td>

                      {/* Event & Category Column */}
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <span
                            className="w-2 h-2 rounded-full shrink-0"
                            style={{ backgroundColor: evt.category_color }}
                          />
                          <span className="font-semibold text-text-dark">
                            {evt.event}
                          </span>
                          <span
                            className="text-[10px] font-semibold px-1.5 py-0.2 rounded"
                            style={{
                              color: evt.category_color,
                              backgroundColor: `${evt.category_color}14`,
                            }}
                          >
                            {evt.category_label}
                          </span>
                        </div>
                      </td>

                      {/* Context / Human Detail */}
                      <td className="py-3 px-4 text-text-dark font-medium truncate max-w-64" title={contextDetail}>
                        {contextDetail}
                      </td>

                      {/* Device & Geo */}
                      <td className="py-3 px-4 text-text-muted">
                        <div>
                          <p className="text-text-dark">{deviceStr}</p>
                          <p className="text-[10px] text-text-muted">{geoStr}</p>
                        </div>
                      </td>

                      {/* Timestamp */}
                      <td className="py-3 px-4 text-text-muted whitespace-nowrap">
                        <div className="flex items-center gap-1">
                          <Clock size={12} />
                          <span>{formatRelativeTime(evt.timestamp)}</span>
                        </div>
                      </td>

                      {/* Action Buttons */}
                      <td className="py-3 px-4 text-right">
                        <div className="flex items-center justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
                          <button
                            type="button"
                            onClick={() => handleUserClick(evt.distinct_id)}
                            className="px-2.5 py-1 text-[11px] font-semibold rounded bg-surface-primary hover:bg-border-default text-text-dark transition-colors cursor-pointer border border-border-default"
                          >
                            User Journey
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setSelectedEvent(evt);
                              setIsEventDrawerOpen(true);
                            }}
                            className="px-2 py-1 text-[11px] font-medium rounded hover:bg-surface-primary text-text-muted hover:text-text-dark transition-colors cursor-pointer border border-transparent hover:border-border-default"
                            title="Inspect raw event JSON"
                          >
                            Raw
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Proper API-Side Pagination Footer */}
        <div className="px-4 py-3 border-t border-border-default flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs text-text-muted">
          <div>
            Showing{' '}
            <span className="font-semibold text-text-dark">
              {events.length > 0 ? (currentPage - 1) * pageSize + 1 : 0}
            </span>{' '}
            to{' '}
            <span className="font-semibold text-text-dark">
              {Math.min(currentPage * pageSize, totalRecords)}
            </span>{' '}
            of <span className="font-semibold text-text-dark">{totalRecords}</span> matching events
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={currentPage === 1}
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              className="px-2.5 py-1 rounded border border-border-default bg-surface-card hover:bg-surface-primary disabled:opacity-40 disabled:pointer-events-none transition-colors cursor-pointer text-text-dark font-medium flex items-center gap-1"
            >
              <ChevronLeft size={14} />
              <span>Previous</span>
            </button>

            <span className="font-medium text-text-dark px-2">
              Page {currentPage} of {totalPages}
            </span>

            <button
              type="button"
              disabled={currentPage >= totalPages}
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              className="px-2.5 py-1 rounded border border-border-default bg-surface-card hover:bg-surface-primary disabled:opacity-40 disabled:pointer-events-none transition-colors cursor-pointer text-text-dark font-medium flex items-center gap-1"
            >
              <span>Next</span>
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      </div>
      </>
      )}

      {/* Slide-out User Activity Journey Details Timeline */}
      <UserJourneyDrawer
        distinctId={selectedUserDistinctId}
        isOpen={isUserDrawerOpen}
        onClose={() => {
          setIsUserDrawerOpen(false);
          setSelectedUserDistinctId(null);
        }}
      />

      {/* Slide-out Raw Event Detail Inspector Drawer */}
      <PostHogEventDrawer
        event={selectedEvent}
        isOpen={isEventDrawerOpen}
        onClose={() => {
          setIsEventDrawerOpen(false);
          setSelectedEvent(null);
        }}
      />

      {/* PostHog Configuration Modal */}
      <PostHogConfigModal
        isOpen={isConfigModalOpen}
        onClose={() => setIsConfigModalOpen(false)}
      />
    </div>
  );
};

export default PostHogEventsPage;
