import "@mantine/core/styles.css";
import { MantineProvider } from "@mantine/core";
const MantineUIProviders = ({ children }: { children: React.ReactNode }) => {
  return (
    <MantineProvider defaultColorScheme="light" forceColorScheme="light">
      {children}
    </MantineProvider>
  );
};

export default MantineUIProviders;

