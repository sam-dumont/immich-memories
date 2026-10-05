---
title: How I run it
description: The full setup I use at home, everything turned on, on Kubernetes with two old NVIDIA cards and a Mac. What each piece adds and what it costs.
---

# How I run it

This is my own install, with every optional piece turned on. The app runs in my home Kubernetes
cluster as one CPU-only pod, next to Immich. Everything that wants a GPU (captions, the picture
classifiers, music stem separation and the render itself) goes to one GPU worker on an 8 GB
NVIDIA T1000. That card is time-sliced: Immich's own machine learning, an ACE-Step music server
and a media server share it. The text reader runs on an Apple Silicon Mac on the same network,
because that's where the memory is. A ten-year-old GTX 1070 in a second node keeps a caption
server on standby. The result is the Full tier with generated music, rendered at 1080p, behind
an OIDC login.

You don't need any of this for a good film. The [Basic tier](../get-started/choose-your-setup.md)
makes a complete one on a NAS. This page is for when you have the hardware and want all of it.

{/* diagram: how-i-run-it */}

## What runs where

| Component | Runs on | What it adds to the film | What it costs |
|---|---|---|---|
| The app: web UI, selection, Laya, the store | Cluster, one CPU-only pod | Everything in Basic: stories, people, trips, titles, time order, the cut itself | 2 CPU and 4 GiB requested, 8 GiB limit; a 10 GiB cache volume and 10 GiB for finished films; no GPU |
| GPU worker (the CUDA inference image) | T1000 node, one time-sliced slot | Captions, the picture classifiers and the document and sensitive-content detectors, music stems for ducking under clip audio, NVENC rendering | About 0.3 GB VRAM for the classifiers and 1 GB for captions; 2 GiB RAM requested, 8 GiB limit; a 10 GiB model cache; up to 20 GiB of render scratch |
| ACE-Step API server | T1000 node, same card | A soundtrack written for the film's length and mood, instead of a bundled track | The 2B turbo model with its 0.6B planner, offloaded to CPU between phases so it fits beside everything else on 8 GB; 20 GiB RAM limit; a 28 GB image |
| Text reader: Gemma 4 E4B, 6-bit, on oMLX | Apple Silicon Mac, on the LAN | Full tier: it reads the period and refines the rules draft; also titles and music mood | Unified memory on the Mac. Mine has 128 GB, which is a lot more than a 4B-class model needs: a 16 GB Mac runs Full |
| Spare caption server (llama.cpp CUDA build) | GTX 1070 node, scaled to zero | Nothing while the worker is up; it's my fallback if the T1000 is busy or down | About 1 GB VRAM and 2 GiB RAM when on |
| Immich and its machine learning | Cluster, GPU nodes | The library, faces and smart search that selection reads | Immich's own budget, not this app's |
| Reverse proxy with TLS, OIDC provider | Cluster ingress, hosted identity provider | Nothing in the film: the family signs in with an account they already have | A small proxy pod; the identity provider is hosted elsewhere |
| Geocoding and map tiles | Public services | Place names, trip names, the map fly-over | Calls leave my network; both are opt-in ([Privacy](privacy.md)) |
| Push notifications | A public ntfy topic | A ping when a film is done or failed | Nothing |

A few choices in there are deliberate:

- **One GPU worker instead of three pods.** One slot on the card, one queue, one token. The
  worker unloads its weights after five idle minutes, so between films it holds almost nothing.
- **The app pod has no GPU.** It only coordinates: it asks the worker for captions, facts and the
  render, and Laya runs on its CPU. That keeps it on the node with its volumes and off the card.
- **One film at a time.** Time-slicing gives every pod access to the card, not its own slice of
  VRAM. The worker, ACE-Step and Immich's machine learning take turns fine; two films at once
  would not.
- **The reader stays on the Mac.** An 8 GB card that is already shared has no room for a
  language model, and the Mac has the memory sitting there anyway.
- **The 1070 is still useful.** llama.cpp still ships kernels for Pascal cards, so captions run
  on it. The inference service doesn't: current onnxruntime CUDA builds dropped Pascal, which is
  why the classifiers live on the T1000. For rendering, the 1070 is actually a bit faster than
  the T1000 ([measured](../better/measured.md)).

On this setup a first monthly film from a cold cache takes 9 to 13 minutes on the cluster card.
[Measure your setup](../better/measured.md) has the other machines.

## On smaller hardware

Start with Basic and add one thing at a time. Each step below changes the film by itself.

- **Just a NAS.** Run [Basic on the NAS](nas.md). It makes the same kind of film from Immich's
  data with bundled music. [One month, three tiers](../better/tier-example.md) shows what you gain
  from each step before you buy anything.
- **One NVIDIA card somewhere on the LAN.** Run the [one GPU service](reference-setup.md) on it
  and keep the app on the NAS. That's my GPU worker without Kubernetes, and it gets you the GPU
  tier: captions, the detectors, the family-viewing check and a GPU render.
- **An old GTX 10xx card.** Put [captions](../better/captions.md) on it and let the classifiers
  run on the app's CPU. Rendering on it works too.
- **No Mac, or no spare memory.** Skip the reader: the GPU tier is a good film. Or use a
  [hosted reader](../better/reader.md#hosted) for a few cents a film.
- **Music.** Bundled tracks are fine. ACE-Step without its planner needs about 7 GB of free
  memory ([music](../better/music.md)); don't squeeze it onto a card that is already full.
- **Only a Mac.** The [Apple Silicon setup](reference/mac-example.md) runs everything natively,
  reader and music included.

[Choose your setup](../get-started/choose-your-setup.md) lists what each tier needs.

## The manifests to start from

The repo ships a maximalist example in three flavours. They describe the same pieces I run, with
a few differences in layout:

- Kustomize: [`deploy/kubernetes/overlays/maximalist`](https://github.com/sam-dumont/immich-memories/tree/main/deploy/kubernetes/overlays/maximalist).
  [Distributed services on Kubernetes](reference/cluster-example.md) walks through the secrets,
  the config and the apply.
- Terraform: [`deploy/terraform/examples/maximalist`](https://github.com/sam-dumont/immich-memories/tree/main/deploy/terraform/examples/maximalist).
  It creates the app, the render sidecar and captions, but not the inference service.
- Compose: [`docker-compose.maximalist.yml`](https://github.com/sam-dumont/immich-memories/blob/main/docker-compose.maximalist.yml),
  for the same config on one Docker host.

Where my cluster differs from the shipped overlay:

- **I run one GPU worker, not three GPU pods.** The overlay puts the render worker in the app pod
  as a sidecar, and the captioner and the inference service in pods of their own: three GPU
  allocations. I run the CUDA inference image with
  `python -m immich_memories_inference.gpu_worker` as one Deployment, give it
  `IMMICH_MEMORIES_RENDER_WORKER_TOKEN`, `IMMICH_MEMORIES_RENDER_WORKER_IMMICH_URL` and
  `NVIDIA_DRIVER_CAPABILITIES=compute,video,utility` (NVENC needs `video`), and point all three
  URLs at its Service. No overlay ships that shape: start from `overlays/inference-cuda` and change
  the command and the environment. The [one GPU service](reference-setup.md) page has the same
  worker for Docker.
- **ACE-Step runs in the cluster, on the same card.** The overlay expects an existing ACE-Step
  server somewhere and doesn't deploy one.
- **My cards are time-sliced.** The NVIDIA device plugin advertises each card as several slots,
  so the worker, ACE-Step and Immich's machine learning all request one GPU and land on the same
  T1000. The overlay assumes whole allocations; sharing a card is cluster configuration you set up
  yourself.
- **The worker also has a LAN address.** A NAS or Mac install can borrow it for captions, facts
  and rendering. Only `/render` checks the token, so that address stays on the LAN.
- **The reader is on the Mac**, same as the overlay's default. Nothing about it is in the cluster
  except a NetworkPolicy port.

The app's side of the one-worker layout, with the worker's Service named `inference` in the same
namespace:

```yaml
advanced:
  inference:
    facts_base_url: http://inference:8092
    fallback_to_local: true
  editorial:
    preparation:
      caption_base_url: http://inference:8092/v1
render:
  worker_base_url: http://inference:8092/render
  worker_token: ${RENDER_WORKER_TOKEN}
  allow_insecure_http: true
```

`fallback_to_local: true` means a worker that is restarting costs that run its picture facts, not
the run. `allow_insecure_http` is an opt-in for plain HTTP inside the cluster: render requests
carry the Immich API key, so only use it on a network you trust.
