---
title: runs
---

# runs

Find previous cuts and films, read their decisions, or render another version. CLI and browser runs share the same history.

## Find a run

```bash
immich-memories runs list
immich-memories runs list --status failed
immich-memories runs show RUN_ID
```

`show` gives status, scope, output/delivery, title source, timing and system details. A partial ID works when unambiguous among the 100 most recent runs; use the full ID for older runs.

## Read the cut

```bash
immich-memories runs story RUN_ID
immich-memories runs why ASSET_ID --run RUN_ID
```

`story` shows shots in playback order, with timecode, capture date and explanation. `why` shows where one picture was kept or dropped and your current persistent decision about it.

Without an ID, `story` reads the most recent completed run; `why` uses that run unless `--run` selects another. The command reports when a decision log is unavailable.

## runs render

Render a saved cut without selecting pictures again:

```bash
immich-memories runs render RUN_ID
immich-memories runs render RUN_ID --revision 2 --no-music
```

A revision is the version saved from the browser editor. Output options such as resolution, title, music, orientation and upload can change, but the selected pictures stay fixed. Configured title or music services can still be used for the render.

For a film across accounts, the saved cut also keeps the exact file copy and the account that can read it. Moving a favourite to another copy does not change which file a replay uses.

Every render is a new run. A saved cut needs its render inputs to replay; if they are unavailable, make a fresh cut.

To listen to generated music first (requires a generator):

```bash
immich-memories music preview RUN_ID
immich-memories runs render RUN_ID --music TRACK_PATH
```

## Storage and deletion

```bash
immich-memories runs storage --json
immich-memories runs stats
immich-memories runs delete RUN_ID
```

`storage` reports directories under output and cache; loose files directly in those roots are not counted. `stats` summarizes history. `delete` removes the run record and its output; add `--keep-output` to keep the file.

To investigate slowness or failures, use [report](./report.md). Every flag: [CLI reference](../../reference/cli-reference.md#runs).
