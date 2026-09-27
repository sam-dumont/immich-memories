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
import { SHOTS } from "../fixture";

/**
 * web/src/routes/runs/+page.svelte: every run, newest first, as a card with
 * the first pictures of its cut. The film just rendered leads, then the cut it
 * came from; the older runs are the fixture library's other stories.
 */

const JUNE = "Jun 1, 2024 to Jun 30, 2024";
const firstFour = (pictures: string[]) => pictures.slice(0, 4);

const RUNS: {
  type: string;
  span: string;
  status: "Completed" | "Failed";
  when: string;
  pictures: string[];
}[] = [
  {
    type: "Monthly Highlights",
    span: JUNE,
    status: "Completed",
    when: "now · Manual",
    pictures: firstFour([
      SHOTS[0].picture,
      "library/home-rain-window-02.jpg",
      SHOTS[2].picture,
      SHOTS[3].picture,
    ]),
  },
  {
    type: "Monthly Highlights",
    span: JUNE,
    status: "Completed",
    when: "4 minutes ago · Manual",
    pictures: firstFour(SHOTS.map((shot) => shot.picture)),
  },
  {
    type: "Trip",
    span: "Jun 21, 2024 to Jun 23, 2024",
    status: "Completed",
    when: "yesterday · Automatic",
    pictures: firstFour(
      SHOTS.filter((shot) => shot.story === "A week by the lake")
        .map((shot) => shot.picture)
        .slice(1),
    ),
  },
  {
    type: "Person Spotlight",
    span: "Jan 1, 2023 to Dec 31, 2023",
    status: "Failed",
    when: "2 days ago · Scheduled",
    pictures: [],
  },
  {
    type: "Custom date range",
    span: "Jun 15, 2024 to Jun 15, 2024",
    status: "Completed",
    when: "3 days ago · Manual",
    pictures: firstFour(
      SHOTS.filter((shot) => shot.day === "2024-06-15").map(
        (shot) => shot.picture,
      ),
    ),
  },
  {
    type: "Special day",
    span: "Jun 8, 2024 to Jun 8, 2024",
    status: "Completed",
    when: "5 days ago · Automatic",
    pictures: firstFour(
      SHOTS.filter((shot) => shot.day === "2024-06-08").map(
        (shot) => shot.picture,
      ),
    ),
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

type Props = { bassIntensity?: number };

export const RunsScene: React.FC<Props> = ({ bassIntensity }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const reveal = (delay: number) =>
    spring({ frame, fps, config: { damping: 20, stiffness: 140 }, delay });

  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      <WindowFrame path="/app/runs" bassIntensity={bassIntensity} enter={false}>
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
