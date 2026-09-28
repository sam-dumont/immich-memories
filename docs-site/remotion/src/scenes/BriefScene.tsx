import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { mdiMovieOpenPlayOutline } from "@mdi/js";
import { COLORS, UI } from "../theme";
import { WindowFrame, onScreen } from "../components/WindowFrame";
import { AppShell, MAIN_X, MAIN_Y } from "../components/AppShell";
import { AnimatedCursor } from "../components/AnimatedCursor";
import { Button, CommandLine, Field, Heading } from "../components/ui";

/**
 * web/src/routes/create/+page.svelte: the memory type as chips, the fields
 * that type reads, the people, the folded "Length and pictures", then the
 * command the server reads the brief as, and Cut. The fixture library is one
 * household's June 2024, so the brief asks for that month.
 */

// The page's own order (FIELDS in create/+page.svelte), in the reader's words (labels.ts).
const TYPES = [
  "Year in Review",
  "Season",
  "Person Spotlight",
  "Multi-Person",
  "Monthly Highlights",
  "On This Day",
  "Album",
  "Trip",
  "Holiday",
  "Special day",
  "Custom date range",
];
// The fixture library's cast (tests/e2e/fake_library.py), nobody's family.
const PEOPLE = ["Robin", "Charlie", "Kit"];

const PICK_TYPE = 45;
const CLICK_YEAR = 80;
const TYPE_YEAR = [86, 98];
const CLICK_MONTH = 112;
const TYPE_MONTH = 118;
export const CLICK_CUT = 150;

// The page asks the server for the command 150 ms after the brief changes.
const DEBOUNCE = 5;

const CONTENT_W = 768;
const CHIP_W = (CONTENT_W - 16) / 3;
const CHIP_H = 38;
const CHIPS_Y = MAIN_Y + 140;
const FIELDS_Y = CHIPS_Y + 4 * CHIP_H + 3 * 8 + 24;
const FIELD_W = (CONTENT_W - 16) / 2;
const CUT_Y = FIELDS_Y + 66 + 24 + 82 + 24 + 54 + 24 + 48 + 8;

const PICK_XY = onScreen(
  MAIN_X + CHIP_W + 8 + CHIP_W / 2,
  CHIPS_Y + CHIP_H + 8 + CHIP_H / 2,
);
const YEAR_XY = onScreen(MAIN_X + 120, FIELDS_Y + 45);
const MONTH_XY = onScreen(MAIN_X + FIELD_W + 16 + 120, FIELDS_Y + 45);
const CUT_XY = onScreen(MAIN_X + 44, CUT_Y + 18);

const cursorSteps = [
  { frame: 30, ...PICK_XY },
  { frame: PICK_TYPE, ...PICK_XY, click: true },
  { frame: CLICK_YEAR, ...YEAR_XY, click: true },
  { frame: CLICK_MONTH, ...MONTH_XY, click: true },
  { frame: CLICK_CUT, ...CUT_XY, click: true },
];

const command = (monthly: boolean, year: string, month: string) =>
  [
    "immich-memories generate",
    `--memory-type=${monthly ? "monthly_highlights" : "year_in_review"}`,
    ...(year ? [`--year=${year}`] : []),
    ...(monthly && month ? [`--month=${month}`] : []),
    "--include-photos --include-live-photos --no-render",
  ].join(" ");

/** What the brief holds at this frame, and what the page's command line says. */
const briefAt = (frame: number) => {
  const monthly = frame >= PICK_TYPE;
  const yearTyped = Math.floor(
    interpolate(frame, TYPE_YEAR, [0, 4], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }),
  );
  const year = frame < CLICK_YEAR ? "2026" : "2024".slice(0, yearTyped);
  const month = frame < CLICK_MONTH ? "8" : frame < TYPE_MONTH ? "" : "6";
  return { monthly, year, month };
};

const Chip: React.FC<{ label: string; chosen: boolean }> = ({
  label,
  chosen,
}) => (
  <div
    style={{
      height: CHIP_H,
      boxSizing: "border-box",
      display: "flex",
      alignItems: "center",
      padding: "0 12px",
      borderRadius: 12,
      fontSize: 14,
      border: `1px solid ${chosen ? UI.primary : UI.gray200}`,
      background: chosen ? UI.primaryTint : "transparent",
      fontWeight: chosen ? 500 : 400,
    }}
  >
    {label}
  </div>
);

const Legend: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div
    style={{
      fontSize: 14,
      lineHeight: "20px",
      fontWeight: 600,
      marginBottom: 8,
    }}
  >
    {children}
  </div>
);

const Disclosure: React.FC<{
  children: React.ReactNode;
  muted?: boolean;
  bold?: boolean;
}> = ({ children, muted, bold }) => (
  <div
    style={{
      display: "flex",
      alignItems: "center",
      gap: 6,
      fontSize: 14,
      lineHeight: "20px",
      fontWeight: bold ? 600 : 400,
      color: muted ? UI.gray600 : UI.dark,
    }}
  >
    <svg
      viewBox="0 0 24 24"
      width={12}
      height={12}
      style={{ fill: "currentColor" }}
    >
      <path d="M8,5V19L19,12L8,5Z" />
    </svg>
    {children}
  </div>
);

/** The brief form, frozen at `frame`; the cut scene draws it no more. */
const BriefForm: React.FC<{ frame: number }> = ({ frame }) => {
  const shown = briefAt(frame);
  // The command line lags the brief by the page's debounce.
  const asked = briefAt(Math.max(0, frame - DEBOUNCE));
  const cutPress = interpolate(
    frame,
    [CLICK_CUT, CLICK_CUT + 4, CLICK_CUT + 8],
    [0, 1, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    },
  );

  return (
    <div
      style={{
        width: CONTENT_W,
        display: "flex",
        flexDirection: "column",
        gap: 24,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <Heading size="large">New memory</Heading>
        <div style={{ fontSize: 16, lineHeight: "24px", color: UI.gray600 }}>
          Choose what the film covers. The cut is made the way the command below
          makes it; you review it before anything renders.
        </div>
      </div>

      <div>
        <Legend>Memory type</Legend>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 8,
          }}
        >
          {TYPES.map((type) => (
            <Chip
              key={type}
              label={type}
              chosen={
                type ===
                (shown.monthly ? "Monthly Highlights" : "Year in Review")
              }
            />
          ))}
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: `${FIELD_W}px ${FIELD_W}px`,
          gap: 16,
        }}
      >
        <Field
          label="Year"
          value={shown.year}
          focused={frame >= CLICK_YEAR && frame < CLICK_MONTH}
          caret={
            frame >= CLICK_YEAR &&
            frame < CLICK_MONTH &&
            Math.floor(frame / 8) % 2 === 0
          }
        />
        {shown.monthly && (
          <Field
            label="Month"
            value={shown.month}
            focused={frame >= CLICK_MONTH && frame < CLICK_CUT}
            caret={
              frame >= CLICK_MONTH &&
              frame < CLICK_CUT &&
              Math.floor(frame / 8) % 2 === 0
            }
          />
        )}
      </div>

      <div>
        <Legend>Only with (optional)</Legend>
        <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
          {PEOPLE.map((name) => (
            <div
              key={name}
              style={{
                border: `1px solid ${UI.gray200}`,
                borderRadius: 999,
                padding: "4px 12px",
                fontSize: 14,
                lineHeight: "20px",
              }}
            >
              {name}
            </div>
          ))}
        </div>
        <Disclosure muted>Grouped condition</Disclosure>
      </div>

      <div
        style={{
          border: `1px solid ${UI.gray200}`,
          borderRadius: 12,
          padding: 16,
        }}
      >
        <Disclosure bold>Length and pictures</Disclosure>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <CommandLine wrap>
          {command(asked.monthly, asked.year, asked.month)}
        </CommandLine>
        <Button icon={mdiMovieOpenPlayOutline} pressed={cutPress}>
          Cut
        </Button>
      </div>
    </div>
  );
};

type Props = { bassIntensity?: number };

export const BriefScene: React.FC<Props> = ({ bassIntensity }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      <WindowFrame path="/app/create" bassIntensity={bassIntensity}>
        <AppShell active="Memory">
          <BriefForm frame={frame} />
        </AppShell>
      </WindowFrame>
      <AnimatedCursor steps={cursorSteps} />
    </AbsoluteFill>
  );
};
