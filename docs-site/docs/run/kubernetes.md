---
title: Kubernetes
---

import DeploymentDiagram from '@site/src/components/DeploymentDiagram';

# Kubernetes

For an existing cluster with persistent storage. [Docker Compose](./docker.md) is the simpler
install. The Kustomize manifests live in `deploy/kubernetes/`; CI renders them but does not deploy
them to a live cluster. [Requirements](./requirements.md) explains platform and memory constraints.

## Supported deployment paths

Use the shipped Kustomize manifests, or the existing [Terraform module](./terraform.md) if
you manage Kubernetes resources with Terraform. Kustomize keeps the one-replica app,
SQLite's persistent volume and the model-fetch init container together in the supplied base.
Terraform has its own inputs and resources; its differences are documented on that page.

There is no project Helm chart or maintained `app-template` values file.
If you need a Helm path, [ask for it](https://github.com/sam-dumont/immich-video-memory-generator/issues/new)
and describe your setup. Helm support will be considered when people request it.

## Prerequisites

- Immich reachable from the cluster, normally port 2283.
- A storage class for three `ReadWriteOnce` PVCs: data/cache 30Gi, output 50Gi, models 5Gi.
- For NVIDIA overlays: GPU Operator, `nvidia` RuntimeClass and labelled GPU nodes.

The default is one CPU-only app, with SQLite on the data PVC. Use local/block storage for SQLite,
not NFS/SMB. Keep `replicas: 1` even with PostgreSQL: the UI has in-process state.

<DeploymentDiagram topology="basic" />

## Quick start

Download/extract the deployment bundle from your chosen
[release](https://github.com/sam-dumont/immich-video-memory-generator/releases). Its image pins
match that release. If using a source checkout instead, check `base/kustomization.yaml`: committed
pins can trail releases. Image tags have no `v` prefix.

```bash
cd deploy/kubernetes
cp base/secret.yaml.example base/secret.yaml
# Edit IMMICH_URL and IMMICH_API_KEY in base/secret.yaml.
kubectl kustomize base
kubectl apply -k base
kubectl rollout status -n immich-memories deploy/immich-memories
```

For a source checkout, set the image before applying:

```bash
(cd base && kustomize edit set image ghcr.io/sam-dumont/immich-video-memory-generator=:X.Y.Z)
```

The `kustomize edit` command requires the standalone Kustomize CLI; `kubectl kustomize` only
builds. You can also edit `images[].newTag` in `base/kustomization.yaml` by hand.

The init container fetches model files needed by its configuration. Its guard includes GPU
detector files, so NAS runs fetch again on every start; existing files are digest-checked rather
than blindly downloaded. Before the first film,
check the running app's actual tier and requirements:

```bash
kubectl exec -n immich-memories deploy/immich-memories -- immich-memories models fetch
kubectl exec -n immich-memories deploy/immich-memories -- immich-memories preflight
kubectl port-forward -n immich-memories svc/immich-memories 8080:80
```

Open `http://localhost:8080`. Set home coordinates and timezone below, then make
[your first film](../get-started/first-film.mdx).

:::caution Keep it private until login works
Authentication is disabled by default. Do not expose the Service or add an Ingress before
[enabling authentication](./authentication.mdx). Keep one UI replica.
:::

## Home base, time zone and the first cut

Add these to the Deployment's `env` (or your overlay), so future applies keep them:

```yaml
- name: IMMICH_MEMORIES_TRIPS__HOMEBASE_LATITUDE
  value: "50.8503"
- name: IMMICH_MEMORIES_TRIPS__HOMEBASE_LONGITUDE
  value: "4.3517"
- name: TZ
  value: Europe/Brussels
```

Home coordinates enable trips and local public holidays. Then
[confirm your family once](../get-started/who-is-who.md).

## Getting the films

The web Render panel can upload to Immich. To default CLI/daily films to upload, set
`IMMICH_MEMORIES_UPLOAD__ENABLED=true` and optionally `IMMICH_MEMORIES_UPLOAD__ALBUM_NAME`.
The key needs [upload permissions](./docker.md#the-api-key).

For local films, copy from the output PVC:

```bash
kubectl get pods -n immich-memories
kubectl cp immich-memories/<pod>:/app/output ./output
```

Confirmed uploads remove their local film; local-only and failed deliveries keep theirs.

## Authentication and Ingress

Add Basic-auth credentials to the Secret, or configure [OIDC](./authentication.mdx#oidc--sso).
Then copy `base/ingress.yaml.example`, set its host/TLS settings and list it in your kustomization.
Use the [proxy trust/cookie checklist](./authentication.mdx#behind-a-reverse-proxy-with-tls).

## How the pod is wired

The app runs as UID/GID 1000 with `fsGroup: 1000`, dropped capabilities, RuntimeDefault seccomp
and a read-only root.

| Path | Storage |
|---|---|
| `/home/immich/.immich-memories` | Data/cache PVC: store, settings, session key, previews, clips and Laya files |
| `/home/immich/.cache` | The same data PVC, mounted again: writable persistent Torch/HF runtime caches |
| `/app/output` | Output PVC: local films |
| `/models` | Models PVC: encoder, WordNet, sensitive-content export and detector cache |
| `/tmp` | 4Gi emptyDir; allow more for 4K |

The app requests 2Gi RAM and one CPU, with limits of 8Gi and four CPUs. The fetch init
container requests 512Mi/250m and is capped at 2Gi/two CPUs. Compose's app limit is 4 GB;
these are different budgets. The 30Gi data claim leaves room beyond the two default 10 GB
preview/video caches. Existing claims do not automatically grow: your StorageClass must allow
expansion, or lower the cache caps until you can resize it.

Base settings come from environment variables and the Secret. Settings saves go to the store;
[environment variables win](./config-file.md#where-a-setting-comes-from).

Keep `enableServiceLinks: false` on every custom pod spec. Service names can otherwise inject
`IMMICH_MEMORIES_*` variables that the app mistakes for configuration and fails to parse.
Keep `automountServiceAccountToken: false` too: nothing in these pods calls the Kubernetes API,
so none of them needs a token for it.

## NetworkPolicy

The base policy allows DNS and TCP ports 80, 443, 2283, 11434 and 8092 to any destination.
A separate rule permits 8080 only to app pods with the `web-ui` component in the same namespace: trigger CronJobs
call Service port 80, which is translated to that backend port.

Ingress allows 8080 without a source selector, so any pod in the cluster can reach the
unauthenticated app. This is not a trusted-pod allow-list. Keep it private until authentication
works and add your own source/destination selectors when you need stricter isolation.
Add the actual ports of your services: 8000 or 9999 for your reader configuration, PostgreSQL
5432 and a separate render worker's 8093. oMLX's port is configurable; the maximalist example
uses 9999. The CNI must enforce NetworkPolicy for any of these rules to matter.

## GPU

For **video encoding/title effects**, apply `overlays/gpu` instead of `base`. It reserves one
NVIDIA GPU for the app. It does not start inference or caption services.
Intel/AMD device plugins and `/dev/dri` mapping are not supplied by these manifests.

## Automatic product tiers {#set-the-preparation-tier}

For **GPU picture preparation**, deploy the model services and point the app at them:

```bash
kubectl apply -k overlays/inference-cuda
kubectl apply -k overlays/captioner-cuda
```

```yaml
- name: IMMICH_MEMORIES_INFERENCE__FACTS_BASE_URL
  value: http://inference:8092
- name: IMMICH_MEMORIES_EDITORIAL__PREPARATION__CAPTION_BASE_URL
  value: http://captioner:8092/v1
```

CPU service variants are `overlays/inference` and `overlays/captioner`. The CUDA captioner
deliberately requests no `nvidia.com/gpu`; it depends on device sharing/time-slicing and has no
scheduler GPU reservation. Configure that on your cluster or add a GPU request on a separate
card. Applying the overlay alone does not make a GPU available.
The default `tier: auto` sees GPU inference separately from encoding.
Add an explicitly enabled [external reader](../better/reader.md) for Full. The app image has no
owned `llama-server`. One `advanced.llm` configuration serves titles, selection, music mood,
special days and explicitly opted-in LLM captions. The commented Deployment recipe uses native
Ollama and `options.num_ctx: 32768`; the `/v1` route needs server-side context configuration. After changing tier/services, run `models fetch` in
the app again for required detectors/Laya, then `preflight`.
[Requirements](./requirements.md#which-tier-you-get) explains the resolver.

## Render worker as a sidecar

`overlays/render-sidecar` puts a worker in the same pod, on an NVIDIA node.
It receives the Immich API key over pod loopback `http://127.0.0.1:8093`.
Copy its `render-worker-secret.yaml.example` to `render-worker-secret.yaml`, set both `token`
(`openssl rand -hex 32`) and `immich-url` to the app's configured Immich server, then apply the
overlay. The request carries selected partner API keys, names, home coordinates and network
settings too; run the worker where those credentials and facts may be read.

Keep app and worker image tags equal. The worker binds loopback, so its probes must use `exec`,
not kubelet HTTP/TCP probes to the pod IP. [Render worker](../better/gpu-render.md) covers remote
workers and transport protection.

### A separate render Deployment

From a source checkout, `services/render-worker/kubernetes.yaml` supplies a separate NVIDIA
Deployment and ClusterIP Service on 8093. Pin its Deployment image to the app's version and
create the `immich-memories-render-worker` Secret with `token` and `immich-url` in that namespace
before applying it. The worker receives per-job Immich credentials from the app; they do not go
in this Secret. Its scratch, state and compilation caches are disposable emptyDir volumes.

Point the app at `http://immich-memories-render-worker:8093` and use the same bearer token.
That private cleartext route needs `render.allow_insecure_http: true` and an app egress rule for
8093; use a TLS endpoint instead when the network is not trusted. Add a worker ingress policy
for your callers. The standalone worker's labels differ from the app's, so the base app policy
does not select it. Its TCP probe confirms a listening port; run the authenticated `/health`
check from the [worker guide](../better/gpu-render.md) to check capabilities.

## The two model services

Inference and caption overlays can also run independently for another app deployment. Create the
namespace first if the base is not deployed. Reader/music servers are not provided by the base.
See [Inference](../better/inference.md), [Captions](../better/captions.md) and [Music](../better/music.md)
for model/service configuration.

## Database

For PostgreSQL, fill in `overlays/postgres/database-secret.yaml` from its example and apply that
overlay instead of base. It connects to an existing PostgreSQL; it does not deploy one.
[PostgreSQL modes](./reference/database.md) gives the database/role SQL.

Add PostgreSQL egress in your own overlay. For example, build on `../postgres` and add this
inline patch to `patches:`:

```yaml
- target:
    kind: NetworkPolicy
    name: immich-memories
  patch: |-
    - op: add
      path: /spec/egress/-
      value:
        ports:
          - port: 5432
            protocol: TCP
```

Use your server's port. The existing app overlays remain alternatives when applied separately.
To combine GPU, PostgreSQL and a render sidecar, build one root from the components:

```bash
mkdir -p deploy/kubernetes/custom
cp deploy/kubernetes/overlays/postgres/database-secret.yaml.example deploy/kubernetes/custom/database-secret.yaml
cp deploy/kubernetes/overlays/render-sidecar/render-worker-secret.yaml.example deploy/kubernetes/custom/render-worker-secret.yaml
```

Fill in those two Secrets, then save `deploy/kubernetes/custom/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../base
  - database-secret.yaml
  - render-worker-secret.yaml
components:
  - ../components/gpu
  - ../components/postgres
  - ../components/render-sidecar
```

Remove any component and Secret you do not need. The GPU component reserves a GPU for the app;
the sidecar also reserves its own GPU. Combining both therefore needs two allocatable GPUs.
Keep the base Secret configured and add database/reader egress for your actual ports in this root.
The optional `../components/reader-egress` adds TCP 8000 for an external reader such as oMLX;
it does not restrict the destination or start a reader. Change the port if yours differs, and
configure `advanced.llm.enabled: true`, its URL and model explicitly.
`kubectl kustomize deploy/kubernetes/custom` previews the result;
`kubectl apply -k deploy/kubernetes/custom` applies one Deployment with all chosen options.
The existing `overlays/gpu`, `overlays/postgres` and `overlays/render-sidecar` paths are thin
wrappers over these components, so existing apply commands still work.

## Batch jobs

`base/cronjobs.yaml` is optional and contains only scheduled HTTP triggers. Add
`- cronjobs.yaml` to `base/kustomization.yaml`, render, then apply that root. They call
`POST /api/trigger` on the running app and mount no application PVCs. Set `IMMICH_MEMORIES_SERVER__TRIGGER_TOKEN` in the Secret.
Both schedules invoke the automatic decision, even the job named monthly: they do not force a
monthly film. The Service selects only `web-ui` pods, so a Ready curl Job is never used as an
HTTP backend.

For a fixed recipe, prefer `kubectl exec ... -- immich-memories generate ...`.
The separate `base/job.yaml` contains only the one-off generate Job. It mounts the PVCs
directly; use it with the Deployment scaled to zero. Never include it just to enable schedules.
If using PostgreSQL, add its Secret to that Job too. Include `job.yaml` in Kustomize so its app
image follows the selected tag; a raw `apply -f` bypasses image transformations.

Or enable the app's [daily timer](../make/automate.md) and skip CronJobs entirely.

## Backups

```bash
kubectl exec -n immich-memories deploy/immich-memories -- immich-memories store backup
kubectl cp immich-memories/<pod>:/home/immich/.immich-memories/backups ./backups
```

Keep the manifest/encryption key. [Restore](./database.md#restore-in-a-container) needs the
Deployment stopped. Caches are disposable; the store is not.

## Probes

Liveness uses `/health/live`; readiness uses `/health/ready`, which returns 503 when Immich/config
is unavailable. `/health` always returns 200 and must not be used as a probe.
[Diagnostics](./maintenance/health-logs-cache.md#health-endpoints) gives response/access details.

## Logs

```bash
kubectl logs -n immich-memories deploy/immich-memories -c immich-memories -f
```

For init failures, use `-c fetch-models`. [Diagnostics](./maintenance/health-logs-cache.md#logging)
has per-run paths and logging variables.

## Upgrading and rollback

Releases attest each platform image digest. Verify the exact platform digest you intend to run
with GitHub CLI (authenticate to GHCR first):

```bash
gh attestation verify "oci://ghcr.io/sam-dumont/immich-video-memory-generator@sha256:<digest>" --repo sam-dumont/immich-video-memory-generator
```

Replace `<digest>` with the platform image's SHA-256 value. Use the inference image's
repository path for that image. Verification checks its recorded
provenance; it does not check your cluster configuration or the model's answers.

Back up, change pins in the base **and any add-on overlays**, render the same kustomization you
installed, then apply it. Run `models fetch` and `preflight` in the updated app.
The init guard checks presence only, so existing files do not prove new pins match.
[Rollback](./maintenance/upgrading.md#rollback) requires the old store backup when its schema changed.

## Another namespace

Set `namespace:` in each kustomization root you apply. Update command `-n` arguments and any
cross-namespace URLs too. Applying raw YAML bypasses the namespace transformation.

## Check it from outside the pod

Use the quick-start `kubectl exec ... preflight` command after service changes. The
[distributed-services guide](./reference/cluster-example.md) shows how to compose separate services.

## The models the first cut needs

Model requirements follow the selected tier. [Model files](./maintenance/health-logs-cache.md#model-files)
lists the fetch options. Run fetch from the app's configuration after adding GPU/Full services.

## Distribute work across services

[Distributed services on Kubernetes](./reference/cluster-example.md) explains GPU allocations,
service boundaries and the shipped composition example. Use it when you need separate placement;
start with the basic install first.
