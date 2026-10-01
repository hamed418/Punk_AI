import { ArrowDownCircle, ArrowUpCircle, MoreVertical } from "lucide-react";
import { Menu, Skeleton } from "@mantine/core";
import { DESIGN_TOKENS } from "@/constant/design-system";
import { useUsersStats } from "@/hooks/api/useUsersApi";

const UserOverviewCards = () => {
  const { data: stats, isLoading } = useUsersStats();

  const payingPercent =
    stats && stats.total_users > 0
      ? ((stats.paying_users / stats.total_users) * 100).toFixed(1)
      : "0.0";

  const activePercent =
    stats && stats.total_users > 0
      ? ((stats.active_users / stats.total_users) * 100).toFixed(1)
      : "0.0";

  const suspendedPercent =
    stats && stats.total_users > 0
      ? ((stats.suspended_users / stats.total_users) * 100).toFixed(1)
      : "0.0";

  const cards = [
    {
      title: "Total Users",
      value: stats ? stats.total_users.toLocaleString() : "—",
      descriptionSuffix: "Registered accounts",
      trend: stats
        ? {
            value: `+${stats.new_this_month}`,
            isPositive: true,
            color: DESIGN_TOKENS.colors.highlightTeal,
            label: "this month",
          }
        : undefined,
    },
    {
      title: "Active (30d)",
      value: stats ? stats.active_users.toLocaleString() : "—",
      highlightPrefix: `${activePercent}%`,
      highlightColor: DESIGN_TOKENS.colors.highlightCyan,
      descriptionSuffix: " of total",
      trend: undefined,
    },
    {
      title: "Paying",
      value: stats ? stats.paying_users.toLocaleString() : "—",
      highlightPrefix: `${payingPercent}%`,
      highlightColor: DESIGN_TOKENS.colors.graphMarker,
      descriptionSuffix: " conversion",
      trend: undefined,
    },
    {
      title: "Suspended",
      value: stats ? stats.suspended_users.toLocaleString() : "—",
      highlightPrefix: stats && stats.suspended_users > 0 ? `${suspendedPercent}%` : undefined,
      highlightColor: DESIGN_TOKENS.colors.highlightPink,
      descriptionSuffix: stats && stats.suspended_users > 0 ? " of total" : "No suspended accounts",
      trend: undefined,
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
              className="p-1.5 rounded-8 text-text-muted hover:text-text-dark hover:bg-surface-primary border border-transparent hover:border-border-default transition-colors cursor-pointer"
              aria-label="Overview options"
            >
              <MoreVertical size={16} />
            </button>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item>Export Report</Menu.Item>
            <Menu.Item>Refresh Metrics</Menu.Item>
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

export default UserOverviewCards;
