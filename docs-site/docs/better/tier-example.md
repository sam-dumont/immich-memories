---
title: One month, three tiers
description: The same demo month cut for real on Basic, GPU and Full, what changed and what didn't.
---

import StaticFile from '@site/src/components/StaticFile';

import Video from '@site/src/components/Video';

# One month, three tiers

July 2025 of the demo library, cut once on each tier: Basic, GPU and Full. The library is
[Wikimedia Commons photographs](https://github.com/sam-dumont/immich-memories/blob/main/tests/e2e/fixtures/library/CREDITS.md)
(CC0 or CC BY) with an invented household on top: Kit's birthday, the grandparents' visit, a road
trip to Nordkapp. It ran on a development build of 1.0.0 (between rc.10 and rc.11), on an M5 Max
Mac with 128 GB, against a real Immich seeded with the library. No personal library was used.

Every tier got the same request: a 60-second monthly highlight, photos on, family sharing, the
app's own title, and the same bundled track (`calm_acoustic_1.opus`, MIT licensed like the rest of
the [bundled music](https://github.com/sam-dumont/immich-memories/blob/main/packages/immich-memories-music/LICENSE-MUSIC)).
Each tier had its own home, so nothing one tier prepared reached the next.

## The film

All three tiers picked the same 15 shots, in the same order, and rendered frame-identical films.
This is that film:

<Video title="The July 2025 film, the same on Basic, GPU and Full" src="/demo/tiers/month.mp4" poster="/demo/tiers/month-contact.jpg" controls playsInline width="100%" />

![Four frames from the film: Kit's birthday cake, the museum in its park in Tervuren, Charlie and Robin with Kit, a red farmhouse below the mountains on the road north.](/demo/tiers/month-contact.jpg)

On this month the people, the favourites and the stories settle every pick before a caption gets
a say: three shots of Kit's birthday, the only picture of Pat, the visit, then the road north. A
library with more lookalike pictures per moment gives the extra evidence more to decide.

## What changed

| | Basic | GPU | Full |
| --- | --- | --- | --- |
| Shots in the cut | 15 | 15 | 15 |
| Pictures checked by the local classifiers | 1,131 | 1,131 | 1,131 |
| Captions written (local SmolVLM server) | none | 15 | 15 |
| Calls to the text reader (a local model) | none | none | 6 |
| Summary of the film | none | none | none |
| Time from request to finished film | 54 s | 76 s | 95 s |

No tier wrote a summary because none was asked for. Model-written titles and the summary are
experimental and off by default (`title_screens.llm_titles`, or `--llm-title` for one run). Turn
them on and the summary is what [`runs story`](../make/cli/runs.md) prints and what goes into the
Immich description on upload. Full still asks its reader with them off: 26 model calls in that
run, 20 of them the captions and other preparation, 6 to the reader refining the rules draft.

The time is one run per tier on one machine: read the order, not the numbers. Rendering took
28 s on Basic, the first run, and 19 s on GPU and Full; the rest of the gap is preparation (24 s on
Basic, 56 s on GPU, 74 s on Full).

This is one month of a small, curated library, cut once per tier. It shows what each tier adds
and what it cost here, not that one tier always makes a better or a different film.

The <StaticFile href="/demo/tiers/provenance.json">provenance</StaticFile> records the code
revision, the software and model versions, the exact request, and for each tier the pictures it
chose (by fixture file name), its summary, its timings and the decode check. The film passed
`ffprobe` stream inspection and a complete `ffmpeg` decode. `scripts/record_tier_example.py`
makes all of it again.

See [Measure your setup](./measured.md) for timing and cost numbers on bigger libraries, and
[Choose your setup](../get-started/choose-your-setup.md) for what each tier adds.
