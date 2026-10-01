import { MoreVertical } from "lucide-react";
import { Menu } from "@mantine/core";
import StatCard from "@/components/stat-card";
import { DESIGN_TOKENS } from "@/constant/design-system";
import { useAdminSupportTickets } from "@/hooks/api/useSupportApi";

const InquiryOverviewCards = () => {
  const { data: ticketsData, refetch } = useAdminSupportTickets({ limit: 100 });

  const total = ticketsData?.total ?? 0;
  const items = ticketsData?.data ?? [];

  const openTickets = items.filter((t) => t.status === "OPEN").length;
  const inProgressTickets = items.filter((t) => t.status === "IN_PROGRESS").length;
  const resolvedTickets = items.filter((t) => t.status === "RESOLVED" || t.status === "CLOSED").length;

  const resolutionRate =
    total > 0 ? ((resolvedTickets / total) * 100).toFixed(1) : "100";

  const stats = [
    {
      title: "Total inquiries",
      value: total.toLocaleString(),
      change: `${items.length} fetched`,
      isPositive: true,
      accentColor: DESIGN_TOKENS.colors.highlightCyan,
      description: "",
    },
    {
      title: "Open tickets",
      value: openTickets.toString(),
      change: `${inProgressTickets} in progress`,
      isPositive: openTickets === 0,
      accentColor: DESIGN_TOKENS.colors.highlightOrange,
      description: openTickets > 0 ? `${openTickets} need response` : "All caught up",
    },
    {
      title: "In progress",
      value: inProgressTickets.toString(),
      change: "Active tickets",
      isPositive: true,
      accentColor: DESIGN_TOKENS.colors.highlightTeal,
      description: "Under agent review",
    },
    {
      title: "Resolution rate",
      value: `${resolutionRate}%`,
      change: `${resolvedTickets} resolved`,
      isPositive: true,
      accentColor: DESIGN_TOKENS.colors.highlightPink,
      description: "",
    },
  ];

  return (
    <div className="space-y-3">
      {/* Section Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-base font-bold text-text-dark">Overview</h2>
        <Menu shadow="md" width={160} position="bottom-end">
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
            <Menu.Item onClick={() => refetch()}>Refresh Metrics</Menu.Item>
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

export default InquiryOverviewCards;
