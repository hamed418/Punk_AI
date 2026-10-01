import { useState, useMemo } from "react";
import { Skeleton, Switch } from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import {
  Tag,
  Plus,
  Search,
  Pencil,
  Trash2,
  Copy,
  History,
  Check,
  Calendar,
  Sparkles,
  Users,
  Percent,
  DollarSign,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { useCoupons, useDeleteCoupon, useUpdateCoupon } from "@/hooks/api/useRedeem";
import type { CouponDetailResponse, DiscountType } from "@/api/redeem";
import CouponModal from "./coupon-modal";
import CouponRedemptionsModal from "./coupon-redemptions-modal";

type FilterTabType = "all" | "active" | "inactive" | DiscountType;

const PAGE_SIZE = 10;

export const CouponTab = () => {
  const [page, setPage] = useState(1);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState<FilterTabType>("all");

  const [togglingCouponId, setTogglingCouponId] = useState<string | null>(null);
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  // Modals state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [couponToEdit, setCouponToEdit] = useState<CouponDetailResponse | null>(null);

  const [isRedemptionsOpen, setIsRedemptionsOpen] = useState(false);
  const [selectedCouponForRedemptions, setSelectedCouponForRedemptions] = useState<{ id: string; code: string } | null>(null);

  // Query params
  const queryParams = useMemo(() => {
    const params: {
      page: number;
      limit: number;
      search?: string;
      status?: string | boolean;
      discount_type?: DiscountType;
    } = {
      page,
      limit: PAGE_SIZE,
    };

    if (searchQuery.trim()) {
      params.search = searchQuery.trim();
    }

    if (activeFilter === "active") {
      params.status = true;
    } else if (activeFilter === "inactive") {
      params.status = false;
    } else if (activeFilter === "percentage" || activeFilter === "fixed_amount" || activeFilter === "full_free") {
      params.discount_type = activeFilter;
    }

    return params;
  }, [page, searchQuery, activeFilter]);

  const { data, isLoading, isFetching } = useCoupons(queryParams);
  const deleteMutation = useDeleteCoupon();
  const updateMutation = useUpdateCoupon();

  const coupons = data?.data ?? [];
  const total = data?.total ?? coupons.length;
  const totalPages = data?.total_pages ?? (Math.ceil(total / PAGE_SIZE) || 1);

  const handleCopyCode = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(code);
    notifications.show({
      title: "Code Copied",
      message: `Coupon code '${code}' copied to clipboard.`,
      color: "teal",
    });
    setTimeout(() => setCopiedCode(null), 2000);
  };

  const handleOpenCreate = () => {
    setCouponToEdit(null);
    setIsModalOpen(true);
  };

  const handleOpenEdit = (coupon: CouponDetailResponse) => {
    setCouponToEdit(coupon);
    setIsModalOpen(true);
  };

  const handleOpenRedemptions = (coupon?: CouponDetailResponse) => {
    if (coupon) {
      setSelectedCouponForRedemptions({ id: coupon.id, code: coupon.code });
    } else {
      setSelectedCouponForRedemptions(null);
    }
    setIsRedemptionsOpen(true);
  };

  const handleToggleActive = async (coupon: CouponDetailResponse, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      setTogglingCouponId(coupon.id);
      const nextActive = !coupon.is_active;
      await updateMutation.mutateAsync({
        couponId: coupon.id,
        payload: {
          is_active: nextActive,
        },
      });
      notifications.show({
        title: nextActive ? "Coupon Activated" : "Coupon Deactivated",
        message: `Coupon ${coupon.code} is now ${nextActive ? "active" : "inactive"}.`,
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
      setTogglingCouponId(null);
    }
  };

  const handleDelete = (coupon: CouponDetailResponse) => {
    modals.openConfirmModal({
      title: (
        <div className="flex items-center gap-2">
          <Trash2 size={16} className="text-red-500" />
          <span className="font-bold text-sm text-text-dark">Delete Coupon</span>
        </div>
      ),
      children: (
        <p className="text-xs text-text-muted leading-relaxed">
          Are you sure you want to permanently delete coupon{" "}
          <span className="font-bold font-mono text-text-dark">{coupon.code}</span>? This action cannot be undone.
        </p>
      ),
      labels: { confirm: "Delete Coupon", cancel: "Cancel" },
      confirmProps: { color: "red" },
      centered: true,
      onConfirm: async () => {
        try {
          await deleteMutation.mutateAsync(coupon.id);
          notifications.show({
            title: "Coupon Deleted",
            message: `Coupon ${coupon.code} has been deleted.`,
            color: "green",
          });
        } catch (err: unknown) {
          const errorObj = err as { message?: string; data?: { detail?: string } };
          notifications.show({
            title: "Delete Failed",
            message: errorObj?.data?.detail || errorObj?.message || "Could not delete coupon.",
            color: "red",
          });
        }
      },
    });
  };

  const formatDate = (dateStr?: string | null) => {
    if (!dateStr) return "Open";
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
    { id: "all", label: "All Coupons" },
    { id: "active", label: "Active" },
    { id: "inactive", label: "Inactive" },
    { id: "percentage", label: "Percentage" },
    { id: "fixed_amount", label: "Fixed Amount" },
    { id: "full_free", label: "Full Free" },
  ];

  return (
    <div className="space-y-4">
      {/* Top Header & Actions */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-text-dark">
            Discount & Promotional Coupons
          </h2>
          <p className="text-xs text-text-muted mt-0.5">
            Create promotional codes, configure percentage or fixed discounts, usage caps, and validity windows.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => handleOpenRedemptions()}
            className="px-3 py-2 rounded-8 border border-border-default bg-surface-primary hover:bg-surface-card text-xs font-semibold text-text-dark transition-colors cursor-pointer flex items-center gap-1.5 shadow-2xs"
          >
            <History size={14} />
            <span>All Redemptions</span>
          </button>

          <button
            type="button"
            onClick={handleOpenCreate}
            className="px-4 py-2 rounded-8 btn-gradient-black text-xs font-semibold cursor-pointer flex items-center gap-2 shadow-2xs group"
          >
            <Plus size={15} strokeWidth={2.5} className="group-hover:scale-110 transition-transform" />
            <span>Create Coupon</span>
          </button>
        </div>
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
          placeholder="Search by coupon code or campaign description..."
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
                <th className="px-4 py-3">Discount</th>
                <th className="px-4 py-3">Redemption Limit</th>
                <th className="px-4 py-3">Validity</th>
                <th className="px-4 py-3">Flags</th>
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
                    <td className="px-4 py-3.5"><Skeleton height={14} width={70} radius="sm" /></td>
                    <td className="px-4 py-3.5"><Skeleton height={14} width={120} radius="sm" /></td>
                    <td className="px-4 py-3.5"><Skeleton height={16} width={60} radius="md" /></td>
                    <td className="px-4 py-3.5"><Skeleton height={20} width={70} radius="md" /></td>
                    <td className="px-4 py-3.5 text-right"><Skeleton height={24} width={80} radius="sm" className="ml-auto" /></td>
                  </tr>
                ))
              ) : coupons.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-text-muted">
                    <div className="w-12 h-12 rounded-full bg-surface-primary border border-border-default flex items-center justify-center mx-auto text-text-muted mb-2">
                      <Tag size={20} />
                    </div>
                    <p className="text-sm font-semibold text-text-dark">No coupons found</p>
                    <p className="text-xs text-text-muted mt-0.5">
                      {searchQuery ? "Try refining your search terms." : "Create your first discount coupon above."}
                    </p>
                  </td>
                </tr>
              ) : (
                coupons.map((coupon) => {
                  const isCopied = copiedCode === coupon.code;
                  return (
                    <tr
                      key={coupon.id}
                      className={`hover:bg-surface-primary/40 transition-colors ${
                        isFetching ? "opacity-75" : ""
                      }`}
                    >
                      {/* Code */}
                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-1.5">
                          <span className="font-mono font-bold text-xs px-2 py-0.5 rounded-full bg-surface-primary border border-border-default text-text-dark">
                            {coupon.code}
                          </span>
                          <button
                            type="button"
                            onClick={() => handleCopyCode(coupon.code)}
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
                        {coupon.description && (
                          <p className="text-[11px] text-text-muted mt-0.5 truncate max-w-xs">
                            {coupon.description}
                          </p>
                        )}
                      </td>

                      {/* Discount */}
                      <td className="px-4 py-3.5">
                        {coupon.discount_type === "percentage" && (
                          <span className="inline-flex items-center gap-1 font-semibold text-teal-600 dark:text-teal-400">
                            <Percent size={12} />
                            <span>{coupon.discount_value}% OFF</span>
                            {coupon.max_discount_amount && (
                              <span className="text-[10px] text-text-muted font-normal">
                                (cap ${coupon.max_discount_amount})
                              </span>
                            )}
                          </span>
                        )}
                        {coupon.discount_type === "fixed_amount" && (
                          <span className="inline-flex items-center gap-0.5 font-semibold text-amber-600 dark:text-amber-400">
                            <DollarSign size={12} />
                            <span>
                              {coupon.discount_value} {coupon.currency} OFF
                            </span>
                          </span>
                        )}
                        {coupon.discount_type === "full_free" && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
                            <Sparkles size={11} />
                            <span>100% Free</span>
                          </span>
                        )}
                      </td>

                      {/* Redemption Limit */}
                      <td className="px-4 py-3.5">
                        <div className="flex flex-col text-[11px]">
                          <span className="font-semibold text-text-dark">
                            {coupon.current_uses} / {coupon.max_uses ?? "∞"} used
                          </span>
                          <span className="text-[10px] text-text-muted">
                            {coupon.usage_limit_per_user ?? 1} per user
                          </span>
                        </div>
                      </td>

                      {/* Validity */}
                      <td className="px-4 py-3.5 text-[11px] text-text-muted">
                        <div className="flex items-center gap-1">
                          <Calendar size={12} className="text-text-muted shrink-0" />
                          <span>
                            {formatDate(coupon.valid_from)} → {formatDate(coupon.valid_till)}
                          </span>
                        </div>
                      </td>

                      {/* Flags */}
                      <td className="px-4 py-3.5">
                        {coupon.new_users_only ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">
                            <Users size={11} />
                            <span>New Users</span>
                          </span>
                        ) : (
                          <span className="text-[11px] text-text-muted">—</span>
                        )}
                      </td>

                      {/* Status */}
                      <td className="px-4 py-3.5">
                        <div
                          role="button"
                          tabIndex={0}
                          onClick={(e) => handleToggleActive(coupon, e)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              handleToggleActive(coupon, e as unknown as React.MouseEvent);
                            }
                          }}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-8 border border-border-default bg-surface-primary hover:bg-surface-card transition-colors cursor-pointer select-none"
                          title={coupon.is_active ? "Click to deactivate" : "Click to activate"}
                        >
                          <Switch
                            checked={coupon.is_active}
                            onChange={() => {}}
                            size="xs"
                            color="teal"
                            disabled={togglingCouponId === coupon.id}
                            className="pointer-events-none"
                          />
                          <span
                            className={`text-[11px] font-medium ${
                              coupon.is_active
                                ? "text-emerald-600 dark:text-emerald-400 font-semibold"
                                : "text-text-muted"
                            }`}
                          >
                            {coupon.is_active ? "Active" : "Inactive"}
                          </span>
                        </div>
                      </td>

                      {/* Actions */}
                      <td className="px-4 py-3.5 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => handleOpenRedemptions(coupon)}
                            className="p-1.5 rounded-8 border border-border-default bg-surface-primary hover:bg-surface-card text-text-muted hover:text-text-dark transition-colors cursor-pointer"
                            title="View Redemptions"
                          >
                            <History size={13} />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleOpenEdit(coupon)}
                            className="p-1.5 rounded-8 border border-border-default bg-surface-primary hover:bg-surface-card text-text-muted hover:text-text-dark transition-colors cursor-pointer"
                            title="Edit Coupon"
                          >
                            <Pencil size={13} />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDelete(coupon)}
                            className="p-1.5 rounded-8 border border-border-default bg-surface-primary hover:bg-surface-card text-text-muted hover:text-red-500 transition-colors cursor-pointer"
                            title="Delete Coupon"
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
              <strong className="text-text-dark">{total}</strong> coupons
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

      {/* Coupon Create/Edit Modal */}
      <CouponModal
        opened={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        couponToEdit={couponToEdit}
      />

      {/* Redemptions Modal */}
      <CouponRedemptionsModal
        opened={isRedemptionsOpen}
        onClose={() => setIsRedemptionsOpen(false)}
        couponId={selectedCouponForRedemptions?.id}
        couponCode={selectedCouponForRedemptions?.code}
      />
    </div>
  );
};

export default CouponTab;
