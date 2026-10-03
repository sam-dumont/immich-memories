# February 2024 hardware smoke test, 3 October 2026

All six configurations delivered a 1080p60 SDR film. The four eligible GPU/Full configurations
also delivered 4K60 HDR films. Every delivered file passed complete video/audio decoding.
**NAS Basic and M2 Basic remain 1080p only.** Default `balanced` quality was used throughout.
The private album contains 21 tagged outputs, including earlier fallbacks and repaired versions.

Fresh confirmations completed on M5 Full (253.593 s), M2 Full (583.562 s) and Kubernetes GPU
(751.999 s on one physical T1000). NAS Basic and NAS GPU retain their original successful runs.
M2 Basic retains its original preparation and a successful render/music retry. This is a measured
smoke checkpoint, not six uninterrupted runs on one current-main revision or a clean-install
qualification. Motion-description gaps remain, and M5 Full used factual fallback for one episode.
Both PRs remain draft pending the remaining feature and installation qualification.

The workload targets 60 seconds, with titles, transitions, date/place captions, photos, videos,
Live Photos and music requested. No `high` quality preset was used. NAS Basic uses bundled music;
the final other five common films and all four maximum films have ACE-Step music and four-stem
mixing. Household media, asset IDs, private logs, album links and credentials are not published.

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

## Initial checkpoint: delivered outputs and total times

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
The six common outputs took priority during the first pass. Later maximum exports and repairs
are recorded below; this failed attempt contributes no 4K performance claim.

## Maximum-resolution follow-up

Basic is capped at 1080p on NAS and M2. Maximum 4K exports apply only to NAS GPU, Kubernetes GPU,
M5 Full and M2 Full. The harness incorrectly attempted maximum exports on Basic; those attempts
are excluded. The M2 output was correctly capped by the application at 1920×1080, and its extra
variant was removed from the comparison album. The NAS attempt was stopped.

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
fix. Keep that revision difference when reading the comparison. Later exports and cold confirmations are recorded below. This earlier result stays separate.

### M2 Full and Kubernetes GPU follow-up

Both saved cuts also produced 3840×2160, 60 fps, HEVC, 10-bit PQ HDR with BT.2020 primaries
at balanced quality. Full-file decoding passed. These reuse selection; they are export timings.

| Configuration | Export wall | Render | Original music phase | Original output bytes | Music outcome |
|---|---:|---:|---:|---:|---|
| M2 Full | 257.069 s | 220.331 s | 15.544 s | 68,882,034 | Bundled fallback: local memory guard |
| Kubernetes GPU | 999.359 s | 919.246 s | 27.468 s | 106,857,116 | GPU OOM; no added music |

Kubernetes then completed a **music-only repair in 140.068 s**, including ACE-Step generation
and four-stem Demucs mixing. It reused the existing 4K video; no selection or encoding was repeated.
The repaired film is 107,715,532 bytes and passed full decoding. The album keeps both versions,
with the original fallback and the repaired maximum explicitly tagged. The earlier 1080p
Kubernetes soundtrack repair took 197.506 s and also passed decoding.

M2 Full subsequently completed a saved-cut 1080p render plus local generated music and all four
stems in 137.184 s. That film passed decoding and was uploaded separately. Its selection is still
from the first pass. That earlier M2 4K film keeps its bundled soundtrack. The final cold run and paired maximum
below use generated music; a standalone music probe was not counted as a film pass.

## Final confirmations and paired maximum exports

The following cold confirmations started with empty app/media/analysis/render caches and the
same source inventory. Installed weights stayed in place. Each command finished without a
phase restart, including generated music and four-stem mixing. Full-file decoding passed.
Selection changed on the smaller Mac after changing its caption backend, so these remain
same-workload comparisons rather than identical-cut comparisons across every machine.

| Cold configuration | Wall | Pipeline | Startup | Discovery | Selection | Render | Clip preparation | Assembly | Music | Output MB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M5 Full | 253.593 | 252.619 | 4.264 | 0.216 | 177.806 | 42.520 | 14.806 | 27.711 | 23.343 | 21.92 |
| M2 Full, llama.cpp caption service | 583.562 | 582.204 | 4.450 | 0.236 | 432.049 | 69.901 | 22.523 | 47.373 | 67.359 | 39.18 |
| Kubernetes GPU, one T1000 | 751.999 | 746.066 | 10.044 | 0.253 | 205.693 | 352.776 | n/a | 352.744 | 164.138 | 42.58 |

M5 now exercised Laya and the Full reader. Its stored warnings still report missing optional
motion descriptions and one unread demanded episode. M2 Full exercised both and had no unread
episode warning, but optional motion descriptions were still missing. Kubernetes also reported
missing optional motion descriptions. These features are not marked as fully exercised.

M2 Basic's final saved-cut render/music retry took **134.060 s**, including 63.112 s render and
63.373 s music. Its 34,480,812-byte film is **1080p60 SDR**, with local ACE-Step and four stems.
The original successful preparation remains measured at 170.275 s; adding the successful retry
from render start through completion gives a **298.654 s composite pipeline**. This is not a new
cold run. Its original failed work and earlier bundled fallback remain in the initial tables.

### What maximum output cost on the Macs

Each pair below uses the same cut within that machine's final run. Both maximum films are
3840×2160 at 60 fps, HEVC, 10-bit PQ HDR with BT.2020 primaries. Both passed complete decoding.
Maximum wall time is a saved-cut export, not another cold selection.

| Configuration | Maximum export wall | 1080p render | 4K render | Extra render | Maximum music | 1080p bytes | 4K bytes | File increase |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M5 Full | 127.934 s | 42.520 s | 86.436 s | 43.916 s | 31.269 s | 21,921,609 | 40,101,960 | 83% |
| M2 Full | 304.711 s | 69.901 s | 180.407 s | 110.506 s | 103.942 s | 39,181,431 | 73,369,904 | 87% |

The gain is four times the output pixels plus a 10-bit HDR output; frame rate stays at 60 fps.
This does not turn lower-resolution or SDR sources into native 4K HDR detail. Music is regenerated
per export. The M2 maximum also selected a later mastered music candidate, so its extra music
time must not be attributed to output resolution.

### GPU maximums and recovery cost

The Kubernetes maximum above retained its video and completed its 140.068-second music repair.
The NAS GPU maximum export took **1,095.863 s**, produced a decoded 4K60 HDR film, then completed
its **music-only repair in 157.558 s**. Its final file is 107,750,044 bytes. The NAS export retry
reused downloads from the failed maximum attempt; it is not a fresh-cache 4K measurement.

To repair NAS music without another encode, source audio was restored from the retained
Kubernetes 4K base. The plan digest, clip order, encoding plan, mute windows and duration matched
exactly. The NAS video packets were unchanged, verified by hashing. Both GPU maximum films now
contain ACE-Step music and four stems and passed full decoding. Earlier fallback films remain
separately labelled in the album. Recovery time is additional work, not a replacement for the
original failed music timing.

### Memory handoffs: fixes and remaining limits

The fixes release the scene-print encoder, reset the native title runtime before releasing the
GPU render phase, and collect unreachable local model owners before clearing allocator caches.
A real T1000 4K title probe freed 610 MiB and produced identical pixels after reinitialization.
A smaller-Mac Laya probe freed about 780 MiB more after cyclic garbage collection.

The M2 reader was already bundled llama.cpp. The separate MLX caption service occupied about
2.3 GiB of physical memory; process RSS alone understated it. A cold Full retry with that service
still fell short of the unchanged 7 GiB music guard. Replacing that caption process with
llama.cpp SmolVLM2 Q8_0 reduced its measured physical footprint to about 507 MiB (528 MiB peak in
three structured controls). The next cold Full run, its maximum export and the Basic saved-cut
repair all completed local music. The measured caption setup is documented in the
[caption service reference](../../docs-site/docs/reference/caption-service.md). This was a running
service replacement, not a demonstrated fresh install or an automatically managed startup service.

One NAS maximum OOM occurred after benchmark uploads triggered Immich ML jobs on the same GPU.
That was benchmark interference: serial generation commands did not prevent upload-triggered
OCR/face/CLIP work. Later GPU measurements ran before further uploads. Following an OOM,
ACE-Step retained about 3.7 GiB despite CPU offload settings, and the next cold selection failed.
After checking that no music jobs were running or queued, the existing ACE-Step deployment was
restarted once. A saved-preparation retry then passed in 474.502 s; the independent cold
confirmation above passed in 751.999 s. The earlier failed cold attempt took 215.502 s and is not
hidden inside either successful timing.

**ACE-Step recovery after OOM remains unresolved.** The successful one-GPU run proves this
workload can finish in one go with services in a healthy state and without competing upload jobs.
It does not prove automatic recovery after OOM or reliable co-scheduling with arbitrary GPU jobs.
GPU Operator time slicing does not unload models on behalf of the application.

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

The final cold confirmations and paired Mac exports ran commit
`b9e89f0dc2485dc8830c1ee95ca105ab181ce2e0` plus patch SHA-256
`694c918dcc06188adbf1228e9208edf5225b684f96a7109fb9a79d13e06b259d`.
The patch's production changes are committed in `5970d39ea`; the executed snapshot remains
identified separately. The render service had the title-runtime cleanup overlaid on `c96b7fb18`.
Main advanced during measurement, including place/title changes in #1947. These results have
not been relabelled as measurements of that later main. Do not treat this batch as a uniform
revision comparison.

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
  reader, caption service, renderer allocation or host pressure was not established at that handoff.
  Follow-up measurements found the separate caption server at 2.3 GiB physical footprint. Local
  music nevertheless completed with that server present. A synthetic Laya load/close probe freed
  about 780 MiB more after cyclic garbage collection, even after the existing allocator cleanup.
  The proposed handoff now collects unreachable Python objects before clearing runtime buffers;
  the final cold confirmation above passed after also replacing the separate caption service.
  The guard remains unchanged.
- **Single-GPU music:** ACE-Step exhausted the shared T1000 in all three Kubernetes attempts.
  Its error reported only 14.44 MiB free. Existing inference processes later accounted for about
  1.6 GiB, but attribution at the failed handoff is incomplete. Sequential steps alone do not prove
  that the previous step freed VRAM. A later 4K attempt also exhausted VRAM. The title runtime
  retained native allocations after its Python renderers were dropped: a real 4K CUDA probe freed
  610 MiB by releasing that runtime, then rendered an identical frame after reinitialization.
  The worker fix releases it before relinquishing the render phase. The music-only repairs passed;
  the final cold one-GPU confirmation passed. Recovery after ACE-Step OOM remains unresolved.
- **Motion descriptions:** [#1633](https://github.com/sam-dumont/immich-memories/pull/1633) made missing
  optional descriptions fall back to plain facts. Cuts do not acquire those lines; preparation does.
  Motion-description coverage was absent here. Live Photo playback and motion measurement are
  separate features. The original M5 plan recorded zero story-motion-description requests.
- **Reader fallback:** each initial Full run had one unread demanded episode and used factual fallback.
  The final M5 confirmation still did; the final M2 confirmation did not.
  M5 reader calls ended with `finish_reason=stop`; this does not match the older oMLX truncation report.
- **NAS titles:** the J4125 title kernel probe hit an illegal instruction; static PIL plates with fades
  completed the film. This is the documented CPU fallback, not a demonstrated new regression.

Passing preflight or `make check-local-audio` alone does not prove the whole film pipeline can hand
memory from selection/rendering to music. A clean-install repeat must use the documented versioned
install route, run preflight, and then finish the same film with every requested service enabled.
The install corrections in this PR are documentation changes; they do not claim such a repeat passed.

The accompanying [CSV](2026-10-03-february-hardware-smoke.csv) preserves the original six-row
checkpoint. The final measurements above are additional observations, not silent replacements.
Private run stores, source manifests, phase trees, logs and decoded films were retained separately.
