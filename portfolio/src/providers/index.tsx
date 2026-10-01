import MantineUIProviders from "./MantineUIProviders";

const Providers = ({ children }: { children: React.ReactNode }) => {
  return <MantineUIProviders>{children}</MantineUIProviders>;
};

export default Providers;
