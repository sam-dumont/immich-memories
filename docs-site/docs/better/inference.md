---
title: Run inference on another machine
---

# Run inference on another machine

The inference service moves picture classifiers off the app’s machine. It helps a slow NAS; it does not speed up video encoding. Use a [render worker](./gpu-render.md) for that.

The service receives picture previews and, for music stem separation, audio tracks. It has no built-in authentication. Keep it on a private network.

## What shares a container

| Work | Where it runs |
|---|---|
| Picture classifiers and Demucs stem separation | One inference service; CPU or CUDA image |
| Captions | A separate container that can reuse the CUDA image and its bundled weights |
| Text reader, ACE-Step music and render worker | Separate optional services |
| Laya family-viewing check | In the app process |

Start with the app alone. Add inference when classification or stem separation holds up a cut. You do not need a separate Demucs container. Add the other services only for the features you use.

Reusing an image saves downloads and disk space. Each running container still needs its own RAM and GPU memory. Classifier queues do not schedule caption or audio work; the [service reference](../reference/inference-service.md#watching-classifier-work) explains the limits.

## Start the service

The Compose profile starts a CPU service:

```bash
docker compose --profile inference up -d
curl -s localhost:8092/health
```

For NVIDIA, install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html), uncomment the inference service’s GPU device reservation in Compose, and select the CUDA image:

```bash
INFERENCE_TAG=latest-cuda docker compose --profile inference up -d
curl -s localhost:8092/health
```

The tag and device reservation both matter. Pin an exact release for unattended deployments. [Full device and Kubernetes recipes](../reference/inference-service.md#running-it-with-compose).

## Connect the app

```yaml
advanced:
  inference:
    facts_base_url: http://inference:8092
    fallback_to_local: true
```

Use `http://immich-memories-inference:8092` within the shipped Compose network. From another machine, use the service’s private LAN address. A Kubernetes Service name only resolves inside its cluster; [LAN access](../reference/inference-service.md#reach-the-service-from-outside-the-cluster) needs its own address.

## Verify acceleration

```bash
immich-memories preflight
curl -s http://inference:8092/health
```

The health response names each loaded producer’s provider. Look for `CUDAExecutionProvider` when you expect NVIDIA. A producer’s list is empty until it loads. A CUDA image can fall back to CPU, so a reachable endpoint alone is not proof of acceleration.

With `tier: auto`, CUDA inference enables GPU; a configured text reader enables Full. Those tiers also need [captions](./captions.md) and Laya. Hardware encoding does not count as inference capability.

## Persistence and failures

Keep the model cache on a volume. The CUDA image bundles its model weights; the CPU image can download missing pinned weights when allowed. The app keeps completed facts in its store, so switching service hosts does not discard matching work.

With `fallback_to_local: true`, missing remote facts can be computed locally if the app has the required models. Set it to `false` if a failed service should stop the cut instead.

Endpoint contracts, queues, concurrency, environment variables and cache provisioning are in the [inference service reference](../reference/inference-service.md). [Performance and costs](./measured.md) contains the measurements.
