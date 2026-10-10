import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { SCENE_START, FPS, PLAYER_FROM, PLAYER_PLAY } from "../src/timeline.ts";

// Run from the repository root via make demo-hero. Derive every cut from the
// composition: changing a scene length must not splice unrelated UI frames.
const theme = process.env.DEMO_THEME ?? "light";
if (!["light", "dark"].includes(theme)) throw new Error("Unknown demo theme");
const name = theme === "dark" ? "dark-demo" : "demo";
const from = SCENE_START.brief / FPS + 3;
const to = SCENE_START.review / FPS + 1;
const render = SCENE_START.render / FPS + 4;
const player = SCENE_START.film / FPS + 3;
const tail = PLAYER_FROM + 3 - PLAYER_PLAY / FPS - 0.5;
const first = to - from;
const second = player - render;
const filter = "fps=10,scale=720:405:flags=lanczos,format=yuv420p";
const graph = [
  `[0:v]trim=${from}:${to},setpts=PTS-STARTPTS,${filter}[a]`,
  `[0:v]trim=${render}:${player},setpts=PTS-STARTPTS,${filter}[b]`,
  `[1:v]trim=${tail}:${tail + 3},setpts=PTS-STARTPTS,${filter}[c]`,
  `[a][b]xfade=transition=fade:duration=0.3:offset=${first - 0.3}[ab]`,
  `[ab][c]xfade=transition=fade:duration=0.5:offset=${first + second - 0.8},hqdn3d,split[x][y]`,
  "[y]palettegen=max_colors=255:stats_mode=diff[p]",
  "[x][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
].join(";");
const result = spawnSync("ffmpeg", [
  "-y", "-loglevel", "error",
  "-i", `docs-site/static/demo/${name}.mp4`,
  "-i", "docs-site/remotion/public/output-preview.mp4",
  "-filter_complex", graph, `docs-site/static/img/${name}-hero.gif`,
], { cwd: fileURLToPath(new URL("../../../", import.meta.url)), stdio: "inherit" });
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
