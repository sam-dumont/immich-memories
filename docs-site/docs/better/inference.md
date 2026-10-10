---
title: Run inference on another machine
---

# Run inference on another machine

For a new GPU or Full install, use the matching tier in [Quick start](../get-started/quick-start.md). This page covers moving inference to another machine.

Move picture analysis off a slow NAS. On NVIDIA, one CUDA worker can also caption pictures,
split music into stems and render the film. Start with the app alone; add this when preparation
or rendering takes too long.

## One NVIDIA container

Use the [one-GPU setup](../run/reference-setup.md#one-gpu-service). It serves these URLs from
one container on port 8092:

| App setting | Worker URL | Work |
|---|---|---|
| `advanced.inference.facts_base_url` | `http://gpu-box:8092` | Picture classifiers and Demucs stems |
| `advanced.editorial.preparation.caption_base_url` | `http://gpu-box:8092/v1` | SmolVLM captions |
| `render.worker_base_url` | `http://gpu-box:8092/render` | Video rendering |

The worker switches between classifier, caption, audio and render phases. It unloads classifier
weights or stops its caption process when another phase needs the GPU. It keeps existing queues
within each phase; it does not run all the models at once or promise that every card will fit them.
The text reader, Laya family-viewing check and ACE-Step generation remain outside this container.

Only `/render` requires the render bearer token. Classifiers, captions and stems are
unauthenticated. Keep the entire address on a trusted private network. The render worker also
receives your Immich API key to download originals.

## Separate inference and captions {#classifiers-and-stems-only}

For an existing Compose install, [select the GPU and CUDA files](../reference/compose-files.md#select-the-files)
from the same release as the app. They start separate inference and caption services on NVIDIA.
Keep the file selection in `.env` so later `docker compose up -d` commands keep both services.

When the app and inference share that Compose network, the inference address is:

```yaml
advanced:
  inference:
    facts_base_url: http://immich-memories-inference:8092
    fallback_to_local: true
```

From another machine, use its private LAN address and publish the service on that address;
the shipped Compose file binds its ports to localhost. [Deployment recipes](../reference/inference-service.md#running-it-with-compose)
cover the images and device reservations. These separate services do not include remote rendering;
use the combined worker above when you need that too.

## Check it

In Docker, prefix `immich-memories` commands with `docker compose exec immich-memories`
from the app's installation folder.

```bash
immich-memories preflight
curl -s http://gpu-box:8092/health
```

Health names each loaded producer's execution provider; empty lists mean it has not loaded yet.
Look for `CUDAExecutionProvider` when you expect NVIDIA. A CUDA image can fall back to CPU, so
an answering port alone does not prove acceleration.

With `tier: auto`, a GPU inference service, a working local CUDA ONNX runtime, or a Mac's Metal GPU enables GPU; an enabled reader with a model makes that Full.
Captions and Laya still need to be ready. Hardware video encoding alone does not change selection tier.

Keep caches on volumes. Completed matching facts stay in the app's store when you move the
service. `fallback_to_local: true` lets the app attempt missing facts or stems locally if its
runtime and model files are installed. Set it to `false` when a failed service should stop the cut.

[Service reference](../reference/inference-service.md): artifact paths, queue limits, offline
setup and memory ownership. [Render setup](./gpu-render.md): tokens, transport and output checks.
