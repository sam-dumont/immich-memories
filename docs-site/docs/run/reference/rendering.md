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
  whole process budget after source preparation finishes. `preflight` shows the assembly choice on its Memory line. 1080p output keeps the default.
  Below 3 GB there is no room for a 4K software HEVC film at all, so when the film's resolution
  is `auto` and the box has no hardware HEVC encoder, a 4K film renders at 1080p instead, in the
  same orientation. `preflight` and the run log say so. A resolution you set yourself, in the
  config or with `--resolution`, is kept: a 4K set that way below 3 GB gets a warning that the
  render may run out of memory, and the fix is `auto` or `1080p`.

## Quality: one dial, calibrated per encoder

`output.quality` (or an explicit `output.crf`) is on libx265's CRF scale, the reference because
libx265 runs everywhere. Every other encoder is calibrated to the same picture, by SSIM on real
1080p60 footage, in constant-quality modes, never bitrate targets.

`high` uses more bits; `balanced` is the default. `fast` keeps the balanced quality target
and changes the speed preset. Output size depends on the pictures, motion and encoder.

| | `high` | `balanced` |
|---|---|---|
| `libx265` (reference) | CRF 18 | CRF 24 |
| `libx264` | CRF 18 | CRF 22 |
| `h264_vaapi` and `h264_qsv` | QP 20 | QP 22 |
| `h264_nvenc` | QP 20 | QP 24 |
| `hevc_videotoolbox` | `-q:v` 65 | `-q:v` 55 |

Hardware encoding reduces CPU work, but does not promise the same file size as software.
The current mapping is in `src/immich_memories/processing/rate_control.py`. If the film bands
on your footage, try `quality: high`.

## Title kernels

The animated title renderer (bokeh, gradients, SDF text) runs through
[Quadrants](https://github.com/Genesis-Embodied-AI/quadrants), which installs with the app. One log
line says what is drawing:

```text
Title kernels: quadrants 1.3.0 on the Metal backend
```

Metal on Apple Silicon, CUDA on NVIDIA and Vulkan where supported render animated effects.
Each GPU backend is tested in a child process first; a failed backend is skipped and named in the
log. Kernels are cached in `~/.immich-memories/cache/kernels`.

CPU rendering draws the text once with Pillow, then FFmpeg slides, scales and fades it over a
still background. This also covers
`IMMICH_FORCE_CPU=1`, a CPU-only kernel backend, a missing compatible Quadrants wheel or a CPU
without AVX. It keeps text and timing without animated kernel effects. Preflight reports the
renderer selected on your machine.
