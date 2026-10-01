import { ArrowDownCircle, ArrowUpCircle, MoreVertical } from "lucide-react";
import { Menu, Skeleton } from "@mantine/core";
import { useQueryClient } from "@tanstack/react-query";
import { DESIGN_TOKENS } from "@/constant/design-system";
import { useCampaignsStats, CAMPAIGNS_QUERY_KEY } from "@/hooks/api/useCampaignsApi";

const CampaignOverviewCards = () => {
  const queryClient = useQueryClient();
  const { data: stats, isLoading, isFetching } = useCampaignsStats();

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: CAMPAIGNS_QUERY_KEY.all });
  };

  const activePercent =
    stats && stats.total_campaigns > 0
      ? ((stats.active_campaigns / stats.total_campaigns) * 100).toFixed(0)
      : "0";

  const formatCurrency = (amount: number) => {
    if (amount >= 1_000_000) return `$${(amount / 1_000_000).toFixed(1)}M`;
    if (amount >= 1_000) return `$${(amount / 1_000).toFixed(1)}k`;
    return `$${amount.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
  };

  const cards = [
    {
      title: "Total campaigns",
      value: stats ? stats.total_campaigns.toLocaleString() : "—",
      descriptionSuffix: "All created campaigns",
      trend: stats && stats.new_this_week > 0
        ? {
            value: `+${stats.new_this_week}`,
            isPositive: true,
            color: DESIGN_TOKENS.colors.highlightCyan,
            label: "this week",
          }
        : undefined,
    },
    {
      title: "Active campaigns",
      value: stats ? stats.active_campaigns.toLocaleString() : "—",
      highlightPrefix: `${activePercent}%`,
      highlightColor: DESIGN_TOKENS.colors.highlightTeal,
      descriptionSuffix: "published or approved",
      trend: undefined,
    },
    {
      title: "Total ad spend",
      value: stats ? formatCurrency(stats.total_spend) : "—",
      highlightPrefix: undefined,
      highlightColor: undefined,
      descriptionSuffix: "across all users",
      trend: undefined,
    },
    {
      title: "Avg ROAS",
      value: stats && stats.avg_roas > 0 ? `${stats.avg_roas.toFixed(1)}x` : "—",
      highlightPrefix: stats && stats.avg_ctr > 0 ? `${stats.avg_ctr.toFixed(1)}% CTR` : undefined,
      highlightColor: DESIGN_TOKENS.colors.highlightPink,
      descriptionSuffix: stats && stats.avg_roas > 0 ? "return on ad spend" : (stats && stats.avg_ctr > 0 ? "average CTR" : "No conversion data"),
      trend: undefined,
    },
  ];

  return (
    <div className="space-y-3">
      {/* Section Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-bold text-text-dark">Overview</h2>
          {isFetching && !isLoading && (
            <span className="text-[11px] text-text-muted animate-pulse font-medium">
              Updating…
            </span>
          )}
        </div>
        <Menu shadow="md" width={150} position="bottom-end">
          <Menu.Target>
            <button
              type="button"
              className="p-1.5 rounded-8 text-text-muted hover:text-text-dark hover:bg-surface-primary border border-transparent hover:border-border-default transition-colors cursor-pointer"
              aria-label="Overview options"
            >
              <MoreVertical size={16} />
            </button>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item onClick={handleRefresh}>Refresh Metrics</Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </div>

      {/* Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
        {cards.map((card, index) => (
          <div
            key={index}
            className="rounded-12 border border-border-default p-0.5 bg-surface-primary flex flex-col transition-all duration-200 hover:shadow-xs"
          >
            {/* Top Section */}
            <div className="h-17.25 rounded-10 p-2 bg-surface-card flex flex-col justify-between">
              <span className="text-[13px] font-normal text-text-dark">
                {card.title}
              </span>
              {isLoading ? (
                <Skeleton height={28} width={80} radius="sm" />
              ) : (
                <span className="text-[24px] font-bold text-text-dark leading-tight tracking-tight">
                  {card.value}
                </span>
              )}
            </div>

            {/* Bottom Meta Section */}
            <div className="h-7.5 px-2 py-1.5 flex items-center justify-between">
              <span className="text-[12px] font-normal text-text-dark truncate">
                {card.highlightPrefix && (
                  <span
                    className="font-medium mr-1"
                    style={{ color: card.highlightColor }}
                  >
                    {card.highlightPrefix}
                  </span>
                )}
                {card.descriptionSuffix}
              </span>

              {card.trend && (
                <div
                  className="flex items-center gap-1 font-medium text-[12px] shrink-0"
                  style={{ color: card.trend.color }}
                >
                  {card.trend.isPositive ? (
                    <ArrowUpCircle size={14} strokeWidth={1.8} />
                  ) : (
                    <ArrowDownCircle size={14} strokeWidth={1.8} />
                  )}
                  <span>
                    {card.trend.value} {card.trend.label}
                  </span>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default CampaignOverviewCards;
