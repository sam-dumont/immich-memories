import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { fontFamily } from "../fonts";
import { COLORS } from "../theme";

export const TitleScene: React.FC = () => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg, color: COLORS.text, fontFamily }}>
      <div style={{
        position: "absolute", inset: "108px 140px", display: "grid",
        gridTemplateColumns: "1.05fr 1fr", gap: 88, alignItems: "center", opacity,
      }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 42 }}>
            <Img src={staticFile("logo.svg")} style={{ width: 72, height: 72 }} />
            <span style={{ fontSize: 34, fontWeight: 600 }}>Immich Memories</span>
          </div>
          <h1 style={{ fontSize: 72, lineHeight: 1.12, letterSpacing: -2.5, fontWeight: 600, margin: 0 }}>
            Watch your memories again, in films you can make your own.
          </h1>
          <div style={{ fontSize: 28, lineHeight: 1.5, marginTop: 36, color: COLORS.textSecondary }}>
            A self-hosted companion for Immich.<br />Open source.
          </div>
        </div>
        <div style={{ display: "grid", gap: 18 }}>
          {["trip-lake-arrival-01.jpg", "garden-cake.jpg", "woods-stream-01.jpg"].map((picture) => (
            <Img key={picture} src={staticFile(`library/${picture}`)} style={{
              width: "100%", height: 242, objectFit: "cover", borderRadius: 10,
            }} />
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
