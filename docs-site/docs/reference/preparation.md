---
title: Preparation and cached facts
---

# Preparation and cached facts

Preparation computes reusable picture facts before a cut. This page covers producer work, progress measurements and cache reuse; the [task guide](../make/cli/prepare.md) has the commands to start.

## `prepare`

Preparation is the part of a cut that looks at pixels: a preview, its measurements, the encoder and eight
context heads. GPU and Full add Marqo, Docling and captions; Basic leaves those two detectors off. Grouping and selection reuse those facts. Rendering still downloads and processes media, encodes frames and mixes audio.

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
head is paid for once, at the next run). Compatible facts are reused. See the
[prepared facts](../run/database.md#prepared-facts) for
refresh conditions and the `store facts status`, `migrate` and selective `refresh` commands.

The output below illustrates the report format. Its 0.948 s/picture has no recorded hardware
provenance and is not a NAS benchmark or a cold-install forecast.

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

The last line projects the measured rate onto `--library-size` pictures (1,000 unless you pass one; the
example used `--library-size 10000`). `s/picture` is the number to compare between machines; `share`
says which producer to move to a faster box. With [the inference service](../better/inference.md) the heads
and detectors run elsewhere, and a `remote_facts` row appears.

Exit 0 means every producer a cut needs finished for every picture. Exit 1 means facts are still missing, and
the run names the producer and the count. On the `full` tier the usual cause is a caption server that is not
running (a 401 or 403 names `advanced.editorial.preparation.caption_api_key`). Rerunning is cheap: run it until
it exits 0.

Preparation can send previews to the caption and inference endpoints you configure. A remote render worker receives source media separately during rendering. The default local setup sends neither. See [Privacy](../run/privacy.md).

### `--overviews` (needs Full)

```bash
immich-memories prepare --year 2024 --month 6 --overviews
```

Make it better (optional). On Full with a model reader configured, `--overviews` also reads each 90-minute episode once
and writes one account per calendar month: a couple of sentences saying what the month was. A model cut of that
month reads it as its thesis instead of paying for it during the cut. It is banked by the readings it
summarises and the model that wrote them, so a rerun over an unchanged month asks nothing. You never have to run
it: a model cut that finds no account writes its own. It is worth it when you would rather pay for a year of
months overnight. With `advanced.editorial.reader: rules` the command refuses it by name. What the account is for is on
[What a model adds](../how-it-chooses/what-a-model-adds.md).
