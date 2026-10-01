import React, { useState, useMemo } from "react";
import { Edit2, Trash2, CheckCircle2, MoreVertical, Layers, Plus, Sparkles } from "lucide-react";
import { Menu, Skeleton } from "@mantine/core";
import type { Plan } from "@/types/subscription";
import { parsePlanData } from "./subscription-utils";

interface SubscriptionPlanListProps {
  plans: Plan[];
  isLoading: boolean;
  openCreateForm: () => void;
  openEditForm: (plan: Plan) => void;
  onDeleteRequest: (plan: Plan) => void;
}

const SubscriptionPlanList: React.FC<SubscriptionPlanListProps> = ({
  plans,
  isLoading,
  openCreateForm,
  openEditForm,
  onDeleteRequest,
}) => {
  const [filter, setFilter] = useState<"all" | "subscription" | "token_pack">("all");

  const filteredPlans = useMemo(() => {
    if (filter === "all") return plans;
    if (filter === "subscription") return plans.filter(p => p.type === "SUBSCRIPTION" || !p.type);
    if (filter === "token_pack") return plans.filter(p => p.type === "TOKEN_PACK");
    return plans;
  }, [plans, filter]);

  const sortedPlans = useMemo(() => {
    return [...filteredPlans].sort((a, b) => {
      const aIsPro = (a.name?.toLowerCase().includes("pro") ?? false) ? -1 : 1;
      const bIsPro = (b.name?.toLowerCase().includes("pro") ?? false) ? -1 : 1;
      if (aIsPro !== bIsPro) return aIsPro - bIsPro;
      const dateA = new Date(a.created_at || 0).getTime();
      const dateB = new Date(b.created_at || 0).getTime();
      return dateA - dateB;
    });
  }, [filteredPlans]);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6">
        {/* Skeleton Filters */}
        <div className="flex gap-2">
          <Skeleton height={36} width={80} radius="xl" />
          <Skeleton height={36} width={100} radius="xl" />
          <Skeleton height={36} width={100} radius="xl" />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="rounded-2xl border border-border-default bg-surface-card p-5 space-y-4 shadow-sm">
              <div className="flex justify-between items-start">
                <Skeleton height={24} width="50%" />
                <Skeleton height={24} width={24} circle />
              </div>
              <Skeleton height={40} width="60%" />
              <Skeleton height={56} radius="md" />
              <div className="space-y-2 pt-4">
                <Skeleton height={14} />
                <Skeleton height={14} width="90%" />
                <Skeleton height={14} width="75%" />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 w-full">
      {/* Filters Section */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => setFilter("all")}
          className={`px-4 py-2 rounded-full text-[13px] font-semibold transition-all duration-200 ${filter === "all"
              ? "bg-black text-white shadow-md transform scale-[1.02]"
              : "bg-surface-card text-text-muted hover:text-text-dark border border-border-default hover:bg-surface-primary"
            }`}
        >
          All Plans
        </button>
        <button
          onClick={() => setFilter("subscription")}
          className={`px-4 py-2 rounded-full text-[13px] font-semibold transition-all duration-200 ${filter === "subscription"
              ? "bg-black text-white shadow-md transform scale-[1.02]"
              : "bg-surface-card text-text-muted hover:text-text-dark border border-border-default hover:bg-surface-primary"
            }`}
        >
          Subscriptions
        </button>
        <button
          onClick={() => setFilter("token_pack")}
          className={`px-4 py-2 rounded-full text-[13px] font-semibold transition-all duration-200 ${filter === "token_pack"
              ? "bg-black text-white shadow-md transform scale-[1.02]"
              : "bg-surface-card text-text-muted hover:text-text-dark border border-border-default hover:bg-surface-primary"
            }`}
        >
          Token Packs
        </button>
      </div>

      {sortedPlans.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 gap-4 border border-dashed border-border-default rounded-2xl bg-surface-primary/50 text-center p-8">
          <div className="p-4 rounded-full bg-surface-card border border-border-default text-text-muted shadow-sm">
            <Layers size={28} />
          </div>
          <div className="space-y-1">
            <h3 className="text-base font-bold text-text-dark">No plans found</h3>
            <p className="text-[13px] text-text-muted max-w-sm mx-auto leading-relaxed">
              {filter === "all"
                ? "Configure subscription tiers or token packs to allow users to purchase token allocations."
                : `You don't have any ${filter.replace('_', ' ')}s yet.`}
            </p>
          </div>
          <button
            type="button"
            onClick={openCreateForm}
            className="mt-4 btn-gradient-black text-[13px] font-medium px-5 py-2.5 rounded-xl flex items-center gap-2 cursor-pointer shadow-md hover:shadow-lg transition-all"
          >
            <Plus size={16} className="text-white" />
            <span>Create New Plan</span>
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {sortedPlans.map((plan, index) => {
            const parsed = parsePlanData(plan);
            const isDark = (plan.name?.toLowerCase().includes("pro") ?? false) || (index === 0 && !plans.some(p => p.name?.toLowerCase().includes("pro")));
            const numericAmount = typeof plan.amount === "number" ? plan.amount : parseFloat(plan.amount) || 0;
            const isTokenPack = plan.type === "TOKEN_PACK";

            return (
              <div
                key={plan.id}
                className={`w-full flex flex-col rounded-[24px] overflow-hidden transition-all duration-300 ease-in-out group relative border ${isDark
                    ? "border-transparent bg-gray-900 shadow-[0_20px_40px_-15px_rgba(0,0,0,0.3)] hover:shadow-[0_25px_50px_-12px_rgba(0,0,0,0.4)] hover:-translate-y-1"
                    : "border-border-default bg-surface-card shadow-[0_8px_30px_-12px_rgba(0,0,0,0.06)] hover:shadow-[0_20px_40px_-15px_rgba(0,0,0,0.1)] hover:-translate-y-1 hover:border-gray-300"
                  }`}
                style={isDark ? {
                  background: "linear-gradient(145deg, #1A1A1A 0%, #0A0A0A 100%)",
                } : {}}
              >
                {/* Dark mode glowing border effect */}
                {isDark && (
                  <div className="absolute inset-0 rounded-[24px] p-[1px] bg-gradient-to-br from-white/20 via-transparent to-white/5 pointer-events-none -z-10" />
                )}

                {/* Card Header & Price Section */}
                <div className={`p-6 pb-5 flex flex-col gap-4 relative z-10 ${isDark ? "text-white" : "text-text-dark"}`}>
                  <div className="flex items-start justify-between">
                    <div className="flex flex-col gap-1.5">
                      <div className="flex items-center gap-2">
                        <h3 className="text-[20px] font-extrabold tracking-tight">
                          {plan.name || parsed.name}
                        </h3>
                        {isDark && <Sparkles size={14} className="text-yellow-400" />}
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        {parsed.status === "published" && (
                          <span className={`text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full ${isDark
                              ? "bg-white/10 text-white/90 border border-white/20"
                              : "bg-emerald-50 text-emerald-600 border border-emerald-200"
                            }`}>
                            Published
                          </span>
                        )}
                        <span className={`text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full ${isDark
                            ? "bg-purple-500/20 text-purple-200 border border-purple-500/30"
                            : "bg-purple-50 text-purple-600 border border-purple-200"
                          }`}>
                          {isTokenPack ? "Token Pack" : "Subscription"}
                        </span>
                      </div>
                    </div>

                    <Menu shadow="md" width={140} position="bottom-end">
                      <Menu.Target>
                        <button
                          type="button"
                          className={`p-1.5 rounded-lg transition-colors cursor-pointer ${isDark ? "text-white/50 hover:text-white hover:bg-white/10" : "text-text-muted hover:text-text-dark hover:bg-surface-primary"
                            }`}
                          aria-label="Plan actions"
                        >
                          <MoreVertical size={16} />
                        </button>
                      </Menu.Target>
                      <Menu.Dropdown>
                        <Menu.Item
                          leftSection={<Edit2 size={14} />}
                          onClick={() => openEditForm(plan)}
                        >
                          Edit Plan
                        </Menu.Item>
                        <Menu.Item
                          leftSection={<Trash2 size={14} />}
                          color="red"
                          onClick={() => onDeleteRequest(plan)}
                        >
                          Delete Plan
                        </Menu.Item>
                      </Menu.Dropdown>
                    </Menu>
                  </div>

                  <div className="flex items-baseline gap-1 mt-2">
                    <span className="text-[36px] font-black leading-none tracking-tighter">
                      ${numericAmount}
                    </span>
                    <span className={`text-[13px] font-medium ${isDark ? "text-white/60" : "text-text-muted"}`}>
                      {plan.interval ? `/${plan.interval}` : "one-time"}
                    </span>
                  </div>

                  <p className={`text-[13px] leading-relaxed line-clamp-2 mt-1 ${isDark ? "text-white/70" : "text-text-muted"}`}>
                    {parsed.shortDescription || "No description provided."}
                  </p>
                </div>

                {/* Tokens Highlight Box */}
                <div className={`mx-6 mb-4 p-4 rounded-2xl flex items-center gap-3 ${isDark
                    ? "bg-white/5 border border-white/10"
                    : "bg-surface-primary border border-border-default/60"
                  }`}>
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 ${isDark ? "bg-white text-black shadow-[0_0_15px_rgba(255,255,255,0.2)]" : "bg-black text-white shadow-md"
                    }`}>
                    <Layers className="w-5 h-5" />
                  </div>
                  <div>
                    <div className={`text-[18px] font-black leading-tight ${isDark ? "text-white" : "text-text-dark"}`}>
                      {plan.total_token_can_use?.toLocaleString() || "0"}
                    </div>
                    <div className={`text-[12px] font-medium ${isDark ? "text-white/60" : "text-text-muted"}`}>
                      Total Tokens
                    </div>
                  </div>
                </div>

                {/* Features List */}
                <div className={`flex-1 px-6 pb-6 pt-2 flex flex-col gap-4 relative z-10 ${isDark ? "border-t border-white/10" : "border-t border-border-default/50"
                  }`}>
                  <h4 className={`text-[12px] font-bold uppercase tracking-wider mt-4 ${isDark ? "text-white/80" : "text-text-dark"
                    }`}>
                    What's included
                  </h4>

                  {parsed.features.length > 0 ? (
                    <ul className="flex flex-col gap-3">
                      {parsed.features.map((feat, i) => (
                        <li key={i} className="flex items-start gap-2.5">
                          <CheckCircle2
                            size={16}
                            strokeWidth={2.5}
                            className={`shrink-0 mt-0.5 ${isDark ? "text-green-400" : "text-green-500"}`}
                          />
                          <span className={`text-[13px] font-medium leading-snug ${isDark ? "text-white/80" : "text-text-muted"}`}>
                            {feat}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className={`text-[13px] italic ${isDark ? "text-white/40" : "text-text-muted"}`}>
                      No features specified.
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default SubscriptionPlanList;
