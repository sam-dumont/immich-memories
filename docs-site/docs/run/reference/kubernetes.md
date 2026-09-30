---
title: "Kubernetes topology and add-ons"
---

# Kubernetes topology and add-ons

## Another namespace

Every manifest says `immich-memories`, but the namespace is yours to pick. To deploy under another
name, set it in each kustomization root you apply, before the first apply:

```bash
cd deploy/kubernetes
for d in base overlays/inference overlays/captioner overlays/inference-lan; do
  (cd "$d" && kustomize edit set namespace photos-memories)
done
```

That renames the Namespace object `base/` creates too. `overlays/gpu`, `overlays/inference-cuda`
and `overlays/captioner-cuda` build on those roots and follow them. Three things do not: the
`-n immich-memories` in every command on these pages, `base/job.yaml` applied with
`kubectl apply -f` (that skips kustomize), and the cross-namespace addresses, which become
`captioner.photos-memories.svc.cluster.local` and so on.


## How the pod is wired

The image runs as `immich`, UID/GID 1000, `HOME=/home/immich`. The manifests set `runAsUser` and
`fsGroup` 1000, drop all capabilities, use the `RuntimeDefault` seccomp profile and mount the root
read-only. Four writable paths:

| Mount | Backed by | Holds |
|---|---|---|
| `/home/immich/.immich-memories` | PVC `immich-memories-cache` | `config.yaml`, `store.db` (the store when it is SQLite: banked facts, readings, your picture decisions, people, run history, automation state, special days), video cache (a `cache.db` there is a pre-store leftover, imported once) |
| `/app/output` | PVC `immich-memories-output` | generated videos |
| `/models` | PVC `immich-memories-models` | pinned model files `immich-memories models fetch` writes, at `IMMICH_MEMORIES_TRIAGE__ENCODER`, `..._MARQO_ONNX`, `..._DETECTOR_CACHE_DIR` and `IMMICH_MEMORIES_FREE_TEXT__WORDNET` |
| `/tmp` | emptyDir 4Gi | FFmpeg intermediates; 8Gi for 4K |

A deployment that predates the models claim has to add it before the next apply, or the pod stays
`Pending` waiting for a volume that does not exist.

Every pod spec here sets `enableServiceLinks: false`. Kubernetes injects one env var per Service
in the namespace by default (`<NAME>_SERVICE_HOST`, `<NAME>_PORT`, ...), and this app's own
`IMMICH_MEMORIES_*` prefix collides with its own Service names. A Service named
`immich-memories-render-worker` injects `IMMICH_MEMORIES_RENDER_WORKER_PORT=tcp://10.x.x.x:8093`,
which the worker's settings then read as its own `port` field and crash on:

```text
port
  Input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='tcp://…:8093', input_type=str]
```

The main app carries the same risk from a Service named `immich-memories` (`IMMICH_MEMORIES_PORT`,
`IMMICH_MEMORIES_SERVICE_HOST`, ...). If you write your own manifest instead of using these, copy
`enableServiceLinks: false` onto every pod spec too.

The base has no ConfigMap; the maximalist overlay adds one. `IMMICH_URL`, `IMMICH_API_KEY` and any other secret setting come from the
Secret (`envFrom`); everything else is an `IMMICH_MEMORIES_<SECTION>__<KEY>` env var on the
Deployment, which carries commented examples for the reader and the daily automation. Settings
saved from the UI go to the store (`store.db` on the PVC by default); env vars override them
([where a setting comes from](.././config-file.md#where-a-setting-comes-from)).

The NetworkPolicy allows egress to DNS, 80 and 443, Immich on 2283, a reader on 11434 (Ollama's
port; oMLX serves on 8000) and the caption server on 8092. Edit the ports if yours differ.


## GPU

Intel Quick Sync and AMD VA-API need `/dev/dri` in the pod, which takes a device plugin these
manifests do not ship; without one the encode runs on the CPU.
`overlays/gpu/deployment-gpu.yaml` patches the Deployment with `runtimeClassName: nvidia`, one
`nvidia.com/gpu`, the two `NVIDIA_*` env vars, the `nvidia.com/gpu.present=true` node selector and
the matching toleration. The app uses that card for NVENC encoding and the title kernels and
nothing else. The editor's optional services run separately; classifiers and Demucs share the inference service, and captions can reuse its CUDA image. See [container boundaries](../../better/inference.md#what-shares-a-container). When the card
cannot start the title kernels, titles still render, on the CPU, and the log says why in one warning
line.


## Render worker as a sidecar

The [render worker](../../better/gpu-render.md) moves the render to an NVIDIA card. Its request carries
your Immich key, so the app only talks plain HTTP to it over loopback; anywhere else it wants
HTTPS or `render.allow_insecure_http: true`. `overlays/render-sidecar` sidesteps both: the worker
runs as a second container in the app's own pod, and the app reaches it at `http://127.0.0.1:8093`.

```bash
cd deploy/kubernetes
cp base/secret.yaml.example base/secret.yaml
cp overlays/render-sidecar/render-worker-secret.yaml.example overlays/render-sidecar/render-worker-secret.yaml
vim base/secret.yaml overlays/render-sidecar/render-worker-secret.yaml   # openssl rand -hex 32 for the token
kubectl apply -k overlays/render-sidecar
```

Three things to know:

- **The whole pod goes to the GPU node**, even though the app container needs no GPU. The overlay
  sets `runtimeClassName: nvidia` and a `nvidia.com/gpu.present: "true"` node selector: change the
  selector to the label your GPU node carries.
- **Keep the two image tags equal.** The overlay pins the worker's tag in its own
  `kustomization.yaml` (the base pin does not reach a container a patch adds), and the app refuses
  a worker on another version before it sends any footage.
- **One Secret, one token, both sides.** `immich-memories-render-worker` holds it; the worker reads
  it as `IMMICH_MEMORIES_RENDER_WORKER_TOKEN`, the app as `IMMICH_MEMORIES_RENDER__WORKER_TOKEN`
  (`render.worker_token`). No `config.yaml` change.

The worker binds loopback only, so its probes run inside the container (`exec`) instead of
`httpGet` or `tcpSocket`, which the kubelet sends to the pod IP. Keep them that way if you edit the
overlay, or the pod never goes Ready.


## The two model services

Both apply on their own, with no Secret and no `base/`. On a cluster where `base/` has not run
yet, create the namespace first (`kubectl create namespace immich-memories`):

```bash
kubectl apply -k deploy/kubernetes/overlays/inference    # heads and detectors, -cuda for a card
kubectl apply -k deploy/kubernetes/overlays/captioner    # the caption server the gpu and full tiers need
```

Point the app at them with `IMMICH_MEMORIES_INFERENCE__FACTS_BASE_URL=http://inference:8092` and
`IMMICH_MEMORIES_EDITORIAL__PREPARATION__CAPTION_BASE_URL=http://captioner:8092/v1` (two
underscores between levels); the base NetworkPolicy already allows egress on 8092. What each overlay patches, and what a card is worth per picture, are on
[the inference service](../../better/inference.md) and [Caption server](../../better/captions.md).

Two add-ons have no overlay here: the reader (commented env vars on the Deployment,
[Add a reader](../../better/reader.md)) and generated music (a server of your own,
[Generated music](../../better/music.md)). The render worker has two: the sidecar above, or its own
Deployment from `services/render-worker/kubernetes.yaml` ([Render on a GPU box](../../better/gpu-render.md)).
Each outside service is a URL on the Deployment; open its port in the NetworkPolicy if it is not
80, 443, 8092 or 11434.


## Batch jobs

`base/job.yaml` holds a one-off `generate` Job and two CronJobs (an automation trigger on the 1st,
and another daily). Uncomment `- job.yaml` in the kustomization.

The store defaults to a SQLite file on the `immich-memories-cache` PVC, one writer at a time; a second pod on
another node writing that file over `ReadWriteMany` corrupts it (WAL mode needs shared memory a
network filesystem does not give two hosts). So the two CronJobs never mount the PVCs: they `curl`
the Deployment's `POST /api/trigger` route instead, running whatever decision `auto run` would have
made. Set `IMMICH_MEMORIES_SERVER__TRIGGER_TOKEN` in `base/secret.yaml` first, or use the in-process
daily timer (`IMMICH_MEMORIES_AUTOMATION__ENABLED=true` on the Deployment) and skip the CronJob
entirely. The one-off `generate` Job still mounts the PVCs directly, since the trigger route takes
no `--year`/`--person` parameters: prefer
`kubectl exec deploy/immich-memories -- immich-memories generate ...` against the running
Deployment, and keep the Job for a batch cluster where the Deployment stays scaled to 0 between
runs.

Whichever clock fires it, the daily film stays on the output PVC unless upload is on
([Getting the films](../kubernetes.md#getting-the-films)); `IMMICH_MEMORIES_AUTOMATION__UPLOAD_TO_IMMICH=true`
uploads the daily runs only. The trigger route itself: [Trigger it over HTTP](../../make/automate.md#trigger-it-over-http).


## Database

The store defaults to a SQLite file on the cache PVC. `overlays/postgres` is not referenced by
`base/kustomization.yaml`, so applying `base` alone keeps that default. To put the store on
PostgreSQL:

```bash
cd deploy/kubernetes
cp overlays/postgres/database-secret.yaml.example overlays/postgres/database-secret.yaml
vim overlays/postgres/database-secret.yaml   # IMMICH_MEMORIES_DATABASE_URL, and the schema if shared
kubectl apply -k overlays/postgres           # instead of base, not after it
```

The overlay builds on `base/` and only adds the database Secret to the Deployment; it does not run
PostgreSQL for you. It and `overlays/gpu` each build on `base/`, so applying one after the other
drops the first one's patch. For both, make one overlay of your own: copy the two patch files and
`database-secret.yaml` into it, next to a kustomization whose resources are `../../base` and `database-secret.yaml`, with both
patches. The one-off `generate` Job in `base/job.yaml` does not get the database Secret either;
add the second `secretRef` there if you run it. The four modes, and the SQL for a dedicated schema
in Immich's own database, are on [Database and the store](.././database.md).


## PostgreSQL network policy

The PostgreSQL overlay does not add 5432 to the base egress policy. Before applying it, add this
strategic merge patch to your combined overlay's `patches:` list. It preserves the existing egress
rules and permits PostgreSQL on 5432 (adjust if your server uses another port):

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: immich-memories
  namespace: immich-memories
spec:
  egress:
    - ports:
        - {port: 53, protocol: UDP}
        - {port: 53, protocol: TCP}
    - ports:
        - {port: 80, protocol: TCP}
        - {port: 443, protocol: TCP}
    - ports:
        - {port: 2283, protocol: TCP}
    - ports:
        - {port: 11434, protocol: TCP}
        - {port: 8092, protocol: TCP}
    - ports:
        - {port: 5432, protocol: TCP}
```

This base policy restricts ports, not destination hosts. Add `to:` selectors or CIDRs if you need
host-level boundaries. [Network and security](../network-security.md) covers proxy and custom ports.
