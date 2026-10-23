---
title: Compose setup files
---

# Compose setup files

Every release, release candidates included, publishes these files beside its deployment bundle.
Download them from the same release: `example.env` and every image default carry its version.

| File | Purpose |
|---|---|
| `docker-compose.yml` | The Basic app on `127.0.0.1:22830` (4 GB memory limit), its config and store volume, and `./output` |
| `example.env` | Immich connection, `IMMICH_MEMORIES_VERSION`, tier, GPU box and reader inputs |
| `docker-compose.gpu.yml` | GPU tier: the inference service, a one-shot download of the pinned caption weights and the caption server; raises the app's limit to 8 GB |
| `docker-compose.full.yml` | Full tier; add after the GPU file, with a reader enabled |
| `docker-compose.cuda.yml` | CUDA images for inference and captions, with NVIDIA device access |
| `docker-compose.gpu-worker.yml` | The unified inference, caption and render worker, on its own GPU box |
| `docker-compose.postgres.yml` | A PostgreSQL 16 store with its own volume; the app waits for it to be healthy |

<Diagram name="deploy-compose" headline="Basic is one container. GPU adds inference and captions; Full connects your reader." />
## Select the files

The base file runs Basic alone and publishes the web UI on host port 22830 (8080 inside the
container), bound to `127.0.0.1`. To reach it from another machine, set `UI_BIND_ADDRESS`; sign-in
is on by default. For NVIDIA, add the GPU and CUDA files from the same release; Full also needs
its tier file and a reader. The matching tab in
[Quick start](../get-started/quick-start.md#1-download-the-files) has the downloads.

GPU:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.cuda.yml up -d
```

Full:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.full.yml -f docker-compose.cuda.yml up -d
```

You can put that selection in `.env` instead, so updates use plain `docker compose up -d`:

```dotenv
COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml:docker-compose.cuda.yml
```

Without the CUDA file, the GPU file's images run on the CPU, which is only useful for diagnosis.
The CUDA file needs the NVIDIA Container Toolkit and a GPU the container can see. Picking a tier
doesn't prove the hardware works: `preflight` reports inference compute separately from video
encoding and warns when acceleration is missing, without changing the tier.

## Reader and Settings

For Full, set all three in `.env` before starting:

```dotenv
READER_ENABLED=true
READER_URL=http://reader-box:8000/v1
READER_MODEL=your-server-model-name
# Optional, when the reader requires authentication:
READER_API_KEY=your-reader-key
```

A URL and model alone never enable the reader. Docker Full needs an external reader: the image
doesn't include the local reader runtime. A native install can leave the URL blank once that
runtime and its model are installed. The same reader inputs work on Basic for titles and music
mood, without turning Basic selection into Full.

The Compose files pass these to the app as `IMMICH_MEMORIES_DEPLOYMENT_*` variables, with the
suffixes `TIER`, `GPU_BOX`, `INFERENCE_URL`, `CAPTION_URL`, `READER_URL`, `READER_MODEL`,
`READER_API_KEY` and `READER_ENABLED`. `TIER` is the tier, ranked like an environment variable, so
`.env` and a config file can't disagree. The others are defaults: saved Settings, YAML and normal
environment overrides win, so the service URLs and reader stay editable in Settings. A normal
override such as `IMMICH_MEMORIES_LLM__BASE_URL` wins over Settings too, and locks that field
there. Native and Kubernetes recipes can set the service URLs directly; an empty inference URL
keeps inference in the app.

## Remote GPU box

The worker file needs `IMMICH_URL` and a shared `RENDER_WORKER_TOKEN`. It publishes port 8092 on
localhost only; set `GPU_WORKER_BIND_ADDRESS` to open it to a private LAN or VPN, and restrict
which machines can reach it. The render token doesn't protect the inference and caption routes,
and the pictures sent there are your library.

The NAS app uses the base file, with this block in its `.env`:

```dotenv
TIER=gpu
GPU_BOX=192.168.1.50
```

That points inference at port 8092 on that address and captions at `/v1` on the same address.
A hostname, an IPv6 address or an explicit port (`GPU_BOX=gpu-box:9000`) also work. Local
fallback stays on. Rendering is set separately: the worker URL ending in `/render` and its token
go in the [render worker settings](./output-rendering.md).

## PostgreSQL

The base file uses SQLite. Add `docker-compose.postgres.yml` only if you want a PostgreSQL store,
and set `POSTGRES_PASSWORD` in `.env`. For an existing SQLite install, follow the
[copy-first procedure](../run/database.md#move-to-postgresql) before enabling the app database URL.
