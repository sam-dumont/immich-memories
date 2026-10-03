---
title: Special-day discovery
---

# Special-day discovery

## `discover-days`

Finds the days something happened on and keeps them in the special-days catalogue in the
[store](../run/database.md), so a film can arrive years later without you asking ("five years ago today"). Run it once, then now and then. Films from it
are the **Special day** type on [Memory types](film-types.mdx#special-day).

```bash
immich-memories discover-days --since 2015
immich-memories discover-days --since 2015 --also-skip 09-14 --also-skip "ascension day"
```

Repeat `--also-skip` to add household dates (`MM-DD`) or holiday names to the calendar. These
receive the same holiday handling below; the flag does not unconditionally exclude a different
occasion that happened on that date.

A day ends when the pictures stop for five hours, not at midnight. Days inside a trip are skipped (the trip film
tells that story). A holiday spent at home has its own type, so with a reader it is judged like any day
and then asked one narrow question: was its occasion the holiday itself? A Father's Day lunch is the
holiday's, and stays out; a cycling race that happened to fall on that date is a special day. With no
answer, or on Basic, a holiday spent at home is skipped as before.

**On Basic** (the default) nothing is asked. A day counts when one recorded fact is loud: most of its
located pictures away from home, at least three favourites, at least three videos making half the day, or a
long day (20 pictures over six active hours) with your close family on it. Each year keeps its strongest
`advanced.automation.special_days_per_year` (6): days away first, the furthest first, then favourites, then
video share, then family presence. The title is "A day in" the place. Without roles in the people registry, a long
day at home is not found.

**On Full tier** (optional), every run of activity is read a month at a time as one line of recorded facts
(time, place, counts, who Immich recognised, close family by role, up to three captions), and the model names
distinct occasions rather than recurring everyday activity. This is a discovery heuristic; it can miss a day that matters to you. Choose a Special day date explicitly or edit the catalogue when that happens. No yearly cap. Titles are checked against what the day recorded: a place it never went or a claim nothing supports
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

A confirmed day is named by its moment when its name misses what made it stand out. A day that held
a baby at home and a concert that night came back "Baby's Day in Jette": the reader named what came
first. The pictures that write the day's own unusual words, taken close together, mark its moment;
when the day's title names none of those words, the moment is asked about alone, and an occasion
found there gives the day its name and its window. The moment only renames: it never makes an
ordinary day an occasion.

A small reader can call a whole run of ordinary days occasions: a newborn's first months came back as
fifty-five "new beginnings". So a confirmed day with four or more other confirmed days within fifteen days
of it has to show what its weeks do not: at least half its captions must write a word it repeats and
that at most one neighbouring day writes at all. A day with nothing around it is never thinned (a
pregnancy test is two pictures of an ordinary day), nor is a day that stands out from its year.

A picture stored as several files counts once. A shared album keeps the camera's file and a smaller copy
under the same name at the same instant; discovery reads the full-size one, with a star either file
carries, the same way the editor does (one 2024 held 2,368 such copies in 21,520 files).

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
