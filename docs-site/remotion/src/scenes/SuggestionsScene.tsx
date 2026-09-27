import React from "react";
import {
  AbsoluteFill,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { mdiPlayOutline, mdiRefresh } from "@mdi/js";
import { COLORS, UI } from "../theme";
import { WindowFrame, onScreen } from "../components/WindowFrame";
import { AppShell, MAIN_X, MAIN_Y } from "../components/AppShell";
import { AnimatedCursor } from "../components/AnimatedCursor";
import { Button, Heading } from "../components/ui";
import { POOL_TOTAL } from "../fixture";

/**
 * web/src/routes/suggestions/+page.svelte: what automation would make next, by
 * the rules `auto suggest` uses. The first candidate is the month the demo
 * just cut by hand; checking it runs the rules without rendering anything.
 * The cast (Kit, Robin) is the fixture library's.
 */

const CANDIDATES = [
  {
    reason: `${POOL_TOTAL} assets, most recent month`,
    people: "",
    meta: `Monthly Highlights · 2024-06-01 – 2024-06-30 · Pictures: ${POOL_TOTAL}`,
  },
  {
    reason: "1st most featured person, 18 assets",
    people: "Kit",
    meta: "Person Spotlight · 2023-01-01 – 2023-12-31 · Pictures: 18",
  },
  {
    reason: "2nd most featured person, 14 assets",
    people: "Robin",
    meta: "Person Spotlight · 2023-01-01 – 2023-12-31 · Pictures: 14",
  },
  {
    reason: `${POOL_TOTAL} assets across the year, never generated`,
    people: "",
    meta: `Year in Review · 2024-01-01 – 2024-12-31 · Pictures: ${POOL_TOTAL}`,
  },
];

const CHECK = 40;
const SETTLED = CHECK + 14;
// The first card's "Check eligibility", before the attempt's own box pushes the cards down:
// the heading block (64), the gap, then the card's padding, reason, meta and key lines.
const CHECK_XY = onScreen(
  MAIN_X + 87,
  MAIN_Y + 64 + 24 + 16 + 28 + 8 + 20 + 8 + 16 + 8 + 18,
);

const Card: React.FC<{
  candidate: (typeof CANDIDATES)[number];
  reveal: number;
}> = ({ candidate, reveal }) => (
  <div
    style={{
      border: `1px solid ${UI.gray200}`,
      borderRadius: 16,
      padding: 16,
      display: "flex",
      flexDirection: "column",
      gap: 8,
      opacity: reveal,
      transform: `translateY(${(1 - reveal) * 12}px)`,
    }}
  >
    <div style={{ fontSize: 18, lineHeight: "28px", fontWeight: 600 }}>
      {candidate.reason}
    </div>
    {candidate.people && (
      <div style={{ fontWeight: 500 }}>{candidate.people}</div>
    )}
    <div
      style={{
        fontSize: 14,
        lineHeight: "20px",
        color: UI.gray600,
        fontVariantNumeric: "tabular-nums",
      }}
    >
      {candidate.meta}
    </div>
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        fontSize: 12,
        lineHeight: "16px",
      }}
    >
      <svg
        viewBox="0 0 24 24"
        width={10}
        height={10}
        style={{ fill: "currentColor" }}
      >
        <path d="M8,5V19L19,12L8,5Z" />
      </svg>
      Candidate key
    </div>
    <div style={{ display: "flex", gap: 8 }}>
      <Button size="small" variant="outline">
        Check eligibility
      </Button>
      <Button size="small" icon={mdiPlayOutline}>
        Run this suggestion
      </Button>
    </div>
  </div>
);

type Props = { bassIntensity?: number };

export const SuggestionsScene: React.FC<Props> = ({ bassIntensity }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const reveal = (delay: number) =>
    spring({ frame, fps, config: { damping: 20, stiffness: 140 }, delay });
  const checked = frame >= CHECK;

  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      <WindowFrame
        path="/app/suggestions"
        bassIntensity={bassIntensity}
        enter={false}
      >
        <AppShell active="Suggestions">
          <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
            <div
              style={{
                display: "flex",
                alignItems: "flex-end",
                justifyContent: "space-between",
                gap: 12,
              }}
            >
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <Heading size="large">Suggestions</Heading>
                <div
                  style={{
                    fontSize: 16,
                    lineHeight: "24px",
                    color: UI.gray600,
                  }}
                >
                  What automation would make next, the same list `auto suggest`
                  prints. Run one as `auto run` would, or check it first without
                  rendering.
                </div>
              </div>
              <Button size="small" variant="outline" icon={mdiRefresh}>
                Refresh suggestions
              </Button>
            </div>
            {checked && (
              <div
                style={{
                  border: `1px solid ${UI.gray200}`,
                  borderRadius: 16,
                  padding: 16,
                  fontSize: 16,
                }}
              >
                {frame < SETTLED
                  ? "Running on the server: starting. It continues if you leave this page."
                  : "Eligible. No video was generated."}
              </div>
            )}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 16,
              }}
            >
              {CANDIDATES.map((candidate, i) => (
                <Card
                  key={candidate.reason}
                  candidate={candidate}
                  reveal={reveal(6 + i * 5)}
                />
              ))}
            </div>
          </div>
        </AppShell>
      </WindowFrame>
      <AnimatedCursor
        steps={[
          { frame: 28, ...CHECK_XY },
          { frame: CHECK, ...CHECK_XY, click: true },
        ]}
      />
    </AbsoluteFill>
  );
};
