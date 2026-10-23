---
title: Requirements and tiers
---

# Requirements and tiers

Basic runs on a plain NAS. GPU adds inference and captions; Full adds a text reader.
[Choose your setup](../get-started/choose-your-setup.md) links the installation path for each tier.

See [Can I run this?](./tested-deployments.md) for platform status, supported Immich versions and untested routes.

## Hardware

Allow this **in addition to what Immich uses**:

| Resource | Start here |
|---|---|
| RAM | 4 GiB free for the app; the Compose file limits it to 4 GiB |
| CPU | 2 cores, x86-64 or ARM64; 4 cores make rendering less painful |
| Disk | about 25 GB plus 0.35 GB per 1,000 pictures and videos in your library for the persistent data volume (about 45 GB for 56,000), plus the image and finished films |
| Immich | v2 or v3, reachable from the app, with an API key |
| Docker | Engine with Compose v2; Docker Desktop also works |
| Python install | Python 3.11 to 3.13 and FFmpeg; see [uv / pip](./uv-pip.md) |

Previews are the part that grows with the library: a year, a lifetime or a captioning pass reads
every picture in scope, at about 0.32 MB each (two real installs: 16 GB for 50,600 previews, 19 GB
for 57,116). The rest is the video and prepared-source caches, 10 GB each, plus the store, models
and backups. The preview cache is capped at 30 GB by default, about 90,000 pictures; past that the
run warns and names `cache.thumbnail_cache_max_size_mb`. An SSD helps. Finished films need their own space unless you upload them to Immich.

A 30-minute film fits inside the default 4 GiB container limit on a NAS, with some swap. Your
library and output settings still affect memory use. See the
[measured examples](../better/measured.md#longer-films-memory-and-duration).

Before you install:

- **Basic output stops at 1080p**, even if you request 4K. More RAM alone does not change that.
- **The first film takes longer.** It prepares the pictures in your chosen period. Later films
  reuse that work, but still have to render.
- **Older Celerons work.** Without AVX, titles use the simpler renderer.
- **ARM64 Docker uses software encoding.** The bundled VA-API drivers are amd64 only.
- **A native `uv`/`pip` install on Linux ARM64 skips local vocal separation.** `sphn`, a dependency
  of the `demucs` extra, ships no wheel there and needs Rust plus a C compiler to build.
- **4K on GPU/Full needs more room.** Allow 8 GB for the app, plus memory for any model services.

See [performance guidance](../better/measured.md) and [platform scope](#supported-and-tested).
Ready? [Install with Docker Compose](./docker.md), or read the [NAS notes](./nas.md).

### GPU and Full resources

The NVIDIA Compose files limit the app to 8 GiB, inference to 4 GiB and captions to 3 GiB, plus
512 MiB for the one-time caption downloader. These are separate container limits, not a total
host budget. Leave room for Immich, the host and any reader too. Model images and service caches
need disk space beyond the app's own. GPU and Full also require the NVIDIA driver and
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
A native Apple Silicon install uses Metal instead.

## The three tiers {#the-preparation-tier}

The installation guides pin the tier you choose. On a custom installation, `tier: auto` chooses
from the inference hardware and model configuration it finds. Preflight checks its requirements.

<Diagram name="decide-tier" headline="auto picks the most your hardware can do. Set tier yourself to pin one." />
| Tier | What it adds | What you need |
|---|---|---|
| **Basic** | A complete film using metadata, CPU picture classifiers and selection rules | The default install and the app's **Download models** step |
| **GPU** | Image captions, extra document/sensitive-content checks and a family-viewing pre-screen | GPU inference, a caption server and the Laya checkpoint |
| **Full** | The GPU features, plus a text model's reading of the period and refinement of the draft | The GPU setup and a configured reader with 32k context |

A hardware **video encoder** or render worker speeds up rendering. It does not enable GPU
selection. [Choose your setup](../get-started/choose-your-setup.md) explains the
benefits before you set up extra services.

### Which tier you get {#which-tier-you-get}

`auto` detects a local CUDA runtime, a Mac's Metal GPU, or an inference service reporting CUDA.
With one of those it chooses GPU; an explicitly enabled reader makes that Full. It does **not** check
whether the caption server or Laya files are ready: run `preflight` after adding services.

A reader on Basic still names special days (trips too with `--llm-title`) and helps pick the music mood.
Selection stays on Basic.
On Apple Silicon, install the `all-mac` extra for GPU discovery. Captions need their own server;
an enabled `openai-compatible` or `ollama` reader with blank `base_url` starts locally when
`llama-server` is installed. Hosted provider presets use their vendor URL instead. The shipped
Docker and Kubernetes app images need an external reader.

A deployment sets its tier with one variable, `IMMICH_MEMORIES_DEPLOYMENT_TIER`: `auto`, `basic`,
`gpu` or `full`. It ranks with the environment, above YAML and Settings. A `tier` in `config.yaml`
or Settings is ignored with a warning naming the variable, and the Settings page shows the tier as
set by the environment. The base Compose and Kubernetes files default to Basic; their GPU/Full
files add the selected tier and its service connections. Terraform and the Kubernetes one-shot
job default to `auto`.

Selecting a tier does not install models or start servers. Full without an enabled reader fails
configuration loading, before the UI or `preflight` can start: configure and enable the reader
first, or select Basic/GPU. Changing tier keeps compatible prepared facts and your review decisions.

## Check this setup

After installation:

```bash
immich-memories preflight
immich-memories capabilities
```

`preflight` checks whether a film can run. `capabilities` reports the resolved tier, services,
encoding and memory budget. In Docker, prefix both with
`docker compose exec immich-memories`. More checks: [Diagnostics](./maintenance/health-logs-cache.md).

## Supported and tested

Docker Compose is the primary install. SQLite and PostgreSQL are supported. The app supports
Immich v2 and v3 API contracts, x86-64/ARM64 CPU deployments, NVIDIA CUDA inference and native
Apple Silicon inference. Hardware and driver combinations still need checking on your machine;
Terraform is an example module to adapt to your cluster.

[Can I run this?](./tested-deployments.md) lists the combinations tested for this release. Run
`preflight` after installing, and read the [render memory details](./reference/rendering.md) before
planning 4K or a worker.
