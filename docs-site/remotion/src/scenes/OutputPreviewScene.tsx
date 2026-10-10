import { AbsoluteFill, Freeze, OffthreadVideo, staticFile, useCurrentFrame } from "remotion";
import { FPS, OUTPUT_FROM, OUTPUT_PLAY_FRAMES } from "../timeline";

/** A continuous passage of the actual CC0 fixture film, at its original speed. */
export const OutputPreviewScene: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <Freeze frame={Math.min(frame, OUTPUT_PLAY_FRAMES - 1)}>
        <OffthreadVideo
          src={staticFile("output-preview.mp4")}
          style={{ width: "100%", height: "100%", objectFit: "contain" }}
          startFrom={Math.round(OUTPUT_FROM * FPS)}
          muted
        />
      </Freeze>
    </AbsoluteFill>
  );
};
