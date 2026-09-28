import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { COLORS, UI } from "../theme";
import { WindowFrame } from "../components/WindowFrame";
import { AppShell } from "../components/AppShell";
import { JobPanel } from "../components/JobPanel";
import { Heading } from "../components/ui";
import { POOL, POOL_TOTAL, SHOTS } from "../fixture";

/**
 * The same page once Cut is pressed: the form gives way to the job panel
 * (web/src/lib/JobPanel.svelte), which follows the cut stage by stage. The
 * counted stage carries the bar, "N of M · ~Ns left in this stage" and the
 * pictures just read; the stages after it only name themselves.
 */

export const CUT_COMMAND =
  "immich-memories generate --memory-type=monthly_highlights --year=2024 --month=6 --include-photos --include-live-photos --no-render";

// The pictures the reading pass goes through, in the order the pool lists them.
const READ_ORDER = [
  ...new Set([
    ...POOL.map((card) => card.picture),
    ...SHOTS.map((shot) => shot.picture),
  ]),
];

// Stage labels: the server's own before the attempt exists (job_routes.py), the
// attempt's first stage (editorial_attempt.py), then the editorial stages in
// the order tests/e2e/fake_editorial.py STAGES reports them.
const TIMELINE = [
  { at: 0, label: "Preparing the pool" },
  { at: 10, label: "Preparing editorial evidence" },
  { at: 92, label: "Reading dates, places and people" },
  { at: 104, label: "Reading event evidence" },
  { at: 114, label: "Editing the memory" },
  { at: 126, label: "Validating selected source timing" },
];
const COUNT_FROM = 12;
const COUNT_TO = 90;

type Props = { bassIntensity?: number };

export const CuttingScene: React.FC<Props> = ({ bassIntensity }) => {
  const frame = useCurrentFrame();
  const stage =
    [...TIMELINE].reverse().find((step) => frame >= step.at) ?? TIMELINE[0];
  const counting = stage.label === "Preparing editorial evidence";

  const exact = interpolate(frame, [COUNT_FROM, COUNT_TO], [0, POOL_TOTAL], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const done = Math.floor(exact);
  // The stage's estimate, rounded the way the panel rounds it: seconds under a minute.
  const stageSeconds = ((COUNT_TO - COUNT_FROM) / 30) * 6;
  const remaining = Math.max(
    1,
    Math.ceil(stageSeconds * (1 - done / POOL_TOTAL)),
  );

  // One picture joins the strip for every four read; the strip keeps the last eight.
  const read = Math.floor(exact / 4);
  const pictures = READ_ORDER.slice(0, Math.min(read, READ_ORDER.length));
  const arriving = exact / 4 - read;

  // The cut runs faster than life: six seconds of it to every second shown.
  const elapsed = Math.floor((frame / 30) * 6);

  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      <WindowFrame
        path="/app/create"
        bassIntensity={bassIntensity}
        enter={false}
      >
        <AppShell active="Memory">
          <div
            style={{
              width: 768,
              display: "flex",
              flexDirection: "column",
              gap: 24,
            }}
          >
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <Heading size="large">New memory</Heading>
              <div
                style={{ fontSize: 16, lineHeight: "24px", color: UI.gray600 }}
              >
                Choose what the film covers. The cut is made the way the command
                below makes it; you review it before anything renders.
              </div>
            </div>
            <JobPanel
              label={stage.label}
              elapsed={`${elapsed}s`}
              command={CUT_COMMAND}
              fraction={counting ? exact / POOL_TOTAL : 0}
              done={counting ? done : undefined}
              total={counting ? POOL_TOTAL : undefined}
              remaining={
                counting ? `~${remaining}s left in this stage` : undefined
              }
              pictures={pictures}
              arriving={frame < COUNT_TO ? Math.min(1, arriving * 2) : 1}
            />
          </div>
        </AppShell>
      </WindowFrame>
    </AbsoluteFill>
  );
};
