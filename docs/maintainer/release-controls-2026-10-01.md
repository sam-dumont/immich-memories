# Release controls recorded on 1–2 October 2026

Repository-only validation record. These measurements belong to their recorded revisions, not to later changes. The public [measurement guide](../../docs-site/docs/better/measured.md) keeps the practical conclusions. The [release-film driver](setup-matrix.md) documents the maintainer workflow.

## Whole-film controls, 1–2 October 2026 {#whole-film-controls}

All fifteen release controls are accepted with the qualifications below and have verified latest
uploads to Immich. Film, audio, source-scope and cache checks passed. The CUDA trip required a
separate native-audio recovery; the CUDA person film used its native full mix, with stem separation
verified afterward without changing the film. Failed attempts do not count as completed films.

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
| Linux CUDA worker / GPU | Person | 2h 57m 14s original; 74.9 s stem recovery | 604.733 | 2160×3840, 60 fps, HDR10 | `4913c3892695` |
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

### Failed CUDA person attempt and scratch correction

The preceding CUDA person attempt was last observed preparing source 129 of 159 before eviction.
Kubernetes evicted the pod because its disk-backed `/tmp` `emptyDir` exceeded the 1 GiB limit.
Exit 137 was a disk-scratch eviction, not an out-of-memory result; it receives no control credit.

The deployment correction raises that disk-backed scratch limit to 8 GiB. The application source
remains `4913c3892695`, the container RAM limit remains 8 GiB, and the model volume stays
persistent. Output retains its separate 20 GiB temporary volume. The subsequent person film
completed with 159 selected sources and 160 retained original IDs, with no unexpected retained originals;
the failed attempt is retained separately.

The person controller took 10,633.5 s. Its worker job took 9425.4 s on 4 CPU cores, an 8 GiB RAM
limit and a T1000 with 8 GB VRAM. The 604.733 s film has 36,284 frames, HEVC 10-bit PQ/BT.2020 at
60 fps, and passed complete video/audio decoding and sampled visual review. Cache transfer took
814.2 s separately; final QA and publication are also outside the controller time.

The original film used the native full-mix fallback after the stem request exceeded the service's
64 MiB upload cap. It was not a stem-integrated mix. A separate recovery passed the same 820.06 s,
157,451,598-byte mastered soundtrack through the corrected production HTTP service and client,
with both transport caps set to 256 MiB. The two corrected modules were isolated in the same GPU
container; their source matches commit `620e232912f0`. It produced four finite full-length stems in
71.7 s, or 74.9 s including waveform verification. The film and master stayed unchanged: no audio
generation, remix or video rerender was repeated. The recovered stems were not used in the original
film. These intervals do not describe a clean uninterrupted film with stem separation.

### Where the time went

| Hardware and tier | Film | Source preparation, s | Assembly, s | Music, s |
|---|---|---:|---:|---:|
| NAS / NAS | Month | 187.7 | 180.6 | 15.7 |
| NAS / NAS | Person | 1857.1 | 2135.0 | 163.2 |
| NAS / NAS | Trip | 516.6 | 286.3 | 42.9 |
| Linux CUDA worker / GPU | Month | Unknown | Unknown | Unknown |
| Linux CUDA worker / GPU | Person | Included in remote assembly | 9427.5, remote scope | 597.3, original full-mix route |
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
also separate from assembly-only timing. The CUDA person's remote assembly includes source
preparation, titles, rendering and the worker check; it is not an encoder-only interval. Its music
phase ends at 00:01:22 UTC, before metadata completion at 00:09:22 UTC. That later overhead is
unattributed, not an exact mixing duration. Stem-only recovery is recorded separately above.
Missing records stay unknown.

Assembly remains a large cost. The M5 Full person film spent another 670.3 s in selection and
analysis. The M2 Full trip spent 911 s rendering nine maps, about 43% of its whole run. The NAS
trip's nine maps took 39 s with lower resolution and reduced motion. Full and GPU retain smooth
animation; these are different profiles.

The route zoom and arrow correction in [#1700](https://github.com/sam-dumont/immich-memories/pull/1700)
applies to ordinary maps too. The three-view shortcut in
[#1703](https://github.com/sam-dumont/immich-memories/pull/1703) applies only when
`animated_background` is false. Selection-index reuse in
[#1706](https://github.com/sam-dumont/immich-memories/pull/1706) and the lower-cadence HDR
conversion/audio-completion fix in
[#1709](https://github.com/sam-dumont/immich-memories/pull/1709) landed after the listed
Mac and NAS controls. The CUDA worker is frozen at `4913c3892695`, before #1709. No whole-film
speedup is claimed for those patches.

### Native audio and encoding

NAS uses bundled music and hardware H.264 at 1080p, with Marqo and Docling off. Its trip opened
VAAPI for 54 compressed encodes. Mac and CUDA controls use native ACE-Step audio. Demucs
separation passed in the recorded runs or qualified recoveries; the CUDA person film used its
native full mix before the separate stem recovery. A synthetic audio probe alone does not prove
that a person film's full workload fits.

The Mac month controls generated one 88 s take each; the CUDA month generated three 88 s takes.
Accepted Mac trip controls generated two 120 s takes each. The recovered CUDA trip also used
two finite 120 s native takes and four finite winning Demucs stems, with no bundled substitution.
M2 GPU and M5 Full person generated
all three requested 120 s takes. These controls produced four finite Demucs stems. The CUDA person
also generated three finite 120 s takes on its first candidate, then obtained four finite 820.06 s
stems in the separate transport recovery described above. Its original film used no bundled music.
The CUDA person assembly records `hevc_nvenc`, preset `p4`, constant QP 24.

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
can still dominate a GPU worker. See [hardware encoding](../../docs-site/docs/run/hardware.md).

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
| Linux CUDA worker / GPU | Person | 7.646 GB cumulative whole-pod cgroup high-water; external ACE separate |
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

The person pod's cumulative high-water was 7,646,384,128 bytes (7.121 GiB), including controller and
worker processes but excluding the external ACE service. It remained unchanged through stem
recovery. Swap and all memory-event counters were zero. This is a whole-pod cumulative counter,
not a separately reset per-stage peak; it does not establish a CPU or memory bottleneck.

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
[#1702](https://github.com/sam-dumont/immich-memories/issues/1702#issuecomment-5937777886)
records a blank map feature layer of 126.6–506.3 MiB per moving frame, repeated tile decoding and
CPU frame construction before NVENC. Those are buffer sizes and observed stages, not a measured
speedup. The map fixes in
[#1729](https://github.com/sam-dumont/immich-memories/pull/1729) and
[#1741](https://github.com/sam-dumont/immich-memories/pull/1741) landed after these
frozen controls. Their timings do not measure those changes, and no whole-film speedup is claimed.
#1702 retains profiling and further optimization as follow-up work.

[#1704](https://github.com/sam-dumont/immich-memories/issues/1704#issuecomment-5938126498)
recorded CPU interpolation for HDR titles, blank-text compositing on textless endings and white-fade
arithmetic after GPU readback. [#1721](https://github.com/sam-dumont/immich-memories/pull/1721)
merged the title implementation after these frozen controls. The accepted timings do not measure
that change, and no whole-film speedup is claimed for it.

The accepted controls stay evidence for their original revisions. The
[hosted-provider benchmark (#1718)](https://github.com/sam-dumont/immich-memories/issues/1718)
and [28-by-2 shared-Mac-cache comparison (#1719)](https://github.com/sam-dumont/immich-memories/issues/1719)
are separate follow-up work. Neither was executed for this closeout.
