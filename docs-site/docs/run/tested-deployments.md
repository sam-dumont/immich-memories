---
title: Can I run this?
description: Tested installs on Linux, Synology, Kubernetes and Apple Silicon, with release, hardware and artifact status.
---

# Can I run this?

Start with **Basic, one prebuilt Docker container**. Budget two CPU cores, 4 GiB for the app
on top of Immich's own needs, and 25 GB of app data plus images and output. GPU and Full need
[additional services](./requirements.md#the-preparation-tier). Hardware encoding alone does not
turn on GPU; a text reader alone does not turn on Full.

## Status meanings

| Status | Meaning |
|---|---|
| **Verified candidate** | An unpublished candidate made playable films; the transcript records supplied artifacts, fresh installation or warm upgrade, and remaining checks |
| **Verified upgrade** | An existing installation was upgraded with public release artifacts and made a playable film; setup corrections are disclosed |
| **Verified first run** | A tester installed from scratch with public artifacts and docs, got a playable film, and the transcript is linked |
| **Partial** | A narrower check passed: a warm benchmark, a developer-run install, or preflight without a full film |
| **Documented, untested** | The steps exist and should work, but nobody has run them end to end yet |
| **Unsupported** | No supported route for this combination; the reason and the alternative are stated |

## The matrix

Keyed by **release and hardware**. When a newer release is tested on the same hardware, the row
updates in place rather than piling up history.

| Platform | Install method | Release verified | Hardware | Tier reached | Status | Notes |
|---|---|---|---|---|---|---|
| Linux x86-64 | [Basic Compose](./docker.md) | v1.0.0-rc.8 candidate | Intel Xeon E3-1240 v6, Docker-in-Docker, 4 GiB app limit | Basic | Verified candidate | Fresh app volume, supplied image archive; album and month films, software H.264; recovered from a 15-second connection outage; [transcript][candidate-runs] |
| Synology | [SSH + Compose](reference/synology-operations.md#sshcompose-installation-from-published-files) | v1.0.0-rc.8 candidate | DS423+, Intel J4125, 4 GiB app limit, software H.264 | Basic | Verified candidate | Fresh app volume, supplied image archive; authenticated UI album and CLI month films; restart and download checks; [transcript][candidate-runs] |
| Synology | [Container Manager GUI](./platforms/synology.md) | n/a | any Synology, software encoding | Basic | Documented, untested | Project wizard not yet exercised |
| Unraid | [GUI template](./platforms/unraid.md) | n/a | any x86-64, software encoding | Basic | Documented, untested | [Report your results](https://github.com/sam-dumont/immich-memories/issues) |
| TrueNAS | [Custom app](./platforms/truenas.md) | n/a | any x86-64, software encoding | Basic | Documented, untested | [Report your results](https://github.com/sam-dumont/immich-memories/issues) |
| Linux ARM64 | [Compose](./docker.md) | n/a | ARM64, software encoding | Basic | Documented, untested | GPU overlays need CUDA and don't apply here |
| Apple Silicon | [Docker Desktop](./offline.md) | v0.103.0 | M-series, software H.264 | Basic | Partial | Isolated runtime, not a public-image pull |
| Apple Silicon | [Native uv/pip](./uv-pip.md) | v1.0.0-rc.8 candidate | M5 Max, 128 GB; M2 Pro, 16 GB; VideoToolbox | Basic | Verified candidate | Supplied wheel, warm upgrades of isolated installs; album and month films on both Macs; [transcript][candidate-runs] |
| Kubernetes (RKE2) | [Generated manifests, GPU](./kubernetes.md#generated-tier-setup) | v1.0.0-rc.8 candidate | NVIDIA T1000 8 GB, shared GPU | GPU | Verified candidate | Fresh namespace, app and inference images pinned by digest; GPU inference, NVENC, CUDA titles; album and month films; [transcript][candidate-runs] |
| Kubernetes | [Independently managed services](reference/kubernetes-operations.md#set-the-preparation-tier) | v1.0.0-rc.8 | NVIDIA T1000 8 GB | Full | Verified upgrade | Published app and CUDA images pinned by digest; automatic film, upload and public delivery link checked. Custom probes needed the [dedicated health endpoints](./maintenance/upgrading.md) |
| NAS app | [Standalone Docker GPU worker](../better/gpu-render.md) | n/a | n/a | GPU | Documented, untested | Kubernetes worker route is verified; Docker worker is not |
| NAS app | [Kubernetes GPU worker](./kubernetes.md) | v0.103.0 | NVIDIA T1000 8 GB | GPU | Partial | Worker routing needed a fix before the film completed |
| Basic | [Prepared models, blocked internet](./offline.md) | v0.103.0 | Docker and Kubernetes | Basic | Partial | Isolated runtime and full decode passed; release-download path not separately checked |
| Basic | [Plus a local text model](./local-models.md) | n/a | n/a | Basic + text | Documented, untested | Model conformance checked separately; a full offline film with it is not |

[candidate-runs]: https://github.com/sam-dumont/immich-memories/issues/956

[first-runs]: https://github.com/sam-dumont/immich-memories/issues/956#issuecomment-6053816158

The candidate rows cover unpublished artifacts built for acceptance. They do not claim a public
release download or a cold install where a warm upgrade was used. The [published-artifact first
runs][first-runs] were on v1.0.0-rc.7.

A verified first run covers installation and a playable film through that route. Separate features,
such as the native macOS scheduler, have their own checks in the linked transcript. Older partial
rows below a verified route describe different setups, not a lower status for the tested route.

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

The real-server CI gate runs Immich **2.7.5, 3.2.2 and 3.3.0**. Other versions may work when
their API major matches; run the checks below before relying on them.
[Native person sharing](./multi-account.mdx#native-person-identities) has its own version checks.

```bash
immich-memories config test
immich-memories preflight
```

In Docker, prefix these with `docker compose exec -T immich-memories`. `config test` reports the
server version and whether your key can read; it doesn't upload anything. Use the
[minimum read permissions](./docker.md#the-api-key) for a new key, and add upload/delete only
for the delivery features you've turned on.

## Reporting a result

If you've run a platform or method marked "Documented, untested" above, open an issue with your
release, hardware, and whether the film completed. Detailed provenance (exact image digests,
timings, intermediate failures) goes in that issue, not on this page: the table only needs to
say what's verified and on what.
