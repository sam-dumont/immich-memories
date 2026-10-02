# HDR assembly: convert once, then duplicate

Investigation for [#1704](https://github.com/sam-dumont/immich-video-memory-generator/issues/1704).
Historical component report. The investigation continued after these measurements;
#1704 is now closed. See the [2 October closeout](2026-10-02-render-performance-closeout.md)
for the merged changes, final M2/M5/GTX 1070/T1000 results and remaining limitations.
Statements below about the decoder or pending work describe the source tested here.

Baseline source: `bafeae8677f78b8e57f4175b82bd08566bcfe23e`.
Local measurements: Apple M5 Max, Python 3.12.11, FFmpeg 8.1 with libzimg and NEON.
Private media, filenames, IDs, captions and command traces stay outside the repository.

## Where the accepted run spent its time

The accepted 605.35-second 4K portrait film spent 1,069.19 seconds in assembly.
Retained phase logs split that into:

| Component | Seconds |
|---|---:|
| Streaming video | 933.541 |
| Assembly audio mixing | 33.226 |
| Final mux | 1.884 |
| Remaining setup/title work | About 100.54 |

VideoToolbox was requested with software fallback allowed. These logs do not prove
physical hardware encoder use. A separate tiny local probe succeeded with software
fallback disabled; that does not retrospectively establish what the accepted run used.

## Decoder attribution

39 captured decoder inputs still existed locally. We replayed three representative
graphs for two seconds each, retaining source seek, scaling, fill, colour conversion
and captions. Raw output went to a discard sink, with one warm-up and three repeats.
These are component measurements, with no compressed encoder or Python frame pipe.
Small concurrent static checks may contribute noise; caption removal showed no reliable gain.

| Source/graph | Full graph | Without transfer conversion | Black fill instead of blur |
|---|---:|---:|---:|
| 1080p HLG, blur fill | 4.157 s | 1.316 s | 3.332 s |
| 4K HLG, fills canvas | 4.255 s | 2.132 s | — |
| 1080p SDR, high cadence, blur fill | 15.783 s | 12.264 s | 3.445 s |

Removing conversion or changing fill was diagnostic only. Neither is a proposed
rendering change. The HDR conversion is necessary for correct colour.

Adding the normal Python read pipe to these full graphs took 4.463, 4.649 and
17.562 seconds respectively. Almost all of each interval was inside the blocking
read boundary: these sources were upstream-limited without an encoder attached.
A separate homogeneous 4K/PQ streaming profile measured 1.545 seconds at the
read boundary, 0.825 at the encoder write boundary and 0.051 in crossfade blending
over 2.652 seconds. A write wait combines pipe transfer and downstream work; it is
not a hardware utilization measurement.

## Duplicate after conversion

The decoder currently applies `fps=60` before HDR conversion. A 30 fps source
therefore converts each frame twice. Conversion is frame-local, so converting the
original frames and duplicating the result avoids that repeated work. Scaling stays
before conversion, and captions stay after the final FPS/timebase reset.

Two-second retained-source comparisons used a real 0.5-second input seek and one
warm-up plus three alternating paired repeats:

| Graph | Original median | Duplication after conversion | Frame/timecode parity |
|---|---:|---:|---|
| 1080p HLG, blur fill | 4.673 s | 2.944 s | Exact, 120 video frames |
| 4K HLG, canvas fill, captured caption | 4.242 s | 2.859 s | Exact, 120 video frames |

The blur graph's child peak rose from about 615 MB to 665 MB; the canvas graph
stayed around 655 MB. Later duplication can require another buffered frame. That
extra memory matters on small containers and needs an end-to-end measurement.

The patch uses matching, positive average and nominal stream rates below the
target FPS, and requires a transfer conversion into 10-bit HDR output.
HDR-to-SDR/RGB24 graphs keep their existing order. Matching metadata is a guard, not
absolute proof of CFR. Disagreeing or unknown rates, equal/higher rates and privacy
effects keep the original filter order. The FPS value and sampling policy never change.
The same source probe supplies geometry and cadence; no extra probe process is added.

Of the 39 retained inputs, 14 satisfy this lower-rate guard: 12 HLG sources at
30 fps and two SDR sources at 24 fps. The profiled 4K canvas source has disagreeing
average/nominal rates, so its table result demonstrates the reordered component;
the conservative patch retains its original order.

An additional captured-caption blur check preserved all 120 frame hashes and
timecodes. Small real-FFmpeg regression cases cover HLG and SDR conversion,
30 and 30000/1001 fps, seek, captions, and both black/blur fill.

## Complete bounded assemblies

The actual guarded patch was compared with the baseline using a retained eligible
30 fps HLG source, a 0.5-second seek and two-second clips. Both sides used 2160×3840,
60 fps, HEVC/VideoToolbox quality 55, 10-bit PQ/BT.2020, captions, 0.5-second
crossfades, original audio, audio normalization and final muxing. One warm-up
preceded three alternating paired repetitions. Python and FFmpeg were unprofiled.

| Constructed film | Baseline median | Candidate median | Reduction |
|---|---:|---:|---:|
| Two clips, 3.5 s | 12.145 s | 8.002 s | 34.1% |
| Six clips, 9.5 s | 38.970 s | 26.338 s | 32.4% |

Raw wall times, in seconds:

- Short baseline: 11.850535, 12.144786, 12.220784; candidate:
  7.877580, 8.002229, 8.127427.
- Longer baseline: 38.092386, 38.970119, 44.139369; candidate:
  24.071005, 26.337768, 27.634481.

Both final films passed complete audio/video decoding. Decoded sample hashes and
timestamps matched the baseline exactly, including audio. The films contain 210
and 570 video frames, with the same duration and HDR metadata on both sides.
These constructed films deliberately exercise eligible inputs. They do not predict
the gain on the accepted 605-second film or a different source mix.

Separate fresh-process memory measurements on the short film sampled the complete
process tree every 150 ms and recorded Python/child RSS high-water marks:

| Memory measure | Baseline | Candidate |
|---|---:|---:|
| Python high-water RSS | 373.19 MB | 323.39 MB |
| Largest child high-water RSS | 888.13 MB | 941.24 MB |
| Sampled whole-tree peak RSS | 2.342 GB | 2.419 GB |

The combined patch reduced Python memory but increased sampled aggregate peak by
77.38 MB, about 3.3%. Sampling may miss a brief peak. There is no demonstrated
aggregate-memory reduction. These Mac RSS measurements do not establish container
safety; the separate cgroup controls below address that question.

## Remove the redundant HDR copy

The HDR decoder also copied every bytes-backed frame into another array. Body
writes, previews and crossfades only read those samples, and the array retains its
original bytes. Keeping the view removes a 24.88 MB copy per 4K HDR frame.

One warm-up plus three alternating repetitions of homogeneous 4K60/PQ assembly,
using two identical prepared clips and a 0.5-second crossfade, produced:

| Film length | Original wall median | Without copy | Original Python CPU | Without copy |
|---|---:|---:|---:|---:|
| 3.5 s | 2.571 s | 2.529 s | 1.181 s | 1.009 s |
| 11.5 s | 6.850 s | 6.767 s | 3.501 s | 3.002 s |

The wall differences are 1.2–1.65%, with overlapping ranges in the longer case.
That is noisy, not a substantial assembly speedup. Python CPU fell about 14–15%.
Separate profiled processes peaked at 367.02 MB versus 317.37 MB for Python.
Read-only ownership and crossfade regression coverage checks that held source
samples survive decoder advances and reuse of the blend destination.

These bounded results do not establish a speedup for the accepted long film or
resolve #1704. The mixed-source and container checks below complete the bounded
correctness/resource review; a matched whole-film performance checkpoint remains
separate.

## Mixed sources and actual container limits

A retained four-source fixture exercises HLG and SDR, canvas and blur fills,
known lower cadence, unknown cadence, and downsampling. Each clip uses a real
0.5-second seek and contributes two seconds, with three 0.5-second crossfades and
date captions: a 6.5-second 2160×3840, 60 fps, 10-bit PQ/BT.2020 film.

The Linux software check used an existing ARM64 runtime, read-only sources,
network disabled, zero swap, true two-core affinity, and libx265 medium/CRF 20
with fixed two-thread pools. The only missing dependency, Babel 2.18.0, was
installed from its lockfile-verified wheel inside disposable containers.

Both the unchanged baseline and candidate hit the real 4 GiB limit during the
first crossfade. The original quota-only attempt also failed; fixing CPU affinity
did not make this worst-case software profile fit. These are failures, not a
4 GiB admission pass. The NAS uses 1080p SDR/VAAPI, outside the HDR deferral path;
its original HDR-to-SDR conversion order remains covered by a regression.

At an 8 GiB limit, the first pair completed and all 390 decoded video frames,
their timestamps, and HDR metadata matched exactly. Audio exposed an existing
shutdown race: the baseline became silent over the final 0.4 seconds while the
candidate retained signal. Decoded audio was identical until 5.833333 seconds;
the difference was missing sound, not lossy AAC variation.

The assembler consumed its required video frames and closed the decoder generator
while that same FFmpeg process could still be writing the clip WAV. The fix gives
FFmpeg the exact video-frame and audio-duration bounds already used by assembly,
then waits for those bounded outputs before yielding the final requested frame.
An earlier cancellation still terminates and reaps the owned child. The fix does
not drain the rest of an original or add another audio pass.

A real delayed-child regression failed before this fix and passes after it.
Real FFmpeg tests compare seeked PCM against an independent reference at fast and
slow consumer rates: exactly 24,000 stereo sample frames in both cases.

The final pair applies the same completion fix to the old baseline and candidate,
retaining the baseline's original FPS order and HDR copies. Both finish under
the real 8 GiB cgroup limit with zero swap and zero OOM events:

| Cgroup peak, complete process group | Corrected baseline | Candidate |
|---|---:|---:|
| Peak memory | 5,280,546,816 bytes | 5,177,516,032 bytes |

All 390 decoded video frames and 305 decoded audio blocks match exactly, including
timestamps, sample sizes, duration, dimensions, and PQ/BT.2020 metadata. This is
Linux software parity/resource evidence, not a VideoToolbox or NAS speed claim.
Concurrent correctness work makes these runs unsuitable for latency claims.
