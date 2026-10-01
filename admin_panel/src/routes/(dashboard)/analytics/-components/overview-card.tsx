import { Skeleton } from "@mantine/core";
import { ArrowDownCircle, ArrowUpCircle } from "lucide-react";
import { DESIGN_TOKENS } from "@/constant/design-system";
import { useAnalyticsOverview } from "@/hooks/api/useAnalyticsApi";

const OverviewCard = () => {
  const { data, isLoading } = useAnalyticsOverview();

  const formatCurrency = (amount: number) => {
    if (amount >= 1_000_000) return `$${(amount / 1_000_000).toFixed(1)}M`;
    if (amount >= 1_000) return `$${(amount / 1_000).toFixed(1)}k`;
    return `$${amount.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
  };

  const cards = [
    {
      title: "Total users",
      value: data ? data.total_users.toLocaleString() : "—",
      change: data?.users_change || "+6.3%",
      isPositive: data?.users_is_positive ?? true,
      accentColor: DESIGN_TOKENS.colors.highlightTeal,
      description: "Registered accounts",
    },
    {
      title: "Active campaigns",
      value: data ? data.active_campaigns.toLocaleString() : "—",
      change: data?.campaigns_change || "+9 this week",
      isPositive: data?.campaigns_is_positive ?? true,
      accentColor: DESIGN_TOKENS.colors.highlightOrange,
      description: "Published or approved",
    },
    {
      title: "AI chats today",
      value: data ? data.ai_chats_today.toLocaleString() : "—",
      change: data?.chats_change || "+12%",
      isPositive: data?.chats_is_positive ?? true,
      accentColor: DESIGN_TOKENS.colors.highlightTeal,
      description: "Across all conversations",
    },
    {
      title: "MRR",
      value: data ? formatCurrency(data.mrr) : "—",
      change: data?.mrr_change || "+8.5%",
      isPositive: data?.mrr_is_positive ?? true,
      accentColor: DESIGN_TOKENS.colors.highlightOrange,
      description: "Monthly active subscriptions",
    },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
      {cards.map((card, index) => (
        <div
          key={index}
          className="rounded-12 border border-border-default p-0.5 bg-surface-primary flex flex-col transition-all duration-200 hover:shadow-xs"
        >
          {/* Top Primary Section */}
          <div className="h-17.25 rounded-10 p-2 bg-surface-card flex flex-col justify-between">
            <span className="text-[13px] font-normal text-text-dark">
              {card.title}
            </span>
            <div className="flex items-baseline gap-1.5 min-w-0">
              {isLoading ? (
                <Skeleton height={28} width={80} radius="sm" />
              ) : (
                <span className="text-[24px] font-bold text-text-dark leading-tight tracking-tight">
                  {card.value}
                </span>
              )}
            </div>
          </div>

          {/* Bottom Meta Section */}
          <div className="h-7.5 px-2 py-1.5 flex items-center justify-between">
            <span className="text-[12px] font-normal text-text-muted truncate">
              {card.description}
            </span>

            {card.change && (
              <div
                className="flex items-center gap-1 font-medium text-[12px] shrink-0"
                style={{ color: card.accentColor }}
              >
                {card.isPositive ? (
                  <ArrowUpCircle size={14} strokeWidth={1.8} />
                ) : (
                  <ArrowDownCircle size={14} strokeWidth={1.8} />
                )}
                <span>{card.change}</span>
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
};

export default OverviewCard;
