import React, { useState, useRef } from "react";
import {
  Drawer,
  Skeleton,
} from "@mantine/core";
import {
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Megaphone,
  Search,
  Send,
  Upload,
} from "lucide-react";
import { DESIGN_TOKENS } from "@/constant/design-system";
import {
  useCampaignsList,
  useCampaignsStats,
  useCampaignDetails,
} from "@/hooks/api/useCampaignsApi";
import type { AdminCampaignListItem, CampaignListParams } from "@/api/campaigns";

// ── Helpers ────────────────────────────────────────────────────────────────

interface TableCheckboxProps {
  checked: boolean;
  onChange: () => void;
  "aria-label"?: string;
}

const TableCheckbox = ({
  checked,
  onChange,
  "aria-label": ariaLabel,
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
      className={`w-4 h-4 rounded-[4px] border transition-all cursor-pointer inline-flex items-center justify-center shrink-0 ${
        checked
          ? "bg-text-dark border-text-dark text-surface-card shadow-2xs"
          : "bg-surface-card border-border-default hover:border-text-muted/60"
      }`}
    >
      {checked && (
        <Check size={11} strokeWidth={3} className="text-surface-card" />
      )}
    </button>
  );
};

const formatCurrency = (amount: number | null | undefined): string => {
  if (amount == null) return "—";
  return `$${Number(amount).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  })}`;
};

const formatDate = (isoString: string | null | undefined): string => {
  if (!isoString) return "—";
  return new Date(isoString).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
};

const formatDateRange = (
  start: string | null | undefined,
  end: string | null | undefined
): string => {
  if (!start && !end) return "Ongoing";
  if (start && !end) return `Since ${formatDate(start)}`;
  return `${formatDate(start)} – ${formatDate(end)}`;
};

const STATUS_CONFIG: Record<
  string,
  { label: string; bg: string; text: string; border: string }
> = {
  published: {
    label: "Published",
    bg: "rgba(0, 211, 63, 0.08)",
    text: DESIGN_TOKENS.colors.stateSuccess,
    border: "rgba(0, 211, 63, 0.2)",
  },
  approved: {
    label: "Approved",
    bg: "rgba(1, 137, 126, 0.08)",
    text: DESIGN_TOKENS.colors.highlightTeal,
    border: "rgba(1, 137, 126, 0.2)",
  },
  draft: {
    label: "Draft",
    bg: "rgba(255, 165, 0, 0.08)",
    text: "#D97706",
    border: "rgba(255, 165, 0, 0.2)",
  },
  pending_approval: {
    label: "Pending",
    bg: "rgba(245, 67, 151, 0.08)",
    text: DESIGN_TOKENS.colors.highlightPink,
    border: "rgba(245, 67, 151, 0.2)",
  },
  archived: {
    label: "Archived",
    bg: "rgba(115, 115, 115, 0.08)",
    text: "#737373",
    border: "rgba(115, 115, 115, 0.2)",
  },
};

const STATUS_FILTER_TABS = [
  { label: "All", value: "all" },
  { label: "Published", value: "published" },
  { label: "Approved", value: "approved" },
  { label: "Draft", value: "draft" },
  { label: "Archived", value: "archived" },
];

const PAGE_SIZE = 10;

// ── Component ──────────────────────────────────────────────────────────────

const CampaignsTable = () => {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [selectedCampaignId, setSelectedCampaignId] = useState<string | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Build query params
  const queryParams: CampaignListParams = {
    page,
    limit: PAGE_SIZE,
    ...(debouncedSearch ? { search: debouncedSearch } : {}),
    ...(statusFilter !== "all" ? { status: statusFilter } : {}),
  };

  const { data, isLoading, isFetching, isPlaceholderData } = useCampaignsList(queryParams);
  const { data: stats } = useCampaignsStats();
  const { data: selectedCampaignDetails, isLoading: isLoadingDetails } = useCampaignDetails(
    isDrawerOpen ? selectedCampaignId : null
  );

  const campaigns = data?.data ?? [];
  const totalPages = isPlaceholderData ? 0 : (data?.total_pages ?? 0);
  const totalCount = isPlaceholderData ? 0 : (data?.total ?? 0);
  const showSkeleton = isLoading || isPlaceholderData;
  const currentCampaigns = showSkeleton ? [] : campaigns;

  // Search handler with 350ms debounce
  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setSearchQuery(val);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    searchTimerRef.current = setTimeout(() => {
      setDebouncedSearch(val);
      setPage(1);
    }, 350);
  };

  const handleTabChange = (val: string) => {
    setStatusFilter(val);
    setPage(1);
    setSelectedIds([]);
  };

  const handleSelectAll = () => {
    if (selectedIds.length === currentCampaigns.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(currentCampaigns.map((c) => c.id));
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    );
  };

  const handleRowClick = (camp: AdminCampaignListItem) => {
    setSelectedCampaignId(camp.id);
    setIsDrawerOpen(true);
  };

  const handleExportCSV = () => {
    const headers = [
      "ID",
      "Campaign Name",
      "User Email",
      "User Name",
      "Channel",
      "Status",
      "Daily Budget (USD)",
      "Spend (USD)",
      "Impressions",
      "Clicks",
      "CTR (%)",
      "Created At",
    ];

    const rows = currentCampaigns.map((c) => [
      c.id,
      `"${(c.name || "").replace(/"/g, '""')}"`,
      `"${c.user_email || ""}"`,
      `"${(c.user_name || "").replace(/"/g, '""')}"`,
      c.platform,
      c.status,
      c.daily_budget_usd ?? "",
      c.spend_usd ?? "0",
      c.impressions,
      c.clicks,
      c.ctr,
      c.created_at,
    ]);

    const csvContent =
      "data:text/csv;charset=utf-8," +
      [headers.join(","), ...rows.map((e) => e.join(","))].join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute(
      "download",
      `campaigns_export_${new Date().toISOString().slice(0, 10)}.csv`
    );
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const getFilterCount = (value: string): number | string => {
    if (!stats) return "…";
    if (value === "all") return stats.total_campaigns;
    return stats.status_breakdown[value] ?? 0;
  };

  const activeCampaign = selectedCampaignDetails || currentCampaigns.find((c) => c.id === selectedCampaignId);

  return (
    <div className="flex flex-col gap-3.5">
      {/* Top Filter Bar & Search Toolbar */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        {/* Filter Buttons */}
        <div className="flex items-center gap-2 overflow-x-auto custom-scrollbar w-full sm:w-auto pb-1 sm:pb-0">
          {STATUS_FILTER_TABS.map((opt) => {
            const isActive = statusFilter === opt.value;
            const count = getFilterCount(opt.value);
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => handleTabChange(opt.value)}
                className={`px-3.5 py-1.5 rounded-full text-xs font-medium transition-all cursor-pointer shrink-0 border flex items-center gap-1.5 ${
                  isActive
                    ? "btn-gradient-black border-transparent shadow-2xs font-semibold"
                    : "bg-surface-card text-text-muted border-border-default hover:text-text-dark hover:border-text-muted/40"
                }`}
                style={{ borderRadius: "9999px" }}
              >
                <span>{opt.label}</span>
                <span className="text-[11px] opacity-75">{count}</span>
              </button>
            );
          })}
        </div>

        {/* Search and Action Buttons */}
        <div className="flex items-center gap-2.5 w-full sm:w-auto">
          <div
            style={{
              display: "flex",
              width: "288px",
              height: "36px",
              padding: "0 12px",
              alignItems: "center",
              gap: "8px",
              borderRadius: "var(--Radius-8, 8px)",
              border: "1px solid var(--Stroke-Primary, #EBEBEB)",
              background: "var(--Background-Surface-Default, #FFF)",
            }}
          >
            <Search
              size={15}
              className="text-text-muted shrink-0 pointer-events-none"
            />
            <input
              type="text"
              placeholder="Search campaigns or users"
              value={searchQuery}
              onChange={handleSearch}
              className="h-full w-full bg-transparent text-[13px] text-text-dark placeholder:text-text-muted focus:outline-none border-none p-0"
            />
          </div>

          {/* Export Button */}
          <button
            type="button"
            onClick={handleExportCSV}
            disabled={currentCampaigns.length === 0}
            className="text-[13px] font-medium text-text-dark hover:bg-surface-primary transition-colors cursor-pointer shadow-2xs shrink-0 whitespace-nowrap disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              display: "flex",
              height: "36px",
              padding: "0 12px",
              alignItems: "center",
              gap: "8px",
              borderRadius: "var(--Radius-8, 8px)",
              border: "1px solid var(--Stroke-Primary, #EBEBEB)",
              background: "var(--Background-Surface-Default, #FFF)",
            }}
          >
            <Upload size={14} className="text-text-muted shrink-0" />
            <span>Export</span>
          </button>
        </div>
      </div>

      {/* Campaign Table Card */}
      <div className="rounded-12 border border-border-default bg-surface-card shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-primary/70 border-b border-border-default text-[12px] font-normal text-text-muted">
                <th className="w-12 px-5 py-3 text-center">
                  <div className="flex items-center justify-center">
                    <TableCheckbox
                      checked={
                        currentCampaigns.length > 0 &&
                        selectedIds.length === currentCampaigns.length
                      }
                      onChange={handleSelectAll}
                      aria-label="Select all campaigns"
                    />
                  </div>
                </th>
                <th className="px-4 py-3 font-normal text-text-muted">Campaign</th>
                <th className="px-4 py-3 font-normal text-text-muted">User</th>
                <th className="px-4 py-3 font-normal text-text-muted">Channel</th>
                <th className="px-4 py-3 font-normal text-text-muted">Budget</th>
                <th className="px-4 py-3 font-normal text-text-muted">Spend</th>
                <th className="px-4 py-3 font-normal text-text-muted">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-default">
              {showSkeleton ? (
                Array.from({ length: 6 }).map((_, idx) => (
                  <tr key={`skel-${idx}`} className="animate-pulse">
                    <td className="px-5 py-4 text-center">
                      <Skeleton height={16} width={16} radius="xs" className="mx-auto" />
                    </td>
                    <td className="px-4 py-4">
                      <div className="flex items-center gap-2.5">
                        <Skeleton height={26} width={26} radius="xl" />
                        <Skeleton height={14} width={160} radius="sm" />
                      </div>
                    </td>
                    <td className="px-4 py-4">
                      <Skeleton height={14} width={140} radius="sm" />
                    </td>
                    <td className="px-4 py-4">
                      <Skeleton height={14} width={60} radius="sm" />
                    </td>
                    <td className="px-4 py-4">
                      <Skeleton height={14} width={70} radius="sm" />
                    </td>
                    <td className="px-4 py-4">
                      <Skeleton height={14} width={60} radius="sm" />
                    </td>
                    <td className="px-4 py-4">
                      <Skeleton height={20} width={70} radius="xl" />
                    </td>
                  </tr>
                ))
              ) : currentCampaigns.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-5 py-12 text-center text-sm text-text-muted">
                    No campaigns found matching your criteria.
                  </td>
                </tr>
              ) : (
                currentCampaigns.map((camp) => {
                  const isSelected = selectedIds.includes(camp.id);
                  const statusConf = STATUS_CONFIG[camp.status] || {
                    label: camp.status,
                    bg: "rgba(115, 115, 115, 0.08)",
                    text: "#737373",
                    border: "rgba(115, 115, 115, 0.2)",
                  };

                  return (
                    <tr
                      key={camp.id}
                      onClick={() => handleRowClick(camp)}
                      className={`hover:bg-surface-primary/60 transition-colors cursor-pointer ${
                        isSelected ? "bg-surface-primary/70" : ""
                      }`}
                    >
                      {/* Checkbox */}
                      <td
                        className="px-5 py-3.5 text-center"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className="flex items-center justify-center">
                          <TableCheckbox
                            checked={isSelected}
                            onChange={() => toggleSelect(camp.id)}
                            aria-label={`Select ${camp.name}`}
                          />
                        </div>
                      </td>

                      {/* Campaign Avatar + Name */}
                      <td className="px-4 py-3.5 max-w-70">
                        <div className="flex items-center gap-2.5">
                          <div className="w-6.5 h-6.5 rounded-full bg-surface-primary border border-border-default flex items-center justify-center shrink-0">
                            <Megaphone size={12} className="text-text-muted" />
                          </div>
                          <span
                            className="text-[13px] font-medium text-text-dark truncate"
                            title={camp.name}
                          >
                            {camp.name}
                          </span>
                        </div>
                      </td>

                      {/* User Email */}
                      <td className="px-4 py-3.5 text-[13px] text-text-dark font-normal">
                        <div className="flex flex-col">
                          <span>{camp.user_email || "—"}</span>
                          {camp.user_name && (
                            <span className="text-[11px] text-text-muted">
                              {camp.user_name}
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Channel */}
                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-1.5 text-[13px] text-text-dark font-medium capitalize">
                          <Send size={12} className="text-text-muted shrink-0 -rotate-12" />
                          <span>{camp.platform}</span>
                        </div>
                      </td>

                      {/* Budget */}
                      <td className="px-4 py-3.5 text-[13px] font-semibold text-text-dark">
                        {camp.daily_budget_usd != null
                          ? `${formatCurrency(camp.daily_budget_usd)}/d`
                          : camp.monthly_budget_usd != null
                          ? `${formatCurrency(camp.monthly_budget_usd)}/mo`
                          : "—"}
                      </td>

                      {/* Spend */}
                      <td className="px-4 py-3.5 text-[13px] font-semibold text-text-dark">
                        {formatCurrency(camp.spend_usd)}
                      </td>

                      {/* Status Tag */}
                      <td className="px-4 py-3.5">
                        <span
                          className="text-[11px] font-semibold px-2 py-0.5 rounded-full border inline-block"
                          style={{
                            backgroundColor: statusConf.bg,
                            color: statusConf.text,
                            borderColor: statusConf.border,
                          }}
                        >
                          {statusConf.label}
                        </span>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Footer */}
        <div className="px-5 py-3.5 border-t border-border-default flex flex-col sm:flex-row items-center justify-between gap-3 text-[13px] text-text-muted">
          <span>
            {showSkeleton ? (
              <span className="animate-pulse">Loading campaigns…</span>
            ) : totalCount === 0 ? (
              "0 campaigns"
            ) : (
              <>
                Showing{" "}
                <span className="font-semibold text-text-dark">
                  {(page - 1) * PAGE_SIZE + 1}
                </span>{" "}
                to{" "}
                <span className="font-semibold text-text-dark">
                  {Math.min(page * PAGE_SIZE, totalCount)}
                </span>{" "}
                of{" "}
                <span className="font-semibold text-text-dark">
                  {totalCount.toLocaleString()}
                </span>{" "}
                campaigns
              </>
            )}
          </span>

          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={page <= 1 || isFetching}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="p-1.5 rounded-[6px] border border-border-default text-text-dark hover:bg-surface-primary disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer flex items-center justify-center"
              aria-label="Previous page"
            >
              <ChevronLeft size={16} />
            </button>

            <span className="px-2 text-xs font-medium text-text-dark min-w-17.5 text-center">
              {isPlaceholderData ? (
                <span className="animate-pulse">…</span>
              ) : (
                `Page ${page} of ${Math.max(1, totalPages)}`
              )}
            </span>

            <button
              type="button"
              disabled={!data?.has_next || isFetching}
              onClick={() => setPage((p) => p + 1)}
              className="p-1.5 rounded-[6px] border border-border-default text-text-dark hover:bg-surface-primary disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer flex items-center justify-center"
              aria-label="Next page"
            >
              <ChevronRight size={16} />
            </button>
          </div>
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
                {activeCampaign?.name || "Campaign Details"}
              </h4>
              <p className="text-[11px] text-text-muted">
                {activeCampaign ? `${activeCampaign.id.slice(0, 8)} • ${activeCampaign.platform.toUpperCase()}` : "—"}
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
                {formatCurrency(activeCampaign?.spend_usd)}
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
                {activeCampaign ? `${activeCampaign.ctr.toFixed(2)}%` : "0.00%"}
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
                {activeCampaign?.roas != null ? `${activeCampaign.roas}x` : "—"}
              </span>
            </div>
          </div>

          {/* Campaign Details */}
          <div className="rounded-12 border border-border-default p-4 bg-surface-card space-y-3">
            <h5 className="text-xs font-bold text-text-dark uppercase tracking-wider">
              Campaign Info
            </h5>

            <div className="space-y-2.5">
              {[
                { label: "Platform", value: activeCampaign?.platform?.toUpperCase() },
                {
                  label: "User",
                  value: activeCampaign?.user_email
                    ? `${activeCampaign.user_email}${activeCampaign.user_name ? ` (${activeCampaign.user_name})` : ""}`
                    : "—",
                },
                {
                  label: "Daily Budget",
                  value: activeCampaign?.daily_budget_usd
                    ? formatCurrency(activeCampaign.daily_budget_usd)
                    : "—",
                },
                {
                  label: "Date Range",
                  value: formatDateRange(activeCampaign?.start_date, activeCampaign?.end_date),
                },
                {
                  label: "Status",
                  value: activeCampaign?.status ? STATUS_CONFIG[activeCampaign.status]?.label || activeCampaign.status : "—",
                },
                {
                  label: "Impressions",
                  value: activeCampaign?.impressions?.toLocaleString() ?? "0",
                },
                {
                  label: "Clicks",
                  value: activeCampaign?.clicks?.toLocaleString() ?? "0",
                },
                {
                  label: "Conversions",
                  value: activeCampaign?.conversions?.toLocaleString() ?? "0",
                },
                {
                  label: "Created Date",
                  value: formatDate(activeCampaign?.created_at),
                },
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
              Automated AI Capabilities
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

          {/* Action Buttons */}
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
    </div>
  );
};

export default CampaignsTable;
