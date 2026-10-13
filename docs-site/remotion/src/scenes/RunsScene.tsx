import React from "react";
import {
  AbsoluteFill,
  Img,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { mdiImageOffOutline } from "@mdi/js";
import { COLORS, UI } from "../theme";
import { WindowFrame } from "../components/WindowFrame";
import { AppShell } from "../components/AppShell";
import { Mdi } from "../components/Mdi";
import { Badge, Button, Heading } from "../components/ui";
import { EDIT_REMOVED, EDIT_SWAPPED, SHOTS } from "../fixture";

/**
 * web/src/routes/runs/+page.svelte: every run, newest first, as a card with
 * the first pictures of its cut. The film just rendered leads, then the cut it
 * came from; the older runs are the fixture library's other stories.
 */

const JULY = "Jul 1, 2025 to Jul 31, 2025";
const firstFour = (pictures: string[]) => pictures.slice(0, 4);

const MONTH_NAMES = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];
/** "2025-07-31" as the runs page prints a one-day range. */
const oneDay = (day: string) => {
  const label = `${MONTH_NAMES[Number(day.slice(5, 7)) - 1]} ${Number(day.slice(8))}, ${day.slice(0, 4)}`;
  return `${label} to ${label}`;
};
// The cut with the saved revision applied: the swapped shot's other picture, the removed one gone.
const REVISED = SHOTS.map((shot, i) =>
  i === EDIT_SWAPPED ? shot.alternatives[0] : shot.picture,
).filter((_, i) => i !== EDIT_REMOVED);
// A custom range over the busiest day of the cut after its first one (the special day's).
const shotsOn = (day: string) => SHOTS.filter((shot) => shot.day === day);
const BUSY_DAY = SHOTS.map((shot) => shot.day)
  .filter((day) => day !== SHOTS[0].day)
  .reduce(
    (best, day) => (shotsOn(day).length > shotsOn(best).length ? day : best),
    SHOTS[SHOTS.length - 1].day,
  );

const RUNS: {
  type: string;
  span: string;
  status: "Completed" | "Failed";
  when: string;
  pictures: string[];
}[] = [
  {
    type: "Monthly Highlights",
    span: JULY,
    status: "Completed",
    when: "now · Manual",
    pictures: firstFour(REVISED),
  },
  {
    type: "Monthly Highlights",
    span: JULY,
    status: "Completed",
    when: "4 minutes ago · Manual",
    pictures: firstFour(SHOTS.map((shot) => shot.picture)),
  },
  {
    type: "Trip",
    span: "Jul 12, 2025 to Jul 30, 2025",
    status: "Completed",
    when: "yesterday · Automatic",
    pictures: firstFour(
      SHOTS.filter((shot) => shot.story === "The road north")
        .map((shot) => shot.picture)
        .slice(1),
    ),
  },
  {
    type: "Custom date range",
    span: oneDay(BUSY_DAY),
    status: "Completed",
    when: "3 days ago · Manual",
    pictures: firstFour(shotsOn(BUSY_DAY).map((shot) => shot.picture)),
  },
  {
    type: "Special day",
    span: oneDay(SHOTS[0].day),
    status: "Completed",
    when: "5 days ago · Automatic",
    pictures: firstFour(shotsOn(SHOTS[0].day).map((shot) => shot.picture)),
  },
];

const CARD_W = (1279 - 3 * 20) / 4;

const Mosaic: React.FC<{ pictures: string[] }> = ({ pictures }) => (
  <div
    style={{
      width: CARD_W,
      height: CARD_W,
      borderRadius: 16,
      overflow: "hidden",
      background: UI.gray100,
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gridTemplateRows: "1fr 1fr",
      gap: 2,
    }}
  >
    {pictures.length ? (
      pictures.map((picture, i) => (
        <Img
          key={picture}
          src={staticFile(picture)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            gridRow:
              pictures.length === 2 || (pictures.length === 3 && i === 0)
                ? "span 2"
                : undefined,
          }}
        />
      ))
    ) : (
      <div
        style={{
          gridColumn: "span 2",
          gridRow: "span 2",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "oklch(70.7% 0.022 261.325)",
          opacity: 0.6,
        }}
      >
        <Mdi path={mdiImageOffOutline} size={48} />
      </div>
    )}
  </div>
);

export const RunsScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const reveal = (delay: number) =>
    spring({ frame, fps, config: { damping: 20, stiffness: 140 }, delay });

  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      <WindowFrame path="/app/runs" enter={false}>
        <AppShell active="Runs">
          <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <Heading size="large">Runs</Heading>
              <div
                style={{ fontSize: 16, lineHeight: "24px", color: UI.gray600 }}
              >
                Manual and automatic runs, including failures. Open a run to
                read its cut and timings.
              </div>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              {[
                "All",
                "Completed",
                "Running",
                "Failed",
                "Cancelled",
                "Interrupted",
              ].map((status) => (
                <Button
                  key={status}
                  size="small"
                  round
                  variant={status === "All" ? "filled" : "outline"}
                  color={status === "All" ? "primary" : "secondary"}
                >
                  {status}
                </Button>
              ))}
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: `repeat(4, ${CARD_W}px)`,
                columnGap: 20,
                rowGap: 32,
              }}
            >
              {RUNS.map((run, i) => {
                const shown = reveal(6 + i * 5);
                return (
                  <div
                    key={`${run.type}-${run.when}`}
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: 8,
                      opacity: shown,
                      transform: `translateY(${(1 - shown) * 14}px)`,
                    }}
                  >
                    <Mosaic pictures={run.pictures} />
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        gap: 8,
                        padding: "0 4px",
                      }}
                    >
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 16, fontWeight: 500 }}>
                          {run.type}
                        </div>
                        <div style={{ fontSize: 14, color: UI.gray600 }}>
                          {run.span}
                        </div>
                      </div>
                      <div>
                        <Badge
                          size="tiny"
                          color={
                            run.status === "Completed" ? "success" : "danger"
                          }
                        >
                          {run.status}
                        </Badge>
                      </div>
                    </div>
                    <div
                      style={{
                        padding: "0 4px",
                        fontSize: 12,
                        color: UI.gray600,
                      }}
                    >
                      {run.when}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </AppShell>
      </WindowFrame>
    </AbsoluteFill>
  );
};
