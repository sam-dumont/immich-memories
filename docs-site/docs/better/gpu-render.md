---
title: Render on a GPU box
---

# Render on a GPU box

On a plain NAS the render is the long part of every run: what the editor read is banked, the
encode is not, so a second cut of the same month still encodes the whole film on the NAS's cores.
The render worker takes that one stage to a machine with an NVIDIA card. Selection stays on the
NAS, and so does the upload back to Immich. Music generation stays with its configured backend;
Demucs stem separation can share the inference worker.

The [combined CUDA worker](../run/reference-setup.md#one-gpu-service) puts this render service,
picture inference, captions and Demucs in one container on port 8092. Its render URL ends in
`/render`; the standalone setup below keeps port 8093.

The render API requires a bearer token, including its health endpoint. The combined worker's
inference, caption and stem routes are unauthenticated. Bind the service to loopback when the app
runs on the same machine; otherwise use a private network and firewall rules that allow only
the app. Keep these ports off the internet.

```mermaid
flowchart TD
    app["App: selection and timing"] -->|"Cut and Immich key"| worker["Trusted NVIDIA worker"]
    immich["Immich originals"] --> worker
    worker -->|"Rendered film"| finish["App: verify, music, upload"]
```

## What it holds

Every job carries the app's own Immich API key, the same one with the same permissions, so the
worker can fetch the selected originals itself. It keeps the key in memory for the job and redacts
it from its messages, but anyone who controls the worker process can read it. Run the worker
somewhere you trust as much as the NAS. If the app never uploads back, give it a read-and-download
key, and that is then all the worker holds.

## Set it up

Use the same app version on both sides: the app refuses a worker on another version before it
sends any footage. On the GPU box, with the NVIDIA container toolkit installed, copy
[`services/render-worker/compose.yaml`](https://github.com/sam-dumont/immich-memories/blob/main/services/render-worker/compose.yaml)
into an empty directory with this `.env`:

```bash
IMMICH_MEMORIES_IMAGE=ghcr.io/sam-dumont/immich-memories:YOUR_APP_TAG
IMMICH_URL=https://photos.example.com
RENDER_WORKER_TOKEN=replace-with-openssl-rand-hex-32
RENDER_BIND_ADDRESS=192.168.1.50    # the worker's LAN address; 127.0.0.1 behind a reverse proxy
```

The worker refuses to start with a token under 32 characters or one with a placeholder word like
`change-me`; `openssl rand -hex 32` gives one that passes. `docker compose up -d` starts it on port 8093. For Kubernetes the same folder has
`kubernetes.yaml`: it wants a Secret with `token` and `immich-url`, one NVIDIA device and the
`nvidia` runtime class. Every worker setting is in the
[worker's README](https://github.com/sam-dumont/immich-memories/tree/main/services/render-worker).

Then on the NAS:

```yaml
render:
  worker_base_url: http://192.168.1.50:8093
  worker_token: ${RENDER_WORKER_TOKEN}
  allow_insecure_http: true
  fallback_to_local: false
```

The request carries your Immich key. The example explicitly trusts this private LAN with
`allow_insecure_http: true`. For HTTPS, configure a reverse proxy, use its URL and omit that opt-in.

On Kubernetes, `deploy/kubernetes/overlays/render-sidecar` runs the worker as a second container
in the app's own pod instead of its own Deployment: the two share a network namespace, so the app
reaches it at `http://127.0.0.1:8093`, loopback, with neither HTTPS nor
`render.allow_insecure_http` needed. See
[the Kubernetes page](../run/reference/kubernetes-operations.md#render-worker-as-a-sidecar).

## Give long jobs both deadlines

The app's `render.timeout_seconds` and the worker's
`IMMICH_MEMORIES_RENDER_WORKER_JOB_TIMEOUT_SECONDS` both default to 3,600 seconds. They are separate
budgets. The app waits for the queue, rendering and result download; the worker bounds its own job.
Increasing only the app timeout still leaves the worker with a one-hour deadline.

For a long film, this example gives the worker six hours and the app a little more time:

```yaml
render:
  timeout_seconds: 21660
```

Set `IMMICH_MEMORIES_RENDER_WORKER_JOB_TIMEOUT_SECONDS=21600` on the worker as well. Choose deadlines
for your queue and film size; this example adds 60 seconds for the handoff after the worker budget.
An app timeout does not cancel an active worker job.

Active rendering keeps ownership of its scratch workspace after a deadline. A stuck native
renderer can still require a worker restart. Increasing the deadline does not stop that job.

The worker receives the app’s map-tile and geocoding switches with the cut. Enable them in the
app’s [network settings](../run/privacy.md) when the film needs maps or place names.

The geocoding server is the worker's own choice, never the job's. The worker ignores the app's
`network.geocoding_url` and geocodes only through
`IMMICH_MEMORIES_RENDER_WORKER_GEOCODING_URL`, a self-hosted Nominatim such as
`http://nominatim.lan:8080`. Unset, the default, the worker does not geocode at all, even when
the app has `network.geocoding: true`; the film keeps the place names Immich gave.

## Check it

In Docker, prefix `immich-memories` commands with `docker compose exec immich-memories`
from the app's installation folder.

```bash
immich-memories preflight -v
curl -H "Authorization: Bearer ${RENDER_WORKER_TOKEN}" http://192.168.1.50:8093/health
```

It reports the worker's reachability, version, CUDA titles and encoders. The worker's own
`/health` says `accelerated: true` only when the CUDA title kernels and NVENC both opened; false on
a box with a card usually means `NVIDIA_DRIVER_CAPABILITIES` lacks `video`
([NVIDIA prerequisites](../run/hardware.md#nvidia)).

## What to expect

- A worker failure fails the run. `fallback_to_local: true` renders the same cut on the NAS instead
  and says so.
- A worker that can't open NVENC still renders, in software, and reports it on `/health` and in the
  job record. A dropped clip is a failed job, never a different film.
- Worker output is H.264 or H.265 MP4. MOV and ProRes require `fallback_to_local: true`
  to render on the app host; with the example's `false`, those requests fail.
- When the film the NAS downloads matches the worker's digest, the NAS keeps the worker's decode
  check instead of decoding the film again, unless music was mixed in.

Use [Measure your setup](./measured.md) to compare a local render and a worker using the same cut.
