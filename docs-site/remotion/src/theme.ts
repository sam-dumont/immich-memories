// The stage the app window floats on, the title card and the terminal.
export const COLORS = {
  bg: "#09090b",
  text: "#dbdbdb",
  textSecondary: "#d4d4d4",
  primary: "#4250af",
  terminalTitleBar: "#161b22",
} as const;

// The web client's own palette, light theme: @immich/ui's tokens
// (web/node_modules/@immich/ui/dist/theme/default.css) and the Tailwind grays
// the client's pages name (border-gray-200, text-gray-600, bg-gray-100).
export const UI = {
  primary: "#4250af",
  primaryTint: "rgba(66, 80, 175, 0.10)",
  primary100: "oklch(0.897 0.033 281.96)",
  primary200: "oklch(0.787 0.07 281.03)",
  primary800: "oklch(0.272 0.088 272.94)",
  light: "#ffffff",
  dark: "oklch(36% 0 17)",
  gray100: "oklch(96.7% 0.003 264.542)",
  gray200: "oklch(92.8% 0.006 264.531)",
  gray300: "oklch(87.2% 0.01 258.338)",
  gray600: "oklch(44.6% 0.03 256.802)",
  neutral100: "oklch(97% 0 0)",
  neutral200: "oklch(92.2% 0 0)",
  neutral800: "oklch(26.9% 0 0)",
  success: "oklch(0.708 0.204 147.56)",
  success100: "oklch(0.937 0.109 148.66)",
  success200: "oklch(0.863 0.249 147.5)",
  success700: "oklch(0.476 0.136 147.69)",
  danger: "oklch(0.633 0.24 28.79)",
  dangerTint: "oklch(0.633 0.24 28.79 / 0.10)",
  danger100: "oklch(0.926 0.034 17.84)",
  danger200: "oklch(0.853 0.074 19.77)",
  danger800: "oklch(0.342 0.131 28.79)",
  info100: "oklch(0.93 0.035 252)",
  info200: "oklch(0.86 0.07 252)",
  info800: "oklch(0.35 0.1 253)",
} as const;

export const FPS = 30;

// The whole demo, in frames. Scene lengths live in Composition.tsx's D map.
export const TOTAL_FRAMES = 1486;

// Music fades out over the last 5 seconds.
export const MUSIC_FADE_START = TOTAL_FRAMES - 150;
