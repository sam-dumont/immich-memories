---
title: Measure your setup
---

# Measure your setup

Find the slow stage before adding a service. Downloads, picture preparation, captions, selection,
rendering and music have different costs. A faster picture model does not guarantee a faster film.

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
