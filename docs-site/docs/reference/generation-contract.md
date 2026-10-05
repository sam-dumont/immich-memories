---
title: Generation and output contract
---

# Generation and output contract

`immich-memories generate` reads a period of your Immich library, drafts a film from it and renders the cut.
Basic processes pictures locally; optional remote services follow your privacy settings. It prepares only the pictures
the film can reach (the ones selection can pick, their Live Photo clips and the bursts around them), never the
whole library, and banks what it measured, so later cuts reuse compatible preparation facts. For a
whole period ahead of time, use [`prepare`](../make/cli/prepare.md).

Without `--duration` the length comes from the material the period holds, and the run prints what decided it:
see [how long a film runs](film-types.mdx#how-long-a-film-runs). With `--duration`, selection budgets the
finished film: it reserves the opening, the ending and the dividers, and credits the crossfade overlap. A
trip's map moves run on top of it ([Maps and film length](output-rendering.md#maps-and-film-length)). A
period with too little material finishes shorter rather than padding.

<Diagram name="seq-generate-reference" headline="The same five steps, with the names you'll find in the code and in the store." />
```bash
immich-memories generate [OPTIONS]
```

Every flag, with its default, is in the generated
[CLI reference](cli-reference.md#generate), or in `generate --help`. This page is
what the flags do not tell you.

`--resolution` takes the config value; `auto` matches source clips. When `--resolution` is omitted,
the command uses `output.resolution`, 1080p by default. `--quality` changes the effective CRF,
mapped onto each hardware encoder's own scale.

`--orientation` defaults to `auto`, which follows the majority orientation of the final kept clips.
Use `landscape`, `portrait` or `square` to set the canvas yourself. Orientation changes rendering
only; it does not change which pictures or video intervals are selected.

Opening titles name the people or the occasion, never the query that produced them. With a reader
configured, the model names a people or occasion film; `--llm-title` extends that to trips,
`--no-llm-title` pins the template, and `--title` and `--subtitle` override all of it. `runs show` says which
source the title came from. See [titles](output-rendering.md#where-the-title-came-from).

`--sharing` says who the film is for, and defaults to `defaults.sharing` (`family`):

```bash
immich-memories generate --memory-type monthly_highlights --year 2024 --month 6 --sharing just-us
immich-memories generate --memory-type monthly_highlights --year 2024 --month 6 --sharing shareable
```

`just-us` plays the household's private moments a caption names (a bath, a nappy change) as well,
`family` keeps them out, and `shareable` plays only what nothing held back. The planned-run summary
and `runs show` print the level. Basic uses the encoder context heads; GPU and Full add picture detectors and
Laya over captions, and sharing never asks the prose LLM. The rules:
[Sharing levels](selection-internals/family-audience-duplicates.md#sharing-levels).

Two root options go before `generate`: `-v` (or `--log-level DEBUG`) for verbose logs, and
`--preset fast` for the CPU-only profile on every knob you did not set.

## Examples

```bash
# A calendar year
immich-memories generate --year 2024

# One month, one person
immich-memories generate --memory-type person_spotlight --person "Riley" --year 2026 --month 2

# The year ending on a birthday, plus the five before it (birth date read from Immich)
immich-memories generate --year 2025 --birthday --person "Emma" --duration 900

# A child with either adult
immich-memories generate --memory-type multi_person --year 2025 \
  --people-expression '("Alex Smith" OR "Morgan Smith") AND "Riley Smith"'

# The same people, forever: no dates, so the window starts at their birth dates
immich-memories generate --memory-type multi_person \
  --people-expression '("Alex Smith" OR "Morgan Smith") AND "Riley Smith"'

# This day across the years, pinned so the run is repeatable
immich-memories generate --memory-type on_this_day --day 2026-08-31 --years-back 20

# Five Christmases in one cut
immich-memories generate --memory-type holiday --holiday christmas --years-back 5

# A day the catalogue found (see discover-days); the title comes from the catalogue
immich-memories generate --memory-type special_day --day 2016-06-12

# A day it never found; the day is the scope and the model writes the title
immich-memories generate --memory-type special_day --day 2021-04-04

# Vertical, 30 seconds, for Reels or Shorts
immich-memories generate --year 2025 --month 8 --short-form 30
```

Seven things the examples hide:

- `--people-expression` takes exact library names, binds `AND` tighter than `OR`, and works on
  date-range memories (months, years, seasons). Trips, albums and single-person presets refuse it.
- `--person` and `--people-expression` look a name up in the people registry first: a person
  there is every face cluster bound to them, in every account the run reads. A name the registry
  doesn't hold matches Immich's own people list.
- A name two registry people share picks both, and the run prints a warning listing each one
  with its id. Pass that id instead (`--person 3f2a9c1e-...`) to pick one. A UUID is always read
  as an id, never a name: a registry person's id, or an Immich person id from either account,
  which picks the registry person holding it (or just that face if nobody does). An id nothing
  holds stops the run before it reads a picture.
- `--accounts primary,partner` reads each named account (from `immich.accounts`, plus `primary`)
  into one film. Without it the primary account reads alone. A face bound to the partner's
  account only counts on the partner's pictures, and `AND` still holds strictly per picture:
  both named people must be recognised on the same picture, even if your partner's phone took
  a different shot of the same afternoon. An unknown name fails before any request. Albums and
  trips reject `--accounts` and read the primary only.
- A person or multi-person memory with no dates at all is not an error. It runs from the first day
  one of its pictures could exist to today, read off the birth dates Immich holds (and the people registry
  where Immich holds none). See [memory types](film-types.mdx#a-people-memory-with-no-dates).
  With no birth date on record anywhere it still asks for `--year`, and says why.
- Holidays follow your home base's country, and moving ones are computed for each year (Easter,
  Thanksgiving, Mother's and Father's Day), with a window of two days either side
  ([Holiday](film-types.mdx#holiday)). A holiday cut runs 60 seconds unless you pass `--duration`.
- `special_day` works on any day, catalogued or not, and requires `--day`. Several catalogued events
  on that day require `--event-id` as well; an ID with no match on the chosen day is refused. Use
  `days-export` to read the event IDs. A day with one catalogue row is scoped and named by it;
  a day without one is scoped to itself, named by `--title`
  or by the model from the day's own facts, and never written back to the catalogue.
  `immich-memories days-due` lists what the catalogue holds.

`--subject` only works with `--from-album`, and needs a model reader. It tells the editor the album
is a pool you picked for that subject, so a lone loaf or a parked car is not refused for having
nobody in it. See [an album made for one subject](film-types.mdx#an-album-made-for-one-subject).

## A film from a sentence

**Highly experimental.** Tuned on one real library and a few synthetic ones: expect wrong
translations on yours. How it reads a sentence, what works and how to report a bad result:
[A film from a sentence](../make/free-text.md).

```bash
immich-memories generate --ask "our cat along the years" --dry-run
immich-memories generate --ask "our cat along the years" --duration 120
```

`--ask` needs `tier: full` (GPU preparation, captions and a configured reader) and a prepared library: it reads the captions,
faces and place names `prepare` banked, plus the letters Immich's OCR found. It prints the
translation before anything runs, one line per decision (which words went where, the rule or
the question behind each, the votes, and how many pictures each filter kept). With `--dry-run`
it also shows which editor rules would drop pool pictures (a count and a few hashed ids per rule,
[details](sentence-parser.md#which-rules-would-drop-pictures)) and stops there. `--ask-trace FILE`
keeps the same translation and rule preview as JSON, which is where the web UI's preview reads it
from.

The sentence is the whole scope, so `--year`, `--person`, `--from-album` and the other scope flags
are refused next to it. The pool it finds is filmed like an album whose subject is your sentence,
forwarded pictures included. One occasion of one day ("our wedding") goes to the special-day
product instead. A sentence the library cannot show makes no film and says which filter emptied
it. The translation is kept with the run, for [`report`](../make/cli/report.md).

Trip detection, naming and its CLI flags are on [Film types: Trip](film-types.mdx#trip).

## What the terminal shows while it runs

One line per stage, the same record the web UI draws its rows from. A stage that counts its work
gets a bar with an estimate for that stage, not for the whole cut:

```text
⠿ Preparing previews: 352/9814 · ~19m left in this stage ━━━━━━━━━━━   3%
  ⏱ 0:41 elapsed
```

With a reader configured, a reader that stops answering is named on the line rather than going quiet. Three
drops, two then four seconds apart, and the run fails naming the endpoint.

## What a run leaves behind

Every run ends with the cut in the order it plays, then a pointer:

```text
Memory generated in 42s
  measured this run
    selection                   11s   6 planned from 6 candidates
    generation                  31s

  CHECK 2 pictures to check before sharing · immich-memories runs why <asset id> --run 20260913_083421_9dcb

  the cut, in order (6 shots, 0:24)
  June 2024
   0:00  2024-06-08  video     4 s  Lunch in the garden: the table and chairs still out on the lawn
   0:04  2024-06-09  photo     4 s  Lunch in the garden: the cake with the candles still in it
   ...
  why any picture is in or out: immich-memories runs why <asset id> --run 20260913_083421_9dcb
```

The two timings are wall-clock around the calls as they happen. [`runs`](../make/cli/runs.md) reads all of it
back later. The reasons are written for every run; `--trace-selection` only adds a copy of the
funnel at a path you choose.

The CHECK line counts the shots in the finished cut that the sensitive-content detector read between
0.2 and 0.5 and that nothing else already holds to family viewing. It is a list, not a gate: no shot
was removed or changed for it. The shots themselves are kept with the run attempt, and
`runs why` names one when you ask about it. A run with none prints
`CHECK 0 pictures to check before sharing`, which says the run looked.

### Run state

<Diagram name="state-run" headline="A run stays running until it ends one of four ways." />
A run's own record (`pipeline_runs.status`) starts `running` and ends one of four ways:
`completed`, `failed`, `cancelled` (you stopped it, from the CLI or the web UI's **Cancel**), or
`interrupted` (the process died without a chance to record why: a killed container, a crash).
Phases are tracked inside a run in order: discovery, download, analysis, selection, render,
music, delivery, complete. `runs show` prints the status and, for a run that didn't finish,
which phase it reached.

## Output

Basic tier caps the final canvas at 1080p, including an explicit `--resolution 4k` request.
Portrait output uses 1080×1920; landscape uses 1920×1080.

`--output` names the file you want, not the path you get. The name gains an 8-character recipe hash
(the same clips in the same order over the same dates hash the same), and every run writes into its own
folder, named after that file plus the run id, so a rerun never overwrites an earlier result:

```bash
immich-memories generate --year 2025 --output ~/Videos/summer.mp4
# writes ~/Videos/summer_3c9e1f0a_20260105_143052_a7b3/summer_3c9e1f0a.mp4
```

Without `--output` the file lands in the same kind of folder in `output.directory` (`~/Videos/Memories/`),
named `{people}_{memory-type}_{dates}_{hash}.mp4`, with `all` when no one is named. Confirmed Immich delivery removes the local film and its work directory. Local-only runs retain their output; `runs delete` removes a run and its output.

`--upload-to-immich --album "2024 Memories"` creates the album if it does not exist; the
persistent form is `upload.enabled: true` and `upload.album_name`.

The memory is filed on the day of its last picture, in the timezone most of its pictures share, so
it sits in your timeline where the memory ends instead of on the day you rendered it. The render
day is what you get when no picture in the cut carries a usable time.

## Two ways to skip the video

`--dry-run` is the cheap preview: it discovers the inputs and reports what preparation the period
still needs. Nothing is selected, so there is nothing to trace.

`--no-render` selects for real, with every reading and every gate, and stops at the encode. The
pictures it lists are the pictures it would have shipped, and the cut is kept as a run: it prints
the run id, `runs story <id>` reads the cut, and [`runs render <id>`](../make/cli/runs.md#runs-render)
turns it into the film later, with or without edits made in the web client. The plan it prints
ends with the title and subtitle the film would open on, so a title can be tried without producing
a file. Use it to compare settings, to time selection without paying for an encode, or to review a
cut before rendering it. The web client's **Cut** button runs exactly this command.
