---
title: Inference service deployment and API
---

# Inference service deployment and API

On Basic the app runs the DINOv2 encoder and its eight heads in its own process, on the
CPU, once per picture. GPU and Full also enable Marqo and Docling. The inference service moves
the active producers to another machine:
a GPU box, a Kubernetes node, or just a container you can restart on its own. The facts are the
same rows either way, so you can add it, move it or drop it without re-deriving anything.

For NVIDIA, use the [one-GPU setup](../run/reference-setup.md#one-gpu-service) to serve classifiers,
SmolVLM captions, Demucs and rendering in one container. The ordinary inference entry point
serves classifiers and stems only. Its Compose and Kubernetes recipes below remain separate
from caption and render services.

Both modes use port 8092. In unified mode, captions are under `/v1` and authenticated rendering
under `/render`. In standalone mode, a separate caption server needs its own host port; shipped
Compose publishes it on 8094.

Picture previews and full music tracks reach inference. Unified rendering also receives your
Immich API key. Only `/render` authenticates requests: keep the listener private. ACE-Step and
the text reader are not served here; Laya remains in the app process.

## Unified worker admission and memory

The CUDA image's default command is still `python -m immich_memories_inference`. To start all
four services, use `python -m immich_memories_inference.gpu_worker` through the shipped
`services/inference/compose.gpu-worker.yaml` recipe. It requires the shared render token, the
app's Immich URL and a scratch directory; [the setup guide](../run/reference-setup.md#one-gpu-service)
shows the environment and app settings.

Requests acquire a classifier, caption or audio phase. A different active phase returns HTTP
503 with `Retry-After: 1`. Render work waits up to 60 seconds for model work, then owns the GPU;
model requests are refused while it is preparing or rendering. Cancellation does not release
active native work before that work finishes. This is phase admission, not one global FIFO.

Before a phase change, the worker unloads classifiers when leaving facts and stops its caption
child when leaving captions. Demucs releases after its response. The next caption request
restarts the child, which listens only on loopback inside the container. Render authentication
headers are not forwarded to it.

The bundled caption command sets context to 8192 tokens but does not explicitly set a RAM
prompt-cache limit or processing-slot count. Phase changes reduce overlapping model residency;
they do not impose a hard host-RAM or VRAM budget. The Compose recipe has no RAM limit. Other
containers and external readers/music backends can still consume the same card.

## Verify the rendering runtime

For the unified worker, keep the `/render` suffix in `render.worker_base_url`. Check
`http://WORKER:8092/render/health` for render readiness; `/health` checks inference and does
not establish that the render route has the expected contract or acceleration support.

Use the app and worker images from the same release. When developing with source mounted over
an older image, install that source revision's declared dependencies too. A source copy does
not update its Python environment. Older custom images may lack `pi-heif`: inference succeeds,
then remote assembly rejects HEIC photos.

Before a long run with a custom image, check `import pi_heif` in the worker's Python environment
and decode a representative HEIC source. A successful health response does not exercise every
media decoder.

## The two images

| Tag | Platforms | Provider |
|---|---|---|
| `:X.Y.Z` | `linux/amd64`, `linux/arm64` | CPU |
| `:X.Y.Z-cuda` | `linux/amd64` | CUDA, falling back to CPU |

`openvino`, `armnn` and `rocm` are not shipped. Quick Sync, VAAPI and NVENC decode, scale and
encode; they run no inference.

The CUDA image uses ONNX Runtime GPU for the DINOv2 encoder, Marqo and Docling. The eight
small heads project the encoder output with NumPy. A graph rejected by CUDA falls back to CPU;
the image tag alone does not certify GPU execution.

Use the published release image tag matching your app. The image names are:

```bash
docker pull ghcr.io/sam-dumont/immich-memories/inference:YOUR_APP_TAG
docker pull ghcr.io/sam-dumont/immich-memories/inference:YOUR_APP_TAG-cuda
```

From a checkout, `docker/Dockerfile.inference` builds either one: `--build-arg DEVICE=cpu` or
`DEVICE=cuda`, with `--build-arg APP_VERSION=0+local`.

## Music stems

With `advanced.inference.facts_base_url` set, the app sends generated music to `POST /audio/stems`
and receives a ZIP containing `drums.wav`, `bass.wav`, `other.wav` and `vocals.wav`. The endpoint
accepts one multipart `file`, up to 256 MiB. One separation runs at a time, off the HTTP event
loop: an upload that arrives while another separates gets HTTP 429 with `Retry-After` before its
body is read, and the app falls back as for any failed stem request. Temporary audio is deleted
after the response. Both inference images include Demucs. The CUDA image bundles
its weights; the CPU image downloads them on first use into `/cache/torch`.

`advanced.inference.fallback_to_local` also controls recovery from a failed stem request. Its
default is `true`: the app uses local Demucs if installed. An explicitly enabled MusicGen server
keeps priority for stems. Neither setting changes the ACE-Step generation endpoint.

## Running it with compose

The base file runs Basic. Add the released GPU tier file to start inference and captions:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
curl -s localhost:8092/health
```

For NVIDIA, install the
[NVIDIA container toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
and use Linux driver **570.124.06 or newer** as the recommended baseline for the image's
CUDA 12.8.1 runtime ([NVIDIA driver table](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-toolkit-release-notes/index.html)).
CUDA 12 minor compatibility can run on drivers from 525.60.13, with feature and PTX/JIT limits;
that lower floor does not guarantee this image's kernels work. Newer cards may need a newer
driver. Check that a container sees the card:

```bash
sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi
```

Add the CUDA file; it selects the CUDA images and reserves the device together:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.cuda.yml up -d
curl -s localhost:8092/health
```

Set `IMMICH_MEMORIES_VERSION` once in `.env` for the app and inference image. There is no
separate inference tag. The GPU preset requests GPU; a CPU image does not satisfy its inference
compute check. Change the inference URL in Settings for an existing install, or use the
[setup builder](/setup) for fresh-install defaults that remain editable there.

The app detects remote GPU capability from the top-level `/health` fields `status: "ok"` and
`provider: "CUDAExecutionProvider"`; that probe loads no models and sends no pictures.
`/health` also names the provider per producer, in `producers.heads.providers`,
`producers.nsfw_marqo.providers` and `producers.doc_docling.providers`, each empty until that
producer has loaded. `CPUExecutionProvider` on a GPU host means the image is the CPU one, the
device reservation did not reach the container, `PROVIDER` names `cpu`, or the driver and the CUDA
runtime in the image do not match. Check the tag first: it is the usual one. A graph ONNX Runtime
turns down gets one WARNING naming the seat and the fallback, so the service never serves CPU
answers quietly.

## On Kubernetes

`deploy/kubernetes/overlays/inference` is the service on its own: a Deployment, a ClusterIP Service
on 8092, a 10Gi model-cache PVC and a NetworkPolicy. It does not pull in `base/`, so it needs no
Secret and no Immich, and runs in a cluster where the app does not.

```bash
kubectl create namespace immich-memories                     # base/ creates it too
kubectl apply -k deploy/kubernetes/overlays/inference        # CPU
kubectl apply -k deploy/kubernetes/overlays/inference-cuda   # NVIDIA nodes
```

`inference-cuda` is the same overlay plus one patch: `runtimeClassName: nvidia`, one
`nvidia.com/gpu`, the two `NVIDIA_*` env vars, the `nvidia.com/gpu.present=true` node selector, the
matching toleration and the `-cuda` tag. Each overlay pins its own tag in an `images:` entry; bump
both together and match them to the app version you are deploying.

Port-forward and read the provider back:

```bash
kubectl -n immich-memories port-forward svc/inference 8092:8092
curl -s localhost:8092/health
```

Then [point the app at it](#point-the-app-at-it): `http://inference:8092` in the same namespace,
`http://inference.immich-memories.svc.cluster.local:8092` across namespaces. The base NetworkPolicy
already allows the app egress on 8092.

### A cold cache volume

The CUDA image bundles DINOv2, the context heads, Marqo, Docling, Laya ONNX and the SmolVLM2
caption model and projector. Its weights live in `/opt/immich-models`, outside the writable
cache mount. Downloads are unnecessary at startup; the image sets `HF_HUB_OFFLINE=1`.
The app's CLI can use the same image, with the bundled paths already configured.

For **standalone** inference, a separate caption container can reuse the CUDA image and layers.
The unified worker starts its own child; do not add this container to that setup:

```bash
image=ghcr.io/sam-dumont/immich-memories/inference:YOUR_APP_TAG-cuda
docker run --rm --gpus all -p 127.0.0.1:8094:8092 \
  -v immich-memories-model-cache:/cache \
  "$image" immich-memories-captioner --cache-ram 128 --parallel 1
```

Point `advanced.editorial.preparation.caption_base_url` at `http://localhost:8094/v1` when
running the app on the host. Between containers, use the caption container's hostname and
port 8092. The llama.cpp runtime bundled in the image is pinned by digest; older NVIDIA cards may compile
kernels on their first request. Its bounded JIT cache stays on `/cache` across restarts.
Laya runs in the app process; the `/facts` service serves the image classifiers.

The CPU image keeps its smaller download. A fresh PVC is empty, which is fine. Both overlays
set `ALLOW_MODEL_DOWNLOADS=true`, and the CPU
service then fetches what it is missing on first use: the pinned DINOv2 export (88 MB), the pinned
Marqo export (22.5 MB) and the Docling snapshot. The ONNX exports are checked against the same
SHA-256 `immich-memories models fetch` pins, the Docling snapshot by Hugging Face revision. Only
the first `/facts` call after a cold start waits for it.

For an offline CPU deployment, provision `/cache/dinov2-small.onnx`,
`/cache/nsfw-marqo-384.onnx` and the pinned Docling snapshot under
`/cache/huggingface` before starting the service. Copy the complete Hugging Face
cache, including snapshot metadata. The [model download command](./cli-reference.md#models-fetch)
needs `--detectors` to fetch Marqo and Docling on Basic; its default destination
is not the service's `/cache` volume. Match the service's configured paths when
copying artifacts. With `ALLOW_MODEL_DOWNLOADS=false`, a missing model returns
503 naming the artifact and expected path.

Offline CPU stem separation additionally needs the `htdemucs` Torch checkpoint cache under
`/cache/torch`. `ALLOW_MODEL_DOWNLOADS` controls classifier downloads, not Demucs. Provision
that cache before disconnecting the service, or use the CUDA image with bundled stem weights.

The pod's root filesystem is read-only, so the overlay sets `HF_HOME=/cache/huggingface` and
`TMPDIR=/tmp`. Without them the download has nowhere to put its temporary files, fails with
`Read-only file system (os error 30)`, and every `/facts` request answers 503 until the pod
restarts. Keep both if you write your own manifests.

### Reach the service from outside the cluster

`http://inference:8092` only resolves inside the cluster. For a NAS or a laptop on the LAN,
`overlays/inference-lan` adds a second Service, type LoadBalancer, on the same pods and port. The
ClusterIP Service is untouched, so no in-cluster caller starts riding an external address, and it
composes with either device overlay.

```bash
kubectl apply -k deploy/kubernetes/overlays/inference-lan
kubectl -n immich-memories get service inference-lan
```

Put what that prints in `facts_base_url`. The address comes from the cluster's load-balancer
controller: without one the Service sits at `<pending>` forever. Nothing behind port 8092 checks a
credential, so do not give it a routable address, and
`kubectl delete -k deploy/kubernetes/overlays/inference-lan` when you are done.

## What it answers

| Endpoint | Question |
|---|---|
| `GET /ping` | are you up |
| `GET /health` | which producers are loaded, at which versions, on which provider each |
| `GET /queue` | waiting and active classifier work, completions, failures and timings |
| `POST /facts` | one picture in: what do the frozen classifiers say about it |

```bash
python3 -c 'import base64,json,sys; print(json.dumps({"image": base64.b64encode(open(sys.argv[1],"rb").read()).decode(), "producers": ["heads"]}))' photo.jpg \
  | curl -s localhost:8092/facts -H 'content-type: application/json' --data-binary @-
```

```json
{"producers": {"heads": {"encoder_key": "…", "facts": [
  {"head": "activity", "version": "public-v1", "label": "outdoors", "confidence": 0.71}]}}}
```

When a producer cannot load, `/facts` answers 503 with the reason in `detail`: which producer,
which artifact, which path. The app repeats that as `Remote classifiers returned HTTP 503:
<detail>`, and the service logs it once per distinct message rather than once per picture. A failed
load is retried on a later request, backing off from 10 s to 2 minutes, so fixing the cause needs
no restart.

A fact on the wire is the bank row without its asset id, and the client stores it verbatim:
**a fact's identity is the artifact that produced it, never the machine that ran it.** No URL,
hostname, device or provider name enters any key, so the same picture through the `cpu` and the
`cuda` image lands on one row, label-identical rather than byte-identical.

## Watching classifier work

```bash
curl -s localhost:8092/queue
```

The response reports `queued`, `active`, `completed`, `failed`, `cancelled` and `rejected`
for each producer, plus `oldest_wait_seconds`, `mean_wait_seconds`, `mean_run_seconds` and
`completed_per_second`. Counts and averages cover this service process since startup;
throughput includes idle time. Waiting time includes admission to the shared worker pool.
Model loading counts as run time. The response contains no pictures or asset identifiers.

Each model has a FIFO queue. Waiting callers yield the worker so another model can run.
At most `REQUEST_THREADS` model calls run at once, with one active call per model. The service
accepts 32 waiting calls across the classifier queues by default. A full queue returns
HTTP 429 with `Retry-After: 1`; callers should reduce concurrency and retry later. The app's
configured local fallback still applies if the request fails. Cancelling a waiting call removes
it; cancelling active native work keeps its worker reserved until that work finishes.

These queues cover `/facts`, in both entry points. Standalone Demucs has its own serial
scheduling. Unified mode adds phase admission across facts, captions, audio and rendering;
`/queue` does not report those other phases. Separate caption servers based on llama.cpp can
expose slots and metrics when their server settings enable them.

## Request limits

The service checks each request's size before reading its body:

| Route | Largest body | Over the limit |
|---|---|---|
| `POST /facts` | the base64 of `MAX_IMAGE_BYTES` (about 21 MiB by default), plus 1 MiB of JSON | HTTP 413 |
| `POST /audio/stems` | 256 MiB of audio, plus 1 MiB of multipart envelope | HTTP 413 |

A declared `Content-Length` over the limit is refused unread. A body that runs past it, declared
or not, is cut off with the same 413. `/facts` holds at most `REQUEST_THREADS` plus
`MAX_QUEUED_REQUESTS` bodies at once; one more gets HTTP 429 with `Retry-After`.

A picture whose header asks for more than 50 million pixels gets HTTP 413 naming its pixel count,
before it is decoded. The file size says little here: a few kilobytes of PNG can decode to
gigabytes.

## Settings

Every setting is an environment variable prefixed `IMMICH_MEMORIES_INFERENCE_`:

| Variable | Default | What it does |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8092` | where to listen. The image sets the host to `0.0.0.0` |
| `CACHE_DIR` | `/cache` | the model cache volume |
| `ENCODER` | `$CACHE_DIR/dinov2-small.onnx` | the pinned DINOv2 export, digest-verified on load |
| `MARQO_ONNX` | `$CACHE_DIR/nsfw-marqo-384.onnx` | the pinned sensitive-content ONNX export |
| `BUNDLE` | the packaged public bundle | head bundle `.npz` |
| `PROVIDER` | `auto` | `auto`, `cpu`, `cuda` or `coreml`. `auto` takes CUDA where the provider is present and CPU otherwise. CoreML is selectable; Linux images use CPU or CUDA |
| `REQUEST_THREADS` | `4` | the thread pool in front of ONNX Runtime. The app's `facts_concurrency` is what fills it |
| `MAX_QUEUED_REQUESTS` | `32` | maximum waiting calls across classifier queues; excess requests get HTTP 429 |
| `IDLE_UNLOAD_SECONDS` | `300` | drop idle weights; `0` holds them |
| `PRELOAD` | `false` | load every producer at boot instead of on first use |
| `DETECTOR_CACHE_DIR` | unset in the runtime; `/opt/immich-models/huggingface` in the CUDA image | where the detector snapshots live; unset uses the Hugging Face cache, with `HF_HOME=/cache/huggingface` in the CPU image |
| `ALLOW_MODEL_DOWNLOADS` | `false` | let a cold cache fetch the pinned exports and the Docling snapshot itself |
| `MAX_IMAGE_BYTES` | `16777216` | refuse a decoded picture larger than this, and size the `/facts` body limit from it |

The CUDA image sets `OPENBLAS_NUM_THREADS=1` for NumPy's small per-picture head projection.
This limits NumPy's BLAS worker pool, which otherwise can compete for a container's CPU quota.
`REQUEST_THREADS` independently controls classifier request concurrency. Measure under your
actual CPU and memory limits before overriding either setting.

Idle unload drops the weights and **keeps the process**: the next request reloads them. Changing
the provider re-keys nothing, so any of this can be retried without re-deriving a fact.

## Point the app at it

Use the [app connection and health checks](../better/inference.md#classifiers-and-stems-only). The [configuration reference](./config-reference.md#inference-service) lists timeout, concurrency and fallback settings.
