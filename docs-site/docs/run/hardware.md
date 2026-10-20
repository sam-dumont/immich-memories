---
title: Hardware encoding
---

# Hardware encoding

Hardware encoding makes the final video faster. It does not select pictures or change the
preparation tier. Picture analysis can use a [separate inference service](../better/inference.md), local CUDA ONNX
or a Mac's MLX/Metal runtime.
Software encoding works when no usable encoder is found.

## Verify it

Start here:

```bash
immich-memories hardware
```

Docker:

```bash
docker compose exec immich-memories immich-memories hardware
```

The app tests a one-frame encode, not just whether FFmpeg lists the codec. During a render, the
log names the encoder used. Prepared facts do not need rebuilding after an encoder change.

With `advanced.hardware.gpu_decode` on (the default), the render also decodes H.264 and HEVC
clips on the hardware. On an NVIDIA card (CUDA) or a Mac (VideoToolbox), the clip then stays on
the GPU while it is scaled to the film's size, turned upright and given its blurred background,
and reaches the CPU once, at film size. HDR frames go to the hardware encoder as P010, the
format it reads, so nothing repacks them on the way. On a 4K test cut on an NVIDIA T1000 worker,
the render's CPU time dropped from 241 s to 72 s.

The picture stays within a few 10-bit code values of the CPU path. A clip the hardware fails to
decode is decoded again in software, and an FFmpeg without the GPU filters (checked once per run)
keeps the CPU path.

Tone mapping an HDR clip into an SDR film, and converting an SDR clip into an HDR one, also run on
the GPU when FFmpeg has libplacebo and a Vulkan device. The GPU runs the same maths as the CPU
chain (zscale and the `tonemap` filter), so the picture lands within a code value of it. A
one-frame comparison per run decides; anything that misses keeps the CPU. On the T1000 worker, 6 s
of 4K HLG tone-mapped to SDR went from 107 s of CPU to 3 s.

- **Docker and Kubernetes on NVIDIA:** the images' FFmpeg has libplacebo. The container needs the
  `graphics` driver capability for Vulkan, next to `video` for NVENC.
- **Mac:** Homebrew's `ffmpeg` has no libplacebo; `ffmpeg-full` does, through MoltenVK. It installs
  beside `ffmpeg` without replacing it, so put `$(brew --prefix ffmpeg-full)/bin` first on the
  `PATH` the app runs with. On an M-series Mac the same 6 s of 4K went from 17 s of CPU to 0.4 s.

Photo moves are cut on the GPU when title effects run on one (CUDA or Metal), and a Live Photo
burst is decoded on the GPU. On NVIDIA its merge is encoded with NVENC's lossless mode, which gives
back exactly the frames x264 would. Crossfades stay on the CPU: sending two 4K frames to the card
and one back costs more than the blend itself.

## Backends

| Hardware | Backend | Setup |
|---|---|---|
| Apple Silicon | VideoToolbox | Native Mac install; no device mapping |
| NVIDIA on Linux | NVENC | Driver, container toolkit and video capability |
| Intel integrated GPU | Quick Sync / VA-API | `/dev/dri` plus its render group |
| AMD on Linux | VA-API | `/dev/dri`, render group and Mesa driver |
| CPU | libx264 / libx265 | Always the fallback |

Normally leave probing on auto. To force a backend:

```yaml
advanced:
  hardware:
    backend: nvidia # auto, none, apple, vaapi or qsv also accepted
    encoder_preset: balanced
```

Availability is per codec. The default `output.codec_policy: prefer_hardware` may choose a codec
the device can encode. `strict` honours the requested codec. Explicit HDR and ProRes do not get
that swap.

## Prerequisites

### NVIDIA

Install the NVIDIA driver and container toolkit. `nvidia-smi` working is not enough: NVENC needs
the **video** driver capability, and GPU tone mapping needs **graphics**. Add this to the app
service (merge with its existing `deploy:`):

```yaml
    environment:
      NVIDIA_DRIVER_CAPABILITIES: "compute,video,utility,graphics"
    deploy:
      resources:
        limits:
          memory: 4G
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu, video, graphics]
```

Kubernetes's GPU overlay supplies the NVIDIA runtime and capabilities.
An incompatible driver/FFmpeg combination fails the probe and falls back to software.
The app image's CPU Torch build is intentional; use the CUDA inference service for GPU analysis.

### Apple Silicon

Use the versioned [native Apple Silicon installation](./uv-pip.md#apple-silicon). An existing
`all-mac` installation already includes the hardware bindings; there is no second app install.

VideoToolbox handles encoding and Metal handles title effects. The `mac` extra alone lacks the
classifiers needed for films. With `tier: auto`, Metal also selects GPU preparation (Full with an enabled reader). Set up the caption service and Laya, or choose `tier: basic` for CPU preparation. [Python installation](./uv-pip.md) also covers the FFmpeg build.

### Intel Quick Sync and AMD VAAPI

The amd64 image includes Intel and Mesa VA-API drivers. On a native Linux install, use
`intel-media-va-driver` (or its non-free variant) or `mesa-va-drivers`.

Pass the render device and its host numeric GID:

```bash
stat -c '%g' /dev/dri/renderD128
```

```yaml
services:
  immich-memories:
    devices:
      - /dev/dri:/dev/dri
    group_add:
      - "104" # use the GID printed above; DSM can use 937
```

The container's UID 1000 otherwise cannot open the device. Verify the driver too:

```bash
docker compose exec immich-memories vainfo
```

Look for `VAEntrypointEncSlice` or `VAEntrypointEncSliceLP`. ARM64 Docker has no bundled hardware
encoding path.

For VAAPI, `advanced.hardware.encoder_preset` maps `fast`, `balanced` and `quality` to
FFmpeg compression levels 7, 4 and 1. Lower levels favor quality; higher levels favor speed.
Supported levels depend on the driver. Changing the preset can change pixels and file size,
even at the same QP, and will not necessarily speed up a film dominated by CPU filters.

## NAS output and HDR

Basic output is capped at 1080p, in the film's orientation. A J4125-class NAS can encode H.264 but
not HEVC. With the default hardware preference, auto HDR can become an SDR H.264 film instead
of forcing slow software HEVC. Strict codec policy or explicit HDR can require software.

## Quality: one dial, calibrated per encoder

| `output.quality` | Use it for |
|---|---|
| `balanced` (default) | Normal films |
| `high` | More detail, larger files |
| `fast` | Balanced picture quality with a faster encoder preset |

Hardware encoders trade speed for larger files at similar picture quality. Exact CRF/QP values,
SSIM measurements and bitrate comparisons are in [Encoder calibration](./reference/rendering.md#quality-one-dial-calibrated-per-encoder).

## Without a GPU

The CPU still prepares, selects and renders films. Preflight reports `Software encoding (libx264)` as OK when no GPU is available. Titles use a static background and text drawn once by Pillow; FFmpeg slides, scales and fades the text. Hardware encoding can still encode those title frames. Moving gradients, bokeh and animated deblur need a rendering GPU. [Measured](../better/measured.md) separates picture analysis from rendering costs.

## Title kernels

`preflight` names the title renderer: GPU kernels, or Pillow text animated by FFmpeg on the CPU. `IMMICH_FORCE_CPU=1` selects the CPU path for title videos.
[Renderer backends and memory budgets](./reference/rendering.md) have the technical details.

### CPUs without AVX

Older Celerons and Atoms can lack AVX. The app tests the kernel renderer in a child process, then
uses Pillow raster text animated by FFmpeg if the probe cannot start. Preflight reports this supported path as OK: `CPU titles (Pillow + FFmpeg); moving backgrounds need a GPU`. Font, layout, palette, duration and frame rate remain; moving gradients and kernel effects do not.

## What the card is actually worth

Measure a small film first. Downloads, title rendering and final playback checks can dominate even
with a fast encoder. The [measurements](../better/measured.md) show where time is spent.
