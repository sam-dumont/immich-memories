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
video kept 7 days) with room for the store to grow. The models are about 140 MB. The one file worth backing
up is the store, `store.db`, where every fact the editor read is banked:
[What to keep](./docker.md#what-to-keep).

Which hosts it has run on, and when, is in [Supported and tested](#supported-and-tested) below.
Timings are on [Measured](../better/measured.md).

## Supported and tested

**Tested** means run end to end, with the date and the commit or release it ran on: check the
date against your version. **Supported** means the code path exists and worked on an earlier
release, but has not been checked since: it probably works, and a report is welcome if it doesn't.
**Untested** means nobody has run it; it may work.

The last release on PyPI is 0.103.0, from 2026-09-17. Rows tested after that date ran on `main`
and the Docker image built from it, not on a `pip install`.

| Area | What | State | Evidence |
|---|---|---|---|
| Setup | Plain NAS (`nas` tier) | Tested | Every pull request cuts a month on a real Immich (v2 and v3); a cut, an edit and a render in the browser, 2026-09-27; 28 films on the maintainer's library (years, months, trips, seasons, people, special days), 2026-09-27, commit [`9eb16812`](https://github.com/sam-dumont/immich-video-memory-generator/commit/9eb168126c0f24f6cced39a0316f0045132e56c8) |
| Setup | GPU and model (`full` tier) | Tested | A July film on the maintainer's library, on `main`, Apple Silicon, 2026-09-28; 28 films on the maintainer's library (years, months, trips, seasons, people, special days), 2026-09-27, commit [`9eb16812`](https://github.com/sam-dumont/immich-video-memory-generator/commit/9eb168126c0f24f6cced39a0316f0045132e56c8) |
| Setup | GPU (`gpu` tier) | Tested | 28 films on the maintainer's library (years, months, trips, seasons, people, special days), 2026-09-27, commit [`9eb16812`](https://github.com/sam-dumont/immich-video-memory-generator/commit/9eb168126c0f24f6cced39a0316f0045132e56c8) |
| Immich | v2.7.5 and v3.2.2 | Tested | Checked on every pull request |
| Immich | 3.1.0 | Tested | The maintainer's library, 2026-09-28 |
| Immich | Other 2.x and 3.x releases | Supported | The version is detected at runtime; only the three above are exercised |
| Database | SQLite (the default) and PostgreSQL 16 | Tested | Both on every pull request that touches the store, since 2026-09-28 |
| Python | 3.11, 3.12, 3.13 | Tested | Every pull request, Linux and macOS |
| Platform | Apple Silicon, from source | Tested | The `full` tier film above, 2026-09-28 |
| Platform | Docker on x86 | Tested, deployment only | Every image change starts the compose file, upgrades, backs up and restores the store; no film renders in that check |
| Platform | Docker on arm64 | Untested | The image builds; it has not been run |
| Platform | Synology DS423+ (no AVX) | Supported | A one-month film on 2026-09-17, release 0.102.0 |
| Platform | Kubernetes manifests | Supported | Films on the maintainer's cluster, 2026-09-13 to 17 |
| Platform | Terraform module | Untested as shipped | An example module: adapt it to your cluster |
| GPU | NVIDIA inference service and NVENC encoding | Supported | 2026-09-17, release 0.102.0, on a T1000 |
| GPU | Intel VA-API and Quick Sync | Supported | 2026-09-11, on the DS423+ |
| GPU | AMD VA-API | Untested | The drivers ship in the image |
| Render worker | The service's own test suite | Tested | Every pull request that touches it; no dated deployment on a real GPU box |
| Reader | Local: oMLX with Gemma 4 E4B (6-bit) | Tested | 2026-09-27, commit [`9eb16812`](https://github.com/sam-dumont/immich-video-memory-generator/commit/9eb168126c0f24f6cced39a0316f0045132e56c8), the `full` films above |
| Reader | Local: llama.cpp, Ollama | Supported | Films on earlier releases |
| Reader | Local: vLLM, mlx-vlm served directly | Untested | |
| Reader | Hosted: z.ai (glm-5.3-flash) and OpenAI (gpt-5.6-luna) | Supported | Last run 2026-09-17; re-test: [#1513](https://github.com/sam-dumont/immich-video-memory-generator/issues/1513) |
| Reader | Hosted: Melious (DeepSeek, deepseek-v4.1-flash) | Supported | Last run 2026-09-15; re-test: [#1513](https://github.com/sam-dumont/immich-video-memory-generator/issues/1513) |
| Reader | Hosted: Anthropic's own API | Untested | The same code path only ran through z.ai's Anthropic-compatible route |
| Reader | Hosted: Melious gemma-4-31b | Not supported | Its API refused every image (HTTP 400), 2026-09-15 |
| Captions | SmolVLM2 500M, on a Mac | Tested | 2026-09-27, commit [`9eb16812`](https://github.com/sam-dumont/immich-video-memory-generator/commit/9eb168126c0f24f6cced39a0316f0045132e56c8), the `gpu` and `full` films above |
| Captions | SmolVLM2 500M, on the CUDA inference service | Supported | 2026-09-17, release 0.102.0 |
| Captions | SmolVLM2 under llama.cpp | Untested | |
| Laya | The family-viewing pre-screen, on a Mac | Tested | 2026-09-27, commit [`9eb16812`](https://github.com/sam-dumont/immich-video-memory-generator/commit/9eb168126c0f24f6cced39a0316f0045132e56c8), the `gpu` and `full` films above |
| Laya | The family-viewing pre-screen, on CUDA | Supported | Films on earlier releases |

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
