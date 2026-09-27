import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";
import { COLORS } from "../theme";
import { WindowFrame, onScreen } from "../components/WindowFrame";
import { AppShell, MAIN_X } from "../components/AppShell";
import { AnimatedCursor } from "../components/AnimatedCursor";
import {
  CARD_W,
  GRID_Y,
  INSPECTOR_X,
  PLAYER_H,
  RUN_ID,
  RunPage,
  BAR_H,
  BAR_SAVED_H,
  FloatingEditBar,
  alternativesOf,
  cardAt,
} from "../components/RunPage";
import { CUT_CONTENT_BUDGET, SHOTS } from "../fixture";

/**
 * The cut is a draft: one shot swapped for another picture of the same moment
 * ("Other pictures of this moment", then "Use this picture instead"), one
 * removed, and the edit bar counts the changes and the seconds against what
 * the titles leave, until "Save revision" keeps them as revision 1.
 */

const SWAPPED = 1;
const REMOVED = 4;
const ALTERNATIVE = alternativesOf(SHOTS[SWAPPED])[0].picture;

const PICK_SWAP = 22;
const SCROLL_DOWN = [30, 56];
const OPEN_ALTERNATIVE = 68;
const USE_IT = 96;
const SCROLL_UP = [108, 134];
const PICK_REMOVE = 150;
const REMOVE = 172;
const SAVE = 200;
const SAVED = SAVE + 8;

// How far the page scrolls to bring the alternatives and the swap button into view.
const SWAP_SCROLL = 560;

// Inspector geometry for a still shot, from the top of the page.
const INSPECTOR_LEFT = MAIN_X + INSPECTOR_X;
const THUMBS_Y =
  GRID_Y + PLAYER_H + 20 + 74 + 20 + 50 + 20 + 44 + 20 + 64 + 20 + 48;
const USE_IT_Y = THUMBS_Y + 88 + 212 + 18;
const REMOVE_Y = GRID_Y + PLAYER_H + 20 + 18;
const COMPARED_BOTTOM = USE_IT_Y + 18 + 8 + 20 + 20 + 44;

const cardXY = (index: number) => {
  const card = cardAt(index);
  return onScreen(MAIN_X + card.x + CARD_W / 2, card.y + 60);
};
const ALT_XY = onScreen(INSPECTOR_LEFT + 48, THUMBS_Y + 40 - SWAP_SCROLL);
const USE_XY = onScreen(INSPECTOR_LEFT + 110, USE_IT_Y - SWAP_SCROLL);
const REMOVE_XY = onScreen(INSPECTOR_LEFT + 96, REMOVE_Y);
// The edit bar floats 16 px above the viewport's bottom; Save revision is its last button.
const SAVE_XY = onScreen(MAIN_X + 1279 - 74, 864 - 16 - 30);

const cursorSteps = [
  { frame: 12, ...cardXY(SWAPPED) },
  { frame: PICK_SWAP, ...cardXY(SWAPPED), click: true },
  { frame: OPEN_ALTERNATIVE, ...ALT_XY, click: true },
  { frame: USE_IT, ...USE_XY, click: true },
  { frame: PICK_REMOVE, ...cardXY(REMOVED), click: true },
  { frame: REMOVE, ...REMOVE_XY, click: true },
  { frame: SAVE, ...SAVE_XY, click: true },
];

const pulse = (frame: number, at: number) =>
  interpolate(frame, [at, at + 4, at + 8], [0, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

type Props = { bassIntensity?: number };

export const EditScene: React.FC<Props> = ({ bassIntensity }) => {
  const frame = useCurrentFrame();
  const scroll = interpolate(
    frame,
    [...SCROLL_DOWN, ...SCROLL_UP],
    [0, SWAP_SCROLL, SWAP_SCROLL, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.inOut(Easing.cubic),
    },
  );
  const selected =
    frame < PICK_SWAP ? 2 : frame < PICK_REMOVE ? SWAPPED : REMOVED;
  const swapped: Record<number, string> =
    frame >= USE_IT ? { [SWAPPED]: ALTERNATIVE } : {};
  const removed = frame >= REMOVE ? [REMOVED] : [];
  const changes = Object.keys(swapped).length + removed.length;
  const saved = frame >= SAVED;
  const barHeight = saved ? BAR_SAVED_H : BAR_H;
  // While the swapped still is open with its comparison, the inspector runs
  // past the sheet and the bar's place in the page moves down with it.
  const natural = selected === SWAPPED ? COMPARED_BOTTOM + 24 : undefined;

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
              view: "sheet",
              selected,
              removed,
              swapped,
              comparing: frame >= OPEN_ALTERNATIVE ? ALTERNATIVE : undefined,
              frame,
              barHeight: changes > 0 ? barHeight : undefined,
              revision: saved,
              press: {
                swap: pulse(frame, USE_IT),
                remove: pulse(frame, REMOVE),
              },
            }}
          />
        </AppShell>
        {changes > 0 && (
          <FloatingEditBar
            scroll={scroll}
            natural={natural}
            count={changes}
            removed={removed}
            budget={CUT_CONTENT_BUDGET}
            saved={saved}
            savePressed={pulse(frame, SAVE)}
          />
        )}
      </WindowFrame>
      <AnimatedCursor steps={cursorSteps} />
    </AbsoluteFill>
  );
};

/** The page as the edit leaves it: the render scene picks it up from here. */
export const EDITED = {
  view: "sheet" as const,
  selected: REMOVED,
  removed: [REMOVED],
  swapped: { [SWAPPED]: ALTERNATIVE },
  comparing: ALTERNATIVE,
  barHeight: BAR_SAVED_H,
  revision: true,
};
