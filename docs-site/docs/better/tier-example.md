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
trip to Nordkapp. It ran on a Mac (Apple Silicon) against a real Immich seeded with the library.
No personal library was used.

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
| Pictures held out of every film | none | 3 | 3 |
| Summary of the film | the stories in order | the stories in order | written by the reader |
| Time from request to finished film | 71 s | 99 s | 126 s |

The three pictures GPU and Full held out are views from the Reinebringen down onto Reine, in the
Lofoten islands. The document check read them as maps (`document-head:geographical_map`), which
they aren't. None of them was in Basic's cut either, so the film didn't change.

The summary is what [`runs story`](../make/cli/runs.md) prints and what goes into the Immich
description on upload. Basic and GPU list the stories: "Kit's birthday, then Lou and Pat's visit,
then The road north". Full's reader wrote: "The period included ordinary days at home and several
visits. Kit's birthday and Lou and Pat's visit were major events, while The road north was a
major trip spanning from July 12th to July 31st."

The time is one run each on one machine. Two earlier runs of the same three took 76 to 108 s
(Basic), 106 to 129 s (GPU) and 136 to 200 s (Full): read the order, not the numbers. Rendering
itself took about 23 s on every tier; the difference is preparation.

## Limits of these runs

This is one month of a small, curated library, cut once per tier. It shows what each tier adds
and what that cost here, not that one tier always makes a better or a different film. Only the
final run's timings are on this page.

The <StaticFile href="/demo/tiers/provenance.json">provenance</StaticFile> records the code
revision, the software and model versions, the exact request, and for each tier the pictures it
chose (by fixture file name), its summary, its timings and the decode check. The film passed
`ffprobe` stream inspection and a complete `ffmpeg` decode. `scripts/record_tier_example.py`
makes all of it again.

See [Measure your setup](./measured.md) for timing and cost numbers on bigger libraries, and
[Choose your setup](../get-started/choose-your-setup.md) for what each tier adds.
