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

Twelve of the fifteen release controls have passed film, audio and cache checks at this snapshot; eleven have verified uploads. The completed M2 Full person film is awaiting upload. The other three controls remain pending. These are warm picture banks with fresh editorial decisions: compatible facts were reused, while original-media acquisition, titles, rendering and music still ran. They are measurements of the listed revisions and profiles, not timings for every later commit or equal-quality comparisons between tiers.

| Hardware and profile | Request | Whole run | Source revision |
|---|---|---:|---|
| NAS / rules / 1080p | Month | 7m 23s | `c4c7356304c5` |
| NAS / rules / 1080p | Person | 78m 51s | `dec8f20e609c` |
| NAS / rules / 1080p | Trip | 17m 33s | `dec8f20e609c` |
| Linux CUDA worker / rules / 4K HDR | Month | 24m 01s | `2a2cadccf7e4` |
| M2 16 GiB / Full / 4K | Month | 15m 29s | `f74936b657d7` |
| M2 16 GiB / Full / 4K | Person | 87m 23s | `4db52f365a5e` |
| M2 16 GiB / Full / 4K | Trip | 35m 05s | `03cc7f56c122` |
| M2 16 GiB / GPU rules / 4K | Month | 7m 18s | `f74936b657d7` |
| M2 16 GiB / GPU rules / 4K | Trip | 26m 00s | `f82de21b5bf5` |
| M5 / Full / 4K | Month | 5m 43s | `cb06e4ba0e0d` |
| M5 / Full / 4K | Person | 39m 40s | `f82de21b5bf5` |
| M5 / Full / 4K | Trip | 18m 42s | `f82de21b5bf5` |

Pending: the M2 GPU person control and the Linux CUDA worker person and trip retries. Earlier failed worker attempts do not count as completed films. The trip retry carries the date-transport fix; the person retry needs matching worker and client deadlines. Final film checks remain required. The latest Linux worker trip attempt on `e42aab375b9e` produced a 128.87 s film, then failed the client duration check after 26m 28s. It remains pending while that mismatch is investigated.

### Where the time went

| Measured control | Selected stage costs |
|---|---|
| M2 Full trip, `03cc7f56c122` | Nine maps: 911 s of 2,105 s total, about 43% |
| NAS trip, `dec8f20e609ce` | Nine maps: 39 s; clip preparation: 517 s; assembly: 286 s; music: 43 s |
| M2 Full person, `4db52f365a5e` | Clip preparation: 449 s; assembly: 2,353 s, about 45% of the run; music: 238 s |
| M5 Full person, `f82de21b5bf5` | Selection: 670 s; clip preparation: 302 s; assembly: 1,069 s; music: 103 s |
| M5 Full trip, `f82de21b5bf5` | Selection: 156 s; clip preparation: 46 s; assembly: 835 s; music: 42 s |

Stage records can overlap; do not add them into a new wall time. The NAS map profile uses lower resolution and reduced motion. Full and GPU retain smooth animation. The route zoom and arrow correction in [#1700](https://github.com/sam-dumont/immich-video-memory-generator/pull/1700) applies to ordinary maps too; the three-view shortcut in [#1703](https://github.com/sam-dumont/immich-video-memory-generator/pull/1703) applies only when `animated_background` is false. The 39 s and 911 s map costs describe different profiles.

Assembly is still expensive after selection. [#1706](https://github.com/sam-dumont/immich-video-memory-generator/pull/1706) merged reuse of selection indexes after these controls. [#1709](https://github.com/sam-dumont/immich-video-memory-generator/pull/1709), which converts lower-cadence HDR frames before duplication, is awaiting validation. Neither changes the measured times above.

### Audio and memory scopes

The NAS controls use bundled music and hardware H.264 at 1080p; the NAS trip opened VAAPI for 54 compressed encodes. NAS preparation leaves Marqo and Docling off. The Mac and CUDA controls run native ACE-Step with four Demucs stems. The Mac person and trip controls include 120 s takes; a synthetic audio probe does not prove that full workload fits.

The NAS month reached 1.71 GiB of container RAM; the NAS trip reached 2.22 GiB, within a 4 GiB limit. Sampled swap was about 11 MiB and 14 MiB respectively, with no memory-limit failures. The accepted CUDA month reached 5.14 GiB in the worker container. Its external audio service was a separate scope, reaching 9.42 GiB in current samples; its older 14.78 GiB historical peak was unchanged during this control. Do not sum peaks from different containers or times.

On the 16 GiB M2, accepted month and trip controls added about 0.97–1.41 GiB of whole-host swap above their starting values. Their owned process trees peaked around 11.0–12.2 GiB RSS. Whole-host swap, process RSS and physical footprint measure different things; swap may include other apps, and summed RSS can count shared pages more than once. These measurements do not establish a smaller physical-memory requirement.

The app now closes the selection-owned Laya model, clears unused local model buffers and releases its owned reader before titles and rendering. An actual M2 Full control observed MLX active memory fall from 842.6 MB to 22 bytes on close; immediately before rendering its cache was zero and its owned reader had exited. Its temporary selection swap surge ended at that boundary. That control completed in 87m 23s, with final host swap 145 MiB above its starting value. Its first of three requested music blocks was refused before generation by the resident-weight admission check; the other two generated 120 s native tracks and four local Demucs stems. The soundtrack repeats those two tracks, with no bundled substitution. The finished 605.35 s portrait film passed all 36,321 frames of video decoding, audio decoding to EOF, twelve visual samples and continuous-awake checks. Its parent physical footprint peaked at 10.92 GiB; that is separate from the owned process tree's 11.70 GiB RSS peak. Producer facts and derived banks were preserved; observed changes were metadata refreshes. This control is accepted with the missing third music block recorded. External model servers retain their own unload policy. Later music work can reopen an app-owned reader.

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

## Before the 56-film batch

The larger batch is held until the known performance fixes are finished and a representative cached
whole film has been measured before and after on the selected candidate. Keep the request, prepared
banks, hardware and output profile matched; record both revisions and any audio or fallback differences.
Review the actual whole-run and per-stage gains, including the maps and assembly that remain expensive,
and present those results before starting any of the 56 films.

The twelve accepted controls above remain evidence for their original revisions. A newer commit does
not require repeating all fifteen controls just to replace their timings. Three controls still need their
finished-film checks. Provider benchmarks stay after completion of the fifteen-control matrix.
