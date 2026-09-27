---
title: Measured
---

# Measured

Reader: power user.

NAS is a good default. GPU and Full add refinement, which can change a few pictures or leave the
cut alone. These measurements show the work each layer did. They do not establish that a higher
tier makes a better film.

## Selection comparison, 27 September 2026

The comparison covered **28 cases across NAS, GPU and Full: 84 attempts**. The cases included
four years, seven months, four trips, three seasons, six people selections and four special days.
All used commit [`9eb16812`](https://github.com/sam-dumont/immich-video-memory-generator/commit/9eb168126c0f24f6cced39a0316f0045132e56c8)
with matched inputs and non-tier settings. Later performance and replacement fixes are not
included in these timings.

The host was an **Apple M5 Max with 128 GB unified memory**, shared with other work. NAS here
means the CPU selection tier running on that Mac, not a measurement of a small NAS appliance.
Full used local Gemma 4 E4B 6-bit; the caption provider was SmolVLM2 500M. Sharing used rules,
picture classifiers and, on GPU and Full, Laya. No sharing request went to the prose model.

### Cache state matters

These were fresh selections using retained media, classifier facts and caption banks. Missing
or changed-version facts were computed where needed. Only **26 new picture captions** were
produced across the batch, so this does not measure cold caption throughput.

The first 26 attempts each started from the same seed. That repeated some preparation between
tiers. From the next attempt, GPU inherited its paired NAS preparation, and Full inherited GPU.
The tables keep those two methods separate.

**The cold-year target of under one hour on 8–16 GB remains unverified.** A quick Full refinement
does not include the work already done by NAS and GPU. One NAS year alone took 72 minutes.

### NAS baseline

These are ranges across the cases in each group, rounded to the nearest second. CLI time
includes acquisition, selection and any post-selection metadata work. Video rendering, music,
cache-copy staging and waiting for another job are outside it.

| Cases | NAS CLI time |
|---|---:|
| Years (4 runs) | 4m14s–72m37s |
| Months (7 runs) | 49s–10m45s |
| Trips (4 runs) | 2m56s–12m02s |
| Seasons (3 runs) | 2m39s–20m54s |
| People (6 runs) | 4m13s–21m04s |
| Special days (4 runs) | 39s–1m42s |

### Additional work after the previous tier

Each entry is the extra CLI time after the preceding layer, not total time from an empty cache.
The GPU and Full year samples differ: only one GPU year and two Full years used this method.

| Layer and cases | Additional CLI time |
|---|---:|
| GPU, years (1 run) | 2m56s |
| Full, years (2 runs) | 30m36s–41m02s |
| GPU, months (1 run) | 27s |
| Full, months (1 run) | 2m12s |
| GPU, trips (4 runs) | 18s–1m26s |
| Full, trips (4 runs) | 4m41s–7m01s |
| GPU, seasons (3 runs) | 28s–1m27s |
| Full, seasons (3 runs) | 4m25s–9m41s |
| GPU, people (6 runs) | 46s–2m20s |
| Full, people (6 runs) | 9m20s–15m44s |
| GPU, special days (4 runs) | 15s–21s |
| Full, special days (4 runs) | 34s–2m23s |

The ranges include unsuccessful attempts: one degraded Full year, one failed Full season check,
one failed GPU people check and one Full people execution failure. Their cost is retained.

### Earlier independent runs

These 17 GPU/Full attempts repeated preparation from the seed. Treat them as standalone
measurements with existing banks, not the extra cost of enabling the next layer.

| Layer and cases | CLI time |
|---|---:|
| GPU, years (3 runs) | 2m20s–61m04s |
| Full, years (2 runs) | 16m10s–16m18s |
| GPU, months (6 runs) | 48s–10m02s |
| Full, months (6 runs) | 1m40s–6m42s |

In the slowest GPU year, CPU classification alone took about 36 minutes. It produced no new
picture captions. That repeated baseline work belongs to this measurement method; it is not
Gemma's refinement cost.

### Results, calls and memory

- **83 selections finished; one execution failed.** Of all 84 attempts, 80 passed the recorded
  selection and reader checks, two failed a selection check, and one had incomplete episode
  reading. Passing these checks is separate from judging the pictures or watching a rendered film.
- **All 28 cases received a private picture-and-reason review.** The owner has not made a final
  preference decision. Ten finished selections carried the existing duration-shortfall label;
  estimated playback is not a measurement of rendered duration.
- **1,627 Gemma and 137 SmolVLM calls were metered**, including failed work. Existing captions
  were reused. No external LLM or retired 30B calls were observed. There was no hosted-request
  charge; hardware and electricity costs were not measured.
- **Memory is not a sizing result.** Process RSS was sampled on a shared host; service activity
  could belong to other jobs, and RSS is not GPU memory. This batch does not prove an 8–16 GB fit.

The [aggregate CSV](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/docs/research/2026-09-27-selection-matrix-aggregates.csv)
keeps the counts, exact timing ranges, medians and failure categories behind these tables.
Household pictures, prompts, identities and individual case records remain private.

For a setup decision, compare your own NAS draft with the refined result. Keep the captions and
facts already computed, measure the added work, and decide whether the changes earn their cost.
Discovery and free-text memories were not tested by this comparison.

## Earlier runs

The dated reports stay in the repository, with every cell and its caveats, for anyone who wants the
history:

- [Setup matrix, 17 September 2026](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/docs/research/2026-09-17-setup-matrix.md):
  a Mac, a Synology NAS and a Kubernetes cluster over one fixture month and one real month, on
  `0.102.0`.
- [Capability matrix, 12 September 2026](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/docs/research/2026-09-12-capability-matrix.md):
  every memory type on a workstation, and `metadata_only` on the NAS.
- [Deployment costs, 12 September 2026](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/docs/research/2026-09-12-deployment-costs.md):
  what each layout needed to stand up.

How to run the matrix yourself: [Setup matrix](../contribute/setup-matrix.md).
