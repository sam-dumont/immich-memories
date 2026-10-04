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
the **video** driver capability. Add this to the app service (merge with its existing `deploy:`):

```yaml
    environment:
      NVIDIA_DRIVER_CAPABILITIES: "compute,video,utility"
    deploy:
      resources:
        limits:
          memory: 4G
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu, video]
```

Kubernetes's GPU overlay supplies the NVIDIA runtime and capabilities.
An incompatible driver/FFmpeg combination fails the probe and falls back to software.
The app image's CPU Torch build is intentional; use the CUDA inference service for GPU analysis.

### Apple Silicon

```bash
uv tool install --python 3.12 "immich-memories[all-mac]"
```

VideoToolbox handles encoding and Metal handles title effects. The `mac` extra alone lacks the
classifiers needed for films. With `tier: auto`, Metal also selects GPU preparation (Full with an enabled reader). Set up the caption service and Laya, or choose `tier: nas` for CPU preparation. [Python installation](./uv-pip.md) also covers the FFmpeg build.

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

The CPU still prepares, selects and renders films. Titles use a static background and text drawn once by Pillow, with FFmpeg opacity fades. Hardware encoding can still encode those title frames. Moving gradients, bokeh and animated deblur need a rendering GPU. [Measured](../better/measured.md) separates picture analysis from rendering costs.

## Title kernels

`preflight` reports whether animated title kernels or the CPU still-plate fallback will run. `IMMICH_FORCE_CPU=1` selects that fallback for title videos.
[Renderer backends and memory budgets](./reference/rendering.md) have the technical details.

### CPUs without AVX

Older Celerons and Atoms can lack AVX. The app tests the kernel renderer in a child process, then
falls back to Pillow still plates with FFmpeg fades if it crashes. Font, layout, palette, duration and frame rate remain; moving gradients and kernel effects do not.

## What the card is actually worth

Measure a small film first. Downloads, title rendering and final playback checks can dominate even
with a fast encoder. The [measurements](../better/measured.md) show where time is spent.
