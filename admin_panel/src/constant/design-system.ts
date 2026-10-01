/**
 * Design System — JS-Side Token Bridge
 *
 * This file provides runtime access to design tokens for contexts where
 * CSS/Tailwind classes can't be used directly (Recharts fills, Mantine
 * `styles` prop, dynamic `style` objects, etc.).
 *
 * Source of truth: CSS custom properties in index.css `:root`.
 * This file mirrors those values so they're available in TypeScript.
 *
 * For Tailwind class usage, prefer semantic utilities:
 *   bg-surface-primary, text-text-dark, border-border-default, etc.
 */

export const DESIGN_TOKENS = {
  // ─── Core Neutral & Surface Colors ───
  colors: {
    /** Page / muted surface background — Tailwind: bg-surface-primary */
    surfacePrimary: "var(--primary-background)",
    /** Card / elevated surface — Tailwind: bg-surface-card */
    surfaceCard: "var(--secondary-active-light)",
    /** Primary heading / body text — Tailwind: text-text-dark */
    textDark: "var(--secondary-active-dark)",
    /** Secondary / helper text — Tailwind: text-text-muted */
    textMuted: "var(--text-primary)",
    /** Default border — Tailwind: border-border-default */
    borderDefault: "var(--border-primary)",

    // Legacy aliases (for existing code that imports these)
    primaryBackground: "#F9F9F9",
    secondaryActiveDark: "#0A0A0A",
    secondaryActiveLight: "#FFFFFF",
    textPrimary: "#737373",
    borderPrimary: "#EBEBEB",

    // ─── Semantic & Accent Colors ───
    /** Total Users, AI Chats Today, Avg CTR */
    highlightTeal: "#01897E",
    /** Active Campaigns, MRR */
    highlightOrange: "#FF5A00",
    /** Total Campaigns, System Live Status indicator */
    highlightCyan: "#01C1B1",
    /** Avg ROAS / ROAB */
    highlightPink: "#F54397",
    /** Chart data point active indicator */
    graphMarker: "#401AFF",
    /** Validated / Active features (Green tick) */
    stateSuccess: "#00D33F",
    /** Deletion / Destructive action (Red trash) */
    stateDanger: "#D80027",
  },

  // ─── Radius Tokens ───
  radius: {
    r8: "8px",
    r10: "10px",
    r12: "12px",
    r16: "16px",
  },

  // ─── Dimensions ───
  dimensions: {
    navbar: { width: "270px", height: "918px" },
    topBar: { width: "1162px", height: "68px" },
    mainCanvas: { width: "1162px", height: "911px" },
  },

  // ─── Gradients & Layered Backgrounds ───
  gradients: {
    proTier:
      "linear-gradient(90deg, #0A0A0A 0%, #171717 49.52%, #0A0A0A 100%), linear-gradient(180deg, rgba(255, 255, 255, 0.16) 0%, rgba(255, 255, 255, 0) 100%)",
    standardTier: "#D1C8FF",
    basicTier: "#F8F8F8",
    subTopActive: `linear-gradient(0deg, #3B2A8C, #3B2A8C), linear-gradient(172.96deg, #FFE8F6 -81.48%, #FFFFFF 94.5%), linear-gradient(0deg, #FFFFFF, #FFFFFF), radial-gradient(93.39% 93.39% at 6.96% 6.61%, #313131 0%, #222222 100%), radial-gradient(74.13% 99.91% at 105.97% -82.55%, rgba(173, 160, 160, 0.92) 65.77%, rgba(34, 34, 34, 0.92) 100%)`,
    purchaseCta:
      "linear-gradient(90deg, #0A0A0A 0%, #171717 49.52%, #0A0A0A 100%), linear-gradient(180deg, rgba(255, 255, 255, 0.16) 0%, rgba(255, 255, 255, 0) 100%)",
  },
} as const;

export type DesignTokens = typeof DESIGN_TOKENS;
