import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";

// Inter, the web client's type (web/src/app.css), from the very file the client serves:
// public/fonts links to src/immich_memories/web/static/fonts, the way public/library links to
// the fixture library. A render then needs no network. Icons are @mdi/js paths, not a font.
export const fontFamily = "Inter";

loadFont({
  family: fontFamily,
  url: staticFile("fonts/inter-latin.woff2"),
  weight: "100 900",
  format: "woff2",
});
