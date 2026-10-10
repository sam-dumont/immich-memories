import { AbsoluteFill, Img, staticFile } from "remotion";
import { fontFamily } from "../fonts";
import { COLORS } from "../theme";

/** Held after the dissolve, so the URL can be read and the music can resolve. */
export const ClosingScene: React.FC = () => (
  <AbsoluteFill style={{
    backgroundColor: COLORS.bg, color: COLORS.text, fontFamily,
    justifyContent: "center", alignItems: "center",
  }}>
    <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
      <Img src={staticFile("logo.svg")} style={{ width: 100, height: 100 }} />
      <div style={{ fontSize: 46, fontWeight: 600, letterSpacing: -1.4 }}>Immich Memories</div>
    </div>
    <div style={{ marginTop: 38, fontSize: 88, fontWeight: 600, letterSpacing: -3 }}>
      Make your first film.
    </div>
    <div style={{ marginTop: 24, fontSize: 36, color: COLORS.textSecondary }}>
      A self-hosted companion for Immich. Open source.
    </div>
    <div style={{ marginTop: 66, fontSize: 38, fontWeight: 600, color: COLORS.primary }}>
      sam-dumont.github.io/immich-memories
    </div>
  </AbsoluteFill>
);
