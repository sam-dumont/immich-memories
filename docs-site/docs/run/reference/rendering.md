---
title: Render memory and encoder calibration
---

# Render memory and encoder calibration

How the render sizes itself to the memory it has, and how one quality setting maps onto each
encoder. To turn on a GPU, see [Hardware encoding](../hardware.md).

## Memory budget

Less memory means fewer photos prepared at once. The app reads the container memory limit when
there is one, otherwise the machine's RAM, reserves 1 GiB for the parent process and allows
3 GiB per preparation worker, with one or two workers. A 4 GiB container prepares one source at a
time; an 8 GiB container prepares two. `immich-memories preflight` prints what it picked, for
example `Photo preparation: 1 at a time (2.0 GB available, container limit)`. Set
`advanced.analysis.source_prepare_workers` to a number from 1 to 4 to override it.

The same figure caps the threads of each clip decode in the render: one per 2 GB, at most 4 and
never more than the CPUs. FFmpeg's own default of one thread per core cost 1.2 GB per 4K decode
on an 18-core Mac.

A box with no hardware HEVC encoder encodes in libx265, which holds about 52 MB per lookahead
frame at 4K. Source encoders share the memory left after the parent reserve, and each sizes its
lookahead from its share. Above 1080p, a share under 4 GiB allows 5 frames, 4 to 6 GiB allows
10, and anything larger keeps the x265 default. 1080p output always keeps the default. Assembly
gets the whole budget once source preparation is done; `preflight` shows its choice on the
Memory line.

Below 3 GB there is no room for a 4K software HEVC film at all. When the film's resolution is
`auto` and the box has no hardware HEVC encoder, a 4K film renders at 1080p instead, in the same
orientation, and `preflight` and the run log say so. A resolution you set yourself, in the config
or with `--resolution`, is kept: a 4K film set that way below 3 GB gets a warning that the render
may run out of memory. The fix is `auto` or `1080p`.

## Quality: one dial, calibrated per encoder

`output.quality` (or an explicit `output.crf`) is on libx265's CRF scale, the reference because
libx265 runs everywhere. Every other encoder is calibrated to the same picture, by SSIM on real
1080p60 footage, in constant-quality modes, never bitrate targets. Where an encoder blocks or
bands at a setting SSIM accepts, the eye wins: `hevc_nvenc` balanced is QP 20 for that reason.

`high` uses more bits; `balanced` is the default. `fast` keeps the balanced quality target
and changes the speed preset. Output size depends on the pictures, motion and encoder.

| | `high` | `balanced` |
|---|---|---|
| `libx265` (reference) | CRF 18 | CRF 24 |
| `libx264` | CRF 18 | CRF 22 |
| `h264_vaapi` and `h264_qsv` | QP 20 | QP 22 |
| `h264_nvenc` | QP 20 | QP 24 |
| `hevc_nvenc` | QP 18 | QP 20 |
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

Metal on Apple Silicon, CUDA on NVIDIA and Vulkan where supported draw the animated effects. The same
kernels also run the photo moves (the per-frame warp, fill and composite) on any of those GPU
backends.
Each GPU backend is tested in a child process first; a failed backend is skipped and named in the
log. Kernels are cached in `~/.immich-memories/cache/kernels`.

Without a GPU backend (`IMMICH_FORCE_CPU=1`, a CPU-only kernel backend, no compatible Quadrants
wheel, or a CPU without AVX), titles are drawn once with Pillow and FFmpeg slides, scales and fades
them over a still background: same text and timing, no animated effects. Photo moves fall back to
OpenCV on the CPU, frame for frame. Preflight names the renderer your machine picked.
