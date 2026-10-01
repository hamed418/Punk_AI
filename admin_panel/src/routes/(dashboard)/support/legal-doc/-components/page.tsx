import LegalDocOverviewCards from "./legal-doc-overview-cards";
import LegalDocList from "./legal-doc-list";

const LegalDocPage = () => {
  return (
    <div className="space-y-6">
      <LegalDocOverviewCards />
      <LegalDocList />
    </div>
  );
};

export default LegalDocPage;