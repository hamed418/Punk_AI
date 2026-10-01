import { MoreVertical } from "lucide-react";
import { Menu } from "@mantine/core";
import StatCard from "@/components/stat-card";
import { DESIGN_TOKENS } from "@/constant/design-system";
import { useFaqCategories, useFaqs, useLandingFaqs, FAQ_QUERY_KEYS } from "@/hooks/api/useFaqApi";
import { useQueryClient } from "@tanstack/react-query";

const FaqOverviewCards = () => {
  const queryClient = useQueryClient();
  const { data: categoriesData } = useFaqCategories();
  const { data: faqsData } = useFaqs({ limit: 100 });
  const { data: landingFaqsData } = useLandingFaqs({ limit: 100 });

  const totalFaqs = faqsData?.total ?? faqsData?.data?.length ?? 0;
  const totalCategories = categoriesData?.total ?? categoriesData?.data?.length ?? 0;
  const totalLandingFaqs = landingFaqsData?.total ?? landingFaqsData?.data?.length ?? 0;
  const activeLandingFaqs = landingFaqsData?.data?.filter((f) => f.is_active).length ?? 0;

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: FAQ_QUERY_KEYS.all });
  };

  const stats = [
    {
      title: "App & Support FAQs",
      value: String(totalFaqs),
      change: `${totalCategories} categories`,
      isPositive: true,
      accentColor: DESIGN_TOKENS.colors.highlightCyan,
      description: "",
    },
    {
      title: "Landing Page FAQs",
      value: String(totalLandingFaqs),
      change: `${activeLandingFaqs} live on punkai.io`,
      isPositive: true,
      accentColor: DESIGN_TOKENS.colors.highlightTeal,
      description: "",
    },
    {
      title: "Helpful Rate",
      value: "94.2%",
      change: "+3.8% positive feedback",
      isPositive: true,
      accentColor: DESIGN_TOKENS.colors.highlightOrange,
      description: "",
    },
    {
      title: "Deflected Tickets",
      value: "1,240",
      change: "+15.2% automated",
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

export default FaqOverviewCards;

