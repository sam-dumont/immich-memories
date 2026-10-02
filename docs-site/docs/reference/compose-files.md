---
title: Compose setup files
---

# Compose setup files

A release publishes these files beside its deployment bundle. Download them from the same
release; `example.env` and every image default carry that release's version, including RC tags.

| File | Purpose |
|---|---|
| `docker-compose.yml` | One NAS app, its persistent config/store volume and output mount |
| `example.env` | Immich connection, one `IMMICH_MEMORIES_VERSION`, optional reader/auth inputs |
| `docker-compose.gpu.yml` | Inference, pinned caption weights and a caption server; requests GPU tier |
| `docker-compose.full.yml` | Requests Full; add after the GPU file and explicitly enable a reader |
| `docker-compose.cuda.yml` | Version-matched CUDA inference, CUDA caption image and NVIDIA device access |
| `docker-compose.gpu-worker.yml` | Standalone combined inference/caption/render worker on one GPU box |
| `docker-compose.postgres.yml` | Optional PostgreSQL store, persistent data and app readiness dependency |

## Select the files

The base file runs alone. Add the GPU file for its services, then Full or CUDA when needed:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.full.yml -f docker-compose.cuda.yml up -d
```

You can put that selection in `.env` instead, so updates use plain `docker compose up -d`:

```dotenv
COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml:docker-compose.cuda.yml
```

The GPU file's default images run on CPU. The CUDA file needs NVIDIA Container Toolkit and
an exposed NVIDIA GPU. Selecting a tier expresses intent; it does not prove the hardware works.
`preflight` reports inference compute separately from video encoding and warns when acceleration
is missing. It leaves the requested tier unchanged.

## Reader and Settings

For Full, set all three in `.env` before starting:

```dotenv
READER_ENABLED=true
READER_URL=http://reader-box:8000/v1
READER_MODEL=your-server-model-name
# Optional, when the reader requires authentication:
READER_API_KEY=your-reader-key
```

A URL/model alone never enables the reader. Docker Full requires an external reader; the shipped
image does not include the local reader runtime. Native installations can use a blank URL after
installing that runtime and its model. The same reader inputs work on NAS for titles and music
mood; they do not turn NAS selection into Full.

Tier files use `IMMICH_MEMORIES_DEPLOYMENT_*` defaults. Saved Settings, YAML and normal runtime
environment overrides still take priority, so inference URL, caption URL and reader settings
remain editable. Explicit runtime overrides such as `IMMICH_MEMORIES_LLM__BASE_URL` keep their
existing precedence and remain locked in Settings.

The deployment suffixes are `TIER`, `GPU_BOX`, `INFERENCE_URL`, `CAPTION_URL`, `READER_URL`,
`READER_MODEL`, `READER_API_KEY` and `READER_ENABLED`. Native or Kubernetes recipes can set explicit service URLs;
an empty inference URL keeps native inference local.

## Remote GPU box

The standalone worker file needs `IMMICH_URL` and a shared `RENDER_WORKER_TOKEN`. It publishes
only on localhost by default; set `GPU_WORKER_BIND_ADDRESS` deliberately for a private LAN or
VPN and restrict which machines can reach it. Pictures sent for inference/captioning are private
library content; the render token does not protect those model routes.

The NAS app uses the base file, with this block in its `.env`:

```dotenv
TIER=gpu
GPU_BOX=192.168.1.50
```

That supplies inference at port 8092 and captions at `/v1` on the same address. Hostnames,
optional ports and IPv6 are accepted. Local fallback stays enabled. Rendering offload stays
separate: set the authenticated worker URL ending in `/render` and its shared token through
[render worker settings](./output-rendering.md).

## PostgreSQL

The base file keeps SQLite. Add `docker-compose.postgres.yml` only when choosing a PostgreSQL
store, and set `POSTGRES_PASSWORD`. For an existing SQLite install, follow the
[copy-first procedure](../run/database.md#move-to-postgresql) before enabling the app database URL.
