---
title: Requirements and tiers
---

# Requirements and tiers

The default install is one container on the box that already runs Immich, and it makes the whole
film there. A GPU or a text model makes it better:
[what each one adds](../get-started/what-a-gpu-or-a-model-adds.md), feature by feature. This page
is what each setup needs, and how the app picks between them.

## Check this setup

Run `immich-memories capabilities` with the config you will use for your films. It reports the
resolved selection tier, provider connections, model files, hardware encoding, render memory
budget and local ACE-Step profiles. NAS output stays capped at 1080p. Add `--json` to save the
same results in a script.

`immich-memories capabilities --test-music` also generates a 15-second synthetic track with each
local profile that passes the memory check: your configured profile, 2B turbo without a planner,
and 2B turbo with the 0.6B planner. Duplicate profiles run once. The first test can download model
weights. Each track must be local, finite, audible and the requested length to earn `verified`.
Failed tests remain in the report, and settings stay unchanged.

An installed model or a successful connection is labelled as a check; it is not a completed film.
Memory estimates cover resident weights, with more needed for generation. A local reader such
as oMLX can keep its model loaded while idle. Unload that model and rerun the music test to measure
what fits with its memory freed. The command leaves model servers alone. Music that works after
unloading a reader has not been proven to fit alongside it.

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
- **NAS tier output is capped at 1080p**, including an explicit 4K request. Portrait films use
  1080×1920, landscape films use 1920×1080, and square films use 1080×1080. Lower resolutions
  stay lower. Photo preparation and final assembly share the same capped canvas.
- **Less memory** means fewer photos rendered at once. The app reserves 1 GiB for the parent
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
**Untested** means nobody has run it; it may work. **Conformance tested** means the individual
production features ran on synthetic fixtures; the pass count is separate from whole-film quality.

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
| Reader | Local: oMLX with Gemma 4 E4B (6-bit) | Conformance tested, 29/34 with request-specific modes | [Measured comparison](../better/measured.md#llm-conformance): the JSON-default regression and trip classification are resolved; remaining failures concern two free-text judgments, vision contracts and period weighting |
| Reader | Local: llama.cpp, Ollama | Supported | Films on earlier releases |
| Reader | Local: vLLM, mlx-vlm served directly | Untested | |
| Reader | Hosted: OpenAI (gpt-5.6-luna) | Conformance tested, 32/34 | [Measured failures](../better/measured.md#llm-conformance): recorded trip place and motion description |
| Reader | Hosted: z.ai (glm-5.3-flash) | Conformance tested, 31/34 | [Measured failures](../better/measured.md#llm-conformance): free-text exclusion, request reading and requested pool |
| Reader | Hosted: Melious (deepseek-v4.1-flash) | Conformance tested, 32/34, `structured_output: false` | [Measured failures](../better/measured.md#llm-conformance): free-text request reading and requested pool |
| Reader | Hosted: Anthropic's own API | Untested | The same code path only ran through z.ai's Anthropic-compatible route |
| Reader | Hosted: Melious gemma-4-31b | Not supported | Its API refused every image (HTTP 400), 2026-09-15 |
| Captions | SmolVLM2 500M, on a Mac | Tested | 2026-09-27, commit [`9eb16812`](https://github.com/sam-dumont/immich-video-memory-generator/commit/9eb168126c0f24f6cced39a0316f0045132e56c8), the `gpu` and `full` films above |
| Captions | SmolVLM2 500M, on the CUDA inference service | Supported | 2026-09-17, release 0.102.0 |
| Captions | SmolVLM2 under llama.cpp | Untested | |
| Laya | The family-viewing pre-screen, on a Mac | Tested | 2026-09-27, commit [`9eb16812`](https://github.com/sam-dumont/immich-video-memory-generator/commit/9eb168126c0f24f6cced39a0316f0045132e56c8), the `gpu` and `full` films above |
| Laya | The family-viewing pre-screen, on CUDA | Supported | Films on earlier releases |

## The three tiers {#the-preparation-tier}

`tier: auto`, the default, picks one tier for preparation and selection alike:

| Tier | Picked when | Also needs | What runs | Family-viewing check |
|---|---|---|---|---|
| **`nas`** | No GPU inference is found (the default) | `models fetch` | Immich metadata, and the DINOv2 encoder with eight heads and two detectors on the CPU | Rules and the detectors |
| **`gpu`** | A GPU inference runtime is found: the [inference service](../better/inference.md) reporting CUDA, a local CUDA runtime, or a Mac's Metal GPU | A [caption server](../better/captions.md) and the Laya checkpoint | NAS, plus captions and Laya for the pictures in the cut and the candidates to replace them | Laya can add holds; it never lifts one |
| **`full`** | GPU, plus a [text model](../better/reader.md) whose `llm.model` and endpoint (`llm.base_url`, or a hosted `llm.provider`) are both set | A text model with a 32k context | GPU, plus the text model's account of the period, its polish of the draft, the title and the music mood | Same as GPU. The text model never decides what is shareable |

`auto` looks only at the GPU runtime and those `llm` keys, not at the caption server or the
Laya checkpoint. `immich-memories preflight` checks the caption server, and `models fetch` also
downloads the Laya checkpoint once the tier is `gpu` or `full`.

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
