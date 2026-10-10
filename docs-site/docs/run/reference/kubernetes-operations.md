---
title: Kubernetes operations
description: Manual manifests, storage, networking, GPU allocation, jobs and recovery for Kubernetes operators.
---

import DeploymentDiagram from '@site/src/components/DeploymentDiagram';

# Kubernetes operations

For a new installation, use [Kubernetes setup](../kubernetes.md). This page covers manual
manifests, changes to a running installation and troubleshooting.

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

## Another namespace

The manifests say `immich-memories` everywhere. To install under another name, decide before you
run anything below:

- Set `namespace:` in each kustomization root you apply. Applying raw YAML bypasses the namespace
  transformation, so the Quick start's `kubectl apply -f base/namespace.yaml` and the Secret you
  apply by file would create or use `immich-memories` anyway. Create your own namespace with
  `kubectl create namespace <name>` instead (skip `base/namespace.yaml`), and set `namespace:` in
  the Secret.
- Change every `-n immich-memories` in the commands to your namespace, and any cross-namespace URL.
- The Secret's *name* does not follow the namespace or a `namePrefix`. It is the literal
  `immich-memories-secrets` in the Deployment (`envFrom`), both CronJobs (`secretKeyRef`) and the
  Secret example, and the base does not contain that Secret (you apply it separately), so
  kustomize has nothing to rename. Create the Secret with exactly that name, in your namespace.

The setup builder has a Namespace field: it writes your value into `secret.yaml`,
`kustomization.yaml` and every `-n` in its commands.

## Quick start

Create the Immich key with the [ten read permissions](.././docker.md#the-api-key). Add the upload
set only when this account receives films; leave **All** unchecked. Put that scoped key in the
Secret below.

Download/extract the deployment bundle from your chosen
[release](https://github.com/sam-dumont/immich-memories/releases). Its image pins
match that release. If using a source checkout instead, check `base/kustomization.yaml`: committed
pins can trail releases. Image tags have no `v` prefix.

Not using the `immich-memories` namespace? Read [Another namespace](#another-namespace) above
first: this block and every `-n immich-memories` after it assume the default.

```bash
cd deploy/kubernetes
# Shipped default namespace. Installing into another one? Set `namespace:` in your own
# kustomization root and apply that with `kubectl apply -k`; never apply base files singly.
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

`rollout status` waits. The GPU tier's first start pulls a multi-GB CUDA image (about 5 minutes on a
test cluster) and the pod sits in `ContainerCreating` the whole time. That is the pull, not a stuck
pod: `kubectl describe pod -n immich-memories` shows `Pulling image`.

On the GPU and Full tiers the app is Ready well before the model services are. A `preflight` in
that gap prints three GPU warnings (`No verified inference GPU for requested gpu tier`, kernels on
the CPU) that clear on their own about two minutes later. Wait for both first, or re-run
`preflight` once they are Ready:

```bash
kubectl rollout status -n immich-memories deploy/immich-memories-inference
kubectl rollout status -n immich-memories deploy/immich-memories-captioner
```

The [setup builder](/setup) puts both after the app's own `rollout status` on those tiers, and it
pins the tier you picked, Basic included, with `IMMICH_MEMORIES_DEPLOYMENT_TIER`.

The temporary Secret file is private (mode 0600); remove it after applying.
The base uses an existing `immich-memories-secrets` Secret. GitOps users can skip the plaintext
copy and use [SOPS or External Secrets](../reference/kubernetes.md#bring-your-own-secret).

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

Open `http://localhost:8080`. Port 8080 taken on your machine? `kubectl port-forward -n immich-memories svc/immich-memories 8081:80` serves it at `http://localhost:8081`: the service port stays 80. Set home coordinates and timezone below, then make
[your first film](../../get-started/first-film.mdx).

:::caution Keep it private until login works
Authentication is disabled by default. Do not expose the Service or add an Ingress before
[enabling authentication](.././authentication.mdx). Keep one UI replica.
:::

### Rotating a key

Keys live in the Secret. Edit it (the generated `custom/secret.yaml`, or your own copy of
`base/secret.yaml.example`), apply, then restart the app, since pods do not pick up new
environment values on their own:

```bash
kubectl apply -k deploy/kubernetes/custom
kubectl rollout restart -n immich-memories deploy/immich-memories
```

On the GPU tier this took 36 seconds and restarted only the app pod. `apply` prints `configured`
for objects that did not change (the captioner and inference Deployments among them); they are not
restarted. Rotate the Immich API key
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
[confirm your family once](../../get-started/who-is-who.md).

## Getting the films

The web Render panel can upload to Immich. To default CLI/daily films to upload, set
`IMMICH_MEMORIES_UPLOAD__ENABLED=true` and optionally `IMMICH_MEMORIES_UPLOAD__ALBUM_NAME`.
The key needs [upload permissions](.././docker.md#the-api-key).

For local films, copy from the output PVC. Each film sits in its own run folder, so copy the
`.mp4` rather than the whole volume ([first film](../../get-started/first-film.mdx)):

```bash
kubectl get pods -n immich-memories
kubectl exec -n immich-memories deploy/immich-memories -c immich-memories -- find /app/output -name '*.mp4'
kubectl cp -n immich-memories -c immich-memories <pod>:/app/output/<run folder>/<name>.mp4 ./film.mp4
```

`kubectl cp` is fine for a short film. For anything over about 100 MB, neither it nor a plain
`exec ... cat > film.mp4` can be trusted: on a 128 MB film, 4 of 4 streamed copies stopped short
(130 to 133 MB of 134 MB, one with `connection reset by peer`) and `kubectl cp` gave 1 full copy
in 2. The size check caught every bad copy, so use it as the loop's exit condition. This copies
in chunks, resumes from the bytes it already has with `tail -c +N`, and stops only when the local
size matches the pod's:

```bash
NS=immich-memories
FILE="/app/output/<run folder>/<name>.mp4"
pod() { kubectl exec -n "$NS" deploy/immich-memories -c immich-memories -- "$@"; }

want=$(pod stat -c %s "$FILE")
: >> film.mp4
until [ "$(wc -c < film.mp4 | tr -d ' ')" -ge "$want" ]; do
  have=$(wc -c < film.mp4 | tr -d ' ')
  pod tail -c +$((have + 1)) "$FILE" >> film.mp4 || sleep 2
done
echo "got $(wc -c < film.mp4 | tr -d ' ') of $want bytes"
```

It works in bash and zsh, on macOS and Linux. A dropped connection costs one retry from where it
stopped, not the whole film. Play the file to the end before you delete anything.

Two other routes skip the problem. The film page in the web UI has a **Download film** link under
the player (port-forward, open the run, click it), and the browser can resume that. Or mount the
output PVC in a throwaway pod and copy from there, which also works when the app pod is down.

A CLI render dies with the `kubectl exec` that started it. For a month or a year, run it detached
inside the pod, for example `kubectl exec ... -- sh -c 'nohup immich-memories runs render RUN_ID > /tmp/render.log 2>&1 &'`,
and check `immich-memories runs list` for the result.

Confirmed uploads remove their local film; local-only and failed deliveries keep theirs.

## Authentication and Ingress

Add Basic-auth credentials to the Secret, or configure [OIDC](.././authentication.mdx#oidc--sso).
Then copy `base/ingress.yaml.example`, set its host/TLS settings and list it in your kustomization.
Use the [proxy trust/cookie checklist](.././authentication.mdx#behind-a-reverse-proxy-with-tls).

## How the pod is wired

<Diagram name="deploy-kubernetes" headline="The base runs the app. Overlays and components bolt on the rest." />
The app runs as UID/GID 1000 with `fsGroup: 1000`, dropped capabilities, RuntimeDefault seccomp
and a read-only root.

| Path | Storage |
|---|---|
| `/home/immich/.immich-memories` | Data/cache PVC: store, settings, session key, previews, clips and Laya files |
| `/home/immich/.cache` | The same data PVC, mounted again: writable persistent Torch/HF runtime caches |
| `/app/output` | Output PVC: local films |
| `/models` | Models PVC: encoder, WordNet, sensitive-content export and detector cache |
| `/tmp` | 4Gi emptyDir for container utilities; app media scratch uses the data/output PVCs |

The app requests 2Gi RAM and one CPU, with limits of 8Gi and four CPUs. The fetch init
container requests 512Mi/250m and is capped at 2Gi/two CPUs. Compose's app limit is 4 GB;
these are different budgets. The 30Gi data claim leaves room beyond the two default 10 GB
preview/video caches. Size larger claims for the largest period you prepare: 60,000 pictures
need about 21 GB of previews alone, before the store, runtime caches, video clips and scratch.
[Cache sizing and recovery](.././maintenance/storage-backups.md#caches) explains the headroom.

Existing claims do not automatically grow when you raise a cache budget. Your StorageClass must
allow expansion; increase the PVC request through your deployment configuration and verify the
mounted filesystem's free space afterwards. If expansion is unavailable, prepare smaller periods
and clear disposable caches while idle. Lower cache caps only reduce retained files: a run keeps
the previews it is actively using even when they exceed the cap.

Base settings come from environment variables and the Secret. Settings saves go to the store;
[environment variables win](.././config-file.md#where-a-setting-comes-from).

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

Check the [service/GPU allocation table](.././local-models.md#kubernetes-services) before choosing
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
Add an explicitly enabled [external reader](../../better/reader.md) for Full. The app image has no
owned `llama-server`. One `advanced.llm` configuration serves titles, selection, music mood,
special days and explicitly opted-in LLM captions. The commented Deployment recipe uses native
Ollama and `options.num_ctx: 32768`; the `/v1` route needs server-side context configuration. After changing tier/services, run `models fetch` in
the app again for required detectors/Laya, then `preflight`.
[Requirements](.././requirements.md#which-tier-you-get) explains the resolver.

## Render worker as a sidecar

`overlays/render-sidecar` puts a worker in the same pod, on an NVIDIA node.
It receives the Immich API key over pod loopback `http://127.0.0.1:8093`.
Copy its `render-worker-secret.yaml.example` to `render-worker-secret.yaml`, set both `token`
(`openssl rand -hex 32`) and `immich-url` to the app's configured Immich server, then apply the
overlay. The request carries selected partner API keys, names, home coordinates and network
settings too; run the worker where those credentials and facts may be read.

Keep app and worker image tags equal. The worker binds loopback, so its probes must use `exec`,
not kubelet HTTP/TCP probes to the pod IP. [Render worker](../../better/gpu-render.md) covers remote
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
check from the [worker guide](../../better/gpu-render.md) to check capabilities.

## The two model services

Inference and caption overlays can also run independently for another app deployment. Create the
namespace first if the base is not deployed. Reader/music servers are not provided by the base.
See [Inference](../../better/inference.md), [Captions](../../better/captions.md) and [Music](../../better/music.md)
for model/service configuration.

## Database

For PostgreSQL, fill in `overlays/postgres/database-secret.yaml` from its example and apply that
overlay instead of base. It connects to an existing PostgreSQL; it does not deploy one.
[PostgreSQL modes](.././reference/database.md) gives the database/role SQL.

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
`- cronjobs.yaml` to `base/kustomization.yaml` (uncomment the line already there), render, then
apply that root. They call `POST /api/trigger` on the running app and mount no application PVCs.
Set `IMMICH_MEMORIES_SERVER__TRIGGER_TOKEN` in the Secret (`openssl rand -hex 32`). The
[setup builder](/setup) does both for you when you tick **Scheduled films (CronJobs)**: the token
goes into the generated `secret.yaml` and its commands switch the CronJobs on before the apply.
Both schedules invoke the automatic decision, even the job named monthly: they do not force a
monthly film. The Service selects only `web-ui` pods, so a Ready curl Job is never used as an
HTTP backend.

**`concurrencyPolicy: Forbid` does not guard anything here.** The Job only sends the trigger and
exits in under a second whatever the outcome, so Kubernetes never sees two Jobs overlap. The guard
is the app's own run lease: while a run is active, a second `POST /api/trigger` is refused with
`HTTP 409` and `{"detail":"a run is already active","attempt_id":"..."}`. Twelve simultaneous
POSTs after a finished film gave 2 accepted (202) and 10 refused (409), and two CronJobs firing in
the same second both got 202, then both ended `skipped` for cooldown. The curl in these Jobs uses
`-f`, so a 409 makes it exit non-zero, and `restartPolicy: OnFailure` retries a failed pod. The
Job's own handling of a 409 has not been observed: only the HTTP answers were checked.

**Test a schedule now, and follow what it started.** Fire a Job from the CronJob without waiting
for its clock:

```bash
kubectl create job -n immich-memories --from=cronjob/immich-memories-auto trigger-test
kubectl logs -n immich-memories job/trigger-test
```

`Complete` only means the trigger was accepted: the Job's log is just
`{"status":"accepted","attempt_id":"...","status_url":"/api/trigger/..."}` and the Job is done in a
few seconds. The film is made by the running app, detached from that HTTP request, and a year can
take close to an hour on four CPU cores (55 minutes for a 538 s film on the first trigger of a fresh library). Follow it with the attempt id and the token.

The app image has no `curl`, so `kubectl exec` can't make this call. Run it from your machine
instead: this reads the attempt id from the Job's log, forwards a local port, asks, and stops the
forward.

```bash
TOKEN=$(kubectl get secret -n immich-memories immich-memories-secrets -o jsonpath='{.data.IMMICH_MEMORIES_SERVER__TRIGGER_TOKEN}' | base64 -d)
ATTEMPT=$(kubectl logs -n immich-memories job/trigger-test | sed -n 's/.*"attempt_id":"\([^"]*\)".*/\1/p')
kubectl port-forward -n immich-memories svc/immich-memories 8081:80 >/dev/null 2>&1 & sleep 3
curl -s -H "Host: localhost" -H "Authorization: Bearer $TOKEN" "http://localhost:8081/api/trigger/$ATTEMPT"; kill %1
```

The answer carries `state` (`running`, then `completed`, `failed` or `skipped`), `phase`, `reason`
and, once there is one, the `run`. `kubectl exec -n immich-memories deploy/immich-memories -- immich-memories runs list`
shows the same run from inside the pod, though it can say "No runs found" for the first seconds.
[The trigger contract](../../reference/automation-contract.md#kubernetes) has every field.

For a fixed recipe, prefer `kubectl exec ... -- immich-memories generate ...`.
The separate `base/job.yaml` contains only the one-off generate Job. It mounts the PVCs
directly; use it with the Deployment scaled to zero. Never include it just to enable schedules.
If using PostgreSQL, add its Secret to that Job too. Include `job.yaml` in Kustomize so its app
image follows the selected tag; a raw `apply -f` bypasses image transformations.

Or enable the app's [daily timer](../../make/automate.md) and skip CronJobs entirely.

## Backups

```bash
kubectl exec -n immich-memories deploy/immich-memories -- immich-memories store backup
kubectl cp immich-memories/<pod>:/home/immich/.immich-memories/backups ./backups
```

Keep the manifest/encryption key. [Restore](.././database.md#restore-in-a-container) needs the
Deployment stopped. Caches are disposable; the store is not.

## Probes

Liveness uses `/health/live`; readiness uses `/health/ready`, which returns 503 when Immich/config
is unavailable. Both accept the pod IP in the probe's `Host` header.

For a custom manifest, check both probe paths before upgrading. `/health` keeps the normal host
validation and can return 421 for a pod-IP request. When accepted, it returns 200 even if Immich
is unavailable, so it must not be used as a probe. Keep the correction in the manifests or
Terraform that own the deployment; a later apply can overwrite a live patch.
[Diagnostics](.././maintenance/health-logs-cache.md#health-endpoints) gives response/access details.

## Logs

```bash
kubectl logs -n immich-memories deploy/immich-memories -c immich-memories -f
```

For init failures, use `-c fetch-models`. [Diagnostics](.././maintenance/health-logs-cache.md#logging)
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
[Rollback](.././maintenance/upgrading.md#rollback) requires the old store backup when its schema changed.

## Check it from outside the pod

Use the quick-start `kubectl exec ... preflight` command after service changes. The
[distributed-services guide](.././reference/cluster-example.md) shows how to compose separate services.

## The models the first cut needs

Model requirements follow the selected tier. [Model files](.././maintenance/health-logs-cache.md#model-files)
lists the fetch options. Run fetch from the app's configuration after adding GPU/Full services.

## Distribute work across services

[Distributed services on Kubernetes](.././reference/cluster-example.md) explains GPU allocations,
service boundaries and the shipped composition example. Use it when you need separate placement;
start with the basic install first.

## Configuration ownership

For each field: runtime environment > operator `config.yaml` > saved Settings > deployment
service defaults > schema default. A command's flags can override its own run. In YAML, the
`advanced:` wrapper contains `auth`, `server`, `llm`, `editorial`, `inference` and other advanced
sections; runtime names in the table omit that wrapper. See the [complete field reference](../../reference/config-reference.md).

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
up new environment values. The [config source report](.././config-file.md#where-a-setting-comes-from)
shows what wins.

The same data PVC is mounted at both `.immich-memories` and `.cache` without `subPath`, so both
paths expose the same volume root. This provides writable persistent runtime caches under a
read-only root; it does not isolate credentials from model code. SQLite, saved credentials and
session keys live there. The model PVC holds weights and the output PVC holds films.
Back up the store **and** keys using [backup/restore](.././maintenance/storage-backups.md).

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
Use the [existing JSON logs with run IDs](.././maintenance/health-logs-cache.md), the health endpoints,
`runs show`, `report`, per-run timings and `llm-usage.json` for model-call usage.
The inference service's `/queue` reports that service's work, not app-wide metrics or readiness.
There's no Prometheus/OpenTelemetry export yet; use the structured logs and health endpoints
above instead.

## Resource requests, QoS and scratch

The shipped app pod is **Burstable**: app requests 1 CPU/2Gi versus limits 4 CPU/8Gi; fetch
init requests 250m/512Mi versus limits 2 CPU/2Gi. The [render memory model](.././reference/rendering.md#memory-budget)
uses the container limit: 4 GiB permits one source-preparation worker; 8 GiB can permit two.
More RAM may increase parallel work; it does **not** enlarge disk-backed `/tmp`.

For a Basic pod on Kubernetes 1.33, add this strategic-merge patch to your overlay's `patches`
list to reserve ceilings rather than rely on spare node capacity. Check what the node can give
first (`kubectl describe node <node> | grep -A8 Allocatable`, minus what is already requested
there). The example below asks for 4 CPU and 8Gi, so it needs a node with more than 4 allocatable
CPUs:

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
your submitted patch.

Reserving more CPU than a node has free leaves the pod **Pending**: 4 CPU never fits where the
node's allocatable is under 4. Because the Deployment strategy is `Recreate`, the old pod is
already gone by then, so the app stays down until you fix the numbers. Start from numbers the
node can actually hold, and expect downtime while a Recreate rollout reschedules.

Reserving 4 CPU/8Gi can leave the pod Pending on a busy node and reduces how many other workloads
fit there; it does not add another UI replica. `/tmp` remains a disk-backed **4Gi emptyDir** under
node ephemeral storage for container utilities. The app directs Python and subprocess scratch
to its configured cache on the data PVC. Video preparation saves and releases one frame batch
at a time. Keep free space on that PVC; enlarging `/tmp` does not enlarge the cache or output.
[Temporary working files](.././maintenance/storage-backups.md#temporary-working-files) lists the
worker locations too. Budget node free disk plus logs/image layers and explicit ephemeral-storage
requests/limits as needed. Increasing the emptyDir limit requires available disk; a memory-backed
emptyDir would instead count against memory. Models, caches and output have separate PVC budgets.

## Reproducible GitOps inputs

Use a **versioned release deployment bundle**, vendor it and review its diff. Packaging substitutes
app/inference image tags and Terraform example pins. A remote Git URL or a raw source archive
skips that substitution and is not the same installation input. The
[vendoring procedure](.././gitops.md) records a real downloadable bundle and distinguishes its
render/validate check from current-candidate or live-cluster evidence.

## Stop or remove this installation

[Stop, reset and uninstall](.././lifecycle.md) separates retaining data for reinstall from deleting app state.
