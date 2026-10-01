import React from "react";
import StatCard from "@/components/stat-card";
import { DESIGN_TOKENS } from "@/constant/design-system";
import { useUsersStats } from "@/hooks/api/useUsersApi";
import { usePlans } from "@/hooks/api/useSubscriptionApi";

const SubscriptionOverviewCard: React.FC = () => {
  const { data: stats, isLoading: statsLoading } = useUsersStats();
  const { data: plans, isLoading: plansLoading } = usePlans();

  const payingUsers = stats?.paying_users ?? 0;
  const totalUsers = stats?.total_users ?? 0;
  const conversionRate = totalUsers > 0 ? ((payingUsers / totalUsers) * 100).toFixed(1) : "0.0";
  const newThisMonth = stats?.new_this_month ?? 0;

  // Compute average plan value
  const validPlans = plans && plans.length > 0 ? plans : [];
  const avgPlanPrice =
    validPlans.length > 0
      ? (
          validPlans.reduce((acc, p) => acc + (typeof p.amount === "number" ? p.amount : parseFloat(p.amount) || 0), 0) /
          validPlans.length
        ).toFixed(2)
      : "29.00";

  const cards = [
    {
      title: "Paying subscribers",
      value: statsLoading ? "..." : payingUsers.toLocaleString(),
      change: `+${newThisMonth}`,
      isPositive: true,
      accentColor: DESIGN_TOKENS.colors.highlightCyan,
      description: "Active subscribers",
      showArrow: true,
    },
    {
      title: "Subscribed conversion",
      value: statsLoading ? "..." : `${conversionRate}%`,
      change: `${payingUsers}/${totalUsers}`,
      isPositive: true,
      accentColor: DESIGN_TOKENS.colors.highlightCyan,
      description: "Of total user base",
      showArrow: false,
    },
    {
      title: "Avg plan value",
      value: plansLoading ? "..." : `$${avgPlanPrice}`,
      subValue: "configured",
      change: `${validPlans.length} plans`,
      isPositive: true,
      accentColor: DESIGN_TOKENS.colors.highlightCyan,
      description: "Across all tiers",
      showArrow: false,
    },
    {
      title: "Active plans",
      value: plansLoading ? "..." : String(validPlans.length),
      change: "Live",
      isPositive: true,
      accentColor: DESIGN_TOKENS.colors.highlightCyan,
      description: "Available in pricing",
      showArrow: false,
    },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
      {cards.map((stat, index) => (
        <StatCard key={index} {...stat} />
      ))}
    </div>
  );
};

export default SubscriptionOverviewCard;

