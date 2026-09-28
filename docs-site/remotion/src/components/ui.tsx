import React from "react";
import { fontFamily } from "../fonts";
import { UI } from "../theme";
import { Mdi } from "./Mdi";

// The handful of @immich/ui components the client's pages are built from, with
// the classes they carry in web/node_modules/@immich/ui/dist.

type ButtonColor = "primary" | "secondary" | "danger";

const BUTTON_COLORS: Record<
  "filled" | "outline" | "ghost",
  Record<ButtonColor, React.CSSProperties>
> = {
  filled: {
    primary: {
      background: UI.primary,
      color: UI.light,
      border: `1px solid ${UI.primary}`,
    },
    secondary: {
      background: UI.dark,
      color: UI.light,
      border: `1px solid ${UI.dark}`,
    },
    danger: {
      background: UI.danger,
      color: UI.light,
      border: `1px solid ${UI.danger}`,
    },
  },
  outline: {
    primary: {
      background: UI.primaryTint,
      color: UI.primary,
      border: `1px solid ${UI.primary}`,
    },
    secondary: {
      background: UI.neutral100,
      color: UI.dark,
      border: `1px solid ${UI.dark}`,
    },
    danger: {
      background: UI.dangerTint,
      color: UI.danger,
      border: `1px solid ${UI.danger}`,
    },
  },
  ghost: {
    primary: {
      background: "transparent",
      color: UI.primary,
      border: "1px solid transparent",
    },
    secondary: {
      background: "transparent",
      color: UI.dark,
      border: "1px solid transparent",
    },
    danger: {
      background: "transparent",
      color: UI.danger,
      border: "1px solid transparent",
    },
  },
};

export const Button: React.FC<{
  children: React.ReactNode;
  icon?: string;
  variant?: "filled" | "outline" | "ghost";
  color?: ButtonColor;
  size?: "tiny" | "small" | "medium";
  round?: boolean;
  disabled?: boolean;
  pressed?: number;
  style?: React.CSSProperties;
}> = ({
  children,
  icon,
  variant = "filled",
  color = "primary",
  size = "medium",
  round,
  disabled,
  pressed = 0,
  style,
}) => (
  <div
    style={{
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      gap: 4,
      width: "fit-content",
      padding:
        size === "tiny"
          ? "4px 12px"
          : size === "small"
            ? "7px 16px"
            : "7px 20px",
      borderRadius: round ? 999 : size === "medium" ? 12 : 8,
      fontFamily,
      fontSize: 14,
      lineHeight: "20px",
      fontWeight: 500,
      whiteSpace: "nowrap",
      opacity: disabled ? 0.5 : 1,
      transform: `scale(${1 - pressed * 0.04})`,
      ...BUTTON_COLORS[variant][color],
      ...style,
    }}
  >
    {icon && <Mdi path={icon} size={18} />}
    {children}
  </div>
);

const BADGE_COLORS = {
  primary: {
    background: UI.primary100,
    color: UI.primary800,
    border: `1px solid ${UI.primary200}`,
  },
  secondary: {
    background: UI.neutral100,
    color: UI.neutral800,
    border: `1px solid ${UI.neutral200}`,
  },
  success: {
    background: UI.success100,
    color: UI.success700,
    border: `1px solid ${UI.success200}`,
  },
  info: {
    background: UI.info100,
    color: UI.info800,
    border: `1px solid ${UI.info200}`,
  },
  danger: {
    background: UI.danger100,
    color: UI.danger800,
    border: `1px solid ${UI.danger200}`,
  },
} as const;

export const Badge: React.FC<{
  children: React.ReactNode;
  color?: keyof typeof BADGE_COLORS;
  size?: "tiny" | "small";
}> = ({ children, color = "primary", size = "small" }) => (
  <span
    style={{
      display: "inline-flex",
      alignItems: "center",
      padding: size === "tiny" ? "1px 8px" : "2px 10px",
      borderRadius: size === "tiny" ? 6 : 8,
      fontSize: size === "tiny" ? 12 : 13,
      fontWeight: 500,
      whiteSpace: "nowrap",
      ...BADGE_COLORS[color],
    }}
  >
    {children}
  </span>
);

export const Heading: React.FC<{
  children: React.ReactNode;
  size: "large" | "small" | "tiny";
  style?: React.CSSProperties;
}> = ({ children, size, style }) => (
  <div
    style={{
      fontSize: size === "large" ? 36 : size === "small" ? 20 : 16,
      fontWeight: 700,
      lineHeight: 1,
      letterSpacing: "-0.025em",
      color: UI.dark,
      ...style,
    }}
  >
    {children}
  </div>
);

export const Muted: React.FC<{
  children: React.ReactNode;
  size?: number;
  style?: React.CSSProperties;
}> = ({ children, size = 14, style }) => (
  <div style={{ fontSize: size, color: UI.gray600, ...style }}>{children}</div>
);

/** A labelled field as the brief and the render panel draw one: label over a bordered box. */
export const Field: React.FC<{
  label: string;
  value: React.ReactNode;
  select?: boolean;
  focused?: boolean;
  caret?: boolean;
  style?: React.CSSProperties;
}> = ({ label, value, select, focused, caret, style }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 4, ...style }}>
    <span style={{ fontSize: 14, fontWeight: 500, color: UI.dark }}>
      {label}
    </span>
    <div
      style={{
        display: "flex",
        alignItems: "center",
        height: 42,
        padding: "0 12px",
        borderRadius: 8,
        border: `1px solid ${focused ? UI.primary : UI.gray300}`,
        boxShadow: focused ? `0 0 0 1px ${UI.primary}` : "none",
        background: UI.light,
        fontSize: 16,
        color: UI.dark,
      }}
    >
      <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden" }}>
        {value}
        {caret && (
          <span
            style={{
              display: "inline-block",
              width: 1.5,
              height: 18,
              marginLeft: 1,
              verticalAlign: "-3px",
              background: UI.dark,
            }}
          />
        )}
      </span>
      {select && (
        <svg
          viewBox="0 0 24 24"
          width={18}
          height={18}
          style={{ fill: UI.dark }}
        >
          <path d="M7,10L12,15L17,10H7Z" />
        </svg>
      )}
    </div>
  </div>
);

/** A native checkbox and its label, as the client's forms leave them. */
export const Check: React.FC<{ label: string; checked?: boolean }> = ({
  label,
  checked,
}) => (
  <div
    style={{
      display: "flex",
      alignItems: "center",
      gap: 8,
      fontSize: 14,
      color: UI.dark,
    }}
  >
    <div
      style={{
        width: 14,
        height: 14,
        borderRadius: 3,
        border: `1px solid ${checked ? UI.primary : "#767676"}`,
        background: checked ? UI.primary : UI.light,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {checked && (
        <svg
          viewBox="0 0 24 24"
          width={12}
          height={12}
          style={{ fill: UI.light }}
        >
          <path d="M9,20.42L2.79,14.21L5.62,11.38L9,14.77L18.88,4.88L21.71,7.71L9,20.42Z" />
        </svg>
      )}
    </div>
    {label}
  </div>
);

/** The grey command line the brief and the progress panel print. */
export const CommandLine: React.FC<{
  children: React.ReactNode;
  /** The brief's line breaks anywhere (break-all); the job panel's truncates. */
  wrap?: boolean;
  style?: React.CSSProperties;
}> = ({ children, wrap, style }) => (
  <div
    style={{
      background: UI.gray100,
      borderRadius: 6,
      padding: "8px 12px",
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
      fontSize: 12,
      lineHeight: "16px",
      color: UI.dark,
      whiteSpace: wrap ? "normal" : "nowrap",
      wordBreak: wrap ? "break-all" : undefined,
      overflow: "hidden",
      textOverflow: wrap ? undefined : "ellipsis",
      ...style,
    }}
  >
    {children}
  </div>
);

/** @immich/ui's ProgressBar: a 16 px rounded track with a primary fill and its stop dot. */
export const ProgressBar: React.FC<{ fraction: number }> = ({ fraction }) => (
  <div
    style={{
      position: "relative",
      height: 16,
      borderRadius: 999,
      background: UI.neutral100,
      overflow: "hidden",
    }}
  >
    <div
      style={{
        height: "100%",
        width: `${Math.max(0, Math.min(1, fraction)) * 100}%`,
        minWidth: fraction > 0 ? 16 : 0,
        borderRadius: 999,
        background: UI.primary,
      }}
    />
    <div
      style={{
        position: "absolute",
        top: 5,
        right: 5,
        width: 6,
        height: 6,
        borderRadius: 999,
        background: UI.primary,
        opacity: 0.7,
      }}
    />
  </div>
);

/** A bordered rounded-2xl card, the client's one container. */
export const Card: React.FC<{
  children: React.ReactNode;
  style?: React.CSSProperties;
}> = ({ children, style }) => (
  <div
    style={{
      border: `1px solid ${UI.gray200}`,
      borderRadius: 16,
      padding: 20,
      background: UI.light,
      ...style,
    }}
  >
    {children}
  </div>
);
