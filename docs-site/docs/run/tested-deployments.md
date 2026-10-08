---
title: Can I run this?
---

# Can I run this?

Start with **Basic, one prebuilt Docker container**. Budget two CPU cores, 4 GiB for the app
on top of Immich's own needs, and 25 GB of app data plus images and output. GPU and Full need
[additional services](./requirements.md#the-preparation-tier). Hardware encoding alone does not
turn on GPU; a text reader alone does not turn on Full.

## Status meanings

| Status | Meaning |
|---|---|
| **Verified first run** | A tester installed from scratch with public artifacts and docs, got a playable film, and the transcript is linked |
| **Partial** | A narrower check passed: a warm benchmark, a developer-run install, or preflight without a full film |
| **Documented, untested** | The steps exist and should work, but nobody has run them end to end yet |
| **Unsupported** | No supported route for this combination; the reason and the alternative are stated |

## The matrix

Keyed by **release and hardware**. When a newer release is tested on the same hardware, the row
updates in place rather than piling up history.

| Platform | Install method | Release verified | Hardware | Tier reached | Status | Notes |
|---|---|---|---|---|---|---|
| Linux x86-64 | [Basic Compose](./docker.md) | v1.0.0-rc.7 | Xeon E3-1240 v6, 4 vCPU, software H.264 | Basic | Verified first run | Docker in Docker on a Kubernetes node; album and month films, network capture: only Immich and GitHub during `models fetch` ([transcript](https://github.com/sam-dumont/immich-memories/issues/956#issuecomment-6053816158)) |
| Synology | [SSH + Compose](./platforms/synology.md#sshcompose-installation-from-published-files) | v1.0.0-rc.7 | DS423+ (Celeron J4125), software H.264 | Basic | Verified first run | Cold pull; web UI over the LAN with sign-in; 30 s album and 60 s month film ([transcript](https://github.com/sam-dumont/immich-memories/issues/956#issuecomment-6053816158)) |
| Synology | [Container Manager GUI](./platforms/synology.md) | n/a | any Synology, software encoding | Basic | Documented, untested | Project wizard not yet exercised |
| Unraid | [GUI template](./platforms/unraid.md) | n/a | any x86-64, software encoding | Basic | Documented, untested | [Report your results](https://github.com/sam-dumont/immich-memories/issues) |
| TrueNAS | [Custom app](./platforms/truenas.md) | n/a | any x86-64, software encoding | Basic | Documented, untested | [Report your results](https://github.com/sam-dumont/immich-memories/issues) |
| Linux ARM64 | [Compose](./docker.md) | n/a | ARM64, software encoding | Basic | Documented, untested | GPU overlays need CUDA and don't apply here |
| Apple Silicon | [Docker Desktop](./offline.md) | v0.103.0 | M-series, software H.264 | Basic | Partial | Isolated runtime, not a public-image pull |
| Apple Silicon | [Native uv/pip](./uv-pip.md) | v1.0.0-rc.7 | M5 Max and M2 Pro, Metal/VideoToolbox | Basic | Verified first run | PyPI install, album and month films; only Immich contacted. A scheduled run against a LAN Immich needs the [Local Network permission](./uv-pip.md) ([transcript](https://github.com/sam-dumont/immich-memories/issues/956#issuecomment-6053816158)) |
| Kubernetes (RKE2) | [Generated manifests, GPU](./kubernetes.md#generated-tier-setup) | v1.0.0-rc.7 | NVIDIA T1000 8 GB | GPU | Verified first run | Release bundle and setup builder, app pod with its own GPU (NVENC, GPU titles), scheduled film from the CronJob ([transcript](https://github.com/sam-dumont/immich-memories/issues/956#issuecomment-6053816158)) |
| Kubernetes (RKE2) | [Generated manifests, Basic with scheduled films](./kubernetes.md#batch-jobs) | v1.0.0-rc.5 | 4 CPUs, software H.264 | Basic | Verified first run | The CronJob's first scheduled attempt made a 9 min year film from 659 pictures in about an hour ([transcript](https://github.com/sam-dumont/immich-memories/issues/956#issuecomment-6039162730)) |
| Kubernetes | [Independently managed services](./kubernetes.md#set-the-preparation-tier) | v1.0.0-rc.5 | NVIDIA T1000 8 GB | GPU | Partial | In daily use: a scheduled film every night, uploaded to Immich; not reinstalled from scratch |
| NAS app | [Standalone Docker GPU worker](../better/gpu-render.md) | n/a | n/a | GPU | Documented, untested | Kubernetes worker route is verified; Docker worker is not |
| NAS app | [Kubernetes GPU worker](./kubernetes.md) | v0.103.0 | NVIDIA T1000 8 GB | GPU | Partial | Worker routing needed a fix before the film completed |
| Basic | [Prepared models, blocked internet](./offline.md) | v0.103.0 | Docker and Kubernetes | Basic | Partial | Isolated runtime and full decode passed; release-download path not separately checked |
| Basic | [Plus a local text model](./local-models.md) | n/a | n/a | Basic + text | Documented, untested | Model conformance checked separately; a full offline film with it is not |

## What each route needs

| Route | Infrastructure and budgets | Reader |
|---|---|---|
| Basic Compose or vendor GUI | Docker/Compose or a vendor manager, 2 cores, 4 GiB app, 25 GB app data plus image/output | None required by default; Immich access only |
| Generated Kubernetes GPU | Cluster with a GPU device plugin, storage class, two schedulable GPU allocations; 8 GiB/4 CPUs plus [service budgets](./local-models.md#kubernetes-services) | External reader for Full |
| Independent Kubernetes | Operator-supplied model/worker endpoints and their own RAM/VRAM/storage | External reader; operator controls GPU sharing and egress |
| Native Apple Silicon | Python, FFmpeg, app/model memory | App-owned `llama-server`, or an external server |
| NAS + GPU box | NAS app budget plus a separate worker/model host | Inference/caption traffic to that host; rendering only moves there if a render endpoint is configured |
| Offline Basic, or extra local models | Models prepared first, firewall covering every process that needs it | None by default; the local-model recipe adds its own text server |

## Immich version support

The client implements the **Immich v2 and v3 API contracts** and detects the major version from
`/api/server/version`. Leave `api_version: auto`; forcing `v2` or `v3` is a troubleshooting
override, not a way to make an unsupported server supported.

The first runs above used Immich 3.2; the test suite also covers 2.7. Newer 3.x releases speak
the same API contract and should work; run the check below before relying on one.

```bash
immich-memories config test
immich-memories preflight
```

In Docker, prefix these with `docker compose exec immich-memories`. `config test` reports the
server version and whether your key can read; it doesn't upload anything. Use the
[minimum read permissions](./docker.md#the-api-key) for a new key, and add upload/delete only
for the delivery features you've turned on.

## Reporting a result

If you've run a platform or method marked "Documented, untested" above, open an issue with your
release, hardware, and whether the film completed. Detailed provenance (exact image digests,
timings, intermediate failures) goes in that issue, not on this page: the table only needs to
say what's verified and on what.
