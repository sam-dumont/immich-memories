import { loadFont } from "@remotion/google-fonts/Inter";

// Inter, the web client's type (web/src/app.css). Icons are @mdi/js paths, not a font.
const { fontFamily } = loadFont("normal", {
  weights: ["400", "500", "600", "700"],
  subsets: ["latin"],
});

export { fontFamily };
