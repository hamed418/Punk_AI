import { useState, useMemo } from "react";
import { Skeleton, Switch } from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import {
  KeyRound,
  Plus,
  Search,
  Pencil,
  Trash2,
  Copy,
  Check,
  Calendar,
  Eye,
  Shield,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { useRedeemCodes, useDeleteRedeemCode, useUpdateRedeemCode } from "@/hooks/api/useRedeem";
import type { RedeemCodesResponse } from "@/api/redeem";
import CodeModal from "./code-modal";
import CodeDetailModal from "./code-detail-modal";

type FilterTabType = "all" | "active" | "inactive" | "single" | "multi";

const PAGE_SIZE = 10;

export const CodeTab = () => {
  const [page, setPage] = useState(1);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState<FilterTabType>("all");

  const [togglingCodeId, setTogglingCodeId] = useState<string | null>(null);
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  // Modals state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [codeToEdit, setCodeToEdit] = useState<RedeemCodesResponse | null>(null);

  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);
  const [selectedCodeId, setSelectedCodeId] = useState<string | null>(null);

  // Query params
  const queryParams = useMemo(() => {
    const params: {
      page: number;
      limit: number;
      search?: string;
      is_active?: boolean;
    } = {
      page,
      limit: PAGE_SIZE,
    };

    if (searchQuery.trim()) {
      params.search = searchQuery.trim();
    }

    if (activeFilter === "active") {
      params.is_active = true;
    } else if (activeFilter === "inactive") {
      params.is_active = false;
    }

    return params;
  }, [page, searchQuery, activeFilter]);

  const { data, isLoading, isFetching } = useRedeemCodes(queryParams);
  const deleteMutation = useDeleteRedeemCode();
  const updateMutation = useUpdateRedeemCode();

  // Local filter for single vs multi if needed
  const codes = useMemo(() => {
    const list = data?.data ?? [];
    if (activeFilter === "single") {
      return list.filter((c) => c.is_single);
    }
    if (activeFilter === "multi") {
      return list.filter((c) => !c.is_single);
    }
    return list;
  }, [data, activeFilter]);

  const total = data?.total ?? codes.length;
  const totalPages = data?.total_pages ?? (Math.ceil(total / PAGE_SIZE) || 1);

  const handleCopyCode = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(code);
    notifications.show({
      title: "Code Copied",
      message: `Redeem code '${code}' copied to clipboard.`,
      color: "teal",
    });
    setTimeout(() => setCopiedCode(null), 2000);
  };

  const handleOpenCreate = () => {
    setCodeToEdit(null);
    setIsModalOpen(true);
  };

  const handleOpenEdit = (code: RedeemCodesResponse) => {
    setCodeToEdit(code);
    setIsModalOpen(true);
  };

  const handleOpenDetails = (codeId: string) => {
    setSelectedCodeId(codeId);
    setIsDetailModalOpen(true);
  };

  const handleToggleActive = async (code: RedeemCodesResponse, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      setTogglingCodeId(code.id);
      const nextActive = !code.is_active;
      await updateMutation.mutateAsync({
        codeId: code.id,
        payload: {
          is_active: nextActive,
        },
      });
      notifications.show({
        title: nextActive ? "Code Activated" : "Code Deactivated",
        message: `Redeem code ${code.code} is now ${nextActive ? "active" : "inactive"}.`,
        color: nextActive ? "teal" : "orange",
      });
    } catch (err: unknown) {
      const errorObj = err as { message?: string; data?: { detail?: string } };
      notifications.show({
        title: "Update Failed",
        message: errorObj?.data?.detail || errorObj?.message || "Could not change active status.",
        color: "red",
      });
    } finally {
      setTogglingCodeId(null);
    }
  };

  const handleDelete = (code: RedeemCodesResponse) => {
    modals.openConfirmModal({
      title: (
        <div className="flex items-center gap-2">
          <Trash2 size={16} className="text-red-500" />
          <span className="font-bold text-sm text-text-dark">Delete Redeem Code</span>
        </div>
      ),
      children: (
        <p className="text-xs text-text-muted leading-relaxed">
          Are you sure you want to permanently delete redeem code{" "}
          <span className="font-bold font-mono text-text-dark">{code.code}</span>? This action cannot be undone.
        </p>
      ),
      labels: { confirm: "Delete Code", cancel: "Cancel" },
      confirmProps: { color: "red" },
      centered: true,
      onConfirm: async () => {
        try {
          await deleteMutation.mutateAsync(code.id);
          notifications.show({
            title: "Code Deleted",
            message: `Redeem code ${code.code} has been deleted.`,
            color: "green",
          });
        } catch (err: unknown) {
          const errorObj = err as { message?: string; data?: { detail?: string } };
          notifications.show({
            title: "Delete Failed",
            message: errorObj?.data?.detail || errorObj?.message || "Could not delete redeem code.",
            color: "red",
          });
        }
      },
    });
  };

  const formatDate = (dateStr?: string | null) => {
    if (!dateStr) return "Never";
    try {
      return new Date(dateStr).toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    } catch {
      return dateStr;
    }
  };

  const filterTabs: { id: FilterTabType; label: string }[] = [
    { id: "all", label: "All Codes" },
    { id: "active", label: "Active" },
    { id: "inactive", label: "Inactive" },
    { id: "single", label: "Single-Use" },
    { id: "multi", label: "Multi-Use" },
  ];

  return (
    <div className="space-y-4">
      {/* Top Header & Actions */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-text-dark">
            Redeem Codes Management
          </h2>
          <p className="text-xs text-text-muted mt-0.5">
            Generate one-time or multi-use redemption codes for subscriptions, testing, or user gifts.
          </p>
        </div>

        <button
          type="button"
          onClick={handleOpenCreate}
          className="px-4 py-2 rounded-8 btn-gradient-black text-xs font-semibold cursor-pointer flex items-center gap-2 shadow-2xs group"
        >
          <Plus size={15} strokeWidth={2.5} className="group-hover:scale-110 transition-transform" />
          <span>Generate Code</span>
        </button>
      </div>

      {/* Pill-shaped Search Bar */}
      <div
        className="w-full h-11 px-4 rounded-full border border-border-default bg-surface-card flex items-center gap-3 transition-colors shadow-2xs hover:border-text-muted/40 focus-within:border-text-dark"
        style={{ borderRadius: "9999px" }}
      >
        <Search size={16} className="text-text-muted shrink-0 pointer-events-none" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => {
            setSearchQuery(e.target.value);
            setPage(1);
          }}
          placeholder="Search by code (e.g. A1B2C3D4)..."
          className="w-full bg-transparent text-[13px] text-text-dark placeholder:text-text-muted focus:outline-none border-none p-0"
        />
      </div>

      {/* Filter Tabs */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1">
        {filterTabs.map((tab) => {
          const isActive = activeFilter === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => {
                setActiveFilter(tab.id);
                setPage(1);
              }}
              className={`px-3 py-1.5 rounded-full text-xs font-semibold transition-all cursor-pointer whitespace-nowrap ${
                isActive
                  ? "bg-text-dark text-white shadow-2xs"
                  : "bg-surface-card border border-border-default text-text-muted hover:text-text-dark hover:border-text-muted/40"
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Table Container */}
      <div className="rounded-12 border border-border-default bg-surface-card shadow-2xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-border-default bg-surface-primary/50 text-[11px] font-semibold text-text-muted uppercase tracking-wider">
                <th className="px-4 py-3">Code</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Redemptions</th>
                <th className="px-4 py-3">Created At</th>
                <th className="px-4 py-3">Expires At</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-default text-xs text-text-dark">
              {isLoading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i}>
                    <td className="px-4 py-3.5"><Skeleton height={18} width={100} radius="md" /></td>
                    <td className="px-4 py-3.5"><Skeleton height={16} width={80} radius="sm" /></td>
                    <td className="px-4 py-3.5"><Skeleton height={14} width={90} radius="sm" /></td>
                    <td className="px-4 py-3.5"><Skeleton height={14} width={100} radius="sm" /></td>
                    <td className="px-4 py-3.5"><Skeleton height={14} width={100} radius="sm" /></td>
                    <td className="px-4 py-3.5"><Skeleton height={20} width={70} radius="md" /></td>
                    <td className="px-4 py-3.5 text-right"><Skeleton height={24} width={80} radius="sm" className="ml-auto" /></td>
                  </tr>
                ))
              ) : codes.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-text-muted">
                    <div className="w-12 h-12 rounded-full bg-surface-primary border border-border-default flex items-center justify-center mx-auto text-text-muted mb-2">
                      <KeyRound size={20} />
                    </div>
                    <p className="text-sm font-semibold text-text-dark">No redeem codes found</p>
                    <p className="text-xs text-text-muted mt-0.5">
                      {searchQuery ? "Try refining your search terms." : "Generate your first redeem code above."}
                    </p>
                  </td>
                </tr>
              ) : (
                codes.map((code) => {
                  const isCopied = copiedCode === code.code;
                  const percentUsed = Math.min(
                    100,
                    Math.round((code.redemption_count / (code.max_redemptions || 1)) * 100)
                  );

                  return (
                    <tr
                      key={code.id}
                      className={`hover:bg-surface-primary/40 transition-colors ${
                        isFetching ? "opacity-75" : ""
                      }`}
                    >
                      {/* Code */}
                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-1.5">
                          <span className="font-mono font-bold text-xs px-2 py-0.5 rounded-full bg-surface-primary border border-border-default text-text-dark">
                            {code.code}
                          </span>
                          <button
                            type="button"
                            onClick={() => handleCopyCode(code.code)}
                            className="p-1 rounded text-text-muted hover:text-text-dark transition-colors cursor-pointer"
                            title="Copy Code"
                          >
                            {isCopied ? (
                              <Check size={13} className="text-emerald-500" />
                            ) : (
                              <Copy size={13} />
                            )}
                          </button>
                        </div>
                      </td>

                      {/* Type */}
                      <td className="px-4 py-3.5">
                        <span
                          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                            code.is_single
                              ? "bg-teal-500/10 text-teal-600 dark:text-teal-400 border border-teal-500/20"
                              : "bg-purple-500/10 text-purple-600 dark:text-purple-400 border border-purple-500/20"
                          }`}
                        >
                          <Shield size={11} />
                          <span>{code.is_single ? "Single-Use" : "Multi-Use"}</span>
                        </span>
                      </td>

                      {/* Redemptions */}
                      <td className="px-4 py-3.5">
                        <div className="flex flex-col gap-1 w-28">
                          <div className="flex justify-between items-center text-[11px]">
                            <span className="font-semibold text-text-dark">
                              {code.redemption_count} / {code.max_redemptions}
                            </span>
                            <span className="text-[10px] text-text-muted">{percentUsed}%</span>
                          </div>
                          <div className="w-full h-1.5 rounded-full bg-surface-primary overflow-hidden">
                            <div
                              className="h-full bg-teal-500 rounded-full transition-all"
                              style={{ width: `${percentUsed}%` }}
                            />
                          </div>
                        </div>
                      </td>

                      {/* Created At */}
                      <td className="px-4 py-3.5 text-[11px] text-text-muted">
                        <div className="flex items-center gap-1">
                          <Calendar size={12} className="text-text-muted shrink-0" />
                          <span>{formatDate(code.created_at)}</span>
                        </div>
                      </td>

                      {/* Expires At */}
                      <td className="px-4 py-3.5 text-[11px] text-text-muted">
                        <div className="flex items-center gap-1">
                          <Calendar size={12} className="text-text-muted shrink-0" />
                          <span>{formatDate(code.expires_at)}</span>
                        </div>
                      </td>

                      {/* Status */}
                      <td className="px-4 py-3.5">
                        <div
                          role="button"
                          tabIndex={0}
                          onClick={(e) => handleToggleActive(code, e)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              handleToggleActive(code, e as unknown as React.MouseEvent);
                            }
                          }}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-8 border border-border-default bg-surface-primary hover:bg-surface-card transition-colors cursor-pointer select-none"
                          title={code.is_active ? "Click to deactivate" : "Click to activate"}
                        >
                          <Switch
                            checked={code.is_active}
                            onChange={() => {}}
                            size="xs"
                            color="teal"
                            disabled={togglingCodeId === code.id}
                            className="pointer-events-none"
                          />
                          <span
                            className={`text-[11px] font-medium ${
                              code.is_active
                                ? "text-emerald-600 dark:text-emerald-400 font-semibold"
                                : "text-text-muted"
                            }`}
                          >
                            {code.is_active ? "Active" : "Inactive"}
                          </span>
                        </div>
                      </td>

                      {/* Actions */}
                      <td className="px-4 py-3.5 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => handleOpenDetails(code.id)}
                            className="p-1.5 rounded-8 border border-border-default bg-surface-primary hover:bg-surface-card text-text-muted hover:text-text-dark transition-colors cursor-pointer"
                            title="View Redemptions Details"
                          >
                            <Eye size={13} />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleOpenEdit(code)}
                            className="p-1.5 rounded-8 border border-border-default bg-surface-primary hover:bg-surface-card text-text-muted hover:text-text-dark transition-colors cursor-pointer"
                            title="Edit Code"
                          >
                            <Pencil size={13} />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDelete(code)}
                            className="p-1.5 rounded-8 border border-border-default bg-surface-primary hover:bg-surface-card text-text-muted hover:text-red-500 transition-colors cursor-pointer"
                            title="Delete Code"
                          >
                            <Trash2 size={13} />
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

        {/* Pagination Footer */}
        {!isLoading && totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-border-default bg-surface-primary/30">
            <span className="text-xs text-text-muted">
              Showing {((page - 1) * PAGE_SIZE) + 1}–{Math.min(page * PAGE_SIZE, total)} of{" "}
              <strong className="text-text-dark">{total}</strong> codes
            </span>

            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1 || isFetching}
                className="p-1.5 rounded-8 border border-border-default bg-surface-card text-text-muted hover:text-text-dark disabled:opacity-40 transition-colors cursor-pointer"
              >
                <ChevronLeft size={14} />
              </button>
              <span className="text-xs font-semibold text-text-dark px-1.5">
                {page} / {totalPages}
              </span>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages || isFetching}
                className="p-1.5 rounded-8 border border-border-default bg-surface-card text-text-muted hover:text-text-dark disabled:opacity-40 transition-colors cursor-pointer"
              >
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Code Modal */}
      <CodeModal
        opened={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        codeToEdit={codeToEdit}
      />

      {/* Code Detail Modal */}
      <CodeDetailModal
        opened={isDetailModalOpen}
        onClose={() => setIsDetailModalOpen(false)}
        codeId={selectedCodeId}
      />
    </div>
  );
};

export default CodeTab;
