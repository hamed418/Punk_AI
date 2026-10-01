import { MoreVertical } from "lucide-react";
import { Menu } from "@mantine/core";
import StatCard from "@/components/stat-card";
import { DESIGN_TOKENS } from "@/constant/design-system";
import { useLegalDocs, LEGAL_DOC_QUERY_KEYS } from "@/hooks/api/useLegalDoc";
import { useQueryClient } from "@tanstack/react-query";

export const LegalDocOverviewCards = () => {
  const queryClient = useQueryClient();
  const { data: legalDocs = [] } = useLegalDocs();

  const totalDocs = legalDocs.length;
  const activeDocs = legalDocs.filter((d) => d.is_active).length;
  const inactiveDocs = totalDocs - activeDocs;
  const termsCount = legalDocs.filter((d) => d.doc_type === "Terms of Service").length;
  const activeTermsCount = legalDocs.filter(
    (d) => d.doc_type === "Terms of Service" && d.is_active
  ).length;
  const privacyCount = legalDocs.filter((d) => d.doc_type === "Privacy Policy").length;
  const activePrivacyCount = legalDocs.filter(
    (d) => d.doc_type === "Privacy Policy" && d.is_active
  ).length;

  const uniqueLanguages = new Set(legalDocs.map((d) => d.language)).size;

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: LEGAL_DOC_QUERY_KEYS.all });
  };

  const stats = [
    {
      title: "Total Legal Documents",
      value: String(totalDocs),
      change: `${activeDocs} Active · ${inactiveDocs} Inactive`,
      isPositive: true,
      accentColor: DESIGN_TOKENS.colors.highlightCyan,
      description: "Published and draft releases",
    },
    {
      title: "Terms of Service",
      value: String(termsCount),
      change: `${activeTermsCount} Active · ${termsCount - activeTermsCount} Inactive`,
      isPositive: true,
      accentColor: DESIGN_TOKENS.colors.highlightTeal,
      description: "Service agreement revisions",
    },
    {
      title: "Privacy Policy",
      value: String(privacyCount),
      change: `${activePrivacyCount} Active · ${privacyCount - activePrivacyCount} Inactive`,
      isPositive: true,
      accentColor: DESIGN_TOKENS.colors.highlightOrange,
      description: "Data protection revisions",
    },
    {
      title: "Supported Languages",
      value: String(uniqueLanguages || 2),
      change: "English & French configured",
      isPositive: true,
      accentColor: DESIGN_TOKENS.colors.highlightPink,
      description: "Multi-locale localization",
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

export default LegalDocOverviewCards;
