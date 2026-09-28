import React from "react";

/** A Material Design Icon from @mdi/js, drawn the way the client draws one: a 24-unit path, filled with the text colour. */
export const Mdi: React.FC<{
  path: string;
  size?: number;
  color?: string;
  style?: React.CSSProperties;
}> = ({ path, size = 20, color = "currentColor", style }) => (
  <svg
    viewBox="0 0 24 24"
    width={size}
    height={size}
    style={{ flexShrink: 0, fill: color, ...style }}
    aria-hidden
  >
    <path d={path} />
  </svg>
);
