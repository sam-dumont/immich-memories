---
title: Caption service contract
---

# Caption service contract

[Add captions](../better/captions.md) gets the Compose service running. This page is the rest: the contract every caption server must meet, the pinned artifacts, other ways to serve them and explicit LLM captions.

## Unified or separate service

The [unified NVIDIA worker](../run/reference-setup.md#one-gpu-service) already serves captions
at `/v1`. It stops its caption process while another GPU phase runs and starts it again on
demand. The standalone Compose and Kubernetes recipes below run their own server; you don't need
one next to the unified worker.

While a render or music phase holds the worker's GPU, it answers 503. Preparation waits: 429,
503 and dropped connections are retried with a growing delay (2 s, up to 30 s between tries,
honouring `Retry-After`) for up to 25 minutes, with a warning that the run is waiting. A worker
still busy after that ends the round with "the inference worker stayed busy"; the pictures stay
outstanding for the next run. Any other 4xx is the picture's own answer and is not retried.

The unified caption route has no authentication, even though `/render` on the same listener
requires a token. Keep it private.

| Setting | Standalone recipes | Unified worker |
|---|---|---|
| Context size | 8192 | 8192 |
| Prompt cache in RAM | 128 MiB (`--cache-ram 128`) | 128 MiB (`LLAMA_ARG_CACHE_RAM` overrides it) |
| Processing slots | 1 (`--parallel 1`) | server default |

The prompt cache holds reusable model state, not saved descriptions. None of these caps the
server's total RAM or VRAM.

## Explicit LLM captions

SmolVLM is the default caption provider. The LLM you configure for titles and the reader never
receives images unless you opt in. To let a vision-capable LLM write missing captions:

```yaml
advanced:
  llm:
    provider: openai-compatible
    base_url: http://localhost:8000/v1
    model: your-vision-capable-model
  editorial:
    preparation:
      caption_provider: llm
```

**This is slower than SmolVLM and can cost a lot more on a hosted API.** The app warns at
startup and in preflight. Image tiles and video frame strips go to the configured LLM with its
credentials and provider settings; the SmolVLM endpoint and `caption_api_key` are not used.

Banked SmolVLM captions and motion lines are reused first. LLM captions are banked under their
own producer identity, so changing models never relabels old captions. Three synthetic tiles
must pass the schema check before any library picture is sent. A failed LLM caption stays
outstanding; nothing falls back to another model.

A film still captions only its selected shots and real replacement candidates; `prepare` covers a
wider scope. This works on Basic and does not turn Basic selection into Full. Sharing decisions
stay with the rules, the classifiers and Laya where enabled.

## The SmolVLM contract

Before a single library picture goes on the wire, the app checks that `GET /models` advertises
`smolvlm2-500m-base-public`, then sends three synthetic control tiles (red, blue, grey) and
requires a schema-valid answer to each. Then each picture is one 400 px JPEG tile, one request at
temperature 0 with a repetition penalty of 1.1, a 140-token cap and a JSON schema the server has to
honour. Two invalid answers bank `caption unavailable`; a timeout, a missing model or a transport
error stays outstanding and the next run picks it up.

The alias is a promise about behaviour: any endpoint can claim it. It says the descriptions
came from SmolVLM2-500M with this prompt and this schema, so captions banked months apart are
comparable. Alias an unrelated vision model and the app believes you, and the bank then holds two
things under one name. The explicit LLM option above uses the configured model's own name instead.

`caption_api_key` goes out as `Authorization: Bearer <key>`; blank sends no header. The reader's
`llm.api_key` is never borrowed for it.

Caption reports name the producer of the caption actually reused, which can differ from the
model configured today. A description and its setting are always read as one pair from the same
producer.

## Accepted artifacts

| Format | Repository | Revision | Runs on |
|---|---|---|---|
| MLX | `mlx-community/SmolVLM2-500M-Video-Instruct-mlx` | `fa57db46815177fbdfd65cc85a2b3416a8332268` | Apple Silicon |
| GGUF | `ggml-org/SmolVLM2-500M-Video-Instruct-GGUF` | `ccd7aae53bcb1997355c2f094959e72b3642ce17` | Anything llama.cpp runs on |

Same 500M model either way; pick what your hardware runs. The GGUF files this page pins:

| File | Size | SHA-256 |
|---|---|---|
| `SmolVLM2-500M-Video-Instruct-Q8_0.gguf` | 437 MB | `6f67b8036b2469fcd71728702720c6b51aebd759b78137a8120733b4d66438bc` |
| `mmproj-SmolVLM2-500M-Video-Instruct-Q8_0.gguf` | 109 MB | `921dc7e259f308e5b027111fa185efcbf33db13f6e35749ddf7f5cdb60ef520b` |

Use the pinned Q8_0 artifacts to match the bundled serving contract.

## Apple Silicon, with mlxcel

```bash
brew install lablup/tap/mlxcel
pip install huggingface-hub          # for the `hf` command, if you do not have it
SNAPSHOT=$(hf download mlx-community/SmolVLM2-500M-Video-Instruct-mlx \
  --revision fa57db46815177fbdfd65cc85a2b3416a8332268)
mlxcel serve --model "$SNAPSHOT" --alias smolvlm2-500m-base-public --host 0.0.0.0 --port 8092
```

`--host 0.0.0.0` because mlxcel binds `127.0.0.1` by default, which an app on a NAS or another
host cannot reach (`Caption endpoint unreachable`). Nothing behind the port checks a credential,
so keep it on your LAN.

`hf download` prints the snapshot directory it wrote, which is what the server wants. Then in your
config:

```yaml
tier: auto
advanced:
  editorial:
    preparation:
      caption_base_url: http://localhost:8092/v1
```

That is the default value of `caption_base_url`. On an Apple Silicon Mac installed with the
`all-mac` extra, `tier: auto` sees the Metal GPU and picks GPU, or Full when an LLM is also
configured. Install the [Laya checkpoint](llm-providers.md#the-laya-audience-pre-screen) too.

From the app in Docker Desktop on the same Mac, the address is
`http://host.docker.internal:8092/v1`; from a NAS, the Mac's LAN name or IP. If you run oMLX for
the reader, keep the SmolVLM caption server as its own process on its own port. A container
doesn't see the Mac's GPU, so configure a [GPU inference service](../better/inference.md) as
well: a caption URL alone does not select the GPU tier.

## Apple Silicon, with llama.cpp

Switching the caption server from mlxcel to llama.cpp cuts its resident memory by about 4x on a
16 GiB Mac; see [Measure your setup](../better/measured.md#caption-service-memory) for the exact
figures. That is the caption server alone; the reader and music need their own memory.

Use the `llama-server` executable installed for the local reader and the GGUF files pinned in the
table above. This is an alternative to the mlxcel caption process, so stop that process before
using its port (leaving both loaded defeats the saving). Keep the same served alias.

```bash
CAPTION_MODELS="$HOME/.immich-memories/models/captioner-gguf"
hf download ggml-org/SmolVLM2-500M-Video-Instruct-GGUF \
  SmolVLM2-500M-Video-Instruct-Q8_0.gguf \
  mmproj-SmolVLM2-500M-Video-Instruct-Q8_0.gguf \
  --revision ccd7aae53bcb1997355c2f094959e72b3642ce17 \
  --local-dir "$CAPTION_MODELS"
llama-server \
  --model "$CAPTION_MODELS/SmolVLM2-500M-Video-Instruct-Q8_0.gguf" \
  --mmproj "$CAPTION_MODELS/mmproj-SmolVLM2-500M-Video-Instruct-Q8_0.gguf" \
  --alias smolvlm2-500m-base-public --host 127.0.0.1 --port 8092 \
  --ctx-size 8192 --cache-ram 128 --parallel 1 --threads 4 --n-gpu-layers 99
```

If the files are already there, check their hashes against the pinned table and reuse them.
This recipe was checked with llama.cpp build 11146; if captions fail to load, try the latest
release. Point `advanced.editorial.preparation.caption_base_url` at `http://127.0.0.1:8092/v1`
and run preflight. Preparation checks the caption schema on the control tiles before it sends any
library preview.

## Docker and Linux, with llama.cpp

The released GPU tier file includes a weight downloader and a caption server. For NVIDIA,
include the CUDA file too ([device prerequisites](#on-an-nvidia-host)); the GPU file alone uses
CPU images for diagnosis. [Compose setup files](./compose-files.md#select-the-files) covers downloads
and keeping the selection in `.env`. The downloader checks both pinned digests before starting:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.cuda.yml up -d
curl -s localhost:8094/v1/models
```

The first start downloads about 546 MB of model and projector weights, plus the container
images; later starts only verify the cached weights. Compose publishes captions on host port
**8094** and inference on **8092**; inside the Compose network both listen on 8092. The GPU tier
file supplies those service URLs as defaults below saved Settings, so you can change them in
Settings. An environment override such as `IMMICH_MEMORIES_EDITORIAL__PREPARATION__CAPTION_BASE_URL`
pins them above Settings.

Asking for GPU doesn't prove the device works. Run preflight after startup: CPU inference does
not pass the GPU compute check.

Running `ghcr.io/ggml-org/llama.cpp:server` by hand works the same way, with the weights
bind-mounted at `/models` and
`--host 0.0.0.0 --ctx-size 8192 --cache-ram 128 --parallel 1 --threads 4`.
Finished captions live in the app's store, not in the server.

Three more flags carry the serving contract:

| Flag | Leave it out and |
|---|---|
| `--alias smolvlm2-500m-base-public` | the server advertises the GGUF path instead, and preflight says the endpoint serves another model |
| `--mmproj …` | the model loads and answers, but cannot interpret images: the control tiles fail and no library picture is sent |
| `--port 8092` | nothing answers where the app looks, and the row reads unreachable |

Preflight checks `/models` and the advertised alias; it does not send an image. Preparation
sends the control tiles first, and failed controls stop it before any library picture is sent.

### On an NVIDIA host

Add the released CUDA file to the base and GPU files:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.cuda.yml up -d
```

It selects the pinned `server-cuda-b10920` caption runtime, requests the NVIDIA device and sets
`LLAMA_ARG_N_GPU_LAYERS=99`. No separate captioner version variable or hand-written override is
needed: 99 is more than the pinned model's layer count, so every layer goes to the GPU. Install
the NVIDIA driver and container toolkit first, then check captions and inference with preflight.

Once you've measured the server under load, you can raise the app's concurrency:

```yaml
IMMICH_MEMORIES_EDITORIAL__PREPARATION__CAPTION_CONCURRENCY: "4"
```

### Speed, and what to set `caption_concurrency` to

Start with the default of 1. On a CPU server, more requests in flight compete for the same
threads and can make it slower. On a GPU, try 4 and measure it next to the other services you
run. Count new captions only: a run that reuses banked captions says nothing about throughput.
The project's own numbers are on [Measure your setup](../better/measured.md).

## Kubernetes

```bash
kubectl create namespace immich-memories   # if you have not already
kubectl apply -k deploy/kubernetes/overlays/captioner        # CPU
kubectl apply -k deploy/kubernetes/overlays/captioner-cuda   # NVIDIA nodes
```

Each overlay is a Deployment, a ClusterIP Service on 8092, a NetworkPolicy and a 2 Gi PVC that
an init container fills and digest-checks before the server starts. Neither overlay includes `base`, so both apply without
the Immich secret: the captioner holds no credential. It does receive a 400 px tile of every
picture it is asked to caption, so the Service stays ClusterIP and the NetworkPolicy allows ingress on 8092
only.

Point the app at it:

```yaml
tier: auto
advanced:
  inference:
    facts_base_url: http://inference:8092
  editorial:
    preparation:
      caption_base_url: http://captioner:8092/v1
```

Across namespaces that is `captioner.immich-memories.svc.cluster.local:8092`.

The app's base manifest uses `tier: auto`. Point it at the GPU inference and caption services;
the resolved product tier sets preparation too:

```bash
kubectl -n immich-memories set env deployment/immich-memories \
  IMMICH_MEMORIES_INFERENCE__FACTS_BASE_URL=http://inference:8092 \
  IMMICH_MEMORIES_EDITORIAL__PREPARATION__CAPTION_BASE_URL=http://captioner:8092/v1
```

`captioner-cuda` is the same Deployment with the `server-cuda-b10920` image, `--n-gpu-layers 99` appended,
and the three things the GPU Operator wants: `runtimeClassName: nvidia`, the `nvidia.com/gpu.present`
node selector and the matching toleration. Nothing else changes, so pointing the app at it is the
block above plus `caption_concurrency: 4`.

It deliberately does not request `nvidia.com/gpu: 1`. Where one card is time-sliced per node that
resource has a single slot, the inference Deployment holds it, and a captioner asking for a second
stays Pending beside an idle card. Without the request, it relies on the NVIDIA runtime exposing
the same card, which is not a portable GPU-sharing or memory guarantee. The unified worker avoids
two Deployments on one card. With a card to spare, put the request back:

```yaml
resources:
  limits:
    nvidia.com/gpu: "1"
  requests:
    nvidia.com/gpu: "1"
```

The standalone overlays pin llama.cpp build b10920: `server-b10920` on CPU and
`server-cuda-b10920` on CUDA. Update both together and validate the serving contract.

## How preflight reports it

`Captions OK Serving smolvlm2-500m-base-public` is the row you want. Failures name the cause:

| Row | What happened |
|---|---|
| `Caption endpoint unreachable` | nothing is listening, or it is not HTTP |
| `Caption server is slow to answer` | the model inventory exceeded `editorial.preparation.caption_timeout_seconds` (90 seconds by default); check the worker logs or raise that timeout for cold model loading |
| `Caption endpoint serves another model` | a server answered and advertised something else |
| `Caption endpoint refused the request` | 401 or 403, so set `caption_api_key` |

`Caption server busy with another phase, will serve captions when free` is an OK row: the unified
worker answered that a render or music phase holds its GPU.

On Basic with the default caption provider the row is skipped (`Not required by basic`). With
explicit LLM captions the row is a warning about sending images; preflight sends no vision
request.

## What a missing captioner costs

On GPU and Full with SmolVLM, prepare stops: the description producer stays outstanding and the
failure names `caption_base_url`. Default Basic does not require that endpoint. With explicit LLM
captions, a failed image request stays outstanding under that provider's identity.
What each tier runs: [Requirements and tiers](../run/requirements.md#the-preparation-tier).

## Knowing which build wrote a caption

The alias doesn't identify a build: every recipe on this page advertises it on port 8092. So
each new caption row also keeps the server's `/models` row and a 16-character digest of
its answers to the three controls, plus an optional label of your own
(`advanced.editorial.preparation.caption_artifact_id`). `prepare` prints one line naming every
captioner behind the bank, with `MIXED` when there is more than one, and
`immich-memories runs why <asset-id> --run <run-id>` shows the one a run used. None of it
re-captions anything already banked.

## Switching servers later

The bank keys on the producer name, `description:smolvlm2-500m-base-public@envelope-v3-compact`,
which carries no format, no quantisation and no weights digest. Swapping MLX for GGUF re-captions
nothing: every banked picture keeps the wording the old server gave it, and short of clearing the
description rows there is no way to ask for a re-caption.

Different runtimes can phrase the same picture differently. A mixed bank keeps each result's
provenance, but switching servers does not normalise existing wording. Pick one if consistency
matters for your library.

## Motion lines

On the `gpu` and `full` tiers, every video a cut prepares gets one banked sentence about what
happens in it, from the same caption server and model. So does every Live Photo whose motion an earlier cut measured at
1.5 or more; one nobody measured yet is not known to play and gets none. The story pick reads that
sentence beside the video's row, so the reader compares a video with a still in text and never
sees a video frame.

The app doesn't download the whole video. Immich answers byte ranges on its playback rendition,
so preparation reads the index (tens of kilobytes), picks the three keyframes nearest a quarter,
half and three quarters of the clip, and reads only those. FFmpeg copies exactly those packets
out of a sparse local copy and decodes them, which behaves the same on FFmpeg 5.1 (the app
image), 6.1, 7.1 and 8.1. A codec other than H.264, HEVC, VP9 or AV1 also costs its first
keyframe, which FFmpeg needs to read the stream at all. The three frames go to the
server as one 960 × 320 JPEG strip with a one-field schema (`description`, 120 characters), under
the same temperature, penalty, token cap and `caption_api_key` as captions.

The bank keys on the picture, its complete source metadata and
`motion-line-v1@smolvlm2-500m-base-public/3-keyframes-320px`, so a changed source is asked again
and nothing else is. Two invalid answers, a playback Immich answers 404 for, or an index the app
cannot read are banked as settled. Timeouts and transport failures stay missing, so a later
`prepare` retries them and reports a visible "motion unavailable" warning. Normal film refinement
reuses its rules draft and does not consume these sentences, so it does not request them or
report their absence as a preparation failure. A model-planning route can use banked lines or
plain clip facts. `caption_concurrency` bounds the requests in flight; keyframe reads run
four at a time.

Each row also records what produced it: a digest of the question asked, the keyframe times it
read, and what made the source owe a line (`video`, or the Live Photo's residual and the
measurement that produced it). Missing provenance is reported as `unrecorded` in the motion metrics.

A video's sentence counts only where its motion is measured. On every tier that samples a
video's frames for the exposure head, preparation also measures their optical-flow residual and
banks it under the picture, its source metadata and
`motion-residual-v1@median-flow-v1-detector-frames-320x240`, with the frame count it was measured
on. A video that measures under 1.5 has its sentence withheld (a favourite keeps it); see
[Picking each shot](../how-it-chooses/picking-shots.md). A missing residual can require another sample; a frame read or measurement failure is named
and does not block the cut.

`prepare` owns motion-description requests. It banks true videos and Live Photo companions whose
measured residual already qualifies them. A first cut can discover motion in an unmeasured Live
Photo; it uses plain facts until a later `prepare` banks that companion's sentence. Cuts read
banked descriptions and never contact the motion-description server. Missing lines remain listed
in the private preparation record. Required captions and safety facts still gate the cut.

The `basic` tier asks for no motion line. The pick then reads the video's plain
facts instead: its length, and the measured motion of a Live Photo that has one.
