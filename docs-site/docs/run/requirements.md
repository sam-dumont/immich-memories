---
title: Requirements and tiers
---

# Requirements and tiers

The default install is one container on the box that already runs Immich, and it makes the whole
film there. A GPU or a text model makes it better:
[what each one adds](../get-started/what-a-gpu-or-a-model-adds.md), feature by feature. This page
is what each setup needs, and how the app picks between them.

## Hardware

For this app's container, on top of what Immich itself uses:

| | Minimum | Recommended |
|---|---|---|
| RAM | 4 GB free for the container (the compose file's limit) | 8 GB, for 4K output or a render running beside Immich's own jobs |
| CPU | 2 cores, x86-64 or ARM64 | 4 cores, x86-64 with AVX |
| Disk | 25 GB on the config volume, plus the 2.4 GB image and your films | the config volume on an SSD |
| OS | Linux with Docker Engine and Compose v2 | same; Docker Desktop on a Mac or Windows works too |
| Immich | v2 or v3, and an API key | same |

What the minimum costs you:

- **Two cores** make the render the long part of every run. The editor banks what it reads, but not
  the encode: a second cut of the same month reads nothing again and still encodes the whole
  film.
- **No AVX** (Intel Celeron J4125 and friends) means the CPU fallback draws the titles instead
  of the animated title kernels: [CPUs without AVX](./hardware.md#cpus-without-avx).
- **ARM64** gets no hardware encoder: the VA-API drivers ship in the amd64 image only.

The 25 GB covers the caches at their default budgets (10 GB of Immich previews, 10 GB of downloaded
video kept 7 days) with room for the store to grow. The models are about 130 MB. The one file worth backing
up is the store, `store.db`, where every fact the editor read is banked:
[What to keep](./docker.md#what-to-keep).

Tested on a Synology DS423+ (Celeron J4125, four cores), on an Apple Silicon Mac and on a
Kubernetes cluster. Timings per host are on [Measured](../better/measured.md).

## The three tiers {#the-preparation-tier}

`tier: auto`, the default, picks one tier for preparation and selection alike:

| Tier | Picked when | What runs | Family-viewing check |
|---|---|---|---|
| **`nas`** | No GPU inference is found (the default) | Immich metadata, and the DINOv2 encoder with eight heads and two detectors on the CPU. Needs `models fetch` | Rules and the detectors |
| **`gpu`** | A GPU inference runtime (the [inference service](../better/inference.md) reporting CUDA, a local CUDA runtime, or a Mac's Metal GPU), plus a [caption server](../better/captions.md) and the Laya checkpoint | NAS, plus captions and Laya for the pictures in the cut and the candidates to replace them | Laya can add holds; it never lifts one |
| **`full`** | GPU, plus a configured [text model](../better/reader.md) with a 32k context | GPU, plus the text model's account of the period, its polish of the draft, the title and the music mood | Same as GPU. The text model never decides what is shareable |

A [render worker](../better/gpu-render.md) or [hardware encoding](./hardware.md) moves or speeds up
the encode. Neither changes the tier: a GPU that encodes video is not a GPU that runs the models.

### Which tier you get {#which-tier-you-get}

- A text model without the GPU tier still writes titles and picks the music mood. Selection stays on
  `nas`, and the log says which service is missing.
- On a Mac the `mac` extra's Metal bindings find the GPU, so an `all-mac` install reaches `gpu` and
  `full`; the caption server and the reader run as their own processes.
- `IMMICH_MEMORIES_TIER` beats `tier:` in `config.yaml`. The compose file and the Kubernetes
  manifests set it to `auto`: remove it if you want the file to decide.
- `nas`, `gpu` and `full` can be set explicitly, for side-by-side comparisons. They don't install a
  model or start a service. `immich-memories preflight` checks what the resolved tier needs.
- A cut reads the cheap facts for every picture it can reach. Captions and Live Photo checks wait for
  the pictures it selects and their replacement candidates. `immich-memories prepare` reads a whole
  period ahead of time when you ask for it.
- Everything is banked per picture and per producer, so changing the tier erases nothing, and a NAS
  library can add captions later.
