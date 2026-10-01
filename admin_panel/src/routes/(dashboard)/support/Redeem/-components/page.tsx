import { useState } from "react";
import { Tag, KeyRound, Sparkles } from "lucide-react";
import { SegmentedControl } from "@mantine/core";
import RedeemOverviewCards from "./redeem-overview-cards";
import CouponTab from "./coupon-tab";
import CodeTab from "./code-tab";
import { useCoupons, useRedeemCodes } from "@/hooks/api/useRedeem";

type RedeemTabType = "coupon" | "code";

export const RedeemPage = () => {
  const [activeTab, setActiveTab] = useState<RedeemTabType>("coupon");
  const { data: couponsData } = useCoupons({ limit: 1 });
  const { data: codesData } = useRedeemCodes({ limit: 1 });

  const totalCoupons = couponsData?.total ?? 0;
  const totalCodes = codesData?.total ?? 0;

  return (
    <div className="space-y-6">
      {/* Overview Cards */}
      <RedeemOverviewCards />

      {/* Main Mode Navigation Tabs (Coupon vs Code) */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border-default pb-3">
        <SegmentedControl
          value={activeTab}
          onChange={(val) => setActiveTab(val as RedeemTabType)}
          data={[
            {
              value: "coupon",
              label: (
                <div
                  className={`flex items-center gap-2 text-xs font-semibold transition-colors ${
                    activeTab === "coupon"
                      ? "text-white"
                      : "text-text-muted hover:text-text-dark"
                  }`}
                >
                  <Tag size={15} />
                  <span>Coupons</span>
                  <span
                    className={`text-[11px] px-1.5 py-0.2 rounded-full font-medium transition-colors ${
                      activeTab === "coupon"
                        ? "bg-white/20 text-white"
                        : "bg-surface-primary text-text-muted border border-border-default"
                    }`}
                  >
                    {totalCoupons}
                  </span>
                </div>
              ),
            },
            {
              value: "code",
              label: (
                <div
                  className={`flex items-center gap-2 text-xs font-semibold transition-colors ${
                    activeTab === "code"
                      ? "text-white"
                      : "text-text-muted hover:text-text-dark"
                  }`}
                >
                  <KeyRound size={15} />
                  <span>Redeem Codes</span>
                  <span
                    className={`text-[11px] px-1.5 py-0.2 rounded-full font-medium transition-colors ${
                      activeTab === "code"
                        ? "bg-emerald-400/20 text-emerald-300"
                        : "bg-emerald-500/10 text-emerald-600 border border-emerald-500/20"
                    }`}
                  >
                    {totalCodes}
                  </span>
                </div>
              ),
            },
          ]}
          withItemsBorders={false}
          styles={{
            root: {
              backgroundColor: "var(--color-surface-card)",
              border: "1px solid var(--color-border-default)",
              padding: "4px",
              borderRadius: "12px",
              boxShadow: "0 1px 2px 0 rgba(0, 0, 0, 0.05)",
            },
            indicator: {
              borderRadius: "8px",
              background: "#0A0A0A",
              boxShadow:
                "0 4px 9.6px 0 rgba(255, 255, 255, 0.25) inset, 0 1px 2px 0 rgba(0, 0, 0, 0.05)",
            },
            control: {
              border: "none !important",
            },
            label: {
              padding: "8px 16px",
              fontSize: "12px",
              fontWeight: 600,
              cursor: "pointer",
            },
          }}
        />

        <div className="text-xs text-text-muted hidden md:flex items-center gap-1.5">
          <Sparkles size={13} className="text-amber-500" />
          <span>
            {activeTab === "coupon"
              ? "Percentage & fixed promo discount rules for checkouts"
              : "Direct subscription & gift redeemable voucher codes"}
          </span>
        </div>
      </div>

      {/* Render Active Manager */}
      {activeTab === "coupon" ? <CouponTab /> : <CodeTab />}
    </div>
  );
};

export default RedeemPage;
