# February 2024 hardware smoke test, 3 October 2026

Six configurations produced a film and passed full video/audio decoding. Four initial commands
completed; M5 Full and M2 Basic completed after saved-cut render retries. This is a first-pass
checkpoint, not six clean full-feature passes and not a clean-install qualification.

All six delivered films are landscape 1920×1080, H.264, 60 fps, SDR BT.709, at the default
`balanced` quality. The target was 60 seconds. Titles, transitions, date/place captions,
photos, videos, Live Photos and music were requested. No `high` quality preset was used.
The private comparison album contains all six, with hardware, tier, variant and source tags
read back and album membership verified. Household media, asset IDs, private logs, album
links and credentials are not part of this report.

## Workload and cold boundary

Each initial run queried 1–29 February 2024: 2,032 source assets (1,737 images and 295 videos),
1,072 eligible preparation items and 15 selected output shots. The same source-inventory
fingerprint was required before every run. Previously uploaded benchmark outputs were excluded
by their exact owned output IDs, leaving the original source fingerprint unchanged.

Each configuration began with an empty app store, analysis bank and media/render caches.
Installed model weights were retained. OS page caches and external services were not reset.
Mac caption servers were already running; the isolated combined GPU worker started cold.
Prebuilt environments were reused. This is cold application data, not six new installations.

Initial measured runs were serial. The last two repairs overlapped only across separate Macs,
with M5 in local music while M2 prepared its output; they shared no GPU. One sample per cell.
Production services remained active. Setup, dependency/model installation, inventory checks,
post-run full-decode verification and album upload are outside the wall timer. Application
validation inside generation remains inside it.

## Hardware and runtime boundaries

| Configuration | Hardware | Resource boundary |
|---|---|---|
| NAS Basic | Synology DS423+, Intel Celeron J4125, Intel UHD 600 VAAPI | 4 CPU affinity, 4 GiB container limit; host about 17.4 GiB |
| NAS + GPU service | Same NAS controller; NVIDIA T1000 8 GB on an i9-13900T Kubernetes worker | NAS 4 CPU/4 GiB; worker 4 CPU/8 GiB; Laya ran on the NAS CPU |
| Kubernetes GPU | i9-13900T VM, 16 visible CPUs, NVIDIA T1000 8 GB | Controller and combined worker in a 4 CPU/8 GiB pod |
| M5 Full | Apple M5 Max, 18 CPU cores, 128 GiB unified memory | Native process, no container memory cap |
| M2 Basic | Apple M2 Pro, 10 CPU cores, 16 GiB unified memory | Native process, no container memory cap |
| M2 Full | Same M2 Pro | Native process, no container memory cap |

Both GPU configurations used **one physical T1000**, shared with the existing ACE-Step service
and other cluster workloads. GPU Operator advertised eight time-slicing shares. Shares do not
provide eight independent memory pools or automatic model eviction. The acceptance target stays
one physical GPU for inference, rendering and music; adding another card is not the remedy.

The NAS runtime used Python 3.11.15 and FFmpeg 7.1.5. Kubernetes used Python 3.12 in the CUDA
inference image, with the app source overlaid. The native environments used Python 3.12.11 on M5
and 3.12.14 on M2. The resumed Mac renders and the fresh M2 Full run selected Homebrew
`ffmpeg-full`; the initial M2 Basic harness incorrectly selected the minimal FFmpeg build.
Both Full configurations used the same pinned Gemma reader weights through local llama.cpp
0.5.0, build 11146 (`7fe450e19`), not oMLX. The separate caption endpoint used SmolVLM2 500M.
The CUDA inference image used as the Kubernetes controller was not a fresh generated app install;
its bundled-music fallback was not demonstrated.

## Delivered outputs and total times

Seconds throughout; output sizes are decimal MB. Raw wall time includes the CLI wrapper.
The pipeline column uses the app's root span, with the two composites defined below.

| Configuration | Original wall, including failures | Successful pipeline | Output MB | Music outcome |
|---|---:|---:|---:|---|
| NAS Basic | 1,503.513 | 1,500.872 | 34.43 | Bundled (requested baseline capability) |
| NAS + GPU service | 1,002.147 | 1,000.238 | 42.58 | ACE-Step service + 4-stem mixing |
| Kubernetes GPU | 447.660 | 445.661 | 41.70 | Generation failed: GPU OOM; no added soundtrack |
| M5 Full | 215.543 | 263.110* | 21.92 | ACE-Step local + 4-stem mixing |
| M2 Basic | 254.739 | 248.731* | 34.48 | Bundled fallback: memory guard |
| M2 Full | 578.480 | 577.697 | 35.68 | Bundled fallback: memory guard |

The 12.189-second Kubernetes music phase is a failed generation attempt, not a music speedup.
Likewise, the M2 bundled fallbacks cannot be ranked against successful generated music on M5.
NAS Basic intentionally used bundled music. NAS GPU and resumed M5 Full completed ACE-Step
music and four-stem Demucs mixing. Kubernetes retained source audio after generated music failed;
the warning claimed a bundled substitution, but no bundled track selection or mix was recorded.

## Detailed phase times

Selection includes its picture preparation, model calls and editorial work. Clip preparation and
assembly are children of render: **do not add them to render again**. The remote GPU path records
source preparation inside remote assembly, so its clip-preparation column is unavailable, not zero.
Music is a separate span after render. Startup, discovery and these named spans do not exhaust
all root-span bookkeeping. For repaired rows, startup/discovery/selection are from the original
run; render and music are from the successful retry.

| Configuration | Startup | Discovery | Selection | Render | Clip preparation | Assembly | Music |
|---|---:|---:|---:|---:|---:|---:|---:|
| NAS Basic | 15.287 | 0.331 | 994.382 | 440.185 | 168.458 | 271.669 | 31.556 |
| NAS + GPU service | 12.160 | 0.325 | 514.264 | 169.287 | n/a | 169.258 | 289.932 |
| Kubernetes GPU | 7.620 | 0.235 | 210.317 | 215.072 | n/a | 215.062 | 12.189 |
| M5 Full | 4.684 | 0.207 | 191.874 | 36.621 | 7.621 | 28.986 | 25.150 |
| M2 Basic | 5.217 | 0.239 | 164.660 | 61.635 | 14.004 | 47.619 | 14.936 |
| M2 Full | 4.550 | 0.221 | 431.814 | 113.237 | 64.953 | 48.278 | 19.507 |

### Failed work and saved-cut recovery

| Configuration | Original failed wall | Render retry wall | Failure and recovery |
|---|---:|---:|---|
| M5 Full | 215.543 s | 67.490 s | Reused environment lacked `pi-heif`; installed the dependency and rendered the saved cut |
| M2 Basic | 254.739 s | 83.753 s | Harness chose FFmpeg without `zscale`; selected existing `ffmpeg-full` and rendered the saved cut |

The starred pipeline totals are `original root start → original render start` plus
`successful retry render start → retry root end`. They preserve the successful original
preparation/selection work. They exclude failed render work and retry startup from the comparison,
but those costs remain in the raw wall and retry columns. They are not uninterrupted cold runs.
Render cleanup had removed intermediate clips, so the render retry rebuilt them; no selection
or analysis cold restart was needed.

A redundant M5 cold retry was stopped after 72.438 s and excluded. An M5 resume command was
rejected before generation because the harness passed `--format h264` rather than `--format mp4`;
that attempt is also excluded. An initial NAS transfer failed because macOS archive metadata
was mistaken for migration input. These are harness failures, not application speed measurements.

The NAS GPU 4K/HDR saved-cut attempt failed after 375.251 s during title construction because
its original run had no persisted date range. No maximum-resolution film was produced.
The six common outputs took priority during the first pass. Maximum-capability 4K exports are
required before the documentation PR becomes ready, alongside uninterrupted end-to-end passes
for all six configurations. Verify 60 fps and HDR where supported, using default balanced quality.
No 4K/HDR performance or correctness claim comes from this checkpoint.

## Maximum-resolution follow-up

The M5 Full saved-cut export completed after the first-pass checkpoint. Full-file decode passed:
3840×2160, 60 fps, HEVC, 10-bit PQ HDR with BT.2020 primaries, default balanced quality. Local
ACE-Step generated the soundtrack and local Demucs returned all four stems. The film was uploaded
to the same comparison album with hardware, tier, output and source tags verified.

| M5 Full saved-cut export | Common 1080p | Maximum 4K HDR |
|---|---:|---:|
| Export wall time | 67.490 s | 117.880 s |
| Render span | 36.621 s | 85.682 s |
| Music span | 25.150 s | 21.684 s |
| Output bytes | 21,921,671 | 40,086,380 |

The 4K render cost 49.061 s more and the file grew by 18,164,709 bytes (83%). It provides four
times the output pixels and a 10-bit HDR output instead of 8-bit SDR. Both exports are 60 fps.
Music is generated separately for each export; its timing difference is not a resolution gain.

This export reused the original selected cut. It does not repair the missing Laya exercise in the
first-pass selection or count as a clean end-to-end acceptance run. Rendering used main
`c96b7fb18` plus the tested smoke fixes; the earlier common repair used `288215135` plus the date
fix. Keep that revision difference when reading the comparison. The remaining maximum exports and
the six uninterrupted acceptance runs are still required before the PR becomes ready.

## Source provenance

The first four attempted configurations (NAS Basic, NAS GPU, M5 Full and M2 Basic) executed
`a3bfc5dbe66efceaf6985abed72c78600a0fbb37`. That was the frozen local revision, not the then-latest
remote main. This was a harness mistake; the measurements have not been relabeled.

Kubernetes GPU, M2 Full and the two successful saved-cut retries executed
`2882151357fd013334c8696bddf19a5765181efd` plus a local date-persistence fix in `generate.py`.
Patch SHA-256: `2589569807edbdff4cee28a520cf2a56a2a791c2b0d789dd1a2bd4dffc86841d`.
The fix records the resolved calendar range for both new and observed runs before rendering;
149 focused generation/saved-cut tests passed. Existing benchmark records were corrected from
their preserved original February CLI requests, without changing timings.

Processing, titles, audio and render-worker implementation files were byte-identical between the
two base revisions. That supports retaining those phase measurements; it does not turn this into
a uniform-current-main matrix. The new documentation PR is separate from the unmerged code fix.

## Memory observations

Process-tree RSS sampled once per second, in GiB. External services are excluded; these are
controller observations, not total system or GPU memory. The Kubernetes pod includes a separate
worker process outside the controller tree. Its observed cgroup peak was about 5.0 GiB with no
cgroup OOM events. The music failure was GPU VRAM exhaustion, not that pod's RAM limit.

| Configuration | Original controller peak | Retry controller peak |
|---|---:|---:|
| NAS Basic | 0.950 | n/a |
| NAS + GPU service | 1.937 | n/a |
| Kubernetes GPU | 1.507 | n/a |
| M5 Full | 7.444 | 6.232 |
| M2 Basic | 2.423 | 2.434 |
| M2 Full | 7.109 | n/a |

## Install findings and remaining qualification gaps

- **HEIC:** `pi-heif` is already a base dependency after [#1893](https://github.com/sam-dumont/immich-memories/pull/1893).
  Copying new source onto an old virtual environment skipped that dependency update. Sync or reinstall
  the chosen version with its extras; model weights and an old environment are different things.
- **Mac Laya:** `all-mac` and `make dev-mac` do not include `laya-mlx`. The reader reference mentions
  the separate install, but the main Mac recipe omitted it. M5 therefore used heads/rules for the
  audience check; M2 Full did exercise Laya. The install instructions need the requirement at the
  point of installation. The six films do not establish identical audience-feature coverage.
- **FFmpeg:** the Python install page already specified `ffmpeg-full` and `zscale`. The harness
  chose the wrong binary on M2 Basic. Verify the effective executable in the app's launch environment,
  including a service's PATH, rather than just checking whether Homebrew has installed the package.
- **M2 music:** ACE-Step's local memory guard refused the 7 GB profile with 5–6 GB available on Full;
  Basic also hit the guard. Full used bundled llama.cpp. The reader was absent when checked after
  completion, but no process-by-process memory snapshot exists at the failing handoff. A retained
  reader, caption service, renderer allocation or host pressure has not been established as the cause.
- **Single-GPU music:** ACE-Step exhausted the shared T1000 in all three Kubernetes attempts.
  Its error reported only 14.44 MiB free. Existing inference processes later accounted for about
  1.6 GiB, but attribution at the failed handoff is incomplete. Sequential steps alone do not prove
  that the previous step freed VRAM. Fix and verify the complete one-GPU pipeline in one run.
- **Motion descriptions:** [#1633](https://github.com/sam-dumont/immich-memories/pull/1633) made missing
  optional descriptions fall back to plain facts. Cuts do not acquire those lines; preparation does.
  Motion-description coverage was absent here. Live Photo playback and motion measurement are
  separate features. The original M5 plan recorded zero story-motion-description requests.
- **Reader fallback:** each Full run had one unread demanded episode and used factual fallback.
  M5 reader calls ended with `finish_reason=stop`; this does not match the older oMLX truncation report.
- **NAS titles:** the J4125 title kernel probe hit an illegal instruction; static PIL plates with fades
  completed the film. This is the documented CPU fallback, not a demonstrated new regression.

Passing preflight or `make check-local-audio` alone does not prove the whole film pipeline can hand
memory from selection/rendering to music. A clean-install repeat must use the documented versioned
install route, run preflight, and then finish the same film with every requested service enabled.
The install corrections in this PR are documentation changes; they do not claim such a repeat passed.

The accompanying [CSV](2026-10-03-february-hardware-smoke.csv) contains only these aggregate timings, sizes and revisions.
Private run stores, source manifests, phase trees, logs and decoded films were retained separately.
