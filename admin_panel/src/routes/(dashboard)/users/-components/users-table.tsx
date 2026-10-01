import React, { useState } from "react";
import {
  Avatar,
  Drawer,
  Modal,
  Skeleton,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  Loader2,
  Mail,
  Search,
  Send,
  ShieldAlert,
  UserCheck,
  XCircle,
} from "lucide-react";
import {
  useUsersList,
  useUserDetails,
  useUpdateUserStatus,
} from "@/hooks/api/useUsersApi";
import usersApi, { type UserListItem, type UserListParams } from "@/api/users";
import { useAuth } from "@/context/AuthContext";
import { DESIGN_TOKENS } from "@/constant/design-system";

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
}: TableCheckboxProps) => (
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
    {checked && <Check size={11} strokeWidth={3} className="text-surface-card" />}
  </button>
);

const formatLastActive = (isoDate: string | null): string => {
  if (!isoDate) return "Never";
  const date = new Date(isoDate);
  const diffMs = Date.now() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHrs = Math.floor(diffMins / 60);
  if (diffHrs < 24) return `${diffHrs}h ago`;
  const diffDays = Math.floor(diffHrs / 24);
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays} days ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
};

const formatJoinDate = (isoDate: string): string =>
  new Date(isoDate).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

const getInitials = (name: string | null, email: string): string => {
  if (name) return name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  return email[0].toUpperCase();
};

const renderPlanBadge = (plan: string | null) => {
  const label = plan ?? "Free";
  switch (label.toLowerCase()) {
    case "pro":
      return (
        <span
          className="text-[12px] font-semibold text-white tracking-wide whitespace-nowrap"
          style={{
            display: "inline-flex",
            padding: "6px 16px",
            justifyContent: "center",
            alignItems: "center",
            gap: "8px",
            borderRadius: "8px",
            border: "1px solid rgba(255,255,255,0.12)",
            background:
              "linear-gradient(180deg,rgba(255,255,255,.16) 0%,rgba(255,255,255,0) 100%),linear-gradient(90deg,#0A0A0A 0%,#171717 49.52%,#0A0A0A 100%)",
            boxShadow:
              "0 4px 46px 0 rgba(255,255,255,.16) inset,0 0 0 1px rgba(186,186,186,.8),0 1px 2px 0 rgba(14,18,27,.16)",
          }}
        >
          Pro
        </span>
      );
    case "standard":
      return (
        <span
          className="text-[12px] font-semibold text-[#3B2A8C] dark:text-[#D1C8FF] tracking-wide whitespace-nowrap"
          style={{
            display: "inline-flex",
            padding: "6px 16px",
            justifyContent: "center",
            alignItems: "center",
            gap: "8px",
            borderRadius: "8px",
            background: "var(--State-Primary-Light, #D1C8FF)",
          }}
        >
          Standard
        </span>
      );
    case "starter":
      return (
        <span className="inline-flex items-center justify-center px-3 py-0.5 rounded-full text-[11px] font-semibold bg-highlight-teal/15 text-highlight-teal">
          Starter
        </span>
      );
    default:
      return (
        <span
          className="text-[12px] font-medium text-text-dark tracking-wide whitespace-nowrap"
          style={{
            display: "inline-flex",
            padding: "6px 16px",
            justifyContent: "center",
            alignItems: "center",
            borderRadius: "8px",
            border: "1px solid var(--Stroke-Secondary,#DFDFDF)",
            background: "var(--Background-Surface-Neutral-Lv1,#F8F8F8)",
          }}
        >
          {label}
        </span>
      );
  }
};

const PLAN_TABS = [
  { label: "All", value: "all" },
  { label: "Free", value: "free" },
  { label: "Starter", value: "starter" },
  { label: "Standard", value: "standard" },
  { label: "Pro", value: "pro" },
  { label: "Suspended", value: "suspended" },
];

const PAGE_SIZE = 10;

// ── Component ──────────────────────────────────────────────────────────────

const UsersTable = () => {
  const [page, setPage] = useState(1);
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [activeTab, setActiveTab] = useState("all");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  // Impersonation integration
  const { user: currentAdmin } = useAuth();
  const [isConfirmModalOpen, setIsConfirmModalOpen] = useState(false);
  const [isImpersonatingPending, setIsImpersonatingPending] = useState(false);

  // Build query params — all filtering is server-side
  const queryParams: UserListParams = {
    page,
    limit: PAGE_SIZE,
    ...(debouncedSearch ? { search: debouncedSearch } : {}),
    ...(activeTab === 'suspended' ? { is_active: false } : {}),
    ...(activeTab !== 'all' && activeTab !== 'suspended' ? { plan: activeTab } : {}),
  };

  const { data, isLoading, isFetching, isPlaceholderData } = useUsersList(queryParams);
  const { data: selectedUser, isLoading: isLoadingDetails } = useUserDetails(
    isDrawerOpen ? selectedUserId : null
  );
  const updateStatus = useUpdateUserStatus();

  const users = data?.data ?? [];
  // Use fresh data's pagination counts — don't show stale counts from previous filter
  const totalPages = isPlaceholderData ? 0 : (data?.total_pages ?? 0);
  const totalCount = isPlaceholderData ? 0 : (data?.total ?? 0);

  // Show skeleton when initial loading OR when switching pages/tabs (placeholder data)
  const showSkeleton = isLoading || isPlaceholderData;
  const filteredUsers = showSkeleton ? [] : users;

  const searchTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setSearchQuery(val);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    searchTimerRef.current = setTimeout(() => {
      setDebouncedSearch(val);
      setPage(1);
    }, 350);
  };

  const handleRowClick = (user: UserListItem) => {
    setSelectedUserId(user.id);
    setIsDrawerOpen(true);
  };

  const handleSelectAll = () => {
    if (selectedIds.length === filteredUsers.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(filteredUsers.map((u) => u.id));
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handleExportCSV = () => {
    const headers = ["ID", "Name", "Email", "Plan", "Campaigns", "AI Chats", "Last Active", "Joined", "Status"];
    const rows = filteredUsers.map((u) => [
      u.id,
      u.full_name ?? "",
      u.email,
      u.subscription_plan ?? "Free",
      u.campaigns_count,
      u.conversations_count,
      formatLastActive(u.last_active_at),
      formatJoinDate(u.created_at),
      u.is_active ? "Active" : "Suspended",
    ]);
    const csv = "data:text/csv;charset=utf-8," +
      [headers.join(","), ...rows.map((r) => r.map(String).join(","))].join("\n");
    const link = document.createElement("a");
    link.setAttribute("href", encodeURI(csv));
    link.setAttribute("download", `users_export_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleToggleStatus = () => {
    if (!selectedUser) return;
    updateStatus.mutate(
      { userId: selectedUser.id, is_active: !selectedUser.is_active },
      { onSuccess: () => setIsDrawerOpen(false) }
    );
  };

  const handleConfirmImpersonation = async () => {
    if (!selectedUser) return;
    setIsImpersonatingPending(true);
    try {
      const res = await usersApi.impersonate(selectedUser.id);
      setIsConfirmModalOpen(false);
      setIsDrawerOpen(false);

      const frontendUrl =
        (import.meta.env.VITE_FRONTEND_URL as string) || "http://localhost:3000";
      const cleanFrontendUrl = frontendUrl.replace(/\/$/, "");
      const launchUrl = `${cleanFrontendUrl}/api/auth/impersonate?token=${encodeURIComponent(
        res.access_token
      )}&refresh_token=${encodeURIComponent(
        res.refresh_token
      )}&admin_url=${encodeURIComponent(window.location.origin)}&redirect=/chat`;

      window.open(launchUrl, "_blank", "noopener,noreferrer");

      notifications.show({
        title: "User Workspace Launched",
        message: `Opened ${selectedUser.full_name || selectedUser.email}'s account in the frontend application.`,
        color: "teal",
        autoClose: 5000,
      });
    } catch (err: any) {
      notifications.show({
        title: "Failed to Impersonate",
        message: err?.message || "Could not initiate impersonation session.",
        color: "red",
        autoClose: 4500,
      });
    } finally {
      setIsImpersonatingPending(false);
    }
  };

  return (
    <div className="flex flex-col gap-3.5">
      {/* Filter Bar */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2 overflow-x-auto custom-scrollbar w-full sm:w-auto pb-1 sm:pb-0">
          {PLAN_TABS.map((opt) => {
            const isActive = activeTab === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => { setActiveTab(opt.value); setPage(1); }}
                className={`px-3.5 py-1.5 rounded-full text-xs font-medium transition-all cursor-pointer shrink-0 border flex items-center gap-1.5 ${
                  isActive
                    ? "btn-gradient-black border-transparent shadow-2xs font-semibold"
                    : "bg-surface-card text-text-muted border-border-default hover:text-text-dark hover:border-text-muted/40"
                }`}
                style={{ borderRadius: "9999px" }}
              >
                {opt.label}
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-2.5 w-full sm:w-auto">
          {/* Search */}
          <div
            style={{
              display: "flex",
              width: "288px",
              height: "36px",
              padding: "0 12px",
              alignItems: "center",
              gap: "8px",
              borderRadius: "8px",
              border: "1px solid var(--Stroke-Primary,#EBEBEB)",
              background: "var(--Background-Surface-Default,#FFF)",
            }}
          >
            <Search size={15} className="text-text-muted shrink-0 pointer-events-none" />
            <input
              type="text"
              placeholder="Search by name or email…"
              value={searchQuery}
              onChange={handleSearch}
              className="h-full w-full bg-transparent text-[13px] text-text-dark placeholder:text-text-muted focus:outline-none border-none p-0"
            />
          </div>

          {/* Export */}
          <button
            type="button"
            onClick={handleExportCSV}
            className="text-[13px] font-medium text-text-dark hover:bg-surface-primary transition-colors cursor-pointer shadow-2xs shrink-0 whitespace-nowrap"
            style={{
              display: "flex",
              height: "36px",
              padding: "0 12px",
              alignItems: "center",
              gap: "8px",
              borderRadius: "8px",
              border: "1px solid var(--Stroke-Primary,#EBEBEB)",
              background: "var(--Background-Surface-Default,#FFF)",
            }}
          >
            <Download size={14} className="text-text-muted shrink-0" />
            <span>Export</span>
          </button>
        </div>
      </div>

      {/* Table Card */}
      <div className="rounded-12 border border-border-default bg-surface-card shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-primary/70 border-b border-border-default text-[12px] font-normal text-text-muted">
                <th className="w-12 px-5 py-3 text-center">
                  <div className="flex items-center justify-center">
                    <TableCheckbox
                      checked={filteredUsers.length > 0 && selectedIds.length === filteredUsers.length}
                      onChange={handleSelectAll}
                      aria-label="Select all users"
                    />
                  </div>
                </th>
                <th className="px-4 py-3 font-normal">User</th>
                <th className="px-4 py-3 font-normal">Plan</th>
                <th className="px-4 py-3 font-normal">Campaigns</th>
                <th className="px-4 py-3 font-normal">AI chats</th>
                <th className="px-4 py-3 font-normal">Contact</th>
                <th className="px-4 py-3 font-normal text-right">Last active</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-default">
              {showSkeleton ? (
                Array.from({ length: PAGE_SIZE }).map((_, i) => (
                  <tr key={i}>
                    <td className="px-5 py-3.5"><Skeleton height={16} width={16} radius="sm" /></td>
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-2.5">
                        <Skeleton circle height={26} width={26} />
                        <Skeleton height={13} width={120} radius="sm" />
                      </div>
                    </td>
                    <td className="px-4 py-3.5"><Skeleton height={26} width={70} radius="md" /></td>
                    <td className="px-4 py-3.5"><Skeleton height={13} width={30} radius="sm" /></td>
                    <td className="px-4 py-3.5"><Skeleton height={13} width={30} radius="sm" /></td>
                    <td className="px-4 py-3.5"><Skeleton height={13} width={160} radius="sm" /></td>
                    <td className="px-4 py-3.5 text-right"><Skeleton height={13} width={80} radius="sm" /></td>
                  </tr>
                ))
              ) : filteredUsers.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-5 py-12 text-center text-sm text-text-muted">
                    No users found matching your criteria.
                  </td>
                </tr>
              ) : (
                filteredUsers.map((user) => {
                  const isSelected = selectedIds.includes(user.id);
                  return (
                    <tr
                      key={user.id}
                      onClick={() => handleRowClick(user)}
                      className={`hover:bg-surface-primary/60 transition-colors cursor-pointer ${
                        isSelected ? "bg-surface-primary/70" : ""
                      } ${isFetching ? "opacity-60" : ""}`}
                    >
                      <td className="px-5 py-3.5 text-center" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-center">
                          <TableCheckbox
                            checked={isSelected}
                            onChange={() => toggleSelect(user.id)}
                            aria-label={`Select ${user.full_name ?? user.email}`}
                          />
                        </div>
                      </td>

                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-2.5">
                          <Avatar size={26} radius="xl" color="dark">
                            {getInitials(user.full_name, user.email)}
                          </Avatar>
                          <div className="flex flex-col min-w-0">
                            <span className="text-[13px] font-medium text-text-dark leading-tight truncate">
                              {user.full_name ?? "—"}
                            </span>
                          </div>
                        </div>
                      </td>

                      <td className="px-4 py-3.5">
                        {renderPlanBadge(user.subscription_plan)}
                      </td>

                      <td className="px-4 py-3.5 text-[13px] text-text-dark font-normal">
                        {user.campaigns_count}
                      </td>

                      <td className="px-4 py-3.5 text-[13px] text-text-dark font-normal">
                        {user.conversations_count}
                      </td>

                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-2 text-[13px] text-text-dark">
                          <span className="truncate max-w-45">{user.email}</span>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              window.location.href = `mailto:${user.email}`;
                            }}
                            className="p-1 rounded text-text-muted hover:text-text-dark transition-colors cursor-pointer shrink-0"
                            title={`Email ${user.email}`}
                          >
                            <Send size={13} />
                          </button>
                        </div>
                      </td>

                      <td className="px-4 py-3.5 text-[13px] text-text-dark font-normal text-right">
                        {formatLastActive(user.last_active_at)}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Footer — always visible once data has loaded at least once */}
        {!isLoading && (
          <div className="flex items-center justify-between px-5 py-3 border-t border-border-default bg-surface-primary/40">
            {/* Left: count info */}
            {isFetching && !isPlaceholderData ? (
              <span className="text-[12px] text-text-muted animate-pulse">Loading…</span>
            ) : isPlaceholderData || totalCount === 0 ? (
              <span className="text-[12px] text-text-muted animate-pulse">Loading…</span>
            ) : (
              <span className="text-[12px] text-text-muted">
                {((page - 1) * PAGE_SIZE) + 1}–{Math.min(page * PAGE_SIZE, totalCount)} of{" "}
                <strong className="text-text-dark">{totalCount.toLocaleString()}</strong> users
              </span>
            )}

            {/* Right: prev / page-indicator / next */}
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1 || isFetching}
                className="p-1.5 rounded-8 border border-border-default bg-surface-card text-text-muted hover:text-text-dark disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
              >
                <ChevronLeft size={14} />
              </button>
              <span className="text-[12px] font-medium text-text-dark px-1 min-w-13 text-center">
                {isPlaceholderData ? (
                  <span className="animate-pulse">…</span>
                ) : (
                  `${page} / ${totalPages || 1}`
                )}
              </span>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(Math.max(totalPages, 1), p + 1))}
                disabled={page >= (totalPages || 1) || isFetching || isPlaceholderData}
                className="p-1.5 rounded-8 border border-border-default bg-surface-card text-text-muted hover:text-text-dark disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
              >
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* User Detail Drawer */}
      <Drawer
        opened={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        position="right"
        size="md"
        padding="lg"
        title={
          isLoadingDetails ? (
            <div className="flex items-center gap-2.5">
              <Skeleton circle height={32} width={32} />
              <div>
                <Skeleton height={13} width={120} radius="sm" mb={4} />
                <Skeleton height={11} width={80} radius="sm" />
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-2.5">
              <Avatar size={32} radius="xl" color="dark">
                {selectedUser
                  ? getInitials(selectedUser.full_name, selectedUser.email)
                  : "?"}
              </Avatar>
              <div>
                <h4 className="text-sm font-bold text-text-dark">
                  {selectedUser?.full_name ?? selectedUser?.email ?? "User Details"}
                </h4>
                <p className="text-[11px] text-text-muted">
                  {selectedUser?.id.slice(0, 8)}… •{" "}
                  {selectedUser?.is_active ? "Active" : "Suspended"}
                </p>
              </div>
            </div>
          )
        }
        styles={{
          header: {
            borderBottom: "1px solid var(--border-primary)",
            paddingBottom: "12px",
          },
          body: { paddingTop: "16px" },
        }}
      >
        {isLoadingDetails ? (
          <div className="space-y-4">
            <Skeleton height={80} radius="md" />
            <Skeleton height={200} radius="md" />
            <Skeleton height={160} radius="md" />
          </div>
        ) : selectedUser ? (
          <div className="space-y-6">
            {/* Metric Summary */}
            <div className="grid grid-cols-3 gap-2.5 p-3 rounded-12 border border-border-default bg-surface-primary">
              <div className="flex flex-col">
                <span className="text-[10px] text-text-muted uppercase font-bold">Plan</span>
                <div className="mt-1">{renderPlanBadge(selectedUser.subscription_plan)}</div>
              </div>
              <div className="flex flex-col">
                <span className="text-[10px] text-text-muted uppercase font-bold">Campaigns</span>
                <span className="text-base font-bold" style={{ color: DESIGN_TOKENS.colors.highlightTeal }}>
                  {selectedUser.campaigns_count}
                </span>
              </div>
              <div className="flex flex-col">
                <span className="text-[10px] text-text-muted uppercase font-bold">AI Chats</span>
                <span className="text-base font-bold" style={{ color: DESIGN_TOKENS.colors.graphMarker }}>
                  {selectedUser.conversations_count}
                </span>
              </div>
            </div>

            {/* Account Info */}
            <div className="rounded-12 border border-border-default p-4 bg-surface-card space-y-3">
              <h5 className="text-xs font-bold text-text-dark uppercase tracking-wider">
                Account Information
              </h5>
              <div className="space-y-2.5">
                {[
                  { label: "Email Address", value: selectedUser.email },
                  { label: "Member Since", value: formatJoinDate(selectedUser.created_at) },
                  { label: "Last Active", value: formatLastActive(selectedUser.last_active_at) },
                  { label: "Verified", value: selectedUser.is_verified ? "Yes ✓" : "No" },
                  { label: "Account Status", value: selectedUser.is_active ? "Active" : "Suspended" },
                  { label: "Free Messages Used", value: `${selectedUser.free_token_usage ?? 0} / ${selectedUser.free_message_limit ?? 10000}` },
                ].map((item, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between p-2 rounded-8 bg-surface-primary border border-border-default"
                  >
                    <span className="text-xs text-text-muted">{item.label}</span>
                    <span className="text-xs font-medium text-text-dark">{item.value}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Session Stats */}
            <div className="rounded-12 border border-border-default p-4 bg-surface-card space-y-3">
              <h5 className="text-xs font-bold text-text-dark uppercase tracking-wider">
                Sessions & Integrations
              </h5>
              <div className="grid grid-cols-2 gap-2">
                {[
                  { label: "Active Sessions", value: selectedUser.active_devices_count },
                  { label: "Total Logins", value: selectedUser.login_count },
                  { label: "Meta Accounts", value: selectedUser.meta_accounts_count },
                  { label: "Ads Accounts", value: selectedUser.ads_accounts_count },
                ].map((item, idx) => (
                  <div
                    key={idx}
                    className="flex flex-col p-2.5 rounded-8 bg-surface-primary border border-border-default"
                  >
                    <span className="text-[10px] text-text-muted uppercase font-bold">{item.label}</span>
                    <span className="text-lg font-bold text-text-dark">{item.value}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Active Ads Accounts */}
            {selectedUser.active_ads_accounts.length > 0 && (
              <div className="rounded-12 border border-border-default p-4 bg-surface-card space-y-3">
                <h5 className="text-xs font-bold text-text-dark uppercase tracking-wider">
                  Active Ads Accounts
                </h5>
                <div className="space-y-2">
                  {selectedUser.active_ads_accounts.map((acc) => (
                    <div
                      key={acc.id}
                      className="flex items-center justify-between p-2 rounded-8 bg-surface-primary border border-border-default"
                    >
                      <span className="text-xs font-medium text-text-dark">
                        {acc.ad_account_name ?? acc.ad_account_id ?? acc.id.slice(0, 8)}
                      </span>
                      <span
                        className="text-[10px] font-bold px-1.5 py-0.5 rounded-4"
                        style={{
                          color: DESIGN_TOKENS.colors.stateSuccess,
                          backgroundColor: `${DESIGN_TOKENS.colors.stateSuccess}14`,
                        }}
                      >
                        {acc.is_subscribed ? "Subscribed" : "Connected"}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Actions */}
            <div className="pt-4 border-t border-border-default space-y-2.5">
              {/* Impersonate User Action */}
              {(() => {
                const isSelf = selectedUser.id === currentAdmin?.id;
                const isSuperAdmin = selectedUser.role === "super_admin";
                const isAdmin = selectedUser.role === "admin";
                const isDisallowedAdmin = isAdmin && currentAdmin?.role !== "super_admin";
                const isSuspended = !selectedUser.is_active;
                const isDisabled = isSelf || isSuperAdmin || isDisallowedAdmin || isSuspended;

                const disabledReason = isSelf
                  ? "You cannot impersonate your own administrator account"
                  : isSuspended
                  ? "Suspended accounts cannot be impersonated"
                  : isSuperAdmin
                  ? "Super administrator accounts cannot be impersonated"
                  : isDisallowedAdmin
                  ? "Administrative accounts can only be impersonated by super admins"
                  : undefined;

                return (
                  <button
                    type="button"
                    onClick={() => setIsConfirmModalOpen(true)}
                    disabled={isDisabled}
                    title={disabledReason}
                    className="w-full py-2.5 rounded-10 border border-amber-500/40 bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 text-xs font-semibold transition-all cursor-pointer flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed uppercase tracking-wider"
                  >
                    <UserCheck size={14} className="text-amber-400" />
                    <span>Impersonate User</span>
                  </button>
                );
              })()}

              <button
                type="button"
                onClick={() => { window.location.href = `mailto:${selectedUser.email}`; }}
                className="w-full py-3 rounded-10 text-surface-card text-xs font-bold uppercase tracking-wider bg-gradient-purchase-cta shadow-md hover:opacity-95 transition-opacity flex items-center justify-center gap-2 cursor-pointer"
              >
                <Mail size={14} className="text-highlight-cyan" />
                <span>Contact via Email</span>
              </button>

              <button
                type="button"
                onClick={handleToggleStatus}
                disabled={updateStatus.isPending}
                className={`w-full py-2.5 rounded-10 border text-xs font-semibold transition-colors cursor-pointer flex items-center justify-center gap-2 ${
                  selectedUser.is_active
                    ? "border-red-300 text-red-500 hover:bg-red-50"
                    : "border-green-300 text-green-600 hover:bg-green-50"
                } disabled:opacity-50`}
              >
                {selectedUser.is_active ? (
                  <><XCircle size={14} /> {updateStatus.isPending ? "Suspending…" : "Suspend User"}</>
                ) : (
                  <><CheckCircle2 size={14} /> {updateStatus.isPending ? "Activating…" : "Activate User"}</>
                )}
              </button>

              <button
                type="button"
                onClick={() => setIsDrawerOpen(false)}
                className="w-full py-2.5 rounded-10 border border-border-default text-text-muted hover:text-text-dark hover:bg-surface-primary text-xs font-semibold transition-colors cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        ) : null}
      </Drawer>

      {/* Impersonation Confirmation Dialog */}
      <Modal
        opened={isConfirmModalOpen}
        onClose={() => !isImpersonatingPending && setIsConfirmModalOpen(false)}
        title={
          <div className="flex items-center gap-2 text-sm font-bold text-text-dark">
            <ShieldAlert size={18} className="text-amber-400" />
            <span>Confirm User Impersonation</span>
          </div>
        }
        centered
        styles={{
          content: {
            backgroundColor: "var(--primary-background, #121212)",
            border: "1px solid rgba(255, 255, 255, 0.12)",
            borderRadius: "14px",
            boxShadow: "0 10px 40px rgba(0, 0, 0, 0.5)",
          },
          header: {
            backgroundColor: "var(--primary-background, #121212)",
            borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
            paddingBottom: "12px",
          },
        }}
      >
        {selectedUser && (
          <div className="space-y-4 pt-2">
            <div className="p-3.5 rounded-10 bg-surface-primary border border-border-default space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="text-text-muted">Target Account:</span>
                <span className="font-bold text-white">{selectedUser.full_name || "Anonymous User"}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-text-muted">Email:</span>
                <span className="font-mono text-text-dark">{selectedUser.email}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-text-muted">Role:</span>
                <span className="font-mono text-[11px] uppercase text-text-muted">{selectedUser.role}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-text-muted">User ID:</span>
                <span className="font-mono text-[11px] text-text-muted truncate max-w-50">{selectedUser.id}</span>
              </div>
            </div>

            <div className="p-3 rounded-8 bg-amber-500/10 border border-amber-500/20 text-xs text-amber-200/90 leading-relaxed space-y-1">
              <p className="font-semibold text-amber-300 flex items-center gap-1.5">
                <ShieldAlert size={14} /> Security Notice
              </p>
              <p className="text-[11px] text-text-muted leading-normal">
                This will open the Punk AI frontend application in a new browser tab authenticated as this user. All operations performed will be logged in the audit feed under your administrator account.
              </p>
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-2">
              <button
                type="button"
                onClick={() => setIsConfirmModalOpen(false)}
                disabled={isImpersonatingPending}
                className="px-4 py-2 rounded-8 border border-border-default text-xs font-semibold text-text-muted hover:text-text-dark hover:bg-surface-primary transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmImpersonation}
                disabled={isImpersonatingPending}
                className="px-4 py-2 rounded-8 bg-linear-to-r from-amber-400 to-amber-500 hover:from-amber-300 hover:to-amber-400 text-black text-xs font-bold transition-all shadow-sm flex items-center gap-1.5 cursor-pointer disabled:opacity-50 uppercase tracking-wider"
              >
                {isImpersonatingPending ? (
                  <>
                    <Loader2 size={13} className="animate-spin" />
                    <span>Launching Workspace…</span>
                  </>
                ) : (
                  <>
                    <ExternalLink size={13} />
                    <span>Launch User Workspace</span>
                  </>
                )}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default UsersTable;
