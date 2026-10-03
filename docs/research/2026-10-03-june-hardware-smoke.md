# June 2023 hardware smoke test, 3 October 2026

All six configurations completed their cold 1080p60 SDR run without a phase restart. All four eligible configurations also completed a same-cut 4K60 HDR export. Every film passed complete video/audio decoding.
**Basic remains 1080p only, on NAS and M2.** All exports use default `balanced` quality.
This repeats the February workload shape on a different month, on one merged application revision:
`4b98c19926eced1b90bf825f882eae61c723de02`. No application source patches were applied during June.
The earlier [February checkpoint](2026-10-03-february-hardware-smoke.md) includes phase repairs;
these accepted June times are uninterrupted runs after setup corrections.

## Workload and measurement boundary

June 2023 contained 725 source assets: 503 images and 222 videos. Every cold run checked the
same private inventory fingerprint before starting. The workload requested a 60-second,
landscape monthly highlights film with titles, transitions, date/place captions and music.
The application chose its photos, videos and Live Photo material from that inventory.
Tier and model decisions can select different shots; this is the same workload, not an identical
edit across six machines. Accepted films run 55.37–59.53 seconds; the 60-second value
is a target. The maximum export uses that machine's exact saved cut and preserves its duration.

Each common run began without an app database, analysis bank or media/render cache. Installed
model files stayed in place. OS page caches and existing external services were not flushed.
The 4K export kept the selected cut and analysis bank but used an empty render cache and generated
music again. It is an additional export, not a second cold end-to-end run.

Wall time includes the CLI process and its normal in-pipeline validation. Setup, dependency
installation, the pre-run inventory query, independent full-file decoding and album upload are
outside that timer. One accepted sample per configuration; these are observations, not averages.
Separate Macs and NAS Basic could overlap. Kubernetes GPU and NAS GPU ran serially on one
physical T1000; uploads were deferred until GPU measurements finished.

## Hardware and installed runtime

| Configuration | Hardware | Resource boundary |
|---|---|---|
| NAS Basic | Synology DS423+, Celeron J4125, Intel UHD 600 VAAPI | 4 CPU affinity, 4 GiB container limit |
| NAS + GPU service | Same NAS; T1000 8 GB on an i9-13900T Kubernetes worker | NAS 4 CPU/4 GiB; worker 4 CPU/8 GiB; Laya on NAS CPU |
| Kubernetes GPU | i9-13900T VM, NVIDIA T1000 8 GB | Controller and combined worker in a 4 CPU/8 GiB pod |
| M5 Full | Apple M5 Max, 18 CPU cores, 128 GiB unified memory | Native process |
| M2 Basic | Apple M2 Pro, 10 CPU cores, 16 GiB unified memory | Native process |
| M2 Full | Same M2 Pro | Native process |

The Full reader is app-owned llama.cpp, version 0.5.0 build 11146 (`7fe450e19`), with the
same installed Gemma reader weights. The M2 uses a separate llama.cpp SmolVLM2 Q8 caption
service, approximately 507 MiB resident in the earlier measured control. It does not use oMLX.
The local music memory guard was not lowered. Local ACE-Step and Demucs run on the Macs;
the GPU configurations use the deployed ACE-Step service and combined worker's Demucs endpoint.
NAS Basic intentionally uses bundled music.

The application fixes are merged in [PR #1945](https://github.com/sam-dumont/immich-memories/pull/1945).
The ACE-Step loading cleanup is merged in [PR #4](https://github.com/sam-dumont/ace-step-1.5/pull/4)
and deployed from image digest
`sha256:45530623b81fa48fd8e4c8398d7d4df4c4ff8b16931edfc3c5cf903dee6dfc24`.
The accepted GPU films exercise the rebuilt service, beyond the earlier injected-failure test.

These are existing runtimes with a frozen source overlay, not six clean installations or a
published-release wheel comparison. The retained generated package-version file predates the
source overlay; the verified application source SHA above identifies the measured code.
The old inference image also needed its missing declared HEIC dependency installed before acceptance.

This is pre-RC1 validation: RC1 is intended to follow these tests. Publication is not a prerequisite
for this source-level matrix. Current main's versioned installation component distinguishes
published installers from unpublished previews. The RC must carry the tested fixes and declared
dependencies; these existing-runtime measurements do not themselves certify a clean install of
the eventual release artifacts.

## Cold 1080p results

Seconds throughout; MB are decimal. Peak RSS samples the CLI process tree once per second;
it includes child processes but excludes separate caption, inference and music services.
It is not total host RAM, a GPU VRAM measurement or a cross-platform memory budget.

| Configuration | Status | Wall s | Pipeline s | File MB | Peak tree RSS GiB |
| --- | --- | --- | --- | --- | --- |
| NAS Basic | passed | 995.629 | 993.219 | 104.555 | 0.702 |
| NAS + GPU service | passed | 1,124.725 | 1,122.426 | 73.745 | 1.944 |
| Kubernetes GPU | passed | 540.546 | 539.017 | 73.743 | 1.575 |
| M5 Full | passed | 208.461 | 207.164 | 53.697 | 8.376 |
| M2 Basic | passed | 202.626 | 202.027 | 80.021 | 10.358 |
| M2 Full | passed | 575.636 | 574.697 | 79.008 | 11.094 |

All common films are H.264, 1920×1080, 60 fps, 8-bit BT.709 SDR, with AAC audio.
NAS Basic uses a bundled soundtrack; the other five require actual ACE-Step generation and
four-stem ducking to pass. Exit code alone is insufficient: a silent music fallback fails this gate.

## Phase timings

Selection includes preparation, detector/caption work, editorial work and Full reader calls.
Assembly is inside render; do not add it again. Music is separate from render. These named
spans omit some root-span bookkeeping and do not sum exactly to wall time. The remote render
path includes source preparation inside assembly.

Music can generate more than one candidate under the same default policy. M2 Full's common
run generated three candidates before choosing one; its maximum needed one. M5 common needed
one and maximum needed two. That variation remains in wall time and explains part of the music
spread; it is not all hardware speed or output-resolution cost. M2 Full's three common candidates
were flagged by the music scorer, which selected the best available candidate after exhausting
the configured attempts. Generation and stem mixing succeeded; a decode pass is not a subjective
soundtrack-quality assessment.

NAS GPU generated three common candidates and one maximum candidate. Its common music took
435.226 s, against 36.178 s for NAS Basic's bundled track. Remote rendering fell from 492.778 s
to 200.024 s, but the extra music work made the complete GPU film slower in this sample.
The upgrade adds captions, detector checks, Laya answers and generated four-stem music;
it does not guarantee a shorter end-to-end time.

On the same M2 Pro, Full took 373.010 s longer than Basic. Selection grew by 275.350 s and
music by 95.798 s, while rendering was 3.757 s shorter. Full adds captions, detector checks,
Laya audience answers and the reader edit pass; generated music is available to both tiers.
The different candidate count above means the entire wall-time difference cannot be charged
to Full's additional selection features. These are different selected films from the same month.

| Configuration | Startup | Discovery | Selection | Render | Assembly | Music |
| --- | --- | --- | --- | --- | --- | --- |
| NAS Basic | 12.279 | 0.096 | 430.794 | 492.778 | 256.789 | 36.178 |
| NAS + GPU service | 13.206 | 0.092 | 451.624 | 200.024 | 200.004 | 435.226 |
| Kubernetes GPU | 7.859 | 0.058 | 151.398 | 152.713 | 152.707 | 219.926 |
| M5 Full | 3.791 | 0.073 | 141.231 | 37.991 | 26.004 | 19.733 |
| M2 Basic | 4.801 | 0.076 | 68.831 | 64.891 | 45.963 | 60.188 |
| M2 Full | 4.647 | 0.077 | 344.182 | 61.134 | 42.981 | 155.986 |

## What 4K HDR costs

Only GPU and Full get this export. Each paired maximum is 3840×2160, 60 fps, HEVC, 10-bit
PQ HDR with BT.2020 primaries. The gain is four times the output pixels and a 10-bit HDR
output. The frame rate stays the same. Lower-resolution or SDR originals do not acquire
native 4K HDR detail. Music is regenerated, so its timing difference is not a resolution penalty.

| Configuration | Export wall | 1080p render | 4K render | Extra render | 4K music | 1080p MB | 4K MB | File growth |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NAS + GPU service | 1,292.173 | 200.024 | 991.250 | 791.226 | 161.128 | 73.745 | 145.739 | 97.6% |
| Kubernetes GPU | 920.430 | 152.713 | 728.983 | 576.270 | 142.690 | 73.743 | 145.709 | 97.6% |
| M5 Full | 136.071 | 37.991 | 94.962 | 56.971 | 29.581 | 53.697 | 91.379 | 70.2% |
| M2 Full | 250.127 | 61.134 | 171.135 | 110.001 | 57.538 | 79.008 | 132.121 | 67.2% |

The NAS-controlled maximum also spent about 125 s on the application's final full-file playback
check, included in export wall time; its common check took about 22 s. The Kubernetes maximum's
check took about 38 s. The extra independent decode after each run is excluded from these timers.
Both remote variants used the same GPU worker and balanced NVENC policy, but their render times
still differed. This single shared-service sample does not isolate the cause of that difference.

## Feature evidence and remaining warnings

The fresh bank contains the following persisted results. Basic has no caption or Laya pass by
design. Caption rows and Laya audience answers demonstrate work performed, not just configuration
flags. Full also requires no unread demanded-episode warning. The counts are after the common
film and its maximum export where applicable; maximum reuses selection.

| Configuration | Caption descriptions | Laya audience answers | Motion descriptions |
| --- | --- | --- | --- |
| NAS Basic | 0 | 0 | 0 |
| NAS + GPU service | 20 | 16 | 0 |
| Kubernetes GPU | 20 | 16 | 0 |
| M5 Full | 70 | 21 | 0 |
| M2 Basic | 0 | 0 | 0 |
| M2 Full | 81 | 21 | 0 |

- Cold selection still uses the documented plain-facts fallback for missing optional motion
  descriptions. This matrix does not count motion descriptions as exercised or fixed.
- NAS Basic's title kernel reports an illegal instruction on the J4125 and falls back to static
  PIL title plates with fades. A completed film does not establish animated-kernel support there.
- Basic recorded a one-frame clip underrun; final output validation and full decoding passed.
- Mixed HLG/PQ inputs are converted to SDR for common exports and PQ for maximum exports.
- Laya's installed checkpoint reports clamped out-of-range temperatures. The affected confidence
  buckets remain uncalibrated; this run tests execution, not classifier calibration.

GPU Operator time-slicing shares still refer to one physical card. They do not create separate
VRAM pools or unload application models. The successful sequence tests this installed service
arrangement with benchmark jobs serialized. It does not prove arbitrary competing workloads
cannot exhaust the same card.

## Setup failures retained outside the accepted timings

The first attempt was not trouble-free. These corrections preceded the final cold acceptance;
no failed work was silently spliced into its phase totals:

- macOS archive metadata produced `._*.py` migration files on Linux; the failed Kubernetes
  start took 2.001 s. The transport now uses
  `COPYFILE_DISABLE=1 tar --no-xattrs`; the failed starts and logs remain in private evidence.
- DSM does not provide Docker's CFS quota interface here. The harness uses four-CPU affinity
  with the same 4 GiB memory limit instead of `--cpus`.
- The detached M2 SSH launcher could not reach Immich. The same inventory request succeeded
  in an attached session, which was kept open for the acceptance sequence. No application
  cache was produced by the failed connectivity checks.
- An overwritten unified worker URL lost its `/render` suffix. Inference health answered, but
  the renderer correctly rejected it. That Kubernetes attempt took 197.747 s. Correcting both
  GPU configurations and checking `/render/health` preceded a fresh run.
- The reused inference image lacked `pi-heif`, causing selected HEIC sources to fail remote
  assembly after 167.827 s. Installing declared dependency `pi-heif==1.4.0` and decoding a real rejected HEIC
  fixed the runtime. The current inference Dockerfile already installs the project dependencies;
  copying new source into an older image does not update those dependencies.
- Pulling the rebuilt ACE image briefly caused node disk pressure; kubelet recovered without
  manual deletion. Image transfer and scheduling time are outside the film timer.
- NAS GPU's first attempt stopped after 103.103 s because the temporary worker's LoadBalancer
  timed out. The same worker answered through the endpoint node's NodePort. Setting that test
  service's `externalTrafficPolicy: Local` moved MetalLB's announcement to the GPU endpoint node;
  inference then responded from the actual NAS container in 0.01 s and authenticated render
  health passed. The failed store was archived before another cold run. This is a correction to
  the temporary deployment, not an application fix or a universal requirement for all clusters.

## Repeating the workload

After installing the tier and its services, fetching the models and passing preflight, the common
command is:

```bash
immich-memories generate --memory-type monthly_highlights --year 2023 --month 6 \
  --duration 60 --resolution 1080p --orientation landscape \
  --music auto --add-date --add-place
```

Use an empty application profile and cache for a cold measurement, retain installed model weights,
and record the effective config. The profiles in this matrix explicitly set 60 fps, SDR and
`balanced` quality. The command alone does not set all three. Do not use `high` for this comparison.
For GPU/Full only, render the resulting saved run at 4K with HEVC and HDR enabled in its output
config, keep 60 fps and balanced quality, and choose an empty render-cache directory. Never request
a 4K Basic comparison.

The private evidence retains inventories, exact commands/configs, failed attempts, source hashes,
phase spans, process-tree samples, full-file decode logs and output checksums. The comparison album
uses hardware, tier, common/maximum output, source revision and music tags. Household media, raw
logs, asset IDs, private hostnames, album links and credentials are excluded from this report.


## Separate fresh Docker first-film gate

The default Basic Docker path also completed on the Synology NAS with a **new persistent volume,
fresh model fetch and no source overlay or runtime dependency installation**. This is an eleventh
film, separately tagged in the private album; it is outside the controlled six-configuration matrix.

The unchanged shipping `docker/Dockerfile` built Linux amd64 with its default `all` extras from
the same application source. Local candidate package version: `1.0.0.dev20261003+g4b98c1992`.
Image identity: `sha256:f62dbfa8d8c86c1564f7d504ee5c1d3677fc448a321b731cbb8c76e32e1a43b6`. This locally built pre-RC candidate is not a published RC1 artifact.
The image contained the installed application, `pi-heif`, ONNX Runtime, Demucs, bundled music and
the web client. The NAS loaded the exact verified image. No package was added after image creation.

The shipped Compose recipe ran as UID 1000 with its default 4 GiB memory limit. Changes were only
the local candidate tag, an isolated project/container name and host port 18081 because the NAS
already uses 8080. The documented output-folder ownership step was applied. No hardware render
device was passed through; this tests the default software-rendering path. The UI health check
passed and `/app` returned HTTP 200. Generation below used the CLI; the DSM Project wizard was
not part of this check.

After `immich-memories models fetch` and `immich-memories preflight`, one command completed:

```bash
immich-memories generate --year 2023 --month 6 --duration 60 \
  --output /app/output/june-docker.mp4
```

The output is 1920×1080, 60/1 fps,
h264, 59.633 seconds,
40,975,087 bytes, with audio and bundled music. Complete video/audio decoding
passed, and the copied file's SHA-256 matched the container's original.

Preflight exited successfully with five OK checks, four warnings and nine skipped optional checks.
The warnings covered the existing broad Immich key, unset home coordinates, simpler title rendering
on this CPU and unavailable hardware encoding. Home coordinates are optional for this monthly film;
new installs should use the documented minimum API-key permissions. Basic used bundled music.
No missing dependency or runtime repair was needed between startup and the completed film.

| Documented install / validation phase | Wall seconds |
| --- | --- |
| load image | 86.444 |
| output permissions | 3.610 |
| compose up | 2.300 |
| models fetch | 6.804 |
| preflight | 19.197 |
| generate | 1,735.796 |
| full decode | 21.339 |

Image build/export and transfer are installation work, not film generation. The local build first
hit a full Docker Desktop disk; clearing builder space preceded the successful unchanged build.
This does not require a NAS user to build from source: the intended RC route supplies the image.
This gate establishes a clean default Docker install and uninterrupted first CLI film for this
candidate. The matrix above separately exercises the GPU services and native Mac features.
