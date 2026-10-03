# Rendering performance closeout, 2 October 2026

Final report for [#1704](https://github.com/sam-dumont/immich-memories/issues/1704)
and [#1702](https://github.com/sam-dumont/immich-memories/issues/1702).
Both issues are closed. The final fixes, #1757, #1773 and #1770, are merged.
The [GitHub checkpoint](https://github.com/sam-dumont/immich-memories/issues/1704#issuecomment-5947887079)
records the same results. Earlier component profiling remains in
[the 1 October report](2026-10-01-hdr-assembly-profile.md).

## Combined rendering results

The final fixture produces portrait 2160×3840, 60 fps, 10-bit PQ/BT.2020 video with
48 kHz stereo audio. It includes a GPU title, a cold synthetic HTTP map, SDR/HLG
clips, captions, crossfades, audio mixing and final muxing. The short film is
14.5 seconds / 870 frames; the longer film is 68.5 seconds / 4,110 frames and 42 clips.

| Host | Film | Baseline wall time | Updated wall time | Less time |
|---|---:|---:|---:|---:|
| M2 | 14.5 s | 154.586 s | 75.161 s | 51.4% |
| M2 | 68.5 s | 592.862 s | 166.401 s | 71.9% |
| M5 | 14.5 s | 81.945 s | 48.959 s | 40.3% |
| M5 | 68.5 s | 263.153 s | 99.025 s | 62.4% |
| GTX 1070 | 14.5 s | 433.353 s | 197.616 s | 54.4% |
| T1000 | 14.5 s | 441.749 s | 217.124 s | 50.8% |
| GTX 1070 | 68.5 s | Not qualified | 467.663 s | Not claimed |
| T1000 | 68.5 s | Not qualified | 574.702 s | Not claimed |

Each final Mac candidate ran once per length. Its unchanged earlier baseline is
the median of two short runs and one long run. Linux short results use one matched
pair per GPU under normal shared-cluster conditions, with CPU/I/O load recorded.
These small samples are evidence for this fixture, not a general throughput ranking.

The long Linux baselines finished assembly but exceeded the harness's 30-minute
limit during redundant full-decode verification. They have no qualified timing.
The final long candidates use container frame-count metadata followed by one full
error-checked video decode and an audio decode. Those runs establish functional
completion and candidate wall time, not a matched long-film speedup.

The timer includes GPU initialization, title rendering, the cold map, assembly,
audio and mux. It excludes prepared input construction, media acquisition,
selection, generated music and output verification. The baseline already includes
the earlier title/cadence fixes. Do not add the component gains below to these gains.
The original 605.35-second, 159-source production film was not rerun; its earlier
1,069.19-second assembly and 2,380.29-second whole-run times remain historical controls.

## Source and hardware verification

Control source: `207f613d4bb6b93fda98c34d1014d79d27dfd56f`. The candidate combined
isolated source from `8498ff1dd`, HLG `fad337568`, SDR qualification `28c63e21c`,
final-frame correction `0b23deb98` and the final HEVC VideoToolbox admission policy.
It did not import the original dirty checkout. Candidate manifest SHA-256:
`ff994b52aac41be2fd12800e33c4cef145552ef69f7252c89b25b457af546a13`.

The decoder, assembler and memory-policy files in merged #1770 (`d3769646a`) match
the hardware-tested files. HLG/SDR qualification shipped in #1757 (`ca8f20e0e`);
#1773 (`517d44028`) fixes the equal-rate final frame. Hosted CI passed, including
Linux FFmpeg integration coverage, after the final main-branch conflicts were resolved.

Macs used Metal and HEVC VideoToolbox quality 65 with software fallback disabled.
Linux used CUDA and HEVC NVENC p7, constant QP 20 and spatial AQ, under 3-CPU/4-GiB
job limits. Hardware encoding was verified; software fallback is not counted as a
GPU result. Private footage was not transferred to the cluster.

The synthetic map uses a six-second Paris-to-Lisbon route and a deterministic
noise tile: 7,719 requests / 388,010,973 bytes, tile SHA-256
`05320285ef65764abf45ce8f15f0120f7ea59b09d3363aafa2a472376e1a9c5d`.
This measures the renderer and a controlled cold HTTP source. It does not measure
public tile-provider latency, production cache hit rates or a full trip library.

## Correctness and memory

Every completed final film passed full video/audio decoding, expected frame count,
duration, frame rate, dimensions and HDR/audio metadata checks. Both Mac candidates'
decoded audio matched their baselines, and sampled title/map/video output passed
visual review. Pixel identity was not a release requirement. The Linux sampled
map frame contains the fixture's synthetic noise tile; it is not a real-map quality test.
All owned Kubernetes benchmark jobs were removed after collecting results.

| Candidate | Short Python peak RSS | Long Python peak RSS |
|---|---:|---:|
| M2 | 1.964 GB | 1.978 GB |
| M5 | 2.399 GB | 2.397 GB |
| GTX 1070 | Not summarized here | 2.104 GB |
| T1000 | Not summarized here | 2.040 GB |

These are Python process peaks in decimal GB, not summed process-tree or cgroup
peaks. The Linux long films completed within their actual 4-GiB job limits.
That does not establish the same memory requirement for every source mix.

## What shipped and why

These are separate component comparisons with their own fixtures. Their percentages
are not additive, and they are not interchangeable with the combined table above.

| Change | Merged PR | Evidence |
|---|---|---|
| GPU titles | #1721 | Opening title: M2 48.75 → 8.81 s; M5 17.97 → 3.81 s. One qualified T1000 pair: 141.41 → 24.24 s |
| Convert before duplicating lower-rate frames | #1739 | M2 73.378 → 50.576 s; M5 31.797 → 22.329 s; one T1000 pair 224.324 → 143.782 s |
| Blur and SDR transfer | #1743, #1746 | Combined Linux fixture: GTX 1070 160.412 → 42.263 s; T1000 176.051 → 68.570 s |
| Reuse source probes | #1745 | Removed 40 extra ffprobe processes in a 20-clip diagnostic; no isolated wall-time claim |
| Borrow decoder buffers | #1755 | About 7% lower Python peak RSS on Macs; Linux about 322–347 → 297–298 MB, with neutral timing |
| HLG transfer | #1757 | M2 30.202 → 22.690 s; M5 13.152 → 10.892 s; GTX 1070 42.903 → 32.139 s; T1000 71.480 → 56.172 s |
| Full-map resizing | #1761 | M2 33.114 → 20.546 s; M5 19.588 → 11.884 s; GTX 1070 67.450 → 51.168 s; T1000 51.793 → 43.725 s |
| Cache visibility | #1766 | Makes reuse visible; no separate speedup claimed |
| Bounded decoder read-ahead | #1770 | M2 21.386 → 19.533 s; M5 10.488 → 8.184 s, with about 49 MB more Python memory |
| Equal-rate final frame | #1773 | FFmpeg 6 retains the distinct final frame; correctness fix, not a speedup claim |

Read-ahead defaults to `hevc_videotoolbox`, HD-or-larger output, at least two
effective CPUs and a known memory budget of at least 4 GiB. Matched T1000 runs
slowed from 35.220 to 41.487 seconds at three CPUs and 31.816 to 40.354 seconds at
four CPUs. GTX 1070 was roughly neutral. Linux and software encoders therefore
remain synchronous. More prefetch is not automatically faster.

## Scope at closeout

The assembly and map investigations (#1704/#1702) are complete within the agreed
scope. The NAS map treatment also shipped in #1703. #1753, #1744, #1771, #1759,
#1760 and #1772 are closed after their fixes merged; #1774 was superseded by #1757.
Hardware-decode exploration #1747 is closed as not planned after its M2 result was
slightly slower and used more memory; the wider sweep is deferred.

[NAS software-HLG memory pressure #1767](https://github.com/sam-dumont/immich-memories/issues/1767)
remains separate. The final checks do not close that issue. Native/Cython exploration,
broader provider/cache sweeps and the larger scenario campaign are also outside this
closeout. This report does not claim that every possible optimization is exhausted.
