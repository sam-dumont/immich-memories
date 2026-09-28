# The Remotion demo

The 50-second product demo on the docs landing page and the README hero GIF are rendered from
this project. The web client (`web/src`, built on @immich/ui) is recreated in React (see
`src/scenes/` and `src/components/`), never screenshotted: the brief, the cut's progress panel,
the run page's contact sheet and inspector, a swap and a removal saved as revision 1, the render
panel and the film on the page, the runs and the suggestions, the same run in a terminal, and it
ends on the film it made. Icons are `@mdi/js` paths, as in the client; the Immich logo never
appears.

| Command (from the repo root) | Produces |
|---|---|
| `make demo-ui` | `docs-site/static/demo/demo.mp4`, the full composition, 1920×1080 H.264 |
| `make demo-hero` | `docs-site/static/img/demo-hero.gif`, the brief, the cut and the review from `demo.mp4` then its last 3 s (the film), 720 px, 10 fps, under 4 MB (the Makefile comment has the window) |
| `make demo-cli` | `public/cli-demo.mp4`, VHS recording the real CLI (`scripts/demo-cli-hermetic.py`: `generate`, `runs story`, `runs why` against the hermetic fakes from `tests/e2e`) |
| `make demo-output` | `public/output-preview.mp4` and `public/output-frame.jpg`, cut on the hermetic launch |
| `make demo-soundtrack` | `public/demo-music.wav`, rebuilt from the bundled acoustic track; also runs with `make demo-ui` |
| `make demo-music` | Optional ACE-Step candidates in `docs-site/static/demo/music-candidates/` |
| `make demo-ui-dev` | Remotion Studio for live preview |

`public/library` is a symlink to `tests/e2e/fixtures/library`, so the demo shows the same pictures
as the tests and the docs (the CC0 fixture library, credits in `CREDITS.md` there; `make
demo-fixture` exports the cut, its stories and the pool page into `src/fixture.ts`).

The soundtrack is `happy_acoustic_s411.opus` from the bundled music package (MIT;
`packages/immich-memories-music/LICENSE-MUSIC`). The recipe crossfades two copies over three
seconds and normalises to -18 LUFS with a -2 dB true-peak ceiling. Remotion fades it in and out.
Rebuilding needs FFmpeg, not a music server or a model download. The homepage and README both
show the hero GIF and link to the full demo with sound. Reduced-motion browsers get a still on
the homepage.
