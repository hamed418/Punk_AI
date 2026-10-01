import React, { useState, useRef } from "react";
import {
  Drawer,
  Menu,
  SegmentedControl,
  Skeleton,
} from "@mantine/core";
import {
  Activity,
  ArrowRight,
  Check,
  CheckCircle2,
  Download,
  Filter,
  Megaphone,
  MoreVertical,
  Search,
  SlidersHorizontal,
  Clock,
  Users,
  ChevronDown,
  X,
} from "lucide-react";
import { Link } from "@tanstack/react-router";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { DESIGN_TOKENS } from "@/constant/design-system";
import {
  useAnalyticsVelocity,
  useAnalyticsRecentCampaigns,
} from "@/hooks/api/useAnalyticsApi";
import { usePostHogEvents, usePostHogUsers } from "@/hooks/api/usePostHogApi";
import {
  getTimeFilterDate,
  getTimeFilterLabel,
} from "@/api/posthog";
import type { PostHogEvent, LifecycleStatus, TimeFilter } from "@/api/posthog";
import { PostHogEventDrawer } from "@/components/posthog/PostHogEventDrawer";
import { PostHogConfigModal } from "@/components/posthog/PostHogConfigModal";
import { UserJourneyDrawer } from "@/components/posthog/UserJourneyDrawer";
import type { RecentCampaignItem } from "@/api/analytics";

interface TableCheckboxProps {
  checked: boolean;
  onChange: () => void;
  ariaLabel?: string;
}

const TableCheckbox = ({
  checked,
  onChange,
  ariaLabel = "Select row",
}: TableCheckboxProps) => {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={ariaLabel}
      onClick={(e) => {
        e.stopPropagation();
        onChange();
      }}
      className={`w-3.5 h-3.5 rounded-[4px] border flex items-center justify-center transition-all cursor-pointer ${
        checked
          ? "bg-text-dark border-text-dark text-surface-card"
          : "bg-surface-card border-border-default hover:border-text-muted text-transparent"
      }`}
    >
      <Check size={11} strokeWidth={3} className={checked ? "block" : "hidden"} />
    </button>
  );
};

interface CustomChartTooltipProps {
  active?: boolean;
  payload?: Array<{ value: number; payload: { reach?: number; conv?: number } }>;
  label?: string;
}

// Custom Recharts Tooltip
const CustomChartTooltip = ({ active, payload, label }: CustomChartTooltipProps) => {
  if (active && payload && payload.length) {
    return (
      <div className="rounded-10 border border-border-default bg-text-dark text-surface-card p-3 shadow-xl text-xs space-y-1.5 min-w-42.5">
        <div className="font-bold flex items-center justify-between border-b border-[#262626] pb-1.5">
          <span>{label} Activity</span>
          <span className="text-highlight-cyan">Active</span>
        </div>
        <div className="flex items-center justify-between text-text-subtle">
          <span>Campaigns:</span>
          <span className="font-bold text-surface-card">{payload[0].value}</span>
        </div>
        {payload[0].payload.reach != null && (
          <div className="flex items-center justify-between text-text-subtle">
            <span>Audience Reach:</span>
            <span className="font-semibold text-highlight-cyan">
              {Number(payload[0].payload.reach).toLocaleString()}
            </span>
          </div>
        )}
        {payload[0].payload.conv != null && (
          <div className="flex items-center justify-between text-text-subtle">
            <span>Conversions:</span>
            <span className="font-semibold text-highlight-pink">
              {Number(payload[0].payload.conv).toLocaleString()}
            </span>
          </div>
        )}
      </div>
    );
  }
  return null;
};

function formatEventTime(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const sec = Math.floor(diff / 1000);
    if (sec < 60) return "Just now";
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h ago`;
    return `${Math.floor(hr / 24)}d ago`;
  } catch {
    return "Recently";
  }
}

const CampaignActivity = () => {
  const [timeframe, setTimeframe] = useState<"daily" | "weekly" | "monthly">("daily");
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [selectedCampaign, setSelectedCampaign] = useState<RecentCampaignItem | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [lifecycleStatus, setLifecycleStatus] = useState<LifecycleStatus>("all");
  const [timeFilter, setTimeFilter] = useState<TimeFilter>("all");
  const [userFilter, setUserFilter] = useState<string>("");
  const [selectedPostHogEvent, setSelectedPostHogEvent] = useState<PostHogEvent | null>(null);
  const [isPostHogDrawerOpen, setIsPostHogDrawerOpen] = useState(false);
  const [selectedUserDistinctId, setSelectedUserDistinctId] = useState<string | null>(null);
  const [isUserJourneyDrawerOpen, setIsUserJourneyDrawerOpen] = useState(false);
  const [isConfigModalOpen, setIsConfigModalOpen] = useState(false);

  // Queries
  const { data: velocityData, isLoading: isLoadingVelocity } =
    useAnalyticsVelocity(timeframe);
  const { data: campaignsData, isLoading: isLoadingCampaigns } =
    useAnalyticsRecentCampaigns(debouncedSearch);
  const { data: identifiedUsers = [] } = usePostHogUsers();
  const { data: postHogData, isLoading: isLoadingPostHog } = usePostHogEvents({
    status: lifecycleStatus,
    distinct_id: userFilter || undefined,
    date_from: getTimeFilterDate(timeFilter),
    pageSize: 15,
  });

  const chartPoints = velocityData?.data ?? [];
  const postHogEvents = postHogData?.events ?? [];
  const campaignsList = campaignsData?.campaigns ?? [];

  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setSearchQuery(val);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    searchTimerRef.current = setTimeout(() => {
      setDebouncedSearch(val);
    }, 350);
  };

  const handleSelectAll = () => {
    if (selectedIds.length === campaignsList.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(campaignsList.map((c) => c.id));
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    );
  };

  const handleRowClick = (camp: RecentCampaignItem) => {
    setSelectedCampaign(camp);
    setIsDrawerOpen(true);
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Middle Row: Graph Card (706px / 2 cols) + Activity Feed (388px / 1 col) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* 4.1.B Analytics Graph Card */}
        <div className="lg:col-span-8 rounded-12 border border-border-default p-4 bg-surface-card flex flex-col justify-between shadow-xs">
          {/* Graph Top Bar */}
          <div className="h-9 flex items-center justify-between gap-3 mb-4">
            <div className="flex items-center gap-2">
              <div
                className="w-3 h-3 rounded-full shrink-0"
                style={{ backgroundColor: DESIGN_TOKENS.colors.graphMarker }}
              />
              <h3 className="text-sm font-bold text-text-dark">
                Campaigns Launched & Performance Velocity
              </h3>
            </div>

            {/* Timeframe Segmented Control & Actions */}
            <div className="flex items-center gap-2">
              <SegmentedControl
                value={timeframe}
                onChange={(val) => setTimeframe(val as "daily" | "weekly" | "monthly")}
                data={[
                  { label: "Daily", value: "daily" },
                  { label: "Weekly", value: "weekly" },
                  { label: "Monthly", value: "monthly" },
                ]}
                size="xs"
                radius="sm"
                withItemsBorders={false}
                className="graph-segmented-control"
                styles={{
                  root: {
                    backgroundColor: "var(--primary-background)",
                    border: "1px solid var(--border-primary)",
                    padding: "3px",
                    borderRadius: DESIGN_TOKENS.radius.r10,
                    outline: "none !important",
                  },
                  indicator: {
                    backgroundColor: "var(--secondary-active-light)",
                    boxShadow:
                      "0 2px 4px 0 rgba(0, 0, 0, 0.05), 0 1px 2px 0 rgba(0, 0, 0, 0.04)",
                    borderRadius: DESIGN_TOKENS.radius.r8,
                    border: "none !important",
                    outline: "none !important",
                  },
                  label: {
                    fontSize: "11px",
                    fontWeight: 600,
                    color: "var(--text-primary)",
                    transition: "color 150ms ease",
                    padding: "4px 12px",
                    border: "none !important",
                    outline: "none !important",
                    "&[data-active]": {
                      color: "var(--secondary-active-dark) !important",
                      border: "none !important",
                      outline: "none !important",
                    },
                    "&:hover": {
                      color: "var(--secondary-active-dark)",
                    },
                  },
                }}
              />

              <Menu shadow="md" width={140} position="bottom-end">
                <Menu.Target>
                  <button
                    type="button"
                    className="p-1.5 rounded-[8px] text-text-muted hover:text-text-dark hover:bg-surface-primary border border-transparent hover:border-border-default transition-colors cursor-pointer"
                    aria-label="More graph options"
                  >
                    <MoreVertical size={16} />
                  </button>
                </Menu.Target>
                <Menu.Dropdown>
                  <Menu.Item leftSection={<Download size={14} />}>
                    Export Data
                  </Menu.Item>
                  <Menu.Item leftSection={<Filter size={14} />}>
                    Filter Metrics
                  </Menu.Item>
                </Menu.Dropdown>
              </Menu>
            </div>
          </div>

          {/* Recharts Area Chart */}
          <div className="w-full h-62.5">
            {isLoadingVelocity && chartPoints.length === 0 ? (
              <div className="w-full h-full flex items-center justify-center">
                <Skeleton height={200} width="100%" radius="md" />
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={chartPoints}
                  margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
                >
                  <defs>
                    <linearGradient id="colorCampaigns" x1="0" y1="0" x2="0" y2="1">
                      <stop
                        offset="5%"
                        stopColor={DESIGN_TOKENS.colors.graphMarker}
                        stopOpacity={0.25}
                      />
                      <stop
                        offset="95%"
                        stopColor={DESIGN_TOKENS.colors.graphMarker}
                        stopOpacity={0.0}
                      />
                    </linearGradient>
                  </defs>
                  <CartesianGrid
                    strokeDasharray="4 4"
                    vertical={false}
                    stroke={DESIGN_TOKENS.colors.borderPrimary}
                  />
                  <XAxis
                    dataKey="name"
                    tickLine={false}
                    axisLine={{ stroke: DESIGN_TOKENS.colors.borderPrimary }}
                    tick={{ fill: DESIGN_TOKENS.colors.textPrimary, fontSize: 11, fontWeight: 500 }}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    tick={{ fill: DESIGN_TOKENS.colors.textPrimary, fontSize: 11 }}
                  />
                  <RechartsTooltip content={<CustomChartTooltip />} />
                  {/* Secondary Benchmark / Comparison Line */}
                  <Area
                    type="monotone"
                    dataKey="benchmark"
                    stroke="#6B4DFF"
                    strokeWidth={2}
                    strokeDasharray="4 4"
                    fill="transparent"
                    dot={false}
                    activeDot={false}
                  />
                  {/* Primary Data Line */}
                  <Area
                    type="monotone"
                    dataKey="campaigns"
                    stroke={DESIGN_TOKENS.colors.graphMarker}
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#colorCampaigns)"
                    activeDot={{
                      r: 5,
                      fill: DESIGN_TOKENS.colors.graphMarker,
                      stroke: DESIGN_TOKENS.colors.secondaryActiveLight,
                      strokeWidth: 2,
                    }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Graph Date Axis Container */}
          <div className="h-4.5 px-6 flex items-center justify-between text-[11px] font-medium text-text-muted border-t border-border-default pt-2 mt-2">
            <span>Period Start</span>
            <span className="flex items-center gap-1.5 text-text-dark font-semibold">
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: DESIGN_TOKENS.colors.stateSuccess }} />
              Real-time Streaming Connected
            </span>
            <span>Period End</span>
          </div>
        </div>

        {/* 4.1.C PostHog Activity & Event Stream Card */}
        <div className="lg:col-span-4 rounded-16 border border-border-default p-4 bg-surface-card flex flex-col justify-between shadow-xs">
          <div className="pb-3 border-b border-border-default space-y-2.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Activity size={16} className="text-text-dark" />
                <h3 className="text-sm font-bold text-text-dark">
                  PostHog Live Events
                </h3>
              </div>

              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-[4px] bg-highlight-teal/10 text-highlight-teal text-[10px] font-bold">
                  <span className="w-1.5 h-1.5 rounded-full bg-highlight-teal animate-pulse" />
                  <span>LIVE</span>
                </div>

                <button
                  type="button"
                  onClick={() => setIsConfigModalOpen(true)}
                  className="p-1 text-text-muted hover:text-text-dark rounded hover:bg-surface-primary transition-colors cursor-pointer"
                  title="Configure PostHog API"
                >
                  <SlidersHorizontal size={14} />
                </button>
              </div>
            </div>

            {/* User & Time Filter Bar */}
            <div className="flex items-center justify-between gap-2 pt-0.5">
              {/* User Selector Menu */}
              <Menu shadow="md" width={220} position="bottom-start">
                <Menu.Target>
                  <button
                    type="button"
                    className={`px-2 py-1 rounded-[6px] border text-[11px] font-medium flex items-center gap-1.5 cursor-pointer transition-colors ${
                      userFilter
                        ? "bg-text-dark text-surface-card border-text-dark"
                        : "bg-surface-primary border-border-default text-text-muted hover:text-text-dark"
                    }`}
                  >
                    <Users size={11} />
                    <span className="truncate max-w-28">
                      {userFilter
                        ? identifiedUsers.find((u) => u.distinct_id === userFilter)?.name || userFilter
                        : "All Users"}
                    </span>
                    <ChevronDown size={10} className="opacity-70" />
                  </button>
                </Menu.Target>
                <Menu.Dropdown className="p-1 max-h-56 overflow-y-auto custom-scrollbar">
                  <Menu.Item
                    onClick={() => setUserFilter("")}
                    className="text-xs py-1"
                  >
                    <div className="flex items-center justify-between w-full">
                      <span>All Users</span>
                      {!userFilter && <Check size={11} className="text-highlight-teal" />}
                    </div>
                  </Menu.Item>
                  <Menu.Divider />
                  {identifiedUsers.map((u) => (
                    <Menu.Item
                      key={u.distinct_id}
                      onClick={() => setUserFilter(u.distinct_id)}
                      className="text-xs py-1"
                    >
                      <div className="flex items-center justify-between w-full">
                        <span className="truncate max-w-36">{u.name}</span>
                        {userFilter === u.distinct_id && <Check size={11} className="text-highlight-teal" />}
                      </div>
                    </Menu.Item>
                  ))}
                </Menu.Dropdown>
              </Menu>

              {/* Time Range Selector Menu */}
              <Menu shadow="md" width={140} position="bottom-end">
                <Menu.Target>
                  <button
                    type="button"
                    className={`px-2 py-1 rounded-[6px] border text-[11px] font-medium flex items-center gap-1.5 cursor-pointer transition-colors ${
                      timeFilter !== "all"
                        ? "bg-text-dark text-surface-card border-text-dark"
                        : "bg-surface-primary border-border-default text-text-muted hover:text-text-dark"
                    }`}
                  >
                    <Clock size={11} />
                    <span>{getTimeFilterLabel(timeFilter)}</span>
                    <ChevronDown size={10} className="opacity-70" />
                  </button>
                </Menu.Target>
                <Menu.Dropdown>
                  {[
                    { id: "all" as TimeFilter, label: "All Time" },
                    { id: "1h" as TimeFilter, label: "Last 1h" },
                    { id: "24h" as TimeFilter, label: "Last 24h" },
                    { id: "7d" as TimeFilter, label: "Last 7d" },
                  ].map((tf) => (
                    <Menu.Item
                      key={tf.id}
                      onClick={() => setTimeFilter(tf.id)}
                      className="text-xs py-1"
                    >
                      <div className="flex items-center justify-between w-full">
                        <span>{tf.label}</span>
                        {timeFilter === tf.id && <Check size={11} className="text-highlight-teal" />}
                      </div>
                    </Menu.Item>
                  ))}
                </Menu.Dropdown>
              </Menu>
            </div>

            {/* Active filters clear tags if filtered */}
            {(userFilter || timeFilter !== "all") && (
              <div className="flex items-center gap-1.5 text-[10px] text-text-muted">
                <span>Active:</span>
                {userFilter && (
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.2 rounded bg-surface-primary border border-border-default font-medium text-text-dark">
                    <span>{identifiedUsers.find((u) => u.distinct_id === userFilter)?.name || userFilter}</span>
                    <button type="button" onClick={() => setUserFilter("")} className="hover:text-state-warning cursor-pointer">
                      <X size={10} />
                    </button>
                  </span>
                )}
                {timeFilter !== "all" && (
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.2 rounded bg-surface-primary border border-border-default font-medium text-text-dark">
                    <span>{getTimeFilterLabel(timeFilter)}</span>
                    <button type="button" onClick={() => setTimeFilter("all")} className="hover:text-state-warning cursor-pointer">
                      <X size={10} />
                    </button>
                  </span>
                )}
              </div>
            )}

            {/* Lifecycle Status Filter Pills */}
            <div className="flex items-center gap-1 overflow-x-auto no-scrollbar py-0.5">
              {[
                { id: "all" as LifecycleStatus, label: "All" },
                { id: "signed_up" as LifecycleStatus, label: "Signed Up" },
                { id: "chat_completed" as LifecycleStatus, label: "Chat" },
                { id: "audience_generated" as LifecycleStatus, label: "Audience" },
                { id: "campaign_published" as LifecycleStatus, label: "Published" },
                { id: "payment_done" as LifecycleStatus, label: "Payment" },
                { id: "canceled" as LifecycleStatus, label: "Canceled" },
              ].map((st) => (
                <button
                  key={st.id}
                  type="button"
                  onClick={() => setLifecycleStatus(st.id)}
                  className={`px-2 py-0.5 text-[11px] rounded-full font-medium transition-all shrink-0 cursor-pointer ${
                    lifecycleStatus === st.id
                      ? "bg-text-dark text-surface-card"
                      : "bg-surface-primary text-text-muted hover:text-text-dark hover:bg-border-default"
                  }`}
                >
                  {st.label}
                </button>
              ))}
            </div>
          </div>

          {/* Event Stream List */}
          <div className="flex-1 py-3 space-y-2.5 overflow-y-auto max-h-65 custom-scrollbar">
            {isLoadingPostHog && postHogEvents.length === 0 ? (
              Array.from({ length: 4 }).map((_, idx) => (
                <div key={idx} className="flex items-start gap-3 p-2">
                  <Skeleton height={10} width={10} radius="xl" className="mt-1 shrink-0" />
                  <div className="flex-1 space-y-1.5">
                    <Skeleton height={12} width="80%" radius="xs" />
                    <Skeleton height={10} width="60%" radius="xs" />
                  </div>
                </div>
              ))
            ) : postHogEvents.length === 0 ? (
              <p className="text-xs text-text-muted text-center py-8">
                No events found for status "{lifecycleStatus}"
              </p>
            ) : (
              postHogEvents.map((item) => {
                const p = item.properties || {};
                const snippet =
                  p.maid_count ? `${Number(p.maid_count).toLocaleString()} MAIDs` :
                  p.daily_budget ? `Budget: $${p.daily_budget}` :
                  p.business_name ? `${p.business_name}` :
                  p.thread_id ? `Thread ${p.thread_id.substring(0, 8)}` :
                  p.campaign_name ? `${p.campaign_name}` :
                  p.$pathname || item.distinct_id;

                return (
                  <div
                    key={item.id}
                    onClick={() => {
                      setSelectedPostHogEvent(item);
                      setIsPostHogDrawerOpen(true);
                    }}
                    className="flex items-start gap-2.5 p-2 rounded-[8px] hover:bg-surface-primary transition-all cursor-pointer group border border-transparent hover:border-border-default"
                  >
                    <div
                      className="w-2 h-2 rounded-full mt-1.5 shrink-0"
                      style={{ backgroundColor: item.category_color }}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-1">
                        <p className="text-xs font-semibold text-text-dark truncate group-hover:text-highlight-teal transition-colors">
                          {item.event}
                        </p>
                        <span className="text-[10px] text-text-muted shrink-0">
                          {formatEventTime(item.timestamp)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-1 mt-0.5 text-[11px] text-text-muted">
                        <span
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedUserDistinctId(item.distinct_id);
                            setIsUserJourneyDrawerOpen(true);
                          }}
                          className="truncate max-w-36 font-mono text-[10px] hover:text-highlight-teal hover:underline cursor-pointer"
                          title="View complete user journey"
                        >
                          {item.distinct_id}
                        </span>
                        <span className="truncate text-text-dark font-medium max-w-28 text-right text-[10px]">
                          {snippet}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          <div className="pt-2 border-t border-border-default">
            <Link
              to="/events"
              className="w-full py-2 rounded-[8px] bg-surface-primary hover:bg-border-default text-xs font-semibold text-text-dark transition-colors flex items-center justify-center gap-1.5 cursor-pointer no-underline"
            >
              <span>View All PostHog Events</span>
              <ArrowRight size={13} />
            </Link>
          </div>
        </div>
      </div>

      {/* 4.1.D Recent Campaigns Table */}
      <div className="rounded-12 border border-border-default bg-surface-card shadow-xs overflow-hidden">
        {/* Recent Top Bar */}
        <div className="h-15 px-5 py-3 flex items-center justify-between gap-4 border-b border-border-default">
          <h3 className="text-base font-bold text-text-dark">
            Recent campaigns across users
          </h3>

          <div className="flex items-center gap-3">
            {/* Search Input */}
            <div className="relative w-48 sm:w-60">
              <Search
                size={15}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none"
              />
              <input
                type="text"
                placeholder="Search campaigns or users"
                value={searchQuery}
                onChange={handleSearch}
                className="w-full pl-9 pr-3 py-1.5 text-xs rounded-[8px] border border-border-default bg-surface-card text-text-dark placeholder:text-text-muted focus:outline-none focus:border-text-dark transition-colors"
              />
            </div>

            {/* View All Button linking to campaigns page */}
            <Link
              to="/campaigns"
              className="px-3.5 py-1.5 rounded-[8px] border border-border-default bg-surface-card hover:bg-surface-primary text-xs font-medium text-text-dark transition-colors cursor-pointer shadow-2xs no-underline inline-flex items-center gap-1"
            >
              View All
            </Link>
          </div>
        </div>

        {/* Table Header Row */}
        <div className="bg-surface-primary border-b border-border-default px-5 py-2.5 grid grid-cols-12 items-center text-[12px] font-normal text-text-muted">
          <div className="col-span-4 flex items-center gap-3">
            <TableCheckbox
              checked={
                campaignsList.length > 0 &&
                selectedIds.length === campaignsList.length
              }
              onChange={handleSelectAll}
              ariaLabel="Select all campaigns"
            />
            <span>Campaign</span>
          </div>
          <div className="col-span-3">User</div>
          <div className="col-span-2">Type</div>
          <div className="col-span-1 sm:col-span-2">CTR</div>
          <div className="col-span-2 sm:col-span-1">Spend</div>
        </div>

        {/* Table Rows */}
        <div className="divide-y divide-border-default">
          {isLoadingCampaigns && campaignsList.length === 0 ? (
            Array.from({ length: 5 }).map((_, idx) => (
              <div key={idx} className="px-5 py-3.5 grid grid-cols-12 items-center gap-2 animate-pulse">
                <div className="col-span-4 flex items-center gap-3">
                  <Skeleton height={14} width={14} radius="xs" />
                  <div className="space-y-1">
                    <Skeleton height={13} width={140} radius="xs" />
                    <Skeleton height={10} width={90} radius="xs" />
                  </div>
                </div>
                <div className="col-span-3">
                  <Skeleton height={13} width={120} radius="xs" />
                </div>
                <div className="col-span-2">
                  <Skeleton height={13} width={70} radius="xs" />
                </div>
                <div className="col-span-1 sm:col-span-2">
                  <Skeleton height={13} width={45} radius="xs" />
                </div>
                <div className="col-span-2 sm:col-span-1">
                  <Skeleton height={13} width={50} radius="xs" />
                </div>
              </div>
            ))
          ) : campaignsList.length === 0 ? (
            <div className="px-5 py-10 text-center text-xs text-text-muted">
              No campaigns found matching your search.
            </div>
          ) : (
            campaignsList.map((camp) => {
              const isSelected = selectedIds.includes(camp.id);
              return (
                <div
                  key={camp.id}
                  onClick={() => handleRowClick(camp)}
                  className={`px-5 py-3 grid grid-cols-12 items-center hover:bg-surface-primary transition-colors cursor-pointer group ${
                    isSelected ? "bg-surface-primary/70" : ""
                  }`}
                >
                  {/* Checkbox + Campaign Name & Date */}
                  <div className="col-span-4 flex items-center gap-3 min-w-0 pr-3">
                    <div
                      onClick={(e) => e.stopPropagation()}
                      className="flex items-center shrink-0"
                    >
                      <TableCheckbox
                        checked={isSelected}
                        onChange={() => toggleSelect(camp.id)}
                        ariaLabel={`Select ${camp.name}`}
                      />
                    </div>
                    <div className="min-w-0">
                      <p className="text-[13px] font-medium text-text-dark truncate" title={camp.name}>
                        {camp.name}
                      </p>
                      <p className="text-[11px] text-text-muted mt-0.5">
                        {camp.dateRange}
                      </p>
                    </div>
                  </div>

                  {/* User: Email + Name */}
                  <div className="col-span-3 flex items-center gap-2.5 min-w-0 pr-3">
                    <div className="w-5.5 h-5.5 rounded-full bg-surface-primary border border-border-default flex items-center justify-center shrink-0 text-[10px] font-semibold text-text-dark uppercase">
                      {camp.userEmail ? camp.userEmail.charAt(0) : "U"}
                    </div>
                    <span className="text-[13px] text-text-dark font-normal truncate" title={camp.userEmail}>
                      {camp.userEmail}
                    </span>
                  </div>

                  {/* Type */}
                  <div className="col-span-2 text-[13px] text-text-dark font-normal">
                    {camp.platform}
                  </div>

                  {/* CTR */}
                  <div className="col-span-1 sm:col-span-2 text-[13px] text-text-dark font-normal">
                    {camp.ctr}
                  </div>

                  {/* Spend */}
                  <div className="col-span-2 sm:col-span-1 text-[13px] text-text-dark font-semibold">
                    {camp.spend}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Campaign Detail Drawer */}
      <Drawer
        opened={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        position="right"
        size="md"
        padding="lg"
        title={
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-[6px] btn-gradient-black flex items-center justify-center text-surface-card">
              <Megaphone size={12} />
            </div>
            <div>
              <h4 className="text-sm font-bold text-text-dark truncate max-w-65">
                {selectedCampaign?.name || "Campaign Details"}
              </h4>
              <p className="text-[11px] text-text-muted">
                {selectedCampaign?.id} • {selectedCampaign?.platform}
              </p>
            </div>
          </div>
        }
        styles={{
          header: {
            borderBottom: "1px solid var(--border-primary)",
            paddingBottom: "12px",
          },
          body: {
            paddingTop: "16px",
          },
        }}
      >
        <div className="space-y-6">
          {/* Header Metric Summary Bar */}
          <div className="grid grid-cols-3 gap-2.5 p-3 rounded-12 border border-border-default bg-surface-primary">
            <div className="flex flex-col">
              <span className="text-[10px] text-text-muted uppercase font-bold">
                Spent
              </span>
              <span className="text-base font-bold text-text-dark">
                {selectedCampaign?.spend || "$2,100"}
              </span>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] text-text-muted uppercase font-bold">
                CTR
              </span>
              <span
                className="text-base font-bold"
                style={{ color: DESIGN_TOKENS.colors.highlightTeal }}
              >
                {selectedCampaign?.ctr || "4.82%"}
              </span>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] text-text-muted uppercase font-bold">
                ROAS
              </span>
              <span
                className="text-base font-bold"
                style={{ color: DESIGN_TOKENS.colors.highlightPink }}
              >
                {selectedCampaign?.roas || "4.2x"}
              </span>
            </div>
          </div>

          {/* Campaign Info Card */}
          <div className="rounded-12 border border-border-default p-4 bg-surface-card space-y-3">
            <h5 className="text-xs font-bold text-text-dark uppercase tracking-wider">
              Campaign Info
            </h5>

            <div className="space-y-2.5">
              {[
                { label: "Platform", value: selectedCampaign?.platform },
                {
                  label: "User",
                  value: selectedCampaign?.userEmail
                    ? `${selectedCampaign.userEmail}${selectedCampaign.manager ? ` (${selectedCampaign.manager})` : ""}`
                    : "—",
                },
                { label: "Date Range", value: selectedCampaign?.dateRange },
                { label: "Status", value: selectedCampaign?.status },
                { label: "Daily Budget", value: selectedCampaign?.daily_budget || "$3,000" },
                { label: "Impressions", value: selectedCampaign?.impressions?.toLocaleString() ?? "0" },
                { label: "Clicks", value: selectedCampaign?.clicks?.toLocaleString() ?? "0" },
                { label: "Conversions", value: selectedCampaign?.conversions?.toLocaleString() ?? "0" },
              ].map((item, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between p-2 rounded-[8px] bg-surface-primary border border-border-default"
                >
                  <span className="text-xs text-text-muted">{item.label}</span>
                  <span className="text-xs font-medium text-text-dark truncate max-w-50" title={String(item.value)}>
                    {item.value || "—"}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Feature List Card */}
          <div className="rounded-12 border border-border-default p-4 bg-surface-card space-y-3">
            <h5 className="text-xs font-bold text-text-dark uppercase tracking-wider">
              Included Automated Features
            </h5>

            <div className="space-y-2">
              {[
                "Smart Bidding with Real-time Signal Processing",
                "Automated Creative Lookalike Generation",
                "Conversion API (CAPI) Server-side Tracking",
                "High ROAS Anomaly Prevention Engine",
              ].map((feat, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between p-2 rounded-[8px] bg-surface-primary border border-border-default"
                >
                  <div className="flex items-center gap-2 text-xs font-medium text-text-dark">
                    <CheckCircle2
                      size={16}
                      style={{ color: DESIGN_TOKENS.colors.stateSuccess }}
                    />
                    <span>{feat}</span>
                  </div>
                  <span
                    className="text-[10px] font-bold px-1.5 py-0.5 rounded-[4px]"
                    style={{
                      color: DESIGN_TOKENS.colors.stateSuccess,
                      backgroundColor: `${DESIGN_TOKENS.colors.stateSuccess}14`,
                    }}
                  >
                    Active
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Action CTA Buttons */}
          <div className="pt-4 border-t border-border-default space-y-2.5">
            <button
              type="button"
              onClick={() => setIsDrawerOpen(false)}
              className="w-full py-2.5 rounded-10 border border-border-default text-text-muted hover:text-text-dark hover:bg-surface-primary text-xs font-semibold transition-colors cursor-pointer"
            >
              Close Drawer
            </button>
          </div>
        </div>
      </Drawer>

      {/* PostHog Event Inspection Drawer */}
      <PostHogEventDrawer
        event={selectedPostHogEvent}
        isOpen={isPostHogDrawerOpen}
        onClose={() => {
          setIsPostHogDrawerOpen(false);
          setSelectedPostHogEvent(null);
        }}
      />

      {/* User Journey Details Timeline Drawer */}
      <UserJourneyDrawer
        distinctId={selectedUserDistinctId}
        isOpen={isUserJourneyDrawerOpen}
        onClose={() => {
          setIsUserJourneyDrawerOpen(false);
          setSelectedUserDistinctId(null);
        }}
      />

      {/* PostHog Cloud Configuration Modal */}
      <PostHogConfigModal
        isOpen={isConfigModalOpen}
        onClose={() => setIsConfigModalOpen(false)}
      />
    </div>
  );
};

export default CampaignActivity;