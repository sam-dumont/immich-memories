import React from "react";
import {
  Easing,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { fontFamily } from "../fonts";
import { UI } from "../theme";

type CameraZoom = {
  targetX: number;
  targetY: number;
  scale: number;
  startFrame: number;
  durationFrames: number;
  /** When the camera pulls back out again; it stays in when omitted. */
  outFrame?: number;
};

type Props = {
  children: React.ReactNode;
  /** The address bar's path, after localhost:8099. */
  path: string;
  zoom?: CameraZoom;
  bassIntensity?: number;
  /** False when the scene continues the previous one on the same page: no float-in. */
  enter?: boolean;
};

export const WINDOW_W = 1600;
export const WINDOW_H = 900;
export const TITLE_H = 36;

const Light: React.FC<{ color: string }> = ({ color }) => (
  <div
    style={{
      width: 11,
      height: 11,
      borderRadius: "50%",
      backgroundColor: color,
    }}
  />
);

const cameraProgress = (frame: number, zoom: CameraZoom) => {
  const inward = interpolate(
    frame,
    [zoom.startFrame, zoom.startFrame + zoom.durationFrames],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  if (zoom.outFrame === undefined) return Easing.inOut(Easing.cubic)(inward);
  const outward = interpolate(
    frame,
    [zoom.outFrame, zoom.outFrame + zoom.durationFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  return Easing.inOut(Easing.cubic)(Math.min(inward, outward));
};

/** A browser window on the dark stage, the web client inside it. */
export const WindowFrame: React.FC<Props> = ({
  children,
  path,
  zoom,
  bassIntensity = 0,
  enter = true,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const entry = enter
    ? spring({ frame, fps, config: { damping: 15, stiffness: 80, mass: 1.2 } })
    : 1;
  const entryY = interpolate(entry, [0, 1], [60, 0]);
  const entryScale = interpolate(entry, [0, 1], [0.92, 1]);
  const entryOpacity = enter
    ? interpolate(frame, [0, 8], [0, 1], { extrapolateRight: "clamp" })
    : 1;

  let camScale = 1;
  let camX = 0;
  let camY = 0;
  if (zoom) {
    const eased = cameraProgress(frame, zoom);
    camScale = 1 + (zoom.scale - 1) * eased;
    camX =
      ((WINDOW_W / 2 - zoom.targetX * WINDOW_W) * (camScale - 1)) / camScale;
    camY =
      ((WINDOW_H / 2 - zoom.targetY * WINDOW_H) * (camScale - 1)) / camScale;
  }

  const shadowY = 30 + bassIntensity * 20;
  const shadowBlur = 60 + bassIntensity * 40;
  const shadowAlpha = 0.45 + bassIntensity * 0.2;

  return (
    <div
      style={{
        position: "absolute",
        top: "50%",
        left: "50%",
        width: WINDOW_W,
        height: WINDOW_H,
        marginLeft: -WINDOW_W / 2,
        marginTop: -WINDOW_H / 2,
        borderRadius: 12,
        overflow: "hidden",
        opacity: entryOpacity,
        boxShadow: `0 ${shadowY}px ${shadowBlur}px rgba(0,0,0,${shadowAlpha})`,
        transform: `translateY(${entryY}px) scale(${entryScale * camScale}) translate(${camX}px, ${camY}px)`,
        transformOrigin: "center center",
        fontFamily,
      }}
    >
      <div
        style={{
          height: TITLE_H,
          backgroundColor: "#e7e7ea",
          borderBottom: "1px solid #d4d4d8",
          display: "flex",
          alignItems: "center",
          paddingLeft: 14,
          gap: 7,
        }}
      >
        <Light color="#ff5f57" />
        <Light color="#febc2e" />
        <Light color="#28c840" />
        <div
          style={{
            flex: 1,
            display: "flex",
            justifyContent: "center",
            marginRight: 60,
          }}
        >
          <div
            style={{
              width: 520,
              height: 24,
              borderRadius: 7,
              background: "#f6f6f7",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 12,
              color: "#52525b",
            }}
          >
            localhost:8099{path}
          </div>
        </div>
      </div>

      <div
        style={{
          width: WINDOW_W,
          height: WINDOW_H - TITLE_H,
          overflow: "hidden",
          backgroundColor: UI.light,
          color: UI.dark,
        }}
      >
        {children}
      </div>
    </div>
  );
};

/** A point in the window's content area, in the 1920x1080 frame the cursor moves over. */
export const onScreen = (x: number, y: number) => ({
  x: (1920 - WINDOW_W) / 2 + x,
  y: (1080 - WINDOW_H) / 2 + TITLE_H + y,
});
