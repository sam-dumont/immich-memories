# Kubernetes Deployment

Kustomize manifests for Immich Memories. The base runs on any cluster (CPU only);
NVIDIA GPU scheduling is an overlay.

Authentication is disabled by default. Do not expose the Service until auth is enabled. The UI is
single-user, single-replica because active workflow state is in-process; keep `replicas: 1`.

These manifests get less exercise than Docker Compose. They are validated with
`kubectl kustomize` in the test suite, not applied to a live cluster on every release — read the
rendered output before you apply it.

```
base/                  CPU-only: Namespace, PVCs, Deployment, Service, NetworkPolicy
  job.yaml             optional one-off CLI Job; Deployment must be scaled to zero
  cronjobs.yaml        optional scheduled HTTP triggers; no application PVC mounts
  ingress.yaml.example optional Ingress — only after enabling authentication
overlays/gpu/          adds runtimeClassName nvidia, nvidia.com/gpu, node selector, tolerations
overlays/inference/    the inference service alone: Deployment, Service on 8092, cache PVC, policy
overlays/inference-cuda/ the same service on an NVIDIA card (patch + `-cuda` image tag)
overlays/inference-lan/  a second Service, type LoadBalancer, for callers outside the cluster
overlays/captioner/    llama.cpp serving the pinned SmolVLM2-500M under the alias `tier: full` wants
overlays/captioner-cuda/ the same server with its layers on an NVIDIA card
overlays/postgres/     optional: point the store at PostgreSQL instead of the default SQLite file
```

## Prerequisites

1. A storage class for three `ReadWriteOnce` PVCs: `immich-memories-cache` 30Gi,
   `immich-memories-output` 50Gi, `immich-memories-models` 5Gi. A deployment made before the
   models claim existed has to add it, or the pod stays `Pending` on a volume that is not there.
2. Immich reachable from the cluster (in-cluster or external, port 2283 by default)
3. GPU overlay only: the [NVIDIA GPU Operator](https://github.com/NVIDIA/gpu-operator)
   (RuntimeClass `nvidia`, `nvidia.com/gpu` resources, `nvidia.com/gpu.present` node label)

## Quick Start

```bash
cd deploy/kubernetes

# 1. Secret: Immich URL + API key (every key becomes an env var in the pod)
kubectl apply -f base/namespace.yaml
secret_file=$(mktemp)
cat base/secret.yaml.example > "$secret_file"
vim "$secret_file"
kubectl apply -f "$secret_file"
rm "$secret_file"

# 2. Deploy — CPU only
kubectl apply -k base
#    or on NVIDIA nodes
kubectl apply -k overlays/gpu

# 3. Open the UI
kubectl port-forward -n immich-memories svc/immich-memories 8080:80
# http://localhost:8080
```

`base/kustomization.yaml` pins the image tag (`images: newTag`). Published tags carry no `v`
prefix — release `vX.Y.Z` is image tag `X.Y.Z` — plus `latest`. The checked-in pin trails the
current release, so check it against the
[releases page](https://github.com/sam-dumont/immich-video-memory-generator/releases) before you
apply, and bump it when you upgrade. The entry rewrites the `fetch-models` init container too, so
both move together. `kubectl apply -f base/job.yaml` skips kustomize entirely and runs the
`:latest` the file names.

## How the pod is wired

The image runs as user `immich`, UID/GID 1000, `HOME=/home/immich`.

| Mount | Backed by | Holds |
|-------|-----------|-------|
| `/home/immich/.immich-memories` | PVC `immich-memories-cache` (writable) | `config.yaml`, `store.db` (banked facts, decisions, readings, run history and automation state), preview/video caches; legacy databases are imported once |
| `/home/immich/.cache` | The same data PVC, mounted again | persistent writable Torch/HF runtime caches |
| `/app/output` | PVC `immich-memories-output` | generated videos (`IMMICH_MEMORIES_OUTPUT__DIRECTORY=/app/output`) |
| `/models` | PVC `immich-memories-models` | the pinned DINOv2 export, the pinned sensitive-content export and the detector snapshots, written by `immich-memories models fetch` |
| `/tmp` | emptyDir 4Gi | FFmpeg intermediates (use 8Gi for 4K) |

The Deployment and one-off Job run the same image's `models fetch` init step. The presence
guard includes GPU detector files, so a NAS re-runs fetch on each start; existing artifacts are
digest-checked. Encoder, WordNet and detector files use `/models`; Laya uses the data PVC.
The app image has no `llama-server`, so a text reader must run externally.
`kubectl logs -n immich-memories deploy/immich-memories -c fetch-models` shows what it did.

There is no ConfigMap. `IMMICH_URL` / `IMMICH_API_KEY` come from the Secret; anything else is an
`IMMICH_MEMORIES_<SECTION>__<KEY>` env var on the Deployment (commented examples for an explicitly enabled text reader
and daily automation are in `base/deployment.yaml`), and the UI settings page saves to the store on the PVC.

Probes: liveness `/health/live` (process up), readiness `/health/ready` (`200` only when config
is present and Immich answers, otherwise `503`). `/health` always returns `200` and is not used.

## Batch Jobs

`base/cronjobs.yaml` contains two scheduled HTTP triggers. Set the trigger token in
the existing `immich-memories-secrets` Secret, uncomment `- cronjobs.yaml` in the kustomization, then run
`kubectl kustomize base` and `kubectl apply -k base`. Both schedules call the normal
`auto run` decision, even the one named monthly. They mount no application PVCs.

`base/job.yaml` contains only a one-off `generate` Job. Include it separately, only while the
Deployment is scaled to zero: both use the same SQLite PVC. Prefer
`kubectl exec deploy/immich-memories -- immich-memories generate ...` for a fixed recipe while
the app is running. A raw `apply -f` bypasses image and namespace transformations.

## GPU

`components/gpu/deployment-gpu.yaml` is a strategic-merge patch on the Deployment: `runtimeClassName:
nvidia`, one `nvidia.com/gpu`, `NVIDIA_*` env, `nodeSelector` on `nvidia.com/gpu.present=true`
and a toleration for the `nvidia.com/gpu` taint. Edit the label or GPU count there. The app
auto-detects the GPU (NVENC encoding and title kernels on CUDA). A card that cannot
start the title kernels costs speed, not titles: they render on the CPU and the log says why in one
warning line. Their compile cache lives on the `data` volume, since the root filesystem is read-only.

`NVIDIA_DRIVER_CAPABILITIES=compute,video,utility` in that patch is required, not decoration.
Asking for `nvidia.com/gpu` gets you `compute,utility`, which is enough for CUDA and not for the
encode chip: without `video` the NVENC probe dies with `-22 (Invalid argument)` and the render
falls back to the CPU. Pods that skip the overlay hit this, so copy the `runtimeClassName` and the
two `NVIDIA_*` env vars into any `base/job.yaml` pod you schedule on a GPU node.

## Inference service

`overlays/inference` is the encoder, the eight heads and the two detectors behind one HTTP port, as
a separate Deployment: a ClusterIP Service named `inference` on 8092, a 10Gi model-cache PVC and
its own NetworkPolicy. It deliberately does not list `../../base` in its resources. This service holds no credential and never talks to Immich. The namespace object still comes from the base, so on a cluster running the
service alone, `kubectl create namespace immich-memories` first.

```bash
kubectl apply -k overlays/inference        # CPU
kubectl apply -k overlays/inference-cuda   # NVIDIA nodes
```

`overlays/inference-cuda` is the same overlay plus `deployment-cuda.yaml`: `runtimeClassName:
nvidia`, one `nvidia.com/gpu`, `NVIDIA_VISIBLE_DEVICES` / `NVIDIA_DRIVER_CAPABILITIES`, the
`nvidia.com/gpu.present` node selector, the `nvidia.com/gpu` toleration, and the `-cuda` image
tag. It is a sibling directory rather than `overlays/inference/cuda` because kustomize reads an
overlay nested inside its own base as a cycle and refuses to build it.

Each overlay pins its own tag (`images: newTag`), the CUDA one with `-cuda` on the end. Bump them
together. Settings are `IMMICH_MEMORIES_INFERENCE_*` env vars with one underscore, not the app's
two; the image already sets host, port and the two cache directories.

To use it, set `IMMICH_MEMORIES_INFERENCE__FACTS_BASE_URL` (two underscores, app side) on the app
Deployment to `http://inference:8092`, or
`http://inference.immich-memories.svc.cluster.local:8092` from another namespace. The base
NetworkPolicy already allows egress on 8092. The encoder and Marqo ONNX exports have to be on the
cache PVC; `ALLOW_MODEL_DOWNLOADS=true` in the overlay only covers the detector snapshots.

`overlays/inference-lan` is for callers that are not in the cluster: a NAS, a laptop, the setup
matrix. It adds a second Service, `inference-lan`, type LoadBalancer, on the same pods and port,
and leaves the ClusterIP one alone, so nothing in-cluster changes and either device overlay
composes with it. It needs a load-balancer controller; without one the Service stays `<pending>`.
Nothing here checks a credential, so do not give it a routable address.

```bash
kubectl apply -k overlays/inference-lan
kubectl -n immich-memories get service inference-lan
kubectl delete -k overlays/inference-lan
```

## Caption server

`overlays/captioner` is llama.cpp serving the pinned SmolVLM2-500M GGUF under the alias
`smolvlm2-500m-base-public`, which is what `tier: full` needs and nothing else in this repo
provides. A Deployment, a ClusterIP Service on 8092, a NetworkPolicy and a 2Gi PVC; an init
container downloads the two pinned files onto the claim and checks both digests before the server
starts.

```bash
kubectl create namespace immich-memories   # if you have not already
kubectl apply -k overlays/captioner
kubectl apply -k overlays/captioner-cuda   # NVIDIA nodes
```

`overlays/captioner-cuda` is the same overlay with `--n-gpu-layers 99` appended and the
`server-cuda` image, which is worth 3.5 s a picture against tenths of a second. It asks for no
`nvidia.com/gpu` resource on purpose: a time-sliced card has one allocatable slot and the inference
Deployment holds it. The caption server page says when to put the request back.

Like the inference overlay it does not list `../../base`: it holds no credential and never talks
to Immich. Point the app at `http://captioner:8092/v1` in the same namespace.
`caption_concurrency` defaults to 1, which is what a CPU captioner wants; raise it to 4 on a card.
The recipe, the flags that carry the contract and the measured per-picture cost are on the
[caption server page](https://sam-dumont.github.io/immich-video-memory-generator/docs/better/captions).

## PostgreSQL

`overlays/postgres` is not referenced by `base/kustomization.yaml`; the base keeps running on the
default SQLite file with no change. It patches `IMMICH_MEMORIES_DATABASE_URL` (and
`IMMICH_MEMORIES_DATABASE_SCHEMA`) onto the Deployment from a second Secret, so the store opens a
PostgreSQL database instead — a separate service, a separate database on your Immich instance, or a
dedicated schema inside Immich's own database. It does not run PostgreSQL for you.

```bash
cd deploy/kubernetes/overlays/postgres
cp database-secret.yaml.example database-secret.yaml
vim database-secret.yaml   # IMMICH_MEMORIES_DATABASE_URL
kubectl apply -k .
```

The four modes, and the exact SQL for the dedicated-schema one, are on
[Database and the store](https://sam-dumont.github.io/immich-video-memory-generator/docs/run/database).

## Ingress

Not shipped by default because auth is off. Enable auth first (basic auth keys in the Secret, or
OIDC), then `cp base/ingress.yaml.example base/ingress.yaml`, set the host, and add
`- ingress.yaml` to `base/kustomization.yaml`.

## Sealed Secrets

```bash
brew install kubeseal
kubectl apply -f base/namespace.yaml
secret_file=$(mktemp)
cat base/secret.yaml.example > "$secret_file"   # fill in, then seal
kubeseal --format=yaml < "$secret_file" > sealed-secret.yaml
rm "$secret_file"
kubectl apply -f sealed-secret.yaml
```

## Backups

`store.db` on the cache PVC is the expensive part: every caption, head answer,
detector verdict and reading the editor has banked. Lose it and the next cut re-reads the library.
Back up the PVC.

`immich-memories store backup` copies the store (decisions, model answers, run history) to one
file; `store restore` puts it back.
