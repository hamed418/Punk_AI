import { useState } from "react";
import { Modal, Skeleton } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { modals } from "@mantine/modals";
import { History, RotateCcw, ChevronLeft, ChevronRight, Mail } from "lucide-react";
import { useCouponRedemptions, useRevertCouponRedemption } from "@/hooks/api/useRedeem";
import type { CouponRedemptionResponse } from "@/api/redeem";

interface CouponRedemptionsModalProps {
  opened: boolean;
  onClose: () => void;
  couponId?: string | null;
  couponCode?: string | null;
}

const PAGE_SIZE = 10;

const CouponRedemptionsModalContent = ({
  couponId,
}: {
  couponId?: string | null;
}) => {
  const [page, setPage] = useState(1);
  const { data, isLoading, isFetching } = useCouponRedemptions({
    coupon_id: couponId ?? undefined,
    page,
    limit: PAGE_SIZE,
  });

  const revertMutation = useRevertCouponRedemption();

  const redemptions = data?.data ?? [];
  const total = data?.total ?? redemptions.length;
  const totalPages = data?.total_pages ?? (Math.ceil(total / PAGE_SIZE) || 1);

  const handleRevert = (item: CouponRedemptionResponse) => {
    const idShort = item.id ? `${String(item.id).slice(0, 8)}...` : "";
    modals.openConfirmModal({
      title: (
        <div className="flex items-center gap-2">
          <RotateCcw size={16} className="text-amber-500" />
          <span className="font-bold text-sm text-text-dark">Revert Coupon Redemption</span>
        </div>
      ),
      children: (
        <p className="text-xs text-text-muted leading-relaxed">
          Are you sure you want to revert redemption <span className="font-mono font-semibold text-text-dark">{idShort}</span> for user{" "}
          <span className="font-semibold text-text-dark">{item.email || item.user_id}</span>? This will restore one use to the coupon.
        </p>
      ),
      labels: { confirm: "Revert Redemption", cancel: "Cancel" },
      confirmProps: { color: "orange" },
      centered: true,
      onConfirm: async () => {
        try {
          await revertMutation.mutateAsync(item.id);
          notifications.show({
            title: "Redemption Reverted",
            message: "The coupon usage count was decremented and status set to reverted.",
            color: "teal",
          });
        } catch (err: unknown) {
          const errorObj = err as { message?: string; data?: { detail?: string } };
          notifications.show({
            title: "Revert Failed",
            message: errorObj?.data?.detail || errorObj?.message || "Could not revert redemption.",
            color: "red",
          });
        }
      },
    });
  };

  const formatDate = (isoString?: string | null) => {
    if (!isoString) return "—";
    try {
      return new Date(isoString).toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return isoString;
    }
  };

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-12 border border-border-default bg-surface-card shadow-2xs">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-border-default bg-surface-primary/50 text-[11px] font-semibold text-text-muted uppercase tracking-wider">
              <th className="px-4 py-3">User</th>
              <th className="px-4 py-3">Amounts</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Redeemed At</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-default text-xs text-text-dark">
            {isLoading ? (
              Array.from({ length: 4 }).map((_, i) => (
                <tr key={i}>
                  <td className="px-4 py-3"><Skeleton height={14} width={140} radius="sm" /></td>
                  <td className="px-4 py-3"><Skeleton height={14} width={100} radius="sm" /></td>
                  <td className="px-4 py-3"><Skeleton height={18} width={60} radius="md" /></td>
                  <td className="px-4 py-3"><Skeleton height={14} width={120} radius="sm" /></td>
                  <td className="px-4 py-3 text-right"><Skeleton height={20} width={60} radius="sm" className="ml-auto" /></td>
                </tr>
              ))
            ) : redemptions.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-text-muted">
                  No redemption records found.
                </td>
              </tr>
            ) : (
              redemptions.map((item) => (
                <tr key={item.id} className="hover:bg-surface-primary/40 transition-colors">
                  <td className="px-4 py-3">
                    <div className="flex flex-col">
                      <span className="font-medium text-text-dark flex items-center gap-1.5">
                        <Mail size={12} className="text-text-muted" />
                        {item.email || "No email"}
                      </span>
                      <span className="text-[10px] text-text-muted font-mono">
                        {item.user_id ? `${String(item.user_id).slice(0, 8)}...` : ""}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-col text-[11px]">
                      <span>Orig: <span className="font-semibold">${(item.original_amount ?? 0).toFixed(2)}</span></span>
                      <span className="text-emerald-500 font-semibold">-${(item.discounted_amount ?? 0).toFixed(2)}</span>
                      <span className="text-text-muted">Final: ${(item.final_amount ?? 0).toFixed(2)}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                        item.status === "applied"
                          ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20"
                          : "bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20"
                      }`}
                    >
                      <span className={`w-1.5 h-1.5 rounded-full ${item.status === "applied" ? "bg-emerald-500" : "bg-amber-500"}`} />
                      <span>{item.status === "applied" ? "Applied" : "Reverted"}</span>
                    </span>
                  </td>
                  <td className="px-4 py-3 text-[11px] text-text-muted">
                    {formatDate(item.redeemed_at)}
                    {item.reverted_at && (
                      <div className="text-[10px] text-amber-500">
                        Reverted: {formatDate(item.reverted_at)}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {item.status === "applied" ? (
                      <button
                        type="button"
                        onClick={() => handleRevert(item)}
                        disabled={revertMutation.isPending}
                        className="px-2.5 py-1 rounded-8 border border-border-default bg-surface-primary hover:bg-surface-card text-amber-600 dark:text-amber-400 hover:border-amber-500/40 text-[11px] font-semibold transition-colors cursor-pointer inline-flex items-center gap-1"
                      >
                        <RotateCcw size={12} />
                        <span>Revert</span>
                      </button>
                    ) : (
                      <span className="text-[11px] text-text-muted italic">Already Reverted</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination controls */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-2">
          <span className="text-xs text-text-muted">
            Page {page} of {totalPages} ({total} redemptions)
          </span>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1 || isFetching}
              className="p-1 rounded-8 border border-border-default bg-surface-card text-text-muted hover:text-text-dark disabled:opacity-40 transition-colors cursor-pointer"
            >
              <ChevronLeft size={14} />
            </button>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages || isFetching}
              className="p-1 rounded-8 border border-border-default bg-surface-card text-text-muted hover:text-text-dark disabled:opacity-40 transition-colors cursor-pointer"
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export const CouponRedemptionsModal = ({
  opened,
  onClose,
  couponId,
  couponCode,
}: CouponRedemptionsModalProps) => {
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2">
          <History size={17} className="text-text-dark" />
          <span className="font-bold text-sm text-text-dark">
            {couponCode ? `Redemptions History: ${couponCode}` : "All Coupon Redemptions"}
          </span>
        </div>
      }
      size="xl"
      centered
      radius="md"
      overlayProps={{ backgroundOpacity: 0.55, blur: 3 }}
      styles={{
        header: {
          backgroundColor: "var(--color-surface-card)",
          borderBottom: "1px solid var(--color-border-default)",
          padding: "16px 20px",
        },
        body: {
          backgroundColor: "var(--color-surface-card)",
          padding: "20px",
        },
      }}
    >
      {opened && (
        <CouponRedemptionsModalContent
          key={couponId ?? "all"}
          couponId={couponId}
        />
      )}
    </Modal>
  );
};

export default CouponRedemptionsModal;
