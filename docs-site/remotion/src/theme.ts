// The stage the app window floats on, the title card and the terminal.
export const COLORS = {
  bg: "var(--demo-stage)",
  text: "var(--immich-ui-dark)",
  textSecondary: "var(--demo-muted)",
  primary: "var(--immich-ui-primary-500)",
  terminalTitleBar: "#161b22",
} as const;

// The same Immich UI tokens as the docs, resolved under the composition's theme.
export const UI = {
  primary: "var(--immich-ui-primary-500)",
  primaryTint: "color-mix(in srgb, var(--immich-ui-primary-500) 10%, transparent)",
  primary100: "var(--immich-ui-primary-100)",
  primary200: "var(--immich-ui-primary-200)",
  primary800: "var(--immich-ui-primary-800)",
  light: "var(--immich-ui-light)",
  dark: "var(--immich-ui-dark)",
  gray100: "var(--demo-gray-100)",
  gray200: "var(--demo-gray-200)",
  gray300: "var(--demo-gray-300)",
  gray600: "var(--demo-muted)",
  neutral100: "var(--demo-gray-100)",
  neutral200: "var(--demo-gray-200)",
  neutral800: "var(--demo-neutral-800)",
  success: "var(--immich-ui-success-500)",
  success100: "var(--immich-ui-success-100)",
  success200: "var(--immich-ui-success-200)",
  success700: "var(--immich-ui-success-700)",
  danger: "var(--immich-ui-danger-500)",
  dangerTint: "color-mix(in srgb, var(--immich-ui-danger-500) 10%, transparent)",
  danger100: "var(--immich-ui-danger-100)",
  danger200: "var(--immich-ui-danger-200)",
  danger800: "var(--immich-ui-danger-800)",
  info100: "var(--immich-ui-info-100)",
  info200: "var(--immich-ui-info-200)",
  info800: "var(--immich-ui-info-800)",
} as const;

export const FPS = 30;

// The whole demo, in frames. Scene lengths live in Composition.tsx's D map.
export const TOTAL_FRAMES = 1486;

// Music fades out over the last 5 seconds.
export const MUSIC_FADE_START = TOTAL_FRAMES - 150;
