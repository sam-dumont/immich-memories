---
title: Inference service deployment and API
---

# Inference service deployment and API

On Basic the app runs the DINOv2 encoder in its own process, on the CPU, once per picture: that
one pass feeds the eight context heads and the finger-over-the-lens check. GPU and Full add Marqo
and Docling. The inference service moves those producers to another machine: a GPU box, a
Kubernetes node, or a container you can restart on its own. The facts are the same rows either
way, so you can add it, move it or drop it without re-deriving anything.

It runs two ways, both on port 8092:

| Mode | Serves | Recipe |
|---|---|---|
| Standalone | classifiers (`/facts`) and music stems | Compose and Kubernetes recipes below; captions run in their own server, published on host port 8094 by the shipped Compose files |
| Unified worker | classifiers, stems, SmolVLM captions under `/v1` and rendering under `/render` | [one-GPU setup](../run/reference-setup.md#one-gpu-service), NVIDIA only |

Picture previews and whole music tracks reach the service, and the unified worker's render route
also receives your Immich API key. Only `/render` checks a token, so keep the listener private.
ACE-Step and the text reader are not served here; Laya stays in the app process.

## Unified worker admission and memory

The CUDA image's default command is `python -m immich_memories_inference` (standalone). To
start all four services, use `python -m immich_memories_inference.gpu_worker` through the shipped
`services/inference/compose.gpu-worker.yaml` recipe. It requires the shared render token, the
app's Immich URL and a scratch directory; [the setup guide](../run/reference-setup.md#one-gpu-service)
shows the environment and app settings.

Each request takes a phase: classifiers, captions or audio. While another phase is active the
worker answers HTTP 503 with `Retry-After: 1`; the app's caption requests wait that out (see
[the caption contract](./caption-service.md#unified-or-separate-service)). Render work waits up to
60 seconds for model work to finish, then owns the GPU, and model requests are refused while it
prepares or renders. Cancelling a request does not stop native work already running.

On a phase change the worker unloads the classifiers when leaving facts and stops its caption
process when leaving captions; Demucs lets go after its response. The next caption request starts
the caption process again, listening only on loopback inside the container. Render
authentication headers are never forwarded to it.

The bundled caption command uses an 8192-token context and a 128 MiB RAM prompt cache
(`LLAMA_ARG_CACHE_RAM` overrides it), with no slot count. Phases keep models from sitting on the
card together; they are not a RAM or VRAM budget. The Compose recipe sets no RAM limit, and other
containers, readers or music servers can still use the same card.

## Verify the rendering runtime

For the unified worker, keep the `/render` suffix in `render.worker_base_url`. Check
`http://WORKER:8092/render/health` for render readiness; `/health` only covers inference.

Use the app and worker images from the same release. If you mount source over an older image,
install that revision's dependencies too: copying source doesn't update the Python environment.
A custom image without `pi-heif` passes inference and then fails remote assembly on HEIC photos,
so check `import pi_heif` in the worker and decode one HEIC before a long run.

## The two images

| Tag | Platforms | Provider |
|---|---|---|
| `:X.Y.Z` | `linux/amd64`, `linux/arm64` | CPU |
| `:X.Y.Z-cuda` | `linux/amd64` | CUDA, falling back to CPU |

There are no `openvino`, `armnn` or `rocm` images. Quick Sync, VAAPI and NVENC handle video
(decode, scale, encode) and run no inference.

The CUDA image runs the DINOv2 encoder, Marqo and Docling on ONNX Runtime GPU; the eight small
heads project the encoder output with NumPy. A graph CUDA rejects falls back to CPU, so read
`/health` rather than trusting the tag.

Use the tag that matches your app release:

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
loop: an upload that arrives during another separation gets HTTP 429 with `Retry-After` before
its body is read, and the app treats it as any failed stem request. Temporary audio is deleted
after the response. Both images include Demucs; the CUDA image bundles its weights and the CPU
image downloads them into `/cache/torch` on first use.

When a stem request fails, `advanced.inference.fallback_to_local` (default `true`) lets the app
use local Demucs if it is installed. An enabled MusicGen server still comes first for stems.
Neither setting touches the ACE-Step generation endpoint.

## Running it with compose

The base file runs Basic. For GPU inference and captions, add the released GPU and CUDA files;
[Compose setup files](./compose-files.md#select-the-files) covers the downloads and keeping the
selection in `.env`. The GPU file alone runs CPU images, useful for diagnosis, and does not pass
the GPU check.

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

`IMMICH_MEMORIES_VERSION` in `.env` sets both the app and the inference image; there is no
separate inference tag. A CPU image does not pass the GPU tier's compute check. Change the
inference URL in Settings, or let the [setup builder](/setup) write defaults you can still edit
there.

The app detects remote GPU capability from the top-level `/health` fields `status: "ok"` and
`provider: "CUDAExecutionProvider"`; that probe loads no models and sends no pictures.
`/health` also names the provider per producer, in `producers.heads.providers`,
`producers.nsfw_marqo.providers`, `producers.doc_docling.providers` and
`producers.obstruction.providers`, each empty until that producer has loaded. The app reads the
producer names there once per run and asks only for the ones the service serves, so a service
older than the app keeps `obstruction` local instead of failing the pass.

`CPUExecutionProvider` on a GPU host means one of four things: the image is the CPU one, the
device reservation didn't reach the container, `PROVIDER` says `cpu`, or the driver doesn't match
the image's CUDA runtime. Check the tag first; it's the usual cause. A graph ONNX Runtime turns
down logs one WARNING naming the seat and the fallback, so CPU answers never pass silently.

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
both together, to the app version you deploy.

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
caption model and projector in `/opt/immich-models`, outside the writable cache mount, and sets
`HF_HUB_OFFLINE=1`: it downloads nothing at startup. The app's CLI can run in the same image with
the bundled paths already configured.

For **standalone** inference, a separate caption container can reuse the CUDA image. The unified
worker starts its own caption process, so don't add this container there:

```bash
image=ghcr.io/sam-dumont/immich-memories/inference:YOUR_APP_TAG-cuda
docker run --rm --gpus all -p 127.0.0.1:8094:8092 \
  -v immich-memories-model-cache:/cache \
  "$image" immich-memories-captioner --cache-ram 128 --parallel 1
```

Point `advanced.editorial.preparation.caption_base_url` at `http://localhost:8094/v1` when
running the app on the host. Between containers, use the caption container's hostname and
port 8092. The bundled llama.cpp runtime is pinned by digest; older NVIDIA cards may compile
kernels on their first request, and that JIT cache stays on `/cache` across restarts.

The CPU image bundles no weights. A fresh PVC is empty, which is fine: both overlays set
`ALLOW_MODEL_DOWNLOADS=true`, and the CPU service fetches what it is missing on first use: the pinned DINOv2 export (88 MB), the pinned
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
ClusterIP Service stays as it is, so in-cluster callers keep the internal address, and it works
with either device overlay.

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

Each model has a FIFO queue, and a waiting caller yields the worker so another model can run.
At most `REQUEST_THREADS` model calls run at once, one per model. The classifier queues hold 32
waiting calls between them by default (`MAX_QUEUED_REQUESTS`); one more gets HTTP 429 with
`Retry-After: 1`, and the app's local fallback applies if the request then fails. Cancelling a
waiting call removes it; cancelling a running one keeps its worker busy until the work finishes.

These queues cover `/facts` in both modes. Demucs runs one separation at a time on its own, and
`/queue` doesn't report the unified worker's other phases. A separate llama.cpp caption server
can expose its own slots and metrics if you enable them there.

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
| `PROVIDER` | `auto`; the CUDA image sets `cuda` | `auto`, `cpu`, `cuda` or `coreml`. `auto` takes CUDA where the provider is present and CPU otherwise. CoreML is selectable; Linux images use CPU or CUDA |
| `REQUEST_THREADS` | `4` | the thread pool in front of ONNX Runtime. The app's `facts_concurrency` is what fills it |
| `MAX_QUEUED_REQUESTS` | `32` | maximum waiting calls across classifier queues; excess requests get HTTP 429 |
| `IDLE_UNLOAD_SECONDS` | `300` | drop idle weights; `0` holds them |
| `PRELOAD` | `false` | load every producer at boot instead of on first use |
| `DETECTOR_CACHE_DIR` | unset in the runtime; `/opt/immich-models/huggingface` in the CUDA image | where the detector snapshots live; unset uses the Hugging Face cache, with `HF_HOME=/cache/huggingface` in the CPU image |
| `ALLOW_MODEL_DOWNLOADS` | `false` | let a cold cache fetch the pinned exports and the Docling snapshot itself |
| `MAX_IMAGE_BYTES` | `16777216` | refuse a decoded picture larger than this, and size the `/facts` body limit from it |

The CUDA image sets `OPENBLAS_NUM_THREADS=1`: the per-picture head projection is small, and a
BLAS pool sized from the host's cores would eat the container's CPU quota. `REQUEST_THREADS` is
separate: it bounds classifier calls. Measure under your real CPU and
memory limits before changing either.

Idle unload drops the weights and **keeps the process**: the next request reloads them. Changing
the provider re-keys nothing, so any of this can be retried without re-deriving a fact.

## Point the app at it

Use the [app connection and health checks](../better/inference.md#classifiers-and-stems-only). The [configuration reference](./config-reference.md#inference-service) lists timeout, concurrency and fallback settings.
