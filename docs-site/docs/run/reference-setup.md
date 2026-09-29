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
gpu-node-a (the newer card, time-sliced)           one machine, everything local
├── immich-memories pod
│   ├── app container                              immich-memories ui
│   └── render-worker (sidecar, loopback :8093)     ├── oMLX: gemma-4-e4b-it-6bit
└── inference service (encoder, heads,               │   (OpenAI-compatible, :9999)
    detectors; ONNX Runtime CUDA, :8092)             ├── mlxcel: SmolVLM caption
                                                     │   server (:8092, localhost)
gpu-node-b (a second, older card)                   └── ACE-Step 1.5, lib mode
└── captioner (llama.cpp server-cuda, :8092)             (XL turbo, bf16, 4B LM)

Traefik (TLS) ── OIDC (Auth0) ── the app            OIDC to the same IdP
the reader (LLM): an OpenAI-compatible server on the LAN, e.g. oMLX on the Mac
```

The server profile is the app's Deployment plus two GPU services, reached through
[`deploy/kubernetes/overlays/maximalist`](https://github.com/sam-dumont/immich-video-memory-generator/tree/main/deploy/kubernetes/overlays/maximalist)
or [`deploy/terraform/examples/maximalist`](https://github.com/sam-dumont/immich-video-memory-generator/tree/main/deploy/terraform/examples/maximalist).
The Mac profile is a source checkout with ACE-Step installed beside it, plus two local servers
(the reader and the caption server): see [Generated music](../better/music.md#install-locally-on-a-mac)
and [Add a reader](../better/reader.md).

## Feature → where it runs → config keys → hardware

| Feature | Where it runs | Config keys | Hardware |
|---|---|---|---|
| App + UI | the Kubernetes pod, or the Mac directly | `tier: full` | any CPU |
| Render worker | sidecar in the app pod, loopback | `render.worker_base_url`, `render.worker_token` | `gpu-node-a`: NVENC h264/hevc |
| Picture reading (inference service) | its own pod, on the newer card | `advanced.inference.facts_base_url` | `gpu-node-a`: ONNX Runtime on CUDA; without it, the app pod's CPU |
| Caption server | a second GPU node, cluster-only | `advanced.editorial.preparation.caption_base_url` | `gpu-node-b`: a Pascal card works (`sm_61`) |
| Caption server (Mac) | mlxcel, localhost | same key, `http://localhost:8092/v1` | Apple Silicon, Metal |
| Reader (LLM) | the Mac, on the LAN | `advanced.llm.base_url`, `advanced.llm.provider`, `advanced.llm.model` | Apple Silicon running oMLX |
| Music | ACE-Step 1.5 API (cluster) or lib mode (Mac) | `advanced.ace_step.mode`, `advanced.ace_step.api_url` | cluster: any card; Mac: Apple Silicon, XL wants more RAM |
| Music stems | Demucs in the inference service | `advanced.inference.facts_base_url` | inference: CUDA or CPU; app/render fallback: CPU; Mac fallback: Metal |
| OIDC behind a proxy | the reverse proxy + the app | `advanced.auth.public_url`, `advanced.auth.trusted_proxies`, `advanced.server.secure_cookies` | none |
| Geocoding + map tiles | `nominatim.openstreetmap.org`, `server.arcgisonline.com` | `network.geocoding`, `network.map_tiles` | none |
| Cache caps | the cache PVC / local disk | `cache.video_cache_max_size_gb`, `cache.thumbnail_cache_max_size_mb` | sized storage |
| Automation | in-process timer, or a CronJob to `/api/trigger` | `advanced.automation.enabled`, `advanced.automation.daily_at` | none |

Missing a piece from this table: drop the row and set `tier` to match, because a named tier never
steps down on its own. `tier: full` refuses to load without `advanced.llm.base_url` and
`advanced.llm.model`, and still asks for captions when no caption server answers; `tier: auto` picks
`gpu` or `full` only once it finds GPU picture reading (a local CUDA runtime or the inference
service), so without one it stays on the plain NAS tier. No ACE-Step means a bundled track. Without
the inference service the app reads pictures on its own CPU: the same answers, a slower first cut.

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
`base`), `overlays/captioner-cuda` and `overlays/inference-cuda`, rather than duplicating any of
them. It keeps the base's 20Gi
cache PVC, so it applies over an existing install. On top: a second init container that installs `config.yaml`,
`IMMICH_MEMORIES_TIER=full` on the app container (the base sets `auto`, and an env var beats
`config.yaml`), and a NetworkPolicy that lets the app reach the LLM and ACE-Step ports. Read
[Kubernetes](./kubernetes.md) first for the base layout this builds on.

### Check the tier it really runs

The tier in the file and the tier the pod runs can differ: the environment wins over
`config.yaml`, and the base Deployment sets `IMMICH_MEMORIES_TIER=auto`. Ask the app, before and
after any change:

```bash
kubectl -n immich-memories exec deploy/immich-memories -c immich-memories -- \
  immich-memories config show | grep '│ tier'
```

The row names the tier and where it came from. `full` from `env` is this setup. `nas` from `env`
means the pod has been cutting on the plain NAS tier, the caption server and the reader never
asked; the log line above the table says why (`Automatic selection tier: nas. ...`).

### The cluster's config.yaml, annotated

The full file `overlays/maximalist/config-map.yaml` ships, redacted of anything that is a
credential (those come from `maximalist-secret.yaml` and expand with `${VAR}`):

```yaml
tier: full

network:
  geocoding: true    # nominatim.openstreetmap.org: place names, trip names
  map_tiles: true    # server.arcgisonline.com: the trip fly-over, location cards

cache:
  video_cache_max_size_gb: 5        # well inside the base's 20Gi cache PVC; a bigger
  thumbnail_cache_max_size_mb: 3000 # library raises both, and the PVC first

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

  inference:
    facts_base_url: "http://inference:8092"   # gpu-node-a, ONNX Runtime on CUDA

  llm:
    provider: "openai-compatible"
    base_url: "http://192.168.1.50:9999/v1"   # oMLX on the Mac, LAN
    model: "gemma-4-e4b-it-6bit"
    api_key: "${LLM_API_KEY}"

  ace_step:
    enabled: true
    mode: api
    api_url: "http://acestep-api:8001"   # an ACE-Step 1.5 API server, not in the overlay
    api_key: "${ACE_STEP_API_KEY}"

  automation:
    enabled: true
    daily_at: "09:00"
```

### Music stems

ACE-Step generates the full track in its separate deployment. Demucs in the inference service
splits it into drums, bass, other and vocals for separate ducking under the clips. The existing
`advanced.inference.facts_base_url` also selects `/audio/stems`. This setup needs ACE-Step and
Demucs; a MusicGen server is optional and is not deployed by this repository.

The inference CUDA image includes the 80 MB `htdemucs` weights under `/opt/immich-models/torch`.
The CPU inference image downloads them on first separation into `/cache/torch`; keep `/cache`
on the model-cache PVC. Jobs run one at a time and their temporary audio files are removed after
the response is sent. ACE-Step keeps its own image, models and Terraform deployment.
On NVIDIA cards without BF16 support, its Oobleck VAE needs FP32 through CPU offload/reload:
FP16 can produce NaNs and silent tracks. The [ACE-Step image patch](https://github.com/sam-dumont/ace-step-1.5#vae-precision-on-older-nvidia-cards)
sets that precision in the VAE selector. Deploy the rebuilt image digest; this upstream selector
does not read `ACESTEP_DTYPE`.

If the service fails, `advanced.inference.fallback_to_local` (default `true`) allows local Demucs.
The app and render-worker image includes it on CPU; the Mac uses Metal. Local separation caches
weights under `~/.cache/torch/hub/checkpoints`. Set `TORCH_HOME` to a persistent cache directory
to reuse them after a container restart. With no inference URL, local separation remains the default.
An explicitly enabled MusicGen server retains priority for stems for existing installations.

The app image takes both Torch and TorchAudio from the CPU wheel index. The inference images
pin matching CPU or CUDA 12.8 wheels. Every image checks the real Demucs model-loader import at
build time, catching missing native libraries before release.

### The two GPU nodes

`gpu-node-a` has the newer card, here an NVIDIA T1000 (Turing, 8 GB), time-sliced with Immich's
own machine-learning pod. It carries the app pod with the render worker as a loopback sidecar
(NVENC h264/hevc, exec probes, below) and the inference service, which reads every picture once:
the encoder, the context heads and the two detectors, on ONNX Runtime's CUDA provider.
`gpu-node-b` has an older GTX 1070 (Pascal, 8 GB) and carries only the caption server: llama.cpp's
CUDA build runs on Pascal, and the caption server is the one GPU workload that doesn't compete
with the app for the busier card.

`overlays/inference-cuda` and `overlays/captioner-cuda` select any node with
`nvidia.com/gpu.present`, so on a two-card cluster pin each to its node. The inference service
belongs on the newer card; this setup was not tested with it on Pascal:

```yaml
# a patch in overlays/maximalist, listed under patches:
apiVersion: apps/v1
kind: Deployment
metadata:
  name: immich-memories-inference
  namespace: immich-memories
spec:
  template:
    spec:
      nodeSelector:
        kubernetes.io/hostname: gpu-node-a   # your newer card's node
```

### Gotchas, with the exact strings to search for

**OIDC, unpinned `public_url`.** Without `auth.public_url` the `redirect_uri` sent to the IdP is
built from the in-cluster request and comes out `http://`, which every IdP refuses before the app
ever sees the callback.

**OIDC, untrusted proxy.** With `public_url` set but no `auth.trusted_proxies`,
`X-Forwarded-Proto` from Traefik is not trusted, so the callback still looks like plain HTTP and
comes back:

```
400 {"detail":"Invalid callback origin"}
```

`trusted_proxies` is the pod CIDR your CNI hands out, IPv4 and IPv6.

**`enableServiceLinks` left on.** Kubernetes injects a set of env vars for every Service in the
namespace by default, and this app's own `IMMICH_MEMORIES_*` prefix collides with its own Service
names. A Service named `immich-memories-render-worker` injects
`IMMICH_MEMORIES_RENDER_WORKER_PORT=tcp://10.x.x.x:8093`, which the worker's settings then read as
its own `port` field and crash on (pydantic's validation error):

```
port
  Input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='tcp://…:8093', input_type=str]
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
refetch, so on a storage class that works this way, patch the caption server's `models` volume to
an `emptyDir` in place of the `immich-memories-caption-models` claim `overlays/captioner` ships.
The cache, output and models PVCs the app itself needs still want real storage.

**`tier: full` in the file, `nas` in the pod.** The base Deployment's `IMMICH_MEMORIES_TIER=auto`
beats `config.yaml`, and `auto` stays on the plain NAS tier until it finds GPU picture reading.
Nothing fails: films still render, from the rules alone, and the caption server and the reader
simply never get a request. Search the log for `Automatic selection tier: nas`, and check with
`config show` as above. The overlay sets the tier in the environment for this reason.

**Which card gets what.** llama.cpp's CUDA build runs on Pascal (`sm_61`); PyTorch's cu128 wheels
no longer do. Put the caption server on the older card, and the inference service and the render
worker on the newer one.

**MTU on a multi-site cluster.** A cluster spanning two sites over VXLAN loses bytes to the tunnel
header; Cilium's default MTU assumes a 1500-byte path that isn't there. Symptoms are intermittent:
large responses (a picture upload, a chat completion from the LAN LLM) stall or hang while small
ones work. Set the CNI's MTU to match the tunnel's real ceiling, e.g. 1370 for a ~1420-byte path,
rather than discovering it one timeout at a time.

## The laptop / workstation (the Mac)

Nothing above needs a second machine or a cluster; this profile runs the same app, the same
config keys, entirely on one Mac, with two local servers instead of a cluster. `lib` mode is not in
`uv tool install` or the `all-mac` extra: ACE-Step runs from a `.venv-acestep` beside a checkout
([Install locally on a Mac](../better/music.md#install-locally-on-a-mac)). OIDC needs `authlib`,
which `all-mac` and `make dev-mac` leave out; `make dev` installs every extra and builds the web
client (it needs Node 22):

```bash
git clone https://github.com/sam-dumont/immich-video-memory-generator.git
cd immich-video-memory-generator
make dev
make install-acestep
uv run immich-memories ui
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
      # mlxcel, serving the same SmolVLM2 alias as the llama.cpp recipe
      caption_base_url: "http://localhost:8092/v1"

  llm:
    provider: "openai-compatible"
    base_url: "http://localhost:9999/v1"   # oMLX, also the cluster's reader over the LAN
    model: "gemma-4-e4b-it-6bit"

  ace_step:
    enabled: true
    mode: lib                        # a local library, not an API server
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
above as a module variable, defaulting to the minimal path (off) until set, except the tier,
automation and the inference service's URL, which go through `env`. The module does not deploy the
inference service: apply `deploy/kubernetes/overlays/inference-cuda` beside it. See
[`deploy/terraform/README.md`](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/deploy/terraform/README.md#the-maximalist-example).
