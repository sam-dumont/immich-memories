---
title: Preparation and cached facts
---

# Preparation and cached facts

Preparation works out the picture facts a cut needs and banks them for every later cut. This page
covers what runs, how to read its report and when banked facts are reused; the
[task guide](../make/cli/prepare.md) has the commands.

## `prepare`

Preparation is the part of a cut that looks at pixels: a preview, its measurements, and one
DINOv2 encoder pass that feeds the eight context heads and the finger-over-the-lens check. GPU and
Full add Marqo, Docling and captions; Basic leaves those off. Grouping and selection then work
from the banked facts. Rendering is separate: it still downloads the media, encodes and mixes.

A film prepares only the pictures it can reach: the ones selection can pick, their Live Photo clips and the
shots taken in the same run. `prepare` does the whole scope instead, so every later film over it starts warm:

```bash
immich-memories models fetch                 # once, before the first run
immich-memories prepare --year 2024 --month 6
```

It prepares the month and stops: no selection, no video. The scope flags are `generate`'s (`--year`,
`--year --month`, `--start --end`, `--start --period`), and the scope is the one a cut would read: no
archived or hidden assets, no forwarded or re-encoded media, none of the films this app uploaded.
With `advanced.analysis.forwarded_copies_when_short` on, a cut can let forwarded copies fill a gap
and prepares those itself; `prepare` always leaves them out. `--month` needs `--year`. Each run
resumes where the last one stopped, so a loop over twelve months works through a year.

Facts are banked per picture and stay free for every later cut until a producer's version
changes; a new head is paid for once, at the next run. [Prepared facts](../run/database.md#prepared-facts)
covers when facts are refreshed and the `store facts status`, `migrate` and `refresh` commands.

The report looks like this (the timings are an illustration, not a benchmark):

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

The last line projects the measured rate onto `--library-size` pictures (1,000 by default; the
example used `--library-size 10000`). `s/picture` is the number to compare between machines;
`share` says which producer to move to a faster box. With [the inference service](../better/inference.md)
the heads and detectors run elsewhere and a `remote_facts` row appears. On GPU and Full there is
always a `captions` row: `0` pending means every picture in the scope already had its caption.

The count is pictures, not files. A Live Photo is one picture, so a month shot mostly in Live
Photos holds about twice as many files in Immich as `prepare` reports: each motion half is
prepared with its still.

| Exit | Meaning |
|---|---|
| 0 | Every producer a cut needs finished for every picture |
| 1 | Facts are still missing (the run names the producer and the count), or Immich is not configured |
| 2 | `--overviews` on a rules tier, or invalid flags |

On GPU and Full the usual cause of exit 1 is a caption server that isn't running; a 401 or 403
names `advanced.editorial.preparation.caption_api_key`. Rerunning is cheap: run it until it exits 0.

Preparation sends previews to the caption and inference endpoints you configure, and nowhere
else; the default Basic setup sends none. See [Privacy](../run/privacy.md).

### `--overviews` (needs Full)

```bash
immich-memories prepare --year 2024 --month 6 --overviews
```

Optional. On Full with a model reader configured, `--overviews` also reads each 90-minute episode
once and writes one account per calendar month: a couple of sentences saying what the month was.
A model cut of that month then judges shots against it instead of paying for it during the cut.
(The film's own summary is a separate question, asked of the stories that film shows.) The
account is banked by the readings it summarises and the model that wrote them, so a rerun over
an unchanged month asks nothing.

You never have to run it: a model cut that finds no account writes its own. It pays when you'd
rather spend a year of months overnight. On Basic or GPU the command refuses it. What the account
is for is on [What a model adds](../how-it-chooses/what-a-model-adds.md).
