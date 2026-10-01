---
title: Measure your setup
---

# Measure your setup

A faster picture model does not guarantee a faster film. Downloads, picture preparation, captions, selection, encoding and music have different costs. Look at the stage that is slow on your machine before adding a service.

## Read one run

```bash
immich-memories runs show RUN_ID
immich-memories report RUN_ID
```

The run reports phase timings, memory and delivery. Review the report before sharing it; it sends nothing itself.

## Compare fairly

Make the same cut twice. The first run may acquire media and prepare facts; the second reuses compatible work. Keep those results separate.

When comparing an add-on, keep the scope, configuration and output format fixed. Record the commit, hardware and cache state. Compare the shots and the finished film as well as the elapsed time.

A local reader and local audio can share machine memory when the app owns their runtimes. An external server keeps its own memory resident until its own policy releases it. This can affect whether another model fits even while the server is idle.

## Inspect capabilities

```bash
immich-memories capabilities
```

This labels configuration and installation checks separately from generation evidence. It does not prove that every selected picture or finished film is right.

The [measurement reference](../reference/performance-evidence.md) explains the scopes to record for picture work, selection, rendering and music.

The [hardware guide](../run/hardware.md) covers encoding and title effects. The [preparation reference](../reference/preparation.md) explains the work that can be reused. For reproducible whole-film comparisons, use [release films](../contribute/setup-matrix.md).

## Whole-film controls, 1 October 2026 {#whole-film-controls}

Fourteen of the fifteen release controls have passed film, audio, source-scope and cache checks;
all fourteen have verified latest uploads to Immich. The Linux CUDA worker person control remains
pending. The trip passed after a separate native-audio recovery. Failed attempts do not count as
completed films.

These runs reused compatible picture facts and made fresh editorial decisions. Original-media
acquisition, titles, rendering and music still ran. Different tiers, source revisions and realised
cuts make this a completion matrix, not a controlled speed comparison. A later patch does not
change the timings of an accepted run.

| Hardware and tier | Film | Whole run | Film seconds | Output | Runtime source |
|---|---|---:|---:|---|---|
| NAS / NAS | Month | 7m 23s | 60.817 | 1080×1920, 60 fps, SDR | `c4c7356304c5` |
| NAS / NAS | Person | 78m 51s | 605.350 | 1080×1920, 60 fps, SDR | `dec8f20e609c` |
| NAS / NAS | Trip | 17m 33s | 164.967 | 1920×1080, 30 fps, SDR | `dec8f20e609c` |
| Linux CUDA worker / GPU | Month | 24m 01s | 60.900 | 2160×3840, 60 fps, HDR10 | `2a2cadccf7e4` |
| Linux CUDA worker / GPU | Trip | 67m 53s original; 8m 01s audio recovery | 164.967 | 3840×2160, 30 fps, HDR10 | `4913c3892695` |
| M2 16 GiB / Full | Month | 15m 29s | 60.400 | 2160×3840, 60 fps, HDR10 | `f74936b657d7` |
| M2 16 GiB / Full | Person | 87m 23s | 605.350 | 2160×3840, 60 fps, HDR10 | `4db52f365a5e` |
| M2 16 GiB / Full | Trip | 35m 05s | 165.433 | 3840×2160, 30 fps, HDR10 | `03cc7f56c122` |
| M2 16 GiB / GPU | Month | 7m 18s | 60.900 | 2160×3840, 60 fps, HDR10 | `f74936b657d7` |
| M2 16 GiB / GPU | Person | 59m 47s | 604.850 | 2160×3840, 60 fps, HDR10 | `4db52f365a5e` |
| M2 16 GiB / GPU | Trip | 26m 00s | 165.033 | 3840×2160, 30 fps, HDR10 | `f82de21b5bf5` |
| M5 / Full | Month | 5m 43s | 60.400 | 2160×3840, 60 fps, HDR10 | `cb06e4ba0e0d` |
| M5 / Full | Person | 39m 40s | 605.350 | 2160×3840, 60 fps, HDR10 | `f82de21b5bf5` |
| M5 / Full | Trip | 18m 42s | 165.433 | 3840×2160, 30 fps, HDR10 | `f82de21b5bf5` |

Whole run is the measured end-to-end control time. Film seconds are the actual output duration;
month and person cuts differ slightly between tiers. HDR outputs use PQ. Runtime source identifies
the accepted run, including equivalent source trees recorded in the evidence.

The CUDA trip's original 4073.2 s includes failed music attempts. Its worker rendered the video in
3131.9 s. After the external ACE service was corrected, the production music phase took another
480.8 s without rerendering the video; the compressed video packets were unchanged. The finished
film passed complete video and audio decoding. These are separate measured intervals, not a
clean uninterrupted whole-film benchmark.

### Where the time went

| Hardware and tier | Film | Source preparation, s | Assembly, s | Music, s |
|---|---|---:|---:|---:|
| NAS / NAS | Month | 187.7 | 180.6 | 15.7 |
| NAS / NAS | Person | 1857.1 | 2135.0 | 163.2 |
| NAS / NAS | Trip | 516.6 | 286.3 | 42.9 |
| Linux CUDA worker / GPU | Month | Unknown | Unknown | Unknown |
| Linux CUDA worker / GPU | Trip | Unknown | Unknown | 480.8, separate recovery |
| M2 / Full | Month | Unknown | Unknown | 76.4 |
| M2 / Full | Person | 449.3 | 2353.2 | 237.5 |
| M2 / Full | Trip | 76.6 | 1254.6 | 136.4 |
| M2 / GPU | Month | Unknown | Unknown | 58.6 |
| M2 / GPU | Person | 481.4 | 2370.9 | 278.5 |
| M2 / GPU | Trip | 75.1 | 1265.7 | 131.2 |
| M5 / Full | Month | 32.0 | 116.0 | 23.7 |
| M5 / Full | Person | 301.5 | 1069.2 | 103.2 |
| M5 / Full | Trip | 45.6 | 834.7 | 42.4 |

Stage records can overlap; do not add them into a new wall time. Assembly includes titles,
composition and encoding. These are not encoder-only timings. The CUDA month receipt records a
967.9 s worker-job lifetime but no complete three-stage breakdown. The trip's worker-job time is
also separate from assembly-only timing. Missing records stay unknown.

Assembly remains a large cost. The M5 Full person film spent another 670.3 s in selection and
analysis. The M2 Full trip spent 911 s rendering nine maps, about 43% of its whole run. The NAS
trip's nine maps took 39 s with lower resolution and reduced motion. Full and GPU retain smooth
animation; these are different profiles.

The route zoom and arrow correction in [#1700](https://github.com/sam-dumont/immich-video-memory-generator/pull/1700)
applies to ordinary maps too. The three-view shortcut in
[#1703](https://github.com/sam-dumont/immich-video-memory-generator/pull/1703) applies only when
`animated_background` is false. Selection-index reuse in
[#1706](https://github.com/sam-dumont/immich-video-memory-generator/pull/1706) and the lower-cadence HDR
conversion/audio-completion fix in
[#1709](https://github.com/sam-dumont/immich-video-memory-generator/pull/1709) landed after the listed
Mac and NAS controls. The CUDA worker is frozen at `4913c3892695`, before #1709. No whole-film
speedup is claimed for those patches.

### Native audio and encoding

NAS uses bundled music and hardware H.264 at 1080p, with Marqo and Docling off. Its trip opened
VAAPI for 54 compressed encodes. Mac and CUDA controls use native ACE-Step audio and Demucs
separation. A synthetic audio probe alone does not prove that a person film's full workload fits.

The Mac month controls generated one 88 s take each; the CUDA month generated three 88 s takes.
Accepted Mac trip controls generated two 120 s takes each. The recovered CUDA trip also used
two finite 120 s native takes and four finite winning Demucs stems, with no bundled substitution.
M2 GPU and M5 Full person generated
all three requested 120 s takes. These controls produced four finite Demucs stems.

M2 Full person generated two of three requested 120 s takes. The resident-weight admission guard
refused the first before generation. Its soundtrack repeats the two successful native tracks,
with four finite local Demucs stems and no bundled substitution. This qualification is part of
its accepted result.

An app-owned local reader releases its model before titles and rendering. In the M2 Full person
control, closing selection reduced MLX active memory from 842.6 MB to 22 bytes; its cache was zero
and its owned reader had exited before rendering. M2 GPU person also reached that boundary with
zero MLX cache and no owned reader. External model services retain their own unload policy;
later music work can reopen an app-owned reader.

M2 GPU person's 154 compressed encodes requested VideoToolbox. A hardware encoder does not
accelerate every step before it. CPU frame construction, map drawing, HDR conversion and copies
can still dominate a GPU worker. See [hardware encoding](../run/hardware.md).

The CUDA trip initially failed in the external ACE service's native FP16 input convolution: a
cuDNN path produced non-finite values on the 120 s workload. The deployed scoped correction at
ACE source `84bd5a2f3133` produced the real trip tracks. This external-service fix is separate
from the app-owned Linux and Mac model-lifetime validation.

### Memory scopes

Linux figures below are whole-container cgroup counters. RAM/combined means RAM and RAM plus
swap, respectively. Mac process-tree RSS can count shared mappings more than once. Parent physical
footprint excludes children. Whole-host swap can include other applications. GB is decimal here;
GiB is used explicitly for binary limits. These scopes do not form one interchangeable RAM requirement.

| Hardware and tier | Film | Recorded peak memory |
|---|---|---|
| NAS / NAS | Month | 1.833 / 1.844 GB cgroup RAM/combined |
| NAS / NAS | Person | 3.722 / 3.756 GB cgroup RAM/combined |
| NAS / NAS | Trip | 2.385 / 2.397 GB cgroup RAM/combined |
| Linux CUDA worker / GPU | Month | 5.517 GB worker cgroup; ACE service separate |
| Linux CUDA worker / GPU | Trip | 6.085 GB cumulative worker cgroup high-water; ACE recovery peak unknown |
| M2 / Full | Month | 12.38 GB process-tree RSS |
| M2 / Full | Person | 12.56 GB process-tree RSS; 11.72 GB parent footprint |
| M2 / Full | Trip | 13.04 GB process-tree RSS |
| M2 / GPU | Month | 11.81 GB process-tree RSS |
| M2 / GPU | Person | 11.86 GB process-tree RSS; 8.49 GB parent footprint |
| M2 / GPU | Trip | 12.63 GB process-tree RSS; 6.17 GB parent footprint |
| M5 / Full | Month | 15.78 GB process-tree RSS |
| M5 / Full | Person | 17.02 GB process-tree RSS; 16.62 GB parent footprint |
| M5 / Full | Trip | 15.47 GB process-tree RSS; 9.27 GB parent footprint |

All three NAS controls completed under the configured 4 GiB limit without OOM or allocation
failures. The CUDA month's external ACE service reached 10.110 GB in current samples. Its older
15.832 GB kernel high-water mark predates the run and is not a new peak for that control.
The trip worker's 6,084,993,024-byte high-water counter was cumulative, not reset for that run;
all memory-event counters remained zero. Separate ACE recovery memory was not recorded. Peaks
from separate services or different times are not summed.

M2 Full person had a transient 6628.94 MiB whole-host swap increase during selection and ended
145.37 MiB above baseline. M2 GPU person peaked 1667.13 MiB above baseline during native music
and ended 366.88 MiB above it. Swap was an accepted tradeoff. The three M5 controls recorded zero
increase over their existing host-swap baselines.

### Recorded model usage

| Full control | Calls | Prompt tokens | Cached prompt tokens | Completion tokens |
|---|---:|---:|---:|---:|
| M2 / Full month | 23 | 99515 | 9582 | 10319 |
| M2 / Full person | 109 | 635764 | 8129 | 24757 |
| M5 / Full month | 23 | 99515 | 9582 | 10320 |
| M5 / Full person | 109 | 635764 | 8130 | 24752 |
| M5 / Full trip | 50 | 188187 | 2979 | 4101 |

These counters belong to the current accepted attempts. Failed retries are excluded. Cached
prompt tokens remain a separate reported counter; no billing total is derived. Missing counters
stay unknown. Hardware, energy and hosted-price attribution were not measured, so there is no
trustworthy dollar total. Unknown cost does not mean free.

### Separate NAS 30-minute stress film

A 30-minute stress film on `f74936b657d7` completed in **4h 20m 45s** (15,645.4147 s), at
1080p portrait, 60 fps, SDR. All 423 compressed video encodes used VAAPI. Complete video/audio
decoding, visual review, cached facts and original-acquisition scope passed. This is separate stress
evidence and adds no credit to the fifteen-control matrix.

Container RAM peaked at 3,078,545,408 bytes. The observed combined RAM-and-swap high-water mark was
4,020,584,448 bytes (3.744 GiB), below the configured **4 GiB** limit of 4,294,967,296 bytes, with no
memory-limit failures. Actual sampled swap peaked at 1,827,979,264 bytes and ended at 7,974,912 bytes.
This result used swap. The memory hold was resolved against the confirmed configured 4 GiB limit;
the measured figures and the earlier hold against 4,000,000,000 bytes were preserved unchanged.

## Remaining performance work

Existing traces and source review found repeated full-frame work in smooth 4K maps and HDR titles.
[#1702](https://github.com/sam-dumont/immich-video-memory-generator/issues/1702#issuecomment-5937777886)
records a blank map feature layer of 126.6–506.3 MiB per moving frame, repeated tile decoding and
CPU frame construction before NVENC. Those are buffer sizes and observed stages, not a measured
speedup. [#1704](https://github.com/sam-dumont/immich-video-memory-generator/issues/1704#issuecomment-5938126498)
records the HDR title path falling back to CPU interpolation, blank-text compositing on textless
endings and white-fade arithmetic after GPU readback. Their implementation and timing validation
remain follow-up work.

The accepted controls stay evidence for their original revisions. Hosted-model comparisons and
the larger 28-by-2 film batch need their own matched scope and validation. Neither was run for
this report.
