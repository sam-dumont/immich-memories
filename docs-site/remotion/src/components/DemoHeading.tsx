import React from "react";
import { Img, staticFile } from "remotion";
import { fontFamily } from "../fonts";
import { COLORS } from "../theme";

/** Outside the recreated app: explain the action without changing its UI. */
export const DemoHeading: React.FC<{ title: string; note?: string }> = ({ title, note }) => (
  <div style={{
    position: "absolute", inset: "0 0 auto", height: 84, padding: "0 160px",
    display: "flex", alignItems: "center", justifyContent: "space-between",
    background: COLORS.bg, color: COLORS.text, fontFamily,
  }}>
    <div style={{ fontSize: 32, fontWeight: 600, letterSpacing: -0.8 }}>{title}</div>
    <div style={{ display: "flex", alignItems: "center", gap: 12, color: COLORS.textSecondary }}>
      {note && <span style={{ fontSize: 20, marginRight: 22 }}>{note}</span>}
      <Img src={staticFile("logo.svg")} style={{ width: 34, height: 34 }} />
      <span style={{ fontSize: 20, fontWeight: 600 }}>Immich Memories</span>
    </div>
  </div>
);
