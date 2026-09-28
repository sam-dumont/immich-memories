---
sidebar_position: 2
sidebar_label: "prepare, people, discover-days"
title: Preparing a library
---

# Preparing a library

Reader: power user.

Four commands that run against the library rather than against one film: `prepare` does the pixel work up
front, `people` works out who is in it, `discover-days` finds the days worth remembering, and a few small ones
answer questions before you generate anything. All of them work on a plain NAS; `prepare --overviews` is the one
that needs a model.

## `prepare`

Preparation is the part of a cut that looks at pixels: a preview, its measurements, the encoder and eight
context heads, the two detectors, and on the `full` tier a caption. Everything after it (grouping, reading,
selection, render) is text and arithmetic.

A film prepares only the pictures it can reach: the ones selection can pick, their Live Photo clips and the
shots taken in the same run. `prepare` does the whole scope instead, so every later film over it starts warm:

```bash
immich-memories models fetch                 # once, before the first run
immich-memories prepare --year 2024 --month 6
```

It prepares the month and stops: no selection, no video. The scope flags are `generate`'s (`--year`,
`--year --month`, `--start --end`, `--start --period`), and the scope is the one a cut would read: no archived
or hidden assets, no forwarded or re-encoded media, none of the films this app uploaded. `--month` needs
`--year`. Each run resumes where the last stopped, so a loop over twelve months works through a year.

Results are banked per picture, and stay free for every later cut until a producer's version changes (a new
head is paid for once, at the next run).

```text
ℹ Preparing 1,440 pictures over 1 window(s)
producer        pending   s/picture   share    elapsed
previews           1440      0.0180    1.9%       26 s
pixels             1440      0.1250   13.2%      3 min
public_heads       1440      0.6070   64.0%     15 min
detectors          1440      0.1980   20.9%      5 min
total              1440      0.9480    100%     23 min

At this rate 10,000 pictures would take 2 h 38 min.
```

`--library-size 10000` prints the last line. `s/picture` is the number to compare between machines; `share`
says which producer to move to a faster box. With [the inference service](../../better/inference.md) the heads
and detectors run elsewhere, and a `remote_facts` row appears.

Exit 0 means every producer a cut needs finished for every picture. Exit 1 means facts are still missing, and
the run names the producer and the count. On the `full` tier the usual cause is a caption server that is not
running (a 401 or 403 names `advanced.editorial.preparation.caption_api_key`). Rerunning is cheap: run it until
it exits 0.

Preparation is the only stage that can send pixels anywhere, and only to endpoints you set. On the default
install it sends nothing. See [Privacy](../../run/privacy.md).

### `--overviews` (needs a reader)

```bash
immich-memories prepare --year 2024 --month 6 --overviews
```

Make it better (optional). With a model reader configured, `--overviews` also reads each 90-minute episode once
and writes one account per calendar month: a couple of sentences saying what the month was. A model cut of that
month reads it as its thesis instead of paying for it during the cut. It is banked by the readings it
summarises and the model that wrote them, so a rerun over an unchanged month asks nothing. You never have to run
it: a model cut that finds no account writes its own. It is worth it when you would rather pay for a year of
months overnight. With `advanced.editorial.reader: rules` the command refuses it by name. What the account is for is on
[What a model adds](../../how-it-chooses/what-a-model-adds.md).

## `people`

Works out who is in your library from the numbers Immich already holds, keeps it in the store as the people
registry, and never overwrites an answer you gave it. It reads counts and dates only, and asks you nothing.

```bash
immich-memories people scan                    # build or refresh the registry
immich-memories people show                    # read it back, --tier narrows it
immich-memories people export --to people.yaml # write it out as YAML to edit or keep
immich-memories people import --from people.yaml --replace
```

The one rule doing most of the work: volume is a burst, continuity is a relationship. 160 pictures over four
active months is four events; the same 160 over forty months is part of your life.

| tier | shape |
|---|---|
| `inner` | dozens of active months, years of span, present in at least a third of the months between |
| `recurring` | a dozen months or more, failing one of the `inner` conditions |
| `episodic` | everything that is not one of the other three |
| `event` | four active months or fewer at twenty-plus pictures each: a burst |

The scan also flags tight pairs (two people who are each a quarter or more of each other's pictures), twins
(same family name and birth date, marked `counts_reliable: false` because face recognition merges them) and one
name on two person records. You are behind the camera, so pairs with you are read from month curves, not shared
frames. The owner comes from `--owner` or `IMMICH_MEMORIES_OWNER` (`identified: told`), else your Immich account
name (`account`), else the longest-running person (`inferred`: check it).

The registry lives in the [store](../../run/database.md), next to every other decision you made. Everything under
`inferred:` is recomputed on each scan; everything under `confirmed:` is yours and never overwritten, and wins
where the two disagree. `people export` writes it out in the shape below (to standard output, or to `--to FILE`
readable only by you):

```yaml
people:
  - ids: [5f2c…]
    name: Alex Example
    birth_date: '1988-04-02'
    inferred:
      tier: inner
      evidence: {count: 4210, active_months: 180, span_years: 17.2, onset: '2009-06', continuity: 0.87}
    confirmed:
      role: null
      links: []
```

`people import --from FILE` replaces the registry with an edited export. It checks the whole file first: a
person without a list of `ids`, or an id listed twice, is refused with its position, and nothing changes. Ids
come back exactly as written, `manual:` ids included. A registry that already holds people is only overwritten
with `--replace`, so an old export can't silently undo newer answers. A scan never reads the file; only an
import does.

The scan also writes its measurements (every person's counts and the pairs seen together) to
`~/.immich-memories/people-graph.json`. That one stays a file: each scan recomputes all of it from Immich and
nothing reads it back.

Upgrading from a version that kept `~/.immich-memories/people.yaml`: the store imports that file once, never
changes or deletes it, and skips anyone it already holds. An answer in the old file fills a person the store
knows but nobody answered for; it never replaces one you gave since.

It is the same registry as the **People** page in the web UI. The roles you confirm there decide who counts as close
family, and selection reads that on every tier: the family seat, the big-story rule, and the relations a model
sees. Setting it up is on [Teach it your family](../../get-started/who-is-who.md); how selection uses it is on
[Family, audience and duplicates](../../how-it-chooses/family-audience-duplicates.md).

## `discover-days`

Finds the days something happened on and keeps them in the special-days catalogue in the
[store](../../run/database.md), so a film can arrive years later without you asking ("five years ago today"). Run it once, then now and then. Films from it
are the **Surprise me** type on [Memory types](../memory-types.mdx#special-day-surprise-me).

```bash
immich-memories discover-days --since 2015
```

A day ends when the pictures stop for five hours, not at midnight. Days inside a trip are skipped (the trip film
tells that story). A holiday spent at home has its own type, so with a reader it is judged like any day
and then asked one narrow question: was its occasion the holiday itself? A Father's Day lunch is the
holiday's, and stays out; a cycling race that happened to fall on that date is a special day. With no
answer, or on a plain NAS, a holiday spent at home is skipped as before.

**On a plain NAS** (the default) nothing is asked. A day counts when one recorded fact is loud: most of its
located pictures away from home, at least three favourites, at least three videos making half the day, or a
long day (20 pictures over six active hours) with your close family on it. Each year keeps its strongest
`advanced.automation.special_days_per_year` (6): days away first, the furthest first, then favourites, then
video share, then family presence. The title is "A day in" the place. Without roles in the people registry, a long
day at home is not found.

**With a reader** (optional), every run of activity is read a month at a time as one line of recorded facts
(time, place, counts, who Immich recognised, close family by role, up to three captions), and the model names
the occasions: the kind of day people tell others about afterwards. A good afternoon at home is not one. No
yearly cap. Titles are checked against what the day recorded: a place it never went or a claim nothing supports
gets the title asked for once more, then the day is dropped.

Each proposed occasion is checked against that day's own evidence. An ordinary-day verdict drops it. An
empty or unreadable answer is asked once more; a day still without a verdict stays unjudged, and the scan
prints why (nothing written about its pictures, the reader failed, or its answer could not be read). A missing subtitle does not discard an otherwise valid confirmation, and
existing valid cached answers are reused.
The month reading compares a month's days and can miss one. So the scan also proposes, with no
model, the days whose own captions keep using words the rest of the year barely does: "race
track" and "Ferrari" on one day, where a cat or a baby written about every week cancels out. There
is no list of occasions or of words to skip. A word counts when it is written about ten or more of
the day's pictures and on at most 3% of the year's described days, and a day needs two such
words. A year with fewer than 34 described days proposes nothing this way. Every proposed day
still goes through the same day check.

A small reader can call a whole run of ordinary days occasions: a newborn's first months came back as
fifty-five "new beginnings". So a confirmed day with four or more other confirmed days within fifteen days
of it has to show what its weeks do not: at least half its captions must write a word it repeats and
that at most one neighbouring day writes at all. A day with nothing around it is never thinned (a
pregnancy test is two pictures of an ordinary day), nor is a day that stands out from its year.

Pictures forwarded to the library (sent by someone else or saved: stills with no camera in their
EXIF) are evidence, not material. They never make a day of their own and never count toward its
pictures, hours or film. On a day your camera already made, their words count for half toward
what stands out, and on a day that stands out a few of their captions reach the day check, marked
as forwarded. A day the month reading proposed is judged on its own pictures. Files saved in one
batch (three or more stamped with one exact second) count only inside the hours your own camera
was out that day, since their time is when they were saved.
A day that contains its occasion (most of its pictures at one place, a stretch the rest of the day
only frames) is asked once more about that stretch before an ordinary verdict drops it, and a
description longer than asked for is cut at a word rather than voiding the answer.

Either way a day is kept only if a film of it can run 30 seconds, and a day can carry a window (the stretch at
the circuit inside a long day) when that window holds at least half its pictures.

The scan resumes by default: years already in the catalogue are skipped. `--rescan` starts over.
`--replace --since 2024 --until 2024` re-scans those years and replaces what they hold, which is how you clean
rows `days-due` marks `stale` (judged by an older version of the question). Without either flag the scan only
ever adds to the catalogue.

```bash
immich-memories days-due              # anniversaries within three days, roundest first
immich-memories days-due --on 2026-12-24
```

The catalogue is yours to edit: a day the scan missed, a title it got wrong, two occasions to merge.
`days-export` writes it as JSON, `days-import` puts an edited file back whole. Every record keeps
exactly what you wrote; a file that is not a list of records changes nothing.

```bash
immich-memories days-export --to days.json
immich-memories days-import --from days.json
```

An install upgraded from before the store keeps its `~/.immich-memories/special-days.json`: the
upgrade copies it into the store once and never touches the file again.

## Small questions

```bash
immich-memories people          # every named person Immich knows
immich-memories years           # the years that contain video
immich-memories preflight       # can it reach Immich, the models, the renderer
```

Bare `people` lists names exactly as Immich holds them: "Emma" versus "Emma S." is the difference between a
film and an empty pool. `years` saves you guessing at `--year` on a library imported from old backups.

`analyze` and `export-project` are older commands. `analyze` counts a year's videos and prepares nothing (use
`prepare`); `export-project` writes a JSON list of the videos in scope that nothing reads back. To see how a
cut was reached, use [`runs why`](./runs.md#runs-why).
