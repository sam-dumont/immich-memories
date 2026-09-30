---
title: Performance and costs
---

# Performance and costs

Measurements describe a particular machine, revision and cache state. They are not minimum specifications or a promise about your library.

## Picture analysis on a NAS {#nas-preparation}

On **30 September 2026**, a Synology DS423+ processed 162 still-image previews with fresh fact stores. It had four CPU cores and a 4 GiB container limit; previews and model files were already local.

| Hardware | DINO and eight heads | DINO, Docling and Marqo |
|---|---:|---:|
| NAS CPU | 112 s | 246 s |
| NAS with T1000 service | 54 s | 63 s |
| NAS with GTX 1070 service | 27 s | 34 s |

All six warm passes took **0.14–0.19 seconds** and made zero model or remote HTTP calls. The app reused its stored facts.

These numbers exclude downloads, video-frame sampling, captions, music and rendering. The GPU service hosts differ, so this compares deployed services rather than isolated cards. It does **not** establish whole-film memory requirements.

## Text readers

The 29 September synthetic conformance run checked 34 features. Tested endpoints passed between **29 and 32** of them; none passed everything. Reported hosted token costs ranged from roughly **$0.005–$0.009**, or **€0.034** for the separately priced endpoint. Those are small fixture checks, not the cost of reading your year of pictures.

A passed API check does not establish good film choices. A larger model is not automatically the one you will prefer.

## Whole selections

An earlier comparison made **84 attempts across 28 cases**, using matched NAS, GPU and Full tiers on an Apple M5 Max with 128 GB unified memory. It reused substantial existing preparation. The owner had not made a final preference decision on the cuts.

The current cold-year target on a small NAS remains unverified. One NAS-tier year took 72 minutes even on that Mac. Rendering and music were outside those selection timings.

## Measure your setup

Make the same cut twice and inspect where the time went:

```bash
immich-memories runs show RUN_ID
immich-memories report RUN_ID
```

Separate first-run acquisition from reused facts, and added model work from the whole run. Compare the finished pictures before deciding an upgrade earned its cost.

[Full dated evidence](../reference/performance-evidence.md) retains the revisions, model names, cache methods, provider failures, exact costs and source CSVs.
