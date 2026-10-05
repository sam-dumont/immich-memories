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
| Linux x86-64 | [Basic Compose](./docker.md) | n/a | any x86-64, software encoding | Basic | Documented, untested | Pull, run, first film not yet recorded |
| Synology | [SSH + Compose](./platforms/synology.md#sshcompose-installation-from-published-files) | v0.103.0 | DS423+ class, software H.264 | Basic | Verified first run | Clean volume, fresh models, shipping Compose file |
| Synology | [Container Manager GUI](./platforms/synology.md) | n/a | any Synology, software encoding | Basic | Documented, untested | Project wizard not yet exercised |
| Unraid | [GUI template](./platforms/unraid.md) | n/a | any x86-64, software encoding | Basic | Documented, untested | [Report your results](https://github.com/sam-dumont/immich-memories/issues) |
| TrueNAS | [Custom app](./platforms/truenas.md) | n/a | any x86-64, software encoding | Basic | Documented, untested | [Report your results](https://github.com/sam-dumont/immich-memories/issues) |
| Linux ARM64 | [Compose](./docker.md) | n/a | ARM64, software encoding | Basic | Documented, untested | GPU overlays need CUDA and don't apply here |
| Apple Silicon | [Docker Desktop](./offline.md) | v0.103.0 | M-series, software H.264 | Basic | Partial | Isolated runtime, not a public-image pull |
| Apple Silicon | [Native uv/pip](./uv-pip.md) | v0.103.0 | M-series, Metal/VideoToolbox | Basic | Partial | Install, preflight, an album film and a month film passed; GPU services not exercised |
| Kubernetes (RKE2) | [Generated manifests, GPU](./kubernetes.md#generated-tier-setup) | v0.103.0 | NVIDIA T1000 8 GB | GPU | Partial | GPU sharing and store placement needed operator fixes |
| Kubernetes | [Independently managed services](./kubernetes.md#set-the-preparation-tier) | v0.103.0 | NVIDIA T1000 8 GB | GPU | Partial | Services already running; setup corrections disclosed |
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

Immich 2.7 through the current 3.x releases are covered by that API contract and by the rows
above. A patch version outside those families should still work if its API major matches; run
the check below before relying on it.

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
