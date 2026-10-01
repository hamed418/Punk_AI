import UserOverviewCards from "./user-overview-cards";
import UsersTable from "./users-table";

const UsersPage = () => {
  return (
    <div className="space-y-6">
      <UserOverviewCards />
      <UsersTable />
    </div>
  );
};

export default UsersPage;
