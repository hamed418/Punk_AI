import { Box, SegmentedControl, useMantineColorScheme } from "@mantine/core"

const SegmentedThemeControl = () => {
    const { colorScheme, setColorScheme } = useMantineColorScheme();
    const theme = colorScheme === "auto" ? "system" : colorScheme;
    const setTheme = (t: "light" | "dark" | "system") => {
  const nextTheme = t === "system" ? "auto" : t;

  if ("startViewTransition" in document) {
    document.startViewTransition(() => {
      setColorScheme(nextTheme);
    });
  } else {
    setColorScheme(nextTheme);
  }
};

    return (
        <Box>
            <SegmentedControl
            size="sm"
                data={[
                    {
                        value: "light",
                        label: <img src="/light_icon.svg" alt="Light" width={16} height={16} />
                    },
                    {
                        value: "dark",
                        label: <img src="/dark_moon.svg" alt="Dark" width={16} height={16} />
                    }
                ]}
                value={theme}
                onChange={(value) => setTheme(value as "light" | "dark")}
            />
        </Box>
    )
}

export default SegmentedThemeControl