---
title: "Kubernetes topology and add-ons"
---

# Kubernetes topology and add-ons

## Bring your own Secret

The base references `immich-memories-secrets` in namespace `immich-memories`; it no longer
creates a Secret. Create it before starting the Deployment. No manifest edits are needed
when your SOPS, Sealed Secrets or External Secrets workflow produces that name.

| Key | When needed |
|---|---|
| `IMMICH_URL`, `IMMICH_API_KEY` | Always; the Immich server and its scoped API key |
| `IMMICH_MEMORIES_AUTH_USERNAME`, `IMMICH_MEMORIES_AUTH_PASSWORD` | Basic UI login |
| `IMMICH_MEMORIES_SECRET_KEY` | Stable encryption key for credentials saved in Settings |
| `IMMICH_MEMORIES_STORAGE_SECRET` | Optional stable web session signing key |
| `IMMICH_MEMORIES_SERVER__TRIGGER_TOKEN` | Scheduled HTTP triggers; generate with `openssl rand -hex 32` |
| `IMMICH_MEMORIES_RENDER__WORKER_TOKEN` | App authentication to a render worker |
| `IMMICH_MEMORIES_DATABASE_URL` | PostgreSQL instead of SQLite |

Other secret environment settings can use the same Secret. Explicit Deployment `env` values
win over `envFrom`. The render-sidecar overlay additionally expects
`immich-memories-render-worker` with keys `token` and `immich-url`; the PostgreSQL overlay
expects its own database Secret. Keep their separate contracts when using those overlays.

An isolated RKE2 run verified the generated custom Kustomize path with a separately created,
nondefault Secret name and matching app reference. The cached `75077f27` candidate started with
fresh ephemeral storage, downloaded NAS models, reached the synthetic Immich fixture, and saved
then reloaded an encrypted Settings credential. The synthetic setting and namespace were removed.

### Verified Terraform runs

Two isolated RKE2 runs applied module revision `53fc813793` with a nondefault existing Secret
and fresh local XFS PVCs:

- The exact `75077f27` candidate run applied with `replicas = 0`, then used a recorded test-only
  `Never` image policy, node pin and scale to one replica. Separate readiness, Immich connectivity,
  preflight (5 OK, 4 warnings, 9 skipped) and encrypted Settings save/reload passed. The initial
  zero-replica apply alone did not validate rollout.
- The published `0.103.0` run applied the unchanged module with one replica from the start,
  without workload patches. Rollout and Immich connectivity passed. This older app predates the
  tier bootstrap, so its default caption check failed; selecting `no_captions` through the module's
  existing environment input and applying again passed preflight (5 OK, 2 warnings, 4 skipped).

Neither external API key nor Settings encryption key appeared in either private Terraform state;
no Terraform Secret resource was created. Both states were destroyed and their separately created
namespaces, Secrets and claim-UID-verified PVs were removed. These runs do not test a live SOPS or
External Secrets provider. Managed/existing modes also have mocked-provider plan checks.

### SOPS

Use your existing [SOPS](https://getsops.io/docs/) age/KMS recipient and decrypt only when
applying. `mktemp` creates a private mode-0600 file; writing the example into it keeps that
mode. Remove it after applying or encrypting. These commands create the namespace first and
never add plaintext to the base resources:

```bash
kubectl apply -f base/namespace.yaml
secret_file=$(mktemp)
cat base/secret.yaml.example > "$secret_file"
# Edit "$secret_file" outside Git; include the keys your setup needs.
sops --encrypt --age YOUR_AGE_RECIPIENT --encrypted-regex '^(data|stringData)$' \
  "$secret_file" > secret.sops.yaml
rm "$secret_file"
sops --decrypt secret.sops.yaml | kubectl apply -f -
kubectl apply -k base
```

Store only the encrypted file in Git, outside the default base resources. `kubectl kustomize`
does not decrypt SOPS; a GitOps controller must have SOPS decryption configured before applying
it. Do not let a controller apply the encrypted values as ordinary credentials.

### External Secrets

Requires an installed [External Secrets Operator](https://external-secrets.io/latest/api/externalsecret/)
and your already configured `ClusterSecretStore`. This v1 example maps two remote properties:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: immich-memories
  namespace: immich-memories
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: YOUR_EXISTING_STORE
    kind: ClusterSecretStore
  target:
    name: immich-memories-secrets
    creationPolicy: Owner
  data:
    - secretKey: IMMICH_URL
      remoteRef: {key: YOUR_REMOTE_RECORD, property: url}
    - secretKey: IMMICH_API_KEY
      remoteRef: {key: YOUR_REMOTE_RECORD, property: api_key}
```

Add mappings for auth, trigger, encryption or database keys you need. Confirm your installed
CRD serves `external-secrets.io/v1`; use its supported API version otherwise. Create the namespace,
apply this resource, then wait for `kubectl wait --for=condition=Ready externalsecret/immich-memories
-n immich-memories` before applying the base. Environment-based credentials are read on pod start;
restart the app Deployment after rotation. These examples are rendered/checked locally, not tested
against a live secret provider. Share your operator/version and rollout results in
[#1800](https://github.com/sam-dumont/immich-memories/issues/1800).

### Terraform

Set `existing_secret_name = "immich-memories-secrets"` to use a Secret in `namespace` instead
of having Terraform create one. Omit `immich_url`, `immich_api_key` and `secret_env`; credential
inputs are ignored in this mode, and their values need not enter Terraform state. Supply all
required keys in the existing Secret, including the render token and `IMMICH_URL` when the
sidecar is enabled. Keep nonsecret settings in `env`; for an external PostgreSQL URL also set
`IMMICH_MEMORIES_DATABASE_SCHEMA` there if you use a custom schema.

For an existing Terraform-managed installation, do not just flip this variable: removing the
managed resource plans its deletion. Transfer ownership with your normal Terraform state
migration procedure before switching, then inspect the plan. This option does not read, rotate
or validate the contents of the existing Secret.

## Another namespace

Every manifest says `immich-memories`, but the namespace is yours to pick. To deploy under another
name, set it in each kustomization root you apply, before the first apply:

```bash
cd deploy/kubernetes
for d in base overlays/*; do
  (cd "$d" && kustomize edit set namespace photos-memories)
done
```

This needs the standalone `kustomize` CLI; `kubectl kustomize` can build but cannot edit.
The loop changes every root, including `render-sidecar`, `postgres` and `maximalist`, so their
Secrets move with their Deployments and the maximalist namespace does not override your choice.
It also renames the Namespace object that `base/` creates. Render each root you use before applying.

Update `-n immich-memories` in commands and cross-namespace addresses such as
`captioner.photos-memories.svc.cluster.local`. Raw `kubectl apply -f` bypasses all namespace
transformations; include optional Jobs or CronJobs in a kustomization instead.


## How the pod is wired

The image runs as `immich`, UID/GID 1000, `HOME=/home/immich`. The manifests set `runAsUser` and
`fsGroup` 1000, drop all capabilities, use the `RuntimeDefault` seccomp profile and mount the root
read-only. Five writable paths:

| Mount | Backed by | Holds |
|---|---|---|
| `/home/immich/.immich-memories` | PVC `immich-memories-cache` | `config.yaml`, `store.db` (the store when it is SQLite: banked facts, readings, your picture decisions, people, run history, automation state, special days), video cache (a `cache.db` there is a pre-store leftover, imported once) |
| `/home/immich/.cache` | The same data/cache PVC mounted again | Torch/HF runtime caches; app and init containers can write here |
| `/app/output` | PVC `immich-memories-output` | generated videos |
| `/models` | PVC `immich-memories-models` | pinned model files `immich-memories models fetch` writes, at `IMMICH_MEMORIES_TRIAGE__ENCODER`, `..._MARQO_ONNX`, `..._DETECTOR_CACHE_DIR` and `IMMICH_MEMORIES_FREE_TEXT__WORDNET` |
| `/tmp` | emptyDir 4Gi | FFmpeg intermediates; 8Gi for 4K |

Laya files remain under the data PVC's `models/` directory. On native installs an owned
reader's GGUF also lives there; these app images have no `llama-server` and use an external reader.
The data claim defaults to 30Gi; the app is capped at 8Gi/four CPUs and model init at 2Gi/two CPUs.

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

The NetworkPolicy allows DNS, 80, 443, 2283, 11434 and 8092 without destination selectors.
It also allows 8080 to app pods with the `web-ui` component in the same namespace for the scheduled trigger calls.
Ingress on 8080 has no source selector; any cluster pod can reach the app. Add operator-owned
selectors when you need stricter isolation. Add ports for your external services: readers may
use 8000 or 9999 (the maximalist oMLX example uses 9999), and a separate render worker uses
8093. Enforcing these policies depends on your CNI.


## GPU

Intel Quick Sync and AMD VA-API need `/dev/dri` in the pod, which takes a device plugin these
manifests do not ship; without one the encode runs on the CPU.
`components/gpu/deployment-gpu.yaml` patches the Deployment with `runtimeClassName: nvidia`, one
`nvidia.com/gpu`, the two `NVIDIA_*` env vars, the `nvidia.com/gpu.present=true` node selector and
the matching toleration. The app uses that card for NVENC encoding and the title kernels and
nothing else. These overlays run separate services: classifiers and Demucs share inference; captions and the render sidecar have their own processes. The [unified CUDA worker](../reference-setup.md#one-gpu-service) is a separate Compose recipe, not part of these overlays. See [container boundaries](../../better/inference.md#one-nvidia-container). When the card
cannot start the title kernels, titles still render, on the CPU, and the log says why in one warning
line.


## Render worker as a sidecar

The [render worker](../../better/gpu-render.md) moves the render to an NVIDIA card. Its request carries
your Immich key, so the app only talks plain HTTP to it over loopback; anywhere else it wants
HTTPS or `render.allow_insecure_http: true`. `overlays/render-sidecar` sidesteps both: the worker
runs as a second container in the app's own pod, and the app reaches it at `http://127.0.0.1:8093`.

```bash
cd deploy/kubernetes
kubectl apply -f base/namespace.yaml
secret_file=$(mktemp)
cat base/secret.yaml.example > "$secret_file"
install -m 600 overlays/render-sidecar/render-worker-secret.yaml.example overlays/render-sidecar/render-worker-secret.yaml
vim "$secret_file" overlays/render-sidecar/render-worker-secret.yaml   # openssl rand -hex 32 for the token
kubectl apply -f "$secret_file"
rm "$secret_file"
kubectl apply -k overlays/render-sidecar
rm overlays/render-sidecar/render-worker-secret.yaml
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

`base/cronjobs.yaml` contains only the two HTTP-trigger schedules, one monthly and one daily.
Set the trigger token and uncomment `- cronjobs.yaml` in the kustomization, then render and
apply that root. The separate `base/job.yaml` contains only the one-off `generate` Job;
include it only with the Deployment scaled to zero.

The store defaults to a SQLite file on the `immich-memories-cache` PVC, one writer at a time; a second pod on
another node writing that file over `ReadWriteMany` corrupts it (WAL mode needs shared memory a
network filesystem does not give two hosts). So the two CronJobs never mount the PVCs: they `curl`
the Deployment's `POST /api/trigger` route instead, running whatever decision `auto run` would have
made. Set `IMMICH_MEMORIES_SERVER__TRIGGER_TOKEN` in the existing `immich-memories-secrets` Secret first, or use the in-process
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
PostgreSQL for you. For GPU plus PostgreSQL, list `components/gpu` and `components/postgres`
in one root alongside `base` and your database Secret. The
[composition recipe](../kubernetes.md#database) also shows the optional render sidecar.
The one-off `generate` Job in `base/job.yaml` does not get the database Secret either;
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
