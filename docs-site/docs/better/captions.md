---
title: Add captions
---

# Add captions

For a new GPU or Full install, [Quick start](../get-started/quick-start.md) starts the required services together. The recipes below cover an existing installation.

Captions are short descriptions used by selection and sharing checks. They are not the date and place labels printed on the film.

Basic works without them. GPU and Full describe the selected pictures and replacement candidates, then reuse those descriptions on later cuts. You do not need to caption the whole library before making a film.

The default captioner is **SmolVLM2 500M**. It receives small picture previews. Keep the service on your private network.

## One NVIDIA worker

If you are adding GPU inference and rendering too, use the [one-GPU setup](../run/reference-setup.md#one-gpu-service).
It serves captions at `/v1` in the same container, starting its bundled caption process on demand.
Set `caption_base_url` to `http://gpu-box:8092/v1`. No separate caption container is needed.

The routes are unauthenticated. Keep the worker private. The GPU and Full tiers still need Laya
in the app; captions alone do not enable GPU selection.

## Separate Docker Compose captioner

For an existing Compose install, [select the GPU and CUDA files](../reference/compose-files.md#select-the-files)
from the same release as the app. They start inference, the caption weight downloader and the
caption server. Keep the file selection in `.env` for later restarts and updates.

Check the caption server from the host running Compose:

```bash
curl -s localhost:8094/v1/models
```

The preset supplies the inference and caption service URLs below saved Settings. On an existing
install, change those URLs in Settings. The captioner is published on host port **8094**; inside
Compose it listens on **8092**. GPU is a requested tier: preflight still checks the inference
provider and Laya runtime. A CPU service does not satisfy GPU readiness.

For NVIDIA, use the CUDA image and device reservation together. The exact [CUDA recipe](../reference/caption-service.md#on-an-nvidia-host) and [Kubernetes overlays](../reference/caption-service.md#kubernetes) are in the service reference.

## Apple Silicon

Use the [native Mac setup](../run/uv-pip.md#apple-silicon) to serve the pinned model natively. Point the app at it:

```yaml
advanced:
  editorial:
    preparation:
      caption_base_url: http://localhost:8092/v1
```

From Docker Desktop, replace `localhost` with `host.docker.internal`. A Docker container cannot use the Mac’s Metal GPU directly; configure GPU inference separately.

## Check it

In Docker, prefix `immich-memories` commands with `docker compose exec immich-memories`
from the app's installation folder.

```bash
immich-memories preflight
```

Look for **Captions OK Serving smolvlm2-500m-base-public**. Preflight checks the served model name; preparation checks synthetic control pictures before sending your library’s pictures. GPU and Full need a working caption provider; Basic with default settings skips it.

The [service reference](../reference/caption-service.md#how-preflight-reports-it) explains unreachable, wrong-model and authentication failures.

## Explicit LLM captions

A reader configured for prose never receives pictures automatically. To send previews and video frame strips to a vision-capable LLM instead, opt in:

```yaml
advanced:
  editorial:
    preparation:
      caption_provider: llm
```

This uses your configured LLM and its credentials. It can cost much more than the small local captioner, especially hosted. The app warns before using it. Existing valid SmolVLM results are reused first.

Model pins, serving flags, caption provenance and motion-description contracts are in the [caption service reference](../reference/caption-service.md).
