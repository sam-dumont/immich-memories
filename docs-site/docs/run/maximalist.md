---
title: A maximalist setup
---

# A maximalist setup

Every optional piece this project ships, on one deployment: the render worker as a sidecar, a
caption server on a card, OIDC behind a reverse proxy, an LLM and ACE-Step on another machine on
the LAN, geocoding and map tiles, and cache caps sized for a bigger library. Written up from a
real cluster deployment. Most installs want a fraction of this; the point of this page is to show
what each piece costs and where it runs, so you can pick the ones worth it.

`deploy/kubernetes/overlays/maximalist` and `docker-compose.maximalist.yml` are the two runnable
forms. Neither invents anything new: both compose overlays and profiles this project already
ships, plus the four pieces nothing else demonstrates yet (a declarative `config.yaml`, OIDC
behind a proxy, an off-box LLM and ACE-Step, and cache caps matched to the volume that holds them).

## What runs where

| Feature | Runs on | Config keys | Hardware |
|---|---|---|---|
| App + UI | the app pod | `tier: full` | any CPU |
| Render worker | sidecar in the app pod ([Kubernetes](./kubernetes.md#render-worker-as-a-sidecar)) or a separate host ([Render on a GPU box](../better/gpu-render.md)) | `render.worker_base_url`, `render.worker_token` | a GPU with NVENC/VideoToolbox/QSV |
| Caption server | `overlays/captioner-cuda` ([Kubernetes](./kubernetes.md#the-two-model-services)) or the `captioner` compose profile with `CAPTIONER_TAG=server-cuda` | `advanced.editorial.preparation.caption_base_url` | an NVIDIA card, including a GTX 1070 (`sm_61`, see [Hardware](./hardware.md#nvidia)) |
| OIDC behind a proxy | your reverse proxy + the app | `advanced.auth.public_url`, `advanced.auth.trusted_proxies`, `advanced.server.secure_cookies` | none |
| Declarative `config.yaml` | a ConfigMap + init container ([below](#a-configyaml-a-configmap-can-own)) | n/a (the file itself) | none |
| LLM on a LAN machine | another host, e.g. an Apple Silicon Mac ([Add a reader](../better/reader.md)) | `advanced.llm.base_url`, `advanced.llm.provider`, `advanced.llm.model` | whatever that host has |
| ACE-Step music | `ace_step.mode: api` against an ACE-Step 1.5 API server, in-cluster or on the same LAN machine | `advanced.ace_step.mode`, `advanced.ace_step.api_url` | ≥12 GB VRAM for the XL variant; the default 2B family fits smaller cards |
| Geocoding + map tiles | `nominatim.openstreetmap.org`, `server.arcgisonline.com` | `network.geocoding`, `network.map_tiles` | none |
| Cache caps | the cache PVC / volume | `cache.video_cache_max_size_gb`, `cache.thumbnail_cache_max_size_mb` | sized storage |
| Automation | the app's in-process timer, or a CronJob hitting `/api/trigger` | `advanced.automation.enabled`, `advanced.automation.daily_at` | none |

## Kubernetes

```bash
cd deploy/kubernetes
cp base/secret.yaml.example base/secret.yaml
cp overlays/render-sidecar/render-worker-secret.yaml.example overlays/render-sidecar/render-worker-secret.yaml
cp overlays/maximalist/maximalist-secret.yaml.example overlays/maximalist/maximalist-secret.yaml
vim base/secret.yaml overlays/render-sidecar/render-worker-secret.yaml \
    overlays/maximalist/maximalist-secret.yaml overlays/maximalist/config-map.yaml
kubectl apply -k overlays/maximalist
```

`overlays/maximalist/kustomization.yaml` composes `overlays/render-sidecar` (which itself pulls in
`base`) and `overlays/captioner-cuda`, rather than duplicating either. Two patches on top of that:
a bigger cache PVC (`pvc-maximalist.yaml`), and a third init container that installs `config.yaml`
(`deployment-maximalist.yaml`). Read [Kubernetes](./kubernetes.md) first: this page assumes the
base layout, the pod's four writable mounts, and `enableServiceLinks: false`, all covered there.

### A config.yaml a ConfigMap can own

`config_loader.py` checks `config.yaml`'s permission bits on every start and warns when the file
is readable by anyone but its owner:

```
Config file /home/immich/.immich-memories/config.yaml is readable by other users. Run: chmod 600 ...
```

A ConfigMap volume cannot satisfy that: every key it mounts comes out `0444`, world-readable, with
no way to `chmod` it from the pod spec. `overlays/maximalist/config-map.yaml` holds the file's
content; `deployment-maximalist.yaml` adds an `install-config` init container that copies it from
the read-only ConfigMap mount onto the writable cache PVC and `chmod 600`s it there, running as
uid 1000 like the rest of the pod. That is the general pattern for anyone who wants `config.yaml`
managed declaratively (GitOps, a Kustomize overlay per environment) instead of thirty env vars: a
ConfigMap for the content, an init container for the permissions.

### OIDC behind the proxy

Set both `advanced.auth.public_url` and `advanced.auth.trusted_proxies`, or the callback fails in
one of two ways. Without `public_url` there is nothing to compare the callback's origin against,
and the `redirect_uri` sent to the IdP is built from the in-cluster request and comes out
`http://`, which every IdP refuses before the app ever sees the request. With `public_url` set but
no `trusted_proxies`, `X-Forwarded-Proto` from the proxy is not trusted, so the request still looks
like plain HTTP to the app, and the callback comes back:

```
400 {"detail": "Invalid callback origin"}
```

`trusted_proxies` is the pod CIDR your CNI hands out, IPv4 and its IPv6 equivalent if the cluster
has one (`kubectl get nodes -o wide`, or your CNI's docs, name it). The full OIDC walkthrough,
including registering the client with your IdP, is on [Authentication](./authentication.mdx#oidc--sso).

### The CUDA captioner

`overlays/captioner-cuda` is on main already; this overlay reuses it rather than shipping a second
copy. It shares the caption alias, weights and port with the CPU `overlays/captioner`; what changes
is `--n-gpu-layers 99` and the node it lands on. Measured on the cluster this was written for: 3.5 s
a picture on the CPU image, 0.08 to 0.23 s on a card. llama.cpp's CUDA build still runs on Pascal
(`sm_61`, a GTX 1070): a card too old for the `-cuda` [inference service](../better/inference.md),
whose PyTorch cu128 wheels have already dropped that architecture, is still worth applying here.

### Cache caps and the PVC

`cache.video_cache_max_size_gb` and `cache.thumbnail_cache_max_size_mb` both default to 10 GB, and
the base cache PVC (`immich-memories-cache`, 20Gi) is sized to hold both defaults plus
`config.yaml`, `store.db` and automation history. `config-map.yaml` raises both caps to 30 GB for a
bigger library, so `pvc-maximalist.yaml` raises the PVC to 80Gi to match. Raise the caps and forget
the PVC, and the cache evicts every run's previews before the next one reads them, back to
re-downloading and re-captioning what a bigger cap was meant to keep. Lower the caps instead if the
PVC has to stay smaller.

### Another namespace

`overlays/maximalist` adds two resources of its own (`config-map.yaml`, `maximalist-secret.yaml`)
beside the ones inherited through `render-sidecar` and `captioner-cuda`. Renaming the namespace
needs one more line in the loop [Kubernetes](./kubernetes.md#another-namespace) already gives:

```bash
(cd deploy/kubernetes/overlays/maximalist && kustomize edit set namespace photos-memories)
```

## Docker Compose

`docker-compose.maximalist.yml` is an override, applied on top of `docker-compose.yml`:

```bash
CAPTIONER_TAG=server-cuda INFERENCE_TAG=latest-cuda \
  docker compose -f docker-compose.yml -f docker-compose.maximalist.yml \
  --profile captioner --profile inference --profile postgres up -d
```

The CUDA captioner and CUDA inference service are already profiles in `docker-compose.yml` with a
commented `reservations.devices` block each; this override does not restate them, only sets the
tags. The store on PostgreSQL needs the `postgres` service in `docker-compose.yml` uncommented
first, same as its own comments say. What the override adds on top: OIDC env vars (with
`AUTH__TRUSTED_PROXIES` as the reverse-proxy container's compose-network address, not a subnet (a
single host has no pod CIDR), an LLM and ACE-Step base URL pointing at a LAN machine, geocoding and
map tiles on, and the same raised cache caps as the Kubernetes overlay.

A single-host compose deployment has no ConfigMap permission problem: `config.yaml` on the host
filesystem, bind-mounted in, already has whatever mode you set with `chmod` before `docker compose
up`. The `install-config` init-container pattern above is Kubernetes-only for that reason.

## An LLM and ACE-Step on the LAN

Both point at any OpenAI-compatible endpoint reachable from wherever the app runs, most often an
Apple Silicon Mac serving `mlx-vlm` or `mlx-audio` on `0.0.0.0` instead of `localhost`, so another
host on the network can reach it:

```yaml
advanced:
  llm:
    provider: openai-compatible
    base_url: http://192.168.1.50:8000/v1
    model: qwen3-vl-30b-a3b-instruct
  ace_step:
    enabled: true
    mode: api
    api_url: http://192.168.1.50:8001
```

`ace_step.mode: api` talks to an ACE-Step 1.5 API server (`acestep-api`: `POST /release_task`,
`GET /query_result`) rather than importing the library in-process, so the Mac's own MLX/MPS
backend does the generation and the app container needs no GPU for music. The XL variant
(`acestep-v15-xl-turbo`) wants at least 12 GB of VRAM upstream; the default 2B `turbo`/`base`
family runs on less. See [Add a reader](../better/reader.md) for the vision-model side and
[Music](../better/music.md) for ACE-Step's other settings.
