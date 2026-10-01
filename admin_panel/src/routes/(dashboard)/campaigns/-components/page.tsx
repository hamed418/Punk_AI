import CampaignOverviewCards from "./campaign-overview-cards";
import CampaignsTable from "./campaigns-table";

const AdCampaignsPage = () => {
    return (
        <div className="space-y-6">
            <CampaignOverviewCards />
            <CampaignsTable />
        </div>
    );
};

export default AdCampaignsPage;
