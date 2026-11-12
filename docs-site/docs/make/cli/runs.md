---
title: runs
---

# runs

Find previous cuts and films, read their decisions, or render another version. CLI and browser runs share the same history.

In Docker, run these commands from the installation folder with
`docker compose exec immich-memories` before `immich-memories`.

## Find a run

```bash
immich-memories runs list
immich-memories runs list --status failed
immich-memories runs show RUN_ID
```

`show` gives status, scope, output, title source, timing and system details. For a film sent to Immich it adds the delivery state, the album and a link to the video; the output line says when the local copy was removed after delivery. A partial ID works when unambiguous among the 100 most recent runs; use the full ID for older runs.

A run whose process is gone (killed, crashed, machine restarted) reads `interrupted` in `list`, `show` and the browser. A run still going in another terminal stays `running`.

## Read the cut

```bash
immich-memories runs story RUN_ID
immich-memories runs why ASSET_ID --run RUN_ID
```

`story` shows shots in playback order, with timecode, capture date and why each one plays: who is on it, what it shows or where it was taken, and what set it apart (a star, a video, the only frame with someone in it). A story that
joins many places is named by its first two and a count of the rest. `why` shows where one picture was kept or dropped and your current persistent decision about it.

Without an ID, `story` reads the most recent completed run; `why` uses that run unless `--run` selects another. The command reports when a decision log is unavailable.

## runs render

Render a saved cut without selecting pictures again:

```bash
immich-memories runs render RUN_ID
immich-memories runs render RUN_ID --revision 2 --no-music
```

A revision is the version saved from the browser editor. Output options such as resolution, title, music, orientation and upload can change, but the selected pictures stay fixed. Configured title or music services can still be used for the render.

For a film across accounts, the saved cut also keeps the exact file copy and the account that can read it. Moving a favourite to another copy does not change which file a replay uses.

Every render is a new run, with its own id: `runs render` and the browser's **Render** both make one. The finished film goes under `output.directory`. `runs upload` takes that render run's id, not the cut's; on a cut that was never rendered it says so and points back here. Once Immich confirms the upload, `runs upload` removes the local film and says so; a failed or incomplete upload keeps it. A saved cut needs its render inputs to replay; if they are unavailable, make a fresh cut.

To listen to generated music first (requires a generator):

```bash
immich-memories music preview RUN_ID
immich-memories runs render RUN_ID --music TRACK_PATH
```

## Re-label a film already in Immich

A film in Immich can lose its description (a slow metadata read took it back), or the label format can change between releases. Rendering it again for a few bytes of text costs about 30 minutes per 10-minute film and leaves a second copy in Immich. `runs label` writes the label again instead:

```bash
immich-memories runs label RUN_ID
immich-memories runs label --all
```

`RUN_ID` is the render run's id, the one `runs upload` or the delivery recorded the Immich asset on. The label is rebuilt from the stored run with the same code the upload uses, written to the asset it was delivered as, then read back after Immich settles. The settle window grows with the film's stored size, so a long film's slow re-read does not take the new label back.

What it does to tags:

- It adds the description, the `immich-memories/generated` tag, the release and day tags, and with `upload.film_tags: true` the type, year and story tags.
- It removes the app's own `version/`, `generated-on/`, `type/`, `year/` and `story/` tags under `immich-memories/` that the current label no longer has. With `upload.film_tags` off, a film's old type, year and story tags go too.
- It never touches a tag outside those: yours, or anything else under `immich-memories/`.

Each run is reported as one of: `written`, `unchanged` (the label already matches, nothing is sent), `asset gone from Immich`, or `rights missing` (the key needs `tag.create`, `tag.asset` and, for the description, `asset.update`). `--all` goes through every run with a recorded Immich asset and keeps going when one fails. The exit code is 1 when a run's key lacks the rights, a write failed or did not stay, or a single named run's film is gone.

The run page has the same action: **Update the Immich label**, for a delivered run.

## Storage and deletion

```bash
immich-memories runs storage --json
immich-memories runs stats
immich-memories runs delete RUN_ID
```

`storage` reports directories under output and cache; loose files directly in those roots are not counted. `stats` summarizes history. `delete` removes the run record and its output; add `--keep-output` to keep the file. Deletion asks for confirmation; use `--yes` for an intentional scripted deletion.

To investigate slowness or failures, use [report](./report.md). Every flag: [CLI reference](../../reference/cli-reference.md#runs).
