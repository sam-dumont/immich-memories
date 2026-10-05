---
title: One GPU service
---

import DeploymentDiagram from '@site/src/components/DeploymentDiagram';

# One GPU service

Keep the app on the NAS and move classifiers, captions, Demucs stems and rendering to one NVIDIA
container. The text reader and ACE-Step music generation are separate choices. Laya runs in the app.

<Diagram name="deploy-compose" headline="Start with one container. Add a file for each upgrade." />
## One GPU service {#one-gpu-service}

Use the CUDA inference image matching the app version, the NVIDIA Container Toolkit and a
private address reachable from the app. From a checkout of that release:

```bash
export GPU_WORKER_IMAGE=ghcr.io/sam-dumont/immich-memories/inference:YOUR_APP_TAG-cuda
export IMMICH_URL=https://photos.example.com
export RENDER_WORKER_TOKEN=$(openssl rand -hex 32)
export GPU_WORKER_BIND_ADDRESS=192.168.1.50
docker compose -f services/inference/compose.gpu-worker.yaml up -d
```

Save the token in your secret manager and use the same value in the app. The recipe defaults to
loopback binding if you omit `GPU_WORKER_BIND_ADDRESS`. The model-cache volume holds reusable
weights and runtime caches; render-scratch holds the worker's downloaded originals and temporary
render files. It is separate from the app's finished-output volume. The service reserves one
NVIDIA GPU and does not set a RAM limit.

Configure the app:

```yaml
advanced:
  inference:
    facts_base_url: http://192.168.1.50:8092
    fallback_to_local: false
  editorial:
    preparation:
      caption_base_url: http://192.168.1.50:8092/v1
render:
  worker_base_url: http://192.168.1.50:8092/render
  worker_token: ${RENDER_WORKER_TOKEN}
  allow_insecure_http: true
  fallback_to_local: false
```

`allow_insecure_http` is an explicit opt-in for this trusted LAN: render requests include the
Immich API key. Use HTTPS through a proxy otherwise, and omit that opt-in. Only `/render` checks
the bearer token; `/facts`, `/audio/stems` and `/v1` have no built-in authentication. Do not expose
this listener to the internet.

<DeploymentDiagram topology="worker" />

Check from the app's environment:

```bash
immich-memories preflight -v
# When the app runs in Docker Compose:
docker compose exec immich-memories immich-memories preflight -v
```

The Compose health check verifies the inference listener and authenticated render health. It
does not certify caption responses or every model's provider. Preflight checks reachability,
model advertisement and reported capabilities; preparation validates synthetic caption controls
before sending library pictures.

## Optional generated music

The CUDA worker separates Demucs stems but does not generate ACE-Step music. Connect your own
[ACE-Step API server](../better/music.md#api-server), or use local library mode on a native Linux
or Mac checkout. The external music server owns its model lifetime. Configure its model and
planner on that server; the app's local `model_variant`, `use_lm` and `cpu_offload` settings do not
change the remote service. Sharing one card still requires room for every resident service.
The [tested ACE-Step build and single-GPU limits](../better/music.md#sharing-one-gpu-with-the-worker)
record the service used for the June cold runs. Kubernetes time-slicing does not unload models.

## Memory and scheduling

Work changes phase between classifiers, captions, audio and rendering. The worker unloads
classifier weights and stops its owned caption subprocess when switching away from them.
Demucs releases after separation. Captions restart on demand.

Rendering waits up to 60 seconds for active model work to finish. Conflicting requests return
`503` with `Retry-After: 1`; classifier queue overflow separately returns `429`. Native work keeps
its GPU ownership even when its client cancels. Requests for the same model phase wait up to
60 seconds for cleanup, then enter that service's existing queue. `/queue` reports classifiers,
not a combined queue for all phases.

One container saves duplicate services and image layers. It still needs enough host RAM and
VRAM for the largest active phase, scratch space for originals and output, and headroom for other
GPU users. The bundled caption command sets an 8192-token context; it does not explicitly bound
llama.cpp's RAM prompt cache or processing slots. Separate-reader or music services can still
compete for the card. Measure your workload before raising concurrency.

## Scratch space for 4K

For 4K rendering, [the Kubernetes storage guidance](./reference/kubernetes.md) recommends
**8 GiB of disk-backed `/tmp`**; size it for your workload. Keep model files and finished output
on their own volumes. A model-only service's small temporary volume can fill during
source preparation after rendering is added.

In Kubernetes, leave the scratch `emptyDir` disk-backed and set its `sizeLimit` for that work.
The node also needs the corresponding free ephemeral storage. A RAM-backed `emptyDir` charges
the container's memory budget; increasing a RAM limit does not increase disk scratch space.

## Other deployments

The shipped Kubernetes inference and caption overlays and render sidecar deploy **separate**
services; there is no unified-worker overlay. Use the [Kubernetes reference](./reference/kubernetes.md)
for those manifests. The [multi-service cluster example](./reference/cluster-example.md) is for
operators deliberately distributing work across nodes.

For Apple Silicon, use the [Mac example](./reference/mac-example.md). The CUDA worker cannot use
Metal. Service API details and offline model provisioning are in the
[inference reference](../reference/inference-service.md).
