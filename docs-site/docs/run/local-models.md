---
title: Basic with a local text model
---

# Basic with a local text model

This reference adds **Ollama 0.35.1**, model **`gemma4:e4b-it-q4_K_M`**, to the prebuilt Basic
app. It supplies a reader: a **text model (LLM)** configured under `advanced.llm`.
It can write titles and music mood. It does **not** add GPU selection, Full or vision captions.
Full additionally needs GPU inference, the caption service and Laya.

The published Docker image has no `llama-server`: Docker and Kubernetes require an external
text-model server. Native Linux/macOS can instead run the [app-owned llama.cpp reader](../better/reader.md),
which is a different model/runtime recipe. External services own their memory and shutdown.

The exact Ollama/model pair has [recorded conformance results](../better/measured.md#ollama-validation)
on an M5 Max with 128 GiB and warm caches. Thinking-off native requests passed 33/34 probes;
motion interpretation failed. That is evidence for individual calls, **not an offline film pass**
or a minimum hardware measurement. The complete deployment below remains untested, tracked in
[#1926](https://github.com/sam-dumont/immich-memories/issues/1926).
[Other providers and failures](../reference/llm-providers.md) remain separate results.

## Prepare the two services

Start from the [Basic prebuilt installation](./docker.md) and retain its app version/digest.
Use an operator-managed Ollama 0.35.1 host reachable only from the app's private network;
its installation, RAM/VRAM and outbound firewall belong to that host. The measured Apple setup
used 128 GiB unified memory; lower-memory hosts have no end-to-end validation here.
On the **model host**, verify the version and acquire the exact model:

```bash
ollama --version
ollama pull gemma4:e4b-it-q4_K_M
ollama show gemma4:e4b-it-q4_K_M
```

Keep the displayed model identity/digest with your test record: an Ollama tag alone can move.
Ollama's native endpoint is port **11434**, with no app-supplied authentication in this recipe.
Keep it on a restricted LAN/VLAN or behind your authenticated proxy; never publish it to the internet.
Its model files stay in Ollama's model directory on that host, separate from app data.

Save this as `config.yaml` beside the app Compose file. `192.168.1.50` is an example; replace it
with the actual private model-host IP. Retain the Basic app's `.env` for Immich and login secrets.

```yaml
tier: basic
upload:
  enabled: false
network:
  geocoding: false
  map_tiles: false
advanced:
  llm:
    enabled: true
    provider: ollama
    base_url: http://192.168.1.50:11434
    model: gemma4:e4b-it-q4_K_M
    reader_concurrency: 1
    extra_params:
      think: false
      options:
        num_ctx: 32768
  ace_step:
    enabled: false
  musicgen:
    enabled: false
  notifications:
    urls: []
```

Add a read-only file mount under the app service's `volumes`:

```yaml
    - ./config.yaml:/home/immich/.immich-memories/config.yaml:ro
```

The app owns `advanced.llm`; Ollama owns model acquisition, port/listen policy and resident
memory. File/environment values override saved Settings. Do not also enable a hosted provider.
A dotted LAN hostname receives the app's “hosted” request defaults; that classification does
not establish where traffic goes. This private-IP recipe avoids it. For dotted names, see
[request concurrency and schema overrides](../better/reader.md#use-an-existing-server).

On the **app host**, recreate, prepare and probe:

```bash
docker compose up -d
docker compose exec immich-memories immich-memories models fetch
docker compose exec immich-memories immich-memories preflight
docker compose exec immich-memories immich-memories capabilities
```

Expect Basic selection and an enabled Ollama reader. Fix failed reader connectivity before the
reference run; a model name alone does not establish readiness. Keep bundled music, local output
and the [20–50-item trial](../get-started/first-film.mdx). Reader failure can leave rules/default
wording with a visible warning; it must not be recorded as successful model use. There is no
configured alternate hosted endpoint in this recipe. The stopped-provider outcome still needs
a disposable test; do not claim the exact error text or no public traffic from configuration alone.

## Network phases and verification

| Phase | Expected recipients and data |
|---|---|
| Artifact/model preparation | App registry and delivery hosts for image layers; GitHub/CDNs for Basic pins, WordNet source; Ollama registry/storage hosts for model weights |
| Startup and warm-up | App → Immich for API/auth probes; app → private Ollama for model/request checks; model host loads its prepared weights |
| Film generation | App → Immich for metadata/previews/originals; app → Ollama for text requests; local film output. No vision frames are opted into the text reader |

Maps/geocoding, hosted endpoints, notifications and generated music stay off. This avoids
ACE-Step/Demucs first-use downloads, but **all** participating services still need an outbound
boundary. The [request inventory](./reference/privacy-egress.md) lists each feature's recipients.

To validate local-only operation on disposable hosts, finish preparation first, then use host/router
firewall rules permitting app → Immich IP/port and app → Ollama IP/11434. Deny other app egress
on IPv4 and IPv6. Deny the **Ollama host/process** public egress too, allowing only replies to the
app and any strictly internal resolver needed. For containers, enforce forwarded traffic, not
just the host OUTPUT chain; for Kubernetes apply destination policies to **both** pods and remove
other additive allow rules. The [offline guide](./offline.md) details those enforcement limits.

Record the actual firewall/CNI configuration. From each app/model namespace verify a permitted
local request and a denied public HTTPS request, then run the bounded film and decode/watch it.
Capture destinations and warnings through startup and generation. A blocked app container cannot
prove that a separate model server made no downloads. Finally stop only the disposable Ollama
service, retry, record the error/degradation and destination log, restore it and confirm recovery.
This protocol is pending execution; it does not certify arbitrary LAN firewalls.

## Kubernetes services {#kubernetes-services}

Use the same candidate/release pins for project images. `VERSION` below means that exact app
image tag, never `latest`; the published bundle substitutes it. CPU app/inference images target
amd64 and arm64; CUDA inference targets **amd64 only**. Inspect the published manifest before
selecting an architecture. Third-party caption/reader image support is independent.

| Service | Image / endpoint / auth | CPU and RAM requests → limits | GPU and storage / startup |
|---|---|---|---|
| App, one replica | Project app `:VERSION`; 8080; Basic/OIDC before LAN exposure | 1 CPU/2Gi → 4 CPU/8Gi; fetch init 250m/512Mi → 2 CPU/2Gi | No GPU in Basic or remote-inference wrapper. Data PVC contains SQLite, Settings/credentials and caches; `/models` pins; `/app/output` films. Init fetches pins |
| CUDA inference | Project `/inference:VERSION-cuda`; 8092; no key in shipped overlay, restrict network | 500m/1Gi → 4 CPU/4Gi | One GPU allocation; `/cache` PVC for weights/HF/JIT; first use can download and warm models; idle unload does not remove files |
| Generated CUDA captioner | `ghcr.io/ggml-org/llama.cpp:server-cuda-b10920`; 8092 `/v1`, alias `smolvlm2-500m-base-public`; network isolation | 500m/1Gi → 4 CPU/3Gi; fetch init 100m/64Mi → 1 CPU/256Mi | Time-sliced, no reservation in the generated GPU wrapper; `/models` PVC contains pinned SmolVLM2 Q8_0 and projector; init verifies/downloads them |
| Independently managed CUDA captioner overlay | Same caption server/alias and resource limits | Same as above | No GPU reservation in this overlay: operator must provide supported device access/sharing or request a separate card. It still consumes VRAM |
| External Full reader | Operator's tested server/model; endpoint and API key as configured | Operator budget; no common measured minimum | Its own model cache, VRAM and startup/download policy. App cannot unload external weights |
| Optional render worker | [Worker image/config](../better/gpu-render.md); 8093; bearer token | Operator-selected worker/sidecar budget | Encoding GPU is separate from selection capability; scratch and model paths belong to worker; media arrives over authenticated HTTP |

The generated GPU wrapper reserves **one GPU allocation**, for the inference service. The
captioner reserves none and relies on time-slicing; the wrapper does not configure sharing. The
historical single-T1000 run had operator-managed sharing and does not prove that a default
exclusive card is enough for both. VRAM depends on loaded models and
concurrency; a missing reservation is not zero consumption or an arbitrary-sharing guarantee.

Only the app and its init/maintenance jobs need the app state volumes. Inference, caption and
external reader use their own caches; HTTP endpoints do not require sharing SQLite or app paths.
Keep SQLite on local/block storage. PostgreSQL removes that file constraint but does not make
multiple UI replicas safe. See [mounts, backups and probes](./kubernetes.md#how-the-pod-is-wired).
Existing services may be reused only after app preflight confirms the expected facts contract,
caption alias and reader configuration; record their exact versions and warm-cache status.
