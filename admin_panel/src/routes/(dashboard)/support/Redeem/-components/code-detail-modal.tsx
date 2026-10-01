import { Modal, Skeleton } from "@mantine/core";
import { KeyRound, Mail, Copy, Check } from "lucide-react";
import { useState } from "react";
import { useRedeemCode } from "@/hooks/api/useRedeem";

interface CodeDetailModalProps {
  opened: boolean;
  onClose: () => void;
  codeId: string | null;
}

export const CodeDetailModal = ({ opened, onClose, codeId }: CodeDetailModalProps) => {
  const { data: codeDetail, isLoading } = useRedeemCode(codeId, { enabled: opened });
  const [copied, setCopied] = useState(false);

  const handleCopy = (val: string) => {
    navigator.clipboard.writeText(val);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const formatDate = (isoString?: string | null) => {
    if (!isoString) return "Never";
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
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2">
          <KeyRound size={17} className="text-text-dark" />
          <span className="font-bold text-sm text-text-dark">
            Redeem Code Details
          </span>
        </div>
      }
      size="lg"
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
      {isLoading ? (
        <div className="space-y-4">
          <Skeleton height={30} width="60%" radius="sm" />
          <div className="grid grid-cols-2 gap-3">
            <Skeleton height={20} radius="sm" />
            <Skeleton height={20} radius="sm" />
            <Skeleton height={20} radius="sm" />
            <Skeleton height={20} radius="sm" />
          </div>
          <Skeleton height={100} radius="md" />
        </div>
      ) : !codeDetail ? (
        <p className="text-xs text-text-muted py-6 text-center">Code not found.</p>
      ) : (
        <div className="space-y-5">
          {/* Top Banner with Code */}
          <div className="p-4 rounded-10 bg-surface-primary border border-border-default flex items-center justify-between">
            <div>
              <span className="text-[11px] text-text-muted font-medium">Redemption Code</span>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-xl font-mono font-bold tracking-wider text-text-dark">
                  {codeDetail.code}
                </span>
                <button
                  type="button"
                  onClick={() => handleCopy(codeDetail.code)}
                  className="p-1 rounded text-text-muted hover:text-text-dark transition-colors cursor-pointer"
                  title="Copy code"
                >
                  {copied ? <Check size={14} className="text-emerald-500" /> : <Copy size={14} />}
                </button>
              </div>
            </div>

            <span
              className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold ${
                codeDetail.is_active
                  ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20"
                  : "bg-surface-card text-text-muted border border-border-default"
              }`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${codeDetail.is_active ? "bg-emerald-500" : "bg-text-muted"}`} />
              <span>{codeDetail.is_active ? "Active" : "Inactive"}</span>
            </span>
          </div>

          {/* Metadata Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs">
            <div className="p-3 rounded-8 bg-surface-primary/50 border border-border-default">
              <span className="text-[11px] text-text-muted block">Redemptions</span>
              <span className="font-bold text-text-dark text-sm mt-0.5 block">
                {codeDetail.redemption_count} / {codeDetail.max_redemptions}
              </span>
            </div>

            <div className="p-3 rounded-8 bg-surface-primary/50 border border-border-default">
              <span className="text-[11px] text-text-muted block">Type</span>
              <span className="font-semibold text-text-dark text-sm mt-0.5 block">
                {codeDetail.is_single ? "Single-Use" : "Multi-Use"}
              </span>
            </div>

            <div className="p-3 rounded-8 bg-surface-primary/50 border border-border-default">
              <span className="text-[11px] text-text-muted block">Expires At</span>
              <span className="font-medium text-text-dark text-xs mt-1 block truncate">
                {formatDate(codeDetail.expires_at)}
              </span>
            </div>
          </div>

          {/* Redemptions Log */}
          <div>
            <h4 className="text-xs font-bold text-text-dark uppercase tracking-wider mb-2">
              Users Who Claimed This Code ({codeDetail.redemptions?.length || 0})
            </h4>

            <div className="rounded-10 border border-border-default overflow-hidden max-h-56 overflow-y-auto">
              {(!codeDetail.redemptions || codeDetail.redemptions.length === 0) ? (
                <div className="py-8 text-center text-xs text-text-muted">
                  This code has not been redeemed by any user yet.
                </div>
              ) : (
                <table className="w-full text-left text-xs border-collapse">
                  <thead className="bg-surface-primary/60 border-b border-border-default text-[11px] font-semibold text-text-muted">
                    <tr>
                      <th className="px-3 py-2">User / Email</th>
                      <th className="px-3 py-2">Redeemed At</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-default">
                    {codeDetail.redemptions.map((red) => (
                      <tr key={red.id} className="hover:bg-surface-primary/40">
                        <td className="px-3 py-2.5">
                          <div className="flex flex-col">
                            <span className="font-medium text-text-dark flex items-center gap-1.5">
                              <Mail size={12} className="text-text-muted" />
                              {red.email || "No email"}
                            </span>
                            <span className="text-[10px] text-text-muted font-mono">{red.user_id}</span>
                          </div>
                        </td>
                        <td className="px-3 py-2.5 text-text-muted text-[11px]">
                          {formatDate(red.redeemed_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
};

export default CodeDetailModal;
