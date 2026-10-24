/**
 * Smart Farm System V.1 — shared design tokens
 * Derived from the existing reference screens (visual approximation).
 * Keep these tokens shared by Web and Mobile; do not create platform-specific
 * competing palettes without a design review.
 */
export const designTokens = {
  color: {
    brand: "#159447",
    brandStrong: "#08783A",
    brandSoft: "#E8F7ED",
    brandTint: "#F3FBF5",
    text: "#202923",
    textMuted: "#68736B",
    background: "#F5F8F5",
    surface: "#FFFFFF",
    surfaceRaised: "#FFFFFF",
    border: "#E3EAE4",
    divider: "#EDF1ED",
    success: "#168447",
    warning: "#D58A17",
    danger: "#D64545",
    info: "#2585C7",
    chartBlue: "#55A9E8",
    chartPurple: "#8A75D8",
  },
  typography: {
    fontFamily: 'Inter, "Noto Sans Thai", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    pageTitle: "1.5rem",
    sectionTitle: "1.125rem",
    body: "0.9375rem",
    caption: "0.8125rem",
    small: "0.75rem",
  },
  radius: {
    control: "10px",
    card: "16px",
    panel: "20px",
    pill: "999px",
  },
  spacing: {
    1: "4px",
    2: "8px",
    3: "12px",
    4: "16px",
    5: "20px",
    6: "24px",
    8: "32px",
    10: "40px",
    12: "48px",
  },
  shadow: {
    card: "0 3px 14px rgb(28 65 40 / 5%)",
    floating: "0 12px 32px rgb(28 65 40 / 10%)",
  },
} as const;
