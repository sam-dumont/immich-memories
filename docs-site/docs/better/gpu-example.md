---
title: Basic and GPU on the same month
description: Two changed shots and the source filters behind a real CC0 comparison.
---

import StaticFile from '@site/src/components/StaticFile';

# Basic and GPU on the same month

Both tiers made a complete film from the same 133 public CC0 assets, asking for a 60-second
June 2024 month with photos. Each kept **14 shots and all four favourites**. Twelve sources
overlapped; GPU selected two different videos. No text reader was enabled.

The pictures are <StaticFile href="/demo/tier-fixture-credits.txt">credited CC0 stock photographs</StaticFile>, with clips
made by panning those photographs. Dates, people and location labels are invented fixture
metadata, not facts about where the photographs were taken.

## Two choices you can see

These frames come from the actual completed films, sampled at 37 and 48 seconds. They show
which sources each cut chose, not exact shot boundaries or a claim that one choice is better.

| Basic | GPU |
|---|---|
| ![Basic at 37 seconds: a swimmer underwater.](/demo/basic-gpu/basic-IMG_2501.jpg) | ![GPU at 37 seconds: a mountain lake and tents.](/demo/basic-gpu/gpu-IMG_2491.jpg) |
| `IMG_2501.mp4` | `IMG_2491.mp4` |
| ![Basic at 48 seconds: a lake below a mountain and forested shore.](/demo/basic-gpu/basic-IMG_2524.jpg) | ![GPU at 48 seconds: a waterfall and green rock face.](/demo/basic-gpu/gpu-IMG_2521.jpg) |
| `IMG_2524.mp4` | `IMG_2521.mp4` |

## What the extra checks did

Basic excluded one screen-like source. GPU excluded three: a screenshot, a scatter plot
and a logo. The two additional exclusions were absent from Basic's finished cut too.
This run therefore shows extra source filtering; it does not show Basic shipping unsafe footage.
Both intent checks passed with the same coverage and no violations.

## What this run establishes

The films were 57 seconds (Basic) and 56.5 seconds (GPU), at 1080p H.264 with stereo AAC.
Both passed complete audio/video decoding. They used the same candidate package and public
options on an M5 Max, with separate fresh stores, picture facts and output. Model weights
were warm and the existing caption server was reused. The candidate still called Basic `nas`.

Default title styles and bundled music differed between runs. GPU logged seven clips without
motion facts and an uncalibrated Laya confidence bucket. This is one observed change, without
independent human quality grading. It does not establish that GPU always makes a better film.

<StaticFile href="/demo/basic-gpu/provenance.json">Frame and film provenance</StaticFile> records source filenames,
sampling times, candidate commit and SHA-256 hashes. The separate
[Basic and Full example](./tier-example.md) adds a text reader and uses a different run setup.
