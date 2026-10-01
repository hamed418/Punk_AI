import InquiryOverviewCards from "./inquiry-overview-cards";
import InquiryTable from "./inquiry-table";

const InquiryPage = () => {
  return (
    <div className="space-y-6">
      <InquiryOverviewCards />
      <InquiryTable />
    </div>
  );
};

export default InquiryPage;
