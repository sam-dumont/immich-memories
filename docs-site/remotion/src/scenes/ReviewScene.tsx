import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";
import { COLORS } from "../theme";
import { WindowFrame, onScreen } from "../components/WindowFrame";
import { AppShell, MAIN_X } from "../components/AppShell";
import { AnimatedCursor } from "../components/AnimatedCursor";
import {
  CARD_W,
  RUN_ID,
  RunPage,
  TOGGLE_Y,
  cardAt,
} from "../components/RunPage";

/**
 * The cut lands on its run page: the contact sheet in the order the film plays
 * it, the first picture under review. A video shot is opened (the inspector
 * plays the stretch the cut uses, and says why the picture is there), then the
 * same cut is read as its weighed stories, and back.
 */

const PICK = 45;
const ZOOM_IN = 58;
const ZOOM_OUT = 110;
const STORIES_AT = 140;
export const SHEET_AGAIN = 176;

const PICKED = 2;
const card = cardAt(PICKED);
const PICK_XY = onScreen(MAIN_X + card.x + CARD_W / 2, card.y + 70);
const STORIES_XY = onScreen(MAIN_X + 154, TOGGLE_Y + 17);
const SHEET_XY = onScreen(MAIN_X + 60, TOGGLE_Y + 17);

const cursorSteps = [
  { frame: 30, ...PICK_XY },
  { frame: PICK, ...PICK_XY, click: true },
  { frame: STORIES_AT, ...STORIES_XY, click: true },
  { frame: SHEET_AGAIN, ...SHEET_XY, click: true },
];

// The camera leans in on the inspector, pinned on the window's bottom-right
// corner, while the page scrolls just far enough to show why the picture is in.
const ZOOM = { targetX: 1, targetY: 1, scale: 1.3, durationFrames: 18 };
const LEAN_SCROLL = 110;

type Props = { bassIntensity?: number };

export const ReviewScene: React.FC<Props> = ({ bassIntensity }) => {
  const frame = useCurrentFrame();
  const view = frame >= STORIES_AT && frame < SHEET_AGAIN ? "stories" : "sheet";
  const scroll = interpolate(
    frame,
    [ZOOM_IN, ZOOM_IN + 18, ZOOM_OUT, ZOOM_OUT + 18],
    [0, LEAN_SCROLL, LEAN_SCROLL, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.inOut(Easing.cubic),
    },
  );
  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      <WindowFrame
        path={`/app/runs/${RUN_ID}`}
        bassIntensity={bassIntensity}
        enter={false}
        zoom={{ ...ZOOM, startFrame: ZOOM_IN, outFrame: ZOOM_OUT }}
      >
        <AppShell active="Runs" scroll={scroll}>
          <RunPage
            state={{
              view,
              selected: frame >= PICK ? PICKED : 0,
              removed: [],
              swapped: {},
              frame,
            }}
          />
        </AppShell>
      </WindowFrame>
      <AnimatedCursor
        steps={cursorSteps}
        hidden={[[ZOOM_IN - 4, ZOOM_OUT + 22]]}
      />
    </AbsoluteFill>
  );
};
