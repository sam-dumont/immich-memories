import React from "react";
import {
  mdiCogOutline,
  mdiHistory,
  mdiLightbulbOutline,
  mdiMovieOpenStarOutline,
  mdiWeatherSunny,
} from "@mdi/js";
import { UI } from "../theme";
import { Mdi } from "./Mdi";

/**
 * web/src/routes/+layout.svelte: @immich/ui's AppShell with the app's own mark
 * (the movie-open-star icon and its name, never Immich's logo), the language
 * select, demo mode and the theme switch in the header, and four destinations
 * in the sidebar.
 */

export type NavPage = "Memory" | "Suggestions" | "Runs" | "Settings";

const NAVIGATION: { title: NavPage; icon: string }[] = [
  { title: "Memory", icon: mdiMovieOpenStarOutline },
  { title: "Suggestions", icon: mdiLightbulbOutline },
  { title: "Runs", icon: mdiHistory },
  { title: "Settings", icon: mdiCogOutline },
];

export const HEADER_H = 72;
export const SIDEBAR_W = 257;
/** Where the page's content starts inside the window's content area (main's px-8 pt-6). */
export const MAIN_X = SIDEBAR_W + 32;
export const MAIN_Y = HEADER_H + 24;

type Props = {
  active: NavPage;
  children: React.ReactNode;
  /** How far the page has scrolled, in px. */
  scroll?: number;
};

export const AppShell: React.FC<Props> = ({ active, children, scroll = 0 }) => (
  <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
    <div
      style={{
        height: HEADER_H,
        flexShrink: 0,
        borderBottom: `1px solid ${UI.neutral200}`,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 16px",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontSize: 18,
          fontWeight: 600,
          color: UI.primary,
        }}
      >
        <Mdi path={mdiMovieOpenStarOutline} size={28} />
        Immich Memories
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            border: `1px solid ${UI.gray300}`,
            borderRadius: 8,
            padding: "4px 8px",
            fontSize: 14,
          }}
        >
          Automatic (browser)
          <svg
            viewBox="0 0 24 24"
            width={16}
            height={16}
            style={{ fill: UI.dark }}
          >
            <path d="M7,10L12,15L17,10H7Z" />
          </svg>
        </div>
        <div style={{ padding: 8, color: UI.primary, display: "flex" }}>
          <Mdi path={mdiWeatherSunny} size={22} />
        </div>
      </div>
    </div>

    <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      <div
        style={{
          width: SIDEBAR_W,
          flexShrink: 0,
          borderRight: `1px solid ${UI.neutral200}`,
          padding: 12,
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        {NAVIGATION.map((item) => {
          const isActive = item.title === active;
          return (
            <div
              key={item.title}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 16,
                padding: "12px 0 12px 20px",
                borderRadius: "0 999px 999px 0",
                background: isActive ? UI.primaryTint : "transparent",
                color: isActive ? UI.primary : UI.dark,
                fontSize: 14,
                fontWeight: 500,
              }}
            >
              <Mdi path={item.icon} size={22} />
              {item.title}
            </div>
          );
        })}
      </div>

      <div
        style={{
          flex: 1,
          minWidth: 0,
          overflow: "hidden",
          position: "relative",
        }}
      >
        <div
          style={{
            padding: "24px 32px 24px",
            transform: `translateY(${-scroll}px)`,
          }}
        >
          {children}
        </div>
      </div>
    </div>
  </div>
);
