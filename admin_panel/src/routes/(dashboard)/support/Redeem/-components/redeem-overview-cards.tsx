import { MoreVertical } from "lucide-react";
import { Menu } from "@mantine/core";
import StatCard from "@/components/stat-card";
import { DESIGN_TOKENS } from "@/constant/design-system";
import { useCoupons, useRedeemCodes, useCouponRedemptions, COUPON_QUERY_KEYS, CODE_QUERY_KEYS } from "@/hooks/api/useRedeem";
import { useQueryClient } from "@tanstack/react-query";

export const RedeemOverviewCards = () => {
  const queryClient = useQueryClient();
  const { data: couponsData } = useCoupons({ limit: 100 });
  const { data: codesData } = useRedeemCodes({ limit: 100 });
  const { data: redemptionsData } = useCouponRedemptions({ limit: 100 });

  const couponsList = couponsData?.data ?? [];
  const codesList = codesData?.data ?? [];

  const totalCoupons = couponsData?.total ?? couponsList.length;
  const activeCoupons = couponsList.filter((c) => c.is_active).length;
  const inactiveCoupons = couponsList.filter((c) => !c.is_active).length;

  const totalCodes = codesData?.total ?? codesList.length;
  const activeCodes = codesList.filter((c) => c.is_active).length;
  const inactiveCodes = codesList.filter((c) => !c.is_active).length;

  const totalRedemptions = redemptionsData?.total ?? redemptionsData?.data?.length ?? 0;
  const singleUseCodes = codesList.filter((c) => c.is_single).length;
  const multiUseCodes = codesList.filter((c) => !c.is_single).length;

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: COUPON_QUERY_KEYS.all });
    queryClient.invalidateQueries({ queryKey: CODE_QUERY_KEYS.all });
  };

  const stats = [
    {
      title: "Total Coupons",
      value: String(totalCoupons),
      change: `${activeCoupons} Active · ${inactiveCoupons} Inactive`,
      isPositive: true,
      accentColor: DESIGN_TOKENS.colors.highlightCyan,
      description: "Promotional discount rules",
    },
    {
      title: "Coupon Redemptions",
      value: String(totalRedemptions),
      change: "Processed checkouts",
      isPositive: true,
      accentColor: DESIGN_TOKENS.colors.highlightTeal,
      description: "Customer usage history",
    },
    {
      title: "Total Redeem Codes",
      value: String(totalCodes),
      change: `${activeCodes} Active · ${inactiveCodes} Inactive`,
      isPositive: true,
      accentColor: DESIGN_TOKENS.colors.highlightOrange,
      description: "Generated reward codes",
    },
    {
      title: "Code Types",
      value: `${singleUseCodes} / ${multiUseCodes}`,
      change: "Single vs Multi use",
      isPositive: true,
      accentColor: DESIGN_TOKENS.colors.highlightPink,
      description: "Redemption constraint mode",
    },
  ];

  return (
    <div className="space-y-3">
      {/* Section Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-base font-bold text-text-dark">Overview</h2>
        <Menu shadow="md" width={140} position="bottom-end">
          <Menu.Target>
            <button
              type="button"
              className="p-1.5 rounded-[8px] text-text-muted hover:text-text-dark hover:bg-surface-primary border border-transparent hover:border-border-default transition-colors cursor-pointer"
              aria-label="Overview options"
            >
              <MoreVertical size={16} />
            </button>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item onClick={handleRefresh}>Refresh Data</Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </div>

      {/* Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
        {stats.map((stat, index) => (
          <StatCard key={index} {...stat} />
        ))}
      </div>
    </div>
  );
};

export default RedeemOverviewCards;
