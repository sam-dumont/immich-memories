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
If you need a Helm path, [ask for it](https://github.com/sam-dumont/immich-memories/issues/new)
and describe your setup. Helm support will be considered when people request it.

## Generated tier setup

The generated GPU path has run on RKE2 with an NVIDIA T1000: cold model initialization,
preflight, encrypted Settings save/reload and a complete first film passed, including full audio/video
decode. The [measured run](../better/measured.md#generated-gpu-first-film) records the 1080p output,
CUDA inference/captions, software encoding and corrected local/block SQLite storage. These checks
used a locally built candidate; they do not verify a published release download.

Use the [setup builder](/setup), select Kubernetes, and enter Immich's reachable URL and API key.
The builder uses the release version displayed on the page. It generates the Secret, namespace-scoped customization,
reader settings when Full is selected, and egress rules for the supplied endpoint ports.
Download each file and save it at its labelled path after extracting that release's bundle.
The generated commands render the exact manifests before applying them.

Basic uses the CPU base. GPU adds the existing CUDA inference and caption deployments through
`components/gpu-services`; Full adds an explicitly enabled external reader. These are requested
tiers. Preflight checks actual compute, captions, Laya and reader availability; a preset name
does not prove readiness. Service defaults stay below saved Settings. The app init container explicitly fetches the GPU
detectors and Laya checkpoint into the shared model PVC before startup; it verifies existing
artifact digests on subsequent starts.

The GPU wrapper requests one `nvidia.com/gpu`, for the inference service only. The captioner
requests none: it lands on a GPU node through the node selector and toleration, and relies on the
card being time-sliced. A cluster with one exclusive GPU therefore needs sharing configured, or
the captioner sits on a card it has not reserved. The app pod gets no GPU either: encoding
(libx264) and titles run on the CPU, and preflight warns "No GPU acceleration". On this tier the
GPU means picture preparation and captions only. To give the app pod a GPU too, add
`../components/gpu` to the `components:` of your `custom/kustomization.yaml` (see [GPU](#gpu)). The external Full reader has its own resource requirements.

Both model services remain ClusterIP; ingress and egress policies
are retained. Generated endpoint port rules are port permissions, not host allow-lists.

For manual Full configuration, copy `overlays/tier-full/reader-config.yaml.example` to
`reader-config.yaml`, set the actual served URL/model, and add its port to your app's egress
policy if it differs from the example TCP8000. A reader API key can be supplied in the app
Secret as `IMMICH_MEMORIES_DEPLOYMENT_READER_API_KEY`, or saved in Settings.

The rest of this page covers the manifests and manual operator changes.

## Prerequisites

- Immich reachable from the cluster, normally port 2283.
- A storage class for three `ReadWriteOnce` PVCs: data/cache 30Gi, output 50Gi, models 5Gi. The
  GPU tier adds two more, caption-models 2Gi and inference-cache 10Gi: five PVCs, 97Gi in total.
  Check the class's reclaim policy first: `Delete` removes the volumes with the namespace,
  `Retain` keeps them (and your store) for a reinstall.
- For NVIDIA overlays: GPU Operator, `nvidia` RuntimeClass and labelled GPU nodes.

The default is one CPU-only app, with SQLite on the data PVC. Use local/block storage for SQLite,
not NFS/SMB. Keep `replicas: 1` even with PostgreSQL: the UI has in-process state. Database leases
serialize CLI work; they do not synchronize multiple UI processes or make multiple replicas safe.

<DeploymentDiagram topology="basic" />

## Quick start

Create the Immich key with the [ten read permissions](./docker.md#the-api-key). Add the upload
set only when this account receives films; leave **All** unchecked. Put that scoped key in the
Secret below.

Download/extract the deployment bundle from your chosen
[release](https://github.com/sam-dumont/immich-memories/releases). Its image pins
match that release. If using a source checkout instead, check `base/kustomization.yaml`: committed
pins can trail releases. Image tags have no `v` prefix.

Using another namespace than `immich-memories`? Read [Another namespace](#another-namespace)
before you run these: `base/namespace.yaml` would create a stray `immich-memories` Namespace, and
every `-n immich-memories` below must change with it.

```bash
cd deploy/kubernetes
kubectl apply -f base/namespace.yaml
secret_file=$(mktemp)
cat base/secret.yaml.example > "$secret_file"
# Edit IMMICH_URL and IMMICH_API_KEY in "$secret_file" outside Git.
kubectl apply -f "$secret_file"
rm "$secret_file"
kubectl kustomize base
kubectl apply -k base
kubectl rollout status -n immich-memories deploy/immich-memories
```

The temporary Secret file is private (mode 0600); remove it after applying.
The base uses an existing `immich-memories-secrets` Secret. GitOps users can skip the plaintext
copy and use [SOPS or External Secrets](reference/kubernetes.md#bring-your-own-secret).

For a source checkout, set the image before applying:

```bash
(cd base && kustomize edit set image ghcr.io/sam-dumont/immich-memories=:X.Y.Z)
```

The `kustomize edit` command requires the standalone Kustomize CLI; `kubectl kustomize` only
builds. You can also edit `images[].newTag` in `base/kustomization.yaml` by hand.

The init container fetches model files needed by its configuration. Its guard includes GPU
detector files, so Basic runs fetch again on every start; existing files are digest-checked rather
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

### Rotating a key

Keys live in the Secret. Edit it (the generated `custom/secret.yaml`, or your own copy of
`base/secret.yaml.example`), apply, then restart the app, since pods do not pick up new
environment values on their own:

```bash
kubectl apply -k deploy/kubernetes/custom
kubectl rollout restart -n immich-memories deploy/immich-memories
```

On the GPU tier this took 36 seconds and restarted only the app pod. Rotate the Immich API key
this way. Leave `IMMICH_MEMORIES_SECRET_KEY` alone: changing it makes saved credentials unreadable (see
[the secret key](#keep-the-secret-key)).

### Keep the secret key

The setup builder generates `IMMICH_MEMORIES_SECRET_KEY` into the Secret. It seals the credentials
you save from Settings (the Immich key, the reader key) inside the store, so the same value has to
open the same rows later. Keep a copy outside the cluster. A restored store paired with a new key
cannot read its saved credentials, and you enter them again.

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

For local films, copy from the output PVC. Each film sits in its own run folder, so copy the
`.mp4` rather than the whole volume ([first film](../get-started/first-film.mdx)):

```bash
kubectl get pods -n immich-memories
kubectl exec -n immich-memories deploy/immich-memories -c immich-memories -- find /app/output -name '*.mp4'
kubectl cp -n immich-memories -c immich-memories <pod>:/app/output/<run folder>/<name>.mp4 ./film.mp4
```

A CLI render dies with the `kubectl exec` that started it. For a month or a year, run it detached
inside the pod, for example `kubectl exec ... -- sh -c 'nohup immich-memories runs render RUN_ID > /tmp/render.log 2>&1 &'`,
and check `immich-memories runs list` for the result.

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

Check the [service/GPU allocation table](./local-models.md#kubernetes-services) before choosing
a generated or independently managed route.

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
gh attestation verify "oci://ghcr.io/sam-dumont/immich-memories@sha256:<digest>" --repo sam-dumont/immich-memories
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
cross-namespace URLs too. Applying raw YAML bypasses the namespace transformation. That includes
the Quick start's `kubectl apply -f base/namespace.yaml` and the Secret you apply by file: create
your own namespace with `kubectl create namespace <name>` instead, and set `namespace:` in the
Secret. The setup builder always writes `immich-memories`; change it in the generated
`secret.yaml` and `kustomization.yaml` if you need another.

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

## Configuration ownership

For each field: runtime environment > operator `config.yaml` > saved Settings > deployment
service defaults > schema default. A command's flags can override its own run. In YAML, the
`advanced:` wrapper contains `auth`, `server`, `llm`, `editorial`, `inference` and other advanced
sections; runtime names in the table omit that wrapper. See the [complete field reference](../reference/config-reference.md).

| Group | Who controls it | Change / secret handling |
|---|---|---|
| `auth.*`, `server.*` | Environment or file only; ignored if saved by old Settings | Recreate/restart after changes; protect credentials in Kubernetes Secrets |
| `database.url`, `database.schema` | Environment/file bootstrap only | Stop writers before changing store; restart; keep the database URL secret |
| `immich.*`, `llm.*`, `editorial.preparation.*`, `inference.*`, `render.*` | Settings unless environment/file pins the key | Saved changes affect subsequent work; changed credential-bearing URLs require credential re-entry; recreate for environment changes |
| `tier`, `output.*`, `audio.*`, `trips.*`, `upload.*`, `automation.*` | Same precedence | Keep output/cache paths on actual mounts; restart after changing the running timer's deployment configuration |
| `IMMICH_MEMORIES_DEPLOYMENT_*` service wiring | Low-priority deployment defaults | Settings can override; these are not the normal high-priority runtime environment keys |

`${VAR}` interpolation happens **in the YAML file only**. Settings rejects literal secret
references; Kubernetes `env.value` does not shell-expand them. Inject an environment value from
`secretKeyRef`/`envFrom`, or let file interpolation read an injected secret. Keep ConfigMaps free
of literal secrets. Restart after updating environment-backed Secrets; existing pods do not pick
up new environment values. The [config source report](./config-file.md#where-a-setting-comes-from)
shows what wins.

The same data PVC is mounted at both `.immich-memories` and `.cache` without `subPath`, so both
paths expose the same volume root. This provides writable persistent runtime caches under a
read-only root; it does not isolate credentials from model code. SQLite, saved credentials and
session keys live there. The model PVC holds weights and the output PVC holds films.
Back up the store **and** keys using [backup/restore](./maintenance/storage-backups.md).

## Probes, outages and monitoring

| Endpoint | HTTP result | Dependency and operational consequence |
|---|---|---|
| `/health/live` | 200 while the web process responds | No Immich probe. Repeated liveness failures can restart the container |
| `/health/ready` | 200 ready; 503 missing/invalid config, unsupported API, failed authentication or unreachable Immich | Authenticated Immich access is required. Failure removes the pod from ready Service endpoints; Terraform can keep waiting even with a live web process |
| `/health` | 200 with detailed status payload | Read the body rather than treating HTTP 200 as readiness. Run/automation/disk detail is gated by the app session when auth is on |

During an Immich outage, inspect `kubectl logs`, pod events, the configured URL/key and NetworkPolicy.
Port-forward directly to `deployment/immich-memories` to diagnose a live but unready pod.
Restore authenticated Immich reachability and confirm `/health/ready` returns 200 and the Service
has ready endpoints again. Do not remove the readiness check to conceal dependency failures.
An outage/recovery test belongs on a disposable Immich endpoint, never the household server.

The app exposes **no Prometheus scrape or OpenTelemetry export endpoint** in this baseline.
Use the [existing JSON logs with run IDs](./maintenance/health-logs-cache.md), the health endpoints,
`runs show`, `report`, per-run timings and `llm-usage.json` for model-call usage.
The inference service's `/queue` reports that service's work, not app-wide metrics or readiness.
[Optional OpenTelemetry export (#656)](https://github.com/sam-dumont/immich-memories/issues/656)
remains separate work. Existing structured logging is available now.

## Resource requests, QoS and scratch

The shipped app pod is **Burstable**: app requests 1 CPU/2Gi versus limits 4 CPU/8Gi; fetch
init requests 250m/512Mi versus limits 2 CPU/2Gi. The [render memory model](./reference/rendering.md#memory-budget)
uses the container limit: 4 GiB permits one source-preparation worker; 8 GiB can permit two.
More RAM may increase parallel work; it does **not** enlarge disk-backed `/tmp`.

For a Basic pod on Kubernetes 1.33, add this strategic-merge patch to your overlay's `patches`
list to reserve the current ceilings rather than rely on spare node capacity:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: immich-memories
spec:
  template:
    spec:
      initContainers:
        - name: fetch-models
          resources:
            requests: {cpu: "2", memory: 2Gi}
            limits: {cpu: "2", memory: 2Gi}
      containers:
        - name: immich-memories
          resources:
            requests: {cpu: "4", memory: 8Gi}
            limits: {cpu: "4", memory: 8Gi}
```

For **Guaranteed** QoS, every ordinary container, init container and sidecar must have CPU and
memory requests equal to its limits. Add the same treatment to `write-config`, render sidecars
and injected mesh/agent containers when present; the Basic patch alone does not cover them.
These are [Kubernetes' container-level QoS rules](https://kubernetes.io/docs/tasks/configure-pod-container/quality-service-pod/).
Inspect the admitted pod's full resource specification and observed `.status.qosClass`, not just
your submitted patch. This example is not yet a live-cluster QoS result.

Reserving 4 CPU/8Gi can leave the pod Pending on a busy node and reduces how many other workloads
fit there; it does not add another UI replica. `/tmp` remains a disk-backed **4Gi emptyDir** under
node ephemeral storage. Budget node free disk plus logs/image layers and explicit ephemeral-storage
requests/limits as needed. Increasing the emptyDir limit requires available disk; a memory-backed
emptyDir would instead count against memory. Models, caches and output have separate PVC budgets.

## Reproducible GitOps inputs

Use a **versioned release deployment bundle**, vendor it and review its diff. Packaging substitutes
app/inference image tags and Terraform example pins. A remote Git URL or a raw source archive
skips that substitution and is not the same installation input. The
[vendoring procedure](./gitops.md) records a real downloadable bundle and distinguishes its
render/validate check from current-candidate or live-cluster evidence.

## Stop or remove this installation

[Stop, reset and uninstall](./lifecycle.md) separates retaining data for reinstall from deleting app state.
