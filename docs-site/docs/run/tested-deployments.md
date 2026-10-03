---
title: Can I run this?
---

# Can I run this?

Start with **Basic, one prebuilt Docker app container**. Budget two CPU cores, 4 GiB for the
app in addition to Immich/host needs, and 25 GB of app data plus images and output. GPU and
Full require [additional services](./requirements.md#the-preparation-tier). Hardware encoding
alone does not enable GPU selection; a text reader alone does not provide Full.

## Candidate status

**No row below is a verified first run of the forthcoming RC.** The available evidence uses
older candidate source trees, locally built artifacts or already prepared services. Matching public
candidate downloads and the source-naive runs remain required by
[#1922](https://github.com/sam-dumont/immich-memories/issues/1922) and
[#956](https://github.com/sam-dumont/immich-memories/issues/956).
This table describes the documentation baseline at `8764721b37ac090ae0ca58be434b3692de4596d0`;
it does not give that commit an installation pass. The dated [measurement record](../better/measured.md)
retains original revisions, dates, timings and qualifications.

| Status | Meaning |
|---|---|
| **Verified first run** | A source-naive tester used the exact row's public prebuilt artifacts and docs from fresh app state, completed preparation/preflight and a playable film, and linked the transcript |
| **Partial** | A narrower check passed; missing first-run steps are named. Warm benchmarks, developer-assisted runs and preflight alone belong here |
| **Documented, untested** | A public recipe exists, but no matching run has been demonstrated |
| **Unsupported** | This combination has no supported route; the reason and alternative are stated |

## Installation and evidence

No current-candidate Immich patch version is established for these rows. The
[compatibility table](./compatibility.md) separates API support, CI targets and verified versions.
“Not recorded” means the old report cannot supply the missing field, not that it was unnecessary.
A dash is deliberately not used as a substitute for evidence.

| Platform and method | App / docs identity in existing evidence | Capability and encoding | Status, evidence and untested steps | Cold setup / first playable film |
|---|---|---|---|---|
| Linux x86-64, [Basic Compose](./docker.md) | Current candidate: not published; matching run: not tested | Basic; CPU encoding unless configured otherwise | **Documented, untested**: fresh anonymous pull through film pending | Not measured / not measured |
| Synology x86-64, [SSH/Compose](./platforms/synology.md#sshcompose-installation-from-published-files) | App `75077f27`, image `49cc60a978ce`; builder `61fa1154` | Basic; software H.264 | **Partial**: [DSM 7.3 film](../better/measured.md#generated-cold-installs); local candidate, custom UI transport; public assets and authenticated proxy untested; Container Manager version not recorded | Total not measured / generation 16m 38.8s, excludes acquisition |
| Synology, [Container Manager GUI](./platforms/synology.md) | Candidate/version: not tested | Basic; encoding not tested | **Documented, untested**: Project wizard, public artifacts and LAN login pending; SSH evidence does not cover GUI | Not measured / not measured |
| Unraid x86-64, [GUI/template](./platforms/unraid.md) | Candidate/version: not tested | Basic; encoding not tested | **Documented, untested**: vendor route and film pending | Not measured / not measured |
| TrueNAS, [custom app](./platforms/truenas.md) | Candidate/version: not tested | Basic; encoding not tested | **Documented, untested**: vendor route and film pending | Not measured / not measured |
| Linux ARM64, [Compose](./docker.md) | Candidate/version: not tested | Basic; software encoding | **Documented, untested**: Linux ARM64 first run pending; app architecture support does not cover CUDA services | Not measured / not measured |
| Apple Silicon, [Docker Desktop Basic](./offline.md) | App `5466706b`; Compose `00cd41df` | Basic; software H.264 | **Partial**: [isolated runtime](./offline.md); local candidate, not a public-download first run | Total not measured / 19-second film, elapsed not recorded |
| RKE2 x86-64 GPU, [generated Kubernetes](./kubernetes.md#generated-tier-setup) | App `75077f27`, inference `d079a0da1633`; generated `5f3de520` | GPU; software H.264 | **Partial**: [RKE2 1.33.4 film](../better/measured.md#generated-gpu-first-film); local images, operator-managed GPU sharing and corrected SQLite placement; public two-allocation route untested | Total not measured / generation 11m 22.8s, excludes init and transfers |
| Kubernetes, [independently managed services](./kubernetes.md#set-the-preparation-tier) | Current candidate: not tested; historical preflight revisions not recorded | Depends on inference/captions/reader; encoding separate | **Partial**: [older checks](../better/measured.md#tested-setups); current service set, first film and complete setup pending | Not measured / not measured |
| Apple Silicon, [native prebuilt package](./uv-pip.md) | Local wheel `0.0.0rc180503`, source `d5b4472b`; matching published package absent | GPU, MLX/Metal; VideoToolbox H.264 | **Partial**: [M5 Max run](../better/measured.md#generated-native-mac); reused weights/caption server; public-package install and cold service startup pending | Not measured / generation 35.38s, warm models |
| NAS app + [standalone Docker GPU worker](../better/gpu-render.md) | Candidate/version: not tested | Selection depends on inference; worker encoding separate | **Documented, untested**: the published Kubernetes worker result does not prove Docker-worker installation | Not measured / not measured |
| NAS app + [Kubernetes GPU worker](../better/measured.md#generated-nas-remote-gpu) | App `75077f27`, image `49cc60a978ce`, worker `d079a0da1633` | GPU facts/captions; NAS software encoding | **Partial**: film passed; cold preflight initially failed, retry used a test overlay; public unmodified candidate pending | Total not measured / generation 6m 53.09s |
| Basic, [prepared models and blocked internet](./offline.md) | Docker `5466706b` / recipe `00cd41df`; Kubernetes `75077f27` | Basic; software H.264 | **Partial**: isolated runtime and complete decode passed on the named topologies; release-download path and DNS-Service policy variant unverified | Not measured / 19-second outputs, elapsed not recorded |
| Basic plus [local text model](./local-models.md) | App candidate: not tested; model conformance evidence linked in recipe | Basic selection, text titles/mood; not Full or vision captions | **Documented, untested**: complete recipe's offline film and provider-stop test pending; conformance is a narrower result | Not measured / not measured |

## What you must provide

All rows need a reachable existing Immich and a [minimum read key](./docker.md#the-api-key).
API targets are Immich v2/v3; exact candidate-tested patch versions remain unverified here.
Installation needs registry/package/model download access. Basic runtime contacts Immich;
local-only runtime requires the separately tested firewall/policy recipe, not just local URLs.

| Route | Supplied infrastructure and budgets | Reader ownership and runtime destinations |
|---|---|---|
| Basic Compose and vendor GUI | Docker/Compose or named vendor manager, 2 cores, app 4 GiB, app data 25 GB plus image/output | No reader required; containers need an external server if enabled; Immich only with default features |
| Generated Kubernetes GPU | Cluster/CNI, storage class, device plugin, two schedulable GPU allocations; app limit 8 GiB/4 CPUs plus [service budgets](./local-models.md#kubernetes-services) | External reader for Full; Immich plus inference/caption services, reader if enabled |
| Independent Kubernetes | Operator supplies compatible model/worker endpoints and their RAM/VRAM/storage; app and init budgets in [Kubernetes](./kubernetes.md) | External readers; operator controls GPU sharing and every service's outbound policy |
| Native Apple Silicon | Python, FFmpeg, app/model memory; historical M5 had 128 GB, not a measured minimum; existing caption server disclosed | App-owned llama-server possible on native macOS/Linux; external servers retain their own memory and egress |
| NAS + GPU box | NAS app budget above plus a separate matching worker/model host; historical T1000 had 8 GB VRAM | Inference/caption traffic to that host; rendering moves only when a render endpoint is configured |
| Offline Basic / extra local models | Models prepared first, firewall/CNI covering every participating process, permitted Immich/local service endpoints | Default Basic has no model endpoint; the named extra-model recipe adds its exact text server |

The historical NAS had **17,836 MiB host RAM** and a **4 GiB app limit**. It does not validate a
stock 4 GiB NAS running Immich and this app together. The historical single T1000 sharing setup
does not prove that two unshared GPU reservations fit on one card.

## Adding a verified result

Record tester/date, public entry URL, docs commit, source and image/package digest, platform/tool
versions, Immich patch version, CPU/host RAM/app limit/GPU, supplied services and cache state.
Attach redacted steps from empty directory through preparation, preflight and complete playback
or decode. Record 20–50 trial inputs, requested/actual duration, output location, upload state,
phase timings and total first-film time; then record the full-month run separately.
Keep failures and interventions visible. Re-run the affected path after the public fix lands.
Update this table after checking actual tagged artifacts; never infer a pass from another topology.
