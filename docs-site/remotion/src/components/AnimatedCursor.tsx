import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { UI } from "../theme";

type CursorStep = {
  frame: number; // when to arrive at this position
  x: number; // target X (px from left of parent)
  y: number; // target Y (px from top of parent)
  click?: boolean; // pulse on arrival
};

type Props = {
  steps: CursorStep[];
  /** Frame windows the pointer steps out of, e.g. while the camera moves in. */
  hidden?: [number, number][];
};

/**
 * The pointer, moving between positions and "clicking": a ring spreads from
 * the tip on each click. Positions are in the 1920x1080 frame (see onScreen).
 */
export const AnimatedCursor: React.FC<Props> = ({ steps, hidden = [] }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  if (steps.length === 0) return null;

  // Find current and previous step
  let currentIdx = 0;
  for (let i = steps.length - 1; i >= 0; i--) {
    if (frame >= steps[i].frame - 15) {
      currentIdx = i;
      break;
    }
  }

  const current = steps[currentIdx];
  const prev = currentIdx > 0 ? steps[currentIdx - 1] : current;

  // Smooth movement via spring
  const moveProgress = spring({
    frame: Math.max(0, frame - (current.frame - 15)),
    fps,
    config: { damping: 20, stiffness: 100 },
  });

  const x = interpolate(moveProgress, [0, 1], [prev.x, current.x]);
  const y = interpolate(moveProgress, [0, 1], [prev.y, current.y]);

  // Click pulse
  let clickScale = 1;
  let glowOpacity = 0.3;
  if (current.click && frame >= current.frame && frame < current.frame + 12) {
    const clickProgress = (frame - current.frame) / 12;
    clickScale = 1 + 0.6 * Math.sin(clickProgress * Math.PI);
    glowOpacity = 0.3 + 0.5 * Math.sin(clickProgress * Math.PI);
  }

  // Only visible after first step
  const visible = frame >= steps[0].frame - 15;
  if (!visible) return null;

  // Fade in
  const fadeIn = interpolate(
    frame,
    [steps[0].frame - 15, steps[0].frame - 5],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  const ring = current.click
    ? interpolate(frame, [current.frame, current.frame + 14], [0, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      })
    : 1;

  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        opacity:
          fadeIn *
          hidden.reduce(
            (shown, [from, to]) =>
              shown *
              interpolate(frame, [from, from + 6, to - 6, to], [1, 0, 0, 1], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              }),
            1,
          ),
        pointerEvents: "none",
        zIndex: 9999,
      }}
    >
      {ring > 0 && ring < 1 && (
        <div
          style={{
            position: "absolute",
            left: -22 * ring,
            top: -22 * ring,
            width: 44 * ring,
            height: 44 * ring,
            borderRadius: "50%",
            border: `3px solid ${UI.primary}`,
            opacity: (1 - ring) * glowOpacity * 1.6,
          }}
        />
      )}
      <svg
        width={28}
        height={28}
        viewBox="0 0 24 24"
        style={{
          position: "absolute",
          left: -5,
          top: -3,
          transform: `scale(${1 / clickScale ** 0.3})`,
          transformOrigin: "5px 3px",
          filter: "drop-shadow(0 2px 3px rgba(0,0,0,0.35))",
        }}
      >
        <path
          d="M5.5,2.5 L5.5,19.5 L9.6,15.6 L12.4,21.6 L15.1,20.4 L12.4,14.5 L18,14.5 Z"
          fill="#111"
          stroke="#fff"
          strokeWidth={1.4}
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
};
