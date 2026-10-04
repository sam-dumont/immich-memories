import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";

// Inter, the web client's type (web/src/app.css): make demo-ui-install copies the files the
// client serves into public/fonts, and the fixture library into public/library, so a render
// needs no network. Icons are @mdi/js paths, not a font.
export const fontFamily = "Inter";

loadFont({
  family: fontFamily,
  url: staticFile("fonts/inter-latin.woff2"),
  weight: "100 900",
  format: "woff2",
});
