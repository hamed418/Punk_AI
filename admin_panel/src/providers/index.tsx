import { QueryProvider } from "./QueryProviders";
import MantineUIProvider from "./MantineUIProvider";
import { AuthProvider } from "@/context/AuthContext";

const Providers = ({ children }: { children: React.ReactNode }) => {
  return (
    <MantineUIProvider>
      <QueryProvider>
        <AuthProvider>
          {children}
        </AuthProvider>
      </QueryProvider>
    </MantineUIProvider>
  );
};

export default Providers;
