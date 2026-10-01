import {
	ColorSchemeScript,
	type CSSVariablesResolver,
	colorsTuple,
	createTheme,
	DEFAULT_THEME,
	MantineProvider,
	mergeMantineTheme,
	virtualColor,
} from "@mantine/core";
import { ModalsProvider } from "@mantine/modals";
import { Notifications } from "@mantine/notifications";
import { NavigationProgress } from "@mantine/nprogress";
import type React from "react";
import { DESIGN_TOKENS } from "@/constant/design-system";

import "@mantine/charts/styles.css";
import "@mantine/core/styles.css";
import "@mantine/dates/styles.css";
import "@mantine/dropzone/styles.css";
import "@mantine/notifications/styles.css";
import "@mantine/nprogress/styles.css";
import "@mantine/spotlight/styles.css";
import "@mantine/tiptap/styles.css";

const cssResolver: CSSVariablesResolver = () => ({
	variables: {
		// 2.1 Core Neutral & Surface Tokens (Universal CSS Variables)
		"--primary-background": DESIGN_TOKENS.colors.primaryBackground,
		"--secondary-active-dark": DESIGN_TOKENS.colors.secondaryActiveDark,
		"--secondary-active-light": DESIGN_TOKENS.colors.secondaryActiveLight,
		"--text-primary": DESIGN_TOKENS.colors.textPrimary,
		"--border-primary": DESIGN_TOKENS.colors.borderPrimary,

		// 2.2 Semantic & Accent Tokens
		"--highlight-teal": DESIGN_TOKENS.colors.highlightTeal,
		"--highlight-orange": DESIGN_TOKENS.colors.highlightOrange,
		"--highlight-cyan": DESIGN_TOKENS.colors.highlightCyan,
		"--highlight-pink": DESIGN_TOKENS.colors.highlightPink,
		"--graph-marker": DESIGN_TOKENS.colors.graphMarker,
		"--state-success": DESIGN_TOKENS.colors.stateSuccess,
		"--state-danger": DESIGN_TOKENS.colors.stateDanger,

		// 2.3 Radius Tokens
		"--radius-8": DESIGN_TOKENS.radius.r8,
		"--radius-10": DESIGN_TOKENS.radius.r10,
		"--radius-12": DESIGN_TOKENS.radius.r12,
		"--radius-16": DESIGN_TOKENS.radius.r16,

		// 5. Master Dimensions
		"--navbar-width": "270px",
		"--navbar-height": "918px",
		"--topbar-width": "1162px",
		"--topbar-height": "68px",
		"--main-canvas-width": "1162px",
		"--main-canvas-height": "911px",
	},
	light: {
		// Mantine-specific color variable mappings
		"--mantine-color-body": DESIGN_TOKENS.colors.secondaryActiveLight,
		"--mantine-color-text": DESIGN_TOKENS.colors.secondaryActiveDark,
		"--mantine-color-primary-background": DESIGN_TOKENS.colors.primaryBackground,
		"--mantine-color-secondary-active-dark": DESIGN_TOKENS.colors.secondaryActiveDark,
		"--mantine-color-secondary-active-light": DESIGN_TOKENS.colors.secondaryActiveLight,
		"--mantine-color-text-primary": DESIGN_TOKENS.colors.textPrimary,
		"--mantine-color-border-primary": DESIGN_TOKENS.colors.borderPrimary,

		"--mantine-color-highlight-teal": DESIGN_TOKENS.colors.highlightTeal,
		"--mantine-color-highlight-orange": DESIGN_TOKENS.colors.highlightOrange,
		"--mantine-color-highlight-cyan": DESIGN_TOKENS.colors.highlightCyan,
		"--mantine-color-highlight-pink": DESIGN_TOKENS.colors.highlightPink,
		"--mantine-color-graph-marker": DESIGN_TOKENS.colors.graphMarker,
		"--mantine-color-state-success": DESIGN_TOKENS.colors.stateSuccess,
		"--mantine-color-state-danger": DESIGN_TOKENS.colors.stateDanger,

		// Backward-compatible mappings
		"--mantine-color-bg-primary": DESIGN_TOKENS.colors.primaryBackground,
		"--mantine-color-bg-secondary": "#F3F3F3",
		"--mantine-color-divider": DESIGN_TOKENS.colors.borderPrimary,
		"--mantine-color-underline": "#8D8D8D",
		"--mantine-color-text-secondary": DESIGN_TOKENS.colors.textPrimary,
		"--mantine-color-widget-primary": DESIGN_TOKENS.colors.secondaryActiveLight,
		"--mantine-color-widget-secondary": DESIGN_TOKENS.colors.primaryBackground,
		"--mantine-color-widget-stroke": DESIGN_TOKENS.colors.borderPrimary,
		"--mantine-color-button-primary": DESIGN_TOKENS.colors.secondaryActiveDark,
		"--mantine-color-button-secondary": DESIGN_TOKENS.colors.secondaryActiveLight,
		"--mantine-color-button-stroke": DESIGN_TOKENS.colors.borderPrimary,
	},
	dark: {
		"--mantine-color-body": "#171717",
		"--mantine-color-text": "#FFFFFF",
		"--mantine-color-primary-background": DESIGN_TOKENS.colors.secondaryActiveDark,
		"--mantine-color-secondary-active-dark": DESIGN_TOKENS.colors.secondaryActiveLight,
		"--mantine-color-secondary-active-light": "#171717",
		"--mantine-color-text-primary": "#A3A3A3",
		"--mantine-color-border-primary": "#262626",

		"--mantine-color-highlight-teal": DESIGN_TOKENS.colors.highlightTeal,
		"--mantine-color-highlight-orange": DESIGN_TOKENS.colors.highlightOrange,
		"--mantine-color-highlight-cyan": DESIGN_TOKENS.colors.highlightCyan,
		"--mantine-color-highlight-pink": DESIGN_TOKENS.colors.highlightPink,
		"--mantine-color-graph-marker": DESIGN_TOKENS.colors.graphMarker,
		"--mantine-color-state-success": DESIGN_TOKENS.colors.stateSuccess,
		"--mantine-color-state-danger": DESIGN_TOKENS.colors.stateDanger,

		// Backward-compatible mappings
		"--mantine-color-bg-primary": "#171717",
		"--mantine-color-bg-secondary": "#262626",
		"--mantine-color-divider": "#262626",
		"--mantine-color-underline": "#8D8D8D",
		"--mantine-color-text-secondary": "#A3A3A3",
		"--mantine-color-widget-primary": "#171717",
		"--mantine-color-widget-secondary": "#262626",
		"--mantine-color-widget-stroke": "#262626",
		"--mantine-color-button-primary": DESIGN_TOKENS.colors.secondaryActiveLight,
		"--mantine-color-button-secondary": "#171717",
		"--mantine-color-button-stroke": "#262626",
	},
});

const MantineUIProvider = ({ children }: { children: React.ReactNode }) => {
	const themeOverride = createTheme({
		black: DESIGN_TOKENS.colors.secondaryActiveDark,
		white: DESIGN_TOKENS.colors.secondaryActiveLight,
		radius: {
			xs: DESIGN_TOKENS.radius.r8,
			sm: DESIGN_TOKENS.radius.r8,
			md: DESIGN_TOKENS.radius.r12,
			lg: DESIGN_TOKENS.radius.r16,
			xl: "20px",
		},
		colors: {
			highlightTeal: colorsTuple(DESIGN_TOKENS.colors.highlightTeal),
			highlightOrange: colorsTuple(DESIGN_TOKENS.colors.highlightOrange),
			highlightCyan: colorsTuple(DESIGN_TOKENS.colors.highlightCyan),
			highlightPink: colorsTuple(DESIGN_TOKENS.colors.highlightPink),
			graphMarker: colorsTuple(DESIGN_TOKENS.colors.graphMarker),
			stateSuccess: colorsTuple(DESIGN_TOKENS.colors.stateSuccess),
			stateDanger: colorsTuple(DESIGN_TOKENS.colors.stateDanger),
			primaryBackground: colorsTuple(DESIGN_TOKENS.colors.primaryBackground),
			secondaryActiveDark: colorsTuple(DESIGN_TOKENS.colors.secondaryActiveDark),
			secondaryActiveLight: colorsTuple(DESIGN_TOKENS.colors.secondaryActiveLight),
			textPrimary: colorsTuple(DESIGN_TOKENS.colors.textPrimary),
			borderPrimary: colorsTuple(DESIGN_TOKENS.colors.borderPrimary),
			primaryLight: colorsTuple(DESIGN_TOKENS.colors.secondaryActiveDark),
			primaryDark: colorsTuple(DESIGN_TOKENS.colors.secondaryActiveLight),
			primary: virtualColor({
				name: "primary",
				dark: "primaryDark",
				light: "primaryLight",
			}),
		},
		breakpoints: {
			xs: "30em",
			sm: "40em",
			md: "48em",
			lg: "64em",
			xl: "80em",
			xxl: "90em",
		},
		other: {
			tokens: DESIGN_TOKENS,
		},
		primaryColor: "primary",
	});

	const theme = mergeMantineTheme(DEFAULT_THEME, themeOverride);

	return (
		<>
			<ColorSchemeScript defaultColorScheme="light" />
			<MantineProvider
				theme={theme}
				defaultColorScheme="light"
				cssVariablesResolver={cssResolver}
			>
				<ModalsProvider>
					<Notifications />
					<NavigationProgress />
					{children}
				</ModalsProvider>
			</MantineProvider>
		</>
	);
};

export default MantineUIProvider;
