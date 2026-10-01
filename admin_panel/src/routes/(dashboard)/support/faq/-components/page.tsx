import { useState } from "react";
import { Globe, HelpCircle, Sparkles } from "lucide-react";
import { SegmentedControl } from "@mantine/core";
import FaqOverviewCards from "./faq-overview-cards";
import FaqList from "./faq-list";
import LandingFaqList from "./landing-faq-list";
import { useFaqs, useLandingFaqs } from "@/hooks/api/useFaqApi";

type FaqTabType = "app" | "landing";

const FaqPage = () => {
  const [activeTab, setActiveTab] = useState<FaqTabType>("app");
  const { data: appFaqsData } = useFaqs({ limit: 100 });
  const { data: landingFaqsData } = useLandingFaqs({ limit: 100 });

  const totalAppFaqs = appFaqsData?.total ?? appFaqsData?.data?.length ?? 0;
  const totalLandingFaqs = landingFaqsData?.total ?? landingFaqsData?.data?.length ?? 0;

  return (
    <div className="space-y-6">
      <FaqOverviewCards />

      {/* Main Mode Navigation Tabs (App FAQ vs Landing FAQ) */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border-default pb-3">
        <SegmentedControl
          value={activeTab}
          onChange={(val) => setActiveTab(val as FaqTabType)}
          data={[
            {
              value: "app",
              label: (
                <div
                  className={`flex items-center gap-2 text-xs font-semibold transition-colors ${
                    activeTab === "app"
                      ? "text-white"
                      : "text-text-muted hover:text-text-dark"
                  }`}
                >
                  <HelpCircle size={15} />
                  <span>App & Support FAQ</span>
                  <span
                    className={`text-[11px] px-1.5 py-0.2 rounded-full font-medium transition-colors ${
                      activeTab === "app"
                        ? "bg-white/20 text-white"
                        : "bg-surface-primary text-text-muted border border-border-default"
                    }`}
                  >
                    {totalAppFaqs}
                  </span>
                </div>
              ),
            },
            {
              value: "landing",
              label: (
                <div
                  className={`flex items-center gap-2 text-xs font-semibold transition-colors ${
                    activeTab === "landing"
                      ? "text-white"
                      : "text-text-muted hover:text-text-dark"
                  }`}
                >
                  <Globe size={15} />
                  <span>Landing Page FAQ</span>
                  <span
                    className={`text-[11px] px-1.5 py-0.2 rounded-full font-medium transition-colors ${
                      activeTab === "landing"
                        ? "bg-emerald-400/20 text-emerald-300"
                        : "bg-emerald-500/10 text-emerald-600 border border-emerald-500/20"
                    }`}
                  >
                    {totalLandingFaqs}
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
            {activeTab === "app"
              ? "Categorized articles for logged-in users & help desk"
              : "Direct public marketing FAQs displayed on punkai.io"}
          </span>
        </div>
      </div>

      {/* Render active FAQ manager */}
      {activeTab === "app" ? <FaqList /> : <LandingFaqList />}
    </div>
  );
};

export default FaqPage;

