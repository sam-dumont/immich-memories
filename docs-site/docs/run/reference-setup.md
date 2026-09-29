---
title: The reference setup
---

# The reference setup

Two machines, every optional piece turned on: a Kubernetes cluster that runs the film-making
pipeline around the clock, and a Mac that runs the same app locally with nothing else around it.
Written up from a real deployment. Most installs want a fraction of this: read [What a GPU or a
model adds](../get-started/what-a-gpu-or-a-model-adds.md) first, and come back here for the pieces
worth adding.

Placeholders throughout: `photos.example.com`, `192.168.1.50`, `gpu-node-a`, `idp.example.com`.
Nothing on this page is a real hostname, IP or node name.

## The two profiles

```
Always-on server (Kubernetes)                    Laptop / workstation (the Mac)
──────────────────────────────                    ──────────────────────────────
gpu-node-a (NVENC + Immich ML, time-sliced)        one machine, everything local
├── immich-memories pod
│   ├── app container                              immich-memories ui
│   └── render-worker (sidecar, loopback :8093)     ├── oMLX: gemma-4-e4b-it-6bit
│                                                    │   (OpenAI-compatible, :9999)
gpu-node-b (a second, older card)                   ├── mlxcel: SmolVLM caption
└── captioner (llama.cpp server-cuda, :8092)         │   server (:8092, localhost)
                                                     └── ACE-Step 1.5, lib mode
Traefik (TLS) ── OIDC (Auth0) ── the app                 (XL turbo, bf16, 4B LM)
                                                    OIDC to the same IdP
```

The server profile is a Deployment plus two single-purpose GPU workloads, reached through
[`deploy/kubernetes/overlays/maximalist`](https://github.com/sam-dumont/immich-video-memory-generator/tree/main/deploy/kubernetes/overlays/maximalist)
or [`deploy/terraform/examples/maximalist`](https://github.com/sam-dumont/immich-video-memory-generator/tree/main/deploy/terraform/examples/maximalist).
The Mac profile is a single `uv tool install`, with three local servers instead of Python
dependencies: see [pip / uv](./uv-pip.md) and [Add a reader](../better/reader.md).

## Feature → where it runs → config keys → hardware

| Feature | Where it runs | Config keys | Hardware |
|---|---|---|---|
| App + UI | the Kubernetes pod, or the Mac directly | `tier: full` | any CPU |
| Render worker | sidecar in the app pod, loopback | `render.worker_base_url`, `render.worker_token` | `gpu-node-a`: NVENC h264/hevc |
| Caption server | a second GPU node, cluster-only | `advanced.editorial.preparation.caption_base_url` | `gpu-node-b`: a Pascal card works (`sm_61`) |
| Caption server (Mac) | mlxcel, localhost | same key, `http://localhost:8092/v1` | Apple Silicon, Metal |
| Reader (LLM) | the Mac, on the LAN | `advanced.llm.base_url`, `advanced.llm.provider`, `advanced.llm.model` | Apple Silicon running oMLX |
| Music | ACE-Step 1.5 API (cluster) or lib mode (Mac) | `advanced.ace_step.mode`, `advanced.ace_step.api_url` | cluster: any card; Mac: Apple Silicon, XL wants more RAM |
| OIDC behind a proxy | the reverse proxy + the app | `advanced.auth.public_url`, `advanced.auth.trusted_proxies`, `advanced.server.secure_cookies` | none |
| Geocoding + map tiles | `nominatim.openstreetmap.org`, `server.arcgisonline.com` | `network.geocoding`, `network.map_tiles` | none |
| Cache caps | the cache PVC / local disk | `cache.video_cache_max_size_gb`, `cache.thumbnail_cache_max_size_mb` | sized storage |
| Automation | in-process timer, or a CronJob to `/api/trigger` | `advanced.automation.enabled`, `advanced.automation.daily_at` | none |

Missing a piece from this table: drop just that row and the app still runs. No caption server
falls back a tier; no reader keeps the rules-based editor; no ACE-Step turns music off.

## The always-on server (Kubernetes)

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
`base`) and `overlays/captioner-cuda`, rather than duplicating either. Two patches on top: a bigger
cache PVC, and a third init container that installs `config.yaml`. Read [Kubernetes](./kubernetes.md)
first for the base layout this builds on.

### The cluster's config.yaml, annotated

The full file `overlays/maximalist/config-map.yaml` ships, redacted of anything that is a
credential (those come from `maximalist-secret.yaml` and expand with `${VAR}`):

```yaml
tier: full

network:
  geocoding: true    # nominatim.openstreetmap.org: place names, trip names
  map_tiles: true    # server.arcgisonline.com: the trip fly-over, location cards

cache:
  video_cache_max_size_gb: 5        # sized to a 10Gi cache PVC, not the 30 GB a
  thumbnail_cache_max_size_mb: 3000 # bigger library would want

advanced:
  auth:
    enabled: true
    provider: oidc                         # Auth0, behind Traefik terminating TLS
    public_url: "https://memories.example.com"
    trusted_proxies:
      - "10.42.0.0/16"   # the cluster's pod CIDR, v4
      - "fd42::/48"      # and v6
    issuer_url: "${OIDC_ISSUER_URL}"
    client_id: "${OIDC_CLIENT_ID}"
    client_secret: "${OIDC_CLIENT_SECRET}"
    allowed_emails:
      - "you@example.com"

  server:
    secure_cookies: true

  editorial:
    preparation:
      caption_base_url: "http://captioner:8092/v1"   # gpu-node-b, server-cuda

  llm:
    provider: "openai-compatible"
    base_url: "http://192.168.1.50:9999/v1"   # oMLX on the Mac, LAN
    model: "gemma-4-e4b-it-6bit"
    api_key: "${LLM_API_KEY}"

  ace_step:
    enabled: true
    mode: api
    api_url: "http://acestep-api:8001"   # in-cluster: ACE-Step 1.5, 1.7B turbo
    api_key: "${ACE_STEP_API_KEY}"

  automation:
    enabled: true
    daily_at: "09:00"
```

### The two GPU nodes

`gpu-node-a` carries the app pod, with the render worker as a loopback sidecar: an NVIDIA T1000
(Turing, 8 GB), time-sliced with Immich's own machine-learning pod and whatever else lands there.
NVENC h264/hevc for the render, exec probes for the worker (below). `gpu-node-b` carries only the
caption server: an older GTX 1070 (Pascal, 8 GB) that PyTorch's cu128 wheels have already dropped
support for, but llama.cpp's CUDA build still runs on. Splitting them this way means the caption
server never competes with the app for the busier card, and a card too old for the CUDA inference
service still earns its keep.

### Gotchas, with the exact strings to search for

**OIDC, unpinned `public_url`.** Without `auth.public_url` the `redirect_uri` sent to the IdP is
built from the in-cluster request and comes out `http://`, which every IdP refuses before the app
ever sees the callback.

**OIDC, untrusted proxy.** With `public_url` set but no `auth.trusted_proxies`,
`X-Forwarded-Proto` from Traefik is not trusted, so the callback still looks like plain HTTP and
comes back:

```
400 {"detail": "Invalid callback origin"}
```

`trusted_proxies` is the pod CIDR your CNI hands out, IPv4 and IPv6.

**`enableServiceLinks` left on.** Kubernetes injects one env var per Service in the namespace by
default, and this app's own `IMMICH_MEMORIES_*` prefix collides with its own Service names. A
Service named `immich-memories-render-worker` injects
`IMMICH_MEMORIES_RENDER_WORKER_PORT=tcp://10.x.x.x:8093`, which the worker's settings then read as
its own `port` field and crash on:

```
port: Input should be a valid integer, unable to parse string as an integer [input_value='tcp://…:8093']
```

Every manifest here sets `enableServiceLinks: false` for exactly this reason (#1608); copy it onto
any pod spec you write yourself.

**A `tcpSocket`/`httpGet` probe on a loopback-only worker.** The kubelet dials the pod IP for both
of those, never `127.0.0.1`: a process inside the container makes no difference. The render
worker binds loopback only, so either probe kind fails forever and the pod never goes Ready. The
sidecar's `startupProbe`/`readinessProbe` run `exec` instead, inside the worker's own network
namespace, where loopback is reachable.

**A PVC that never binds.** A storage class provisioning only static, pre-created PVs (no dynamic
provisioner, `volumeBindingMode: Immediate`) leaves a fresh PVC `Pending` forever if no PV happens
to match it. The caption weights are the case that bites here: they are pinned artifacts, cheap to
refetch, so `overlays/captioner-cuda` gets away with an `emptyDir` model cache instead of a claim
when the cluster's storage class works this way. The cache, output and models PVCs the app itself
needs still want real storage.

**`sm_61` vs PyTorch cu128.** Covered above: llama.cpp's CUDA build runs on Pascal, PyTorch's
cu128 wheels do not. Put the caption server, not the inference service, on the older card.

**MTU on a multi-site cluster.** A cluster spanning two sites over VXLAN loses bytes to the tunnel
header; Cilium's default MTU assumes a 1500-byte path that isn't there. Symptoms are intermittent:
large responses (a picture upload, a chat completion from the LAN LLM) stall or hang while small
ones work. Set the CNI's MTU to match the tunnel's real ceiling, e.g. 1370 for a ~1420-byte path,
rather than discovering it one timeout at a time.

## The laptop / workstation (the Mac)

Nothing above needs a second machine or a cluster; this profile runs the same app, the same
config keys, entirely on one Mac. Install with the `all-mac` extra
([Hardware](./hardware.md#apple-silicon)), then three local servers instead of a cluster:

```bash
uv tool install "immich-memories[all-mac]"
```

### The Mac's config.yaml, annotated

Every key below is valid on current `main`; nothing here is exotic or Tier-2-only by accident.

```yaml
tier: full

network:
  geocoding: true
  map_tiles: true

cache:
  video_cache_max_size_gb: 10
  thumbnail_cache_max_size_mb: 10000

advanced:
  auth:
    enabled: true
    provider: oidc          # the same IdP as the cluster profile
    issuer_url: "${OIDC_ISSUER_URL}"
    client_id: "${OIDC_CLIENT_ID}"
    client_secret: "${OIDC_CLIENT_SECRET}"

  editorial:
    preparation:
      # mlxcel: llama.cpp's SmolVLM2 alias, served locally
      caption_base_url: "http://localhost:8092/v1"

  llm:
    provider: "openai-compatible"
    base_url: "http://localhost:9999/v1"   # oMLX, bound to this machine only
    model: "gemma-4-e4b-it-6bit"

  ace_step:
    enabled: true
    mode: lib                        # in-process, not an API server
    model_variant: "acestep-v15-xl-turbo"   # the XL variant
    lm_model_size: "4B"
    use_lm: true
```

`mode: lib` needs Python 3.12 specifically ([ACE-Step config reference](../reference/config-reference.md));
`mode: api` (the cluster profile's choice) has no such constraint, which is why the two profiles
differ here. Running `oidc` against `issuer_url` alone, with no `public_url`, is fine on a
single-user machine reached only at `localhost`: nothing forwards a proxied `Host` header for
`trusted_proxies` to matter, so the origin check in
[Authentication](./authentication.mdx#oidc--sso) has nothing to second-guess.

## Terraform

`deploy/terraform/examples/maximalist` is the Terraform form of the server profile: every feature
above as a module variable, defaulting to the minimal path (off) until set. See
[`deploy/terraform/README.md`](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/deploy/terraform/README.md#the-maximalist-example).
