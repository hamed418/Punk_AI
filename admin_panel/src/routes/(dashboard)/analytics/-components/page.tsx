import CampaignActivity from "./campaign-activity";
import OverviewCard from "./overview-card";

const AnalyticsPage = () => {
    return (
        <div className="space-y-6">
            <OverviewCard />
            <CampaignActivity />
        </div>
    );
};

export default AnalyticsPage;