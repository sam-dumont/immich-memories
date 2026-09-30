---
title: How this was built
---

# How this was built

This started in December 2025 as a birthday film for my son. Nine months later it had gone through three web UIs, four assembly engines and several approaches to choosing pictures.

A few decisions survived all that work.

## Choosing is editing

The early version scored each picture and took the best scores. It could produce a technically decent film and miss the point: a positive pregnancy test lost to a sharpness threshold in a film about my son's first year.

The current editor starts with moments and stories instead. A birthday or a week away gets room as a story, not because every picture scored well. Favourites and confirmed relationships tell it what matters. You can review the result before rendering.

[How it chooses](../how-it-chooses/overview.md) describes the current behavior.

## The NAS became the default

My Mac could run models. Most people installing beside Immich already have a NAS, and asking them to host another model before making one film was a bad starting point.

The rules editor now makes the whole film on a CPU. GPU inference adds captions and checks; a text model can refine the draft. The extra services improve an existing result instead of being the price of entry.

[Optional upgrades](../get-started/what-a-gpu-or-a-model-adds.md) explains the difference.

## Rendering had to fit

One long FFmpeg crossfade chain over twelve 4K clips produced the right picture and ate the machine's memory. Chunking brought the peak down to 2.2 GB; streaming reduced it further. Audio drift, HDR conversion and Live Photo joins each needed their own fixes.

The [architecture](../contribute/architecture.md) and [rendering reference](../reference/media-processing.md) explain what runs now.

## Two AIs, human decisions

Claude and Codex wrote most of the code. I set the direction, watched the films and recorded rules the agents could check: chronological output, favourites win their moment, quiet periods need no filler.

The agents also wrote bugs. CI checks types, complexity, architecture boundaries and security, but a passing build cannot decide whether a family film is good. That still means watching it.

[DISCLAIMER.md](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/DISCLAIMER.md) covers the development approach and its limits.

The [full chronological account](https://github.com/sam-dumont/immich-video-memory-generator/blob/f79b8a0c/docs-site/docs/welcome/how-this-was-built.md) records the experiments and measurements as they stood before this docs revision. Current setup instructions live in the guides above.
