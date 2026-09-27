---
title: Add captions
---

# Add captions

Reader: power user.

The `nas` product tier runs without them by default. GPU and Full start with the NAS selection,
then caption those shots with a 500M vision model. A replacement candidate gets its caption
before it is judged. Each caption is banked and reused by later films:

```json
{"description": "A stack of wrapped gifts on a wooden table.", "setting": "insufficient evidence"}
```

Making a film does not require captioning the whole library. Use `prepare` when you want
captions ahead of time for other features. Live Photo companion checks and video frame sampling
also wait until a shot is selected or considered as a replacement.

What that buys:

- **The family-viewing check reads activities described in the caption.** Laya checks eight
  findings, including bathing, changing and identifying records. A supported bathing finding
  keeps the picture in just-us films; an identifying record is held from every sharing level.
  This adds evidence beyond the picture detectors, but a missed or incorrect caption can still
  miss the activity. Review the pictures before sharing them.
- **A [reader](./reader.md) reads them**, and the [Laya pre-screen](./reader.md#the-laya-audience-pre-screen)
  answers from them.

What it costs: a caption service and time. Compose includes a captioner profile; you can also
run a separate server as described below.
CPU captioning can be slow, so automatic selection stays on NAS without GPU inference capability.
The caption server receives a 400 px tile of each requested picture, once per caption generation.
Those pixels leave your network only if the server you configure is outside it.

## Explicit LLM captions

SmolVLM is the default caption provider. An LLM configured for titles or prose never receives
images automatically. To let a vision-capable LLM supply missing captions, opt in:

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

**This is less efficient than SmolVLM and can be much more expensive, especially on hosted
infrastructure.** The app warns at startup and in preflight. Image tiles and video frame strips
go to the configured LLM, using its credentials and provider settings. The SmolVLM endpoint and
`caption_api_key` are unused for this choice.

Existing valid SmolVLM captions and motion lines stay banked and are reused first. New LLM
captions have a separate producer identity and provenance; changing models does not relabel old
captions. Before new picture captions, three synthetic tiles must pass the schema check. A failed
LLM caption stays outstanding, with no automatic fallback to another model.

Film generation still captions only the selected shots and actual candidates. `prepare` is the
explicit job for a wider scope. This choice works on NAS without promoting selection to Full:
automatic tiers still follow available GPU inference capability. Sharing decisions remain with
the rules, classifiers and Laya where enabled.

## The SmolVLM contract

Before a single library picture goes on the wire, the app checks that `GET /models` advertises
`smolvlm2-500m-base-public`, then sends three synthetic control tiles (red, blue, grey) and
requires a schema-valid answer to each. Then each picture is one 400 px JPEG tile, one request at
temperature 0 with a repetition penalty of 1.1, a 140-token cap and a JSON schema the server has to
honour. Two invalid answers bank `caption unavailable`; a timeout, a missing model or a transport
error stays outstanding and the next run picks it up.

The alias is a promise about behaviour, not a name lookup: any endpoint can claim it. It means the
descriptions under that name came from SmolVLM2-500M with this prompt and this schema, so a bank
filled last month and one filled today are comparable. Alias an unrelated vision model and the app will
believe you, and the bank then holds two things under one name. The default SmolVLM provider
expects this alias from your server. The explicit LLM
option above uses the configured model's own identity instead.

`caption_api_key` goes out as `Authorization: Bearer <key>`; blank sends no header. The reader's
`llm.api_key` is never borrowed for it.

Caption reports name the producer of the caption actually reused, which can differ from the
currently configured model. Older captions without provenance stay marked unknown. A description
and its setting are read as one complete pair from the same producer.

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

Q8_0 is the quantisation to run. Q4_K_M measured twice as slow and worse; f16 is eighteen times
slower for no gain.

## Apple Silicon, with mlxcel

The Apple Silicon caption server used for this project's controls.

```bash
brew install lablup/tap/mlxcel
pip install huggingface-hub          # for the `hf` command, if you do not have it
SNAPSHOT=$(hf download mlx-community/SmolVLM2-500M-Video-Instruct-mlx \
  --revision fa57db46815177fbdfd65cc85a2b3416a8332268)
mlxcel serve --model "$SNAPSHOT" --alias smolvlm2-500m-base-public --host 0.0.0.0 --port 8092
```

`--host 0.0.0.0` because mlxcel binds `127.0.0.1` by default, which an app on a NAS or another host
cannot reach (`Caption endpoint unreachable`); nothing behind the port checks a credential, so keep
it on your LAN.

`hf download` prints the snapshot directory it wrote, which is what the server wants. Then in your
config:

```yaml
tier: auto
advanced:
  editorial:
    preparation:
      caption_base_url: http://localhost:8092/v1
```

That is the default value of `caption_base_url`. With a usable local MLX runtime, automatic
selection chooses GPU, or Full when an LLM is also configured. Install the
[Laya checkpoint](./reader.md#the-laya-audience-pre-screen) too. From the app in Docker Desktop on the same Mac, the address is
`http://host.docker.internal:8092/v1`; from a NAS, the Mac's LAN name or IP. If you run oMLX
for the reader, use the separate SmolVLM caption server with its own process
on its own port. A container does not inherit the Mac's MLX runtime: configure a
[GPU inference service](./inference.md) as well. A caption URL alone does not select the GPU tier.

## Docker and Linux, with llama.cpp

The compose file ships this as a profile: one service downloads and digest-checks the weights, one
serves them.


```bash
docker compose --profile captioner up -d
curl -s localhost:8094/v1/models
```

The first `up` pulls 546 MB; re-running it is cheap, the digest check short-circuits.
Compose publishes captions on host port **8094** and inference on **8092**, so both
profiles can run together. Inside the Compose network both services still use port 8092.

Point the app at the captioner and a GPU inference service in `docker-compose.yml`:

```yaml
IMMICH_MEMORIES_TIER: "auto"
IMMICH_MEMORIES_INFERENCE__FACTS_BASE_URL: "http://immich-memories-inference:8092"
IMMICH_MEMORIES_EDITORIAL__PREPARATION__CAPTION_BASE_URL: "http://immich-memories-captioner:8092/v1"
```

The inference service must report CUDA for automatic GPU selection. A CPU service alone keeps
selection on NAS. Preparation follows the product tier; do not set a separate preparation tier.

Running `ghcr.io/ggml-org/llama.cpp:server` by hand works the same way, with the weights
bind-mounted at `/models` and `--host 0.0.0.0 --ctx-size 8192 --threads 4`. Three of its flags
carry the contract, and each fails as something else:

| Flag | Leave it out and |
|---|---|
| `--alias smolvlm2-500m-base-public` | the server advertises the GGUF path instead, and preflight says the endpoint serves another model |
| `--mmproj …` | the model loads and answers, but it is blind: the control tiles fail and no library picture is sent |
| `--port 8092` | nothing answers where the app looks, and the row reads unreachable |

This recipe clears the alias and all three schema controls first attempt; 136 of 136 fixture
pictures validated. Do not reach for `--model-url` and `--mmproj-url` to skip the download: on
build b10920 they are accepted, ignored, and the server starts with zero models loaded, so
`/models` comes back empty and preflight reports the wrong problem.

### On an NVIDIA host

Two halves, neither of which works alone: the tag that carries CUDA
(`export CAPTIONER_TAG=server-cuda`) and the device. From a checkout the device comes from
`docker/hwaccel.captioner.yml`. That file holds `extends:` targets, not services, so it cannot go
on the command line as `-f` itself; a three-line override pulls its `cuda` block into the
captioner:

```bash
cat > captioner.cuda.yml <<'EOF'
services:
  immich-memories-captioner:
    extends: { file: docker/hwaccel.captioner.yml, service: cuda }
EOF
CAPTIONER_TAG=server-cuda docker compose -f docker-compose.yml -f captioner.cuda.yml --profile captioner up -d
```

A downloaded `docker-compose.yml` reads no file beside itself, so the same two blocks ship in the
captioner service commented out. Uncomment both:

```yaml
    environment:
      LLAMA_ARG_N_GPU_LAYERS: "99"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities:
                - gpu
```

99 is "all of them", and a 500M model has 32. By hand that is `--gpus all`, the `server-cuda` image
and `--n-gpu-layers 99`. Raise the concurrency with it:

```yaml
IMMICH_MEMORIES_EDITORIAL__PREPARATION__CAPTION_CONCURRENCY: "4"
```

### Speed, and what to set `caption_concurrency` to

Start with the default of 1. More concurrent requests can make a CPU server slower because
they compete for the same threads. On a GPU, try 4 and measure with the other services you run.
Report new captions separately from cache hits: a selection run that reuses captions does not
measure caption throughput. Dated measurements belong on [Measured](./measured.md).

## Kubernetes

```bash
kubectl create namespace immich-memories   # if you have not already
kubectl apply -k deploy/kubernetes/overlays/captioner        # CPU
kubectl apply -k deploy/kubernetes/overlays/captioner-cuda   # NVIDIA nodes
```

A Deployment, a ClusterIP Service on 8092, a NetworkPolicy and a 2 Gi PVC an init container fills
and digest-checks before the server starts. Neither overlay includes `base`, so both apply without
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

`captioner-cuda` is the same Deployment with the `server-cuda` image, `--n-gpu-layers 99` appended,
and the three things the GPU Operator wants: `runtimeClassName: nvidia`, the `nvidia.com/gpu.present`
node selector and the matching toleration. Nothing else changes, so pointing the app at it is the
block above plus `caption_concurrency: 4`.

It deliberately does not request `nvidia.com/gpu: 1`. Where one card is time-sliced per node that
resource has a single slot, the inference Deployment holds it, and a captioner asking for a second
stays Pending beside an idle card. Without the request it shares, which works because the weights
are 546 MB. With a card to spare, put the request back:

```yaml
resources:
  limits:
    nvidia.com/gpu: "1"
  requests:
    nvidia.com/gpu: "1"
```

Both overlays float their tag, `server` and `server-cuda`, and the two have to be one llama.cpp
build: pinning means `server-bNNNNN` and `server-cuda-bNNNNN`, both or neither.

## How preflight reports it

`Captions OK Serving smolvlm2-500m-base-public` is the row you want. Three ways it goes wrong:

| Row | What happened |
|---|---|
| `Caption endpoint unreachable` | nothing is listening, or it is not HTTP |
| `Caption endpoint serves another model` | a server answered and advertised something else |
| `Caption endpoint refused the request` | 401 or 403, so set `caption_api_key` |

On NAS with the default caption provider the row reads `SKIPPED`. An explicit LLM-caption
opt-in checks the configured LLM's vision responses instead.

## What a missing captioner costs

On GPU and Full with SmolVLM, prepare stops: the description producer stays outstanding and the
failure names `caption_base_url`. Default NAS does not require that endpoint. With explicit LLM
captions, a failed image request stays outstanding under that provider's identity.
What each tier runs: [Requirements and tiers](../run/requirements.md#the-preparation-tier).

## Knowing which build wrote a caption

The alias is a contract, not a build identifier: both recipes on this page advertise it on port
8092. So each new caption row also keeps the server's `/models` row and a 16-character digest of
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

That matters because the two builds word it differently. Same picture, same prompt, MLX against
GGUF Q8_0: `A bunch of balloons tied together with a string.` / `sky and clouds` against `A bunch
of balloons in the sky,` / `insufficient evidence`. `description` stays close, `setting` diverges,
and neither is graded better than the other. But a bank filled by both holds a mix with nothing
marking the seam, so if that matters for your library, pick one server and keep it.
