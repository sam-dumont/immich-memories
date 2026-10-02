# Audit A: README, welcome, get-started, make

Tree audited: HEAD `b371427b` (shallow clone, 50 commits). CLI checked with `uv run --no-sync immich-memories <cmd> --help` (version reported `0.1.dev50`). Web labels checked against `web/src` (English msgids in `t('...')`). Config claims checked against the pydantic models and by loading test configs through `Config.from_yaml` / the section models. Every relative link and `#anchor` in the 14 docs pages was resolved by a script against target headings (all resolve; the docs build also runs with `onBrokenLinks/onBrokenAnchors: 'throw'`). `make docs-voice` reports `clean`; no em or en dashes in any assigned page.

## 1. Coverage

| Page | Claims checked (rough) | Findings | Verdict |
|---|---|---|---|
| README.md | 30 | 1 (A-15, shared) | Accurate. Every link target, the static GIFs/MP4s, CREDITS.md, CONTRIBUTING.md, DISCLAIMER.md and LICENSE exist; Immich v2/v3, 4 GB and the localhost/auth default all match the code |
| welcome/introduction.mdx | 20 | 0 | Accurate. Links, Video component and poster asset are all correct |
| welcome/about.mdx | 10 | 0 | Accurate where checkable; the rest is narrative |
| welcome/how-this-was-built.md | 45 | 0 | Nothing found wrong. Issues #764 and #1033 match their titles. Most history numbers can't be checked (see section 3) |
| get-started/quick-start.md (+ InstallationFiles) | 35 | 4 (A-14, A-15, A-20, A-22) | Works as written. Small wording problems about disk, cores and symptom labels |
| get-started/first-film.mdx | 30 | 1 (A-16) | Every UI label matches the Svelte client |
| get-started/who-is-who.md | 25 | 0 | Accurate: env keys, compose pass-through, config path, close-family roles, preflight home-base check and UI labels |
| get-started/what-a-gpu-or-a-model-adds.md | 15 | 1 (A-21) | Accurate. One gap for native Mac installs |
| make/improve-a-film.md | 15 | 2 (A-12, A-19) | Accurate. Link text and a missing web route |
| make/memory-types.mdx | 30 | 4 (A-3, A-11, A-12, A-18) | One real trap: the length unit in the web UI |
| make/titles-maps-music.md | 35 | 6 (A-1, A-4, A-5, A-11, A-13, plus A-16 note) | **One blocker**: you cannot choose a title style in config |
| make/photos-and-live-photos.md | 20 | 2 (A-2, A-17) | Config key given without its section, and that breaks config load |
| make/automate.md | 30 | 3 (A-5, A-6, A-23) | Commands and keys are right. The notification example uses plain HTTP and has no Docker route |
| make/free-text.md | 20 | 2 (A-7, A-8) | Behaviour verified in `_ask_generation.py`. Two steps don't say how to do them |
| make/web-ui.mdx | 25 | 4 (A-9, A-10, A-11, A-12) | Labels exist. Page roles are framed slightly wrong |
| src/components/InstallationFiles, ThemedScreenshot, Video | 10 | 1 (A-20) | Correct. Image tag scheme (no `v`) matches release.yml:666 |

Totals: about 395 claims checked, 23 findings.

## 2. Findings

### A-1 [BLOCKER] make/titles-maps-music.md:36 (heading "Styles", line 34): a title style can't be chosen in configuration
- Claim: "Choose a title style in your configuration, then try a preview before rendering the whole film:" followed by `titles test --style elegant_minimal`.
- Reality: the config schema accepts only `title_screens.style_mode: auto | random`. A named style such as `elegant_minimal` fails validation, so the whole config fails to load. The renderer can take a named style (titles/generator.py:167-170, "or specific style name"), but the schema never lets one through. Only `titles test --style` takes a name, and that only previews. The reader can't do what the page says.
- Evidence: src/immich_memories/config_models_render.py:294 `style_mode: Literal["auto", "random"]`. Run: `TitleScreenConfig(style_mode='elegant_minimal')` -> `REJECTED ... Input should be 'auto' or 'random' [type=literal_error]`. reference/output-rendering.md:49-51 documents only auto and random.
- Fix: replace line 36 with "Titles pick a palette from the film's mood (`title_screens.style_mode: auto`, the default) or a random named style (`random`). You can preview each named style before rendering:". Alternatively, widen the Literal to the five style names. That is a product call, because generator.py already handles names.
- Confidence: VERIFIED

### A-2 [GAP] make/photos-and-live-photos.md:41 and :18: config keys given without a section; the bare key breaks config load
- Claim (41): "Disable `include_live_photos` to use the stills only." Claim (18): "or disable photos in the configuration."
- Reality: the key is `analysis.include_live_photos`. `analysis` is a Tier-2 section, so in YAML it goes under `advanced:` (or top-level `analysis:`). Env form: `IMMICH_MEMORIES_ANALYSIS__INCLUDE_LIVE_PHOTOS=false`. A reader who writes the bare key at the top of config.yaml gets a config that does not load. The photos switch is `photos.enabled`, and the page never names it. Neither line mentions the web UI checkboxes (**Include photos**, **Include Live Photos** under **Length and pictures**) or `--no-live-photos`.
- Evidence: src/immich_memories/config_models_analysis.py:74; config_loader.py:58-75 (`_TIER2_SECTIONS` contains `analysis`); config_models_render.py:332-335 (`PhotoConfig.enabled`). Loading a YAML containing only `include_live_photos: false` through `Config.from_yaml` gives `include_live_photos  Extra inputs are not permitted [type=extra_forbidden]`. web/src/routes/create/+page.svelte:487-488.
- Fix (41): "To use the stills only, untick **Include Live Photos** under **Length and pictures**, pass `--no-live-photos`, or set `advanced.analysis.include_live_photos: false`." Fix (18): "...pass `--no-photos`, untick **Include photos**, or set `photos.enabled: false`."
- Confidence: VERIFIED

### A-3 [GAP] make/memory-types.mdx:28: the web UI takes the length in minutes, and portrait is a separate render choice
- Claim: "Set a length when you have a destination in mind, such as a 30-second portrait film."
- Reality: the web field is "Length in minutes (fitted to the pictures when empty)", with `min="0.5" step="0.5"`, and the value is multiplied by 60. A reader who types 30 asks for a 30-minute film. Portrait is set separately, under **Orientation** in the Render panel. On the CLI, `--duration 30` sets seconds and `--short-form 30` sets 30 s and makes the film vertical.
- Evidence: web/src/routes/create/+page.svelte:479 and :154 (`duration: minutes ? Math.round(minutes * 60) : null`); web/src/lib/RenderPanel.svelte:169-173; `generate --help`: `--short-form [15|30|60|90]  Short-form preset: sets the duration and makes the video vertical`.
- Fix: "Set a length when you have a destination in mind. In the web UI it is in minutes under **Length and pictures** (0.5 is 30 seconds); pick **Portrait** under **Orientation** when you render. On the CLI, `--short-form 30` does both."
- Confidence: VERIFIED

### A-4 [GAP] make/titles-maps-music.md:39: `titles test` in Docker writes where the container user can't write and the host can't see
- Claim: `immich-memories titles test --year 2025 --style elegant_minimal` (no Docker prefix, no output path).
- Reality: without `-o`, the preview is written to `Path.cwd() / "title_screen_preview.mp4"`. Under `docker compose exec`, the working directory is the image WORKDIR `/app`. That directory is created by root and isn't chowned (only `/app/output` is), and it isn't mounted on the host either. A NAS reader most likely gets a permission error, or at best a file they can't open.
- Evidence: src/immich_memories/cli/titles.py:221; docker/Dockerfile:121 (`WORKDIR /app` as root), :182-183 (only `/app/output` chowned), :193 (`USER immich`); docker-compose.yml:44 (`./output:/app/output`).
- Fix: "In Docker: `docker compose exec immich-memories immich-memories titles test --year 2025 --style elegant_minimal -o /app/output/title-test.mp4`, then open `./output/title-test.mp4`."
- Confidence: LIKELY (the command was not run in the image; directory ownership comes from reading the Dockerfile)

### A-5 [GAP] make/automate.md:62-68, make/titles-maps-music.md:16-19, :54-57: YAML only, no route for the Docker reader
- Claim: notification setup is shown only as `advanced: notifications: ...` YAML. Film language (`title_screens.locale`) and maps (`network.map_tiles`) are shown only as YAML under "Set it in your configuration".
- Reality: the primary reader runs the compose file. There, config.yaml lives inside the named volume `immich-memories-config` (`/home/immich/.immich-memories`), which a NAS user can't edit from the host. The compose file passes no `NOTIFICATIONS`, `TITLE_SCREENS` or `NETWORK` env vars. The **Settings** page can save `title_screens.locale` and `network.map_tiles`. It can save `notifications.urls` only when `IMMICH_MEMORIES_SECRET_KEY` is set, because any key named `urls` is stored as a secret.
- Evidence: docker-compose.yml:43 and :45-89 (env block); src/immich_memories/settings_store.py:46 (`_SECRET_FIELD_NAMES = ... | {"api_keys", "secret", "token", "urls"}`) and :61-63; web/src/lib/SettingsEditor.svelte:75-77 (the secrets warning); web/settings.py:101-104 (every section is listed).
- Fix: after each YAML block, add one sentence. For automate.md: "On Docker, set `IMMICH_MEMORIES_SECRET_KEY` in `.env`, recreate the container, then save the URLs in **Settings → notifications → urls** as a JSON list." For titles-maps-music.md: "On Docker, change it in **Settings → title screens → locale** (or **network → map_tiles**)."
- Confidence: VERIFIED (secret classification and env block). The Settings flow was read from code, not clicked.

### A-6 [GAP] make/automate.md:67: the ntfy example sends notifications over plain HTTP
- Claim: `- "ntfy://ntfy.sh/my-topic"`
- Reality: in Apprise, `ntfy://host/topic` is "private server" mode with `secure=False`, which means `http://ntfy.sh/my-topic`. Notification text can carry film titles, which can include names. The privacy-conscious reader gets a plaintext channel to a third party. `ntfys://ntfy.sh/my-topic` gives `secure=True`. `ntfy://my-topic` uses cloud mode, which posts to `https://ntfy.sh`.
- Evidence: `apprise.Apprise().add('ntfy://ntfy.sh/my-topic')` gives `NotifyNtfy host=ntfy.sh topics=['my-topic'] secure=False mode=private`. The `ntfys://` form gives `secure=True`. Apprise source: `cloud_notify_url = "https://ntfy.sh"`.
- Fix: replace with `- "ntfys://ntfy.sh/my-topic"`, and optionally add "Anyone who knows a public ntfy topic can read it; pick an unguessable name."
- Confidence: VERIFIED

### A-7 [GAP] make/free-text.md:16: "Prepare the period" without saying how
- Claim: "Prepare the period you want to search, and run `models fetch`..."
- Reality: when nothing is prepared, `--ask` refuses with "The store holds no library to read: run immich-memories prepare first". The page never names `prepare`. Preparation also happens when you cut a period, but the page doesn't say that either.
- Evidence: src/immich_memories/cli/_ask_generation.py:157-160; `immich-memories prepare --help` (`--year`, `--month`, `--start/--end/--period`).
- Fix: "Prepare the period you want to search first, by cutting it once or with `immich-memories prepare --year 2025` (Docker: prefix `docker compose exec immich-memories`)."
- Confidence: VERIFIED

### A-8 [CLARITY] make/free-text.md:44: "Mark the wrong pictures ... on the run" exists only on the CLI
- Claim: "Mark the wrong pictures and describe what is missing on the run."
- Reality: marking is done only with `immich-memories report RUN_ID --wrong ASSET_ID --missing "..."`. The web run page has no control for it. A web reader will look for a button that doesn't exist.
- Evidence: `report --help` (`--wrong ASSET_ID`, `--missing TEXT`); make/cli/report.md:27-31. The web/src strings for the run and pool pages contain no "wrong" or "missing" control (only RunReport's "Include captions of flagged photos").
- Fix: "Mark the wrong pictures and say what is missing with `immich-memories report RUN_ID --wrong ASSET_ID --missing \"the red bike\"`; the marks stay on the run."
- Confidence: VERIFIED

### A-9 [CLARITY] make/web-ui.mdx:17: review and render don't happen on the Memory page
- Claim: "| **Memory** | Choose a film, cut it, review it and render it. |" and "| **Runs** | Open earlier cuts and films... |"
- Reality: when a cut succeeds, the client navigates to `/app/runs/<id>`, where the Runs nav item is highlighted. The contact sheet, Pool, Save revision and the Render panel all live there. A reader who goes back to **Memory** to render finds only the brief form.
- Evidence: web/src/routes/create/+page.svelte:244 (`goto('/app/runs/...')`); web/src/routes/+layout.svelte:21-26 (nav, active by path prefix); the run page imports RenderPanel.
- Fix: "| **Memory** | Choose a film and cut it. The finished cut opens under **Runs**, where you review and render it. |"
- Confidence: VERIFIED

### A-10 [CLARITY] make/web-ui.mdx:38: report buttons are on every run, not only failed ones
- Claim: "A failed run has **Copy report** and **Download report** too."
- Reality: `<RunReport>` renders on every run page, whatever the status.
- Evidence: web/src/routes/runs/[run_id]/+page.svelte:160 (rendered with no status condition); web/src/lib/RunReport.svelte:68-84.
- Fix: "Every run has **Copy report** and **Download report**; use them on a failed run, and review the redacted report before sharing it in an issue."
- Confidence: VERIFIED

### A-11 [POLISH] UI labels that differ from the client
- memory-types.mdx:17 "Multi-person": the UI says **Multi-Person** (web/src/lib/labels.ts:8).
- memory-types.mdx:22 "Special Day": the UI says **Special day** (labels.ts:14).
- titles-maps-music.md:63 "choose **Automatic**, **No music**, or upload your own": the radio is **Automatic (as configured)** and the button is **Upload a track** (RenderPanel.svelte:212, :223).
- titles-maps-music.md:12 "type a **Title**": the field label is "Title (decided as generate decides when empty)". There is also a **Who names the film** select, which the page doesn't mention (RenderPanel.svelte:158-167).
- Fix: use the exact labels above.
- Confidence: VERIFIED

### A-12 [POLISH] Link text that doesn't match the target page's title
- web-ui.mdx:26 "[Choose a memory]": the target's title is "Choose a film".
- web-ui.mdx:46 "[People and home]": the target's title is "Home and people".
- improve-a-film.md:27 "[Memory types]": the target's title is "Choose a film".
- Fix: match the titles (introduction.mdx already uses "Home and people" and "Choose a film").
- Confidence: VERIFIED

### A-13 [POLISH] make/titles-maps-music.md:87: stale custom anchor
- Claim: `## Generated music {#install-locally-on-a-mac}`
- Reality: the section has no Mac install steps; it just links to better/music.md. Nothing in the repo links to `#install-locally-on-a-mac` (grep over md/mdx/py/ts/svelte/yml finds only this heading and reference/output-rendering.md:331, which carries the same id). The id is kept for old external links, but it promises content that isn't there.
- Fix: drop the custom id (or add a redirect note), so the anchor reads `#generated-music`.
- Confidence: VERIFIED (that nothing in the repo links to it). External inbound links: unknown.

### A-14 [CLARITY] get-started/quick-start.md:9: "25 GB of disk for this container"
- Claim: "...4 GB of RAM and 25 GB of disk for this container."
- Reality: requirements.md:18 says "25 GB for the persistent data volume, plus the image and finished films". The image adds a few GB on top: Dockerfile:60 records 2.37 GB measured on arm64 with `INSTALL_EXTRAS=all`, the release default (Dockerfile:37, release.yml:415). A newcomer sizing a NAS share at 25 GB total will run short.
- Fix: "...and 25 GB of disk for its data, plus room for the image and your films."
- Confidence: VERIFIED (both texts). The image size is the Dockerfile's own measurement.

### A-15 [CLARITY] quick-start.md:9 and README.md:28 vs docker-compose.yml:11-14: cores and RAM
- Claim (quick-start): "two CPU cores, 4 GB of RAM". README: "4 GB of RAM for this container".
- Reality: the header of the compose file, which the quick start has the reader download, says "Encoding: 4-8GB RAM, 4+ cores" and caps memory at 4G (line 104). requirements.md:16-17 says 4 GiB and 2 cores ("4 cores make rendering less painful") and reports a 30-minute film under 4 GiB using swap. So the docs are consistent with each other, but the compose comment contradicts them for anyone who reads it.
- Fix: align the compose header (for example "Encoding: up to the 4 GB limit at 1080p, swap helps; 4 cores render faster; 8 GB for 4K") or have the docs say "4 cores and 8 GB for 4K".
- Confidence: VERIFIED

### A-16 [CLARITY] get-started/first-film.mdx:49: deleting the local copy isn't specific to the web
- Claim: "a successful upload removes the web render's local copy."
- Reality: every confirmed delivery removes the local output, whether it came from the CLI, the web or automation. make/cli/generate.md:85 says so for the CLI. Saying "web render's" suggests a CLI upload keeps the file.
- Evidence: src/immich_memories/generate_delivery.py:34-48 and :158/:164 (no surface condition).
- Fix: "a confirmed upload removes the local copy."
- Confidence: VERIFIED

### A-17 [CLARITY] make/photos-and-live-photos.md:45: tone-mapping on H.264-only hardware applies only on the NAS tier
- Claim: "A device with hardware H.264 but no hardware HEVC tone-maps HDR photos and companions to SDR during preparation."
- Reality: this happens only when `config.tier == "nas"`. On GPU or Full, an H.264-only device keeps HDR.
- Evidence: src/immich_memories/photos/encoding.py:40-48; src/immich_memories/processing/live_photo_merger.py:760-762.
- Fix: "On the NAS tier, a device with hardware H.264 but no hardware HEVC tone-maps..."
- Confidence: VERIFIED

### A-18 [GAP] make/memory-types.mdx:46: album subject is CLI-only and isn't named
- Claim: "A reader can also use a declared subject for collections such as cars or baking."
- Reality: the subject is `generate --from-album NAME --subject "..."` and needs a model reader. The web album form offers only the album (`album: ['from_album']`).
- Evidence: web/src/routes/create/+page.svelte:25; `generate --help` (`--subject TEXT ... Needs a model reader`).
- Fix: "With a [reader](../better/reader.md), `generate --from-album \"Bread\" --subject \"bread I baked\"` holds every picture to that subject (CLI only)."
- Confidence: VERIFIED

### A-19 [CLARITY] make/improve-a-film.md:17: rendering a saved revision again points only at the CLI
- Claim: "| Render a saved revision again | [Saved runs](cli/runs.md) |"
- Reality: the web does this too: Runs → open the run → **Render** → **What to render** → **Revision N**. That is the page's own audience.
- Evidence: web/src/lib/RenderPanel.svelte:140-145.
- Fix: "Open it in **Runs** and pick the revision under **What to render**; on the CLI, [`runs render --revision`](cli/runs.md#runs-render)."
- Confidence: VERIFIED

### A-20 [POLISH] src/components/InstallationFiles/index.tsx:21: "RC tag" text
- Claim (shown on non-release builds): "The release docs pin these files and the image to the RC tag."
- Reality: the `released` regex accepts both final and RC versions (`^v?\d+\.\d+\.\d+(?:-rc\.\d+)?$`, line 10). After 1.0.0 the release docs pin to the final tag.
- Fix: "...to the release tag."
- Confidence: VERIFIED

### A-21 [GAP] get-started/what-a-gpu-or-a-model-adds.md:19: a native Mac picks the GPU tier on its own
- Claim: the page frames GPU and Full as tiers you reach by adding something ("Make a few films on the default install first", the table "Add").
- Reality: with `tier: auto`, a Metal GPU or MLX on the host resolves to `gpu` with nothing added. The GPU tier then needs the caption service. A native Mac reader following "default install first" lands on a tier that wants a caption server. This is documented at run/requirements.md:58 and reference/caption-service.md:119, but not on this page, which is where a beginner learns about tiers.
- Evidence: src/immich_memories/config_compute.py:45-53; src/immich_memories/config_tiers.py:69-74 and :38-42 (`gpu` sets preparation `full`).
- Fix: add "On a Mac running natively, `auto` finds the Metal GPU and chooses GPU, which needs a caption service; set `tier: nas` to stay on the default path."
- Confidence: VERIFIED (code). Not run on a Mac.

### A-22 [POLISH] get-started/quick-start.md:61, :63: symptom labels don't match what the app prints
- Claim: "Missing pinned model", "Cannot connect to Immich".
- Reality: preflight prints Immich `Connection failed` (preflight.py:111/118). A missing encoder reads "public heads need the pinned DINOv2 ONNX export at ... Run `immich-memories models fetch`..." (analysis/editorial_preparation_heads.py:32-38). The column is headed "Message or symptom", so these aren't false, but a reader searching the page for their error text won't find it.
- Fix: use "Immich: Connection failed" and "...needs the pinned DINOv2 ONNX export...".
- Confidence: VERIFIED

### A-23 [CLARITY] make/automate.md:27: two overlapping upload switches; only one is named
- Claim: "configure `upload.enabled` and `upload.album_name` if films should arrive in Immich".
- Reality: that works, because the automatic `generate` child reads `upload.enabled` (cli/_run_inputs.py:63). But automation also has `automation.upload_to_immich` and `automation.album_name` (config_models_automation.py:62-63). When `automation.upload_to_immich` is set, `automation.album_name` is passed as `--album` and wins over `upload.album_name` (automation/runner.py:612-619; generation_request.py:136-139; cli/_pipeline_runner.py:578). A reader who finds both in Settings can't tell which applies.
- Fix: "`upload.enabled` covers every film; `advanced.automation.upload_to_immich` and `automation.album_name` apply only to automatic runs and take precedence for their album."
- Confidence: VERIFIED

## 3. Unverifiable claims

- quick-start.md:30 Immich menu path "Account Settings > API Keys > New API Key": this is Immich's own UI, outside this repo. example.env:12 uses the same wording.
- quick-start.md:47 `ssh -L 8080:localhost:8080 you@your-nas`: correct against the compose 127.0.0.1 binding. I believe Synology DSM's sshd can ship with `AllowTcpForwarding no`, which would make the tunnel fail silently; I couldn't check that here. Worth a check on a DSM box.
- photos-and-live-photos.md:24, :28 "continuous 4.5-second shot", "8.1 seconds": the merged MP4s are Git LFS pointers in this checkout (`version https://git-lfs.github.com/spec/v1`), so I couldn't probe them. The source counts (3 and 6) match the files in docs-site/static/demos/live-photos/. The docs deploy pulls LFS (docs.yml `git lfs pull`), so the site serves the real files.
- welcome/how-this-was-built.md: dates, commit counts (22 commits on December 29, 56 days, 127 days, 51 builds), sizes (27 GB, 2.2 GB, 550 MB, 108 GB), test counts, the 47,528 and 10,142 deleted lines, and all quotes. The clone is shallow (50 commits) and the GitHub repo was created on 2026-03-06 (`gh api repos/...` `created_at`), so the history before March isn't reachable. What I could check holds: #764 is "refactor(selection): selection becomes an edit..." and #1033 is "ffprobe failed to inspect output artifact on large output, video was actually valid (false failure)"; the 500-to-800-line cap matches CLAUDE.md; the store is SQLite or PostgreSQL. Line 107 says the SvelteKit client "replaced it in one pull request". web/src/routes/+layout.svelte:20 has a comment describing a migration in slices ("each slice of #1395 moves one"). Not contradictory enough to report.
- welcome/about.mdx:7-9 (400 clips, Premiere, two hours): personal narrative.
- who-is-who.md:43 "A person film also uses the relationships you confirmed": not traced to code.
- automate.md:39 "Trips wait until after you are home and birthdays wait a little": matches reference/automation-contract.md:91 (7 days and 2 days). The detector code wasn't traced.
- titles-maps-music.md:59 "Maps add time to the finished film beyond the picture budget": plausible from the map timing keys (config_models_render.py:251-262), but the budget arithmetic wasn't traced.
- automate.md:27 "The time uses the container's timezone (TZ)": the scheduler uses `datetime.now().astimezone()` (automation/in_process_scheduler.py:50-56), so it is correct as long as the image has zone data. python:3.11-slim normally ships tzdata; I didn't run a container to confirm.

## Not re-reported (already known, nothing new found)
Docs not published for RCs (confirmed again: docs.yml skips `prerelease`). App-owned reader is impossible in Docker (what-a-gpu:19 repeats "inside the app on Linux or macOS"). The compose captioner comment says set tier to full. The release bundle doesn't repin the inference image tag (InstallationFiles' override pins only the app service; `INFERENCE_TAG` stays `latest`).
