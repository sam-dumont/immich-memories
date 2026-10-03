---
title: Measure your setup
---

# Measure your setup

Find the slow stage before adding a service. Downloads, picture preparation, captions, selection,
rendering and music have different costs. A faster picture model does not guarantee a faster film.

## Tested setups, 2 October 2026 {#tested-setups}

These are separate checks, not four timed clean installs on the current release.
The [docs-only installation gate](https://github.com/sam-dumont/immich-video-memory-generator/issues/956)
records the Mac, Docker, Synology and Kubernetes preflight runs; those runs stopped before generation.
The finished-film controls below came from later, separate runs with prepared picture facts.

| Machine | Setup checked | First preparation time | Finished-film evidence |
|---|---|---|---|
| M2 Pro, 16 GB | Native Full | Not recorded in these controls | One-minute month: 15m 29s, 4K HDR10 |
| M5 Max | Native Full; reader and captions on the Mac | Not recorded in these controls | One-minute month: 5m 43s, 4K HDR10 |
| Synology DS423+, J4125 | Compose app; NAS controls, plus a preflight run with remote reader/captions | Not recorded in these controls | One-minute NAS month: 7m 23s, 1080p SDR |
| RKE2 cluster, NVIDIA T1000 | App and CUDA captions; install and preflight verified | Not recorded in the installation run | No finished film in that docs-only run; isolated rendering timings are below |

The Mac controls used generated music and the NAS used bundled music. They are not matched
NAS-versus-Full quality comparisons. The [paired CC0 month films](./tier-example.md) are available
with selected-shot differences, provenance and warm-cache/dependency/calibration caveats. That
example is separate from the [#1719 28-case suite](https://github.com/sam-dumont/immich-video-memory-generator/issues/1719); do not treat
these different films as either comparison. Record setup, downloads, preparation and generation
separately when repeating the [first-run gate](https://github.com/sam-dumont/immich-video-memory-generator/issues/956).

## Read one run

```bash
immich-memories runs show RUN_ID
immich-memories report RUN_ID
```

The run reports phase timings, memory and delivery. Review the report before sharing it; it sends
nothing itself. Assembly includes titles, maps, composition and encoding, so its time is not an
encoder-only benchmark.

## Measured examples, 1 October 2026 {#whole-film-controls}

These are finished films from specific source revisions. They show the range to expect, not a
speed ranking: the tiers used different edits, output profiles and music backends. Picture facts
were already prepared; original-media acquisition, fresh selection, titles, rendering and music
still ran. Preparing a new library takes additional time.

| Setup | Film | End-to-end time | Output | Source revision |
|---|---|---|---|---|
| Physical NAS, NAS tier | One-minute month | 7m 23s | 1080p portrait, 60 fps, SDR | `c4c7356304c5` |
| Physical NAS, NAS tier | Ten-minute person film | 78m 51s | 1080p portrait, 60 fps, SDR | `dec8f20e609c` |
| M2 with 16 GiB, Full tier | One-minute month | 15m 29s | 4K portrait, 60 fps, HDR10 | `f74936b657d7` |
| M5, Full tier | One-minute month | 5m 43s | 4K portrait, 60 fps, HDR10 | `cb06e4ba0e0d` |
| M5, Full tier | Ten-minute person film | 39m 40s | 4K portrait, 60 fps, HDR10 | `f82de21b5bf5` |

`f74936b657d7` was an unpublished measurement checkout, absent from the public repository.
The M2 month and NAS stress run below are historical observations; that source cannot be
checked out from this repository to reproduce them.

NAS used bundled music. The Mac films used local ACE-Step music and Demucs stem separation.
The M2 Full month recorded 12.38 GB process-tree RSS; the M5 Full person recorded 17.02 GB.
RSS can count shared mappings more than once and is not a minimum RAM requirement.

### Longer films and memory

A separate 30-minute NAS stress film took **4h 20m 45s** at 1080p portrait, 60 fps, SDR, on
`f74936b657d7`. It completed under a **4 GiB container limit**, peaking at about **2.87 GiB RAM**
and **3.74 GiB RAM plus swap**. It used swap. This supports that tested workload; a container
limit alone does not guarantee that every library or film fits.

Maps can dominate a trip render. In one M2 Full trip, nine smooth 4K maps took 911 seconds,
about 43% of the whole run. The NAS version used lower resolution and reduced motion. For
cheaper maps, choose `preset: fast`; [titles and maps](../make/titles-maps-music.md) explains it.

## Rendering improvements, 2 October 2026 {#rendering-performance}

The completed [#1704](https://github.com/sam-dumont/immich-video-memory-generator/issues/1704)
and [#1702](https://github.com/sam-dumont/immich-video-memory-generator/issues/1702)
work reduced title, map and assembly costs. Final combined checks used synthetic
portrait 4K HDR10 video at 60 fps, with titles, maps, captions, transitions and audio.

| Host | Film length | Before | After | Less time |
|---|---:|---:|---:|---:|
| M2 | 14.5 s | 154.6 s | 75.2 s | 51% |
| M2 | 68.5 s | 592.9 s | 166.4 s | 72% |
| M5 | 14.5 s | 81.9 s | 49.0 s | 40% |
| M5 | 68.5 s | 263.2 s | 99.0 s | 62% |
| GTX 1070 | 14.5 s | 433.4 s | 197.6 s | 54% |
| T1000 | 14.5 s | 441.7 s | 217.1 s | 51% |

Each final Mac candidate ran once against unchanged earlier controls: two short
baseline runs and one long run. Linux used one matched short pair per GPU under
shared-cluster load. These are rendering times, excluding media acquisition,
selection and generated music. They do not replace the whole-film controls above,
and the baseline already includes earlier title/cadence improvements.

Both Linux GPUs also completed the 68.5-second, 42-clip film: 467.7 seconds on
GTX 1070 and 574.7 seconds on T1000. The long Linux baseline checks timed out during
redundant output verification, so no long-film Linux speedup is claimed. All final
outputs passed full video/audio decoding, timing and HDR metadata checks. The merged
assembly files match the isolated source used for these tests.

Mac read-ahead stays enabled only for the measured HEVC VideoToolbox path with enough
CPU and memory. It slowed the T1000 down, so Linux and software encoders stay synchronous.
The [full report](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/docs/research/2026-10-02-render-performance-closeout.md)
records source revisions, memory, component gains and measurement limits. Separate
[NAS software-HLG memory work](https://github.com/sam-dumont/immich-video-memory-generator/issues/1767)
remains open.

## LLM contract fixes, 1 October 2026 {#llm-contract-fixes}

The Gemma conformance results use 6-bit MLX on oMLX, rather than the app-owned Q4_0 GGUF.

The follow-up for [#1645–#1660](https://github.com/sam-dumont/immich-video-memory-generator/issues/1645)
uses fixes based on `b96d7d6a`, the four models listed below, and synthetic inputs only.
Provider runs overlapped on the shared Mac. Raw request/reply evidence stays private.
Server schema modes were left unchanged, including Melious's `structured_output: false`.

The complete 34-feature command was rerun after the fixes:

| Endpoint | Passed | Summed probe time | HTTP attempts | Failed feature |
|---|---:|---:|---:|---|
| Gemma, gemma-4-e4b-it-6bit | 33/34 | 213.63 s | 86 | Video motion |
| OpenAI, gpt-5.6-luna | 33/34 | 206.59 s | 87 | Video motion |
| z.ai, glm-5.3-flash | 34/34 | 294.78 s | 85 | None in this run |
| Melious, deepseek-v4.1-flash | 34/34 | 223.44 s | 85 | None in this run |

The [aggregate CSV](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/docs/research/2026-10-01-llm-contract-fixes.csv)
contains the 136 complete-suite rows and 74 separate held-out checks. Blank token counters
mean unreported. These are single runs with potentially warm server caches; the timings are
not isolated throughput measurements. The held-out rows are not added to the 34-feature score.

The request reader now states and validates field types before voting, retains complete fenced
JSON, and stops when too few valid readings remain. Weather modifiers survive the time/subject
handoff; picture-quality adjectives no longer acquire dictionary noun subjects. Caption prompts
state their required fields. Story weighting repairs contradictory central/minor assignments,
and trip-title instructions consistently prefer the recorded place, including a country.

Separate held-out checks passed on Gemma, z.ai and Melious: otters and sailboats in 2030;
rainy, foggy, sunny and snowy caption pools; Norway-only and Brittany/France trip titles;
and graduation or wedding scenes against an ordinary desk scene. The weather rows use the final
rerun after fixing split adjective/time readings and derived noun choices. Young forms
(puppy, foal, duckling) and restrictive modifiers (striped horse, wooden chair, red car) passed
on all four providers. These small checks do not establish general selection quality.

### Motion is still a provider limitation

The serialized JPEG was inspected: its three numbered panels preserve the generated positions
and their order. The prompt explicitly compares positions within each panel. Neither change
makes every reader reliable. Five separate controls ask for right, left, up, down and stationary:

| Endpoint | Passed | Remaining failures |
|---|---:|---|
| Gemma 4 E4B, 6-bit MLX on oMLX | 1/5 | Both horizontal movements called stationary; vertical replies exceeded the 120-character contract |
| OpenAI | 2/5 | Both horizontal movements called stationary; downward movement also acquired a horizontal direction |
| z.ai | 3/5 | Both vertical movements also acquired a horizontal direction |
| Melious | 3/5 | Both vertical movements also acquired a horizontal direction |

All four passed the stationary control in this final set. An earlier Melious run invented leftward
movement on the same stationary input, so that pass is not a reliability guarantee. Direction
checks reject orthogonal movement and stationary descriptions of moving frames. The character
cap remains enforced. [#1650](https://github.com/sam-dumont/immich-video-memory-generator/issues/1650)
records the remaining capability gap.

Story comparisons can also vary: z.ai tied the race and routine scene in one complete run,
although both held-out occasion comparisons passed. Contradictory central/minor answers now
receive bounded repair; a valid but poor ranking still fails the conformance check
([#1653](https://github.com/sam-dumont/immich-video-memory-generator/issues/1653)).

## Compare fairly

Render the same saved cut twice. The first run may acquire media; the second can reuse compatible
work. Keep cold and warm results separate. When testing an add-on, keep the scope and output
format fixed, record the revision and hardware, and watch both films.

Measure the app and each service separately. A local reader and local audio can share machine
memory when the app owns their runtimes. External servers keep memory resident according to
their own policies, even while idle. Peaks from separate services are not interchangeable with
whole-machine or whole-container memory measurements.

The [measurement reference](../reference/performance-evidence.md) lists what to record for picture
work, selection, rendering and music. The [hardware guide](../run/hardware.md) explains which
steps an encoder accelerates; the [preparation reference](../reference/preparation.md) explains reuse.

## Inspect capabilities

```bash
immich-memories capabilities
```

This separates configuration and installation checks from generation evidence. It does not
prove that every selected picture or finished film is right. Run
[preflight](../run/maintenance/health-logs-cache.md) after changing services.
