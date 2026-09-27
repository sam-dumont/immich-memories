import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";
import { COLORS } from "../theme";
import {
  TITLE_H,
  WINDOW_H,
  WINDOW_W,
  WindowFrame,
  onScreen,
} from "../components/WindowFrame";
import { AppShell, MAIN_X } from "../components/AppShell";
import { AnimatedCursor } from "../components/AnimatedCursor";
import { FloatingEditBar, RUN_ID, RunPage } from "../components/RunPage";
import { EDITED } from "./EditScene";
import { JOB_SCROLL } from "./RenderScene";
import { CUT_CONTENT_BUDGET } from "../fixture";

/**
 * The render is done: the panel says so, and the film plays on the page. It
 * starts on the birthday candles, a stretch the revision did not touch.
 */

// The film element's top, from the top of the page, once the job panel above it has finished.
const FILM_Y = 1416 + 32 + 124 + 16;
const FILM_SCROLL = FILM_Y - 200;
const PLAY = 30;
const FILM_FROM = 19.2;

const FILM_CENTRE = { x: MAIN_X + 384, y: FILM_Y + 216 - FILM_SCROLL };
const PLAY_XY = onScreen(FILM_CENTRE.x, FILM_CENTRE.y);

type Props = { bassIntensity?: number };

export const FilmScene: React.FC<Props> = ({ bassIntensity }) => {
  const frame = useCurrentFrame();
  const scroll = interpolate(frame, [0, 22], [JOB_SCROLL, FILM_SCROLL], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      <WindowFrame
        path={`/app/runs/${RUN_ID}`}
        bassIntensity={bassIntensity}
        enter={false}
        zoom={{
          targetX: FILM_CENTRE.x / WINDOW_W,
          targetY: (TITLE_H + FILM_CENTRE.y) / WINDOW_H,
          scale: 1.45,
          startFrame: PLAY + 6,
          durationFrames: 24,
        }}
      >
        <AppShell active="Runs" scroll={scroll}>
          <RunPage
            state={{
              ...EDITED,
              frame,
              render: {
                revision: true,
                addDate: true,
                job: { label: "", fraction: 1, elapsed: "3m 12s", done: true },
                // A video starts at its sequence's first frame: back the start off by the frames before Play.
                film: { playing: frame >= PLAY, from: FILM_FROM - PLAY / 30 },
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
      <AnimatedCursor
        steps={[
          { frame: 22, ...PLAY_XY },
          { frame: PLAY, ...PLAY_XY, click: true },
        ]}
        hidden={[[PLAY + 4, 400]]}
      />
    </AbsoluteFill>
  );
};
