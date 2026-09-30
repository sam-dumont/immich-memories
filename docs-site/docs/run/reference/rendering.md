---
title: Render memory and encoder calibration
---

# Render memory and encoder calibration

For diagnosing memory limits or comparing encoders. To enable a GPU, use
[Hardware encoding](../hardware.md).

## Memory budget

Less memory means fewer photos rendered at once. The app reserves 1 GiB for the parent
  process, then allows 3 GiB per preparation worker, with at least one and at most two workers.
  It uses the container memory limit when set, otherwise the machine's RAM. A 4 GiB container
  prepares one source at a time; an 8 GiB container can prepare two.
  `immich-memories preflight` prints what it picked, for example
  `Photo preparation: 1 at a time (2.0 GB available, container limit)`. Setting
  `advanced.analysis.source_prepare_workers` to a number (1 to 4) overrides it.
  The same memory figure caps the threads of each clip decode in the render (one per 2 GB, up
  to 4): FFmpeg's own default of one per core cost 1.2 GB per 4K decode on an 18-core Mac.
  A box with no hardware HEVC encoder encodes in libx265, which holds about 52 MB per frame it
  looks ahead at 4K. Source encoders share the memory left after the parent reserve; each
  encoder uses its own share to size its lookahead. Above 1080p, a share below 4 GiB allows
  5 frames, 4 to less than 6 GiB allows 10, and larger shares keep the x265 default. A bounded
  encoder processes one frame at a time, matching the memory measurements. Assembly uses the
  whole process budget after source preparation finishes. The files come out a few
  percent smaller at a slightly lower quality: at 1080p with a lookahead of 10, 3% smaller and
  0.03 dB lower. `preflight` shows the assembly choice on its Memory line. 1080p output keeps the
  default everywhere.
  Below 3 GB there is no room for a 4K software HEVC film at all, so when the film's resolution
  is `auto` and the box has no hardware HEVC encoder, a 4K film renders at 1080p instead, in the
  same orientation. `preflight` and the run log say so. A resolution you set yourself, in the
  config or with `--resolution`, is kept: a 4K set that way below 3 GB gets a warning that the
  render may run out of memory, and the fix is `auto` or `1080p`.

## Quality: one dial, calibrated per encoder

`output.quality` (or an explicit `output.crf`) is on libx265's CRF scale, the reference because
libx265 runs everywhere. Every other encoder is calibrated to the same picture, by SSIM on real
1080p60 footage, in constant-quality modes, never bitrate targets.

| `quality` | reference CRF | SSIM | software bitrate | per minute |
|---|---|---|---|---|
| `high` | 18 | 0.99169 | 4.6 Mbps | about 35 MB |
| `balanced` (default) | 24 | 0.98451 | 1.6 Mbps | about 12 MB |
| `fast` | 24 | 0.98451 | 1.6 Mbps | about 12 MB, encoded as fast as the backend can |

There is no tier below `balanced`: the next step down bands on sky and skin. `fast` keeps the
balanced picture and buys speed from the encoder preset.

| | `high` | `balanced` |
|---|---|---|
| `libx265` (reference) | CRF 18 | CRF 24 |
| `libx264` | CRF 18 | CRF 22 |
| `h264_vaapi` and `h264_qsv` | QP 20 | QP 22 |
| `h264_nvenc` | QP 20 | QP 24 |
| `hevc_videotoolbox` | `-q:v` 65 | `-q:v` 55 |

Hardware buys speed, not quality per byte. Bits for the same picture:

| Backend | Bits for the same picture |
|---|---|
| NVENC (T1000, Turing) | 1.2x libx264 |
| VAAPI (J4125, Gemini Lake) | 2.2x libx264 |
| VideoToolbox (Apple Silicon) | 2.9x libx265 |

QSV carries VAAPI's anchors (same iHD driver, same silicon); nobody here has measured an AMD card.
The clip, hardware and method behind each anchor are in
`src/immich_memories/processing/rate_control.py`. If a backend bands on your footage, set
`quality: high` and open an issue.

## Title kernels

The animated title renderer (bokeh, gradients, SDF text) runs through
[Quadrants](https://github.com/Genesis-Embodied-AI/quadrants), which installs with the app. One log
line says what is drawing:

```text
Title kernels: quadrants 1.3.0 on the Metal backend
```

Metal on Apple Silicon, CUDA on NVIDIA, Vulkan on an integrated GPU, CPU everywhere else. Each GPU
backend is tried in a throwaway child process first; one that fails is skipped and named in the
log once. Kernels are cached in `~/.immich-memories/cache/kernels`. `IMMICH_FORCE_CPU=1` keeps the
kernel renderer but runs it on the processor.

Quadrants publishes wheels for Python 3.10 to 3.13 on Linux (x86_64, aarch64), macOS arm64 and
Windows, and none for Intel macOS or Python 3.14. This app needs 3.11 or later, so the kernels need
**3.11 to 3.13**. Everywhere else titles draw through PIL: same text and timing, no kernel effects.
`immich-memories preflight` says which renderer a machine will use.

### CPUs without AVX

The CPU kernel backend needs AVX. Celeron J-series (the J4125 in a Synology DS423+) and older Atoms
don't have it, and the kernel library dies with SIGILL as it loads. The app loads it in a child
process first, so such a box renders titles through PIL and says so up front:

```text
Title rendering       WARNING   kernel backend crashed on this CPU: illegal
                                instruction; titles fall back to the PIL renderer
```

On that box PIL is also the faster renderer, so nothing is lost but the effects.
