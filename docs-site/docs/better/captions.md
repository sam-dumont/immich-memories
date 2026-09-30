---
title: Add captions
---

# Add captions

Captions are short descriptions used by selection and sharing checks. They are not the date and place labels printed on the film.

NAS works without them. GPU and Full describe the selected pictures and replacement candidates, then reuse those descriptions on later cuts. You do not need to caption the whole library before making a film.

The default captioner is **SmolVLM2 500M**. It receives small picture previews. Keep the service on your private network.

## Docker Compose

The repository’s Compose file includes a captioner profile:

```bash
docker compose --profile captioner up -d
curl -s localhost:8094/v1/models
```

Connect the app to both a [GPU inference service](./inference.md) and the captioner. In the app service’s environment:

```yaml
IMMICH_MEMORIES_TIER: auto
IMMICH_MEMORIES_INFERENCE__FACTS_BASE_URL: http://immich-memories-inference:8092
IMMICH_MEMORIES_EDITORIAL__PREPARATION__CAPTION_BASE_URL: http://immich-memories-captioner:8092/v1
```

The captioner is published on host port **8094**; inside Compose it listens on **8092**. A caption URL alone does not select the GPU tier. Install Laya’s [runtime and checkpoint](../reference/llm-providers.md#the-laya-audience-pre-screen) too.

For NVIDIA, use the CUDA image and device reservation together. The exact [CUDA recipe](../reference/caption-service.md#on-an-nvidia-host) and [Kubernetes overlays](../reference/caption-service.md#kubernetes) are in the service reference.

## Apple Silicon

Use the [mlxcel recipe](../reference/caption-service.md#apple-silicon-with-mlxcel) to serve the pinned model natively. Point the app at it:

```yaml
advanced:
  editorial:
    preparation:
      caption_base_url: http://localhost:8092/v1
```

From Docker Desktop, replace `localhost` with `host.docker.internal`. A Docker container cannot use the Mac’s Metal GPU directly; configure GPU inference separately.

## Check it

```bash
immich-memories preflight
```

Look for **Captions OK Serving smolvlm2-500m-base-public**. The app checks the served model and synthetic control pictures before sending your library’s pictures. GPU and Full need a working caption provider; NAS with default settings skips it.

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
