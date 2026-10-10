# The Remotion demo

The 92-second product demo on the docs landing page and the README hero GIF are rendered from
this project. The web client (`web/src`, built on @immich/ui) is recreated in React (see
`src/scenes/` and `src/components/`), never screenshotted: the brief, the cut's progress panel,
the run page's contact sheet and inspector, a swap and a removal saved as revision 1, the render
panel and the film on the page, the runs and the suggestions, the same run in a terminal, and a continuous passage of the film it made. A held closing frame shows the docs address. Icons are `@mdi/js` paths, as in the client; the Immich logo never
appears.

| Command (from the repo root) | Produces |
|---|---|
| `make demo-ui` | `docs-site/static/demo/demo.mp4`, the full composition, 1920×1080 H.264 |
| `make demo-hero` | `docs-site/static/img/demo-hero.gif`: the brief, the cut and the review, then Render and the film on the page, then the film full bleed from where the page's player is (the shared timeline supplies the windows), 720 px, 10 fps, under 4 MB |
| `make demo-cli` | `public/cli-demo.mp4` and `src/cli-timing.ts`, VHS recording the real CLI (`scripts/demo-cli-hermetic.py`: `generate`, `runs story`, `runs why` against the hermetic fakes from `tests/e2e`); the script writes the second each command starts at, where `CliScene` cuts |
| `make demo-output` | `public/output-preview.mp4` and `public/output-frame.jpg`, cut on the hermetic launch |
| `make demo-soundtrack` | `public/demo-music.wav`, rebuilt from the bundled acoustic track; also runs with `make demo-ui` |
| `make demo-music` | Optional ACE-Step candidates in `docs-site/static/demo/music-candidates/` |
| `make demo-ui-dev` | Remotion Studio for live preview |

`make demo-ui-install` copies `tests/e2e/fixtures/library` to `public/library`, so the demo shows
the same pictures as the tests and the docs, and the web client's own Inter to `public/fonts`, so a
render needs no network (the CC0 fixture library, credits in `CREDITS.md` there; `make
demo-fixture` exports the cut, its stories and the pool page into `src/fixture.ts`).

The soundtrack is `happy_acoustic_s411.opus` from the bundled music package (MIT;
`packages/immich-memories-music/LICENSE-MUSIC`). The recipe crossfades four copies with three-second overlaps and normalises to -18 LUFS with a -2 dB true-peak ceiling. Remotion fades it in and out.
Rebuilding needs FFmpeg, not a music server or a model download. The homepage embeds the full demo with controls and a themed poster. It autoplays muted; viewers can enable sound. Reduced-motion
visitors get the poster and press Play themselves. The README uses the short hero GIF and links to the full demo.

The opening and closing frames use the docs logo, Inter and the shared Immich UI colour tokens.
Scene headings explain the action; preparation and rendering are labelled as sped up. The CLI
keeps its command and explanations readable. The final film passage plays at normal speed,
holds its last picture, then dissolves into the closing frame. Music fades with that frame and
ends half a second before the video.

`src/timeline.ts` owns scene lengths, overlaps and the selected film passage. `scripts/hero.mjs`
reads those positions for the GIF, including the handoff from the page's player to the film.
After regenerating `output-preview.mp4`, review the passage named there: it must contain complete
shots and finish before the next shot begins. `make demo-output` pins English for the fixture's
titles and dates, independent of the machine running it.

Review each scene in both themes, including cursor targets, reading time, the revised render form
and the final hold. `make demo-ui` extracts each homepage poster from frame 65 of its matching full demo into
`docs-site/static/demo/demo-poster.jpg` and `dark-demo-poster.jpg`.
