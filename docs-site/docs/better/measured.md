---
title: Measure your setup
---

# Measure your setup

Find the slow stage before adding a service. Downloads, picture preparation, captions, selection,
rendering and music have different costs. A faster picture model does not guarantee a faster film.

## Six-configuration February checkpoint, 3 October 2026

A private February 2024 workload produced six decoded 1080p60 H.264 SDR films at default
`balanced` quality. Each initial app store and media/analysis cache was empty; installed weights
and external services were retained. These were reused runtimes, not six clean installations.

| Configuration | Pipeline time | Outcome |
|---|---:|---|
| DS423+ Basic | 25m 01s | Bundled music; CPU title fallback |
| DS423+ with T1000 service, GPU | 16m 40s | Generated music; missing optional motion descriptions |
| Kubernetes T1000, GPU | 7m 26s | Music generation failed; source audio retained |
| M5 Max Full | 4m 23s, composite | Saved-cut render retry; generated music; original Laya fallback |
| M2 Pro Basic | 4m 09s, composite | Saved-cut render retry; bundled music after memory guard |
| M2 Pro Full | 9m 38s | Bundled music after memory guard; one unread episode |

The composites retain original successful phases and use the resumed render/music tail. They
are not uninterrupted runs. The two base revisions also differ, and the later runs include a
local date-persistence fix. Failed music is not a speedup. Both GPU configurations used one
physical 8 GB T1000; the single-GPU generated-music path still needs an uninterrupted passing run.
Maximum-resolution exports remain deferred.

The [detailed report and CSV](https://github.com/sam-dumont/immich-memories/blob/main/docs/research/2026-10-03-february-hardware-smoke.md)
record phase timings, failed work, hardware limits, exact revisions, memory and install gaps.
The [Mac install recipe](../run/reference/mac-example.md) now makes the separate Laya runtime,
HEIC import check and full FFmpeg selection explicit. These corrections do not establish that a
fresh install has been revalidated.

## One month across six configurations, 3 October 2026 {#february-hardware-matrix}

The February 2024 smoke workload requested a 60-second film from the same 2,032-source
inventory on six hardware/tier configurations. The common output was **1080p60 SDR**, with
titles, transitions, photo/video/Live Photo sources and default **balanced** quality. Each
initial run started with empty app, analysis and media/render caches; installed model files
and external services were retained. Upload and full-file verification are outside the timer.

| Configuration | Recorded time | What that time covers | Final music |
|---|---:|---|---|
| Synology DS423+, J4125, Basic | 25m 04s | Original uninterrupted cold run | Bundled |
| Same NAS, GPU tier with Kubernetes services | 16m 42s | Original uninterrupted cold run | ACE-Step service + four stems |
| Kubernetes GPU, one T1000 8 GB | 12m 32s | Final uninterrupted cold confirmation | ACE-Step service + four stems |
| M5 Max, 128 GiB, Full | 4m 14s | Cold confirmation with one reader fallback; repaired below | Local ACE-Step + four stems |
| M2 Pro, 16 GiB, Basic | 4m 59s | Composite: original preparation plus successful render/music phases | Local ACE-Step + four stems |
| M2 Pro, 16 GiB, Full | 9m 44s | Final uninterrupted cold confirmation | Local ACE-Step + four stems |

All six final films passed complete video/audio decoding. M2 Basic's final saved-cut retry
itself took **2m 14s**; it was not a new cold run. Its failed render and earlier bundled
fallback remain in the detailed report. The revisions changed as bugs were repaired, and
model-driven selection can choose different shots. This is a common-workload checkpoint,
not six identical cuts on one release or a clean-install speed ranking.

### What the maximum export added

**Basic stayed at 1080p on both NAS and M2.** NAS GPU, Kubernetes GPU, M5 Full and M2 Full
also delivered 3840×2160, 60 fps, HEVC, 10-bit PQ HDR with BT.2020 primaries. All four passed
full decoding. The GPU maximums retained their rendered video and needed music-only repairs.

The latest Mac pairs reused each machine's selected cut. M5 includes the reader repair below:

| Same-cut comparison | M5 Full | M2 Full |
|---|---:|---:|
| 1080p render | 36.7 s | 69.9 s |
| 4K HDR render | 90.5 s | 180.4 s |
| Extra render time | **53.8 s** | **110.5 s** |
| 1080p file | 22.31 MB | 39.18 MB |
| 4K HDR file | 40.62 MB | 73.37 MB |
| File growth | **82%** | **87%** |

You gain four times the output pixels and a 10-bit HDR output. Frame rate stays at 60 fps;
lower-resolution or SDR sources do not acquire native 4K HDR detail. Music was generated
separately for each export, so its timing is not part of the resolution penalty. The shared
GPU measurements include changing load and revisions; their larger export times are not
isolated resolution costs.

### What still limits the claim

- Optional motion descriptions were missing; selection used plain clip facts for those clips.
  Those descriptions are not counted as exercised just because a film finished. M5 Full also
  initially left one demanded episode unread: an oMLX workaround had disabled its owned
  llama.cpp schema. The fix and a selection-onward retry took **1m 45s**, reused preparation,
  and completed with no unread episodes. Its paired 4K export took **2m 01s**. Both passed
  generated music, four stems and decoding; the original cold timing remains above.
- M2's successful Full run used the bundled llama.cpp reader and a separate llama.cpp caption
  service. Replacing the earlier caption service reduced its measured footprint from about
  2.3 GiB to 507 MiB. The [smaller-Mac caption recipe](../reference/caption-service.md) records
  that setup; the local music memory guard was not lowered.
- One physical T1000 served the Kubernetes path. GPU Operator time slicing did not evict
  models or prevent other workloads from using VRAM. Upload-triggered Immich ML work caused
  interference, and ACE-Step retained VRAM after an OOM. A service restart preceded the
  successful cold confirmation. A separate ACE-Step loading-cleanup fix passed an isolated
  CUDA failure/recovery control; full API recovery on the patched image remains unverified.

The [full timing and recovery report](https://github.com/sam-dumont/immich-memories/blob/main/docs/research/2026-10-03-february-hardware-smoke.md)
contains phase timings, failed attempts, exact source revisions and installation findings.
The films use a private library and are not public demo assets. For something you can watch,
use the [CC0 Basic/GPU example](./gpu-example.md) or [Basic/Full example](./tier-example.md).
[Choose your setup](../get-started/choose-your-setup.md#what-you-give-up-with-basic) separates
what each tier adds from optional music and rendering services.

## Tested setups, 2 October 2026 {#tested-setups}

These are separate checks, not four timed clean installs on the current release.
The [docs-only installation gate](https://github.com/sam-dumont/immich-memories/issues/956)
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
example is separate from the [#1719 28-case suite](https://github.com/sam-dumont/immich-memories/issues/1719); do not treat
these different films as either comparison. Record setup, downloads, preparation and generation
separately when repeating the [first-run gate](https://github.com/sam-dumont/immich-memories/issues/956).

## Generated cold installs, 2 October 2026 {#generated-cold-installs}

A fresh generated NAS setup ran on DSM 7.3 on x86_64 (reported model `DS423`), with
17,836 MiB RAM reported by `free -m`, a 4 GiB container limit, empty configuration/output
volumes and no copied model or picture cache.
It used 133 public CC0 assets from June 2024 and the unmodified first-film command:

```bash
immich-memories generate --year 2024 --month 6 --duration 60
```

Explicit model download took **6 seconds**. The recorded film run took **16m 38.8s**, producing
**57 seconds of 1920×1080 H.264/AAC**, 16,036,267 bytes, with 14 shots (6 videos and 8 stills).
Bundled music, rules selection and the default output settings remained enabled; no upload was
requested. A full FFmpeg audio/video decode exited successfully. Preflight completed with
5 OK, 4 warnings and 9 skipped checks; it was not a warning-free run.

This was **software encoding**, with no VAAPI device passed through. The title kernel crashed
on this CPU and fell back to PIL title plates; HDR input was tone-mapped to SDR for the default
H.264 output. These warnings remained visible on the completed run. Playback and an inactive
reader URL save/reload/restore passed in the actual NAS UI. The Settings test restored the
original empty saved-settings state.

The runtime candidate came from source tree `75077f27c4eb2f4516a1db5ba5e57d52a314fe18`,
image `sha256:49cc60a978ce92cc9d9081770f690de9cdfe17650afcb36bc63ebf281ccdb162`.
The builder generated its byte-exact file at revision `61fa1154` using the local candidate alias
`0.0.0-rc.75077`; this alias was **not a published release**. The installation used SSH/Compose,
not the DSM Project wizard. DSM rejected the ordinary SSH tunnel for this account; UI checks
used a temporary localhost-only SSH stdio transport without changing the NAS SSH policy.
The [Synology access instructions](../run/platforms/synology.md#4-open-the-app) explain that
forwarding prerequisite and the authenticated reverse-proxy alternative.

This is one real cold run, not a speed comparison: other NAS workloads and candidate-image
export were active. The older warm controls and paired films above remain separate evidence.

### Generated GPU Kubernetes first film {#generated-gpu-first-film}

The generated GPU path ran in a fresh namespace on RKE2 `v1.33.4+rke2r1`, with an NVIDIA
T1000 8 GB shared between the CUDA inference and caption services. The app had a **4 CPU,
8 GiB limit** and no GPU device. Empty model volumes fetched the pinned detectors, Laya and
caption weights; the app database used local/block storage, with models and output on NFS.
Preflight finished in **11.68 seconds**, with 9 OK, 4 warnings and 5 skipped checks.

Using the same 133 public CC0 assets, a June 2024 monthly film requested for 60 seconds took
**11m 22.8s** to generate. It produced **56.5 seconds of 1920×1080 H.264 at 30 fps**, with
stereo AAC audio, 16,154,477 bytes. FFprobe and a complete FFmpeg audio/video decode passed.
Rules selection, full picture preparation, detectors, Laya and CUDA captions stayed enabled;
there were no resolution overrides or feature-disable flags. The run used bundled music.
Encoding used software, titles used CPU static plates, and HDR input was tone-mapped to SDR. Seven clips lacked motion facts and
used plain clip facts; that warning remained visible.

This used source tree `75077f27c4eb2f4516a1db5ba5e57d52a314fe18`, app image
`49cc60a978ce` and matching inference image `d079a0da1633`, with generated resources from
`5f3de520`. It was a local candidate install, **not a published release download**. The first
attempt paired that app with an older released inference image; the strict facts validator
refused the incompatible heads. The failed test database was cleared before the paired run,
so its picture facts were prepared afresh. SQLite also correctly refused an initial NFS data
volume; the corrected run used local/block storage.

The generation time excludes image builds and transfers, model initialization and preflight.
App image transfer took 385.9 seconds; the matching inference image import took 343.8 seconds.
Cold model initialization completed, but no complete cold-install stopwatch was recorded.
The generated Settings encryption key passed a secret save/masked reload/encrypted-storage
check; the temporary setting was removed. The test namespace and its volumes were then removed.
This is one installation and film check, not a matched hardware speed comparison.

## Generated native Mac check, 3 October 2026 {#generated-native-mac}

The generated GPU setup ran on an **Apple M5 Max with 128 GB RAM**, using an isolated
candidate wheel from `d5b4472b8525e82fefdd78143aca62e16e707ce1`. Installing that local
`0.0.0rc180503` wheel replaced the generated PyPI install: this was **not a published-release
installation**. Model-only files and existing Hugging Face snapshots were reused; the app
configuration, database, picture facts and output were fresh. The existing loopback caption
server stayed unchanged, so this check does not establish a cold model download or a new
caption-service installation.

Model verification took **0.90 seconds** and preflight **13.84 seconds**, with 11 OK,
2 warnings and 5 skipped checks. A June 2024 monthly film from the same 133 public/synthetic
assets, requested for 20 seconds with photos included, took **35.38 seconds**. It produced
**19 seconds of 1920×1080 H.264 at 30 fps**, stereo 48 kHz AAC, 5,402,495 bytes.
FFprobe and complete audio/video decoding passed. Local MLX/Metal picture inference and
Laya, the existing MLX caption server, Metal title kernels and `h264_videotoolbox` encoding
were used. The reader and generated music stayed disabled; bundled music remained enabled.

Warnings included unset home coordinates, one clip without motion facts, a Laya confidence
bucket warning and HDR input tone-mapped to SDR. The loopback UI served the built client;
its owned process was stopped without changing the caption service or normal app settings.
The separate ACE-Step setup and import checks passed, but no ACE-Step track was generated.
This source-informed check is not the source-naive #956 gate or a matched speed comparison.

## NAS app with remote GPU, 3 October 2026 {#generated-nas-remote-gpu}

The physical DSM NAS app used the generated GPU setup against a combined worker on one
T1000 in an owned Kubernetes namespace. This exercised `GPU_BOX` facts and caption routes;
it was not a standalone Docker Compose worker deployment. The app used candidate source
`75077f27` and image `49cc60a978ce`, with matching worker image `d079a0da1633`.

Cold local model acquisition took **26.93 seconds**, including the pinned ONNX Laya file
(877 MB). The original cold preflight **failed after 20.48 seconds**: its five-second caption
probe expired while the worker lazily started the caption model. After that model was ready,
preflight passed in **14.67 seconds**, with 9 OK, 4 warnings and 5 skipped checks.

A separate cold-start check restarted the owned worker and verified that no caption process
was running. With only the reviewed caption timeout/error changes transplanted into the
frozen app's preflight file, preflight passed in **32.00 seconds**, with the same check counts
and no prewarming. This was a single-file test overlay, not a rebuilt current-source image;
the completed film below used the original candidate.

The film run used `generate --year 2024 --month 6 --duration 20` and took **6m 53.09s**
from SSH command start through successful exit, including configuration probes, preparation,
rendering and music. It produced **19 seconds of 1920×1080 H.264/AAC**, with bundled music
and no upload. Complete FFmpeg audio/video decoding passed. The worker prepared facts for
133 assets and captions for four selected clips; the NAS encoded in software and used PIL
title fallback. One clip lacked motion facts. The product tier was GPU; the internal
captioned preparation mode did not enable a text reader or make this a Full-tier run.

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

The completed [#1704](https://github.com/sam-dumont/immich-memories/issues/1704)
and [#1702](https://github.com/sam-dumont/immich-memories/issues/1702)
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
The [full report](https://github.com/sam-dumont/immich-memories/blob/main/docs/research/2026-10-02-render-performance-closeout.md)
records source revisions, memory, component gains and measurement limits. Separate
[NAS software-HLG memory work](https://github.com/sam-dumont/immich-memories/issues/1767)
remains open.

## Ollama on M5 Max, 3 October 2026 {#ollama-validation}

Gemma 4 E4B was tested through both Ollama APIs using the same 34 synthetic
production-feature checks as the oMLX validation. This run used Ollama 0.35.1,
`gemma4:e4b-it-q4_K_M`, an M5 Max with 128 GiB RAM, and a 32,768-token context.
Source: `a3bfc5dbe66efceaf6985abed72c78600a0fbb37`. The model is the same Gemma
variant; its Q4_K_M GGUF weights differ from the earlier 6-bit MLX weights.

| API and thinking setting | Passed | Summed probe time | HTTP attempts |
|---|---:|---:|---:|
| Native, server default | 34/34 | 318.77 s | 85 |
| Native, `think: false` | 33/34 | 53.01 s | 85 |
| Compatible, default app settings | 25/34 | 345.19 s | 97 |
| Compatible, `reasoning_effort: none` | 32/34 | 45.04 s | 85 |

Use the [explicit thinking-off recipes](../reference/llm-providers.md#ollama)
for the text reader. Both read all 22 episodes and selected eight story moments
in the separate larger-prompt checks. Native Ollama with server-default thinking
truncated its first large episode response: earlier requests in the complete suite
had already taught the app to budget extra tokens. The compatible route ignores
the default oMLX-style thinking switch and can return empty answers at small token limits.

With thinking off, both APIs failed the motion example; the compatible API also
lost the race from a period summary. Image captioning and the other feature checks
passed. These were single sequential runs with warm server caches, not a throughput
comparison with oMLX or an end-to-end film validation. The M2 and SmolVLM2 were not tested.
The [report and reproducible configs](https://github.com/sam-dumont/immich-memories/blob/main/docs/research/2026-10-03-ollama-validation.md)
and [aggregate CSV](https://github.com/sam-dumont/immich-memories/blob/main/docs/research/2026-10-03-ollama-validation.csv)
record all four runs, including failures.

## LLM contract fixes, 1 October 2026 {#llm-contract-fixes}

The Gemma conformance results use 6-bit MLX on oMLX, rather than the app-owned Q4_0 GGUF.

The follow-up for [#1645–#1660](https://github.com/sam-dumont/immich-memories/issues/1645)
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

The [aggregate CSV](https://github.com/sam-dumont/immich-memories/blob/main/docs/research/2026-10-01-llm-contract-fixes.csv)
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
cap remains enforced. [#1650](https://github.com/sam-dumont/immich-memories/issues/1650)
records the remaining capability gap.

Story comparisons can also vary: z.ai tied the race and routine scene in one complete run,
although both held-out occasion comparisons passed. Contradictory central/minor answers now
receive bounded repair; a valid but poor ranking still fails the conformance check
([#1653](https://github.com/sam-dumont/immich-memories/issues/1653)).

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
