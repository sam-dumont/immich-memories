---
title: One month, three tiers
description: Real Basic, GPU and Full cuts of the same CC0 fixture month, with films and limits.
---

import StaticFile from '@site/src/components/StaticFile';

import Video from '@site/src/components/Video';

# One month, three tiers

These are finished films from the same June 2024 fixture library: 133 assets and three
synthetic people in a disposable Immich instance. The pictures are
<StaticFile href="/demo/tier-fixture-credits.txt">credited CC0 stock photographs</StaticFile>;
the dates, names and household story are invented. No personal library was used. The linked
provenance files record the code revisions, software and models used for these examples.

Every request asked for a 60-second monthly highlight with photos, family sharing and template
titles. Upload was disabled.

## Basic and GPU

Asking for the same June 2024 month, Basic and GPU each kept 14 shots and all four favourites.
Twelve sources overlapped; GPU selected two different videos.

| Basic | GPU |
|---|---|
| ![Basic at 37 seconds: a swimmer underwater.](/demo/basic-gpu/basic-IMG_2501.jpg) | ![GPU at 37 seconds: a mountain lake and tents.](/demo/basic-gpu/gpu-IMG_2491.jpg) |
| `IMG_2501.mp4` | `IMG_2491.mp4` |
| ![Basic at 48 seconds: a lake below a mountain and forested shore.](/demo/basic-gpu/basic-IMG_2524.jpg) | ![GPU at 48 seconds: a waterfall and green rock face.](/demo/basic-gpu/gpu-IMG_2521.jpg) |
| `IMG_2524.mp4` | `IMG_2521.mp4` |

Basic excluded one screen-like source; GPU excluded three (a screenshot, a scatter plot and a
logo), none of which made Basic's cut either. This shows extra source filtering, not Basic
shipping unsafe footage. Both films passed complete audio/video decoding.

<StaticFile href="/demo/basic-gpu/provenance.json">Frame and film provenance</StaticFile> records
source filenames and sampling times.

The sampled Basic and GPU films used different bundled tracks and title styles. These still
frames carry no audio; they compare which pictures made the cut. Model weights were already
cached, but each tier used a fresh, separate store. GPU had no motion evidence for seven clips.

## Basic and Full

Both films use the bundled `calm_acoustic_1.opus` soundtrack, which is
<StaticFile href="/demo/tier-music-license.txt">MIT licensed</StaticFile>.

<Video src="/demo/tier-nas.mp4" poster="/demo/tier-nas-contact.png" controls playsInline width="100%" />

![Four actual frames from the Basic film: a playground swing, misty forest, market stall and mountain scenery.](/demo/tier-nas-contact.png)

<Video src="/demo/tier-full.mp4" poster="/demo/tier-full-contact.png" controls playsInline width="100%" />

![Four actual frames from the Full film: a playground swing, birthday cake, forest fern and mountain scenery.](/demo/tier-full-contact.png)

Full used real SmolVLM captions, detectors, the cached Laya checkpoint and a local text reader.
There was no reader or caption fallback. Each cut selects 14 shots and keeps four favourites.
13 of 14 shots overlap: Basic includes `IMG_2483.jpg`; Full instead includes `IMG_2432.jpg`.
Full rejects three screen-like assets at eligibility; Basic rejects one.

| Recorded result | Basic | Full |
| --- | --- | --- |
| Finished duration | 56.0 s | 56.5 s |
| Selection wall time | 11.5 s | 42.7 s |
| Rendering wall time | 35.3 s | 35.5 s |
| File size | 36.9 MB | 36.1 MB |
| Video and audio | 1280×720 H.264, AAC | 1280×720 H.264, AAC |
| Complete decode check | Passed | Passed |

The duration is a target, not an exact output length. This is one paired example, not a quality
guarantee or a speed benchmark across every library. A changed cut is something you can watch,
not proof that one tier always makes a better film.

## Limits of these runs

In the Basic/Full pair, seven clips had no motion evidence in the Full run, so Full used plain
clip facts for them. The store and cache started fresh and were shared; Full reused Basic's facts and
acquired its own missing model facts. Basic selection used ONNX Runtime 1.28.0 and PyTorch 2.14.0;
Full selection and both renders used ONNX Runtime 1.30.0 and PyTorch 2.14.1. These recorded timings
include that environment difference. Both finished files passed `ffprobe` stream
inspection and complete video/audio decoding with `ffmpeg`.

The <StaticFile href="/demo/tier-provenance.json">sanitized provenance</StaticFile> records the
sources used and selected filenames. The fixture credit manifest records each photograph's
source and licence. No credentials or execution logs are included.

See [Measure your setup](./measured.md) for timing and cost numbers from the project's own
hardware, and [Choose your setup](../get-started/choose-your-setup.md) for what each tier adds.
