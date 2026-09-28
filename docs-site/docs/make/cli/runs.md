---
sidebar_position: 5
title: runs
---

# runs

Reader: power user.

Every `generate`, from the CLI or the web UI, writes a run row: how long it took, how many clips it processed,
where the title came from, the model's call count and cost when a model was used, errors, system info. It does
not record render settings. `runs` reads that history back, and `runs story` and `runs why` are how you find out
what the editor did and why. Every flag
is in the [CLI reference](../../reference/cli-reference.md#runs).

## runs list

```bash
immich-memories runs list                          # the last 20
immich-memories runs list --status failed
immich-memories runs list --person "Emma" --limit 5
```

`--status` takes `completed`, `failed`, `running`, `cancelled` or `interrupted`.

## runs show

```bash
immich-memories runs show 20260105_1430
```

Status, date range, clip counts, **Title From**, output file, duration and size, **Sharing** (who the cut was
for: just us, family or shareable; `runs story` prints it too), the phase-by-phase timing,
and the machine it ran on (CPU, GPU, RAM, FFmpeg version).

**Title From** is the source of the opening title: `override` (you typed it), `album`, `occasion`, `model`,
`place` (a trip) or `fallback` (the template). The table is on
[Titles](../titles-maps-music.md#where-the-title-came-from).

A run whose cut was checked against its promises also prints `Cut checks: N broken promise(s)`; the rows are in
the attempt's `derived-decisions/cut-invariants.private.json` (see
[How it chooses](../../how-it-chooses/overview.md)).

A partial run id matches if it is unambiguous among the 100 most recent runs. Older than that, a
unique prefix still reports "Run not found": use the full id.

### Model spend

The **Model** block: calls, judgment-cache hits, tokens, wall time, and any thinking calls truncated at the
token budget. A run that made no model call (every NAS run) prints no such block. It is reported per run, not
per phase: the tracked phases (clip extraction, assembly, music) all come after selection, and selection is
most of the model budget, so a per-phase total would understate the bill.

## runs story

The cut of a run in the order it plays: one line per shot with its timecode, capture day, kind
(photo or video), length, the story it was granted to and the reason the editor wrote. A month
change prints as a chapter line. It is the same record the web UI's contact sheet draws.

Timecodes and lengths are the film's, not the plan's: the renderer fits the selected seconds into the
timeline's content budget and the opening card plays before the first picture, and both are applied here. The
header gives the pictures and videos, then about how long the film runs. That last number is an estimate until
the file exists, because smart transitions decide fade or cut at each boundary. `runs show` prints the duration
measured from the render.

```bash
immich-memories runs story              # the most recent completed run
immich-memories runs story 20260913_08  # a run id or a unique prefix
immich-memories runs story ~/.immich-memories/cache/editorial-runs/june/attempts/a1   # an attempt directory
```

The end-of-run block of `generate` prints the first eight shots and this command for the rest.

## runs why

What a run decided about one picture: the passes it survived, the pass that dropped it and the
reason, and, when it made the cut, where it plays.

```bash
immich-memories runs why 3f1c9a2e-... --run 20260913_08   # --run defaults to the latest completed run
```

Every run writes its decision log (`selection-trace.private.json`) beside its plan, so this works without
`--trace-selection`. A run with no log answers "left no decision log".

A picture on the run's check-before-sharing list gets one more line, naming what the
sensitive-content detector read for it and the hold it sits under:

```text
  worth a look before sharing: the exposure head read 0.35, under the 0.5 hold
```

When you trimmed or removed the picture while reviewing the cut before rendering it, a line says so:
`Your review: you trimmed it to 1-3.5 s.` The web UI keeps each review's edits in the store.

The last line is your own word on the picture as it stands today, which may be newer than the run:
`Your word on it now: You cleared its hold (a nudity detector flagged it).`, or, where a hold stands
and you haven't answered it, the hold and the [`pictures clear-hold`](./pictures.md) command that
lifts it.

Both commands find the run through the run id, which the CLI and the web UI share: a memory cut on
the page can be read from the terminal and the other way round.

## runs render

```bash
immich-memories runs render                      # the latest completed run, as it was cut
immich-memories runs render 20260927_080000_cafe --revision 2 --no-music
```

Renders a finished cut again, or one of the revisions the web client saved, without selecting
anything: no model is asked and no rule runs again. The cut's own render inputs are read back
from its attempt directory, the revision's removals, trims, screen times, swaps and added pool
pictures are applied
the way the web export applies them, and the film goes through the same engine as `generate`.
It lands in your output folder and shows up in `runs list` as a new run.

It takes `generate`'s output flags under the same names: `--title`, `--subtitle`,
`--llm-title/--no-llm-title`, `--transition`, `--resolution`, `--orientation`, `--scale-mode`,
`--format`, `--quality`, `--music`, `--no-music`, `--music-volume`, `--add-date`, `--add-place`,
`--privacy-mode`, `--upload-to-immich`, `--album`. The length is the cut's, unless a revision
keeps more than the titles left room for: then the film grows to hold it.

`generate --no-render` and then `runs render` is a cut and its film in two steps. A cut made
before this version kept no render inputs; `runs render` says so, and `generate` cuts it again.

To hear the music before rendering, `immich-memories music preview RUN` generates the track this
cut would get, from its own timeline and the mood its text reads as, and prints where it wrote
it; `runs render RUN --music PATH` then uses exactly that track. It needs a music generator
(`advanced.musicgen` or `advanced.ace_step`) and says so when there is none.

## runs stats

```bash
immich-memories runs stats
```

Total runs, completed and failed as raw counts, total video generated, total and average
processing time, and average and total clips processed. No completion rate.

## runs delete

Removes the run and its output file. `--keep-output` deletes the record only, `--yes` skips the
confirmation prompt for scripts.

```bash
immich-memories runs delete 20260105_143052_a7b3
```

## runs storage

Where the space went under the output and cache roots, changing nothing. It groups by run status
and lists the ten largest directories, and it walks directories only, so loose files sitting
directly in a root count as nothing.

```bash
immich-memories runs storage --json
```

## Report a run

`immich-memories report [RUN_ID]` prints a redacted report for a GitHub issue. Without an ID it uses the
latest run. Add `--json` for tooling or `--bundle report.zip` for the full report and logs. Read it before
sharing it. The command makes no network requests.

Free-text memories (caption threads, #1436) will add their redacted request and selection funnel.
No run records that section yet, so today's reports don't have it. Once they do, the captions of
photos you flagged, and why they were flagged, stay out unless you pass `--include-flagged-captions`.
Review that text before sharing. Pictures are never attached.

`runs show` also prints the saved span tree, rates per item, and the uncovered part of the run's wall
clock. `prepare` records a run too. Older runs keep the timings they originally recorded.
The setup matrix copies these same measurements from each attempt's `timings.private.json`.
