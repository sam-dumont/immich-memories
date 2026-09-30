---
title: On a NAS
---

# On a NAS

Use the [Docker Compose install](./docker.md). These are the differences on Synology, QNAP,
TrueNAS SCALE and Unraid. Start with one month: a NAS can make the whole film, but a year's
first preparation is a bigger job.

## Install

Import `docker-compose.yml` as a project in your NAS's container manager. Put `.env` and an
`output` folder beside it. Fill in the Immich URL/key, home coordinates and timezone as in
[Docker step 2](./docker.md#2-connect-immich).

After starting the project, SSH into that folder:

```bash
sudo docker compose exec immich-memories immich-memories models fetch
sudo docker compose exec immich-memories immich-memories preflight
```

Then [reach the UI](#reaching-the-ui) and make [your first film](../get-started/first-film.mdx).
The default NAS tier needs no caption server or text model.

### The output folder

The image runs as UID/GID 1000. NAS users often have a different UID, so preflight can report
`Output directory is not writable`. Fix the folder over SSH:

```bash
sudo chown -R 1000:1000 output
```

Or run the service as your NAS user (`id` prints its UID/GID): set `user: "<uid>:<gid>"` in the
Compose service and chown the config volume to match. If you remove the output bind mount,
turn on [upload-back](./docker.md#films-into-immich) so films reach Immich.

### Reaching the UI

The default port is local to the NAS. From your desktop:

```bash
ssh -L 8080:localhost:8080 you@your-nas
```

Open `http://localhost:8080` on the desktop. For LAN access, enable authentication and change
the port mapping: [Docker access recipe](./docker.md#reaching-the-ui-from-another-machine).
If another NAS app uses 8080, change the host port (left side) and tunnel to that port.

### Do not use `cpus:` on a Synology

DSM kernels without the CFS bandwidth controller reject a CPU quota with
`NanoCPUs can not be set`. The shipped Compose file sets none. To leave a core for Immich,
pin this app to three cores on a four-core NAS:

```yaml
    cpuset: "0-2"
```

## What to expect

NAS films are capped at 1080p. The default 4 GB memory limit suits that output.
The first film reads the pictures in its period and saves the results; later films reuse matching
results. Rendering still happens every time.

The CPU classifiers provide less detector coverage than GPU/Full. Those tiers add captions,
document/sensitive-content detectors and the Laya pre-screen. See
[what the upgrades add](../get-started/what-a-gpu-or-a-model-adds.md).

Preparation timings are on [Measured](../better/measured.md#nas-preparation); they exclude
downloads, music and rendering. A long film also gets a full playback check after rendering,
which can take time. The log reports progress once a minute.

## Encoding

An Intel NAS can use Quick Sync for H.264. Uncomment the device block in Compose, and use the
numeric group that owns the render node:

```bash
stat -c '%g' /dev/dri/renderD128
```

```yaml
    devices:
      - /dev/dri:/dev/dri
    group_add:
      - "937" # example DSM GID; use the number from stat
```

Verify with [Hardware encoding](./hardware.md#verify-it). Passing the device without its group
leaves it visible but unusable.

J4125-class NAS hardware cannot encode HEVC. With the default `prefer_hardware` policy, the app
can choose H.264 instead. A strict H.265 or explicit HDR request can require software encoding.
ARM64 Docker uses software encoding. Non-AVX Celerons use the simpler title renderer.

## Memory and disk

Keep the persistent store. Size the preview cache for the pictures your films can reach:
roughly 0.35 MB per picture. The default preview/video budgets total 20 GB.
[Storage and caches](./maintenance/health-logs-cache.md#caches) covers caps and cleanup.
Uploaded films are removed locally after confirmed delivery; local-only films keep growing.

## Every night

The running UI can make one memory a day. Enable the timer in Compose and set `TZ`:
[Docker automation](./docker.md#daily-automation). [Automate it](../make/automate.md) explains
what it picks and how to upload the result.

## Long films

Stay at 1080p on NAS. For rendering on a stronger machine, use a
[render worker](../better/gpu-render.md); that changes rendering, not the selection tier.

## What a NAS can't do

GPU selection and local generated music need their respective GPU services. A reader alone still
helps with titles and music mood. Use the [add-on guide](../get-started/what-a-gpu-or-a-model-adds.md)
to choose the next useful piece.

## Everything else

The Docker instructions cover [API-key permissions](./docker.md#the-api-key),
[uploads](./docker.md#films-into-immich), [backups](./database.md#managing-the-store) and
[upgrades](./maintenance/upgrading.md#docker). Prefix container commands with `sudo` if your NAS
requires it.
