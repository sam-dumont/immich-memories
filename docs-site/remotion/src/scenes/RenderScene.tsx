import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";
import { COLORS } from "../theme";
import { WindowFrame, onScreen } from "../components/WindowFrame";
import { AppShell, MAIN_X } from "../components/AppShell";
import { AnimatedCursor } from "../components/AnimatedCursor";
import { FloatingEditBar, RUN_ID, RunPage } from "../components/RunPage";
import { elapsedLabel } from "../components/JobPanel";
import { EDITED } from "./EditScene";
import { CUT_CONTENT_BUDGET } from "../fixture";

/**
 * Below the sheet, the render panel: revision 1 picked as what to render (the
 * date and place overlays are on already), Render. The form gives way to the render job, which
 * reports its own stages the way `runs render --progress-file` writes them.
 */

// The render panel's heading, from the top of the page (below the saved bar and the revision).
const RENDER_Y = 1416;
const FORM_Y = RENDER_Y + 32;
const PANEL_SCROLL = 1306;
const BUTTON_SCROLL = 1506;
// Once the form is gone the page is shorter, and the browser pulls the scroll back with it.
export const JOB_SCROLL = 860;

const OPEN_SELECT = 38;
const PICK_REVISION = 54;
const RENDER = 108;
const JOB_START = RENDER + 4;

const SELECT_XY = onScreen(MAIN_X + 188, FORM_Y + 45 - PANEL_SCROLL);
const REVISION_XY = onScreen(
  MAIN_X + 120,
  FORM_Y + 70 + 4 + 34 + 17 - PANEL_SCROLL,
);
// The privacy checkbox wraps to two lines at this width: the checks take 96 px, not 76.
const RENDER_XY = onScreen(
  MAIN_X + 40,
  FORM_Y + 5 * 82 + 96 + 16 + 132 + 16 + 20 + 16 + 31 - BUTTON_SCROLL,
);

const cursorSteps = [
  { frame: 30, ...SELECT_XY },
  { frame: OPEN_SELECT, ...SELECT_XY, click: true },
  { frame: PICK_REVISION, ...REVISION_XY, click: true },
  { frame: RENDER, ...RENDER_XY, click: true },
];

// What the render reports, in the words of its progress callbacks
// (runs_render.py, title_divider_planner.py, streaming_assembler.py).
const STAGES = [
  { at: 0, label: "Preparing the render", fraction: 0 },
  { at: 6, label: "Generating month dividers...", fraction: 0.05 },
  { at: 12, label: "Streaming video assembly...", fraction: 0.07 },
  { at: 34, label: "Mixing audio...", fraction: 0.85 },
  { at: 42, label: "Muxing final output...", fraction: 0.95 },
];

export const renderJobAt = (frame: number) => {
  const since = frame - JOB_START;
  const stage =
    [...STAGES].reverse().find((step) => since >= step.at) ?? STAGES[0];
  const fraction =
    stage.label === "Streaming video assembly..."
      ? interpolate(since, [12, 34], [0.07, 0.8], { extrapolateRight: "clamp" })
      : stage.fraction;
  // The render runs faster than life: two minutes to every second shown.
  return {
    label: stage.label,
    fraction,
    elapsed: elapsedLabel((since / 30) * 120),
    done: false,
  };
};

type Props = { bassIntensity?: number };

export const RenderScene: React.FC<Props> = ({ bassIntensity }) => {
  const frame = useCurrentFrame();
  const easing = Easing.inOut(Easing.cubic);
  const scroll =
    frame >= JOB_START
      ? JOB_SCROLL
      : interpolate(
          frame,
          [0, 26, 76, 96],
          [0, PANEL_SCROLL, PANEL_SCROLL, BUTTON_SCROLL],
          {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing,
          },
        );
  const open =
    frame >= OPEN_SELECT && frame < PICK_REVISION
      ? frame < PICK_REVISION - 8
        ? ("cut" as const)
        : ("revision" as const)
      : undefined;
  const press = interpolate(
    frame,
    [RENDER, RENDER + 3, RENDER + 6],
    [0, 1, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    },
  );

  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      <WindowFrame
        path={`/app/runs/${RUN_ID}`}
        bassIntensity={bassIntensity}
        enter={false}
      >
        <AppShell active="Runs" scroll={scroll}>
          <RunPage
            state={{
              ...EDITED,
              frame,
              render: {
                revision: frame >= PICK_REVISION,
                open,
                addDate: true,
                renderPressed: press,
                job: frame >= JOB_START ? renderJobAt(frame) : undefined,
              },
            }}
          />
        </AppShell>
        <FloatingEditBar
          scroll={scroll}
          count={2}
          removed={EDITED.removed}
          budget={CUT_CONTENT_BUDGET}
          saved
          savePressed={0}
        />
      </WindowFrame>
      <AnimatedCursor steps={cursorSteps} />
    </AbsoluteFill>
  );
};
