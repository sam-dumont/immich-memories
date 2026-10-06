---
title: Measure your setup
---

# Measure your setup

Find the slow stage before adding a service: downloads, picture preparation, captions,
selection, rendering and music all cost differently. A faster picture model does not
guarantee a faster film.

Every number below is a single timed run on the hardware named next to it, not a statistical
benchmark. Library size, cache state and shared load all move these numbers. Treat them as
a range to expect, not a speed ranking between machines.

## Cold start time by hardware and tier {#cold-start-time-by-hardware-and-tier}

A first film, from an empty cache, requesting a 60-second month from a library of 700 to 2,000
pictures, default quality, 1080p SDR:

| Hardware | Tier | Cold time | Music |
| --- | --- | ---: | --- |
| Synology NAS, Celeron J4125 | Basic | 17 to 25 min | Bundled |
| Same NAS, with a Kubernetes GPU service | GPU | 17 min | Generated (ACE-Step service) |
| Kubernetes, NVIDIA T1000 8 GB | GPU | 9 to 13 min | Generated (ACE-Step service) |
| M2 Pro, 16 GB | Basic | 5 min | Generated (local ACE-Step) |
| M2 Pro, 16 GB | Full | 10 min | Generated (local ACE-Step) |
| M5 Max, 128 GB | Full | 3.5 to 4 min | Generated (local ACE-Step) |

A from-scratch Docker install on the same NAS, model download included, takes about 29 minutes
end to end on top of the cold time above. Captions and a text reader add the GPU/Full download
and preparation time once, on the first run; later runs reuse what they already prepared.

## 4K/HDR render cost vs 1080p {#4k-hdr-render-cost}

Same cut, same machine, rendered again at 3840×2160 60 fps HEVC 10-bit HDR instead of 1080p60 SDR:

| Hardware | 1080p render | 4K HDR render | File size growth |
| --- | ---: | ---: | ---: |
| M5 Max | 37 s | 91 s | +82% |
| M2 Pro | 70 s | 180 s | +87% |
| NAS + GPU render worker | adds about 13 min | | |
| Kubernetes GPU | adds about 9 to 10 min | | |

4K HDR gives you four times the pixels and 10-bit HDR; both stay at 60 fps. An SDR or
lower-resolution source does not gain native HDR detail from this step. Music is generated
separately for each export, so its time is not part of this render cost. The shared-GPU numbers
move with other load on that card, more than the Mac numbers do.

## Render worker and generated music sharing one GPU {#render-worker-and-music-sharing-one-gpu}

A render worker and ACE-Step can share one small GPU card: tested with both running serially on
a single NVIDIA T1000 8 GB, including generated music and four-stem separation, with no manual
unload or restart needed between films.

ACE-Step on that same card can recover cleanly from memory pressure: after an injected
out-of-memory failure, a rebuilt service (with the model-loading cleanup fix, see
[the pinned image](../reference/local-audio.md#in-a-container)) generated an 88-second track in
about 148 seconds, with no restart. GPU time-slicing gives access to the card, not separate VRAM
pools: run one film at a time on a shared card, and check an actual generated track rather than
trusting a passing health check.

Render-worker assembly time by hardware, for two film lengths (titles, maps, transitions and
audio; excludes media download, selection and generated music):

| Hardware | 14.5 s film | 68.5 s film |
| --- | ---: | ---: |
| M2 | 75 s | 166 s |
| M5 | 49 s | 99 s |
| GTX 1070 | 198 s | 468 s |
| NVIDIA T1000 | 217 s | 575 s |

## Hosted reader: time and cost per provider {#hosted-reader-time-and-cost}

A hosted reader costs a few cents per request; it does not remove the time spent reading the
library, checking pictures or rendering locally. Measured on Full tier, M5 Max, local picture
models, for the same monthly request:

| Provider | Whole run | Film produced | Estimated cost |
| --- | ---: | --- | ---: |
| OpenAI | 78 s | 61 s, 15 pictures | $0.01 |
| z.ai | 120 s | 61 s, 15 pictures | $0.01 |
| Melious | 180 s | 61 s, 15 pictures | €0.07 |

A longer request costs proportionally more: a 5-minute film ran z.ai at about $0.05 and Melious
at about €0.42. On a 34-case feature suite (titles, free-text, captions, music mood, editorial
choices), every provider passed 33 or 34 out of 34, in 2 to 9 minutes of combined request time,
for $0.01 to €0.03.

**Motion direction is the weak spot.** Across every hosted provider tested (OpenAI, z.ai,
Melious) and the local Gemma reader, direction-of-motion questions (left/right/up/down/still)
passed 1 to 3 out of 5 controls. Treat a hosted or local reader's motion description as a bonus,
not a fact to rely on. Other feature checks (captions, story comparisons, titles) passed
consistently.

## Local reader time and accuracy {#local-reader-time-and-accuracy}

Ollama and oMLX, both running Gemma 4 E4B on an M5 Max with 128 GB, against the same 34-case
feature suite used for hosted providers above:

| Reader | Passed | Combined request time |
| --- | ---: | ---: |
| oMLX, thinking off | 33/34 | 53 s |
| Ollama native API, thinking off | 33/34 | 53 s |
| Ollama OpenAI-compatible API | 25 to 32/34 | 45 to 345 s |

A local reader has no per-request fee; hardware and electricity were not priced here. Turn
thinking off explicitly on both APIs: leaving it on lets reasoning consume part of a large
request's token budget and can truncate the answer. See
[Ollama settings](../reference/llm-providers.md#ollama) for the exact recipe.

## Longer films: memory and duration {#longer-films-memory-and-duration}

| Setup | Film | End-to-end time | Output |
| --- | --- | ---: | --- |
| NAS, Basic | One-minute month | 7 min | 1080p SDR |
| NAS, Basic | Ten-minute person film | 79 min | 1080p SDR |
| M2 Pro, Full | One-minute month | 15 min | 4K HDR10 |
| M5 Max, Full | One-minute month | 6 min | 4K HDR10 |
| M5 Max, Full | Ten-minute person film | 40 min | 4K HDR10 |

Picture facts were already prepared for these; preparing a new library adds time on top. A
30-minute NAS film completed in 4h 21m at 1080p SDR, inside a 4 GiB container limit, peaking
around 2.9 GiB RAM (3.7 GiB with swap). That is one tested workload, not a guarantee that every
library or length fits the same container limit.

Maps can dominate a trip film: nine smooth 4K maps took 15 minutes on an M2 Full trip, about 43%
of the whole run. Use `preset: fast` for cheaper maps; see
[titles and maps](../make/titles-maps-music.md).

Process memory for a Full-tier month on M2 Pro ran about 12 GB RSS; a ten-minute Full film on
M5 Max ran about 17 GB RSS. RSS can count shared memory more than once and is not a minimum RAM
requirement.

## Caption service memory {#caption-service-memory}

Switching the Mac caption server from mlxcel to llama.cpp, same SmolVLM2 model, same requests:
resident memory dropped from about 2.3 GiB to about 507 MiB on a 16 GiB Mac. See
[the caption service reference](../reference/caption-service.md#apple-silicon-with-llamacpp) for
the setup.

## Finger over the lens {#finger-over-the-lens}

The finger check is a small head trained only on public images (Commons pictures and synthetic
fingers pasted on them). It was then run against the maintainer's library, which it never saw in
training.

| Set | Flagged |
| --- | --- |
| Real finger-over-the-lens photos | 26 of 49 |
| Real finger-over-the-lens video previews | 11 of 20 |
| Look-alike photos with no finger | 32 of 440 |
| Random photos | 4 of 2,000 |
| Look-alike video previews with no finger | 6 of 69 |
| Random video previews | 9 of 384 |
| Whole library | 240 of 56,372 (0.4%) |

It catches about half of the real ones. That's why a flagged picture only loses to a clean shot of
the same moment and is never dropped: see [picking a shot](../how-it-chooses/picking-shots.md).

## Read your own run

```bash
immich-memories runs show RUN_ID
immich-memories report RUN_ID
```

The report breaks down phase timings, memory and delivery for a run you actually made. Review
it before sharing; it sends nothing on its own. Assembly includes titles, maps, composition and
encoding, so its time is not an encoder-only number.

```bash
immich-memories capabilities
```

`capabilities` separates configuration and installation checks from generation evidence; it
does not prove that every selected picture or finished film is right. Run
[preflight](../run/maintenance/health-logs-cache.md) after changing services.

## Compare fairly

Render the same saved cut twice: the first run may acquire media, the second reuses compatible
work. Keep cold and warm results separate. When testing an add-on, keep the scope and output
format fixed, note the hardware, and watch both films rather than trusting the numbers alone.

Measure the app and each service separately. A local reader and local audio can share machine
memory when the app owns their runtimes; external servers keep memory resident on their own
schedule, even while idle. See [benchmarking your own setup](../reference/performance-evidence.md)
for what to record, and [two tiers of the same month](./tier-example.md) for a side-by-side film
comparison.
