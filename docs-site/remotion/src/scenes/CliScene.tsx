import React from "react";
import {
  AbsoluteFill,
  interpolate,
  OffthreadVideo,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { SCENE_FRAMES } from "../timeline";
import { COLORS } from "../theme";
import { CLI_TIMING } from "../cli-timing";

// The recording is the real CLI, a couple of minutes from the first prompt to
// `open`. The command is typed at a readable pace, the generate run is a
// time-lapse; `runs story` and `runs why` are held
// long enough to read. The cut points are the seconds the recording script wrote
// down as it typed each command (cli-timing.ts), so a new recording moves them.
const CLI_FRAMES = SCENE_FRAMES.cli;
const FPS = 30;
// Keep the typed command and the explanations readable; accelerate the run itself.
const TYPED = CLI_TIMING.generate + 4.5;
const LEGS: { from: number; to: number; frames: number }[] = [
  { from: CLI_TIMING.generate, to: TYPED, frames: 105 },
  { from: TYPED, to: CLI_TIMING.story, frames: 30 },
  { from: CLI_TIMING.story, to: CLI_TIMING.why, frames: 105 },
  { from: CLI_TIMING.why, to: CLI_TIMING.whyNot, frames: 105 },
  { from: CLI_TIMING.whyNot, to: CLI_TIMING.open, frames: 90 },
  { from: CLI_TIMING.open, to: CLI_TIMING.end, frames: CLI_FRAMES - 435 },
];

const Recording: React.FC = () => {
  let at = 0;
  return (
    <>
      {LEGS.map((leg) => {
        const start = at;
        at += leg.frames;
        return (
          <Sequence key={leg.from} from={start} durationInFrames={leg.frames} layout="none">
            <OffthreadVideo
              src={staticFile("cli-demo.mp4")}
              style={{ width: "100%", height: "calc(100% - 36px)", objectFit: "cover" }}
              muted
              startFrom={Math.round(leg.from * FPS)}
              playbackRate={(leg.to - leg.from) * FPS / leg.frames}
            />
          </Sequence>
        );
      })}
    </>
  );
};

export const CliScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const entry = spring({
    frame,
    fps,
    config: { damping: 28, stiffness: 100 },
  });
  const entryY = interpolate(entry, [0, 1], [50, 0]);
  const entryScale = interpolate(entry, [0, 1], [0.93, 1]);
  const entryOpacity = interpolate(frame, [0, 8], [0, 1], {
    extrapolateRight: "clamp",
  });
  const floatY = 0;

  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      <div
        style={{
          position: "absolute",
          top: "50%",
          left: "50%",
          width: 1500,
          height: 872,
          marginLeft: -750,
          marginTop: -436,
          borderRadius: 12,
          overflow: "hidden",
          opacity: entryOpacity,
          boxShadow: "0 30px 70px rgba(0,0,0,0.5)",
          transform: `translateY(${entryY + floatY}px) scale(${entryScale})`,
        }}
      >
        <div
          style={{
            height: 36,
            backgroundColor: COLORS.terminalTitleBar,
            display: "flex",
            alignItems: "center",
            paddingLeft: 14,
            gap: 7,
          }}
        >
          <div
            style={{
              width: 11,
              height: 11,
              borderRadius: "50%",
              backgroundColor: "#ff5f57",
            }}
          />
          <div
            style={{
              width: 11,
              height: 11,
              borderRadius: "50%",
              backgroundColor: "#febc2e",
            }}
          />
          <div
            style={{
              width: 11,
              height: 11,
              borderRadius: "50%",
              backgroundColor: "#28c840",
            }}
          />
          <div
            style={{
              flex: 1,
              textAlign: "center",
              fontSize: 12,
              color: "#6e7681",
              fontFamily: "monospace",
              marginRight: 60,
            }}
          >
            Terminal — immich-memories generate
          </div>
        </div>

        <Recording />
      </div>
    </AbsoluteFill>
  );
};
